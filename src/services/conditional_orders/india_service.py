"""
India Market Conditional Order Service

Handles conditional orders for Indian markets (NSE, BSE, MCX)
Price monitoring fallback chain: Upstox/Zerodha/DhanQ → Cross-Broker Hub
"""

import sys
import asyncio
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

from .base import (
    BaseConditionalOrderService,
    PriceMonitor,
    BrokerPriceMonitor,
    RateLimitTracker,
)

try:
    import pytz
    IST = pytz.timezone('Asia/Kolkata')
except ImportError:
    IST = None


class IndiaPriceMonitor(PriceMonitor):
    """
    Price monitor for Indian markets (NSE options).
    Uses Upstox/Zerodha API with proper instrument key lookup.
    """
    
    def __init__(self, symbol: str, strike: float, opt_type: str, callback: Callable[[str, float], None], 
                 broker_instance: Any = None, expiry: str = None, broker_name: str = 'upstox'):
        super().__init__(symbol, callback)
        self.strike = strike
        self.opt_type = opt_type
        self.broker_instance = broker_instance
        self.broker_name = broker_name
        self.expiry = expiry
        self.poll_interval = 2
        self._error_count = 0
        self._max_errors = 10
        self._instrument_key = None
        self._instrument_key_lookup_done = False
        self._poll_count = 0
    
    def _get_underlying_key(self) -> str:
        """Get Upstox underlying key for NSE indices."""
        index_map = {
            'NIFTY': 'NSE_INDEX|Nifty 50',
            'BANKNIFTY': 'NSE_INDEX|Nifty Bank',
            'FINNIFTY': 'NSE_INDEX|Nifty Fin Service',
            'MIDCPNIFTY': 'NSE_INDEX|NIFTY MID SELECT',
        }
        return index_map.get(self.symbol.upper(), f'NSE_EQ|{self.symbol}')
    
    async def _lookup_instrument_key(self) -> Optional[str]:
        """Look up the Upstox instrument key for this option contract."""
        if not self.broker_instance:
            return None
        
        try:
            # Try Upstox _lookup_instrument_key method first
            if hasattr(self.broker_instance, '_lookup_instrument_key'):
                result = await self.broker_instance._lookup_instrument_key(
                    self.symbol,
                    float(self.strike) if self.strike else 0,
                    self.opt_type[0].upper() if self.opt_type else 'C',
                    self.expiry
                )
                # Result can be tuple (key, lot_size) or just key
                if isinstance(result, tuple):
                    key = result[0]
                else:
                    key = result
                if key:
                    sys.stderr.write(f"[INDIA] ✓ Found instrument key for {self.symbol} {self.strike}{self.opt_type}: {key}\n")
                    sys.stderr.flush()
                    return key
            
            # Fallback to get_option_instrument_key
            elif hasattr(self.broker_instance, 'get_option_instrument_key'):
                key = await self.broker_instance.get_option_instrument_key(
                    self.symbol,
                    self.strike,
                    self.opt_type,
                    self.expiry
                )
                if key:
                    sys.stderr.write(f"[INDIA] ✓ Found instrument key for {self.symbol} {self.strike}{self.opt_type}: {key}\n")
                    sys.stderr.flush()
                    return key
        except Exception as e:
            sys.stderr.write(f"[INDIA] Instrument lookup error: {e}\n")
            sys.stderr.flush()
        
        return None
    
    async def start(self):
        """Start monitoring Indian market price."""
        self.is_running = True
        sys.stderr.write(f"[INDIA] Starting monitor for {self.symbol} {self.strike}{self.opt_type} exp={self.expiry} (broker: {self.broker_name})\n")
        sys.stderr.flush()
        
        if not self._instrument_key_lookup_done and self.broker_instance:
            self._instrument_key = await self._lookup_instrument_key()
            self._instrument_key_lookup_done = True
            
            if not self._instrument_key:
                sys.stderr.write(f"[INDIA] Warning: No instrument key found, using fallback\n")
                sys.stderr.flush()
        
        while self.is_running:
            try:
                price = await self._fetch_price()
                self._poll_count += 1
                
                if self._poll_count <= 3 or self._poll_count % 30 == 0:
                    sys.stderr.write(f"[INDIA] Poll #{self._poll_count} {self.symbol}: ₹{price}\n")
                    sys.stderr.flush()
                
                if price and price != self.last_price:
                    self.last_price = price
                    self._error_count = 0
                    await self.callback(self.symbol, float(price))
                elif not price:
                    self._error_count += 1
                    if self._error_count >= self._max_errors:
                        sys.stderr.write(f"[INDIA] Too many errors, stopping monitor\n")
                        sys.stderr.flush()
                        self.is_running = False
                        return False
            except Exception as e:
                sys.stderr.write(f"[INDIA] Monitor error: {e}\n")
                sys.stderr.flush()
                self._error_count += 1
            
            await asyncio.sleep(self.poll_interval)
    
    async def _fetch_price(self) -> Optional[float]:
        """Fetch price from broker or cross-broker hub fallback."""
        if self.broker_instance and self._instrument_key:
            return await self._fetch_from_broker()
        return None
    
    async def _fetch_from_broker(self) -> Optional[float]:
        """Fetch price from Upstox/Zerodha API."""
        try:
            if self.broker_name.lower() == 'upstox':
                if hasattr(self.broker_instance, 'get_ltp_v3'):
                    ltp = await self.broker_instance.get_ltp_v3(self._instrument_key)
                    return float(ltp) if ltp else None
                elif hasattr(self.broker_instance, 'get_quote'):
                    quote = await self.broker_instance.get_quote(self._instrument_key)
                    if quote:
                        for key, data in quote.items():
                            if hasattr(data, 'last_price'):
                                return float(data.last_price)
                            elif isinstance(data, dict) and 'last_price' in data:
                                return float(data['last_price'])
            
            elif self.broker_name.lower() == 'zerodha':
                if hasattr(self.broker_instance, 'ltp'):
                    loop = asyncio.get_event_loop()
                    ltp_data = await loop.run_in_executor(
                        None, 
                        lambda: self.broker_instance.ltp([self._instrument_key])
                    )
                    if ltp_data and self._instrument_key in ltp_data:
                        return float(ltp_data[self._instrument_key]['last_price'])
            
            elif self.broker_name.lower() == 'dhanq':
                if hasattr(self.broker_instance, 'get_ltp'):
                    loop = asyncio.get_event_loop()
                    ltp = await loop.run_in_executor(
                        None,
                        lambda: self.broker_instance.get_ltp(self._instrument_key)
                    )
                    return float(ltp) if ltp else None
        
        except Exception as e:
            sys.stderr.write(f"[INDIA] Broker fetch error: {e}\n")
            sys.stderr.flush()
        
        return None
    


class IndiaConditionalOrderService(BaseConditionalOrderService):
    """
    Conditional order service for Indian markets.
    
    Supports brokers: Upstox, Zerodha, DhanQ
    Fallback chain: Channel Broker → Cross-Broker Hub
    """
    
    MARKET = 'INDIA'
    
    def _init_rate_limiters(self):
        """Initialize rate limiters for India brokers."""
        self.rate_limiters = {
            'upstox': RateLimitTracker('upstox', 250),
            'zerodha': RateLimitTracker('zerodha', 180),
            'dhanq': RateLimitTracker('dhanq', 60),
        }
    
    def get_supported_brokers(self) -> List[str]:
        """Return list of India market brokers."""
        return ['upstox', 'zerodha', 'dhanq']
    
    async def build_price_monitor(self, order: Dict, broker_instance: Any, broker_name: str) -> Optional[PriceMonitor]:
        """
        Build price monitor for India market orders.
        
        Fallback chain:
        1. Channel-configured broker (Upstox/Zerodha/DhanQ) - real-time
        2. Cross-broker hub fallback
        """
        symbol = order['symbol']
        strike = order.get('strike', 0)
        opt_type = order.get('opt_type', 'C')
        expiry = order.get('expiry')
        
        effective_broker = broker_instance
        effective_broker_name = broker_name.lower() if broker_name else None
        
        if not effective_broker:
            for b_name in self.get_supported_brokers():
                if b_name in self.broker_instances:
                    effective_broker = self.broker_instances[b_name]
                    effective_broker_name = b_name
                    self._log(f"Using registered broker: {b_name}")
                    break
        
        async def price_callback(sym: str, price: float):
            await self._on_price_update(order['id'], sym, price)
        
        if effective_broker:
            data_source = effective_broker_name
            self._log(f"Using {effective_broker_name} for {symbol} {strike}{opt_type} (real-time)")
            monitor = IndiaPriceMonitor(
                symbol,
                strike,
                opt_type,
                price_callback,
                effective_broker,
                expiry,
                effective_broker_name
            )
        else:
            data_source = 'cross_hub'
            self._log(f"No India broker connected for {symbol}, using cross-broker hub fallback")
            monitor = None
            for bname, binst in self.broker_instances.items():
                if binst and hasattr(binst, 'get_quote'):
                    data_source = bname.lower()
                    self._log(f"Using {bname} for {symbol} (fallback broker REST)")
                    monitor = BrokerPriceMonitor(symbol, price_callback, bname, binst)
                    break
            if not monitor:
                self._log(f"ERROR: No price source for {symbol} — no brokers connected")
                return None
        
        from gui_app.database import update_conditional_order_status
        status = 'ACTIVE_MONITORING' if effective_broker else 'FALLBACK_MONITORING'
        update_conditional_order_status(
            order['id'],
            status,
            data_source_active=data_source
        )
        
        return monitor
