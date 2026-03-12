# TRADE212 Integration Plan — BotifyTrades

## Trading 212 API Assessment

| Capability | Status |
|---|---|
| Stocks/ETFs | Full support (buy, sell, fractional shares) |
| Options | NOT supported — Invest/ISA accounts only |
| Order Types | Market, Limit, Stop, Stop-Limit |
| WebSocket/Streaming | NOT available — REST-only, must poll |
| Auth | API Key + API Secret (Basic Auth, Base64 encoded) |
| Environments | Paper: `demo.trading212.com/api/v0`, Live: `live.trading212.com/api/v0` |
| Fractional Shares | Supported (quantity can be decimal like 0.1) |
| Idempotency | NOT idempotent — duplicate requests create duplicate orders |

### API Endpoints

| Endpoint | Method | Rate Limit | Purpose |
|---|---|---|---|
| `/api/v0/equity/orders/market` | POST | 50 req/1min | Market orders |
| `/api/v0/equity/orders/limit` | POST | 1 req/2s | Limit orders |
| `/api/v0/equity/orders/stop` | POST | 1 req/2s | Stop orders |
| `/api/v0/equity/orders/stop_limit` | POST | 1 req/2s | Stop-Limit orders |
| `/api/v0/equity/orders` | GET | 1 req/5s | All pending orders |
| `/api/v0/equity/orders/{id}` | GET | 1 req/1s | Single order status |
| `/api/v0/equity/orders/{id}` | DELETE | 50 req/1min | Cancel order |
| `/api/v0/equity/portfolio` | GET | 1 req/5s | All positions |
| `/api/v0/equity/portfolio/{ticker}` | GET | 1 req/1s | Single position |
| `/api/v0/equity/account/summary` | GET | 1 req/5s | Account info |
| `/api/v0/equity/metadata/instruments` | GET | 1 req/5s | Instrument list |
| `/api/v0/equity/history/orders` | GET | 1 req/5s | Order history (cursor-paginated) |

### Key API Quirks

- **Ticker format**: `AAPL_US_EQ` (symbol + exchange + type suffix), NOT just `AAPL`
- **Sell orders use NEGATIVE quantity** (e.g., `-10.5` to sell 10.5 shares)
- **API is NOT idempotent** — duplicate POST requests create duplicate orders
- **50 max pending orders** per ticker per account
- **Rate limits are per-account** regardless of which API key or IP
- **No WebSocket** — must poll for positions, orders, and quotes

### Request/Response Formats

**Market Order Request:**
```json
{
  "ticker": "AAPL_US_EQ",
  "quantity": 0.1,
  "extendedHours": true
}
```

**Limit Order Request:**
```json
{
  "ticker": "AAPL_US_EQ",
  "quantity": 0.1,
  "limitPrice": 100.23,
  "timeValidity": "DAY"
}
```

**Stop Order Request:**
```json
{
  "ticker": "AAPL_US_EQ",
  "quantity": -0.1,
  "stopPrice": 95.00,
  "timeValidity": "GOOD_TILL_CANCEL"
}
```

**Order Response:**
```json
{
  "id": 12345,
  "createdAt": "2026-03-12T10:00:00Z",
  "currency": "USD",
  "ticker": "AAPL_US_EQ",
  "quantity": 0.1,
  "filledQuantity": 0.0,
  "side": "BUY",
  "status": "NEW",
  "type": "MARKET",
  "timeInForce": "DAY",
  "instrument": {
    "ticker": "AAPL_US_EQ",
    "name": "Apple Inc",
    "currency": "USD",
    "isin": "US0378331005"
  }
}
```

**Order Statuses:** `LOCAL`, `UNCONFIRMED`, `CONFIRMED`, `NEW`, `CANCELLING`, `CANCELLED`, `PARTIALLY_FILLED`, `FILLED`, `REJECTED`, `REPLACING`, `REPLACED`

**Account Summary Response:**
```json
{
  "id": 123456,
  "currency": "USD",
  "totalValue": 50000.00,
  "cash": {
    "availableToTrade": 25000.00,
    "reservedForOrders": 500.00,
    "inPies": 0.00
  },
  "investments": {
    "currentValue": 24500.00,
    "totalCost": 20000.00,
    "unrealizedProfitLoss": 4500.00,
    "realizedProfitLoss": 1200.00
  }
}
```

---

## Codebase Integration Surface — Complete File-by-File Map

### TIER 1 — Core Broker Infrastructure (7 files)

| # | File | Line(s) | Change Required |
|---|---|---|---|
| 1 | `src/brokers/__init__.py` | L26-30 | Add `BrokerFactory.register_broker('TRADING212', Trading212Broker)` |
| 2 | `src/brokers/trading212_broker.py` | NEW FILE | Full `BrokerInterface` implementation with rate limiter, ticker cache, auth |
| 3 | `src/services/broker_capabilities.py` | L30-79 | Add `BrokerCapability` entry: stocks=True, options=False |
| 4 | `src/services/broker_health_monitor.py` | L42-81 | Add health status map entry for TRADING212 |
| 5 | `src/services/broker_sync_service.py` | L2377-2400 | Add TRADING212 case in broker name normalization if-elif chain |
| 6 | `src/risk/position_cache.py` | L91-100 | Add `'TRADING212': 'Trading212'` to display name map |
| 7 | `src/services/unfilled_order_chaser.py` | L1319-1328 | Add TRADING212 to broker instance mapping |

### TIER 2 — Execution Flow: selfbot_webull.py (6 locations)

| # | Line(s) | Change Required |
|---|---|---|
| 8 | ~L6719 | Add TRADING212 to broker normalization dictionary |
| 9 | ~L11768 | Add TRADING212 to broker mapping |
| 10 | ~L12170 | Add TRADING212 to broker mapping |
| 11 | ~L12717 | Add TRADING212 to broker mapping |
| 12 | ~L12895 | Add TRADING212 to broker mapping |
| 13 | ~L15005 | Add 'TRADING212' to `uses_modern_signature` list (stock orders only) |
| 14 | ~L15356 | Add TRADING212 stock order branching |

### TIER 3 — BrokerManager (1 file)

| # | File | Change Required |
|---|---|---|
| 15 | `src/broker_manager.py` | Add TRADING212 init block (config-driven, Live + Paper, own try/except) |

### TIER 4 — GUI Routes & Database (3 files)

| # | File | Line(s) | Change Required |
|---|---|---|---|
| 16 | `gui_app/routes.py` | L7133-7139 | Add TRADING212 to internal broker adapter mapping |
| 17 | `gui_app/routes.py` | L10524-10579 | Add TRADING212 to order placement routing |
| 18 | `gui_app/routes.py` | L13342-13352 | Add TRADING212 to broker types mapping |
| 19 | `gui_app/routes.py` | L18838-18845 | Add TRADING212 to supported brokers list |
| 20 | `gui_app/database.py` | L3682 | Add 'TRADING212' to brokers list in `get_all_positions_for_user` |
| 21 | `gui_app/live_snapshot.py` | L965-971 | Add TRADING212 to fetch function mapping |

### TIER 5 — Frontend Templates (8 files)

| # | File | Line(s) | Change Required |
|---|---|---|---|
| 22 | `gui_app/templates/index.html` | L151-160 | Add TRADING212 to broker `<option>` dropdown |
| 23 | `gui_app/templates/index.html` | L2268 | Add TRADING212 JS brokerLabel conditional |
| 24 | `gui_app/templates/index.html` | L3117-3125 | Add TRADING212 CSS gradient mapping |
| 25 | `gui_app/templates/trades.html` | L172-179, L230-239 | Add TRADING212 to filter dropdowns |
| 26 | `gui_app/templates/performance.html` | L158-163 | Add TRADING212 to filter dropdown |
| 27 | `gui_app/templates/performance.html` | L376-380 | Add TRADING212 chart color |
| 28 | `gui_app/templates/execution.html` | L129-171 | Add TRADING212 multi-broker checkbox |
| 29 | `gui_app/templates/pnl_tracker.html` | L327-343 | Add `.broker-badge.trading212` CSS class |
| 30 | `gui_app/static/js/channels.js` | L6 | Add 'TRADING212' to `ALL_BROKERS` array |
| 31 | `gui_app/templates/options.html` | L1020-1027 | Hide/skip TRADING212 (no options support) |
| 32 | `ui/wizard/pages/broker_selection.py` | L259-263 | Add TRADING212 to setup wizard list |

### TIER 6 — Database Seed (1 operation)

| # | Change Required |
|---|---|
| 33 | INSERT into `broker_profiles`: broker_name=`TRADING212`, country_code=`UK`, display_name=`Trading 212`, credential_fields=`["api_key", "api_secret", "environment"]`, supports_options=`0`, supports_stocks=`1`, supports_paper=`1`, python_library=`requests` |

---

## Architecture Decisions (Architect-Reviewed)

### 1. Duplicate Order Guard — CRITICAL

**Problem:** T212 API is NOT idempotent. Duplicate POST = duplicate real order = real money at risk.

**Solution:** System-wide execution fingerprint guard (benefits all future non-idempotent brokers).
- Fingerprint: `SHA256(broker + channel + action + symbol + qty + 5-second time bucket)`
- Thread-safe TTL cache (5-10s window)
- Checked in `execute_on_single_broker` BEFORE any order POST
- Stored in memory (not DB — needs to be fast)

### 2. STC → Negative Quantity Conversion

**Decision:** Handle INSIDE the broker adapter (`trading212_broker.py`), not upstream.
- Adapter receives standard `(symbol, action='SELL', quantity=10)` call
- Internally converts to `quantity=-10` for the T212 API payload
- Keeps the adapter self-contained; no changes to upstream execution flow

### 3. Trading212DataHub — Yes, Create One

**Rationale:** Multiple consumers need position data (live snapshot, broker sync, risk monitor). Without a shared cache, each consumer polls independently, blowing the 1 req/5s rate limit.
- Simple polling cache: poll once every 5s, share cached result
- Pattern matches existing `webull_data_hub.py` / `schwab_data_hub.py`
- Exposes `get_positions()`, `get_account_summary()`, `get_pending_orders()` from cache

### 4. Ticker Translation Cache

- Load full instrument list from `/metadata/instruments` on `connect()`
- Build bidirectional map: `AAPL ↔ AAPL_US_EQ`
- TTL refresh: every 24 hours
- Unknown symbol fallback: try `{SYMBOL}_US_EQ` heuristic, log warning, fail gracefully
- Cache instrument metadata (minTradeQuantity, maxTradeQuantity) for fractional share validation

### 5. Per-Endpoint Rate Limiting

| Endpoint Category | Rate Limit | Implementation |
|---|---|---|
| Market orders | 50 req/min | Token bucket, 1 token per 1.2s |
| Limit/Stop/StopLimit orders | 1 req/2s | Strict sequential queue |
| Cancel orders | 50 req/min | Token bucket |
| Positions/Account/Instruments | 1 req/5s | Shared polling cache (DataHub) |
| Single order status | 1 req/1s | Individual rate gate |

### 6. Option Signal Handling

When an option signal arrives on a T212-enabled channel:
- Skip execution for T212 with log: `"[TRADING212] ⚠️ Options not supported — signal skipped"`
- Continue execution on other enabled brokers for that channel
- No crash, no error notification to the user
- Pre-flight capability check BEFORE calling `place_option_order`

### 7. Connection Test

- Use generic `broker.test_connection()` pattern (consistent with other brokers)
- T212 test hits `GET /api/v0/equity/account/summary`
- Returns account ID + available cash on success
- Add T212-specific branch in `api_test_broker_connection` route

---

## Execution Flow Detail

```
Signal arrives from Discord/Telegram
    │
    ▼
Channel's enabled_brokers includes "TRADING212"
    │
    ▼
execute_on_single_broker(signal, "TRADING212", t212_instance)
    │
    ├── Daily PnL Limit Check → Block if daily loss limit reached
    ├── Circuit Breaker (order_resilience) → Check for rapid-fire failures
    ├── Health Monitor → Verify T212 is responsive
    ├── Position Sizing → Calculate qty from portfolio % or fixed amount
    │
    ├── IF signal.asset == 'option':
    │       SKIP with log warning "Options not supported"
    │       Return {success: false, reason: 'options_not_supported'}
    │
    ├── IF signal.asset == 'stock':
    │       │
    │       ├── Duplicate Order Guard → Check fingerprint cache
    │       │       If duplicate: BLOCK, return {success: false, reason: 'duplicate'}
    │       │
    │       ├── Ticker Translation → AAPL → AAPL_US_EQ via instrument cache
    │       │       If unknown: try heuristic, log warning
    │       │
    │       ├── Quantity Conversion → BUY: positive, SELL: negative
    │       │
    │       ├── Order Type Selection:
    │       │       MARKET: POST /equity/orders/market (50/min limit)
    │       │       LIMIT:  POST /equity/orders/limit  (1/2s limit, queued)
    │       │
    │       ├── Rate Limiter → Wait for token before POST
    │       │
    │       ├── POST to Trading 212 API
    │       │
    │       ├── Parse Response → Map T212 statuses to internal statuses
    │       │       NEW/CONFIRMED → PENDING
    │       │       FILLED → OPEN
    │       │       REJECTED/CANCELLED → FAILED
    │       │
    │       └── Track in UnfilledOrderChaser (if not immediately filled)
    │
    ▼
BrokerSyncService (every 30s):
    ├── Poll GET /equity/portfolio → Reconcile with trades table
    ├── Poll GET /equity/orders → Check pending order statuses
    ├── Poll GET /equity/history/orders → Backfill fill prices
    └── Update execution_lots / execution_closures for PNL
```

---

## Impact Analysis — What Breaks

### Will NOT Break (Existing Functionality Safe)

| Subsystem | Why It's Safe |
|---|---|
| BrokerManager init | Each broker has its own try/except block; T212 failure won't affect others |
| Broker sync loop | Uses `asyncio.gather(return_exceptions=True)` + 3 layers of try/except |
| Live snapshot page | Only fetches brokers in its hardcoded dictionary; T212 simply won't appear |
| Order routing (routes.py) | Has explicit `else: return 400 "Unknown broker"` |
| Options page | Falls back to Webull/Alpaca for data |
| Risk engine | Completely broker-agnostic |
| Signal parser | Completely broker-independent |

### Functional Gaps If Not Fully Wired

| Gap | Impact | Severity |
|---|---|---|
| Option signals on T212 channels | Silent `AttributeError` instead of clean skip | Medium |
| Order chaser won't track T212 | Unfilled limit orders never get chased | High |
| Position sync returns empty | Trades stay "OPEN" forever, no PNL updates | High |
| Live snapshot page | T212 positions invisible on dashboard | Medium |
| PNL badge styling | Unstyled badge, visually inconsistent | Low |

### Integration Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Duplicate orders from non-idempotent API | **CRITICAL** | System-wide fingerprint guard with 5s TTL |
| Bad import in `src/brokers/__init__.py` | **CRITICAL** | Test import before registering; lazy import pattern |
| Typo in selfbot_webull.py broker mappings | **HIGH** | Grep verification after each edit |
| Rate limit 429 during multi-signal bursts | HIGH | Per-endpoint token bucket with async queue |
| Database migration constraint violation | HIGH | Test INSERT on paper DB first |
| Symbol not found (OTC, recent IPO) | MEDIUM | Heuristic fallback + graceful failure |
| Position sync staleness (5s polling lag) | MEDIUM | Acceptable for stocks; document the lag |
| API is beta — could change | MEDIUM | Abstraction layer isolates changes |

---

## Implementation Phases & Dependencies

```
Phase 1: Core Broker Module
├── trading212_broker.py (BrokerInterface implementation)
├── Trading212Client (HTTP client with auth, rate limiter)
├── Ticker translation cache
├── Duplicate order fingerprint guard
└── Unit tests against demo.trading212.com
    │
    ▼
Phase 2: Execution Flow Wiring (depends on Phase 1)
├── BrokerFactory registration
├── BrokerManager init block
├── selfbot_webull.py broker mappings (6 locations)
├── uses_modern_signature list
├── Option signal skip logic
└── Grep verification: all 6 mapping dicts updated
    │
    ▼
Phase 3: Sync + Order Chaser + PNL (depends on Phase 2)
├── Trading212DataHub (polling cache)
├── BrokerSyncService normalization case
├── UnfilledOrderChaser broker instance map
├── Position reconciliation logic
├── Fill price backfill from order history
├── execution_lots / execution_closures population
└── Risk position cache update
    │
    ├──────────────────────────────┐
    ▼                              ▼
Phase 4a: GUI/Database         Phase 4b: Frontend Templates
├── broker_profiles seed       ├── index.html (dropdown, label, CSS)
├── routes.py (4 locations)    ├── trades.html (2 dropdowns)
├── database.py (1 location)   ├── performance.html (dropdown + color)
├── live_snapshot.py            ├── execution.html (checkbox)
├── Connection test route       ├── pnl_tracker.html (badge CSS)
├── broker_capabilities.py     ├── channels.js (ALL_BROKERS)
├── broker_health_monitor.py   ├── options.html (hide T212)
└── position_cache.py          └── wizard/broker_selection.py
    │                              │
    └──────────────┬───────────────┘
                   ▼
             Phase 5: Validation
             ├── Demo/Paper trading test suite
             ├── Buy/sell fractional shares
             ├── Cancel + replace chase test
             ├── Rate limit soak test
             ├── Duplicate protection replay test
             ├── Multi-broker parallel execution test
             └── PNL page verification
```

### Phase Estimates

| Phase | Files | Complexity | Estimate |
|---|---|---|---|
| Phase 1: Core Broker | 1 new file | High (rate limiter, ticker cache, auth, dedup guard) | Core foundation |
| Phase 2: Execution | 2 files, 8 locations | Medium (pattern-matching existing brokers) | Wiring |
| Phase 3: Sync/PNL | 3 files | High (normalization, DataHub, fill backfill) | Data pipeline |
| Phase 4a: GUI/DB | 5 files, 8 locations | Low-Medium (additive changes) | Configuration |
| Phase 4b: Frontend | 8 files, 12 locations | Low (additive HTML/CSS/JS) | UI polish |
| Phase 5: Validation | 0 files (testing only) | Medium (live API testing) | Verification |

---

## Database Schema

### broker_profiles Row

```sql
INSERT INTO broker_profiles (
    country_code, broker_name, display_name, credential_fields,
    python_library, supports_options, supports_stocks, supports_paper,
    token_expiry_info, enabled, display_order
) VALUES (
    'UK', 'TRADING212', 'Trading 212',
    '["api_key", "api_secret", "environment"]',
    'requests', 0, 1, 1,
    'API keys do not expire. Generate from Trading 212 app settings.',
    1, 10
);
```

### broker_credentials Storage

```json
{
    "api_key": "user_provided_key",
    "api_secret": "user_provided_secret",
    "environment": "demo"
}
```

### Trading 212 Brand Colors (for UI)

```css
.broker-badge.trading212 {
    background: linear-gradient(135deg, #0052FF, #00A3FF);
    color: #fff;
}
```

Chart color: `#0052FF` (Trading 212 brand blue)

---

## BrokerInterface Method Mapping

| BrokerInterface Method | Trading 212 Implementation |
|---|---|
| `connect()` | Base64 encode key:secret, GET /account/summary to validate |
| `disconnect()` | Close HTTP session |
| `get_account_info()` | GET /account/summary → map to {buying_power, cash, portfolio_value} |
| `get_positions()` | GET /portfolio → normalize to standard position format |
| `place_stock_order(symbol, action, qty, price)` | Translate ticker, negate qty for SELL, POST /orders/market or /orders/limit |
| `place_option_order(...)` | Return `{success: False, error: 'Options not supported on Trading 212'}` |
| `get_quote(symbol)` | GET /portfolio/{ticker} for held positions, or use QuoteAggregator fallback |
| `cancel_order(order_id)` | DELETE /orders/{id} |
| `get_pending_orders()` | GET /orders |
| `get_order_history(count)` | GET /history/orders with cursor pagination |
| `test_connection()` | GET /account/summary, return success + account_id |

---

## No-Go Scenarios (When NOT to Route to T212)

| Scenario | Action |
|---|---|
| Option signal (calls/puts) | Skip T212, execute on other enabled brokers |
| Short selling (STC without position) | Block — T212 Invest accounts don't support shorting |
| Order value exceeds account currency | Block — T212 only executes in primary account currency |
| Symbol not in instrument list | Skip with warning, attempt heuristic, fail gracefully |
| Rate limit 429 received | Queue and retry after backoff, do NOT duplicate the order |
| Market closed + market order | T212 queues until market opens (inform user) |
