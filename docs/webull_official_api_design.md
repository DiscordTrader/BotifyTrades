# Webull Official API Integration — Complete Design Document

**Date:** 2026-05-09  
**Author:** Architecture Review  
**Status:** Design Phase  

---

## TASK 1: DOCUMENTATION REVIEW

### 1. Authentication Mechanism

**Type:** HMAC-SHA1 per-request signature (stateless — no session cookies or bearer tokens for standard API)

**Every request requires 7 headers:**

| Header | Value |
|--------|-------|
| `x-app-key` | Developer app key |
| `x-timestamp` | ISO 8601 UTC: `YYYY-MM-DDThh:mm:ssZ` |
| `x-signature` | HMAC-SHA1 signature (computed per request) |
| `x-signature-algorithm` | `HMAC-SHA1` |
| `x-signature-version` | `1.0` |
| `x-signature-nonce` | Unique UUID hex per request |
| `x-version` | `v2` |

**Signature Algorithm (3 steps):**

1. **Build sign string:**
   - Merge query params + 6 signing headers (`x-app-key`, `x-timestamp`, `x-signature-algorithm`, `x-signature-version`, `x-signature-nonce`, `host`) → sort alphabetically → join as `key1=value1&key2=value2&...` = `str1`
   - If POST body exists: `str2 = toUpperCase(MD5(compact_json_body))` (separators `(',',':')`)
   - `str3 = path + "&" + str1` (+ `"&" + str2` if body exists)
   - URL-encode `str3` → `encoded_string`

2. **Key:** `app_secret + "&"` (trailing ampersand required)

3. **Signature:** `base64(HMAC-SHA1(key, encoded_string))`

**Critical note:** `x-app-secret` appears in some OpenAPI specs as a header parameter but is NEVER sent as a header — it's only used client-side for signing. The `x-signature` and `x-version` headers do NOT participate in signing.

### 2. Required Permissions / Scopes

**No granular scopes.** Access is app-level — your `app_key`/`app_secret` pair grants full access to all endpoints for all linked accounts. There is no OAuth scope system for the standard API.

**OAuth Connect API** (separate path for third-party apps managing other users' accounts):
- Uses `/oauth-openapi/` prefix instead of `/openapi/`
- Authorization Code → Access Token (30 min) → Refresh Token (15 days)
- **Not needed for BotifyTrades** — we use direct app credentials

### 3. Account Management APIs

| Endpoint | Method | Path | Rate Limit |
|----------|--------|------|------------|
| Account List | GET | `/openapi/account/list` | 10 req/30s |
| Account Balance | GET | `/openapi/assets/balance` | 2 req/2s |
| Account Positions | GET | `/openapi/assets/positions` | 2 req/2s |

**Account types returned:** MARGIN, CASH  
**Account classes:** INDIVIDUAL_CASH, INDIVIDUAL_MARGIN, ROTH_IRA, TRADITIONAL_IRA, ROLLOVER_IRA, MANAGED_ROTH_IRA, MANAGED_TRADITIONAL_IRA, CRYPTO, FUTURES, EVENTS_CASH

**Balance response gives:** total_cash_balance, total_market_value, total_unrealized_profit_loss, total_net_liquidation_value, total_day_profit_loss, day_trades_left, buying_power, settled_cash, unsettled_cash, margin fields, plus per-currency breakdown.

### 4. Trading / Order Placement APIs

| Endpoint | Method | Path | Rate Limit |
|----------|--------|------|------------|
| Place Order | POST | `/openapi/trade/order/place` | 600 req/min |
| Batch Place | POST | `/openapi/trade/order/batch-place` | 600 req/min |
| Preview Order | POST | `/openapi/trade/order/preview` | — |
| Replace Order | POST | `/openapi/trade/order/replace` | 600 req/min |
| Cancel Order | POST | `/openapi/trade/order/cancel` | 600 req/min |

**Supported order types:** MARKET, LIMIT, STOP_LOSS, STOP_LOSS_LIMIT, TRAILING_STOP_LOSS, MARKET_ON_OPEN (institutional), MARKET_ON_CLOSE (institutional), LIMIT_ON_OPEN (institutional)

**Supported instruments:** EQUITY, OPTION, FUTURES, CRYPTO, EVENT

**Native bracket orders via `combo_type`:**
- `NORMAL` — Single order
- `MASTER` — Primary with TP/SL attached
- `STOP_PROFIT` — Take-profit leg
- `STOP_LOSS` — Stop-loss leg
- `OTO` — One-Triggers-Other
- `OCO` — One-Cancels-Other
- `OTOCO` — One-Triggers-OCO (full bracket in one call)

**Option support via standard place order:**
- `instrument_type: "OPTION"` with `option_strategy` + `legs[]`
- Strategies: SINGLE, COVERED_STOCK, VERTICAL, STRADDLE, STRANGLE, CALENDAR, BUTTERFLY, CONDOR, IRON_BUTTERFLY, IRON_CONDOR, COLLAR_WITH_STOCK, DIAGONAL
- `position_intent`: BUY_TO_OPEN, BUY_TO_CLOSE, SELL_TO_OPEN, SELL_TO_CLOSE

> **CRITICAL FINDING:** The v2 API handles options through the standard `/openapi/trade/order/place` endpoint with `instrument_type: "OPTION"`. The SDK's separate `place_option()` / `cancel_option()` methods (in `webullsdktrade/request/v2/`) are HK-only, but the generic place order with OPTION instrument type works for US clients. This is confirmed by the API docs listing OPTION in the instrument_type enum for the standard endpoints.

### 5. Market Data APIs

| Endpoint | Method | Path | Rate Limit |
|----------|--------|------|------------|
| Subscribe (MQTT) | POST | `/openapi/market-data/streaming/subscribe` | 600 req/min |
| Unsubscribe (MQTT) | POST | `/openapi/market-data/streaming/unsubscribe` | — |

**MQTT Streaming:**
- Protocol: MQTT v3.1.1 over TCP (`data-api.webull.com:1883`) or WebSocket (`wss://data-api.webull.com:8883/mqtt`)
- Max 5 concurrent connections per App Key
- Max 100 symbols per subscribe call
- Max push rate: 3 msgs/sec/connection
- Categories: `US_STOCK`, `US_ETF`
- Sub types: `QUOTE` (order book), `SNAPSHOT` (market data), `TICK` (tick-by-tick)
- Data format: **Protobuf** (not JSON) for quote/snapshot/tick topics
- `notice` topic: JSON for server notifications
- `echo` topic: Heartbeat

**Snapshot protobuf fields:** symbol, instrument_id, timestamp, price, open, high, low, pre_close, volume, change, change_ratio, ext_price, ext_volume, ovn_price, ovn_volume

**Quote protobuf fields:** asks[]{price, size}, bids[]{price, size} — up to 50 levels for US stocks

### 6. Order Management (Cancel, Modify, Status)

**Cancel:** POST `/openapi/trade/order/cancel` with `{account_id, client_order_id}`
- Uses the client-assigned `client_order_id`, NOT the broker `order_id`
- Returns confirmation with both IDs

**Replace/Modify:** POST `/openapi/trade/order/replace` with `{account_id, modify_orders[]}`
- Can modify: `time_in_force`, `stop_price`, `limit_price`, `quantity`, `order_type`, `trailing_type`, `trailing_stop_step`
- **Crypto NOT supported** for replace
- Futures have restrictions on what fields can be modified per order type

**Order status values:** PENDING, SUBMITTED, CANCELLED, FILLED, FAILED, PARTIAL_FILLED

### 7. Position Management APIs

**GET** `/openapi/assets/positions?account_id=<id>`

Response per position:
- `position_id`, `symbol`, `quantity`, `cost_price`, `last_price`, `unrealized_profit_loss`
- `instrument_type`: EQUITY, OPTION, FUTURES, CRYPTO, EVENT
- `currency`: USD
- For options: `option_strategy`, `legs[]` with strike_price, option_expire_date, option_type (CALL/PUT), option_contract_multiplier

This gives us **everything needed** for the Dashboard positions card and PnL tracking.

### 8. Execution / Fill Reporting

**Order Detail:** GET `/openapi/trade/order/detail?account_id=<id>&client_order_id=<id>`
- Returns `filled_quantity`, `filled_price`, `filled_time`, `filled_time_at` (ISO)

**Order History:** GET `/openapi/trade/order/history?account_id=<id>&start_date=&end_date=&page_size=`
- Max lookback: 2 years
- Default: last 7 days
- Page size: max 100

**gRPC Trade Events:** Real-time fill notifications (see #9)

There is **no separate executions/fills endpoint** — fill data comes from order detail/history or gRPC events.

### 9. Streaming / WebSocket Capabilities

**Two streaming channels:**

| Channel | Protocol | Purpose | Endpoint |
|---------|----------|---------|----------|
| Market Data | MQTT v3.1.1 | Quotes, snapshots, ticks | `data-api.webull.com:1883` (TCP) or `:8883/mqtt` (WSS) |
| Trade Events | gRPC Server Streaming | Order fills, cancels, fails | `events-api.webull.com` |

**gRPC Trade Events:**
- Subscribe types: `1` (order status changes), `2` (position events/settlements)
- Event types: SubscribeSuccess, Ping, AuthError, NumOfConnExceed, SubscribeExpired
- Scene types in payload: FILLED, FINAL_FILLED, PLACE_FAILED, MODIFY_SUCCESS, MODIFY_FAILED, CANCEL_SUCCESS, CANCEL_FAILED
- Payload fields: account_id, client_order_id, instrument_id, order_status, symbol, qty, filled_price, filled_qty, filled_time, side, scene_type

**MQTT Connection:**
- ClientId = unique `session_id`
- User Name = App Key
- Password = any value
- After disconnect, server retains state ~1 minute

### 10. Rate Limiting Policies

| Endpoint Category | Limit |
|-------------------|-------|
| Place/Replace/Cancel Order | 600 req/min (10/sec) |
| Market Data Subscribe | 600 req/min |
| Account Balance/Positions | 2 req/2 sec (1/sec) |
| Order History/Open Orders/Detail | 2 req/2 sec (1/sec) |
| Token Create/Check | 10 req/30 sec |
| Account List | 10 req/30 sec |
| MQTT push rate | 3 msg/sec/connection |
| MQTT connections | 5 per App Key |

**Compared to unofficial API:** Official rate limits are MORE generous for trading (600/min vs ~1/sec) but STRICTER for account data (2/2s vs unlimited).

### 11. Sandbox / Test Environment

| Service | Production | Test/UAT |
|---------|-----------|----------|
| HTTP API | `api.webull.com` | `us-openapi-alb.uat.webullbroker.com` |
| Trade Events | `events-api.webull.com` | `us-openapi-events.uat.webullbroker.com` |
| Market Data | `data-api.webull.com` | (same/not specified) |

**Test accounts available (shared, public):**

| Account ID | App Key | App Secret |
|------------|---------|------------|
| `J6HA4EBQRQFJD2J6NQH0F7M649` | `a88f2efed4dca02b9bc1a3cecbc35dba` | `c2895b3526cc7c7588758351ddf425d6` |
| `HBGQE8NM0CQG4Q34ABOM83HD09` | `6d9f1a0aa919a127697b567bb704369e` | `adb8931f708ea3d57ec1486f10abf58c` |
| `4BJITU00JUIVEDO5V3PRA5C5G8` | `eecbf4489f460ad2f7aecef37b267618` | `8abf920a9cc3cb7af3ea5e9e03850692` |

Test environment tokens are auto-valid — no 2FA needed. This enables proper integration testing without risking real money.

### 12. Required Headers

**Every request (7 mandatory):**
```
x-app-key: <app_key>
x-timestamp: 2026-05-09T14:30:00Z
x-signature: <computed_hmac>
x-signature-algorithm: HMAC-SHA1
x-signature-version: 1.0
x-signature-nonce: <uuid_hex>
x-version: v2
Content-Type: application/json  (POST requests)
```

**Optional:**
- `x-access-token`: Required only if 2FA is enabled
- `category`: Rate limit classification (e.g., `US_STOCK`)

### 13. Token Refresh Mechanism

**Standard API:** No token refresh needed. HMAC-SHA1 signing is stateless — each request is independently signed. No session tokens expire.

**2FA Token (optional):**
- Created via POST `/openapi/auth/token/create`
- Status lifecycle: PENDING → (verify via Webull App SMS within 5 min) → NORMAL → (15 days no API calls) → INVALID
- Check status via POST `/openapi/auth/token/check`
- If INVALID, create a new token

**OAuth Connect API tokens (not needed for BotifyTrades):**
- Access Token: 30 minutes
- Refresh Token: 15 days

**Impact on BotifyTrades:** With standard API authentication (no 2FA), there are **zero token refresh concerns**. The app_key + app_secret are permanent credentials. This is a massive simplification compared to Schwab's OAuth token refresh dance.

### 14. Retail vs Institutional Limitations

| Feature | Retail | Institutional |
|---------|--------|---------------|
| MARKET_ON_OPEN | No | Yes |
| MARKET_ON_CLOSE | No | Yes |
| LIMIT_ON_OPEN | No | Yes |
| Algo orders (TWAP/VWAP/POV) | No | Yes |
| All other order types | Yes | Yes |
| Options (SINGLE leg) | Yes | Yes |
| Options (multi-leg strategies) | Yes | Yes |
| Bracket orders (OCO/OTO/OTOCO) | Yes | Yes |
| Fractional shares | Yes (MARKET only, min $5) | Yes |
| Extended hours | Yes (ALL session) | Yes |

**Key limitation for BotifyTrades:** MOO/MOC orders are institutional-only. Since BotifyTrades doesn't use these, no impact.

### 15. Undocumented / Poorly Documented Areas

1. **Instrument lookup / symbol search:** No documented endpoint for searching symbols or getting instrument details by ticker. The API uses `symbol` string directly — no `instrument_id` needed for v2 API. However, option symbols follow a specific format that is not fully documented (the `legs[]` array uses individual fields: symbol, strike_price, option_expire_date, option_type instead of OCC-format symbols).

2. **Webhook vs polling for fills:** The gRPC trade event stream is documented at the proto level but lacks practical examples for Python. The `grpcio` package is required but doesn't build on Python 3.14. Fallback strategy: poll `/openapi/trade/order/open` + `/openapi/trade/order/detail`.

3. **MQTT protobuf schemas:** The protobuf message definitions are documented but the `.proto` files are not provided as downloadable artifacts. You need to reconstruct them from the documentation.

4. **Batch order response format:** The `/openapi/trade/order/batch-place` endpoint is mentioned but its request/response schema is not fully documented separate from the single place order.

5. **Option exercise/assignment:** No documented endpoint for option exercise or assignment handling.

6. **Transfer/deposit/withdrawal:** No documented endpoints for fund transfers.

7. **Historical market data:** No documented REST endpoint for historical OHLCV bars (candles). Only real-time streaming via MQTT.

8. **Fractional shares quantity format:** Documentation says "between 0 (exclusive) and 1 (inclusive)" for fractional, but doesn't clarify decimal precision limits for stocks (crypto is 8 decimals).

---

## TASK 2: FEATURE MAPPING TABLE

| # | BotifyTrades Feature | Webull Official API Endpoint | Method | Notes |
|---|---------------------|------------------------------|--------|-------|
| 1 | **Connect / Authenticate** | HMAC-SHA1 signing per request | N/A | No connect call — stateless auth. Validate with `/openapi/account/list` |
| 2 | **Get account info / balance** | `/openapi/assets/balance?account_id=` | GET | Returns cash, market_value, buying_power, unrealized_pnl, day_pnl, margin info |
| 3 | **Get account list** | `/openapi/account/list` | GET | Returns account_id, type, class for all linked accounts |
| 4 | **Get positions** | `/openapi/assets/positions?account_id=` | GET | Returns position_id, symbol, qty, cost_price, last_price, unrealized_pnl, legs[] |
| 5 | **Place stock MARKET order** | `/openapi/trade/order/place` | POST | `instrument_type:"EQUITY", order_type:"MARKET", combo_type:"NORMAL"` |
| 6 | **Place stock LIMIT order** | `/openapi/trade/order/place` | POST | `instrument_type:"EQUITY", order_type:"LIMIT", limit_price:"..."` |
| 7 | **Place option BTO** | `/openapi/trade/order/place` | POST | `instrument_type:"OPTION", position_intent:"BUY_TO_OPEN", option_strategy:"SINGLE", legs:[{...}]` |
| 8 | **Place option STC** | `/openapi/trade/order/place` | POST | `instrument_type:"OPTION", position_intent:"SELL_TO_CLOSE", legs:[{...}]` |
| 9 | **Place option BTO spread** | `/openapi/trade/order/place` | POST | `option_strategy:"VERTICAL"/"IRON_CONDOR"/etc, legs:[{...},{...}]` |
| 10 | **Cancel order** | `/openapi/trade/order/cancel` | POST | `{account_id, client_order_id}` — uses CLIENT order ID |
| 11 | **Modify / replace order** | `/openapi/trade/order/replace` | POST | Can modify price, qty, TIF, order_type. Crypto NOT supported |
| 12 | **Get open orders** | `/openapi/trade/order/open?account_id=` | GET | Returns pending/submitted orders with status, fill info |
| 13 | **Get order status / detail** | `/openapi/trade/order/detail?account_id=&client_order_id=` | GET | Single order lookup by client_order_id |
| 14 | **Get order history** | `/openapi/trade/order/history?account_id=&start_date=&end_date=` | GET | Up to 2 years lookback, paginated (max 100/page) |
| 15 | **Place bracket (PT + SL)** | `/openapi/trade/order/place` | POST | `combo_type:"OTOCO"` with MASTER + STOP_PROFIT + STOP_LOSS legs |
| 16 | **Place OCO order** | `/openapi/trade/order/place` | POST | `combo_type:"OCO"` with two linked orders |
| 17 | **Place OTO order** | `/openapi/trade/order/place` | POST | `combo_type:"OTO"` — primary triggers secondary |
| 18 | **Place trailing stop** | `/openapi/trade/order/place` | POST | `order_type:"TRAILING_STOP_LOSS", trailing_type:"AMOUNT"/"PERCENTAGE", trailing_stop_step:"..."` |
| 19 | **Get quotes / prices** | MQTT subscribe → SNAPSHOT | MQTT | `/openapi/market-data/streaming/subscribe` then listen on MQTT |
| 20 | **Stream real-time prices** | MQTT subscribe → QUOTE/TICK | MQTT | Protobuf on `quote`/`tick` topics, max 100 symbols |
| 21 | **Stream order events** | gRPC server streaming | gRPC | `events-api.webull.com`, subscribeType=1 for order fills |
| 22 | **Extended hours trading** | `support_trading_session: "ALL"` | — | Field on place order; stocks only |
| 23 | **Position P&L tracking** | `/openapi/assets/positions` | GET | `unrealized_profit_loss` per position + `cost_price` + `last_price` |
| 24 | **Account balance monitoring** | `/openapi/assets/balance` | GET | `total_unrealized_profit_loss`, `total_day_profit_loss`, buying_power |
| 25 | **Fractional shares** | `/openapi/trade/order/place` | POST | MARKET only, qty between 0-1, min $5 value, `entrust_type:"QTY"` or `"AMOUNT"` |
| 26 | **Paper / sandbox trading** | UAT environment | — | `us-openapi-alb.uat.webullbroker.com` with test credentials |
| 27 | **Bulk order placement** | `/openapi/trade/order/batch-place` | POST | Multiple orders in single call |
| 28 | **Order fill notifications** | gRPC trade events | gRPC | scene_type: FILLED, FINAL_FILLED with filled_price, filled_qty |
| 29 | **Rate limit management** | Response headers / local tracking | — | Must implement client-side token bucket per endpoint category |
| 30 | **Conditional orders (position monitor)** | Native OCO/OTO/OTOCO | POST | Replaces client-side conditional order engine for bracket exits |

### Feature Gap Analysis

| BotifyTrades Need | Official API Status | Workaround |
|-------------------|-------------------|------------|
| Option symbol lookup (OCC format → legs) | No symbol search endpoint | Parse OCC symbol locally: extract underlying, expiry, type, strike → populate `legs[]` |
| Historical price bars | Not available via REST | Keep using unofficial API for historical data, or use MQTT snapshot for current prices |
| gRPC on Python 3.14 | `grpcio` doesn't build | Poll `/openapi/trade/order/open` every 2-5s as fallback; or use Python 3.13 |
| MOO/MOC orders | Institutional only | Not used by BotifyTrades — no impact |
| Crypto replace/modify | Not supported | Cancel + re-place (same as current unofficial behavior) |

---

## TASK 3: ARCHITECTURE DESIGN

### File Structure

```
src/brokers/webull_official/
├── __init__.py              # Package init, exports WebullOfficialBroker
├── auth.py                  # HMAC-SHA1 signing, header construction
├── client.py                # Async HTTP client (httpx), request/response handling
├── broker.py                # BrokerInterface implementation (main entry point)
├── accounts.py              # Account list, balance, profile queries
├── orders.py                # Place, cancel, replace, query orders
├── positions.py             # Position queries, P&L calculations
├── streaming.py             # MQTT market data + gRPC trade events
├── models.py                # Dataclasses for API responses
├── exceptions.py            # Custom exception hierarchy
├── rate_limiter.py          # Per-endpoint token bucket rate limiting
├── config.py                # Environment URLs, constants
└── tests/
    ├── __init__.py
    ├── test_auth.py          # Signature generation tests with known vectors
    ├── test_orders.py        # Order placement/cancel/replace tests
    ├── test_models.py        # Response parsing tests
    └── test_rate_limiter.py  # Rate limiter tests
```

**Also modified (existing files):**
```
src/selfbot_webull.py           # Add WebullOfficialBroker init + BrokerManager wiring
src/services/unified_price_hub.py   # Add webull_official hub registration
src/services/relay_client.py        # Add WEBULL_OFFICIAL to broker name mapping
src/services/broker_sync_service.py # Add webull_official sync support
gui_app/routes.py                   # Add /api/webull_official/* endpoints
gui_app/templates/index.html        # Add WEBULL_OFFICIAL to broker dropdown
```

### Module Design

#### `config.py` — Environment Configuration

```python
from dataclasses import dataclass

@dataclass
class WebullConfig:
    app_key: str
    app_secret: str
    account_id: str = ""
    environment: str = "production"
    
    @property
    def base_url(self) -> str:
        if self.environment == "test":
            return "https://us-openapi-alb.uat.webullbroker.com"
        return "https://api.webull.com"
    
    @property
    def events_url(self) -> str:
        if self.environment == "test":
            return "us-openapi-events.uat.webullbroker.com"
        return "events-api.webull.com"
    
    @property
    def mqtt_host(self) -> str:
        return "data-api.webull.com"
    
    @property
    def mqtt_port(self) -> int:
        return 1883
    
    @property
    def mqtt_wss_url(self) -> str:
        return "wss://data-api.webull.com:8883/mqtt"
```

#### `auth.py` — HMAC-SHA1 Signing

```python
import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import quote


class WebullAuth:
    def __init__(self, app_key: str, app_secret: str):
        self._app_key = app_key
        self._signing_key = (app_secret + "&").encode("utf-8")
    
    def sign_request(self, method: str, path: str, host: str,
                     query_params: dict = None, body: dict = None) -> dict:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = uuid.uuid4().hex
        
        signing_headers = {
            "x-app-key": self._app_key,
            "x-timestamp": timestamp,
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": nonce,
            "host": host,
        }
        
        all_params = {}
        all_params.update(signing_headers)
        if query_params:
            all_params.update(query_params)
        
        sorted_pairs = sorted(all_params.items())
        str1 = "&".join(f"{k}={v}" for k, v in sorted_pairs)
        
        str3 = path + "&" + str1
        if body is not None:
            compact_body = json.dumps(body, separators=(",", ":"), sort_keys=False)
            str2 = hashlib.md5(compact_body.encode("utf-8")).hexdigest().upper()
            str3 += "&" + str2
        
        encoded_string = quote(str3, safe="")
        
        sig_bytes = hmac.new(self._signing_key, encoded_string.encode("utf-8"), hashlib.sha1).digest()
        signature = base64.b64encode(sig_bytes).decode("utf-8")
        
        headers = {
            "x-app-key": self._app_key,
            "x-timestamp": timestamp,
            "x-signature": signature,
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": nonce,
            "x-version": "v2",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        
        return headers
```

#### `exceptions.py` — Error Hierarchy

```python
class WebullAPIError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(f"[{status_code}] {error_code}: {message}")

class WebullAuthError(WebullAPIError):
    pass

class WebullRateLimitError(WebullAPIError):
    pass

class WebullOrderError(WebullAPIError):
    pass

class WebullConnectionError(Exception):
    pass
```

#### `rate_limiter.py` — Token Bucket Per Endpoint

```python
import asyncio
import time
from collections import defaultdict


class RateLimiter:
    LIMITS = {
        "order": (600, 60),       # 600 per 60 seconds
        "account_data": (2, 2),   # 2 per 2 seconds
        "token": (10, 30),        # 10 per 30 seconds
        "account_list": (10, 30), # 10 per 30 seconds
        "subscribe": (600, 60),   # 600 per 60 seconds
    }
    
    ENDPOINT_CATEGORY = {
        "/openapi/trade/order/place": "order",
        "/openapi/trade/order/cancel": "order",
        "/openapi/trade/order/replace": "order",
        "/openapi/trade/order/batch-place": "order",
        "/openapi/trade/order/preview": "order",
        "/openapi/assets/balance": "account_data",
        "/openapi/assets/positions": "account_data",
        "/openapi/trade/order/history": "account_data",
        "/openapi/trade/order/open": "account_data",
        "/openapi/trade/order/detail": "account_data",
        "/openapi/account/list": "account_list",
        "/openapi/auth/token/create": "token",
        "/openapi/auth/token/check": "token",
        "/openapi/market-data/streaming/subscribe": "subscribe",
    }
    
    def __init__(self):
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def acquire(self, path: str):
        category = self.ENDPOINT_CATEGORY.get(path)
        if not category:
            return
        
        max_requests, window_seconds = self.LIMITS[category]
        
        async with self._lock:
            now = time.monotonic()
            timestamps = self._timestamps[category]
            
            timestamps[:] = [t for t in timestamps if now - t < window_seconds]
            
            if len(timestamps) >= max_requests:
                wait_time = timestamps[0] + window_seconds - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    timestamps[:] = [t for t in timestamps if time.monotonic() - t < window_seconds]
            
            timestamps.append(time.monotonic())
```

#### `models.py` — Response Dataclasses

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class WebullAccount:
    account_id: str
    account_type: str
    account_class: str
    account_label: str
    user_id: str = ""


@dataclass
class WebullBalance:
    total_cash_balance: float = 0.0
    total_market_value: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_net_liquidation: float = 0.0
    total_day_pnl: float = 0.0
    buying_power: float = 0.0
    settled_cash: float = 0.0
    unsettled_cash: float = 0.0
    day_trades_left: str = ""
    option_buying_power: float = 0.0
    day_buying_power: float = 0.0
    overnight_buying_power: float = 0.0
    
    @classmethod
    def from_api(cls, data: dict) -> "WebullBalance":
        currency_assets = data.get("account_currency_assets", [{}])
        usd = currency_assets[0] if currency_assets else {}
        return cls(
            total_cash_balance=float(data.get("total_cash_balance") or 0),
            total_market_value=float(data.get("total_market_value") or 0),
            total_unrealized_pnl=float(data.get("total_unrealized_profit_loss") or 0),
            total_net_liquidation=float(data.get("total_net_liquidation_value") or 0),
            total_day_pnl=float(data.get("total_day_profit_loss") or 0),
            buying_power=float(usd.get("buying_power") or 0),
            settled_cash=float(usd.get("settled_cash") or 0),
            unsettled_cash=float(usd.get("unsettled_cash") or 0),
            day_trades_left=data.get("day_trades_left", ""),
            option_buying_power=float(usd.get("option_buying_power") or 0),
            day_buying_power=float(usd.get("day_buying_power") or 0),
            overnight_buying_power=float(usd.get("overnight_buying_power") or 0),
        )


@dataclass
class WebullPosition:
    position_id: str
    symbol: str
    quantity: float
    cost_price: float
    last_price: float
    unrealized_pnl: float
    instrument_type: str
    currency: str = "USD"
    option_type: str = ""       # CALL / PUT
    strike_price: float = 0.0
    expiry_date: str = ""       # yyyy-MM-dd
    option_strategy: str = ""
    multiplier: int = 100
    
    @classmethod
    def from_api(cls, data: dict) -> "WebullPosition":
        legs = data.get("legs", [])
        leg = legs[0] if legs else {}
        return cls(
            position_id=data.get("position_id", ""),
            symbol=data.get("symbol", ""),
            quantity=float(data.get("quantity") or 0),
            cost_price=float(data.get("cost_price") or 0),
            last_price=float(data.get("last_price") or 0),
            unrealized_pnl=float(data.get("unrealized_profit_loss") or 0),
            instrument_type=data.get("instrument_type", "EQUITY"),
            option_type=leg.get("option_type", ""),
            strike_price=float(leg.get("option_exercise_price") or 0),
            expiry_date=leg.get("option_expire_date", ""),
            option_strategy=data.get("option_strategy", ""),
            multiplier=int(leg.get("option_contract_multiplier") or 100),
        )


@dataclass
class WebullOrder:
    client_order_id: str
    order_id: str
    symbol: str
    side: str
    status: str
    order_type: str
    instrument_type: str
    quantity: float
    filled_quantity: float
    filled_price: float
    limit_price: float = 0.0
    stop_price: float = 0.0
    time_in_force: str = "DAY"
    place_time: str = ""
    filled_time: str = ""
    combo_type: str = "NORMAL"
    
    @classmethod
    def from_api(cls, data: dict, combo_type: str = "NORMAL") -> "WebullOrder":
        return cls(
            client_order_id=data.get("client_order_id", ""),
            order_id=data.get("order_id", ""),
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            status=data.get("status", ""),
            order_type=data.get("order_type", ""),
            instrument_type=data.get("instrument_type", "EQUITY"),
            quantity=float(data.get("total_quantity") or 0),
            filled_quantity=float(data.get("filled_quantity") or 0),
            filled_price=float(data.get("filled_price") or 0),
            limit_price=float(data.get("limit_price") or 0),
            stop_price=float(data.get("stop_price") or 0),
            time_in_force=data.get("time_in_force", "DAY"),
            place_time=data.get("place_time_at", ""),
            filled_time=data.get("filled_time_at", ""),
            combo_type=combo_type,
        )


@dataclass
class PlaceOrderResult:
    client_order_id: str
    order_id: str = ""
    combo_order_id: str = ""
    client_combo_order_id: str = ""
```

#### `client.py` — Async HTTP Client

```python
import httpx
import logging
from typing import Optional
from urllib.parse import urlparse

from .auth import WebullAuth
from .config import WebullConfig
from .exceptions import WebullAPIError, WebullAuthError, WebullRateLimitError, WebullOrderError
from .rate_limiter import RateLimiter

log = logging.getLogger("webull_official")


class WebullClient:
    def __init__(self, config: WebullConfig):
        self._config = config
        self._auth = WebullAuth(config.app_key, config.app_secret)
        self._rate_limiter = RateLimiter()
        self._http: Optional[httpx.AsyncClient] = None
    
    async def start(self):
        self._http = httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    
    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
    
    async def get(self, path: str, params: dict = None) -> dict:
        await self._rate_limiter.acquire(path)
        host = urlparse(self._config.base_url).hostname
        headers = self._auth.sign_request("GET", path, host, query_params=params)
        
        resp = await self._http.get(path, params=params, headers=headers)
        return self._handle_response(resp, path)
    
    async def post(self, path: str, body: dict = None) -> dict:
        await self._rate_limiter.acquire(path)
        host = urlparse(self._config.base_url).hostname
        headers = self._auth.sign_request("POST", path, host, body=body)
        
        import json
        raw_body = json.dumps(body, separators=(",", ":")) if body else None
        resp = await self._http.post(path, content=raw_body, headers=headers)
        return self._handle_response(resp, path)
    
    def _handle_response(self, resp: httpx.Response, path: str) -> dict:
        if resp.status_code == 200:
            if not resp.content:
                return {}
            return resp.json()
        
        try:
            error_data = resp.json()
        except Exception:
            error_data = {"error_code": "UNKNOWN", "message": resp.text}
        
        error_code = error_data.get("error_code", "UNKNOWN")
        message = error_data.get("message", "")
        
        if resp.status_code == 401:
            raise WebullAuthError(resp.status_code, error_code, message)
        
        if "order" in path:
            raise WebullOrderError(resp.status_code, error_code, message)
        
        raise WebullAPIError(resp.status_code, error_code, message)
```

#### `accounts.py` — Account Operations

```python
from typing import Optional
from .client import WebullClient
from .models import WebullAccount, WebullBalance


class AccountsAPI:
    def __init__(self, client: WebullClient):
        self._client = client
    
    async def list_accounts(self) -> list[WebullAccount]:
        data = await self._client.get("/openapi/account/list")
        if not isinstance(data, list):
            data = data.get("accounts", data.get("data", []))
        return [
            WebullAccount(
                account_id=a.get("account_id", ""),
                account_type=a.get("account_type", ""),
                account_class=a.get("account_class", ""),
                account_label=a.get("account_label", ""),
                user_id=a.get("user_id", ""),
            )
            for a in data
        ]
    
    async def get_balance(self, account_id: str) -> WebullBalance:
        data = await self._client.get(
            "/openapi/assets/balance",
            params={"account_id": account_id},
        )
        return WebullBalance.from_api(data)
```

#### `positions.py` — Position Operations

```python
from .client import WebullClient
from .models import WebullPosition


class PositionsAPI:
    def __init__(self, client: WebullClient):
        self._client = client
    
    async def get_positions(self, account_id: str) -> list[WebullPosition]:
        data = await self._client.get(
            "/openapi/assets/positions",
            params={"account_id": account_id},
        )
        items = data if isinstance(data, list) else data.get("positions", [])
        return [WebullPosition.from_api(p) for p in items]
```

#### `orders.py` — Order Operations

```python
import uuid
from typing import Optional
from .client import WebullClient
from .models import WebullOrder, PlaceOrderResult


class OrdersAPI:
    def __init__(self, client: WebullClient):
        self._client = client
    
    def _gen_client_order_id(self) -> str:
        return uuid.uuid4().hex[:32]
    
    async def place_stock_order(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        limit_price: float = None,
        stop_price: float = None,
        time_in_force: str = "DAY",
        extended_hours: bool = False,
        client_order_id: str = None,
    ) -> PlaceOrderResult:
        order = {
            "client_order_id": client_order_id or self._gen_client_order_id(),
            "combo_type": "NORMAL",
            "instrument_type": "EQUITY",
            "entrust_type": "QTY",
            "symbol": symbol,
            "market": "US",
            "side": side,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "quantity": str(quantity),
            "support_trading_session": "ALL" if extended_hours else "CORE",
        }
        if limit_price is not None:
            order["limit_price"] = str(limit_price)
        if stop_price is not None:
            order["stop_price"] = str(stop_price)
        
        body = {"account_id": account_id, "new_orders": [order]}
        data = await self._client.post("/openapi/trade/order/place", body)
        
        return PlaceOrderResult(
            client_order_id=data.get("client_order_id", order["client_order_id"]),
            order_id=data.get("order_id", ""),
            combo_order_id=data.get("combo_order_id", ""),
        )
    
    async def place_option_order(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: int,
        option_type: str,
        strike_price: float,
        expiry_date: str,
        position_intent: str,
        order_type: str = "LIMIT",
        limit_price: float = None,
        time_in_force: str = "DAY",
        client_order_id: str = None,
    ) -> PlaceOrderResult:
        coid = client_order_id or self._gen_client_order_id()
        order = {
            "client_order_id": coid,
            "combo_type": "NORMAL",
            "instrument_type": "OPTION",
            "option_strategy": "SINGLE",
            "entrust_type": "QTY",
            "symbol": symbol,
            "market": "US",
            "side": side,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "quantity": str(quantity),
            "position_intent": position_intent,
            "legs": [{
                "side": side,
                "quantity": str(quantity),
                "symbol": symbol,
                "market": "US",
                "instrument_type": "OPTION",
                "strike_price": str(strike_price),
                "option_expire_date": expiry_date,
                "option_type": option_type,
            }],
        }
        if limit_price is not None:
            order["limit_price"] = str(limit_price)
        
        body = {"account_id": account_id, "new_orders": [order]}
        data = await self._client.post("/openapi/trade/order/place", body)
        
        return PlaceOrderResult(
            client_order_id=data.get("client_order_id", coid),
            order_id=data.get("order_id", ""),
        )
    
    async def place_bracket_order(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        limit_price: float = None,
        take_profit_price: float = None,
        stop_loss_price: float = None,
        extended_hours: bool = False,
        client_order_id: str = None,
    ) -> PlaceOrderResult:
        combo_id = client_order_id or self._gen_client_order_id()
        exit_side = "SELL" if side == "BUY" else "BUY"
        
        master = {
            "client_order_id": self._gen_client_order_id(),
            "combo_type": "MASTER",
            "instrument_type": "EQUITY",
            "entrust_type": "QTY",
            "symbol": symbol,
            "market": "US",
            "side": side,
            "order_type": order_type,
            "time_in_force": "DAY",
            "quantity": str(quantity),
            "support_trading_session": "ALL" if extended_hours else "CORE",
        }
        if limit_price is not None:
            master["limit_price"] = str(limit_price)
        
        orders = [master]
        
        if take_profit_price is not None:
            orders.append({
                "client_order_id": self._gen_client_order_id(),
                "combo_type": "STOP_PROFIT",
                "instrument_type": "EQUITY",
                "entrust_type": "QTY",
                "symbol": symbol,
                "market": "US",
                "side": exit_side,
                "order_type": "LIMIT",
                "time_in_force": "GTC",
                "quantity": str(quantity),
                "limit_price": str(take_profit_price),
                "support_trading_session": "ALL" if extended_hours else "CORE",
            })
        
        if stop_loss_price is not None:
            orders.append({
                "client_order_id": self._gen_client_order_id(),
                "combo_type": "STOP_LOSS",
                "instrument_type": "EQUITY",
                "entrust_type": "QTY",
                "symbol": symbol,
                "market": "US",
                "side": exit_side,
                "order_type": "STOP_LOSS",
                "time_in_force": "GTC",
                "quantity": str(quantity),
                "stop_price": str(stop_loss_price),
                "support_trading_session": "ALL" if extended_hours else "CORE",
            })
        
        body = {
            "account_id": account_id,
            "client_combo_order_id": combo_id,
            "new_orders": orders,
        }
        data = await self._client.post("/openapi/trade/order/place", body)
        
        return PlaceOrderResult(
            client_order_id=data.get("client_order_id", ""),
            combo_order_id=data.get("combo_order_id", ""),
            client_combo_order_id=combo_id,
        )
    
    async def place_trailing_stop(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: float,
        trailing_type: str,
        trailing_stop_step: float,
        client_order_id: str = None,
    ) -> PlaceOrderResult:
        coid = client_order_id or self._gen_client_order_id()
        order = {
            "client_order_id": coid,
            "combo_type": "NORMAL",
            "instrument_type": "EQUITY",
            "entrust_type": "QTY",
            "symbol": symbol,
            "market": "US",
            "side": side,
            "order_type": "TRAILING_STOP_LOSS",
            "time_in_force": "DAY",
            "quantity": str(quantity),
            "trailing_type": trailing_type,
            "trailing_stop_step": str(trailing_stop_step),
        }
        body = {"account_id": account_id, "new_orders": [order]}
        data = await self._client.post("/openapi/trade/order/place", body)
        return PlaceOrderResult(
            client_order_id=data.get("client_order_id", coid),
            order_id=data.get("order_id", ""),
        )
    
    async def cancel_order(self, account_id: str, client_order_id: str) -> dict:
        body = {
            "account_id": account_id,
            "client_order_id": client_order_id,
        }
        return await self._client.post("/openapi/trade/order/cancel", body)
    
    async def replace_order(
        self,
        account_id: str,
        client_order_id: str,
        limit_price: float = None,
        stop_price: float = None,
        quantity: float = None,
        time_in_force: str = None,
    ) -> dict:
        modify = {"client_order_id": client_order_id}
        if limit_price is not None:
            modify["limit_price"] = str(limit_price)
        if stop_price is not None:
            modify["stop_price"] = str(stop_price)
        if quantity is not None:
            modify["quantity"] = str(quantity)
        if time_in_force is not None:
            modify["time_in_force"] = time_in_force
        
        body = {"account_id": account_id, "modify_orders": [modify]}
        return await self._client.post("/openapi/trade/order/replace", body)
    
    async def get_open_orders(self, account_id: str, page_size: int = 100) -> list[WebullOrder]:
        data = await self._client.get(
            "/openapi/trade/order/open",
            params={"account_id": account_id, "page_size": str(page_size)},
        )
        results = []
        items = data if isinstance(data, list) else data.get("orders", [])
        for group in items:
            combo_type = group.get("combo_type", "NORMAL")
            for order in group.get("orders", [group]):
                results.append(WebullOrder.from_api(order, combo_type))
        return results
    
    async def get_order_detail(self, account_id: str, client_order_id: str) -> WebullOrder:
        data = await self._client.get(
            "/openapi/trade/order/detail",
            params={"account_id": account_id, "client_order_id": client_order_id},
        )
        orders = data.get("orders", [data])
        return WebullOrder.from_api(orders[0] if orders else data)
    
    async def get_order_history(
        self,
        account_id: str,
        start_date: str = None,
        end_date: str = None,
        page_size: int = 100,
    ) -> list[WebullOrder]:
        params = {"account_id": account_id, "page_size": str(page_size)}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        
        data = await self._client.get("/openapi/trade/order/history", params)
        results = []
        items = data if isinstance(data, list) else data.get("orders", [])
        for group in items:
            combo_type = group.get("combo_type", "NORMAL")
            for order in group.get("orders", [group]):
                results.append(WebullOrder.from_api(order, combo_type))
        return results
```

#### `streaming.py` — MQTT Market Data + Trade Event Polling

```python
import asyncio
import json
import logging
import uuid
from typing import Callable, Optional

from .client import WebullClient
from .config import WebullConfig

log = logging.getLogger("webull_official")


class WebullMarketStream:
    """MQTT-based market data streaming with HTTP subscription management."""
    
    def __init__(self, config: WebullConfig, client: WebullClient):
        self._config = config
        self._client = client
        self._session_id = uuid.uuid4().hex
        self._mqtt_client = None
        self._callbacks: dict[str, list[Callable]] = {}
        self._subscribed_symbols: set[str] = set()
    
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
    """Polls open orders for fill status changes (gRPC fallback)."""
    
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
            except Exception as e:
                log.error(f"[WEBULL-OFF] Poll error: {e}")
            
            await asyncio.sleep(self._interval)
```

#### `broker.py` — BrokerInterface Implementation

```python
import asyncio
import logging
from typing import Optional

from .client import WebullClient
from .config import WebullConfig
from .accounts import AccountsAPI
from .orders import OrdersAPI
from .positions import PositionsAPI
from .streaming import WebullMarketStream, TradeEventPoller
from .models import WebullBalance, WebullPosition, WebullOrder

log = logging.getLogger("webull_official")

# Import from project root
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from broker_interface import BrokerInterface, OrderResult


class WebullOfficialBroker(BrokerInterface):
    def __init__(self, loop=None, name="WEBULL_OFFICIAL", paper_trade=False):
        self.name = name
        self.loop = loop or asyncio.get_event_loop()
        self.paper_trade = paper_trade
        self.connected = False
        self.account_id = ""
        self.account_number = ""
        
        self._config: Optional[WebullConfig] = None
        self._client: Optional[WebullClient] = None
        self._accounts: Optional[AccountsAPI] = None
        self._orders: Optional[OrdersAPI] = None
        self._positions: Optional[PositionsAPI] = None
        self._stream: Optional[WebullMarketStream] = None
        self._event_poller: Optional[TradeEventPoller] = None
        
        self._cached_balance: Optional[WebullBalance] = None
        self._cached_positions: list[WebullPosition] = []
    
    async def connect(self, app_key: str, app_secret: str,
                      account_id: str = "", environment: str = "production"):
        try:
            self._config = WebullConfig(
                app_key=app_key,
                app_secret=app_secret,
                account_id=account_id,
                environment="test" if self.paper_trade else environment,
            )
            self._client = WebullClient(self._config)
            await self._client.start()
            
            self._accounts = AccountsAPI(self._client)
            self._orders = OrdersAPI(self._client)
            self._positions = PositionsAPI(self._client)
            
            accounts = await self._accounts.list_accounts()
            if not accounts:
                print(f"[{self.name}] ❌ No accounts found")
                return False
            
            if account_id:
                matched = [a for a in accounts if a.account_id == account_id]
                if matched:
                    self.account_id = matched[0].account_id
                    self.account_number = matched[0].account_id
                else:
                    print(f"[{self.name}] ⚠️ Account {account_id} not found, using first")
                    self.account_id = accounts[0].account_id
            else:
                margin_accounts = [a for a in accounts if a.account_type == "MARGIN"]
                target = margin_accounts[0] if margin_accounts else accounts[0]
                self.account_id = target.account_id
                self.account_number = target.account_id
            
            balance = await self._accounts.get_balance(self.account_id)
            self.connected = True
            print(f"[{self.name}] ✅ Connected — Account: {self.account_id}, "
                  f"Balance: ${balance.total_net_liquidation:,.2f}")
            return True
            
        except Exception as e:
            print(f"[{self.name}] ❌ Connection failed: {e}")
            self.connected = False
            return False
    
    async def disconnect(self):
        if self._event_poller:
            await self._event_poller.stop()
        if self._stream:
            await self._stream.disconnect()
        if self._client:
            await self._client.close()
        self.connected = False
        print(f"[{self.name}] Disconnected")
    
    async def get_account_info(self) -> dict:
        if not self.connected:
            return {}
        balance = await self._accounts.get_balance(self.account_id)
        self._cached_balance = balance
        return {
            "account_id": self.account_id,
            "account_number": self.account_number,
            "cash_balance": balance.total_cash_balance,
            "buying_power": balance.buying_power,
            "portfolio_value": balance.total_net_liquidation,
            "market_value": balance.total_market_value,
            "unrealized_pnl": balance.total_unrealized_pnl,
            "day_pnl": balance.total_day_pnl,
            "settled_cash": balance.settled_cash,
            "unsettled_cash": balance.unsettled_cash,
            "day_trades_left": balance.day_trades_left,
            "option_buying_power": balance.option_buying_power,
        }
    
    async def get_positions(self) -> list:
        if not self.connected:
            return []
        positions = await self._positions.get_positions(self.account_id)
        self._cached_positions = positions
        return [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "avg_cost": p.cost_price,
                "current_price": p.last_price,
                "unrealized_pl": p.unrealized_pnl,
                "asset": "option" if p.instrument_type == "OPTION" else "stock",
                "position_id": p.position_id,
                "option_type": p.option_type,
                "strike_price": p.strike_price,
                "expiry_date": p.expiry_date,
            }
            for p in positions
        ]
    
    async def place_stock_order(self, symbol, quantity, action, order_type="MARKET",
                                 limit_price=None, stop_price=None, duration="DAY",
                                 extended_hours=False) -> OrderResult:
        if not self.connected:
            return OrderResult(success=False, message="Not connected")
        
        side_map = {"BUY": "BUY", "SELL": "SELL", "BTO": "BUY", "STC": "SELL",
                     "SHORT": "SHORT", "COVER": "BUY"}
        side = side_map.get(action.upper(), action.upper())
        
        type_map = {"MARKET": "MARKET", "LIMIT": "LIMIT",
                     "STOP": "STOP_LOSS", "STOP_LIMIT": "STOP_LOSS_LIMIT"}
        otype = type_map.get(order_type.upper(), order_type.upper())
        
        tif_map = {"DAY": "DAY", "GTC": "GTC", "IOC": "IOC"}
        tif = tif_map.get(duration.upper(), "DAY")
        
        try:
            result = await self._orders.place_stock_order(
                account_id=self.account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=otype,
                limit_price=limit_price,
                stop_price=stop_price,
                time_in_force=tif,
                extended_hours=extended_hours,
            )
            return OrderResult(
                success=True,
                order_id=result.order_id or result.client_order_id,
                message=f"Order placed: {side} {quantity} {symbol}",
                price=limit_price,
                quantity=quantity,
                symbol=symbol,
                action=action,
            )
        except Exception as e:
            return OrderResult(
                success=False,
                message=str(e),
                symbol=symbol,
                action=action,
                quantity=quantity,
            )
    
    async def place_option_order(self, symbol, quantity, action, order_type="LIMIT",
                                  limit_price=None, option_type=None,
                                  strike_price=None, expiry_date=None,
                                  **kwargs) -> OrderResult:
        if not self.connected:
            return OrderResult(success=False, message="Not connected")
        
        intent_map = {"BTO": "BUY_TO_OPEN", "STC": "SELL_TO_CLOSE",
                       "STO": "SELL_TO_OPEN", "BTC": "BUY_TO_CLOSE"}
        position_intent = intent_map.get(action.upper(), "BUY_TO_OPEN")
        
        side = "BUY" if action.upper() in ("BTO", "BTC") else "SELL"
        otype = "CALL" if option_type and option_type.upper().startswith("C") else "PUT"
        
        try:
            result = await self._orders.place_option_order(
                account_id=self.account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                option_type=otype,
                strike_price=strike_price,
                expiry_date=expiry_date,
                position_intent=position_intent,
                order_type=order_type.upper(),
                limit_price=limit_price,
            )
            return OrderResult(
                success=True,
                order_id=result.order_id or result.client_order_id,
                message=f"Option order placed: {action} {quantity}x {symbol}",
                price=limit_price,
                quantity=quantity,
                symbol=symbol,
                action=action,
            )
        except Exception as e:
            return OrderResult(
                success=False,
                message=str(e),
                symbol=symbol,
                action=action,
                quantity=quantity,
            )
    
    async def get_quote(self, symbol) -> dict:
        # No REST quote endpoint — would come from MQTT stream cache
        # Return from cached stream data or empty
        return {"symbol": symbol, "last": 0.0, "bid": 0.0, "ask": 0.0}
    
    # === Extended methods (not in base BrokerInterface) ===
    
    async def place_bracket_order(self, symbol, quantity, side, order_type="MARKET",
                                   limit_price=None, take_profit=None, stop_loss=None,
                                   extended_hours=False) -> OrderResult:
        if not self.connected:
            return OrderResult(success=False, message="Not connected")
        
        try:
            result = await self._orders.place_bracket_order(
                account_id=self.account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                take_profit_price=take_profit,
                stop_loss_price=stop_loss,
                extended_hours=extended_hours,
            )
            return OrderResult(
                success=True,
                order_id=result.combo_order_id or result.client_combo_order_id,
                message=f"Bracket order placed: {side} {quantity} {symbol} "
                        f"TP={take_profit} SL={stop_loss}",
                quantity=quantity,
                symbol=symbol,
                action=side,
            )
        except Exception as e:
            return OrderResult(success=False, message=str(e), symbol=symbol)
    
    async def cancel_order_by_id(self, client_order_id: str) -> bool:
        try:
            await self._orders.cancel_order(self.account_id, client_order_id)
            return True
        except Exception as e:
            print(f"[{self.name}] Cancel failed: {e}")
            return False
    
    async def get_pending_orders(self) -> list:
        if not self.connected:
            return []
        orders = await self._orders.get_open_orders(self.account_id)
        return [
            {
                "order_id": o.client_order_id,
                "broker_order_id": o.order_id,
                "symbol": o.symbol,
                "quantity": o.quantity,
                "filled_quantity": o.filled_quantity,
                "limit_price": o.limit_price,
                "stop_price": o.stop_price,
                "action": o.side,
                "status": o.status,
                "order_type": o.order_type,
                "combo_type": o.combo_type,
            }
            for o in orders
        ]
    
    async def start_streaming(self, symbols: list[str] = None):
        if not self._stream:
            self._stream = WebullMarketStream(self._config, self._client)
        
        connected = await self._stream.connect()
        if connected and symbols:
            await self._stream.subscribe(symbols)
        
        if not self._event_poller:
            self._event_poller = TradeEventPoller(self._client, self.account_id)
            await self._event_poller.start()
```

### Wiring into Existing Bot

#### `selfbot_webull.py` Changes (~25 lines)

At broker initialization (near line 7790):
```python
# After existing Webull broker init:
if WEBULL_OFFICIAL_ENABLED:
    from brokers.webull_official import WebullOfficialBroker
    self.webull_official_broker = WebullOfficialBroker(
        loop=self.loop, name="WEBULL_OFFICIAL", paper_trade=PAPER_TRADE
    )
    await self.webull_official_broker.connect(
        app_key=WEBULL_OFFICIAL_APP_KEY,
        app_secret=WEBULL_OFFICIAL_APP_SECRET,
        account_id=WEBULL_OFFICIAL_ACCOUNT_ID,
    )
```

At BrokerManager (line 8565), add to broker dict:
```python
if hasattr(self, 'webull_official_broker') and self.webull_official_broker.connected:
    brokers["WEBULL_OFFICIAL"] = self.webull_official_broker
```

At signal routing (line 18437), add case:
```python
elif broker_name_lower in ("webull_official", "webull official"):
    broker_instance = self.webull_official_broker
```

#### `unified_price_hub.py` Changes (~8 lines)

At `_HUB_REGISTRY` (line 73):
```python
("webull_official", "services.webull_official_data_hub", "WebullOfficialDataHub.instance"),
```

At `_BROKER_NAME_TO_HUB` (line 455):
```python
"WEBULL_OFFICIAL": "webull_official",
```

#### `relay_client.py` Changes (~4 lines)

At `_get_broker_by_name()` (line 519):
```python
elif name == "webull_official":
    return getattr(self.bot, 'webull_official_broker', None)
```

At `_get_all_broker_instances()` (line 537):
```python
if hasattr(self.bot, 'webull_official_broker'):
    instances.append(self.bot.webull_official_broker)
```

---

## CRITICAL DESIGN DECISIONS

### 1. Direct HTTP vs SDK

**Decision: Direct HTTP (httpx)**

Reasons:
- The installed SDK (`webull-python-sdk-trade` v0.1.18) is the **old v1 API** — uses `instrument_id`, HK-focused option endpoints
- The newer SDK (`webull-openapi-python-sdk`) requires `grpcio` which doesn't build on Python 3.14
- The v2 REST API is well-documented and uses `symbol` strings directly — no instrument lookup needed
- httpx is already a project dependency for Schwab
- HMAC-SHA1 signing is ~20 lines of code

### 2. Options via Standard Place Order (not separate endpoints)

**Decision: Use `/openapi/trade/order/place` with `instrument_type: "OPTION"`**

The SDK's `place_option()` / `cancel_option()` methods have docstrings stating "exclusively available for Webull Hong Kong brokerage clients." However, the v2 REST API's standard place order endpoint supports `instrument_type: "OPTION"` with `legs[]` for all markets including US. This is confirmed by the API documentation listing OPTION in the instrument_type enum.

### 3. Native Bracket Orders

**Decision: Use native OTOCO instead of client-side position monitor brackets**

The official API supports `combo_type: "OTOCO"` which combines:
- `MASTER` entry order
- `STOP_PROFIT` take-profit leg
- `STOP_LOSS` stop-loss leg

This is broker-managed — no client polling needed. Major reliability improvement over the current position_monitor approach for Webull brackets.

**The position monitor should still run** for:
- Trailing stop adjustments (dynamic re-pricing)
- Multi-PT tiered exits (scale-out at PT1, PT2, PT3)
- Time-based exits
- Channel-specific risk rules

### 4. gRPC Fallback Strategy

**Decision: Order polling with 3-second interval**

Since `grpcio` doesn't build on Python 3.14, we poll `/openapi/trade/order/open` every 3 seconds to detect fills. Rate limit is 2 req/2s = 1/s, so 3s interval is safe. When/if Python 3.14 gets grpcio support, swap in the gRPC stream.

### 5. client_order_id Strategy

**Decision: UUID-based, 32-char hex**

The API enforces `client_order_id` max 32 chars, unique per account. We use `uuid.uuid4().hex[:32]`. This ID is used for cancel/replace — we must store the mapping `client_order_id → broker_order_id` in the position cache.

---

## ESTIMATED IMPLEMENTATION EFFORT

| Component | Lines | Days | Priority |
|-----------|-------|------|----------|
| `auth.py` | ~60 | 0.5 | P0 |
| `config.py` | ~30 | 0.5 | P0 |
| `exceptions.py` | ~25 | 0.5 | P0 |
| `rate_limiter.py` | ~60 | 0.5 | P0 |
| `models.py` | ~150 | 1 | P0 |
| `client.py` | ~80 | 1 | P0 |
| `accounts.py` | ~40 | 0.5 | P0 |
| `orders.py` | ~250 | 2 | P0 |
| `positions.py` | ~30 | 0.5 | P0 |
| `broker.py` | ~300 | 2 | P0 |
| `streaming.py` | ~200 | 2 | P1 |
| Bot wiring (selfbot, UPH, relay) | ~50 | 1 | P0 |
| GUI routes | ~100 | 1 | P1 |
| Tests | ~200 | 2 | P1 |
| **Total** | **~1,575** | **~14 days** | |

### Implementation Order

1. **Phase 1 (Days 1-4):** Core module — auth, client, config, exceptions, rate_limiter, models
2. **Phase 2 (Days 5-8):** Trading — accounts, orders, positions, broker.py with BrokerInterface
3. **Phase 3 (Days 9-11):** Integration — bot wiring, UPH registration, GUI routes
4. **Phase 4 (Days 12-14):** Streaming — MQTT market data, trade event polling, tests

### Test Strategy

1. **Unit tests** against UAT environment with public test credentials
2. **Signature verification** using documented test vectors
3. **Order flow test:** Place → Query → Replace → Cancel cycle in sandbox
4. **Integration test:** Wire into bot in paper mode, verify Dashboard cards populate
