# IB Gateway — Complete Gap Analysis

**Scope**: Every gap in the IB Gateway pipeline from real-time price → conditional order monitoring → execution → risk engine price monitoring → risk evaluation → exit execution
**Date**: 2026-06-19 (initial analysis) | **Updated**: 2026-06-20 (10 gaps fixed)

---

## Pipeline Overview

```
IB Gateway (TCP :4001/:4002)
    │
    ├─── reqMktData (200-300ms batch)  ──┐
    ├─── reqTickByTickData (sub-ms, ≤20) ┤
    │                                    ▼
    │                          IBKRDataHub (singleton cache)
    │                            │           │
    │                     event: quote_updated
    │                            │           │
    │              ┌─────────────┤           ├──────────────┐
    │              ▼             ▼           ▼              ▼
    │         UPH cache    CandlePreWarm  RiskManager   StreamingPrice
    │         (aggregator) (EMA engine)  (direct sub)   Monitor (cond)
    │              │             │           │              │
    │              └──────┬──────┘           │              │
    │                     ▼                  ▼              ▼
    │              evaluate_exit_actions()  trigger eval   
    │                     │                  │
    │                     ▼                  ▼
    │              _execute_exit()     execute_conditional()
    │                     │                  │
    └─────────────────────┴──────────────────┘
                          │
                    place_stock_order() / place_option_order()
                    (MarketOrder / LimitOrder ONLY in ibkr_broker.py)
                    (StopOrder imported inline in position_monitor.py brackets)
```

---

## PHASE 1: Real-Time Price → IBKRDataHub

### GAP 1 — Greeks Discarded at Hub Layer
**Severity**: 🟠 HIGH
**Location**: `ibkr_data_hub.py:_process_pending_tickers()`
**Issue**: IB Gateway sends `ticker.modelGreeks` with delta, gamma, theta, vega, impliedVol via tick type 233. The hub only extracts `modelGreeks.optPrice` as a fallback for illiquid options. All greeks are discarded.
**`IBKRQuoteData`** has no greeks fields → `UnifiedQuote` greeks stay 0.0 for all IBKR-sourced options.
**Impact**: Any consumer (risk engine, GUI, conditional orders) expecting greeks from UPH for IBKR options gets zeros. Delta-weighted sizing, gamma exposure analysis, and options analytics are blind for IBKR.

### GAP 2 — reqTickByTickData Limited to 20 Symbols
**Severity**: 🟡 MEDIUM
**Location**: `ibkr_data_hub.py:_start_market_data()`
**Issue**: `reqTickByTickData` provides sub-millisecond tick delivery but is capped at 20 simultaneous subscriptions (IB Gateway limit). Symbol #21+ falls back to `reqMktData` with 200-300ms batching.
**Impact**: With >20 positions, the 21st+ symbol has 200-300ms latency before IBKRDataHub even sees the price. Combined with the 250ms conditional order poll interval, total latency reaches ~550ms.

### GAP 3 — Option Subscription Silently Fails Without Pre-Registered Contract
**Severity**: 🟠 HIGH
**Location**: `ibkr_data_hub.py:subscribe_symbol()`
**Issue**: If symbol contains `_` (option format like `SPX_20240120_5000_C`) and no contract is already registered in `_symbol_to_contract`, the method returns silently without subscribing. Contracts only get registered when they appear in `ib.portfolio()` (existing positions).
**Impact**: Conditional orders for IBKR options that aren't yet in the portfolio receive NO streaming data. The monitor falls back to REST polling (1s intervals), adding latency to trigger detection.

### GAP 4 — TWS Error Codes 2104/2106/2107/2108 Not Handled
**Severity**: ~~🟡 LOW~~ → ✅ **FIXED** (2026-06-20)
**Location**: `ibkr_data_hub.py:_on_error_event()`
**Issue**: Market data farm status messages (connected/disconnected) were silently ignored.
**Fix**: Added `elif errorCode in (2104, 2106):` and `elif errorCode in (2107, 2108):` branches. Code 2104 sets `_streaming_active = True` (farm OK). Code 2108 sets `_streaming_active = False` and emits `data_farm_disconnected` event (farm inactive). Codes 2106/2107 logged as info/warning for HMDS farm status.

### GAP 5 — No Per-Symbol Dead Subscription Detection
**Severity**: ~~🟡 MEDIUM~~ → ✅ **FIXED** (2026-06-20)
**Location**: `ibkr_data_hub.py`
**Issue**: If `reqMktData` silently failed for a specific symbol, there was no mechanism to detect the dead subscription.
**Fix**: Added `_per_symbol_last_tick: Dict[str, float]` tracking dict and `_PER_SYMBOL_DEAD_THRESHOLD = 60.0` constant. Every tick updates the per-symbol timestamp in `_process_pending_tickers()` and `update_quote()`. The reconciliation loop detects symbols with no ticks for >60s, cancels their `reqMktData`, and re-queues them as pending subscriptions for automatic re-subscribe.

### GAP 6 — connectedEvent Not Subscribed
**Severity**: ~~🟡 LOW~~ → ✅ **FIXED** (2026-06-20)
**Location**: `ibkr_data_hub.py:attach_broker()`
**Issue**: Only `disconnectedEvent` was wired. After reconnect, up to 10s delay before streaming resumed.
**Fix**: Wired `ib.connectedEvent += self._on_connected` in `_attach_events()` and corresponding `-=` in `detach_broker()`. New `_on_connected()` handler immediately restores `_streaming_active`, resets stale counter, re-subscribes all pending symbols, and emits `connected` event. Eliminates the 10s reconciliation loop delay.

---

## PHASE 2: IBKRDataHub → UPH (Unified Price Hub)

### GAP 7 — `get_quote_price()` TypeError on Every Conditional Order Poll
**Severity**: ~~🟡 MEDIUM~~ → ✅ **FIXED** (2026-06-20)
**Location**: `unified_price_hub.py:get_quote_price()` vs `conditional_orders/base.py:StreamingPriceMonitor._query_hub()`
**Issue**: StreamingPriceMonitor called `get_quote_price(symbol, allow_stale=True)` but UPH's signature was `get_quote_price(self, symbol: str)` — no `allow_stale` parameter. Every 250ms poll hit a `TypeError`.
**Fix**: Added `allow_stale: bool = False` parameter to `UnifiedPriceHub.get_quote_price()` matching IBKRDataHub's signature. Eliminates ~240 unnecessary exceptions/min/symbol. The `_query_hub()` TypeError fallback in `base.py` is preserved for backward compatibility with older hub instances.

### GAP 8 — UPH Hub Cache TTL = 30 Seconds
**Severity**: 🟡 LOW
**Location**: `unified_price_hub.py:_HUB_CACHE_TTL = 30`
**Issue**: Hub instances (IBKRDataHub, SchwabDataHub, etc.) are cached for 30 seconds in UPH's `_get_hubs()`. If a hub connects or disconnects, UPH won't discover the change for up to 30 seconds.
**Impact**: Newly connected IBKR won't start flowing prices through UPH for up to 30s. Not critical since direct event subscriptions are also active.

### GAP 9 — No open_interest / implied_volatility in UnifiedQuote
**Severity**: 🟡 MEDIUM
**Location**: `unified_price_hub.py:UnifiedQuote`
**Issue**: `UnifiedQuote` has `delta, gamma, theta, vega` fields but no `open_interest` or `implied_volatility`. IB Gateway provides both via tick types 101 (OI) and 233 (IV).
**Impact**: Options analysis through UPH is incomplete. Consumers needing OI/IV must go directly to broker hubs, bypassing the aggregation layer.

---

## PHASE 3: UPH → Conditional Order Price Monitoring

### GAP 10 — Event-Driven Wakeup Only for IBKR Hub
**Severity**: 🟡 MEDIUM
**Location**: `conditional_orders/base.py:StreamingPriceMonitor`
**Issue**: The `asyncio.Event` instant-wakeup mechanism is only wired for IBKRDataHub's `quote_updated` event. Schwab, Webull, and Tastytrade hubs don't trigger event-driven wakeup — they rely on the 250ms poll interval.
**Impact**: For IBKR: near-instant price delivery to conditional orders. For all other brokers: up to 250ms latency floor on every price update.

### GAP 11 — Frozen Feed Detection is Market-Hours Only
**Severity**: ~~🟡 MEDIUM~~ → ✅ **FIXED** (2026-06-20)
**Location**: `conditional_orders/base.py:_is_us_market_hours()`
**Issue**: Frozen feed detection (3s unchanged threshold) only ran during market hours (4am–8pm ET). Extended hours feeds could freeze undetected.
**Fix**: Removed the `and self._is_us_market_hours()` gate from the frozen detection condition. Now uses a relaxed 5× threshold (15s instead of 3s) during off-hours via `_effective_frozen_threshold = self.FROZEN_THRESHOLD if _in_market else self.FROZEN_THRESHOLD * 5`. Frozen feed detection is now active 24/7 with appropriate sensitivity.

### GAP 12 — Legacy conditional_order_service.py Bypasses UPH Entirely
**Severity**: 🟠 HIGH
**Location**: `conditional_order_service.py` (1539 lines)
**Issue**: The legacy service calls `broker_instance.get_quote()` directly in ~7 locations. No UPH integration, no frozen feed detection, no event-driven wakeup, no 150ms confirmation window, no cross-hub arbitrage.
**Impact**: If legacy service is still used for any order, it gets inferior price monitoring. Whether it's still active depends on how orders are routed — both systems coexist.

### GAP 13 — Trigger Confirmation Window Not Configurable
**Severity**: 🟡 LOW
**Location**: `conditional_orders/base.py:_on_price_update()`
**Issue**: The 150ms confirmation window (requiring 2+ ticks to confirm a trigger) is hardcoded. For fast-moving 0DTE options, 150ms may cause missed triggers. For stocks, it's appropriate.
**Impact**: Minor — the 150ms window filters single-tick spikes, which is generally correct behavior.

### GAP 14 — Execution Callback 30s Timeout
**Severity**: ~~🟡 MEDIUM~~ → ✅ **FIXED** (2026-06-20)
**Location**: `conditional_orders/base.py:_execute_order()`
**Issue**: Execution ran with a 30s timeout. One retry after 5s, then permanent ERROR state.
**Fix**: Added a second retry with 45s timeout after the first retry fails. Sequence: initial 30s timeout → 5s wait → retry 1 (30s timeout) → 3s wait → retry 2 (45s timeout). Only goes to ERROR after all retries exhausted. Gives the main event loop 3 chances to process during high-activity bursts.

---

## PHASE 4: UPH → Risk Engine Price Monitoring

### GAP 15 — IBKR Positions Start at Price $0 (CRITICAL)
**Severity**: 🔴 CRITICAL
**Location**: `position_monitor.py:3601`
```python
current_price=0,  # hardcoded
```
**Issue**: `_fetch_ibkr_cached()` reads positions from IBKRDataHub's cache and sets `current_price=0` for every position. The actual price is supposed to be overlaid by `_update_prices_from_hub()` using streaming data. If the streaming overlay fails for any reason:
- Hub not streaming
- Quote stale >30s (`_HUB_PRICE_MAX_AGE`)
- Option `raw_symbol` format mismatch between position and hub cache key
- Hub returns None

...the position keeps `current_price=0`, hits the ZERO PRICE GUARD (L4393), and is **silently skipped** for all risk evaluation. No alarm, no escalation, no fallback to REST. The only evidence is a single print to stdout (logged once per position key).

**Impact**: An IBKR position can sit completely unprotected — no SL, no PT, no trailing — for the entire session if streaming prices fail to attach. This is the #1 financial risk in the IBKR pipeline.

### GAP 16 — IBKR Option Symbol Format Mismatch
**Severity**: 🟠 HIGH
**Location**: `position_monitor.py:3936` vs `ibkr_data_hub.py` cache keys
**Issue**: Positions use `raw_symbol = f"{symbol}_{expiry}_{strike}_{right}"` (e.g., `SPX_20240120_5000_C`). IBKRDataHub stores quotes under whatever key ib_insync's ticker uses (which may be the conId-resolved contract string). If these keys don't match, `_get_fresh_hub_price(raw_symbol)` returns None → price stays $0.
**Impact**: IBKR option positions fail to get streaming price overlay. Combined with GAP 15, the option position is unprotected.

### GAP 17 — EMA Engine Subscribes to Hubs, Not UPH
**Severity**: 🟠 HIGH
**Location**: `ema_engine.py:CandlePreWarmService` subscribes via `hub.on('quote_updated')`
**Issue**: The EMA engine gets ticks from individual broker hubs directly. The risk engine prefers UPH (which aggregates all hubs). Different price sources → potential timing discrepancies.
- UPH may aggregate a cross-hub price that resolves a freeze, but EMA engine doesn't see it.
- EMA engine may see a hub-only tick that UPH hasn't processed yet.
**Impact**: Risk engine and EMA engine can make decisions based on different prices for the same symbol at the same instant.

### GAP 18 — Stale Price Allows Profit Target Exits
**Severity**: 🟡 MEDIUM
**Location**: `position_monitor.py:_evaluate_exit_conditions()` staleness gate
**Issue**: The staleness gate intentionally ALLOWS profit target exits on stale prices. The comment says "selling at stale HIGH is favorable." But if the price is stale-high (e.g., previous close leaked in during extended hours), this triggers a false PT exit.
**Impact**: False PT exits during extended hours or after data gaps. The freshness guard catches SL scenarios but explicitly passes PT scenarios through.

### GAP 19 — Interval Extremes Only in Tick-Driven Path
**Severity**: 🟡 MEDIUM
**Location**: `position_monitor.py:_monitoring_cycle()` vs `_run_incremental_eval()`
**Issue**: `interval_high` and `interval_low` (intra-tick extremes) are only populated in the tick-driven incremental eval path (Path B). The periodic monitoring cycle (Path A) gets hub-overlay prices but NO interval extremes.
**Impact**: The dedup gate in `evaluate_exit_actions()` may suppress evaluation when the price hasn't changed but a significant intra-interval dip (SL touch) occurred and recovered. The dip is invisible in the periodic cycle.

### GAP 20 — No Cross-Broker Price Consensus for Same Symbol
**Severity**: 🟡 MEDIUM
**Location**: `position_monitor.py:_update_prices_from_hub()`
**Issue**: Each position uses its own broker's hub price. SPY on IBKR uses IBKRDataHub price. SPY on Schwab uses SchwabDataHub price. No cross-broker NBBO consensus for routine evaluation. Cross-hub check is only used for stuck-price REPAIR.
**Impact**: The same underlying can trigger SL on one broker but not another due to bid/ask spread differences between data feeds.

---

## PHASE 5: Risk Engine Evaluation with Risk Settings

### GAP 21 — evaluate_exit_actions() Dedup Can Miss Dips
**Severity**: 🟡 MEDIUM
**Location**: `risk_engine.py:evaluate_exit_actions()` dedup gate (~L360)
**Issue**: Skips evaluation if `last_evaluated_price == current_price AND no new EMA candle AND no interval extremes`. But as noted in GAP 19, interval extremes aren't always populated. If price dips below SL and recovers before the next periodic cycle, the dedup gate sees the same price and skips.
**Impact**: A brief SL-piercing spike can go undetected in the periodic evaluation cycle.

### GAP 22 — EMA Candle Gap on Hub Disconnect
**Severity**: 🟡 MEDIUM
**Location**: `ema_engine.py:CandleAggregator.process_tick()`
**Issue**: Candles only finalize when the NEXT tick arrives in a new time boundary. If ticks stop (IBKR disconnect, low volume), the current candle remains open indefinitely. The `_poll_loop` (5s) provides REST ticks only after 15s of silence.
**Impact**: If a 5-min candle should have closed during a 15s data gap, the EMA engine misses the candle close. The EMA calculation operates on incomplete data, potentially delaying an exit signal.

### GAP 23 — EMA IBKR Option Underlying Mismatch
**Severity**: 🟡 MEDIUM
**Location**: `ema_engine.py:CandlePreWarmService._on_quote_updated()`
**Issue**: EMA subscription uses `position.symbol` (underlying like SPY). For options with `ema_use_underlying=True`, this is correct. But IBKRDataHub emits `quote_updated` events keyed by the contract symbol (which for options includes strike/expiry). If the key doesn't match `position.symbol`, the EMA engine never receives ticks.
**Impact**: EMA risk evaluation may not fire for IBKR options if the tick key doesn't match the underlying symbol.

### GAP 24 — Dynamic SL Not Re-Evaluated After Bracket PT Fill
**Severity**: 🟡 LOW
**Location**: `position_monitor.py:_detect_and_handle_bracket_fill()` L5558-5571
**Issue**: After a broker bracket PT fill is detected, the code escalates the dynamic SL correctly. But it uses `self.cache.update_enhanced_risk_state()` which writes to the cache — there's no immediate re-evaluation of the position. The next evaluation cycle picks it up, but there's a 0.2-1s gap where the old SL is in effect.
**Impact**: Minor — the gap is short and the position still has broker-side stop protection if brackets are in place.

---

## PHASE 6: Exit Execution

### GAP 25 — ibkr_broker.py Only Imports MarketOrder + LimitOrder
**Severity**: 🟡 INFO (Design Choice)
**Location**: `ibkr_broker.py:19`
```python
from ib_insync import IB, Stock, Option, MarketOrder, LimitOrder, util
```
**Design**: The broker module handles entry orders only (Market/Limit). Bracket management (native StopOrder, LimitOrder for PT, OCA groups) is the risk engine's responsibility in `position_monitor.py:5959-6030`, gated by the per-channel `broker_bracket_mode` setting (`'both'` / `'sl_only'` / `'pt_only'` / `'none'`). Default is `'none'` (intentional — user opts in via Channel Management → Risk Management → Broker Bracket Orders).
**When enabled**: Full native IB Gateway bracket: `StopOrder` (GTC, outsideRth) + `LimitOrder` for PT (GTC) + OCA group linking + CBOE option increment rounding + dynamic SL sync. This is a complete, working implementation.
**Not a bug**: This is intentional separation of concerns — entry via broker module, protection via risk engine.

### GAP 26 — Risk Engine Imports StopOrder Inline for Brackets
**Severity**: 🟡 INFO (confirms GAP 25 is by design)
**Location**: `position_monitor.py:5965, 7103`
```python
from ib_insync import StopOrder, LimitOrder as IBLimitOrder, Stock as IBStock, Option as IBOption
```
**Design**: The risk engine's `_place_initial_broker_bracket()` places native IB Gateway orders when `broker_bracket_mode != 'none'`. Features: GTC TIF, outsideRth, OCA group for SL+PT linking, CBOE increment snapping, dynamic SL adjustment via `_sync_broker_stop_to_dynamic_sl()`, PT fill detection and next-tier placement.

### GAP 27 — 1-5s Unprotected Window After Entry Fill
**Severity**: 🟡 LOW (Accepted Trade-Off)
**Location**: `ibkr_broker.py:place_stock_order()`, `place_option_order()`
**Design**: Entry fill → risk engine detects position (0.2-1s) → bracket placement. This 1-5 second gap exists because the system uses post-fill bracket placement rather than `ib.bracketOrder()` for atomicity. This trade-off enables per-channel bracket mode flexibility, dynamic SL profiles (conservative/standard/aggressive), tier-based PT progression, and the ability to adjust brackets after placement. An atomic `ib.bracketOrder()` would not support these features.
**Risk**: In extremely fast markets (0DTE options), the 1-5s gap is theoretically material. In practice, the risk engine's 0.2s monitoring loop provides synthetic protection during this window even before the bracket is placed.

### GAP 28 — No TrailingStopOrder Support
**Severity**: 🟠 HIGH
**Location**: `ibkr_broker.py` (not imported), `position_monitor.py` (not used in brackets)
**Issue**: IB Gateway supports native trailing stop orders (`TrailingStopOrder` with `trailingPercent` or `auxPrice`). Neither the broker module nor the risk engine bracket code uses them. All trailing is synthetic via the 0.2s monitoring loop.
**Impact**: If bot crashes, all trailing stop protection is lost. A native IB Gateway trailing stop would survive bot crashes.

### GAP 29 — No TIF Control in ibkr_broker.py
**Severity**: ~~🟠 HIGH~~ → ✅ **FIXED** (2026-06-20)
**Location**: `ibkr_broker.py:place_stock_order()`, `place_option_order()`
**Issue**: Neither method set `order.tif`. Defaults to ib_insync's default (DAY). Entry limit orders were always DAY.
**Fix**: Added `tif: Optional[str] = None` parameter to both `place_stock_order()` and `place_option_order()`. When provided, sets `order.tif = tif` after order creation. Supports all IB TIF values: `'DAY'`, `'GTC'`, `'IOC'`, `'FOK'`, `'OPG'`, `'GTD'`. Default behavior unchanged (DAY) when not specified.

### GAP 30 — No execDetailsEvent / commissionReportEvent
**Severity**: ~~🟠 HIGH~~ → ✅ **FIXED** (2026-06-20)
**Location**: `ibkr_data_hub.py:attach_broker()`
**Issue**: The hub did not subscribe to `ib.execDetailsEvent` or `ib.commissionReportEvent`. Fill price, time, exchange, and commission cost were not captured.
**Fix**: Wired both events in `_attach_events()` and `detach_broker()`. Added `_on_exec_details(trade, fill)` handler capturing exec_id, order_id, symbol, side, shares, price, exchange, time, avg_price, cum_qty — emits `exec_details` event. Added `_on_commission_report(trade, fill, report)` handler capturing commission, currency, realized P&L — emits `commission_report` event. Both keep rolling 500-entry buffers. Accessor methods: `get_recent_executions(limit)` and `get_commission(exec_id)`.

### GAP 31 — No Auto-Adjust for Options on Insufficient Funds
**Severity**: 🟡 MEDIUM
**Location**: `ibkr_broker.py:place_option_order()` vs `place_stock_order()`
**Issue**: `place_stock_order()` has auto-adjust logic on "insufficient" errors (L602-613): queries buying power, computes max quantity, retries. `place_option_order()` has no such logic — an insufficient funds error is terminal.
**Impact**: If an option signal exceeds buying power, the order fails permanently. Stock orders auto-adjust.

### GAP 32 — Option Chain Returns Zeros for Bid/Ask/Greeks
**Severity**: 🟡 MEDIUM
**Location**: `ibkr_broker.py:get_option_chain()` (~L1066-1150)
**Issue**: Option chain discovery uses `reqSecDefOptParams` to get strikes/expirations, then qualifies each contract. But it does NOT call `reqMktData` for the chain strikes — all bid/ask/last/greeks are hardcoded to 0.
**Impact**: IBKR option chain in the GUI shows $0 for every field. Users can't see live option prices from IBKR.

### GAP 33 — get_positions() Flattens by Symbol
**Severity**: ~~🟡 MEDIUM~~ → ✅ **FIXED** (2026-06-20)
**Location**: `ibkr_broker.py:get_positions()` (L305-328)
**Issue**: Returned `{symbol: quantity}` dict. Holding AAPL stock AND AAPL options caused the last one to overwrite.
**Fix**: `get_positions()` now uses composite keys: stocks use plain symbol (`AAPL`), options use `symbol_expiry_strike_right` format (`AAPL_20240120_150.0_C`). Checks `contract.secType == 'OPT'` to determine key format. Both stock and option positions for the same underlying now coexist.

### GAP 34 — Bracket Placement Max 3 Attempts Then Gives Up
**Severity**: 🟡 MEDIUM
**Location**: `position_monitor.py:4589-4592`
**Issue**: If bracket placement fails 3 times (network error, IB rejection, etc.), the system permanently gives up for that position. The risk engine falls back to synthetic monitoring, but there's no retry after the initial 3 failures.
**Impact**: Transient IB Gateway issues (restart, brief disconnect) during the bracket placement window permanently prevent native stop protection for that position.

### GAP 35 — Bracket After-Hours Deferred for Options Only
**Severity**: 🟡 LOW
**Location**: `position_monitor.py:4575-4586`
**Issue**: Bracket placement is deferred for options during after-hours (IB Gateway may reject stop orders for options outside RTH). Stocks don't have this guard.
**Impact**: Correct behavior for options, but the deferral means option positions entered in extended hours have no bracket protection until market opens. The synthetic monitoring loop still evaluates them.

---

## PHASE 7: ib_insync Deprecation

### GAP 36 — ib_insync Is Deprecated
**Severity**: 🟠 HIGH (long-term)
**Location**: `ibkr_broker.py:19`, `ibkr_data_hub.py`, `position_monitor.py` (inline imports)
**Issue**: The original maintainer (Ewald de Wit) passed away in early 2024. ib_insync is no longer updated. The successor is **ib_async** (maintained by Matt Stancliff, github.com/ib-api-reloaded/ib_async), which implements the full IBKR API binary protocol. IBKR's minimum supported TWS/Gateway version is 10.30 (March 2025).
**Impact**: Continued use of ib_insync risks compatibility breakage with newer IB Gateway versions. New TWS API features (protocol buffers, order resubmission on reconnect, etc.) are unavailable.

---

## Summary Matrix

| Phase | ID | Gap | Severity | Financial Risk |
|-------|-----|-----|----------|---------------|
| 1. Hub | GAP-1 | Greeks discarded | 🟠 HIGH | Options analytics blind |
| 1. Hub | GAP-2 | TickByTick 20 symbol limit | 🟡 MED | 550ms latency for 21st+ symbol |
| 1. Hub | GAP-3 | Option subscribe silent fail | 🟠 HIGH | No streaming for new options |
| 1. Hub | GAP-4 | Farm status codes ignored | ✅ **FIXED** | Farm health now visible |
| 1. Hub | GAP-5 | No per-symbol dead sub detection | ✅ **FIXED** | Dead subs auto-resubscribe after 60s |
| 1. Hub | GAP-6 | connectedEvent not wired | ✅ **FIXED** | Instant reconnect (was 10s) |
| 2. UPH | GAP-7 | TypeError on every poll | ✅ **FIXED** | 240 exceptions/min eliminated |
| 2. UPH | GAP-8 | Hub cache TTL 30s | 🟡 LOW | New hub discovery delay |
| 2. UPH | GAP-9 | No OI/IV in UnifiedQuote | 🟡 MED | Incomplete options data |
| 3. Cond | GAP-10 | Event wakeup IBKR only | 🟡 MED | 250ms floor for other brokers |
| 3. Cond | GAP-11 | Frozen detect market-hours only | ✅ **FIXED** | Extended hours frozen detection active (15s) |
| 3. Cond | GAP-12 | Legacy service bypasses UPH | 🟠 HIGH | No advanced monitoring for legacy orders |
| 3. Cond | GAP-13 | 150ms window not configurable | 🟡 LOW | Minor for 0DTE |
| 3. Cond | GAP-14 | Execution callback 30s timeout | ✅ **FIXED** | 3 retries before ERROR (was 1) |
| 4. Risk | **GAP-15** | **IBKR positions start at $0** | **✅ FIXED** | **Fixed: price waterfall at construction** |
| 4. Risk | GAP-16 | Option symbol format mismatch | 🟠 HIGH | Hub lookup fails → price stays $0 |
| 4. Risk | GAP-17 | EMA subscribes hubs not UPH | 🟠 HIGH | EMA and risk see different prices |
| 4. Risk | GAP-18 | Stale price allows PT exits | 🟡 MED | False PT trigger on stale-high |
| 4. Risk | GAP-19 | Interval extremes periodic only | 🟡 MED | Dip-and-recover invisible |
| 4. Risk | GAP-20 | No cross-broker price consensus | 🟡 MED | Same symbol, different SL triggers |
| 5. Eval | GAP-21 | Dedup gate misses dips | 🟡 MED | Brief SL pierce undetected |
| 5. Eval | GAP-22 | EMA candle gap on disconnect | 🟡 MED | Missed candle close delays EMA exit |
| 5. Eval | GAP-23 | EMA IBKR option underlying mismatch | 🟡 MED | EMA may not fire for IBKR options |
| 5. Eval | GAP-24 | Dynamic SL re-eval gap | 🟡 LOW | 0.2-1s with old SL after PT fill |
| 6. Exec | GAP-25 | ibkr_broker.py: Market/Limit only | 🟡 INFO | Design choice: brackets via risk engine |
| 6. Exec | GAP-26 | Risk engine imports StopOrder inline | 🟡 INFO | Confirms GAP-25 is by design |
| 6. Exec | GAP-27 | Post-fill bracket (1-5s window) | 🟡 LOW | Accepted trade-off for flexibility |
| 6. Exec | GAP-28 | No TrailingStopOrder | 🟠 HIGH | Trailing lost on bot crash |
| 6. Exec | GAP-29 | No TIF control in broker | ✅ **FIXED** | TIF param added (DAY/GTC/IOC/FOK) |
| 6. Exec | GAP-30 | No execDetails/commission events | ✅ **FIXED** | Fill price/time/exchange/commission captured |
| 6. Exec | GAP-31 | No option auto-adjust | 🟡 MED | Option order fails on insufficient |
| 6. Exec | GAP-32 | Option chain returns zeros | 🟡 MED | No live IBKR option chain |
| 6. Exec | GAP-33 | get_positions() flattens by symbol | ✅ **FIXED** | Composite keys prevent overwrite |
| 6. Exec | GAP-34 | Bracket 3-attempt hard cap | 🟡 MED | Transient failure = no bracket ever |
| 6. Exec | GAP-35 | Options bracket deferred after-hours | 🟡 LOW | Correct but noted |
| 7. Lib | GAP-36 | ib_insync deprecated | 🟠 HIGH | Future compatibility risk |

### Counts

| Severity | Count |
|----------|-------|
| ✅ FIXED | 10 (GAP-4, 5, 6, 7, 11, 14, 15, 29, 30, 33) |
| 🟠 HIGH | 6 (GAP-1, 3, 12, 16, 17, 28) |
| 🟡 MEDIUM | 12 |
| 🟡 LOW | 5 |
| 🟡 INFO | 3 (Design choices: GAP-25, 26, 27) |
| **Total** | **36 (10 fixed, 3 design choices, 23 remaining)** |

---

## IBKR Stocks — Remaining Gaps Analysis

**Date**: 2026-06-20 (post-fix assessment)

With GAPs 4, 5, 6, 7, 11, 14, 15, 29, 30, 33 now fixed, the following gaps **still affect IBKR stock trading specifically**:

### Stock-Critical (action needed)

| ID | Gap | Stock Impact | Priority |
|----|-----|-------------|----------|
| GAP-2 | TickByTick 20-symbol limit | With >20 stock positions, symbols 21+ get 200-300ms batched data instead of sub-ms ticks. Affects fast-moving stocks during volatile sessions. | 🟡 MED — IB Gateway hard limit; mitigate by prioritizing high-risk positions for TickByTick slots |
| GAP-19 | Interval extremes periodic only | A stock that dips below SL and recovers within the 0.2s monitoring cycle gap is invisible in the periodic path. The tick-driven path (Path B) catches it, but Path A does not. | 🟡 MED — Add interval_high/low population to the periodic cycle |
| GAP-21 | Dedup gate misses dips | Related to GAP-19: if a stock's price dips below SL and recovers before the next evaluation, the dedup gate sees the same pre/post price and skips. | 🟡 MED — Modify dedup gate to always evaluate when price crossed a risk threshold during the interval |
| GAP-28 | No TrailingStopOrder | If bot crashes, stock trailing stop protection is lost. A native IB `TrailingStopOrder` would survive. Stocks are simpler to bracket than options (no RTH restrictions). | 🟠 HIGH — Implement native `TrailingStopOrder` for stock positions when `broker_bracket_mode` is enabled |
| GAP-34 | Bracket 3-attempt hard cap | A brief IB Gateway restart during bracket placement permanently prevents native stop protection for that stock position. | 🟡 MED — Add periodic retry (e.g., every 60s) after initial 3 failures |

### Stock-Relevant but Lower Priority

| ID | Gap | Stock Impact | Priority |
|----|-----|-------------|----------|
| GAP-8 | Hub cache TTL 30s | New IBKR connection takes up to 30s to appear in UPH. Stocks get prices directly from IBKRDataHub event subscription, so impact is limited to UPH-only consumers. | 🟡 LOW |
| GAP-10 | Event wakeup IBKR only | Not a stock issue — IBKR stocks already use event-driven wakeup. Only affects stocks on other brokers. | N/A for IBKR stocks |
| GAP-12 | Legacy conditional order service | If any stock conditional orders still route through the legacy service, they get inferior monitoring (no UPH, no frozen detection). | 🟠 HIGH — Deprecate legacy path |
| GAP-18 | Stale price allows PT exits | A stock position could false-trigger a profit target on a stale-high price (e.g., previous close during extended hours). | 🟡 MED |
| GAP-20 | No cross-broker NBBO | If same stock is held on IBKR and Schwab, different bid/ask spreads could cause SL on one but not the other. | 🟡 MED |
| GAP-31 | No option auto-adjust | Does not affect stocks — `place_stock_order()` already has auto-adjust. | N/A for stocks |
| GAP-36 | ib_insync deprecated | Affects all IBKR operations including stocks. Long-term migration to ib_async needed. | 🟠 HIGH (long-term) |

### Stock Pipeline Health Summary (Updated after live validation + fixes 2026-06-20)

```
Price Feed:     ✅ Healthy — farm status (GAP-4), dead subs auto-heal (GAP-5), instant reconnect (GAP-6)
Conditional:    ✅ FIXED  — stale price tracking (COND-1), unsubscribe on stop (COND-3), non-blocking retry (COND-4)
Risk Engine:    ✅ FIXED  — bracket placeOrder direct call (RISK-1); RISK-2/RISK-3 remain (stale fetch, zero-price skip)
Execution:      ✅ FIXED  — input validation (EXEC-1), timeout handling (EXEC-2), STC auto-adjust (EXEC-3)
Broker Sync:    ✅ FIXED  — ib.portfolio() with marketPrice (SYNC-1); SYNC-2/SYNC-3 remain (label mismatch)
Positions:      ✅ Healthy — composite keys (GAP-33), no flattening

Remaining Risk: 🟡 Moderate (6 TODO items in priority list)
```

---

## IBKR Stocks — Live Validation Gap Analysis (2026-06-20)

**Method**: End-to-end code trace of 4 pipelines (Execution, Conditional Orders, Risk Engine, Broker Sync)
**Focus**: Stocks on IBKR only — real bugs, race conditions, silent failures
**Result**: 19 new gaps found (6 CRITICAL, 10 HIGH, 3 MEDIUM)

---

### CRITICAL (6) — Trade-Breaking

#### EXEC-1 — No input validation on stock order qty/price
**File**: `ibkr_broker.py:555-566`
**Pipeline**: Execution
**Issue**: The only check is `quantity > MAX_ORDER_SIZE` (caps at 70000). No check for `quantity <= 0`, `quantity == None`, negative price, or zero price for limit orders. Invalid values sent directly to IB API.
**Impact**: A signal with qty=0 or qty=-5 goes to IB. Could cause confusing rejections or unintended behavior.

#### EXEC-2 — _wait_for_fill timeout returns success=True on unacknowledged orders
**File**: `ibkr_broker.py:587-610`
**Pipeline**: Execution
**Issue**: When `_wait_for_fill` times out (10s with no fill status), trade status may be `PreSubmitted`/`PendingSubmit` — neither is in the rejection check. Code falls through to `OrderResult(success=True)` with the limit price as fill price (not actual fill). Position monitor starts tracking a phantom position.
**Impact**: Order reported as filled when it may still be pending at the exchange. Double execution risk.

#### COND-1 — allow_stale=True defeats staleness protection in conditional orders
**File**: `conditional_orders/base.py:497`
**Pipeline**: Conditional Orders
**Issue**: `_query_hub()` calls `get_quote_price(symbol, allow_stale=True)` → IBKRDataHub uses 300s stale threshold. `_update_price_timestamp(price)` resets the staleness clock to `now` every 250ms poll, even when the underlying quote hasn't changed in minutes. The 30-second staleness guard in `_execute_order()` NEVER fires for hub-sourced prices because `_last_price_update_time` is refreshed every poll cycle regardless of actual quote freshness.
**Impact**: Conditional orders can trigger and execute on prices that are **minutes old**. A stock could have dropped 10% but the conditional still triggers on the stale cached price.

#### COND-2 — No execution_callback → order stuck in TRIGGERED forever
**File**: `conditional_orders/base.py:2846`
**Pipeline**: Conditional Orders
**Issue**: If `execution_callback` is `None` (startup race where orders load from DB before bot wires up callback), status is set to `TRIGGERED`, monitor is stopped, order removed from pending. The `if self.execution_callback:` check passes silently. No execution, no retry, no notification, no expiry.
**Impact**: Order permanently stuck in `TRIGGERED` status. No trade executed. No user notification.

#### RISK-1 — asyncio.to_thread wraps IBKR bracket placeOrder — silently fails
**File**: `position_monitor.py:6028,6043,6701,7174`
**Pipeline**: Risk Engine
**Issue**: Bracket SL/PT orders use `await asyncio.to_thread(self.ibkr_broker.ib.placeOrder, contract, sl_order)`. But `ibkr_broker.py:584` has an explicit comment: *"placeOrder is synchronous — do NOT wrap in asyncio.to_thread. asyncio.to_thread runs in a threadpool thread with no event loop, causing ib_insync to raise 'There is no current event loop in thread'."* The exception is caught by the broad `except Exception as e` handler.
**Impact**: **ALL IBKR bracket stop-loss and profit-target orders likely fail silently.** Stock positions on IBKR have NO native broker SL protection. If the bot crashes, there is zero stop-loss coverage.

#### SYNC-1 — broker_sync IBKR current_price always $0 — P&L clobbered
**File**: `broker_sync_service.py:748,1683-1684`
**Pipeline**: Broker Sync
**Issue**: IBKR fetch path calls `ib.positions()` which returns Position namedtuples WITHOUT market price. All stocks get `current_price: 0`. Line 1683-1684 always writes `pnl=0, pnl_percent=0` to DB. Line 1685: `if current_price:` is falsy for 0, so current_price itself isn't written — but the zero P&L IS.
**Impact**: Dashboard P&L for IBKR stock trades is always $0 / 0%. Correct P&L from other components gets overwritten every sync cycle.

---

### HIGH (10) — Significant Reliability Issues

#### EXEC-3 — Auto-adjust fires on STC (sell) orders — wrong qty calculation
**File**: `ibkr_broker.py:615-624`
**Pipeline**: Execution
**Issue**: On "insufficient" error for STC, recalculates `max_qty = int(buying_power / current_price)`. Buying power is irrelevant for sells — should use position quantity. Could compute nonsensical quantity.
**Impact**: Potential naked short or wrong-quantity sell.

#### EXEC-4 — qualifyContractsAsync return value unchecked
**File**: `ibkr_broker.py:560`
**Pipeline**: Execution
**Issue**: `qualifyContractsAsync(contract)` can return empty list for invalid symbols. Return value not checked. Proceeds to `placeOrder` with unqualified contract.
**Impact**: IB rejects with confusing error instead of clean "invalid symbol" message.

#### EXEC-5 — cancel_order returns success on already-filled orders
**File**: `ibkr_broker.py:347-356`
**Pipeline**: Execution
**Issue**: `isDone()` returns `True` for filled orders. Cancel reported as success even though the fill already happened.
**Impact**: Caller places replacement order thinking original was cancelled → double execution.

#### EXEC-6 — tif parameter never passed from signal dispatcher
**File**: `selfbot_webull.py:19187-19204,21473-21479`
**Pipeline**: Execution
**Issue**: Neither paper nor live dispatch paths include `tif` in kwargs to `place_stock_order()`. All IBKR stock entries default to DAY.
**Impact**: GTC/IOC signal intents silently ignored. Entry limit orders always expire at market close.

#### COND-3 — IBKR market data subscriptions leak on monitor stop
**File**: `conditional_orders/base.py:748-755`
**Pipeline**: Conditional Orders
**Issue**: `_try_unsubscribe_streaming()` only handles Schwab/Webull (`_streaming_client` pattern). IBKR uses ib_insync via IBKRDataHub. `reqMktData` is NEVER cancelled when a conditional order monitor stops.
**Impact**: Over time, exhausts IB's ~100 concurrent `reqMktData` limit. New conditionals silently get no streaming data.

#### COND-4 — Execution retry uses blocking time.sleep() — freezes event loop
**File**: `conditional_orders/base.py:2884,2893`
**Pipeline**: Conditional Orders
**Issue**: `time.sleep(5)` + `time.sleep(3)` during retries blocks the asyncio event loop for 8 seconds. All other conditional orders stop receiving price updates.
**Impact**: All conditional order monitoring paused during any execution retry window.

#### RISK-2 — allow_stale=True in _fetch_ibkr_cached accepts 5-min stale prices
**File**: `position_monitor.py:3604-3607`
**Pipeline**: Risk Engine
**Issue**: `get_quote_price(allow_stale=True)` uses IBKRDataHub's 300s stale threshold. But `_update_prices_from_hub()` only overlays quotes <30s old. Position starts with 5-min stale price that's never corrected until a fresh tick arrives.
**Impact**: SL/PT decisions on stale prices for up to 5 minutes after position loading.

#### RISK-3 — Zero-price stock positions silently skipped for risk evaluation
**File**: `position_monitor.py:3632,4424`
**Pipeline**: Risk Engine
**Issue**: When price waterfall fails entirely, snapshot created with `current_price=0`. Zero-price guard (L4424) tries recovery but if it also fails, position is silently skipped — no SL evaluation, no exit, no notification.
**Impact**: IBKR stock position completely unprotected. User sees it in dashboard but risk engine ignores it.

#### SYNC-2 — IBKR broker label mismatch — cache cleanup keys never match
**File**: `broker_sync_service.py:2073,2138,2338`
**Pipeline**: Broker Sync
**Issue**: Sync constructs `pos_key = f"{broker_name}_{symbol}_stock"` with `broker_name='IBKR_LIVE'/'IBKR_PAPER'`. Conditional orders create cache entries with `broker='IBKR'` (no suffix). Keys like `IBKR_AAPL_stock` never match cleanup for `IBKR_LIVE_AAPL_stock`.
**Impact**: Stale cache entries leak. Can cause false risk state on position re-entry.

#### SYNC-3 — broker_sync bypasses IBKRDataHub — parallel inferior data path
**File**: `broker_sync_service.py:701-766`
**Pipeline**: Broker Sync
**Issue**: Calls `ib.positions()` directly instead of using IBKRDataHub which already has streaming positions with market prices. Creates a parallel data path that's strictly worse.
**Impact**: All IBKR data in broker_sync is stale/zero-priced even though real-time data exists in IBKRDataHub.

---

### MEDIUM (3) — Degraded Behavior

#### EXEC-7 — outsideRth on MarketOrder rejected during extended hours
**File**: `ibkr_broker.py:578`
**Pipeline**: Execution
**Issue**: `outsideRth=True` set on ALL orders including MarketOrder. IB rejects MarketOrder with outsideRth for US stocks outside RTH. Only LimitOrder works.
**Impact**: Market orders fail during pre-market/after-hours if extended hours is enabled in settings.

#### EXEC-8 — modify_order does not verify IB accepted the modification
**File**: `ibkr_broker.py:449-455`
**Pipeline**: Execution
**Issue**: After `placeOrder` for modification, sleeps 0.5s and returns success. No status event check.
**Impact**: Silent failure — stop/limit price update may be rejected by IB but caller believes it succeeded.

#### RISK-4 — 5s STALENESS_EXIT_BLOCK too aggressive for low-volume IBKR stocks
**File**: `position_monitor.py:1735`
**Pipeline**: Risk Engine
**Issue**: SL exit blocked if price unchanged >5s. Low-volume stocks naturally have 10-30s gaps between trades.
**Impact**: Genuine SL breach exit delayed up to 60s until REST check override fires.

---

### Priority Fix Order for IBKR Stocks

```
IMMEDIATE (trade safety):                                              STATUS
  1. RISK-1: Fix asyncio.to_thread in bracket placement               ✅ FIXED 2026-06-20
  2. SYNC-1: Use ib.portfolio() in broker_sync (fix P&L display)      ✅ FIXED 2026-06-20
  3. EXEC-2: Check status properly after _wait_for_fill timeout       ✅ FIXED 2026-06-20
  4. COND-1: Track actual quote timestamp vs poll timestamp            ✅ FIXED 2026-06-20

NEXT (reliability):
  5. EXEC-1: Add qty/price validation in place_stock_order             ✅ FIXED 2026-06-20
  6. EXEC-3: Fix auto-adjust to use position qty for STC              ✅ FIXED 2026-06-20
  7. COND-3: Call IBKRDataHub.unsubscribe_symbol() on monitor stop     ✅ FIXED 2026-06-20
  8. COND-4: Replace time.sleep() with asyncio.sleep() in retry       ✅ FIXED 2026-06-20
  9. COND-2: Log error + set status=ERROR when callback is None        ○ TODO
 10. EXEC-4: Check qualifyContractsAsync result                        ○ TODO

LATER (polish):
 11. EXEC-5: Check trade status before reporting cancel success        ○ TODO
 12. EXEC-6: Wire tif from signal through dispatcher                   ○ TODO
 13. SYNC-2: Normalize IBKR/IBKR_LIVE/IBKR_PAPER in cache keys       ○ TODO
 14. EXEC-7: Only set outsideRth on LimitOrder                         ○ TODO
```

---

## Enterprise Architecture Audit — Live Position Monitoring (2026-06-20)

**Scope**: Full pipeline audit — data hubs → snapshot daemon → API → frontend rendering
**Method**: 3 parallel auditors (Snapshot, Data Hub, Frontend) + manual code trace
**Result**: 24 gaps found (4 CRITICAL, 9 HIGH, 11 MEDIUM)

### CRITICAL (4) — Incorrect Financial Data

| ID | Area | Gap | File | Impact |
|---|---|---|---|---|
| HUB-1 | Data Hub | `IBKRDataHub.get_quote()` returns **mutable reference** — streaming thread mutates `.last`/`.bid` while caller reads different tick values | `ibkr_data_hub.py:640-649` | **Data race**: caller sees bid from tick N, ask from tick N+1. Inconsistent snapshot corrupts P&L. Fix: `return copy.copy(q)` under lock |
| SNAP-14 | Snapshot | **Fuzzy match links WRONG DB trade** to live option position when strike=0 | `live_snapshot.py:1131-1147` | Picks first dict-order match — non-deterministic. Wrong P&L, wrong channel attribution, wrong SL% applied |
| FE-1 | Frontend | **P&L assumes long direction** — never checks `trade.direction` | `trades.html:955,847-854` | Short/STO positions show **inverted P&L**. Profitable short displays as loss. Users make wrong decisions |
| FE-2 | Frontend | **Fabricated bid/ask** — `bid=price-0.01, ask=price+0.01` before real quote arrives | `trades.html:1159-1162` | Fake $0.01 spread meaningless for options ($0.10-$1.00 real). Users may submit orders at fabricated prices |

### HIGH (9) — Reliability / Data Loss

| ID | Area | Gap | File | Impact |
|---|---|---|---|---|
| SNAP-2 | Snapshot | `ThreadPoolExecutor.shutdown(wait=True)` **blocks entire daemon** if any broker hangs | `live_snapshot.py:1522-1545` | One hung IBKR call = ALL brokers' data goes stale for 60s+ |
| SNAP-10 | Snapshot | All broker fetchers **swallow exceptions as `[]`** — overwrites previous good data | `live_snapshot.py:multiple` | Auth failure/rate limit → all positions for that broker **vanish** from dashboard |
| HUB-3 | Data Hub | `_subscribed_symbols` set modified from **multiple threads without lock** | `ibkr_data_hub.py:multiple` | Check-then-act race → duplicate `reqMktData` → exhaust IB's 100 subscription limit |
| HUB-4 | Data Hub | `UPH.get_quote_price()` **`allow_stale` parameter is a no-op** | `unified_price_hub.py:369-372` | API contract inconsistency: callers believe they control staleness but they don't |
| HUB-5 | Data Hub | `IBKRDataHub.get_quote()` **returns `last=0`** for newly created symbols before first tick | `ibkr_data_hub.py:640-649` | Risk engine/dashboard sees $0 for new position before first tick arrives |
| SNAP-15 | Snapshot | Multiple DB trades matching same position — **silent data overwrite** | `live_snapshot.py:1148-1175` | Only best-ranked trade's metadata kept. Other trades invisible |
| FE-5 | Frontend | **No concurrency guard** on `unifiedLivePoll` — 3 callers race | `trades.html:1966-2010` | Overlapping responses → older data overwrites newer. Doubled server load when SSE fails |
| FE-4 | Frontend | **Stale `maxQuantity`** baked into quickClose onclick at render time | `trades.html:1039-1041` | Partial fill between rebuilds → user submits close for more shares than held |
| SNAP-8 | Snapshot | **Robinhood cache has no thread lock** — cross-thread data race | `live_snapshot.py:479,487-493` | Torn reads possible; T212 and Webull Official have locks, RH doesn't |

### MEDIUM (11) — Degraded Behavior / Tech Debt

| ID | Area | Gap | File | Impact |
|---|---|---|---|---|
| SNAP-5 | Snapshot | `_last_good_prices_global` grows unbounded | `live_snapshot.py:1421` | Closed positions never evicted. Memory leak over weeks |
| SNAP-7 | Snapshot | `_build_prices` acquires lock per-position | `live_snapshot.py:1442` | 50+ lock acquire/release per cycle. Unnecessary contention |
| HUB-6 | Data Hub | SchwabDataHub event handler registration not thread-safe | `schwab_data_hub.py:101-119` | Two concurrent `on()` calls: second overwrites first, handler lost |
| HUB-8 | Data Hub | `get_quote_detailed()` return keys inconsistent across hubs | multiple | IBKR: no "price" key. Webull: "open"/"close". UPH: "open_price"/"close_price" |
| HUB-10 | Data Hub | `_quotes_lock` held for **entire pendingTickers batch** | `ibkr_data_hub.py:504-529` | Blocks all `get_quote()` callers during 250ms batch processing |
| HUB-11 | Data Hub | `_emit()` passes **mutable** IBKRQuoteData to handlers | `ibkr_data_hub.py:543-544` | Handlers can corrupt internal hub state |
| SNAP-22 | Snapshot | `start_snapshot_daemon` no lock — double start possible | `live_snapshot.py:1635-1651` | Two concurrent calls create two daemon threads |
| FE-7 | Frontend | `.toFixed(2)` truncates sub-penny option prices | `trades.html:929-941` | $0.0050 displays as $0.01. Loses precision |
| FE-8 | Frontend | Full table rebuild loses scroll position | `trades.html:829-832` | Position add/remove → user scrolled to #15 jumps to top |
| FE-6 | Frontend | SSE events carry no price data — always full HTTP fetch | `trades.html:2169-2171` | Every 3-6s backend tick → full round-trip. No version skip |
| HUB-2 | Data Hub | `_per_symbol_last_tick` written without lock | `ibkr_data_hub.py:636` | Reconciliation loop re-subscribes active symbols |

### Priority Fix Matrix

```
IMMEDIATE (financial correctness):                                       STATUS
  1. HUB-1:   Return copy.copy() from IBKRDataHub.get_quote()           ✅ FIXED 2026-06-20
  2. FE-1:    Fix P&L formula for short/STO positions                    ○ TODO (frontend)
  3. SNAP-10: On fetch error, keep previous cache (don't overwrite [])   ✅ FIXED 2026-06-20
  4. HUB-5:   Add last>0 check in IBKRDataHub.get_quote()               ✅ FIXED 2026-06-20

SHORT-TERM (reliability):
  5. SNAP-2:  Use cancel_futures=True or manual executor management      ○ TODO
  6. FE-5:    Add in-flight guard to unifiedLivePoll                     ○ TODO (frontend)
  7. HUB-3:   Lock all _subscribed_symbols access                        ○ TODO
  8. FE-2:    Show "-" instead of fabricated bid/ask                      ○ TODO (frontend)
  9. FE-4:    Read live qty from state, not baked onclick                 ○ TODO (frontend)
 10. SNAP-8:  Add _rh_cache_lock                                         ○ TODO

MEDIUM-TERM (polish):
 11. HUB-4:   Implement allow_stale in UPH.get_quote_price()            ○ TODO
 12. SNAP-5:  Evict closed positions from price caches                   ✅ FIXED 2026-06-20
 13. SNAP-7:  Single lock acquisition in _build_prices loop              ✅ FIXED 2026-06-20
 14. FE-7:    Dynamic toFixed(2/4) based on price magnitude              ○ TODO (frontend)
 15. FE-8:    Save/restore scrollTop around table rebuild                 ○ TODO (frontend)
```
