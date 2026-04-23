"""
Tastytrade Data Hub
===================
Centralized cache and event bus for all Tastytrade data.
Follows the same singleton pattern as SchwabDataHub / WebullDataHub / IBKRDataHub.

Quote data is populated via DXLink streaming (zero REST API calls for quotes).
Position/order snapshots use periodic REST calls via the broker's existing methods.
"""

import asyncio
import inspect
import time
import threading
from typing import Dict, Optional, List, Any, Callable, Set


async def _await_if_needed(result):
    """Handle tastytrade SDK calls that may be sync or async depending on version."""
    if inspect.isawaitable(result):
        return await result
    return result
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
        self._quotes_lock = threading.Lock()
        self._positions: List[Dict[str, Any]] = []
        self._positions_time: float = 0
        self._pending_orders: List[Dict[str, Any]] = []
        self._orders_time: float = 0
        self._account_info: Dict[str, Any] = {}
        self._account_time: float = 0
        self._order_history: List[Dict[str, Any]] = []
        self._order_history_time: float = 0

        self._event_handlers: Dict[str, List[Callable]] = {}
        self._event_lock = threading.Lock()
        self._streaming_active = False
        self._last_quote_ts: float = 0
        self._subscribed_symbols: Set[str] = set()
        self._pending_subscribe: Set[str] = set()
        self._subscribe_event: Optional[asyncio.Event] = None

        self._broker = None
        self._streamer = None
        self._stream_task: Optional[asyncio.Task] = None
        self._stream_loop: Optional[asyncio.AbstractEventLoop] = None
        self._streamer_symbol_cache: Dict[str, str] = {}
        self._reconnect_count = 0

        self.POSITION_CACHE_TTL = 15
        self.ORDER_CACHE_TTL = 15
        self.ACCOUNT_CACHE_TTL = 30
        self.ORDER_HISTORY_CACHE_TTL = 60
        self.QUOTE_STALE_THRESHOLD = 120

        print("[TASTYTRADE_HUB] TastytradeDataHub initialized (singleton)")

    def set_broker(self, broker):
        self._broker = broker

    def on(self, event: str, handler: Callable):
        with self._event_lock:
            handlers = self._event_handlers.get(event)
            if handlers is None:
                self._event_handlers[event] = [handler]
            else:
                new_list = list(handlers)
                new_list.append(handler)
                self._event_handlers[event] = new_list

    def off(self, event: str, handler: Callable):
        with self._event_lock:
            handlers = self._event_handlers.get(event)
            if handlers is not None:
                self._event_handlers[event] = [h for h in handlers if h != handler]

    def _emit(self, event: str, data: Any = None):
        with self._event_lock:
            handlers = list(self._event_handlers.get(event, []))
        if not handlers:
            return
        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                print(f"[TASTYTRADE_HUB] Event handler error ({event}): {e}")

    def update_quote(self, symbol: str, quote_data: Dict[str, Any], source: str = "stream"):
        with self._quotes_lock:
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
        with self._quotes_lock:
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

    def subscribe_symbol(self, symbol: str):
        if symbol in self._subscribed_symbols:
            return
        self._pending_subscribe.add(symbol)
        if self._subscribe_event:
            self._subscribe_event.set()

    def _resolve_streamer_symbol(self, symbol: str) -> str:
        cached = self._streamer_symbol_cache.get(symbol)
        if cached:
            return cached
        if not self._broker or not hasattr(self._broker, 'session') or not self._broker.session:
            return symbol
        try:
            from tastytrade import Equity
            result = Equity.get(self._broker.session, symbol)
            if inspect.isawaitable(result):
                loop = asyncio.new_event_loop()
                try:
                    result = loop.run_until_complete(result)
                finally:
                    loop.close()
            equity = result
            if equity and hasattr(equity, 'streamer_symbol'):
                self._streamer_symbol_cache[symbol] = equity.streamer_symbol
                return equity.streamer_symbol
        except Exception:
            pass
        return symbol

    async def start_streaming(self, loop: asyncio.AbstractEventLoop = None):
        if self._stream_task and not self._stream_task.done():
            return
        if not self._broker or not hasattr(self._broker, 'session') or not self._broker.session:
            print("[TASTYTRADE_HUB] Cannot start streaming — no broker session")
            return
        self._stream_loop = loop or asyncio.get_event_loop()
        self._subscribe_event = asyncio.Event()
        self._stream_task = asyncio.create_task(self._streaming_loop())
        print("[TASTYTRADE_HUB] ✓ Persistent DXLink streaming task started")

    async def stop_streaming(self):
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        self._stream_task = None
        self._streaming_active = False
        self._streamer = None
        print("[TASTYTRADE_HUB] Streaming stopped")

    async def _streaming_loop(self):
        try:
            from tastytrade import DXLinkStreamer
            from tastytrade.dxfeed import Quote
        except ImportError:
            print("[TASTYTRADE_HUB] DXLink not available — streaming disabled")
            return

        while True:
            try:
                session = self._broker.session if self._broker else None
                if not session:
                    print("[TASTYTRADE_HUB] No session — waiting 10s before retry")
                    await asyncio.sleep(10)
                    continue

                print(f"[TASTYTRADE_HUB] Opening persistent DXLink connection (attempt #{self._reconnect_count + 1})...")
                async with DXLinkStreamer(session) as streamer:
                    self._streamer = streamer
                    self._streaming_active = True
                    self._reconnect_count += 1
                    self._emit('streaming_status', True)

                    if self._subscribed_symbols:
                        streamer_syms = []
                        for sym in self._subscribed_symbols:
                            s = await asyncio.to_thread(self._resolve_streamer_symbol, sym)
                            streamer_syms.append(s)
                        await streamer.subscribe(Quote, streamer_syms)
                        print(f"[TASTYTRADE_HUB] Re-subscribed {len(streamer_syms)} symbol(s) after reconnect")

                    if self._pending_subscribe:
                        new_syms = list(self._pending_subscribe)
                        self._pending_subscribe.clear()
                        streamer_syms = []
                        for sym in new_syms:
                            s = await asyncio.to_thread(self._resolve_streamer_symbol, sym)
                            streamer_syms.append(s)
                            self._subscribed_symbols.add(sym)
                        await streamer.subscribe(Quote, streamer_syms)
                        print(f"[TASTYTRADE_HUB] Subscribed to {len(streamer_syms)} initial symbol(s): {new_syms}")

                    print(f"[TASTYTRADE_HUB] ✓ DXLink stream active — listening for quotes")

                    while True:
                        subscribe_wait = asyncio.create_task(self._subscribe_event.wait())
                        quote_wait = asyncio.create_task(self._get_next_quote(streamer, Quote))

                        done, pending = await asyncio.wait(
                            {subscribe_wait, quote_wait},
                            return_when=asyncio.FIRST_COMPLETED
                        )

                        for task in pending:
                            task.cancel()
                            try:
                                await task
                            except (asyncio.CancelledError, Exception):
                                pass

                        if subscribe_wait in done:
                            self._subscribe_event.clear()
                            if self._pending_subscribe:
                                new_syms = list(self._pending_subscribe)
                                self._pending_subscribe.clear()
                                streamer_syms = []
                                for sym in new_syms:
                                    s = await asyncio.to_thread(self._resolve_streamer_symbol, sym)
                                    streamer_syms.append(s)
                                    self._subscribed_symbols.add(sym)
                                await streamer.subscribe(Quote, streamer_syms)
                                print(f"[TASTYTRADE_HUB] ✓ Dynamically subscribed: {new_syms}")

                        if quote_wait in done:
                            try:
                                quote_event = quote_wait.result()
                                if quote_event:
                                    self._process_quote_event(quote_event)
                            except Exception:
                                pass

            except asyncio.CancelledError:
                print("[TASTYTRADE_HUB] Streaming task cancelled")
                self._streaming_active = False
                self._streamer = None
                return
            except Exception as e:
                self._streaming_active = False
                self._streamer = None
                err_str = str(e)
                if 'GeneratorExit' not in err_str:
                    print(f"[TASTYTRADE_HUB] Stream error: {e} — reconnecting in 5s")
                await asyncio.sleep(5)

    async def _get_next_quote(self, streamer, quote_cls):
        try:
            return await asyncio.wait_for(streamer.get_event(quote_cls), timeout=30.0)
        except asyncio.TimeoutError:
            return None

    def _process_quote_event(self, quote_event):
        symbol = getattr(quote_event, 'event_symbol', None)
        if not symbol:
            return

        display_symbol = symbol
        for orig, streamer_sym in self._streamer_symbol_cache.items():
            if streamer_sym == symbol:
                display_symbol = orig
                break

        bid = float(getattr(quote_event, 'bid_price', 0) or 0)
        ask = float(getattr(quote_event, 'ask_price', 0) or 0)

        quote_data = {}
        if bid > 0:
            quote_data['bid'] = bid
        if ask > 0:
            quote_data['ask'] = ask
        if bid > 0 and ask > 0:
            quote_data['last'] = round((bid + ask) / 2, 4)

        if quote_data:
            self.update_quote(display_symbol, quote_data, source="dxlink_stream")


_hub_instance = None

def get_tastytrade_data_hub() -> TastytradeDataHub:
    global _hub_instance
    if _hub_instance is None:
        _hub_instance = TastytradeDataHub()
    return _hub_instance
