"""
Price Monitor Service
=====================
Real-time price monitoring for signal routing positions with API rate limiting.

Features:
- Activates on BTO (position created in ledger)
- Deactivates on close (position fully exited)
- Uses RateLimitManager to respect broker API limits
- Updates PositionLedger with current prices
- Broker-aware price fetching with dynamic fallback chain
- Adaptive polling based on % distance to stop (1s near, 5s mid, 10s far)
"""

import asyncio
import threading
import time
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any, Set, Callable
from dataclasses import dataclass, field

from src.services.rate_limit_manager import RateLimitManager, BROKER_LIMITS
from src.services.position_ledger import get_position_ledger, LedgerPosition
from src.services.broker_capabilities import (
    get_fallback_brokers,
    can_fetch_quotes,
    get_rate_limit_key,
    AssetType,
    BrokerCapability
)


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
    entry_price: float = 0.0
    early_stop_price: Optional[float] = None
    asset_type: str = "option"


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
        
        self._brokers: Dict[str, Any] = {}
        self._connected_broker_ids: List[str] = []
        
        self._default_interval = 5.0
        self._near_stop_interval = 1.0
        self._mid_buffer_interval = 3.0
        self._far_buffer_interval = 5.0
        self._max_failed_attempts = 5
        self._price_stale_threshold = 120
        
        self._streaming_client = None
        self._option_id_cache: Dict[str, int] = {}

        self._initialized = True
        print("[PRICE_MONITOR] ✓ PriceMonitorService initialized")

    def set_streaming_client(self, client):
        self._streaming_client = client
        print("[PRICE_MONITOR] ✓ Streaming client registered for auto-subscribe")
    
    def set_webull_client(self, client):
        """Set the Webull client for price fetching."""
        self._webull_client = client
        self.register_broker('WEBULL', client)
        print("[PRICE_MONITOR] ✓ Webull client registered")
    
    def set_alpaca_broker(self, broker):
        """Set the Alpaca broker for price fetching."""
        self._alpaca_broker = broker
        self.register_broker('ALPACA', broker)
        print("[PRICE_MONITOR] ✓ Alpaca broker registered")
    
    def register_broker(self, broker_id: str, broker_instance: Any):
        """Register a broker for price fetching."""
        self._brokers[broker_id.upper()] = broker_instance
        if broker_id.upper() not in self._connected_broker_ids:
            self._connected_broker_ids.append(broker_id.upper())
        print(f"[PRICE_MONITOR] ✓ Broker registered: {broker_id}")
    
    def get_connected_brokers(self) -> List[str]:
        """Get list of connected broker IDs."""
        return self._connected_broker_ids.copy()
    
    def register_position(self, position: LedgerPosition) -> bool:
        """Register a position for price monitoring."""
        if not position.id:
            print(f"[PRICE_MONITOR] Cannot register position without ID")
            return False
        
        with self._positions_lock:
            if position.id in self._positions:
                return True
            
            asset_type = "option" if position.strike and position.expiry else "stock"
            
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
                last_update=time.time(),
                entry_price=position.entry_price,
                asset_type=asset_type
            )
            
            self._positions[position.id] = monitored
            print(f"[PRICE_MONITOR] ✓ Registered: {position.option_key} (ID: {position.id}, broker: {position.broker_id})")
            return True
    
    def update_early_stop(self, position_id: int, early_stop_price: float):
        """Update the early trailing stop price for adaptive polling."""
        with self._positions_lock:
            if position_id in self._positions:
                self._positions[position_id].early_stop_price = early_stop_price
    
    def get_adaptive_interval(self, pos: MonitoredPosition) -> float:
        """
        Calculate adaptive polling interval based on % distance to early stop.
        
        Near stop (<2% buffer): 1 second
        Mid buffer (2-5%): 3 seconds  
        Far buffer (>5%): 5 seconds
        """
        if not pos.early_stop_price or pos.early_stop_price <= 0:
            return self._default_interval
        
        if pos.last_price <= 0 or pos.entry_price <= 0:
            return self._default_interval
        
        pct_above_stop = ((pos.last_price - pos.early_stop_price) / pos.entry_price) * 100
        
        if pct_above_stop < 2.0:
            return self._near_stop_interval
        elif pct_above_stop < 5.0:
            return self._mid_buffer_interval
        else:
            return self._far_buffer_interval
    
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
        """Fetch option price from Webull. Uses cached option_id and auto-subscribes for streaming."""
        if not self._webull_client:
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
            side = 'call' if option_type.upper() == 'C' else 'put'
            
            cache_key = f"{symbol.upper()}_{strike:.2f}_{iso_exp}_{option_type.upper()}"
            option_id = self._option_id_cache.get(cache_key)
            
            if not option_id:
                try:
                    from src.services.webull_data_hub import get_webull_data_hub
                    hub = get_webull_data_hub()
                    hub_id = hub.get_option_ticker_id(symbol, strike, iso_exp, side)
                    if hub_id:
                        option_id = hub_id
                        self._option_id_cache[cache_key] = option_id
                except Exception:
                    pass
            
            if not option_id:
                can_request, wait_time = self.rate_limiter.can_make_request('webull')
                if not can_request:
                    return None
                
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
                
                self._option_id_cache[cache_key] = option_id
                try:
                    from src.services.webull_data_hub import get_webull_data_hub
                    hub = get_webull_data_hub()
                    hub.set_option_ticker_id(symbol, strike, iso_exp, side, int(option_id))
                except Exception:
                    pass
            
            if self._streaming_client and option_id:
                try:
                    tid_str = str(option_id)
                    if tid_str not in getattr(self._streaming_client, '_subscribed_ticker_ids', set()):
                        opt_symbol = f"{symbol.upper()}_{strike}{option_type.upper()}"
                        self._streaming_client.subscribe_symbol(opt_symbol, tid_str, is_option=True)
                        print(f"[PRICE_MONITOR] Auto-subscribed option {opt_symbol} (tid={tid_str}) for streaming")
                except Exception:
                    pass
            
            can_request, _ = self.rate_limiter.can_make_request('webull')
            if not can_request:
                return None
            
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
    
    async def _fetch_index_option_price_yfinance(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str
    ) -> Optional[float]:
        """
        Fetch index option price from yfinance (SPX, NDX, VIX, etc).
        
        yfinance supports index options that brokers like Alpaca/Robinhood don't.
        Uses ^SPX for SPX, ^NDX for NDX, etc.
        """
        try:
            import yfinance as yf
            
            SYMBOL_MAP = {
                'SPX': '^SPX', 'SPXW': '^SPX',
                'NDX': '^NDX', 'NDXP': '^NDX',
                'VIX': '^VIX', 'VIXW': '^VIX',
                'RUT': '^RUT', 'DJX': '^DJI',
                'XSP': '^XSP'
            }
            
            yf_symbol = SYMBOL_MAP.get(symbol.upper(), f'^{symbol.upper()}')
            
            try:
                exp_date = datetime.strptime(expiry, "%Y-%m-%d")
            except ValueError:
                try:
                    exp_date = datetime.strptime(expiry, "%m/%d/%Y")
                except ValueError:
                    exp_date = datetime.strptime(expiry, "%m/%d")
                    exp_date = exp_date.replace(year=datetime.now().year)
            
            yf_expiry = exp_date.strftime("%Y-%m-%d")
            
            def fetch():
                ticker = yf.Ticker(yf_symbol)
                try:
                    chain = ticker.option_chain(yf_expiry)
                except Exception:
                    return None
                
                opt_df = chain.calls if option_type.upper() == 'C' else chain.puts
                
                if opt_df.empty:
                    return None
                
                opt_df['strike_diff'] = abs(opt_df['strike'] - strike)
                closest = opt_df.loc[opt_df['strike_diff'].idxmin()]
                
                if closest['strike_diff'] > 5.0:
                    return None
                
                bid = closest.get('bid', 0)
                ask = closest.get('ask', 0)
                last = closest.get('lastPrice', 0)
                
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                elif last > 0:
                    return last
                return None
            
            price = await asyncio.get_event_loop().run_in_executor(None, fetch)
            
            if price and price > 0:
                print(f"[PRICE_MONITOR] ✓ yfinance index option: {symbol} {strike}{option_type} = ${price:.2f}")
            
            return price
            
        except ImportError:
            print("[PRICE_MONITOR] yfinance not installed for index option pricing")
            return None
        except Exception as e:
            print(f"[PRICE_MONITOR] yfinance error for {symbol}: {e}")
            return None
    
    async def _fetch_price_from_broker(
        self,
        broker_id: str,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str,
        asset_type: str = "option"
    ) -> Optional[float]:
        """Fetch price from a specific broker."""
        broker = self._brokers.get(broker_id.upper())
        if not broker:
            return None
        
        rate_key = get_rate_limit_key(broker_id)
        can_request, _ = self.rate_limiter.can_make_request(rate_key)
        if not can_request:
            return None
        
        try:
            if asset_type == "option":
                if hasattr(broker, 'get_option_quote'):
                    quote = await broker.get_option_quote(symbol, strike, expiry, option_type)
                    self.rate_limiter.record_request(rate_key)
                    if quote:
                        bid = quote.get('bid', 0)
                        ask = quote.get('ask', 0)
                        last = quote.get('last', 0)
                        if bid > 0 and ask > 0:
                            return (bid + ask) / 2
                        elif last > 0:
                            return last
            else:
                if hasattr(broker, 'get_quote'):
                    price = await broker.get_quote(symbol)
                    self.rate_limiter.record_request(rate_key)
                    if price and price > 0:
                        return price
            return None
        except Exception as e:
            print(f"[PRICE_MONITOR] {broker_id} error for {symbol}: {e}")
            return None
    
    def _check_streaming_hubs(self, pos: MonitoredPosition) -> Optional[float]:
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming():
                if pos.asset_type == "option":
                    ticker_id = None
                    try:
                        from gui_app.database import get_trade_by_id
                        trade = get_trade_by_id(pos.position_id)
                        if trade:
                            ticker_id = trade.get('option_id')
                    except Exception:
                        pass
                    if ticker_id:
                        price = hub.get_quote_price(str(ticker_id))
                        if price and price > 0:
                            return price
                else:
                    price = hub.get_quote_price(pos.symbol)
                    if price and price > 0:
                        return price
        except Exception:
            pass
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            schwab_hub = get_schwab_data_hub()
            if schwab_hub.is_streaming() and pos.asset_type == "option" and pos.expiry and pos.strike:
                expiry = pos.expiry
                if '/' in expiry:
                    parts = expiry.split('/')
                    if len(parts) == 3:
                        expiry = f"20{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                    elif len(parts) == 2:
                        import datetime
                        year = datetime.datetime.now().year
                        expiry = f"{year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                if '-' in expiry:
                    opt_type = pos.option_type or 'C'
                    underlying = pos.symbol.upper().ljust(6)
                    ep = expiry.split('-')
                    if len(ep) == 3:
                        occ = f"{underlying}{ep[0][2:]}{ep[1]}{ep[2]}{opt_type.upper()}{int(float(pos.strike) * 1000):08d}"
                        data = schwab_hub.get_quote_detailed(occ)
                        if data:
                            bid = data.get('bid', 0)
                            ask = data.get('ask', 0)
                            last = data.get('last', 0)
                            if bid > 0 and ask > 0:
                                return (bid + ask) / 2
                            elif last > 0:
                                return last
            elif schwab_hub.is_streaming() and pos.asset_type != "option":
                price = schwab_hub.get_quote_price(pos.symbol)
                if price and price > 0:
                    return price
        except Exception:
            pass
        return None

    async def _fetch_price(self, pos: MonitoredPosition) -> Optional[float]:
        """Fetch price using streaming hubs first (zero API cost), then broker-aware fallback chain."""
        hub_price = self._check_streaming_hubs(pos)
        if hub_price and hub_price > 0:
            return hub_price

        asset_type_enum = AssetType.OPTION if pos.asset_type == "option" else AssetType.STOCK
        
        fallback_brokers = get_fallback_brokers(
            pos.broker_id,
            self._connected_broker_ids,
            asset_type_enum
        )
        
        for broker_id in fallback_brokers:
            try:
                price = await self._fetch_price_from_broker(
                    broker_id,
                    pos.symbol,
                    pos.strike,
                    pos.expiry,
                    pos.option_type,
                    pos.asset_type
                )
                if price and price > 0:
                    pos.preferred_data_source = broker_id.lower()
                    return price
            except Exception:
                continue
        
        if pos.asset_type == "option":
            price = await self._fetch_option_price_webull(
                pos.symbol, pos.strike, pos.expiry, pos.option_type
            )
            if price and price > 0:
                pos.preferred_data_source = "webull_legacy"
                return price
            
            price = await self._fetch_option_price_alpaca(
                pos.symbol, pos.strike, pos.expiry, pos.option_type
            )
            if price and price > 0:
                pos.preferred_data_source = "alpaca_legacy"
                return price
            
            INDEX_SYMBOLS = {'SPX', 'SPXW', 'NDX', 'NDXP', 'VIX', 'VIXW', 'XSP', 'RUT', 'DJX'}
            if pos.symbol.upper() in INDEX_SYMBOLS:
                price = await self._fetch_index_option_price_yfinance(
                    pos.symbol, pos.strike, pos.expiry, pos.option_type
                )
                if price and price > 0:
                    pos.preferred_data_source = "yfinance_index"
                    return price
        
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
        Tries streaming hubs first (zero API cost), then Webull, then Alpaca fallback.
        """
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            schwab_hub = get_schwab_data_hub()
            if schwab_hub.is_streaming() and expiry and strike:
                norm_expiry = expiry
                if '/' in norm_expiry:
                    parts = norm_expiry.split('/')
                    if len(parts) == 3:
                        norm_expiry = f"20{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                    elif len(parts) == 2:
                        import datetime as _dt
                        norm_expiry = f"{_dt.datetime.now().year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                if '-' in norm_expiry:
                    ep = norm_expiry.split('-')
                    if len(ep) == 3:
                        ot = (option_type or 'C').upper()
                        occ = f"{symbol.upper().ljust(6)}{ep[0][2:]}{ep[1]}{ep[2]}{ot}{int(float(strike) * 1000):08d}"
                        data = schwab_hub.get_quote_detailed(occ)
                        if data:
                            bid = data.get('bid', 0)
                            ask = data.get('ask', 0)
                            last = data.get('last', 0)
                            if bid > 0 and ask > 0:
                                return (bid + ask) / 2
                            elif last > 0:
                                return last
        except Exception:
            pass

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
