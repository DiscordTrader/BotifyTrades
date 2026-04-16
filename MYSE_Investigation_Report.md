# MYSE Trade — What Actually Happened
**Date of events:** 16 April 2026, 14:09–14:13 EST
**Symbol:** MYSE (stock, 1 share on Webull)
**Channel settings used:** "test" — Stop Loss 1.0%, Take Profit 1.0%

---

## Your Concern
> "MYSE didn't execute stop loss and didn't place a TP bracket order."

## Short Answer
Both things **did** happen — but for the wrong reasons, so from the broker's screen it looked like nothing worked.

- The **Take Profit bracket WAS placed** at $3.91 on Webull.
- The **Stop Loss WAS triggered** almost immediately and cancelled that TP bracket one second later.
- Net result: you ended up flat at ≈ $3.78 with a $0.01 profit, and no visible TP order on Webull — looking exactly like "nothing happened."

The bot acted on a **wrong entry price** ($3.87 instead of the real fill $3.77), which is why both orders ended up at wrong levels and the SL fired instantly.

---

## What You Saw in the Log
```
[RISK] 🆕 NEW POSITION DETECTED: MYSE on Webull (qty=1.0, avg_cost=$3.77, current=$3.78)
[RISK] 📋 PROGRESSIVE BRACKET: MYSE entry=$3.87 SL=N/A PT1=$3.91 …
```

Notice the contradiction on these two lines:
- **Line 1** (from Webull): actual average cost = **$3.77**
- **Line 2** (from risk engine): entry used = **$3.87**

The bot is receiving the correct price from the broker, then internally using a different, stale one to calculate the bracket orders.

---

## Why Two Different Entry Prices Existed

### Step 1 — You had a prior MYSE trade in the database
When the bot restarted, it loaded trade **#826** from its memory, which was recorded with an entry price of **$3.87** (from an earlier session or an earlier manual fill).

### Step 2 — A new signal came in: "myse ober 3.72"
This created **conditional order #511**, which triggered a new BUY at $3.7750 and Webull filled it at **$3.77**.

### Step 3 — Webull merged the two into one position
Webull doesn't keep two separate "lots" for the same stock. It combined them and reported **1 share @ avg $3.77**.

### Step 4 — The database got corrected, but the live risk cache did not
The bot's sync routine noticed the mismatch and updated the database:
```
[SYNC] ✓ Trade #826 (MYSE) entry price synced: DB=$3.8700 → Broker=$3.7700
```
**However**, the *in-memory* risk engine (the part that decides when to place TP/SL) keeps its own cached copy of the entry price. That cached copy was **not** refreshed.

### Step 5 — The "safety tolerance" silently kept the wrong number
Inside the risk engine there is a guard rule:

> "If the broker's new average cost differs from my cached entry by less than **5%**, ignore the change."

The purpose is to avoid overreacting to tiny broker rounding differences. But in this case:

- Old cached price: **$3.87**
- New real price: **$3.77**
- Difference: **2.6%**  → below the 5% threshold → **change discarded, stale $3.87 kept.**

For a stock trading around $3.77, a 10-cent discrepancy is enormous — but the rule treats it as noise.

### Step 6 — Bracket orders were calculated from the wrong number
- Take Profit = $3.87 × 1.01 = **$3.91** (placed on Webull, order ID `9PHUS…QSSB`).
- Stop Loss came from an *older* conditional order (#510) that had been set up with **SL = $3.80** — a level *above* the real fill of $3.77.

### Step 7 — Instant stop-loss trigger
On the very next tick the engine saw current price = $3.78, compared it to its SL = $3.80, and concluded "price is below stop loss → exit now."
The TP bracket it had just placed 1 second earlier was cancelled, and a market SELL was sent.

### Step 8 — The cancel request actually failed, but was logged as success
```
⚠️ Cancel order 9PHUS…QSSB response: False      ← Webull said NO
✅ Cancelled broker PT1 order #9PHUS…QSSB        ← Bot reported YES
```
The cancel might not have actually gone through at Webull. In this case the market sell filled first so it didn't matter, but it is a silent failure path.

---

## Timeline at a Glance

| Time (EST) | Event |
|---|---|
| 14:09:39 | Bot restart. Loaded trade #826 with stale entry **$3.87**. Cached SL = $3.80 from old conditional #510. |
| 14:10:47 | New Discord signal "myse ober 3.72" → conditional #511 created. |
| 14:10:48 | Signal triggers → BUY placed. |
| 14:10:52 | Webull fills @ **$3.77**. Database row corrected ($3.87 → $3.77). **Risk cache not updated** (2.6% < 5% tolerance). |
| 14:10:54 | Risk engine evaluates using stale $3.87 → places TP @ **$3.91**. |
| 14:10:55 | Same cycle: current $3.78 ≤ cached SL $3.80 → **Stop-loss triggers**. TP cancel request sent. |
| 14:10:56 | Webull refuses the cancel (`response: False`), bot logs it as ✅ success. Market SELL placed. |
| 14:10:57 | Market SELL fills @ $3.78. Position closed, net +$0.01. |
| 14:11:01 | Broker still shows 1 share (old trade #826 still linked). Cache finally refreshes entry to $3.77 because the "closing" flag is now on. |
| 14:11:32 | Second stop-loss trigger for trade #826 at $3.76. Market SELL → flat. |
| 14:13:10 | New signal "myse ober 3.68" → conditional #512. Fills @ $3.73. |
| 14:13:14 | New cycle shows `Entry: $3.73 \| SL: $3.7996` — **the old stale $3.80-level SL is STILL cached** and would fire again on any price drop. |

---

## Why the TP Bracket Looks Missing on Webull
It was placed at 14:10:55 and cancelled at 14:10:56 — **one second later**. By the time you checked Webull, only the market-sell fill remained visible.

## Why It Looks Like the Stop Loss Didn't Fire
It fired *too early* and at a *nonsensical level* ($3.80 — above the actual fill of $3.77). The bot sold for essentially break-even, which feels nothing like "hit my 1% stop loss at $3.73". From your perspective, when price later dropped to $3.68, no stop loss fired **because the position was already closed earlier**.

---

## Root Causes (Ranked by Impact)

| # | Issue | Where |
|---|---|---|
| 1 | **Conditional order #510 had `SL = $3.80` paired with a fill at $3.77** — an SL above entry for a long position is guaranteed to fire immediately. No validator rejects this impossible pairing. | Conditional order creation / risk linking |
| 2 | **The 5% tolerance ignored a real $3.87 → $3.77 correction** for a sub-$5 stock. Tolerance should be tighter for low-priced equities, or keyed to absolute cents rather than percent. | `position_cache.py` — `ENTRY_PRICE_CHANGE_TOLERANCE = 0.05` |
| 3 | **Risk cache's stop-loss price is never recomputed when the entry finally refreshes**, so a stale $3.80-level SL survived across three separate MYSE fills ($3.87 → $3.77 → $3.73) and would have fired wrongly on any future trade at this symbol/broker. | `position_cache.py` reset branch only updates `entry_price`, not `stop_loss_price` / `profit_target_price` |
| 4 | **Bracket orders have no "just-placed grace period"** — a TP can be placed and cancelled within the same evaluation cycle if an SL check runs microseconds later. | `position_monitor.py` — SL evaluation runs in same loop iteration as bracket placement |
| 5 | **Failed Webull cancel (`response: False`) is logged as success** — risk of stranded orders at the broker. | Cancel-order handler |
| 6 | **Webull streaming ticks aren't reaching the risk evaluator for MYSE** — the bot keeps falling back to Schwab REST quotes every few seconds (`🔄 STUCK PRICE FIX`), causing ~2-10 second lags in price updates. | Webull stream → risk cache pipeline |

---

## What It Looks Like After Fixing (for context)
With the real entry $3.77 and channel 'test' settings (1% SL, 1% TP):
- Correct SL level: **$3.7323**
- Correct TP level: **$3.8077**
- Price path $3.78 → $3.76 → $3.79 → $3.76 would **not** have triggered SL.
- TP would only fire if price reached $3.81+ — which it briefly touched around 14:10:54 and could have exited cleanly.

---

*No code changes were made during this investigation. This document only explains what the logs show.*
