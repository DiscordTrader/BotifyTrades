# Risk Engine — Price Sourcing, Exit Timing, and Staleness Gate Flow

This document covers the complete journey of how the risk engine gets prices, detects frozen prices, switches between sources, and exactly when exits (profit targets and stop losses) execute — all traced from the actual code in `src/risk/position_monitor.py`.

---

## Table of Contents

1. [Monitoring Cycle — The Heartbeat](#1-monitoring-cycle--the-heartbeat)
2. [Step 1: Hub Price Overlay — Instant Streaming Prices](#2-step-1-hub-price-overlay--instant-streaming-prices)
3. [Step 2: Stuck Price Detection — When Does REST Kick In?](#3-step-2-stuck-price-detection--when-does-rest-kick-in)
4. [Step 3: Exit Evaluation — Staleness Gate Decision](#4-step-3-exit-evaluation--staleness-gate-decision)
5. [Complete Timeline: Profit Target Hit](#5-complete-timeline-profit-target-hit)
6. [Complete Timeline: Stop Loss Hit](#6-complete-timeline-stop-loss-hit)
7. [Complete Timeline: Price Truly Frozen (Low Liquidity)](#7-complete-timeline-price-truly-frozen-low-liquidity)
8. [Complete Timeline: Price Actually Stale (Wrong Price)](#8-complete-timeline-price-actually-stale-wrong-price)
9. [All Price Sources and Their Speeds](#9-all-price-sources-and-their-speeds)
10. [Staleness Gate — Where It Sits in the Path](#10-staleness-gate--where-it-sits-in-the-path)
11. [Summary Timing Table](#11-summary-timing-table)

---

## 1. Monitoring Cycle — The Heartbeat

The risk engine runs in a continuous loop. Each iteration is one "cycle."

**Cycle interval** (line 1997-2036):

| Situation | Interval | How |
|-----------|----------|-----|
| Fill watch active (just placed an order) | **0.5s** | Rapid polling to detect fills |
| Custom setting in GUI (`risk_check_interval_seconds`) | **0.2s – 60s** | User-configurable |
| Default (positions open, no fill watch) | **1s** | `DEFAULT_MONITORING_INTERVAL = 1` |
| No positions, risk disabled | **5s** | Standby mode |

**Early Wake** (lines 1877-1917): Even during the sleep between cycles, the engine checks every **50ms** for order events from streaming hubs (Webull/Schwab/IBKR). If an order event arrives (fill, cancel, etc.), the cycle wakes early and runs immediately — no waiting for the next 1s tick.

### What happens in each cycle (lines 2199-2202):

```
Every ~1 second:
  ┌──────────────────────────────────────────────────────────┐
  │  1. Clear per-cycle state                                │
  │     _rest_repair_cycle_keys.clear()                      │
  │     _rest_confirmed_this_cycle.clear()                   │
  │                                                          │
  │  2. _update_prices_from_hub(positions)    ← STEP 1       │
  │     Overlay streaming prices from ALL connected hubs     │
  │                                                          │
  │  3. _detect_and_fix_stuck_prices(positions) ← STEP 2     │
  │     Check for frozen prices, try cross-hub + REST        │
  │                                                          │
  │  4. For each position:                                   │
  │     _evaluate_exit_conditions()           ← STEP 3       │
  │     Staleness gate + exit checks                         │
  └──────────────────────────────────────────────────────────┘
```

---

## 2. Step 1: Hub Price Overlay — Instant Streaming Prices

**Function**: `_update_prices_from_hub()` (line 7010)  
**Speed**: Instant — reads from in-memory cache, zero API calls  
**Runs**: Every cycle, FIRST thing

This is the **primary price source**. Each broker's positions get prices from their own streaming hub, then positions without hub updates get prices from other brokers' hubs (cross-broker sourcing).

### Hub Cascade Order for Same-Broker Positions:

Each position's price is updated from **its own broker's streaming hub** first:

| Position Broker | Primary Hub | Streaming Method |
|-----------------|-------------|------------------|
| Webull | Webull Data Hub | MQTT real-time stream |
| Schwab | Schwab Data Hub | WebSocket real-time stream |
| IBKR | IBKR Data Hub | `ib_insync` native events |
| Tastytrade | Tastytrade Data Hub | DXLink WebSocket stream |
| Trading212 | T212 Data Hub | Portfolio-based price cache |

### Cross-Broker Fallback (lines 7232-7357):

If a position's **own hub didn't have a fresh price**, the system tries OTHER broker hubs:

```
Position on Schwab but Schwab hub has no price for this symbol?
  → Try Webull hub (if streaming)
  → Try IBKR hub (if streaming)
  → Try Tastytrade hub (if streaming)
  → Try T212 hub (if available)
  → Pick the freshest one (by quote timestamp)
```

### Freshness Rules:

```python
_HUB_PRICE_MAX_AGE = 30  # seconds (line 6281)
```

- `_get_fresh_hub_price(hub, symbol, max_age=30)` — Only uses a hub price if the quote timestamp is less than 30 seconds old (line 6468-6489)
- For cross-hub stuck-price checks: `max_age=2` — much stricter, only accepts quotes received within last 2 seconds (line 6808, 6813)
- Hub must be "live" to be used for cross-hub: requires actual tick receipt (`_last_quote_ts > 0`) and recency within 120s (lines 6767-6774)

### Price Priority Logic:

```python
# For each quote, price is extracted in this order (lines 6478-6488):
1. quote.last       → Last trade price (if > 0)
2. (bid + ask) / 2  → Mid-point (if both > 0)
3. bid              → Bid only (if > 0)
4. ask              → Ask only (if > 0)
```

### REST Repair Guard (lines 7060-7066):

If `_detect_and_fix_stuck_prices` recently corrected a price via REST, the hub overlay **will NOT overwrite it** for up to `_HUB_PRICE_MAX_AGE` (30s) — UNLESS the hub price materially differs (>0.5% from the repaired price), indicating the stream has genuinely recovered.

**Bottom line**: After `_update_prices_from_hub`, every position has the freshest streaming price available. This happens in-memory with **zero API calls** and takes **<1ms**.

---

## 3. Step 2: Stuck Price Detection — When Does REST Kick In?

**Function**: `_detect_and_fix_stuck_prices()` (line 6528)  
**Runs**: Every cycle, AFTER hub overlay  
**Purpose**: Detect prices that haven't moved and try harder sources

### 3.1 How "Stuck" Is Detected

For every position, a tracker records the last time the price **actually changed** (by more than $0.0001):

```python
tracker = {
    'last_price': 6.35,         # Current price
    'last_changed': timestamp,  # When it last changed
    'rest_refreshed': 0,        # Last REST attempt time
    'rest_checked_ok': 0        # Last SUCCESSFUL REST response time
}
```

Each cycle: if `abs(current_price - tracker.last_price) > 0.0001`, the clock resets. If not, `stuck_seconds` grows.

### 3.2 Timing Thresholds — When REST Is Triggered

| Session | Stuck Threshold (triggers REST) | REST Cooldown | REST Sources Tried |
|---------|---------------------------------|---------------|-------------------|
| **Regular hours** | **3 seconds** | 3s between attempts | Cross-hub → Schwab REST → Webull REST → broker get_quote |
| **Extended hours** | **15 seconds** | 10s between attempts | Same cascade |
| **Market closed** | **3 seconds** | 30s between attempts | Same cascade |

### 3.3 The Complete REST Cascade

When a price is stuck beyond the threshold, the system tries sources in this order:

```
STEP A: Cross-Hub Streaming Check (line 6581)
  → Try ALL other brokers' streaming hubs (not the position's own broker)
  → Hub must be live (_is_hub_live) and quote must be <2s old
  → Cascade: Webull → Schwab → IBKR → T212
  → If any returns a DIFFERENT price → use it immediately
  → If any returns SAME price → note as cross_hub_confirmed_same

STEP B: REST API Check (line 6593) — only if cross-hub didn't find different price
  → For Webull position: try Schwab REST → Webull REST → broker get_quote
  → For Schwab position: try Webull REST → Schwab REST → broker get_quote
  → For other brokers: try Schwab REST → Webull REST → broker get_quote
  → Each REST source: if returns DIFFERENT price → return immediately
  → If ALL return SAME price → return price with source='confirmed-same'
  → If ALL fail (no response) → return None

STEP C: Sanity Checks (lines 6603-6622) — on any REST price found
  → Reject if REST price is >30% from entry AND streaming is <10% from entry
  → Reject if REST price is >30% jump from streaming price
```

### 3.4 What Happens After REST Check

**If REST found a DIFFERENT price** (line 6624):
```
→ Position price updated to new price
→ Stuck tracker clock reset
→ _rest_repair_cycle_keys[key] set (marks repair happened)
→ _rest_confirmed_this_cycle[key] set (marks REST confirmed)
→ _rest_repaired_prices[key] set (protects from hub re-overwrite for 30s)
→ Any existing _rest_validated_same cleared
→ Log: "🔄 STUCK PRICE FIX (REST/Schwab): ... was $X → $Y"
```

**If REST confirmed SAME price AND stuck ≥ 10s** (line 6638):
```
→ _rest_validated_same[key] set (persists up to 60s TTL)
→ Log: "✓ PRICE VALIDATED (REST): ... confirmed price $X is real"
```

**If REST failed entirely (all sources returned None)**:
```
→ Nothing set
→ _rest_checked = False
→ No validation, no repair
```

### 3.5 REST Quota

```python
_MAX_REST_REPAIRS_PER_CYCLE = 3  # Per-cycle limit (line 6533)
```

| REST Result | Counts Against Quota? |
|-------------|----------------------|
| Returns DIFFERENT price (actual repair) | YES — +1 to quota |
| Returns SAME price (validation) | NO — does not consume quota |
| Already-validated position re-checking | Uses expanded limit: 3 + 4 = 7 |

This means: even if 10 positions are all stuck at the same time, same-price validations never block each other. Only actual price corrections (rare) consume the 3-per-cycle limit.

---

## 4. Step 3: Exit Evaluation — Staleness Gate Decision

**Function**: `_evaluate_exit_conditions()` (line 3553)  
**Runs**: For EACH position, AFTER Steps 1 and 2  
**Purpose**: Check all exit conditions, with the staleness gate as a safety layer

### 4.1 State Available at This Point

By the time exit evaluation runs, the position already has:
- The freshest hub streaming price (from Step 1)
- Any stuck price correction or validation (from Step 2)
- These flags set from Step 2:

```python
_is_repair_cycle       # REST found different price this cycle
_is_rest_confirmed     # REST confirmed (different price found)
_is_rest_validated_same # REST confirmed same price is real (60s TTL)
_rest_override_available = _is_rest_confirmed OR _is_rest_validated_same
```

### 4.2 Freshness Guard — First Check (line 3559)

Before staleness, a one-time freshness check runs for extended hours:

```
Is this extended hours AND current price shows loss >1.5x the SL percentage?
├── YES → Check streaming hubs for fresh price
│   ├── Fresh price shows loss < SL% → "price was prev close" → BLOCK exit, update price
│   ├── Fresh price confirms loss → ALLOW exit
│   └── No fresh price available → defer 1 cycle, then allow
└── NO → Continue to staleness check
```

### 4.3 The Staleness Gate Decision Tree (lines 3563-3598)

```
Does a stuck tracker exist for this position?
│
├── NO → staleness_is_blocking = False → ALL exits allowed
│
└── YES → How long unchanged (change_age)?
    │
    ├── change_age ≤ threshold (10s regular / 300s extended)?
    │   → staleness_is_blocking = False → ALL exits allowed
    │
    └── change_age > threshold?
        │
        ├── _rest_override_available = True? (REST confirmed or validated)
        │   → staleness_is_blocking = False → ALL exits allowed
        │   → Log: "✓ STALENESS OVERRIDE: ... REST-validated same — allowing SL evaluation"
        │
        ├── change_age > 90s AND rest_checked_ok > 0? (escape hatch)
        │   → staleness_is_blocking = False → ALL exits allowed
        │   → Log: "✓ MAX STALENESS OVERRIDE: ... unchanged 95s — REST checked, allowing SL (90s safety limit)"
        │
        └── Neither override?
            → staleness_is_blocking = True → SL-type exits BLOCKED, PTs ALLOWED
```

### 4.4 Which Exits Are Affected

When `_staleness_is_blocking = True`:

| Exit Type | What Happens |
|-----------|-------------|
| **Profit Target** | **ALWAYS ALLOWED** — selling at a stale high is favorable (line 3631) |
| **Tiered Profit Targets (PT1-PT4)** | **ALWAYS ALLOWED** — evaluated after staleness checks |
| Stop Loss (price-based) | **BLOCKED** until fresh price (line 3620) |
| Channel Stop Loss | **BLOCKED** (line 3642) |
| Dynamic SL | **BLOCKED** (line 3705) |
| Trailing Stop | **BLOCKED** (line 3734) |
| Early Trailing Stop | **BLOCKED** (line 3705) |
| Giveback Guard | **BLOCKED** (line 3705) |
| EMA Cross Exit | **BLOCKED** (line 3705) |

### 4.5 Repair Cycle Guard (line 3616)

When REST found a DIFFERENT price and corrected it this cycle:

```python
_allow_eval = not _is_repair_cycle or _is_rest_confirmed
```

If price was just corrected, the exit uses the NEW (corrected) price — it's allowed because `_is_rest_confirmed` is also set whenever `_is_repair_cycle` is set.

---

## 5. Complete Timeline: Profit Target Hit

**Scenario**: AAPL bought at $180, PT1 at 5% ($189), price streaming from Webull hub at $190.

```
t=0.0s  Cycle starts
t=0.0s  Step 1: _update_prices_from_hub → Webull hub has $190.00 → position.current_price = 190.00
t=0.0s  Step 2: _detect_and_fix_stuck_prices → price just changed → tracker resets (not stuck)
t=0.0s  Step 3: _evaluate_exit_conditions
         → _staleness_is_blocking = False (price is moving)
         → evaluate_price_based_stops → PT1 hit ($190 > $189)
         → decision.should_exit = True, risk_trigger = 'profit_target'
         → _staleness_is_blocking? False → doesn't matter
         → EXIT EXECUTES IMMEDIATELY
```

**Time from price received to exit decision**: **< 1ms** (same cycle)  
**Time from price change to exit**: **≤ 1 second** (next monitoring cycle)

**What if price is frozen at $190 for 15 seconds?**

```
t=15s   _staleness_is_blocking = True (no REST override available)
        BUT: risk_trigger = 'profit_target'
        → Check: _staleness_is_blocking AND trigger in ('stop_loss', 'stop_loss_price')? → NO
        → "STALENESS BYPASS: profit target hit — allowing exit despite 15s stale price"
        → EXIT EXECUTES — profit targets are NEVER blocked
```

---

## 6. Complete Timeline: Stop Loss Hit

**Scenario**: TSLA bought at $200, SL at 5% ($190), price drops to $189 on Schwab.

### Case A: Price Is Moving (Normal Case)

```
t=0.0s  Step 1: Schwab hub has $189.00 → position.current_price = 189.00
t=0.0s  Step 2: Price changed from $191 → tracker resets (stuck_seconds = 0)
t=0.0s  Step 3: Staleness gate check
         → change_age = 0 → below threshold (10s) → _staleness_is_blocking = False
         → evaluate_price_based_stops → SL hit ($189 < $190)
         → EXIT EXECUTES IMMEDIATELY
```

**Time to exit**: **≤ 1 second** from price drop

### Case B: Price Frozen at $189 (Hub Stops Updating)

```
t=0s    Price = $189, tracker starts. Not stuck yet.
t=1s    Same price. stuck_seconds=1. Below 3s threshold. No REST.
         → Staleness gate: change_age=1 < 10s → not blocking → SL EXITS ALLOWED
t=3s    stuck_seconds=3 → ABOVE 3s threshold
         → Cross-hub check: try Webull hub → finds $189.10 → DIFFERENT!
         → position.current_price = $189.10 → tracker resets
         → Staleness gate: _is_rest_confirmed → exits allowed → SL checked at $189.10
         → If still below SL → EXIT EXECUTES

If cross-hub ALSO returns $189:
t=3s    Cross-hub returns $189 (same). REST check:
         → Schwab REST → $189 (same), Webull REST → $189 (same)
         → Returns $189 with source='confirmed-same'
         → _rest_checked = True, rest_checked_ok set
         → stuck_seconds=3 < 10 → validation NOT set yet
         → Staleness gate: change_age=3 < 10s → not blocking → SL EXITS ALLOWED

t=6s    REST cooldown (3s) elapsed → REST check again → $189 same → _rest_checked = True
         → stuck_seconds=6 < 10 → validation not set
         → Staleness gate: change_age=6 < 10s → not blocking → SL EXITS ALLOWED

t=10s   stuck_seconds=10 → REST check → same price
         → stuck_seconds=10 >= 10 → _rest_validated_same SET ✓
         → Staleness gate: change_age=10 > threshold (10s)
         → _rest_override_available = True (validated same)
         → _staleness_is_blocking = False → SL EXITS ALLOWED
```

### Case C: All REST Sources Fail

```
t=3s    REST attempted → all return None (connectivity issue)
         → _rest_checked = False, rest_checked_ok NOT set
         → Staleness gate: change_age=3 < 10s → not blocking → SL ALLOWED

t=10s   change_age crosses 10s threshold
         → No override available (no REST success)
         → _staleness_is_blocking = True → SL BLOCKED
         → Log: "🛡️ STALENESS GATE: TSLA price unchanged for 10s — blocking STOP LOSS exit"

t=11-89s SL remains BLOCKED. REST retried every 3s but keeps failing.

t=90s   escape hatch check: change_age > 90? YES
         → BUT rest_checked_ok = 0 (never got a successful REST response)
         → Escape hatch NOT triggered → SL STAYS BLOCKED
         → (This is correct — we can't confirm the price is real without any REST response)

If REST succeeds at any point (say t=45s):
t=45s   REST returns $189 (same) → _rest_checked = True → rest_checked_ok set
         → stuck_seconds=45 >= 10 → _rest_validated_same SET
         → _staleness_is_blocking = False → SL UNBLOCKED
```

---

## 7. Complete Timeline: Price Truly Frozen (Low Liquidity)

**Scenario**: SATL at $6.35 on Webull, only Webull connected, stock barely trades (the v8.1.8 case).

```
STEP 1 — Hub Overlay (every cycle):
  Webull hub has $6.35 → position.current_price = $6.35
  (Hub keeps reporting same price because the stock isn't trading)

STEP 2 — Stuck Detection:
  t=0s:  Tracker created. stuck_seconds=0.
  t=1s:  stuck_seconds=1. Below 3s. Skip REST.
  t=3s:  stuck_seconds=3. ABOVE 3s threshold.
         Cross-hub: no other broker → nothing.
         REST: Webull REST API → returns $6.35 (same as streaming).
           → _try_rest_quote returns $6.35 with source='confirmed-same' (NOT None!)
           → _rest_checked = True ✓
           → rest_checked_ok = now ✓
           → stuck_seconds=3 < 10 → validation not set yet.
  t=6s:  REST cooldown elapsed. REST again → $6.35 same → _rest_checked = True.
  t=9s:  REST again → $6.35 same.

  t=11s: stuck_seconds=11.
         REST → $6.35 same → _rest_checked = True.
         stuck_seconds=11 ≥ 10 ✓, not sanity_rejected ✓, _rest_checked ✓
         → _rest_validated_same[WEBULL_SATL_stock] = now ← VALIDATED
         → Log: "✓ PRICE VALIDATED (REST): WEBULL SATL frozen 11s — confirmed price $6.3500 is real"

STEP 3 — Exit Evaluation (t=11s):
  _is_rest_validated_same = True
  _rest_override_available = True
  change_age = 11 > threshold (10s)
  → _rest_override_available? YES
  → _staleness_is_blocking = False
  → Log: "✓ STALENESS OVERRIDE: SATL price $6.35 stale 11s but REST-validated same — allowing SL evaluation"
  → ALL EXITS ALLOWED (SL and PT both)

Ongoing (t=11s to t=71s):
  _rest_validated_same persists (60s TTL). Exits remain allowed.
  REST re-checks every 3s, keeps confirming same price.

t=71s:  _rest_validated_same expires (60s TTL from t=11s).
  Next REST check → same price → re-validates immediately → exits stay allowed.
  (Already-validated positions get expanded REST quota: 3+4=7, so re-validation isn't blocked.)

If somehow validation lapses AND REST stops responding:
t=91s:  change_age > 90 AND rest_checked_ok > 0 (set at t=3s)
  → ESCAPE HATCH triggers → exits force-allowed regardless
```

**Total time from "price stops moving" to "SL exit allowed"**: **~11-13 seconds**  
(3s stuck threshold + 3s REST cooldown cycles + 10s validation threshold)

---

## 8. Complete Timeline: Price Actually Stale (Wrong Price)

**Scenario**: Pre-market opens, AAPL position shows yesterday's close ($185) instead of the actual pre-market price ($192). Entry was $190. SL at 5% ($180.50).

```
t=0s:  Position loaded with price $185.00 (yesterday's close — WRONG).
       Tracker: {last_price: 185.00, last_changed: t0}

STEP 1 — Hub Overlay:
  Webull hub has $192.00 (real pre-market price) → position.current_price = $192.00
  → Tracker detects price change (185 → 192), resets.
  → Staleness clock resets. No issues.
  → EXIT: Normal SL evaluation at $192. Above SL ($180.50). No exit. Correct.

If Webull hub doesn't have pre-market data:
  → position.current_price stays at $185.00

STEP 2 — Stuck Detection (t=3s):
  stuck_seconds=3 → REST check.
  Schwab REST → returns $192.00 (different from $185).
  → PRICE FIX: position.current_price = $192.00.
  → Tracker resets. _rest_confirmed_this_cycle set.
  → Log: "🔄 STUCK PRICE FIX (REST/Schwab): WEBULL AAPL was $185.0000 (frozen 3s) → $192.0000"

STEP 3 — Exit Evaluation:
  Price is now $192.00. Above SL ($180.50). No exit triggered. Correct.

But what if REST also returns $185 (both stale)?
  → REST returns same price → _rest_validated_same set after 10s.
  → HOWEVER: Freshness Guard catches this FIRST (line 3559):
    deviation = |$185 - $190| / $190 = 2.6%
    sl_pct * 1.5 = 5% * 1.5 = 7.5%
    2.6% < 7.5% → NOT triggered by freshness guard.
  → Staleness validates the $185 price as "real."
  → SL at $180.50 → $185 > $180.50 → No SL exit. Correct (price is above SL).

What if wrong price IS below SL (e.g., entry $190, wrong price $170)?
  → Freshness Guard: deviation = |$170 - $190| / $190 = 10.5%
    sl_pct * 1.5 = 5% * 1.5 = 7.5%
    10.5% > 7.5% → TRIGGERED!
  → Check streaming hubs for fresh price.
  → If Webull hub says $188 (1.1% loss < 5% SL) → "price was stale" → BLOCK false SL, update price.
  → If no hub available → defer 1 cycle, then allow (can't defer forever).
```

---

## 9. All Price Sources and Their Speeds

### Price Source Hierarchy (fastest to slowest):

| # | Source | Speed | API Cost | When Used |
|---|--------|-------|----------|-----------|
| 1 | **Own broker's streaming hub** | **Instant** (in-memory) | Zero | Every cycle, Step 1 |
| 2 | **Cross-broker streaming hub** | **Instant** (in-memory) | Zero | Step 1 (if own hub has no price) |
| 3 | **Cross-hub stuck check** | **Instant** (in-memory, max_age=2s) | Zero | Step 2, when stuck ≥ 3s |
| 4 | **Schwab REST API** | **200-500ms** | 1 API call | Step 2, when cross-hub fails |
| 5 | **Webull REST API** | **200-500ms** | 1 API call | Step 2, after Schwab REST |
| 6 | **Broker get_quote()** | **200-1000ms** | 1 API call | Step 2, last resort |

### Streaming Hub Providers and What They Cover:

| Hub | Streaming Tech | Stocks | Options | Max Age for "Fresh" |
|-----|----------------|--------|---------|----------------------|
| Webull | MQTT | ✓ | ✓ | 30s (default), 2s (cross-hub stuck check) |
| Schwab | WebSocket | ✓ | ✓ | 30s (default), 2s (cross-hub stuck check) |
| IBKR | ib_insync events | ✓ | ✓ | 30s (default), 2s (cross-hub stuck check) |
| Tastytrade | DXLink WebSocket | ✓ | ✓ | 30s (default) |
| Trading212 | Portfolio cache | ✓ (stocks only) | ✗ | 30s (default) |

---

## 10. Staleness Gate — Where It Sits in the Path

The staleness gate is NOT a separate step — it's a **decision layer inside Step 3** (exit evaluation). Here's where it fits:

```
┌─────────────────────────────────────────────────────────────────┐
│ MONITORING CYCLE (~1s)                                         │
│                                                                │
│  ┌─ STEP 1: Hub Price Overlay ─────────────────────────────┐   │
│  │  Own broker hub → cross-broker hubs → best price wins   │   │
│  │  Speed: instant, zero API calls                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           ↓                                    │
│  ┌─ STEP 2: Stuck Price Detection ─────────────────────────┐   │
│  │  Price unchanged > 3s?                                  │   │
│  │  ├── YES → Cross-hub check (instant)                    │   │
│  │  │   ├── Different price? → FIX IT → set confirmed      │   │
│  │  │   └── Same/nothing? → REST API check (200-500ms)     │   │
│  │  │       ├── Different price? → FIX IT → set confirmed   │   │
│  │  │       ├── Same price? → set validated_same (if ≥10s)  │   │
│  │  │       └── All failed? → nothing set                   │   │
│  │  └── NO → skip (price is moving)                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           ↓                                    │
│  ┌─ STEP 3: Exit Evaluation (per position) ────────────────┐   │
│  │                                                         │   │
│  │  ┌─ Freshness Guard (extended hours only) ───────────┐  │   │
│  │  │  Large loss on first cycle? Check hubs for truth.  │  │   │
│  │  └───────────────────────────────────────────────────┘  │   │
│  │                       ↓                                 │   │
│  │  ┌─ STALENESS GATE ─────────────────────────────────┐   │   │
│  │  │  change_age > threshold?                         │   │   │
│  │  │  ├── Override available? → NOT blocking           │   │   │
│  │  │  ├── 90s escape hatch? → NOT blocking             │   │   │
│  │  │  └── No override? → BLOCKING (SL only, not PT)    │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  │                       ↓                                 │   │
│  │  ┌─ Exit Checks ────────────────────────────────────┐   │   │
│  │  │  1. Price-based SL/PT → if blocking, SL blocked   │   │   │
│  │  │  2. Channel SL → if blocking, blocked             │   │   │
│  │  │  3. Tiered PTs → always allowed                   │   │   │
│  │  │  4. Enhanced Risk (dynamic SL, giveback, EMA)     │   │   │
│  │  │     → if blocking AND SL-type → blocked           │   │   │
│  │  │  5. Trailing Stop → if blocking, blocked           │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           ↓                                    │
│  If exit decision made → queue exit order for execution        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 11. Summary Timing Table

### How fast does the risk engine detect and exit?

| Scenario | Price Source Used | Time to Correct Price | Staleness Gate | Time to Exit |
|----------|------------------|-----------------------|----------------|-------------|
| **Price moving normally** | Own hub streaming | Instant (0ms) | Not engaged | **≤ 1s** (next cycle) |
| **Own hub stale, other hub has price** | Cross-broker hub | Instant (Step 1) | Not engaged | **≤ 1s** |
| **All hubs stale, REST finds different price** | REST API | ~3-4s (3s threshold + REST call) | Confirmed → not blocking | **~4s** |
| **All sources show same price (low liquidity)** | REST confirms same | ~11-13s (3s + cooldown + 10s validation) | Validated → not blocking | **~12s** |
| **All REST sources fail, then recover** | REST (delayed) | Whenever REST succeeds | Validated once REST succeeds | **Variable** |
| **All REST sources permanently fail** | None | Never | Blocks forever (correct — can't confirm) | **Never** (safety) |
| **Price frozen >90s + at least 1 REST success** | Escape hatch | 90s | Force-allowed | **~90s** |

### Profit Target vs Stop Loss — Key Difference:

| | Profit Target | Stop Loss |
|---|---|---|
| **Staleness gate applies?** | **NEVER** — always allowed | YES — blocked until validated |
| **Time to exit (price moving)** | ≤ 1s | ≤ 1s |
| **Time to exit (price frozen, REST works)** | ≤ 1s (not blocked) | ~12s (needs validation) |
| **Time to exit (price frozen, REST fails)** | ≤ 1s (not blocked) | Blocked until REST succeeds or 90s escape |
| **Reasoning** | Selling at a stale HIGH is favorable | Selling at a stale LOW could be a false trigger |
