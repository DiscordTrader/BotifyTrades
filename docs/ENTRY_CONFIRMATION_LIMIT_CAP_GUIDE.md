# Entry Confirmation & Limit Cap — How It Works

## Overview

Entry Confirmation and Limit Cap are two channel settings that work together to give you **smart entry protection** on stock trades. Instead of buying instantly when a signal arrives, the bot waits for the price to confirm the breakout, then places a limit order with a price ceiling so you never overpay.

---

## The Two Settings

### Entry Confirmation (%)

**What it does:** Converts a normal buy signal into a conditional (watched) order. The bot won't buy immediately — it monitors the price and only buys when the stock moves up by your specified percentage above the signal price.

**Why use it:** Filters out fake breakouts. If a signal says "GXAI over $2.60" but the stock never actually breaks above $2.60, no money is spent.

**Where to set it:** Admin → Channels → Settings → Entry Confirmation %

---

### Limit Cap (%)

**What it does:** Sets a maximum price you're willing to pay. When the conditional order triggers, instead of chasing the stock at any price, the bot places a **limit order** at the trigger price + your cap percentage.

**Why use it:** Prevents buying at an inflated price if the stock spikes fast after the trigger. You either get filled at a reasonable price or you don't get filled at all.

**Where to set it:** Admin → Channels → Settings → Limit Cap toggle + Limit Cap %

---

## How They Work Together — Step by Step

### Example: Signal "BTO GXAI over $2.60" with Entry Confirmation 0% + Limit Cap 5%

```
Signal arrives: "BTO GXAI over $2.60"
Current price: $2.58

Step 1 — Conditional Order Created
  ┌─────────────────────────────────┐
  │ Trigger: Buy when GXAI ≥ $2.60 │
  │ Limit Cap: 5% above trigger    │
  │ Max buy price: $2.73            │
  │ Status: MONITORING              │
  └─────────────────────────────────┘
  The bot is watching the price. No order placed yet.

Step 2 — Price Monitoring
  Time     Price    Action
  10:01    $2.58    Watching... (below $2.60 trigger)
  10:02    $2.55    Watching... (below $2.60 trigger)
  10:03    $2.59    Watching... (below $2.60 trigger)
  10:04    $2.61    TRIGGERED! Price crossed $2.60

Step 3 — Limit Order Placed
  ┌─────────────────────────────────────┐
  │ BUY GXAI                            │
  │ Order Type: LIMIT                   │
  │ Limit Price: $2.73 (trigger + 5%)   │
  │ Current market: $2.61               │
  │ Result: FILLS at $2.61 ✅           │
  └─────────────────────────────────────┘
  Market price ($2.61) is below the cap ($2.73),
  so the limit order fills at $2.61.
```

### Example: What Happens When the Price Spikes Past Your Cap

```
Signal arrives: "BTO GXAI over $2.60"
Limit Cap: 5% → Max buy price: $2.73

  Time     Price    Action
  10:01    $2.58    Watching...
  10:02    $2.59    Watching...
  10:03    $2.90    TRIGGERED! Price crossed $2.60
                    BUT $2.90 > $2.73 cap
                    Limit order placed at $2.73
                    Market is at $2.90 → ORDER WON'T FILL ✅

  Protection worked! You didn't chase the stock
  up to $2.90. If it pulls back to $2.73 or below,
  the limit order fills. Otherwise, you skip the trade.
```

---

## Example with Entry Confirmation + Limit Cap Combined

### Settings: Entry Confirmation 2% + Limit Cap 5%

```
Signal arrives: "BTO PAVM at $10.00"
Current price: $10.00

Step 1 — Entry Confirmation Adjusts the Trigger
  Signal price:    $10.00
  Confirmation %:  2%
  New trigger:     $10.20 ($10.00 × 1.02)

  The bot now waits for PAVM to reach $10.20
  (proving the stock is actually moving up).

Step 2 — Limit Cap Computed from Trigger
  Trigger price:   $10.20
  Limit Cap %:     5%
  Max buy price:   $10.71 ($10.20 × 1.05)

Step 3 — Monitoring
  Time     Price     Action
  10:01    $10.00    Watching... (below $10.20)
  10:05    $10.10    Watching... (below $10.20)
  10:08    $10.15    Watching... (below $10.20)
  10:12    $10.22    TRIGGERED! Crossed $10.20

Step 4 — Order Placement
  ┌─────────────────────────────────────────┐
  │ BUY PAVM                                │
  │ Limit Price: $10.71 (hard ceiling)      │
  │ Market: $10.22 → FILLS at $10.22 ✅    │
  └─────────────────────────────────────────┘
```

---

## Trigger Offset (Optional Fine-Tuning)

**Trigger Offset** adjusts the trigger price slightly — useful when you want the trigger to be a bit above or below the signal price.

| Mode | Example | Effect |
|------|---------|--------|
| Percent: **-1%** | Signal $2.60 | Trigger becomes $2.574 (fires sooner) |
| Percent: **+2%** | Signal $2.60 | Trigger becomes $2.652 (fires later) |
| Dollar: **-$0.05** | Signal $2.60 | Trigger becomes $2.55 |
| Dollar: **+$0.10** | Signal $2.60 | Trigger becomes $2.70 |

**Note:** Entry Confirmation and Trigger Offset both adjust the trigger price. If both are set, Entry Confirmation is applied first (at signal arrival), then Trigger Offset is applied on top (at conditional order creation).

---

## Channel Order Mode Interaction

Your channel can be set to "market" or "limit" order mode. Here's how it interacts:

| Channel Mode | Limit Cap OFF | Limit Cap ON |
|---|---|---|
| **Limit mode** | Limit order at signal price | Limit order at cap price (ceiling) |
| **Market mode** | Market order (no price limit) | **Limit order at cap price** — cap overrides market mode |

**Important:** When Limit Cap is enabled, it always acts as a hard ceiling, even if your channel is set to market order mode. This is by design — the whole point of Limit Cap is to prevent overpaying.

---

## Settings Summary Table

| Setting | DB Field | Default | What It Controls |
|---|---|---|---|
| Entry Confirmation % | `entry_confirmation_pct` | 0 (off) | How far above signal price the stock must go before buying |
| Limit Cap Enabled | `limit_cap_enabled` | Off | Toggle for price ceiling protection |
| Limit Cap % | `limit_cap_pct` | 5% | Maximum buy price = trigger + this % |
| Trigger Offset Mode | `trigger_offset_mode` | percent | Whether offset is in % or $ |
| Trigger Offset Value | `trigger_offset_value` | 0 | Additional trigger price adjustment |
| Entry Order Mode | `entry_order_mode` | limit | Market or limit (Limit Cap overrides when enabled) |

---

## Quick Setup Recipes

### Recipe 1: "Buy the breakout, but don't chase" (Most Common)
- Entry Confirmation: **0%** (use the signal's trigger price as-is)
- Limit Cap: **ON, 5%**
- Result: Buys when trigger is hit, but never pays more than 5% above trigger.

### Recipe 2: "Confirm the move first, then buy safely"
- Entry Confirmation: **2%**
- Limit Cap: **ON, 3%**
- Result: Waits for a 2% move to confirm direction, then caps the buy at 3% above the confirmed trigger.

### Recipe 3: "I trust the signal, just get me in"
- Entry Confirmation: **0%**
- Limit Cap: **OFF**
- Entry Order Mode: **market**
- Result: Market order fires immediately at whatever the current price is. No protection.

### Recipe 4: "Conservative breakout with tight cap"
- Entry Confirmation: **1%**
- Limit Cap: **ON, 2%**
- Trigger Offset: **-0.5%** (enter slightly earlier)
- Result: Trigger at signal price + 0.5%, cap at trigger + 2%. Very tight entry window.

---

## Visual Flow Diagram

```
Signal Arrives (BTO GXAI $2.60)
        │
        ▼
┌─── Entry Confirmation? ───┐
│                            │
│  YES (2%)                  │  NO
│  Trigger = $2.60 × 1.02   │  Trigger = $2.60
│  = $2.652                  │
└────────┬───────────────────┘
         │
         ▼
┌─── Trigger Offset? ───────┐
│                            │
│  YES (-1%)                 │  NO
│  Trigger = $2.652 × 0.99  │  Trigger stays
│  = $2.6255                 │
└────────┬───────────────────┘
         │
         ▼
  Conditional Order Created
  Bot monitors price...
         │
         ▼
  Price hits trigger ─────────── Price never reaches trigger
         │                              │
         ▼                              ▼
┌─── Limit Cap? ────────────┐    Order expires (timeout)
│                            │
│  YES (5%)                  │  NO
│  Limit = Trigger × 1.05   │  Market or limit at
│  = max price ceiling       │  signal price
└────────┬───────────────────┘
         │
         ▼
  Market ≤ Cap?
  YES → Fills at market ✅
  NO  → Won't fill (protected) 🛡️
```
