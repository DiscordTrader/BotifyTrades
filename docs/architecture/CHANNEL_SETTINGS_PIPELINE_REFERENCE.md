# Channel Settings Pipeline Reference

**Date**: 2026-06-20
**Purpose**: Definitive reference for validating all channel settings flow correctly from UI → DB → execution → broker API. Use this document when adding new brokers, modifying settings, or debugging execution issues.
**Coverage**: 2 UI paths × 6 tabs total × 8 brokers

---

## ⚠️ TWO SEPARATE UIs — Different Paths, No Conflict

```
PATH 1: Trading → Channels → ⚙️ Settings button
  File: gui_app/templates/channels.html
  Modal: channelSettingsModal
  Tabs:
    ├── Sizing tab (buildSizingTab)       → Position Size, Default Qty, Balance Mode
    ├── Risk Controls tab (buildRiskControlsTab) → Signal Handling, Slippage, Price Controls, NDX→QQQ
    ├── Order Types tab (buildOrderTypesTab)     → Entry/Trim/SL order mode + offsets
    └── Conditional tab (buildConditionalTab)    → Enable, Timeouts, Trigger Offset, Breakout Reset

PATH 2: Trading → Execution → Channel Card → 🛡️ Risk Management
  File: gui_app/static/js/channels.js
  Section: Inline expandable row (risk-management-row-{id})
  Tabs:
    ├── Targets & SL tab    → SL%, PT1-4%, Trailing, Leave Runner, Exit Strategy Mode
    └── Advanced tab         → Broker Bracket (OCO), Dynamic SL, EMA, Giveback, Early Trailing

Both paths write to DIFFERENT columns on the SAME channels table row.
Zero conflict — completely disjoint field sets.
```
---

## Architecture Overview

```
UI (channels.html / channels.js)
  │
  ├── PUT /api/channels/{id}  ──►  channels table (SQLite)
  │
  ▼
Orchestrator (selfbot_webull.py)
  │
  ├── Phase 1: Signal Handler ──► read channel_info, apply sizing + routing
  ├── Phase 2: Execution Handler ──► apply order types + sizing overrides
  └── Multi-Broker Worker ──► final qty calc, dispatch to broker API
  │
  ▼
Risk Engine (position_monitor.py + risk_engine.py)
  │
  ├── get_channel_risk_settings() ──► ChannelRiskSettings dataclass
  ├── evaluate_exit_actions() ──► SL/PT/trailing/dynamic/EMA/giveback
  └── _execute_exit() / _place_initial_broker_bracket() ──► broker API
```

---

## Tab 1: Sizing

### Settings Matrix

| Setting | UI Location | DB Column | Applied At | Brokers |
|---|---|---|---|---|
| **Position Size %** | Execute section | `position_size_pct` | selfbot:15810,16919,18067-18260 | ALL (pre-computed qty) |
| **Default Qty** | Execute section | `default_quantity` | selfbot:15809,16918 (HIGHEST priority) | ALL |
| **Force My Size** | Execute toggle | `ignore_signal_position_size` | selfbot:16348-16363 | ALL (exec only, not track) |
| **Balance Mode** | Execute dropdown | `sizing_mode` | selfbot:15823,16929,18077-18097 | ALL + Webull Legacy internal |
| **Track Position %** | Track section | `tracking_position_size_pct` | selfbot:16824,17470 | Paper/tracking only |
| **Track Default Qty** | Track section | `tracking_default_quantity` | ⚠️ **DEAD — NEVER READ** | NONE |
| **Max Position $** | Limits section | `channel_max_position_size` | selfbot:15845-15864,18176-18179 | ALL |
| **Global Max $** | Settings page | `max_position_size` | selfbot:15903,16991 (global cap) | ALL |
| **Global Default Qty** | Settings page | `global_default_quantity` | selfbot:15894,16984 (fallback) | ALL |

### Sizing Priority Cascade (BTO/BUY)

```
1. default_quantity (channel fixed)          ← HIGHEST
2. position_size_pct (channel %)
3. Signal parsed qty ("BTO 5 SPY...")
4. global_default_quantity
5. max_position_size / cost-per-unit
6. Fallback: 1 contract
─── then caps applied ───
7. channel_max_position_size (channel cap)
8. max_position_size (global cap)            ← FINAL SAFETY
```

### Gap Found
- ⚠️ `tracking_default_quantity` — saved to DB, rendered in UI, but **never read** by execution code

---

## Tab 2: Risk Controls (Targets & SL + Advanced)

### Targets & SL Sub-Tab

| Setting | DB Column | Applied At | Brokers | Notes |
|---|---|---|---|---|
| **Stop Loss %** | `stop_loss_pct` | risk_engine:395 (Priority 1) | ALL | Also: bracket SL, emergency market, candle SL |
| **PT1-4 %** | `profit_target_1-4_pct` | risk_engine:660 (Priority 5) | ALL | Tiered partial exits |
| **PT1-4 Qty** | `profit_target_qty_1-4` | risk_engine:670 → calculate_tier_quantities | ALL | Custom qty > auto-split |
| **PT1-4 Trim %** | `profit_target_trim_pct_1-4` | risk_engine:674 → calculate_tier_quantities | ALL | % of remaining position |
| **Trailing Stop %** | `trailing_stop_pct` | risk_engine:700 (Priority 6) | ALL | Skipped if early_trailing on |
| **Trailing Activation %** | `trailing_activation_pct` | risk_engine:702 | ALL | Also: giveback guard threshold |
| **Exit Strategy Mode** | `exit_strategy_mode` | pos_monitor:4700 | ALL | signal/risk/hybrid |
| **Order Chase** | `order_chase_enabled` | selfbot:19463 → UnfilledOrderChaser | ALL | Off/Entry/Exit/Both |
| **Leave Runner** | `leave_runner_enabled/pct` | risk_engine:672, :475 | ALL | Reserves % of position |

### Advanced Sub-Tab

| Setting | DB Column | Applied At | Brokers | Notes |
|---|---|---|---|---|
| **Bracket Mode** | `broker_bracket_mode` | pos_monitor:5693 | ALL 8 | both/sl_only/pt_only/none |
| **Early Trailing** | `enable_early_trailing` + activation + step | risk_engine:558 (Priority 4) | ALL | Replaces legacy trailing |
| **Dynamic SL** | `enable_dynamic_sl` + profile | risk_engine:404 (Priority 2) | ALL | conservative/standard/aggressive |
| **Escalation Only** | `escalation_only_mode` | pos_monitor:4934 | ALL | PT marks tiers but doesn't sell |
| **Giveback Guard** | `enable_giveback_guard` + pct | risk_engine:528 (Priority 3) | ALL | After PT2 hit or trail activation |
| **EMA Risk** | `ema_risk_enabled` + 8 sub-settings | risk_engine:440 (Priority 2.5) | ALL | Runs even in signal mode |
| **PT Near-Lock** | `enable_pt_near_lock` + 5 sub-settings | risk_engine:611 (Priority 4.5) | ALL | Tight trail near PT threshold |

### Risk Evaluation Priority Order

```
1. Hard SL (stop_loss_pct)                          ← SELL_ALL
2. Dynamic SL (enable_dynamic_sl + profile)         ← SELL_ALL after PT hit
2.5. EMA Exit/Escalation (ema_risk_enabled)         ← SELL_ALL or SL escalation
3. Giveback Guard (enable_giveback_guard)            ← SELL_ALL if pnl drawback
4. Early Trailing (enable_early_trailing)            ← SELL_ALL trailing stop
4.5. PT Near-Lock (enable_pt_near_lock)             ← tight trail near PT
5. Tiered Profit Targets (profit_target_1-4_pct)    ← SELL_PARTIAL
6. Legacy Trailing Stop (trailing_stop_pct)          ← SELL_ALL (if early trail off)
```

### Broker Bracket Support Matrix

| Broker | SL Order | PT Order | OCO | Native Trailing | DAY TIF Replay |
|---|---|---|---|---|---|
| **Webull Official** | STOP_LOSS / STOP_LOSS_LIMIT | LIMIT | ✅ OCO | ✅ Stocks only | ✅ Options |
| **Schwab** | STOP / STOP_LIMIT | LIMIT | ✅ OCO | ❌ | ✅ Options |
| **IBKR** | StopOrder | LimitOrder | ❌ (software) | ❌ (software) | ✅ Options |
| **Alpaca** | StopOrderRequest | LimitOrderRequest | ❌ | ❌ | ❌ |
| **Tastytrade** | Risk engine only | Risk engine only | ❌ | ❌ | ❌ |
| **Robinhood** | Risk engine only | Risk engine only | ❌ | ❌ | ❌ |
| **Webull Legacy** | Separate orders | Separate orders | ❌ | ❌ | ❌ |
| **Trading212** | stop_limit_order | limit_order | ❌ | ❌ | ❌ |

---

## Tab 3: Order Types

### Settings Matrix

| Setting | DB Column | Applied At | Notes |
|---|---|---|---|
| **Entry Order** (market/limit) | `entry_order_mode` | selfbot:10326,16384,17273 | Sets `_use_market_order` flag |
| **Trim Order** (market/limit) | `trim_order_mode` | selfbot:16389,17278 + pos_monitor:8378 | Auto-locked to limit when PT bracket active |
| **Trim Offset ($)** | `trim_limit_offset` | tiered_targets:280-320 | price - offset (dollar mode) |
| **Trim Offset (%)** | `trim_limit_offset_pct` | tiered_targets:280-320 | price × (1 - pct/100) |
| **Trim Offset Mode** | `trim_limit_offset_mode` | tiered_targets:280-320 | dollar / percent |
| **SL Order** (market/limit) | `sl_order_mode` | pos_monitor:8344,6264 | Overridden: hard SL always market |
| **SL Limit Offset %** | `sl_limit_offset` | pos_monitor:8368-8376 | price × (1 - offset) for limit SL |

### Per-Broker Order Type Support

| Broker | True Market | Limit | Stop | Stop-Limit | Trailing Stop |
|---|---|---|---|---|---|
| **Webull Official** | ✅ | ✅ | ✅ STOP_LOSS | ✅ STOP_LOSS_LIMIT | ✅ Stocks only |
| **Schwab** | ✅ (NORMAL session) | ✅ | ✅ STOP | ✅ STOP_LIMIT | ❌ |
| **IBKR** | ✅ MarketOrder | ✅ LimitOrder | ✅ StopOrder | ❌ | ❌ (software) |
| **Alpaca** | ✅ (no ext hrs) | ✅ | ✅ | ✅ | ✅ trailing_stop |
| **Tastytrade** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Robinhood** | ✅ Stocks only | ✅ | ❌ | ❌ | ❌ |
| **Webull Legacy** | Aggressive limit | ✅ | ❌ native | ❌ native | ❌ |
| **Trading212** | ✅ Stocks only | ✅ Stocks only | ❌ | ✅ stop_limit | ❌ |

### Key Behaviors

1. **SL Order Mode override**: Hard SL and Dynamic SL **always force market** regardless of `sl_order_mode` setting (pos_monitor:8349). Only trailing/early-trailing/giveback respect the limit setting.
2. **Emergency market**: If loss ≥ 2× configured SL%, forces market regardless of all settings (pos_monitor:8365).
3. **Bracket PT lock**: When `broker_bracket_mode` is `both` or `pt_only`, `trim_order_mode` is forced to `limit` (routes.py:2189).
4. **No entry limit offset**: There is no per-channel limit offset for BTO orders. Entry limits use the signal's parsed price directly.

---

## Tab 4: Conditional Orders

### Settings Matrix

| Setting | DB Column | Applied At | Notes |
|---|---|---|---|
| **Enable** | `conditional_order_enabled` | selfbot:16701 | Per-channel gate |
| **Timeout (minutes)** | `conditional_order_timeout_minutes` | base.py:1767-1770 | Expiry from creation time |
| **Order Timeout (all)** | `order_timeout_minutes` | selfbot:19460 → order chaser | Regular order timeout, NOT conditional |
| **Entry Confirmation %** | `entry_confirmation_pct` | selfbot:16686-16698 | Converts BTO → conditional (stocks only) |
| **Breakout Reset** | `breakout_reset_enabled` | base.py:2462-2505 | Requires pullback before trigger |
| **Trigger Offset Mode** | `trigger_offset_mode` | base.py:1721-1757 | percent / dollar |
| **Trigger Offset Value** | `trigger_offset_percent/value` | base.py:1721-1757 → compute_adjusted_trigger | Channel → global fallback |

### Conditional Order Lifecycle

```
Signal "AAPL over $250" arrives
  │
  ├── is_conditional_order_signal() detects "over" keyword
  ├── parse_conditional_order_signal() → symbol=AAPL, trigger=250, type=over
  │
  ▼
create_order() (base.py:1661)
  ├── Apply trigger offset: 250 × (1 + offset%) = adjusted_trigger
  ├── Read channel settings: sizing, SL%, PT%, trailing, slippage
  ├── Save to DB: conditional_orders table
  └── Start StreamingPriceMonitor → polls hub every 250ms
  │
  ▼
_on_price_update() (base.py:2381)
  ├── Check expiry → breakout reset → price vs adjusted_trigger
  ├── 150ms confirmation (2+ ticks must confirm)
  └── _execute_order() → execution_callback → order_queue → broker
```

### Per-Broker Conditional Order Latency

| Broker | Price Source | Monitoring Latency | Notes |
|---|---|---|---|
| **IBKR** | reqMktData (event-driven) | **50-200ms** | Fastest — `_price_event.set()` wakeup |
| **Schwab** | WebSocket L1 | **200-750ms** | 250ms polling |
| **Webull Official** | MQTT WSS | **100-750ms** | 250ms polling |
| **Webull Legacy** | MQTT | **100-750ms** | 250ms polling |
| **Tastytrade** | DXLink WS | **200-750ms** | 250ms polling |
| **Alpaca** | REST polling | **1000-2000ms** | No streaming hub |
| **Robinhood** | REST polling | **2000-4000ms** | Slowest — 2s interval |
| **Trading212** | Portfolio refresh | **5000ms** | Stocks only |

### Settings Not Wired (dead code)

| Setting | Status | Location |
|---|---|---|
| `entry_price_offset_percent` (global) | ⚠️ **DEAD** | Stored in settings table, shown in UI, never read by execution |
| `auto_execute` (global) | ⚠️ **DEAD** | Stored, shown in UI, never checked — orders always auto-execute |
| `conditional_auto_execute` (per-channel) | ⚠️ **DEAD** | DB column exists, no UI, never checked |

---

## Adding a New Broker — Checklist

### Entry Path (BTO/BUY)

- [ ] Broker receives pre-computed `quantity` from orchestrator (no sizing code needed)
- [ ] Broker supports `place_stock_order(symbol, quantity, action, price, order_type)` interface
- [ ] Broker supports `place_option_order(symbol, strike, expiry, option_type, action, quantity, price)` interface
- [ ] Market orders: `price=None` → broker uses market type
- [ ] Limit orders: `price` provided → broker uses limit type
- [ ] Add broker to `MULTI_BROKER_DISPATCH` routing in selfbot_webull.py
- [ ] Add broker health check to `_validate_broker_health()` in selfbot_webull.py

### Exit Path (STC/SELL/SL/PT)

- [ ] Broker registered in `_get_broker_instance_for_bracket()` (position_monitor.py:5538)
- [ ] Bracket SL: implement `place_stop_order()` or `place_option_stop_limit()` — or risk engine handles via software
- [ ] Bracket PT: implement `place_stock_order(LIMIT)` / `place_option_order(LIMIT)`
- [ ] OCO (optional): implement `place_oco_bracket()` for linked SL+PT
- [ ] Add broker to `_direct_execute_exit()` dispatch (position_monitor.py:8506)
- [ ] Add broker to `_update_prices_from_hub()` streaming overlay (position_monitor.py:9803)

### Streaming / Price Feed

- [ ] Create `BrokerDataHub` (or use existing WebullDataHub pattern)
- [ ] Register hub with UnifiedPriceHub `_HUB_REGISTRY`
- [ ] Emit `quote_updated` events on price ticks
- [ ] Add rate limiter to `_init_rate_limiters()` in us_service.py
- [ ] Add broker to `subscribe_symbol()` routing in unified_price_hub.py

### Dashboard

- [ ] Add `_fetch_<broker>()` function to `live_snapshot.py`
- [ ] Add broker branch to `_overlay_streaming_prices()` in live_snapshot.py
- [ ] Add broker to `_refresh_snapshot()` ThreadPoolExecutor dispatch

### Sync

- [ ] Add broker to `broker_sync_service.py` sync cycle
- [ ] Ensure positions have `current_price` (not $0)
- [ ] Map broker name consistently (e.g., `BROKER_LIVE` / `BROKER_PAPER`)

---

## Validation Queries

### Verify a setting flows end-to-end

```sql
-- Check DB value
SELECT position_size_pct, stop_loss_pct, broker_bracket_mode, exit_strategy_mode
FROM channels WHERE id = ?;

-- Check risk settings loaded correctly (via API)
GET /api/channels/{id}/risk-settings
```

### Verify broker bracket orders

```sql
-- Check active bracket orders in position cache
SELECT position_key, broker_stop_order_id, broker_pt_order_id,
       broker_oco_order_id, broker_sl_order_type
FROM risk_position_cache WHERE broker_stop_order_id IS NOT NULL;
```

### Verify conditional order monitoring

```sql
-- Check active conditional orders
SELECT id, symbol, trigger_price, adjusted_trigger_price, trigger_type,
       status, broker, channel_id, expires_at
FROM conditional_orders WHERE status IN ('PENDING', 'MONITORING');
```

---

## Channels.html Settings Audit — Gap Analysis (2026-06-20)

Comprehensive audit of all 4 tabs in Trading → Channels → Settings modal.

### Gaps Found: 9 total (1 DEAD, 7 HALF-WIRED, 1 MISLEADING UI)

| # | Setting | Tab | Status | Issue |
|---|---|---|---|---|
| 1 | `tracking_default_quantity` | Sizing | 🔴 **DEAD** | Saved to DB, shown in UI, **never read by any Python code**. Paper trades use `tracking_position_size_pct` or signal qty only |
| 2 | `ignore_signal_position_size` | Sizing | ⚠️ HALF-WIRED | Works for execution but **not checked in tracking/paper path** (lines 16828-16836, 17462-17480) |
| 3 | `sl_order_mode` | Order Types | ⚠️ HALF-WIRED | **DEAD for hard SL and dynamic SL** — `position_monitor.py:8348-8351` always forces market with TIERED URGENCY. Only works for trailing/early_trailing/giveback exits |
| 4 | `sl_limit_offset` | Order Types | ⚠️ HALF-WIRED | **Never applied to broker OCO brackets** — Schwab OCO (L5839) and WO OCO (L6270) use raw SL price without offset. Only applies to software risk engine exits |
| 5 | EMA exits | Order Types | ⚠️ MISSING | **EMA exits bypass ALL order type settings** — `ema_exit`/`ema_no_trend` triggers not in `sl_triggers` tuple and not checked as `is_pt_exit`, so they use base limit price with no market/limit override |
| 6 | `order_timeout_minutes` | Conditional | ⚠️ HALF-WIRED | **DEAD for conditional orders** — `base.py:1767` reads only `conditional_order_timeout_minutes`. `order_timeout_minutes` works for regular order chasing only. UI says "all orders" — misleading |
| 7 | Bracket trim lock | Order Types | ⚠️ MISSING | **No execution-level enforcement** — UI disables dropdown, API forces value, but `position_monitor.py` has no guard if DB gets out of sync |
| 8 | `conditional_order_enabled` | Conditional | ⚠️ INCONSISTENT | Default = `True` in `base.py:1698` vs `0` in `selfbot_webull.py:16701` — if DB value is NULL, behavior differs per code path |
| 9 | `entry_confirmation_pct` | Conditional | ⚠️ MISLEADING UI | Helper text says "Works for all signal types" but **options are explicitly skipped** (`selfbot:16697`) |

### Per-Setting Wiring Status — ALL 4 Tabs

#### Sizing Tab (channels.html `buildSizingTab`)

| Setting | UI | DB | Python Read | Applied | ALL Brokers? |
|---|---|---|---|---|---|
| `execute_enabled` | :1802 | ✅ | ✅ selfbot:11978 | ✅ | ✅ |
| `position_size_pct` | :1807 | ✅ | ✅ selfbot:15810 | ✅ worker:18067 | ✅ ALL 8 |
| `default_quantity` | :1813 | ✅ | ✅ selfbot:15809 | ✅ highest priority | ✅ ALL 8 |
| `ignore_signal_position_size` | :1819 | ✅ | ✅ selfbot:16348 | ⚠️ exec only | ✅ exec, ❌ track |
| `sizing_mode` | :1826 | ✅ | ✅ selfbot:15823 | ✅ SOD/pre-market | ✅ ALL 8 |
| `track_enabled` | :1843 | ✅ | ✅ selfbot:11979 | ✅ | N/A |
| `tracking_position_size_pct` | :1849 | ✅ | ✅ selfbot:16824 | ✅ | Paper only |
| `tracking_default_quantity` | :1854 | ✅ | 🔴 **NEVER** | 🔴 **DEAD** | ❌ NONE |
| `channel_max_position_size` | :1867 | ✅ | ✅ selfbot:15811 | ✅ pre-cap + worker | ✅ ALL 8 |

#### Risk Controls Tab (channels.html `buildRiskControlsTab`)

| Setting | UI | DB | Python Read | Applied | ALL Brokers? |
|---|---|---|---|---|---|
| `signal_update_automation` | :1890 | ✅ | ✅ db:12661 | ✅ Discord edit handler | ✅ ALL |
| `slippage_protection_enabled` | :1924 | ✅ | ✅ selfbot:1646 | ✅ 5 check points | ✅ ALL 8 |
| `slippage_max_pct` | :1929 | ✅ | ✅ selfbot:1646 | ✅ threshold check | ✅ ALL 8 |
| `slippage_wait_minutes` | :1935 | ✅ | ✅ selfbot:1645 | ✅ wait duration | ✅ ALL 8 |
| `limit_cap_enabled` | :1934 | ✅ | ✅ base.py:1841 | ✅ conditional only | ✅ ALL 8 |
| `limit_cap_pct` | :1940 | ✅ | ✅ base.py:1841 | ✅ price ceiling | ✅ ALL 8 |
| `ndx_to_qqq_enabled` | :1956 | ✅ | ✅ selfbot:16395 | ✅ options only | ✅ ALL 8 (T212 N/A) |
| `ndx_to_qqq_delta` | :1963 | ✅ | ✅ selfbot:16415 | ✅ delta matching | ✅ ALL 8 (T212 N/A) |

#### Order Types Tab (channels.html `buildOrderTypesTab`)

| Setting | UI | DB | Python Read | Applied | ALL Brokers? |
|---|---|---|---|---|---|
| `entry_order_mode` | :1976 | ✅ | ✅ selfbot:10326 | ✅ _use_market_order | ✅ ALL 8 |
| `trim_order_mode` | :1991 | ✅ | ✅ selfbot:16389 + pm:8379 | ⚠️ EMA bypassed | ✅ for PT exits |
| `trim_limit_offset` | :2020 | ✅ | ✅ pm:908 → tiered:288 | ✅ dollar mode | ✅ ALL 8 |
| `trim_limit_offset_pct` | :2030 | ✅ | ✅ pm:910 → tiered:310 | ✅ percent mode | ✅ ALL 8 |
| `trim_limit_offset_mode` | :2015 | ✅ | ✅ pm:909 | ✅ | ✅ ALL 8 |
| `sl_order_mode` | :2037 | ✅ | ✅ pm:8342 | ⚠️ dead for hard/dynamic SL | trailing/giveback only |
| `sl_limit_offset` | :2046 | ✅ | ✅ pm:8368 | ⚠️ not applied to OCO | software exits only |

#### Conditional Tab (channels.html `buildConditionalTab`)

| Setting | UI | DB | Python Read | Applied | ALL Brokers? |
|---|---|---|---|---|---|
| `conditional_order_enabled` | :2069 | ✅ | ✅ selfbot:16701 | ⚠️ inconsistent default | ✅ ALL (stocks only) |
| `order_timeout_minutes` | :2077 | ✅ | ✅ selfbot:19460 | ⚠️ regular orders only | ✅ ALL 8 |
| `conditional_order_timeout_minutes` | :2083 | ✅ | ✅ base.py:1767 | ✅ conditional expiry | ✅ ALL |
| `entry_confirmation_pct` | :2097 | ✅ | ✅ selfbot:16686 | ⚠️ stocks only | ✅ stocks only |
| `breakout_reset_enabled` | :2113 | ✅ | ✅ base.py:1838 | ✅ pullback guard | ✅ ALL |
| `trigger_offset_mode` | :2127 | ✅ | ✅ base.py:1722 | ✅ percent + dollar | ✅ ALL |
| `trigger_offset_percent/value` | :2138 | ✅ | ✅ base.py:1724 | ✅ adjusted trigger | ✅ ALL |
