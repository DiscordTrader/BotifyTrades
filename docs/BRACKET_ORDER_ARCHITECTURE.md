# Bracket Order Architecture: Current vs Proposed

---

## CURRENT ARCHITECTURE (How It Works Today)

There are **two separate systems** that can place bracket orders, and they don't coordinate with each other.

### System 1: Entry-Time Brackets (in `selfbot_webull.py`)

When a signal arrives (e.g., `BTO 100 SMCI @ $42.50` from Phoenix), the function `execute_on_single_broker()` decides whether to place a bracket order based on the exit strategy mode:

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

Imagine Phoenix sends: `BTO 100 SMCI @ $42.50`  
Channel has SL=10%, PT1=+15% configured.

```
T+0s:  execute_on_single_broker() places bracket:
         Entry: BUY 100 SMCI @ $42.50
         SL:    SELL 100 SMCI @ $38.25  (stop order)
         PT:    SELL 100 SMCI @ $48.88  (limit order)

T+15s: Risk Engine detects position, calls _place_initial_broker_bracket()
         Places ANOTHER SL: SELL 100 @ $38.25
         Places ANOTHER PT: SELL 100 @ $48.88

Result: 2 SL orders + 2 PT orders on the SAME 100 shares!
        If SL triggers, broker tries to sell 200 shares but you only have 100
```

### Problem 2: SIGNAL MODE — No Broker Protection

Phoenix sends: `BTO 500 LUNR @ $8.20`  
Channel has SL=10% configured, but signal message didn't include SL/PT.

```
T+0s:  Signal: BTO 500 LUNR @ $8.20
       execute_on_single_broker() checks: did signal message have PT/SL?
       Answer: NO (SL=10% came from channel defaults, not from Phoenix)
       Result: bracket SKIPPED, entry-only order placed

T+0s:  Position has ZERO protection at broker!
       500 shares of LUNR with no stop loss, no profit target
       Relies entirely on Phoenix sending "STC LUNR" message later

T+???  If bot goes offline -> position is completely unprotected!
       LUNR drops 30% -> you lose $1,230 with no SL to protect you
```

### Problem 3: RISK MODE — 15-Second Gap

Phoenix sends: `BTO 200 RKLB @ $25.00`

```
T+0s:   execute_on_single_broker() -> bracket BLOCKED for risk mode
        Entry order placed: BUY 200 RKLB @ $25.00
        NO SL, NO PT at broker

T+0s to T+15s:  UNPROTECTED! No SL at broker for ~15 seconds
                If RKLB drops 5% in those 15 seconds = $250 loss
                with no protection

T+15s:  Risk Engine syncs positions, detects fill
        _place_initial_broker_bracket() places SL + PT1
        Now protected (but 15s late)
```

### Problem 4: Dynamic SL Not Replaced at Broker

Continuing the RKLB example after Risk Engine places initial bracket:

```
T+15s:  SL placed at broker: SELL 200 RKLB @ $22.50 (10% below $25.00)

T+30m:  RKLB hits $28.75 (PT1 = +15%)
        Risk Engine internally moves SL to $25.00 (breakeven)
        BUT the broker still has the old SL order @ $22.50!

        Internal SL = $25.00 (breakeven)
        Broker SL   = $22.50 (still the original -10%)
        
        MISMATCH!

Result: RKLB drops to $22.50 -> broker fills old SL
        You lose $2.50/share ($500 total) instead of breaking even
        The dynamic SL escalation was supposed to protect you!
```

### Problem 5: No PT Cascade

```
T+15s:  Bracket placed with only PT1: SELL 60 RKLB @ $28.75
        No PT2, no PT3 at broker

T+30m:  PT1 fills (SELL 60 @ $28.75)
        Remaining 140 shares have NO profit target at broker
        Must rely on Risk Engine's internal monitoring for PT2/PT3
        If bot goes offline after PT1 fill -> 140 shares unprotected
```

---

## PROPOSED ARCHITECTURE (Single Owner: Risk Engine)

The core idea: **Remove all bracket logic from the entry path.** Make the Risk Engine the single owner of ALL bracket orders across ALL exit modes.

### Step 1: Entry Order (Same for ALL Modes)

Phoenix sends: `BTO 200 RKLB @ $25.00`

```
execute_on_single_broker() places ENTRY ONLY:
  BUY 200 RKLB @ $25.00 (market order)

NO bracket legs placed — no SL, no PT
This is the SAME regardless of exit mode (hybrid, signal, or risk)
```

**What changes in code:**
- Remove the `use_bracket` logic from all 3 gates in `selfbot_webull.py`
- Entry path always places a simple market/limit order, never a bracket

### Step 2: Risk Engine Places Initial Bracket (ALL Modes)

Risk Engine detects the fill (via broker sync or fill-watch callback), then places the initial bracket. Where it gets the SL/PT values depends on the exit mode:

```
RISK mode (Phoenix channel set to risk, SL=10%, PT1=+15%):
  Risk Engine computes from channel settings:
    SL = 10% below $25.00 = $22.50
    PT1 = 15% above $25.00 = $28.75, qty = 60 shares (tier 1 allocation)
  Places at broker:
    SL order:  SELL 200 RKLB @ $22.50 (stop)
    PT1 order: SELL 60 RKLB @ $28.75 (limit)

SIGNAL mode (Phoenix sent "BTO 200 RKLB @ $25.00, SL $23.50, PT $28.00"):
  Risk Engine reads signal-provided values (from settings_source provenance):
    SL = $23.50 (from Phoenix's message)
    PT1 = $28.00 (from Phoenix's message)
  Places at broker:
    SL order:  SELL 200 RKLB @ $23.50 (stop)
    PT1 order: SELL 200 RKLB @ $28.00 (limit)

HYBRID mode:
  Risk Engine picks the tighter protection:
    Signal SL = $23.50, Channel SL = $22.50
    Uses $23.50 (tighter / closer to entry = more protective)
    PT1 = from signal or channel, whichever is available
```

**What changes in code:**
- `position_monitor.py`: Enable `_place_initial_broker_bracket()` for signal mode (currently blocked)
- Use `settings_source` provenance to determine where PT/SL values come from

### Step 3: PT Cascade + Dynamic SL Replacement

When PT1 fills at broker, the Risk Engine runs the escalation cycle.  
Continuing the RKLB example in Risk mode (SL=10%, PT1=+15%, PT2=+25%, PT3=+40%, Dynamic SL=Standard):

```
PT1 fills: SELL 60 RKLB @ $28.75 (PT1 = +15% above $25.00)

  1. CANCEL old SL order at broker
     cancel_order(broker_stop_order_id)   -- removes the $22.50 stop

  2. Place NEW SL at escalated price
     Standard profile: PT1 hit = move SL to breakeven
     NEW SL = $25.00 (breakeven)
     place_order(SELL 140 RKLB @ $25.00, type=stop)

  3. Place PT2 at broker
     PT2 = +25% above $25.00 = $31.25
     Tier 2 allocation = 60 shares
     place_order(SELL 60 RKLB @ $31.25, type=limit)

PT2 fills: SELL 60 RKLB @ $31.25

  1. CANCEL old SL @ $25.00
  2. Place NEW SL @ $26.25 (+5% above entry, Standard profile PT2)
  3. Place PT3: SELL 80 RKLB @ $35.00 (runner, +40% above entry)

...and so on for each tier
```

**What changes in code:**
- `position_monitor.py`: On each dynamic SL update, call `_sync_stop_to_broker()` to cancel old SL and place new one
- Ensure `_place_next_pt_bracket()` fires after each PT fill

### SL-Only Escalation Mode

Same SL replacement behavior, but PT hits do NOT trigger partial sells.  
Example: Phoenix channel with SL-Only Escalation, 200 shares of RKLB:

```
RKLB hits $28.75 (PT1 level):
  - NO sell order executed (position stays at 200 shares)
  - SL moved from $22.50 -> $25.00 (breakeven)
  - Old broker SL cancelled, new SL placed at $25.00

RKLB hits $31.25 (PT2 level):
  - NO sell order executed (still 200 shares)
  - SL moved from $25.00 -> $26.25
  - Old broker SL cancelled, new SL placed at $26.25

RKLB drops to $26.25:
  - SL fills: SELL ALL 200 shares @ $26.25
  - Full position exits at once
  - Profit: $1.25/share × 200 = $250 (locked in by escalated SL)
```

---

## REAL TRADE EXAMPLE — Stock (Phoenix Channel, RKLB)

**Setup:** Risk Mode, 200 shares of RKLB @ $25.00, SL=10%, PT1=+15%, PT2=+25%, PT3=+40%, Dynamic SL=Standard

Tier allocation: PT1 = 60 shares, PT2 = 60 shares, PT3/Runner = 80 shares

### Timeline:

```
T + 0 sec      ENTRY
               Phoenix sends: "BTO 200 RKLB @ $25.00"
               Bot places: BUY 200 RKLB @ MARKET
               NO bracket legs — just the entry order
               Cost: 200 × $25.00 = $5,000
                    |
                    v
T + 3 sec      RISK ENGINE DETECTS FILL → PLACES INITIAL BRACKET
               _place_initial_broker_bracket() places:
                 SL order:  SELL 200 RKLB @ $22.50 (stop)    [10% below $25.00]
                 PT1 order: SELL 60 RKLB @ $28.75 (limit)    [15% above $25.00]
               
               Position now protected at broker!
               Even if bot goes offline, broker will execute SL or PT1.
                    |
                    v
T + 30 min     PT1 FILLS — ESCALATION CYCLE #1
               RKLB hits $28.75 → broker fills: SELL 60 @ $28.75
               Profit locked: 60 × ($28.75 - $25.00) = $225
               
               Risk Engine detects fill, then:
                 1. CANCEL old SL @ $22.50        (remove outdated stop)
                 2. Place NEW SL @ $25.00          (breakeven — Standard PT1)
                 3. Place PT2: SELL 60 @ $31.25    (25% above entry)
               
               Remaining: 140 shares, SL = $25.00, PT2 pending
               Worst case now = breakeven (not a loss!)
                    |
                    v
T + 1 hour     PT2 FILLS — ESCALATION CYCLE #2
               RKLB hits $31.25 → broker fills: SELL 60 @ $31.25
               Profit locked: 60 × ($31.25 - $25.00) = $375
               
               Risk Engine detects fill, then:
                 1. CANCEL old SL @ $25.00
                 2. Place NEW SL @ $26.25          (+5% above entry — Standard PT2)
                 3. Place PT3: SELL 80 @ $35.00    (40% above entry, runner)
               
               Remaining: 80 shares (runner), SL = $26.25, PT3 pending
               Worst case now = $1.25/share profit locked in
                    |
                    v
T + 2 hours    PRICE DROPS → ESCALATED SL FILLS
               RKLB drops back to $26.25 → SL fills: SELL 80 @ $26.25
               Cancel PT3 order (no longer needed)
               Runner profit: 80 × ($26.25 - $25.00) = $100
               
               Position fully closed!
               
               TOTAL PROFIT:
                 PT1:    60 shares × $3.75 profit  = $225
                 PT2:    60 shares × $6.25 profit  = $375
                 SL exit: 80 shares × $1.25 profit = $100
                 ─────────────────────────────────────────
                 TOTAL: $700 profit on $5,000 position (14% return)
```

---

## REAL TRADE EXAMPLE — Penny Stock (Phoenix Channel, LUNR)

**Setup:** Signal Mode, 500 shares of LUNR @ $8.20  
Phoenix message included: `SL $7.50, PT $9.80`

### Timeline:

```
T + 0 sec      ENTRY
               Phoenix sends: "BTO 500 LUNR @ $8.20, SL $7.50, PT $9.80"
               Bot places: BUY 500 LUNR @ MARKET
               NO bracket legs — just the entry order
               Cost: 500 × $8.20 = $4,100
                    |
                    v
T + 3 sec      RISK ENGINE DETECTS FILL → PLACES SIGNAL-PROVIDED BRACKET
               Signal mode + signal-provided SL/PT (from settings_source provenance)
               _place_initial_broker_bracket() places:
                 SL order:  SELL 500 LUNR @ $7.50 (stop)    [from Phoenix's message]
                 PT1 order: SELL 500 LUNR @ $9.80 (limit)   [from Phoenix's message]
               
               Penny stock protected at broker!
               Even if bot disconnects, SL at $7.50 protects against crash.
                    |
                    v
T + 45 min     PT1 FILLS
               LUNR hits $9.80 → broker fills: SELL 500 @ $9.80
               Cancel SL order (no longer needed)
               
               Position fully closed!
               Profit: 500 × ($9.80 - $8.20) = $800 (19.5% return)
```

### What Happens Today (Current Bug):

```
T + 0 sec      Phoenix sends: "BTO 500 LUNR @ $8.20, SL $7.50, PT $9.80"
               Signal mode checks _signal_has_bracket...
               
               IF provenance is correct:  bracket placed at entry  ← sometimes works
               IF provenance is wrong:    bracket SKIPPED           ← LUNR has NO protection!
               
               Risk Engine?  BLOCKED for signal mode — won't place brackets either.
               
               Result: 500 shares of a volatile penny stock with ZERO broker protection.
               LUNR drops 40% → you lose $1,640 with nothing to stop it.
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
