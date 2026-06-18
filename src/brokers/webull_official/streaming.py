import asyncio
import json
import logging
import threading
import uuid
from typing import Callable, Optional

from .client import WebullClient
from .config import WebullConfig

log = logging.getLogger("webull_official")


class WebullMarketStream:
    def __init__(self, config: WebullConfig, client: WebullClient):
        self._config = config
        self._client = client
        self._session_id = uuid.uuid4().hex
        self._mqtt_client = None
        self._callbacks: dict[str, list[Callable]] = {}
        self._subscribed_symbols: set[str] = set()
        self._symbol_categories: dict[str, str] = {}  # symbol → "US_STOCK" | "US_OPTION"
        self.on_quote_callback: Optional[Callable] = None  # set by broker after init
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None  # captured at connect()
        self._reconnect_timer: Optional[threading.Timer] = None
        self._reconnect_delay: float = 2.0

    async def connect(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            log.warning("[WEBULL-OFF] paho-mqtt not installed, streaming disabled")
            return False

        self._main_loop = asyncio.get_running_loop()

        self._mqtt_client = mqtt.Client(
            client_id=self._session_id,
            transport="tcp",
            protocol=mqtt.MQTTv311,
        )
        self._mqtt_client.username_pw_set(self._config.app_key, "password")
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_message = self._on_message
        self._mqtt_client.on_disconnect = self._on_disconnect

        self._mqtt_client.connect_async(
            self._config.mqtt_host,
            self._config.mqtt_port,
            keepalive=30,
        )
        self._mqtt_client.loop_start()
        return True

    async def subscribe(self, symbols: list[str], sub_types: list[str] = None, category: str = "US_STOCK"):
        if sub_types is None:
            sub_types = ["SNAPSHOT", "QUOTE"] if category == "US_OPTION" else ["SNAPSHOT"]

        batch_size = 100
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            body = {
                "session_id": self._session_id,
                "symbols": batch,
                "category": category,
                "sub_types": sub_types,
                "grab": True,
            }
            await self._client.post("/openapi/market-data/streaming/subscribe", body)
            self._subscribed_symbols.update(batch)
            for s in batch:
                self._symbol_categories[s] = category

    async def unsubscribe(self, symbols: list[str]):
        body = {
            "session_id": self._session_id,
            "symbols": symbols,
            "category": "US_STOCK",
            "sub_types": ["SNAPSHOT", "QUOTE", "TICK"],
        }
        await self._client.post("/openapi/market-data/streaming/unsubscribe", body)
        self._subscribed_symbols -= set(symbols)
        for s in symbols:
            self._symbol_categories.pop(s, None)

    def on(self, event: str, callback: Callable):
        self._callbacks.setdefault(event, []).append(callback)

    def _emit(self, event: str, data):
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception as e:
                log.error(f"[WEBULL-OFF] Stream callback error: {e}")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._reconnect_delay = 2.0
            log.info("[WEBULL-OFF] MQTT connected")
            client.subscribe("snapshot")
            client.subscribe("quote")
            client.subscribe("tick")
            client.subscribe("notice")
            # Re-subscribe all symbols after reconnect (session-side subscriptions are lost)
            if self._subscribed_symbols and self._main_loop and self._main_loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(self._resubscribe_all(), self._main_loop)
                except Exception as _e:
                    log.warning(f"[WEBULL-OFF] Reconnect re-subscribe failed: {_e}")
        else:
            log.error(f"[WEBULL-OFF] MQTT connect failed: rc={rc}")

    async def _resubscribe_all(self):
        if not self._subscribed_symbols:
            return
        syms = list(self._subscribed_symbols)
        cats = dict(self._symbol_categories)
        by_cat: dict[str, list[str]] = {}
        for s in syms:
            by_cat.setdefault(cats.get(s, "US_STOCK"), []).append(s)
        failed = []
        for cat, cat_syms in by_cat.items():
            try:
                await self.subscribe(cat_syms, category=cat)
            except Exception as _e:
                log.warning(f"[WEBULL-OFF] Re-subscribe failed for {len(cat_syms)} {cat} symbols: {_e}")
                failed.extend(cat_syms)
        if failed:
            log.warning(f"[WEBULL-OFF] {len(failed)} symbols not re-subscribed after reconnect: {failed}")
        else:
            log.info(f"[WEBULL-OFF] Re-subscribed {len(syms)} symbols after reconnect ({list(by_cat.keys())})")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        if topic == "notice":
            try:
                data = json.loads(msg.payload)
                self._emit("notice", data)
            except Exception:
                pass
        elif topic in ("snapshot", "quote", "tick"):
            self._emit(topic, msg.payload)
            if self.on_quote_callback:
                try:
                    tick = json.loads(msg.payload)
                    self.on_quote_callback(tick)
                except Exception:
                    pass
        elif topic == "echo":
            pass

    def _on_disconnect(self, client, userdata, rc):
        log.warning(f"[WEBULL-OFF] MQTT disconnected: rc={rc}")
        self._emit("disconnect", rc)
        if rc != 0 and self._mqtt_client:
            self._schedule_reconnect()

    def _schedule_reconnect(self):
        if self._reconnect_timer and self._reconnect_timer.is_alive():
            return
        delay = min(self._reconnect_delay, 60.0)
        self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)
        log.warning(f"[WEBULL-OFF] Reconnecting in {delay:.0f}s...")
        self._reconnect_timer = threading.Timer(delay, self._do_reconnect)
        self._reconnect_timer.daemon = True
        self._reconnect_timer.start()

    def _do_reconnect(self):
        if not self._mqtt_client:
            return
        try:
            self._mqtt_client.reconnect()
            self._reconnect_delay = 2.0
        except Exception as _e:
            log.warning(f"[WEBULL-OFF] Reconnect attempt failed: {_e}")

    async def disconnect(self):
        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
            self._mqtt_client = None


class TradeEventPoller:
    def __init__(self, client: WebullClient, account_id: str, interval: float = 5.0):
        self._client = client
        self._account_id = account_id
        self._interval = interval
        self._running = False
        self._known_fills: dict[str, float] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._task: Optional[asyncio.Task] = None

    def on(self, event: str, callback: Callable):
        self._callbacks.setdefault(event, []).append(callback)

    def _emit(self, event: str, data):
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception as e:
                log.error(f"[WEBULL-OFF] Event callback error: {e}")

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _poll_loop(self):
        from .orders import OrdersAPI
        from datetime import datetime, timedelta
        orders_api = OrdersAPI(self._client)
        _cycle = 0
        _backoff = 0

        while self._running:
            if _backoff > 0:
                try:
                    await asyncio.sleep(_backoff)
                except asyncio.CancelledError:
                    break
                _backoff = 0

            try:
                orders = await orders_api.get_open_orders(self._account_id)
                for order in orders:
                    prev_filled = self._known_fills.get(order.client_order_id, 0)
                    if order.filled_quantity > prev_filled:
                        self._emit("fill", {
                            "client_order_id": order.client_order_id,
                            "order_id": order.order_id,
                            "symbol": order.symbol,
                            "side": order.side,
                            "filled_qty": order.filled_quantity,
                            "filled_price": order.filled_price,
                            "status": order.status,
                            "new_fills": order.filled_quantity - prev_filled,
                        })
                    self._known_fills[order.client_order_id] = order.filled_quantity

                    if order.status in ("FILLED", "CANCELLED", "FAILED"):
                        self._emit("terminal", {
                            "client_order_id": order.client_order_id,
                            "status": order.status,
                            "symbol": order.symbol,
                        })
            except asyncio.CancelledError:
                break
            except Exception as e:
                if "TOO_MANY_REQUESTS" in str(e) or "429" in str(e):
                    log.warning(f"[WEBULL-OFF] Poll rate limited — backing off 15s")
                    _backoff = 15
                else:
                    log.error(f"[WEBULL-OFF] Poll error: {e}")

            # Every 10 cycles, scan order history to catch fills that transitioned out of open orders between polls
            _cycle += 1
            if _cycle % 10 == 0:
                try:
                    today = datetime.utcnow().strftime('%Y-%m-%d')
                    tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime('%Y-%m-%d')
                    hist = await orders_api.get_order_history(
                        self._account_id,
                        start_date=today,
                        end_date=tomorrow,
                        page_size=50,
                    )
                    for order in hist:
                        prev = self._known_fills.get(order.client_order_id, 0)
                        if order.status == "FILLED" and order.filled_quantity > prev:
                            self._emit("fill", {
                                "client_order_id": order.client_order_id,
                                "order_id": order.order_id,
                                "symbol": order.symbol,
                                "side": order.side,
                                "filled_qty": order.filled_quantity,
                                "filled_price": order.filled_price,
                                "status": order.status,
                                "new_fills": order.filled_quantity - prev,
                                "from_history": True,
                            })
                            self._known_fills[order.client_order_id] = order.filled_quantity
                            self._emit("terminal", {"client_order_id": order.client_order_id, "status": "FILLED", "symbol": order.symbol})
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.warning(f"[WEBULL-OFF] Order history catchup error: {e}")

            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break
