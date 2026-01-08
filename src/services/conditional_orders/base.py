"""
Base Conditional Order Service

Abstract base class with shared logic for market-specific implementations.
Each market service inherits from this and provides its own:
- Broker registry
- Rate limiters  
- Price monitor fallback chain
- Event loop/thread isolation
"""

import os
import asyncio
import aiohttp
import threading
import json
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
from abc import ABC, abstractmethod

try:
    import pytz
    IST = pytz.timezone('Asia/Kolkata')
    EST = pytz.timezone('America/New_York')
except ImportError:
    IST = None
    EST = None

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from gui_app.database import (
    get_conditional_order_settings,
    save_conditional_order_settings,
    create_conditional_order,
    update_conditional_order_status,
    get_active_conditional_orders,
    get_conditional_order_by_id,
    cancel_conditional_order,
    expire_old_conditional_orders,
    get_channel_conditional_settings,
)


class OrderStatus(Enum):
    PENDING = 'PENDING'
    VALIDATING = 'VALIDATING'
    PENDING_MONITOR = 'PENDING_MONITOR'
    ACTIVE_MONITORING = 'ACTIVE_MONITORING'
    FALLBACK_MONITORING = 'FALLBACK_MONITORING'
    TRIGGERED = 'TRIGGERED'
    EXECUTING = 'EXECUTING'
    TRACKING = 'TRACKING'
    TERMINATED = 'TERMINATED'
    CANCELED = 'CANCELED'
    EXPIRED = 'EXPIRED'
    ERROR = 'ERROR'


@dataclass
class RateLimitTracker:
    """Track API rate limits per broker/provider."""
    name: str
    max_calls_per_minute: int
    calls: List[float] = field(default_factory=list)
    
    def record_call(self):
        self.calls.append(datetime.now().timestamp())
        self._cleanup_old_calls()
    
    def _cleanup_old_calls(self):
        cutoff = datetime.now().timestamp() - 60
        self.calls = [c for c in self.calls if c > cutoff]
    
    def get_usage_ratio(self) -> float:
        self._cleanup_old_calls()
        return len(self.calls) / self.max_calls_per_minute if self.max_calls_per_minute > 0 else 0
    
    def can_make_call(self) -> bool:
        return self.get_usage_ratio() < 1.0
    
    def should_fallback(self, threshold: float = 0.8) -> bool:
        return self.get_usage_ratio() >= threshold


class PriceMonitor(ABC):
    """Base class for price monitoring."""
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None]):
        self.symbol = symbol
        self.callback = callback
        self.is_running = False
        self.last_price = None
    
    @abstractmethod
    async def start(self):
        """Start monitoring - must be implemented by subclass."""
        pass
    
    async def stop(self):
        """Stop monitoring."""
        self.is_running = False


class FinnhubPriceMonitor(PriceMonitor):
    """Price monitor using Finnhub API (US stocks)."""
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None], api_key: str):
        super().__init__(symbol, callback)
        self.api_key = api_key
        self.poll_interval = 1  # 60 req/min limit - can poll every 1 second
    
    async def start(self):
        self.is_running = True
        sys.stderr.write(f"[FINNHUB] Starting price monitor for {self.symbol}\n")
        sys.stderr.flush()
        
        async with aiohttp.ClientSession() as session:
            poll_count = 0
            while self.is_running:
                try:
                    url = f"https://finnhub.io/api/v1/quote?symbol={self.symbol}&token={self.api_key}"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            price = data.get('c')
                            poll_count += 1
                            if poll_count <= 3 or poll_count % 20 == 0:
                                sys.stderr.write(f"[FINNHUB] Poll #{poll_count} {self.symbol}: ${price}\n")
                                sys.stderr.flush()
                            if price and price != self.last_price:
                                self.last_price = price
                                await self.callback(self.symbol, float(price))
                except Exception as e:
                    sys.stderr.write(f"[FINNHUB] Error for {self.symbol}: {e}\n")
                    sys.stderr.flush()
                
                await asyncio.sleep(self.poll_interval)


class YFinancePriceMonitor(PriceMonitor):
    """Price monitor using yfinance (delayed data fallback)."""
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None]):
        super().__init__(symbol, callback)
        self.poll_interval = 15
    
    async def start(self):
        self.is_running = True
        sys.stderr.write(f"[YFINANCE] Starting price monitor for {self.symbol} (delayed ~15min)\n")
        sys.stderr.flush()
        
        poll_count = 0
        while self.is_running:
            try:
                price = await self._fetch_price()
                poll_count += 1
                if poll_count <= 3 or poll_count % 10 == 0:
                    sys.stderr.write(f"[YFINANCE] Poll #{poll_count} {self.symbol}: ${price}\n")
                    sys.stderr.flush()
                if price and price != self.last_price:
                    self.last_price = price
                    await self.callback(self.symbol, float(price))
            except Exception as e:
                sys.stderr.write(f"[YFINANCE] Error for {self.symbol}: {e}\n")
                sys.stderr.flush()
            
            await asyncio.sleep(self.poll_interval)
    
    async def _fetch_price(self) -> Optional[float]:
        if not YFINANCE_AVAILABLE:
            return None
        try:
            loop = asyncio.get_event_loop()
            def get_fast_price():
                ticker = yf.Ticker(self.symbol)
                fast_info = ticker.fast_info
                return fast_info.get('lastPrice') or fast_info.get('regularMarketPrice')
            price = await loop.run_in_executor(None, get_fast_price)
            return float(price) if price else None
        except Exception as e:
            sys.stderr.write(f"[YFINANCE] Fetch error for {self.symbol}: {e}\n")
            sys.stderr.flush()
            return None


class BrokerPriceMonitor(PriceMonitor):
    """Price monitor using broker API (Webull, Alpaca, Questrade, etc.)."""
    
    # Broker-specific poll intervals based on API rate limits
    BROKER_POLL_INTERVALS = {
        'alpaca': 1,      # 200 req/min limit - can poll every 1 second
        'alpaca_paper': 1,
        'alpaca_live': 1,
        'webull': 3,      # 10 req/30 sec limit - minimum 3 seconds
        'questrade': 2,   # Conservative default
        'tastytrade': 2,
        'ibkr': 1,        # No strict limit for TWS
        'schwab': 2,
    }
    
    def __init__(self, symbol: str, callback: Callable[[str, float], None], broker_name: str, broker_instance: Any = None):
        super().__init__(symbol, callback)
        self.broker_name = broker_name
        self.broker_instance = broker_instance
        # Set poll interval based on broker API limits
        broker_lower = broker_name.lower()
        self.poll_interval = self.BROKER_POLL_INTERVALS.get(broker_lower, 2)  # Default 2 sec
    
    async def start(self):
        self.is_running = True
        sys.stderr.write(f"[{self.broker_name.upper()}] Starting price monitor for {self.symbol} (poll interval: {self.poll_interval}s)\n")
        sys.stderr.flush()
        
        poll_count = 0
        while self.is_running:
            try:
                price = await self._fetch_price()
                poll_count += 1
                if poll_count <= 3 or poll_count % 10 == 0:
                    sys.stderr.write(f"[{self.broker_name.upper()}] Poll #{poll_count} for {self.symbol}: price={price}\n")
                    sys.stderr.flush()
                if price and price != self.last_price:
                    self.last_price = price
                    await self.callback(self.symbol, price)
            except Exception as e:
                sys.stderr.write(f"[{self.broker_name.upper()}] Error for {self.symbol}: {e}\n")
                sys.stderr.flush()
            
            await asyncio.sleep(self.poll_interval)
    
    async def _fetch_price(self) -> Optional[float]:
        if not self.broker_instance:
            return None
        
        try:
            loop = asyncio.get_event_loop()
            broker_lower = self.broker_name.lower()
            
            # Normalize broker name: 'alpaca_paper' -> 'alpaca'
            broker_normalized = broker_lower.replace('_paper', '').replace('_live', '')
            
            # Handle Alpaca and Alpaca Paper
            if broker_normalized == 'alpaca':
                from alpaca.data import StockHistoricalDataClient
                from alpaca.data.requests import StockLatestQuoteRequest
                
                # AlpacaBroker stores credentials in config dict
                api_key = None
                api_secret = None
                if hasattr(self.broker_instance, 'config'):
                    api_key = self.broker_instance.config.get('api_key')
                    api_secret = self.broker_instance.config.get('api_secret')
                elif hasattr(self.broker_instance, 'api_key') and hasattr(self.broker_instance, 'secret_key'):
                    api_key = self.broker_instance.api_key
                    api_secret = self.broker_instance.secret_key
                
                if api_key and api_secret:
                    client = StockHistoricalDataClient(api_key, api_secret)
                    request = StockLatestQuoteRequest(symbol_or_symbols=self.symbol)
                    quotes = await loop.run_in_executor(None, lambda: client.get_stock_latest_quote(request))
                    if self.symbol in quotes:
                        quote = quotes[self.symbol]
                        # Use midpoint of bid/ask for more accurate price
                        bid = float(quote.bid_price) if quote.bid_price else 0
                        ask = float(quote.ask_price) if quote.ask_price else 0
                        if bid > 0 and ask > 0:
                            return (bid + ask) / 2
                        elif ask > 0:
                            return ask
                        elif bid > 0:
                            return bid
            
            elif broker_lower == 'webull':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await loop.run_in_executor(None, lambda: self.broker_instance.get_quote(self.symbol))
                    if quote and 'close' in quote:
                        return float(quote['close'])
            
            elif broker_lower == 'questrade':
                if hasattr(self.broker_instance, 'get_quote'):
                    quote = await loop.run_in_executor(None, lambda: self.broker_instance.get_quote(self.symbol))
                    if quote and 'lastTradePrice' in quote:
                        return float(quote['lastTradePrice'])
            
        except Exception as e:
            sys.stderr.write(f"[{self.broker_name.upper()}] Quote error for {self.symbol}: {e}\n")
            sys.stderr.flush()
        
        return None


class BaseConditionalOrderService(ABC):
    """
    Abstract base class for market-specific conditional order services.
    
    Each market (US, India, Canada) implements its own service with:
    - Isolated event loop and thread
    - Market-specific broker registry
    - Market-specific rate limiters
    - Market-specific price monitor fallback chain
    """
    
    MARKET = 'BASE'
    
    def __init__(self):
        self.is_running = False
        self.monitors: Dict[int, PriceMonitor] = {}
        self.monitor_tasks: Dict[int, asyncio.Task] = {}
        self.pending_orders: Dict[int, Dict] = {}
        self.broker_instances: Dict[str, Any] = {}
        self.rate_limiters: Dict[str, RateLimitTracker] = {}
        self.execution_callback: Optional[Callable] = None
        self.main_event_loop: Optional[asyncio.AbstractEventLoop] = None
        self.notification_callback: Optional[Callable] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._thread_logs = deque(maxlen=100)
        self.finnhub_api_key = os.getenv('FINNHUB_API_KEY', '')
        
        self._init_rate_limiters()
    
    @abstractmethod
    def _init_rate_limiters(self):
        """Initialize market-specific rate limiters."""
        pass
    
    @abstractmethod
    def get_supported_brokers(self) -> List[str]:
        """Return list of broker names supported by this market."""
        pass
    
    @abstractmethod
    async def build_price_monitor(self, order: Dict, broker_instance: Any, broker_name: str) -> Optional[PriceMonitor]:
        """Build a price monitor for the given order using market-specific logic."""
        pass
    
    def _log(self, msg: str):
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] [{self.MARKET}] {msg}"
        self._thread_logs.append(full_msg)
        sys.stderr.write(f"[{self.MARKET}] {msg}\n")
        sys.stderr.flush()
    
    def set_broker_instance(self, broker_name: str, instance: Any):
        """Register a broker instance for this market's price monitoring."""
        broker_lower = broker_name.lower()
        if broker_lower in [b.lower() for b in self.get_supported_brokers()]:
            self.broker_instances[broker_lower] = instance
            self._log(f"Registered broker: {broker_name}")
        else:
            self._log(f"Broker {broker_name} not supported for {self.MARKET} market")
    
    def set_execution_callback(self, callback: Callable, main_loop: Optional[asyncio.AbstractEventLoop] = None):
        self.execution_callback = callback
        self.main_event_loop = main_loop
    
    def set_notification_callback(self, callback: Callable):
        self.notification_callback = callback
    
    def is_enabled(self) -> bool:
        settings = get_conditional_order_settings()
        return settings.get('enabled', False)
    
    def start(self):
        """Start the service in its own thread with isolated event loop."""
        if self.is_running:
            self._log("Already running")
            return
        
        self._log("Starting service...")
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True, name=f"Conditional-{self.MARKET}")
        self._thread.start()
    
    def _run_event_loop(self):
        """Run event loop in dedicated thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.is_running = True
        self._log("Event loop started")
        
        try:
            self._loop.run_until_complete(self._main_loop())
        except Exception as e:
            self._log(f"Event loop error: {e}")
        finally:
            self._loop.close()
            self.is_running = False
            self._log("Event loop stopped")
    
    async def _main_loop(self):
        """Main monitoring loop."""
        await self._restore_active_orders()
        
        while self.is_running:
            try:
                await self._check_expirations()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log(f"Main loop error: {e}")
                await asyncio.sleep(5)
    
    async def _restore_active_orders(self):
        """Restore monitors for active orders on startup."""
        orders = get_active_conditional_orders()
        market_orders = [o for o in orders if o.get('market', 'US') == self.MARKET]
        
        if not market_orders:
            self._log("No active orders to restore")
            return
        
        self._log(f"Restoring {len(market_orders)} active orders")
        for order in market_orders:
            order_id = order['id']
            self.pending_orders[order_id] = order
            await self._start_monitor(order_id, order)
        
        self._log(f"Restored {len(market_orders)} orders")
    
    async def _check_expirations(self):
        """Check and expire old orders."""
        expired_count = expire_old_conditional_orders()
        if expired_count > 0:
            self._log(f"Expired {expired_count} old orders")
            for order_id in list(self.pending_orders.keys()):
                order = get_conditional_order_by_id(order_id)
                if order and order.get('status') == 'EXPIRED':
                    if order_id in self.monitors:
                        await self.monitors[order_id].stop()
                        del self.monitors[order_id]
                    if order_id in self.monitor_tasks:
                        self.monitor_tasks[order_id].cancel()
                        del self.monitor_tasks[order_id]
                    if order_id in self.pending_orders:
                        del self.pending_orders[order_id]
    
    def create_order(self, channel_id: str, parsed_signal: Dict[str, Any], broker: str) -> Optional[int]:
        """Create a new conditional order."""
        if not self.is_enabled():
            self._log("Service disabled")
            return None
        
        channel_settings = get_channel_conditional_settings(channel_id)
        if not channel_settings.get('conditional_order_enabled', True):
            self._log(f"Disabled for channel {channel_id}")
            return None
        
        # Priority: passed broker (from enabled_brokers) > legacy broker_override setting
        effective_broker = broker or channel_settings.get('broker_override')
        if not effective_broker:
            self._log(f"No broker for channel {channel_id}")
            return None
        self._log(f"Using broker: {effective_broker} for channel {channel_id}")
        
        trigger_price = parsed_signal.get('trigger_price', 0)
        trigger_type = parsed_signal.get('trigger_type', 'over')
        trigger_offset = channel_settings.get('trigger_offset_percent', 0.0) or 0.0
        
        if trigger_offset != 0:
            if trigger_type == 'over':
                adjusted_price = trigger_price * (1 + trigger_offset / 100)
            else:
                adjusted_price = trigger_price * (1 - trigger_offset / 100)
        else:
            adjusted_price = trigger_price
        
        timeout_minutes = channel_settings.get('order_timeout_minutes') or channel_settings.get('conditional_order_timeout_minutes')
        if timeout_minutes:
            expires_at = (datetime.now() + timedelta(minutes=timeout_minutes)).strftime('%Y-%m-%d %H:%M:%S')
        else:
            expires_at = None
        
        size_mode = parsed_signal.get('size_mode')
        qty_value = None
        
        if size_mode == 'percent_account':
            qty_value = parsed_signal.get('position_size_pct')
        elif size_mode == 'fixed_qty':
            qty_value = parsed_signal.get('fixed_qty')
        else:
            if channel_settings.get('position_size_pct'):
                size_mode = 'percent_account'
                qty_value = channel_settings.get('position_size_pct')
            elif channel_settings.get('default_quantity'):
                size_mode = 'fixed_qty'
                qty_value = channel_settings.get('default_quantity')
        
        profit_targets = parsed_signal.get('profit_targets', [])
        if not profit_targets:
            channel_targets = []
            for i in range(1, 5):
                pt_pct = channel_settings.get(f'profit_target_{i}_pct')
                if pt_pct and pt_pct > 0:
                    channel_targets.append(pt_pct)
            if channel_targets:
                profit_targets = channel_targets
        
        stop_loss_value = parsed_signal.get('stop_loss_value') or parsed_signal.get('stop_loss')
        stop_loss_type = parsed_signal.get('stop_loss_type')
        if not stop_loss_value and channel_settings.get('stop_loss_pct'):
            stop_loss_type = 'percent'
            stop_loss_value = channel_settings.get('stop_loss_pct')
        
        order_id = create_conditional_order(
            channel_id=channel_id,
            symbol=parsed_signal.get('symbol'),
            trigger_type=trigger_type,
            trigger_price=adjusted_price,
            adjusted_trigger_price=adjusted_price,
            broker_primary=effective_broker,
            stop_loss_type=stop_loss_type,
            stop_loss_value=stop_loss_value,
            take_profit_targets=json.dumps(profit_targets) if profit_targets else None,
            size_mode=size_mode,
            qty_value=qty_value,
            calculated_qty=parsed_signal.get('qty') or parsed_signal.get('quantity'),
            expires_at=expires_at,
            original_message=parsed_signal.get('original_message'),
            asset_type='option' if parsed_signal.get('strike') else 'stock',
            strike=parsed_signal.get('strike'),
            opt_type=parsed_signal.get('opt_type'),
            market=self.MARKET,
            expiry=parsed_signal.get('expiry'),
            lot_size=parsed_signal.get('lot_size'),
            lots=parsed_signal.get('lots'),
        )
        
        if order_id:
            self._log(f"Created order #{order_id} for {parsed_signal.get('symbol')}")
            self._schedule_monitoring(order_id)
        
        return order_id
    
    def _schedule_monitoring(self, order_id: int):
        """Schedule price monitoring for an order."""
        order = get_conditional_order_by_id(order_id)
        if not order:
            return
        
        update_conditional_order_status(
            order_id,
            'ACTIVE_MONITORING',
            event='MONITORING_STARTED',
            details=f"Started monitoring {order['symbol']}"
        )
        
        self.pending_orders[order_id] = order
        
        if self.is_running and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._start_monitor(order_id, order),
                self._loop
            )
    
    async def _start_monitor(self, order_id: int, order: Dict):
        """Start a price monitor for an order using market-specific logic."""
        symbol = order['symbol']
        broker = order['broker_primary']
        
        self._log(f"Starting monitor for #{order_id} {symbol} broker={broker}")
        
        # Normalize broker name for lookup: 'alpaca_paper' -> 'alpaca', 'ALPACA_PAPER' -> 'alpaca'
        broker_lower = broker.lower() if broker else ''
        broker_key = broker_lower.replace('_paper', '').replace('_live', '')
        broker_instance = self.broker_instances.get(broker_key) if broker_key else None
        
        if not broker_instance and broker_lower:
            # Fallback: try direct lookup
            broker_instance = self.broker_instances.get(broker_lower)
        
        monitor = await self.build_price_monitor(order, broker_instance, broker or '')
        
        if not monitor:
            self._log(f"No price monitor available for #{order_id}")
            update_conditional_order_status(
                order_id,
                'ERROR',
                event='NO_PRICE_SOURCE',
                error_message='No price source available for this market'
            )
            return
        
        self.monitors[order_id] = monitor
        
        def _on_monitor_done(task: asyncio.Task, oid: int = order_id):
            try:
                result = task.result()
                if result is False:
                    self._log(f"Order #{oid}: Monitor returned False")
                    if oid in self.monitors:
                        del self.monitors[oid]
                    if oid in self.pending_orders:
                        del self.pending_orders[oid]
                    if oid in self.monitor_tasks:
                        del self.monitor_tasks[oid]
            except asyncio.CancelledError:
                self._log(f"Monitor #{oid} cancelled")
            except Exception as e:
                self._log(f"Monitor error #{oid}: {e}")
        
        async def price_callback(sym: str, price: float):
            await self._on_price_update(order_id, sym, price)
        
        monitor.callback = price_callback
        
        task = asyncio.create_task(monitor.start())
        task.add_done_callback(lambda t: _on_monitor_done(t, order_id))
        self.monitor_tasks[order_id] = task
        
        self._log(f"Started monitor task for #{order_id}")
    
    async def _on_price_update(self, order_id: int, symbol: str, price: float):
        """Handle price update from monitor."""
        order = self.pending_orders.get(order_id)
        if not order:
            return
        
        trigger_price = order.get('trigger_price', 0)
        trigger_type = order.get('trigger_type', 'over')
        
        try:
            from gui_app.database import update_conditional_order_price
            update_conditional_order_price(order_id, price)
        except Exception:
            pass
        
        self._log(f"Price update #{order_id} {symbol} @ {price:.2f} (trigger: {trigger_type} {trigger_price})")
        
        triggered = False
        if trigger_type == 'over' and price >= trigger_price:
            triggered = True
        elif trigger_type == 'under' and price <= trigger_price:
            triggered = True
        
        if triggered:
            self._log(f"TRIGGERED #{order_id} {symbol}")
            await self._execute_order(order_id, order, price)
    
    async def _execute_order(self, order_id: int, order: Dict, trigger_price: float):
        """Execute triggered order."""
        if order_id in self.monitors:
            await self.monitors[order_id].stop()
            del self.monitors[order_id]
        
        if order_id in self.monitor_tasks:
            self.monitor_tasks[order_id].cancel()
            del self.monitor_tasks[order_id]
        
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
        
        update_conditional_order_status(
            order_id,
            'TRIGGERED',
            triggered_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            event='CONDITION_MET',
            details=f"Price reached {trigger_price}"
        )
        
        if self.execution_callback:
            try:
                order['triggered_price'] = trigger_price
                result = self.execution_callback(order, trigger_price)
                if asyncio.iscoroutine(result):
                    if self.main_event_loop and self.main_event_loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(result, self.main_event_loop)
                        try:
                            future.result(timeout=30)
                        except Exception as e:
                            self._log(f"Async execution error #{order_id}: {e}")
                    else:
                        self._log(f"Cannot execute async callback - no main event loop")
                update_conditional_order_status(order_id, 'EXECUTING')
            except Exception as e:
                self._log(f"Execution error #{order_id}: {e}")
                update_conditional_order_status(
                    order_id,
                    'ERROR',
                    event='EXECUTION_FAILED',
                    error_message=str(e)
                )
    
    def cancel_order(self, order_id: int) -> bool:
        """Cancel a conditional order."""
        if order_id in self.monitors:
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.monitors[order_id].stop(),
                    self._loop
                )
            del self.monitors[order_id]
        
        if order_id in self.monitor_tasks:
            self.monitor_tasks[order_id].cancel()
            del self.monitor_tasks[order_id]
        
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
        
        return cancel_conditional_order(order_id)
    
    def shutdown(self):
        """Shutdown the service."""
        self._log("Shutting down...")
        self.is_running = False
        
        for order_id, task in list(self.monitor_tasks.items()):
            task.cancel()
        
        self.monitors.clear()
        self.monitor_tasks.clear()
        self.pending_orders.clear()
        
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
