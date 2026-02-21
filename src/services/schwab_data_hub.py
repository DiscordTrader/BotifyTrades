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
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._quotes: Dict[str, QuoteData] = {}
        self._quotes_lock = threading.Lock()

        self._positions: List[Dict[str, Any]] = []
        self._positions_detailed: List[Dict[str, Any]] = []
        self._positions_lock = threading.Lock()
        self._positions_time: float = 0
        self._positions_detailed_time: float = 0

        self._pending_orders: List[Dict[str, Any]] = []
        self._orders_lock = threading.Lock()
        self._orders_time: float = 0

        self._account_info: Dict[str, Any] = {}
        self._account_lock = threading.Lock()
        self._account_time: float = 0

        self._order_history: List[Dict[str, Any]] = []
        self._order_history_lock = threading.Lock()
        self._order_history_time: float = 0

        self._event_handlers: Dict[str, List[Callable]] = {}
        self._event_lock = threading.Lock()

        self._streaming_active = False
        self._subscribed_symbols: Set[str] = set()

        self.POSITION_CACHE_TTL = 15
        self.ORDER_CACHE_TTL = 15
        self.ACCOUNT_CACHE_TTL = 30
        self.ORDER_HISTORY_CACHE_TTL = 60
        self.QUOTE_STALE_THRESHOLD = 120

        print("[SCHWAB_HUB] ✓ SchwabDataHub initialized (singleton)")

    def on(self, event: str, handler: Callable):
        with self._event_lock:
            if event not in self._event_handlers:
                self._event_handlers[event] = []
            self._event_handlers[event].append(handler)

    def off(self, event: str, handler: Callable):
        with self._event_lock:
            if event in self._event_handlers:
                self._event_handlers[event] = [h for h in self._event_handlers[event] if h != handler]

    def _emit(self, event: str, data: Any = None):
        with self._event_lock:
            handlers = list(self._event_handlers.get(event, []))
        for handler in handlers:
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

        self._emit('quote_updated', {'symbol': symbol, 'quote': existing})

    def get_quote(self, symbol: str) -> Optional[QuoteData]:
        with self._quotes_lock:
            quote = self._quotes.get(symbol)
            if quote and (time.time() - quote.timestamp) < self.QUOTE_STALE_THRESHOLD:
                return quote
        return None

    def get_quote_price(self, symbol: str) -> Optional[float]:
        quote = self.get_quote(symbol)
        if quote and quote.last > 0:
            return quote.last
        return None

    def get_quote_detailed(self, symbol: str) -> Optional[Dict[str, Any]]:
        quote = self.get_quote(symbol)
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
        with self._quotes_lock:
            now = time.time()
            return {s: q for s, q in self._quotes.items()
                    if (now - q.timestamp) < self.QUOTE_STALE_THRESHOLD}

    def update_positions(self, positions: List[Dict[str, Any]], detailed: bool = False, source: str = "unknown"):
        with self._positions_lock:
            if detailed:
                self._positions_detailed = list(positions)
                self._positions_detailed_time = time.time()
            else:
                self._positions = list(positions)
                self._positions_time = time.time()
        event = 'positions_detailed_updated' if detailed else 'positions_updated'
        self._emit(event, positions)

    def get_positions(self, detailed: bool = False) -> Optional[List[Dict[str, Any]]]:
        with self._positions_lock:
            if detailed:
                if self._positions_detailed_time > 0 and (time.time() - self._positions_detailed_time) < self.POSITION_CACHE_TTL:
                    return list(self._positions_detailed)
            else:
                if self._positions_time > 0 and (time.time() - self._positions_time) < self.POSITION_CACHE_TTL:
                    return list(self._positions)
        return None

    def get_positions_age(self, detailed: bool = False) -> float:
        with self._positions_lock:
            ts = self._positions_detailed_time if detailed else self._positions_time
            return time.time() - ts if ts > 0 else float('inf')

    def update_pending_orders(self, orders: List[Dict[str, Any]]):
        with self._orders_lock:
            self._pending_orders = list(orders)
            self._orders_time = time.time()
        self._emit('orders_updated', orders)

    def get_pending_orders(self) -> Optional[List[Dict[str, Any]]]:
        with self._orders_lock:
            if self._orders_time > 0 and (time.time() - self._orders_time) < self.ORDER_CACHE_TTL:
                return list(self._pending_orders)
        return None

    def update_account_info(self, info: Dict[str, Any]):
        with self._account_lock:
            self._account_info = dict(info)
            self._account_time = time.time()
        self._emit('account_updated', info)

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        with self._account_lock:
            if self._account_time > 0 and (time.time() - self._account_time) < self.ACCOUNT_CACHE_TTL:
                return dict(self._account_info)
        return None

    def update_order_history(self, orders: List[Dict[str, Any]]):
        with self._order_history_lock:
            self._order_history = list(orders)
            self._order_history_time = time.time()
        self._emit('order_history_updated', orders)

    def get_order_history(self) -> Optional[List[Dict[str, Any]]]:
        with self._order_history_lock:
            if self._order_history_time > 0 and (time.time() - self._order_history_time) < self.ORDER_HISTORY_CACHE_TTL:
                return list(self._order_history)
        return None

    def set_streaming_active(self, active: bool):
        self._streaming_active = active
        self._emit('streaming_status', active)

    def is_streaming(self) -> bool:
        return self._streaming_active

    def add_subscribed_symbols(self, symbols: Set[str]):
        self._subscribed_symbols.update(symbols)

    def remove_subscribed_symbols(self, symbols: Set[str]):
        self._subscribed_symbols -= symbols

    def get_subscribed_symbols(self) -> Set[str]:
        return set(self._subscribed_symbols)

    def invalidate_positions(self):
        with self._positions_lock:
            self._positions_time = 0
            self._positions_detailed_time = 0

    def invalidate_orders(self):
        with self._orders_lock:
            self._orders_time = 0

    def invalidate_all(self):
        self.invalidate_positions()
        self.invalidate_orders()
        with self._account_lock:
            self._account_time = 0
        with self._order_history_lock:
            self._order_history_time = 0

    def get_stats(self) -> Dict[str, Any]:
        with self._quotes_lock:
            quote_count = len(self._quotes)
            fresh_quotes = sum(1 for q in self._quotes.values()
                             if (time.time() - q.timestamp) < 10)
        return {
            'streaming_active': self._streaming_active,
            'total_quotes_cached': quote_count,
            'fresh_quotes_10s': fresh_quotes,
            'subscribed_symbols': len(self._subscribed_symbols),
            'positions_age_s': round(self.get_positions_age(), 1),
            'positions_detailed_age_s': round(self.get_positions_age(detailed=True), 1),
            'orders_age_s': round(time.time() - self._orders_time, 1) if self._orders_time > 0 else 'never',
            'account_age_s': round(time.time() - self._account_time, 1) if self._account_time > 0 else 'never',
        }


def get_schwab_data_hub() -> SchwabDataHub:
    return SchwabDataHub()
