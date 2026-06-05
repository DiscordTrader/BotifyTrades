# TRADE212 Integration Plan — BotifyTrades (Definitive)

## Architect Review: Attached Document vs Replit Plan vs Actual Codebase

### Gap Reality Check — Attached Document's 26 Gaps

The attached architecture document scores the system very low (Risk=0/10, Discord Intake=3/10) and proposes 26 gaps. **Most of these are phantom gaps** — the BotifyTrades codebase already has robust implementations. Here is the truth table:

| Attached Doc Gap | Score Given | ACTUAL Status | What Already Exists |
|---|---|---|---|
| GAP-01: No signal persistence | CRITICAL | **SOLVED** | SQLite `trades` table + `PositionLedger` persists all signals/trades across restarts |
| GAP-02: No duplicate signal guard | CRITICAL | **SOLVED** | `SignalDeduplicator` in `signal_parsing_pipeline.py` — TTL cache with async locks |
| GAP-03: No signal schema validation | CRITICAL | **SOLVED** | 5-tier parsing pipeline with Pydantic-style validation + confidence scoring (blocks <0.8) |
| GAP-04: No channel/role authorization | HIGH | **SOLVED** | `allowed_author_ids`, `allowed_guild_ids`, per-channel EXECUTE/TRACK flags |
| GAP-05: No signal-to-broker routing | HIGH | **SOLVED** | `SignalRoutingEngine` with per-channel broker selection + routing ledger |
| GAP-06: No pre-trade risk gateway | CRITICAL | **SOLVED** | Full risk engine: position sizing limits, daily P&L limits, market hours, buying power checks |
| GAP-07: No order idempotency | CRITICAL | **PARTIAL** | `ExitArbiter` locks + `OrderResilienceLayer`; T212-specific fingerprint guard needed |
| GAP-08: No fill confirmation | CRITICAL | **SOLVED** | `UnfilledOrderChaser` with configurable timeout + chase + cancel |
| GAP-09: No partial fill handling | HIGH | **SOLVED** | `TradeState.remaining_qty` tracking + ratio-based partial exits |
| GAP-10: Clock drift | CRITICAL | **MINOR** | Low priority — system uses asyncio event loop competently; T212 DataHub will use proper timing |
| GAP-11: No cache TTL/eviction | HIGH | **SOLVED** | Enrichment cache pruning, position cache cycle management |
| GAP-12: No delta thresholds | HIGH | **N/A** | Uses WebSocket streaming for Webull/Schwab — no noise issue; T212 DataHub polls at 5s intervals |
| GAP-13: No cross-broker reconciliation | MEDIUM | **SOLVED** | `BrokerSyncService` runs every 30s reconciling DB vs broker positions |
| GAP-14: No durable event bus | CRITICAL | **SOLVED** | SQLite trades/execution_lots/execution_closures provide full persistence |
| GAP-15: No P&L aggregation | CRITICAL | **SOLVED** | `DailyPnLLimitService` + cross-broker P&L tracking + per-trade FIFO lot matching |
| GAP-16: No signal_id linkage | HIGH | **SOLVED** | `routing_mapping_id` links trades to originating signals |
| GAP-17: No schema versioning | MEDIUM | **LOW PRIORITY** | Internal system — schema migrations handled by database.py |
| GAP-18: No kill switch | CRITICAL | **SOLVED** | `CircuitBreaker.halt_global()` in `circuit_breaker.py` |
| GAP-19: No daily max-loss breaker | CRITICAL | **SOLVED** | `DailyPnLLimitService` with dollar/percentage limits, auto-lock on breach |
| GAP-20: No position size limits | CRITICAL | **SOLVED** | `position_sizing_service.py` with max_position_pct, min/max contracts |
| GAP-21: No market hours check | HIGH | **SOLVED** | `market_hours.py` with holidays, pre/after-market, weekend detection |
| GAP-22: No health endpoints | CRITICAL | **SOLVED** | Flask dashboard + `/api/v2/broker-states` + health monitoring |
| GAP-23: No structured logging | CRITICAL | **SOLVED** | `logging_config.py` with specialized loggers (signal, execution, balance, etc.) |
| GAP-24: No alerting | HIGH | **PARTIAL** | Console + dashboard alerts exist; no PagerDuty (not needed for this deployment) |
| GAP-25: No secret management | HIGH | **SOLVED** | Replit Secrets + encrypted config table in SQLite |
| GAP-26: No soft-throttle detection | MEDIUM | **REAL GAP** | Needs implementation in T212 DataHub |

**Summary: 22 of 26 gaps are PHANTOM (already solved). Only 4 items have value:**
- GAP-07 partial: T212-specific duplicate order fingerprint guard
- GAP-10 minor: perf_counter-anchored polling (good practice for DataHub)
- GAP-24 partial: External alerting (low priority)
- GAP-26 real: T212 soft-throttle detection via response time P99

### Attached Document — What to REJECT

| Recommendation | Why It's Rejected |
|---|---|
| Redis Streams for signal persistence | System uses SQLite — works perfectly, no Redis dependency needed |
| Redis-backed kill switch | `CircuitBreaker.halt_global()` already exists in-process |
| FastAPI health endpoints | System uses Flask — adding FastAPI creates dual-framework mess |
| Prometheus metrics | System has its own monitoring via Flask dashboard |
| PagerDuty integration | Overkill for current deployment; Discord alerts sufficient |
| structlog migration | Existing `logging_config.py` is comprehensive |
| Pydantic v2 migration | System already validates signals through 5-tier pipeline |
| aiohttp client library | System uses `httpx` (Schwab) and `requests`; stay consistent |

### Attached Document — What to ADOPT

| Idea | How to Adapt |
|---|---|
| Adaptive polling states (pending/active/watching/idle) | Implement in Trading212DataHub with proper intervals |
| Dual-endpoint interleave (portfolio ↔ orders) | Good for cutting effective latency in DataHub poller |
| perf_counter-anchored timing | Use in DataHub polling loop |
| Soft-throttle detection (P99 monitoring) | Add response time tracking in Trading212Client |
| Token bucket per endpoint | Already have `rate_limit_manager.py` — add T212 profile |

### Replit Plan — What to KEEP (Almost Everything)

| Component | Status |
|---|---|
| 33 touch-point file-by-file map | ✅ Keep — verified accurate |
| 5-phase dependency chain | ✅ Keep — correct ordering |
| Rate limit analysis (GET /portfolio bottleneck) | ✅ Keep — critical constraint |
| Trading212DataHub centralized cache | ✅ Keep — mandatory solution |
| Duplicate order fingerprint guard | ✅ Keep — T212 API is not idempotent |
| Ticker translation cache (AAPL → AAPL_US_EQ) | ✅ Keep — required for all T212 API calls |
| Negative quantity for SELL | ✅ Keep — handled inside adapter |
| Per-endpoint rate limiting | ✅ Keep — enhance with soft-throttle detection |
| BrokerInterface pattern | ✅ Keep — consistent with other brokers |

---

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
- **Soft throttle**: Returns 200 OK with stale data (NOT 429) — must detect via response time P99

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

## Definitive Architecture Decisions

### 1. Duplicate Order Guard — CRITICAL (System-Wide)

**Problem:** T212 API is NOT idempotent. Duplicate POST = duplicate real order = real money at risk.

**Solution:** System-wide execution fingerprint guard (benefits all future non-idempotent brokers).
- Fingerprint: `SHA256(broker + channel + action + symbol + qty + 5-second time bucket)`
- Thread-safe TTL cache (5-10s window) — in-memory, not Redis
- Checked in `execute_on_single_broker` BEFORE any order POST
- Stored in memory (not DB — needs to be fast)

### 2. STC → Negative Quantity Conversion

**Decision:** Handle INSIDE the broker adapter (`trading212_broker.py`), not upstream.
- Adapter receives standard `(symbol, action='SELL', quantity=10)` call
- Internally converts to `quantity=-10` for the T212 API payload
- Keeps the adapter self-contained; no changes to upstream execution flow

### 3. Trading212DataHub — Centralized Polling Cache (MANDATORY)

**Rationale:** Multiple consumers need position data (live snapshot, broker sync, risk monitor). Without a shared cache, each consumer polls independently, blowing the 1 req/5s rate limit.

**Design (enhanced from both documents):**
```
                    Trading212DataHub
                    (Single Poller)
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    GET /portfolio  GET /orders  GET /account/summary
    (every 5s)      (every 5s)   (every 10s)
          │              │              │
          ▼              ▼              ▼
      positions_cache  orders_cache  account_cache
          │              │              │
    ┌─────┼─────┐   ┌───┼───┐     ┌───┼───┐
    │     │     │   │       │     │       │
  Risk  Price  Live Sync  Chaser Snapshot Dashboard
  Engine Mon.  Snap Svc          Daemon
```

**Adaptive Polling States (from attached document — good idea):**
| State | Interval | Trigger |
|---|---|---|
| `idle` | 30s | No open positions, no pending orders |
| `watching` | 5s | Positions open, no pending activity |
| `active` | 2s (interleaved = 1s effective) | Active trading, positions being monitored |
| `pending` | 1s (interleaved = 0.5s effective) | Order just submitted, awaiting fill confirmation |

**State Transitions:**
```
idle → watching  (position detected OR order placed)
watching → active  (risk engine evaluating positions)
active → pending  (BTO/STC order submitted)
pending → active  (fill confirmed)
active → watching  (no evaluations for 60s)
watching → idle  (no positions for 5 min)
```

**Soft-Throttle Detection (from attached document):**
- Track response time P99 for each endpoint
- If P99 > 2.5× baseline median → treat as soft throttle
- Back off to maximum interval, mark prices as stale
- Alert operator via console log

**perf_counter-Anchored Timing (from attached document):**
- Use `time.perf_counter()` for wall-clock-anchored intervals
- Calculate actual sleep needed after subtracting work time
- Log drift warnings when > 200ms

### 4. Ticker Translation Cache

- Load full instrument list from `/metadata/instruments` on `connect()`
- Build bidirectional map: `AAPL ↔ AAPL_US_EQ`
- TTL refresh: every 24 hours
- Unknown symbol fallback: try `{SYMBOL}_US_EQ` heuristic, log warning, fail gracefully
- Cache instrument metadata (minTradeQuantity, maxTradeQuantity) for fractional share validation

### 5. Per-Endpoint Rate Limiting

Uses existing `rate_limit_manager.py` with T212-specific profile:

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

### TIER 4 — GUI Routes & Database (14 files — EXPANDED after audit)

| # | File | Line(s) | Change Required | Gap Status |
|---|---|---|---|---|
| 16 | `gui_app/routes.py` | L7133-7139 | Add TRADING212 to internal broker adapter mapping | ✅ In plan |
| 17 | `gui_app/routes.py` | L10524-10579 | Add TRADING212 to order placement routing | ✅ In plan |
| 18 | `gui_app/routes.py` | L13342-13352 | Add TRADING212 to broker types mapping | ✅ In plan |
| 19 | `gui_app/routes.py` | L18838-18845 | Add TRADING212 to supported brokers list | ✅ In plan |
| 20 | `gui_app/database.py` | L3682 | Add 'TRADING212' to brokers list in `get_all_positions_for_user` | ✅ In plan |
| 21 | `gui_app/live_snapshot.py` | L965-971 | Add TRADING212 to fetch function mapping + new `_fetch_trading212()` | ✅ In plan |
| 22 | `gui_app/routes.py` | L5700-5714 | Add TRADING212 to `SUPPORTED_CANCEL_BROKERS` dict (order cancellation via DELETE /orders/{id}) | 🆕 GAP-01 |
| 23 | `gui_app/routes.py` | L5809 | Add `if 'TRADING212' in broker:` block in `close_position_by_id` (sell-to-close via market order with negative qty) | 🆕 GAP-03 |
| 24 | `gui_app/routes.py` | L18593 | Add `trading212` to `EXTENDED_HOURS_SUPPORT` dict (T212 supports extended hours via `extendedHours: true` flag) | 🆕 GAP-04 |
| 25 | `gui_app/routes.py` | L18216 | Add `elif broker_name == 'trading212':` block in `api_test_broker_connection` | 🆕 GAP-05 |
| 26 | `gui_app/routes.py` | L18803 | Add `('trading212', 'broker', 'UK', 'USD')` to initialization status check list | 🆕 GAP-06 |
| 27 | `gui_app/routes.py` | L18873 | Add `trading212` entry to `BROKER_CONFIGS` dict (country=UK, currency=USD/GBP/EUR) | 🆕 GAP-07 |
| 28 | `gui_app/routes.py` | L1671 | Add `trading212` entry to `BROKER_REGIONS` dict | 🆕 GAP-08 |
| 29 | `gui_app/routes.py` | NEW | Add `GET/POST /api/brokers/credentials/trading212` endpoint (API Key + Environment selector) | 🆕 GAP-25 |
| 30 | `gui_app/database.py` | L3683 | Add 'TRADING212' to default brokers fallback list | 🆕 GAP-20 |
| 31 | `gui_app/database.py` | L12800 | Ensure `broker_limits` table tracks T212 rate limit hits (auto if broker_name column is generic) | 🆕 GAP-23 |
| 32 | `gui_app/broker_credentials_service.py` | NEW funcs | Add `save_trading212_credentials()` and `get_trading212_credentials()` | 🆕 GAP-26 |
| 33 | `src/core/config_loader.py` | credentials | Add T212 to `load_credentials_from_database()` so BrokerFactory receives T212 creds at startup | 🆕 GAP-27 |
| 34 | `gui_app/routes.py` | L4353-4413 | Add `trading212_live` and `trading212_paper` entries to `/api/brokers/all_accounts` response + T212 account data fetch block | 🆕 GAP-32 |
| 35 | `gui_app/routes.py` | L13039-13170 | Add T212 connection status check block in `/api/brokers/status`: `getattr(_bot_instance, 'trading212_broker', None)` → check `.connected` → `set_broker_status()` | 🆕 GAP-33 |
| 36 | `gui_app/routes.py` | L13181-13195 | Add `'TRADING212': 'trading212'` and `'TRADING212_PAPER': 'trading212_paper'` to health monitor `broker_map` dict | 🆕 GAP-34 |
| 37 | `gui_app/routes.py` | L6981-6989 | **CRITICAL:** Add `'TRADING212': 'trading212_broker'` to `/api/trades/close-all` `broker_attr_map`. Without this, emergency Close All SKIPS T212 positions. | 🆕 GAP-35 |

### TIER 5 — Frontend Templates & JS (EXPANDED after Channels/Execution audit)

| # | File | Line(s) | Change Required | Gap Status |
|---|---|---|---|---|
| 34 | `gui_app/templates/index.html` | L147 | Add TRADING212 to Account Balance filter dropdown | 🆕 GAP-09 |
| 35 | `gui_app/templates/index.html` | L151-160 | Add TRADING212 to main broker `<option>` dropdown | ✅ In plan |
| 36 | `gui_app/templates/index.html` | L321 | Add TRADING212 to Filled Orders filter dropdown | 🆕 GAP-10 |
| 37 | `gui_app/templates/index.html` | L1093 | Add `.broker-badge.trading212` CSS class (gradient: `linear-gradient(135deg, #0052FF, #00A3FF)`) | 🆕 GAP-11 |
| 38 | `gui_app/templates/index.html` | L1912-2100 | Add TRADING212 to JS broker labeling + color mapping logic | 🆕 GAP-12 |
| 39 | `gui_app/templates/index.html` | L2268 | Add TRADING212 JS brokerLabel conditional | ✅ In plan |
| 40 | `gui_app/templates/index.html` | L3117-3125 | Add TRADING212 CSS gradient mapping | ✅ In plan |
| 41 | `gui_app/templates/trades.html` | L153-154 | Add `.qt-source.trading212` CSS class for Quick Trade badges | 🆕 GAP-13 |
| 42 | `gui_app/templates/trades.html` | L171 | Add TRADING212 to Quick Trade broker selector dropdown | 🆕 GAP-14 |
| 43 | `gui_app/templates/trades.html` | L172-179, L230-239 | Add TRADING212 to trade filter dropdowns | ✅ In plan |
| 44 | `gui_app/templates/performance.html` | L158-163 | Add TRADING212 to filter dropdown | ✅ In plan |
| 45 | `gui_app/templates/performance.html` | L376-380 | Add TRADING212 chart color `#0052FF` | ✅ In plan |
| 46 | `gui_app/templates/execution.html` | L129-171 | Add TRADING212 multi-broker checkbox | ✅ In plan |
| 47 | `gui_app/templates/pnl_tracker.html` | L327-343 | Add `.broker-badge.trading212` CSS class with gradient | ✅ In plan |
| 48 | `gui_app/templates/options.html` | L1020-1027 | Hide/skip TRADING212 (no options support) | ✅ In plan |
| 49 | `gui_app/templates/options.html` | L1435-1444 | Add `trading212` to `brokerRefreshRates` JS object (rate: 5000ms) | 🆕 GAP-15 |
| 50 | `gui_app/templates/settings.html` | L349-356 | Add Trading 212 connection status badge to status grid | 🆕 GAP-16 |
| 51 | `gui_app/templates/settings.html` | L620-900 | Add Trading 212 credential input section (API Key + Environment dropdown: live/demo) | 🆕 GAP-17 |
| 52 | `gui_app/templates/verification.html` | L105 | Add TRADING212 to broker verification selector | 🆕 GAP-18 |
| 53 | `gui_app/templates/brokers.html` | L747 | Add TRADING212 to multi-broker management selector | 🆕 GAP-19 |
| 54 | `gui_app/static/js/channels.js` | L6 | Add 'TRADING212' to `ALL_BROKERS` array | ✅ In plan |
| 55 | `ui/wizard/pages/broker_selection.py` | L259-263 | Add TRADING212 to setup wizard broker checklist | ✅ In plan |
| 56 | `ui/wizard/pages/broker_credentials.py` | Dynamic | Add TRADING212 credential form generation (API Key + Environment) | 🆕 GAP-28 |
| 57 | `gui_app/static/js/channels.js` | L125-194 | **Per-channel broker checkboxes are HARDCODED HTML, not generated from ALL_BROKERS.** Must add 2 new `<label>` blocks: TRADING212 LIVE (icon 📊, color #0052FF) + TRADING212 PAPER (icon 📊, color #00ff88) | 🆕 GAP-29 |
| 58 | `gui_app/templates/execution.html` | L7-57 | Add T212 account overview card to top dashboard (blue gradient `#0052FF→#00A3FF`, buying power + net liq) | 🆕 GAP-30 |
| 59 | `gui_app/templates/execution.html` | L220-265 | Add `data.trading212_live` handler in `loadAllAccounts()` JS to populate T212 card | 🆕 GAP-31 |
| 60 | `gui_app/templates/channels.html` | L930 | Update description text to include "Trading 212" in broker list | 🆕 GAP-36 |

### TIER 6 — New Files

| # | File | Purpose |
|---|---|---|
| 61 | `src/brokers/trading212_broker.py` | BrokerInterface implementation |
| 62 | `src/services/trading212_data_hub.py` | Centralized polling cache with adaptive states |
| 63 | `src/services/trading212_client.py` | HTTP client with auth, rate limiter, soft-throttle detection |

### TIER 7 — Database Seed

| # | Change Required | Gap Status |
|---|---|---|
| 64 | INSERT into `broker_profiles`: broker_name=`TRADING212`, country_code=`UK`, display_name=`Trading 212`, credential_fields=`["api_key", "environment"]`, supports_options=`0`, supports_stocks=`1`, supports_paper=`1`, python_library=`requests` | ✅ In plan (expanded) |

### TIER 8 — Risk Engine (from risk engine audit — R21-R24)

| # | File | Line(s) | Change Required | Gap Status |
|---|---|---|---|---|
| 65 | `src/risk/position_monitor.py` | L1077-1081 | Add `trading212_broker=None` parameter to `RiskManager.__init__()` | 🆕 R22 |
| 66 | `src/selfbot_webull.py` | L8132-8141 | Add `trading212_broker=self.trading212_broker` to `RiskManager()` instantiation call | 🆕 R23 |
| 67 | `src/risk/position_monitor.py` | L3078-3093 | Add `elif 'TRADING212' in broker_upper: broker_instance = self.trading212_broker` to `_direct_execute_exit()` | 🆕 R21 |
| 68 | `src/risk/position_monitor.py` | L1613-1621 | Add `trading212_count` to position summary logging | 🆕 R24 |

### REVISED TOTAL: 68 touch points (was 36 → 60 → 68 across 3 audit rounds)

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

## Rate Limit Budget — The Hard Constraint

### GET /portfolio (1 req/5s = 12 req/min MAX) — #1 BOTTLENECK

**Without DataHub (WILL BREACH):**

| Consumer | Calls/min | T212 Limit/min | Status |
|---|---|---|---|
| Risk Engine (position monitor) | 12–60 | 12 | BREACH |
| Broker Sync Service | 2 | 12 | OK alone |
| Live Snapshot Daemon | 12 | 12 | AT LIMIT alone |
| **TOTAL (best case)** | **26** | **12** | **2x OVER** |

**With DataHub (SAFE):**

| Endpoint | DataHub Poll Rate | T212 Limit | Status |
|---|---|---|---|
| GET /portfolio | 1 req/5s | 1 req/5s | AT LIMIT (safe) |
| GET /orders | 1 req/5s | 1 req/5s | AT LIMIT (safe) |
| GET /account/summary | 1 req/10s | 1 req/5s | UNDER LIMIT (safe) |
| GET /history/orders | 1 req/30s | 1 req/5s | UNDER LIMIT (safe) |

All consumers read from DataHub cache — ZERO direct API calls.

### Unfilled Order Chaser — Requires T212-Specific Throttling

| Setting | Standard Brokers | T212 Value | Reason |
|---|---|---|---|
| risk_check_interval_seconds | 1s | 5s (minimum) | Match /portfolio rate limit |
| order_chase_timeout | 4s | 10s | Slower chase to stay within limits |
| order_chase_max_attempts | 3 | 2 | Fewer chases to conserve API budget |
| order_chase_status_poll | 1s | 5s | Match /orders rate limit |

---

## Execution Flow

```
Signal arrives from Discord/Telegram
    │
    ▼
Channel's enabled_brokers includes "TRADING212"
    │
    ▼
execute_on_single_broker(signal, "TRADING212", t212_instance)
    │
    ├── Duplicate Order Fingerprint Guard → Check SHA256 cache
    │       If duplicate within 5s: BLOCK, return {success: false, reason: 'duplicate'}
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
    ├── Read from Trading212DataHub cache → Reconcile with trades table
    ├── Check pending order statuses (from DataHub orders cache)
    ├── Backfill fill prices from order history (from DataHub history cache)
    └── Update execution_lots / execution_closures for PNL
```

---

## Implementation Phases & Dependencies

```
Phase 1: Core Broker Module + HTTP Client
├── trading212_client.py (HTTP client with auth, rate limiter, soft-throttle)
├── trading212_broker.py (BrokerInterface implementation)
├── Ticker translation cache with 24h TTL refresh
├── Duplicate order fingerprint guard (system-wide, benefits all brokers)
└── Test against demo.trading212.com
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
Phase 3: DataHub + Sync + Order Chaser (depends on Phase 2)
├── Trading212DataHub (centralized polling cache with adaptive states)
├── BrokerSyncService normalization case
├── UnfilledOrderChaser broker instance map (throttled intervals)
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
             ├── Rate limit soak test (idle/light/normal/heavy scenarios)
             ├── Soft-throttle detection verification
             ├── Duplicate protection replay test
             ├── Multi-broker parallel execution test
             └── PNL page verification
```

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

## No-Go Scenarios (When NOT to Route to T212)

| Scenario | Action |
|---|---|
| Option signal (calls/puts) | Skip T212, execute on other enabled brokers |
| Short selling (STC without position) | Block — T212 Invest accounts don't support shorting |
| Order value exceeds account currency | Block — T212 only executes in primary account currency |
| Symbol not in instrument list | Skip with warning, attempt heuristic, fail gracefully |
| Rate limit soft-throttle detected | Queue and retry after backoff, do NOT duplicate the order |
| Market closed + market order | T212 queues until market opens (inform user) |

---

## Risk Register — Where the Bot WILL Break

### CRITICAL Risks (Will cause real financial loss if not mitigated)

| ID | Component | What Breaks | Conditions | Probability | Mitigation |
|---|---|---|---|---|---|
| R12 | `broker_sync_service._fetch_and_normalize()` | **Missing T212 branch in if/elif chain returns empty positions/orders.** After 2 consecutive empty responses, sync service marks OPEN trades as cancelled. T212 trades get falsely closed in DB, triggering duplicate re-imports and phantom "closed externally" events. | T212 added to BrokerManager but not to sync service's explicit if/elif dispatch | Certain (if missed) | Add explicit TRADING212 normalizer branch. Change unknown-broker fallback from empty-success to logged error. |
| R14 | `position_monitor._fetch_all_positions()` | **Risk engine completely blind to T212 positions.** Stop losses, trailing stops, profit targets — NONE fire for T212 positions. Positions sit with no risk protection. | T212 positions exist but no `_fetch_trading212_cached()` function in the hardcoded asyncio.gather list | Certain (if missed) | Add `_fetch_trading212_cached()` to the gather list. Wire Trading212DataHub as the data source (no direct API calls). |
| R18 | `execute_on_single_broker` + `order_resilience.py` | **Duplicate real orders on T212.** Network timeout → OrderResilienceLayer retries → T212 receives duplicate POST → two real orders fill → double position. T212 API is NOT idempotent. | Network timeout during POST /orders/market or /orders/limit, followed by automatic retry | Likely | Implement SHA256 fingerprint guard (broker+channel+action+symbol+qty+5s bucket) checked BEFORE POST. For T212 specifically: on timeout, probe GET /orders first before retrying. |
| R21 | `position_monitor._direct_execute_exit()` (L3078-3093) | **Risk engine SL/PT exits SILENTLY FAIL for T212.** The backup direct execution path has an if/elif chain for 7 broker variants (Robinhood, Schwab, Alpaca, IBKR, Tastytrade, Webull, Webull_Paper). Missing TRADING212 branch → prints "No broker instance" → does nothing. Position bleeds without protection. **WORSE than R14**: R14 = can't see positions. R21 = can see them but can't ACT on them. | Risk engine triggers SL/PT/trailing stop for any T212 position AND primary order_queue worker is slow/blocked | Certain (if missed) | Add `elif 'TRADING212' in broker_upper: broker_instance = self.trading212_broker` to the if/elif chain. This is part of a **3-LINK CHAIN** with R22 and R23 — all 3 must be fixed together. |
| R22 | `RiskManager.__init__()` (L1077-1081) | **Constructor has no trading212_broker parameter.** Even with R21's elif branch added, `self.trading212_broker` raises AttributeError because it was never set. The init signature only accepts: alpaca_broker, schwab_broker, ibkr_broker, tastytrade_broker, robinhood_broker. | R21 fix attempted without R22 | Certain (if missed) | Add `trading212_broker=None` parameter to `__init__()`, store as `self.trading212_broker = trading212_broker`. |
| R23 | `selfbot_webull.py` RiskManager() instantiation (L8132-8141) | **T212 broker instance never passed to RiskManager.** The actual call only passes alpaca_broker, schwab_broker, robinhood_broker. Even with R21+R22 fixed, trading212_broker=None → exits still silently fail. **This is the 3rd link in the R21-R22-R23 chain.** | R21+R22 fixed but R23 missed | Certain (if missed) | Add `trading212_broker=self.trading212_broker` to the RiskManager() constructor call. |

### HIGH Risks (Will cause functional failures)

| ID | Component | What Breaks | Conditions | Probability | Mitigation |
|---|---|---|---|---|---|
| R1-R6 | `selfbot_webull.py` (6 broker_map locations) | **T212 signals silently dropped on one or more execution paths.** There are 6 SEPARATE identical broker_map dictionaries at lines ~7005, ~12047, ~12449, ~12868, ~12996, ~13220. Missing T212 from ANY ONE causes that path to silently skip T212 with no error. User sees trade execute on Webull/Schwab but not on T212 — no crash, no log, no indication. | T212 added to 5 of 6 maps but one is missed (easy to do — they're spread across 6000+ lines) | Certain (one will be missed) | Refactor: extract ONE centralized `BROKER_MAP` constant at module level. All 6 locations reference it. Add startup assertion verifying TRADING212 is in the map. |
| R7 | `execute_on_single_broker` | **Option signal attempts T212 execution, fails confusingly.** Code checks `signal['asset'] == 'option'` then calls `place_option_order()`. T212 adapter returns error dict, but the try/except around the entire block catches it as generic failure. DB trade record may still be created with status PENDING that never resolves. | Option signal on a channel with T212 enabled alongside other brokers | Likely | Add early capability check: `if broker == TRADING212 and asset == option: return {success: False, reason: 'options_not_supported', skipped: True}` BEFORE the option/stock dispatch. This must be a clean skip, not a failure. |
| R8 | `execute_on_single_broker` result handling | **Error result from T212 triggers downstream side effects.** If T212 returns a dict with unexpected keys (e.g., T212 error body containing an `id` field), post-execution logic may interpret it as a successful order and register it in the unfilled order chaser or create execution lots. | T212 API error response has `id` or `orderId` field in error body | Possible | Enforce canonical success contract: only trigger DB/chaser/lot side effects when `result.get('success') is True` (strict boolean check). |
| R10 | `BrokerManager.initialize()` | **T212 instance stored in partial/disconnected state.** If `connect()` returns False (not raises), the instance may still be stored in self.brokers and later used for order execution, causing silent failures or API errors. | T212 API key invalid, environment wrong, or demo.trading212.com down during startup | Possible | Guard: `if await broker.connect() is True: self.brokers[name] = broker` with explicit True check. Add `is_connected()` health check method. |
| R11 | `broker_sync_service._perform_sync()` | **T212 never synced even when positions exist.** _perform_sync uses HARDCODED attribute checks like `hasattr(self.broker_manager, 'webull_broker')`. Without `trading212_broker` attribute, sync loop skips T212 entirely. Trades stay PENDING forever, no P&L updates, fills never confirmed in DB. | T212 added to BrokerManager but _perform_sync hardcoded list not updated | Certain (if missed) | Add `trading212_broker` and `trading212_paper_broker` attribute checks to _perform_sync. Add startup validation that all initialized brokers have sync coverage. |
| R13 | `broker_sync_service._is_broker_match()` / `_get_order_status()` | **T212 reconciliation silently fails.** Broker name normalization doesn't recognize 'TRADING212' or 'Trading212' as matching. Pending orders aren't matched to DB trades. Filled orders aren't detected. Cancelled orders aren't cleaned up. | Sync service encounters T212 broker name variant not in normalization aliases | Likely | Add T212 aliases to `_is_broker_match` normalization matrix: `{'TRADING212', 'Trading212', 'trading212', 'TRADING_212', 'Trading 212'}`. |
| R15 | Risk engine (all exit strategies) | **SL/PT exits fire on stale prices.** T212 polls at 5s intervals (DataHub). Risk engine evaluates current_price without staleness check. A stock drops 3% in 2 seconds, but risk engine sees the 5-second-old price and doesn't trigger SL. Conversely, a price spike in stale data triggers premature PT. | Active T212 stock position with volatile price movement between poll intervals | Likely | (1) Cross-broker price sync: if T212 stock is also streamable via Schwab/Webull hub, steal the streaming price. (2) Add optional price_age_seconds to PositionSnapshot; log warning when risk decisions use prices > 5s old. (3) Document in UI that T212 risk monitoring has 5-10s latency vs <1s for streaming brokers. |
| R16 | Trading212DataHub | **Soft throttle serves stale data silently.** T212 returns HTTP 200 OK with STALE DATA when throttled (not 429). DataHub stores stale positions/prices as current. Risk engine, sync service, and dashboard all see wrong data without any indication. | T212 API under load or account hitting sustained rate limits | Likely | Track response time P99 per endpoint in DataHub. If P99 > 2.5× baseline median, flag as soft-throttled: mark all cached data as `is_stale=True`, back off poll interval, log alert. |
| R17 | `unfilled_order_chaser.py` | **Order chaser immediately rate-limited.** Default 1-second status poll hits T212 GET /orders (1 req/5s limit) at 12× allowed rate. Chaser enters retry loop, consumes entire endpoint budget, blocks sync service and DataHub from polling orders. | Any T212 limit order that doesn't fill immediately | Certain | Add per-broker poll floor config. T212 minimum: 5s status poll interval, 2 max chase attempts (vs 3 for other brokers), 10s chase timeout (vs 4s). |
| R19 | `trading212_broker.place_stock_order()` | **Ticker translation fails on cold cache.** Signal arrives before instrument list loads from GET /metadata/instruments. Ticker `AAPL` can't be translated to `AAPL_US_EQ`. Order fails, but user thinks trade was placed. | Signal arrives within first 10-30 seconds of bot startup while instrument cache is warming | Likely | Block T212 order execution until instrument cache is warm (`_instruments_ready` flag). Return `{success: False, reason: 'instrument_cache_loading'}` if not ready. Log estimated warmup time. |

### MEDIUM Risks (Degraded experience but no financial loss)

| ID | Component | What Breaks | Conditions | Probability | Mitigation |
|---|---|---|---|---|---|
| R9 | `execute_on_single_broker` signature routing | **Wrong stock order call signature used.** If T212 not in `uses_modern_signature` list, the old-style Webull-specific signature is used (wrong kwargs), causing TypeError. Caught by try/except but order silently fails. | Stock signal routed to T212 | Possible | Add 'TRADING212' to `uses_modern_signature` list. Add integration test verifying stock order call signature matches adapter interface. |
| R20 | Position sizing / quantity format | **Float quantity rejected by non-T212 brokers, or int quantity wastes T212 fractional support.** If position_sizing_service returns float 0.7 for T212, the same signal on Webull (which doesn't support fractional stocks) may fail. If it returns int 1, T212's fractional share advantage is lost. | Multi-broker channel with T212 + Webull executing same stock signal | Possible | Add broker-specific quantity normalizer in the adapter layer. T212 adapter accepts floats as-is. Other adapters floor to int. Position sizing stays broker-agnostic upstream. |

---

## Risk Mitigation Summary — Mandatory Pre-Implementation Checklist

### Before ANY Code (Architecture Guards)

| # | Action | Prevents |
|---|---|---|
| 1 | Extract ONE centralized `BROKER_MAP` constant in selfbot_webull.py; all 6 locations reference it | R1-R6: Silent signal drops |
| 2 | Add startup self-test: assert all required broker IDs exist in all dispatch maps | R1-R6: Missing entries |
| 3 | Add SHA256 fingerprint guard in `execute_on_single_broker` BEFORE any broker POST | R18: Duplicate real orders |
| 4 | Add per-broker poll floor in unfilled_order_chaser config | R17: Rate limit breach |

### Phase 1 Implementation (Core Adapter)

| # | Action | Prevents |
|---|---|---|
| 5 | `trading212_broker.place_option_order()` returns clean skip (not error) | R7: Confusing option failures |
| 6 | `connect()` returns explicit True/False; BrokerManager only stores on True | R10: Partial-state broker |
| 7 | Ticker cache loads synchronously during `connect()` with `_instruments_ready` gate | R19: Cold cache failures |
| 8 | Canonical success contract: downstream side effects only on `result.get('success') is True` | R8: False-positive tracking |

### Phase 2 Implementation (DataHub + Sync)

| # | Action | Prevents |
|---|---|---|
| 9 | Add `_fetch_trading212_cached()` to position_monitor asyncio.gather | R14: Blind risk engine |
| 10 | Add TRADING212 branch to broker_sync_service if/elif chain | R12: False trade closures |
| 11 | Add T212 attrs to _perform_sync hardcoded list | R11: Never-syncing |
| 12 | Add T212 aliases to _is_broker_match normalization | R13: Reconciliation failures |
| 13 | Add P99 response-time tracking for soft-throttle detection | R16: Stale data poisoning |

### Phase 3 (Risk Engine — 3-LINK CHAIN, all must be done together)

| # | Action | Prevents |
|---|---|---|
| 14 | Add `trading212_broker=None` parameter to `RiskManager.__init__()`, store as `self.trading212_broker` | R22: AttributeError on exit routing |
| 15 | Add `trading212_broker=self.trading212_broker` to RiskManager() call in selfbot_webull.py L8132 | R23: Broker instance is None |
| 16 | Add `elif 'TRADING212' in broker_upper: broker_instance = self.trading212_broker` to `_direct_execute_exit()` L3078 | R21: Silent SL/PT exit failure |
| 17 | Wire cross-broker price sync for T212 stock symbols (ALREADY WORKS — L1243 auto-subscribes non-Webull/non-Schwab stocks via Schwab streaming) | R15: Stale price exits |
| 18 | Add `trading212_count` to position summary logging at L1613 | R24: Missing T212 count in monitoring log |
| 19 | Add price staleness logging for non-streaming broker positions | R15: Silent stale decisions |

### ⚠️ R21-R22-R23 Chain Dependency Warning

```
R22 (add __init__ parameter)
    └─→ R23 (pass instance at instantiation)
        └─→ R21 (route exit in _direct_execute_exit)

Missing ANY ONE link = stop loss exits SILENTLY FAIL for ALL T212 positions.
The position bleeds money with no protection and no error logged (only "No broker instance" print).
```

---

## Impact Analysis — What Will NOT Break

| Subsystem | Why It's Safe |
|---|---|
| BrokerManager init | Each broker has its own try/except block; T212 failure won't affect others |
| Broker sync loop | Uses `asyncio.gather(return_exceptions=True)` + 3 layers of try/except |
| Live snapshot page | Only fetches brokers in its hardcoded dictionary; T212 added explicitly |
| Order routing (routes.py) | Has explicit `else: return 400 "Unknown broker"` |
| Options page | Falls back to Webull/Alpaca for data |
| Signal parser | Completely broker-independent |
| Existing brokers | Zero changes to Webull/Schwab/IBKR/Alpaca/Tastytrade/Robinhood code |
| Risk engine evaluation logic | Broker-agnostic — tiered_targets.py, global_risk.py, trailing_stop.py all evaluate PositionSnapshot regardless of broker field. No changes needed to evaluation logic itself. |
| Risk engine cross-broker streaming | T212 stock positions automatically get Schwab streaming prices (L1243 logic: non-Webull + non-Schwab → subscribe via Schwab). R15 is self-mitigating for stocks. |
