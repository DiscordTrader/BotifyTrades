"""
QA Gate 4: Webull Official API Streaming & Integration Tests
Tests: MQTT streaming, trade event poller, broker wiring, credential service
"""
import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestWebullMarketStream:
    def test_subscribe_batches_at_100(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        mock_client = MagicMock()
        post_calls = []

        async def fake_post(path, body):
            post_calls.append(body)
            return {}

        mock_client.post = fake_post
        stream = WebullMarketStream(cfg, mock_client)

        symbols = [f"SYM{i}" for i in range(250)]
        asyncio.run(stream.subscribe(symbols))

        assert len(post_calls) == 3
        assert len(post_calls[0]["symbols"]) == 100
        assert len(post_calls[1]["symbols"]) == 100
        assert len(post_calls[2]["symbols"]) == 50
        assert stream._subscribed_symbols == set(symbols)

    def test_unsubscribe_removes_symbols(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value={})

        stream = WebullMarketStream(cfg, mock_client)
        stream._subscribed_symbols = {"AAPL", "MSFT", "TSLA"}

        asyncio.run(stream.unsubscribe(["AAPL", "MSFT"]))
        assert stream._subscribed_symbols == {"TSLA"}

    def test_on_callback_registered_and_emitted(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        stream = WebullMarketStream(cfg, MagicMock())

        received = []
        stream.on("snapshot", lambda data: received.append(data))
        stream._emit("snapshot", {"price": 150.0})

        assert len(received) == 1
        assert received[0]["price"] == 150.0

    def test_multiple_callbacks_for_same_event(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        stream = WebullMarketStream(cfg, MagicMock())

        results = []
        stream.on("quote", lambda d: results.append("a"))
        stream.on("quote", lambda d: results.append("b"))
        stream._emit("quote", {})

        assert results == ["a", "b"]

    def test_on_message_routes_snapshot_topic(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        stream = WebullMarketStream(cfg, MagicMock())

        received = []
        stream.on("snapshot", lambda d: received.append(d))

        msg = MagicMock()
        msg.topic = "snapshot"
        msg.payload = b"test_payload"
        stream._on_message(None, None, msg)

        assert len(received) == 1
        assert received[0] == b"test_payload"

    def test_on_message_routes_notice_as_json(self):
        import json
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        stream = WebullMarketStream(cfg, MagicMock())

        received = []
        stream.on("notice", lambda d: received.append(d))

        msg = MagicMock()
        msg.topic = "notice"
        msg.payload = json.dumps({"type": "order_fill"}).encode()
        stream._on_message(None, None, msg)

        assert len(received) == 1
        assert received[0]["type"] == "order_fill"

    def test_disconnect_emits_event(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        stream = WebullMarketStream(cfg, MagicMock())

        dc_reasons = []
        stream.on("disconnect", lambda rc: dc_reasons.append(rc))
        stream._on_disconnect(None, None, 7)

        assert dc_reasons == [7]

    def test_session_id_is_unique(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        s1 = WebullMarketStream(cfg, MagicMock())
        s2 = WebullMarketStream(cfg, MagicMock())
        assert s1._session_id != s2._session_id

    def test_subscribe_sends_correct_body(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        mock_client = MagicMock()
        bodies = []

        async def capture_post(path, body):
            bodies.append((path, body))
            return {}

        mock_client.post = capture_post
        stream = WebullMarketStream(cfg, mock_client)

        asyncio.run(stream.subscribe(["AAPL", "MSFT"], sub_types=["QUOTE", "TICK"]))

        assert len(bodies) == 1
        path, body = bodies[0]
        assert path == "/openapi/market-data/streaming/subscribe"
        assert body["symbols"] == ["AAPL", "MSFT"]
        assert body["sub_types"] == ["QUOTE", "TICK"]
        assert body["category"] == "US_STOCK"
        assert body["grab"] is True


class TestTradeEventPoller:
    def test_fill_event_emitted_on_new_fill(self):
        from brokers.webull_official.streaming import TradeEventPoller
        from brokers.webull_official.models import WebullOrder

        mock_client = MagicMock()
        poller = TradeEventPoller(mock_client, "ACC001", interval=0.01)

        fills = []
        poller.on("fill", lambda d: fills.append(d))

        mock_order = WebullOrder(
            client_order_id="c1", order_id="o1", symbol="AAPL",
            side="BUY", status="PARTIAL_FILLED", order_type="LIMIT",
            instrument_type="EQUITY", quantity=100, filled_quantity=50,
            filled_price=150.0
        )

        async def _test():
            with patch("brokers.webull_official.orders.OrdersAPI.get_open_orders",
                       new_callable=AsyncMock, return_value=[mock_order]):
                await poller.start()
                await asyncio.sleep(0.05)
                await poller.stop()

        asyncio.run(_test())

        assert len(fills) >= 1
        assert fills[0]["symbol"] == "AAPL"
        assert fills[0]["filled_qty"] == 50
        assert fills[0]["new_fills"] == 50

    def test_terminal_event_on_filled_order(self):
        from brokers.webull_official.streaming import TradeEventPoller
        from brokers.webull_official.models import WebullOrder

        mock_client = MagicMock()
        poller = TradeEventPoller(mock_client, "ACC001", interval=0.01)

        terminals = []
        poller.on("terminal", lambda d: terminals.append(d))

        mock_order = WebullOrder(
            client_order_id="c2", order_id="o2", symbol="TSLA",
            side="SELL", status="FILLED", order_type="MARKET",
            instrument_type="EQUITY", quantity=10, filled_quantity=10,
            filled_price=250.0
        )

        async def _test():
            with patch("brokers.webull_official.orders.OrdersAPI.get_open_orders",
                       new_callable=AsyncMock, return_value=[mock_order]):
                await poller.start()
                await asyncio.sleep(0.05)
                await poller.stop()

        asyncio.run(_test())

        assert len(terminals) >= 1
        assert terminals[0]["status"] == "FILLED"
        assert terminals[0]["symbol"] == "TSLA"

    def test_no_duplicate_fill_events(self):
        from brokers.webull_official.streaming import TradeEventPoller
        from brokers.webull_official.models import WebullOrder

        mock_client = MagicMock()
        poller = TradeEventPoller(mock_client, "ACC001", interval=0.01)

        fills = []
        poller.on("fill", lambda d: fills.append(d))

        mock_order = WebullOrder(
            client_order_id="c3", order_id="o3", symbol="NVDA",
            side="BUY", status="PARTIAL_FILLED", order_type="LIMIT",
            instrument_type="EQUITY", quantity=100, filled_quantity=25,
            filled_price=900.0
        )

        call_count = 0

        async def _test():
            nonlocal call_count

            async def get_orders(account_id):
                nonlocal call_count
                call_count += 1
                return [mock_order]

            with patch("brokers.webull_official.orders.OrdersAPI.get_open_orders",
                       side_effect=get_orders):
                await poller.start()
                await asyncio.sleep(0.08)
                await poller.stop()

        asyncio.run(_test())

        fill_events_for_c3 = [f for f in fills if f["client_order_id"] == "c3"]
        assert len(fill_events_for_c3) == 1

    def test_stop_cancels_task(self):
        from brokers.webull_official.streaming import TradeEventPoller

        mock_client = MagicMock()
        poller = TradeEventPoller(mock_client, "ACC001", interval=0.01)

        async def _test():
            with patch("brokers.webull_official.orders.OrdersAPI.get_open_orders",
                       new_callable=AsyncMock, return_value=[]):
                await poller.start()
                assert poller._running is True
                assert poller._task is not None
                await poller.stop()
                assert poller._running is False
                assert poller._task is None

        asyncio.run(_test())

    def test_poll_error_does_not_crash(self):
        from brokers.webull_official.streaming import TradeEventPoller

        mock_client = MagicMock()
        poller = TradeEventPoller(mock_client, "ACC001", interval=0.01)

        async def _test():
            with patch("brokers.webull_official.orders.OrdersAPI.get_open_orders",
                       new_callable=AsyncMock, side_effect=ConnectionError("network down")):
                await poller.start()
                await asyncio.sleep(0.05)
                assert poller._running is True
                await poller.stop()

        asyncio.run(_test())


class TestCredentialService:
    def test_get_webull_official_credentials_defaults(self):
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "gui_app"))
        from gui_app.broker_credentials_service import get_webull_official_credentials

        with patch("gui_app.broker_credentials_service.load_config", return_value=None):
            creds = get_webull_official_credentials()

        assert creds["app_key"] == ""
        assert creds["app_secret"] == ""
        assert creds["environment"] == "production"
        assert creds["paper_mode"] is False

    def test_get_webull_official_credentials_with_data(self):
        from gui_app.broker_credentials_service import get_webull_official_credentials

        stored = {
            "app_key": "test_key_123",
            "app_secret": "test_secret_456",
            "environment": "test",
        }
        with patch("gui_app.broker_credentials_service.load_config", return_value=stored):
            creds = get_webull_official_credentials()

        assert creds["app_key"] == "test_key_123"
        assert creds["app_secret"] == "test_secret_456"
        assert creds["environment"] == "test"
        assert creds["paper_mode"] is False


class TestBrokerWiring:
    def test_get_broker_instance_resolves_webull_official(self):
        from selfbot_webull import SelfClient

        bot = object.__new__(SelfClient)
        mock_broker = MagicMock()
        mock_broker.connected = True
        bot.webull_official_broker = mock_broker
        bot.broker = MagicMock()

        result = bot.get_broker_instance("webull_official")
        assert result is mock_broker

    def test_get_broker_instance_webull_official_before_webull(self):
        from selfbot_webull import SelfClient

        bot = object.__new__(SelfClient)
        mock_official = MagicMock()
        mock_legacy = MagicMock()
        bot.webull_official_broker = mock_official
        bot.broker = mock_legacy

        assert bot.get_broker_instance("webull_official") is mock_official
        assert bot.get_broker_instance("webull") is mock_legacy

    def test_relay_client_broker_map_has_webull_official(self):
        from services.relay_client import RelayClient

        client = object.__new__(RelayClient)
        client._bot = MagicMock()
        mock_broker = MagicMock()
        client._bot.webull_official_broker = mock_broker

        broker = client._get_broker_by_name("WEBULL_OFFICIAL")
        assert broker is mock_broker


class TestIntegrationWiring:
    def test_unified_price_hub_has_webull_official_mapping(self):
        from services.unified_price_hub import UnifiedPriceHub

        assert "WEBULL_OFFICIAL" in UnifiedPriceHub._BROKER_NAME_TO_HUB
        assert "WEBULL_OFFICIAL_LIVE" in UnifiedPriceHub._BROKER_NAME_TO_HUB
        assert "WEBULL_OFFICIAL_PAPER" in UnifiedPriceHub._BROKER_NAME_TO_HUB

    def test_webull_official_import_flag_exists(self):
        import selfbot_webull
        assert hasattr(selfbot_webull, 'WEBULL_OFFICIAL_AVAILABLE')
