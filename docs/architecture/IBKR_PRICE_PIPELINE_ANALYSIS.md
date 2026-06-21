# IBKR Execution, Conditional Orders & Risk Engine — Deep Analysis

**Scope**: IBKR execution path gaps vs TWS API, conditional order price monitoring wiring, and risk engine real-time price pipeline
**Date**: 2026-06-19
**Method**: Code-level audit of `ibkr_broker.py`, `ibkr_data_hub.py`, `unified_price_hub.py`, `conditional_orders/`, `position_monitor.py`, `risk_engine.py`, `ema_engine.py`

---

## Table of Contents

1. [Complete Price Data Flow Diagram](#1-complete-price-data-flow-diagram)
2. [IBKR Execution Gaps vs TWS API](#2-ibkr-execution-gaps-vs-tws-api)
3. [IBKR Data Hub Streaming Analysis](#3-ibkr-data-hub-streaming-analysis)
4. [Unified Price Hub (UPH) Wiring](#4-unified-price-hub-uph-wiring)
5. [Conditional Order Price Monitoring](#5-conditional-order-price-monitoring)
6. [Risk Engine Price Wiring](#6-risk-engine-price-wiring)
7. [EMA Risk Engine Analysis](#7-ema-risk-engine-analysis)
8. [Gap Summary & Impact Matrix](#8-gap-summary--impact-matrix)

---

## 1. Complete Price Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                    TWS / IB GATEWAY (TCP)                        │
│         reqMktData (200-300ms batched, continuous)                │
│         reqTickByTickData (sub-ms, ≤20 symbols)                  │
└──────────────┬───────────────────────┬───────────────────────────┘
               │                       │
               ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    IBKRDataHub (Singleton)                       │
│   pendingTickersEvent → _process_pending_tickers()               │
│   TickByTick → _on_tick_by_tick()                                │
│                                                                  │
│   Cache: Dict[symbol → IBKRQuoteData]                            │
│   Fields: bid, ask, last, volume, OHLC  ❌ NO GREEKS             │
│   Staleness: QUOTE_STALE_THRESHOLD = 300s                        │
│                                                                  │
│   Emits: 'quote_updated' {symbol, source='ibkr_stream', quote}   │
└──────┬────────────────────────────┬─────────────────────────────┘
       │                            │
       │   Event subscription       │   Event subscription
       ▼                            ▼
┌──────────────────┐    ┌────────────────────────────────────────┐
│ UnifiedPriceHub  │    │        CandlePreWarmService             │
│ (UPH Singleton)  │    │        (EMA Engine)                     │
│                  │    │                                          │
│ Also receives    │    │ hub.on('quote_updated') → process_tick() │
│ from: Webull,    │    │ Builds OHLC candles from ticks           │
│ Schwab, Tasty    │    │ ❌ Subscribes to HUBS, not UPH           │
│                  │    │ _poll_loop (5s) REST fallback             │
│ Cache: Dict[     │    └──────────────┬─────────────────────────┘
│  canon_sym →     │                   │
│  UnifiedQuote]   │                   ▼
│                  │    ┌────────────────────────────────────────┐
│ Freshness:       │    │ EMAEngine → EMAExitEvaluator            │
│ fresh ≤3s        │    │ Provides EMA state to risk engine       │
│ aging  ≤5s       │    └────────────────────────────────────────┘
│ stale  ≤10s      │
│ degraded ≤30s    │
│ unverified >30s  │
│                  │
│ Emits own        │
│ 'quote_updated'  │
└──────┬───────────┘
       │
       │  Event: 'quote_updated'        get_quote() / get_quote_price()
       │  (tick-driven fast path)        (periodic cycle)
       ▼                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RiskManager (position_monitor.py)              │
│                                                                  │
│  DUAL-PATH ARCHITECTURE:                                         │
│                                                                  │
│  Path A: Periodic cycle (~1s)                                    │
│  ├── _fetch_all_positions() → REST/hub-cached per broker         │
│  ├── _update_prices_from_hub() → streaming overlay (30s max age) │
│  ├── _detect_and_fix_stuck_prices() → REST repair fallback       │
│  └── _evaluate_position() for each position                      │
│                                                                  │
│  Path B: Tick-driven (<50ms)                                     │
│  ├── _on_quote_update() → marks symbol dirty + interval hi/lo    │
│  ├── _price_wake_event → _run_incremental_eval()                 │
│  └── Evaluates ONLY dirty-symbol positions                       │
│                                                                  │
│  Per-position: builds TradeState → evaluate_exit_actions()        │
│  Price used: position.current_price (from streaming overlay)      │
│  PnL: (current_price - entry_price) / entry_price × 100          │
└──────────────────────────────────┬──────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│           risk_engine.evaluate_exit_actions()                    │
│           (Pure function, no side effects)                       │
│                                                                  │
│  Input: TradeState + ChannelRiskSettings                         │
│  Output: List[RiskAction] + updated TradeState                   │
│                                                                  │
│  Priority chain:                                                 │
│  1. Hard SL:    pnl_pct ≤ −SL%                                   │
│  2. Dynamic SL: floor rises after PT hits (3 profiles)           │
│  2.5 EMA Exit:  candle cross-through EMA line                    │
│  3. Giveback:   pnl_pct drops below max_pnl × (1 − giveback%)   │
│  4. Early Trail: breakeven lock + step profit lock               │
│  4.5 PT Near:   tight trail within threshold% of next PT         │
│  5. Tiered PT:  PT1-PT4 partial exits                            │
│  6. Trailing:   trail below peak after activation                │
└─────────────────────────────────────────────────────────────────┘
```

**Parallel path for Conditional Orders:**

```
┌─────────────────────────────────────────────────────────────────┐
│              StreamingPriceMonitor (conditional_orders/base.py)   │
│                                                                  │
│  7-tier priority chain (US market):                              │
│  P0: UPH (cross-broker consistency)                              │
│  P1: Order's broker streaming hub                                │
│  P2: Alt broker streaming hub (cross-broker WebSocket)           │
│  P3: Order's broker REST API                                     │
│  P4: Order's broker hub (pending stream)                         │
│  P5: Alt broker hub                                              │
│  P6: Any connected broker REST                                   │
│                                                                  │
│  Poll: 250ms hub cache reads                                     │
│  Event: IBKR 'quote_updated' → instant wakeup                   │
│  Frozen: 3s unchanged → cross-hub probe → REST fallback          │
│  Trigger: 150ms confirmation window (2+ ticks)                   │
│  Staleness: 30s block on execution                               │
│                                                                  │
│  ⚠️ BUG: Calls UPH.get_quote_price(sym, allow_stale=True)       │
│     but UPH doesn't accept allow_stale → TypeError every 250ms   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. IBKR Execution Gaps vs TWS API

### What's Implemented

| Feature | Status | Details |
|---------|--------|---------|
| Connection to TWS/Gateway | ✅ | Auto-detection TWS ↔ Gateway, alt-port fallback |
| Auto-reconnect | ✅ | Exponential backoff (5s–120s), 3 attempts, fresh `IB()` per attempt |
| MarketOrder | ✅ | Stock + options |
| LimitOrder | ✅ | Stock + options, SEC Rule 612 price rounding |
| `qualifyContracts()` | ✅ | Used for both stocks and options |
| `outsideRth` | ✅ | Reads from DB config per broker |
| Fill waiting | ✅ | Event-driven via `trade.statusEvent`, 10s timeout |
| Auto-adjust quantity | ✅ | On insufficient funds (stocks only) |
| Cancel order | ✅ | Via `ib.cancelOrder()` |
| Modify order | ✅ | Via `ib.placeOrder()` with existing trade |
| Get positions | ✅ | Via `ib.positions()` and `ib.portfolio()` |
| Option chain discovery | ⚠️ | Via `reqSecDefOptParams` but returns zeros for bid/ask/greeks |
| Streaming quotes | ✅ | Via IBKRDataHub (`reqMktData` + `reqTickByTickData`) |

### What's Missing (vs TWS API)

#### CRITICAL — Order Types Not Supported

| Missing Order Type | TWS API Support | Impact |
|-------------------|-----------------|--------|
| **StopOrder** | `ib_insync.StopOrder()` | ❌ Cannot place native stop-loss — ALL SL is synthetic via price monitor polling |
| **StopLimitOrder** | `ib_insync.StopLimitOrder()` | ❌ No stop-limit for controlled exit pricing |
| **TrailingStopOrder** | `order.orderType = 'TRAIL'` | ❌ No native trailing — synthetic polling only |
| **BracketOrder** | `ib.bracketOrder()` | ❌ No native OCO — 3 orders linked by `ocaGroup`. Synthetic only |

**Impact**: Every exit for IBKR positions relies on the software polling prices at 250ms–1s intervals and placing a separate market/limit order when triggered. If the bot crashes or loses connectivity, positions have **zero broker-side protection**. A native IBKR bracket order would survive bot crashes because the orders live on IB's servers.

#### HIGH — Missing Features

| Missing Feature | TWS API Method | Impact |
|----------------|---------------|--------|
| **Time-in-Force** | `order.tif = 'GTC'/'IOC'/'FOK'/'OPG'` | All orders use default DAY TIF. No GTC for multi-day entries, no IOC for speed-critical exits |
| **Multi-account** | `order.account = 'U...'` | No account parameter on orders — breaks FA accounts |
| **`execDetailsEvent`** | `ib.execDetailsEvent += handler` | Fill details (execution price, time, exchange) not captured. Only `orderStatus` tracked |
| **`commissionReportEvent`** | `ib.commissionReportEvent += handler` | Commission costs never captured — P&L calculations miss trading costs |
| **`reqContractDetails()`** | For disambiguation | Ambiguous option contracts may silently resolve wrong |
| **TWS error code handling** | Error codes 200, 201, 202, 110, 103, 104 | Not handled — only string-pattern matching on rejection messages |

#### MEDIUM — Missing Capabilities

| Missing | TWS API | Impact |
|---------|---------|--------|
| Combo orders / Spreads | `Contract(comboLegs=[...])` | No multi-leg option strategies |
| Adaptive algo | `order.algoStrategy = 'Adaptive'` | No smart routing optimization |
| WhatIf margin check | `order.whatIf = True` | Cannot pre-check margin before execution |
| `reqCompletedOrders()` | Historical fill access | No access to order history from TWS |
| Greeks from streaming | tick type 233 `modelGreeks` | Available in IB data but not extracted (see §3) |

#### LOW — Nice-to-Have

| Missing | Notes |
|---------|-------|
| TWAP/VWAP algos | Not relevant for signal-following bot |
| Scanner | Has its own signal sources |
| News feeds | Not needed |
| Historical data | Uses yfinance as fallback |

### Import Evidence

```python
# ibkr_broker.py line 1:
from ib_insync import IB, Stock, Option, MarketOrder, LimitOrder, util
# MISSING: StopOrder, StopLimitOrder, TrailingStopOrder, Contract,
#          ComboLeg, TagValue, Order, BracketOrder
```

### ib_insync Deprecation Risk

**ib_insync is deprecated** — the original maintainer (Ewald de Wit) passed away in early 2024. The library is no longer updated. The successor is **ib_async** (maintained by Matt Stancliff), which implements the full IBKR API binary protocol. IBKR's minimum supported TWS version is now 10.30 (March 2025). Continued use of ib_insync risks compatibility breakage with newer TWS versions.

---

## 3. IBKR Data Hub Streaming Analysis

### What Works Well

| Feature | Implementation | Assessment |
|---------|---------------|------------|
| Continuous streaming | `reqMktData(snapshot=False)` | ✅ Correct — continuous, not snapshot |
| Sub-ms tick delivery | `reqTickByTickData('AllLast')` ≤20 symbols | ✅ Excellent for active positions |
| Thread-safe cache | Fine-grained locks per resource | ✅ Proper isolation |
| Event-driven updates | `pendingTickersEvent` → emit `quote_updated` | ✅ <200ms latency |
| Error code handling | 1100/1101/1102/504/10167/10089/10168 | ✅ Comprehensive |
| Zombie detection | No quotes for 30s × 2 checks → reconnect | ✅ Good failsafe |
| Reconnection | Fresh `IB()` + alt-port + re-subscribe | ✅ Robust |

### Critical Gap: Greeks Not Propagated

```
TWS sends tick 233 (modelGreeks) with:
  → optPrice, impliedVol, delta, gamma, vega, theta, pvDividend

IBKRDataHub._process_pending_tickers() extracts:
  → ticker.modelGreeks.optPrice ONLY (for illiquid option fallback)
  → delta, gamma, theta, vega, impliedVol are DISCARDED

IBKRQuoteData has NO greeks fields (__slots__ = symbol, bid, ask, last, ...)

UnifiedQuote HAS greeks fields (delta, gamma, theta, vega) → stay at 0.0
```

**Impact**: Any consumer expecting greeks from UPH for IBKR-sourced quotes gets zeros. This affects options analysis, delta-weighted position sizing, and gamma exposure calculations. The data is available from TWS but is discarded at the hub layer.

### Missing Error Codes

| TWS Code | Meaning | Current Handling |
|----------|---------|-----------------|
| 2104 | Market data farm connected | ❌ Silently ignored |
| 2106 | HMDS data farm connected | ❌ Silently ignored |
| 2107 | HMDS data farm disconnected | ❌ Silently ignored |
| 2108 | Market data farm disconnected | ❌ Silently ignored |
| 200 | No security definition found | ❌ Not handled in hub |
| 201 | Order rejected | ❌ Not handled in hub |
| 10038 | Failed to cancel order | ❌ Not handled |

### Option Subscription Gap

`subscribe_symbol()` requires either:
- A plain equity symbol (auto-creates `Stock(symbol, 'SMART', 'USD')`)
- An option symbol with `_` separator AND a pre-registered contract

If an option contract is NOT in the portfolio (e.g., watching a new option before entering), `subscribe_symbol('SPX_20240120_5000_C')` **silently returns** without subscribing because no contract is registered. No error, no fallback, no alert.

---

## 4. Unified Price Hub (UPH) Wiring

### Hub Registration

| Hub | Protocol | Registered | Real Streaming |
|-----|----------|-----------|----------------|
| Webull | MQTT | ✅ | ✅ |
| Schwab | WebSocket | ✅ | ✅ |
| IBKR | ib_insync events | ✅ | ✅ |
| Tastytrade | DXLink | ✅ | ✅ |
| Trading212 | REST | ✅ | ❌ Stub only |

### UPH Bug: `get_quote_price()` TypeError

**Location**: `unified_price_hub.py` vs `conditional_orders/base.py`

```python
# StreamingPriceMonitor._query_hub() calls:
self.data_hub.get_quote_price(self.symbol, allow_stale=True)

# But UPH.get_quote_price() signature is:
def get_quote_price(self, symbol: str) -> Optional[float]:
    # No allow_stale parameter!
```

Every 250ms poll cycle from conditional orders hits a `TypeError`, caught by a fallback `except TypeError` that retries without the kwarg. This is ~240 unnecessary exceptions per minute per monitored symbol.

### UPH Bypass Inventory

These code paths read prices **directly from hubs or broker REST**, bypassing UPH entirely:

| Bypasser | File | Calls | Impact |
|----------|------|-------|--------|
| EMA engine | `ema_engine.py:1051` | `webull_data_hub.get_quote()` | EMA sees different prices than risk engine |
| Main bot | `selfbot_webull.py` (11 locations) | `webull_data_hub.get_quote()`, `wb.get_quote()` | Inconsistent price views |
| Trade tracker | `trade_tracker.py:224,258` | `webull_data_hub.get_quote()` | P&L calculations may differ |
| Legacy conditional orders | `conditional_order_service.py` (7 locations) | `broker.get_quote()` directly | No UPH consistency |
| NDX/QQQ converter | `ndx_qqq_converter.py` | `webull_data_hub.get_quote()` | Index conversion prices |
| Quote aggregator | `quote_aggregator.py` | Raw broker `get_quote()` | Aggregator bypasses aggregator |
| Signal verification | `signal_verification.py` | Raw Webull/Alpaca REST | Verification prices differ |

### Missing Fields in UnifiedQuote

| Field | In UnifiedQuote | Available from IBKR | Available from Schwab |
|-------|----------------|--------------------|-----------------------|
| `delta` | ✅ (always 0 from IBKR) | ✅ tick 233 | ✅ |
| `gamma` | ✅ (always 0 from IBKR) | ✅ tick 233 | ✅ |
| `theta` | ✅ (always 0 from IBKR) | ✅ tick 233 | ✅ |
| `vega` | ✅ (always 0 from IBKR) | ✅ tick 233 | ✅ |
| `open_interest` | ❌ | ✅ tick 101 | ✅ |
| `implied_vol` | ❌ | ✅ tick 233 | ✅ |

---

## 5. Conditional Order Price Monitoring

### Architecture: 7-Tier Price Fallback (US Market)

```
Priority  Source                     Latency        API Cost
───────────────────────────────────────────────────────────
P0        UPH (unified hub)          <3s (fresh)    Zero
P1        Order's broker stream      <200ms         Zero
P2        Alt broker stream          <200ms         Zero
P3        Order's broker REST        1-3s           1 call
P4        Order's broker hub         pending stream  Zero
P5        Alt broker hub             pending stream  Zero
P6        Any broker REST            1-3s           1 call
```

### StreamingPriceMonitor Timing Parameters

| Parameter | Value | Location |
|-----------|-------|----------|
| Hub poll interval | 250ms | `base.py` `HUB_POLL_INTERVAL` |
| IBKR event wakeup | Instant | `quote_updated` → `asyncio.Event.set()` |
| Frozen detection | 3.0s unchanged | `FROZEN_THRESHOLD` |
| Frozen probe cooldown | 3.0s | `FROZEN_PROBE_COOLDOWN` |
| REST fallback | After 4 hub misses | `REST_FALLBACK_INTERVAL=1s` |
| Trigger confirmation | 150ms window | 2+ ticks required |
| Execution stale guard | 30s | Blocks if price >30s old |

### Gaps in Conditional Order Pricing

| # | Gap | Severity | Detail |
|---|-----|----------|--------|
| CO-1 | Frozen detection is market-hours only | MEDIUM | `_is_us_market_hours()` returns False outside 4am–8pm ET. Extended hours frozen feeds not detected |
| CO-2 | Event-driven wakeup only for IBKR | MEDIUM | Schwab/Webull/Tastytrade rely on 250ms polling — no instant wakeup |
| CO-3 | `allow_stale` TypeError on every poll | LOW | 240 exceptions/min/symbol. Caught but wasteful |
| CO-4 | Legacy service bypasses UPH entirely | HIGH | `conditional_order_service.py` uses `broker.get_quote()` with no UPH, no frozen detection, no confirmation window |
| CO-5 | Slippage protection is warning-only | MEDIUM | Checks slippage at execution but never blocks — deferred to broker |
| CO-6 | IBKR option subscribe silently fails | HIGH | Options without pre-registered contracts get no streaming data |
| CO-7 | Execution callback 30s timeout | MEDIUM | If main event loop is blocked, conditional order execution times out |
| CO-8 | Cross-hub cache TTL 30s | LOW | Hub connect/disconnect not picked up for up to 30s |

---

## 6. Risk Engine Price Wiring

### How Prices Reach `evaluate_exit_actions()`

```
1. Periodic cycle builds position list:
   _fetch_ibkr_cached() → current_price = 0  ← PROBLEM
   _fetch_ibkr_positions() → current_price = pos.marketPrice

2. Streaming overlay:
   _update_prices_from_hub() reads IBKRDataHub.get_quote()
   ├── Freshness gate: max_age = 30 seconds
   ├── Price: quote.last → mid(bid,ask) → bid → ask
   ├── Index guard: reject price if >50× avg_cost
   └── REST repair guard: won't overwrite recent REST fix

3. Stuck price detection:
   _detect_and_fix_stuck_prices() (2s threshold regular hours)
   ├── Cross-hub price check (from non-native hubs, 2s max-age)
   └── REST quote fallback with ±30% sanity check

4. TradeState construction:
   entry_price  ← from trade DB (via PositionCache)
   current_price ← from streaming overlay
   highest_price ← max(current, interval_high, previous_highest)
   interval_high ← from tick accumulator (dirty-symbol path only)
   interval_low  ← from tick accumulator (dirty-symbol path only)

5. evaluate_exit_actions(state, config):
   pnl_pct = (current_price - entry_price) / entry_price × 100
   effective_low = min(current_price, interval_low)
```

### Risk Engine Staleness Guards

| Guard | Threshold | What It Does |
|-------|-----------|--------------|
| Price unchanged | 2s (regular) / 15s (extended) | Triggers stuck-price repair |
| Hub price max age | 30s | Rejects stale hub quotes |
| Exit staleness block | 5s (regular) / 300s (extended) | Blocks SL exits on stale price |
| REST sanity check | ±30% (regular) / ±80% (extended) | Rejects large jumps |
| Zero price guard | price == 0 | Silently skips evaluation |
| Absurd PnL guard | >500% or <-95% | Warns but doesn't block |
| REST repair protection | 30s | Prevents hub from overwriting fresh REST fix |

### Risk Engine Gaps

| # | Gap | Severity | Detail |
|---|-----|----------|--------|
| RE-1 | IBKR positions start at price $0 | CRITICAL | `_fetch_ibkr_cached()` sets `current_price=0`. If streaming overlay fails (hub not streaming, stale >30s, symbol mismatch), position hits zero-price guard and is silently skipped indefinitely. No escalation. |
| RE-2 | IBKR option symbol mismatch | HIGH | Position uses `raw_symbol = f"{sym}_{exp}_{strike}_{right}"`. Hub stores quotes under ib_insync's key format. Mismatch → `_get_fresh_hub_price()` returns None → price stays 0. |
| RE-3 | Stale price triggers PT exits | MEDIUM | Staleness gate intentionally ALLOWS PT exits on stale prices ("selling at stale HIGH is favorable"). But stale-high price (previous close in extended hours) causes false PT exit. |
| RE-4 | Multi-broker same-symbol, different prices | MEDIUM | SPY on Schwab and IBKR each use their own hub's price. No cross-broker consensus for routine evaluation. Cross-hub only used for stuck-price repair. |
| RE-5 | Interval extremes only in tick path | MEDIUM | Periodic monitoring cycle gets hub-overlay prices but NO interval extremes. Dedup gate may suppress eval when intra-interval dip occurred and recovered. |
| RE-6 | Tick-driven eval uses stale position snapshot | LOW | `_run_incremental_eval()` uses `_last_positions_snapshot` from previous cycle. New/removed positions between cycles may be missed. |

---

## 7. EMA Risk Engine Analysis

### Architecture

```
Price Source → CandleAggregator → EMAEngine → EMAExitEvaluator
                                                    ↓
                                              RiskManager uses
                                              EMA state in
                                              evaluate_exit_actions()
```

### CandlePreWarmService

- **Subscribes to**: Broker hubs directly via `hub.on('quote_updated')` — **NOT UPH**
- **Tick processing**: Extracts `last` price, feeds to `CandleAggregator.process_tick()`
- **Poll fallback**: `_poll_loop()` every 5s for symbols with no tick in 15s
- **Pre-warm**: Fetches historical candles from Webull `get_bars()`, Schwab `get_price_history()`, or yfinance
- **Supported timeframes**: Configurable (default 5-min candles from `ema_timeframe` setting)

### EMA Evaluation Logic

```python
# EMAExitEvaluator (simplified):
if candle.open >= ema_value and candle.close < ema_value:
    # Price crossed through EMA (bearish for longs)
    return EMADecision.EXIT  # or ESCALATE depending on buffer

if unfavorable_candles >= no_trend_candles_threshold:
    return EMADecision.NO_TREND_EXIT  # Extended period below EMA
```

- **2-candle warmup**: After position entry, EMA ignores the first 2 candles (avoids false exit on entry volatility)
- **Buffer**: `ema_buffer_pct` allows EMA line crossing tolerance
- **Options behavior**: EMA escalation SKIPPED for options — only EXIT fires
- **Escalation**: For stocks, can ESCALATE stop-loss tighter instead of full exit

### EMA Engine Gaps

| # | Gap | Severity | Detail |
|---|-----|----------|--------|
| EMA-1 | Subscribes to hubs, not UPH | HIGH | CandlePreWarmService gets ticks from individual hubs. RiskManager prefers UPH. Different price feeds → timing discrepancies. If UPH aggregates a cross-hub price that resolves a freeze, EMA engine doesn't see it. |
| EMA-2 | Candle gap vulnerability | MEDIUM | `CandleAggregator.process_tick()` only finalizes a candle when the NEXT tick arrives in a new time boundary. If ticks stop (hub disconnect, low volume), the current candle remains open indefinitely. The _poll_loop (5s) provides REST ticks only after 15s of silence — a 15s gap could span multiple candle periods. |
| EMA-3 | IBKR option underlying mismatch | MEDIUM | EMA uses `position.symbol` (underlying like SPY). IBKR hub publishes quotes keyed by contract symbol. If `ema_use_underlying=True` but hub ticks arrive under the contract key, the EMA engine never receives ticks for the underlying. |
| EMA-4 | Direct Webull hub dependency | LOW | `_try_broker_candles()` hardcodes `webull_hub._broker._wb.get_bars()` — tightly coupled to Webull internals. Breaks if Webull broker is not connected. |
| EMA-5 | Pre-warm source priority is Webull-first | LOW | Historical candle warmup tries Webull → Schwab → yfinance. If Webull is not connected, adds latency from fallback chain. |

---

## 8. Gap Summary & Impact Matrix

### IBKR Execution Gaps

| ID | Gap | Severity | Financial Risk | Fix Complexity |
|----|-----|----------|---------------|----------------|
| IBKR-1 | No StopOrder support | 🔴 CRITICAL | Positions have no broker-side protection if bot crashes | Low — add `from ib_insync import StopOrder` + 20 lines |
| IBKR-2 | No BracketOrder support | 🔴 CRITICAL | Entry+SL+PT cannot be placed atomically | Medium — implement `ib.bracketOrder()` + OCA group tracking |
| IBKR-3 | No TrailingStopOrder | 🟠 HIGH | Native trailing on IB servers would survive bot crash | Low — add `TrailingStopOrder` + configure `trailingPercent` |
| IBKR-4 | No TIF control (GTC/IOC) | 🟠 HIGH | All orders default to DAY — multi-day positions lose protection overnight | Low — add `order.tif` parameter |
| IBKR-5 | No `execDetailsEvent` | 🟠 HIGH | Fill price, time, exchange not captured for audit | Low — subscribe to event, log to DB |
| IBKR-6 | No `commissionReportEvent` | 🟠 HIGH | Commission costs invisible — P&L inaccurate | Low — subscribe to event, record per trade |
| IBKR-7 | No multi-account | 🟠 HIGH | FA accounts can't target specific sub-accounts | Medium — add `order.account` parameter |
| IBKR-8 | Greeks not propagated from hub | 🟠 HIGH | UPH greeks stay 0 for IBKR options | Low — add fields to IBKRQuoteData, extract from `ticker.modelGreeks` |
| IBKR-9 | ib_insync deprecated | 🟡 MEDIUM | Library no longer maintained, TWS compatibility risk | High — migrate to ib_async |
| IBKR-10 | Option chain returns zeros | 🟡 MEDIUM | Can't display live option chain from IBKR | Medium — add `reqMktData` for chain strikes |

### Price Pipeline Gaps

| ID | Gap | Severity | Financial Risk | Fix Complexity |
|----|-----|----------|---------------|----------------|
| PP-1 | IBKR positions start at $0 | 🔴 CRITICAL | Risk engine silently skips position — no SL protection | Low — initialize from `pos.marketPrice` or `pos.marketValue/pos.position` |
| PP-2 | EMA subscribes to hubs, not UPH | 🟠 HIGH | EMA and risk engine see different prices | Low — change subscription target to UPH |
| PP-3 | `get_quote_price()` TypeError | 🟡 MEDIUM | 240 exceptions/min/symbol wasteful overhead | Low — add `allow_stale=True` param to UPH method |
| PP-4 | Legacy conditional service bypasses UPH | 🟠 HIGH | No frozen detection, no confirmation window, no cross-hub | Medium — retire legacy service, migrate to new router |
| PP-5 | 11+ direct hub calls bypass UPH | 🟡 MEDIUM | Inconsistent price views across subsystems | Medium — route through UPH |
| PP-6 | No open_interest/implied_vol in UPH | 🟡 MEDIUM | Options analysis incomplete | Low — add fields to UnifiedQuote |
| PP-7 | Stale price allows PT exits | 🟡 MEDIUM | False PT trigger on stale-high price | Low — add freshness check for PT exits |
| PP-8 | IBKR option symbol format mismatch | 🟠 HIGH | Hub lookup fails → price stays 0 → no risk eval | Medium — normalize option symbol keys |

### Risk Engine Gaps

| ID | Gap | Severity | Financial Risk | Fix Complexity |
|----|-----|----------|---------------|----------------|
| RK-1 | No native IBKR SL orders | 🔴 CRITICAL | Bot crash = unprotected positions | See IBKR-1, IBKR-2 |
| RK-2 | Interval extremes missing in periodic cycle | 🟡 MEDIUM | Intra-interval dip not captured in periodic eval | Low — carry interval extremes into periodic cycle |
| RK-3 | EMA candle gap on hub disconnect | 🟡 MEDIUM | Missed candle close → delayed EMA exit signal | Medium — detect gap, insert synthetic close |
| RK-4 | Multi-broker same-symbol price divergence | 🟡 MEDIUM | Different exit decisions for same underlying | Low — use cross-broker NBBO as risk price |
| RK-5 | Zero-price silent skip with no escalation | 🟠 HIGH | Position with persistent $0 price never evaluated | Low — add alert after N consecutive zero-price cycles |

### Conditional Order Gaps

| ID | Gap | Severity | Financial Risk | Fix Complexity |
|----|-----|----------|---------------|----------------|
| CO-1 | Extended hours frozen feed not detected | 🟡 MEDIUM | Conditional order monitors stale price after hours | Low — extend market hours window |
| CO-2 | Only IBKR gets event-driven wakeup | 🟡 MEDIUM | Other brokers have 250ms poll latency | Medium — add event wiring for all hubs |
| CO-3 | IBKR option subscribe silently fails | 🟠 HIGH | No streaming for unwatched options | Medium — resolve contract before subscribe |

---

## Appendix: Numeric Parameters

| Parameter | Value | File:Line |
|-----------|-------|-----------|
| reqMktData batching | 200–300ms | TWS internal |
| reqTickByTickData latency | 100–300µs | TWS internal |
| reqTickByTickData limit | 20 symbols | IBKRDataHub |
| Hub poll interval (conditional) | 250ms | base.py `HUB_POLL_INTERVAL` |
| Hub poll interval (UPH) | 2s | unified_price_hub.py `_poll_loop` |
| Frozen detection threshold | 3.0s | base.py `FROZEN_THRESHOLD` |
| Frozen probe cooldown | 3.0s | base.py `FROZEN_PROBE_COOLDOWN` |
| REST fallback interval | 1.0s | base.py `REST_FALLBACK_INTERVAL` |
| REST fallback trigger | 4 hub misses | base.py |
| Trigger confirmation window | 150ms | base.py |
| Execution stale guard | 30s | base.py `_execute_order` |
| UPH freshness: fresh | ≤3s | unified_price_hub.py |
| UPH freshness: aging | ≤5s | unified_price_hub.py |
| UPH freshness: stale | ≤10s | unified_price_hub.py |
| UPH freshness: degraded | ≤30s | unified_price_hub.py |
| IBKR quote stale threshold | 300s | ibkr_data_hub.py `QUOTE_STALE_THRESHOLD` |
| Hub price max age (risk) | 30s | position_monitor.py `_HUB_PRICE_MAX_AGE` |
| Stuck price threshold | 2s (regular) / 15s (extended) | position_monitor.py |
| Staleness exit block | 5s (regular) / 300s (extended) | position_monitor.py |
| REST sanity check | ±30% (regular) / ±80% (extended) | position_monitor.py |
| REST repair protection | 30s | position_monitor.py |
| Cross-hub cache TTL | 30s | base.py / unified_price_hub.py |
| EMA candle default | 5-min | ema_engine.py |
| EMA warmup candles | 2 | ema_engine.py |
| EMA poll fallback | 5s | ema_engine.py `_poll_loop` |
| EMA tick silence threshold | 15s | ema_engine.py |
| Reconnect cooldown | 15s | ibkr_data_hub.py `_RECONNECT_COOLDOWN` |
| Zombie detection | 30s × 2 checks | ibkr_data_hub.py |
| Tick pump interval | 10ms | ibkr_data_hub.py `_tick_pump_loop` |
