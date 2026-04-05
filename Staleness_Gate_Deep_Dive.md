# Staleness Gate — Complete Technical Breakdown

This document traces the exact code path of the Staleness Gate system in `src/risk/position_monitor.py`. Every section references real line numbers and real variable names. No guesses.

---

## 1. What Is the Staleness Gate?

The Staleness Gate prevents the risk engine from executing **stop-loss type exits** (SL, trailing stop, dynamic SL, giveback guard, EMA exits) when the position price hasn't changed for a suspicious duration. The concern: a "frozen" or stale price (e.g., yesterday's closing price bleeding into the current session) could falsely trigger a stop loss.

**Profit target exits are NEVER blocked** — selling at a stale high is favorable.

---

## 2. Configuration Constants (lines 1387-1393)

```python
self._stuck_price_tracker = {}           # Tracks per-position price change history
self._STUCK_PRICE_THRESHOLD = 3          # Seconds before a price is considered "stuck" (triggers REST check)
self._STALENESS_EXIT_BLOCK_THRESHOLD = 10 # Seconds before staleness can block exits
self._rest_confirmed_this_cycle = {}     # Keys where REST found a DIFFERENT price this cycle
self._rest_validated_same = {}           # Keys where REST confirmed SAME price is real (60s TTL)
self._rest_repair_cycle_keys = {}        # Keys that had price repaired via REST this cycle
```

---

## 3. The Two-Phase System

The staleness gate operates in two phases that run **every monitoring cycle**:

| Phase | Function | When |
|-------|----------|------|
| **Phase 1: Detection & Validation** | `_detect_and_fix_stuck_prices()` | Runs FIRST, before any exit evaluation (line 2202) |
| **Phase 2: Exit Gating** | `_evaluate_exit_conditions()` | Runs SECOND, uses Phase 1 results to allow/block exits (line 3553) |

### Per-Cycle Reset (lines 2199-2202)
```python
self._rest_repair_cycle_keys.clear()      # Reset repair keys each cycle
self._rest_confirmed_this_cycle.clear()   # Reset REST-confirmed keys each cycle
# NOTE: _rest_validated_same is NOT cleared per cycle — it persists with 60s TTL
self._update_prices_from_hub(positions)
await self._detect_and_fix_stuck_prices(positions)  # Phase 1
```

---

## 4. Phase 1: Detection & Validation (`_detect_and_fix_stuck_prices`, line 6528)

### 4.1 Session-Based Timing

```python
rest_cooldown = 3.0 if session == 'regular' else (10.0 if session == 'extended' else 30.0)
_MAX_REST_REPAIRS_PER_CYCLE = 3  # Max price-change REST repairs per cycle
```

| Session | REST Cooldown | Stuck Threshold | Exit Block Threshold |
|---------|--------------|-----------------|---------------------|
| Regular | 3s | 3s | 10s |
| Extended | 10s | 15s | 300s |
| Closed | 30s | 3s | 10s |

### 4.2 Stuck Price Tracking (lines 6536-6575)

For each position, the tracker maintains:

```python
tracker = {
    'last_price': 1.88,        # Last known price
    'last_changed': 1712060000, # Timestamp when price last changed
    'rest_refreshed': 0,        # Timestamp of last REST check attempt
    'rest_checked_ok': 0        # Timestamp of last SUCCESSFUL REST response
}
```

**Price Change Detection (line 6547):**
```python
if abs(pos.current_price - tracker['last_price']) > 0.0001:
    tracker['last_price'] = pos.current_price
    tracker['last_changed'] = now          # Reset staleness clock
    tracker['rest_refreshed'] = 0          # Allow immediate REST check next time
    if key in self._rest_validated_same:
        del self._rest_validated_same[key]  # Clear validation when price moves
    continue  # Price moved — not stuck
```

**Example — SATL at $6.35 on Webull:**
```
t=0s:  Tracker created: {last_price: 6.35, last_changed: t0}
t=1s:  Price still $6.35 → stuck_seconds = 1 → below STUCK_PRICE_THRESHOLD (3s) → skip
t=2s:  Price still $6.35 → stuck_seconds = 2 → below threshold → skip
t=3s:  Price still $6.35 → stuck_seconds = 3 → ABOVE threshold → becomes a candidate
```

### 4.3 Extended Hours Prev-Close Detection (lines 6556-6566)

During extended hours, if price is >15% below entry and stuck for >2s, it's flagged as potentially stale (yesterday's closing price):

```python
if session == 'extended' and stuck_seconds >= 2:
    dev = abs(pos.current_price - entry) / entry
    if dev > 0.15 and pos.current_price < entry:
        # Force immediate REST refresh — likely prev-close leak
```

### 4.4 Candidate Processing — Cross-Hub Check (line 6581)

For each stuck candidate, the system first checks cross-broker streaming hubs for a fresh price:

```python
fresh_price = self._try_cross_hub_price(pos, now)
```

If the cross-hub returns the same price:
```python
if fresh_price and abs(fresh_price - pos.current_price) < 0.0001:
    _cross_hub_confirmed_same = True  # Same price from different source = evidence it's real
```

### 4.5 REST API Verification (lines 6588-6602)

If cross-hub found nothing different, REST is called:

```python
_already_validated = key in self._rest_validated_same
_rest_limit = _MAX_REST_REPAIRS_PER_CYCLE if not _already_validated else _MAX_REST_REPAIRS_PER_CYCLE + 4
if rest_repairs_this_cycle < _rest_limit:
    tracker['rest_refreshed'] = now              # Attempt timestamp (for cooldown)
    rest_price = await self._try_rest_quote(pos)
    _rest_checked = rest_price is not None
    if _rest_checked:
        tracker['rest_checked_ok'] = now          # Successful response timestamp (for escape hatch)
    if rest_price and rest_price > 0:
        fresh_price = rest_price
        if abs(rest_price - pos.current_price) > 0.0001:
            rest_repairs_this_cycle += 1           # Only price-CHANGE repairs count against quota
```

**REST Quota Rules:**
| Situation | Quota Limit |
|-----------|-------------|
| New stuck position (never validated) | 3 per cycle |
| Already validated position (re-validation) | 7 per cycle (3+4) |
| REST returns same price | Does NOT consume quota |
| REST returns different price | Consumes 1 quota |

### 4.6 `_try_rest_quote` — How REST Handles Same Price (line 6831)

This is the critical function that was fixed. It checks multiple REST sources in order:

**For a Webull position:**
```
1. Try Schwab REST API → if price differs from current → return immediately
2. Try Webull REST API  → if price differs from current → return immediately
3. Try broker get_quote  → if price differs from current → return immediately
4. If ALL returned valid prices but ALL matched current → return price with source='confirmed-same'
```

```python
_last_valid_rest = None
# ... each REST source ...
if price and price > 0:
    _last_valid_rest = price
    if abs(price - current) > 0.0001:
        return price  # DIFFERENT price — immediate return

# End of function — no source returned a different price
if _last_valid_rest and _last_valid_rest > 0:
    self._last_rest_source = 'confirmed-same'
    return _last_valid_rest  # Return the same-price value (NOT None)
return None  # Only returned if ALL REST calls failed entirely
```

**Example — SATL at $6.35, only Webull connected:**
```
1. Schwab REST → returns None (not connected)
2. Webull REST → returns $6.35 (same as current)
   → _last_valid_rest = 6.35
   → abs(6.35 - 6.35) = 0.0 → NOT > 0.0001 → don't return early
3. broker get_quote → returns $6.35 (same again)
   → _last_valid_rest = 6.35
4. End of function: _last_valid_rest = 6.35 > 0
   → return 6.35 with source='confirmed-same'
```

Result: `_rest_checked = True` (rest_price is not None)

### 4.7 REST Sanity Checks (lines 6603-6622)

Before accepting a REST price, two sanity checks run:

**Check 1 — Entry Deviation Guard:**
```python
if rest_deviation > 0.30 and streaming_deviation < 0.10:
    # REST says price is 30%+ from entry, but streaming says <10% from entry
    # REST is likely returning stale/wrong data → REJECT
    _sanity_rejected = True
```

**Check 2 — Price Jump Guard:**
```python
if price_jump > 0.30:
    # REST price is >30% different from streaming price
    # Suspicious jump → REJECT
    _sanity_rejected = True
```

### 4.8 Outcome: Price Fix vs. Validation (lines 6624-6643)

After REST check, two possible outcomes:

**Outcome A — Price Changed (REST found different price):**
```python
if fresh_price and abs(fresh_price - pos.current_price) > 0.0001:
    pos.current_price = fresh_price                   # Update position with fresh price
    tracker['last_changed'] = now                      # Reset staleness clock
    self._rest_repair_cycle_keys[key] = now            # Mark as repaired this cycle
    self._rest_confirmed_this_cycle[key] = now         # Mark as REST-confirmed
```
Log: `[RISK] 🔄 STUCK PRICE FIX (REST/Schwab): WEBULL SATL was $5.90 (frozen 15s) → $6.35`

**Outcome B — Price Same (REST confirmed same price is real):**
```python
elif stuck_seconds >= 10 and not _sanity_rejected and (_rest_checked or _cross_hub_confirmed_same):
    self._rest_validated_same[key] = now
```
Log: `[RISK] ✓ PRICE VALIDATED (REST): WEBULL SATL frozen 15s — confirmed price $6.3500 is real (same from all sources)`

**Example — SATL at $6.35, Webull only, price unchanged for 12s:**
```
Phase 1 runs:
1. Cross-hub check → nothing (no other brokers)
2. REST check → returns $6.35 (same price, source='confirmed-same')
3. _rest_checked = True
4. abs(6.35 - 6.35) = 0 → NOT > 0.0001 → Outcome A skipped
5. stuck_seconds = 12 >= 10 ✓, not sanity_rejected ✓, _rest_checked = True ✓
6. → _rest_validated_same[key] = now
7. Log: "✓ PRICE VALIDATED (REST): ... confirmed price $6.3500 is real"
```

### 4.9 Validation TTL & Cleanup (lines 6666-6673)

```python
# Remove validations for positions that no longer exist
stale_validated = [k for k in self._rest_validated_same if k not in active_keys]

# Expire validations older than 60 seconds
_ttl_expired = [k for k, ts in self._rest_validated_same.items()
                if (time.time() - ts) > 60]
```

After 60s, the validation expires. On the next cycle, if the price is still stuck, `_detect_and_fix_stuck_prices` runs REST again and re-validates. This re-validation does NOT consume the main REST quota (already-validated positions get +4 extra quota).

---

## 5. Phase 2: Exit Gating (`_evaluate_exit_conditions`, line 3553)

### 5.1 Key Lookups (lines 3553-3557)

```python
_repair_key = f"{position.broker}_{position.symbol}_{position.asset}"
# e.g., "WEBULL_SATL_stock"

_is_repair_cycle = _repair_key in self._rest_repair_cycle_keys
# True if REST found a DIFFERENT price this cycle (price was actually wrong)

_is_rest_confirmed = _repair_key in self._rest_confirmed_this_cycle
# True if REST found a DIFFERENT price this cycle (used for repair cycle override)

_is_rest_validated_same = _repair_key in self._rest_validated_same
# True if REST confirmed SAME price is real (set in Phase 1, persists up to 60s)
```

### 5.2 Freshness Guard (lines 3559-3561)

Before staleness logic, a first-cycle freshness check runs:

```python
freshness_result = self._check_price_freshness(position, cache, channel_settings)
if freshness_result is not None:
    return freshness_result  # Block or allow based on freshness
```

This catches a specific edge case: during **extended hours only**, if the current price shows a loss >1.5x the SL percentage, it's likely yesterday's close leaking through. The system checks streaming hubs for a fresh price. If streaming confirms the price is NOT actually that far down, the stale price is blocked.

**Example — Entry $10.00, SL 10%, current price $8.00 during pre-market:**
```
deviation = ($10.00 - $8.00) / $10.00 = 20%
sl_pct * 1.5 = 10% * 1.5 = 15%
20% > 15% → suspicious
→ Check Webull/Schwab/IBKR streaming hubs for fresh price
→ If hub says $9.85 (only 1.5% loss) → price was stale, BLOCK false SL
→ If hub says $7.90 (21% loss) → price is confirmed bad, ALLOW SL
```

### 5.3 Staleness Decision Tree (lines 3563-3598)

```python
_staleness_is_blocking = False
_rest_override_available = _is_rest_confirmed or _is_rest_validated_same
```

The decision tree:

```
Is price stuck (tracker exists)?
├── NO → _staleness_is_blocking = False (price is moving, no issue)
│
└── YES → How long has it been unchanged?
    │
    ├── change_age <= threshold (10s regular / 300s extended)?
    │   └── _staleness_is_blocking = False (not stuck long enough to worry)
    │
    └── change_age > threshold?
        │
        ├── _rest_override_available = True?
        │   └── _staleness_is_blocking = False
        │   └── Log: "✓ STALENESS OVERRIDE: SATL price $6.35 stale 25s but REST-validated same — allowing SL evaluation"
        │
        ├── change_age > 90s AND rest_checked_ok > 0?
        │   └── _staleness_is_blocking = False (ESCAPE HATCH)
        │   └── Log: "✓ MAX STALENESS OVERRIDE: SATL price $6.35 unchanged 95s — REST checked, allowing SL evaluation (90s safety limit)"
        │
        └── Neither override available?
            └── _staleness_is_blocking = True (BLOCKING)
```

### 5.4 What Gets Blocked vs. Allowed When Staleness IS Blocking

| Exit Type | Blocked? | Line | Reason |
|-----------|----------|------|--------|
| Price-based Stop Loss | YES | 3620 | `risk_trigger in ('stop_loss', 'stop_loss_price')` |
| Channel Stop Loss | YES | 3642 | `_staleness_is_blocking` check |
| Dynamic SL | YES | 3705 | `_is_sl_type` check (contains 'sl') |
| Trailing Stop | YES | 3734 | Explicit `_staleness_is_blocking` check |
| Early Trailing Stop | YES | 3705 | `_is_sl_type` check (contains 'early_trailing') |
| Giveback Guard | YES | 3705 | `_is_sl_type` check (contains 'giveback') |
| EMA Exit | YES | 3705 | `_is_sl_type` check (contains 'ema_exit') |
| EMA No-Trend Exit | YES | 3705 | `_is_sl_type` check (contains 'ema_no_trend') |
| **Profit Target** | **NO** | 3631 | Explicit bypass with log: "selling at stale HIGH is favorable" |
| **Tiered Profit Targets** | **NO** | 3660+ | Evaluated after staleness checks, not gated |

### 5.5 Repair Cycle Guard (lines 3616, 3632, 3646-3650)

When REST found a DIFFERENT price and repaired it this cycle (`_is_repair_cycle = True`), all SL-type exits are blocked UNLESS `_is_rest_confirmed = True`. This prevents executing a stop loss on a price that was just corrected — the corrected price needs to be evaluated first.

```python
_allow_eval = not _is_repair_cycle or _is_rest_confirmed
```

---

## 6. Complete Example Walkthroughs

### Example A: SATL $6.35 on Webull — Low Liquidity, Price Unchanged (Regular Hours)

This is the exact v8.1.8 failure scenario that is now fixed.

```
Cycle 1 (t=0):
  Phase 1: Tracker created for WEBULL_SATL_stock: {last_price: 6.35, last_changed: t0}
  Phase 2: No tracker staleness (brand new) → _staleness_is_blocking = False
  → Exits allowed normally

Cycle 2 (t=1.5s):
  Phase 1: Price still $6.35 → stuck_seconds = 1.5 → below STUCK_PRICE_THRESHOLD (3s) → no REST check
  Phase 2: change_age = 1.5 → below STALENESS_EXIT_BLOCK_THRESHOLD (10s)
  → _staleness_is_blocking = False → exits allowed

Cycle 3 (t=3.5s):
  Phase 1: stuck_seconds = 3.5 → above STUCK_PRICE_THRESHOLD (3s)
  → Cross-hub: no other broker connected → nothing
  → REST: _try_rest_quote(SATL)
    → Schwab REST: not connected → None
    → Webull REST: returns $6.35 (bid/ask midpoint)
    → _last_valid_rest = 6.35, same as current → source='confirmed-same'
    → rest_price = 6.35
  → _rest_checked = True
  → tracker['rest_checked_ok'] = now
  → abs(6.35 - 6.35) = 0 → NOT a price fix
  → stuck_seconds = 3.5 < STALENESS_EXIT_BLOCK_THRESHOLD (10) → validation not set yet
  Phase 2: change_age = 3.5 → below threshold (10s) → _staleness_is_blocking = False → exits allowed

Cycle 4 (t=6s):
  Phase 1: stuck_seconds = 6 → above 3s → REST cooldown = 3s, last REST was 3.5s → elapsed 2.5s < 3s
  → REST skipped (cooldown)
  Phase 2: change_age = 6 → below 10s → exits allowed

Cycle 5 (t=8s):
  Phase 1: stuck_seconds = 8 → REST cooldown elapsed → REST check again
  → REST returns $6.35 again → _rest_checked = True, tracker['rest_checked_ok'] = now
  → stuck_seconds = 8 < 10 → validation not set yet
  Phase 2: change_age = 8 → below 10s → exits allowed

Cycle 6 (t=11s):
  Phase 1: stuck_seconds = 11 → REST check
  → REST returns $6.35 → _rest_checked = True
  → stuck_seconds = 11 >= 10 → _rest_validated_same[WEBULL_SATL_stock] = now  ← VALIDATED
  → Log: "✓ PRICE VALIDATED (REST): WEBULL SATL frozen 11s — confirmed price $6.3500 is real"
  Phase 2:
  → _is_rest_validated_same = True
  → _rest_override_available = True
  → change_age = 11 > threshold (10)
  → _rest_override_available is True → _staleness_is_blocking = False
  → Log: "✓ STALENESS OVERRIDE: SATL price $6.35 stale 11s but REST-validated same — allowing SL evaluation"
  → ALL EXITS ALLOWED (including SL)

Subsequent cycles:
  Every 3s, REST is re-checked. Validation persists for 60s, then re-validated.
  If validation expires before next REST check, the 90s escape hatch catches it.
```

### Example B: COCP $1.88 on Webull — Price Changes Then Freezes

```
Cycle 1 (t=0):
  Tracker: {last_price: 1.88, last_changed: t0}

Cycle at t=5s:
  Price changed to $1.90 → tracker reset: {last_price: 1.90, last_changed: t5}
  → _rest_validated_same cleared for this key

Cycle at t=8s (price still $1.90):
  stuck_seconds = 3 → REST check → returns $1.90 → same → _rest_checked = True
  → stuck_seconds = 3 < 10 → validation not set

Cycle at t=15s:
  stuck_seconds = 10 → REST check → returns $1.90 → same → _rest_validated_same set
  → Phase 2: override available → exits allowed

Cycle at t=17s:
  Price changes to $1.86 → tracker reset, _rest_validated_same cleared
  → Staleness clock starts over from scratch
```

### Example C: SPY $550.00 on Schwab — Active Stock, Price Always Moving

```
Every cycle: abs(current - tracker.last_price) > 0.0001 → tracker reset
→ _staleness_is_blocking never becomes True
→ All exits always allowed (staleness gate never engages)
```

### Example D: GV $0.41 on Webull — REST Fails to Return Price

```
Cycle at t=3s:
  REST check → all REST sources return None (connectivity issue)
  → _rest_checked = False → rest_checked_ok not set

Cycle at t=11s:
  REST check → still returns None
  → _rest_checked = False
  → stuck_seconds = 11 >= 10, BUT _rest_checked = False AND _cross_hub_confirmed_same = False
  → _rest_validated_same NOT set

Phase 2:
  → _rest_override_available = False
  → change_age = 11 > threshold (10)
  → _rest_override_available? No
  → change_age > 90? No (only 11s)
  → _staleness_is_blocking = True → SL exits BLOCKED

Cycle at t=50s:
  REST finally returns $0.41 → _rest_checked = True → rest_checked_ok set
  → _rest_validated_same set → override available → exits unblocked

IF REST NEVER SUCCEEDS:
  At t=91s: change_age > 90 AND rest_checked_ok = 0 → escape hatch NOT triggered
  → Remains blocked (correct — cannot confirm price is real without any REST response)
```

### Example E: TSLA $180.00 on Webull — Extended Hours, Price Frozen

Extended hours uses a 300s threshold:

```
Cycle at t=3s:  stuck → REST check → same price → _rest_checked = True
Cycle at t=11s: _rest_validated_same set (stuck_seconds >= 10)

Phase 2:
  session = 'extended' → _effective_threshold = 300
  change_age = 11 → 11 < 300 → below threshold → _staleness_is_blocking = False
  → Exits allowed (threshold not even reached in extended hours until 300s)

Cycle at t=301s (if price truly unchanged for 5 minutes):
  change_age = 301 > 300 → threshold exceeded
  → _rest_override_available = True (re-validated via REST)
  → _staleness_is_blocking = False → exits allowed

Note: Between 10s-300s in extended hours, a separate check (lines 3596-3612) also runs:
  → Webull hub get_quote_price confirms price within 2% → bypass logged
```

### Example F: Multiple Stuck Positions — REST Quota

```
4 positions stuck simultaneously: SATL, CYCN, GV, COCP (all Webull, all unchanged)

Cycle processing (sorted by longest stuck first):
  SATL (stuck 45s): REST → same price → _rest_checked ✓ → quota NOT consumed (same price)
  CYCN (stuck 30s): REST → same price → _rest_checked ✓ → quota NOT consumed
  GV   (stuck 25s): REST → same price → _rest_checked ✓ → quota NOT consumed
  COCP (stuck 20s): REST → same price → _rest_checked ✓ → quota NOT consumed

rest_repairs_this_cycle = 0 (only price CHANGES consume quota)
→ ALL 4 positions get REST-checked
→ ALL 4 get _rest_validated_same set
→ ALL 4 have exits unblocked
```

### Example G: Profit Target Hit While Staleness Is Blocking

```
SATL at $6.35, entry $5.50, PT1 = 20% ($6.60), SL = 10% ($4.95)
Price frozen at $6.65 for 15s (above PT1)
REST returns None (connectivity issue)
→ _staleness_is_blocking = True

Phase 2 evaluates:
  evaluate_price_based_stops → decision: profit_target exit
  → risk_trigger = 'profit_target'
  → Check: _staleness_is_blocking AND risk_trigger in ('stop_loss', 'stop_loss_price')? → NO
  → Falls to else:
    → _staleness_is_blocking AND risk_trigger == 'profit_target'? → YES
    → Log: "✓ STALENESS BYPASS: SATL profit target hit — allowing exit despite 15s stale price (selling at stale HIGH is favorable)"
    → return decision → EXIT EXECUTES
```

---

## 7. The Three Safety Layers

| Layer | Trigger | Effect | Max Wait |
|-------|---------|--------|----------|
| **REST Validated Same** | REST returns same price after 10s stuck | `_rest_override_available = True` | ~13s (3s threshold + 10s block threshold) |
| **Cross-Hub Confirmed** | Different broker's streaming shows same price | `_rest_override_available = True` | ~13s |
| **90s Escape Hatch** | Price unchanged 90s + at least one successful REST response | Force-allow exits | 90s absolute maximum |

### Layer Priority in the Decision Tree (line 3575-3598):

```
change_age > threshold?
  ├── _rest_override_available?         → ALLOW (Layer 1 or 2)
  ├── change_age > 90 + rest_checked_ok? → ALLOW (Layer 3 — escape hatch)
  └── Neither?                          → BLOCK
```

---

## 8. What Was Broken in v8.1.8 and Why

In version 8.1.8, `_try_rest_quote` returned `None` when REST confirmed the same price:

```python
# OLD CODE (v8.1.8):
if price and price > 0 and abs(price - current) > 0.0001:
    return price
# ... all sources checked ...
return None   # ← Same price = None = REST didn't "find" anything
```

This caused:
- `_rest_checked = False` (rest_price was None)
- `_rest_validated_same` never set (required `_rest_checked = True`)
- `_rest_override_available` always False
- `_staleness_is_blocking` always True after 10s
- **All SL exits blocked indefinitely**

The fix (current code):
```python
# NEW CODE:
_last_valid_rest = None
if price and price > 0:
    _last_valid_rest = price
    if abs(price - current) > 0.0001:
        return price  # Different price — return immediately
# ... all sources checked ...
if _last_valid_rest and _last_valid_rest > 0:
    self._last_rest_source = 'confirmed-same'
    return _last_valid_rest  # ← Same price returned as confirmation
return None  # Only if ALL REST calls failed entirely
```

---

## 9. Log Messages Quick Reference

| Log Message | Meaning | Exits Allowed? |
|-------------|---------|----------------|
| `✓ STALENESS OVERRIDE: ... REST-validated same — allowing SL evaluation` | REST confirmed same price is real | YES |
| `✓ STALENESS OVERRIDE: ... REST-confirmed fresh — allowing SL evaluation` | REST found a different (fresh) price | YES |
| `✓ MAX STALENESS OVERRIDE: ... unchanged 95s — REST checked, allowing SL evaluation (90s safety limit)` | 90s escape hatch triggered | YES |
| `✓ PRICE VALIDATED (REST): ... confirmed price $X is real` | Phase 1 set _rest_validated_same | YES (next cycle) |
| `🔄 STUCK PRICE FIX (REST/Schwab): ... was $X → $Y` | Phase 1 corrected the price | YES |
| `🛡️ STALENESS GATE: ... blocking STOP LOSS exit` | Staleness is blocking | NO (SL blocked) |
| `🛡️ STALENESS GATE: ... blocking channel STOP LOSS exit` | Channel SL blocked by staleness | NO |
| `🛡️ STALENESS GATE: ... blocking enhanced risk exit` | Dynamic SL/trailing/etc blocked | NO |
| `🛡️ STALENESS GATE: ... blocking trailing stop exit` | Trailing stop blocked | NO |
| `✓ STALENESS BYPASS: ... profit target hit — allowing exit` | Profit target on stale price | YES |
| `🛡️ REST SANITY REJECT: ... rejecting stale REST price` | REST price failed sanity check | N/A (REST ignored) |
| `🛡️ FRESHNESS GUARD: ... BLOCKING false SL exit` | First-cycle freshness guard | NO (first cycle only) |
