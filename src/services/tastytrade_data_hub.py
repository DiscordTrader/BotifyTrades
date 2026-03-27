"""
Tastytrade Data Hub
===================
Centralized cache and event bus for all Tastytrade data.
Follows the same singleton pattern as SchwabDataHub / WebullDataHub / IBKRDataHub.

Quote data is populated via DXLink streaming (zero REST API calls for quotes).
Position/order snapshots use periodic REST calls via the broker's existing methods.
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


class TastytradeDataHub:
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
        self._positions: List[Dict[str, Any]] = []
        self._positions_time: float = 0
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

        self._broker = None

        self.POSITION_CACHE_TTL = 15
        self.ORDER_CACHE_TTL = 15
        self.ACCOUNT_CACHE_TTL = 30
        self.ORDER_HISTORY_CACHE_TTL = 60
        self.QUOTE_STALE_THRESHOLD = 120

        print("[TASTYTRADE_HUB] TastytradeDataHub initialized (singleton)")

    def set_broker(self, broker):
        self._broker = broker

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
                print(f"[TASTYTRADE_HUB] Event handler error ({event}): {e}")

    def update_quote(self, symbol: str, quote_data: Dict[str, Any], source: str = "stream"):
        existing = self._quotes.get(symbol)
        if existing is None:
            existing = QuoteData(symbol=symbol)
            self._quotes[symbol] = existing

        if 'bid' in quote_data:
            existing.bid = float(quote_data.get('bid', existing.bid) or 0)
        if 'ask' in quote_data:
            existing.ask = float(quote_data.get('ask', existing.ask) or 0)
        if 'last' in quote_data:
            existing.last = float(quote_data.get('last', existing.last) or 0)
        if existing.last == 0 and existing.bid > 0 and existing.ask > 0:
            existing.last = (existing.bid + existing.ask) / 2
        if 'volume' in quote_data:
            existing.volume = int(quote_data.get('volume', existing.volume) or 0)
        if 'delta' in quote_data:
            existing.delta = float(quote_data.get('delta', 0) or 0)
        if 'gamma' in quote_data:
            existing.gamma = float(quote_data.get('gamma', 0) or 0)
        if 'theta' in quote_data:
            existing.theta = float(quote_data.get('theta', 0) or 0)
        if 'vega' in quote_data:
            existing.vega = float(quote_data.get('vega', 0) or 0)
        if 'iv' in quote_data:
            existing.implied_volatility = float(quote_data.get('iv', 0) or 0)

        existing.timestamp = time.time()
        existing.source = source
        self._last_quote_ts = existing.timestamp
        self._emit('quote_updated', {'symbol': symbol, 'quote': existing})

    def get_quote(self, symbol: str, max_age: Optional[float] = None) -> Optional[QuoteData]:
        quote = self._quotes.get(symbol)
        threshold = max_age if max_age is not None else self.QUOTE_STALE_THRESHOLD
        if quote and (time.time() - quote.timestamp) < threshold:
            return quote
        return None

    def get_quote_price(self, symbol: str) -> Optional[float]:
        quote = self.get_quote(symbol)
        if quote:
            if quote.last > 0:
                return quote.last
            if quote.bid > 0 and quote.ask > 0:
                return (quote.bid + quote.ask) / 2
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

    def update_positions(self, positions: List[Dict[str, Any]], source: str = "unknown"):
        self._positions = list(positions)
        self._positions_time = time.time()
        self._emit('positions_updated', positions)

    def get_positions(self) -> Optional[List[Dict[str, Any]]]:
        t = self._positions_time
        if t > 0 and (time.time() - t) < self.POSITION_CACHE_TTL:
            return list(self._positions)
        return None

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

    def get_account_info(self, max_age_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        ttl = max_age_seconds if max_age_seconds is not None else self.ACCOUNT_CACHE_TTL
        t = self._account_time
        if t > 0 and (time.time() - t) < ttl:
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
            if (time.time() - self._last_quote_ts) > 60:
                return False
        return True

    def request_risk_eval(self):
        self._emit('risk_eval_requested', None)


_hub_instance = None

def get_tastytrade_data_hub() -> TastytradeDataHub:
    global _hub_instance
    if _hub_instance is None:
        _hub_instance = TastytradeDataHub()
    return _hub_instance
