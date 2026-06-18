# Webull Official — Execution Path Bug Tracker
**Date:** 2026-06-17  
**Version at analysis:** v12.1.5  
**Scope:** All execution paths — stock/option entry, PT exits, SL exits, Dynamic SL, SL escalation, trailing stop, EMA risk, all risk engine settings

---

## Status Legend
| Symbol | Meaning |
|--------|---------|
| 🔴 | Open — Critical/High, affects live trading |
| 🟡 | Open — Medium, latent or indirect |
| 🟢 | Fixed |
| ⬛ | Won't fix / informational |

---

## Critical & High — Live Trading Impact

### G-B1+B3 🟢 `position_effect` missing from option order legs
**File:** `src/brokers/webull_official/orders.py:81-90`  
**Severity:** Critical  
**Impact:** STC option orders have no `position_effect: CLOSE` in the leg. Webull API may default to OPEN, creating a **naked short** instead of closing the existing long.  
**Root cause:** `position_intent` param accepted by `place_option_order` but never written into the `legs[]` dict or the top-level order dict.  
**Fix:** Add `position_effect` to each leg: `"CLOSE"` for STC/BTC, `"OPEN"` for BTO/STO.  
**Fixed in:** commit pending

---

### G-E1 🟢 `_risk_management_order` not set for WEBULL_OFFICIAL in direct-exit path
**File:** `src/risk/position_monitor.py:8034`  
**Severity:** Critical  
**Impact:** Risk engine's direct-exit path (SL, PT, trailing) calls `place_option_order` without `_risk_management_order=True`. When broker position API returns stale empty list, RISK BYPASS gate at selfbot_webull.py:18668 rejects the order. **SL exits are silently dropped.**  
**Root cause:** Line 8034 checks `broker_upper in ('WEBULL', 'WEBULL_PAPER', 'SCHWAB')` — WEBULL_OFFICIAL excluded.  
**Fix:** Add `'WEBULL_OFFICIAL'` to the condition; inject `_risk_management_order=True` and `_signal_price_fallback`.  
**Fixed in:** commit pending

---

### G-B2 🟢 `_signal_price_fallback` not injected for WEBULL_OFFICIAL market exits
**File:** `src/risk/position_monitor.py:8034-8038`  
**Severity:** High  
**Impact:** When risk engine fires a market STC and `get_option_quote` returns 404, `effective_limit` is None → order hard-rejected: *"Options require a limit price."* Position stays open past SL.  
**Root cause:** `_signal_price_fallback` only injected for `('WEBULL', 'WEBULL_PAPER', 'SCHWAB')`, not WEBULL_OFFICIAL.  
**Fix:** Same block as G-E1 — inject `_signal_price_fallback=stc_signal['price']` when `order_price is None`.  
**Fixed in:** commit pending (same fix as G-E1)

---

### G-B6 🟢 PT replace uses hardcoded strike=0, expiry='', option_type='C'
**File:** `src/risk/position_monitor.py:~7295-7303`  
**Severity:** High  
**Impact:** After PT1 fills and PT2 needs to be placed, `_replace_pt_bracket_order` calls `place_option_order` with `strike=0, expiry='', option_type='C'` hardcoded. **All PT replacement orders fail for WEBULL_OFFICIAL options.** Position has no exit bracket after PT1.  
**Root cause:** `ChannelRiskSettings` has no `strike` attribute; hardcoded fallback never replaced with real position data.  
**Fix:** Thread `PositionSnapshot` into `_replace_pt_bracket_order`; use `position.strike`, `position.expiry`, `position.direction`.  
**Fixed in:** pending

---

### G-B5 🟢 Expiry format not normalized before sending to Webull API
**File:** `src/brokers/webull_official/broker.py:place_option_order`  
**Severity:** High  
**Impact:** Positions enriched via legacy Webull hub have expiry in `MM/DD` format. Webull API requires `YYYY-MM-DD`. Any STC/PT exit for such positions fails with invalid date error.  
**Root cause:** No normalization in `broker.py` before passing to `orders.py`.  
**Fix:** Normalize `effective_expiry` to `YYYY-MM-DD` inside `place_option_order`.  
**Fixed in:** commit pending

---

### G-B4 🟢 TIF hardcoded `DAY` for option buy side (copy-paste dead code)
**File:** `src/brokers/webull_official/broker.py:460`  
**Severity:** Medium  
**Code:** `tif = "DAY" if side == "SELL" else "DAY"` — both branches are `"DAY"`  
**Impact:** PT bracket orders that should be GTC expire at market close. Next morning position has no PT bracket.  
**Fix:** `tif = "DAY" if side == "SELL" else kwargs.get('time_in_force', 'GTC')`  
**Fixed in:** commit pending

---

### G-E3 🟢 New option positions not auto-subscribed to MQTT on discovery
**File:** `src/risk/position_monitor.py:_fetch_webull_official_positions`  
**Severity:** High  
**Impact:** Options entered during a session are not subscribed to MQTT price feed. SL monitoring uses REST polling (15s lag). In high-volatility gaps, position blows past SL before risk engine reacts.  
**Fix:** In `_fetch_webull_official_positions`, when a new option position is discovered, call `broker_instance.subscribe_symbol(raw_symbol, is_option=True)`.  
**Fixed in:** pending

---

## Medium — Latent / Indirect Impact

### G-D3 🟢 `option_id` in position dict is `position_id` string, not Webull numeric ID
**File:** `src/brokers/webull_official/broker.py:get_positions`  
**Severity:** High  
**Impact:** STC position match-by-option_id (selfbot_webull.py:18630) never matches for WEBULL_OFFICIAL. Falls through to fuzzy match every time, adding latency and fragility.  
**Fix:** Extract numeric Webull `ticker_id` / `optionId` from API response in `models.py` and expose in position dict.

---

### G-C1 🟢 Cancel order uses `client_order_id` but stored ID may be broker numeric ID
**File:** `src/brokers/webull_official/orders.py:cancel_order`  
**Severity:** Medium  
**Impact:** `OrderResult.order_id = result.order_id or result.client_order_id`. When Webull returns a numeric `order_id`, that's what gets stored. Cancel attempts with the numeric ID via `client_order_id` field will fail, leaving stale PT/SL orders alive.  
**Fix:** Ensure `client_order_id` (UUID, always locally known) is stored and used for all cancel calls. Store both IDs in `OrderResult`.

---

### G-F1 🟡 MQTT subscribes only `SNAPSHOT` sub_type — missing `QUOTE` for real-time bid/ask
**File:** `src/brokers/webull_official/streaming.py:subscribe`  
**Severity:** Medium  
**Impact:** `SNAPSHOT` delivers ~1Hz snapshots. Missing `QUOTE` means bid/ask for SL exit pricing may be stale. SL exits execute at `last` instead of live bid.  
**Fix:** Pass `sub_types=["SNAPSHOT", "QUOTE"]` for `US_OPTION` category subscriptions. Also subscribe MQTT topic `"tick"` in `_on_connect`.

---

### G-F3 🟢 `TradeEventPoller` polls only open orders — fills missed for fast-filling orders
**File:** `src/brokers/webull_official/streaming.py:TradeEventPoller`  
**Severity:** Medium  
**Impact:** Fast-filling orders transition PARTIAL→FILLED between 3-second polls. Fill callback never fires. Position sync misses the fill. Trade record not updated.  
**Fix:** Every N cycles (e.g., 5), call `get_order_history` for the past 10 minutes and emit any missed fills.

---

### G-A1 🟡 No position existence check before stock STC
**File:** `src/brokers/webull_official/broker.py:place_stock_order`  
**Severity:** Medium  
**Impact:** Duplicate STC signals can be sent after a position is already closed. Broker rejects silently with an error.  
**Fix:** For `side == "SELL"`, call `get_positions(max_age_seconds=10)` and verify symbol exists with qty > 0.

---

### G-G4 🟢 `get_order_history` implemented but never called for missed-fill detection
**File:** `src/brokers/webull_official/streaming.py:TradeEventPoller`  
**Impact:** See G-F3. Same fix.

---

### G-F2 🟡 Option MQTT snapshot delivers `close`, not `bid` — SL uses stale last price
**File:** `src/brokers/webull_official/broker.py:_on_mqtt_quote`  
**Severity:** Medium  
**Impact:** When only `close` is present in MQTT payload, `bid=0`, so SL exit limit is set from `last_price` (up to 15s stale).  
**Fix:** Fix addressed partially by G-F1 (add QUOTE sub_type). Also: in `_on_mqtt_quote`, fall back `bid = last` when `bid=0` so the exit has a meaningful price.

---

### G-A2 🟢 `stop_price` not precision-rounded for penny stocks
**File:** `src/brokers/webull_official/broker.py:place_stock_order`  
**Severity:** Low  
**Fix:** Apply same rounding to `stop_price` as `price` (2dp ≥$1, 4dp <$1).

---

### G-A3 🟢 No fractional quantity validation for option orders
**File:** `src/brokers/webull_official/orders.py:place_option_order`  
**Severity:** Low  
**Fix:** Cast `quantity` to `int` in `place_option_order`; raise `ValueError` for non-integer.

---

### G-G2 🟡 Native trailing stop not exposed in broker facade
**File:** `src/brokers/webull_official/broker.py`  
**Severity:** Low  
**Notes:** `orders.py:place_trailing_stop` implemented but no method in `broker.py`. Risk engine uses local trailing stop monitoring instead.

---

## Won't Fix / Informational

### G-B7 ⬛ Multi-leg / spread orders not supported
`option_strategy: "SINGLE"` always. Single-leg only. Not a bug — spreads not in scope.

### G-G5 ⬛ P&L is REST-based only (30s stale on dashboard)
No real-time P&L API available from Webull. Dashboard P&L lag is acceptable.

### G-G6 ⬛ `batch-place` already used correctly
`new_orders` array already supports batch semantics. No change needed.

---

## Risk Engine Coverage Matrix

| Risk Feature | WEBULL_OFFICIAL Path | Status |
|---|---|---|
| BTO stock entry | `place_stock_order` via worker | 🟢 Working |
| BTO option entry | `place_option_order` via worker | 🟡 G-B1 fixed |
| STC stock exit (signal) | `place_stock_order` via worker | 🟢 Working |
| STC option exit (signal) | `place_option_order` via worker | 🟡 G-B1 fixed |
| PT1 bracket (stock) | `place_stock_order` GTC limit | 🟢 Working |
| PT1 bracket (option) | `place_option_order` direct | 🟡 G-B4, G-B5 |
| PT2/PT3 cascade (option) | `_replace_pt_bracket_order` | 🔴 G-B6 broken |
| SL stock (native stop) | `place_stop_order` | 🟢 Working |
| SL option (local monitor) | `_build_stc_signal` → direct-exit | 🟡 G-E1, G-E3 |
| SL option (market order) | `place_option_order` price=None | 🟡 G-B2 fixed |
| Dynamic SL | local monitor, same exit path | 🟡 G-E1 fixed |
| SL escalation | local monitor, same exit path | 🟡 G-E1 fixed |
| Trailing stop (local) | local monitor, same exit path | 🟡 G-E1 fixed |
| Trailing stop (native) | NOT wired | 🟡 G-G2 |
| EMA risk (local) | price hub → risk engine check | 🟡 G-E3 (price lag) |
| MQTT streaming | `_on_mqtt_quote` → WebullDataHub | 🟡 G-F1, G-F2 |
| Fill detection | `TradeEventPoller` | 🟡 G-F3 |
| Cancel/replace PT | cancel + re-place | 🟡 G-C1, G-C2 |

---

## Fix History

| Date | Fix | Gaps Resolved |
|------|-----|---------------|
| 2026-06-17 | Price precision rounding in place_stock_order | LNKS/TGE failures |
| 2026-06-17 | RateLimiter asyncio.Lock lazy-init | LPA event loop error |
| 2026-06-17 | RISK BYPASS scoped to WEBULL_OFFICIAL only | G-code review F1+F2 |
| 2026-06-17 | option_id write sites use None not 0 | G-code review F3 |
| 2026-06-17 | G-B1+B3: position_effect in option legs | Naked short prevention |
| 2026-06-17 | G-E1+B2: _risk_management_order for WEBULL_OFFICIAL | SL exit dropout |
| 2026-06-17 | G-B5: Expiry normalization | MM/DD format rejections |
| 2026-06-17 | G-B4: TIF GTC for option buy side | PT bracket daily expiry |
| 2026-06-17 | G-B6: PT replace parses strike/expiry/direction from position_key | PositionCacheEntry lacks option metadata fields |
| 2026-06-17 | G-E3: Auto-subscribe new option positions to MQTT on discovery | 15s SL lag for new positions |
| 2026-06-17 | G-F3+G-G4: TradeEventPoller history catchup every 5 cycles | Missed fills for fast-filling orders |
| 2026-06-17 | G-D3: Expose option_id in get_positions() dict | Position match-by-id always fell through to fuzzy match |
| 2026-06-17 | G-C1: Return client_order_id (UUID) from place_*_order | Cancel/status calls always failed with broker numeric ID |
| 2026-06-17 | G-A2: stop_price precision rounding | Penny stock stop orders rejected with PRICE_PRECISION_EXCEED |
| 2026-06-17 | G-A3: int(quantity) guard in place_option_order | Fractional qty causes API rejection |
