# Risk Management System — Settings Guide

This document explains every risk management setting, how they work together, and which combinations to use for different trading styles.

---

## Table of Contents

1. [Quick-Start Presets](#1-quick-start-presets)
2. [Profit Targets (T1/T2/T3/T4)](#2-profit-targets-t1t2t3t4)
3. [Trim Order Mode](#3-trim-order-mode-market-vs-limit)
4. [Broker Bracket Orders & Native OCO](#4-broker-bracket-orders--native-oco)
5. [Stop Loss](#5-stop-loss)
6. [Dynamic SL (SL Escalation)](#6-dynamic-sl-sl-escalation)
7. [Early Trailing](#7-early-trailing)
8. [Trailing Stop](#8-trailing-stop)
9. [Giveback Guard](#9-giveback-guard)
10. [Leave Runner](#10-leave-runner)
11. [Exit Strategy Mode](#11-exit-strategy-mode)
12. [Feature Interaction Matrix](#12-feature-interaction-matrix)
13. [Common Scenarios Walkthrough](#13-common-scenarios-walkthrough)

---

## 1. Quick-Start Presets

Choose the preset closest to your style, then customize individual settings.

### Scalper (Quick In/Out)
| Setting | Value |
|---------|-------|
| Profit Targets | T1: 3%, T2: 5% |
| Stop Loss | 2% |
| Trim Order Mode | Market |
| Dynamic SL | Off |
| Early Trailing | Off |
| Leave Runner | Off |

### Swing Trader (Hold for Bigger Moves)
| Setting | Value |
|---------|-------|
| Profit Targets | T1: 8%, T2: 15%, T3: 25% |
| Stop Loss | 10% |
| Trim Order Mode | Limit |
| Dynamic SL | Standard profile |
| Early Trailing | On (activation: 5%, step: 3%) |
| Leave Runner | On (25%) |

### Momentum Runner (Let Winners Run)
| Setting | Value |
|---------|-------|
| Profit Targets | T1: 10%, T2: 20%, T3: 35%, T4: 50% |
| Stop Loss | 12% |
| Trim Order Mode | Market |
| Dynamic SL | Conservative profile |
| Early Trailing | Off |
| Trailing Stop | 8% (activation: 15%) |
| Leave Runner | On (30%) |
| Giveback Guard | On (30%) |

---

## 2. Profit Targets (T1/T2/T3/T4)

Profit targets define percentage gains where you want to sell portions of your position. Up to 4 tiers are supported.

### Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `profit_target_1_pct` | % gain to trigger Tier 1 sell | 0 (disabled) |
| `profit_target_2_pct` | % gain to trigger Tier 2 sell | 0 (disabled) |
| `profit_target_3_pct` | % gain to trigger Tier 3 sell | 0 (disabled) |
| `profit_target_4_pct` | % gain to trigger Tier 4 sell | 0 (disabled) |

### How Quantity Per Tier Is Decided

There are three ways to control how many shares sell at each tier (checked in this order):

#### Option A: Fixed Quantity Per Tier
Set an exact number of shares to sell at each tier.

| Setting | Description |
|---------|-------------|
| `profit_target_qty_1` | Exact shares to sell at T1 |
| `profit_target_qty_2` | Exact shares to sell at T2 |
| `profit_target_qty_3` | Exact shares to sell at T3 |
| `profit_target_qty_4` | Exact shares to sell at T4 |

**Example**: You own 100 shares. `qty_1=25, qty_2=25, qty_3=25, qty_4=25` → Sell 25 at each tier.

#### Option B: Trim Percentage Per Tier
Set what percentage of the *sellable* position to sell at each tier.

| Setting | Description |
|---------|-------------|
| `profit_target_trim_pct_1` | % of sellable shares to sell at T1 |
| `profit_target_trim_pct_2` | % of sellable shares to sell at T2 |
| `profit_target_trim_pct_3` | % of sellable shares to sell at T3 |
| `profit_target_trim_pct_4` | % of sellable shares to sell at T4 |

**Example**: 100 shares, `trim_pct_1=30` → Sell 30 shares at T1. Remaining 70 shares are split across remaining tiers.

#### Option C: Auto-Calculate (default)
If neither qty nor trim_pct is set, shares are split equally across remaining active tiers.

**Example**: 100 shares, 4 tiers active → ~25 per tier.  
**Example**: 12 shares, 3 tiers active → 4 per tier.

#### Small Position Handling
| Position Size | Behavior |
|---------------|----------|
| 1 contract | Sells all at first PT hit (full close) |
| 2 contracts, 2+ tiers | Sells 1 at T1, 1 at T2 |
| 2 contracts, 1 tier | Sells all at T1 |

### How Tiers Execute

Tiers execute **sequentially** — T2 only evaluates after T1 has filled, T3 after T2, etc.

```
Price rises to T1 → Sell T1 qty → Mark T1 hit
Price rises to T2 → Sell T2 qty → Mark T2 hit
Price rises to T3 → Sell T3 qty → Mark T3 hit
Price rises to T4 → Sell T4 qty → Mark T4 hit
```

A tier is skipped if:
- It was already hit (`tierN_hit = true`)
- There's a pending order for that tier awaiting fill
- The tier % is set to 0 (disabled)

### Interaction with Other Features
- **Leave Runner**: Reserves shares that won't be sold at ANY tier (see [Leave Runner](#10-leave-runner))
- **Dynamic SL**: After each tier hit, SL can escalate upward (see [Dynamic SL](#6-dynamic-sl-sl-escalation))
- **Bracket Orders**: How the tier sell is placed at the broker depends on `trim_order_mode` (see next section)

---

## 3. Trim Order Mode (Market vs Limit)

Controls HOW profit target sells are executed at the broker.

| Mode | Description | Best For |
|------|-------------|----------|
| `market` | Sell at current market price when PT hits | Fast fills, volatile stocks |
| `limit` | Sell at a limit price near the PT level | Better fill prices, liquid stocks |

### Market Mode
- The **software risk engine** detects when price hits a PT level, then sends a market sell
- No limit order is pre-placed at the broker
- Fills immediately at whatever the bid price is
- **No broker-native OCO** — only a standalone stop loss is placed at the broker

### Limit Mode
- A **limit sell order** is pre-placed at the broker at the PT price (with an offset)
- Can use **native OCO** bracket orders that link SL and PT together
- The broker fills the PT when price reaches the limit
- Better fills but may not execute in fast-moving markets

### Limit Offset Settings

When `trim_order_mode = 'limit'`, these control how far below the PT price the limit is set:

| Setting | Description | Default |
|---------|-------------|---------|
| `trim_limit_offset_mode` | `'dollar'` or `'percent'` | `'dollar'` |
| `trim_limit_offset` | Dollar amount below PT price | $0.01 |
| `trim_limit_offset_pct` | Percent below PT price | 2.0% |

**Dollar mode example**: PT at $50.00, offset $0.05 → Limit at $49.95  
**Percent mode example**: PT at $50.00, offset 2% → Limit at $49.00

For penny stocks (< $1.00), 4 decimal precision is used. If the calculated limit would be ≤ $0, it defaults to 8% below current price.

### Decision Diagram

```
trim_order_mode = ?
    │
    ├─ 'market'
    │   ├─ Broker: Standalone STOP order only (for SL)
    │   ├─ PT execution: Software risk engine sends market sell when PT% hit
    │   └─ OCO: NOT used
    │
    └─ 'limit'
        ├─ If SL + PT both configured + equity (not option):
        │   └─ Broker: Native OCO bracket (SL + PT linked)
        ├─ If only SL or only PT:
        │   └─ Broker: Separate STOP + LIMIT orders
        └─ PT execution: Broker fills the limit order automatically
```

---

## 4. Broker Bracket Orders & Native OCO

### What Are Bracket Orders?

Bracket orders are protective orders placed at the broker that automatically execute without the bot needing to be running. They provide safety if the bot loses connection.

| Order Type | Purpose |
|------------|---------|
| **STOP** (stop-loss) | Sells if price drops to SL level |
| **LIMIT** (profit target) | Sells if price rises to PT level |
| **OCO** (one-cancels-other) | Links SL + PT — when one fills, the other auto-cancels |

### Bracket Mode Setting

| Setting | Description |
|---------|-------------|
| `broker_bracket_mode = 'both'` | Place both SL and PT at broker (default) |
| `broker_bracket_mode = 'sl_only'` | Only SL at broker, software handles PT |
| `broker_bracket_mode = 'pt_only'` | Only PT at broker, software handles SL |
| `broker_bracket_mode = 'none'` | No broker orders, software handles everything |

### When Is Native OCO Used?

Native OCO (Schwab's `orderStrategyType: "OCO"`) is used when ALL of these are true:
1. `trim_order_mode = 'limit'` (not market)
2. Both SL price and PT price are valid (> 0)
3. PT quantity > 0
4. Position is equity (not an option)
5. `broker_bracket_mode` allows both SL and PT

### OCO + Standalone Stop Pattern

When a position has more shares than the T1 trim quantity, the system places:

```
Example: 100 shares, T1 sells 25 shares

OCO Order (25 shares):
  ├─ Leg 1: STOP SELL 25 @ $45.00 (SL)
  └─ Leg 2: LIMIT SELL 25 @ $55.00 (PT)
  → If PT fills: SL auto-cancels for these 25 shares
  → If SL triggers: PT auto-cancels for these 25 shares

Standalone STOP (75 shares):
  └─ STOP SELL 75 @ $45.00 (SL for remaining shares)
  → Always active regardless of OCO outcome
```

**When SL triggers**: Both OCO-SL (25) and standalone STOP (75) fire = full 100-share exit.  
**When PT fills**: OCO-SL auto-cancels (25 shares protected). Standalone STOP (75) remains active.

### After a Tier Fills (Cascade)

When T1 fills, the system:
1. Cancels the old OCO bracket
2. Calculates T2 price and quantity
3. Places a new OCO for T2 (SL + PT for T2 qty)
4. Updates the standalone stop for the remaining shares
5. Escalates SL if Dynamic SL is enabled

```
After T1 fill (75 shares remain, T2 sells 25):

New OCO Order (25 shares):
  ├─ Leg 1: STOP SELL 25 @ $47.00 (escalated SL)
  └─ Leg 2: LIMIT SELL 25 @ $60.00 (T2 price)

Updated Standalone STOP (50 shares):
  └─ STOP SELL 50 @ $47.00 (escalated SL)
```

### When OCO Is NOT Used

| Condition | What Happens Instead |
|-----------|---------------------|
| `trim_order_mode = 'market'` | Standalone STOP only. Risk engine sells at market when PT hits. |
| Option contracts | Separate STOP + LIMIT orders (OCO not supported for options) |
| OCO placement fails (429, API error) | Falls back to separate STOP + LIMIT orders |
| `broker_bracket_mode = 'sl_only'` | Only STOP order. Software handles PT. |

### SL Order Mode

| Setting | Description |
|---------|-------------|
| `sl_order_mode = 'market'` | Stop triggers a market sell (guaranteed fill, possible slippage) |
| `sl_order_mode = 'limit'` | Stop triggers a limit sell (better price, may not fill) |
| `sl_limit_offset` | How far below SL price to set the limit (default: $0.03) |

---

## 5. Stop Loss

The initial stop loss that protects the position from the moment of entry.

### Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `stop_loss_pct` | % below entry to trigger SL | 0 (disabled) |

### SL Source Priority

Multiple systems can set the stop loss price. They are checked in this order:

```
1. Manual Override Price  (manual_sl_price)   ← Highest priority
2. Manual Override %      (manual_sl_pct)
3. Dynamic SL             (dynamic_sl_price)  ← After PT hits
4. Channel SL             (stop_loss_pct)     ← Default fallback
```

**Manual overrides** are set via Discord commands (e.g., `!sl AKAN 9.50`) and take top priority unless exit_strategy_mode is 'risk'.

### How It Works

```
Entry price: $50.00
Stop loss: 10%
SL price: $50.00 × (1 - 10/100) = $45.00

If current price drops to $45.00 or below → SELL ALL shares
```

### Dynamic SL Floor

When Dynamic SL is active, there's a safety floor. If the Dynamic SL price would be TIGHTER (higher) than the channel SL, the channel SL takes over:

```
Entry: $50.00
Channel SL: 10% → $45.00
Dynamic SL after T1: $50.00 (breakeven)

Since $50.00 > $45.00, Dynamic SL wins.
But if Dynamic SL calculated $44.00 (below channel SL floor), channel SL $45.00 is used instead.
```

---

## 6. Dynamic SL (SL Escalation)

Dynamic SL automatically moves the stop loss upward as profit targets are hit. This locks in progressively more profit.

### Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `enable_dynamic_sl` | Enable/disable feature | Off |
| `dynamic_sl_profile` | `'conservative'`, `'standard'`, or `'aggressive'` | `'standard'` |

### Profiles

Each profile defines where the SL moves after each tier hit:

| Event | Conservative | Standard | Aggressive |
|-------|-------------|----------|------------|
| **T1 hit** | Breakeven (0%) | Breakeven (0%) | Entry -2% (still allows small loss) |
| **T2 hit** | Entry +3% | Entry +5% | Breakeven (0%) |
| **T3 hit** | Entry +8% | Entry +10% | Entry +8% |
| **T4 hit** | Entry +15% | Entry +17% | Entry +15% |

### Example with Standard Profile

```
Entry: $10.00, Initial SL at $9.00 (-10%)

Price hits T1 (7.8% = $10.78):
  → Sell T1 shares
  → SL escalates to $10.00 (breakeven, 0%)
  → Broker stop updated from $9.00 → $10.00

Price hits T2 (10% = $11.00):
  → Sell T2 shares
  → SL escalates to $10.50 (entry +5%)
  → Broker stop updated from $10.00 → $10.50

Price hits T3 (15% = $11.50):
  → Sell T3 shares
  → SL escalates to $11.00 (entry +10%)
  → Broker stop updated from $10.50 → $11.00
```

### Ratchet Beyond Last Tier

After ALL tiers are hit, if price continues rising, the SL ratchets up to maintain the same "giveback distance" as the last tier:

```
All 4 tiers hit. Profile says T4 SL = entry +17%.
T4 was at +20%. Giveback allowed = 20% - 17% = 3%.

Price rises to +30%:
  → New SL = 30% - 3% = +27% above entry
  → SL ratchets up with price, always 3% behind
```

### How It Syncs to Broker

When the Dynamic SL price changes:
1. The risk engine calculates the new SL price
2. If it's higher than the current SL (never moves down), it updates `cache.dynamic_sl_price`
3. Enqueues a broker operation to update the stop order
4. **If OCO is active**: Cancel old OCO → Place new OCO with new SL + same PT
5. **If standalone stop**: Cancel old stop → Place new stop at new SL price

### Safety Cap
The dynamic SL is always capped at 2% below the current price. This prevents the SL from being set too close and triggering on normal price fluctuations.

---

## 7. Early Trailing

A profit-locking mechanism that activates earlier than a traditional trailing stop. It locks in breakeven first, then ratchets up in fixed steps.

### Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `enable_early_trailing` | Enable/disable | Off |
| `early_trailing_activation_pct` | % gain to activate (lock breakeven) | 5.0% |
| `early_trailing_step_pct` | Each profit step to lock | 3.0% |

### How It Works — Step by Step

```
Entry: $10.00
Activation: 5%
Step: 3%

1. Price at $10.40 (+4%): INACTIVE — below activation threshold
   → Stop remains at channel SL (e.g., $9.00)

2. Price hits $10.50 (+5%): ACTIVATED — lock breakeven
   → early_stop_price = $10.00 (entry price)
   → Steps locked: 0

3. Price rises to $10.79 (+7.9%): No new step yet
   → Need +8% for step 1 (activation 5% + 1×3%)
   → Stop stays at $10.00

4. Price hits $10.80 (+8%): STEP 1 LOCKED
   → early_stop_price = $10.00 × (1 + 3/100) = $10.30
   → Steps locked: 1

5. Price hits $11.10 (+11%): STEP 2 LOCKED
   → early_stop_price = $10.00 × (1 + 6/100) = $10.60
   → Steps locked: 2

6. Price drops to $10.60: EXIT TRIGGERED
   → Sells at $10.60, locking +6% profit
```

### Visual Timeline

```
Price %   Action
───────────────────────────────────
  +12%    ·························· Step 2 stop at +6%
  +11%    ■ Step 2 locked
  +10%    │
   +9%    │
   +8%    ■ Step 1 locked ········· Step 1 stop at +3%
   +7%    │
   +6%    │
   +5%    ■ Activated ············· Breakeven stop at 0%
   +4%    │ (not yet activated)
   +3%    │
   +2%    │
   +1%    │
    0%    ■ Entry ················· Channel SL (e.g., -10%)
  -10%    ■ Channel SL
```

### Interaction with Dynamic SL

Both features can be active. The HIGHER of the two stop prices is used:

```
After T1 hit:
  Dynamic SL says: $10.00 (breakeven via standard profile)
  Early Trailing says: $10.30 (step 1 locked)
  → Effective SL: $10.30 (early trailing wins — it's higher)
```

### Cannot Combine With Trailing Stop

Early Trailing and Trailing Stop are **mutually exclusive**. Enabling both will show an error. Choose one:

| Feature | When to Use |
|---------|------------|
| Early Trailing | Want to lock breakeven early, then ratchet in fixed steps |
| Trailing Stop | Want a simple % trail from the highest price reached |

---

## 8. Trailing Stop

A traditional trailing stop that activates at a profit threshold and then trails a fixed percentage below the highest price.

### Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `trailing_stop_pct` | % distance below highest price | 0 (disabled) |
| `trailing_activation_pct` | % gain required before trailing activates | 15% |

### How It Works

```
Entry: $10.00
Trailing: 5%
Activation: 15%

Phase 1: NOT YET ACTIVATED (price below +15%)
  → Channel SL at $9.00 (-10%) protects position
  → Highest price tracked but trailing not applied

Phase 2: ACTIVATED (price hits $11.50 = +15%)
  → Trailing stop = highest_price × (1 - 5/100)
  → $11.50 × 0.95 = $10.925

Phase 3: PRICE CONTINUES RISING
  → Price hits $12.00: trailing = $12.00 × 0.95 = $11.40
  → Price hits $13.00: trailing = $13.00 × 0.95 = $12.35
  → Trailing only moves UP, never down

Phase 4: PRICE REVERSES
  → Highest was $13.00, trailing at $12.35
  → Price drops to $12.35: EXIT — sell all shares
```

### Key Behaviors

- **Trailing only moves up**: Once the stop ratchets to $12.35, it stays there even if price drops
- **Before activation**: The channel SL percentage acts as the stop loss
- **After activation**: The trailing stop replaces the channel SL
- **Full position exit**: Trailing stop exits the entire remaining position (not partial)

### Interaction with Leave Runner

If Leave Runner is enabled, the trailing stop will sell everything EXCEPT the runner quantity:

```
100 shares, 25% runner
Trailing stop triggers:
  → Sell 75 shares (trailing exit)
  → Keep 25 shares (runner)
```

---

## 9. Giveback Guard

Prevents giving back too much unrealized profit. If the position has reached a high profit level and then drops significantly, the guard triggers an exit.

### Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `enable_giveback_guard` | Enable/disable | Off |
| `giveback_allowed_pct` | Max % of peak profit to give back | 30% |

### How It Works

```
Entry: $10.00
Giveback allowed: 30%

Price history:
  → $12.00 (+20%): max_pnl_seen = 20%
  → $13.00 (+30%): max_pnl_seen = 30%
  → $12.50 (+25%): Gave back 5% of 30% = 16.7% → OK

  → $11.90 (+19%): Gave back 11% of 30% = 36.7% → EXCEEDS 30%!
  → EXIT TRIGGERED at $11.90
```

**Formula**:
```
giveback_from_peak = max_pnl_seen - current_pnl_pct
allowed_giveback = max_pnl_seen × (giveback_allowed_pct / 100)

If giveback_from_peak > allowed_giveback → EXIT
```

### When Is It Useful?

Best for positions that run up significantly, then start reversing. Without giveback guard, you might ride all the way back down. With it, you lock in a portion of the peak profit.

### Interaction with Tiers

Giveback guard evaluates AFTER tiered targets. If T1 already sold some shares, the guard protects the remaining shares from giving back too much profit.

---

## 10. Leave Runner

Reserves a portion of the position that is NEVER sold by profit targets. The runner stays in the position to capture extended moves.

### Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `leave_runner_enabled` | Enable/disable | Off |
| `leave_runner_pct` | % of original position to keep | 25% |

### How It Works

```
100 shares, leave_runner_pct = 25%
Runner qty = max(1, int(100 × 0.25)) = 25 shares
Max sellable = 100 - 25 = 75 shares

T1 sells 25 (of 75 sellable)
T2 sells 25 (of 50 remaining sellable)
T3 sells 25 (of 25 remaining sellable)
T4: 0 sellable (all non-runner shares sold)

25 runner shares remain in position
```

### Runner Protection vs Exits

| Exit Type | Respects Runner? |
|-----------|-----------------|
| Profit Targets (T1-T4) | YES — qty capped to max_sellable |
| Stop Loss | NO — sells everything |
| Dynamic SL trigger | NO — sells everything |
| Trailing Stop | YES — keeps runner shares |
| Giveback Guard | NO — sells everything |
| Early Trailing exit | NO — sells everything |

**Stop loss and emergency exits always sell ALL shares** including runners. Runners are only protected during normal PT profit-taking.

### Small Position Behavior

| Shares | Runner (25%) | Sellable | Behavior |
|--------|-------------|----------|----------|
| 1 | 0 | 1 | No runner possible |
| 2 | 1 | 1 | Sell 1 at PT, keep 1 runner |
| 4 | 1 | 3 | Sell 3 across tiers, keep 1 |
| 10 | 2 | 8 | Sell 8 across tiers, keep 2 |

---

## 11. Exit Strategy Mode

Controls how the risk engine and signal channels interact for exit decisions.

| Mode | Description |
|------|-------------|
| `signal` | Follow the Discord signal channel's exit calls. Risk engine provides backup SL only. |
| `risk` | Risk engine manages all exits autonomously. Ignores manual SL overrides. |
| `hybrid` | Both systems active. Risk engine exits are approved by the arbiter. Manual overrides allowed. |

### How Hybrid Mode Works

```
1. Risk engine detects PT hit → proposes exit
2. Exit Order Arbiter evaluates:
   - Is this a valid exit for the current strategy?
   - Does it conflict with a pending signal?
3. If approved → Execute the sell
4. If rejected → Skip (log reason)
```

### Manual Override Behavior

| Mode | Manual SL Price | Manual SL % |
|------|----------------|-------------|
| `signal` | Respected (highest priority) | Respected |
| `hybrid` | Respected (highest priority) | Respected |
| `risk` | IGNORED | IGNORED |

---

## 12. Feature Interaction Matrix

### Which features can be combined?

| Feature A | Feature B | Compatible? | Notes |
|-----------|-----------|-------------|-------|
| Profit Targets | Stop Loss | YES | Both always recommended |
| Profit Targets | Dynamic SL | YES | Dynamic SL escalates after each PT hit |
| Profit Targets | Early Trailing | YES | Both protect, higher SL wins |
| Profit Targets | Trailing Stop | YES | Trailing activates at higher % than PTs |
| Profit Targets | Leave Runner | YES | Runner reserves shares from PT sells |
| Profit Targets | Giveback Guard | YES | Guard protects remaining shares after PT sells |
| Dynamic SL | Early Trailing | YES | Higher of the two SL prices is used |
| Dynamic SL | Trailing Stop | YES | Higher of the two SL prices is used |
| Early Trailing | Trailing Stop | **NO** | Mutually exclusive — pick one |
| Leave Runner | Any SL/exit | PARTIAL | SL exits sell all; only PTs respect runner |
| Giveback Guard | Dynamic SL | YES | Independent checks, first trigger wins |
| OCO Bracket | Market trim | **NO** | OCO requires limit mode |
| OCO Bracket | Options | **NO** | OCO only for equities |

### Exit Priority (which triggers first?)

When multiple exit conditions are true simultaneously, the FIRST match in this order wins:

```
1. Hard Stop Loss          ← Channel SL or manual override
2. Dynamic SL trigger      ← After PT hits escalated the SL
3. Early Trailing exit     ← Breakeven/step lock broken
4. Giveback Guard          ← Profit drawdown exceeded
5. Tiered Profit Target    ← T1/T2/T3/T4 partial sells
6. Trailing Stop           ← Trail from highest price broken
```

### Bracket Order Decision Tree

```
Is trim_order_mode 'market'?
  ├─ YES → Standalone STOP only at broker
  │        Risk engine sends market sell when PT% hit
  │        No OCO
  │
  └─ NO (limit) → Check conditions for OCO:
       │
       ├─ SL price valid AND PT price valid AND equity?
       │   └─ YES → Native OCO bracket
       │            OCO(SL + PT for trim_qty) + Standalone STOP(remainder)
       │
       └─ NO → Separate STOP + LIMIT orders
```

---

## 13. Common Scenarios Walkthrough

### Scenario A: Simple 2-Tier Trade with Market Exits

**Settings**: T1=8%, T2=15%, SL=10%, trim_mode=market, Dynamic SL=standard

```
BUY 50 shares at $10.00

Broker places:
  → STOP SELL 50 @ $9.00 (10% SL, covers ALL shares)

Price rises to $10.80 (+8%) → T1 HIT
  → Risk engine sends: MARKET SELL 25 shares
  → Filled at $10.79
  → Dynamic SL escalates to $10.00 (breakeven)
  → Broker updates: STOP SELL 25 @ $10.00

Price rises to $11.50 (+15%) → T2 HIT
  → Risk engine sends: MARKET SELL 25 shares
  → Filled at $11.49
  → Position closed. All broker orders cancelled.

Result: 25 × $10.79 + 25 × $11.49 = $556.00 on $500 investment (+11.2%)
```

### Scenario B: OCO Bracket with Limit Exits

**Settings**: T1=10%, T2=20%, SL=8%, trim_mode=limit, offset=$0.05

```
BUY 40 shares at $25.00

Broker places:
  → OCO(SL=$23.00, PT=$27.45) for 20 shares [T1 qty]
  → Standalone STOP SELL 20 @ $23.00 [remaining]

Price rises to $27.50 → OCO PT limit fills at $27.45
  → OCO SL auto-cancels (these 20 shares no longer need SL)
  → T1 marked as hit
  → New OCO(SL=$26.25, PT=$29.95) for 20 shares [T2 qty]
  → (Dynamic SL escalated to $25.00, but T2 OCO SL uses $26.25 from standard profile +5%)

Price drops to $26.25 → OCO SL triggers
  → Sells 20 shares at ~$26.25
  → Position closed.

Result: 20 × $27.45 + 20 × $26.25 = $1,074 on $1,000 investment (+7.4%)
```

### Scenario C: Early Trailing Locks Profit on a Volatile Stock

**Settings**: T1=5%, SL=10%, Early Trailing: activation=5%, step=2%

```
BUY 30 shares at $8.00

Broker places:
  → STOP SELL 30 @ $7.20 (10% SL)

Price rises to $8.40 (+5%): T1 HITS + EARLY TRAILING ACTIVATES
  → Sell 15 shares at T1
  → Early trailing locks breakeven: early_stop = $8.00
  → Broker updates: STOP SELL 15 @ $8.00

Price rises to $8.56 (+7%): STEP 1 LOCKED
  → early_stop = $8.00 × 1.02 = $8.16
  → Broker updates: STOP SELL 15 @ $8.16

Price drops to $8.30, then rises to $8.72 (+9%): STEP 2 LOCKED
  → early_stop = $8.00 × 1.04 = $8.32
  → Broker updates: STOP SELL 15 @ $8.32

Price crashes to $8.32: EARLY TRAILING EXIT
  → Sells remaining 15 shares at $8.32
  → Locked +4% on remaining shares despite crash

Result: 15 × $8.40 + 15 × $8.32 = $250.80 on $240 investment (+4.5%)
```

### Scenario D: Leave Runner with All 4 Tiers

**Settings**: T1=5%, T2=10%, T3=20%, T4=40%, SL=8%, Leave Runner=20%, Dynamic SL=aggressive

```
BUY 100 shares at $10.00
Runner: 20 shares (20%)
Sellable: 80 shares

T1 (+5%): Sell 20 shares at $10.50
  → 80 remain (60 sellable + 20 runner)
  → Dynamic SL → $9.80 (aggressive: entry -2%)

T2 (+10%): Sell 20 shares at $11.00
  → 60 remain (40 sellable + 20 runner)
  → Dynamic SL → $10.00 (aggressive: breakeven)

T3 (+20%): Sell 20 shares at $12.00
  → 40 remain (20 sellable + 20 runner)
  → Dynamic SL → $10.80 (aggressive: entry +8%)

T4 (+40%): Sell 20 shares at $14.00
  → 20 remain (0 sellable + 20 runner)
  → Dynamic SL → $11.50 (aggressive: entry +15%)

Runner shares (20) remain with SL at $11.50.
If price keeps rising, Dynamic SL ratchets up.
If price drops to $11.50 → sells all 20 runners.
```

---

## Glossary

| Term | Definition |
|------|-----------|
| **OCO** | One-Cancels-Other — a broker order type that links two orders. When one fills, the other automatically cancels. |
| **Bracket** | A set of protective orders (SL + PT) placed at the broker. |
| **Trim** | Selling a portion of the position (partial exit). |
| **Runner** | Shares intentionally left in the position to capture extended moves. |
| **Escalation** | Moving the stop loss upward (toward profit) after a profit target is hit. |
| **Ratchet** | A stop that can only move in one direction (up for long positions). Never moves back down. |
| **Cascade** | After a tier fills, the system cancels old brackets and places new ones for the next tier. |
| **Tier Hit** | When price reaches a profit target level and the sell order fills. |
| **Giveback** | The amount of unrealized profit lost when price drops from its peak. |
