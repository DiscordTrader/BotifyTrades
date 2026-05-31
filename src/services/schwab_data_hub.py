"""
Schwab Data Hub
===============
Centralized cache and event bus for all Schwab data.
All services read from this hub instead of making direct Schwab API calls.

Architecture:
- Single source of truth for Schwab positions, orders, quotes, account info
- Event-driven: services subscribe to data updates
- Reduces Schwab API calls from 138-186/min to ~20-40/min
- Quote data populated by WebSocket streaming (zero API calls)
- Position/order snapshots via periodic REST (consolidated, not per-service)

Thread safety:
- All attribute mutations use CPython GIL-atomic operations (dict[key]=val,
  self.attr=val) so no threading.Lock is needed. This avoids blocking the
  asyncio event loop when the streaming client calls update_quote() from
  within its receive coroutine.
"""

import time
import threading
from typing import Dict, Optional, List, Any, Callable, Set
from dataclasses import dataclass, field


@dataclass
class QuoteData:
    symbol: str
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    high: float = 0.0
    low: float = 0.0
    open_price: float = 0.0
    close_price: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    open_interest: int = 0
    implied_volatility: float = 0.0
    timestamp: float = 0.0
    source: str = "stream"


class SchwabDataHub:
    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._initialized = False
                    cls._instance = inst
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._quotes: Dict[str, QuoteData] = {}
        self._quotes_lock = threading.Lock()

        self._positions: List[Dict[str, Any]] = []
        self._positions_detailed: List[Dict[str, Any]] = []
        self._positions_time: float = 0
        self._positions_detailed_time: float = 0

        self._pending_orders: List[Dict[str, Any]] = []
        self._orders_time: float = 0

        self._account_info: Dict[str, Any] = {}
        self._account_time: float = 0

        self._order_history: List[Dict[str, Any]] = []
        self._order_history_time: float = 0

        self._event_handlers: Dict[str, List[Callable]] = {}

        self._streaming_active = False
        self._last_quote_ts: float = 0
        self._subscribed_symbols: Set[str] = set()
        self._pending_equity_subs: Set[str] = set()
        self._pending_option_subs: Set[str] = set()
        self._pending_subs_lock = threading.Lock()
        self._risk_eval_requested = threading.Event()

        self.POSITION_CACHE_TTL = 15
        self.ORDER_CACHE_TTL = 15
        self.ACCOUNT_CACHE_TTL = 30
        self.ORDER_HISTORY_CACHE_TTL = 60
        self.QUOTE_STALE_THRESHOLD = 120

        print("[SCHWAB_HUB] ✓ SchwabDataHub initialized (singleton)")

    def on(self, event: str, handler: Callable):
        handlers = self._event_handlers.get(event)
        if handlers is None:
            self._event_handlers[event] = [handler]
        else:
            new_list = list(handlers)
            new_list.append(handler)
            self._event_handlers[event] = new_list

    def off(self, event: str, handler: Callable):
        handlers = self._event_handlers.get(event)
        if handlers is not None:
            self._event_handlers[event] = [h for h in handlers if h != handler]

    def _emit(self, event: str, data: Any = None):
        handlers = self._event_handlers.get(event)
        if not handlers:
            return
        for handler in list(handlers):
            try:
                handler(data)
            except Exception as e:
                print(f"[SCHWAB_HUB] Event handler error ({event}): {e}")

    def update_quote(self, symbol: str, quote_data: Dict[str, Any], source: str = "stream"):
        with self._quotes_lock:
            existing = self._quotes.get(symbol)
            if existing is None:
                existing = QuoteData(symbol=symbol)
                self._quotes[symbol] = existing

            if 'bid' in quote_data or 'BID_PRICE' in quote_data:
                existing.bid = float(quote_data.get('bid', quote_data.get('BID_PRICE', existing.bid)) or 0)
            if 'ask' in quote_data or 'ASK_PRICE' in quote_data:
                existing.ask = float(quote_data.get('ask', quote_data.get('ASK_PRICE', existing.ask)) or 0)
            if 'last' in quote_data or 'LAST_PRICE' in quote_data:
                existing.last = float(quote_data.get('last', quote_data.get('LAST_PRICE', existing.last)) or 0)
            if 'volume' in quote_data or 'TOTAL_VOLUME' in quote_data:
                existing.volume = int(quote_data.get('volume', quote_data.get('TOTAL_VOLUME', existing.volume)) or 0)
            if 'high' in quote_data or 'HIGH_PRICE' in quote_data:
                existing.high = float(quote_data.get('high', quote_data.get('HIGH_PRICE', existing.high)) or 0)
            if 'low' in quote_data or 'LOW_PRICE' in quote_data:
                existing.low = float(quote_data.get('low', quote_data.get('LOW_PRICE', existing.low)) or 0)

            if 'DELTA' in quote_data:
                existing.delta = float(quote_data.get('DELTA', 0) or 0)
            if 'GAMMA' in quote_data:
                existing.gamma = float(quote_data.get('GAMMA', 0) or 0)
            if 'THETA' in quote_data:
                existing.theta = float(quote_data.get('THETA', 0) or 0)
            if 'VEGA' in quote_data:
                existing.vega = float(quote_data.get('VEGA', 0) or 0)
            if 'OPEN_INTEREST' in quote_data:
                existing.open_interest = int(quote_data.get('OPEN_INTEREST', 0) or 0)
            if 'VOLATILITY' in quote_data:
                existing.implied_volatility = float(quote_data.get('VOLATILITY', 0) or 0)

            existing.timestamp = time.time()
            existing.source = source

        self._last_quote_ts = existing.timestamp
        self._emit('quote_updated', {'symbol': symbol, 'quote': existing})

    def get_quote(self, symbol: str, max_age: Optional[float] = None) -> Optional[QuoteData]:
        with self._quotes_lock:
            quote = self._quotes.get(symbol)
            threshold = max_age if max_age is not None else self.QUOTE_STALE_THRESHOLD
            if quote and (time.time() - quote.timestamp) < threshold:
                return quote
            return None

    def get_quote_price(self, symbol: str) -> Optional[float]:
        quote = self.get_quote(symbol)
        if quote and quote.last > 0:
            return quote.last
        return None

    def get_quote_detailed(self, symbol: str, max_age: Optional[float] = None) -> Optional[Dict[str, Any]]:
        quote = self.get_quote(symbol, max_age=max_age)
        if quote:
            return {
                'bid': quote.bid,
                'ask': quote.ask,
                'last': quote.last,
                'price': quote.last,
                'volume': quote.volume,
                'high': quote.high,
                'low': quote.low,
                'delta': quote.delta,
                'gamma': quote.gamma,
                'theta': quote.theta,
                'vega': quote.vega,
                'open_interest': quote.open_interest,
                'implied_volatility': quote.implied_volatility,
                'source': quote.source,
                'timestamp': quote.timestamp
            }
        return None

    def get_all_quotes(self) -> Dict[str, QuoteData]:
        now = time.time()
        quotes = self._quotes
        return {s: q for s, q in quotes.items()
                if (now - q.timestamp) < self.QUOTE_STALE_THRESHOLD}

    def update_positions(self, positions: List[Dict[str, Any]], detailed: bool = False, source: str = "unknown"):
        if detailed:
            self._positions_detailed = list(positions)
            self._positions_detailed_time = time.time()
        else:
            self._positions = list(positions)
            self._positions_time = time.time()
        event = 'positions_detailed_updated' if detailed else 'positions_updated'
        self._emit(event, positions)

    def get_positions(self, detailed: bool = False) -> Optional[List[Dict[str, Any]]]:
        if detailed:
            t = self._positions_detailed_time
            if t > 0 and (time.time() - t) < self.POSITION_CACHE_TTL:
                return list(self._positions_detailed)
        else:
            t = self._positions_time
            if t > 0 and (time.time() - t) < self.POSITION_CACHE_TTL:
                return list(self._positions)
        return None

    def get_positions_age(self, detailed: bool = False) -> float:
        ts = self._positions_detailed_time if detailed else self._positions_time
        return time.time() - ts if ts > 0 else float('inf')

    def update_pending_orders(self, orders: List[Dict[str, Any]]):
        self._pending_orders = list(orders)
        self._orders_time = time.time()
        self._emit('orders_updated', orders)

    def get_pending_orders(self) -> Optional[List[Dict[str, Any]]]:
        t = self._orders_time
        if t > 0 and (time.time() - t) < self.ORDER_CACHE_TTL:
            return list(self._pending_orders)
        return None

    def update_account_info(self, info: Dict[str, Any]):
        self._account_info = dict(info)
        self._account_time = time.time()
        self._emit('account_updated', info)

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        t = self._account_time
        if t > 0 and (time.time() - t) < self.ACCOUNT_CACHE_TTL:
            return dict(self._account_info)
        return None

    def update_order_history(self, orders: List[Dict[str, Any]]):
        self._order_history = list(orders)
        self._order_history_time = time.time()
        self._emit('order_history_updated', orders)

    def get_order_history(self) -> Optional[List[Dict[str, Any]]]:
        t = self._order_history_time
        if t > 0 and (time.time() - t) < self.ORDER_HISTORY_CACHE_TTL:
            return list(self._order_history)
        return None

    def set_streaming_active(self, active: bool):
        self._streaming_active = active
        self._emit('streaming_status', active)

    def is_streaming(self) -> bool:
        if not self._streaming_active:
            return False
        if self._last_quote_ts > 0:
            import time as _t
            if (_t.time() - self._last_quote_ts) > 60:
                return False
        return True

    def request_risk_eval(self):
        self._risk_eval_requested.set()

    def check_risk_eval_requested(self) -> bool:
        if self._risk_eval_requested.is_set():
            self._risk_eval_requested.clear()
            return True
        return False

    def request_subscribe_equities(self, symbols: Set[str]):
        with self._pending_subs_lock:
            new = symbols - self._subscribed_symbols
            if new:
                self._pending_equity_subs |= new

    def request_subscribe_options(self, symbols: Set[str]):
        with self._pending_subs_lock:
            new = symbols - self._subscribed_symbols
            if new:
                self._pending_option_subs |= new

    def drain_pending_subscriptions(self) -> Set[str]:
        with self._pending_subs_lock:
            pending = self._pending_equity_subs - self._subscribed_symbols
            self._pending_equity_subs.clear()
        return pending

    def drain_pending_option_subscriptions(self) -> Set[str]:
        with self._pending_subs_lock:
            pending = self._pending_option_subs - self._subscribed_symbols
            self._pending_option_subs.clear()
        return pending

    def add_subscribed_symbols(self, symbols: Set[str]):
        with self._pending_subs_lock:
            self._subscribed_symbols = self._subscribed_symbols | symbols

    def remove_subscribed_symbols(self, symbols: Set[str]):
        with self._pending_subs_lock:
            self._subscribed_symbols = self._subscribed_symbols - symbols

    def get_subscribed_symbols(self) -> Set[str]:
        with self._pending_subs_lock:
            return set(self._subscribed_symbols)

    def invalidate_positions(self):
        self._positions_time = 0
        self._positions_detailed_time = 0

    def invalidate_orders(self):
        self._orders_time = 0

    def invalidate_all(self):
        self.invalidate_positions()
        self.invalidate_orders()
        self._account_time = 0
        self._order_history_time = 0

    def get_stats(self) -> Dict[str, Any]:
        quotes = self._quotes
        now = time.time()
        quote_count = len(quotes)
        fresh_quotes = sum(1 for q in quotes.values()
                         if (now - q.timestamp) < 10)
        return {
            'streaming_active': self._streaming_active,
            'total_quotes_cached': quote_count,
            'fresh_quotes_10s': fresh_quotes,
            'subscribed_symbols': len(self._subscribed_symbols),
            'positions_age_s': round(self.get_positions_age(), 1),
            'positions_detailed_age_s': round(self.get_positions_age(detailed=True), 1),
            'orders_age_s': round(now - self._orders_time, 1) if self._orders_time > 0 else 'never',
            'account_age_s': round(now - self._account_time, 1) if self._account_time > 0 else 'never',
        }


_schwab_data_hub_instance: Optional[SchwabDataHub] = None
_schwab_data_hub_lock = threading.Lock()


def get_schwab_data_hub() -> SchwabDataHub:
    global _schwab_data_hub_instance
    if _schwab_data_hub_instance is None:
        with _schwab_data_hub_lock:
            if _schwab_data_hub_instance is None:
                _schwab_data_hub_instance = SchwabDataHub()
    return _schwab_data_hub_instance
