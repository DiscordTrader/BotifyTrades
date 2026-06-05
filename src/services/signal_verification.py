"""
Signal Verification Service
Professional-grade signal verification against real-time market data
Detects paper trading, slippage issues, and impossible fills

Data Sources (priority order):
1. Webull API - Real-time bid/ask data (when connected)
2. Tastytrade API - Real-time bid/ask data (when connected)
3. Alpaca API - Real-time bid/ask data (when connected)
4. yfinance - Delayed 15-30 min fallback

Features:
- Historical quote capture at signal execution time
- Time-window tolerance for price verification (+/- 30 seconds)
- Trust score calculation with red flag detection
"""

import yfinance as yf
import sqlite3
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd
import numpy as np

# Use the main database from gui_app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
try:
    from gui_app import database as db
    USE_GUI_DB = True
except ImportError:
    USE_GUI_DB = False
    DATABASE_PATH = os.path.join(os.path.dirname(__file__), '..', 'bot_data.db')

_webull_client = None
_tastytrade_session = None
_alpaca_broker = None
_schwab_broker = None
_ibkr_broker = None
_robinhood_broker = None

# Time window tolerance for historical price verification (seconds)
TIME_WINDOW_TOLERANCE = 30

def set_broker_clients(webull_client=None, tastytrade_session=None, alpaca_broker=None, schwab_broker=None, ibkr_broker=None, robinhood_broker=None):
    """Set broker clients for real-time data access"""
    global _webull_client, _tastytrade_session, _alpaca_broker, _schwab_broker, _ibkr_broker, _robinhood_broker
    _webull_client = webull_client
    _tastytrade_session = tastytrade_session
    _alpaca_broker = alpaca_broker
    _schwab_broker = schwab_broker
    _ibkr_broker = ibkr_broker
    _robinhood_broker = robinhood_broker
    sources = []
    if webull_client:
        sources.append('Webull')
    if tastytrade_session:
        sources.append('Tastytrade')
    if alpaca_broker:
        sources.append('Alpaca')
    if schwab_broker:
        sources.append('Schwab')
    if ibkr_broker:
        sources.append('IBKR')
    if robinhood_broker:
        sources.append('Robinhood')
    if sources:
        print(f"[VERIFY] ✓ Real-time data sources enabled: {', '.join(sources)}")
    else:
        print("[VERIFY] ⚠️ Using yfinance (delayed data) - no broker connected")


def get_broker_status() -> Dict[str, bool]:
    """Get status of connected broker data sources"""
    return {
        'webull': _webull_client is not None,
        'tastytrade': _tastytrade_session is not None,
        'alpaca': _alpaca_broker is not None,
        'schwab': _schwab_broker is not None,
        'ibkr': _ibkr_broker is not None,
        'robinhood': _robinhood_broker is not None,
        'any_realtime': any([_webull_client, _tastytrade_session, _alpaca_broker, _schwab_broker, _ibkr_broker, _robinhood_broker])
    }


class SignalVerificationService:
    """Verify trading signals against real-time market data"""
    
    def __init__(self):
        self.cache = {}
        self.cache_duration = 60
        self.data_source = 'unknown'
    
    def get_db(self):
        """Get database connection from the main gui_app database"""
        if USE_GUI_DB:
            conn = db.get_connection()
            conn._is_shared = True
            return conn
        else:
            conn = sqlite3.connect(DATABASE_PATH)
            conn.row_factory = sqlite3.Row
            conn._is_shared = False
            return conn
    
    def _close_db(self, conn):
        """Close database connection only if it's not the shared thread-local one"""
        if conn and not getattr(conn, '_is_shared', False):
            conn.close()
    
    def _check_streaming_hubs_option(self, ticker: str, strike: float, expiry: str, 
                                      direction: str) -> Optional[Dict]:
        """Check streaming hubs for option quote before REST calls (zero API cost)."""
        opt_char = 'C' if direction.lower() == 'call' else 'P'
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming():
                try:
                    from gui_app.database import get_db
                    db_conn = get_db()
                    cursor = db_conn.execute(
                        "SELECT option_id FROM trades WHERE symbol=? AND strike=? AND call_put=? AND status='OPEN' LIMIT 1",
                        (ticker, strike, opt_char)
                    )
                    row = cursor.fetchone()
                    if row and row[0]:
                        data = hub.get_quote_detailed(str(row[0]))
                        if data and (data.get('bid', 0) > 0 or data.get('ask', 0) > 0 or data.get('last', 0) > 0):
                            print(f"[VERIFY] ⚡ Got option quote from Webull streaming hub (zero API cost)")
                            self.data_source = 'webull_streaming'
                            return {
                                'bid': float(data.get('bid', 0) or 0),
                                'ask': float(data.get('ask', 0) or 0),
                                'last': float(data.get('last', 0) or 0),
                                'volume': int(data.get('volume', 0) or 0),
                                'strike': strike,
                                'timestamp': datetime.now().isoformat(),
                                'source': 'webull_streaming'
                            }
                except Exception:
                    pass
        except Exception:
            pass
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            schwab_hub = get_schwab_data_hub()
            if schwab_hub.is_streaming():
                iso_exp = expiry
                if '/' in expiry:
                    try:
                        exp_date = datetime.strptime(expiry, "%m/%d/%Y")
                        iso_exp = exp_date.strftime("%Y-%m-%d")
                    except ValueError:
                        pass
                if '-' in iso_exp:
                    from src.brokers.schwab_broker import SchwabBroker
                    occ = SchwabBroker._build_option_symbol(None, ticker, iso_exp, strike, opt_char)
                    data = schwab_hub.get_quote_detailed(occ)
                    if data and (data.get('bid', 0) > 0 or data.get('ask', 0) > 0 or data.get('last', 0) > 0):
                        print(f"[VERIFY] ⚡ Got option quote from Schwab streaming hub (zero API cost)")
                        self.data_source = 'schwab_streaming'
                        return {
                            'bid': float(data.get('bid', 0) or 0),
                            'ask': float(data.get('ask', 0) or 0),
                            'last': float(data.get('last', 0) or 0),
                            'volume': int(data.get('volume', 0) or 0),
                            'strike': strike,
                            'timestamp': datetime.now().isoformat(),
                            'source': 'schwab_streaming'
                        }
        except Exception:
            pass
        return None

    def _check_streaming_hubs_stock(self, ticker: str) -> Optional[Dict]:
        """Check streaming hubs for stock quote before REST calls (zero API cost)."""
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming():
                data = hub.get_quote_detailed(ticker)
                if data and (data.get('bid', 0) > 0 or data.get('last', 0) > 0):
                    print(f"[VERIFY] ⚡ Got stock quote from Webull streaming hub (zero API cost)")
                    self.data_source = 'webull_streaming'
                    return {
                        'bid': float(data.get('bid', 0) or 0),
                        'ask': float(data.get('ask', 0) or 0),
                        'last': float(data.get('last', 0) or 0),
                        'volume': int(data.get('volume', 0) or 0),
                        'timestamp': datetime.now().isoformat(),
                        'source': 'webull_streaming'
                    }
        except Exception:
            pass
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            hub = get_schwab_data_hub()
            if hub.is_streaming():
                data = hub.get_quote_detailed(ticker)
                if data and (data.get('bid', 0) > 0 or data.get('last', 0) > 0):
                    print(f"[VERIFY] ⚡ Got stock quote from Schwab streaming hub (zero API cost)")
                    self.data_source = 'schwab_streaming'
                    return {
                        'bid': float(data.get('bid', 0) or 0),
                        'ask': float(data.get('ask', 0) or 0),
                        'last': float(data.get('last', 0) or 0),
                        'volume': int(data.get('volume', 0) or 0),
                        'timestamp': datetime.now().isoformat(),
                        'source': 'schwab_streaming'
                    }
        except Exception:
            pass
        return None

    def _get_webull_option_quote(self, ticker: str, strike: float, expiry: str, 
                                  direction: str) -> Optional[Dict]:
        """Get real-time option quote — streaming hubs first, then Webull REST fallback"""
        hub_result = self._check_streaming_hubs_option(ticker, strike, expiry, direction)
        if hub_result:
            return hub_result

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
        if not _tastytrade_session:
            return None
        
        try:
            from tastytrade.instruments import get_option_chain
            
            try:
                exp_date = datetime.strptime(expiry, "%Y-%m-%d")
            except ValueError:
                exp_date = datetime.strptime(expiry, "%m/%d/%Y")
            
            import inspect as _inspect
            chain = get_option_chain(_tastytrade_session, ticker)
            if _inspect.isawaitable(chain):
                import asyncio as _asyncio
                _loop = _asyncio.new_event_loop()
                try:
                    chain = _loop.run_until_complete(chain)
                finally:
                    _loop.close()
            
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
    
    def _run_schwab_async_safe(self, coro_func):
        """Execute Schwab async coroutine safely from any context
        
        Uses a dedicated thread with its own event loop to avoid
        deadlocks when called from existing async contexts.
        
        Args:
            coro_func: A callable that returns a coroutine (not the coroutine itself)
        """
        import asyncio
        import concurrent.futures
        
        def run_in_thread():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(coro_func())
            finally:
                new_loop.close()
        
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_in_thread)
                return future.result(timeout=15)
        except concurrent.futures.TimeoutError:
            print("[VERIFY] Schwab quote timeout")
            return None
        except Exception as e:
            print(f"[VERIFY] Schwab async execution error: {e}")
            return None
    
    def _get_schwab_option_quote(self, ticker: str, strike: float, expiry: str,
                                  direction: str) -> Optional[Dict]:
        """Get real-time option quote from Schwab"""
        if not _schwab_broker:
            return None
        
        try:
            try:
                exp_date = datetime.strptime(expiry, "%Y-%m-%d")
            except ValueError:
                exp_date = datetime.strptime(expiry, "%m/%d/%Y")
            
            iso_exp = exp_date.strftime("%Y-%m-%d")
            opt_type = 'CALL' if direction.lower() == 'call' else 'PUT'
            
            quote = self._run_schwab_async_safe(
                lambda: _schwab_broker.get_option_quote(ticker, strike, iso_exp, opt_type)
            )
            
            if quote:
                bid = float(quote.get('bid', 0) or 0)
                ask = float(quote.get('ask', 0) or 0)
                last = float(quote.get('last', 0) or quote.get('price', 0) or 0)
                
                if bid > 0 or ask > 0 or last > 0:
                    self.data_source = 'schwab_realtime'
                    return {
                        'bid': bid,
                        'ask': ask,
                        'last': last,
                        'volume': int(quote.get('volume', 0) or 0),
                        'open_interest': int(quote.get('open_interest', 0) or 0),
                        'implied_volatility': float(quote.get('implied_volatility', 0) or 0),
                        'strike': strike,
                        'timestamp': datetime.now().isoformat(),
                        'source': 'schwab_realtime'
                    }
        except Exception as e:
            print(f"[VERIFY] Schwab option quote error: {e}")
        return None
    
    def _run_ibkr_async_safe(self, coro_func):
        """Execute IBKR async coroutine safely from any context
        
        Uses a dedicated thread with its own event loop to avoid
        deadlocks when called from existing async contexts.
        
        Args:
            coro_func: A callable that returns a coroutine (not the coroutine itself)
        """
        import asyncio
        import concurrent.futures
        
        def run_in_thread():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(coro_func())
            finally:
                new_loop.close()
        
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_in_thread)
                return future.result(timeout=15)
        except concurrent.futures.TimeoutError:
            print("[VERIFY] IBKR quote timeout")
            return None
        except Exception as e:
            print(f"[VERIFY] IBKR async execution error: {e}")
            return None
    
    def _get_ibkr_option_quote(self, ticker: str, strike: float, expiry: str,
                                direction: str) -> Optional[Dict]:
        """Get real-time option quote from IBKR (requires TWS/Gateway)"""
        if not _ibkr_broker or not hasattr(_ibkr_broker, 'ib'):
            return None
        
        try:
            if not _ibkr_broker.ib.isConnected():
                return None
            
            quote = self._run_ibkr_async_safe(
                lambda: _ibkr_broker.get_option_quote(ticker, strike, expiry, direction)
            )
            
            if quote:
                bid = float(quote.get('bid', 0) or 0)
                ask = float(quote.get('ask', 0) or 0)
                last = float(quote.get('last', 0) or quote.get('price', 0) or 0)
                
                if bid > 0 or ask > 0 or last > 0:
                    self.data_source = 'ibkr_realtime'
                    return {
                        'bid': bid,
                        'ask': ask,
                        'last': last,
                        'volume': int(quote.get('volume', 0) or 0),
                        'open_interest': int(quote.get('open_interest', 0) or 0),
                        'implied_volatility': float(quote.get('implied_volatility', 0) or 0),
                        'strike': strike,
                        'timestamp': datetime.now().isoformat(),
                        'source': 'ibkr_realtime'
                    }
        except Exception as e:
            print(f"[VERIFY] IBKR option quote error: {e}")
        return None
    
    def _run_robinhood_async_safe(self, coro_func):
        """Execute Robinhood async coroutine safely from any context
        
        Uses a dedicated thread with its own event loop to avoid
        deadlocks when called from existing async contexts.
        
        Args:
            coro_func: A callable that returns a coroutine (not the coroutine itself)
        """
        import asyncio
        import concurrent.futures
        
        def run_in_thread():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(coro_func())
            finally:
                new_loop.close()
        
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_in_thread)
                return future.result(timeout=15)
        except concurrent.futures.TimeoutError:
            print("[VERIFY] Robinhood quote timeout")
            return None
        except Exception as e:
            print(f"[VERIFY] Robinhood async execution error: {e}")
            return None
    
    def _get_robinhood_option_quote(self, ticker: str, strike: float, expiry: str,
                                     direction: str) -> Optional[Dict]:
        """Get option quote from Robinhood (WARNING: LIVE ONLY - no paper trading)"""
        if not _robinhood_broker:
            return None
        
        try:
            quote = self._run_robinhood_async_safe(
                lambda: _robinhood_broker.get_option_quote(ticker, strike, expiry, direction)
            )
            
            if quote:
                bid = float(quote.get('bid', 0) or 0)
                ask = float(quote.get('ask', 0) or 0)
                last = float(quote.get('last', 0) or quote.get('price', 0) or 0)
                
                if bid > 0 or ask > 0 or last > 0:
                    self.data_source = 'robinhood_live'
                    return {
                        'bid': bid,
                        'ask': ask,
                        'last': last,
                        'volume': int(quote.get('volume', 0) or 0),
                        'open_interest': int(quote.get('open_interest', 0) or 0),
                        'implied_volatility': float(quote.get('implied_volatility', 0) or 0),
                        'strike': strike,
                        'timestamp': datetime.now().isoformat(),
                        'source': 'robinhood_live'
                    }
        except Exception as e:
            print(f"[VERIFY] Robinhood option quote error: {e}")
        return None
    
    def get_option_market_data(self, ticker: str, strike: float, expiry: str, 
                                direction: str, preferred_broker: str = 'auto') -> Optional[Dict]:
        """
        Fetch options data for verification - uses preferred broker or auto-selects
        
        Args:
            preferred_broker: 'auto', 'webull', 'tastytrade', 'schwab', 'ibkr', 'robinhood', or 'yfinance'
        
        Priority when auto:
        1. Webull (real-time)
        2. Tastytrade (real-time)
        3. Schwab (real-time)
        4. IBKR (real-time, requires TWS/Gateway)
        5. Robinhood (live only - WARNING: no paper trading)
        6. yfinance (delayed 15-30 min)
        """
        cache_key = f"{ticker}_{strike}_{expiry}_{direction}_{preferred_broker}"
        now = datetime.now()
        
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if (now - cached_time).seconds < self.cache_duration:
                return cached_data
        
        data = None
        
        if preferred_broker == 'webull':
            data = self._get_webull_option_quote(ticker, strike, expiry, direction)
            if not data:
                print(f"[VERIFY] Webull not available, no fallback (user selected Webull only)")
        elif preferred_broker == 'tastytrade':
            data = self._get_tastytrade_option_quote(ticker, strike, expiry, direction)
            if not data:
                print(f"[VERIFY] Tastytrade not available, no fallback (user selected Tastytrade only)")
        elif preferred_broker == 'schwab':
            data = self._get_schwab_option_quote(ticker, strike, expiry, direction)
            if not data:
                print(f"[VERIFY] Schwab not available, no fallback (user selected Schwab only)")
        elif preferred_broker == 'ibkr':
            data = self._get_ibkr_option_quote(ticker, strike, expiry, direction)
            if not data:
                print(f"[VERIFY] IBKR not available, no fallback (user selected IBKR only)")
        elif preferred_broker == 'robinhood':
            data = self._get_robinhood_option_quote(ticker, strike, expiry, direction)
            if not data:
                print(f"[VERIFY] Robinhood not available, no fallback (user selected Robinhood only)")
        elif preferred_broker == 'yfinance':
            data = self._get_yfinance_option_quote(ticker, strike, expiry, direction)
        else:
            data = self._get_webull_option_quote(ticker, strike, expiry, direction)
            if not data:
                data = self._get_tastytrade_option_quote(ticker, strike, expiry, direction)
            if not data:
                data = self._get_schwab_option_quote(ticker, strike, expiry, direction)
            if not data:
                data = self._get_ibkr_option_quote(ticker, strike, expiry, direction)
            if not data:
                data = self._get_robinhood_option_quote(ticker, strike, expiry, direction)
            if not data:
                data = self._get_yfinance_option_quote(ticker, strike, expiry, direction)
        
        if data:
            self.cache[cache_key] = (data, now)
        
        return data
    
    def _get_alpaca_stock_quote(self, ticker: str) -> Optional[Dict]:
        """Get real-time stock quote from Alpaca"""
        if not _alpaca_broker:
            return None
        
        try:
            quote = _alpaca_broker.get_quote(ticker)
            if quote:
                bid = float(quote.get('bid', 0) or 0)
                ask = float(quote.get('ask', 0) or 0)
                last = float(quote.get('last', 0) or quote.get('price', 0) or 0)
                
                if bid > 0 or ask > 0 or last > 0:
                    self.data_source = 'alpaca_realtime'
                    return {
                        'bid': bid,
                        'ask': ask,
                        'last': last,
                        'volume': int(quote.get('volume', 0) or 0),
                        'timestamp': datetime.now().isoformat(),
                        'source': 'alpaca_realtime'
                    }
        except Exception as e:
            print(f"[VERIFY] Alpaca stock quote error: {e}")
        return None
    
    def _get_schwab_stock_quote(self, ticker: str) -> Optional[Dict]:
        """Get real-time stock quote from Schwab"""
        if not _schwab_broker:
            return None
        
        try:
            quote = self._run_schwab_async_safe(lambda: _schwab_broker.get_quote_detailed(ticker))
            
            if quote:
                bid = float(quote.get('bid', 0) or 0)
                ask = float(quote.get('ask', 0) or 0)
                last = float(quote.get('last', 0) or quote.get('price', 0) or 0)
                
                if bid > 0 or ask > 0 or last > 0:
                    self.data_source = 'schwab_realtime'
                    return {
                        'bid': bid,
                        'ask': ask,
                        'last': last,
                        'volume': int(quote.get('volume', 0) or 0),
                        'timestamp': datetime.now().isoformat(),
                        'source': 'schwab_realtime'
                    }
        except Exception as e:
            print(f"[VERIFY] Schwab stock quote error: {e}")
        return None
    
    def _get_ibkr_stock_quote(self, ticker: str) -> Optional[Dict]:
        """Get real-time stock quote from IBKR (requires TWS/Gateway)"""
        if not _ibkr_broker or not hasattr(_ibkr_broker, 'ib'):
            return None
        
        try:
            if not _ibkr_broker.ib.isConnected():
                return None
            
            quote = self._run_ibkr_async_safe(lambda: _ibkr_broker.get_quote_detailed(ticker))
            
            if quote:
                bid = float(quote.get('bid', 0) or 0)
                ask = float(quote.get('ask', 0) or 0)
                last = float(quote.get('last', 0) or quote.get('price', 0) or 0)
                
                if bid > 0 or ask > 0 or last > 0:
                    self.data_source = 'ibkr_realtime'
                    return {
                        'bid': bid,
                        'ask': ask,
                        'last': last,
                        'volume': int(quote.get('volume', 0) or 0),
                        'timestamp': datetime.now().isoformat(),
                        'source': 'ibkr_realtime'
                    }
        except Exception as e:
            print(f"[VERIFY] IBKR stock quote error: {e}")
        return None
    
    def _get_robinhood_stock_quote(self, ticker: str) -> Optional[Dict]:
        """Get stock quote from Robinhood (WARNING: LIVE ONLY - no paper trading)"""
        if not _robinhood_broker:
            return None
        
        try:
            quote = self._run_robinhood_async_safe(lambda: _robinhood_broker.get_quote_detailed(ticker))
            
            if quote:
                bid = float(quote.get('bid', 0) or 0)
                ask = float(quote.get('ask', 0) or 0)
                last = float(quote.get('last', 0) or quote.get('price', 0) or 0)
                
                if bid > 0 or ask > 0 or last > 0:
                    self.data_source = 'robinhood_live'
                    return {
                        'bid': bid,
                        'ask': ask,
                        'last': last,
                        'volume': int(quote.get('volume', 0) or 0),
                        'timestamp': datetime.now().isoformat(),
                        'source': 'robinhood_live'
                    }
        except Exception as e:
            print(f"[VERIFY] Robinhood stock quote error: {e}")
        return None
    
    def get_stock_market_data(self, ticker: str, preferred_broker: str = 'auto') -> Optional[Dict]:
        """Fetch stock quote — streaming hubs first, then preferred broker"""
        
        if preferred_broker != 'yfinance':
            hub_result = self._check_streaming_hubs_stock(ticker)
            if hub_result:
                return hub_result

        if preferred_broker == 'yfinance':
            pass
        elif preferred_broker == 'schwab':
            data = self._get_schwab_stock_quote(ticker)
            if data:
                return data
        elif preferred_broker == 'alpaca':
            data = self._get_alpaca_stock_quote(ticker)
            if data:
                return data
        elif preferred_broker == 'webull' or (preferred_broker == 'auto' and _webull_client):
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
        elif preferred_broker == 'auto' and _alpaca_broker:
            data = self._get_alpaca_stock_quote(ticker)
            if data:
                return data
        elif preferred_broker == 'auto' and _schwab_broker:
            data = self._get_schwab_stock_quote(ticker)
            if data:
                return data
        elif preferred_broker == 'ibkr':
            data = self._get_ibkr_stock_quote(ticker)
            if data:
                return data
        elif preferred_broker == 'auto' and _ibkr_broker:
            data = self._get_ibkr_stock_quote(ticker)
            if data:
                return data
        elif preferred_broker == 'robinhood':
            data = self._get_robinhood_stock_quote(ticker)
            if data:
                return data
        elif preferred_broker == 'auto' and _robinhood_broker:
            data = self._get_robinhood_stock_quote(ticker)
            if data:
                return data
        
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
    
    def capture_quote_at_signal_time(self, signal_data: Dict, preferred_broker: str = 'auto') -> Optional[Dict]:
        """
        Capture and store real-time quote at the moment a signal is detected.
        This is called when a new signal is parsed, before execution.
        
        Args:
            signal_data: Dict with ticker, strike, expiry, direction
            preferred_broker: Broker to use for quote
            
        Returns:
            Market data snapshot with timestamp
        """
        ticker = signal_data.get('ticker', '').upper()
        asset_type = signal_data.get('asset_type', 'option')
        
        try:
            if asset_type == 'option':
                market_data = self.get_option_market_data(
                    ticker,
                    float(signal_data.get('strike', 0)),
                    signal_data.get('expiry', ''),
                    signal_data.get('direction', 'call'),
                    preferred_broker=preferred_broker
                )
            else:
                market_data = self.get_stock_market_data(ticker, preferred_broker=preferred_broker)
            
            if market_data:
                market_data['captured_at'] = datetime.now().isoformat()
                market_data['capture_type'] = 'signal_time'
                print(f"[VERIFY] Captured quote for {ticker}: bid=${market_data.get('bid', 0):.2f}, ask=${market_data.get('ask', 0):.2f}")
                return market_data
                
        except Exception as e:
            print(f"[VERIFY] Failed to capture quote at signal time: {e}")
        
        return None
    
    def _is_within_time_window(self, signal_time_str: str, market_timestamp_str: str) -> Tuple[bool, float]:
        """
        Check if market data timestamp is within acceptable time window of signal.
        Uses TIME_WINDOW_TOLERANCE (default 30 seconds).
        
        Returns:
            Tuple of (is_within_window, time_difference_seconds)
        """
        try:
            if isinstance(signal_time_str, str):
                signal_time = datetime.fromisoformat(signal_time_str.replace('Z', '+00:00'))
            else:
                signal_time = signal_time_str
            
            if isinstance(market_timestamp_str, str):
                market_time = datetime.fromisoformat(market_timestamp_str.replace('Z', '+00:00'))
            else:
                market_time = market_timestamp_str
            
            time_diff = abs((market_time - signal_time).total_seconds())
            is_within = time_diff <= TIME_WINDOW_TOLERANCE
            
            return is_within, time_diff
            
        except Exception as e:
            print(f"[VERIFY] Time window check error: {e}")
            return False, -1
    
    def verify_signal(self, signal_data: Dict, preferred_broker: str = 'auto', 
                      historical_quote: Optional[Dict] = None) -> Dict:
        """
        Verify a single signal against market data
        
        Args:
            signal_data: Dict with ticker, strike, expiry, direction, signal_price, signal_time
            preferred_broker: 'auto', 'webull', 'tastytrade', 'alpaca', or 'yfinance'
            historical_quote: Optional pre-captured quote from signal execution time
        
        Returns:
            Verification result with slippage, executability, time-window validation, etc.
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
            'confidence_score': 0,
            'data_source': 'unknown',
            'time_window_valid': False,
            'time_difference_seconds': -1,
            'used_historical_quote': False
        }
        
        # Use historical quote if provided (captured at signal execution time)
        market_data = None
        if historical_quote:
            market_data = historical_quote
            result['used_historical_quote'] = True
            result['notes'].append('Using historical quote captured at signal time')
            
            # Validate time window
            captured_at = historical_quote.get('captured_at') or historical_quote.get('timestamp')
            if captured_at:
                is_within, time_diff = self._is_within_time_window(signal_time, captured_at)
                result['time_window_valid'] = is_within
                result['time_difference_seconds'] = time_diff
                if is_within:
                    result['notes'].append(f'Quote within {TIME_WINDOW_TOLERANCE}s window ({time_diff:.1f}s)')
                else:
                    result['notes'].append(f'Quote outside time window ({time_diff:.1f}s > {TIME_WINDOW_TOLERANCE}s)')
                    result['red_flags'].append('STALE_QUOTE')
        
        # Fetch fresh market data if no historical quote provided
        if not market_data:
            if asset_type == 'option':
                market_data = self.get_option_market_data(
                    ticker,
                    float(signal_data.get('strike', 0)),
                    signal_data.get('expiry', ''),
                    signal_data.get('direction', 'call'),
                    preferred_broker=preferred_broker
                )
            else:
                market_data = self.get_stock_market_data(ticker, preferred_broker=preferred_broker)
            
            # For fresh quotes, always check time window and apply penalties
            if market_data:
                market_timestamp = market_data.get('timestamp')
                if market_timestamp:
                    is_within, time_diff = self._is_within_time_window(signal_time, market_timestamp)
                    result['time_window_valid'] = is_within
                    result['time_difference_seconds'] = time_diff
                    
                    # Apply stale quote penalty for fresh quotes outside time window
                    if not is_within:
                        result['notes'].append(f'Fresh quote outside time window ({time_diff:.1f}s > {TIME_WINDOW_TOLERANCE}s)')
                        result['red_flags'].append('STALE_QUOTE')
        
        if not market_data:
            result['verification_status'] = 'NO_DATA'
            result['notes'].append('Could not fetch market data for verification')
            return result
        
        result['market_data'] = market_data
        result['data_source'] = market_data.get('source', 'unknown')
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
        
        # ORDER SIZE ANALYSIS - Check if signal quantity could realistically fill
        signal_qty = signal_data.get('signal_quantity', 1)
        if signal_qty and volume > 0:
            qty_to_volume_ratio = signal_qty / volume
            result['qty_to_volume_ratio'] = round(qty_to_volume_ratio, 4)
            
            if qty_to_volume_ratio > 0.5:
                result['red_flags'].append('POSITION_SIZE_EXCEEDS_LIQUIDITY')
                result['notes'].append(f'Position size ({signal_qty}) is {qty_to_volume_ratio*100:.1f}% of total volume - SUSPICIOUS')
            elif qty_to_volume_ratio > 0.2:
                result['red_flags'].append('LARGE_POSITION_RELATIVE_TO_VOLUME')
                result['notes'].append(f'Large position relative to volume ({qty_to_volume_ratio*100:.1f}%)')
        elif signal_qty and volume == 0:
            result['red_flags'].append('FILL_IMPOSSIBLE_NO_VOLUME')
            result['notes'].append(f'Cannot fill {signal_qty} contracts with ZERO volume')
        
        # PRICE MOVEMENT RED FLAGS
        if last > 0 and signal_price > 0:
            price_vs_last = abs(signal_price - last) / last * 100
            if price_vs_last > 20:
                result['red_flags'].append('EXTREME_PRICE_DEVIATION')
                result['notes'].append(f'Signal price deviates {price_vs_last:.1f}% from last trade')
        
        # OPEN INTEREST CHECK (for options)
        open_interest = market_data.get('open_interest', 0) or 0
        if asset_type == 'option':
            if open_interest == 0 and signal_qty > 0:
                result['red_flags'].append('ZERO_OPEN_INTEREST')
                result['notes'].append('Zero open interest - Very illiquid option')
            elif open_interest > 0 and signal_qty > open_interest * 0.1:
                result['red_flags'].append('POSITION_EXCEEDS_10PCT_OI')
                result['notes'].append(f'Position is {signal_qty/open_interest*100:.1f}% of open interest')
        
        confidence = 100
        
        # CORE VERIFICATION CHECKS
        if not result['within_spread']:
            confidence -= 20
        if 'PRICE_BELOW_BID' in result['red_flags']:
            confidence -= 40  # Critical: price below bid is highly suspicious
        
        # VOLUME/LIQUIDITY PENALTIES
        if 'ZERO_VOLUME' in result['red_flags']:
            confidence -= 30
        elif 'LOW_VOLUME' in result['red_flags']:
            confidence -= 15
        if 'WIDE_SPREAD' in result['red_flags']:
            confidence -= 15
        
        # SLIPPAGE PENALTIES (tiered)
        slippage = abs(result['slippage_pct'])
        if slippage > 10:
            confidence -= 20
        elif slippage > 5:
            confidence -= 10
        elif slippage > 2:
            confidence -= 5
        
        # ORDER SIZE PENALTIES
        if 'POSITION_SIZE_EXCEEDS_LIQUIDITY' in result['red_flags']:
            confidence -= 35  # Very suspicious - position > 50% of volume
        elif 'LARGE_POSITION_RELATIVE_TO_VOLUME' in result['red_flags']:
            confidence -= 15
        if 'FILL_IMPOSSIBLE_NO_VOLUME' in result['red_flags']:
            confidence -= 40  # Critical: cannot fill with zero volume
        
        # OPEN INTEREST PENALTIES (options only)
        if 'ZERO_OPEN_INTEREST' in result['red_flags']:
            confidence -= 25
        elif 'POSITION_EXCEEDS_10PCT_OI' in result['red_flags']:
            confidence -= 15
        
        # PRICE DEVIATION PENALTY
        if 'EXTREME_PRICE_DEVIATION' in result['red_flags']:
            confidence -= 20
        
        # Time-window validation penalties
        if 'STALE_QUOTE' in result['red_flags']:
            confidence -= 15
            result['notes'].append('Stale quote penalty applied (-15)')
        
        # Boost confidence if using historical quote within time window
        if result['used_historical_quote'] and result['time_window_valid']:
            confidence += 10
            result['notes'].append('Historical quote bonus applied (+10)')
        
        # Penalty for using delayed data sources
        if result['data_source'] == 'yfinance_delayed':
            confidence -= 5
            result['notes'].append('Delayed data source penalty (-5)')
        
        # Bonus for real-time broker data
        if result['data_source'] in ('webull_realtime', 'alpaca_realtime', 'tastytrade_realtime'):
            confidence += 5
            result['notes'].append('Real-time data bonus (+5)')
        
        result['confidence_score'] = max(0, min(100, confidence))
        
        if confidence >= 80:
            result['verification_status'] = 'VERIFIED'
        elif confidence >= 50:
            result['verification_status'] = 'QUESTIONABLE'
        else:
            result['verification_status'] = 'SUSPICIOUS'
        
        return result
    
    def save_verification(self, verification: Dict, signal_id: Optional[int] = None, 
                          channel_id: Optional[int] = None, user_id: Optional[int] = None) -> Optional[int]:
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
        self._close_db(conn)
        
        return verification_id
    
    def get_verifications(self, entity_type: Optional[str] = None, entity_id: Optional[str] = None,
                          status: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """Get verification records with filters"""
        conn = self.get_db()
        cursor = conn.cursor()
        
        query = 'SELECT * FROM signal_verifications WHERE 1=1'
        params = []
        
        if entity_type == 'channel' and entity_id:
            query += ' AND channel_id = ?'
            params.append(entity_id)
        elif entity_type == 'user' and entity_id:
            query += ' AND author_name = ?'
            params.append(entity_id)
        
        if status:
            query += ' AND verification_status = ?'
            params.append(status)
        
        query += ' ORDER BY created_at DESC LIMIT ?'
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        self._close_db(conn)
        
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
            where_clause = 'author_name = ?'
        
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
        self._close_db(conn)
        
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
        
        # INDUSTRY-STANDARD TRUST SCORE CALCULATION
        # Weights: Verified status (40%), Within spread (25%), High liquidity (20%), Low slippage (15%)
        verified_component = (verified / total * 40) if total > 0 else 0
        spread_component = (within_spread / total * 25) if total > 0 else 0
        liquidity_component = (high_volume / total * 20) if total > 0 else 0
        
        # Slippage penalty: reduce score for high average slippage
        avg_slippage = abs(row['avg_slippage'] or 0)
        slippage_component = max(0, 15 - (avg_slippage * 2))  # 15 points max, lose 2 per % slippage
        
        # Suspicious trade penalty
        suspicious_penalty = (suspicious / total * 10) if total > 0 else 0
        
        trust_score = verified_component + spread_component + liquidity_component + slippage_component - suspicious_penalty
        
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
            where_clause = 'lc.author_name = ?'
        
        cursor.execute(f'''
            SELECT 
                lc.id, sl.symbol as ticker, sl.asset_type, sl.open_price, lc.close_price,
                lc.pnl_percent, lc.pnl as pnl_dollars, lc.closed_qty as quantity, lc.closed_at,
                sl.strike, sl.expiry, sl.call_put as direction,
                sl.opened_at as entry_time,
                sl.original_qty as signal_quantity
            FROM lot_closures lc
            LEFT JOIN signal_lots sl ON lc.lot_id = sl.id
            WHERE {where_clause} AND lc.closed_at >= ?
            ORDER BY lc.closed_at DESC
            LIMIT 200
        ''', (entity_id, date_filter))
        
        trades = [dict(row) for row in cursor.fetchall()]
        self._close_db(conn)
        
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
            ticker = trade.get('ticker') or 'UNKNOWN'
            
            if pnl_pct > 0:
                reported_wins += 1
            else:
                reported_losses += 1
            reported_pnl += pnl_dollars
            
            # CRITICAL FIX: Use entry_time (opened_at) instead of closed_at
            # This ensures we verify against market conditions when signal was issued
            entry_time = trade.get('entry_time') or trade.get('closed_at')
            
            signal_data = {
                'ticker': ticker,
                'asset_type': trade.get('asset_type', 'option'),
                'strike': trade.get('strike'),
                'expiry': trade.get('expiry'),
                'direction': trade.get('direction', 'call'),
                'signal_price': trade.get('open_price', 0),
                'signal_time': entry_time,
                'signal_quantity': trade.get('signal_quantity', 1)
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
                    'ticker': ticker,
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


def verify_single_signal(signal_data: Dict, preferred_broker: str = 'auto') -> Dict:
    """Convenience function to verify a single signal with optional broker preference"""
    service = SignalVerificationService()
    return service.verify_signal(signal_data, preferred_broker=preferred_broker)


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
