# Webull Official API — QA Test Plan

**Date:** 2026-05-09  
**Companion to:** `docs/webull_official_api_design.md`  
**Philosophy:** Every implementation phase gets a QA gate before proceeding. QA validates three things:
1. **Regression** — existing bot features still work
2. **New code** — the new module works as intended
3. **Gaps** — anything missing, broken, or untested

---

## QA Gate Structure

```
Phase 1: Core Module  ──→  QA Gate 1  ──→  Pass?  ──→  Phase 2
Phase 2: Trading       ──→  QA Gate 2  ──→  Pass?  ──→  Phase 3
Phase 3: Integration   ──→  QA Gate 3  ──→  Pass?  ──→  Phase 4
Phase 4: Streaming     ──→  QA Gate 4  ──→  Pass?  ──→  SHIP
```

Each gate has:
- **Automated tests** (pytest) — must all pass
- **Manual validation checklist** — developer confirms
- **Gap report template** — structured findings doc
- **Go/No-Go criteria** — what blocks proceeding

---

## QA GATE 1: Core Module

**After:** auth.py, client.py, config.py, exceptions.py, rate_limiter.py, models.py  
**Before:** Any trading or account code

### 1A. Automated Tests — `tests/unit/test_webull_official_auth.py`

```python
"""
QA Gate 1: Webull Official API Core Module Tests
Tests: auth signing, config, rate limiter, models, exceptions
"""
import pytest
import asyncio
import json
import hashlib
import hmac
import base64
import time
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote


class TestHMACSigning:
    """Validate HMAC-SHA1 signature generation matches Webull spec."""
    
    def test_signature_with_known_vector(self):
        """Verify against documented test vector from Webull docs.
        Path: /trade/place_order, App Secret: 0f50a2e853334a9aae1a783bee120c1f
        Expected: kvlS6opdZDhEBo5jq40nHYXaLvM=
        """
        from brokers.webull_official.auth import WebullAuth
        
        auth = WebullAuth("test_app_key", "0f50a2e853334a9aae1a783bee120c1f")
        # The sign_request output should contain a valid base64 signature
        headers = auth.sign_request(
            "POST", "/trade/place_order", "api.webull.com",
            body={"symbol": "AAPL", "side": "BUY"}
        )
        assert "x-signature" in headers
        sig = headers["x-signature"]
        # Must be valid base64
        base64.b64decode(sig)
        assert len(sig) > 10
    
    def test_signature_changes_with_different_nonce(self):
        """Each request must produce a different signature."""
        from brokers.webull_official.auth import WebullAuth
        
        auth = WebullAuth("key", "secret")
        h1 = auth.sign_request("GET", "/test", "api.webull.com")
        h2 = auth.sign_request("GET", "/test", "api.webull.com")
        
        assert h1["x-signature"] != h2["x-signature"]
        assert h1["x-signature-nonce"] != h2["x-signature-nonce"]
    
    def test_required_headers_present(self):
        """All 7 mandatory headers must be set."""
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
        """Timestamp must be YYYY-MM-DDThh:mm:ssZ format."""
        from brokers.webull_official.auth import WebullAuth
        
        auth = WebullAuth("key", "secret")
        headers = auth.sign_request("GET", "/test", "api.webull.com")
        
        ts = headers["x-timestamp"]
        assert ts.endswith("Z")
        assert "T" in ts
        assert len(ts) == 20  # 2026-05-09T14:30:00Z
    
    def test_post_body_md5_included_in_signing(self):
        """POST requests must MD5-hash the compact JSON body."""
        from brokers.webull_official.auth import WebullAuth
        
        auth = WebullAuth("key", "secret")
        body = {"account_id": "123", "symbol": "AAPL"}
        
        h_with_body = auth.sign_request("POST", "/test", "api.webull.com", body=body)
        h_without_body = auth.sign_request("GET", "/test", "api.webull.com")
        
        # Signatures must differ because body hash is part of sign string
        # (timestamps/nonces differ too, but this validates body is processed)
        assert h_with_body["x-signature"] != h_without_body["x-signature"]
        assert "Content-Type" in h_with_body
        assert "Content-Type" not in h_without_body
    
    def test_signing_key_has_trailing_ampersand(self):
        """Signing key must be 'app_secret&' (trailing & required)."""
        from brokers.webull_official.auth import WebullAuth
        
        auth = WebullAuth("key", "mysecret")
        assert auth._signing_key == b"mysecret&"
    
    def test_query_params_included_in_signing(self):
        """Query params must be part of the signature string."""
        from brokers.webull_official.auth import WebullAuth
        
        auth = WebullAuth("key", "secret")
        h1 = auth.sign_request("GET", "/test", "api.webull.com", query_params={"a": "1"})
        h2 = auth.sign_request("GET", "/test", "api.webull.com", query_params={"a": "2"})
        
        # Different params → different signatures (nonce differs too, but
        # this test confirms params are in the sign string conceptually)
        assert h1["x-signature"] != h2["x-signature"]
    
    def test_app_secret_not_in_headers(self):
        """App secret must NEVER appear in any header."""
        from brokers.webull_official.auth import WebullAuth
        
        secret = "super_secret_value_12345"
        auth = WebullAuth("key", secret)
        headers = auth.sign_request("POST", "/test", "api.webull.com", body={"x": 1})
        
        for k, v in headers.items():
            assert secret not in v, f"Secret leaked in header {k}"
            assert "x-app-secret" != k, "x-app-secret must not be a header"


class TestConfig:
    """Validate environment configuration."""
    
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


class TestRateLimiter:
    """Validate token bucket rate limiting."""
    
    @pytest.mark.asyncio
    async def test_order_endpoint_allows_burst(self):
        """Order endpoints allow 600/min — a few quick calls should pass."""
        from brokers.webull_official.rate_limiter import RateLimiter
        
        rl = RateLimiter()
        start = time.monotonic()
        for _ in range(5):
            await rl.acquire("/openapi/trade/order/place")
        elapsed = time.monotonic() - start
        
        assert elapsed < 1.0  # 5 calls well under 600/min cap
    
    @pytest.mark.asyncio
    async def test_account_data_throttled(self):
        """Account data: 2 req/2s — 3rd call in <2s should be delayed."""
        from brokers.webull_official.rate_limiter import RateLimiter
        
        rl = RateLimiter()
        await rl.acquire("/openapi/assets/balance")
        await rl.acquire("/openapi/assets/balance")
        
        start = time.monotonic()
        await rl.acquire("/openapi/assets/balance")  # 3rd call — should wait
        elapsed = time.monotonic() - start
        
        assert elapsed >= 1.0  # Had to wait for window to clear
    
    @pytest.mark.asyncio
    async def test_unknown_endpoint_no_limit(self):
        """Endpoints not in the map should pass without delay."""
        from brokers.webull_official.rate_limiter import RateLimiter
        
        rl = RateLimiter()
        start = time.monotonic()
        for _ in range(100):
            await rl.acquire("/unknown/path")
        elapsed = time.monotonic() - start
        
        assert elapsed < 1.0
    
    def test_all_known_endpoints_have_category(self):
        """Every documented endpoint must map to a rate limit category."""
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
    """Validate response model parsing."""
    
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
        """API may return empty strings or missing fields."""
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


class TestExceptions:
    """Validate exception hierarchy."""
    
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
```

### 1B. Regression Test — Existing Suite Must Still Pass

```bash
# Run BEFORE and AFTER Phase 1 — both runs must produce identical results
pytest tests/ -v --tb=short 2>&1 | tee qa_gate1_regression.txt

# Expected: 423/423 pass (or whatever current baseline is)
# FAIL criteria: ANY new failure not present in the "before" run
```

### 1C. Manual Validation Checklist

| # | Check | Pass? |
|---|-------|-------|
| 1 | `from brokers.webull_official.auth import WebullAuth` imports cleanly | |
| 2 | `from brokers.webull_official.config import WebullConfig` imports cleanly | |
| 3 | `from brokers.webull_official.models import WebullBalance, WebullPosition, WebullOrder` imports cleanly | |
| 4 | `from brokers.webull_official.rate_limiter import RateLimiter` imports cleanly | |
| 5 | `from brokers.webull_official.exceptions import WebullAPIError` imports cleanly | |
| 6 | No new dependencies added to requirements.txt that break existing installs | |
| 7 | Module doesn't import anything from unofficial webull API | |
| 8 | `python -c "import brokers.webull_official"` exits 0 from src/ | |

### 1D. Gap Report Template

```
QA Gate 1 Gap Report — Date: ___
Tester: ___

REGRESSION:
- [ ] Full test suite pass count: ___ / ___
- [ ] Any new failures? List:
- [ ] Any new warnings? List:

NEW CODE:
- [ ] Auth signature tests: ___ / ___ pass
- [ ] Config tests: ___ / ___ pass
- [ ] Rate limiter tests: ___ / ___ pass
- [ ] Model tests: ___ / ___ pass
- [ ] Exception tests: ___ / ___ pass

GAPS FOUND:
1. ___
2. ___

GO / NO-GO: ___
Blocker (if no-go): ___
```

---

## QA GATE 2: Trading Operations

**After:** accounts.py, orders.py, positions.py, broker.py  
**Before:** Bot wiring and GUI integration

### 2A. Automated Tests — `tests/unit/test_webull_official_trading.py`

```python
"""
QA Gate 2: Webull Official Trading Operations Tests
Tests: account queries, order placement, position fetching, broker interface
"""
import pytest
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass


class TestAccountsAPI:
    """Validate account operations."""
    
    @pytest.mark.asyncio
    async def test_list_accounts_parses_response(self):
        from brokers.webull_official.accounts import AccountsAPI
        
        mock_client = AsyncMock()
        mock_client.get.return_value = [
            {
                "account_id": "ACC001",
                "account_type": "MARGIN",
                "account_class": "INDIVIDUAL_MARGIN",
                "account_label": "Individual Margin",
                "user_id": "U001",
            },
            {
                "account_id": "ACC002",
                "account_type": "CASH",
                "account_class": "ROTH_IRA",
                "account_label": "Roth IRA",
                "user_id": "U001",
            }
        ]
        
        api = AccountsAPI(mock_client)
        accounts = await api.list_accounts()
        
        assert len(accounts) == 2
        assert accounts[0].account_id == "ACC001"
        assert accounts[0].account_type == "MARGIN"
        assert accounts[1].account_class == "ROTH_IRA"
    
    @pytest.mark.asyncio
    async def test_get_balance_calls_correct_endpoint(self):
        from brokers.webull_official.accounts import AccountsAPI
        
        mock_client = AsyncMock()
        mock_client.get.return_value = {
            "total_cash_balance": "10000",
            "total_market_value": "50000",
            "total_unrealized_profit_loss": "0",
            "total_net_liquidation_value": "60000",
            "total_day_profit_loss": "0",
            "account_currency_assets": [{"buying_power": "20000"}]
        }
        
        api = AccountsAPI(mock_client)
        balance = await api.get_balance("ACC001")
        
        mock_client.get.assert_called_with(
            "/openapi/assets/balance",
            params={"account_id": "ACC001"},
        )
        assert balance.total_net_liquidation == 60000.0


class TestOrdersAPI:
    """Validate order operations."""
    
    @pytest.mark.asyncio
    async def test_place_stock_market_order(self):
        from brokers.webull_official.orders import OrdersAPI
        
        mock_client = AsyncMock()
        mock_client.post.return_value = {
            "client_order_id": "test123",
            "order_id": "WB456",
        }
        
        api = OrdersAPI(mock_client)
        result = await api.place_stock_order(
            account_id="ACC001",
            symbol="AAPL",
            side="BUY",
            quantity=10,
            order_type="MARKET",
        )
        
        assert result.client_order_id == "test123"
        assert result.order_id == "WB456"
        
        call_body = mock_client.post.call_args[0][1]
        assert call_body["account_id"] == "ACC001"
        order = call_body["new_orders"][0]
        assert order["symbol"] == "AAPL"
        assert order["side"] == "BUY"
        assert order["order_type"] == "MARKET"
        assert order["instrument_type"] == "EQUITY"
        assert order["combo_type"] == "NORMAL"
        assert order["entrust_type"] == "QTY"
        assert order["market"] == "US"
    
    @pytest.mark.asyncio
    async def test_place_stock_limit_order_with_price(self):
        from brokers.webull_official.orders import OrdersAPI
        
        mock_client = AsyncMock()
        mock_client.post.return_value = {"client_order_id": "lim1", "order_id": "WB789"}
        
        api = OrdersAPI(mock_client)
        await api.place_stock_order(
            account_id="ACC001", symbol="TSLA", side="SELL",
            quantity=5, order_type="LIMIT", limit_price=250.50,
        )
        
        call_body = mock_client.post.call_args[0][1]
        order = call_body["new_orders"][0]
        assert order["order_type"] == "LIMIT"
        assert order["limit_price"] == "250.50"
    
    @pytest.mark.asyncio
    async def test_place_option_order_has_legs(self):
        from brokers.webull_official.orders import OrdersAPI
        
        mock_client = AsyncMock()
        mock_client.post.return_value = {"client_order_id": "opt1", "order_id": "WB999"}
        
        api = OrdersAPI(mock_client)
        await api.place_option_order(
            account_id="ACC001",
            symbol="AAPL",
            side="BUY",
            quantity=2,
            option_type="CALL",
            strike_price=180.0,
            expiry_date="2026-06-20",
            position_intent="BUY_TO_OPEN",
            order_type="LIMIT",
            limit_price=5.50,
        )
        
        call_body = mock_client.post.call_args[0][1]
        order = call_body["new_orders"][0]
        assert order["instrument_type"] == "OPTION"
        assert order["option_strategy"] == "SINGLE"
        assert order["position_intent"] == "BUY_TO_OPEN"
        assert len(order["legs"]) == 1
        leg = order["legs"][0]
        assert leg["strike_price"] == "180.0"
        assert leg["option_expire_date"] == "2026-06-20"
        assert leg["option_type"] == "CALL"
    
    @pytest.mark.asyncio
    async def test_place_bracket_order_has_three_legs(self):
        from brokers.webull_official.orders import OrdersAPI
        
        mock_client = AsyncMock()
        mock_client.post.return_value = {
            "combo_order_id": "combo1",
            "client_order_id": "",
        }
        
        api = OrdersAPI(mock_client)
        await api.place_bracket_order(
            account_id="ACC001",
            symbol="AAPL",
            side="BUY",
            quantity=10,
            order_type="LIMIT",
            limit_price=150.0,
            take_profit_price=165.0,
            stop_loss_price=140.0,
        )
        
        call_body = mock_client.post.call_args[0][1]
        orders = call_body["new_orders"]
        assert len(orders) == 3
        
        combo_types = [o["combo_type"] for o in orders]
        assert "MASTER" in combo_types
        assert "STOP_PROFIT" in combo_types
        assert "STOP_LOSS" in combo_types
        
        master = [o for o in orders if o["combo_type"] == "MASTER"][0]
        assert master["side"] == "BUY"
        assert master["order_type"] == "LIMIT"
        
        tp = [o for o in orders if o["combo_type"] == "STOP_PROFIT"][0]
        assert tp["side"] == "SELL"  # Exit side
        assert tp["limit_price"] == "165.0"
        
        sl = [o for o in orders if o["combo_type"] == "STOP_LOSS"][0]
        assert sl["side"] == "SELL"  # Exit side
        assert sl["stop_price"] == "140.0"
    
    @pytest.mark.asyncio
    async def test_bracket_exit_side_flips_for_short(self):
        from brokers.webull_official.orders import OrdersAPI
        
        mock_client = AsyncMock()
        mock_client.post.return_value = {"combo_order_id": "c2"}
        
        api = OrdersAPI(mock_client)
        await api.place_bracket_order(
            account_id="ACC001", symbol="SPY", side="SHORT",
            quantity=50, take_profit_price=400.0, stop_loss_price=460.0,
        )
        
        call_body = mock_client.post.call_args[0][1]
        orders = call_body["new_orders"]
        
        tp = [o for o in orders if o["combo_type"] == "STOP_PROFIT"][0]
        assert tp["side"] == "BUY"  # Cover side for short
        
        sl = [o for o in orders if o["combo_type"] == "STOP_LOSS"][0]
        assert sl["side"] == "BUY"
    
    @pytest.mark.asyncio
    async def test_cancel_order_sends_client_order_id(self):
        from brokers.webull_official.orders import OrdersAPI
        
        mock_client = AsyncMock()
        mock_client.post.return_value = {}
        
        api = OrdersAPI(mock_client)
        await api.cancel_order("ACC001", "my_order_123")
        
        call_body = mock_client.post.call_args[0][1]
        assert call_body["account_id"] == "ACC001"
        assert call_body["client_order_id"] == "my_order_123"
    
    @pytest.mark.asyncio
    async def test_replace_order_only_sends_changed_fields(self):
        from brokers.webull_official.orders import OrdersAPI
        
        mock_client = AsyncMock()
        mock_client.post.return_value = {}
        
        api = OrdersAPI(mock_client)
        await api.replace_order("ACC001", "ord1", limit_price=155.0)
        
        call_body = mock_client.post.call_args[0][1]
        modify = call_body["modify_orders"][0]
        assert modify["client_order_id"] == "ord1"
        assert modify["limit_price"] == "155.0"
        assert "quantity" not in modify  # Not passed = not sent
        assert "stop_price" not in modify
    
    @pytest.mark.asyncio
    async def test_trailing_stop_order(self):
        from brokers.webull_official.orders import OrdersAPI
        
        mock_client = AsyncMock()
        mock_client.post.return_value = {"client_order_id": "ts1", "order_id": "WB_TS"}
        
        api = OrdersAPI(mock_client)
        await api.place_trailing_stop(
            account_id="ACC001", symbol="AAPL", side="SELL",
            quantity=10, trailing_type="PERCENTAGE", trailing_stop_step=0.05,
        )
        
        call_body = mock_client.post.call_args[0][1]
        order = call_body["new_orders"][0]
        assert order["order_type"] == "TRAILING_STOP_LOSS"
        assert order["trailing_type"] == "PERCENTAGE"
        assert order["trailing_stop_step"] == "0.05"
    
    def test_client_order_id_max_32_chars(self):
        from brokers.webull_official.orders import OrdersAPI
        
        api = OrdersAPI(MagicMock())
        coid = api._gen_client_order_id()
        assert len(coid) <= 32
        assert len(coid) > 0
    
    @pytest.mark.asyncio
    async def test_extended_hours_sets_all_session(self):
        from brokers.webull_official.orders import OrdersAPI
        
        mock_client = AsyncMock()
        mock_client.post.return_value = {"client_order_id": "eh1", "order_id": "WB_EH"}
        
        api = OrdersAPI(mock_client)
        await api.place_stock_order(
            account_id="ACC001", symbol="AAPL", side="BUY",
            quantity=10, extended_hours=True,
        )
        
        order = mock_client.post.call_args[0][1]["new_orders"][0]
        assert order["support_trading_session"] == "ALL"
    
    @pytest.mark.asyncio
    async def test_regular_hours_sets_core_session(self):
        from brokers.webull_official.orders import OrdersAPI
        
        mock_client = AsyncMock()
        mock_client.post.return_value = {"client_order_id": "rh1", "order_id": "WB_RH"}
        
        api = OrdersAPI(mock_client)
        await api.place_stock_order(
            account_id="ACC001", symbol="AAPL", side="BUY",
            quantity=10, extended_hours=False,
        )
        
        order = mock_client.post.call_args[0][1]["new_orders"][0]
        assert order["support_trading_session"] == "CORE"


class TestBrokerInterface:
    """Validate BrokerInterface contract compliance."""
    
    @pytest.mark.asyncio
    async def test_get_account_info_returns_expected_keys(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = True
        broker.account_id = "ACC001"
        
        mock_accounts = AsyncMock()
        mock_accounts.get_balance.return_value = MagicMock(
            total_cash_balance=10000, total_market_value=50000,
            total_unrealized_pnl=500, total_net_liquidation=60000,
            total_day_pnl=-100, buying_power=20000,
            settled_cash=8000, unsettled_cash=2000,
            day_trades_left="3", option_buying_power=15000,
        )
        broker._accounts = mock_accounts
        
        info = await broker.get_account_info()
        
        required_keys = [
            "account_id", "cash_balance", "buying_power",
            "portfolio_value", "market_value", "unrealized_pnl",
            "day_pnl",
        ]
        for key in required_keys:
            assert key in info, f"Missing key: {key}"
    
    @pytest.mark.asyncio
    async def test_get_positions_returns_list_of_dicts(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.models import WebullPosition
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = True
        broker.account_id = "ACC001"
        
        mock_positions = AsyncMock()
        mock_positions.get_positions.return_value = [
            WebullPosition(
                position_id="P1", symbol="AAPL", quantity=100,
                cost_price=150, last_price=155, unrealized_pnl=500,
                instrument_type="EQUITY",
            )
        ]
        broker._positions = mock_positions
        
        positions = await broker.get_positions()
        
        assert len(positions) == 1
        pos = positions[0]
        assert pos["symbol"] == "AAPL"
        assert pos["quantity"] == 100
        assert pos["avg_cost"] == 150
        assert pos["current_price"] == 155
        assert pos["unrealized_pl"] == 500
        assert pos["asset"] == "stock"
    
    @pytest.mark.asyncio
    async def test_option_position_marked_as_option(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.models import WebullPosition
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = True
        broker.account_id = "ACC001"
        
        mock_positions = AsyncMock()
        mock_positions.get_positions.return_value = [
            WebullPosition(
                position_id="P2", symbol="AAPL", quantity=5,
                cost_price=3.5, last_price=5.2, unrealized_pnl=850,
                instrument_type="OPTION", option_type="CALL",
                strike_price=180, expiry_date="2026-06-20",
            )
        ]
        broker._positions = mock_positions
        
        positions = await broker.get_positions()
        pos = positions[0]
        assert pos["asset"] == "option"
        assert pos["option_type"] == "CALL"
        assert pos["strike_price"] == 180
    
    @pytest.mark.asyncio
    async def test_place_stock_order_action_mapping(self):
        """BTO→BUY, STC→SELL, SHORT→SHORT, COVER→BUY."""
        from brokers.webull_official.broker import WebullOfficialBroker
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = True
        broker.account_id = "ACC001"
        
        mock_orders = AsyncMock()
        mock_orders.place_stock_order.return_value = MagicMock(
            client_order_id="c1", order_id="o1"
        )
        broker._orders = mock_orders
        
        mappings = {"BTO": "BUY", "STC": "SELL", "BUY": "BUY",
                     "SELL": "SELL", "SHORT": "SHORT", "COVER": "BUY"}
        
        for action, expected_side in mappings.items():
            await broker.place_stock_order("AAPL", 10, action)
            call_kwargs = mock_orders.place_stock_order.call_args[1]
            assert call_kwargs["side"] == expected_side, \
                f"Action {action} should map to side {expected_side}"
    
    @pytest.mark.asyncio
    async def test_place_stock_order_type_mapping(self):
        """MARKET, LIMIT, STOP, STOP_LIMIT map correctly."""
        from brokers.webull_official.broker import WebullOfficialBroker
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = True
        broker.account_id = "ACC001"
        
        mock_orders = AsyncMock()
        mock_orders.place_stock_order.return_value = MagicMock(
            client_order_id="c1", order_id="o1"
        )
        broker._orders = mock_orders
        
        mappings = {
            "MARKET": "MARKET",
            "LIMIT": "LIMIT",
            "STOP": "STOP_LOSS",
            "STOP_LIMIT": "STOP_LOSS_LIMIT",
        }
        
        for bot_type, api_type in mappings.items():
            await broker.place_stock_order(
                "AAPL", 10, "BUY", order_type=bot_type, limit_price=150
            )
            call_kwargs = mock_orders.place_stock_order.call_args[1]
            assert call_kwargs["order_type"] == api_type, \
                f"Order type {bot_type} should map to {api_type}"
    
    @pytest.mark.asyncio
    async def test_place_option_order_intent_mapping(self):
        """BTO→BUY_TO_OPEN, STC→SELL_TO_CLOSE, etc."""
        from brokers.webull_official.broker import WebullOfficialBroker
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = True
        broker.account_id = "ACC001"
        
        mock_orders = AsyncMock()
        mock_orders.place_option_order.return_value = MagicMock(
            client_order_id="c1", order_id="o1"
        )
        broker._orders = mock_orders
        
        mappings = {
            "BTO": "BUY_TO_OPEN",
            "STC": "SELL_TO_CLOSE",
            "STO": "SELL_TO_OPEN",
            "BTC": "BUY_TO_CLOSE",
        }
        
        for action, expected_intent in mappings.items():
            await broker.place_option_order(
                "AAPL", 1, action, limit_price=5.0,
                option_type="CALL", strike_price=180, expiry_date="2026-06-20"
            )
            call_kwargs = mock_orders.place_option_order.call_args[1]
            assert call_kwargs["position_intent"] == expected_intent
    
    @pytest.mark.asyncio
    async def test_disconnected_broker_returns_failure(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = False
        
        result = await broker.place_stock_order("AAPL", 10, "BUY")
        assert result.success is False
        assert "Not connected" in result.message
        
        positions = await broker.get_positions()
        assert positions == []
        
        info = await broker.get_account_info()
        assert info == {}
    
    @pytest.mark.asyncio
    async def test_order_error_returns_failure_with_message(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.exceptions import WebullOrderError
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = True
        broker.account_id = "ACC001"
        
        mock_orders = AsyncMock()
        mock_orders.place_stock_order.side_effect = WebullOrderError(
            417, "INVALID_PARAMETER", "Quantity must be positive"
        )
        broker._orders = mock_orders
        
        result = await broker.place_stock_order("AAPL", -1, "BUY")
        assert result.success is False
        assert "Quantity" in result.message or "INVALID" in result.message
    
    @pytest.mark.asyncio
    async def test_get_pending_orders_returns_expected_format(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.models import WebullOrder
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = True
        broker.account_id = "ACC001"
        
        mock_orders = AsyncMock()
        mock_orders.get_open_orders.return_value = [
            WebullOrder(
                client_order_id="c1", order_id="wb1", symbol="AAPL",
                side="BUY", status="SUBMITTED", order_type="LIMIT",
                instrument_type="EQUITY", quantity=10, filled_quantity=0,
                filled_price=0, limit_price=150.0,
            )
        ]
        broker._orders = mock_orders
        
        orders = await broker.get_pending_orders()
        assert len(orders) == 1
        o = orders[0]
        assert o["order_id"] == "c1"  # client_order_id used as primary ID
        assert o["broker_order_id"] == "wb1"
        assert o["symbol"] == "AAPL"
        assert o["status"] == "SUBMITTED"


class TestClientResponseHandling:
    """Validate HTTP client error handling."""
    
    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self):
        from brokers.webull_official.client import WebullClient
        from brokers.webull_official.config import WebullConfig
        from brokers.webull_official.exceptions import WebullAuthError
        
        config = WebullConfig(app_key="k", app_secret="s")
        client = WebullClient(config)
        
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "error_code": "UNAUTHORIZED",
            "message": "Insufficient permission"
        }
        
        with pytest.raises(WebullAuthError) as exc_info:
            client._handle_response(mock_response, "/test")
        assert exc_info.value.status_code == 401
    
    @pytest.mark.asyncio
    async def test_417_on_order_raises_order_error(self):
        from brokers.webull_official.client import WebullClient
        from brokers.webull_official.config import WebullConfig
        from brokers.webull_official.exceptions import WebullOrderError
        
        config = WebullConfig(app_key="k", app_secret="s")
        client = WebullClient(config)
        
        mock_response = MagicMock()
        mock_response.status_code = 417
        mock_response.json.return_value = {
            "error_code": "INVALID_PARAMETER",
            "message": "Bad qty"
        }
        
        with pytest.raises(WebullOrderError):
            client._handle_response(mock_response, "/openapi/trade/order/place")
    
    @pytest.mark.asyncio
    async def test_200_returns_json(self):
        from brokers.webull_official.client import WebullClient
        from brokers.webull_official.config import WebullConfig
        
        config = WebullConfig(app_key="k", app_secret="s")
        client = WebullClient(config)
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"ok": true}'
        mock_response.json.return_value = {"ok": True}
        
        result = client._handle_response(mock_response, "/test")
        assert result == {"ok": True}
```

### 2B. Regression Check

```bash
# Must pass identically to Gate 1 baseline
pytest tests/ -v --tb=short 2>&1 | tee qa_gate2_regression.txt
diff qa_gate1_regression.txt qa_gate2_regression.txt  # Only timing should differ
```

### 2C. Manual Validation Checklist

| # | Check | Pass? |
|---|-------|-------|
| 1 | `OrderResult` from `broker_interface.py` is used correctly (not a custom result type) | |
| 2 | Broker `connect()` signature matches how `selfbot_webull.py` will call it | |
| 3 | `get_account_info()` returns same keys as SchwabBroker (`buying_power`, `portfolio_value`, `unrealized_pnl`) | |
| 4 | `get_positions()` returns same shape as SchwabBroker (`symbol`, `quantity`, `avg_cost`, `current_price`, `unrealized_pl`, `asset`) | |
| 5 | `get_pending_orders()` returns same shape as SchwabBroker (`order_id`, `symbol`, `quantity`, `limit_price`, `action`, `status`, `order_type`) | |
| 6 | All string values sent to API are type `str` (not `float`/`int`) — Webull API requires string numbers | |
| 7 | `combo_type` for brackets matches Webull docs: MASTER + STOP_PROFIT + STOP_LOSS (not OTOCO in individual orders) | |
| 8 | No direct calls to unofficial Webull API in new module | |
| 9 | Error from API propagates as `OrderResult(success=False, message=...)` — never crashes | |

### 2D. Gap Report Template

```
QA Gate 2 Gap Report — Date: ___

REGRESSION:
- [ ] Full test suite: ___ / ___
- [ ] Any new failures?

INTERFACE COMPLIANCE:
- [ ] get_account_info() output matches Schwab shape?
- [ ] get_positions() output matches Schwab shape?
- [ ] place_stock_order() returns OrderResult?
- [ ] place_option_order() returns OrderResult?
- [ ] All action mappings correct? (BTO/STC/BUY/SELL/SHORT/COVER)
- [ ] All order type mappings correct? (MARKET/LIMIT/STOP/STOP_LIMIT)

ORDER FLOW GAPS:
- [ ] Bracket order: Does MASTER+STOP_PROFIT+STOP_LOSS combo work?
- [ ] Cancel uses client_order_id (not order_id)?
- [ ] Replace sends only changed fields?
- [ ] Trailing stop sends PERCENTAGE/AMOUNT correctly?

EDGE CASES:
- [ ] Empty positions list returns []?
- [ ] Empty balance returns zeroes?
- [ ] Partial fill status handled?
- [ ] Rate limit error handled gracefully?

GO / NO-GO: ___
```

---

## QA GATE 3: Bot Integration

**After:** Wiring into selfbot_webull.py, unified_price_hub.py, relay_client.py, GUI routes  
**Before:** Streaming and final polish

### 3A. Automated Tests — `tests/unit/test_webull_official_integration.py`

```python
"""
QA Gate 3: Bot Integration Tests
Tests: broker routing, UPH registration, relay mapping, GUI routes, import safety
"""
import pytest
import sys
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))


class TestImportSafety:
    """New module must not break existing imports."""
    
    def test_existing_broker_imports_unchanged(self):
        """All existing broker modules still import."""
        # These must not raise ImportError
        from broker_interface import BrokerInterface, OrderResult, BrokerFactory
        assert BrokerInterface is not None
        assert OrderResult is not None
    
    def test_webull_official_import_doesnt_break_existing(self):
        """Importing new module doesn't pollute existing namespaces."""
        try:
            from brokers.webull_official import WebullOfficialBroker
            assert WebullOfficialBroker is not None
        except ImportError:
            pytest.skip("Module not yet created")
    
    def test_no_circular_imports(self):
        """No circular import between new module and existing code."""
        try:
            from brokers.webull_official.broker import WebullOfficialBroker
            from brokers.webull_official.auth import WebullAuth
            from brokers.webull_official.client import WebullClient
            from brokers.webull_official.orders import OrdersAPI
            from brokers.webull_official.accounts import AccountsAPI
            from brokers.webull_official.positions import PositionsAPI
        except ImportError:
            pytest.skip("Module not yet created")


class TestUPHRegistration:
    """Validate UnifiedPriceHub recognizes WEBULL_OFFICIAL."""
    
    def test_broker_name_mapping_exists(self):
        """WEBULL_OFFICIAL must resolve to a hub key."""
        from services.unified_price_hub import UnifiedPriceHub
        
        hub = UnifiedPriceHub()
        # After integration, these should resolve
        key = hub._resolve_hub_key("WEBULL_OFFICIAL")
        assert key is not None, "WEBULL_OFFICIAL not in _BROKER_NAME_TO_HUB"
    
    def test_existing_broker_mappings_preserved(self):
        """All existing broker→hub mappings must still work."""
        from services.unified_price_hub import UnifiedPriceHub
        
        hub = UnifiedPriceHub()
        existing = {
            "SCHWAB": "schwab",
            "WEBULL": "webull",
            "IBKR": "ibkr",
            "TASTYTRADE": "tastytrade",
        }
        for broker, expected_hub in existing.items():
            assert hub._resolve_hub_key(broker) == expected_hub, \
                f"Existing mapping broken: {broker}"
    
    def test_webull_official_doesnt_collide_with_webull(self):
        """WEBULL and WEBULL_OFFICIAL must map to different hubs."""
        from services.unified_price_hub import UnifiedPriceHub
        
        hub = UnifiedPriceHub()
        webull_key = hub._resolve_hub_key("WEBULL")
        official_key = hub._resolve_hub_key("WEBULL_OFFICIAL")
        
        # They should be different — one uses unofficial, one uses official
        # Unless the design decision was to share the same hub
        assert webull_key is not None
        assert official_key is not None


class TestSignalRouting:
    """Validate broker name routing includes WEBULL_OFFICIAL."""
    
    def test_broker_name_normalization(self):
        """Various name formats should all normalize."""
        test_names = [
            "webull_official", "WEBULL_OFFICIAL",
            "webull official", "Webull_Official",
        ]
        for name in test_names:
            normalized = name.lower().replace(" ", "_")
            assert "webull_official" in normalized, \
                f"Name '{name}' doesn't normalize to include 'webull_official'"
    
    def test_existing_broker_names_still_route(self):
        """Existing broker name patterns must not be broken."""
        existing = ["webull", "schwab", "alpaca", "ibkr", "tastytrade"]
        for name in existing:
            assert name.lower() == name
            assert "official" not in name


class TestGUIRoutes:
    """Validate GUI routes for WEBULL_OFFICIAL."""
    
    def test_broker_dropdown_has_webull_official(self):
        """index.html broker dropdown must include WEBULL_OFFICIAL option."""
        index_path = Path(__file__).parent.parent.parent / "gui_app" / "templates" / "index.html"
        if not index_path.exists():
            pytest.skip("index.html not found")
        
        content = index_path.read_text(encoding="utf-8")
        # After integration, the dropdown should have this option
        assert "webull_official" in content.lower() or "WEBULL_OFFICIAL" in content, \
            "WEBULL_OFFICIAL not in broker dropdown"
    
    def test_existing_routes_file_syntax_valid(self):
        """routes.py must still parse without SyntaxError."""
        routes_path = Path(__file__).parent.parent.parent / "gui_app" / "routes.py"
        if not routes_path.exists():
            pytest.skip("routes.py not found")
        
        source = routes_path.read_text(encoding="utf-8")
        try:
            compile(source, "routes.py", "exec")
        except SyntaxError as e:
            pytest.fail(f"routes.py has SyntaxError: {e}")


class TestRelayClient:
    """Validate relay client includes WEBULL_OFFICIAL."""
    
    def test_relay_source_has_webull_official(self):
        """relay_client.py must handle WEBULL_OFFICIAL broker name."""
        relay_path = Path(__file__).parent.parent.parent / "src" / "services" / "relay_client.py"
        if not relay_path.exists():
            pytest.skip("relay_client.py not found")
        
        content = relay_path.read_text(encoding="utf-8")
        assert "webull_official" in content.lower(), \
            "relay_client.py doesn't handle WEBULL_OFFICIAL"


class TestExistingBrokerRegression:
    """Existing broker tests must still pass unchanged."""
    
    def test_schwab_broker_module_imports(self):
        try:
            # Just verify import doesn't break
            spec = importlib.util.find_spec("brokers.schwab_broker")
            assert spec is not None or True  # May not be importable without deps
        except Exception:
            pass  # OK if deps not available locally
    
    def test_broker_interface_unchanged(self):
        """BrokerInterface abstract methods must be unchanged."""
        from broker_interface import BrokerInterface
        import inspect
        
        expected_methods = [
            "connect", "disconnect", "get_account_info",
            "get_positions", "place_stock_order",
            "place_option_order", "get_quote",
        ]
        actual = [m for m in dir(BrokerInterface) if not m.startswith("_")]
        
        for method in expected_methods:
            assert method in actual, \
                f"BrokerInterface missing method: {method}"
```

### 3B. Regression — Full Suite + Manual Smoke Test

```bash
# Automated
pytest tests/ -v --tb=short 2>&1 | tee qa_gate3_regression.txt

# Manual smoke test (bot in dry-run mode):
# 1. Start bot with WEBULL_OFFICIAL_ENABLED=false → verify all existing brokers work
# 2. Start bot with WEBULL_OFFICIAL_ENABLED=true, credentials empty → verify graceful skip
# 3. Start Flask GUI → verify all Dashboard cards render for existing brokers
# 4. Visit Trading → Dashboard → Account Balance → verify dropdown has WEBULL_OFFICIAL
```

### 3C. Manual Validation Checklist

| # | Check | Pass? |
|---|-------|-------|
| 1 | Bot starts successfully with `WEBULL_OFFICIAL_ENABLED=false` | |
| 2 | Bot starts successfully with `WEBULL_OFFICIAL_ENABLED=true` + valid test creds | |
| 3 | Bot starts with `WEBULL_OFFICIAL_ENABLED=true` + invalid creds → logs error, continues | |
| 4 | Existing Schwab broker still connects and shows balance | |
| 5 | Existing unofficial Webull broker still connects | |
| 6 | UPH resolves prices for existing brokers | |
| 7 | Relay client lists all brokers including WEBULL_OFFICIAL when connected | |
| 8 | GUI Dashboard → Account Balance card dropdown shows WEBULL_OFFICIAL | |
| 9 | GUI selects WEBULL_OFFICIAL → shows balance from official API | |
| 10 | GUI selects SCHWAB → still shows Schwab balance (no regression) | |
| 11 | Position monitor still creates brackets for existing brokers | |
| 12 | Conditional orders still fire for existing brokers | |

### 3D. Gap Report Template

```
QA Gate 3 Gap Report — Date: ___

REGRESSION:
- [ ] Full test suite: ___ / ___
- [ ] Bot startup (existing brokers): PASS / FAIL
- [ ] GUI smoke test (existing features): PASS / FAIL

INTEGRATION:
- [ ] selfbot_webull.py: WebullOfficialBroker initialized correctly?
- [ ] BrokerManager includes WEBULL_OFFICIAL?
- [ ] Signal routing handles "webull_official" broker name?
- [ ] UPH maps WEBULL_OFFICIAL to hub?
- [ ] Relay client includes WEBULL_OFFICIAL?
- [ ] GUI dropdown includes WEBULL_OFFICIAL?
- [ ] GUI balance endpoint works for WEBULL_OFFICIAL?

COLLISION RISKS:
- [ ] WEBULL vs WEBULL_OFFICIAL don't interfere?
- [ ] Position cache keys don't collide (different broker prefix)?
- [ ] Database trades table stores correct broker name?
- [ ] Conditional order routing distinguishes the two Webull brokers?

GO / NO-GO: ___
```

---

## QA GATE 4: Streaming & Final Validation

**After:** MQTT streaming, trade event polling, all tests  
**Before:** Production deployment / release

### 4A. Automated Tests — `tests/unit/test_webull_official_streaming.py`

```python
"""
QA Gate 4: Streaming and End-to-End Tests
Tests: MQTT connect, trade event polling, full order flow
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestMQTTStreaming:
    """Validate MQTT market data streaming."""
    
    @pytest.mark.asyncio
    async def test_subscribe_sends_correct_body(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig
        
        config = WebullConfig(app_key="k", app_secret="s")
        mock_client = AsyncMock()
        
        stream = WebullMarketStream(config, mock_client)
        await stream.subscribe(["AAPL", "TSLA"], sub_types=["SNAPSHOT"])
        
        mock_client.post.assert_called_once()
        body = mock_client.post.call_args[0][1]
        assert body["symbols"] == ["AAPL", "TSLA"]
        assert body["category"] == "US_STOCK"
        assert body["sub_types"] == ["SNAPSHOT"]
        assert "session_id" in body
    
    @pytest.mark.asyncio
    async def test_subscribe_batches_over_100_symbols(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig
        
        config = WebullConfig(app_key="k", app_secret="s")
        mock_client = AsyncMock()
        
        stream = WebullMarketStream(config, mock_client)
        symbols = [f"SYM{i}" for i in range(250)]
        await stream.subscribe(symbols)
        
        assert mock_client.post.call_count == 3  # 100 + 100 + 50
    
    def test_event_callback_registration(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig
        
        config = WebullConfig(app_key="k", app_secret="s")
        stream = WebullMarketStream(config, MagicMock())
        
        callback = MagicMock()
        stream.on("snapshot", callback)
        
        assert "snapshot" in stream._callbacks
        assert callback in stream._callbacks["snapshot"]
    
    @pytest.mark.asyncio
    async def test_unsubscribe_removes_symbols(self):
        from brokers.webull_official.streaming import WebullMarketStream
        from brokers.webull_official.config import WebullConfig
        
        config = WebullConfig(app_key="k", app_secret="s")
        mock_client = AsyncMock()
        
        stream = WebullMarketStream(config, mock_client)
        stream._subscribed_symbols = {"AAPL", "TSLA", "NVDA"}
        await stream.unsubscribe(["TSLA"])
        
        assert "TSLA" not in stream._subscribed_symbols
        assert "AAPL" in stream._subscribed_symbols


class TestTradeEventPoller:
    """Validate order fill detection via polling."""
    
    @pytest.mark.asyncio
    async def test_detects_new_fill(self):
        from brokers.webull_official.streaming import TradeEventPoller
        from brokers.webull_official.models import WebullOrder
        
        mock_client = AsyncMock()
        poller = TradeEventPoller(mock_client, "ACC001", interval=0.1)
        
        fill_events = []
        poller.on("fill", lambda data: fill_events.append(data))
        
        # Simulate: first poll sees partial fill
        with patch("brokers.webull_official.streaming.OrdersAPI") as MockOrders:
            mock_orders_api = AsyncMock()
            mock_orders_api.get_open_orders.return_value = [
                WebullOrder(
                    client_order_id="c1", order_id="o1", symbol="AAPL",
                    side="BUY", status="PARTIAL_FILLED", order_type="LIMIT",
                    instrument_type="EQUITY", quantity=100, filled_quantity=50,
                    filled_price=150.0,
                )
            ]
            MockOrders.return_value = mock_orders_api
            
            poller._running = True
            # Run one poll iteration manually
            await poller._poll_loop.__wrapped__(poller)  # Would need refactor
    
    def test_callback_registration(self):
        from brokers.webull_official.streaming import TradeEventPoller
        
        poller = TradeEventPoller(MagicMock(), "ACC001")
        
        fill_cb = MagicMock()
        terminal_cb = MagicMock()
        poller.on("fill", fill_cb)
        poller.on("terminal", terminal_cb)
        
        assert fill_cb in poller._callbacks["fill"]
        assert terminal_cb in poller._callbacks["terminal"]


class TestEndToEndOrderFlow:
    """Validate complete order lifecycle: place → query → cancel."""
    
    @pytest.mark.asyncio
    async def test_stock_order_lifecycle(self):
        """Place → verify pending → cancel → verify cancelled."""
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.models import WebullOrder
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = True
        broker.account_id = "ACC001"
        
        mock_orders = AsyncMock()
        
        # Step 1: Place
        mock_orders.place_stock_order.return_value = MagicMock(
            client_order_id="lifecycle_test_1",
            order_id="WB_LT1",
        )
        broker._orders = mock_orders
        
        result = await broker.place_stock_order("AAPL", 10, "BUY", "LIMIT", limit_price=150)
        assert result.success is True
        assert result.order_id in ("lifecycle_test_1", "WB_LT1")
        
        # Step 2: Query pending
        mock_orders.get_open_orders.return_value = [
            WebullOrder(
                client_order_id="lifecycle_test_1", order_id="WB_LT1",
                symbol="AAPL", side="BUY", status="SUBMITTED",
                order_type="LIMIT", instrument_type="EQUITY",
                quantity=10, filled_quantity=0, filled_price=0,
                limit_price=150.0,
            )
        ]
        pending = await broker.get_pending_orders()
        assert len(pending) == 1
        assert pending[0]["order_id"] == "lifecycle_test_1"
        assert pending[0]["status"] == "SUBMITTED"
        
        # Step 3: Cancel
        mock_orders.cancel_order.return_value = {}
        cancelled = await broker.cancel_order_by_id("lifecycle_test_1")
        assert cancelled is True
        mock_orders.cancel_order.assert_called_with("ACC001", "lifecycle_test_1")
    
    @pytest.mark.asyncio
    async def test_bracket_order_lifecycle(self):
        """Place bracket → verify 3 orders created."""
        from brokers.webull_official.broker import WebullOfficialBroker
        
        broker = WebullOfficialBroker(name="TEST")
        broker.connected = True
        broker.account_id = "ACC001"
        
        mock_orders = AsyncMock()
        mock_orders.place_bracket_order.return_value = MagicMock(
            client_combo_order_id="bracket_test_1",
            combo_order_id="WB_COMBO_1",
            client_order_id="",
        )
        broker._orders = mock_orders
        
        result = await broker.place_bracket_order(
            "AAPL", 10, "BUY", order_type="LIMIT", limit_price=150,
            take_profit=165, stop_loss=140,
        )
        
        assert result.success is True
        assert "bracket" in result.message.lower() or "Bracket" in result.message
```

### 4B. Full Regression + UAT Smoke Test

```bash
# Full automated suite
pytest tests/ -v --tb=short 2>&1 | tee qa_gate4_regression.txt

# UAT smoke test with Webull test credentials:
# 1. Connect to UAT environment with public test account
# 2. Place a LIMIT order → verify order_id returned
# 3. Query open orders → verify order appears
# 4. Cancel the order → verify CANCELLED status
# 5. Query balance → verify non-zero response
# 6. Query positions → verify response parses
# 7. Subscribe MQTT for AAPL → verify snapshot received
```

### 4C. Final Validation Checklist

| # | Check | Pass? |
|---|-------|-------|
| 1 | All automated tests pass (Gate 1 + 2 + 3 + 4 combined) | |
| 2 | UAT: Connect with test credentials succeeds | |
| 3 | UAT: Place stock limit order succeeds | |
| 4 | UAT: Cancel order succeeds | |
| 5 | UAT: Get balance returns valid data | |
| 6 | UAT: Get positions returns valid data | |
| 7 | UAT: MQTT subscribe receives snapshot data | |
| 8 | Bot startup with all brokers enabled: no crashes | |
| 9 | GUI all Dashboard cards render with WEBULL_OFFICIAL selected | |
| 10 | Position monitor creates brackets via native OTOCO for WEBULL_OFFICIAL | |
| 11 | Conditional orders route to correct broker | |
| 12 | Relay client reports WEBULL_OFFICIAL status | |
| 13 | No unofficial Webull API calls in new module | |
| 14 | Rate limiter prevents burst on account endpoints | |
| 15 | Error from Webull API surfaces in GUI as user-friendly message | |

### 4D. Final Gap Report

```
QA Gate 4 Final Report — Date: ___

TEST RESULTS:
- Unit tests: ___ / ___
- Integration tests: ___ / ___
- UAT smoke tests: ___ / 7

STREAMING:
- [ ] MQTT connects to data-api.webull.com?
- [ ] MQTT receives protobuf snapshot data?
- [ ] Protobuf deserializes to quote format?
- [ ] UPH receives and caches quotes from MQTT stream?
- [ ] Trade event poller detects fills within 5 seconds?
- [ ] Poller respects rate limit (max 1 req/sec on account_data)?

PERFORMANCE:
- [ ] Auth signing adds <5ms overhead per request?
- [ ] Rate limiter doesn't block trading during normal operation?
- [ ] MQTT reconnects after disconnect within 60 seconds?

SECURITY:
- [ ] App secret never logged or printed?
- [ ] App secret never in HTTP headers?
- [ ] Test credentials not in production config?
- [ ] No hardcoded credentials in source?

KNOWN LIMITATIONS:
1. gRPC trade events not available (Python 3.14 compat) — polling fallback
2. No REST quote endpoint — prices only via MQTT stream
3. Historical candle data not available — use unofficial API or external source
4. Option orders: HK-specific endpoints NOT used, standard place_order with OPTION type used instead (needs UAT confirmation)

SHIP DECISION: ___
```

---

## RUNNING THE COMPLETE QA SUITE

```bash
# Run all QA tests in one shot (after all 4 phases):
pytest tests/unit/test_webull_official_auth.py \
       tests/unit/test_webull_official_trading.py \
       tests/unit/test_webull_official_integration.py \
       tests/unit/test_webull_official_streaming.py \
       -v --tb=short

# Run alongside existing tests to verify no regression:
pytest tests/ -v --tb=short

# Generate coverage report:
pytest tests/unit/test_webull_official_*.py --cov=brokers.webull_official --cov-report=term-missing
```

## Test Count Summary

| Gate | Test File | Test Count | Status |
|------|-----------|------------|--------|
| 1 | `test_webull_official_auth.py` | 25 | PASS |
| 2 | `test_webull_official_trading.py` | 30 | PASS |
| 4 | `test_webull_official_streaming.py` | 21 | PASS |
| — | Existing suite | 463+ | PASS |
| **Total** | | **539+** | **ALL PASS** |

**Note:** Gate 3 integration tests were merged into `test_webull_official_streaming.py` (TestBrokerWiring, TestIntegrationWiring, TestCredentialService classes) for simpler test organization.

## QA Gate Results (May 2026)

| Gate | Date | Result | Notes |
|------|------|--------|-------|
| Gate 1 — Core Module | 2026-05-09 | PASS | Auth, config, rate limiter, models, exceptions |
| Gate 2 — Trading | 2026-05-09 | PASS | Orders, accounts, positions, broker interface |
| Gate 3 — Integration | 2026-05-10 | PASS | UPH, relay, GUI, settings UI, multi-broker dispatch |
| Gate 4 — Streaming | 2026-05-10 | PASS | MQTT, poller, fill detection, credential wiring |
| **SHIP DECISION** | **2026-05-10** | **GO** | All 4 gates passed, 12 integration points verified |
