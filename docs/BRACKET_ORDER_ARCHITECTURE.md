# Bracket Order Architecture: Current vs Proposed

---

## V8.2.3 ARCHITECTURE (How Bracket Orders Actually Work)

There are **two separate systems** that place bracket orders, and they work in different modes.

### System 1: Entry-Time Brackets (in `selfbot_webull.py`)

When a stock signal arrives (e.g., `BTO 100 SMCI @ $42.50` from Phoenix), the bot first runs **Bracket Auto-Generation** — if the signal doesn't have SL/PT but the channel has them configured, it computes dollar prices from the channel percentages. Then `execute_on_single_broker()` decides whether to place the bracket:

```
Signal arrives -> Bracket Auto-Generation -> execute_on_single_broker()

BRACKET AUTO-GENERATION (line ~15353):
  - Only runs for stock BTO signals with a price
  - Only runs if exit mode is NOT 'signal' and NOT 'risk'
  - If signal has no SL but channel has stop_loss_pct:
      Computes SL price = entry × (1 - stop_loss_pct/100)
  - If signal has no PT but channel has profit_target_1_pct:
      Computes PT price = entry × (1 + pt1_pct/100)
  - Signal mode: SKIPPED ("exits via STC signals only")
  - Risk mode: SKIPPED ("progressive brackets placed by risk engine after fill")

BRACKET GATE (execute_on_single_broker, line ~16166):
  use_bracket = BTO + has SL/PT + broker supports it + exit_mode not in ('signal','risk')

  HYBRID mode:  YES — bracket placed at entry (entry + SL + PT1)
  SIGNAL mode:  NO — bracket always skipped (auto-gen also skipped)
  RISK mode:    NO — bracket always skipped (auto-gen also skipped)

PAPER TRADE GATE (line ~18548):
  use_bracket = BTO + has SL/PT + broker supports it + exit_mode != 'signal'
  NOTE: Risk mode NOT excluded here (inconsistency with main gate)

LIVE TRADE GATE (line ~18770):
  use_bracket = BTO + has SL/PT + broker supports it + exit_mode != 'signal'
  NOTE: Risk mode NOT excluded here (inconsistency with main gate)
```

### System 2: Risk Engine Brackets (in `position_monitor.py`)

After a trade fills, the Risk Engine detects the new position via broker sync and can place its own brackets:

```
Position detected -> _evaluate_position() -> checks broker_orders_placed flag

BRACKET TRIGGER (line ~3507):
  if channel_settings AND NOT cache.broker_orders_placed:
      if exit_mode in ('risk', 'hybrid'):
          _place_initial_broker_bracket()

  RISK mode:    YES — places bracket from channel SL% and PT1%
  HYBRID mode:  YES — places bracket from channel SL% and PT1%
  SIGNAL mode:  NO — skipped, risk engine does not place brackets
```

**What `_place_initial_broker_bracket()` does (line ~4161):**
- Computes SL price from channel `stop_loss_pct`
- Computes PT1 price from channel `profit_target_1_pct`
- Calculates tier qty (how many shares for PT1 using `calculate_auto_tier_quantities`)
- Places SL stop order + PT1 limit order at broker
- Stores `broker_stop_order_id` and `broker_pt_order_id` in cache
- Sets `broker_orders_placed = True` (prevents re-placement)

**What happens when PT1 fills (line ~3711):**
- Risk engine detects tier hit + `broker_orders_placed` + has `broker_pt_order_id`
- Enqueues `PLACE_PT{next}` broker operation
- `_place_next_pt_bracket()` places next tier's limit order at broker
- Also enqueues `RESIZE_STOP` to sync the stop order qty to remaining position

**What happens on Dynamic SL escalation (line ~3960):**
- When `MOVE_STOP` action fires, enqueues `SYNC_STOP` broker operation
- `_sync_stop_to_broker()` cancels old SL order, places new SL at escalated price
- Supports Schwab, Alpaca, Webull, IBKR, Tastytrade, Trading212, Robinhood
- Each broker uses cancel + resubmit (Schwab also has native replace)

**Signal-level SL/PT override (line ~650):**
- If the trade record has `stop_loss_price` and `profit_target_price` from the signal
- Risk engine converts those to percentages and uses them as overrides
- This works even when global risk is disabled (per-trade bracket from signal)

---

## PROBLEMS WITH V8.2.3 SETUP

### Problem 1: HYBRID MODE — Potential Duplicate Bracket Legs

Phoenix sends: `BTO 100 SMCI @ $42.50`  
Channel has SL=10%, PT1=+15% configured, exit mode = hybrid.

```
T+0s:  Bracket Auto-Gen: computes SL=$38.25, PT=$48.88
       execute_on_single_broker() places bracket:
         Entry: BUY 100 SMCI @ $42.50
         SL:    SELL 100 SMCI @ $38.25  (stop order)
         PT:    SELL 100 SMCI @ $48.88  (limit order)

T+15s: Risk Engine detects position
       broker_orders_placed = False (entry-time brackets don't set this flag!)
       Calls _place_initial_broker_bracket()
       Places ANOTHER SL: SELL 100 @ $38.25
       Places ANOTHER PT: SELL 100 @ $48.88

Result: 2 SL orders + 2 PT orders on the SAME 100 shares!
        If SL triggers, broker tries to sell 200 shares but you only have 100
```

### Problem 2: SIGNAL MODE — No Broker-Side Protection At All

Phoenix sends: `BTO 500 LUNR @ $8.20`  
Channel has SL=10% configured, exit mode = signal.  
Signal message didn't include SL/PT explicitly.

```
T+0s:  Bracket Auto-Gen: SKIPPED (exit_mode = 'signal')
       execute_on_single_broker(): bracket gate fails (exit_mode = 'signal')
       Entry order placed: BUY 500 LUNR @ $8.20

T+0s:  Position has ZERO protection at broker!
       500 shares of LUNR with no stop loss, no profit target
       Relies entirely on Phoenix sending "STC LUNR" message later

T+15s: Risk Engine detects position
       exit_mode = 'signal' → _place_initial_broker_bracket() SKIPPED

T+???  If bot goes offline -> position is completely unprotected!
       LUNR drops 30% -> you lose $1,230 with no SL to protect you
```

### Problem 3: RISK MODE — Works Well, But Has a ~3-15s Gap

Phoenix sends: `BTO 200 RKLB @ $25.00`  
Channel has SL=10%, PT1=+15%, exit mode = risk.

```
T+0s:   Bracket Auto-Gen: SKIPPED (exit_mode = 'risk')
        execute_on_single_broker(): bracket gate blocks risk mode
        Entry order placed: BUY 200 RKLB @ $25.00
        NO SL, NO PT at broker yet

T+3-15s: Risk Engine detects position via broker sync
         exit_mode = 'risk' → calls _place_initial_broker_bracket()
         Places SL @ $22.50 + PT1 SELL 60 @ $28.75
         Stores broker_stop_order_id and broker_pt_order_id
         Sets broker_orders_placed = True

Gap: ~3-15 seconds with no protection (fill-watch can reduce this)
     Risk mode OTHERWISE works correctly for the full lifecycle
```

### Problem 4: Risk Mode PT Cascade + SL Sync DOES Work (v8.2.3)

Continuing the RKLB risk mode example — this part actually works:

```
T+30m:  RKLB hits $28.75 → PT1 fills (SELL 60 @ $28.75)
        Risk Engine detects tier hit:
          1. Enqueues PLACE_PT2 → _place_next_pt_bracket() places PT2 at broker
          2. Enqueues RESIZE_STOP → _sync_stop_to_broker() updates SL qty

T+30m:  Dynamic SL escalation fires (MOVE_STOP action):
          Enqueues SYNC_STOP → _sync_stop_to_broker():
            cancel_order(old_sl_id)
            place new SL at escalated price (e.g., breakeven $25.00)

This cascade continues for PT2 → PT3 → etc.
```

**So risk mode in v8.2.3 already has working PT cascade and SL replacement!**  
The main gaps are: signal mode has no brackets, and hybrid mode has duplicates.

### Problem 5: Legacy Paper/Live Gates Allow Risk Mode (Bug)

```
Main gate (execute_on_single_broker):
  exit_mode not in ('signal', 'risk')     ← correctly blocks both

Paper gate:
  exit_mode != 'signal'                   ← only blocks signal, risk mode gets through!

Live gate:
  exit_mode != 'signal'                   ← only blocks signal, risk mode gets through!

If a stock signal goes through the legacy paper/live path in risk mode,
it WILL place a bracket at entry time → Risk Engine ALSO places brackets → duplicates
```

---

## IMPLEMENTED ARCHITECTURE (Single Owner: Risk Engine)

The core idea: **Remove all bracket logic from the entry path.** Make the Risk Engine the single owner of ALL bracket orders across ALL exit modes.

### Step 1: Entry Order (Same for ALL Modes)

Phoenix sends: `BTO 200 RKLB @ $25.00`

```
execute_on_single_broker() places ENTRY ONLY:
  BUY 200 RKLB @ $25.00 (market order)

NO bracket legs placed — no SL, no PT
This is the SAME regardless of exit mode (hybrid, signal, or risk)
```

**Implementation (completed):**
- All 3 bracket gates in `selfbot_webull.py` set `use_bracket = False` unconditionally
- Bracket auto-generation removed — Risk Engine uses channel percentages directly
- Signal-provided SL/PT still stored on trade record for Risk Engine consumption

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

**Implementation (completed):**
- `position_monitor.py`: Removed exit_mode gate — bracket now fires for ALL modes when SL>0 or PT1>0
- `get_channel_risk_settings()`: Now returns settings for signal mode when channel/signal SL/PT exists
- False `broker_orders_placed=True` removed when no levels exist (prevents silent suppression)

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

**Implementation (already working in v8.2.3, unchanged):**
- `_sync_stop_to_broker()` already fires on MOVE_STOP, ACTIVATE_EARLY_TRAIL, UPDATE_EARLY_STOP
- `_place_next_pt_bracket()` already fires on tier hit when `broker_orders_placed=True`
- RESIZE_STOP resizes SL qty after partial fills
- All brokers supported: Schwab, Alpaca, Webull (stocks), IBKR, Tastytrade, Trading212, Robinhood

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

### What Happened Before (v8.2.3 Bug — Now Fixed):

```
T + 0 sec      Phoenix sends: "BTO 500 LUNR @ $8.20, SL $7.50, PT $9.80"
               Signal mode checks _signal_has_bracket...
               
               IF provenance is correct:  bracket placed at entry  ← sometimes worked
               IF provenance is wrong:    bracket SKIPPED           ← LUNR had NO protection!
               
               Risk Engine?  BLOCKED for signal mode — wouldn't place brackets either.
               
               Result: 500 shares of a volatile penny stock with ZERO broker protection.

NOW (Fixed): Risk Engine places brackets for ALL modes after fill detection.
             Signal SL/PT flows through trade record to Risk Engine.
             No more provenance-dependent entry-time bracket ambiguity.
```

---

## BROKER-SPECIFIC SL REPLACEMENT

How each broker handles cancelling and replacing stop loss orders:

| Broker | Method | Details |
|--------|--------|---------|
| **Webull** | Cancel + New Order | `cancel_order(old_sl_id)` then `place_order(new_sl)`. Stocks only — options monitored locally |
| **Schwab** | Cancel + New Order | `cancel_order(old_sl_id)` then `place_stop_order(new_price)`. Stocks and options |
| **Alpaca** | Cancel + New Order | `cancel_order(old_sl_id)` then StopOrderRequest. Has OCO but replace via cancel+new |
| **IBKR** | Cancel + New Order | `cancel_order(old_sl_id)` then `place_stop_order(new_sl)` |
| **Tastytrade** | No Bracket Support | SL/PT monitored locally by Risk Engine. Market sell when triggered |
| **Trading212** | Cancel + New Order | Stocks only — options not supported |
| **Robinhood** | Cancel + New Order | `cancel_order(old_sl_id)` then `place_order(new_sl)` |

---

## CODE CHANGES SUMMARY (Implemented)

| File | Change | Status |
|------|--------|--------|
| `selfbot_webull.py` | All 3 bracket gates set `use_bracket = False` — entry always places simple order | ✅ Done |
| `selfbot_webull.py` | Bracket auto-generation removed — Risk Engine uses channel percentages directly | ✅ Done |
| `position_monitor.py` | Removed exit_mode gate — `_place_initial_broker_bracket()` fires for ALL modes when SL>0 or PT1>0 | ✅ Done |
| `position_monitor.py` | `get_channel_risk_settings()` now returns settings for signal mode when channel/signal SL/PT exists | ✅ Done |
| `position_monitor.py` | Removed false `broker_orders_placed=True` when no SL/PT levels exist | ✅ Done |
| `position_monitor.py` | PT cascade + SL sync already working from v8.2.3 (unchanged) | ✅ Existing |
| `settings_source` | Provenance flags (`sl:signal`, `pt:signal`, etc.) preserved for audit trail | ✅ Existing |
