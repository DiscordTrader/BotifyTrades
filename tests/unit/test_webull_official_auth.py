"""
QA Gate 1: Webull Official API Core Module Tests
Tests: auth signing, config, rate limiter, models, exceptions
"""
import pytest
import asyncio
import base64
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestHMACSigning:
    def test_signature_produces_valid_base64(self):
        from brokers.webull_official.auth import WebullAuth

        auth = WebullAuth("test_app_key", "0f50a2e853334a9aae1a783bee120c1f")
        headers = auth.sign_request(
            "POST", "/trade/place_order", "api.webull.com",
            body={"symbol": "AAPL", "side": "BUY"}
        )
        assert "x-signature" in headers
        sig = headers["x-signature"]
        decoded = base64.b64decode(sig)
        assert len(decoded) == 20  # SHA1 produces 20-byte digest

    def test_signature_changes_with_different_nonce(self):
        from brokers.webull_official.auth import WebullAuth

        auth = WebullAuth("key", "secret")
        h1 = auth.sign_request("GET", "/test", "api.webull.com")
        h2 = auth.sign_request("GET", "/test", "api.webull.com")

        assert h1["x-signature"] != h2["x-signature"]
        assert h1["x-signature-nonce"] != h2["x-signature-nonce"]

    def test_required_headers_present(self):
        from brokers.webull_official.auth import WebullAuth

        auth = WebullAuth("my_key", "my_secret")
        headers = auth.sign_request("GET", "/test", "api.webull.com")

        required = [
            "x-app-key", "x-timestamp", "x-signature",
            "x-signature-algorithm", "x-signature-version",
            "x-signature-nonce", "x-version"
        ]
        for h in required:
            assert h in headers, f"Missing required header: {h}"

        assert headers["x-app-key"] == "my_key"
        assert headers["x-signature-algorithm"] == "HMAC-SHA1"
        assert headers["x-signature-version"] == "1.0"
        assert headers["x-version"] == "v2"

    def test_timestamp_is_iso8601_utc(self):
        from brokers.webull_official.auth import WebullAuth

        auth = WebullAuth("key", "secret")
        headers = auth.sign_request("GET", "/test", "api.webull.com")

        ts = headers["x-timestamp"]
        assert ts.endswith("Z")
        assert "T" in ts
        assert len(ts) == 20

    def test_post_body_adds_content_type(self):
        from brokers.webull_official.auth import WebullAuth

        auth = WebullAuth("key", "secret")
        h_with_body = auth.sign_request("POST", "/test", "api.webull.com", body={"x": 1})
        h_without_body = auth.sign_request("GET", "/test", "api.webull.com")

        assert "Content-Type" in h_with_body
        assert h_with_body["Content-Type"] == "application/json"
        assert "Content-Type" not in h_without_body

    def test_signing_key_has_trailing_ampersand(self):
        from brokers.webull_official.auth import WebullAuth

        auth = WebullAuth("key", "mysecret")
        assert auth._signing_key == b"mysecret&"

    def test_app_secret_not_in_headers(self):
        from brokers.webull_official.auth import WebullAuth

        secret = "super_secret_value_12345"
        auth = WebullAuth("key", secret)
        headers = auth.sign_request("POST", "/test", "api.webull.com", body={"x": 1})

        for k, v in headers.items():
            assert secret not in v, f"Secret leaked in header {k}"
            assert k != "x-app-secret", "x-app-secret must not be a header"

    def test_query_params_affect_signature(self):
        from brokers.webull_official.auth import WebullAuth

        auth = WebullAuth("key", "secret")
        h1 = auth.sign_request("GET", "/test", "api.webull.com", query_params={"a": "1"})
        h2 = auth.sign_request("GET", "/test", "api.webull.com", query_params={"a": "2"})

        assert h1["x-signature"] != h2["x-signature"]

    def test_different_paths_produce_different_signatures(self):
        from brokers.webull_official.auth import WebullAuth

        auth = WebullAuth("key", "secret")
        h1 = auth.sign_request("GET", "/path1", "api.webull.com")
        h2 = auth.sign_request("GET", "/path2", "api.webull.com")

        assert h1["x-signature"] != h2["x-signature"]


class TestConfig:
    def test_production_urls(self):
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s", environment="production")
        assert "api.webull.com" in cfg.base_url
        assert "events-api.webull.com" in cfg.events_url
        assert cfg.mqtt_port == 1883

    def test_test_urls(self):
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s", environment="test")
        assert "uat" in cfg.base_url
        assert "uat" in cfg.events_url

    def test_default_is_production(self):
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        assert "api.webull.com" in cfg.base_url

    def test_mqtt_wss_url(self):
        from brokers.webull_official.config import WebullConfig

        cfg = WebullConfig(app_key="k", app_secret="s")
        assert "wss://" in cfg.mqtt_wss_url
        assert "8883" in cfg.mqtt_wss_url


class TestRateLimiter:
    def test_order_endpoint_allows_burst(self):
        from brokers.webull_official.rate_limiter import RateLimiter

        async def _run():
            rl = RateLimiter()
            start = time.monotonic()
            for _ in range(5):
                await rl.acquire("/openapi/trade/order/place")
            return time.monotonic() - start

        elapsed = asyncio.run(_run())
        assert elapsed < 1.0

    def test_account_data_throttled(self):
        from brokers.webull_official.rate_limiter import RateLimiter

        async def _run():
            rl = RateLimiter()
            await rl.acquire("/openapi/assets/balance")
            await rl.acquire("/openapi/assets/balance")
            start = time.monotonic()
            await rl.acquire("/openapi/assets/balance")
            return time.monotonic() - start

        elapsed = asyncio.run(_run())
        assert elapsed >= 0.5

    def test_unknown_endpoint_no_limit(self):
        from brokers.webull_official.rate_limiter import RateLimiter

        async def _run():
            rl = RateLimiter()
            start = time.monotonic()
            for _ in range(50):
                await rl.acquire("/unknown/path")
            return time.monotonic() - start

        elapsed = asyncio.run(_run())
        assert elapsed < 1.0

    def test_all_known_endpoints_have_category(self):
        from brokers.webull_official.rate_limiter import RateLimiter

        known_endpoints = [
            "/openapi/trade/order/place",
            "/openapi/trade/order/cancel",
            "/openapi/trade/order/replace",
            "/openapi/assets/balance",
            "/openapi/assets/positions",
            "/openapi/trade/order/history",
            "/openapi/trade/order/open",
            "/openapi/trade/order/detail",
            "/openapi/account/list",
        ]
        for ep in known_endpoints:
            assert ep in RateLimiter.ENDPOINT_CATEGORY, f"Missing category for {ep}"


class TestModels:
    def test_balance_from_api(self):
        from brokers.webull_official.models import WebullBalance

        raw = {
            "total_cash_balance": "25000.50",
            "total_market_value": "75000.00",
            "total_unrealized_profit_loss": "1500.25",
            "total_net_liquidation_value": "100000.50",
            "total_day_profit_loss": "-250.00",
            "day_trades_left": "3",
            "account_currency_assets": [{
                "currency": "USD",
                "buying_power": "50000.00",
                "settled_cash": "20000.00",
                "unsettled_cash": "5000.50",
                "option_buying_power": "30000.00",
                "day_buying_power": "100000.00",
                "overnight_buying_power": "50000.00",
            }]
        }
        bal = WebullBalance.from_api(raw)

        assert bal.total_cash_balance == 25000.50
        assert bal.total_market_value == 75000.00
        assert bal.total_unrealized_pnl == 1500.25
        assert bal.total_net_liquidation == 100000.50
        assert bal.total_day_pnl == -250.00
        assert bal.buying_power == 50000.00
        assert bal.day_trades_left == "3"

    def test_balance_from_api_empty_fields(self):
        from brokers.webull_official.models import WebullBalance

        raw = {
            "total_cash_balance": "",
            "total_market_value": None,
            "account_currency_assets": []
        }
        bal = WebullBalance.from_api(raw)

        assert bal.total_cash_balance == 0.0
        assert bal.total_market_value == 0.0
        assert bal.buying_power == 0.0

    def test_position_from_api_stock(self):
        from brokers.webull_official.models import WebullPosition

        raw = {
            "position_id": "P001",
            "symbol": "AAPL",
            "quantity": "100",
            "cost_price": "150.00",
            "last_price": "155.00",
            "unrealized_profit_loss": "500.00",
            "instrument_type": "EQUITY",
            "currency": "USD",
        }
        pos = WebullPosition.from_api(raw)

        assert pos.symbol == "AAPL"
        assert pos.quantity == 100.0
        assert pos.cost_price == 150.0
        assert pos.last_price == 155.0
        assert pos.unrealized_pnl == 500.0
        assert pos.instrument_type == "EQUITY"
        assert pos.option_type == ""

    def test_position_from_api_option(self):
        from brokers.webull_official.models import WebullPosition

        raw = {
            "position_id": "P002",
            "symbol": "AAPL",
            "quantity": "5",
            "cost_price": "3.50",
            "last_price": "5.20",
            "unrealized_profit_loss": "850.00",
            "instrument_type": "OPTION",
            "option_strategy": "SINGLE",
            "legs": [{
                "option_type": "CALL",
                "option_exercise_price": "180.00",
                "option_expire_date": "2026-06-20",
                "option_contract_multiplier": "100",
            }]
        }
        pos = WebullPosition.from_api(raw)

        assert pos.instrument_type == "OPTION"
        assert pos.option_type == "CALL"
        assert pos.strike_price == 180.0
        assert pos.expiry_date == "2026-06-20"
        assert pos.multiplier == 100

    def test_order_from_api(self):
        from brokers.webull_official.models import WebullOrder

        raw = {
            "client_order_id": "abc123",
            "order_id": "WB789",
            "symbol": "TSLA",
            "side": "BUY",
            "status": "FILLED",
            "order_type": "LIMIT",
            "instrument_type": "EQUITY",
            "total_quantity": "10",
            "filled_quantity": "10",
            "filled_price": "250.50",
            "limit_price": "251.00",
            "time_in_force": "DAY",
            "place_time_at": "2026-05-09T14:30:00Z",
            "filled_time_at": "2026-05-09T14:30:05Z",
        }
        order = WebullOrder.from_api(raw)

        assert order.client_order_id == "abc123"
        assert order.order_id == "WB789"
        assert order.status == "FILLED"
        assert order.filled_quantity == 10.0
        assert order.filled_price == 250.50

    def test_order_partial_fill(self):
        from brokers.webull_official.models import WebullOrder

        raw = {
            "client_order_id": "pf001",
            "order_id": "WB999",
            "symbol": "NVDA",
            "side": "BUY",
            "status": "PARTIAL_FILLED",
            "order_type": "LIMIT",
            "instrument_type": "EQUITY",
            "total_quantity": "100",
            "filled_quantity": "45",
            "filled_price": "900.00",
        }
        order = WebullOrder.from_api(raw)

        assert order.status == "PARTIAL_FILLED"
        assert order.filled_quantity == 45.0
        assert order.quantity == 100.0

    def test_place_order_result_dataclass(self):
        from brokers.webull_official.models import PlaceOrderResult

        r = PlaceOrderResult(client_order_id="c1", order_id="o1")
        assert r.client_order_id == "c1"
        assert r.order_id == "o1"
        assert r.combo_order_id == ""


class TestExceptions:
    def test_auth_error_is_api_error(self):
        from brokers.webull_official.exceptions import WebullAPIError, WebullAuthError

        err = WebullAuthError(401, "UNAUTHORIZED", "Bad credentials")
        assert isinstance(err, WebullAPIError)
        assert err.status_code == 401
        assert err.error_code == "UNAUTHORIZED"

    def test_order_error_is_api_error(self):
        from brokers.webull_official.exceptions import WebullAPIError, WebullOrderError

        err = WebullOrderError(417, "INVALID_PARAMETER", "Bad qty")
        assert isinstance(err, WebullAPIError)
        assert "417" in str(err)

    def test_connection_error_independent(self):
        from brokers.webull_official.exceptions import WebullConnectionError, WebullAPIError

        err = WebullConnectionError("timeout")
        assert not isinstance(err, WebullAPIError)

    def test_rate_limit_error_is_api_error(self):
        from brokers.webull_official.exceptions import WebullAPIError, WebullRateLimitError

        err = WebullRateLimitError(429, "RATE_LIMITED", "Too many requests")
        assert isinstance(err, WebullAPIError)
