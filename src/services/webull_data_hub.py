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
import asyncio
import threading
import logging
from typing import Dict, Optional, List, Any, Callable, Set, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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
        self._last_quote_ts: float = 0
        self._subscribed_symbols: Set[str] = set()
        self._subscribed_ticker_ids: Set[str] = set()

        self.POSITION_CACHE_TTL = 45
        self.ORDER_CACHE_TTL = 45
        self.ACCOUNT_CACHE_TTL = 90
        self.QUOTE_STALE_THRESHOLD = 120
        self.OPTION_ID_TTL = 600

        self._option_id_cache: Dict[str, Tuple[int, float]] = {}
        self._option_id_lock = threading.Lock()

        self._refresh_positions_lock = asyncio.Lock()
        self._refresh_account_lock = asyncio.Lock()
        self._refresh_orders_lock = asyncio.Lock()

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
                raw_price = float(quote_data.get('last', quote_data.get('price', existing.last)) or 0)
                if 0 < raw_price < 500000:
                    existing.last = raw_price
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

        self._last_quote_ts = time.time()
        self._emit('quote_updated', {'symbol': symbol.upper(), 'quote': existing})

    def get_quote(self, symbol: str, max_age: Optional[float] = None) -> Optional[WebullQuoteData]:
        threshold = max_age if max_age is not None else self.QUOTE_STALE_THRESHOLD
        with self._quotes_lock:
            quote = self._quotes.get(symbol.upper())
            if quote and (time.time() - quote.timestamp) < threshold:
                return quote
        resolved = self.get_symbol_by_ticker_id(symbol)
        if resolved:
            with self._quotes_lock:
                quote = self._quotes.get(resolved.upper())
                if quote and (time.time() - quote.timestamp) < threshold:
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
            ticker_id = pos.get('ticker', {}).get('tickerId') or pos.get('tickerId')
            symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
            if ticker_id and symbol:
                self.register_ticker_id(symbol, ticker_id)

        self._emit('positions_updated', positions)

    def get_positions(self, max_age_seconds: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        ttl = max_age_seconds if max_age_seconds is not None else self.POSITION_CACHE_TTL
        with self._positions_lock:
            if self._positions_time > 0 and (time.time() - self._positions_time) < ttl:
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

    def get_pending_orders(self, max_age_seconds: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        ttl = max_age_seconds if max_age_seconds is not None else self.ORDER_CACHE_TTL
        with self._orders_lock:
            if self._orders_time > 0 and (time.time() - self._orders_time) < ttl:
                return list(self._pending_orders)
        return None

    def update_account_info(self, info: Dict[str, Any]):
        with self._account_lock:
            self._account_info = dict(info)
            self._account_time = time.time()
        self._emit('account_updated', info)

    def get_account_info(self, max_age_seconds: Optional[int] = None) -> Optional[Dict[str, Any]]:
        ttl = max_age_seconds if max_age_seconds is not None else self.ACCOUNT_CACHE_TTL
        with self._account_lock:
            if self._account_time > 0 and (time.time() - self._account_time) < ttl:
                return dict(self._account_info)
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

    def invalidate_account(self):
        with self._account_lock:
            self._account_time = 0

    def invalidate_all(self):
        self.invalidate_positions()
        self.invalidate_orders()
        self.invalidate_account()

    def get_option_ticker_id(self, symbol: str, strike: float, expiry: str, side: str) -> Optional[int]:
        key = f"{symbol.upper()}_{float(strike):.2f}_{expiry}_{side.upper()}"
        with self._option_id_lock:
            entry = self._option_id_cache.get(key)
            if entry and (time.time() - entry[1]) < self.OPTION_ID_TTL:
                return entry[0]
            if entry:
                del self._option_id_cache[key]
        return None

    def set_option_ticker_id(self, symbol: str, strike: float, expiry: str, side: str, ticker_id: int):
        key = f"{symbol.upper()}_{float(strike):.2f}_{expiry}_{side.upper()}"
        with self._option_id_lock:
            self._option_id_cache[key] = (ticker_id, time.time())

    async def refresh_positions_once(self, wb_instance):
        if self._refresh_positions_lock.locked():
            return
        async with self._refresh_positions_lock:
            try:
                positions = await asyncio.to_thread(wb_instance.get_positions)
                if positions is not None:
                    self.update_positions(positions)
                    print("[WEBULL_HUB] Positions refreshed after order event")
            except Exception as e:
                logger.warning(f"Position refresh after order event failed: {e}")

    async def refresh_account_once(self, wb_instance):
        if self._refresh_account_lock.locked():
            return
        async with self._refresh_account_lock:
            try:
                account = await asyncio.to_thread(wb_instance.get_account)
                if account and isinstance(account, dict):
                    self.update_account_info(account)
                    print("[WEBULL_HUB] Account refreshed after order event")
            except Exception as e:
                logger.warning(f"Account refresh after order event failed: {e}")

    async def refresh_orders_once(self, wb_instance):
        if self._refresh_orders_lock.locked():
            return
        async with self._refresh_orders_lock:
            try:
                orders_raw = await asyncio.to_thread(wb_instance.get_current_orders)
                if orders_raw is not None:
                    normalized = []
                    for order in orders_raw:
                        ticker = order.get('ticker', {})
                        symbol = ticker.get('symbol', '') if ticker else ''
                        normalized.append({
                            'order_id': str(order.get('orderId', '')),
                            'symbol': symbol,
                            'quantity': int(order.get('totalQuantity', 0)),
                            'limit_price': float(order.get('lmtPrice', 0)) if order.get('lmtPrice') else None,
                            'action': order.get('action', ''),
                            'status': order.get('status', ''),
                            'order_type': order.get('orderType', ''),
                            'filled_quantity': int(order.get('filledQuantity', 0))
                        })
                    self.update_pending_orders(normalized)
                    print(f"[WEBULL_HUB] Orders refreshed after order event ({len(normalized)} orders)")
            except Exception as e:
                logger.warning(f"Orders refresh after order event failed: {e}")

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


_webull_data_hub_instance: Optional[WebullDataHub] = None
_webull_data_hub_lock = threading.Lock()


def get_webull_data_hub() -> WebullDataHub:
    global _webull_data_hub_instance
    if _webull_data_hub_instance is None:
        with _webull_data_hub_lock:
            if _webull_data_hub_instance is None:
                _webull_data_hub_instance = WebullDataHub()
    return _webull_data_hub_instance
