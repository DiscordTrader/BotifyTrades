# BotifyTrades — Comprehensive Risk & Order Architecture

## Table of Contents

1. [Entry Order Flow (All Brokers)](#1-entry-order-flow-all-brokers)
2. [Progressive Broker Bracket System](#2-progressive-broker-bracket-system)
3. [Order Chaser Alignment](#3-order-chaser-alignment)
4. [Dynamic Stop Loss Escalation](#4-dynamic-stop-loss-escalation)
5. [SL-Only Escalation Mode](#5-sl-only-escalation-mode)
6. [EMA Candlestick Risk Engine](#6-ema-candlestick-risk-engine)
7. [Multi-PT Cascade](#7-multi-pt-cascade)
8. [Complete Exit Priority Order](#8-complete-exit-priority-order)
9. [Broker Capability Matrix](#9-broker-capability-matrix)

---

## 1. Entry Order Flow (All Brokers)

### Signal → Entry Pipeline

```
Discord/Telegram Signal
  → Signal Parser (extract symbol, strike, expiry, direction)
  → Channel Settings Lookup (risk params, broker assignment)
  → Slippage Check (_evaluate_slippage)
  → Entry Range Validation
  → Broker-Specific Order Placement
  → Background Verification
  → Risk Engine Registration
```

### Broker-Specific Entry Behavior

| Broker | Stocks — Regular Hours | Stocks — Extended Hours | Options |
|--------|----------------------|------------------------|---------|
| **Webull** | Market order via SDK `place_order` | Auto-converts MKT→LMT (+3% offset, +8% penny stocks) | Limit only (simulated market via aggressive Ask + buffer); CBOE tick rounding ($0.05/<$3, $0.10/≥$3) |
| **Schwab** | Market order (no price → MKT) | Session type switches to `SEAMLESS` | Limit only; mid-price from `schwab_data_hub` or REST; CBOE penny increment rounding |
| **Alpaca** | Market or Limit | Market or Limit (supports extended hours natively) | Limit only; DAY TIF for options |
| **IBKR** | Market or Limit | `outsideRth=True` flag on orders | Limit; full OCC contract qualification via `ib_insync` |
| **TastyTrade** | Market or Limit via `tastytrade` SDK | N/A (regular hours only) | Limit via `build_leg` + `NewOrder`; DAY TIF |
| **Trading212** | Market only (LIVE API beta) | Not supported | Not supported (stocks only) |
| **Robinhood** | Market or Limit via `robin_stocks` | Supported with `extendedHours=True` | Limit only; no stop orders for options |

### Post-Entry Verification

All brokers perform multi-stage verification:

1. **Immediate Check** (1.5–2s delay): Catches `REJECTED` / `CANCELLED` / `EXPIRED` status immediately.
2. **Background Verification** (async, up to 3 retries at 2s intervals): Confirms fill, detects parking (`PENDING_ACTIVATION` for after-hours orders), releases exit locks on failure.
3. **Webull-Specific**: Includes transient retry logic (`MAX_TRANSIENT_RETRIES=3`) for "system busy" errors with trade token refresh.

---

## 2. Progressive Broker Bracket System

### Architecture

The system uses a "Progressive Bracket" — one PT limit order at a time on the broker, cascading to the next after each fill. This design is necessary because most brokers don't support multiple simultaneous bracket legs for the same position.

### Initial Bracket Placement (`_place_initial_broker_bracket`)

Triggered after a BTO entry is confirmed. Places two orders simultaneously:

```
Entry Confirmed
  → Calculate SL price: entry × (1 - stop_loss_pct / 100)
  → Calculate PT1 price: entry × (1 + profit_target_1_pct / 100)
  → Calculate PT1 qty via calculate_auto_tier_quantities()
  → Place SL order (full position qty) — Stop order
  → Place PT1 order (tier qty) — Limit order
  → Register PT1 with Order Chaser
  → Set cache.broker_orders_placed = True
```

### Broker-Specific Bracket Implementations

#### Schwab
- **SL**: `place_stop_order()` with `GOOD_TILL_CANCEL` duration, `sell_to_close` (options) or `sell` (stocks)
- **PT**: `place_option_order()` or `place_stock_order()` with limit price

#### Alpaca
- **SL**: `StopOrderRequest` via `trading_client.submit_order()`, GTC for stocks, DAY for options
- **PT**: `LimitOrderRequest` via same client

#### IBKR
- **SL**: `ib_insync.StopOrder('SELL', qty, stop_price)` with `outsideRth` flag
- **PT**: `ib_insync.LimitOrder('SELL', qty, limit_price)` with `outsideRth` flag
- Requires contract qualification: `qualifyContractsAsync(contract)` before placement

#### TastyTrade
- **SL (Stocks)**: Native `STOP` order type via `TTNewOrder` with `stop_trigger`
- **SL (Options)**: Uses `LIMIT` order at the SL price (TastyTrade does not support stop orders for options)
- **PT**: `LIMIT` order; GTC for stocks, DAY for options

#### Trading212
- **LIVE API**: Broker-side brackets skipped entirely — software-only risk monitoring
- **Practice API**: `place_stop_order()` for SL, `place_stock_order()` with limit for PT
- Stocks only — options not supported
- 4-layer protection prevents bracket attempts on LIVE accounts

#### Robinhood
- **SL (Stocks)**: `place_stock_order()` with `stop_price` parameter
- **SL (Options)**: Not supported — SL monitored locally by software
- **PT**: `place_option_order()` or `place_stock_order()` with limit price

#### Webull
- **SL (Stocks)**: `place_order(orderType='STP', stpPrice=price, enforce='GTC')` with retry logic (tries `outsideRegularTradingHour=True` first, falls back to `False`)
- **SL (Options)**: Not supported — SL monitored locally
- **PT (Stocks)**: `place_order(orderType='LMT', enforce='GTC', outsideRegularTradingHour=True)`
- **PT (Options)**: Via `place_option_order()` using resolved `optionId`

### Trim Order Mode

If `trim_order_mode = 'market'`, broker-side PT placement is completely disabled. The risk engine handles exits with market orders when thresholds are hit. When `trim_order_mode = 'limit'`, the trim price is calculated with a configurable offset:

- **Dollar offset mode**: Price rounded to nearest $0.04/$0.09 boundary (e.g., $1.54, $1.59)
- **Percent offset mode**: Price adjusted by `trim_limit_offset_pct` (default 2%)
- **Penny stock handling**: If price < $1.00, precision is 4 decimal places; uses 8% fallback if dollar offset would go negative

---

## 3. Order Chaser Alignment

### Overview

The `UnfilledOrderChaser` service monitors all pending orders (entry and exit) and "chases" unfilled orders with progressively aggressive pricing.

### Two Registries

| Registry | Purpose | Tracked Orders |
|----------|---------|---------------|
| `_tracked_orders` | Exit (STC) orders | Risk engine PT/SL sells |
| `_tracked_entry_orders` | Entry (BTO) orders | Signal-triggered buys |

### Chase Flow — 3-Step Escalation

```
Order Placed → Registered with Chaser
  → Monitor Loop (0.5s poll interval)
  → Stale? (age > 1s timeout)
    → Attempt 1: Cancel → Replace at MID-PRICE (bid+ask)/2
    → Attempt 2: Cancel → Replace at BID (exits) / ASK (entries)
    → Attempt 3: Cancel → MARKET ORDER (price=0, force fill)

Exit timeline:  ~1s stale → ~1.2s mid → ~2.2s bid → ~3.2s market = ~4s worst case
Entry timeline: ~1s stale → ~1.2s mid → ~2.2s ask → cancel (no market for entries)
```

### Risk Engine Integration

- **`_register_pt_with_chaser`**: Called after every successful PT limit order placement. Registers the `order_id` so the chaser can escalate unfilled PT orders to mid-price or market.
- **Fill Confirmation**: `cache.confirm_order_fill()` updates tier state when chaser detects a fill.
- **Lease Management**: Chaser releases `ExitLeaseManager` locks on completion/failure, allowing the risk engine to retry.
- **Startup Recovery**: `_restore_pending_orders()` queries `trades` table for `PENDING` orders to resume chasing after reboot.

### Cancel-Replace Race Protection

The chaser implements strict cancel-replace safety to prevent duplicates:

1. **Strict Cancel Settlement**: `_wait_for_cancel_settlement()` loops up to 3 re-fetches (0.2s apart) confirming the old order is gone. If still active after all checks → **abort replacement entirely** (no duplicate risk).
2. **Fill Verification on Disappearance**: If order disappears from pending during cancel window, `_verify_order_fill()` checks broker status. If `PENDING_ACTIVATION` → skip replacement (market not open). If verified filled → mark filled. Only replace on `CANCELLED`/`UNKNOWN`.
3. **Correct Qty Recompute**: Post-cancel replacement uses `original_total_qty = int(order.quantity)` (never pre-subtracted remaining), preventing double-subtraction on cumulative-fill brokers.
4. **Atomic PT ID Swap**: `_atomic_pt_id_clear_and_cancel()` acquires per-position lock (`_broker_stop_locks`) before clearing PT order ID and cancelling. `_atomic_pt_id_swap()` acquires same lock before syncing new ID. Lock auto-created if absent. This prevents position_monitor from reading stale or None PT IDs during the swap window.

### Chaser + Progressive Bracket Alignment

When PT1 is placed on the broker and registered with the chaser:
1. If PT1 fills normally → `_place_next_pt_bracket` places PT2
2. If PT1 goes stale → Chaser adjusts price to mid → Fills → PT2 placed
3. If PT1 never fills after max attempts → Chaser sends market order → PT2 placed after fill
4. After any PT fill → `_sync_stop_to_broker` resizes the SL order to remaining qty

---

## 4. Dynamic Stop Loss Escalation

### Profiles

Three built-in profiles define how the SL moves after each PT hit:

| Profile | After PT1 | After PT2 | After PT3 | After PT4 |
|---------|-----------|-----------|-----------|-----------|
| **Conservative** | Breakeven (0%) | +3% | +8% | +15% |
| **Standard** | Breakeven (0%) | +5% | +10% | +17% |
| **Aggressive** | -2% (small loss) | Breakeven (0%) | +8% | +15% |

### Calculation (`calculate_dynamic_sl`)

```python
sl_price = entry_price × (1 + sl_pct / 100)
```

Where `sl_pct` comes from the profile table based on `highest_tier_hit`.

### Safety Cap

If the calculated SL would be ≥ current price (which would trigger an immediate sell), it is capped at 2% below the current price:
```python
capped_sl = current_price × 0.98
```
If even the capped price is below entry, SL reverts to entry price (breakeven).

### Ratchet Mechanism (Post-Final-PT)

When all configured PTs have been hit and the price continues rising, the SL ratchets upward:

```python
giveback_pct = highest_tier_pct - highest_sl_pct  # (min 5%)
ratchet_sl_pct = current_pnl - giveback_pct
ratchet_sl_price = entry × (1 + ratchet_sl_pct / 100)
```

This creates a trailing behavior that protects profits beyond the final PT while allowing the configured giveback buffer.

### Broker Sync

When `dynamic_sl_price` is updated and the position has active broker stop orders:
1. `SYNC_STOP` operation is enqueued (priority 10)
2. `_sync_stop_to_broker()` cancels old stop, places new stop at escalated price
3. New SL is never synced lower than the existing broker stop (ratchet-only direction)

---

## 5. SL-Only Escalation Mode

### Purpose

`escalation_only_mode` suppresses all partial sells from tiered profit targets. Instead, PT thresholds serve purely as SL escalation milestones. The full position size is maintained through all PTs.

### How It Works

```
Price crosses PT1 threshold
  → cache.tier1_hit = True (NO partial sell)
  → calculate_dynamic_sl() with pts_hit = {1: True}
  → SL moves to profile-defined level
  → If broker_orders_placed: enqueue SYNC_STOP

Price crosses PT2 threshold
  → cache.tier2_hit = True (NO partial sell)
  → calculate_dynamic_sl() with pts_hit = {1: True, 2: True}
  → SL moves higher (ratchet only)
  → Broker stop synced again

...continues until all PTs hit...

All PTs hit + price still rising
  → Ratchet mechanism takes over
  → SL trails at (current_pnl - giveback_pct)
```

### Key Difference from Normal Mode

| Behavior | Normal Mode | Escalation Only |
|----------|-------------|-----------------|
| PT1 hit | Sell 25% (or configured qty) | No sell; mark tier, escalate SL |
| PT2 hit | Sell 25% | No sell; escalate SL further |
| Position size | Shrinks with each PT | Stays at 100% until SL or full exit |
| SL movement | Same escalation profiles | Same escalation profiles |
| Use case | Scale-out profit locking | "Let it ride" with trailing SL protection |

---

## 6. EMA Candlestick Risk Engine

### Overview

The EMA (Exponential Moving Average) risk system provides trend-following exit intelligence using real-time candlestick data. It sits at **priority 2.5** in the exit hierarchy — after hard/dynamic SL but before giveback guard and trailing stops.

### Candle Service (`CandlePreWarmService`)

- Builds OHLC candles from real-time tick data via broker data hubs
- Pre-warms with historical candles on subscription for immediate EMA readiness
- Supports underlying tracking (`ema_use_underlying`) for options — tracks the stock (e.g., SPY) instead of the option contract
- Extended hours support via `ema_extended_hours` flag

### EMA Configuration

| Setting | Description | Default |
|---------|-------------|---------|
| `ema_risk_enabled` | Master toggle | per-channel |
| `ema_exit_enabled` | Allow full/partial exits on EMA cross | per-channel |
| `ema_escalation_enabled` | Allow SL escalation to EMA value | per-channel |
| `ema_timeframe_minutes` | Candle timeframe (e.g., 5 min) | per-channel |
| `ema_period` | EMA period (e.g., 9) | per-channel |
| `ema_buffer_pct` | Buffer below EMA for escalation price | per-channel |
| `ema_no_trend_candles` | Candles on wrong side before no-trend exit | per-channel |
| `ema_use_underlying` | Track underlying stock for option positions | per-channel |

### EMA Decisions

| Decision | Trigger | Action |
|----------|---------|--------|
| **EXIT** | Candle crosses through EMA (long: open > EMA, close < EMA) | `SELL_ALL` or partial sell (leave runner) |
| **ESCALATE** | Price on favorable side of EMA; escalation enabled | `MOVE_STOP` to EMA value ± buffer (stocks only, not options) |
| **NO_TREND_EXIT** | Price on unfavorable side for `ema_no_trend_candles` consecutive candles | `SELL_ALL` |
| **NO_TREND_TICK** | Price on unfavorable side, counting candles toward threshold | Increment counter |
| **HOLD** | No actionable signal | No action |

### Warmup Guard

A 2-candle warmup period (`EMA_WARMUP_CANDLES = 2`) prevents false exits immediately after entry. EXIT decisions during the first 2 post-entry candles are suppressed.

### EMA + Dynamic SL Interaction

- EMA escalation respects the channel's hard SL floor: if the EMA-derived stop is between entry and the hard SL floor, it's ignored to prevent widening the SL beyond the channel's configured maximum loss
- EMA stops only move upward (ratchet behavior)
- The `ema_no_trend_count` persists across evaluation cycles and resets when the price returns to the favorable side

---

## 7. Multi-PT Cascade

### Quantity Distribution (`calculate_auto_tier_quantities`)

Given `total_qty`, `leave_runner_pct`, and `enabled_tiers`:

```
runner_qty = floor(total_qty × leave_runner_pct / 100)
sellable_qty = total_qty - runner_qty
base_qty = sellable_qty // num_tiers
remainder = sellable_qty % num_tiers
```

Remainder is distributed one-by-one to earlier tiers.

**Example**: 10 contracts, 20% runner, 3 tiers:
- Runner: 2 contracts
- Sellable: 8 contracts
- PT1: 3, PT2: 3, PT3: 2

### Cascade Flow

```
Entry → _place_initial_broker_bracket()
  → SL order (full qty) + PT1 limit (tier qty)
  → PT1 registered with chaser

PT1 fills at broker
  → _place_next_pt_bracket(completed_tier=1)
    → Lock per position (idempotent)
    → Skip if cache.broker_pt_tier >= 2
    → _place_next_pt_bracket_inner()
      → Calculate PT2 price, qty
      → Cancel old PT order
      → Place new PT2 limit order
      → Register PT2 with chaser
      → cache.broker_pt_tier = 2
    → _sync_stop_to_broker() — resize SL to remaining qty

PT2 fills → same flow for PT3
PT3 fills → same flow for PT4 (if configured)
Final PT fills → SL remains for runner protection
```

### Tier Evaluation (`evaluate_tiered_targets`)

The tiered targets function checks each tier sequentially with guards:

1. **Not already hit**: `cache.tier{N}_hit == False`
2. **No pending order**: `cache.has_pending_order_for_tier(N) == False`
3. **Threshold configured**: `profit_target_{N}_pct > 0`
4. **Price exceeded**: `pct_change >= threshold`

For the final tier (whichever is last configured), leave-runner logic applies — the exit qty is reduced by the runner amount.

### Progressive Bracket Suppression

When `cache.broker_orders_placed == True`, the position monitor suppresses software-side partial sells for tiers that have active broker orders. Instead of executing the sell directly, it enqueues `PLACE_PT{n+1}` to maintain the progressive chain.

---

## 8. Complete Exit Priority Order

The risk engine evaluates exit conditions in strict priority order. Higher-priority exits short-circuit lower ones:

```
Priority 1: HARD STOP LOSS
  └─ pnl_pct <= -stop_loss_pct → SELL_ALL (immediate)

Priority 2: DYNAMIC STOP LOSS (requires ≥1 PT hit)
  ├─ Calculate new SL from profile + pts_hit
  ├─ If new SL > current → MOVE_STOP
  └─ If price <= dynamic_sl_price → SELL_ALL (immediate)

Priority 2.5: EMA RISK ENGINE (if enabled, after 2-candle warmup)
  ├─ EXIT: Candle crosses EMA → SELL_ALL or partial (leave runner)
  ├─ ESCALATE: Price favorable → MOVE_STOP to EMA-buffer
  ├─ NO_TREND_EXIT: Wrong side for N candles → SELL_ALL
  └─ NO_TREND_TICK: Counting toward threshold

Priority 3: GIVEBACK GUARD (if enabled, after PT2 hit or max_pnl ≥ activation)
  ├─ Activation: max_pnl_seen ≥ trailing_activation_pct or PT2 hit
  ├─ giveback_threshold = max_pnl × (1 - giveback_allowed_pct / 100)
  └─ If pnl_pct ≤ giveback_threshold → SELL_ALL

Priority 4: EARLY TRAILING STOP (mutually exclusive with legacy trailing)
  ├─ Activation: pnl_pct ≥ early_trailing_activation_pct → lock breakeven
  ├─ Step-up: Every +step_pct% → lock higher stop price
  └─ If price ≤ early_stop_price → SELL_ALL

Priority 5: TIERED PROFIT TARGETS (PT1–PT4)
  ├─ For each tier: check threshold, calculate qty, SELL_PARTIAL
  ├─ Escalation-only mode: mark tier hit, skip sell, escalate SL
  └─ Auto-qty distribution with leave-runner reservation

Priority 6: LEGACY TRAILING STOP (skipped if early trailing enabled)
  ├─ Activation: pnl_pct ≥ trailing_activation_pct
  ├─ trail_stop = highest_price × (1 - trailing_stop_pct / 100)
  └─ If price ≤ trail_stop → SELL_ALL
```

### Idempotency

The risk engine uses a price-change guard:
```python
if last_evaluated_price == current_price and not has_new_ema_candle and not has_interval_extremes:
    return (no actions)
```
This prevents duplicate evaluations at the same price point, except when new EMA candle data or interval price extremes arrive.

### Interval Extremes

The system tracks `interval_high` and `interval_low` — the highest and lowest prices seen between evaluation cycles. This prevents gaps where a price spike or dip between ticks could be missed:
- `interval_high` updates `highest_price` (for trailing/giveback)
- `interval_low` used as `effective_low` for SL/trailing checks (catches flash drops)

---

## 9. Broker Capability Matrix

| Capability | Webull | Schwab | Alpaca | IBKR | TastyTrade | Trading212 | Robinhood |
|-----------|--------|--------|--------|------|------------|------------|-----------|
| **Stock Market Orders** | Yes | Yes | Yes | Yes | Yes | Yes (LIVE) | Yes |
| **Stock Limit Orders** | Yes | Yes | Yes | Yes | Yes | Practice only | Yes |
| **Stock Stop Orders** | Yes (STP+stpPrice) | Yes | Yes | Yes | Yes (STOP type) | Practice only | Yes |
| **Option Limit Orders** | Yes (via optionId) | Yes (OCC symbol) | Yes | Yes (ib_insync) | Yes (build_leg) | N/A | Yes |
| **Option Stop Orders** | No (local SL) | Yes | Yes | Yes | No (uses limit) | N/A | No (local SL) |
| **Extended Hours** | Yes (auto MKT→LMT) | Yes (SEAMLESS) | Yes (native) | Yes (outsideRth) | No | No | Yes |
| **Broker-Side SL** | Stocks only | Stocks + Options | Stocks + Options | Stocks + Options | Stocks only (limit for options) | Practice stocks only | Stocks only |
| **Broker-Side PT** | Yes | Yes | Yes | Yes | Yes | Practice stocks only | Yes |
| **Progressive Bracket** | Yes | Yes | Yes | Yes | Yes | Practice only | Yes |
| **CBOE Tick Rounding** | Yes ($0.05/$0.10) | Yes (penny increment) | No (native) | No (native) | No (native) | N/A | No |
| **Order Chaser** | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| **T212 LIVE Protection** | N/A | N/A | N/A | N/A | N/A | 4-layer block | N/A |

### Trading212 LIVE 4-Layer Protection

1. `_place_initial_broker_bracket` → detects `is_live` → skips bracket, relies on software monitoring
2. `place_stop_order()` → returns failure for LIVE accounts
3. `place_stock_order()` → only allows market orders on LIVE
4. `_instruments_ready` gate → prevents any bracket attempts before instrument cache loads

### TastyTrade Option Stop Workaround

TastyTrade API does not support native `STOP` orders for options. The system places a `LIMIT` order at the stop-loss price instead. This means:
- The SL limit order sits on the book waiting to be hit
- Unlike a true stop, it can fill if price touches the SL level (desired behavior)
- Log message explicitly notes: `[limit used - options don't support stop orders on TastyTrade]`
