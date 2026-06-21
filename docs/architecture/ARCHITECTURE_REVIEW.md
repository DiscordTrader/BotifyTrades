# BotifyTrades — Senior Fintech Architecture Review

**Reviewer**: Senior Fintech Architect (automated code-level audit)
**Date**: 2026-06-19
**Scope**: Full platform — trade ingestion, signal parsing, broker integrations, risk engine, position management, error handling, logging, scalability
**Version**: 12.1.9 (~167K lines Python across ~134 files)

> **Verdict**: The system is a feature-rich, production-deployed trading platform with sophisticated risk management (6-level exit priority chain, industry-grade retry, sub-second monitoring). However, it carries **critical security vulnerabilities** (unauthenticated trade execution endpoints, no CSRF, token leaks), **data integrity risks** (triple source-of-truth, no transaction safety on trade state transitions), and **structural debt** (23K-line monoliths, print-based logging) that pose material financial risk.

---

## Table of Contents

1. [Current Architecture](#1-current-architecture)
2. [Weaknesses](#2-weaknesses)
3. [Security Concerns](#3-security-concerns)
4. [Missed-Trade Scenarios](#4-missed-trade-scenarios)
5. [Recommendations](#5-recommendations)
6. [Refactoring Roadmap](#6-refactoring-roadmap)

---

## 1. Current Architecture

### 1.1 Trade Ingestion Pipeline

```
Discord Gateway                    Telegram (Telethon)
       │                                  │
       ▼                                  ▼
  on_message (L10705)              TelegramListener
       │                                  │
       ▼                                  │
  _process_message (L11949)               │
  ├── Message dedup (asyncio.Lock + set)  │
  ├── Channel lookup (sync SQLite, 10s cache)
  ├── 5-tier signal parsing cascade       │
  ├── Position sizing (6-tier priority)   │
  └── order_queue.put()                   │
            │                             │
            ▼                             ▼
     _PriorityOrderQueue         telegram_signal_bridge()
     (asyncio.PriorityQueue,     (stdlib Queue → async bridge,
      unbounded, 2 priority       100ms poll interval)
      levels: RISK=0, NORMAL=1)       │
            │◄────────────────────────┘
            ▼
       worker() (L19815) — SINGLE CONSUMER
       ├── Order-level dedup (permanent set + 60s TTL dict)
       ├── Exit lease check (risk orders)
       ├── Broker routing (channel config → enabled_brokers)
       ├── Multi-broker: asyncio.gather (parallel)
       │   └── execute_on_single_broker()
       │       ├── Daily P&L limit gate
       │       ├── Circuit breaker gate
       │       ├── Broker health gate
       │       ├── Position sizing (buying power query)
       │       └── Broker API call → OrderResult
       ├── Retry: OPTIONS ONLY (3×, exp backoff 2s/4s/8s)
       └── task_done()
```

**Key characteristics**:
- Single-consumer worker drains an unbounded priority queue
- Risk-triggered exits (stop-loss, trailing) take priority over new signal entries
- Multi-broker execution via `asyncio.gather` — parallel across brokers, serial within each
- Position sizing uses signal price at parse time, not real-time quote at execution time
- Stock orders have zero retry logic; only options get 3 retries

### 1.2 Signal Parsing Architecture

Five-tier cascade, first match wins:

| Tier | Source | Implementation | Latency |
|------|--------|---------------|---------|
| 1 | Embed parsers | SpySniper, Sir Goldman (format-specific) | <1ms |
| 2 | SignalFormatRegistry | 157 priority-ordered regex handlers (4763 lines) | <5ms |
| 3 | Channel-specific parsers | 17 parser files in `src/signals/` (300KB total) | <5ms |
| 4 | Standard regex | OPT_REGEX, STK_REGEX, 15+ compiled patterns | <1ms |
| 5 | AI fallback | OpenAI/Claude/Gemini (confidence ≥ 0.8 gate) | 1–5s |

**Strengths**: Extensive format coverage, confidence gating on AI, admin approval required for AI-learned patterns.
**Weaknesses**: An exception in any tier-1-4 parser silently drops the signal (no fallthrough to AI). AI tier adds 1–5s latency, blocking the async context.

### 1.3 Broker Integration Architecture

12 brokers behind `BrokerInterface` ABC → `OrderResult` dataclass:

```
BrokerInterface (ABC)
  ├── connect/disconnect/get_account_info/get_positions
  ├── place_stock_order → OrderResult(success, order_id, message, ...)
  ├── place_option_order → OrderResult
  └── get_quote
        │
BrokerFactory (static registry: name → class)
        │
BrokerManager (strict routing, no default broker)
```

5 data hubs provide streaming prices: Webull (MQTT), Schwab (WebSocket), IBKR (ib_insync events), Tastytrade (DXLink), Trading212 (REST). `UnifiedPriceHub` aggregates across all hubs with freshness classification (fresh <3s / aging <5s / stale <10s / degraded <30s).

### 1.4 Risk Management Engine

Sub-second monitoring loop (0.2s default) with 6-level exit priority:

```
Position Monitor (0.2s loop)
  │
  ├── Fetch positions (hub-first, REST fallback per broker)
  │
  ├── Per-position evaluation:
  │   1. Hard Stop Loss         → Full exit
  │   2. Dynamic SL             → Escalating stop after PT hits
  │   2.5 EMA Exit              → Candlestick trend-based exit
  │   3. Giveback Guard         → Max-profit giveback protection
  │   4. Early Trailing         → Breakeven lock + stepped profit lock
  │   4.5 PT Near-Lock          → Tight trailing near unmet PT
  │   5. Tiered Profit Targets  → PT1-PT4 partial exits
  │   6. Legacy Trailing Stop   → Traditional trailing from peak
  │
  ├── Exit execution → order_queue (RISK priority)
  │
  └── Position cache save (every ~2s to .position_cache.json)
```

**Strengths**: Pure-function evaluators (`evaluate_exit_actions` is idempotent), industry-grade retry (4-phase backoff with market-order escalation), exit lease system prevents duplicate orders, 60+ configurable fields per channel.

### 1.5 Position State Management

**Triple source-of-truth** — the most significant architectural concern:

| Store | Backing | Owner | Contains |
|-------|---------|-------|----------|
| `trades` table | SQLite (WAL) | GUI, sync service, risk engine | Trade records, status, P&L |
| `PositionCache` | In-memory + `.position_cache.json` | Risk engine | Real-time risk state (SL/PT levels, trailing stops, tier hits, EMA state) |
| `PositionLedger` | Separate SQLite table | Signal Routing Engine (admin-only) | Virtual positions for webhook forwarding |

No transactional coupling between them. The `trades` table has 16+ `UPDATE` paths with no centralized state machine.

---

## 2. Weaknesses

### 2.1 Structural (God Files)

| File | Lines | Size | Impact |
|------|-------|------|--------|
| `selfbot_webull.py` | 23,597 | 1.4MB | Entire bot lifecycle in one file: 4 classes, 30+ regex patterns, ~10K-line `_process_message`, startup orchestration |
| `routes.py` | 23,491 | 1.1MB | 250+ endpoints in one `register_routes()` — no blueprints |
| `database.py` | 15,383 | 618KB | 74 tables in one `init_db()`, all CRUD in one file |
| `position_monitor.py` | 10,293 | 573KB | Monitoring + 8-broker fetching + exit execution + bracket management |
| `broker_sync_service.py` | 4,453 | 257KB | 14-broker sync in one class |

These monoliths make reasoning about state transitions, testing isolated paths, and onboarding engineers extremely difficult. A single change to the risk evaluation path requires navigating a 10K-line file with deeply nested conditionals.

### 2.2 Trade Execution Weaknesses

#### W-1: task_done() Leak in Worker (HIGH)
**Location**: `selfbot_webull.py:22597-22602`

The worker's outer `except Exception` handler does **not** call `self.order_queue.task_done()`. Every unhandled exception permanently increments the queue's unfinished-task counter. If `join()` is ever called, it deadlocks. Over long uptime, leaked tasks accumulate silently.

#### W-2: Stock Orders Have Zero Retry Logic (HIGH)
**Location**: `selfbot_webull.py:21439-21480`

Option orders get 3 retries with exponential backoff for transient errors ("system is busy", "timeout"). Stock orders have **no retry** — a transient 500 from the broker results in a permanently lost trade with no recovery.

#### W-3: Unbounded Order Queue (HIGH)
**Location**: `selfbot_webull.py:7319-7345`

`_PriorityOrderQueue` wraps `asyncio.PriorityQueue()` with no `maxsize`. A flood of signals (e.g., a spammy Discord channel) grows the queue without bound. No backpressure, no overflow rejection, no alerting. Memory exhaustion is the only limit.

#### W-4: Non-Deterministic Dedup Eviction (MEDIUM)
**Location**: `selfbot_webull.py:11970-11973, 19947-19950`

Both `_processed_messages` and `_executed_orders_permanent` use `list(set)[:N]` for eviction. Python sets are unordered — this evicts **arbitrary** entries, not oldest. Under sustained load, recently-processed message IDs can be evicted while old ones persist, reopening duplicate execution windows.

#### W-5: Multi-Broker Partial Failure Not Reconciled (MEDIUM)
**Location**: `selfbot_webull.py:20154-20350`

When executing across multiple brokers via `asyncio.gather`, if broker A succeeds and broker B fails, the signal is marked "success" overall. No retry for the failed broker, no rollback, no alert — positions become inconsistent across brokers.

#### W-6: Position Sizing Uses Stale Price (MEDIUM)
**Location**: `selfbot_webull.py:15803-15930, 18067-18260`

Quantity is calculated at parse time using the signal's stated price (`qty = floor(budget / signal_price)`), not a real-time quote. The gap between parse and execution can be seconds to minutes (queue depth dependent). In fast markets, this causes 10–30% over/under-sizing.

#### W-7: No Persistent Queue (MEDIUM)
The in-memory `asyncio.PriorityQueue` provides no durability. A crash between enqueue and execution permanently loses the signal. No WAL, no recovery mechanism, no "at-least-once" delivery guarantee.

### 2.3 Risk Engine Weaknesses

#### W-8: Exit Lease Race Window (HIGH)
**Location**: `exit_lease_manager.py` — `LEASE_EXPIRY_SECONDS=180`

When a lease expires during active order execution, `acquire()` silently overwrites it. The original holder (e.g., order chaser) has **no notification** that its lease was stolen. If the original completes its order after the new holder starts, duplicate exit orders can occur. The `_exit_executed_keys` set provides a secondary guard but could miss timing-dependent races.

#### W-9: Schwab HTTP 500/502/503 Not Retried (HIGH)
**Location**: `schwab_broker.py` — `_make_request()`

Schwab's `_make_request()` handles 429 (rate limit) with progressive backoff and 401 (auth) with token refresh + retry. However, **HTTP 500/502/503 server errors are NOT retried**. A Schwab outage during a stop-loss exit means the protective order is lost with no retry — the position stays unprotected until the risk engine's next 5-minute extended retry cycle.

#### W-10: No Monitoring Loop Crash Escalation (MEDIUM)
**Location**: `position_monitor.py` — `start_monitoring()`

The monitoring loop catches `Exception` and continues with a sleep. There is no crash counter, no circuit breaker, no alert on repeated failures. The loop could crash-and-restart every cycle for hours, silently failing to evaluate risk on every position.

#### W-11: Cascade Failure — API Budget Blocks Stop-Loss (MEDIUM)
**Location**: `schwab_broker.py` — API budget tracking

When Schwab's API budget is exhausted (120 calls/min), non-order calls get synthetic 503s while exit orders bypass the block. However, exit orders still need price quotes for limit-order pricing. If the quote call is budget-blocked, the exit falls back to market — acceptable — but the 429 backoff can impose up to 5 seconds of delay on a stop-loss exit during a Schwab rate storm.

### 2.4 Data Integrity Weaknesses

#### W-12: Triple Source-of-Truth with No Consistency (CRITICAL)
Three independent stores (`trades` table, `PositionCache`, `PositionLedger`) maintain position state with no transactional coupling:
- Cache saves every ~2s to JSON; crash loses up to 2s of risk state
- DB `close_trade()` has no `WHERE status='OPEN'` precondition — can re-close already-closed trades
- `update_trade()` accepts arbitrary `**kwargs` with no validation
- Only `close_lot()` and `process_filled_order_event()` use `BEGIN IMMEDIATE`

#### W-13: Risk-Close vs Sync-Close Race (HIGH)
1. Risk engine detects SL hit → sets `cache.closing=True` → submits STC
2. STC fills → broker position disappears
3. Sync service sees trade OPEN in DB but missing from broker → after 4 cycles (2 min) → closes in DB
4. Risk engine's post-fill handler also closes in DB
5. Both succeed — no `WHERE status='OPEN'` guard. P&L may differ between paths.

**The sync service does NOT check `PositionCache.is_closing()` before closing trades.**

#### W-14: Cache Corruption Loses Risk State Permanently (MEDIUM)
If `.position_cache.json` is corrupted, `load()` returns 0 positions. `restore_full_risk_state_from_db()` restores tier hits, trailing state, and dynamic SL from the `trades` table. However, **flip-flop price locks, EMA candle state, pending orders dict, and bracket order IDs are NOT in the DB** — they are permanently lost. Orphaned bracket orders at the broker persist until manual cleanup.

### 2.5 Logging & Observability Weaknesses

#### W-15: Print-Based Logging for Real-Money Trades (HIGH)
**Evidence**: `broker_sync_service.py:16` contains:
```python
# Use print() for logging - it's redirected to the logging system
# logger = logging.getLogger(__name__)  # Not configured, logs go nowhere
```

The entire codebase (100+ print calls in `schwab_broker.py`, 150+ in `position_monitor.py`) uses `print()` with emoji-prefixed strings for all trade-critical operations. `smart_print()` replaces `builtins.print` to route through tag-based string matching to stdlib handlers.

Two competing logging systems (`logging_config.py` and `core/logging_service.py`) exist, neither is fully used.

**Impact**: No structured logging, no correlation IDs linking signals to executions, no machine-parseable output. Debugging a production trade failure requires regex-grepping through plaintext logs.

#### W-16: No Immutable Order Audit Trail (CRITICAL for regulated trading)
Order placement, fill/reject events, and cancellations produce only `print()` output. The `trades` table records final state but not the sequence of attempts, retries, or partial fills. The only proper audit trail is `conditional_order_audit` — limited to conditional orders only.

**Missing durable records for**: order placement attempts, order rejections with broker error codes, retry sequences, risk exit decisions, settings changes (no previous-value capture).

#### W-17: Error Deduplication Destroys Context (MEDIUM)
**Location**: `database.py:9932-9937`

The `error_logs` table merges identical errors within 1 hour, incrementing `occurrence_count`. If the same order fails 50 times with different symbols, only the first occurrence's context is preserved.

#### W-18: In-Memory Log Buffer (MEDIUM)
**Location**: `log_monitor.py`

`LogMonitor` uses `deque(maxlen=500)` — volatile, lost on restart, provides ~30 minutes of history at high activity. Powers the AI chat assistant's log awareness.

---

## 3. Security Concerns

### S-1: Unauthenticated Trade Execution Endpoints (CRITICAL)

**~40 state-changing POST endpoints lack `@login_required`**, relying solely on a `before_request` hook with a growing whitelist of bypassed path prefixes.

| Endpoint | Action | Risk |
|----------|--------|------|
| `POST /api/stocks/order` | Places live stock orders | Unauthorized trade execution |
| `POST /api/options/order` | Places live options orders | Unauthorized trade execution |
| `POST /api/schwab/positions/<symbol>/close` | Closes Schwab positions | Unauthorized liquidation |
| `POST /api/alpaca/positions/<symbol>/close` | Closes Alpaca positions | Unauthorized liquidation |
| `POST /api/webull/positions/close` | Closes Webull positions | Unauthorized liquidation |
| `POST /api/trades/<id>/close` | Closes positions by trade ID | Unauthorized liquidation |
| `POST /api/trades/<id>/force-close-db` | Force-closes trades | Data manipulation |
| `POST /api/brokers/credentials/*` | Saves broker credentials | Credential theft |
| `POST /api/settings` | Saves all settings | Config tampering |
| `POST /api/settings/api_keys` | Saves AI/API keys | Key theft |
| `POST /api/brokers/connect/<broker_id>` | Connects any broker | Unauthorized access |

Defense-in-depth requires BOTH `@login_required` on the endpoint AND the `before_request` hook. A single whitelist misconfiguration exposes all these endpoints.

### S-2: No CSRF Protection (CRITICAL)

Zero CSRF protection on any endpoint — no Flask-WTF, no CSRFProtect, no X-CSRF-Token header validation. Combined with `SESSION_COOKIE_SAMESITE='Lax'`, a malicious page can trigger trade execution or credential overwrites via cross-origin POST. The only CSRF protection found is in the Schwab OAuth flow (state parameter).

### S-3: Network Exposure — HTTP on 0.0.0.0 (CRITICAL)

```python
# gui_app/app.py:146
def start_gui_server(host='0.0.0.0', port=None):
# gui_app/app.py:78
app.config['SESSION_COOKIE_SECURE'] = False
```

Flask binds to all interfaces over plaintext HTTP. Session cookies transmitted without encryption. Any device on the same network can intercept sessions, steal credentials, and execute trades.

### S-4: Broker Tokens Exposed via API (CRITICAL)

**Location**: `routes.py:16176-16186`

`GET /api/brokers/credentials/webull` returns full plaintext `access_token` and `refresh_token`. Only `password` and `trade_pin` are masked. Anyone with network access to port 5000 can steal these tokens.

### S-5: Hardcoded License Secret Key (HIGH)

**Location**: `license/config/constants.py:8-10`

```python
return b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0..."
```

96-character hex key hardcoded as fallback. Comment says "should be obfuscated with PyArmor" — obfuscation is not security. Anyone with the binary can extract this key and forge license tokens.

### S-6: Weak Encryption Key Derivation (HIGH)

**Location**: `config_service.py:36-41`

When deriving from `LICENSE_KEY`, uses a single SHA-256 pass with static salt prefix `botify_creds_`. No iterations (PBKDF2/scrypt/argon2), no random salt. If the license key is known, all encrypted credentials can be decrypted.

### S-7: Schwab Tokens Stored as Plaintext JSON (HIGH)

**Location**: `schwab_auth.py:78-87`

`schwab_token.json` contains access/refresh tokens as plaintext JSON in the working directory. No encryption, no file permission restrictions.

### S-8: Discord Token Leaked to Logs (HIGH)

**Location**: `selfbot_webull.py:1252-1255`

```python
print(f"[CONFIG]   Token starts with: {USER_TOKEN[:20]}...")
print(f"[CONFIG]   Token ends with: ...{USER_TOKEN[-15:]}")
```

First 20 and last 15 characters of the ~70-char Discord token logged to stdout on every startup. Leaks ~50% of the token to log files and crash reports.

### S-9: Flask SECRET_KEY in Plaintext SQLite (MEDIUM)

**Location**: `app.py:56-64`

The session signing key is stored as plaintext in `bot_data.db`. Anyone who can read the database can forge session cookies and bypass authentication.

### S-10: Robinhood Hardcoded Client ID (MEDIUM)

**Location**: `routes.py:17563`

```python
"client_id": "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS",
```

Impersonates the official Robinhood client — a ToS violation that could result in account termination.

### S-11: Rate Limiting Bypass (MEDIUM)

**Location**: `routes.py:128, 1026`

Login rate limiting uses in-memory dict (reset on restart) and trusts `X-Forwarded-For` header (trivially spoofable).

---

## 4. Missed-Trade Scenarios

Scenarios where a valid trading signal fails to execute or executes incorrectly:

### MT-1: Signal Dropped by Parser Exception (MEDIUM probability)

**Trigger**: Any parser in tiers 1–4 throws an unhandled exception.
**Mechanism**: `_process_message()` has broad try/except blocks, but individual format parsers earlier in the cascade may not. An exception causes the function to return without queuing the signal.
**Evidence**: `selfbot_webull.py:11949` — no per-parser exception isolation.
**Impact**: Signal permanently lost. No retry, no alert, no DB record.

### MT-2: Stock Order Transient Failure (HIGH probability in volatile markets)

**Trigger**: Broker returns "system is busy", "timeout", or HTTP 500 on a stock order.
**Mechanism**: Option orders retry 3× (`selfbot_webull.py:21249`). Stock orders have zero retry (`selfbot_webull.py:21439`).
**Impact**: Trade permanently lost. Only a print() log records the failure.

### MT-3: Bot Crash Between Enqueue and Execution (LOW probability, HIGH impact)

**Trigger**: Process crash (OOM, unhandled exception, power loss) while signals are queued.
**Mechanism**: `asyncio.PriorityQueue` is in-memory only. No WAL, no disk persistence.
**Impact**: All queued signals lost. No recovery on restart.

### MT-4: Multi-Broker Partial Execution (MEDIUM probability)

**Trigger**: Signal routed to 3 brokers; broker B gets a 429 rate limit.
**Mechanism**: `asyncio.gather` returns partial success. No retry for failed brokers (`selfbot_webull.py:20286`).
**Impact**: Position opened on 2 of 3 brokers. No reconciliation, no alert. Risk engine may not evaluate the missing position correctly.

### MT-5: Dedup Cache Eviction Causes Re-Execution (LOW probability)

**Trigger**: >1000 signals processed, non-deterministic set eviction removes a recent message ID.
**Mechanism**: `list(set)[:500]` eviction is not FIFO (`selfbot_webull.py:11970`).
**Impact**: Same signal executed twice. Double position opened.

### MT-6: Stale Channel Config Causes Misrouting (LOW probability)

**Trigger**: Channel broker assignment changed in GUI while 10s cache is active.
**Mechanism**: `_get_channel_info()` caches for 10 seconds (`selfbot_webull.py:7493`).
**Impact**: Signal routed to wrong broker for up to 10 seconds after config change.

### MT-7: AI Fallback Timeout Blocks Worker (LOW probability, MEDIUM impact)

**Trigger**: AI provider (OpenAI/Claude/Gemini) responds slowly (>5s).
**Mechanism**: AI parsing in `_process_message()` awaits the API call, blocking the async context.
**Impact**: All other signal processing stalls until the AI call completes or times out.

### MT-8: Schwab 500 During Stop-Loss Exit (MEDIUM probability during outages)

**Trigger**: Schwab API returns HTTP 500 during a risk-triggered STC.
**Mechanism**: `_make_request()` does not retry 500/502/503 errors.
**Impact**: Stop-loss exit fails. Position unprotected until the risk engine's extended retry (5-minute intervals). In a fast crash, the loss can compound significantly.

### MT-9: Exit Order Killed by Cancel-Replace Gap (LOW probability)

**Trigger**: Order chaser cancels a pending exit to replace at better price; replacement fails.
**Mechanism**: Between cancel success and replacement failure, position has NO protective order.
**Impact**: If bot crashes in this window, position is unprotected until next monitoring cycle. Mitigated by market-order fallback, but the window exists.

### MT-10: Telegram Signal 100ms–1100ms Latency (MEDIUM probability for scalping)

**Trigger**: Telegram signal arrives between poll cycles.
**Mechanism**: Bridge polls with 1s timeout + 0.1s sleep (`selfbot_webull.py:19633`).
**Impact**: For time-sensitive scalping signals (0DTE options), 100ms–1.1s added latency can mean significant slippage or missed entry.

---

## 5. Recommendations

### Priority 1 — Financial Safety (Do First)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| R-1 | No `@login_required` on trade endpoints | Add decorator to every state-changing endpoint; audit all 250+ routes | 2 days |
| R-2 | No CSRF protection | Install Flask-WTF, add CSRFProtect, require token on all POST/PUT/DELETE | 1 day |
| R-3 | HTTP on 0.0.0.0 | Bind to `127.0.0.1` by default; add TLS option; set `SESSION_COOKIE_SECURE=True` | 1 day |
| R-4 | Token exposure via GET API | Mask all tokens/secrets in credential GET endpoints; never return raw token values | 0.5 day |
| R-5 | Stock order retry gap | Apply same 3-retry transient-error logic to stock orders | 0.5 day |
| R-6 | Schwab HTTP 500 not retried | Add retry-with-backoff for 500/502/503 in `_make_request()` | 0.5 day |
| R-7 | `close_trade()` no precondition | Add `WHERE status='OPEN'` to all trade-closing SQL; return affected-row count | 0.5 day |
| R-8 | `task_done()` leak in worker | Add `task_done()` in the outer except handler; guard against unbound `signal` | 0.5 hour |

### Priority 2 — Data Integrity (Do Next)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| R-9 | Triple SSOT | Designate `trades` table as the sole SSOT; make PositionCache a read-through cache that writes back to DB; deprecate PositionLedger or merge | 2 weeks |
| R-10 | No trade state machine | Introduce `TradeStatus` enum (PENDING→OPEN→CLOSING→CLOSED→CANCELLED) with enforced transitions; reject invalid transitions at the DB layer | 1 week |
| R-11 | Sync-vs-risk race | Have sync service check `PositionCache.is_closing()` before closing trades; use `BEGIN IMMEDIATE` for all status transitions | 2 days |
| R-12 | Dedup eviction bug | Replace `set` with `OrderedDict` or `collections.deque` for FIFO eviction | 1 day |
| R-13 | Persistent order queue | Replace in-memory `asyncio.PriorityQueue` with SQLite-backed persistent queue; dequeue marks "in-progress", completion marks "done" | 3 days |

### Priority 3 — Observability (Do Soon)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| R-14 | Print-based logging | Adopt structured logging (stdlib `logging` + JSON formatter); add correlation IDs from signal→parse→execute→fill | 1 week |
| R-15 | No order audit trail | Create `order_attempts` table: every placement attempt, fill, rejection, retry with timestamps, broker error codes, and trace_id | 3 days |
| R-16 | No settings changelog | Add `settings_history` table with old_value, new_value, changed_by, timestamp | 1 day |
| R-17 | Error dedup destroys context | Store each occurrence as a separate row; add aggregation at query time, not write time | 1 day |
| R-18 | No metrics emission | Add lightweight Prometheus client counters: orders_placed, orders_filled, orders_failed, risk_exits, parse_latency_ms | 2 days |

### Priority 4 — Structural (Do Gradually)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| R-19 | `selfbot_webull.py` 23.6K lines | Extract: `WebullBroker` → `src/brokers/`, signal parsing → `src/signals/pipeline.py`, worker → `src/execution/worker.py`, startup → `src/boot.py` | 2 weeks |
| R-20 | `routes.py` 23.5K lines | Split into Flask blueprints: `auth_bp`, `trades_bp`, `brokers_bp`, `settings_bp`, `admin_bp`, etc. | 1 week |
| R-21 | `database.py` 15.4K lines | Split by domain: `db/trades.py`, `db/channels.py`, `db/risk.py`, `db/signals.py`, `db/schema.py`; add proper migration framework (Alembic) | 2 weeks |
| R-22 | `position_monitor.py` 10.3K lines | Extract: per-broker fetch methods → `risk/broker_fetch.py`, bracket management → `risk/bracket_manager.py`, exit execution → `risk/exit_executor.py` | 1 week |
| R-23 | Dual conditional order systems | Remove legacy `conditional_order_service.py`; migrate all usage to `conditional_orders/` package | 3 days |
| R-24 | Duplicated WebullBroker | Remove the 5K-line `WebullBroker` class from `selfbot_webull.py`; use only `src/brokers/webull_broker.py` | 2 days |

### Priority 5 — Security Hardening

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| R-25 | Hardcoded license key | Move to environment variable only; remove hardcoded fallback | 0.5 day |
| R-26 | Weak KDF | Replace single SHA-256 with PBKDF2 (600K iterations) or argon2id; add random salt per key | 1 day |
| R-27 | `.encryption_key` no permissions | Add `os.chmod(0o600)` after writing; document secure storage | 0.5 day |
| R-28 | Discord token leaked to logs | Remove token printing entirely; log only `Token: ***configured***` | 0.5 hour |
| R-29 | Schwab tokens plaintext on disk | Encrypt `schwab_token.json` with the same Fernet key used for other credentials | 1 day |
| R-30 | Password hashing iterations | Upgrade PBKDF2 from 100K to 600K iterations (OWASP 2023) or migrate to bcrypt/argon2id | 0.5 day |
| R-31 | Exception details leaked to clients | Catch exceptions in routes; return generic error messages; log details server-side only | 1 day |
| R-32 | Rate limiting bypass | Persist login attempts to DB; validate `X-Forwarded-For` against trusted proxies only | 1 day |

---

## 6. Refactoring Roadmap

### Phase 1: Critical Safety (Week 1–2)

**Goal**: Eliminate unauthenticated trade execution and data integrity risks that can cause financial loss.

```
Week 1:
├── R-1:  Add @login_required to all state-changing endpoints
├── R-2:  Install CSRF protection (Flask-WTF)
├── R-3:  Bind Flask to 127.0.0.1; add SESSION_COOKIE_SECURE
├── R-4:  Mask tokens in credential GET endpoints
├── R-5:  Add retry logic to stock orders
├── R-6:  Add HTTP 500 retry to Schwab broker
├── R-7:  Add WHERE status='OPEN' to close_trade()
├── R-8:  Fix task_done() leak in worker
└── R-28: Remove Discord token printing

Week 2:
├── R-11: Sync service checks is_closing() before close
├── R-12: Replace set eviction with OrderedDict FIFO
├── R-25: Remove hardcoded license secret key
├── R-27: Set file permissions on .encryption_key
└── R-29: Encrypt schwab_token.json
```

**Acceptance criteria**: No endpoint executes trades without authentication. No trade-closing SQL succeeds on already-closed trades. All transient broker errors are retried.

### Phase 2: Observability (Week 3–4)

**Goal**: Establish structured logging and audit trail sufficient for post-incident investigation.

```
Week 3:
├── R-14: Structured logging with JSON formatter + correlation IDs
├── R-15: order_attempts audit table
├── R-17: Remove error deduplication at write time
└── R-28: Remove all token/credential printing

Week 4:
├── R-16: settings_history changelog table
├── R-18: Prometheus counters for key trading metrics
└── Backfill: Add structured log calls to all broker order paths
```

**Acceptance criteria**: Every order placement attempt is durably recorded with trace_id, broker response, and latency. Settings changes preserve previous values. Metrics endpoint exposes orders_placed/filled/failed counters.

### Phase 3: Data Integrity (Week 5–8)

**Goal**: Establish single source-of-truth for position state with enforced state machine.

```
Week 5-6:
├── R-10: TradeStatus enum with enforced transitions
├── R-9:  PositionCache as write-through cache to trades table
├── R-13: Persistent order queue (SQLite-backed)
└── R-23: Remove legacy conditional_order_service.py

Week 7-8:
├── R-9 (continued): Deprecate PositionLedger or merge into trades table
├── Transaction safety: BEGIN IMMEDIATE on all trade status transitions
└── Reconciliation: Sync service respects risk engine state
```

**Acceptance criteria**: Trade status transitions are enforced (OPEN→CLOSING→CLOSED only). PositionCache and trades table are always consistent. No signals lost on crash (persistent queue).

### Phase 4: Structural Decomposition (Week 9–16)

**Goal**: Break god-files into maintainable, testable modules.

```
Week 9-10:
├── R-24: Remove duplicate WebullBroker from selfbot_webull.py
├── R-19: Extract worker, signal pipeline, startup from selfbot_webull.py
└── R-22: Extract broker-fetch and exit-execution from position_monitor.py

Week 11-12:
├── R-20: Split routes.py into Flask blueprints
└── R-21: Split database.py by domain

Week 13-14:
├── R-21 (continued): Add Alembic migration framework
├── R-26: Upgrade KDF to argon2id
└── R-30: Upgrade password hashing

Week 15-16:
├── Integration test coverage for critical paths
├── R-31: Sanitize exception details in API responses
├── R-32: Persistent rate limiting
└── Final security audit
```

**Acceptance criteria**: No file exceeds 3,000 lines. Each module has clear boundaries and can be tested in isolation. Database schema changes are managed by versioned migrations.

### Phase 5: Scalability Foundations (Future)

Not urgent for a single-user desktop app, but necessary if the platform scales:

- **Event-driven architecture**: Replace polling loops with proper event bus (asyncio signals or message broker)
- **Connection pooling**: Replace thread-local SQLite connections with connection pool + read replicas
- **Async-native DB**: Migrate to aiosqlite or PostgreSQL with asyncpg for non-blocking DB access
- **Queue infrastructure**: Replace SQLite-backed queue with Redis or RabbitMQ for multi-instance support
- **API gateway**: Reverse proxy (nginx/caddy) with TLS termination, rate limiting, and request validation
- **Container deployment**: Docker image with secrets management (Vault, AWS Secrets Manager)

---

## Appendix: Numeric Parameters Reference

| Parameter | Value | Location | Risk Relevance |
|-----------|-------|----------|----------------|
| Risk monitoring interval | 0.2s | position_monitor.py | Controls SL evaluation frequency |
| Exit fast retries | 5 | risk_types.py:506 | Attempts before extended mode |
| Market order escalation | After 2 limit failures | risk_types.py:507 | Forced market on persistent failure |
| Extended retry interval | 300s (5 min) | risk_types.py:508 | Gap between extended retries |
| Closing timeout | 180s | position_cache.py:38 | Auto-resets closing flag |
| Exit lease expiry | 180s | exit_lease_manager.py:26 | Duplicate exit risk window |
| Order chase timeout | 1s | unfilled_order_chaser.py:149 | Time before chasing stale order |
| Max chase attempts | 3 | unfilled_order_chaser.py:150 | Chases before fallback |
| Schwab API budget | 120/min | schwab_broker.py:74 | Hard rate limit |
| Schwab throttle point | 96/min | schwab_broker.py:75 | Non-critical calls throttled |
| Schwab exit 429 wait cap | 5s | schwab_broker.py:928 | Max delay on exit during 429 |
| Sync service interval | 30s | broker_sync_service.py | Position reconciliation frequency |
| Channel info cache | 10s | selfbot_webull.py:7493 | Stale routing window |
| Dedup cache max (messages) | 1000 | selfbot_webull.py:11970 | Before non-FIFO eviction |
| Dedup cache max (orders) | 2000 | selfbot_webull.py:19947 | Before non-FIFO eviction |
| Position cache save | ~2s | position_monitor.py:2948 | Max risk state loss on crash |
| Telegram bridge poll | 1s + 0.1s sleep | selfbot_webull.py:19633 | Signal latency floor |
| AI confidence gate | 0.8 | ai_signal_parser.py | Below this, signal rejected |
| Login rate limit | 5 per 5 min | routes.py:128 | In-memory only |
| Session lifetime | 24h | app.py:77 | Cookie expiry |
| Log buffer (LogMonitor) | 500 entries | log_monitor.py | ~30 min at high activity |
| Error dedup window | 1 hour | database.py:9932 | Context destruction window |
