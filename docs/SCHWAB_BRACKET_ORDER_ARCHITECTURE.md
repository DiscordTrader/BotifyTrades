# Schwab Bracket Order Architecture — Gap Analysis & Design

> **Status:** Review Document (Do Not Implement)  
> **Date:** 2026-04-19  
> **Scope:** Schwab broker bracket order integration, progressive PT cascade, dynamic SL escalation, and `broker_bracket_mode` options

---

## Table of Contents

1. [Current Architecture](#1-current-architecture)
2. [Schwab Official API Capabilities](#2-schwab-official-api-capabilities)
3. [Broker Bracket Mode Options (UI)](#3-broker-bracket-mode-options-ui)
4. [Progressive PT Cascade Flow](#4-progressive-pt-cascade-flow)
5. [Dynamic SL Escalation Integration](#5-dynamic-sl-escalation-integration)
6. [Identified Gaps](#6-identified-gaps)
7. [Race Conditions](#7-race-conditions)
8. [Recommended Architecture (Target State)](#8-recommended-architecture-target-state)
9. [Implementation Priorities](#9-implementation-priorities)

---

## 1. Current Architecture

### Entry Flow (selfbot_webull.py)

The entry order is ALWAYS placed as a **SINGLE** order — bracket entry is disabled:

```
selfbot_webull.py:16796-16801
    # Bracket orders are now placed exclusively by the Risk Engine (position_monitor.py)
    # after fill detection. This prevents duplicate bracket legs and ensures a single
    # owner for the entire bracket lifecycle.
    use_bracket = False  ← hardcoded
```

This is the correct design decision — it separates entry from exit management.

### Bracket Placement Flow (position_monitor.py)

After the BTO fills and the risk engine detects the new position:

```
position_monitor.py:4044-4058
    if channel_settings and not cache.broker_orders_placed:
        _bracket_attempts = getattr(cache, '_bracket_attempt_count', 0)
        if _bracket_attempts >= 3:
            # Give up after 3 failures — risk engine manages exits
        else:
            await self._place_initial_broker_bracket(position, cache, channel_settings)
```

### What Gets Placed on Schwab (Current)

```
_place_initial_broker_bracket() → position_monitor.py:4879-4965

TWO INDEPENDENT ORDERS (not linked):
  1. place_stop_order()    → SINGLE STOP order (SL, full qty, GTC)
  2. place_option_order()  → SINGLE LIMIT order (PT1, partial qty, _skip_cancel_check=True)
```

**Critical Finding:** The `place_oco_order()` method exists in `schwab_broker.py:2865` and correctly builds an OCO payload — but is **NEVER called** by the risk engine.

### PT Cascade Flow (Current)

```
position_monitor.py:4113-4121 (when risk engine detects PT hit)
    decision._broker_pt_needs_cancel = True
    → _enqueue_broker_op('CANCEL_PT_FOR_LOCAL', priority=5)    # Cancel current PT
    → _enqueue_broker_op('PLACE_PT{next}', priority=20)         # Place next PT

_place_next_pt_bracket_inner() → position_monitor.py:5409-5511
    → Cancel old PT order
    → Calculate next tier qty via calculate_tier_quantities()
    → Place new SINGLE LIMIT order for PT{next}
    → RESIZE_STOP enqueued (priority=15) to sync SL qty to remaining position
```

### SL Sync Flow (Current)

```
_sync_stop_to_broker_inner() → position_monitor.py:5732-5810
    1. Cancel existing STOP order by cached order_id
    2. Wait for cancel to propagate (implicit via await)
    3. Place NEW STOP order with:
       - Current position quantity (position.quantity)
       - New stop price
    4. Update cache.broker_stop_order_id
```

---

## 2. Schwab Official API Capabilities

### Order Strategy Types

| Type | Description | Schwab Behavior |
|------|-------------|-----------------|
| `SINGLE` | One order, no children | Standard independent order |
| `OCO` | One-Cancels-Other | Two children: when one fills/cancels, other auto-cancels |
| `TRIGGER` | Parent triggers children | When parent fills → children activate |

### Available in Your Code (schwab_broker.py)

| Method | Lines | Schwab Strategy | Currently Used By Risk Engine? |
|--------|-------|-----------------|-------------------------------|
| `place_stop_order()` | 2574-2668 | SINGLE STOP | ✅ Yes — for SL |
| `place_stock_order()` | 1094-1344 | SINGLE LIMIT/MARKET | ✅ Yes — for PT (stocks) |
| `place_option_order()` | 1346-1804 | SINGLE LIMIT/MARKET | ✅ Yes — for PT (options) |
| `place_oco_order()` | 2865-2997 | **OCO** (SL+PT linked) | ❌ **NEVER CALLED** |
| `place_bracket_order()` | 2999-3199 | **TRIGGER + OCO** (entry+SL+PT) | ❌ **NEVER CALLED** |
| `replace_order()` | 3444-3471 | **PUT /orders/{id}** (atomic replace) | ❌ **NEVER CALLED** |
| `cancel_order()` | 3422-3442 | DELETE /orders/{id} | ✅ Yes |

### Schwab API Replace Order (PUT)

Schwab supports **atomic order replacement** via `PUT /accounts/{hash}/orders/{orderId}`:
- Cancels the old order and places the new order in a single API call
- Returns the new order ID in the `Location` header
- Eliminates the cancel-then-place race window

Your code has `replace_order()` at `schwab_broker.py:3444` — it's implemented but **never used** by the risk engine.

### Schwab OCO Behavior

When an OCO order is placed:
```json
{
    "orderStrategyType": "OCO",
    "childOrderStrategies": [
        { "orderType": "LIMIT", ... },   // PT leg
        { "orderType": "STOP", ... }      // SL leg
    ]
}
```

- If PT LIMIT fills → SL STOP is **automatically cancelled** by Schwab
- If SL STOP triggers → PT LIMIT is **automatically cancelled** by Schwab
- Parent OCO order ID tracks both children
- Children inherit `session` and `duration` from their own fields (not parent)

### Schwab Constraints

| Constraint | Detail |
|-----------|--------|
| STOP in SEAMLESS session | ❌ Not supported — must use NORMAL |
| OCO with mixed sessions | ⚠️ Both children should use same session |
| STOP order on options | ✅ Supported with OCC symbol |
| GTC on options | ⚠️ Some option series reject GTC — use DAY |
| Replace OCO | ✅ Replace parent replaces both children |
| Cancel OCO | ✅ Cancel parent cancels both children |
| Max children per OCO | 2 (one PT + one SL) |
| Nested OCO in TRIGGER | ✅ Supported (entry → OCO children) |

---

## 3. Broker Bracket Mode Options (UI)

**Location:** Trading → Execution → Channel Management → Per Channel Risk Management → Targets & SL tab

### UI Options

| Option | `broker_bracket_mode` value | Description |
|--------|---------------------------|-------------|
| **Both** | `'both'` | Place both SL and PT orders on broker |
| **SL Only** | `'sl_only'` | Place only SL on broker; risk engine handles PT |
| **PT Only** | `'pt_only'` | Place only PT on broker; risk engine handles SL |
| **Disabled** | `'none'` | No broker orders; risk engine handles everything |

### Current Code Path per Mode

```python
# risk_types.py — computed properties
@property
def allows_broker_sl(self) -> bool:
    return self.broker_bracket_mode in ('both', 'sl_only')

@property
def allows_broker_pt(self) -> bool:
    return self.broker_bracket_mode in ('both', 'pt_only')

# position_monitor.py:4834-4838
_allows_sl = getattr(channel_settings, 'allows_broker_sl', True)
_allows_pt = getattr(channel_settings, 'allows_broker_pt', True)
sl_price = round(...) if sl_pct > 0 and _allows_sl else None
pt1_price = round(...) if pt1_pct > 0 and _allows_pt else None
```

### Mode Behavior Matrix

| Mode | Broker SL | Broker PT | Risk Engine SL | Risk Engine PT | OCO Possible? |
|------|-----------|-----------|----------------|----------------|---------------|
| `both` | ✅ STOP order | ✅ LIMIT order | ✅ Also monitors | ✅ Also monitors | ✅ Yes |
| `sl_only` | ✅ STOP order | ❌ None | ✅ Also monitors | ✅ Full control | ❌ No (only one leg) |
| `pt_only` | ❌ None | ✅ LIMIT order | ✅ Full control | ✅ Also monitors | ❌ No (only one leg) |
| `none` | ❌ None | ❌ None | ✅ Full control | ✅ Full control | ❌ N/A |

**Key Insight:** OCO only makes sense in `both` mode where both SL and PT are broker-managed. In `sl_only` or `pt_only`, independent SINGLE orders are correct.

---

## 4. Progressive PT Cascade Flow

### Desired Behavior

```
Entry fills → Place OCO(SL + PT1)
  ↓
PT1 fills → Schwab auto-cancels SL
  → Bot detects PT1 fill
  → Place new OCO(SL_escalated + PT2) for remaining qty
  ↓
PT2 fills → Schwab auto-cancels SL_escalated
  → Bot detects PT2 fill
  → Place new OCO(SL_escalated_more + PT3) for remaining qty
  ↓
PT3 fills → same pattern
  ↓
PT4 fills → final exit (or leave runner)
```

### Current Implementation (position_monitor.py)

```
Entry fills → Place STOP(SL) + LIMIT(PT1) [INDEPENDENT]
  ↓
Risk engine detects PT1 pct reached:
  → Sets decision._broker_pt_needs_cancel = True    (line 4270)
  → Enqueues CANCEL_PT_FOR_LOCAL (priority 5)        (line 4117)
  → Enqueues PLACE_PT{next} (priority 20)            (line 4120)
  → Executes local partial exit via _execute_exit()   (line 4122)
  ↓
After partial exit completes:
  → RESIZE_STOP enqueued (priority 15)                (line 5406)
  → _sync_stop_to_broker() cancel+replace SL order
```

### Cascade Sequence Detail

| Step | Broker Op Queue | Priority | What Happens |
|------|----------------|----------|--------------|
| 1 | `CANCEL_PT_FOR_LOCAL` | 5 | Cancel broker PT1 order |
| 2 | `SYNC_STOP` | 10 | Cancel old SL + place new SL at dynamic price |
| 3 | `RESIZE_STOP` | 15 | Cancel SL again + place new SL with updated qty |
| 4 | `PLACE_PT2` | 20 | Place new LIMIT order for PT2 |

**Problem:** Steps 2 and 3 both cancel and replace the SL order — that's **two cancel+place cycles** for a single PT cascade event, creating unnecessary API calls and race windows.

---

## 5. Dynamic SL Escalation Integration

### Dynamic SL Profiles (risk_engine.py:150-169)

```python
DYNAMIC_SL_PROFILES = {
    'conservative': {
        'pt1_sl_pct': 0,     # SL stays at entry
        'pt2_sl_pct': 3,     # SL moves to +3%
        'pt3_sl_pct': 8,     # SL moves to +8%
        'pt4_sl_pct': 15     # SL moves to +15%
    },
    'standard': {
        'pt1_sl_pct': 0,     # SL stays at entry
        'pt2_sl_pct': 5,     # SL moves to +5%
        'pt3_sl_pct': 10,    # SL moves to +10%
        'pt4_sl_pct': 17     # SL moves to +17%
    },
    'aggressive': {
        'pt1_sl_pct': -2,    # SL stays below entry
        'pt2_sl_pct': 0,     # SL moves to entry
        'pt3_sl_pct': 8,     # SL moves to +8%
        'pt4_sl_pct': 15     # SL moves to +15%
    }
}
```

### How Dynamic SL Interacts with Broker Orders

```
position_monitor.py:4488-4522 (escalation_only_mode)
    → calculate_dynamic_sl(entry_price, pts_hit, profile)
    → cache.dynamic_sl_price = new_dynamic_sl
    → _enqueue_broker_op('SYNC_STOP', priority=10)
        → _sync_stop_to_broker(position, cache, new_sl_price)

position_monitor.py:4568-4575 (risk_engine ActionType.MOVE_STOP)
    → cache.dynamic_sl_price = action.new_stop_price
    → _enqueue_broker_op('SYNC_STOP', priority=10)

position_monitor.py:4589-4593 (early trailing activation)
    → cache.early_stop_price = breakeven_price
    → _enqueue_broker_op('SYNC_STOP', priority=10)

position_monitor.py:4605-4609 (early trailing step locked)
    → cache.early_stop_price = new_locked_price
    → _enqueue_broker_op('SYNC_STOP', priority=10)
```

### Dynamic SL + Broker Bracket Mode Interaction

| Scenario | `broker_bracket_mode` | Dynamic SL Enabled | Expected Behavior | Current Behavior |
|----------|----------------------|-------------------|-------------------|-----------------|
| PT1 hit, SL escalates | `both` | Yes | Replace SL order at new price + replace PT with PT2 | Cancel+new SL, cancel+new PT (4 API calls, 2 race windows) |
| PT1 hit, SL escalates | `sl_only` | Yes | Replace SL order at new price, no PT on broker | Cancel+new SL (2 API calls, 1 race window) |
| PT1 hit, SL escalates | `pt_only` | Yes | No SL on broker, replace PT with PT2 | Cancel+new PT only |
| PT1 hit, SL escalates | `none` | Yes | No broker orders at all | Correct — risk engine only |
| No PT hit, SL escalates (early trail) | `both` | N/A | Replace SL order only, keep PT | Cancel+new SL |
| SL only mode, dynamic SL escalates | `sl_only` | Yes | Replace SL at new price | Cancel+new SL |

---

## 6. Identified Gaps

### GAP 1: Independent Orders Instead of OCO (CRITICAL)

**Current:** SL and PT placed as two independent SINGLE orders  
**Should be:** Linked OCO order when `broker_bracket_mode = 'both'`

**Impact:**
- When SL triggers at Schwab, PT is NOT auto-cancelled → orphaned LIMIT order → potential double-exit or rejection
- When PT fills at Schwab, SL is NOT auto-cancelled → orphaned STOP order → triggers later → rejected (no position)
- The "fill + immediate rejection" the user reports is exactly this orphaned-order scenario

**Evidence:** `place_oco_order()` exists at `schwab_broker.py:2865` with correct payload but is never called.

**Fix:** In `_place_initial_broker_bracket()`, when `broker_bracket_mode == 'both'` and both SL and PT are configured, use `place_oco_order()` instead of two separate orders.

### GAP 2: Cancel+New Instead of Replace (HIGH)

**Current:** `_sync_stop_to_broker_inner()` does:
1. `cancel_order(cache.broker_stop_order_id)` → DELETE API call
2. Check cancel success
3. `place_stop_order(...)` → POST API call

**Should be:** `replace_order(order_id, new_payload)` → single PUT API call

**Impact:** 2-4 second window where no SL protection exists on broker. Price could gap through stop level during this window.

**Evidence:** `replace_order()` exists at `schwab_broker.py:3444` with correct PUT implementation but is never called by the risk engine.

### GAP 3: OCO Replacement on PT Cascade (HIGH)

**Current:** When PT1 fills:
1. Cancel old PT order (priority 5)
2. Sync SL to new price (priority 10) — cancel old SL + place new SL
3. Resize SL to remaining qty (priority 15) — cancel SL AGAIN + place new SL
4. Place PT2 as new LIMIT (priority 20)

That's **6 API calls** and **3 race windows** for one cascade event.

**Should be (with OCO):**
1. PT1 fills → Schwab auto-cancels SL (0 API calls)
2. Place new OCO(SL_escalated + PT2) with remaining qty → 1 API call

That's **1 API call** and **0 race windows**.

### GAP 4: Double SL Sync After PT Hit (MEDIUM)

The broker ops queue processes in priority order:
```
Priority 10: SYNC_STOP → cancel old SL → place new SL (dynamic SL price)
Priority 15: RESIZE_STOP → cancel the SL just placed → place another SL (same price, updated qty)
```

This is wasteful and creates an unnecessary race window. Both operations should be merged.

### GAP 5: SL Quantity Stale Between PT Fill and Resize (MEDIUM)

**Timeline:**
```
T+0:   PT1 partial exit executes (sell 2 of 5, now holding 3)
T+0:   SL STOP order still has qty=5 on Schwab
T+1:   SYNC_STOP fires → cancel SL → place new SL (still may use stale qty if position.quantity not yet updated)
T+3:   RESIZE_STOP fires → cancel SL → place new SL (now with correct qty)
```

**Window:** 1-3 seconds where SL order has wrong quantity. If SL triggers during this window → Schwab tries to sell 5 when only 3 held → **REJECTED**.

### GAP 6: No Fill Detection for Broker-Side PT/SL (HIGH)

**Current:** The risk engine detects PT hits by checking `pct_change >= target_pct` on each cycle. But the **broker** may fill the PT order before the risk engine evaluates it.

**Scenario:**
```
T+0:   Price hits PT1 → Schwab fills LIMIT order (PT1)
T+1:   Risk engine cycle — position.quantity is reduced
T+1:   Risk engine sees pct_change >= pt1_pct → tries to execute PT1 AGAIN
        → Double exit attempt
```

The risk engine does check `cache.tier1_hit` but the broker fill happens asynchronously. If the position quantity already reduced due to broker fill, the risk engine may not link it to the PT1 tier correctly.

### GAP 7: `broker_bracket_mode` Change Mid-Position (LOW)

If user changes `broker_bracket_mode` from `both` to `none` via the GUI while a position is open:
- Cache invalidation re-reads settings
- New settings say `allows_broker_sl = False`
- But the **existing STOP order** is still live on Schwab
- No cleanup logic for mode change mid-position

### GAP 8: OCO Session Mismatch (LOW)

`place_oco_order()` uses `self._get_session_type()` for both children. But STOP orders don't work in SEAMLESS session. If the session is SEAMLESS:
- PT child → SEAMLESS (fine for LIMIT)
- SL child → SEAMLESS (STOP not supported → **REJECTED**)

The standalone `place_stop_order()` correctly forces NORMAL, but `place_oco_order()` does not handle this.

### GAP 9: PT Cascade Skip When `trim_order_mode = 'market'` (LOW)

```python
# _place_next_pt_bracket_inner:5432-5435
if _trim_mode == 'market':
    print(f"PROGRESSIVE: PT{next_tier} skipped — trim_order_mode is 'market'")
    return
```

When `trim_order_mode = 'market'`, no broker PT orders are placed, but the SL is not resized either. The RESIZE_STOP at line 5406 runs after `_place_next_pt_bracket()` returns, so it does fire — but if SL is also managed by OCO, the OCO would already be cancelled when the PT leg filled, and no new OCO is placed.

### GAP 10: `sl_only` Mode — SL Not Escalated on PT Hit (MEDIUM)

When `broker_bracket_mode = 'sl_only'`:
- SL is placed on broker
- PT is NOT placed on broker (risk engine handles)
- When risk engine triggers PT1 exit locally, it enqueues `SYNC_STOP` to escalate SL

But the flow at `position_monitor.py:4113-4121` only enqueues PT-related ops when `_broker_pt_needs_cancel` is True — which is only True when `cache.broker_pt_order_id` exists. In `sl_only` mode, there's no broker PT order, so the cascade logic may skip the SL resize.

**Verification needed:** Does `RESIZE_STOP` at line 5406 fire regardless of whether a PT was broker-placed?

Looking at the code:
```python
# _place_next_pt_bracket:5402-5407
if cache.broker_stop_order_id and not cache.closing:
    _current_sl = cache.dynamic_sl_price or cache.early_stop_price or cache.stop_loss_price
    if _current_sl and _current_sl > 0:
        self._enqueue_broker_op(pos_key, 'RESIZE_STOP', 15,
            lambda ...: self._sync_stop_to_broker(...))
```

This runs inside `_place_next_pt_bracket()`, which is only called when `_broker_pt_needs_cancel` is True. In `sl_only` mode, `_broker_pt_needs_cancel` is False → `_place_next_pt_bracket()` is never called → **RESIZE_STOP is never enqueued**.

The SL order keeps the original entry-time stop price and full quantity even after partial PT exits.

**Impact:** In `sl_only` mode, after PT1 partial exit:
- SL order has wrong quantity (5 instead of 3)
- SL order has wrong price (entry SL instead of escalated dynamic SL)
- If SL triggers → quantity mismatch rejection

---

## 7. Race Conditions

### RC-1: SL Triggers During Cancel Window (HIGH)

```
T+0.0  Risk engine decides to exit (e.g., trailing stop)
T+0.0  Calls cancel_order(SL_order_id)
T+0.1  Schwab receives cancel... but STOP already triggered at exchange
T+0.2  STOP → MARKET SELL executes and FILLS (position closed)
T+2.0  Cancel returns "success" (order already filled, not actually cancelled)
T+2.5  Risk engine places new STC order
T+3.0  STC REJECTED — position already closed by filled STOP
```

**Fix with OCO:** If SL and PT are in an OCO, and the risk engine needs to override with a local exit, it cancels the **OCO parent** (one cancel cancels both legs), then places the local STC.

**Fix with Replace:** Use `replace_order()` to atomically swap the SL order with the new STC order.

### RC-2: PT Fills at Broker While Risk Engine Also Fires PT (MEDIUM)

```
T+0    Price hits PT1 target
T+0.1  Schwab fills LIMIT PT1 order (broker-side)
T+0.5  Risk engine evaluates: pct_change >= pt1_pct → fires PT1 exit too
T+0.5  Risk engine tries to sell PT1 qty → REJECTED (broker already sold it)
```

**Current mitigation:** `cache.tier1_hit` flag. But the flag is set by the risk engine's local evaluation, not by broker fill detection. The broker fill may not be reflected in `position.quantity` for 1-3 seconds.

### RC-3: Double RESIZE_STOP (LOW)

```
T+0    PT1 hit triggers both SYNC_STOP (priority 10) and RESIZE_STOP (priority 15)
T+0.5  SYNC_STOP: cancel SL #100 → place SL #101 (new price, old qty)
T+1.0  RESIZE_STOP: cancel SL #101 → place SL #102 (same price, new qty)
```

Not dangerous but wasteful (4 API calls instead of 1) and has a brief window where SL #101 exists with wrong qty.

### RC-4: GUI Settings Change During Bracket Cascade (LOW)

```
T+0    PT1 hit, cascade starts
T+0.1  User changes broker_bracket_mode from 'both' to 'none' in GUI
T+0.3  CANCEL_PT fires with old settings → cancels PT order
T+1.0  PLACE_PT2 fires with NEW settings → allows_broker_pt is False → skips
T+1.5  RESIZE_STOP fires with NEW settings → allows_broker_sl is False → skips
Result: SL order from initial placement is still live but never updated/cancelled
```

---

## 8. Recommended Architecture (Target State)

### Mode-Based Bracket Strategy

```
broker_bracket_mode = 'both':
    → Use OCO(SL + PT) on Schwab
    → On PT fill: Schwab auto-cancels SL
    → Bot places new OCO(SL_escalated + PT_next) for remaining qty
    → On final PT (or leave runner): place standalone SL

broker_bracket_mode = 'sl_only':
    → Place standalone STOP order for SL
    → Risk engine handles all PT exits locally
    → On PT partial exit: replace_order() to update SL qty + price
    → On Dynamic SL escalation: replace_order() to update price

broker_bracket_mode = 'pt_only':
    → Place standalone LIMIT order for PT1
    → Risk engine handles SL locally
    → On PT1 fill: place new LIMIT for PT2 (no SL on broker)
    → No SL sync needed

broker_bracket_mode = 'none':
    → No broker orders at all
    → Risk engine handles everything
    → Fastest local response, no API latency
```

### OCO Cascade (Target for `both` mode)

```
Phase 1: Initial Bracket
    Entry fills → detect in risk engine
    → place_oco_order(symbol, qty=FULL, sl_price, pt1_price)
    → Store parent OCO order_id as cache.broker_oco_order_id
    → Extract child order IDs for tracking

Phase 2: PT1 Fills (Schwab auto-cancels SL)
    → Detect PT1 fill (position.quantity reduced)
    → Mark tier1_hit = True
    → Calculate dynamic SL: new_sl = entry * (1 + profile.pt1_sl_pct/100)
    → Calculate PT2 qty via calculate_tier_quantities()
    → place_oco_order(symbol, qty=remaining, sl_price=new_sl, pt2_price)
    → Update cache.broker_oco_order_id

Phase 3: PT2 Fills → same pattern
    → Dynamic SL escalates further (pt2_sl_pct)
    → place_oco_order(remaining, new_sl, pt3_price)

Phase 4: PT3 Fills → same pattern
    → Dynamic SL escalates (pt3_sl_pct)
    → If PT4 exists: place_oco_order(remaining, new_sl, pt4_price)
    → If no PT4 + leave_runner: place standalone STOP(runner_qty, sl_price)
    → If no PT4 + no runner: no bracket (position fully exited or risk engine manages)

Phase 5: Final PT Fills or Leave Runner
    → If leave_runner: standalone STOP for runner qty at highest dynamic SL
    → If no runner: position fully closed, no orders
```

### Replace Order for SL Updates (Target for `sl_only` mode)

```
Dynamic SL escalates:
    → Build new STOP order payload (new price, current qty)
    → replace_order(cache.broker_stop_order_id, new_payload)
    → Update cache.broker_stop_order_id with new order ID

Benefits:
    → Atomic: no window without SL protection
    → 1 API call instead of 2
    → No race condition
```

### Fill Detection Strategy

```
Option A: Position Quantity Delta (Current — Passive)
    → Each risk cycle checks position.quantity
    → If qty decreased and broker_pt_order_id exists → infer PT fill
    → Problem: 1-3 second delay, may conflict with risk engine's own exit

Option B: Order Status Polling (Active)
    → Poll broker_pt_order_id status each cycle
    → If status == 'FILLED' → confirm PT fill, trigger cascade
    → Problem: additional API calls, rate limit pressure

Option C: Schwab Streaming Order Activity (Best)
    → Schwab WebSocket subscription: ACCT_ACTIVITY
    → Real-time fill notifications
    → Immediately detect SL/PT fills
    → Zero additional API calls
    → Problem: requires streaming client changes
```

---

## 9. Implementation Priorities

### Priority 1: Use OCO for `both` Mode (Fixes GAP 1 + RC-1 + RC-2)

**Impact:** Eliminates the root cause of "fill + rejection" issue  
**Effort:** Medium — `place_oco_order()` already exists, need to wire it in `_place_initial_broker_bracket()`  
**Changes:**
- `position_monitor.py`: When `broker_bracket_mode == 'both'`, call `place_oco_order()` instead of `place_stop_order()` + `place_option_order()`
- Track OCO parent order_id in cache
- On PT cascade: cancel OCO parent → place new OCO
- Fix session mismatch in `place_oco_order()` (force NORMAL for STOP leg)

### Priority 2: Use `replace_order()` for SL Sync (Fixes GAP 2 + RC-3)

**Impact:** Eliminates cancel window, reduces API calls by 50%  
**Effort:** Low — `replace_order()` already exists  
**Changes:**
- `_sync_stop_to_broker_inner()`: Use `replace_order()` instead of `cancel_order()` + `place_stop_order()`
- Merge SYNC_STOP and RESIZE_STOP into single operation

### Priority 3: Fix `sl_only` Mode SL Resize (Fixes GAP 10)

**Impact:** Prevents quantity mismatch rejections in `sl_only` mode  
**Effort:** Low  
**Changes:**
- After local PT partial exit, always enqueue RESIZE_STOP if `cache.broker_stop_order_id` exists
- Don't gate SL resize on `_broker_pt_needs_cancel`

### Priority 4: Fix OCO Session Handling (Fixes GAP 8)

**Impact:** Prevents OCO rejections in extended hours  
**Effort:** Low  
**Changes:**
- In `place_oco_order()`: force NORMAL session for STOP child, allow SEAMLESS for LIMIT child
- Or force both to NORMAL when STOP is involved

### Priority 5: Add Broker Fill Detection (Fixes GAP 6)

**Impact:** Prevents double exits and ensures correct tier tracking  
**Effort:** High — requires streaming changes or polling  
**Changes:**
- Option A: Check `get_order_status(broker_pt_order_id)` each risk cycle
- Option B: Subscribe to Schwab ACCT_ACTIVITY stream (best long-term)

### Priority 6: Handle Mode Change Mid-Position (Fixes GAP 7)

**Impact:** Low — edge case  
**Effort:** Medium  
**Changes:**
- On settings invalidation, compare old vs new `broker_bracket_mode`
- If mode changed to `none`, cancel all existing broker orders
- If mode changed to `sl_only`, cancel PT order, keep SL

---

## 10. Three Sources of SL/PT — How They Feed Bracket Orders

Bracket order SL/PT prices are NOT hardcoded — they come from a **three-source precedence chain**.

### Source 1: Signal-Parsed SL/PT (from Discord messages)

Trader messages often embed explicit SL and PT levels:

```
Example A: "@Daytrades ONFO over 1.50, SL 10%, first target 1.65-1.75"
  → Parser extracts: SL=10%, PT=$1.65 (lower bound of range)
  → Stored on trades table: stop_loss_price=$1.35, profit_target_price=$1.65

Example B: "ENTERED LONG: $PBM, ENTRY: $9.00, S.L: $8.28, 1st Target: $9.75-9.90"
  → Parser extracts: SL=$8.28, PT=$9.75
  → Stored on trades table: stop_loss_price=$8.28, profit_target_price=$9.75
```

### Source 2: Channel Risk Settings (from UI)

Per-channel settings configured in the GUI (e.g., PT1=9%, SL=8%, Dynamic SL profile, etc.)

### Source 3: Risk Engine (runtime)

Dynamic calculations: Dynamic SL escalation, Early Trailing, Giveback Guard — computed each cycle.

### Precedence Logic (position_monitor.py:908-931)

```
exit_mode = 'risk':
    → Signal SL/PT IGNORED entirely
    → Channel settings are authoritative
    → Bracket uses channel SL% and channel PT1%

exit_mode = 'hybrid' or 'signal':
    → Signal SL/PT OVERRIDES channel PT1 and SL
    → Converted from price to % using entry price
    → Safety check: if signal PT% > channel PT2%, signal PT is discarded
      (prevents breaking tier order)
    → Channel PT2/PT3/PT4 kept for cascade
```

### How Merged Values Flow to Brackets

```
Signal: SL=$8.28, PT=$9.75, Entry=$9.00
Channel: PT1=9%, PT2=20%, PT3=30%, SL=8%

Merge result (exit_mode=hybrid):
  → stop_loss_pct = 8.0%  (from signal: ($9.00-$8.28)/$9.00)  ← OVERRIDES channel 8%
  → profit_target_1_pct = 8.3%  (from signal: ($9.75-$9.00)/$9.00)  ← OVERRIDES channel 9%
  → profit_target_2_pct = 20%  (channel)  ← KEPT
  → profit_target_3_pct = 30%  (channel)  ← KEPT
  → All other channel settings preserved (Dynamic SL, bracket mode, etc.)

_place_initial_broker_bracket() then:
  → sl_price = $9.00 * (1 - 8.0/100) = $8.28  ← matches signal
  → pt1_price = $9.00 * (1 + 8.3/100) = $9.75  ← matches signal
```

### After PT1 Hits — Dynamic SL Takes Over

Once PT1 fills, the **signal SL is no longer relevant**. Dynamic SL escalation calculates a new SL based on the profile:

```
Standard profile after PT1 hit: pt1_sl_pct = 0%
  → New SL = $9.00 * 1.0 = $9.00 (breakeven)
  → This REPLACES the signal SL of $8.28

After PT2 hit: pt2_sl_pct = 5%
  → New SL = $9.00 * 1.05 = $9.45 (locks +5% profit)
```

This is correct — the signal sets the initial risk, dynamic SL progressively locks profit.

### Lifecycle with Signal SL/PT + Channel Tiers + Dynamic SL

```
Signal: "LONG $PBM $9.00, S.L: $8.28, Target: $9.75"
Channel: PT2=20%, PT3=30%, Dynamic SL=standard, mode=both

T+0     BTO 5x PBM at $9.00 (signal SL=$8.28, PT=$9.75)
T+2s    OCO placed: SL STOP $8.28 qty=5 + PT1 LIMIT $9.75 qty=2

T+30m   PT1 fills at $9.75 (2 sold) → Schwab auto-cancels SL
        Dynamic SL escalates: pt1_sl_pct=0% → SL=$9.00 (breakeven)
        New OCO: SL STOP $9.00 qty=3 + PT2 LIMIT $10.80 qty=1

T+1h    PT2 fills at $10.80 → Schwab auto-cancels SL  
        Dynamic SL: pt2_sl_pct=5% → SL=$9.45
        New OCO: SL STOP $9.45 qty=2 + PT3 LIMIT $11.70 qty=1

T+2h    PT3 fills at $11.70 → runner remains (1 contract)
        Dynamic SL: pt3_sl_pct=10% → SL=$9.90
        Standalone STOP $9.90 qty=1 (no more PTs, leave runner)
```

### No Signal SL/PT — Pure Channel Settings

```
Signal: "BTO AAPL 200C" (no SL/PT in message)
Channel: PT1=9%, PT2=20%, SL=8%, Dynamic SL=standard, mode=both

T+0     BTO 5x at $5.00 (no signal override)
T+2s    OCO placed: SL STOP $4.60 qty=5 + PT1 LIMIT $5.45 qty=2
        (uses channel 8% SL and 9% PT1 directly)
```

### exit_mode = 'risk' — Signal Values Ignored

```
Signal: "LONG $PBM $9.00, S.L: $8.28, Target: $9.75"
Channel: PT1=9%, SL=8%, exit_mode=risk

T+0     BTO at $9.00
        → Signal SL=$8.28 and PT=$9.75 are DISCARDED
        → Log: "Exit mode is 'risk' - using channel settings"
T+2s    OCO placed: SL STOP $8.28 qty=5 + PT1 LIMIT $9.81 qty=2
        (uses channel 8% SL and 9% PT1 from entry $9.00)
```

### GAP 11: Signal PT Range — Only Lower Bound Used (OK — By Design)

Both examples have PT ranges (`$1.65-1.75`, `$9.75-9.90`). Parser takes the lower bound. For bracket LIMIT orders, this is **conservative and correct** — ensures fills at the minimum acceptable target.

### GAP 12: No Signal-Level Multi-Tier Support (LOW)

Signals only provide a single PT level. If a signal says "Target: $9.75-$9.90, Target 2: $11.00", the second target is not parsed. Only the first target overrides PT1; channel PT2/PT3/PT4 handle the cascade.

This is acceptable for current use — traders rarely embed 4 profit targets in a Discord message.

---

## 11. Industry Architect Review — Additional Gaps

A production-grade trading system review across failure modes, crash recovery, Schwab API constraints, edge cases, and operational risk.

### GAP 13: Bracket Order State NOT Persisted to Database (CRITICAL)

**Finding:** `broker_stop_order_id`, `broker_pt_order_id`, `broker_pt_tier`, and `broker_orders_placed` are stored **only in the in-memory `PositionCacheEntry`** (`risk_types.py:327-330`). They are never written to SQLite.

**Impact — Bot Restart / Crash:**
```
T+0     Bot places OCO on Schwab: SL STOP #500 + PT LIMIT #501
T+5m    Bot crashes (OOM, power loss, Windows update, etc.)
T+10m   Bot restarts
         → PositionCache rebuilt from positions API
         → cache.broker_stop_order_id = None (lost!)
         → cache.broker_pt_order_id = None (lost!)
         → cache.broker_orders_placed = False (lost!)
         ↓
         Risk engine sees broker_orders_placed=False
         → Places SECOND set of bracket orders: SL #600 + PT #601
         → Now Schwab has TWO STOP orders + TWO LIMIT orders for same position
         → One fills → other gets rejected OR double-fills
```

**Comparison to other persisted state:**
- `trailing_activated` → ✅ Persisted via `save_trailing_state()`
- `early_trailing_active` → ✅ Persisted via `persist_early_trailing_state()`
- `dynamic_sl_price` → ✅ Persisted via `update_enhanced_risk_state()`
- `broker_stop_order_id` → ❌ **NOT persisted**
- `broker_pt_order_id` → ❌ **NOT persisted**

**Fix:** Add `broker_stop_order_id`, `broker_pt_order_id`, `broker_pt_tier`, `broker_orders_placed` columns to the trades table (or a new `bracket_state` table). Persist after every bracket operation. On restart, load from DB and reconcile against Schwab's actual order state.

### GAP 14: No Reconciliation on Startup (CRITICAL)

**Finding:** After a restart, the bot does not query Schwab for existing open orders to determine if bracket orders are already in place. It blindly re-places brackets based on `cache.broker_orders_placed` (which defaults to `False` after restart — see GAP 13).

**Industry standard:** On startup, a production trading system should:
1. Query `GET /accounts/{hash}/orders` for all WORKING orders
2. Match each to known positions
3. Recognize existing SL/PT orders and populate the cache
4. Only place new brackets if none exist

**Current partial mitigation:** `position_cache.py:282-285` resets `broker_orders_placed=False` when both order IDs are None (cleanup). But this runs during normal operation, not as a startup reconciliation step.

### GAP 15: OCO Cancel Returns Parent ID — Child IDs Unknown (HIGH)

**Finding:** When `place_oco_order()` succeeds, it returns the **parent OCO order ID** from the `Location` header. But Schwab does NOT return child order IDs in the response.

**Problem for monitoring:**
```python
# Current code stores one ID:
cache.broker_stop_order_id = str(sl_result.order_id)    # ← individual order
cache.broker_pt_order_id = str(pt_result.order_id)      # ← individual order

# With OCO, you get only the parent:
cache.broker_oco_order_id = str(oco_result.order_id)    # ← parent
# But which child is the SL? Which is the PT? Unknown without a follow-up GET.
```

**To cancel just the OCO parent:** `DELETE /orders/{parent_id}` cancels both children — this works.

**To track which child filled:** Must `GET /orders/{parent_id}` and inspect `childOrderStrategies[].status` for each child.

**Fix:** After placing OCO, immediately `GET /orders/{oco_id}` to extract child order IDs. Store separately for fill tracking.

### GAP 16: Schwab Rate Limit Pressure During PT Cascade (HIGH)

**Finding:** Schwab enforces 120 API calls/minute budget. A single PT cascade event currently uses **6 API calls** (GAP 3). With the OCO fix, it drops to 1-2. But during volatile sessions:

```
5 positions × PT hit within same minute:
  Current: 5 × 6 = 30 API calls for bracket ops alone
  + Regular risk cycle polling
  + Quote fetches
  → Easily hits 120/min budget
```

**Current mitigation:** `schwab_broker.py:189` has `_should_throttle_non_critical()` which checks usage. But bracket operations are not classified as "critical" vs "non-critical" — they use the same `_make_request()` path.

**Risk:** If a 429 (rate limit) hits during a bracket cancel+replace window, the position is left without SL protection for `retry_after` seconds (default 60s).

**Fix priority for OCO:** OCO reduces API calls by 83%, largely solving this. But `_make_request()` should prioritize bracket operations by marking them as `is_exit_order=True` (which gets shorter 429 retry waits).

### GAP 17: 0DTE / Same-Day Expiry Option Brackets (HIGH)

**Finding:** STOP orders on 0DTE options with `duration=GOOD_TILL_CANCEL` will be **automatically cancelled by Schwab at expiry**. This is a Schwab exchange rule — GTC on same-day expiry options is treated as DAY.

**Current code:** `place_stop_order()` at `schwab_broker.py:2581` defaults to `duration='GOOD_TILL_CANCEL'`. For 0DTE options, this means:
- SL STOP placed at 9:35 AM with GTC
- Schwab silently converts to DAY
- At 4:00 PM (or option expiry event), Schwab cancels the STOP
- If price gaps through stop near close, no protection

**But more critically:** For 0DTE, the bracket is fine because positions close same day. The risk is with `_get_duration()` not checking near-expiry for bracket-placed stop orders (it only checks in `place_option_order()` via `is_near_expiry`).

**Fix:** In `_place_initial_broker_bracket()`, detect 0DTE options and use `duration='DAY'` explicitly for the SL STOP order. The OCO `place_oco_order()` should also accept a duration parameter.

### GAP 18: Schwab SEAMLESS Session + STOP in OCO (HIGH)

**Finding:** The standalone `place_stop_order()` correctly forces `NORMAL` session when Schwab is in `SEAMLESS` mode (`schwab_broker.py:2608-2610`). But `place_oco_order()` at line 2900 uses `session = self._get_session_type()` for **both** children.

```python
# place_oco_order():2900
session = self._get_session_type()   # Could return "SEAMLESS"

profit_leg = { "session": session, ... }    # LIMIT — SEAMLESS OK
stop_leg = { "session": session, ... }      # STOP — SEAMLESS REJECTED!
```

**Impact:** If user has extended hours enabled or it's outside regular hours, the OCO will be **rejected by Schwab** because the STOP child uses SEAMLESS session.

**Fix:** In `place_oco_order()`, force the STOP child to `session="NORMAL"` regardless. The LIMIT child can stay SEAMLESS.

But there's a deeper issue: **Schwab may reject an OCO if the two children use different sessions.** This needs testing. If Schwab requires consistent sessions in OCO children, then both must be NORMAL when a STOP is involved.

### GAP 19: Partial Fill on PT Broker Order (MEDIUM)

**Finding:** If the broker's PT LIMIT order is **partially filled** (e.g., placed for qty=2, only 1 fills before price retraces), the current code does not handle this.

```
OCO placed: SL STOP qty=5 + PT1 LIMIT qty=2
PT1 LIMIT partially fills: 1 of 2 sold
  → OCO is still live (neither child fully filled)
  → SL STOP still has qty=5 (wrong — should be 4 now)
  → PT1 LIMIT still working for remaining 1
```

**Schwab behavior:** OCO children are NOT cancelled on partial fill of a sibling. Only when a child reaches FILLED status does the OCO cancel the other child.

**Impact:** Position quantity is reduced by 1, but SL quantity is still 5. If SL triggers → Schwab tries to sell 5 → rejected (only 4 held).

**Fix:** Monitor for PARTIALLY_FILLED status on OCO children. On partial fill, replace the OCO with updated quantities.

### GAP 20: Multiple Concurrent Positions Same Symbol (MEDIUM)

**Finding:** If the bot holds two positions in the same symbol on Schwab (e.g., different channels, different entries), bracket orders may interfere:

```
Position A: 3x AAPL $200C (channel: FoxTrades)
Position B: 2x AAPL $200C (channel: Daytrades)

Both share the same underlying symbol on Schwab.
Schwab sees one combined position: 5x AAPL $200C.

Bracket for A: SL STOP qty=3 at $4.50
Bracket for B: SL STOP qty=2 at $5.00
Total stop orders: qty=5 — if both trigger, Schwab processes both.
```

**Problem:** `_cancel_conflicting_sell_orders()` cancels ALL sell orders for a symbol. When exiting Position A, it may also cancel Position B's SL.

**Fix:** Store OCC symbol + order IDs per position key, cancel only the specific order IDs tracked in each position's cache entry (which the code already does for bracket orders). But `_cancel_all_open_orders_for_symbol()` in the STC flow is a blunt instrument.

### GAP 21: Replace Order Failure — Leaves No Protection (MEDIUM)

**Finding:** The recommended fix (use `replace_order()`) has its own failure mode:

```
Replace SL #100 with new SL at $5.00:
  → PUT /orders/100 → Schwab returns 400 (bad request)
  → Old order #100 is STILL CANCELLED (Schwab cancels first, then validates new order)
  → New order was not created
  → Position has NO SL protection
```

**Schwab replace behavior:** Replace = atomic cancel + create. If the create fails, the cancel still takes effect. This is not truly atomic from a safety perspective.

**Fix:** If `replace_order()` fails:
1. Immediately fall back to `place_stop_order()` with the same parameters
2. If that also fails, flag the position as "unprotected" and alert
3. Log the gap window duration for audit

### GAP 22: Token Expiry During Bracket Cascade (MEDIUM)

**Finding:** Schwab access tokens expire every 30 minutes. `_make_request()` handles 401 with token refresh. But during a multi-step bracket cascade:

```
Step 1: Cancel old OCO → success (token valid)
Step 2: Token expires
Step 3: Place new OCO → 401 → refresh token → retry → success
Gap: ~5-10 seconds between cancel and new OCO where no protection exists
```

**Current mitigation:** `_ensure_valid_token()` is called at the start of each operation. But the cascade involves multiple sequential API calls, and the token can expire between them.

**Fix:** The OCO approach largely solves this — one API call instead of multiple. But for `replace_order()`, the token should be proactively refreshed if within 60 seconds of expiry before starting the replace.

### GAP 23: CBOE Price Increment Drift in OCO (LOW)

**Finding:** `_round_to_cboe_increment()` rounds option prices to valid CBOE tick sizes ($0.05 under $3, $0.10 over $3). For OCO:

```
SL STOP at calculated $2.97 → rounded to $2.95 (CBOE $0.05 increment)
PT LIMIT at calculated $3.02 → rounded to $3.00 (CBOE $0.10 increment — just crossed $3.00 boundary)

If price hovers around $3.00:
  $2.97 SL → $2.95 (more aggressive stop, 2 ticks below intended)
  $3.02 PT → $3.00 (less generous target, rounds down)
```

**Impact:** Minor but consistent negative slippage on options near the $3.00 boundary.

**Fix:** This is inherent to CBOE rules. Document the behavior. Consider using STOP_LIMIT instead of STOP for SL leg to control fill price.

### GAP 24: Stale `position.quantity` During Rapid Cascade (LOW)

**Finding:** `_place_next_pt_bracket_inner()` reads `position.quantity` at line 5458 to cap the next tier's qty. But `position` is the snapshot from the risk cycle — it may be 1-3 seconds stale.

```
PT1 fills at T+0 (qty goes from 5 → 3)
PT cascade runs at T+0.5
position.quantity still shows 5 (snapshot not refreshed)
PT2 qty calculated as 1, but max is min(1, 5) → 1 ← correct by accident
But if PT2 qty should be 3 (remaining), it's capped to 1 based on stale calculation
```

**Current mitigation:** `remaining_qty = int(position.quantity)` at line 5458, and `next_qty = min(next_qty, remaining_qty)` at line 5460. With the OCO approach, the qty is calculated from `calculate_tier_quantities()` using `original_qty`, so this is less of an issue.

### Summary: Gap Priority Matrix (All 24 Gaps)

| Priority | Gap # | Title | Severity | Effort |
|----------|-------|-------|----------|--------|
| **P0** | 13 | Bracket state not persisted to DB | CRITICAL | Medium |
| **P0** | 14 | No order reconciliation on startup | CRITICAL | Medium |
| **P1** | 1 | Independent orders instead of OCO | CRITICAL | Medium |
| **P1** | 2 | Cancel+new instead of replace | HIGH | Low |
| **P1** | 18 | SEAMLESS session in OCO STOP child | HIGH | Low |
| **P1** | 15 | OCO child order IDs unknown | HIGH | Low |
| **P2** | 3 | OCO not used for PT cascade | HIGH | Medium |
| **P2** | 6 | No broker-side fill detection | HIGH | High |
| **P2** | 16 | Rate limit pressure during cascade | HIGH | Low (solved by OCO) |
| **P2** | 17 | 0DTE option GTC → DAY conversion | HIGH | Low |
| **P2** | 10 | sl_only mode never resizes SL | MEDIUM | Low |
| **P2** | 21 | Replace failure leaves no protection | MEDIUM | Low |
| **P3** | 4 | Double SYNC+RESIZE stop | MEDIUM | Low |
| **P3** | 5 | SL qty stale between PT fill and resize | MEDIUM | Low (solved by OCO) |
| **P3** | 19 | Partial fill on PT broker order | MEDIUM | Medium |
| **P3** | 20 | Multiple positions same symbol | MEDIUM | Medium |
| **P3** | 22 | Token expiry during cascade | MEDIUM | Low |
| **P3** | 12 | No signal multi-tier support | LOW | Low |
| **P4** | 7 | Mode change mid-position | LOW | Medium |
| **P4** | 8 | OCO session mismatch (covered by 18) | LOW | Low |
| **P4** | 9 | PT cascade skip trim=market | LOW | Low |
| **P4** | 11 | Signal PT range lower bound only | LOW | N/A (by design) |
| **P4** | 23 | CBOE increment drift near $3.00 | LOW | N/A (inherent) |
| **P4** | 24 | Stale position.quantity in cascade | LOW | Low |

### Recommended Implementation Phases

#### Phase 0: Safety Foundation (Gaps 13, 14) — Before Any OCO Work
1. Persist bracket order IDs to database
2. On startup, reconcile open orders on Schwab against DB state
3. Clean up orphaned orders (exist on Schwab but position closed in DB)

Without this, any improvement to the bracket system is undermined by restart data loss.

#### Phase 1: OCO Core (Gaps 1, 18, 15, 2) — Eliminate Rejections
1. Fix `place_oco_order()` session handling (STOP child → NORMAL)
2. Wire OCO into `_place_initial_broker_bracket()` for `both` mode
3. After OCO placement, GET parent to extract child IDs
4. Use `replace_order()` for SL sync in `sl_only` mode

#### Phase 2: PT Cascade + Dynamic SL (Gaps 3, 10, 17, 21)
1. On PT fill detected: cancel OCO parent → place new OCO with escalated SL + next PT
2. Fix `sl_only` mode SL resize after partial exits
3. Handle 0DTE duration correctly
4. Add replace fallback on failure

#### Phase 3: Fill Detection + Reconciliation (Gaps 6, 16, 19)
1. Poll OCO order status each risk cycle (check for fills)
2. Or subscribe to Schwab ACCT_ACTIVITY stream
3. Handle partial fills on OCO children
4. Monitor API budget and prioritize bracket ops

---

## Appendix A: Current vs Target API Call Count

### Per PT Cascade Event

| Operation | Current (Independent) | Target (OCO) | Savings |
|-----------|----------------------|---------------|---------|
| Cancel old PT | 1 DELETE | 0 (auto-cancelled) | -1 |
| Sync SL (cancel) | 1 DELETE | 0 (auto-cancelled) | -1 |
| Sync SL (new) | 1 POST | 0 (part of new OCO) | -1 |
| Resize SL (cancel) | 1 DELETE | 0 (merged) | -1 |
| Resize SL (new) | 1 POST | 0 (part of new OCO) | -1 |
| Place new PT | 1 POST | 0 (part of new OCO) | -1 |
| Place new OCO | 0 | 1 POST | +1 |
| **Total** | **6 API calls** | **1 API call** | **-83%** |

### Per Dynamic SL Escalation (no PT change)

| Operation | Current | Target (Replace) | Savings |
|-----------|---------|-------------------|---------|
| Cancel old SL | 1 DELETE | 0 | -1 |
| Place new SL | 1 POST | 0 | -1 |
| Replace SL | 0 | 1 PUT | +1 |
| **Total** | **2 API calls** | **1 API call** | **-50%** |

---

## Appendix B: Schwab API Payload Examples

### OCO Order (SL + PT)

```json
{
    "orderStrategyType": "OCO",
    "childOrderStrategies": [
        {
            "orderStrategyType": "SINGLE",
            "orderType": "LIMIT",
            "session": "NORMAL",
            "duration": "GOOD_TILL_CANCEL",
            "price": "5.50",
            "orderLegCollection": [{
                "instruction": "SELL_TO_CLOSE",
                "quantity": 3,
                "instrument": {
                    "symbol": "AAPL  260620C00200000",
                    "assetType": "OPTION"
                }
            }]
        },
        {
            "orderStrategyType": "SINGLE",
            "orderType": "STOP",
            "session": "NORMAL",
            "duration": "GOOD_TILL_CANCEL",
            "stopPrice": "3.80",
            "orderLegCollection": [{
                "instruction": "SELL_TO_CLOSE",
                "quantity": 3,
                "instrument": {
                    "symbol": "AAPL  260620C00200000",
                    "assetType": "OPTION"
                }
            }]
        }
    ]
}
```

### Replace Order (PUT)

```
PUT /trader/v1/accounts/{accountHash}/orders/{orderId}

Body: (same structure as new order)
{
    "orderStrategyType": "SINGLE",
    "orderType": "STOP",
    "session": "NORMAL",
    "duration": "GOOD_TILL_CANCEL",
    "stopPrice": "4.20",
    "orderLegCollection": [{
        "instruction": "SELL_TO_CLOSE",
        "quantity": 2,
        "instrument": {
            "symbol": "AAPL  260620C00200000",
            "assetType": "OPTION"
        }
    }]
}

Response: 201 Created
Location: /accounts/{hash}/orders/{newOrderId}
```

---

## Appendix C: Complete Lifecycle Example

### Scenario: 5 contracts, PT1=10%, PT2=20%, PT3=30%, SL=8%, Dynamic SL Standard, Leave Runner 20%, Mode=Both

```
T+0     BTO 5x AAPL $200C fills at $5.00
        entry_price = $5.00
        
        Tier calculation (leave_runner=20% → runner_qty=1, sellable=4):
          PT1: 2 contracts  (4/3 ≈ 1.33, rounded with remainder)
          PT2: 1 contract
          PT3: 1 contract
          Runner: 1 contract

T+2s    Risk engine places OCO:
        SL leg: STOP $4.60 (8% below $5.00), qty=5, GTC
        PT1 leg: LIMIT $5.50 (10% above $5.00), qty=2, GTC
        OCO order_id = #1000 (parent tracks both)

T+30m   Price hits $5.50 → PT1 LIMIT fills (2 contracts sold)
        → Schwab auto-cancels SL STOP (OCO behavior)
        → Position: 3 contracts remaining
        
        Dynamic SL: standard profile, pt1_sl_pct=0% → SL at $5.00 (breakeven)
        
        Risk engine places new OCO:
        SL leg: STOP $5.00, qty=3, GTC
        PT2 leg: LIMIT $6.00 (20%), qty=1, GTC
        OCO order_id = #1001

T+1h    Price hits $6.00 → PT2 LIMIT fills (1 contract sold)
        → Schwab auto-cancels SL STOP
        → Position: 2 contracts remaining
        
        Dynamic SL: pt2_sl_pct=5% → SL at $5.25

        Risk engine places new OCO:
        SL leg: STOP $5.25, qty=2, GTC
        PT3 leg: LIMIT $6.50 (30%), qty=1, GTC
        OCO order_id = #1002

T+2h    Price hits $6.50 → PT3 LIMIT fills (1 contract sold)
        → Schwab auto-cancels SL STOP
        → Position: 1 contract remaining (runner)
        
        Dynamic SL: pt3_sl_pct=10% → SL at $5.50
        
        Leave runner: no more PTs, place standalone SL:
        STOP $5.50, qty=1, GTC
        order_id = #1003

T+EOD   Runner either:
        a) SL triggers at $5.50 → exits at +10% (locked profit)
        b) Trader sends STC signal → cancel SL #1003 → execute STC
        c) Dynamic SL escalates further if price continues up
```

### Same Scenario with `sl_only` Mode

```
T+2s    Place standalone STOP $4.60, qty=5, GTC → order #2000
        (No PT on broker — risk engine monitors PT targets)

T+30m   Risk engine detects pct_change >= 10% → executes PT1 locally (sell 2)
        → replace_order(#2000, {STOP $5.00, qty=3}) → new order #2001

T+1h    Risk engine detects pct_change >= 20% → executes PT2 locally (sell 1)
        → replace_order(#2001, {STOP $5.25, qty=2}) → new order #2002

T+2h    Risk engine detects pct_change >= 30% → executes PT3 locally (sell 1)
        → replace_order(#2002, {STOP $5.50, qty=1}) → new order #2003

T+EOD   Runner SL at $5.50 protecting locked profit
```

### Same Scenario with `pt_only` Mode

```
T+2s    Place standalone LIMIT $5.50, qty=2, GTC → order #3000
        (No SL on broker — risk engine monitors SL)

T+30m   PT1 LIMIT fills at Schwab (2 sold)
        → Risk engine detects qty reduced → marks tier1_hit
        → Place LIMIT $6.00, qty=1, GTC → order #3001

T+1h    PT2 LIMIT fills → place LIMIT $6.50, qty=1 → order #3002

T+2h    PT3 LIMIT fills → runner remains, no more PT orders

T+EOD   SL protection is fully local — risk engine can react faster
        but no broker-side safety net if bot crashes
```
