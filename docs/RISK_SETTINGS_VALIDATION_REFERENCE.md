# Risk Management Settings — Validation Reference

This document defines the **complete end-to-end data flow** for every risk management setting in BotifyTrades. Use it as a checklist whenever adding or modifying any setting to ensure nothing is missed.

---

## How To Use This Document

When **adding a new setting** or **changing an existing one**, walk through each layer below and verify the field exists and is wired correctly at every step:

1. **UI** → field is rendered and collected on save
2. **API** → field is sent in the save payload
3. **Database** → column exists and is in `update_channel` allowed list
4. **Risk Engine SELECT** → field is in all 4 main SELECT queries at the correct column index
5. **Direct Lookup Fallback** → field is fetched and mapped in the LEFT JOIN fallback path
6. **ChannelRiskSettings** → field exists on the dataclass in `risk_types.py`
7. **Constructor** → all 4 constructors pass the value from `row[N]` to the dataclass
8. **Cache Invalidation** → field is in the `risk_fields` set in `routes.py` (line ~2136)
9. **Channel-Specific Risk Override** → field is in `channel_specific_risk_fields` tuple (line ~2081) if changing it should auto-set `use_global_risk_settings=0`
10. **Signal Routing Inheritance** → field is inherited when signals route to execution channels
11. **Consumption** → the risk engine or relevant service actually reads and acts on the value

---

## Files Involved (Quick Reference)

| Layer | File | Purpose |
|---|---|---|
| UI | `gui_app/static/js/channels.js` | Renders settings, collects on save (`saveRiskManagement`) |
| API Route | `gui_app/routes.py` | `/api/channels/<id>` PUT handler, cache invalidation |
| DB Schema & Writes | `gui_app/database.py` | Column migration, `update_channel` allowed fields |
| DB Read-back | `gui_app/database.py` | `get_channels()`, `get_channel_by_id()` |
| Save Verification | `gui_app/settings_validator.py` | `CRITICAL_CHANNEL_FIELDS` post-save check |
| Risk Dataclass | `src/risk/risk_types.py` | `ChannelRiskSettings` dataclass definition |
| Risk Engine | `src/risk/position_monitor.py` | 4 SELECT queries, 4 constructors, direct lookup fallback |
| Position Cache | `src/risk/position_cache.py` | `invalidate_channel_settings()` |
| Signal Routing | `src/selfbot_webull.py` | Inherits settings when routing signals |

---

## Master Field Registry (42 Fields)

### Row Index Map — Main SELECT Queries

The 4 main SELECT queries in `position_monitor.py` use LEFT JOINs to `channels` and produce rows with these column indices:

| Row Index | Field | DB Column | ChannelRiskSettings Attr |
|---|---|---|---|
| row[0] | channel_id | trades.channel_id | channel_id |
| row[1] | profit_target_1_pct | channels.profit_target_1_pct | profit_target_1_pct |
| row[2] | profit_target_2_pct | channels.profit_target_2_pct | profit_target_2_pct |
| row[3] | profit_target_3_pct | channels.profit_target_3_pct | profit_target_3_pct |
| row[4] | stop_loss_pct | channels.stop_loss_pct | stop_loss_pct |
| row[5] | trailing_stop_pct | channels.trailing_stop_pct | trailing_stop_pct |
| row[6] | trailing_activation_pct | channels.trailing_activation_pct | trailing_activation_pct |
| row[7] | channel_name | channels.name | channel_name |
| row[8] | risk_management_enabled | channels.risk_management_enabled | (gating flag) |
| row[9] | leave_runner_enabled | channels.leave_runner_enabled | leave_runner_enabled |
| row[10] | leave_runner_pct | channels.leave_runner_pct | leave_runner_pct |
| row[11] | profit_target_4_pct | channels.profit_target_4_pct | profit_target_4_pct |
| row[12] | profit_target_qty_1 | channels.profit_target_qty_1 | profit_target_qty_1 |
| row[13] | profit_target_qty_2 | channels.profit_target_qty_2 | profit_target_qty_2 |
| row[14] | profit_target_qty_3 | channels.profit_target_qty_3 | profit_target_qty_3 |
| row[15] | profit_target_qty_4 | channels.profit_target_qty_4 | profit_target_qty_4 |
| row[16] | trim_order_mode | channels.trim_order_mode | trim_order_mode |
| row[17] | trim_limit_offset | channels.trim_limit_offset | trim_limit_offset |
| row[18] | exit_strategy_mode | channels.exit_strategy_mode | exit_strategy_mode |
| row[19] | enable_dynamic_sl | channels.enable_dynamic_sl | enable_dynamic_sl |
| row[20] | enable_giveback_guard | channels.enable_giveback_guard | enable_giveback_guard |
| row[21] | giveback_allowed_pct | channels.giveback_allowed_pct | giveback_allowed_pct |
| row[22] | dynamic_sl_profile | channels.dynamic_sl_profile | dynamic_sl_profile |
| row[23] | (trade fields vary) | — | — |
| row[24] | enable_early_trailing | channels.enable_early_trailing | enable_early_trailing |
| row[25] | early_trailing_activation_pct | channels.early_trailing_activation_pct | early_trailing_activation_pct |
| row[26] | early_trailing_step_pct | channels.early_trailing_step_pct | early_trailing_step_pct |
| row[27] | (trade SL price) | trades.sl_price | (not a setting) |
| row[28] | (trade PT price) | trades.tp_price | (not a setting) |
| row[29] | (trade fields) | — | — |
| row[30] | sl_order_mode | channels.sl_order_mode | sl_order_mode |
| row[31] | sl_limit_offset | channels.sl_limit_offset | sl_limit_offset |
| row[32] | trim_limit_offset_mode | channels.trim_limit_offset_mode | trim_limit_offset_mode |
| row[33] | trim_limit_offset_pct | channels.trim_limit_offset_pct | trim_limit_offset_pct |
| row[34] | use_global_risk_settings | channels.use_global_risk_settings | (gating flag) |
| row[35] | ema_risk_enabled | channels.ema_risk_enabled | ema_risk_enabled |
| row[36] | ema_period | channels.ema_period | ema_period |
| row[37] | ema_timeframe_minutes | channels.ema_timeframe_minutes | ema_timeframe_minutes |
| row[38] | ema_buffer_pct | channels.ema_buffer_pct | ema_buffer_pct |
| row[39] | ema_exit_enabled | channels.ema_exit_enabled | ema_exit_enabled |
| row[40] | ema_escalation_enabled | channels.ema_escalation_enabled | ema_escalation_enabled |
| row[41] | ema_extended_hours | channels.ema_extended_hours | ema_extended_hours |
| row[42] | ema_use_underlying | channels.ema_use_underlying | ema_use_underlying |
| row[43] | ema_no_trend_candles | channels.ema_no_trend_candles | ema_no_trend_candles |
| row[44] | escalation_only_mode | channels.escalation_only_mode | escalation_only_mode |
| row[45] | profit_target_trim_pct_1 | channels.profit_target_trim_pct_1 | profit_target_trim_pct_1 |
| row[46] | profit_target_trim_pct_2 | channels.profit_target_trim_pct_2 | profit_target_trim_pct_2 |
| row[47] | profit_target_trim_pct_3 | channels.profit_target_trim_pct_3 | profit_target_trim_pct_3 |
| row[48] | profit_target_trim_pct_4 | channels.profit_target_trim_pct_4 | profit_target_trim_pct_4 |
| row[49] | broker_bracket_mode | channels.broker_bracket_mode | broker_bracket_mode |

### Direct Lookup Fallback Column Map

When the LEFT JOIN returns NULL (channel not matched), `position_monitor.py` does a direct `SELECT ... FROM channels` query. The column indices in that fallback query (`ch_row[N]`) map to `row[N]` as follows:

| ch_row Index | Field | Maps to row[] |
|---|---|---|
| ch_row[0] | risk_management_enabled | row[8] |
| ch_row[1] | use_global_risk_settings | row[34] |
| ch_row[2] | name | row[7] |
| ch_row[3] | profit_target_1_pct | row[1] |
| ch_row[4] | profit_target_2_pct | row[2] |
| ch_row[5] | profit_target_3_pct | row[3] |
| ch_row[6] | stop_loss_pct | row[4] |
| ch_row[7] | trailing_stop_pct | row[5] |
| ch_row[8] | trailing_activation_pct | row[6] |
| ch_row[9] | leave_runner_enabled | row[9] |
| ch_row[10] | leave_runner_pct | row[10] |
| ch_row[11] | profit_target_4_pct | row[11] |
| ch_row[12-15] | profit_target_qty_1-4 | row[12-15] |
| ch_row[16] | trim_order_mode | row[16] |
| ch_row[17] | trim_limit_offset | row[17] |
| ch_row[18] | exit_strategy_mode | row[18] |
| ch_row[19] | enable_dynamic_sl | row[19] |
| ch_row[20] | enable_giveback_guard | row[20] |
| ch_row[21] | giveback_allowed_pct | row[21] |
| ch_row[22] | dynamic_sl_profile | row[22] |
| ch_row[23] | enable_early_trailing | row[24] |
| ch_row[24] | early_trailing_activation_pct | row[25] |
| ch_row[25] | early_trailing_step_pct | row[26] |
| ch_row[26] | sl_order_mode | row[30] |
| ch_row[27] | sl_limit_offset | row[31] |
| ch_row[28] | trim_limit_offset_mode | row[32] |
| ch_row[29] | trim_limit_offset_pct | row[33] |
| ch_row[30] | ema_risk_enabled | row[35] |
| ch_row[31] | ema_period | row[36] |
| ch_row[32] | ema_timeframe_minutes | row[37] |
| ch_row[33] | ema_buffer_pct | row[38] |
| ch_row[34] | ema_exit_enabled | row[39] |
| ch_row[35] | ema_escalation_enabled | row[40] |
| ch_row[36] | ema_extended_hours | row[41] |
| ch_row[37] | ema_use_underlying | row[42] |
| ch_row[38] | ema_no_trend_candles | row[43] |
| ch_row[39] | escalation_only_mode | row[44] |
| ch_row[40] | profit_target_trim_pct_1 | row[45] |
| ch_row[41] | profit_target_trim_pct_2 | row[46] |
| ch_row[42] | profit_target_trim_pct_3 | row[47] |
| ch_row[43] | profit_target_trim_pct_4 | row[48] |
| ch_row[44] | broker_bracket_mode | row[49] |

---

## Cache Invalidation Set

Located in `gui_app/routes.py` (line ~2136). When any field in this set is included in a channel update, `request_settings_invalidation()` is called to flush the risk engine's cached `ChannelRiskSettings` objects:

```
risk_management_enabled, profit_target_1_pct, profit_target_2_pct,
profit_target_3_pct, profit_target_4_pct, stop_loss_pct,
trailing_stop_pct, trailing_activation_pct, leave_runner_enabled,
leave_runner_pct, profit_target_qty_1, profit_target_qty_2,
profit_target_qty_3, profit_target_qty_4,
profit_target_trim_pct_1, profit_target_trim_pct_2,
profit_target_trim_pct_3, profit_target_trim_pct_4, exit_strategy_mode,
enable_dynamic_sl, enable_giveback_guard, giveback_allowed_pct, dynamic_sl_profile, escalation_only_mode,
enable_early_trailing, early_trailing_activation_pct, early_trailing_step_pct,
ema_risk_enabled, ema_period, ema_timeframe_minutes, ema_buffer_pct,
ema_exit_enabled, ema_escalation_enabled, ema_extended_hours, ema_use_underlying, ema_no_trend_candles,
sl_order_mode, sl_limit_offset, entry_order_mode,
trim_order_mode, trim_limit_offset, trim_limit_offset_mode, trim_limit_offset_pct,
order_chase_enabled, entry_chase_enabled, use_global_risk_settings,
broker_bracket_mode
```

**Note**: `sizing_mode` is intentionally NOT in this set — it only affects entry-time sizing, not risk engine evaluation.

---

## Channel-Specific Risk Fields (Auto-Override)

Located in `gui_app/routes.py` (line ~2081). When any field in this tuple is set on a channel, `use_global_risk_settings` is automatically set to `0` (channel uses its own settings, not global defaults):

```
risk_management_enabled, stop_loss_pct, profit_target_1_pct,
exit_strategy_mode, signal_update_automation, escalation_only_mode,
trailing_stop_pct, trailing_activation_pct,
enable_early_trailing, early_trailing_activation_pct, early_trailing_step_pct,
enable_dynamic_sl, enable_giveback_guard, giveback_allowed_pct,
profit_target_2_pct, profit_target_3_pct, profit_target_4_pct,
broker_bracket_mode
```

---

## ChannelRiskSettings Dataclass Fields

Defined in `src/risk/risk_types.py`, class `ChannelRiskSettings`:

| Field | Type | Default | Notes |
|---|---|---|---|
| channel_id | str | (required) | |
| channel_name | str | (required) | |
| profit_target_1_pct | float | 0.0 | |
| profit_target_2_pct | float | 0.0 | |
| profit_target_3_pct | float | 0.0 | |
| profit_target_4_pct | float | 0.0 | |
| profit_target_qty_1 | Optional[int] | None | Custom qty (None = auto) |
| profit_target_qty_2 | Optional[int] | None | |
| profit_target_qty_3 | Optional[int] | None | |
| profit_target_qty_4 | Optional[int] | None | |
| profit_target_trim_pct_1 | Optional[float] | None | Custom trim % (None = auto) |
| profit_target_trim_pct_2 | Optional[float] | None | |
| profit_target_trim_pct_3 | Optional[float] | None | |
| profit_target_trim_pct_4 | Optional[float] | None | |
| stop_loss_pct | float | 0.0 | |
| trailing_stop_pct | float | 0.0 | |
| trailing_activation_pct | float | 15.0 | |
| leave_runner_enabled | bool | False | |
| leave_runner_pct | float | 25.0 | |
| trim_order_mode | str | 'market' | 'market' or 'limit' |
| sl_order_mode | str | 'limit' | 'market' or 'limit' |
| trim_limit_offset | float | 0.01 | Dollar offset |
| trim_limit_offset_mode | str | 'dollar' | 'dollar' or 'percent' |
| trim_limit_offset_pct | float | 2.0 | Percent offset |
| sl_limit_offset | float | 0.03 | SL limit offset % |
| exit_strategy_mode | str | 'signal' | 'signal', 'risk', 'hybrid' |
| enable_dynamic_sl | bool | False | |
| enable_giveback_guard | bool | False | |
| giveback_allowed_pct | float | 30.0 | |
| dynamic_sl_profile | str | 'standard' | 'conservative', 'standard', 'aggressive' |
| enable_early_trailing | bool | False | |
| early_trailing_activation_pct | float | 5.0 | |
| early_trailing_step_pct | float | 3.0 | |
| escalation_only_mode | bool | False | |
| broker_bracket_mode | str | 'both' | 'both', 'sl_only', 'pt_only', 'none' |
| ema_risk_enabled | bool | False | |
| ema_period | int | 5 | |
| ema_timeframe_minutes | int | 5 | |
| ema_buffer_pct | float | 0.1 | |
| ema_exit_enabled | bool | True | |
| ema_escalation_enabled | bool | True | |
| ema_extended_hours | bool | False | |
| ema_use_underlying | bool | True | |
| ema_no_trend_candles | int | 3 | |

### Computed Properties

| Property | Logic |
|---|---|
| `allows_broker_sl` | `broker_bracket_mode in ('both', 'sl_only')` |
| `allows_broker_pt` | `broker_bracket_mode in ('both', 'pt_only')` |
| `has_tiered_targets` | Any PT > 0 |

---

## Non-Risk Channel Settings (Not in risk_fields)

These fields are saved via `update_channel` but do NOT trigger risk cache invalidation (correct behavior):

| Field | Purpose |
|---|---|
| `sizing_mode` | Affects entry-time sizing only, not risk evaluation |
| `trade_summary_enabled` | Per-channel P/L posting toggle |
| `order_chase_enabled` / `entry_chase_enabled` | Chaser service reads directly |
| `conditional_order_*` | Conditional order service settings |
| `slippage_*` / `limit_cap_*` | Entry-time slippage checks |
| `ndx_to_qqq_*` | Symbol conversion settings |
| `ticker_filter_*` | Entry-time filtering |

---

## Checklist: Adding a New Risk Setting

### Step 1: Database

- [ ] Add column migration in `gui_app/database.py` `init_db()` with `ALTER TABLE channels ADD COLUMN ... DEFAULT ...`
- [ ] Add the field name to the `update_channel` allowed fields list (line ~2876)
- [ ] Verify `get_channels()` uses `SELECT *` (it does — all new columns auto-included)

### Step 2: API Route

- [ ] Add the field to `risk_fields` set in `routes.py` (line ~2136) for cache invalidation
- [ ] If the field should auto-override global settings, add to `channel_specific_risk_fields` tuple (line ~2081)
- [ ] Optionally add to `CRITICAL_CHANNEL_FIELDS` in `settings_validator.py` for post-save verification

### Step 3: UI

- [ ] Add input/toggle/radio in `channels.js` channel card HTML
- [ ] Collect the value in `saveRiskManagement()` function
- [ ] Include in the payload sent to `PUT /api/channels/{id}`
- [ ] Add help text to `showRiskHelp()` if using a `?` button

### Step 4: Risk Engine — ChannelRiskSettings Dataclass

- [ ] Add field with type and default to `ChannelRiskSettings` in `src/risk/risk_types.py`
- [ ] Add any computed properties if needed

### Step 5: Risk Engine — SELECT Queries

There are **4 main SELECT queries** in `position_monitor.py` that join `trades` with `channels`. Each must include the new column at the same index position:

- [ ] Query 1: Active positions (stocks)
- [ ] Query 2: Active positions (options)
- [ ] Query 3: Pending positions (stocks)
- [ ] Query 4: Pending positions (options)

**Critical**: The new column must be at the SAME index position across all 4 queries. Currently the next available index is **row[50]**.

### Step 6: Risk Engine — Direct Lookup Fallback

- [ ] Add the column to the fallback `SELECT ... FROM channels` query (line ~704)
- [ ] Map `ch_row[N]` to `row[M]` in the fallback assignment block
- [ ] Ensure `while len(row) < X` pads enough (currently pads to 50 — increase if row index > 49)

### Step 7: Risk Engine — Constructors

There are **4 constructor calls** that build `ChannelRiskSettings(...)` from row data. Each must include the new field:

- [ ] Constructor for stocks (active)
- [ ] Constructor for options (active)
- [ ] Constructor for stocks (pending)
- [ ] Constructor for options (pending)

Pattern: `new_field=row[N] if len(row) > N and row[N] else DEFAULT_VALUE`

### Step 8: Signal Routing Inheritance

- [ ] In `src/selfbot_webull.py`, ensure the field is inherited when signals route from source to execution channel

### Step 9: Consumption

- [ ] Write the actual logic that reads the setting and acts on it
- [ ] Add guards (e.g., `if not getattr(channel_settings, 'new_field', DEFAULT):`)

### Step 10: Verify

- [ ] Save a value via UI
- [ ] Query DB to confirm persistence: `SELECT new_field FROM channels WHERE name = ?`
- [ ] Check risk engine logs to confirm the value is loaded into `ChannelRiskSettings`
- [ ] Test the actual behavior the setting controls

---

## Checklist: Modifying an Existing Setting

### Changing Type or Valid Values

- [ ] Update `ChannelRiskSettings` field type/default in `risk_types.py`
- [ ] Update UI input constraints (min/max/step/options)
- [ ] Update `CRITICAL_CHANNEL_FIELDS` schema if the field is there
- [ ] Verify all 4 constructors handle the new type correctly

### Changing Row Index

**Do not change existing row indices.** Always append new fields at the end (next available index). Changing indices breaks all 4 queries, all 4 constructors, and the fallback lookup.

### Removing a Setting

- [ ] Keep the DB column (backward compat) or add migration to drop it
- [ ] Remove from `saveRiskManagement()` payload
- [ ] Remove from `risk_fields` and `channel_specific_risk_fields`
- [ ] Remove from constructors (use default value)
- [ ] Remove consumption logic

---

## 4-Constructor Locations

For reference, the 4 constructor calls in `position_monitor.py` that build `ChannelRiskSettings` from query rows:

| Constructor | Approximate Line | Context |
|---|---|---|
| #1 | ~826 | Active stock positions |
| #2 | ~879 | Active option positions |
| #3 | ~1019 | Additional query path |
| #4 | (fallback) | Direct lookup when JOIN fails |

All must use identical `row[N]` → field mappings.

---

## Known Special Cases

1. **`sizing_mode`**: NOT in `risk_fields` — correct, it only affects entry-time sizing
2. **`trade_summary_enabled`**: Not a risk field, consumed by P/L posting service
3. **`order_chase_enabled` / `entry_chase_enabled`**: In `risk_fields` for invalidation but consumed by the Order Chaser service, not the risk evaluation loop
4. **`broker_bracket_mode`**: Has computed properties (`allows_broker_sl`, `allows_broker_pt`) — any code consuming it should use these properties, not raw string comparison
5. **Row padding**: The fallback lookup does `while len(row) < 50: row.append(None)` — must increase this if adding fields beyond row[49]
6. **`ch_row` index ≠ `row` index**: The fallback query has a different column order than the main JOINed query — always verify both mappings when adding fields

---

## Verification Script

Run this to validate all fields are wired correctly:

```bash
python3 -c "
import sqlite3, re

# Check DB columns
conn = sqlite3.connect('bot_data.db')
c = conn.cursor()
c.execute('PRAGMA table_info(channels)')
db_cols = {r[1] for r in c.fetchall()}

# Expected risk fields
expected = [
    'profit_target_1_pct', 'profit_target_2_pct', 'profit_target_3_pct', 'profit_target_4_pct',
    'profit_target_qty_1', 'profit_target_qty_2', 'profit_target_qty_3', 'profit_target_qty_4',
    'profit_target_trim_pct_1', 'profit_target_trim_pct_2', 'profit_target_trim_pct_3', 'profit_target_trim_pct_4',
    'stop_loss_pct', 'trailing_stop_pct', 'trailing_activation_pct',
    'enable_early_trailing', 'early_trailing_activation_pct', 'early_trailing_step_pct',
    'exit_strategy_mode', 'trim_order_mode', 'sl_order_mode', 'broker_bracket_mode',
    'order_chase_enabled', 'entry_chase_enabled',
    'leave_runner_enabled', 'leave_runner_pct',
    'enable_dynamic_sl', 'dynamic_sl_profile', 'escalation_only_mode',
    'enable_giveback_guard', 'giveback_allowed_pct',
    'ema_risk_enabled', 'ema_period', 'ema_timeframe_minutes', 'ema_buffer_pct',
    'ema_exit_enabled', 'ema_escalation_enabled', 'ema_extended_hours', 'ema_use_underlying', 'ema_no_trend_candles',
    'risk_management_enabled', 'trade_summary_enabled'
]

missing = [f for f in expected if f not in db_cols]
print(f'DB columns: {\"ALL PRESENT\" if not missing else \"MISSING: \" + str(missing)}')

# Check update_channel allowed list
with open('gui_app/database.py', 'r') as f:
    content = f.read()
match = re.search(r'if key in \[(.*?)\]:', content, re.DOTALL)
if match:
    allowed = re.findall(r\"'([^']+)'\", match.group(1))
    missing_allowed = [f for f in expected if f not in allowed]
    print(f'update_channel: {\"ALL PRESENT\" if not missing_allowed else \"MISSING: \" + str(missing_allowed)}')

conn.close()
print('Validation complete.')
"
```

---

*Last verified: April 16, 2026 — 42 fields, all passing end-to-end.*
