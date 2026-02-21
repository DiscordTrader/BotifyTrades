"""
Webull Data Hub
===============
Centralized cache and event bus for all Webull data.
All services read from this hub instead of making direct Webull API calls.

Architecture:
- Single source of truth for Webull positions, orders, quotes, account info
- Event-driven: services subscribe to data updates
- Quote data populated by MQTT streaming (zero API calls)
- Position/order snapshots via periodic REST (consolidated, not per-service)
- Mirrors SchwabDataHub architecture for consistency
"""

import time
import threading
from typing import Dict, Optional, List, Any, Callable, Set
from dataclasses import dataclass, field


@dataclass
class WebullQuoteData:
    symbol: str
    ticker_id: str = ""
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    high: float = 0.0
    low: float = 0.0
    open_price: float = 0.0
    close_price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    timestamp: float = 0.0
    source: str = "stream"


class WebullDataHub:
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

        self._quotes: Dict[str, WebullQuoteData] = {}
        self._quotes_lock = threading.Lock()

        self._ticker_id_map: Dict[str, str] = {}
        self._ticker_id_reverse: Dict[str, str] = {}
        self._ticker_map_lock = threading.Lock()

        self._positions: List[Dict[str, Any]] = []
        self._positions_lock = threading.Lock()
        self._positions_time: float = 0

        self._pending_orders: List[Dict[str, Any]] = []
        self._orders_lock = threading.Lock()
        self._orders_time: float = 0

        self._account_info: Dict[str, Any] = {}
        self._account_lock = threading.Lock()
        self._account_time: float = 0

        self._event_handlers: Dict[str, List[Callable]] = {}
        self._event_lock = threading.Lock()

        self._streaming_active = False
        self._subscribed_symbols: Set[str] = set()
        self._subscribed_ticker_ids: Set[str] = set()

        self.POSITION_CACHE_TTL = 30
        self.ORDER_CACHE_TTL = 30
        self.ACCOUNT_CACHE_TTL = 60
        self.QUOTE_STALE_THRESHOLD = 120

        self._risk_eval_requested = threading.Event()

        print("[WEBULL_HUB] ✓ WebullDataHub initialized (singleton)")

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
                print(f"[WEBULL_HUB] Event handler error ({event}): {e}")

    def register_ticker_id(self, symbol: str, ticker_id: str):
        with self._ticker_map_lock:
            self._ticker_id_map[symbol.upper()] = str(ticker_id)
            self._ticker_id_reverse[str(ticker_id)] = symbol.upper()

    def get_ticker_id(self, symbol: str) -> Optional[str]:
        with self._ticker_map_lock:
            return self._ticker_id_map.get(symbol.upper())

    def get_symbol_by_ticker_id(self, ticker_id: str) -> Optional[str]:
        with self._ticker_map_lock:
            return self._ticker_id_reverse.get(str(ticker_id))

    def update_quote(self, symbol: str, quote_data: Dict[str, Any], source: str = "stream"):
        with self._quotes_lock:
            existing = self._quotes.get(symbol.upper())
            if existing is None:
                existing = WebullQuoteData(symbol=symbol.upper())
                self._quotes[symbol.upper()] = existing

            if 'bid' in quote_data:
                existing.bid = float(quote_data['bid'] or 0)
            if 'ask' in quote_data:
                existing.ask = float(quote_data['ask'] or 0)
            if 'last' in quote_data or 'price' in quote_data:
                existing.last = float(quote_data.get('last', quote_data.get('price', existing.last)) or 0)
            if 'volume' in quote_data:
                existing.volume = int(quote_data['volume'] or 0)
            if 'high' in quote_data:
                existing.high = float(quote_data['high'] or 0)
            if 'low' in quote_data:
                existing.low = float(quote_data['low'] or 0)
            if 'open' in quote_data:
                existing.open_price = float(quote_data['open'] or 0)
            if 'close' in quote_data:
                existing.close_price = float(quote_data['close'] or 0)
            if 'change' in quote_data:
                existing.change = float(quote_data['change'] or 0)
            if 'changeRatio' in quote_data:
                existing.change_pct = float(quote_data['changeRatio'] or 0)
            if 'ticker_id' in quote_data:
                existing.ticker_id = str(quote_data['ticker_id'])

            existing.timestamp = time.time()
            existing.source = source

        self._emit('quote_updated', {'symbol': symbol.upper(), 'quote': existing})

    def get_quote(self, symbol: str) -> Optional[WebullQuoteData]:
        with self._quotes_lock:
            quote = self._quotes.get(symbol.upper())
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
                'open': quote.open_price,
                'close': quote.close_price,
                'change': quote.change,
                'change_pct': quote.change_pct,
                'source': quote.source,
                'timestamp': quote.timestamp
            }
        return None

    def get_all_quotes(self) -> Dict[str, WebullQuoteData]:
        with self._quotes_lock:
            now = time.time()
            return {s: q for s, q in self._quotes.items()
                    if (now - q.timestamp) < self.QUOTE_STALE_THRESHOLD}

    def update_positions(self, positions: List[Dict[str, Any]], source: str = "rest"):
        with self._positions_lock:
            self._positions = list(positions)
            self._positions_time = time.time()

        for pos in positions:
            ticker_id = pos.get('ticker', {}).get('tickerId')
            symbol = pos.get('ticker', {}).get('symbol', '')
            if ticker_id and symbol:
                self.register_ticker_id(symbol, ticker_id)

        self._emit('positions_updated', positions)

    def get_positions(self) -> Optional[List[Dict[str, Any]]]:
        with self._positions_lock:
            if self._positions_time > 0 and (time.time() - self._positions_time) < self.POSITION_CACHE_TTL:
                return list(self._positions)
        return None

    def get_positions_age(self) -> float:
        with self._positions_lock:
            return time.time() - self._positions_time if self._positions_time > 0 else float('inf')

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

    def request_risk_eval(self):
        self._risk_eval_requested.set()

    def check_risk_eval_requested(self) -> bool:
        if self._risk_eval_requested.is_set():
            self._risk_eval_requested.clear()
            return True
        return False

    def invalidate_positions(self):
        with self._positions_lock:
            self._positions_time = 0

    def invalidate_orders(self):
        with self._orders_lock:
            self._orders_time = 0

    def invalidate_all(self):
        self.invalidate_positions()
        self.invalidate_orders()
        with self._account_lock:
            self._account_time = 0

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
            'subscribed_ticker_ids': len(self._subscribed_ticker_ids),
            'positions_age_s': round(self.get_positions_age(), 1),
            'orders_age_s': round(time.time() - self._orders_time, 1) if self._orders_time > 0 else 'never',
            'account_age_s': round(time.time() - self._account_time, 1) if self._account_time > 0 else 'never',
        }


def get_webull_data_hub() -> WebullDataHub:
    return WebullDataHub()
