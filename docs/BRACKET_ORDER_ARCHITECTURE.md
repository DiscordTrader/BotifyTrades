# Bracket Order Architecture: Current vs Proposed

---

## CURRENT ARCHITECTURE (How It Works Today)

There are **two separate systems** that can place bracket orders, and they don't coordinate with each other.

### System 1: Entry-Time Brackets (in `selfbot_webull.py`)

When a signal arrives (e.g., `BTO AAPL $190C`), the function `execute_on_single_broker()` decides whether to place a bracket order based on the exit strategy mode:

```
Signal arrives -> execute_on_single_broker() -> Should I place a bracket?

  HYBRID mode:  YES - always places bracket (entry + SL + PT1)
  SIGNAL mode:  ONLY if the signal message itself had PT/SL
                Channel-default PT/SL does NOT trigger bracket
  RISK mode:    NEVER - bracket is blocked
```

**Code location:** `selfbot_webull.py` lines ~16337-16345 (main gate), ~18724-18734 (paper), ~18947-18957 (live)

### System 2: Risk Engine Brackets (in `position_monitor.py`)

After a trade is filled, the Risk Engine detects the new position via broker sync (~15 seconds later) and can also place brackets:

```
Position detected -> _place_initial_broker_bracket() -> Places SL + PT1 at broker

  RISK mode:    YES - places bracket from channel risk settings
  HYBRID mode:  YES - places bracket
  SIGNAL mode:  NO - blocked, does not place brackets
```

**Code location:** `position_monitor.py` function `_place_initial_broker_bracket()`

---

## PROBLEMS WITH CURRENT SETUP

### Problem 1: HYBRID MODE — Duplicate Bracket Legs

```
T+0s:  execute_on_single_broker() places bracket:
         Entry BUY 5x, SL SELL 5x @ $185, PT SELL 5x @ $195

T+15s: Risk Engine detects position, calls _place_initial_broker_bracket()
         Places ANOTHER SL SELL 5x @ $185, ANOTHER PT SELL 5x @ $195

Result: 2 SL orders + 2 PT orders on the SAME position!
        If SL triggers, broker tries to sell 10x but you only have 5x
```

### Problem 2: SIGNAL MODE — No Broker Protection

```
T+0s:  Signal: BTO AAPL $190C (channel has SL=10% configured)
       execute_on_single_broker() checks: did signal message have PT/SL?
       Answer: NO (SL came from channel defaults)
       Result: bracket SKIPPED, entry-only order placed

T+0s:  Position has ZERO protection at broker
       No stop loss order, no profit target order
       Relies entirely on trader sending "STC" message later

T+???  If bot goes offline -> position is completely unprotected!
       No SL at broker = unlimited downside risk
```

### Problem 3: RISK MODE — 15-Second Gap

```
T+0s:   Signal: BTO AAPL $190C
        execute_on_single_broker() -> bracket BLOCKED for risk mode
        Entry order placed WITHOUT any SL/PT

T+0s to T+15s:  UNPROTECTED!  No SL at broker for ~15 seconds
                Price could crash during this window

T+15s:  Risk Engine syncs positions, detects fill
        _place_initial_broker_bracket() places SL + PT1
        Now protected (but 15s late)
```

### Problem 4: Dynamic SL Not Replaced at Broker

```
T+0s:   SL placed at broker @ $2.70

T+30m:  PT1 fills, Risk Engine internally moves SL to $3.00 (breakeven)
        BUT the broker still has the old SL order @ $2.70!
        Internal SL = $3.00, Broker SL = $2.70 (mismatch)

Result: If price drops to $2.70, broker fills old SL order
        You lose money that the dynamic SL should have protected
```

### Problem 5: No PT Cascade

```
T+0s:   Bracket placed with PT1 @ $3.45 only
        No PT2, no PT3 at broker

T+30m:  PT1 fills (SELL 2x @ $3.45)
        Remaining 4x contracts have NO profit target at broker
        Must rely on Risk Engine's internal monitoring for PT2/PT3
        If bot goes offline after PT1 fill -> no PT2 protection
```

---

## PROPOSED ARCHITECTURE (Single Owner: Risk Engine)

The core idea: **Remove all bracket logic from the entry path.** Make the Risk Engine the single owner of ALL bracket orders across ALL exit modes.

### Step 1: Entry Order (Same for ALL Modes)

```
Signal arrives: BTO 6x AAPL $190C @ $3.00

execute_on_single_broker() places ENTRY ONLY:
  BUY 6x AAPL $190C @ MARKET

NO bracket legs placed (no SL, no PT)
This is the SAME regardless of exit mode (hybrid, signal, or risk)
```

**What changes in code:**
- Remove the `use_bracket` logic from all 3 gates in `selfbot_webull.py`
- Entry path always places a simple market/limit order, never a bracket

### Step 2: Risk Engine Places Initial Bracket (ALL Modes)

```
Risk Engine detects fill (via broker sync or fill-watch callback)

Calls _place_initial_broker_bracket() for ALL modes:

  RISK mode:
    SL = from channel risk settings (e.g., 10% below entry)
    PT1 = from channel tier settings (e.g., +15% above entry)
    Qty per tier = calculated from tier configuration

  SIGNAL mode:
    SL = from signal message (e.g., $185)
    PT1 = from signal message (e.g., $195)
    Uses provenance flags (settings_source) to know what came from signal

  HYBRID mode:
    SL = tighter of signal SL vs channel SL (ExitOrderArbiter)
    PT1 = from signal or channel, whichever is available

Result: SL + PT1 placed at broker for ALL modes!
        Single owner = no duplicates
```

**What changes in code:**
- `position_monitor.py`: Enable `_place_initial_broker_bracket()` for signal mode (currently blocked)
- Use `settings_source` provenance to determine where PT/SL values come from

### Step 3: PT Cascade + Dynamic SL Replacement

When PT1 fills at broker, the Risk Engine runs the escalation cycle:

```
PT1 fills: SELL 2x @ $3.45

  1. CANCEL old SL order at broker
     cancel_order(broker_stop_order_id)

  2. Place NEW SL at escalated price
     e.g., SL moved from $2.70 -> $3.00 (breakeven)
     Standard dynamic SL profile: PT1 hit = move SL to breakeven

  3. Place PT2 at broker
     SELL 2x @ $3.75 (next tier target)
     _place_next_pt_bracket() handles this

PT2 fills: SELL 2x @ $3.75

  1. CANCEL old SL @ $3.00
  2. Place NEW SL @ $3.15 (+5% above entry)
  3. Place PT3: SELL 2x @ $4.20

...and so on for each tier
```

**What changes in code:**
- `position_monitor.py`: On each dynamic SL update, call `_sync_stop_to_broker()` to cancel old SL and place new one
- Ensure `_place_next_pt_bracket()` fires after each PT fill

### SL-Only Escalation Mode

Same SL replacement behavior, but PT hits do NOT trigger partial sells:

```
PT1 price reached ($3.45):
  - NO sell order executed
  - SL moved from $2.70 -> $3.00 (breakeven)
  - Old broker SL cancelled, new SL placed

PT2 price reached ($3.75):
  - NO sell order executed
  - SL moved from $3.00 -> $3.15
  - Old broker SL cancelled, new SL placed

Price drops to $3.15:
  - SL fills: SELL ALL 6x @ $3.15
  - Full position exits at once
```

---

## REAL TRADE EXAMPLE

**Setup:** Risk Mode, AAPL $190C, Entry $3.00, SL=10%, PT1=+15%, PT2=+25%, PT3=+40%, Dynamic SL=Standard

### Timeline:

```
T + 0 sec      ENTRY
               Signal: BTO 6x AAPL $190C @ $3.00
               execute_on_single_broker() places: BUY 6x AAPL $190C @ MARKET
               NO bracket legs — just the entry order
                    |
                    v
T + 3 sec      RISK ENGINE DETECTS FILL
               _place_initial_broker_bracket() places:
                 SL order:  SELL 6x @ $2.70 (stop)    [10% below $3.00]
                 PT1 order: SELL 2x @ $3.45 (limit)   [15% above $3.00]
               Position now protected at broker!
                    |
                    v
T + 30 min     PT1 FILLS — ESCALATION CYCLE #1
               Broker fills: SELL 2x @ $3.45 (PT1 hit!)
               Risk Engine detects fill, then:
                 1. CANCEL old SL @ $2.70
                 2. Place NEW SL @ $3.00 (breakeven)
                 3. Place PT2: SELL 2x @ $3.75 (25% above entry)
               Remaining: 4x AAPL $190C, SL=$3.00, PT2 pending
                    |
                    v
T + 1 hour     PT2 FILLS — ESCALATION CYCLE #2
               Broker fills: SELL 2x @ $3.75 (PT2 hit!)
               Risk Engine detects fill, then:
                 1. CANCEL old SL @ $3.00
                 2. Place NEW SL @ $3.15 (+5% above entry)
                 3. Place PT3: SELL 2x @ $4.20 (40% above entry)
               Remaining: 2x AAPL $190C, SL=$3.15, PT3 pending
                    |
                    v
T + 2 hours    PRICE DROPS — SL FILLS
               Price drops to $3.15 -> SL order fills: SELL 2x @ $3.15
               Cancel PT3 order (no longer needed)
               Position fully closed!
               
               Profit: 2x@$3.45 + 2x@$3.75 + 2x@$3.15 = $3.70 total gain
```

---

## BROKER-SPECIFIC SL REPLACEMENT

How each broker handles cancelling and replacing stop loss orders:

| Broker | Method | Details |
|--------|--------|---------|
| **Webull** | Cancel + New Order | `cancel_order(old_sl_id)` then `place_order(new_sl)`. 3 unlinked orders, cancel/replace individually |
| **Schwab** | Native Replace | `replace_order(old_sl_id, new_price)`. Most efficient, single API call |
| **Alpaca** | Cancel + New Order | `cancel_order(old_sl_id)` then `place_order(new_sl)`. Has true OCO but replace via cancel+new |
| **Tastytrade** | No Bracket Support | SL/PT monitored locally by Risk Engine. Risk Engine places market sell orders when triggered |

---

## CODE CHANGES SUMMARY

| File | Change |
|------|--------|
| `selfbot_webull.py` | Remove bracket gates from all 3 entry paths (main, paper, live). Entry always places simple order. |
| `position_monitor.py` | Enable `_place_initial_broker_bracket()` for signal mode (currently only risk/hybrid) |
| `position_monitor.py` | On each dynamic SL update, call `_sync_stop_to_broker()` to cancel+replace broker-side SL |
| `position_monitor.py` | Ensure `_place_next_pt_bracket()` fires after each PT fill for PT cascade |
| `settings_source` | Keep provenance flags (`sl:signal`, `pt:signal`, etc.) for audit trail |
