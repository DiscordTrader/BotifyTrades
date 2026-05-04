# BotifyTrades QA Playbook — Complete Validation Reference

## Overview

This document defines the complete quality assurance checklist for BotifyTrades. Every page, API endpoint, database table, and setting must be validated before releasing a new version. The checklist is organized by the application's tab structure.

**Current Version Baseline:** 9.3.4+
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

#### Quick Add Form

| # | Test | Status |
|---|------|--------|
| 2.1 | Page loads, all channels listed | [ ] |
| 2.2 | Add channel with Discord Channel ID | [ ] |
| 2.3 | Channel name field | [ ] |
| 2.4 | Market/Country dropdown (US / CA / IN) | [ ] |
| 2.5 | Execute Trades toggle on create | [ ] |
| 2.6 | Track Signals toggle on create | [ ] |
| 2.7 | Edit channel settings | [ ] |
| 2.8 | Delete channel | [ ] |
| 2.9 | Reset channel | [ ] |
| 2.10 | Market filter (USA/Canada/India) | [ ] |
| 2.11 | Category filter | [ ] |
| 2.12 | Channel allowed users CRUD | [ ] |
| 2.13 | Recent messages scan | [ ] |
| 2.14 | Canada-specific channels (`/channels/canada`) | [ ] |
| 2.15 | Multi-broker selection (`enabled_brokers` JSON) | [ ] |
| 2.16 | Platform type (discord/telegram) | [ ] |

#### Tab 1: Sizing

| # | Test | Status |
|---|------|--------|
| 2.17 | Execute Trades toggle (`execute_enabled`) | [ ] |
| 2.18 | Position Size % (`position_size_pct`, range 0.1-100) | [ ] |
| 2.19 | Default Qty (`default_quantity`, range 1-1000) | [ ] |
| 2.20 | Force My Size % toggle (`ignore_signal_position_size`) | [ ] |
| 2.21 | Balance Mode dropdown (`sizing_mode`: live / pre_market / start_of_day) | [ ] |
| 2.22 | Track Signals toggle (`track_enabled`) | [ ] |
| 2.23 | Tracking Position Size % (`tracking_position_size_pct`) | [ ] |
| 2.24 | Tracking Default Qty (`tracking_default_quantity`) | [ ] |
| 2.25 | Max Position $ (`channel_max_position_size`, range 100-100000) | [ ] |

#### Tab 2: Risk Controls

| # | Test | Status |
|---|------|--------|
| 2.26 | Signal Update Automation toggle (`signal_update_automation`) | [ ] |
| 2.27 | Slippage Protection enable (`slippage_protection_enabled`) | [ ] |
| 2.28 | Slippage Max % (`slippage_max_pct`, range 1-500) | [ ] |
| 2.29 | Slippage Wait minutes (`slippage_wait_minutes`, range 1-120) | [ ] |
| 2.30 | Limit Cap enable (`limit_cap_enabled`) | [ ] |
| 2.31 | Limit Cap % (`limit_cap_pct`, range 0.1-50, default 5) | [ ] |
| 2.32 | NDX→QQQ Conversion enable (`ndx_to_qqq_enabled`) | [ ] |
| 2.33 | NDX→QQQ Target Delta (`ndx_to_qqq_delta`, range 0.1-1.0, default 0.3) | [ ] |

#### Tab 3: Order Types

| # | Test | Status |
|---|------|--------|
| 2.34 | Entry Order Type dropdown (`entry_order_mode`: limit / market) | [ ] |
| 2.35 | Trim Order Type dropdown (`trim_order_mode`: market / limit) | [ ] |
| 2.36 | Stop Loss Order Type dropdown (`sl_order_mode`: limit / market) | [ ] |

#### Tab 4: Conditional

| # | Test | Status |
|---|------|--------|
| 2.37 | Conditional Orders enable (`conditional_order_enabled`) | [ ] |
| 2.38 | Order Timeout - all orders (`order_timeout_minutes`, range 1-1440) | [ ] |
| 2.39 | Conditional Timeout (`conditional_order_timeout_minutes`, range 1-1440) | [ ] |
| 2.40 | Entry Confirmation Buffer % (`entry_confirmation_pct`, range 0-50) | [ ] |
| 2.41 | Breakout Reset Guard toggle (`breakout_reset_enabled`, default 1) | [ ] |
| 2.42 | Trigger Offset Mode dropdown (`trigger_offset_mode`: percent / dollar) | [ ] |
| 2.43 | Trigger Offset Value (`trigger_offset_percent` / `trigger_offset_value`, range -100 to 100) | [ ] |

#### Risk Settings per Channel (see RISK_SETTINGS_VALIDATION_REFERENCE.md for full 42-field wiring)

These fields are set via the Risk Management panel on the Execution page (Section 3):

| # | Test | Status |
|---|------|--------|
| 2.44 | Risk management enable/disable (`risk_management_enabled`) | [ ] |
| 2.45 | Use global risk settings toggle (`use_global_risk_settings`) | [ ] |
| 2.46 | Channel daily loss limit (`channel_daily_loss_limit`) | [ ] |
| 2.47 | Channel max positions (`channel_max_positions`) | [ ] |
| 2.48 | Circuit breaker per channel (`circuit_breaker_enabled`) | [ ] |
| 2.49 | Cache invalidation fires on risk field save | [ ] |

**API Endpoints:**
- [ ] `GET /api/channels` — list (with market/category filters)
- [ ] `POST /api/channels` — create
- [ ] `PUT /api/channels/<id>` — update (all tab fields)
- [ ] `DELETE /api/channels/<id>` — delete
- [ ] `POST /api/channels/<id>/reset` — reset
- [ ] `GET /api/channels/<id>/allowed_users` — list users
- [ ] `POST /api/channels/<id>/allowed_users` — add user
- [ ] `DELETE /api/channels/<id>/allowed_users/<uid>` — remove user
- [ ] `GET /api/channels/<id>/users` — get users in channel
- [ ] `GET /api/channels/<id>/recent-messages` — scan messages
- [ ] `POST /api/channels/<id>/scan` — scan for signals

**Database Tables:** `channels` (70+ columns), `channel_allowed_users`, `channel_messages`

**Database Columns (channels table):**
- Core: `id`, `discord_channel_id`, `name`, `market`, `platform`, `is_active`, `created_at`, `updated_at`
- Sizing: `execute_enabled`, `track_enabled`, `position_size_pct`, `default_quantity`, `tracking_position_size_pct`, `tracking_default_quantity`, `channel_max_position_size`, `sizing_mode`, `ignore_signal_position_size`
- Risk Controls: `signal_update_automation`, `slippage_protection_enabled`, `slippage_max_pct`, `slippage_wait_minutes`, `limit_cap_enabled`, `limit_cap_pct`, `ndx_to_qqq_enabled`, `ndx_to_qqq_delta`
- Order Types: `entry_order_mode`, `trim_order_mode`, `sl_order_mode`, `sl_limit_offset`
- Conditional: `conditional_order_enabled`, `order_timeout_minutes`, `conditional_order_timeout_minutes`, `entry_confirmation_pct`, `breakout_reset_enabled`, `trigger_offset_mode`, `trigger_offset_percent`, `trigger_offset_value`
- Risk Management: `risk_management_enabled`, `stop_loss_pct`, `profit_target_1-4_pct`, `profit_target_qty_1-4`, `profit_target_trim_pct_1-4`, `trailing_stop_pct`, `trailing_activation_pct`, `enable_early_trailing`, `early_trailing_activation_pct`, `early_trailing_step_pct`, `leave_runner_enabled`, `leave_runner_pct`, `exit_strategy_mode`, `enable_dynamic_sl`, `dynamic_sl_profile`, `escalation_only_mode`, `enable_giveback_guard`, `giveback_allowed_pct`, `ema_risk_enabled`, `ema_period`, `ema_timeframe_minutes`, `ema_buffer_pct`, `ema_exit_enabled`, `ema_escalation_enabled`, `ema_no_trend_candles`, `ema_use_underlying`, `ema_extended_hours`, `trim_limit_offset`, `trim_limit_offset_mode`, `trim_limit_offset_pct`, `order_chase_enabled`, `entry_chase_enabled`, `broker_bracket_mode`, `trade_summary_enabled`
- Multi-broker: `enabled_brokers`, `use_global_risk_settings`, `channel_daily_loss_limit`, `channel_max_positions`, `circuit_breaker_enabled`
- Telegram: `telegram_chat_id`, `telegram_chat_type`, `telegram_username`
- Legacy/Additional: `category`, `broker_override`, `paper_trade_enabled`, `profit_target_pct`, `signal_update_automation_override`, `exit_strategy_mode_override`, `conditional_order_expiry`, `conditional_auto_execute`, `ticker_filter_mode`, `ticker_filter_list`

---

### 3. Execution (`/execution`) [GATE]

**Page:** `execution.html` | **Route:** `GET /execution`

#### Execution Data

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

#### Per-Channel Risk Management Panel (🛡️ button)

The risk panel has **2 tabs**: "Targets & SL" and "Advanced", plus Quick Presets.

**Quick Presets:**

| # | Test | Status |
|---|------|--------|
| 3.11 | Default preset (PT1:10%, SL:10%, Trail:3%, TrailAct:11%) | [ ] |
| 3.12 | Swing preset (PT1-4:15/30/50/75%, SL:25%, Trail:15%) | [ ] |
| 3.13 | Momentum preset (PT1-4:20/40/60/100%, SL:20%, EarlyTrail:5%/3%) | [ ] |
| 3.14 | Trend preset (PT1-4:25/50/100/150%, SL:30%, Trail:20%) | [ ] |
| 3.15 | Risk status badge shows ENABLED/DISABLED | [ ] |
| 3.16 | Risk summary rail shows active features as pills | [ ] |
| 3.16a | Preset applies order type settings via API (`PUT /api/channels/<id>`) not DOM | [ ] |

**Tab: Targets & SL**

| # | Test | Status |
|---|------|--------|
| 3.17 | PT1 Target % (`profit_target_1_pct`, range 0-500) | [ ] |
| 3.18 | PT2 Target % (`profit_target_2_pct`) | [ ] |
| 3.19 | PT3 Target % (`profit_target_3_pct`) | [ ] |
| 3.20 | PT4 Target % (`profit_target_4_pct`) | [ ] |
| 3.21 | PT1 Trim Qty (`profit_target_qty_1`) | [ ] |
| 3.22 | PT2 Trim Qty (`profit_target_qty_2`) | [ ] |
| 3.23 | PT3 Trim Qty (`profit_target_qty_3`) | [ ] |
| 3.24 | PT4 Trim Qty (`profit_target_qty_4`) | [ ] |
| 3.25 | PT1 Trim % (`profit_target_trim_pct_1`, range 0-100) | [ ] |
| 3.26 | PT2 Trim % (`profit_target_trim_pct_2`) | [ ] |
| 3.27 | PT3 Trim % (`profit_target_trim_pct_3`) | [ ] |
| 3.28 | PT4 Trim % (`profit_target_trim_pct_4`) | [ ] |
| 3.29 | Stop Loss % (`stop_loss_pct`, range 0-100) | [ ] |
| 3.30 | Trailing Stop % (`trailing_stop_pct`, range 0-100) | [ ] |
| 3.31 | Trailing Activation % (`trailing_activation_pct`, range 0-500) | [ ] |
| 3.32 | Exit Strategy Mode radio (`exit_strategy_mode`: signal/risk/hybrid) | [ ] |
| 3.33 | Order Chase mode dropdown (off/entry/exit/both → `order_chase_enabled` + `entry_chase_enabled`) | [ ] |
| 3.34 | Leave Runner enable (`leave_runner_enabled`) | [ ] |
| 3.35 | Leave Runner % (`leave_runner_pct`, default 25, range 1-100) | [ ] |

> **Note:** Trim Order Type and SL Order Type controls are in **Channels → Order Types** tab (Tab 3). Broker Bracket Orders and Early Trailing Stop are in the **Advanced** tab below.

**Tab: Advanced**

| # | Test | Status |
|---|------|--------|
| 3.36 | Broker Bracket Mode radio (`broker_bracket_mode`: both/sl_only/pt_only/none) | [ ] |
| 3.37 | `handleBracketModeChange()` auto-disables market trim when PT bracket active | [ ] |
| 3.38 | "Order type settings" info note links to Order Types tab | [ ] |
| 3.39 | Early Trailing enable (`enable_early_trailing`) — mutually exclusive with trailing | [ ] |
| 3.40 | Early Trailing Breakeven at % (`early_trailing_activation_pct`, default 5) | [ ] |
| 3.41 | Early Trailing Lock profit every % (`early_trailing_step_pct`, default 3) | [ ] |
| 3.42 | Dynamic SL enable (`enable_dynamic_sl`) | [ ] |
| 3.43 | Dynamic SL Profile (`dynamic_sl_profile`: conservative/standard/aggressive) | [ ] |
| 3.44 | SL Escalation Only mode (`escalation_only_mode`) | [ ] |
| 3.45 | Conservative profile: PT1→BE, PT2→+3%, PT3→+8%, PT4→+15% | [ ] |
| 3.46 | Standard profile: PT1→BE, PT2→+5%, PT3→+10%, PT4→+17% | [ ] |
| 3.47 | Aggressive profile: PT1→-2%, PT2→BE, PT3→+8%, PT4→+15% | [ ] |
| 3.48 | Giveback Guard enable (`enable_giveback_guard`) | [ ] |
| 3.49 | Max Giveback % (`giveback_allowed_pct`, default 30, range 5-80) | [ ] |
| 3.50 | EMA Risk enable (`ema_risk_enabled`) | [ ] |
| 3.51 | EMA Period dropdown (`ema_period`: 3/5/8/13/21, default 5) | [ ] |
| 3.52 | EMA Candle Timeframe (`ema_timeframe_minutes`: 1/2/3/5, default 5) | [ ] |
| 3.53 | EMA Buffer % (`ema_buffer_pct`, default 0.1, range 0-2) | [ ] |
| 3.54 | EMA Exit on Cross (`ema_exit_enabled`, default 1) | [ ] |
| 3.55 | EMA Stop Escalation (`ema_escalation_enabled`, default 1) | [ ] |
| 3.56 | EMA No-Trend Candles (`ema_no_trend_candles`, default 3, range 1-20) | [ ] |
| 3.57 | EMA Use Underlying Chart (`ema_use_underlying`, default 1) | [ ] |
| 3.58 | EMA Extended Hours (`ema_extended_hours`, default 0) | [ ] |
| 3.59 | Trade Summary enable per channel (`trade_summary_enabled`) | [ ] |

#### Execution Latency Tracking [GATE]

| # | Test | Status |
|---|------|--------|
| 3.60 | `detected_at` timestamp set at all 6 signal entry points (Discord options, stocks, alert parser, conditional trigger, Telegram bridge) | [ ] |
| 3.61 | `parsed_at` timestamp set immediately after signal parsing | [ ] |
| 3.62 | `_order_submitted_at` captured BEFORE broker API call (not after fill) | [ ] |
| 3.63 | Conditional order `_triggered_at` flows as `detected_at` for triggered signals | [ ] |
| 3.64 | Telegram `detected_at` set in `listener.py` at parse time (not after queue wait) | [ ] |
| 3.65 | `save_pending_order_metadata()` accepts explicit `order_submitted_at` parameter | [ ] |
| 3.66 | Negative latency guard: `latency_parse_ms < 0` → set to NULL | [ ] |
| 3.67 | Negative latency guard: `latency_broker_ms < 0` → set to NULL | [ ] |
| 3.68 | Negative latency guard: `latency_total_ms < 0` → set to NULL | [ ] |
| 3.69 | `/api/latency/stats` returns summary (avg, p50, p95), by-broker breakdown, recent trades | [ ] |
| 3.70 | Latency badges color-coded: green (<1.5s), yellow (1.5-3s), red (>3s) | [ ] |
| 3.71 | Closed Trades tab shows latency column with color badges | [ ] |
| 3.72 | P&L Tracker position cards show latency column | [ ] |

**API Endpoints:**
- [ ] `GET /api/execution-pnl` — execution P&L data (includes `latency.parse_ms`, `latency.broker_ms`, `latency.total_ms`)
- [ ] `GET /api/execution-pnl/filters` — filter options
- [ ] `GET /api/execution-lots` — broker fill lots
- [ ] `GET /api/signal-summary` — signal summary
- [ ] `GET /api/signal-summary/<lot_id>/executions` — executions per lot
- [ ] `GET /api/latency/stats` — latency statistics (avg/p50/p95, by-broker, recent)
- [ ] `GET /api/pnl/detailed` — includes `latency_ms`, `latency_parse_ms`, `latency_broker_ms` per position
- [ ] `PUT /api/channels/<id>` — saves all risk management fields

**Database Tables:** `signal_lots`, `lot_closures`, `execution_lots`, `execution_closures`, `pending_order_metadata`, `filled_orders`

**Risk fields stored in:** `channels` table (see Section 2 database columns)

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
| 4.11 | Latency column in position cards (between Avg Return and Status) | [ ] |
| 4.12 | Latency badge colors match thresholds (green/yellow/red) | [ ] |
| 4.13 | Position card grid layout — all columns in single row (8-column grid) | [ ] |
| 4.14 | Aggregate footer row aligns with 8-column header grid | [ ] |
| 4.15 | Hold Time column shows formatted duration per position (`formatHoldTime()` in pnl_tracker.html) | [ ] |
| 4.16 | Hold Time color coding: purple < 1h, cyan < 1d, orange < 7d, green >= 7d | [ ] |
| 4.17 | Direction breakdown bar renders below summary stats (`#directionBreakdown` div) | [ ] |
| 4.18 | Direction breakdown computes from `pos.asset_type` + `pos.call_put` client-side in `updateSummaryStats()` | [ ] |
| 4.19 | Stocks direction: `asset_type='stock'` → 📈 Stocks with WR%, W/L, PnL | [ ] |
| 4.20 | Calls direction: `asset_type='option' && call_put='C'` → 🟢 Calls with WR%, W/L, PnL | [ ] |
| 4.21 | Puts direction: `asset_type='option' && call_put='P'` → 🔴 Puts with WR%, W/L, PnL | [ ] |
| 4.22 | Direction bar hidden when no closed positions exist | [ ] |
| 4.23 | Only categories with trades are shown (no empty "Calls: —" pills) | [ ] |
| 4.24 | `close_lot()` rejects `close_price <= 0` — guard at `database.py:4942` prevents $0 exit creating -100% PnL | [ ] |
| 4.25 | `_build_stc_signal()` returns None when `position.current_price <= 0` — guard at `position_monitor.py:~7459` | [ ] |

**API Endpoints:**
- [ ] `GET /api/pnl/detailed` — detailed P&L (includes `asset_type`, `call_put`, latency fields)
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
| 5.15 | "Closed Trades" tab loads from `/api/execution-pnl` (not order history) | [ ] |
| 5.16 | Closed Trades table columns: Symbol, Broker, Qty, Entry, Exit, P&L, P&L%, Latency, Exit Reason, Filled | [ ] |
| 5.17 | Closed Trades latency badges color-coded (green/yellow/red) | [ ] |
| 5.18 | Closed Trades exit reason badges color-coded (PT=green, STOP=red, TRAIL=yellow, MANUAL=grey) | [ ] |

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
| 7.10 | Avg Hold Time stat card shows correct duration (6th card, id `statHoldTime`) | [ ] |
| 7.11 | Hold time precision — `avg_hold_days` rounded to 4 decimals (not 1) for accurate h:m display | [ ] |
| 7.12 | Trader style label: Scalper (< 1h), Day Trader (< 1d), Swing (< 14d), Position (>= 14d) | [ ] |
| 7.13 | 6-column stat grid layout (`repeat(6, 1fr)`) accommodates Hold Time card | [ ] |
| 7.14 | Direction breakdown cards row renders below stats (`#directionBreakdownRow` div) | [ ] |
| 7.15 | Direction breakdown sourced from `performance_analytics.get_performance_v2()` → `direction_breakdown` dict | [ ] |
| 7.16 | Each direction card shows: icon, label, trade count, WR% in accent color, PnL, win/loss bar | [ ] |
| 7.17 | Stocks card: 📈 cyan `#00d4ff` with progress bar at WR% width | [ ] |
| 7.18 | Calls card: 🟢 green `#30D158` with progress bar at WR% width | [ ] |
| 7.19 | Puts card: 🔴 red `#FF453A` with progress bar at WR% width | [ ] |
| 7.20 | Direction breakdown hidden when no closed positions exist | [ ] |
| 7.21 | Direction derived from `sl.asset_type` + `sl.call_put` in SQL query (`performance_analytics.py:172`) | [ ] |
| 7.22 | Direction aggregation per `trade_agg` entry — handles multi-closure lots correctly | [ ] |

**API Endpoints:**
- [ ] `GET /api/performance-v2` — enhanced analytics (sections param, includes `direction_breakdown`)
- [ ] `GET /api/performance` — legacy performance (includes `direction_breakdown`)
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
| 8.7 | Channel tab loads data — query joins `channels → signal_lots (via channel_id) → lot_closures` (not through signals) | [ ] |
| 8.8 | User tab loads data — query joins `signal_lots → lot_closures → channels` (via channel_id, not signal_id) | [ ] |
| 8.9 | Channel `signal_lots.channel_id` is TEXT — join uses `CAST(sl.channel_id AS INTEGER) = c.id` | [ ] |
| 8.10 | Market filter uses `c.market` (channels table) not `s.market` (signals table) — signals join removed | [ ] |
| 8.11 | Avg Hold column in channel table — sortable header `avg_holding_days`, uses `formatHoldTime()` | [ ] |
| 8.12 | Avg Hold column in user table — sortable header, sort case in user switch at line ~443 | [ ] |
| 8.13 | Hold time precision — `ROUND(AVG(lc.holding_days), 4)` in channel query, `round(..., 4)` in Python | [ ] |
| 8.14 | `formatHoldTime()` defined in leaderboard.html — same function as pnl_tracker.html | [ ] |
| 8.15 | Win% by Type column in channel table — shows `formatDirectionBreakdown(channel.direction_breakdown)` | [ ] |
| 8.16 | Win% by Type column in user table — shows `formatDirectionBreakdown(user.direction_breakdown)` | [ ] |
| 8.17 | Direction breakdown pills: 📈 Stocks cyan, 🟢 Calls green, 🔴 Puts red with WR% | [ ] |
| 8.18 | Direction pill tooltips show full detail: "stocks: 7W/3L $15.04" | [ ] |
| 8.19 | Only categories with trades render (no empty pills for missing directions) | [ ] |
| 8.20 | Direction breakdown query grouped by `channel_id, direction` — single query for all channels | [ ] |
| 8.21 | User direction breakdown query grouped by `author_name, direction` — single query for all users | [ ] |
| 8.22 | Time period filter (`all`, `year`, `month`, `week`, `today`, `custom`) works on channel tab | [ ] |
| 8.23 | Time period filter works on user tab | [ ] |
| 8.24 | Custom date range picker filters by `lc.closed_at` between start/end dates | [ ] |
| 8.25 | Top Performer banner shows correct #1 channel/user based on TQS sort | [ ] |
| 8.26 | Top/Bottom 3 performers cards update when switching channel ↔ user view | [ ] |
| 8.27 | `formatHoldTime()` renders: `< 1m` purple, `Nm` purple, `Nh Nm` cyan, `Nd Nh` orange, `Nd` green | [ ] |
| 8.28 | Enhanced leaderboard join fixed — uses `channels → signal_lots (via channel_id)` not through signals | [ ] |

**API Endpoints:**
- [ ] `GET /api/leaderboard` — channel leaderboard (includes `direction_breakdown` per channel)
- [ ] `GET /api/leaderboard/users` — user rankings (includes `direction_breakdown` per user)
- [ ] `GET /api/leaderboard/enhanced` — enhanced metrics (join fixed to use channel_id)
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

The Settings page has **28 distinct sections** organized as collapsible cards.

#### 13a. Setup Wizard

| # | Test | Status |
|---|------|--------|
| 13.1 | Launch Setup Wizard button | [ ] |
| 13.2 | Wizard status display | [ ] |

- [ ] `POST /api/wizard/launch` — launch wizard
- [ ] `GET /api/wizard/status` — wizard status

#### 13b. Debug Report

| # | Test | Status |
|---|------|--------|
| 13.3 | Open Debug Report Tool modal | [ ] |
| 13.4 | Reference number generation | [ ] |
| 13.5 | Email status display | [ ] |

- [ ] `POST /api/debug-report/submit` — submit report
- [ ] `GET /api/debug-report/history` — report history

#### 13c. License Status (on Settings page)

| # | Test | Status |
|---|------|--------|
| 13.6 | License key display | [ ] |
| 13.7 | Days remaining display | [ ] |
| 13.8 | Status badge (Active/Expired) | [ ] |

#### 13d. Discord Credentials

| # | Test | Status |
|---|------|--------|
| 13.9 | Discord token save/load (password field) | [ ] |
| 13.10 | Discord connection status badge | [ ] |
| 13.11 | Connect/test button | [ ] |

- [ ] `GET /api/brokers/credentials/discord` — get
- [ ] `POST /api/brokers/credentials/discord` — save
- [ ] `POST /api/brokers/connect/discord` — test

#### 13e. Alpaca Paper Trading

| # | Test | Status |
|---|------|--------|
| 13.12 | API Key (PKXXXXXXXX format) | [ ] |
| 13.13 | Secret Key | [ ] |
| 13.14 | Connection status badge | [ ] |

- [ ] `GET /api/brokers/credentials/alpaca` (paper_mode: true)
- [ ] `POST /api/brokers/credentials/alpaca` (paper_mode: true)
- [ ] `POST /api/brokers/connect/alpaca_paper` — test

#### 13f. Alpaca Live Trading

| # | Test | Status |
|---|------|--------|
| 13.15 | Live API Key (AKXXXXXXXX format) | [ ] |
| 13.16 | Live Secret Key | [ ] |
| 13.17 | Connection status badge | [ ] |

- [ ] `POST /api/brokers/credentials/alpaca` (paper_mode: false)
- [ ] `POST /api/brokers/connect/alpaca_live` — test

#### 13g. TastyTrade Paper Trading

| # | Test | Status |
|---|------|--------|
| 13.18 | OAuth2 Client Secret | [ ] |
| 13.19 | OAuth2 Refresh Token | [ ] |
| 13.20 | Username (legacy/deprecated) | [ ] |
| 13.21 | Password (legacy/deprecated) | [ ] |
| 13.22 | Account selector dropdown (auto/specific) | [ ] |
| 13.23 | Connection status badge | [ ] |

- [ ] `GET /api/brokers/credentials/tastytrade` — get
- [ ] `POST /api/brokers/credentials/tastytrade` — save

#### 13h. TastyTrade Live Trading

| # | Test | Status |
|---|------|--------|
| 13.24 | OAuth2 Client Secret (live) | [ ] |
| 13.25 | OAuth2 Refresh Token (live) | [ ] |
| 13.26 | Account selector (live) | [ ] |
| 13.27 | Connection status badge | [ ] |
| 13.28 | Clear credentials button | [ ] |

- [ ] `POST /api/brokers/credentials/tastytrade/clear` — clear

#### 13i. Robinhood (Live Only)

| # | Test | Status |
|---|------|--------|
| 13.29 | Email/Username | [ ] |
| 13.30 | Password | [ ] |
| 13.31 | 2FA TOTP Secret (optional) | [ ] |
| 13.32 | Connection status badge | [ ] |

- [ ] `GET /api/settings/robinhood` — get
- [ ] `POST /api/settings/robinhood` — save
- [ ] `POST /api/brokers/connect/robinhood` — test

#### 13j. Trading 212

| # | Test | Status |
|---|------|--------|
| 13.33 | API Key | [ ] |
| 13.34 | API Secret | [ ] |
| 13.35 | Environment dropdown (demo / live) | [ ] |
| 13.36 | Connection status badge | [ ] |

- [ ] `GET /api/brokers/credentials/trading212` — get
- [ ] `POST /api/brokers/credentials/trading212` — save
- [ ] `POST /api/brokers/connect/trading212` — test

#### 13k. Charles Schwab (OAuth)

| # | Test | Status |
|---|------|--------|
| 13.37 | Client ID (App Key) | [ ] |
| 13.38 | Client Secret | [ ] |
| 13.39 | Redirect URI | [ ] |
| 13.40 | Dry Run Mode toggle (log without executing) | [ ] |
| 13.41 | Connect with Schwab button → OAuth flow | [ ] |
| 13.42 | OAuth status polling | [ ] |
| 13.43 | Token expiry display | [ ] |
| 13.44 | Refresh Token button | [ ] |
| 13.45 | Disconnect button | [ ] |
| 13.46 | Manual Code entry (local deployments) | [ ] |

- [ ] `GET /api/brokers/SCHWAB/credentials` — get
- [ ] `POST /api/brokers/SCHWAB/credentials` — save
- [ ] `GET /schwab/auth-url` — OAuth URL
- [ ] `GET /schwab/callback` — OAuth callback
- [ ] `GET /api/schwab/callback` — OAuth callback (alt)
- [ ] `GET /schwab/oauth-status` — poll completion
- [ ] `POST /schwab/oauth-reset` — reset flow
- [ ] `GET /schwab/status` — connection status
- [ ] `POST /schwab/refresh` — token refresh
- [ ] `POST /schwab/disconnect` — disconnect
- [ ] `POST /schwab/manual-code` — manual code

#### 13l. Webull

| # | Test | Status |
|---|------|--------|
| 13.47 | Token-Only Mode toggle (bypass captcha) | [ ] |
| 13.48 | Email | [ ] |
| 13.49 | Password | [ ] |
| 13.50 | Trade PIN (6 digits, required) | [ ] |
| 13.51 | Device ID (DID, optional) | [ ] |
| 13.52 | Access Token (auto-saved) | [ ] |
| 13.53 | Refresh Token (default: "dummy") | [ ] |
| 13.54 | Account Type radio (Margin / Cash / IRA) | [ ] |
| 13.55 | Clear Webull Tokens button | [ ] |
| 13.56 | Connection status badge | [ ] |

- [ ] `GET /api/brokers/credentials/webull` — get
- [ ] `POST /api/brokers/credentials/webull` — save
- [ ] `POST /api/brokers/credentials/webull/clear-tokens` — clear
- [ ] `POST /api/brokers/connect/webull` — test
- [ ] `POST /api/webull/auth/login` — login
- [ ] `POST /api/webull/auth/request-mfa` — MFA
- [ ] `POST /api/webull/auth/security-question` — security question
- [ ] `POST /api/webull/auth/session-login` — session login

#### 13m. Interactive Brokers (IBKR)

| # | Test | Status |
|---|------|--------|
| 13.57 | TWS/Gateway Host (default: 127.0.0.1) | [ ] |
| 13.58 | Paper Port (default: 7497) | [ ] |
| 13.59 | Live Port (default: 7496) | [ ] |
| 13.60 | Client ID (default: 1) | [ ] |
| 13.61 | Paper Trading Mode toggle | [ ] |
| 13.62 | Connection status badge | [ ] |

- [ ] `GET /api/brokers/credentials/ibkr` — get
- [ ] `POST /api/brokers/credentials/ibkr` — save
- [ ] `POST /api/brokers/connect/ibkr` — test

#### 13n. Clear Stale Trades

| # | Test | Status |
|---|------|--------|
| 13.63 | Per-broker clear buttons | [ ] |
| 13.64 | Stale trade count display | [ ] |

- [ ] `POST /api/trades/clear-stale` — clear
- [ ] `GET /api/trades/stale-count` — count

#### 13o. Trade Notifications (Discord Webhook)

| # | Test | Status |
|---|------|--------|
| 13.65 | Enable notifications toggle | [ ] |
| 13.66 | Discord Webhook URL | [ ] |
| 13.67 | Discord Channel ID (optional) | [ ] |
| 13.68 | Test Webhook button | [ ] |

- [ ] `GET /api/settings/discord_notifications` — get
- [ ] `POST /api/settings/discord_notifications` — save
- [ ] `POST /api/settings/test_webhook` — test

#### 13p. AI & Market Data APIs

| # | Test | Status |
|---|------|--------|
| 13.69 | AI Provider dropdown (replit_ai / openai / disabled) | [ ] |
| 13.70 | OpenAI API Key (shown when openai selected) | [ ] |
| 13.71 | Alpha Vantage Key (option flow scanning) | [ ] |
| 13.72 | Finnhub API Key (market news & data) | [ ] |

- [ ] `GET /api/settings/api_keys` — get
- [ ] `POST /api/settings/api_keys` — save

#### 13q. Slippage Protection

| # | Test | Status |
|---|------|--------|
| 13.73 | Enable Protection toggle | [ ] |
| 13.74 | Maximum Threshold % (range 1-50, step 0.5, default 10) | [ ] |

- [ ] `GET /api/settings/slippage` — get
- [ ] `POST /api/settings/slippage` — save

**Database:** `slippage_settings` (`enabled`, `threshold_percent`)

#### 13r. Risk Management (Global Defaults)

| # | Test | Status |
|---|------|--------|
| 13.75 | Enable Monitoring toggle | [ ] |
| 13.76 | Profit Target % (range 0-100, step 5, default 20) | [ ] |
| 13.77 | Stop Loss % (range 0-100, step 5, default 10) | [ ] |
| 13.78 | Trailing Stop % (range 0-50, step 1, default 5) | [ ] |

- [ ] `GET /api/settings/risk_management` — get
- [ ] `POST /api/settings/risk_management` — save

**Database:** `risk_management_settings` (`enabled`, `profit_target_percent`, `stop_loss_percent`, `trailing_stop_percent`)

#### 13s. AI Analysis

| # | Test | Status |
|---|------|--------|
| 13.79 | Enable AI Analysis toggle | [ ] |
| 13.80 | AI Model dropdown (gpt-4o-mini / gpt-4o) | [ ] |
| 13.81 | Sentiment Analysis toggle | [ ] |

- [ ] `GET /api/settings/ai_analysis` — get
- [ ] `POST /api/settings/ai_analysis` — save

**Database:** `ai_settings` (`enabled`, `model`, `sentiment_enabled`)

#### 13t. Trading Limits (Position Sizing)

| # | Test | Status |
|---|------|--------|
| 13.82 | Enable Max Position Size toggle | [ ] |
| 13.83 | Max Position Size $ (range 100-10000, step 100, default 600) | [ ] |
| 13.84 | Global Default Quantity (when max-position disabled) | [ ] |
| 13.85 | EMA Risk Global Enabled toggle | [ ] |

- [ ] `GET /api/settings/trading` — get
- [ ] `POST /api/settings/trading` — save

**Database:** `trading_settings` (`max_position_size`, `max_position_size_enabled`, `global_default_quantity`, `ema_risk_global_enabled`)

#### 13u. Advanced Settings (Debug)

| # | Test | Status |
|---|------|--------|
| 13.86 | Debug Mode toggle (ON/OFF) | [ ] |

- [ ] `GET /api/settings/debug` — get
- [ ] `POST /api/settings/debug` — save (`{ enabled: bool }`)

#### 13v. Discord Bot Settings (Collapsible)

| # | Test | Status |
|---|------|--------|
| 13.87 | Allow Self Messages toggle | [ ] |
| 13.88 | Discovery Mode toggle | [ ] |
| 13.89 | Option Signal Pattern regex | [ ] |
| 13.90 | Stock Signal Pattern regex | [ ] |
| 13.91 | Allowed Author IDs (comma-separated) | [ ] |
| 13.92 | Allowed Guild IDs (comma-separated) | [ ] |
| 13.93 | Reset Patterns to Default button | [ ] |

- [ ] `GET /api/settings/discord` — get
- [ ] `POST /api/settings/discord` — save

**Database:** `discord_settings` (`allow_self_messages`, `discovery_mode`, `option_pattern`, `stock_pattern`, `allowed_author_ids`, `allowed_guild_ids`)

#### 13w. Trade Notifications (Channel Settings)

| # | Test | Status |
|---|------|--------|
| 13.94 | Enable Discord Notifications toggle | [ ] |
| 13.95 | Notification Channel ID | [ ] |

- [ ] `GET /api/notifications/settings` — get
- [ ] `POST /api/notifications/settings` — save

#### 13x. Background Services

| # | Test | Status |
|---|------|--------|
| 13.96 | Broker Sync Service toggle | [ ] |
| 13.97 | Risk Monitor Service toggle | [ ] |
| 13.98 | Auto-Import External Positions toggle | [ ] |

- [ ] `GET /api/settings/background_services` — get
- [ ] `POST /api/settings/background_services` — save

#### 13y. Trade Monitor (Broker Sync)

| # | Test | Status |
|---|------|--------|
| 13.99 | Enable Trade Monitor toggle | [ ] |
| 13.100 | Target Webhook Channel dropdown | [ ] |
| 13.101 | Poll Interval seconds (range 5-300, default 10) | [ ] |
| 13.102 | Include Stock Trades toggle | [ ] |
| 13.103 | Include Option Trades toggle | [ ] |
| 13.104 | Post BTO Signals toggle | [ ] |
| 13.105 | Post STC Signals toggle | [ ] |
| 13.106 | Test Mode toggle (include pending orders) | [ ] |

- [ ] `GET /api/settings/trade_monitor` — get
- [ ] `POST /api/settings/trade_monitor` — save

**Database:** `trade_monitor_settings` (`enabled`, `poll_interval_seconds`, `target_webhook_channel_id`, `include_stocks`, `include_options`, `post_bto_signals`, `post_stc_signals`)

#### 13z. Conditional Orders (Global)

| # | Test | Status |
|---|------|--------|
| 13.107 | Enable Conditional Order Service toggle | [ ] |
| 13.108 | Default Order Expiry dropdown (end_of_day / 1_hour / 4_hours / 1_day) | [ ] |
| 13.109 | Global Trigger Offset Mode (percent / dollar) | [ ] |
| 13.110 | Trigger Offset Value (range -100 to 100) | [ ] |
| 13.111 | Entry Price Offset % (range -10 to 10) | [ ] |
| 13.112 | Auto-Execute When Triggered toggle | [ ] |

- [ ] `GET /api/settings/conditional_orders` — get
- [ ] `POST /api/settings/conditional_orders` — save

#### 13aa. Global Risk Management

| # | Test | Status |
|---|------|--------|
| 13.113 | Exit Strategy Mode dropdown (signal/risk/hybrid) | [ ] |
| 13.114 | Auto SL/PT Updates toggle (`signal_update_automation`) | [ ] |
| 13.115 | Risk Check Interval seconds (range 0.2-60, default 1) | [ ] |
| 13.116 | Max Open Positions (0 = unlimited) | [ ] |
| 13.117 | Daily Loss Limit $ (0 = no limit) | [ ] |
| 13.118 | Circuit Breaker enable | [ ] |

- [ ] `GET /api/settings/global-risk` — get
- [ ] `POST /api/settings/global-risk` — save
- [ ] `PUT /api/settings/global-risk` — update

**Database:** `global_risk_settings` (`exit_strategy_mode`, `enable_signal_update_automation`, `risk_check_interval_seconds`, `global_max_positions`, `global_daily_loss_limit`, `enable_circuit_breaker`)

#### 13ab. Daily P&L Limits

| # | Test | Status |
|---|------|--------|
| 13.119 | Enable Daily P&L Limits toggle | [ ] |
| 13.120 | Max Daily Loss $ (step 50) | [ ] |
| 13.121 | Max Daily Loss % (range 0-100, step 0.5) | [ ] |
| 13.122 | Max Daily Profit $ (step 50) | [ ] |
| 13.123 | Max Daily Profit % (range 0-100, step 0.5) | [ ] |
| 13.124 | Max Daily Trades Per Broker (0 = unlimited) | [ ] |
| 13.125 | Warning Threshold % (range 0-100, step 5, default 80) | [ ] |
| 13.126 | Daily Reset Time dropdown (09:30 / 00:00 / 04:00 ET) | [ ] |

**Database:** `global_risk_settings` (`daily_pnl_limit_enabled`, `daily_loss_limit_dollar`, `daily_loss_limit_pct`, `daily_profit_limit`, `daily_profit_limit_pct`, `daily_pnl_warning_pct`, `daily_pnl_reset_time`), `daily_pnl_state` (per-broker state)

#### 13ac. Telegram Settings

| # | Test | Status |
|---|------|--------|
| 13.127 | Telegram enable toggle | [ ] |
| 13.128 | API ID | [ ] |
| 13.129 | API Hash | [ ] |
| 13.130 | Phone number | [ ] |
| 13.131 | Test connection | [ ] |
| 13.132 | Verify code / 2FA | [ ] |
| 13.133 | Telegram channel CRUD | [ ] |

- [ ] `GET /api/settings/telegram` — get
- [ ] `POST /api/settings/telegram` — save
- [ ] `POST /api/telegram/test-connection` — test
- [ ] `POST /api/telegram/verify-code` — verify
- [ ] `POST /api/telegram/verify-2fa` — 2FA
- [ ] Telegram channel CRUD (GET/POST/PUT/DELETE `/api/telegram/channels`)

**Database:** `telegram_settings` (`api_id`, `api_hash`, `phone_number`, `session_string`, `session_status`)

#### 13ad. Webhook Settings

| # | Test | Status |
|---|------|--------|
| 13.134 | Webhook config save/load | [ ] |
| 13.135 | Webhook test | [ ] |
| 13.136 | Webhook channel CRUD | [ ] |
| 13.137 | Webhook channel test | [ ] |
| 13.138 | BTO/STC post via webhook | [ ] |

- [ ] `GET /api/webhook/config` + `POST`
- [ ] `POST /api/webhook/test`
- [ ] Webhook channel CRUD (GET/POST/PUT/DELETE `/api/webhook/channels`)
- [ ] `POST /api/webhook/post_bto` / `POST /api/webhook/post_stc`
- [ ] `GET /api/webhook/positions` — positions
- [ ] `POST /api/webhook/find_position` — find position

#### 13ae. Broker Common Operations

- [ ] `POST /api/brokers/connect/<id>` — connect
- [ ] `POST /api/brokers/disconnect/<id>` — disconnect
- [ ] `POST /api/brokers/reload` — reload all
- [ ] `GET /api/brokers/grouped` — by country
- [ ] `GET /api/brokers/<name>/profile` — profile
- [ ] `POST /api/brokers/<name>/test` — test
- [ ] `POST /api/brokers/<name>/reconnect` — reconnect
- [ ] `GET /api/brokers/extended-hours` — extended hours
- [ ] `GET /api/broker/available` — available
- [ ] `GET /google_login` — Google OAuth
- [ ] `GET /google_login/callback` — Google callback

**All Settings Database Tables:** `settings`, `trading_settings`, `slippage_settings`, `risk_management_settings`, `ai_settings`, `discord_settings`, `telegram_settings`, `global_risk_settings`, `daily_pnl_state`, `trade_monitor_settings`, `conditional_orders`, `config` (encrypted), `broker_credentials`, `broker_profiles`, `broker_sync_state`, `service_registry`, `broker_limits`, `user_sizing_settings`, `analyst_portfolios`, `email_config`

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
| 17.12 | Broker bracket orders — standalone SL + PT placement | [ ] |
| 17.13 | Per-channel vs global risk settings | [ ] |
| 17.14 | Risk cache invalidation on setting change | [ ] |
| 17.15 | Circuit breaker (daily loss limit) | [ ] |
| 17.16 | Daily P&L limit enforcement | [ ] |
| 17.17 | Escalation only mode | [ ] |

#### OCO Bracket Orders (Schwab) [GATE]

| # | Test | Status |
|---|------|--------|
| 17.18 | OCO initial bracket — tries native OCO for stocks with limit trim mode | [ ] |
| 17.19 | OCO skipped when `trim_order_mode='market'` even with SL+PT configured | [ ] |
| 17.20 | OCO fallback — falls back to separate SL+PT when OCO fails or non-stock | [ ] |
| 17.21 | OCO suppression — software sell suppressed when OCO manages the active PT tier | [ ] |
| 17.22 | OCO PT cascade — old OCO cancelled, new OCO placed with current SL + next PT | [ ] |
| 17.23 | OCO stop sync — OCO cancelled and re-placed with updated SL price + same PT | [ ] |
| 17.24 | OCO-aware cancel — OCO added to cancel list, no double-cancel when OCO=PT ID | [ ] |
| 17.25 | OCO cache fields cleared together (`broker_oco_order_id`, `_sl_price`, `_pt_price`, `_qty`) | [ ] |
| 17.26 | Stale `broker_stop_order_id` cleared when it matches old OCO ID (cascade + stop sync) | [ ] |
| 17.27 | OCO initial placement aliases `broker_stop_order_id` = `broker_pt_order_id` = OCO ID | [ ] |
| 17.28 | Standalone stop qty = total qty - OCO qty; skip if OCO covers all shares | [ ] |
| 17.29 | Non-OCO fallback preserves `_skip_cancel_check=True` on all SL/PT placements | [ ] |
| 17.30 | OCO fields reset on startup in position_cache.py `load()` (all 4 fields) | [ ] |
| 17.31 | OCO fields serialized in `to_dict()` / deserialized in `from_dict()` | [ ] |
| 17.32 | Bracket attempt limit — gives up after 3 retries (`_bracket_attempt_count`) | [ ] |

#### Partial Exit & Deferred SL Re-place [GATE]

| # | Test | Status |
|---|------|--------|
| 17.33 | Partial exit cancels ALL brackets (SL + PT + OCO) | [ ] |
| 17.34 | `_need_replace_stop` flag set on partial exit | [ ] |
| 17.35 | Deferred SL re-place fires after 15s delay via `_pending_broker_sl_replace` | [ ] |
| 17.36 | Field names match: writer `_pending_sl_replace_price` / `_sl_cancelled_at` ↔ consumer | [ ] |
| 17.37 | PT fill sets `_pending_broker_sl_replace` for deferred SL re-place (Group 9) | [ ] |

#### Wide Spread Guard [GATE]

| # | Test | Status |
|---|------|--------|
| 17.38 | SL/trailing/giveback exit: spread ≥50% → use last price instead of stale bid | [ ] |
| 17.39 | SL exit: spread <50% → normal bid pricing | [ ] |
| 17.40 | PT exit: spread ≥50% → use last price (existing logic) | [ ] |

#### Position Monitor Diagnostics

| # | Test | Status |
|---|------|--------|
| 17.41 | Stuck price threshold = 2 (not 3) | [ ] |
| 17.42 | Tick eval logging every 100 ticks with max latency, slow tick >200ms logged | [ ] |
| 17.43 | Cycle timing logged every 50 cycles; logged at >500ms, tagged SLOW at >1000ms | [ ] |
| 17.44 | Heartbeat interval 150s with stream status, cycle/tick stats | [ ] |
| 17.45 | Position status logging per risk eval cycle with P&L%, SL/PT prices, SL distance | [ ] |
| 17.46 | Stale bracket reset: `broker_orders_placed=true` + no order IDs → reset | [ ] |
| 17.47 | Scale-in detection: qty increase → cancel old brackets + clear OCO fields, re-place | [ ] |
| 17.48 | Multi-broker streaming check: Schwab, IBKR, Tastytrade hub standby detection | [ ] |

#### Position Cache Safety

| # | Test | Status |
|---|------|--------|
| 17.49 | Entry-price corruption guard (`_guard_against_corrupt_risk_levels`) clears invalid SL/PT | [ ] |
| 17.50 | Flip-flop entry-price detection locks price after oscillation detected | [ ] |

#### Webull SL Retry

| # | Test | Status |
|---|------|--------|
| 17.51 | Webull SL uses retry counter (`_webull_stp_fail_count`) not permanent flag | [ ] |
| 17.52 | Webull SL retries on next cycle instead of permanently disabling | [ ] |

#### HTTP Pool Recovery (Schwab Broker) [GATE]

| # | Test | Status |
|---|------|--------|
| 17.53 | `_create_http_client()` returns httpx.AsyncClient with limits 15/8 | [ ] |
| 17.54 | `_reset_http_client()` closes old client, creates new, logs reason | [ ] |
| 17.55 | `_make_request()` catches `PoolTimeout`/`ConnectTimeout`/`ReadTimeout`, resets and retries once | [ ] |
| 17.56 | `TimeoutError` resets client but re-raises (no silent swallow) | [ ] |
| 17.57 | Error logging uses `type(e).__name__: {e}` format in get_account_info, get_positions | [ ] |

#### Lot Closure Fill Reconciliation [GATE]

| # | Test | Status |
|---|------|--------|
| 17.58 | `reconcile_trade_fill_price()` updates lot_closures with broker fill price | [ ] |
| 17.59 | Lot closure PNL recalculated after fill reconciliation | [ ] |
| 17.60 | Options use 100x multiplier in lot closure PNL calc | [ ] |
| 17.61 | Lot closure reconcile error is non-blocking (caught, logged, doesn't abort) | [ ] |

#### Broker Fill Sync — All Brokers [GATE]

| # | Test | Status |
|---|------|--------|
| 17.63a | Webull fills synced via `get_order_history()` | [ ] |
| 17.63b | Alpaca fills synced via `get_filled_orders()` or `get_orders(status='closed')` | [ ] |
| 17.63c | Schwab fills synced via `get_order_history()` | [ ] |
| 17.63d | Trading212 fills synced via `get_order_history()` (status=FILLED filter) | [ ] |
| 17.63e | Tastytrade fills synced via `get_filled_orders()` | [ ] |
| 17.63f | IBKR fills synced via `ib.trades()` — iterates filled trades with orderStatus.status='Filled' | [ ] |
| 17.63g | IBKR fill extracts: orderId, symbol, filled qty, avgFillPrice, fills[-1].time | [ ] |
| 17.63h | IBKR options extract expiry (YYYYMMDD→YYYY-MM-DD), strike, right | [ ] |
| 17.63i | IBKR fill skipped when `filled_qty <= 0` or `avg_price <= 0` | [ ] |
| 17.63j | STC fills update `pending_order_metadata` status to FILLED | [ ] |
| 17.63k | STC fills hydrate `exit_fill_price` on lot_closures via `_record_execution_closure()` | [ ] |
| 17.63l | BTO fills create `execution_lots` via `_record_execution_lot()` | [ ] |
| 17.63m | Fill deduplication via `filled_orders` table UNIQUE constraint | [ ] |
| 17.63n | Fill sync runs every 1 cycle (pending trades) or every 5 cycles (no pending) | [ ] |

#### Exit Price Safety Guards [GATE]

| # | Test | Status |
|---|------|--------|
| 17.63o | `close_lot()` rejects `close_price <= 0` (returns None, does not create closure) | [ ] |
| 17.63p | `close_lot()` rejects `close_price = None` (returns None) | [ ] |
| 17.63q | `_build_stc_signal()` returns None when `position.current_price <= 0` | [ ] |
| 17.63r | `_execute_exit()` handles `_build_stc_signal()` returning None (resets closing state) | [ ] |
| 17.63s | Risk engine retries on next cycle when price unavailable (no permanent abort) | [ ] |
| 17.63t | Lot P&L never shows -100% from $0 exit price (guard prevents it) | [ ] |

#### Position Cache Atomic Save [GATE]

| # | Test | Status |
|---|------|--------|
| 17.62 | Cache save uses `json.dump` → `.tmp` → `os.replace()` (no partial writes) | [ ] |
| 17.63 | Thread-safe: `_cache_lock` scoped to data snapshot only, not I/O | [ ] |

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
| 18.10 | Default settings: `conditional_order_auto_execute=true` | [ ] |
| 18.11 | Default settings: `conditional_order_trigger_offset_mode=percent` | [ ] |
| 18.12 | Default settings: `conditional_order_trigger_offset_percent=0` | [ ] |
| 18.13 | Default settings: `conditional_order_entry_price_offset_percent=0` | [ ] |
| 18.14 | Default settings: `conditional_order_default_expiry=end_of_day` | [ ] |

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
- [ ] `GET /api/system/consistency-check` — consistency
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

**Expected: 82+ tables across 4 databases** (as of v9.2.5)

| Database | Tables | Purpose |
|----------|--------|---------|
| `bot_data.db` | 72 | Main trading database |
| `agent_data.db` | 6 | Agent Studio orchestration |
| `india_bot.db` | 9 | India market trading |
| `license_server.db` | 5 | License management |

**Tables in bot_data.db not listed elsewhere (verify exist):**
`notification_log`, `partial_exits`, `position_ledger`, `schwab_token_metadata`, `webhook_channels`, `webhook_closures`, `webhook_config`, `webhook_positions`, `broker_notifications`

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

**Last Updated**: 2026-05-03
**Version**: 4.3.0
**Total Sections**: 35 main + 42 sub-sections
**Total Test Cases**: 589 field-level checks
**Total API Endpoint Checks**: 374 (all verified against running app)
**Total Database Tables**: 82+ (72 in bot_data.db, 6 agent, 9 india, 5 license)
**Validation Script**: `scripts/validate_qa_playbook.py` — run to verify all routes
