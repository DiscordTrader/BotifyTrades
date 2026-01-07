"""
Contract Master Service - Dynamic lot size lookup per broker with caching

This service provides:
1. Dynamic lot size lookup from each broker's instrument master
2. In-memory cache with TTL (default 6 hours)
3. Fallback to hardcoded values if API fails
4. Support for index options, stock options, and futures
"""

import os
import json
import time
import threading
from typing import Dict, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

CACHE_TTL_SECONDS = int(os.getenv('CONTRACT_TTL_SECONDS', 6 * 60 * 60))

FALLBACK_LOT_SIZES = {
    'NIFTY': 25,
    'BANKNIFTY': 15,
    'FINNIFTY': 25,
    'MIDCPNIFTY': 50,
    'SENSEX': 10,
    'BANKEX': 15,
    'NIFTYNXT50': 25,
}

@dataclass
class Contract:
    """Represents a tradeable contract"""
    tradingsymbol: str
    exchange: str
    expiry: Optional[str]
    lot_size: int
    instrument_type: str
    strike: Optional[float] = None
    option_type: Optional[str] = None
    underlying: Optional[str] = None


class ContractMaster:
    """
    Unified contract master service for dynamic lot size lookup across brokers.
    
    Usage:
        master = ContractMaster()
        lot_size = master.get_lot_size('upstox', 'NIFTY')
        contract = master.get_option_contract('upstox', 'NIFTY', 26300, 'PE')
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
        
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_lock = threading.Lock()
        self._initialized = True
        
        print("[CONTRACT_MASTER] Service initialized")
    
    def get_lot_size(self, broker: str, underlying: str, 
                     instrument_type: str = 'OPT',
                     strike: Optional[float] = None,
                     option_type: Optional[str] = None,
                     expiry: Optional[str] = None) -> int:
        """
        Get lot size for a given underlying from the specified broker.
        
        Args:
            broker: Broker name (upstox, zerodha, dhan)
            underlying: Symbol like NIFTY, BANKNIFTY, RELIANCE
            instrument_type: OPT for options, FUT for futures
            strike: Strike price (for options)
            option_type: CE or PE (for options)
            expiry: Expiry date (optional)
            
        Returns:
            Lot size as integer
        """
        broker = broker.lower()
        underlying = underlying.upper()
        
        cache_key = f"{broker}:{underlying}"
        
        with self._cache_lock:
            if cache_key in self._cache:
                cache_time = self._cache_timestamps.get(cache_key, 0)
                if time.time() - cache_time < CACHE_TTL_SECONDS:
                    cached = self._cache[cache_key]
                    return cached.get('lot_size', FALLBACK_LOT_SIZES.get(underlying, 1))
        
        lot_size = self._fetch_lot_size(broker, underlying, instrument_type, strike, option_type, expiry)
        
        with self._cache_lock:
            self._cache[cache_key] = {'lot_size': lot_size, 'underlying': underlying}
            self._cache_timestamps[cache_key] = time.time()
        
        return lot_size
    
    def _fetch_lot_size(self, broker: str, underlying: str,
                        instrument_type: str = 'OPT',
                        strike: Optional[float] = None,
                        option_type: Optional[str] = None,
                        expiry: Optional[str] = None) -> int:
        """Fetch lot size from broker-specific source"""
        
        try:
            if broker == 'upstox':
                return self._fetch_upstox_lot_size(underlying, instrument_type, strike, option_type, expiry)
            elif broker == 'zerodha':
                return self._fetch_zerodha_lot_size(underlying, instrument_type)
            elif broker in ('dhan', 'dhanq', 'dhanhq'):
                return self._fetch_dhan_lot_size(underlying, instrument_type)
            else:
                print(f"[CONTRACT_MASTER] Unknown broker: {broker}, using fallback")
                return FALLBACK_LOT_SIZES.get(underlying, 1)
        except Exception as e:
            print(f"[CONTRACT_MASTER] Error fetching lot size for {broker}/{underlying}: {e}")
            return FALLBACK_LOT_SIZES.get(underlying, 1)
    
    def _fetch_upstox_lot_size(self, underlying: str, instrument_type: str,
                                strike: Optional[float], option_type: Optional[str],
                                expiry: Optional[str]) -> int:
        """Fetch lot size from Upstox option contracts API"""
        import requests
        
        try:
            underlying_keys = {
                'NIFTY': 'NSE_INDEX|Nifty 50',
                'BANKNIFTY': 'NSE_INDEX|Nifty Bank',
                'FINNIFTY': 'NSE_INDEX|Nifty Fin Service',
                'MIDCPNIFTY': 'NSE_INDEX|NIFTY MIDCAP 50',
                'SENSEX': 'BSE_INDEX|SENSEX',
                'BANKEX': 'BSE_INDEX|BANKEX',
            }
            
            underlying_key = underlying_keys.get(underlying)
            if not underlying_key:
                print(f"[CONTRACT_MASTER] Upstox: Unknown index {underlying}, using fallback")
                return FALLBACK_LOT_SIZES.get(underlying, 1)
            
            from gui_app.database import get_broker_credentials
            creds = get_broker_credentials('upstox')
            access_token = creds.get('access_token') if creds else None
            
            if not access_token:
                print("[CONTRACT_MASTER] Upstox: No access token, using fallback")
                return FALLBACK_LOT_SIZES.get(underlying, 1)
            
            import urllib.parse
            encoded_key = urllib.parse.quote(underlying_key)
            url = f"https://api.upstox.com/v2/option/contract?instrument_key={encoded_key}"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    contracts = data.get('data', [])
                    if contracts and len(contracts) > 0:
                        first_contract = contracts[0]
                        lot_size = first_contract.get('lot_size', FALLBACK_LOT_SIZES.get(underlying, 1))
                        print(f"[CONTRACT_MASTER] Upstox: {underlying} lot_size={lot_size}")
                        return lot_size
            
            print(f"[CONTRACT_MASTER] Upstox: Could not fetch contracts for {underlying}")
            return FALLBACK_LOT_SIZES.get(underlying, 1)
            
        except Exception as e:
            print(f"[CONTRACT_MASTER] Upstox error: {e}")
            return FALLBACK_LOT_SIZES.get(underlying, 1)
    
    def _fetch_zerodha_lot_size(self, underlying: str, instrument_type: str) -> int:
        """Fetch lot size from Zerodha instrument master"""
        import requests
        
        try:
            cache_file = 'data/contract_master/zerodha_instruments.json'
            
            if os.path.exists(cache_file):
                file_time = os.path.getmtime(cache_file)
                if time.time() - file_time < CACHE_TTL_SECONDS:
                    with open(cache_file, 'r') as f:
                        instruments = json.load(f)
                        for inst in instruments:
                            if inst.get('name', '').upper() == underlying:
                                return inst.get('lot_size', FALLBACK_LOT_SIZES.get(underlying, 1))
            
            url = "https://api.kite.trade/instruments"
            response = requests.get(url, timeout=30)
            
            if response.status_code == 200:
                import csv
                import io
                
                reader = csv.DictReader(io.StringIO(response.text))
                instruments = []
                
                for row in reader:
                    if row.get('segment') == 'NFO-OPT' or row.get('segment') == 'NFO-FUT':
                        if row.get('name', '').upper() == underlying:
                            lot_size = int(row.get('lot_size', 1))
                            
                            instruments.append({
                                'name': row.get('name'),
                                'tradingsymbol': row.get('tradingsymbol'),
                                'lot_size': lot_size,
                                'segment': row.get('segment')
                            })
                            
                            os.makedirs('data/contract_master', exist_ok=True)
                            with open(cache_file, 'w') as f:
                                json.dump(instruments[:100], f)
                            
                            print(f"[CONTRACT_MASTER] Zerodha: {underlying} lot_size={lot_size}")
                            return lot_size
            
            print(f"[CONTRACT_MASTER] Zerodha: Could not find {underlying} in instruments")
            return FALLBACK_LOT_SIZES.get(underlying, 1)
            
        except Exception as e:
            print(f"[CONTRACT_MASTER] Zerodha error: {e}")
            return FALLBACK_LOT_SIZES.get(underlying, 1)
    
    def _fetch_dhan_lot_size(self, underlying: str, instrument_type: str) -> int:
        """Fetch lot size from Dhan scrip master"""
        try:
            cache_file = 'data/contract_master/dhan_instruments.json'
            
            if os.path.exists(cache_file):
                file_time = os.path.getmtime(cache_file)
                if time.time() - file_time < CACHE_TTL_SECONDS:
                    with open(cache_file, 'r') as f:
                        instruments = json.load(f)
                        for inst in instruments:
                            if inst.get('underlying', '').upper() == underlying:
                                return inst.get('lot_size', FALLBACK_LOT_SIZES.get(underlying, 1))
            
            print(f"[CONTRACT_MASTER] Dhan: Using fallback for {underlying}")
            return FALLBACK_LOT_SIZES.get(underlying, 1)
            
        except Exception as e:
            print(f"[CONTRACT_MASTER] Dhan error: {e}")
            return FALLBACK_LOT_SIZES.get(underlying, 1)
    
    def get_option_contract(self, broker: str, underlying: str, 
                           strike: float, option_type: str,
                           expiry: Optional[str] = None) -> Optional[Contract]:
        """
        Get full contract details for an option.
        
        Args:
            broker: Broker name
            underlying: Symbol like NIFTY
            strike: Strike price
            option_type: CE or PE
            expiry: Expiry date (optional, uses nearest weekly for index)
            
        Returns:
            Contract object or None if not found
        """
        lot_size = self.get_lot_size(broker, underlying, 'OPT', strike, option_type, expiry)
        
        return Contract(
            tradingsymbol=f"{underlying}{int(strike)}{option_type}",
            exchange='NFO',
            expiry=expiry,
            lot_size=lot_size,
            instrument_type='OPT',
            strike=strike,
            option_type=option_type,
            underlying=underlying
        )
    
    def get_future_contract(self, broker: str, underlying: str,
                           expiry: Optional[str] = None) -> Optional[Contract]:
        """
        Get full contract details for a future.
        
        Args:
            broker: Broker name
            underlying: Symbol like NIFTY
            expiry: Expiry date (optional, uses nearest monthly)
            
        Returns:
            Contract object or None if not found
        """
        lot_size = self.get_lot_size(broker, underlying, 'FUT')
        
        return Contract(
            tradingsymbol=f"{underlying}FUT",
            exchange='NFO',
            expiry=expiry,
            lot_size=lot_size,
            instrument_type='FUT',
            underlying=underlying
        )
    
    def refresh(self, broker: str = None) -> None:
        """
        Force refresh the contract master cache.
        
        Args:
            broker: Specific broker to refresh, or None for all
        """
        with self._cache_lock:
            if broker:
                keys_to_remove = [k for k in self._cache if k.startswith(f"{broker.lower()}:")]
                for k in keys_to_remove:
                    del self._cache[k]
                    if k in self._cache_timestamps:
                        del self._cache_timestamps[k]
                print(f"[CONTRACT_MASTER] Cache cleared for broker: {broker}")
            else:
                self._cache.clear()
                self._cache_timestamps.clear()
                print("[CONTRACT_MASTER] Cache cleared for all brokers")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._cache_lock:
            return {
                'entries': len(self._cache),
                'ttl_seconds': CACHE_TTL_SECONDS,
                'brokers': list(set(k.split(':')[0] for k in self._cache.keys()))
            }


contract_master = ContractMaster()


def get_lot_size(broker: str, underlying: str, **kwargs) -> int:
    """Convenience function to get lot size"""
    return contract_master.get_lot_size(broker, underlying, **kwargs)


def get_option_contract(broker: str, underlying: str, strike: float, 
                       option_type: str, expiry: Optional[str] = None) -> Optional[Contract]:
    """Convenience function to get option contract"""
    return contract_master.get_option_contract(broker, underlying, strike, option_type, expiry)
