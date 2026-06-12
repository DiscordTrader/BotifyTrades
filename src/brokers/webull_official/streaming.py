import asyncio
import json
import logging
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
        self.on_quote_callback: Optional[Callable] = None  # set by broker after init

    async def connect(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            log.warning("[WEBULL-OFF] paho-mqtt not installed, streaming disabled")
            return False

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
        )
        self._mqtt_client.loop_start()
        return True

    async def subscribe(self, symbols: list[str], sub_types: list[str] = None):
        if sub_types is None:
            sub_types = ["SNAPSHOT"]

        batch_size = 100
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            body = {
                "session_id": self._session_id,
                "symbols": batch,
                "category": "US_STOCK",
                "sub_types": sub_types,
                "grab": True,
            }
            await self._client.post("/openapi/market-data/streaming/subscribe", body)
            self._subscribed_symbols.update(batch)

    async def unsubscribe(self, symbols: list[str]):
        body = {
            "session_id": self._session_id,
            "symbols": symbols,
            "category": "US_STOCK",
            "sub_types": ["SNAPSHOT", "QUOTE", "TICK"],
        }
        await self._client.post("/openapi/market-data/streaming/unsubscribe", body)
        self._subscribed_symbols -= set(symbols)

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
            log.info("[WEBULL-OFF] MQTT connected")
            client.subscribe("snapshot")
            client.subscribe("quote")
            client.subscribe("notice")
        else:
            log.error(f"[WEBULL-OFF] MQTT connect failed: rc={rc}")

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

    async def disconnect(self):
        if self._mqtt_client:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
            self._mqtt_client = None


class TradeEventPoller:
    def __init__(self, client: WebullClient, account_id: str, interval: float = 3.0):
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
        orders_api = OrdersAPI(self._client)

        while self._running:
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
                log.error(f"[WEBULL-OFF] Poll error: {e}")

            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break
