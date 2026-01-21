"""
NDX to QQQ Conversion Service

Converts NDX option signals to equivalent QQQ options with target delta (default 0.3).
Uses broker APIs first (Webull, Alpaca), falls back to Finnhub for options chain data.

Usage:
    from src.services.ndx_qqq_converter import convert_ndx_to_qqq
    
    converted_signal = await convert_ndx_to_qqq(
        signal={'symbol': 'NDX', 'strike': 20000, 'opt_type': 'C', 'expiry': '01/21'},
        channel_settings={'ndx_to_qqq_delta': 0.3},
        broker='Webull'
    )
"""

import os
import asyncio
from datetime import datetime, date
from typing import Dict, Optional, List, Any
import aiohttp


class NDXtoQQQConverter:
    """Service for converting NDX options to QQQ equivalents with delta selection"""
    
    DEFAULT_DELTA = 0.30
    CACHE_TTL = 60  # Cache options chain for 60 seconds
    
    def __init__(self):
        self._chain_cache: Dict[str, Dict] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self.finnhub_api_key = os.environ.get('FINNHUB_API_KEY', '')
    
    async def convert_signal(
        self,
        signal: Dict[str, Any],
        target_delta: float = 0.30,
        broker: str = None,
        enabled_brokers: List[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Convert an NDX option signal to QQQ equivalent with target delta.
        
        Args:
            signal: Original signal dict with symbol, strike, opt_type, expiry
            target_delta: Target delta for strike selection (default 0.30)
            broker: Primary broker to use for data
            enabled_brokers: List of enabled brokers for fallback
            
        Returns:
            Converted signal dict with QQQ symbol and new strike, or None if conversion failed
        """
        symbol = signal.get('symbol', '').upper()
        
        if symbol not in ['NDX', '$NDX', 'NASDAQ', 'NQ']:
            return None
        
        opt_type = signal.get('opt_type', 'C').upper()
        expiry = signal.get('expiry', '')
        original_strike = signal.get('strike')
        
        print(f"[NDX→QQQ] Converting {symbol} {original_strike}{opt_type} {expiry} to QQQ with δ={target_delta}")
        
        expiry_date = self._parse_expiry(expiry)
        if not expiry_date:
            print(f"[NDX→QQQ] ⚠️ Could not parse expiry: {expiry}, using today")
            expiry_date = date.today()
        
        qqq_strike = await self._find_strike_by_delta(
            symbol='QQQ',
            opt_type=opt_type,
            expiry_date=expiry_date,
            target_delta=target_delta,
            broker=broker,
            enabled_brokers=enabled_brokers or []
        )
        
        if qqq_strike is None:
            qqq_strike = await self._fallback_strike_approximation(
                opt_type=opt_type,
                broker=broker,
                target_delta=target_delta
            )
        
        if qqq_strike is None:
            print(f"[NDX→QQQ] ❌ Could not determine QQQ strike, conversion failed")
            return None
        
        converted = signal.copy()
        converted['original_symbol'] = symbol
        converted['original_strike'] = original_strike
        converted['symbol'] = 'QQQ'
        converted['strike'] = qqq_strike
        converted['_ndx_converted'] = True
        converted['_target_delta'] = target_delta
        
        print(f"[NDX→QQQ] ✓ Converted to QQQ {qqq_strike}{opt_type} {expiry}")
        return converted
    
    async def _find_strike_by_delta(
        self,
        symbol: str,
        opt_type: str,
        expiry_date: date,
        target_delta: float,
        broker: str = None,
        enabled_brokers: List[str] = None
    ) -> Optional[float]:
        """Find strike with delta closest to target using broker data"""
        
        brokers_to_try = []
        if broker:
            brokers_to_try.append(broker)
        if enabled_brokers:
            for b in enabled_brokers:
                if b not in brokers_to_try:
                    brokers_to_try.append(b)
        
        chain = None
        for broker_name in brokers_to_try:
            chain = await self._get_options_chain(symbol, expiry_date, broker_name)
            if chain:
                print(f"[NDX→QQQ] Using {broker_name} for options chain data")
                break
        
        if not chain:
            chain = await self._get_finnhub_options_chain(symbol, expiry_date)
            if chain:
                print(f"[NDX→QQQ] Using Finnhub fallback for options chain data")
        
        if not chain:
            print(f"[NDX→QQQ] ⚠️ No options chain data available")
            return None
        
        options = chain.get('calls' if opt_type == 'C' else 'puts', [])
        
        best_strike = None
        best_delta_diff = float('inf')
        
        for opt in options:
            delta = opt.get('delta')
            if delta is None:
                continue
            
            delta = abs(delta) if opt_type == 'P' else delta
            
            delta_diff = abs(delta - target_delta)
            if delta_diff < best_delta_diff:
                best_delta_diff = delta_diff
                best_strike = opt.get('strike')
        
        if best_strike:
            print(f"[NDX→QQQ] Found strike {best_strike} with delta diff {best_delta_diff:.3f}")
        
        return best_strike
    
    async def _get_options_chain(
        self,
        symbol: str,
        expiry_date: date,
        broker: str
    ) -> Optional[Dict]:
        """Get options chain from broker API"""
        
        cache_key = f"{symbol}_{expiry_date}_{broker}"
        now = datetime.now().timestamp()
        
        if cache_key in self._chain_cache:
            if now - self._cache_timestamps.get(cache_key, 0) < self.CACHE_TTL:
                return self._chain_cache[cache_key]
        
        chain = None
        broker_upper = broker.upper() if broker else ''
        
        if 'ALPACA' in broker_upper:
            chain = await self._get_alpaca_options_chain(symbol, expiry_date)
        elif 'WEBULL' in broker_upper:
            chain = await self._get_webull_options_chain(symbol, expiry_date)
        
        if chain:
            self._chain_cache[cache_key] = chain
            self._cache_timestamps[cache_key] = now
        
        return chain
    
    async def _get_alpaca_options_chain(
        self,
        symbol: str,
        expiry_date: date
    ) -> Optional[Dict]:
        """Get options chain with Greeks from Alpaca Market Data API"""
        try:
            from alpaca.data.historical.option import OptionHistoricalDataClient
            from alpaca.data.requests import OptionChainRequest
            from alpaca.trading.client import TradingClient
            import os
            
            api_key = os.environ.get('ALPACA_API_KEY', os.environ.get('APCA_API_KEY_ID', ''))
            api_secret = os.environ.get('ALPACA_API_SECRET', os.environ.get('APCA_API_SECRET_KEY', ''))
            
            if not api_key or not api_secret:
                print(f"[NDX→QQQ] Alpaca credentials not available")
                return None
            
            client = OptionHistoricalDataClient(api_key, api_secret)
            
            request = OptionChainRequest(
                underlying_symbol=symbol,
                expiration_date=expiry_date
            )
            
            chain_data = client.get_option_chain(request)
            
            if not chain_data:
                return None
            
            calls = []
            puts = []
            
            for contract_symbol, snapshot in chain_data.items():
                strike = snapshot.strike_price if hasattr(snapshot, 'strike_price') else None
                delta = None
                
                if hasattr(snapshot, 'greeks') and snapshot.greeks:
                    delta = snapshot.greeks.delta
                
                opt_data = {
                    'strike': strike,
                    'delta': delta,
                    'contract': contract_symbol
                }
                
                if 'C' in contract_symbol[-10:-8]:
                    calls.append(opt_data)
                else:
                    puts.append(opt_data)
            
            return {'calls': calls, 'puts': puts}
            
        except ImportError:
            print(f"[NDX→QQQ] alpaca-py not installed for options chain")
            return None
        except Exception as e:
            print(f"[NDX→QQQ] Alpaca options chain error: {e}")
            return None
    
    async def _get_webull_options_chain(
        self,
        symbol: str,
        expiry_date: date
    ) -> Optional[Dict]:
        """Get options chain from Webull (limited Greeks support)"""
        try:
            from webull import webull
            
            wb = webull()
            
            expiry_str = expiry_date.strftime('%Y-%m-%d')
            chain = wb.get_options(symbol, expiry_str)
            
            if not chain:
                return None
            
            calls = []
            puts = []
            
            for opt in chain:
                strike = float(opt.get('strikePrice', 0))
                delta = opt.get('delta')
                opt_type = opt.get('direction', 'call')
                
                opt_data = {
                    'strike': strike,
                    'delta': float(delta) if delta else None
                }
                
                if opt_type.lower() == 'call':
                    calls.append(opt_data)
                else:
                    puts.append(opt_data)
            
            return {'calls': calls, 'puts': puts}
            
        except Exception as e:
            print(f"[NDX→QQQ] Webull options chain error: {e}")
            return None
    
    async def _get_finnhub_options_chain(
        self,
        symbol: str,
        expiry_date: date
    ) -> Optional[Dict]:
        """Get options chain from Finnhub API (fallback)"""
        if not self.finnhub_api_key:
            print(f"[NDX→QQQ] Finnhub API key not available")
            return None
        
        try:
            url = f"https://finnhub.io/api/v1/stock/option-chain"
            params = {
                'symbol': symbol,
                'token': self.finnhub_api_key
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        print(f"[NDX→QQQ] Finnhub returned status {resp.status}")
                        return None
                    
                    data = await resp.json()
            
            if not data or 'data' not in data:
                return None
            
            expiry_str = expiry_date.strftime('%Y-%m-%d')
            
            calls = []
            puts = []
            
            for expiry_data in data.get('data', []):
                if expiry_data.get('expirationDate') != expiry_str:
                    continue
                
                for opt in expiry_data.get('options', {}).get('CALL', []):
                    calls.append({
                        'strike': opt.get('strike'),
                        'delta': opt.get('greeks', {}).get('delta')
                    })
                
                for opt in expiry_data.get('options', {}).get('PUT', []):
                    puts.append({
                        'strike': opt.get('strike'),
                        'delta': opt.get('greeks', {}).get('delta')
                    })
            
            return {'calls': calls, 'puts': puts} if calls or puts else None
            
        except Exception as e:
            print(f"[NDX→QQQ] Finnhub options chain error: {e}")
            return None
    
    async def _fallback_strike_approximation(
        self,
        opt_type: str,
        broker: str = None,
        target_delta: float = 0.30
    ) -> Optional[float]:
        """
        Fallback: Select ATM +1 strike for delta ~0.30 when Greeks unavailable.
        
        For delta 0.30:
        - CALLS: ATM +1 strike (1 point above current price = slightly OTM)
        - PUTS: ATM -1 strike (1 point below current price = slightly OTM)
        
        This gives approximately 0.30-0.35 delta for near-term options.
        """
        try:
            qqq_price = await self._get_qqq_price(broker)
            if not qqq_price:
                print(f"[NDX→QQQ] Could not get QQQ price for fallback")
                return None
            
            atm_strike = round(qqq_price)
            
            if opt_type == 'C':
                strike = atm_strike + 1
            else:
                strike = atm_strike - 1
            
            print(f"[NDX→QQQ] Fallback: QQQ=${qqq_price:.2f}, ATM=${atm_strike}, using ATM+1 → strike ${strike}")
            return strike
            
        except Exception as e:
            print(f"[NDX→QQQ] Fallback strike error: {e}")
            return None
    
    async def _get_qqq_price(self, broker: str = None) -> Optional[float]:
        """Get current QQQ price from broker or Finnhub"""
        try:
            if broker and 'WEBULL' in broker.upper():
                from webull import webull
                wb = webull()
                quote = wb.get_quote('QQQ')
                if quote and 'close' in quote:
                    return float(quote['close'])
        except Exception as e:
            print(f"[NDX→QQQ] Webull quote error: {e}")
        
        try:
            if self.finnhub_api_key:
                url = f"https://finnhub.io/api/v1/quote"
                params = {'symbol': 'QQQ', 'token': self.finnhub_api_key}
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data.get('c')  # Current price
        except Exception as e:
            print(f"[NDX→QQQ] Finnhub quote error: {e}")
        
        try:
            import yfinance as yf
            ticker = yf.Ticker('QQQ')
            return ticker.info.get('regularMarketPrice')
        except Exception:
            pass
        
        return None
    
    def _parse_expiry(self, expiry: str) -> Optional[date]:
        """Parse expiry string to date object"""
        if not expiry:
            return None
        
        formats = [
            '%m/%d',
            '%m/%d/%Y',
            '%m/%d/%y',
            '%Y-%m-%d',
            '%m-%d-%Y',
            '%m-%d'
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(expiry.strip(), fmt)
                if parsed.year == 1900:
                    parsed = parsed.replace(year=datetime.now().year)
                return parsed.date()
            except ValueError:
                continue
        
        return None


_converter_instance: Optional[NDXtoQQQConverter] = None


def get_ndx_qqq_converter() -> NDXtoQQQConverter:
    """Get singleton converter instance"""
    global _converter_instance
    if _converter_instance is None:
        _converter_instance = NDXtoQQQConverter()
    return _converter_instance


async def convert_ndx_to_qqq(
    signal: Dict[str, Any],
    target_delta: float = 0.30,
    broker: str = None,
    enabled_brokers: List[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to convert NDX signal to QQQ.
    
    Returns:
        Converted signal dict, or None if not an NDX signal or conversion failed
    """
    print(f"[NDX→QQQ WRAPPER] Entering convert_ndx_to_qqq function", flush=True)
    print(f"[NDX→QQQ WRAPPER] signal={signal}", flush=True)
    print(f"[NDX→QQQ WRAPPER] target_delta={target_delta}, broker={broker}", flush=True)
    try:
        converter = get_ndx_qqq_converter()
        print(f"[NDX→QQQ WRAPPER] Got converter instance", flush=True)
        result = await converter.convert_signal(signal, target_delta, broker, enabled_brokers)
        print(f"[NDX→QQQ WRAPPER] Result: {result}", flush=True)
        return result
    except Exception as e:
        print(f"[NDX→QQQ WRAPPER] ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
        raise


def is_ndx_signal(signal: Dict[str, Any]) -> bool:
    """Check if signal is for NDX"""
    symbol = signal.get('symbol', '').upper()
    return symbol in ['NDX', '$NDX', 'NASDAQ', 'NQ']
