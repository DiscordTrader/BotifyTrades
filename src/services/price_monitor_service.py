"""
Price Monitor Service
=====================
Real-time price monitoring for signal routing positions with API rate limiting.

Features:
- Activates on BTO (position created in ledger)
- Deactivates on close (position fully exited)
- Uses RateLimitManager to respect broker API limits
- Updates PositionLedger with current prices
- Priority-based data source fallback (Webull → Alpaca → Finnhub)
"""

import asyncio
import threading
import time
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any, Set
from dataclasses import dataclass, field

from src.services.rate_limit_manager import RateLimitManager, BROKER_LIMITS
from src.services.position_ledger import get_position_ledger, LedgerPosition


@dataclass
class MonitoredPosition:
    """Position being actively monitored for price updates."""
    position_id: int
    option_key: str
    symbol: str
    expiry: str
    strike: float
    option_type: str
    channel_id: str
    broker_id: str
    last_price: float = 0.0
    last_update: float = 0.0
    failed_attempts: int = 0
    preferred_data_source: str = "webull"


class PriceMonitorService:
    """
    Real-time price monitoring for positions in the ledger.
    
    Uses the RateLimitManager to efficiently fetch prices across multiple
    data sources while respecting API rate limits.
    """
    
    _instance: Optional['PriceMonitorService'] = None
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
        
        self.rate_limiter = RateLimitManager()
        self.ledger = get_position_ledger()
        
        self._positions: Dict[int, MonitoredPosition] = {}
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._positions_lock = threading.Lock()
        
        self._webull_client = None
        self._alpaca_broker = None
        self._finnhub_key = os.getenv('FINNHUB_API_KEY', '')
        
        self._default_interval = 5.0
        self._max_failed_attempts = 5
        self._price_stale_threshold = 120
        
        self._initialized = True
        print("[PRICE_MONITOR] ✓ PriceMonitorService initialized")
    
    def set_webull_client(self, client):
        """Set the Webull client for price fetching."""
        self._webull_client = client
        print("[PRICE_MONITOR] ✓ Webull client registered")
    
    def set_alpaca_broker(self, broker):
        """Set the Alpaca broker for price fetching."""
        self._alpaca_broker = broker
        print("[PRICE_MONITOR] ✓ Alpaca broker registered")
    
    def register_position(self, position: LedgerPosition) -> bool:
        """Register a position for price monitoring."""
        if not position.id:
            print(f"[PRICE_MONITOR] Cannot register position without ID")
            return False
        
        with self._positions_lock:
            if position.id in self._positions:
                return True
            
            monitored = MonitoredPosition(
                position_id=position.id,
                option_key=position.option_key,
                symbol=position.symbol,
                expiry=position.expiry,
                strike=position.strike,
                option_type=position.option_type,
                channel_id=position.channel_id,
                broker_id=position.broker_id,
                last_price=position.entry_price,
                last_update=time.time()
            )
            
            self._positions[position.id] = monitored
            print(f"[PRICE_MONITOR] ✓ Registered: {position.option_key} (ID: {position.id})")
            return True
    
    def unregister_position(self, position_id: int) -> bool:
        """Unregister a position from price monitoring."""
        with self._positions_lock:
            if position_id in self._positions:
                pos = self._positions.pop(position_id)
                print(f"[PRICE_MONITOR] ✓ Unregistered: {pos.option_key} (ID: {position_id})")
                return True
            return False
    
    def get_monitored_count(self) -> int:
        """Get the number of positions being monitored."""
        with self._positions_lock:
            return len(self._positions)
    
    def get_monitored_positions(self) -> List[MonitoredPosition]:
        """Get a copy of all monitored positions."""
        with self._positions_lock:
            return list(self._positions.values())
    
    async def _fetch_option_price_webull(
        self, 
        symbol: str, 
        strike: float, 
        expiry: str, 
        option_type: str
    ) -> Optional[float]:
        """Fetch option price from Webull."""
        if not self._webull_client:
            return None
        
        can_request, wait_time = self.rate_limiter.can_make_request('webull')
        if not can_request:
            return None
        
        try:
            wb = self._webull_client
            
            try:
                exp_date = datetime.strptime(expiry, "%Y-%m-%d")
            except ValueError:
                try:
                    exp_date = datetime.strptime(expiry, "%m/%d/%Y")
                except ValueError:
                    exp_date = datetime.strptime(expiry, "%m/%d")
                    exp_date = exp_date.replace(year=datetime.now().year)
            
            iso_exp = exp_date.strftime("%Y-%m-%d")
            opt_type = 'call' if option_type.upper() == 'C' else 'put'
            
            def fetch_options():
                return wb.get_options(stock=symbol, direction=opt_type, expireDate=iso_exp)
            
            options = await asyncio.get_event_loop().run_in_executor(None, fetch_options)
            self.rate_limiter.record_request('webull')
            
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
            
            can_request, _ = self.rate_limiter.can_make_request('webull')
            if not can_request:
                last = float(best_match.get('close', 0) or best_match.get('latestPrice', 0) or 0)
                return last if last > 0 else None
            
            def fetch_quote():
                return wb.get_option_quote(stock=symbol, optionId=str(option_id))
            
            quote = await asyncio.get_event_loop().run_in_executor(None, fetch_quote)
            self.rate_limiter.record_request('webull')
            
            if not quote:
                return None
            
            if 'data' in quote and isinstance(quote.get('data'), list):
                for opt in quote.get('data', []):
                    if opt.get('tickerId') == option_id:
                        askList = opt.get('askList', [])
                        bidList = opt.get('bidList', [])
                        
                        ask = float(askList[0].get('price', 0)) if askList else 0
                        bid = float(bidList[0].get('price', 0)) if bidList else 0
                        last = float(opt.get('close', 0) or opt.get('latestPrice', 0) or 0)
                        
                        if bid > 0 and ask > 0:
                            return (bid + ask) / 2
                        elif last > 0:
                            return last
            else:
                ask = float(quote.get('askPrice', 0) or 0)
                bid = float(quote.get('bidPrice', 0) or 0)
                last = float(quote.get('lastPrice', 0) or quote.get('close', 0) or 0)
                
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                elif last > 0:
                    return last
            
            return None
            
        except Exception as e:
            print(f"[PRICE_MONITOR] Webull error for {symbol}: {e}")
            return None
    
    async def _fetch_option_price_alpaca(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str
    ) -> Optional[float]:
        """Fetch option price from Alpaca."""
        if not self._alpaca_broker:
            return None
        
        can_request, _ = self.rate_limiter.can_make_request('alpaca')
        if not can_request:
            return None
        
        try:
            if hasattr(self._alpaca_broker, 'get_option_quote'):
                quote = await self._alpaca_broker.get_option_quote(
                    symbol, strike, expiry, option_type
                )
                self.rate_limiter.record_request('alpaca')
                
                if quote:
                    bid = quote.get('bid', 0)
                    ask = quote.get('ask', 0)
                    last = quote.get('last', 0)
                    
                    if bid > 0 and ask > 0:
                        return (bid + ask) / 2
                    elif last > 0:
                        return last
            
            return None
            
        except Exception as e:
            print(f"[PRICE_MONITOR] Alpaca error for {symbol}: {e}")
            return None
    
    async def _fetch_price(self, pos: MonitoredPosition) -> Optional[float]:
        """Fetch price using fallback data sources."""
        sources = [
            ('webull', self._fetch_option_price_webull),
            ('alpaca', self._fetch_option_price_alpaca),
        ]
        
        for source_name, fetch_func in sources:
            try:
                price = await fetch_func(
                    pos.symbol, 
                    pos.strike, 
                    pos.expiry, 
                    pos.option_type
                )
                if price and price > 0:
                    pos.preferred_data_source = source_name
                    return price
            except Exception as e:
                continue
        
        return None
    
    async def get_option_price(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str
    ) -> Optional[float]:
        """
        Public method to fetch option price immediately.
        
        Used for instant price fetch on position creation (no poll delay).
        Tries Webull first, then Alpaca fallback.
        """
        for source_name, fetch_func in [
            ('webull', self._fetch_option_price_webull),
            ('alpaca', self._fetch_option_price_alpaca),
        ]:
            try:
                price = await fetch_func(symbol, strike, expiry, option_type)
                if price and price > 0:
                    return price
            except Exception:
                continue
        
        return None
    
    async def _update_position_prices(self):
        """Update prices for all monitored positions."""
        with self._positions_lock:
            positions = list(self._positions.values())
        
        if not positions:
            return
        
        now = time.time()
        
        for pos in positions:
            if pos.failed_attempts >= self._max_failed_attempts:
                continue
            
            try:
                price = await self._fetch_price(pos)
                
                if price and price > 0:
                    staleness = int(now - pos.last_update) if pos.last_update > 0 else 0
                    
                    self.ledger.update_price(
                        pos.position_id,
                        price,
                        staleness_sec=0
                    )
                    
                    pos.last_price = price
                    pos.last_update = now
                    pos.failed_attempts = 0
                else:
                    pos.failed_attempts += 1
                    
                    if pos.last_price > 0:
                        staleness = int(now - pos.last_update)
                        if staleness > 0:
                            self.ledger.update_price(
                                pos.position_id,
                                pos.last_price,
                                staleness_sec=staleness
                            )
            
            except Exception as e:
                print(f"[PRICE_MONITOR] Error updating {pos.option_key}: {e}")
                pos.failed_attempts += 1
            
            await asyncio.sleep(0.5)
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        print("[PRICE_MONITOR] ✓ Price monitor loop started")
        
        while self._running:
            try:
                await self._update_position_prices()
                
                count = self.get_monitored_count()
                if count > 0:
                    interval = max(self._default_interval, count * 0.5)
                else:
                    interval = 30.0
                
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[PRICE_MONITOR] Monitor loop error: {e}")
                await asyncio.sleep(10)
        
        print("[PRICE_MONITOR] Price monitor loop stopped")
    
    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Start the price monitoring service."""
        if self._running:
            return
        
        self._loop = loop or asyncio.get_event_loop()
        self._running = True
        
        self._monitor_task = self._loop.create_task(self._monitor_loop())
        print("[PRICE_MONITOR] ✓ Service started")
    
    def stop(self):
        """Stop the price monitoring service."""
        self._running = False
        
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        
        print("[PRICE_MONITOR] Service stopped")
    
    def sync_from_ledger(self):
        """Sync monitored positions from the ledger (for startup reconciliation)."""
        open_positions = self.ledger.get_open_positions()
        
        synced = 0
        for pos in open_positions:
            if self.register_position(pos):
                synced += 1
        
        print(f"[PRICE_MONITOR] ✓ Synced {synced} positions from ledger")
        return synced


_price_monitor_instance: Optional[PriceMonitorService] = None


def get_price_monitor() -> PriceMonitorService:
    """Get the singleton PriceMonitorService instance."""
    global _price_monitor_instance
    if _price_monitor_instance is None:
        _price_monitor_instance = PriceMonitorService()
    return _price_monitor_instance
