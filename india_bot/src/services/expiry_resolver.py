"""
Expiry Resolver Service - Dynamic expiry resolution using broker instrument masters

This service resolves the correct trading instrument for signals by:
1. Fetching and caching full instrument masters from brokers (Upstox, Zerodha)
2. Automatically picking the next valid expiry when not specified in signal
3. Validating specified expiries against available contracts
4. Supporting both OPTIONS and FUTURES
5. Handling weekly vs monthly expiries without hardcoded weekday rules

Usage:
    from src.services.expiry_resolver import resolve_instrument, ExpiryResolver
    
    resolver = ExpiryResolver()
    contract = resolver.resolve(
        underlying='NIFTY',
        strike=26300,
        option_type='PE',
        expiry=None,  # Auto-pick next expiry
        broker='upstox'
    )
"""

import os
import re
import json
import time
import logging
import threading
import requests
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

try:
    import pytz
    IST = pytz.timezone('Asia/Kolkata')
except ImportError:
    IST = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('ExpiryResolver')

CACHE_TTL_SECONDS = int(os.getenv('INSTRUMENT_CACHE_TTL', 12 * 60 * 60))

SYMBOL_ALIASES = {
    'NIFTY50': 'NIFTY',
    'NIFTY 50': 'NIFTY',
    'BANK NIFTY': 'BANKNIFTY',
    'FIN NIFTY': 'FINNIFTY',
    'MIDCAP NIFTY': 'MIDCPNIFTY',
    'MIDCAP': 'MIDCPNIFTY',
}

MONTH_MAP = {
    'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
    'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
    '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6,
    '7': 7, '8': 8, '9': 9, '10': 10, '11': 11, '12': 12,
    '01': 1, '02': 2, '03': 3, '04': 4, '05': 5, '06': 6,
    '07': 7, '08': 8, '09': 9,
}

UPSTOX_UNDERLYING_KEYS = {
    'NIFTY': 'NSE_INDEX|Nifty 50',
    'BANKNIFTY': 'NSE_INDEX|Nifty Bank',
    'FINNIFTY': 'NSE_INDEX|Nifty Fin Service',
    'MIDCPNIFTY': 'NSE_INDEX|NIFTY MIDCAP 50',
    'SENSEX': 'BSE_INDEX|SENSEX',
    'BANKEX': 'BSE_INDEX|BANKEX',
}


class InstrumentType(Enum):
    OPTION_CE = 'CE'
    OPTION_PE = 'PE'
    FUTURE = 'FUT'


@dataclass
class ResolvedContract:
    """Represents a resolved tradeable contract"""
    trading_symbol: str
    instrument_key: Optional[str] = None
    instrument_token: Optional[int] = None
    expiry_date: Optional[str] = None
    lot_size: int = 1
    exchange: str = 'NFO'
    segment: str = 'NFO-OPT'
    underlying: str = ''
    strike: Optional[float] = None
    option_type: Optional[str] = None
    instrument_type: str = 'OPT'
    broker: str = ''
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'trading_symbol': self.trading_symbol,
            'instrument_key': self.instrument_key,
            'instrument_token': self.instrument_token,
            'expiry_date': self.expiry_date,
            'lot_size': self.lot_size,
            'exchange': self.exchange,
            'segment': self.segment,
            'underlying': self.underlying,
            'strike': self.strike,
            'option_type': self.option_type,
            'instrument_type': self.instrument_type,
            'broker': self.broker,
        }


@dataclass
class InstrumentCache:
    """Cached instrument data for a broker"""
    instruments: List[Dict[str, Any]] = field(default_factory=list)
    last_refresh: float = 0
    broker: str = ''
    
    def is_valid(self) -> bool:
        return (time.time() - self.last_refresh) < CACHE_TTL_SECONDS and len(self.instruments) > 0


class ExpiryResolver:
    """
    Main expiry resolution service.
    
    Fetches instrument masters from brokers and resolves signals to valid contracts.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._caches: Dict[str, InstrumentCache] = {}
        self._cache_lock = threading.Lock()
        self._initialized = True
        
        logger.info("[EXPIRY_RESOLVER] Service initialized")
    
    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol using alias mapping"""
        symbol = symbol.upper().strip()
        return SYMBOL_ALIASES.get(symbol, symbol)
    
    def _get_today(self) -> datetime:
        """Get current date in IST"""
        if IST:
            return datetime.now(IST).replace(tzinfo=None)
        return datetime.now()
    
    def _parse_expiry_string(self, expiry_str: str) -> Optional[datetime]:
        """
        Parse various expiry string formats into datetime.
        
        Supported formats:
        - MM/DD (e.g., "01/07")
        - MM/DD/YY (e.g., "01/07/26")
        - DD-MMM-YY (e.g., "07-JAN-26")
        - DD-MMM-YYYY (e.g., "07-JAN-2026")
        - YYYY-MM-DD (e.g., "2026-01-07")
        - DDMMMYY (e.g., "07JAN26")
        - Month code only: JAN, FEB, etc.
        """
        if not expiry_str:
            return None
        
        expiry_str = expiry_str.upper().strip()
        today = self._get_today()
        
        try:
            if re.match(r'^\d{1,2}/\d{1,2}$', expiry_str):
                month, day = map(int, expiry_str.split('/'))
                year = today.year
                candidate = datetime(year, month, day)
                if candidate < today:
                    candidate = datetime(year + 1, month, day)
                return candidate
            
            if re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}$', expiry_str):
                parts = expiry_str.split('/')
                month, day = int(parts[0]), int(parts[1])
                year = int(parts[2])
                if year < 100:
                    year += 2000
                return datetime(year, month, day)
            
            if re.match(r'^\d{4}-\d{2}-\d{2}$', expiry_str):
                return datetime.strptime(expiry_str, '%Y-%m-%d')
            
            match = re.match(r'^(\d{1,2})-?(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)-?(\d{2,4})?$', expiry_str)
            if match:
                day = int(match.group(1))
                month = MONTH_MAP[match.group(2)]
                year_str = match.group(3)
                if year_str:
                    year = int(year_str)
                    if year < 100:
                        year += 2000
                else:
                    year = today.year
                candidate = datetime(year, month, day)
                if candidate < today and not year_str:
                    candidate = datetime(year + 1, month, day)
                return candidate
            
            match = re.match(r'^(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2,4})$', expiry_str)
            if match:
                day = int(match.group(1))
                month = MONTH_MAP[match.group(2)]
                year = int(match.group(3))
                if year < 100:
                    year += 2000
                return datetime(year, month, day)
            
            if expiry_str in MONTH_MAP:
                month = MONTH_MAP[expiry_str]
                year = today.year
                if month < today.month:
                    year += 1
                return datetime(year, month, 28)
                
        except (ValueError, KeyError) as e:
            logger.warning(f"[EXPIRY_RESOLVER] Failed to parse expiry '{expiry_str}': {e}")
        
        return None
    
    def _get_upstox_instruments(self, underlying: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch instruments from Upstox option contracts API"""
        cache_key = f"upstox:{underlying}"
        
        with self._cache_lock:
            if cache_key in self._caches and self._caches[cache_key].is_valid() and not force_refresh:
                return self._caches[cache_key].instruments
        
        try:
            from gui_app.database import get_broker_credentials
            creds = get_broker_credentials('upstox')
            access_token = creds.get('access_token') if creds else None
            
            if not access_token:
                logger.warning("[EXPIRY_RESOLVER] Upstox: No access token available")
                return []
            
            underlying_key = UPSTOX_UNDERLYING_KEYS.get(underlying)
            if not underlying_key:
                logger.warning(f"[EXPIRY_RESOLVER] Upstox: Unknown underlying {underlying}")
                return []
            
            import urllib.parse
            encoded_key = urllib.parse.quote(underlying_key)
            url = f"https://api.upstox.com/v2/option/contract?instrument_key={encoded_key}"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"[EXPIRY_RESOLVER] Upstox API error: {response.status_code}")
                return []
            
            data = response.json()
            if data.get('status') != 'success':
                logger.error(f"[EXPIRY_RESOLVER] Upstox API failed: {data}")
                return []
            
            instruments = data.get('data', [])
            logger.info(f"[EXPIRY_RESOLVER] Upstox: Fetched {len(instruments)} contracts for {underlying}")
            
            with self._cache_lock:
                self._caches[cache_key] = InstrumentCache(
                    instruments=instruments,
                    last_refresh=time.time(),
                    broker='upstox'
                )
            
            return instruments
            
        except Exception as e:
            logger.error(f"[EXPIRY_RESOLVER] Upstox fetch error: {e}")
            return []
    
    def _get_zerodha_instruments(self, underlying: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Fetch instruments from Zerodha instrument master"""
        cache_key = "zerodha:all"
        
        with self._cache_lock:
            if cache_key in self._caches and self._caches[cache_key].is_valid() and not force_refresh:
                all_instruments = self._caches[cache_key].instruments
                return [i for i in all_instruments if i.get('name', '').upper() == underlying]
        
        try:
            cache_file = 'data/instruments/zerodha_nfo.json'
            os.makedirs('data/instruments', exist_ok=True)
            
            if os.path.exists(cache_file) and not force_refresh:
                file_time = os.path.getmtime(cache_file)
                if time.time() - file_time < CACHE_TTL_SECONDS:
                    with open(cache_file, 'r') as f:
                        instruments = json.load(f)
                        with self._cache_lock:
                            self._caches[cache_key] = InstrumentCache(
                                instruments=instruments,
                                last_refresh=file_time,
                                broker='zerodha'
                            )
                        return [i for i in instruments if i.get('name', '').upper() == underlying]
            
            url = "https://api.kite.trade/instruments"
            response = requests.get(url, timeout=60)
            
            if response.status_code != 200:
                logger.error(f"[EXPIRY_RESOLVER] Zerodha API error: {response.status_code}")
                return []
            
            import csv
            import io
            
            reader = csv.DictReader(io.StringIO(response.text))
            instruments = []
            
            for row in reader:
                segment = row.get('segment', '')
                if segment in ('NFO-OPT', 'NFO-FUT', 'BFO-OPT', 'BFO-FUT'):
                    instruments.append({
                        'name': row.get('name', ''),
                        'tradingsymbol': row.get('tradingsymbol', ''),
                        'instrument_token': int(row.get('instrument_token', 0)),
                        'lot_size': int(row.get('lot_size', 1)),
                        'segment': segment,
                        'exchange': row.get('exchange', 'NFO'),
                        'expiry': row.get('expiry', ''),
                        'strike': float(row.get('strike', 0)) if row.get('strike') else None,
                        'instrument_type': row.get('instrument_type', ''),
                    })
            
            with open(cache_file, 'w') as f:
                json.dump(instruments, f)
            
            logger.info(f"[EXPIRY_RESOLVER] Zerodha: Fetched {len(instruments)} NFO instruments")
            
            with self._cache_lock:
                self._caches[cache_key] = InstrumentCache(
                    instruments=instruments,
                    last_refresh=time.time(),
                    broker='zerodha'
                )
            
            return [i for i in instruments if i.get('name', '').upper() == underlying]
            
        except Exception as e:
            logger.error(f"[EXPIRY_RESOLVER] Zerodha fetch error: {e}")
            return []
    
    def _filter_options(
        self,
        instruments: List[Dict[str, Any]],
        underlying: str,
        strike: float,
        option_type: str,
        broker: str
    ) -> List[Dict[str, Any]]:
        """Filter instruments to matching option contracts"""
        today = self._get_today()
        matching = []
        
        strike_tolerance = 0.01
        
        for inst in instruments:
            if broker == 'upstox':
                inst_strike = inst.get('strike_price', 0)
                inst_opt_type = inst.get('instrument_type', '')
                inst_expiry_str = inst.get('expiry', '')
            else:
                inst_strike = inst.get('strike', 0)
                inst_opt_type = inst.get('instrument_type', '')
                inst_expiry_str = inst.get('expiry', '')
            
            if not inst_strike or abs(float(inst_strike) - strike) > strike_tolerance:
                continue
            
            if inst_opt_type.upper() != option_type.upper():
                continue
            
            try:
                if broker == 'upstox':
                    expiry_date = datetime.strptime(inst_expiry_str, '%Y-%m-%d')
                else:
                    expiry_date = datetime.strptime(inst_expiry_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                continue
            
            if expiry_date.date() < today.date():
                continue
            
            matching.append({
                **inst,
                '_expiry_date': expiry_date
            })
        
        matching.sort(key=lambda x: x['_expiry_date'])
        return matching
    
    def _filter_futures(
        self,
        instruments: List[Dict[str, Any]],
        underlying: str,
        broker: str
    ) -> List[Dict[str, Any]]:
        """Filter instruments to matching futures contracts"""
        today = self._get_today()
        matching = []
        
        for inst in instruments:
            if broker == 'upstox':
                inst_type = inst.get('instrument_type', '')
            else:
                inst_type = inst.get('instrument_type', '')
            
            if inst_type.upper() != 'FUT':
                continue
            
            inst_expiry_str = inst.get('expiry', '')
            try:
                if broker == 'upstox':
                    expiry_date = datetime.strptime(inst_expiry_str, '%Y-%m-%d')
                else:
                    expiry_date = datetime.strptime(inst_expiry_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                continue
            
            if expiry_date.date() < today.date():
                continue
            
            matching.append({
                **inst,
                '_expiry_date': expiry_date
            })
        
        matching.sort(key=lambda x: x['_expiry_date'])
        return matching
    
    def resolve_option(
        self,
        underlying: str,
        strike: float,
        option_type: str,
        expiry: Optional[str] = None,
        broker: str = 'upstox'
    ) -> Optional[ResolvedContract]:
        """
        Resolve an option signal to a valid contract.
        
        Args:
            underlying: Symbol (NIFTY, BANKNIFTY, etc.)
            strike: Strike price
            option_type: CE or PE
            expiry: Optional expiry string (auto-picks next if None)
            broker: Broker name (upstox or zerodha)
            
        Returns:
            ResolvedContract or None if no match found
        """
        underlying = self._normalize_symbol(underlying)
        option_type = option_type.upper()
        broker = broker.lower()
        
        if broker == 'upstox':
            instruments = self._get_upstox_instruments(underlying)
        elif broker in ('zerodha', 'kite'):
            instruments = self._get_zerodha_instruments(underlying)
        else:
            logger.error(f"[EXPIRY_RESOLVER] Unsupported broker: {broker}")
            return None
        
        if not instruments:
            logger.error(f"[EXPIRY_RESOLVER] No instruments found for {underlying} on {broker}")
            return None
        
        matching = self._filter_options(instruments, underlying, strike, option_type, broker)
        
        if not matching:
            logger.error(f"[EXPIRY_RESOLVER] No matching contract for {underlying} {strike} {option_type}")
            return None
        
        selected = None
        
        if expiry:
            parsed_expiry = self._parse_expiry_string(expiry)
            if parsed_expiry:
                for inst in matching:
                    if inst['_expiry_date'].date() == parsed_expiry.date():
                        selected = inst
                        break
                
                if not selected:
                    logger.warning(f"[EXPIRY_RESOLVER] Specified expiry {expiry} not found, using nearest")
        
        if not selected:
            selected = matching[0]
            if expiry:
                logger.warning(f"[EXPIRY_RESOLVER] Fallback to nearest expiry: {selected.get('expiry')}")
            else:
                logger.info(f"[EXPIRY_RESOLVER] Auto-selected expiry: {selected.get('expiry')}")
        
        if broker == 'upstox':
            return ResolvedContract(
                trading_symbol=selected.get('trading_symbol', f"{underlying}{int(strike)}{option_type}"),
                instrument_key=selected.get('instrument_key'),
                expiry_date=selected.get('expiry'),
                lot_size=selected.get('lot_size', 1),
                exchange='NSE_FO',
                segment='NSE_FO',
                underlying=underlying,
                strike=strike,
                option_type=option_type,
                instrument_type='OPT',
                broker=broker,
            )
        else:
            trading_sym = selected.get('tradingsymbol') or f"{underlying}{int(strike)}{option_type}"
            return ResolvedContract(
                trading_symbol=trading_sym,
                instrument_token=selected.get('instrument_token'),
                expiry_date=selected.get('expiry'),
                lot_size=selected.get('lot_size', 1),
                exchange=selected.get('exchange', 'NFO'),
                segment=selected.get('segment', 'NFO-OPT'),
                underlying=underlying,
                strike=strike,
                option_type=option_type,
                instrument_type='OPT',
                broker=broker,
            )
    
    def resolve_future(
        self,
        underlying: str,
        expiry: Optional[str] = None,
        broker: str = 'upstox'
    ) -> Optional[ResolvedContract]:
        """
        Resolve a futures signal to a valid contract.
        
        Args:
            underlying: Symbol (NIFTY, BANKNIFTY, etc.)
            expiry: Optional expiry/month string (auto-picks nearest if None)
            broker: Broker name (upstox or zerodha)
            
        Returns:
            ResolvedContract or None if no match found
        """
        underlying = self._normalize_symbol(underlying)
        broker = broker.lower()
        
        if broker == 'upstox':
            instruments = self._get_upstox_instruments(underlying)
        elif broker in ('zerodha', 'kite'):
            instruments = self._get_zerodha_instruments(underlying)
        else:
            logger.error(f"[EXPIRY_RESOLVER] Unsupported broker: {broker}")
            return None
        
        if not instruments:
            logger.error(f"[EXPIRY_RESOLVER] No instruments found for {underlying} on {broker}")
            return None
        
        matching = self._filter_futures(instruments, underlying, broker)
        
        if not matching:
            logger.error(f"[EXPIRY_RESOLVER] No matching futures contract for {underlying}")
            return None
        
        selected = None
        
        if expiry:
            parsed_expiry = self._parse_expiry_string(expiry)
            if parsed_expiry:
                for inst in matching:
                    if inst['_expiry_date'].month == parsed_expiry.month and \
                       inst['_expiry_date'].year == parsed_expiry.year:
                        selected = inst
                        break
        
        if not selected:
            selected = matching[0]
            logger.info(f"[EXPIRY_RESOLVER] Auto-selected futures expiry: {selected.get('expiry')}")
        
        if broker == 'upstox':
            return ResolvedContract(
                trading_symbol=selected.get('trading_symbol', f"{underlying}FUT"),
                instrument_key=selected.get('instrument_key'),
                expiry_date=selected.get('expiry'),
                lot_size=selected.get('lot_size', 1),
                exchange='NSE_FO',
                segment='NSE_FO',
                underlying=underlying,
                instrument_type='FUT',
                broker=broker,
            )
        else:
            trading_sym = selected.get('tradingsymbol') or f"{underlying}FUT"
            return ResolvedContract(
                trading_symbol=trading_sym,
                instrument_token=selected.get('instrument_token'),
                expiry_date=selected.get('expiry'),
                lot_size=selected.get('lot_size', 1),
                exchange=selected.get('exchange', 'NFO'),
                segment=selected.get('segment', 'NFO-FUT'),
                underlying=underlying,
                instrument_type='FUT',
                broker=broker,
            )
    
    def resolve(
        self,
        underlying: str,
        instrument_type: str = 'OPT',
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
        expiry: Optional[str] = None,
        broker: str = 'upstox'
    ) -> Optional[ResolvedContract]:
        """
        Unified resolution method for both options and futures.
        
        Args:
            underlying: Symbol (NIFTY, BANKNIFTY, etc.)
            instrument_type: OPT or FUT
            strike: Strike price (required for options)
            option_type: CE or PE (required for options)
            expiry: Optional expiry string
            broker: Broker name
            
        Returns:
            ResolvedContract or None
        """
        if instrument_type.upper() == 'FUT':
            return self.resolve_future(underlying, expiry, broker)
        else:
            if strike is None or option_type is None:
                logger.error("[EXPIRY_RESOLVER] Strike and option_type required for options")
                return None
            return self.resolve_option(underlying, strike, option_type, expiry, broker)
    
    def get_available_expiries(
        self,
        underlying: str,
        broker: str = 'upstox'
    ) -> List[str]:
        """Get all available expiry dates for an underlying"""
        underlying = self._normalize_symbol(underlying)
        broker = broker.lower()
        
        if broker == 'upstox':
            instruments = self._get_upstox_instruments(underlying)
        else:
            instruments = self._get_zerodha_instruments(underlying)
        
        today = self._get_today()
        expiries = set()
        
        for inst in instruments:
            expiry_str = inst.get('expiry', '')
            try:
                expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
                if expiry_date.date() >= today.date():
                    expiries.add(expiry_str)
            except (ValueError, TypeError):
                continue
        
        return sorted(list(expiries))
    
    def refresh_cache(self, broker: str = None, underlying: str = None):
        """Force refresh instrument cache"""
        with self._cache_lock:
            if broker and underlying:
                cache_key = f"{broker.lower()}:{underlying.upper()}"
                if cache_key in self._caches:
                    del self._caches[cache_key]
            elif broker:
                keys_to_remove = [k for k in self._caches if k.startswith(f"{broker.lower()}:")]
                for k in keys_to_remove:
                    del self._caches[k]
            else:
                self._caches.clear()
        
        logger.info(f"[EXPIRY_RESOLVER] Cache refreshed for {broker or 'all'}/{underlying or 'all'}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._cache_lock:
            stats = {}
            for key, cache in self._caches.items():
                stats[key] = {
                    'instruments': len(cache.instruments),
                    'age_seconds': time.time() - cache.last_refresh,
                    'is_valid': cache.is_valid()
                }
            return stats


expiry_resolver = ExpiryResolver()


def resolve_instrument(
    signal: Dict[str, Any],
    broker: str = 'upstox'
) -> Optional[ResolvedContract]:
    """
    Convenience function to resolve a parsed signal to a contract.
    
    Args:
        signal: Parsed signal dict with keys: symbol, strike, opt_type, expiry, asset
        broker: Broker name
        
    Returns:
        ResolvedContract or None
    """
    underlying = signal.get('symbol', '')
    asset_type = signal.get('asset', 'option')
    
    if asset_type == 'future' or signal.get('instrument_type') == 'FUT':
        return expiry_resolver.resolve_future(
            underlying=underlying,
            expiry=signal.get('expiry'),
            broker=broker
        )
    else:
        return expiry_resolver.resolve_option(
            underlying=underlying,
            strike=float(signal.get('strike', 0)),
            option_type=signal.get('opt_type', 'CE'),
            expiry=signal.get('expiry'),
            broker=broker
        )


def get_next_expiry(underlying: str, broker: str = 'upstox') -> Optional[str]:
    """Get the next available expiry date for an underlying"""
    expiries = expiry_resolver.get_available_expiries(underlying, broker)
    return expiries[0] if expiries else None
