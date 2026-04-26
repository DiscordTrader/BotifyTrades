# BotifyTrades QA Playbook — Complete Validation Reference

## Overview

This document defines the complete quality assurance checklist for BotifyTrades. Every page, API endpoint, database table, and setting must be validated before releasing a new version. The checklist is organized by the application's tab structure.

**Current Version Baseline:** 9.2.5
**Validation Reference:** `docs/RISK_SETTINGS_VALIDATION_REFERENCE.md` (42-field risk settings wiring)

---

## Pre-Release Gate

Before tagging any new version (v9.2.6+), ALL sections marked **[GATE]** must pass. Non-gate items are recommended but non-blocking.

### Quick Validation Commands

```bash
# 1. Syntax check all Python files
find src/ gui_app/ -name "*.py" | xargs -I{} python -m py_compile {}

# 2. Run unit tests
pytest qa/tests/unit -v -m unit

# 3. Run integration tests
pytest qa/tests/integration -v -m integration

# 4. Run full test suite with coverage
pytest qa/tests -v --cov=src --cov=gui_app --cov-report=html

# 5. Database schema validation
python -c "from gui_app.database import init_db; init_db(); print('DB OK')"

# 6. Risk settings wiring check (see RISK_SETTINGS_VALIDATION_REFERENCE.md)
python3 docs/scripts/validate_risk_fields.py  # or inline script from reference doc
```

---

## TRADING TAB

### 1. Dashboard (`/`) [GATE]

**Page:** `index.html` | **Route:** `GET /`

| # | Test | Status |
|---|------|--------|
| 1.1 | Page loads without errors | [ ] |
| 1.2 | Broker states display for all regions (USA, Canada, UK_EU) | [ ] |
| 1.3 | Balance and buying power shown per connected broker | [ ] |
| 1.4 | Broker connection status indicators (green/red/yellow) | [ ] |
| 1.5 | Disconnect/reconnect broker from dashboard | [ ] |
| 1.6 | Real-time price refresh works | [ ] |
| 1.7 | Start-of-day balance capture (`POST /api/sod-balance/capture`) | [ ] |
| 1.8 | Daily P&L display against SOD balance | [ ] |
| 1.9 | Kill switch toggle works | [ ] |
| 1.10 | Paper trade indicator visible when enabled | [ ] |

**API Endpoints:**
- [ ] `GET /api/v2/broker-states` — returns all broker states
- [ ] `GET /api/v2/broker-states/<broker>` — returns specific broker
- [ ] `POST /api/v2/broker-states/<broker>/refresh` — refreshes broker
- [ ] `POST /api/v2/broker-states/refresh-all` — refreshes all
- [ ] `GET /api/v2/broker-states/by-region/<region>` — filters by region
- [ ] `GET /api/sod-balance` — returns start-of-day balance
- [ ] `GET /api/brokers/status` — all broker connection status
- [ ] `GET /api/brokers/health` — broker health check
- [ ] `GET /api/stats` — system statistics

**Database Tables:** `broker_states`, `daily_pnl_state`, `broker_credentials`

---

### 2. Channels (`/channels`) [GATE]

**Page:** `channels.html` | **Route:** `GET /channels`

| # | Test | Status |
|---|------|--------|
| 2.1 | Page loads, all channels listed | [ ] |
| 2.2 | Add new channel (Discord ID, name, category) | [ ] |
| 2.3 | Edit channel settings | [ ] |
| 2.4 | Delete channel | [ ] |
| 2.5 | Reset channel | [ ] |
| 2.6 | Toggle execute/track enabled | [ ] |
| 2.7 | Paper trade toggle per channel | [ ] |
| 2.8 | Broker override selection | [ ] |
| 2.9 | Market filter (USA/Canada/India) | [ ] |
| 2.10 | Category filter | [ ] |
| 2.11 | Channel allowed users CRUD | [ ] |
| 2.12 | Recent messages scan | [ ] |
| 2.13 | Canada-specific channels (`/channels/canada`) | [ ] |

**Risk Settings per Channel (see RISK_SETTINGS_VALIDATION_REFERENCE.md for full 42-field wiring):**

| # | Test | Status |
|---|------|--------|
| 2.14 | Risk management enable/disable | [ ] |
| 2.15 | Stop loss % saves and loads | [ ] |
| 2.16 | 4-tier profit targets (PT1-PT4 %) | [ ] |
| 2.17 | Profit target quantities (qty 1-4) | [ ] |
| 2.18 | Profit target trim percentages (trim 1-4) | [ ] |
| 2.19 | Trailing stop % and activation % | [ ] |
| 2.20 | Early trailing (enable, activation %, step %) | [ ] |
| 2.21 | Leave runner (enable, %) | [ ] |
| 2.22 | Exit strategy mode (signal/risk/hybrid) | [ ] |
| 2.23 | Dynamic SL (enable, profile: conservative/standard/aggressive) | [ ] |
| 2.24 | Giveback guard (enable, allowed %) | [ ] |
| 2.25 | Escalation only mode | [ ] |
| 2.26 | Trim order mode (market/limit) + offset | [ ] |
| 2.27 | SL order mode (market/limit) + offset | [ ] |
| 2.28 | Broker bracket mode (both/sl_only/pt_only/none) | [ ] |
| 2.29 | EMA risk settings (all 9 fields) | [ ] |
| 2.30 | Use global risk settings toggle | [ ] |
| 2.31 | Signal update automation | [ ] |
| 2.32 | Sizing mode (mirror/fixed_dollar/fixed_contracts) | [ ] |
| 2.33 | Conditional order settings (enable, trigger offset, expiry, timeout) | [ ] |
| 2.34 | Slippage protection (enable, max %) | [ ] |
| 2.35 | Limit cap (enable, %) | [ ] |
| 2.36 | NDX→QQQ conversion (enable, delta) | [ ] |
| 2.37 | Ticker filter (mode, list) | [ ] |
| 2.38 | Entry order mode | [ ] |
| 2.39 | Order chase / entry chase enable | [ ] |
| 2.40 | Trade summary enabled per channel | [ ] |
| 2.41 | Channel daily loss limit, max positions | [ ] |
| 2.42 | Cache invalidation fires on risk field save | [ ] |

**API Endpoints:**
- [ ] `GET /api/channels` — list (with market/category filters)
- [ ] `POST /api/channels` — create
- [ ] `PUT /api/channels/<id>` — update
- [ ] `DELETE /api/channels/<id>` — delete
- [ ] `POST /api/channels/<id>/reset` — reset
- [ ] `GET /api/channels/<id>/allowed_users` — list users
- [ ] `POST /api/channels/<id>/allowed_users` — add user
- [ ] `DELETE /api/channels/<id>/allowed_users/<uid>` — remove user
- [ ] `GET /api/channels/<id>/recent-messages` — scan messages
- [ ] `POST /api/channels/<id>/scan` — scan for signals

**Database Tables:** `channels` (60+ columns), `channel_allowed_users`, `channel_messages`

---

### 3. Execution (`/execution`) [GATE]

**Page:** `execution.html` | **Route:** `GET /execution`

| # | Test | Status |
|---|------|--------|
| 3.1 | Page loads, execution-enabled channels shown | [ ] |
| 3.2 | Execution P&L summary loads | [ ] |
| 3.3 | Execution lots displayed with fill prices | [ ] |
| 3.4 | Signal lots displayed with FIFO tracking | [ ] |
| 3.5 | Lot closures show P&L per closure | [ ] |
| 3.6 | Slippage tracking (signal vs fill price) | [ ] |
| 3.7 | Latency tracking (parse, broker, total) | [ ] |
| 3.8 | Filter by channel, broker, date range | [ ] |
| 3.9 | Signal summary view | [ ] |
| 3.10 | Signal lot → execution lots drill-down | [ ] |

**API Endpoints:**
- [ ] `GET /api/execution-pnl` — execution P&L data
- [ ] `GET /api/execution-pnl/filters` — filter options
- [ ] `GET /api/execution-lots` — broker fill lots
- [ ] `GET /api/signal-summary` — signal summary
- [ ] `GET /api/signal-summary/<lot_id>/executions` — executions per lot

**Database Tables:** `signal_lots`, `lot_closures`, `execution_lots`, `execution_closures`, `pending_order_metadata`, `filled_orders`

---

### 4. P&L Tracker (`/pnl`) [GATE]

**Page:** `pnl_tracker.html` | **Route:** `GET /pnl`

| # | Test | Status |
|---|------|--------|
| 4.1 | Page loads with P&L data | [ ] |
| 4.2 | Detailed P&L breakdown | [ ] |
| 4.3 | P&L by user/author | [ ] |
| 4.4 | P&L purge by date | [ ] |
| 4.5 | P&L purge by author | [ ] |
| 4.6 | P&L reset functionality | [ ] |
| 4.7 | FIFO lot matching accuracy | [ ] |
| 4.8 | Open position P&L calculation | [ ] |
| 4.9 | Closed position P&L calculation | [ ] |
| 4.10 | Signal vs execution P&L comparison | [ ] |

**API Endpoints:**
- [ ] `GET /api/pnl/detailed` — detailed P&L
- [ ] `GET /api/pnl/users` — P&L by users
- [ ] `POST /api/reset/pnl` — reset P&L
- [ ] `POST /api/pnl/purge/by-date` — purge by date
- [ ] `POST /api/pnl/purge/by-author` — purge by author
- [ ] `GET /api/pnl/authors` — list authors
- [ ] `GET /api/pnl/dates` — list dates

**Database Tables:** `signal_lots`, `lot_closures`, `execution_lots`, `execution_closures`

---

### 5. Trades (`/trades`) [GATE]

**Page:** `trades.html` | **Route:** `GET /trades`

| # | Test | Status |
|---|------|--------|
| 5.1 | Page loads with live trades | [ ] |
| 5.2 | Open positions displayed with real-time prices | [ ] |
| 5.3 | Close specific trade | [ ] |
| 5.4 | Close all trades | [ ] |
| 5.5 | Force close trade (DB only) | [ ] |
| 5.6 | Per-trade risk settings view/edit | [ ] |
| 5.7 | Live snapshot updates | [ ] |
| 5.8 | Real-time price refresh | [ ] |
| 5.9 | Merged trades view | [ ] |
| 5.10 | Clear stale trades | [ ] |
| 5.11 | Rejected trades view with reasons | [ ] |
| 5.12 | Trade status badges (OPEN/CLOSED/PENDING/FAILED) | [ ] |
| 5.13 | Trailing stop indicators | [ ] |
| 5.14 | Profit target hit indicators (PT1-PT4) | [ ] |

**API Endpoints:**
- [ ] `GET /api/trades` — all trades
- [ ] `GET /api/trades/summary` — trades summary
- [ ] `GET /api/trades/live-snapshot` — live snapshot
- [ ] `GET /api/trades/realtime-prices` — real-time prices
- [ ] `POST /api/trades/close-all` — close all
- [ ] `POST /api/trades/<id>/close` — close specific
- [ ] `POST /api/trades/<id>/force-close-db` — force close DB
- [ ] `GET /api/trades/<id>/risk-settings` — get risk settings
- [ ] `PUT /api/trades/<id>/risk-settings` — update risk settings
- [ ] `GET /api/trades/merged` — merged trades
- [ ] `GET /api/trades/clear-stale` — clear stale
- [ ] `GET /api/trades/stale-count` — stale count
- [ ] `GET /api/trades/rejected` — rejected trades
- [ ] `POST /api/refresh_prices` — refresh prices

**Database Tables:** `trades` (50+ columns), `position_risk_settings`

---

## ANALYSIS TAB

### 6. Options (`/options`)

**Page:** `options.html` | **Route:** `GET /options`

| # | Test | Status |
|---|------|--------|
| 6.1 | Page loads | [ ] |
| 6.2 | Option expirations load for symbol | [ ] |
| 6.3 | Option chain displays calls/puts | [ ] |
| 6.4 | Strike quote loads bid/ask/last | [ ] |
| 6.5 | Quick chain retrieval | [ ] |
| 6.6 | Streaming quotes (subscribe/stream) | [ ] |
| 6.7 | Place options order | [ ] |
| 6.8 | Chain stream with key updates | [ ] |

**API Endpoints:**
- [ ] `GET /api/options/expirations` — expirations
- [ ] `GET /api/options/chain` — chain data
- [ ] `POST /api/options/strike-quote` — strike quote
- [ ] `GET /api/options/quick-chain` — quick chain
- [ ] `POST /api/options/subscribe-stream` — subscribe
- [ ] `GET /api/options/stream-quotes` — streaming quotes
- [ ] `GET /api/options/chain-stream` — chain stream
- [ ] `POST /api/options/chain-stream/update-keys` — update keys
- [ ] `POST /api/options/order` — place order

---

### 7. My Performance (`/performance`)

**Page:** `performance.html` | **Route:** `GET /performance`

| # | Test | Status |
|---|------|--------|
| 7.1 | Page loads with analytics | [ ] |
| 7.2 | Overview section (total P&L, win rate, trades) | [ ] |
| 7.3 | Journal section (trade log) | [ ] |
| 7.4 | Breakdown section (by channel, symbol, time) | [ ] |
| 7.5 | Heatmap section (calendar view) | [ ] |
| 7.6 | Edge section (statistical edge analysis) | [ ] |
| 7.7 | Brokers section (per-broker performance) | [ ] |
| 7.8 | Date range filtering | [ ] |
| 7.9 | User P&L data | [ ] |

**API Endpoints:**
- [ ] `GET /api/performance-v2` — enhanced analytics (sections param)
- [ ] `GET /api/performance` — legacy performance
- [ ] `GET /api/performance/summary` — summary
- [ ] `POST /api/performance/pnl` — P&L data
- [ ] `POST /api/performance/pnl/users` — user P&L
- [ ] `GET /api/broker-performance` — broker performance

**Database Tables:** `performance_snapshots`, `lot_closures`, `execution_closures`

---

### 8. Leaderboard (`/leaderboard`)

**Page:** `leaderboard.html` | **Route:** `GET /leaderboard`

| # | Test | Status |
|---|------|--------|
| 8.1 | Page loads with rankings | [ ] |
| 8.2 | Channel leaderboard displays | [ ] |
| 8.3 | User leaderboard displays | [ ] |
| 8.4 | Enhanced leaderboard metrics | [ ] |
| 8.5 | Execution leaderboard (fill quality) | [ ] |
| 8.6 | Sorting by different metrics | [ ] |

**API Endpoints:**
- [ ] `GET /api/leaderboard` — leaderboard data
- [ ] `GET /api/leaderboard/users` — user rankings
- [ ] `GET /api/leaderboard/enhanced` — enhanced metrics
- [ ] `GET /api/leaderboard/execution` — execution quality

---

### 9. Simulate (`/simulation`)

**Page:** `simulation.html` | **Route:** `GET /simulation`

| # | Test | Status |
|---|------|--------|
| 9.1 | Page loads | [ ] |
| 9.2 | Portfolio simulation runs | [ ] |
| 9.3 | Presets load/apply | [ ] |
| 9.4 | Entity stats display | [ ] |
| 9.5 | Exact simulation | [ ] |
| 9.6 | Historical simulation | [ ] |
| 9.7 | Custom simulation | [ ] |
| 9.8 | Autocomplete for entities | [ ] |
| 9.9 | Optimizer runs | [ ] |
| 9.10 | Copy 1:1 simulation | [ ] |
| 9.11 | Recovery simulation | [ ] |
| 9.12 | Monte Carlo simulation | [ ] |
| 9.13 | Comprehensive simulation | [ ] |
| 9.14 | Correlation analysis | [ ] |
| 9.15 | Risk presets | [ ] |

**API Endpoints:**
- [ ] `POST /api/simulate` — portfolio simulation
- [ ] `GET /api/simulate/presets` — presets
- [ ] `GET /api/simulate/stats/<type>/<id>` — entity stats
- [ ] `POST /api/simulate/exact` — exact
- [ ] `POST /api/simulate/historical` — historical
- [ ] `POST /api/simulate/custom` — custom
- [ ] `GET /api/simulate/autocomplete/<type>` — autocomplete
- [ ] `POST /api/simulate/optimizer` — optimizer
- [ ] `POST /api/simulate/copy1to1` — copy 1:1
- [ ] `POST /api/simulate/recovery` — recovery
- [ ] `POST /api/simulate/monte-carlo` — Monte Carlo
- [ ] `POST /api/simulate/comprehensive` — comprehensive
- [ ] `POST /api/simulate/correlation` — correlation
- [ ] `GET /api/simulate/risk-presets` — risk presets

---

### 10. Verify Signals (`/verification`) [GATE]

**Page:** `verification.html` | **Route:** `GET /verification`

| # | Test | Status |
|---|------|--------|
| 10.1 | Page loads with broker selection | [ ] |
| 10.2 | Channel verification (paper trading detection) | [ ] |
| 10.3 | User verification (slippage detection) | [ ] |
| 10.4 | Fill validation (signal vs broker fill) | [ ] |
| 10.5 | Analysis period selection (7-60 days) | [ ] |
| 10.6 | Verification report generation | [ ] |
| 10.7 | Entity analysis drill-down | [ ] |
| 10.8 | Verification stats (per channel, per user) | [ ] |

**API Endpoints:**
- [ ] `GET /api/verification/broker-status` — broker verification status
- [ ] `POST /api/verification/verify` — verify entity
- [ ] `GET /api/verification/report/<entity_type>/<entity_id>` — report
- [ ] `GET /api/verification/analyze/<entity_type>/<entity_id>` — analysis
- [ ] `GET /api/verification/stats/<entity_type>/<entity_id>` — stats
- [ ] `GET /api/verification/users` — users for verification
- [ ] `GET /api/verification/channels` — channels for verification

**Database Tables:** `signal_verifications`, `verification_stats`

---

### 11. Signal History (`/signals`, `/signals/us`, `/signals/canada`)

**Page:** `signal_history.html` | **Routes:** `GET /signals`, `GET /signals/us`, `GET /signals/canada`

| # | Test | Status |
|---|------|--------|
| 11.1 | All signals page loads | [ ] |
| 11.2 | US signals filtered (USD market) | [ ] |
| 11.3 | Canada signals filtered (CAD market) | [ ] |
| 11.4 | Signal detail view | [ ] |
| 11.5 | Signal statistics | [ ] |
| 11.6 | Export signals | [ ] |
| 11.7 | Filter by symbol, status, broker, date | [ ] |

**API Endpoints:**
- [ ] `GET /api/signals` — all signals
- [ ] `GET /api/signals/history` — signal history
- [ ] `GET /api/signals/<id>` — signal detail
- [ ] `GET /api/signals/statistics` — statistics
- [ ] `GET /api/signals/export` — export

**Database Tables:** `signals`, `signal_instances`, `signal_event_transitions`

---

## ADMIN TAB

### 12. System Health (`/health`) [GATE]

**Page:** `health.html` | **Route:** `GET /health`

| # | Test | Status |
|---|------|--------|
| 10.1 | Page loads with health status | [ ] |
| 10.2 | Full health check runs | [ ] |
| 10.3 | Individual component test | [ ] |
| 10.4 | Diagnostics display | [ ] |
| 10.5 | Migration status check | [ ] |
| 10.6 | Migration upgrade runs | [ ] |
| 10.7 | Database schema validation | [ ] |
| 10.8 | Consistency check | [ ] |
| 10.9 | Build info display | [ ] |
| 10.10 | Code version display | [ ] |
| 10.11 | Bot status/stop/restart | [ ] |
| 10.12 | QA test runner | [ ] |

**API Endpoints:**
- [ ] `GET /api/health/full` — full health
- [ ] `POST /api/health/test/<component>` — test component
- [ ] `GET /api/health/diagnostics` — diagnostics
- [ ] `GET /api/health/run-tests` — run tests
- [ ] `GET /api/health/migrations` — migration status
- [ ] `POST /api/health/migrations/upgrade` — run migrations
- [ ] `GET /api/system/consistency-check` — consistency check
- [ ] `GET /api/system/build-info` — build info
- [ ] `GET /api/api/code-version` — code version
- [ ] `POST /api/bot/status` — bot status
- [ ] `POST /api/bot/stop` — stop bot
- [ ] `POST /api/bot/restart` — restart bot
- [ ] `GET /api/qa/validate` — QA validation
- [ ] `GET /api/qa/features` — QA features
- [ ] `GET /api/qa/database-schema` — DB schema
- [ ] `GET /api/qa/workflows` — QA workflows
- [ ] `GET /api/qa/trading-pipeline` — trading pipeline
- [ ] `POST /api/qa/pytest` — run pytest
- [ ] `GET /api/qa/feature/<name>` — specific QA feature
- [ ] `POST /api/qa/impact` — impact analysis
- [ ] `POST /api/qa/tests/run` — run QA tests

**Database Tables:** `error_logs`, `known_issues`, `debug_reports`, `service_registry`, `service_metrics`

---

### 13. Settings (`/settings`) [GATE]

**Page:** `settings.html` | **Route:** `GET /settings`

#### 13a. Trading Settings

| # | Test | Status |
|---|------|--------|
| 11.1 | Global default quantity saves/loads | [ ] |
| 11.2 | Max position size saves/loads | [ ] |
| 11.3 | Trade summary enabled toggle | [ ] |
| 11.4 | Trade summary channel setting | [ ] |

- [ ] `GET /api/settings/trading` — get trading settings
- [ ] `POST /api/settings/trading` — save trading settings

#### 13b. Global Risk Settings

| # | Test | Status |
|---|------|--------|
| 11.5 | Signal update automation toggle | [ ] |
| 11.6 | Exit strategy mode (signal/risk/hybrid) | [ ] |
| 11.7 | Circuit breaker enable | [ ] |
| 11.8 | Global daily loss limit | [ ] |
| 11.9 | Global max positions | [ ] |
| 11.10 | Order timeout minutes | [ ] |
| 11.11 | Risk check interval seconds | [ ] |
| 11.12 | Daily P&L limits (dollar, %, profit limit) | [ ] |
| 11.13 | Daily P&L warning threshold | [ ] |
| 11.14 | Daily P&L reset time | [ ] |
| 11.15 | Max daily trades (default + overrides) | [ ] |

- [ ] `GET /api/settings/global-risk` — get global risk
- [ ] `POST /api/settings/global-risk` — save global risk
- [ ] `PUT /api/settings/global-risk` — update global risk

#### 13c. Conditional Order Settings

| # | Test | Status |
|---|------|--------|
| 11.16 | Conditional orders enable toggle | [ ] |
| 11.17 | Trigger offset (%, mode, value) | [ ] |
| 11.18 | Default expiry settings | [ ] |
| 11.19 | Auto-execute toggle | [ ] |
| 11.20 | Timeout minutes | [ ] |

- [ ] `GET /api/settings/conditional_orders` — get settings
- [ ] `POST /api/settings/conditional_orders` — save settings

#### 13d. Slippage Settings

| # | Test | Status |
|---|------|--------|
| 11.21 | Slippage protection enable | [ ] |
| 11.22 | Threshold percent | [ ] |

- [ ] `GET /api/settings/slippage` — get slippage
- [ ] `POST /api/settings/slippage` — save slippage

#### 13e. Discord Settings

| # | Test | Status |
|---|------|--------|
| 11.23 | Allow self-messages toggle | [ ] |
| 11.24 | Discovery mode toggle | [ ] |
| 11.25 | Option/stock signal patterns | [ ] |
| 11.26 | Allowed author IDs | [ ] |
| 11.27 | Allowed guild IDs | [ ] |

- [ ] `GET /api/settings/discord` — get Discord
- [ ] `POST /api/settings/discord` — save Discord
- [ ] `GET /api/settings/discord_notifications` — get notifications
- [ ] `POST /api/settings/discord_notifications` — save notifications

#### 13f. Telegram Settings

| # | Test | Status |
|---|------|--------|
| 11.28 | Telegram enable toggle | [ ] |
| 11.29 | API ID and hash | [ ] |
| 11.30 | Phone number | [ ] |
| 11.31 | Test connection | [ ] |
| 11.32 | Verify code / 2FA | [ ] |
| 11.33 | Telegram channel CRUD | [ ] |

- [ ] `GET /api/settings/telegram` — get Telegram
- [ ] `POST /api/settings/telegram` — save Telegram
- [ ] `POST /api/telegram/test-connection` — test
- [ ] `POST /api/telegram/verify-code` — verify code
- [ ] `POST /api/telegram/verify-2fa` — verify 2FA
- [ ] Telegram channel CRUD (GET/POST/PUT/DELETE)

#### 13g. Broker Credentials

| # | Test | Status |
|---|------|--------|
| 11.34 | Schwab credentials save/load | [ ] |
| 11.35 | Alpaca credentials (paper + live) | [ ] |
| 11.36 | Webull credentials + token clear | [ ] |
| 11.37 | Tastytrade credentials + clear | [ ] |
| 11.38 | Trading212 credentials | [ ] |
| 11.39 | IBKR credentials | [ ] |
| 11.40 | Robinhood credentials | [ ] |
| 11.41 | Extended hours toggle per broker | [ ] |
| 11.42 | Broker connect/disconnect | [ ] |
| 11.43 | Broker reload | [ ] |

- [ ] Broker credential GET/POST for each broker
- [ ] `POST /api/brokers/connect/<id>` — connect
- [ ] `POST /api/brokers/disconnect/<id>` — disconnect
- [ ] `POST /api/brokers/reload` — reload
- [ ] `GET /api/brokers/grouped` — brokers by country
- [ ] `GET /api/brokers/<name>/profile` — broker profile
- [ ] `POST /api/brokers/<name>/test` — test connection
- [ ] `POST /api/brokers/<name>/reconnect` — reconnect
- [ ] `GET /api/brokers/by-country/<code>` — brokers by country
- [ ] `GET /api/brokers/extended-hours` — extended hours brokers
- [ ] `GET /api/broker/available` — available brokers

**Schwab OAuth Flow (Blueprint):**

| # | Test | Status |
|---|------|--------|
| 13.63 | Schwab auth URL generation | [ ] |
| 13.64 | Schwab OAuth callback handling | [ ] |
| 13.65 | Schwab OAuth status polling | [ ] |
| 13.66 | Schwab token refresh | [ ] |
| 13.67 | Schwab disconnect | [ ] |
| 13.68 | Schwab manual code entry | [ ] |

- [ ] `GET /schwab/auth-url` — get auth URL
- [ ] `GET /schwab/callback` — OAuth callback
- [ ] `GET /schwab/oauth-status` — poll completion
- [ ] `POST /schwab/oauth-reset` — reset flow
- [ ] `GET /schwab/status` — connection status
- [ ] `POST /schwab/refresh` — token refresh
- [ ] `POST /schwab/disconnect` — disconnect
- [ ] `POST /schwab/manual-code` — manual code entry

**Google OAuth Flow (Blueprint):**

- [ ] `GET /google_login` — initiate Google OAuth
- [ ] `GET /google_login/callback` — Google callback

**Webull Multi-Step Auth:**

| # | Test | Status |
|---|------|--------|
| 13.69 | Webull email/password login | [ ] |
| 13.70 | Webull MFA request | [ ] |
| 13.71 | Webull security question | [ ] |
| 13.72 | Webull session login | [ ] |

- [ ] `POST /api/webull/auth/login` — login
- [ ] `POST /api/webull/auth/request-mfa` — MFA
- [ ] `POST /api/webull/auth/security-question` — security question
- [ ] `POST /api/webull/auth/session-login` — session login

#### 13h. AI Analysis Settings

- [ ] `GET /api/settings/ai_analysis` — get AI settings
- [ ] `POST /api/settings/ai_analysis` — save AI settings

#### 13i. Signal Conversion Settings

| # | Test | Status |
|---|------|--------|
| 13.54 | Signal conversion enable/disable | [ ] |
| 13.55 | Conversion channel configuration | [ ] |

- [ ] `GET /api/settings/signal_conversion` — get signal conversion
- [ ] `POST /api/settings/signal_conversion` — save signal conversion

#### 13j. Trade Monitor Settings

| # | Test | Status |
|---|------|--------|
| 13.56 | Trade monitor enable/disable | [ ] |
| 13.57 | Poll interval setting | [ ] |
| 13.58 | Include stocks/options toggles | [ ] |
| 13.59 | BTO/STC posting toggles | [ ] |

- [ ] `GET /api/settings/trade_monitor` — get trade monitor
- [ ] `POST /api/settings/trade_monitor` — save trade monitor

#### 13k. Risk Management Settings

- [ ] `GET /api/settings/risk_management` — get risk management
- [ ] `POST /api/settings/risk_management` — save risk management

#### 13l. Sizing Settings

| # | Test | Status |
|---|------|--------|
| 13.60 | Position sizing mode configuration | [ ] |
| 13.61 | User sizing overrides | [ ] |
| 13.62 | Analyst portfolio assignment | [ ] |

- [ ] `GET /api/sizing-settings` — get sizing
- [ ] `POST /api/sizing-settings` — save sizing
- [ ] `POST /api/analyst-portfolio` — set analyst portfolio

#### 13m. Debug Settings

- [ ] `GET /api/settings/debug` — get debug settings
- [ ] `POST /api/settings/debug` — update debug settings

#### 13n. Webhook Settings

| # | Test | Status |
|---|------|--------|
| 11.44 | Webhook config save/load | [ ] |
| 11.45 | Webhook test | [ ] |
| 11.46 | Webhook channel CRUD | [ ] |
| 11.47 | Webhook channel test | [ ] |
| 11.48 | BTO/STC post via webhook | [ ] |

- [ ] `GET /api/webhook/config` + `POST`
- [ ] `POST /api/webhook/test`
- [ ] Webhook channel CRUD (GET/POST/PUT/DELETE)
- [ ] `POST /api/webhook/post_bto` / `POST /api/webhook/post_stc`
- [ ] `GET /api/webhook/positions` — webhook positions
- [ ] `POST /api/webhook/find_position` — find position

#### 13o. Background Services

- [ ] `GET /api/settings/background_services` — get services
- [ ] `POST /api/settings/background_services` — save services

#### 13p. Notification Settings

| # | Test | Status |
|---|------|--------|
| 11.49 | Trade notifications toggle | [ ] |
| 11.50 | Profit notifications toggle | [ ] |
| 11.51 | Error notifications toggle | [ ] |
| 11.52 | Discord/email/desktop toggles | [ ] |
| 11.53 | Test notification | [ ] |

- [ ] `GET /api/notifications/settings` + `POST`
- [ ] `POST /api/notifications/test`

**Database Tables:** `settings`, `trading_settings`, `slippage_settings`, `ai_settings`, `discord_settings`, `telegram_settings`, `global_risk_settings`, `risk_management_settings`, `trade_monitor_settings`, `email_config`, `config` (encrypted credentials), `broker_credentials`, `broker_profiles`, `broker_sync_state`, `service_registry`, `broker_limits`, `user_sizing_settings`, `analyst_portfolios`

---

### 14. License (`/license`) [GATE]

**Page:** `license.html` | **Route:** `GET /license`

| # | Test | Status |
|---|------|--------|
| 12.1 | Page loads with license status | [ ] |
| 12.2 | License activation with key | [ ] |
| 12.3 | License validation | [ ] |
| 12.4 | License deactivation | [ ] |
| 12.5 | Machine info display | [ ] |
| 12.6 | Trial start | [ ] |
| 12.7 | License health check | [ ] |
| 12.8 | Expiry display and warning | [ ] |

**API Endpoints:**
- [ ] `GET /api/license/status` — status
- [ ] `GET /api/license/machine-info` — machine info
- [ ] `POST /api/license/activate` — activate
- [ ] `POST /api/license/validate` — validate
- [ ] `POST /api/license/deactivate` — deactivate
- [ ] `GET /api/v1/license/health` — health
- [ ] `POST /api/v1/license/trial` — start trial

**Database Tables:** `local_license`, `server_licenses`, `server_trials`, `server_machines`, `license_validation_log`

---

### 15. Docs (`/architecture`)

**Page:** `architecture.html` | **Route:** `GET /architecture`

| # | Test | Status |
|---|------|--------|
| 13.1 | Page loads (public, no auth required) | [ ] |
| 13.2 | Architecture diagrams display | [ ] |

---

### 16. Help Center (`/help`)

**Page:** `help.html` | **Route:** `GET /help`

| # | Test | Status |
|---|------|--------|
| 14.1 | Page loads | [ ] |
| 14.2 | Setup guides display | [ ] |
| 14.3 | Settings documentation | [ ] |
| 14.4 | AI chat integration | [ ] |

**Chat API Endpoints:**
- [ ] `POST /api/chat` — send message
- [ ] `POST /api/chat/upload-log` — upload log
- [ ] `GET /api/chat/suggestions` — suggestions
- [ ] `GET /api/chat/topics` — topics
- [ ] `GET /api/chat/status` — status
- [ ] `POST /api/chat/errors/seen` — mark errors seen
- [ ] `GET /api/chat/logs` — chat logs

---

## CROSS-CUTTING FEATURES

### 17. Signal Processing [GATE]

| # | Test | Status |
|---|------|--------|
| 15.1 | BTO/STC standard format parsing | [ ] |
| 15.2 | Bullwinkle (lotto) format | [ ] |
| 15.3 | Jacob (ENTERED LONG) format | [ ] |
| 15.4 | Z-scalps format | [ ] |
| 15.5 | Jake format | [ ] |
| 15.6 | Order Executed format | [ ] |
| 15.7 | Bishop (I'M ENTERING) format | [ ] |
| 15.8 | EvaPanda format | [ ] |
| 15.9 | Conditional (over/above/under/below) | [ ] |
| 15.10 | Signal format CRUD | [ ] |
| 15.11 | Format discovery (AI) | [ ] |
| 15.12 | Test parse | [ ] |
| 15.13 | Learned patterns | [ ] |

**API Endpoints:**
- [ ] `GET /api/signal-formats` — list formats
- [ ] `PUT /api/signal-formats/<id>` — update
- [ ] `DELETE /api/signal-formats/<id>` — delete
- [ ] `POST /api/signal-formats/<id>/toggle` — toggle
- [ ] `POST /api/signal-formats/test-parse` — test parse
- [ ] `GET /api/signal-formats/ai-status` — AI status
- [ ] `POST /api/signal-formats/discover` — discover

**Database Tables:** `signals`, `signal_instances`, `signal_formats`, `signal_format_cache`, `signal_event_transitions`, `learned_patterns`

---

### 18. Multi-Broker Routing [GATE]

| # | Test | Status |
|---|------|--------|
| 16.1 | STRICT routing: no primary broker fallback | [ ] |
| 16.2 | Single broker execution | [ ] |
| 16.3 | Multi-broker execution (all configured brokers) | [ ] |
| 16.4 | Broker not connected scenario | [ ] |
| 16.5 | All-or-reject policy verification | [ ] |
| 16.6 | Broker-specific balance check | [ ] |
| 16.7 | Extended hours execution | [ ] |

**Supported Brokers:** Schwab, Alpaca, Webull, Tastytrade, Trading212, IBKR, Robinhood, Upstox (India)

**Balance API Endpoints (one per broker):**
- [ ] `GET /api/schwab/balance`
- [ ] `GET /api/alpaca/balance`
- [ ] `GET /api/webull/balance`
- [ ] `GET /api/tastytrade/balance`
- [ ] `GET /api/trading212/balance`
- [ ] `GET /api/ibkr/balance`
- [ ] `GET /api/robinhood/balance`

---

### 19. Risk Management [GATE]

| # | Test | Status |
|---|------|--------|
| 17.1 | Stop loss trigger at threshold | [ ] |
| 17.2 | Trailing stop activation after profit threshold | [ ] |
| 17.3 | Trailing stop trigger on pullback | [ ] |
| 17.4 | Trailing stop NOT on downside (before threshold) | [ ] |
| 17.5 | 4-tier profit targets in sequence | [ ] |
| 17.6 | Exit strategy modes (signal, risk, hybrid) | [ ] |
| 17.7 | Leave runner functionality | [ ] |
| 17.8 | Dynamic SL escalation (3 profiles) | [ ] |
| 17.9 | Giveback guard activation | [ ] |
| 17.10 | Early trailing (activation + step) | [ ] |
| 17.11 | EMA-based stop loss | [ ] |
| 17.12 | Broker bracket orders (SL + PT) | [ ] |
| 17.13 | Per-channel vs global risk settings | [ ] |
| 17.14 | Risk cache invalidation on setting change | [ ] |
| 17.15 | Circuit breaker (daily loss limit) | [ ] |
| 17.16 | Daily P&L limit enforcement | [ ] |
| 17.17 | Escalation only mode | [ ] |

**Validation:** Run the full 10-step checklist from `RISK_SETTINGS_VALIDATION_REFERENCE.md`

**Database Tables:** `global_risk_settings`, `daily_pnl_state`, `risk_events`, `risk_management_settings`, `position_risk_settings`

---

### 20. Conditional Orders [GATE]

| # | Test | Status |
|---|------|--------|
| 18.1 | Over/above trigger conditions | [ ] |
| 18.2 | Under/below trigger conditions | [ ] |
| 18.3 | Timeout precedence (order → conditional → expiry) | [ ] |
| 18.4 | Channel settings linkage | [ ] |
| 18.5 | Order expiration (end of day, minute-based) | [ ] |
| 18.6 | Cancel conditional order | [ ] |
| 18.7 | Audit trail | [ ] |
| 18.8 | Live price monitoring | [ ] |
| 18.9 | Purge old orders | [ ] |

**API Endpoints:**
- [ ] `GET /api/conditional_orders` — list
- [ ] `GET /api/conditional_orders/<id>` — detail
- [ ] `POST /api/conditional_orders/<id>/cancel` — cancel
- [ ] `GET /api/conditional_orders/<id>/audit` — audit
- [ ] `POST /api/conditional_orders/purge` — purge
- [ ] `GET /api/conditional_orders/status` — status
- [ ] `GET /api/conditional_orders/live_prices` — live prices
- [ ] `POST /api/conditional_orders/<id>/offset` — offset order price

**Database Tables:** `conditional_orders`, `conditional_order_audit`

---

### 21. Signal Routing (Admin) [GATE]

**Page:** `signal_routing.html` | **Route:** `GET /admin/signal-routing`

| # | Test | Status |
|---|------|--------|
| 19.1 | Routing mapping CRUD | [ ] |
| 19.2 | Source → destination channel routing | [ ] |
| 19.3 | Webhook destination routing | [ ] |
| 19.4 | Per-routing risk settings | [ ] |
| 19.5 | Routing positions view | [ ] |
| 19.6 | Routing P&L view | [ ] |
| 19.7 | Enable/disable individual mappings | [ ] |

**API Endpoints:**
- [ ] `GET /api/admin/signal-routing` — list
- [ ] `POST /api/admin/signal-routing` — create
- [ ] `PUT /api/admin/signal-routing/<id>` — update
- [ ] `DELETE /api/admin/signal-routing/<id>` — delete
- [ ] `GET /api/admin/signal-routing/positions` — positions
- [ ] `GET /api/admin/signal-routing/pnl` — P&L

**Database Tables:** `signal_routing_mappings`, `channel_mappings`, `conversion_channels`

---

### 22. Authentication & User Management

| # | Test | Status |
|---|------|--------|
| 20.1 | Login page loads | [ ] |
| 20.2 | Admin login works | [ ] |
| 20.3 | User login works (user_mode) | [ ] |
| 20.4 | Signup flow | [ ] |
| 20.5 | Consent form acceptance | [ ] |
| 20.6 | Password reset (forgot → email → reset) | [ ] |
| 20.7 | Local reset (no email) | [ ] |
| 20.8 | Session timeout / auto-logout | [ ] |
| 20.9 | Setup wizard | [ ] |
| 20.10 | User dashboard (SaaS) | [ ] |
| 20.11 | User simulation (SaaS) | [ ] |
| 20.12 | Waitlist signup/management | [ ] |

**Database Tables:** `app_users`, `end_users`, `user_subscriptions`, `password_reset_tokens`, `waitlist`

---

### 23. Upgrade & Version Management

| # | Test | Status |
|---|------|--------|
| 21.1 | Version info display | [ ] |
| 21.2 | Check for upgrades | [ ] |
| 21.3 | Upgrade readiness check | [ ] |
| 21.4 | Backup creation | [ ] |
| 21.5 | Backup restore | [ ] |
| 21.6 | Run upgrade | [ ] |
| 21.7 | Upgrade history | [ ] |

**API Endpoints:**
- [ ] `GET /api/upgrade/version` — version info
- [ ] `POST /api/upgrade/check` — check
- [ ] `GET /api/upgrade/readiness` — readiness
- [ ] `GET /api/upgrade/backups` — list backups
- [ ] `POST /api/upgrade/backup` — create backup
- [ ] `POST /api/upgrade/backup/restore` — restore
- [ ] `POST /api/upgrade/run` — run upgrade
- [ ] `GET /api/upgrade/history` — history
- [ ] `POST /api/upgrade/skip` — skip upgrade
- [ ] `POST /api/upgrade/remind-later` — remind later

---

### 24. Error Tracking & Debug

| # | Test | Status |
|---|------|--------|
| 22.1 | Error logs display | [ ] |
| 22.2 | Frequent errors aggregation | [ ] |
| 22.3 | Error resolution marking | [ ] |
| 22.4 | Known issues database | [ ] |
| 22.5 | Debug report submission | [ ] |
| 22.6 | Debug report history | [ ] |

**API Endpoints:**
- [ ] `GET /api/errors` — list errors
- [ ] `GET /api/errors/frequent` — frequent errors
- [ ] `POST /api/errors/<id>/resolve` — resolve
- [ ] `GET /api/errors/known-issues` — known issues
- [ ] `POST /api/errors/log` — log error
- [ ] `POST /api/debug-report/submit` — submit report
- [ ] `GET /api/debug-report/history` — report history

---

### 25. Services & Rate Limiting

| # | Test | Status |
|---|------|--------|
| 23.1 | Service registry displays | [ ] |
| 23.2 | Service toggle on/off | [ ] |
| 23.3 | Service interval configuration | [ ] |
| 23.4 | Broker rate limit display | [ ] |
| 23.5 | Order events log | [ ] |

**API Endpoints:**
- [ ] `GET /api/services` — list services
- [ ] `PUT /api/services/<id>` — update
- [ ] `POST /api/services/<id>/toggle` — toggle
- [ ] `GET /api/broker-limits` — rate limits
- [ ] `GET /api/services/status` — services status
- [ ] `GET /api/order-events` — order events
- [ ] `POST /api/order-events/clear` — clear events
- [ ] `GET /api/order-events/stats` — event stats

**Database Tables:** `service_registry`, `service_metrics`, `broker_limits`, `order_events`

---

### 26. India Market Features

| # | Test | Status |
|---|------|--------|
| 26.1 | Upstox broker connection | [ ] |
| 26.2 | Upstox funds display | [ ] |
| 26.3 | Upstox positions display | [ ] |
| 26.4 | Upstox orders display | [ ] |
| 26.5 | Upstox trades display | [ ] |
| 26.6 | Upstox execution timing | [ ] |
| 26.7 | Upstox holdings | [ ] |
| 26.8 | Upstox account info | [ ] |
| 26.9 | Upstox order cancellation | [ ] |
| 26.10 | Upstox AMO queue enable/disable | [ ] |
| 26.11 | Upstox pending orders CRUD | [ ] |
| 26.12 | NSE/BSE market channels | [ ] |
| 26.13 | Lot size handling for India F&O | [ ] |
| 26.14 | India bot dashboard (`india_bot/`) | [ ] |
| 26.15 | India bot channels page | [ ] |
| 26.16 | India signals processing | [ ] |
| 26.17 | India conditional orders | [ ] |
| 26.18 | Zerodha broker integration | [ ] |
| 26.19 | DhanQ broker integration | [ ] |

**API Endpoints (main app):**
- [ ] `GET /api/brokers/upstox/funds` — Upstox funds
- [ ] `GET /api/brokers/upstox/positions` — positions
- [ ] `GET /api/brokers/upstox/orders` — orders
- [ ] `GET /api/brokers/upstox/trades` — trades
- [ ] `GET /api/brokers/upstox/execution-timing` — timing
- [ ] `GET /api/brokers/upstox/holdings` — holdings
- [ ] `GET /api/brokers/upstox/account` — account
- [ ] `POST /api/brokers/upstox/cancel-order` — cancel
- [ ] `GET /api/upstox/pending-orders` — pending orders
- [ ] `DELETE /api/upstox/pending-orders/<id>` — delete pending
- [ ] `GET /api/upstox/amo-queue-enabled` — AMO status
- [ ] `POST /api/upstox/amo-queue-enabled` — set AMO

**India Bot API Endpoints (`india_bot/gui_app/`):**
- [ ] `GET /api/health` — India bot health
- [ ] `GET /api/channels` — India channels
- [ ] `GET /api/channels/<chat_id>` — channel settings
- [ ] `GET /api/conditional-orders` — India conditional orders
- [ ] `GET /api/broker/status` — India broker status
- [ ] `GET /api/broker/<name>/credentials` — broker credentials
- [ ] `POST /api/broker/<name>/credentials` — save credentials
- [ ] `GET /api/upstox/orders` — Upstox orders
- [ ] `GET /api/upstox/positions` — Upstox positions
- [ ] `GET /api/signals` — India signals
- [ ] `GET /api/pending-orders` — pending orders

**Database Tables (bot_data.db):** `upstox_pending_orders`, `countries`, `broker_profiles`

**Database Tables (india_bot.db — 9 tables):** `settings`, `broker_credentials`, `telegram_channels`, `india_signals`, `india_conditional_orders`, `india_positions`, `upstox_pending_orders`, `zerodha_pending_orders`, `dhanq_pending_orders`

---

### 27. Real-Time Streaming

| # | Test | Status |
|---|------|--------|
| 27.1 | Live snapshot stream connects | [ ] |
| 27.2 | Force snapshot refresh | [ ] |
| 27.3 | Streaming stock quotes | [ ] |
| 27.4 | Individual stock quote stream | [ ] |

**API Endpoints:**
- [ ] `GET /api/snapshot/stream` — SSE live snapshots
- [ ] `POST /api/snapshot/force-refresh` — force refresh
- [ ] `GET /api/streaming/quotes` — streaming quotes
- [ ] `GET /api/streaming/stock-quote` — individual stock quote

---

### 28. Discord Signal Sending

| # | Test | Status |
|---|------|--------|
| 28.1 | Send signal to single Discord channel | [ ] |
| 28.2 | Send signal to multiple channels | [ ] |
| 28.3 | Get available send channels | [ ] |

**API Endpoints:**
- [ ] `POST /api/discord/send-signal` — send signal
- [ ] `POST /api/discord/send-signal-multi` — send to multiple
- [ ] `GET /api/discord/send-channels` — available channels

---

### 29. Channel Messages Management

| # | Test | Status |
|---|------|--------|
| 29.1 | Message settings load/save | [ ] |
| 29.2 | Message purge (retention cleanup) | [ ] |
| 29.3 | Channel messages display | [ ] |

**API Endpoints:**
- [ ] `GET /api/channel-messages/settings` — get settings
- [ ] `POST /api/channel-messages/settings` — save settings
- [ ] `POST /api/channel-messages/purge` — purge messages
- [ ] `GET /api/channel-messages` — list messages

**Database Tables:** `channel_messages`

---

### 30. Notifications (Runtime)

| # | Test | Status |
|---|------|--------|
| 30.1 | Notifications display | [ ] |
| 30.2 | Clear notifications | [ ] |
| 30.3 | Broker notifications | [ ] |
| 30.4 | Mark notifications as read | [ ] |

**API Endpoints:**
- [ ] `GET /api/notifications` — list notifications
- [ ] `POST /api/notifications/clear` — clear all
- [ ] `GET /api/brokers/notifications` — broker notifications
- [ ] `POST /api/brokers/notifications/mark-read` — mark read

---

### 31. Risk Status & Diagnostics

| # | Test | Status |
|---|------|--------|
| 31.1 | Risk status overview | [ ] |
| 31.2 | Unprotected trades detection | [ ] |
| 31.3 | Risk debug keys | [ ] |
| 31.4 | System diagnostics | [ ] |
| 31.5 | Diagnostics by category | [ ] |
| 31.6 | Daily P&L status | [ ] |
| 31.7 | Daily P&L unlock | [ ] |
| 31.8 | UPH status | [ ] |

**API Endpoints:**
- [ ] `GET /api/risk-status` — risk status
- [ ] `GET /api/unprotected-trades` — unprotected trades
- [ ] `GET /api/debug-risk-keys` — debug risk keys
- [ ] `GET /api/diagnostics` — diagnostics
- [ ] `GET /api/diagnostics/category/<category>` — by category
- [ ] `GET /api/daily-pnl-status` — daily P&L status
- [ ] `POST /api/daily-pnl-unlock` — unlock daily P&L
- [ ] `GET /api/uph/status` — UPH status

**Database Tables:** `risk_events`, `daily_pnl_state`

---

### 32. System Utilities

| # | Test | Status |
|---|------|--------|
| 32.1 | Backfill fill prices | [ ] |
| 32.2 | Consistency check | [ ] |
| 32.3 | Validate channel configuration | [ ] |
| 32.4 | Position sync across brokers | [ ] |
| 32.5 | Trade monitor synced orders | [ ] |
| 32.6 | Wizard launch/status | [ ] |

**API Endpoints:**
- [ ] `POST /api/system/backfill-fill-prices` — backfill
- [ ] `POST /api/system/consistency-check` — consistency
- [ ] `GET /api/system/validate-channel/<id>` — validate channel
- [ ] `POST /api/sync-positions` — sync positions
- [ ] `GET /api/trade_monitor/synced_orders` — synced orders
- [ ] `POST /api/wizard/launch` — launch wizard
- [ ] `GET /api/wizard/status` — wizard status

---

### 33. Admin Panel (Separate Application)

**App:** `admin_panel/app.py` | **Port:** separate from main app

| # | Test | Status |
|---|------|--------|
| 33.1 | Admin login page loads | [ ] |
| 33.2 | Admin authentication works | [ ] |
| 33.3 | Admin dashboard loads | [ ] |
| 33.4 | License management CRUD | [ ] |
| 33.5 | Device activation tracking | [ ] |
| 33.6 | Audit log display | [ ] |
| 33.7 | Admin forgot/reset password | [ ] |
| 33.8 | Admin settings | [ ] |

**Routes:**
- [ ] `GET /` — admin home
- [ ] `GET, POST /login` — admin login
- [ ] `GET /logout` — admin logout
- [ ] `GET, POST /forgot-password` — forgot password
- [ ] `GET, POST /reset-password/<token>` — reset password

**Database Tables (license_server.db — 5 tables):** `licenses`, `device_activations`, `admin_users`, `password_reset_tokens`, `audit_log`

---

### 34. Broker Analytics & Positions

| # | Test | Status |
|---|------|--------|
| 34.1 | Broker analytics page loads | [ ] |
| 34.2 | Broker-specific position display | [ ] |
| 34.3 | Position close per broker | [ ] |
| 34.4 | Order cancellation per broker | [ ] |
| 34.5 | Bot trades view | [ ] |
| 34.6 | Broker accounts listing | [ ] |

**API Endpoints:**
- [ ] `GET /api/broker/analytics/<broker_id>` — analytics
- [ ] `GET /api/broker/positions/<broker_id>` — positions
- [ ] `GET /api/broker/available` — available brokers
- [ ] `GET /api/brokers/all_accounts` — all accounts
- [ ] `GET /api/bot-trades` — bot trades
- [ ] `POST /api/schwab/positions/<symbol>/close` — close Schwab position
- [ ] `POST /api/robinhood/positions/<symbol>/close` — close Robinhood position
- [ ] `POST /api/ibkr/positions/<symbol>/close` — close IBKR position
- [ ] `POST /api/tastytrade/positions/<symbol>/close` — close Tastytrade position
- [ ] `POST /api/alpaca/positions/<symbol>/close` — close Alpaca position
- [ ] `POST /api/robinhood/orders/<id>/cancel` — cancel Robinhood order
- [ ] `POST /api/alpaca/orders/<id>/cancel` — cancel Alpaca order
- [ ] `POST /api/orders/<broker>/<id>/cancel` — generic cancel

---

### 35. Channel Mappings

| # | Test | Status |
|---|------|--------|
| 35.1 | Channel mapping CRUD | [ ] |
| 35.2 | Source to destination mapping | [ ] |

**API Endpoints:**
- [ ] `GET /api/channel_mappings` — list
- [ ] `POST /api/channel_mappings` — create
- [ ] `PUT /api/channel_mappings/<id>` — update
- [ ] `DELETE /api/channel_mappings/<id>` — delete

**Database Tables:** `channel_mappings`, `conversion_channels`

---

## DATABASE VALIDATION

### Table Count Check [GATE]

**Expected: 74 tables across 4 databases** (as of v9.2.5)

| Database | Tables | Purpose |
|----------|--------|---------|
| `bot_data.db` | ~54 | Main trading database |
| `agent_data.db` | 6 | Agent Studio orchestration |
| `india_bot.db` | 9 | India market trading |
| `license_server.db` | 5 | License management |

```bash
# Check all 4 databases
for db in bot_data.db agent_data.db india_bot/gui_app/india_bot.db license_server.db; do
  echo "=== $db ==="
  python3 -c "
import sqlite3, os
if not os.path.exists('$db'):
    print('  NOT FOUND'); exit()
conn = sqlite3.connect('$db')
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print(f'  Tables: {len(tables)}')
for t in sorted(tables):
    print(f'    {t[0]}')
conn.close()
"
done
```

### Migration Integrity [GATE]

- [ ] All ALTER TABLE migrations run without error on fresh DB
- [ ] All ALTER TABLE migrations are idempotent (safe to re-run)
- [ ] Default values set for all new columns
- [ ] No data loss on schema upgrade

---

## COVERAGE REQUIREMENTS

| Area | Minimum Coverage |
|------|-----------------|
| Signal Parser | 80% |
| Database Operations | 70% |
| Multi-Broker Routing | 80% |
| Risk Management | 70% |
| Channel CRUD | 60% |
| Trade Management | 60% |
| Overall | 50% |

---

## RELEASE CHECKLIST

### Before Tagging Version

- [ ] All [GATE] sections above pass
- [ ] `python -m py_compile` passes on all `.py` files
- [ ] `pytest qa/tests -v` passes
- [ ] Risk settings wiring validated (RISK_SETTINGS_VALIDATION_REFERENCE.md)
- [ ] Database migrations run on fresh DB
- [ ] No hardcoded secrets in committed code
- [ ] Pre-commit hook passes
- [ ] Version bumped via `VersionManager.bump_version()`
- [ ] PR created and reviewed
- [ ] Changelog updated

### After Tagging Version

- [ ] Git tag created (`v9.x.x`)
- [ ] Tag pushed to remote
- [ ] GitHub Actions build triggered (user + admin)
- [ ] Build artifacts verified (Windows, Linux, macOS Intel, macOS Silicon)
- [ ] Release published to public repo

---

**Last Updated**: 2026-04-26
**Version**: 3.0.0
**Total Sections**: 35
**Total Test Cases**: 300+
**Total API Endpoints Covered**: 447+
**Total Database Tables**: 74 (across 4 databases)
