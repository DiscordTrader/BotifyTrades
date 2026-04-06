# EMA Dynamic Stop Loss — Bug Analysis & Fix

## How EMA Escalation caused early stop-outs on low-priced stocks (AIXI case study)

---

## 1. THE BUG — What Went Wrong

### The Problem Flow

```
┌──────────────────────┐     ┌──────────────────────┐     ┌─────────────────────────┐     ┌──────────────────────┐
│     1. ENTRY         │     │    2. EMA SEEDS       │     │  3. DYN-SL OVERRIDES    │     │    4. EARLY EXIT     │
│                      │     │                       │     │                         │     │                      │
│ AIXI bought @ $0.36  │────>│ EMA(5) = $0.3567      │────>│ cache.dynamic_sl =      │────>│ Price dips to $0.3537│
│ Channel SL = 10%     │     │ EMA escalate offset   │     │   $0.3563               │     │ = -1.76% from entry  │
│ SL Price = $0.3240   │     │   = 0.1%              │     │ Overrides channel SL    │     │                      │
│                      │     │ New stop = $0.3563     │     │   ($0.3240)             │     │ STOPPED OUT!         │
│                      │     │                       │     │ Effective SL = 1.03%!   │     │ (should be -10%)     │
└──────────────────────┘     └──────────────────────┘     └─────────────────────────┘     └──────────────────────┘
```

---

## 2. PRICE DIAGRAM — AIXI Example

```
Price ($)
  │
  │
0.3600 ──────────────────────────────────────────── Entry Price ($0.3600)
  │                          ▲
  │                          │ Only 1.03% gap!
  │                          ▼
0.3563 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  EMA DYN-SL ($0.3563)
  │              ╳ Exit triggered here (-1.76%)
0.3537 ─ ─ ─ ─ ─╳─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  Actual exit price
  │
  │                   ▲
  │                   │
  │                   │  THE GAP
  │                   │  8.24% of breathing room
  │                   │  was stolen by DYN-SL!
  │                   │
  │                   ▼
0.3240 ──────────────────────────────────────────── Channel SL ($0.3240 = -10%)
  │                                                 ↑ This is where it SHOULD
  │                                                   have stopped out
  │
  └──────────────────────────────────────────────── Time →
```

**The position should have had 8.24% more room to breathe. Instead it was killed at -1.76%.**

---

## 3. THE ROOT CAUSE — Code Flow

```
┌─────────────────────────────────────────────────┐
│              risk_engine.py                      │
│                                                  │
│  EMA evaluates price                             │
│  EMA(5) = $0.3567                                │
│  Decision: ESCALATE                              │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│           risk_engine.py (line 400)              │
│                                                  │    ┌───────────────────────────────────┐
│  current_stop = 0  ← (new position!)            │    │         BUG: No Floor Check!      │
│  ema_stop = $0.3563                              │    │                                   │
│                                                  │    │  The EMA escalation had NO guard  │
│  Check: $0.3563 > 0  →  TRUE                    │────│  against setting a stop tighter   │
│  Action: EMA_ESCALATE_STOP                       │    │  than the channel's configured SL.│
│                                                  │    │                                   │
│  For a new position (no PTs hit),                │    │  For a new position, current_stop  │
│  current_stop = 0, so ANY EMA price              │    │  = 0, so ANY EMA price passed     │
│  passes the > 0 check!                           │    │  the > 0 check.                   │
└──────────────────────┬──────────────────────────┘    │                                   │
                       │                                │  EMA could override a -10% SL     │
                       ▼                                │  with a -1% SL immediately after  │
┌─────────────────────────────────────────────────┐    │  entry.                           │
│        position_monitor.py (line 4111)           │    └───────────────────────────────────┘
│                                                  │
│  EMA_ESCALATE_STOP handler:                      │
│  cache.dynamic_sl_price = $0.3563                │
│  (Writes to position cache)                      │
└──────────────────────┬──────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│         tiered_targets.py (line 323)             │
│                                                  │
│  if dynamic_sl_price exists:                     │
│      USE IT instead of channel SL                │
│                                                  │
│  SL = 1.03% instead of 10%                      │
│  → EARLY STOP OUT                               │
└─────────────────────────────────────────────────┘
```

---

## 4. THE FIX — Two-Layer Protection

### Layer 1: Gate at `risk_engine.py`

This prevents the EMA escalation from even writing a bad stop price.

```
┌──────────────────────┐     ┌─────────────────────────────┐     ┌──────────────────────┐
│  EMA wants to        │     │    DECISION GATE             │     │                      │
│  ESCALATE            │     │                              │     │   YES → BLOCKED!     │
│                      │────>│  Is stop < entry price       │────>│   EMA stop rejected  │
│  New stop = $0.3563  │     │  AND > channel SL floor?     │     │   Keep channel SL    │
│                      │     │                              │     │   = 10%              │
└──────────────────────┘     │  $0.3563 < $0.3600? YES      │     │                      │
                             │  $0.3563 > $0.3240? YES      │     └──────────────────────┘
                             │                              │
                             │  Both YES = BLOCK IT         │
                             └──────────────┬───────────────┘
                                            │
                                            │ NO (stop is above entry = position in profit)
                                            ▼
                                   ┌──────────────────────┐
                                   │   ALLOWED            │
                                   │   EMA stop is above  │
                                   │   entry price        │
                                   │   (position in       │
                                   │    profit)           │
                                   └──────────────────────┘
```

**Logic**: If the EMA wants to set a stop that is:
- **Below** the entry price (position would be at a loss), AND
- **Above** the channel's configured SL floor (tighter than what you configured)

Then the escalation is **rejected**. The EMA is only allowed to tighten the stop when the position is in profit.

---

### Layer 2: Safety Net at `tiered_targets.py`

Even if Layer 1 is somehow bypassed, this catches it at evaluation time.

```
┌──────────────────────┐     ┌─────────────────────────────┐     ┌──────────────────────┐
│  dynamic_sl_price    │     │    SAFETY CHECK              │     │                      │
│  exists AND          │     │                              │     │  YES → Fall back to  │
│  position is at      │────>│  Is DYN-SL tighter than      │────>│  CHANNEL SL (10%)    │
│  a LOSS              │     │  channel SL?                 │     │  Position protected! │
│  (price < entry)     │     │                              │     │                      │
│                      │     │  (DYN-SL price > channel     │     └──────────────────────┘
└──────────────────────┘     │   SL floor price?)           │
                             │                              │
                             └──────────────────────────────┘
```

---

## 5. BEFORE vs AFTER — AIXI Example

### BEFORE (Buggy)

```
Entry:         $0.3600
Channel SL:    -10% = $0.3240
EMA seeds:     EMA(5) = $0.3567
EMA stop:      0.1% offset = $0.3563

┌─────────────────────────────────────────┐
│  dynamic_sl_price = $0.3563             │
│  → Overrides channel SL!               │
│                                         │
│  Effective SL: -1.03%                   │
│  Price hits $0.3537 → EXIT              │
│                                         │
│  Result: Stopped out at -1.76%          │
│  instead of riding to recovery          │
│  or proper -10% stop                    │
└─────────────────────────────────────────┘
```

### AFTER (Fixed)

```
Entry:         $0.3600
Channel SL:    -10% = $0.3240
EMA seeds:     EMA(5) = $0.3567
EMA stop:      0.1% offset = $0.3563

┌─────────────────────────────────────────┐
│  Gate check (Layer 1):                  │
│  $0.3563 < $0.3600 (below entry)  ✓     │
│  $0.3563 > $0.3240 (above floor)  ✓     │
│  → BLOCKED! Not allowed.               │
│                                         │
│  Effective SL: -10% = $0.3240           │
│  Price hits $0.3537 → NO EXIT           │
│  Position continues running ✓           │
└─────────────────────────────────────────┘
```

---

## 6. THE RULE

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│  EMA can only TIGHTEN the stop loss when:                                       │
│                                                                                 │
│    • The new stop is ABOVE entry price (position is in profit), OR              │
│    • The new stop is BELOW the channel's configured SL floor                    │
│      (wider stop — never happens in practice)                                   │
│                                                                                 │
│  EMA CANNOT set a stop that is below entry but above the channel SL floor.      │
│  This prevents penny-stock EMA noise from overriding your configured            │
│  risk levels.                                                                   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. FILES CHANGED

| File | Change |
|------|--------|
| `src/risk/risk_engine.py` (line ~400) | Added gate check: EMA escalation blocked when proposed stop is below entry but above channel SL floor |
| `src/risk/tiered_targets.py` (line ~323) | Added safety net: dynamic SL falls back to channel SL when it would be tighter for a losing position |

---

## 8. VISUAL SUMMARY

```
         Entry ($0.3600)
              │
    ══════════╪══════════════════════════════
              │
   FORBIDDEN  │  ← EMA cannot set stops here
     ZONE     │     (below entry, above channel SL)
              │
    ──────────┼────────────────────────────── Channel SL Floor ($0.3240)
              │
   ALLOWED    │  ← EMA could theoretically set stops here
   (but why?) │     (below channel SL = wider stop)
              │
    ══════════╪══════════════════════════════


         Entry ($0.3600)
              │
   ALLOWED    │  ← EMA CAN tighten stops here
     ZONE     │     (above entry = position in profit!)
              │
    ══════════╪══════════════════════════════ e.g., $0.3700 after price rises
```
