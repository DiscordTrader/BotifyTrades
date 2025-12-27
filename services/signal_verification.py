"""
Signal Verification Service
Professional-grade signal verification against real-time market data
Detects paper trading, slippage issues, and impossible fills

Data Sources (priority order):
1. Webull API - Real-time bid/ask data (when connected)
2. Tastytrade API - Real-time bid/ask data (when connected)  
3. yfinance - Delayed 15-30 min fallback
"""

import yfinance as yf
import sqlite3
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import numpy as np

DATABASE_PATH = os.path.join(os.path.dirname(__file__), '..', 'bot_data.db')

_webull_client = None
_tastytrade_session = None

def set_broker_clients(webull_client=None, tastytrade_session=None):
    """Set broker clients for real-time data access"""
    global _webull_client, _tastytrade_session
    _webull_client = webull_client
    _tastytrade_session = tastytrade_session
    sources = []
    if webull_client:
        sources.append('Webull')
    if tastytrade_session:
        sources.append('Tastytrade')
    if sources:
        print(f"[VERIFY] Real-time data sources enabled: {', '.join(sources)}")
    else:
        print("[VERIFY] Using yfinance (delayed data) - no broker connected")


class SignalVerificationService:
    """Verify trading signals against real-time market data"""
    
    def __init__(self):
        self.cache = {}
        self.cache_duration = 60
        self.data_source = 'unknown'
    
    def get_db(self):
        """Get database connection"""
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _get_webull_option_quote(self, ticker: str, strike: float, expiry: str, 
                                  direction: str) -> Optional[Dict]:
        """Get real-time option quote from Webull"""
        global _webull_client
        if not _webull_client:
            return None
        
        try:
            try:
                exp_date = datetime.strptime(expiry, "%Y-%m-%d")
            except ValueError:
                exp_date = datetime.strptime(expiry, "%m/%d/%Y")
            
            iso_exp = exp_date.strftime("%Y-%m-%d")
            opt_type = 'call' if direction.lower() == 'call' else 'put'
            
            options = _webull_client.get_options(stock=ticker, direction=opt_type, expireDate=iso_exp)
            
            if not options:
                return None
            
            best_match = None
            min_diff = float('inf')
            
            for opt in options:
                opt_strike = float(opt.get('strikePrice', 0))
                diff = abs(opt_strike - strike)
                if diff < min_diff:
                    min_diff = diff
                    best_match = opt
            
            if not best_match or min_diff > 1.0:
                return None
            
            option_id = best_match.get('tickerId')
            if not option_id:
                return None
            
            quote = _webull_client.get_option_quote(stock=ticker, optionId=str(option_id))
            
            if not quote:
                return None
            
            bid = 0.0
            ask = 0.0
            last = 0.0
            volume = 0
            
            if 'data' in quote and isinstance(quote.get('data'), list):
                for opt in quote.get('data', []):
                    if opt.get('tickerId') == option_id:
                        askList = opt.get('askList', [])
                        bidList = opt.get('bidList', [])
                        
                        if askList and len(askList) > 0:
                            ask = float(askList[0].get('price', 0))
                        if bidList and len(bidList) > 0:
                            bid = float(bidList[0].get('price', 0))
                        
                        last = float(opt.get('close', 0) or opt.get('latestPrice', 0) or 0)
                        volume = int(opt.get('volume', 0) or 0)
                        break
            else:
                ask = float(quote.get('askPrice', 0) or 0)
                bid = float(quote.get('bidPrice', 0) or 0)
                last = float(quote.get('lastPrice', 0) or quote.get('close', 0) or 0)
                volume = int(quote.get('volume', 0) or 0)
            
            if bid > 0 or ask > 0 or last > 0:
                self.data_source = 'webull_realtime'
                return {
                    'bid': bid,
                    'ask': ask,
                    'last': last,
                    'volume': volume,
                    'open_interest': int(best_match.get('openInterest', 0) or 0),
                    'implied_volatility': float(best_match.get('impVol', 0) or 0),
                    'strike': float(best_match.get('strikePrice', strike)),
                    'timestamp': datetime.now().isoformat(),
                    'source': 'webull_realtime'
                }
            
            return None
            
        except Exception as e:
            print(f"[VERIFY] Webull quote error: {e}")
            return None
    
    def _get_tastytrade_option_quote(self, ticker: str, strike: float, expiry: str,
                                      direction: str) -> Optional[Dict]:
        """Get real-time option quote from Tastytrade"""
        global _tastytrade_session
        if not _tastytrade_session:
            return None
        
        try:
            from tastytrade.instruments import get_option_chain
            from tastytrade.dxfeed import DXLinkStreamer
            
            try:
                exp_date = datetime.strptime(expiry, "%Y-%m-%d")
            except ValueError:
                exp_date = datetime.strptime(expiry, "%m/%d/%Y")
            
            chain = get_option_chain(_tastytrade_session, ticker)
            
            if not chain:
                return None
            
            exp_str = exp_date.strftime("%Y-%m-%d")
            
            if exp_str not in chain:
                return None
            
            options = chain[exp_str]
            opt_type = 'C' if direction.lower() == 'call' else 'P'
            
            best_match = None
            min_diff = float('inf')
            
            for opt in options:
                if opt.option_type == opt_type:
                    diff = abs(float(opt.strike_price) - strike)
                    if diff < min_diff:
                        min_diff = diff
                        best_match = opt
            
            if not best_match or min_diff > 1.0:
                return None
            
            self.data_source = 'tastytrade_realtime'
            return {
                'bid': float(getattr(best_match, 'bid', 0) or 0),
                'ask': float(getattr(best_match, 'ask', 0) or 0),
                'last': float(getattr(best_match, 'last', 0) or 0),
                'volume': int(getattr(best_match, 'volume', 0) or 0),
                'open_interest': int(getattr(best_match, 'open_interest', 0) or 0),
                'implied_volatility': float(getattr(best_match, 'implied_volatility', 0) or 0),
                'strike': float(best_match.strike_price),
                'timestamp': datetime.now().isoformat(),
                'source': 'tastytrade_realtime'
            }
            
        except Exception as e:
            print(f"[VERIFY] Tastytrade quote error: {e}")
            return None
    
    def _get_yfinance_option_quote(self, ticker: str, strike: float, expiry: str,
                                    direction: str) -> Optional[Dict]:
        """Fallback: Get delayed option quote from yfinance"""
        try:
            stock = yf.Ticker(ticker)
            
            try:
                exp_date = datetime.strptime(expiry, "%Y-%m-%d")
            except ValueError:
                exp_date = datetime.strptime(expiry, "%m/%d/%Y")
            
            exp_str = exp_date.strftime("%Y-%m-%d")
            
            try:
                chain = stock.option_chain(exp_str)
            except Exception as e:
                print(f"[VERIFY] yfinance chain error for {ticker} {exp_str}: {e}")
                return None
            
            options_df = chain.calls if direction.lower() == 'call' else chain.puts
            
            if options_df.empty:
                return None
            
            options_df['strike_diff'] = abs(options_df['strike'] - strike)
            closest = options_df.loc[options_df['strike_diff'].idxmin()]
            
            if closest['strike_diff'] > 1.0:
                return None
            
            self.data_source = 'yfinance_delayed'
            return {
                'bid': float(closest.get('bid', 0)) if pd.notna(closest.get('bid')) else 0,
                'ask': float(closest.get('ask', 0)) if pd.notna(closest.get('ask')) else 0,
                'last': float(closest.get('lastPrice', 0)) if pd.notna(closest.get('lastPrice')) else 0,
                'volume': int(closest.get('volume', 0)) if pd.notna(closest.get('volume')) else 0,
                'open_interest': int(closest.get('openInterest', 0)) if pd.notna(closest.get('openInterest')) else 0,
                'implied_volatility': float(closest.get('impliedVolatility', 0)) if pd.notna(closest.get('impliedVolatility')) else 0,
                'strike': float(closest['strike']),
                'timestamp': datetime.now().isoformat(),
                'source': 'yfinance_delayed'
            }
            
        except Exception as e:
            print(f"[VERIFY] yfinance error: {e}")
            return None
    
    def get_option_market_data(self, ticker: str, strike: float, expiry: str, 
                                direction: str) -> Optional[Dict]:
        """
        Fetch options data for verification - tries brokers first, falls back to yfinance
        
        Priority:
        1. Webull (real-time)
        2. Tastytrade (real-time)
        3. yfinance (delayed 15-30 min)
        """
        cache_key = f"{ticker}_{strike}_{expiry}_{direction}"
        now = datetime.now()
        
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if (now - cached_time).seconds < self.cache_duration:
                return cached_data
        
        data = self._get_webull_option_quote(ticker, strike, expiry, direction)
        
        if not data:
            data = self._get_tastytrade_option_quote(ticker, strike, expiry, direction)
        
        if not data:
            data = self._get_yfinance_option_quote(ticker, strike, expiry, direction)
        
        if data:
            self.cache[cache_key] = (data, now)
        
        return data
    
    def get_stock_market_data(self, ticker: str) -> Optional[Dict]:
        """Fetch stock quote - tries Webull first, falls back to yfinance"""
        global _webull_client
        
        if _webull_client:
            try:
                quote = _webull_client.get_quote(stock=ticker)
                if quote:
                    ask = float(quote.get('askPrice', 0) or 0)
                    bid = float(quote.get('bidPrice', 0) or 0)
                    last = float(quote.get('close', 0) or quote.get('lastPrice', 0) or 0)
                    
                    if bid > 0 or ask > 0 or last > 0:
                        self.data_source = 'webull_realtime'
                        return {
                            'bid': bid,
                            'ask': ask,
                            'last': last,
                            'volume': int(quote.get('volume', 0) or 0),
                            'timestamp': datetime.now().isoformat(),
                            'source': 'webull_realtime'
                        }
            except Exception as e:
                print(f"[VERIFY] Webull stock quote error: {e}")
        
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            self.data_source = 'yfinance_delayed'
            return {
                'bid': info.get('bid', 0) or 0,
                'ask': info.get('ask', 0) or 0,
                'last': info.get('regularMarketPrice', info.get('currentPrice', 0)) or 0,
                'volume': info.get('volume', 0) or 0,
                'timestamp': datetime.now().isoformat(),
                'source': 'yfinance_delayed'
            }
        except Exception as e:
            print(f"[VERIFY] yfinance stock error for {ticker}: {e}")
            return None
    
    def verify_signal(self, signal_data: Dict) -> Dict:
        """
        Verify a single signal against market data
        
        Args:
            signal_data: Dict with ticker, strike, expiry, direction, signal_price, signal_time
        
        Returns:
            Verification result with slippage, executability, etc.
        """
        ticker = signal_data.get('ticker', '').upper()
        asset_type = signal_data.get('asset_type', 'option')
        signal_price = float(signal_data.get('signal_price', 0))
        signal_time = signal_data.get('signal_time', datetime.now().isoformat())
        
        result = {
            'ticker': ticker,
            'signal_price': signal_price,
            'signal_time': signal_time,
            'market_data': None,
            'verification_status': 'PENDING',
            'executable': False,
            'within_spread': False,
            'slippage_pct': 0,
            'price_difference': 0,
            'execution_difficulty': 'UNKNOWN',
            'volume_liquidity': 'UNKNOWN',
            'notes': [],
            'red_flags': [],
            'confidence_score': 0
        }
        
        if asset_type == 'option':
            market_data = self.get_option_market_data(
                ticker,
                float(signal_data.get('strike', 0)),
                signal_data.get('expiry', ''),
                signal_data.get('direction', 'call')
            )
        else:
            market_data = self.get_stock_market_data(ticker)
        
        if not market_data:
            result['verification_status'] = 'NO_DATA'
            result['notes'].append('Could not fetch market data for verification')
            return result
        
        result['market_data'] = market_data
        bid = market_data.get('bid', 0)
        ask = market_data.get('ask', 0)
        last = market_data.get('last', 0)
        volume = market_data.get('volume', 0)
        
        if signal_price >= bid and signal_price <= ask:
            result['within_spread'] = True
            result['executable'] = True
            result['notes'].append('Signal price is within bid-ask spread - VALID')
        elif bid > 0 and ask > 0:
            if signal_price < bid:
                result['notes'].append(f'Signal price ${signal_price:.2f} BELOW bid ${bid:.2f} - SUSPICIOUS')
                result['red_flags'].append('PRICE_BELOW_BID')
            elif signal_price > ask:
                result['notes'].append(f'Signal price ${signal_price:.2f} ABOVE ask ${ask:.2f} - Slippage likely')
        
        if ask > 0 and bid > 0:
            mid_price = (bid + ask) / 2
            result['price_difference'] = signal_price - mid_price
            result['slippage_pct'] = ((signal_price - mid_price) / mid_price * 100) if mid_price > 0 else 0
        
        spread = ask - bid if ask > 0 and bid > 0 else 0
        spread_pct = (spread / bid * 100) if bid > 0 else 0
        
        if spread_pct > 20:
            result['execution_difficulty'] = 'VERY_HARD'
            result['notes'].append(f'Wide spread ({spread_pct:.1f}%) - Execution very difficult')
            result['red_flags'].append('WIDE_SPREAD')
        elif spread_pct > 10:
            result['execution_difficulty'] = 'HARD'
            result['notes'].append(f'Moderate spread ({spread_pct:.1f}%) - Execution difficult')
        elif spread_pct > 5:
            result['execution_difficulty'] = 'MODERATE'
        else:
            result['execution_difficulty'] = 'EASY'
        
        if volume == 0:
            result['volume_liquidity'] = 'NONE'
            result['red_flags'].append('ZERO_VOLUME')
            result['notes'].append('ZERO volume - Trade may not have executed')
        elif volume < 10:
            result['volume_liquidity'] = 'VERY_LOW'
            result['red_flags'].append('LOW_VOLUME')
            result['notes'].append('Very low volume - Execution questionable')
        elif volume < 100:
            result['volume_liquidity'] = 'LOW'
        elif volume < 1000:
            result['volume_liquidity'] = 'MODERATE'
        else:
            result['volume_liquidity'] = 'HIGH'
        
        confidence = 100
        
        if not result['within_spread']:
            confidence -= 20
        if 'PRICE_BELOW_BID' in result['red_flags']:
            confidence -= 40
        if 'ZERO_VOLUME' in result['red_flags']:
            confidence -= 30
        elif 'LOW_VOLUME' in result['red_flags']:
            confidence -= 15
        if 'WIDE_SPREAD' in result['red_flags']:
            confidence -= 15
        if abs(result['slippage_pct']) > 5:
            confidence -= 10
        
        result['confidence_score'] = max(0, confidence)
        
        if confidence >= 80:
            result['verification_status'] = 'VERIFIED'
        elif confidence >= 50:
            result['verification_status'] = 'QUESTIONABLE'
        else:
            result['verification_status'] = 'SUSPICIOUS'
        
        return result
    
    def save_verification(self, verification: Dict, signal_id: int = None, 
                          channel_id: int = None, user_id: int = None) -> int:
        """Save verification result to database"""
        conn = self.get_db()
        cursor = conn.cursor()
        
        market_data = verification.get('market_data', {}) or {}
        
        cursor.execute('''
            INSERT INTO signal_verifications (
                signal_id, channel_id, user_id, ticker, asset_type,
                strike, expiry, direction, signal_price, signal_timestamp,
                market_bid, market_ask, market_last, market_volume, open_interest,
                implied_volatility, market_timestamp, price_difference, slippage_pct,
                within_spread, executable, execution_difficulty, volume_liquidity,
                verification_status, verification_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            signal_id, channel_id, user_id,
            verification.get('ticker'),
            verification.get('asset_type', 'option'),
            verification.get('strike'),
            verification.get('expiry'),
            verification.get('direction'),
            verification.get('signal_price'),
            verification.get('signal_time'),
            market_data.get('bid'),
            market_data.get('ask'),
            market_data.get('last'),
            market_data.get('volume'),
            market_data.get('open_interest'),
            market_data.get('implied_volatility'),
            market_data.get('timestamp'),
            verification.get('price_difference'),
            verification.get('slippage_pct'),
            1 if verification.get('within_spread') else 0,
            1 if verification.get('executable') else 0,
            verification.get('execution_difficulty'),
            verification.get('volume_liquidity'),
            verification.get('verification_status'),
            '; '.join(verification.get('notes', []))
        ))
        
        verification_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return verification_id
    
    def get_verifications(self, entity_type: str = None, entity_id: str = None,
                          status: str = None, limit: int = 100) -> List[Dict]:
        """Get verification records with filters"""
        conn = self.get_db()
        cursor = conn.cursor()
        
        query = 'SELECT * FROM signal_verifications WHERE 1=1'
        params = []
        
        if entity_type == 'channel' and entity_id:
            query += ' AND channel_id = ?'
            params.append(entity_id)
        elif entity_type == 'user' and entity_id:
            query += ' AND user_id = ?'
            params.append(entity_id)
        
        if status:
            query += ' AND verification_status = ?'
            params.append(status)
        
        query += ' ORDER BY created_at DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_verification_stats(self, entity_type: str, entity_id: str,
                               days: int = 30) -> Dict:
        """Calculate verification statistics for an entity"""
        conn = self.get_db()
        cursor = conn.cursor()
        
        date_filter = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        if entity_type == 'channel':
            where_clause = 'channel_id = ?'
        else:
            where_clause = 'user_id = ?'
        
        cursor.execute(f'''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN verification_status = 'VERIFIED' THEN 1 ELSE 0 END) as verified,
                SUM(CASE WHEN verification_status = 'QUESTIONABLE' THEN 1 ELSE 0 END) as questionable,
                SUM(CASE WHEN verification_status = 'SUSPICIOUS' THEN 1 ELSE 0 END) as suspicious,
                SUM(CASE WHEN within_spread = 1 THEN 1 ELSE 0 END) as within_spread,
                SUM(CASE WHEN executable = 1 THEN 1 ELSE 0 END) as executable,
                AVG(slippage_pct) as avg_slippage,
                AVG(price_difference) as avg_price_diff,
                SUM(CASE WHEN volume_liquidity = 'HIGH' THEN 1 ELSE 0 END) as high_volume,
                SUM(CASE WHEN volume_liquidity IN ('NONE', 'VERY_LOW') THEN 1 ELSE 0 END) as low_volume
            FROM signal_verifications
            WHERE {where_clause} AND created_at >= ?
        ''', (entity_id, date_filter))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row or row['total'] == 0:
            return {
                'total': 0,
                'verified': 0,
                'questionable': 0,
                'suspicious': 0,
                'verified_pct': 0,
                'suspicious_pct': 0,
                'within_spread_pct': 0,
                'executable_pct': 0,
                'avg_slippage': 0,
                'avg_price_diff': 0,
                'high_volume_pct': 0,
                'low_volume_pct': 0,
                'trust_score': 0
            }
        
        total = row['total']
        verified = row['verified'] or 0
        suspicious = row['suspicious'] or 0
        within_spread = row['within_spread'] or 0
        executable = row['executable'] or 0
        high_volume = row['high_volume'] or 0
        low_volume = row['low_volume'] or 0
        
        trust_score = (verified / total * 50) + (within_spread / total * 30) + (high_volume / total * 20) if total > 0 else 0
        
        return {
            'total': total,
            'verified': verified,
            'questionable': row['questionable'] or 0,
            'suspicious': suspicious,
            'verified_pct': round(verified / total * 100, 1) if total > 0 else 0,
            'suspicious_pct': round(suspicious / total * 100, 1) if total > 0 else 0,
            'within_spread_pct': round(within_spread / total * 100, 1) if total > 0 else 0,
            'executable_pct': round(executable / total * 100, 1) if total > 0 else 0,
            'avg_slippage': round(row['avg_slippage'] or 0, 2),
            'avg_price_diff': round(row['avg_price_diff'] or 0, 4),
            'high_volume_pct': round(high_volume / total * 100, 1) if total > 0 else 0,
            'low_volume_pct': round(low_volume / total * 100, 1) if total > 0 else 0,
            'trust_score': round(trust_score, 1)
        }
    
    def analyze_trade_history(self, entity_type: str, entity_id: str,
                              days: int = 30) -> Dict:
        """
        Analyze historical trades and calculate realistic vs reported performance
        
        Returns comparison between reported signals and what was actually executable
        """
        conn = self.get_db()
        cursor = conn.cursor()
        
        date_filter = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        if entity_type == 'channel':
            where_clause = 'lc.channel_id = ?'
        else:
            where_clause = 'lc.user_id = ?'
        
        cursor.execute(f'''
            SELECT 
                lc.id, lc.ticker, lc.asset_type, lc.open_price, lc.close_price,
                lc.pnl_percent, lc.pnl_dollars, lc.quantity, lc.closed_at,
                lc.strike, lc.expiry, lc.direction
            FROM lot_closures lc
            WHERE {where_clause} AND lc.closed_at >= ?
            ORDER BY lc.closed_at DESC
            LIMIT 200
        ''', (entity_id, date_filter))
        
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        reported_wins = 0
        reported_losses = 0
        reported_pnl = 0
        executable_wins = 0
        executable_losses = 0
        executable_pnl = 0
        suspicious_trades = []
        
        for trade in trades:
            pnl_pct = trade.get('pnl_percent', 0) or 0
            pnl_dollars = trade.get('pnl_dollars', 0) or 0
            
            if pnl_pct > 0:
                reported_wins += 1
            else:
                reported_losses += 1
            reported_pnl += pnl_dollars
            
            signal_data = {
                'ticker': trade.get('ticker'),
                'asset_type': trade.get('asset_type', 'option'),
                'strike': trade.get('strike'),
                'expiry': trade.get('expiry'),
                'direction': trade.get('direction', 'call'),
                'signal_price': trade.get('open_price', 0),
                'signal_time': trade.get('closed_at')
            }
            
            verification = self.verify_signal(signal_data)
            
            if verification['verification_status'] == 'VERIFIED':
                if pnl_pct > 0:
                    executable_wins += 1
                else:
                    executable_losses += 1
                
                slippage_factor = 1 + (verification['slippage_pct'] / 100)
                adjusted_pnl = pnl_dollars * slippage_factor
                executable_pnl += adjusted_pnl
            elif verification['verification_status'] == 'SUSPICIOUS':
                suspicious_trades.append({
                    'ticker': trade['ticker'],
                    'date': trade.get('closed_at', '')[:10] if trade.get('closed_at') else '',
                    'reported_pnl': pnl_pct,
                    'red_flags': verification.get('red_flags', []),
                    'notes': verification.get('notes', [])
                })
        
        total_reported = reported_wins + reported_losses
        total_executable = executable_wins + executable_losses
        
        return {
            'reported': {
                'total_trades': total_reported,
                'wins': reported_wins,
                'losses': reported_losses,
                'win_rate': round(reported_wins / total_reported * 100, 1) if total_reported > 0 else 0,
                'total_pnl': round(reported_pnl, 2)
            },
            'executable': {
                'total_trades': total_executable,
                'wins': executable_wins,
                'losses': executable_losses,
                'win_rate': round(executable_wins / total_executable * 100, 1) if total_executable > 0 else 0,
                'total_pnl': round(executable_pnl, 2),
                'execution_rate': round(total_executable / total_reported * 100, 1) if total_reported > 0 else 0
            },
            'analysis': {
                'pnl_difference': round(reported_pnl - executable_pnl, 2),
                'pnl_difference_pct': round((reported_pnl - executable_pnl) / abs(reported_pnl) * 100, 1) if reported_pnl != 0 else 0,
                'suspicious_trades': len(suspicious_trades),
                'suspicious_pct': round(len(suspicious_trades) / total_reported * 100, 1) if total_reported > 0 else 0,
                'suspicious_details': suspicious_trades[:10]
            }
        }


def verify_single_signal(signal_data: Dict) -> Dict:
    """Convenience function to verify a single signal"""
    service = SignalVerificationService()
    return service.verify_signal(signal_data)


def get_verification_report(entity_type: str, entity_id: str, days: int = 30) -> Dict:
    """Get comprehensive verification report for an entity"""
    service = SignalVerificationService()
    
    stats = service.get_verification_stats(entity_type, entity_id, days)
    analysis = service.analyze_trade_history(entity_type, entity_id, days)
    verifications = service.get_verifications(entity_type, entity_id, limit=50)
    
    return {
        'success': True,
        'entity_type': entity_type,
        'entity_id': entity_id,
        'period_days': days,
        'stats': stats,
        'performance_comparison': analysis,
        'recent_verifications': verifications
    }
