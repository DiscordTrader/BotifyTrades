# BotifyTrades v9.3.2 — Architecture Reference Prompt

You are working on BotifyTrades, a multi-broker automated trading bot that monitors Discord signals, executes trades, and manages risk across 7+ brokers. Below is the complete architecture for the two core real-time systems.

---

## System 1: Conditional Order Monitoring

### Overview
Conditional orders are "watch and fire" orders — the user says "PAPL over 1.43" and the system monitors the price, then auto-executes a BTO when the condition triggers. Orders are market-isolated (US, India, Canada) and each market runs its own async service with independent broker/hub discovery.

### Components

```
Signal (Discord message)
  → ConditionalOrderRouter          [src/services/conditional_orders/router.py]
    → USConditionalOrderService     [us_service.py]
    → IndiaConditionalOrderService  [india_service.py]
    → CanadaConditionalOrderService [canada_service.py]
      → BaseConditionalOrderService [base.py] — shared monitoring/execution logic
```

### Order Lifecycle

```
PENDING → ACTIVE_MONITORING → TRIGGERED → EXECUTING → EXECUTED
                                                     → FAILED / EXPIRED / CANCELLED
```

1. **Parse**: Signal like `PAPL over 1.43` parsed into symbol, direction (over/under), trigger price
2. **Store**: Written to `conditional_orders` DB table with channel_id, broker, SL/PT from channel settings
3. **Monitor**: `build_price_monitor()` selects the best price source (see Priority Chain below)
4. **Trigger**: `_on_price_update()` compares live price vs trigger — fires when condition met
5. **Execute**: `_execute_order()` runs safety gates then calls `broker.place_order()`

### Price Monitor Priority Chain (P1–P6)

The system picks the highest-quality price source available:

| Priority | Source | Latency | API Cost | Class |
|----------|--------|---------|----------|-------|
| P1 | Primary broker streaming hub (WebSocket cache) | <100ms | Zero | `StreamingPriceMonitor` |
| P2 | Alt broker streaming hub (cross-broker WebSocket) | <100ms | Zero | `StreamingPriceMonitor` |
| P3 | Broker REST API (direct `get_quote()`) | 1-3s | Per-call | `BrokerPriceMonitor` |
| P4 | Hub pending stream (will auto-upgrade) | 1-3s | Minimal | `StreamingPriceMonitor` |
| P5 | Alt hub (not streaming, REST fallback) | 1-3s | Per-call | `StreamingPriceMonitor` |
| P6 | Any connected broker's REST API | 2-5s | Per-call | Fallback |

**StreamingPriceMonitor**: Reads from data hub cache (`hub.get_quote_price(symbol)`). Zero API calls. Falls back to REST if hub has no data. Cross-hub fallback scans all registered hubs.

**BrokerPriceMonitor**: Direct REST polling via `broker.get_quote()`. Rate-limited. Handles async brokers via `asyncio.run_coroutine_threadsafe()` from monitoring thread. When event loop unavailable, falls back to broker's `_data_hub.get_quote_price()` (synchronous cache read).

### Async/Sync Bridge

The conditional order monitor runs in a **separate thread** from the main bot. Brokers like Schwab have async `get_quote()` methods. The bridge:

```python
# In BrokerPriceMonitor._call_broker_quote_sync():
main_loop = broker_instance._event_loop  # Set during broker.connect()
future = asyncio.run_coroutine_threadsafe(broker.get_quote(symbol), main_loop)
result = future.result(timeout=10)

# Fallback when loop unavailable:
hub = broker_instance._data_hub
price = hub.get_quote_price(symbol)  # Sync cache read, no event loop needed
```

### Dynamic Discovery

- **Brokers**: `_discover_brokers()` scans `bot_ref.brokers` / `bot_ref.broker_map`, registers per market
- **Data Hubs**: `_discover_data_hubs()` imports from `_HUB_REGISTRY` (module paths for each hub), registers if available
- **Auto-upgrade**: If streaming starts after P3/P4 selected, monitor upgrades to P1/P2 automatically

### Safety Gates (before execution)

1. Channel execute_enabled check
2. Duplicate trigger guard (`_executing_orders` set)
3. Order expiry validation
4. Price staleness guard (>30s stale → block)
5. Global circuit breaker
6. Channel-specific circuit breaker
7. Daily P&L limits
8. Broker-specific validation
9. Breakout-reset guard (if price already past trigger at creation, require pullback first)

---

## System 2: Risk Management Position Monitoring

### Overview
Monitors all open positions across all connected brokers. Evaluates SL/PT/trailing/EMA/giveback rules per-channel. Places broker-native bracket orders (OCO on Schwab). Handles partial exits, tier cascading, and deferred SL re-placement.

### Components

```
Position Sources (7 brokers)
  → RiskManager                    [src/risk/position_monitor.py]  ~9000 lines
    → PositionCache                [src/risk/position_cache.py]    — persistent state
    → ChannelRiskSettings          [src/risk/risk_types.py]        — per-channel config
    → PositionCacheEntry           [src/risk/risk_types.py]        — per-position state
    → Risk Engine                  [src/risk/risk_engine.py]       — pure evaluation logic
    → UnifiedPriceHub              [src/services/unified_price_hub.py] — cross-broker prices
    → BrokerSyncService            [src/services/broker_sync_service.py] — position reconciliation
```

### Dual Evaluation Model

**1. Poll-Based Cycles** (`_monitoring_cycle()`):
- Runs every ~1s (live) or ~5s (paper)
- Fetches positions from all brokers via REST APIs
- Full risk evaluation per position per cycle
- Metrics: cycle time, fetch time, eval time, position count

**2. Streaming Tick-Based** (event-driven):
- Subscribes to price ticks from Webull/Schwab/IBKR/Tastytrade streaming hubs
- Immediate evaluation on each tick (sub-100ms response)
- Only evaluates "dirty" positions (price changed since last eval)
- Metrics: tick→eval latency, avg/max tick time

**Hybrid**: Both run simultaneously. Streaming handles fast price moves; polling catches positions streaming might miss (new fills, broker reconnects).

### Position Cache (`PositionCacheEntry`)

Persistent state per position (survives restarts via `.position_cache.json`):

```python
# Identity
entry_price, highest_price, original_qty, broker, raw_symbol

# Risk State
stop_loss_price, profit_target_price, trailing_stop_price, dynamic_sl_price

# Tier Tracking (which PT tiers have been hit)
tier1_hit, tier2_hit, tier3_hit, tier4_hit  # boolean flags

# Broker Bracket Orders
broker_stop_order_id      # Standalone SL order ID
broker_pt_order_id        # Standalone PT order ID  
broker_oco_order_id       # OCO combined order ID
broker_oco_sl_price       # OCO SL price
broker_oco_pt_price       # OCO PT price
broker_oco_qty            # OCO quantity
broker_orders_placed      # Flag: brackets already placed

# Deferred SL Re-place (after partial exit)
_pending_broker_sl_replace   # Flag: SL needs re-placement
_pending_sl_replace_price    # Price to re-place SL at
_sl_cancelled_at             # Timestamp of cancellation (15s delay enforced)

# Exit Retry
exit_retry_count, exit_retry_cooldown_until, use_market_order, permanent_failure
```

### Channel Risk Settings (`ChannelRiskSettings`)

Per-channel configuration from database:

```python
# Tiered Profit Targets
profit_target_1_pct .. profit_target_4_pct   # % above entry
profit_target_qty_1 .. profit_target_qty_4   # Custom trim quantities
profit_target_trim_pct_1 .. 4                # % of position to trim

# Stop Loss
stop_loss_pct, sl_order_mode ('market'|'limit'), sl_limit_offset

# Trailing Stop
trailing_stop_pct, trailing_activation_pct

# Advanced Features
enable_dynamic_sl          # Escalate SL after PT hits
enable_giveback_guard      # Exit if gives back >N% of max profit
enable_early_trailing      # Breakeven lock + profit stepping
ema_risk_enabled           # EMA-5 trend monitoring for exits

# Broker Brackets
broker_bracket_mode        # 'both'|'sl_only'|'pt_only'|'none'

# Exit Strategy
exit_strategy_mode         # 'signal'|'risk'|'hybrid'
```

### Risk Evaluation Priority (highest first)

```
1. Hard SL           — immediate protection, immutable
2. Dynamic SL        — escalated SL after profit targets hit
3. EMA Exit          — EMA-5 trend break (candlestick-based)
4. Giveback Guard    — max profit protection (e.g., give back only 30%)
5. Early Trailing    — breakeven lock + profit stepping
6. Tiered PTs        — partial exits at tiers 1-4
7. Legacy Trailing   — classic trailing stop
```

Returns: `ExitDecision(should_exit, reason, exit_qty, is_partial, risk_trigger, tier_hit)`

### Broker Bracket Orders (OCO)

**Initial Placement** (`_place_initial_broker_bracket()`):
- After position detected with `broker_bracket_mode != 'none'`
- Schwab equity: places native OCO (SL + PT as atomic order)
- OCO for `pt1_qty`, standalone SL for remainder (`qty - pt1_qty`)
- Options: separate SL + PT orders (OCO not supported)
- Market trim mode: skips OCO, risk engine handles PT sells

**OCO Order-ID Management**:
```python
# On OCO place:
cache.broker_oco_order_id = oco_id
cache.broker_oco_sl_price = sl_price
cache.broker_oco_pt_price = pt_price
cache.broker_oco_qty = pt1_qty
cache.broker_pt_order_id = oco_id  # Alias — same order

# On OCO cancel (stale ID fix):
_old_oco_id = cache.broker_oco_order_id
await broker.cancel_order(cache.broker_oco_order_id)
if cache.broker_stop_order_id == _old_oco_id:
    cache.broker_stop_order_id = None  # Prevent stale ID cancel loop
cache.broker_oco_order_id = None
```

**PT Tier Cascade**:
```
PT1 fills → cancel OCO → place new OCO for PT2 (new SL + PT2 price, remaining qty)
PT2 fills → cancel OCO → place new OCO for PT3
...
```

**Stop Sync** (SL price updates):
```
Dynamic SL escalates → cancel old OCO → place new OCO (new SL, same PT, same qty)
Trailing SL updates  → cancel old stop → place new stop at trailing price
```

**Deferred SL Re-place** (after partial exit):
```
Partial exit → cancel all brackets → queue STC order
  → set _pending_broker_sl_replace = True
  → _pending_sl_replace_price = captured stop price
  → _sl_cancelled_at = now()
  → After 15s delay: re-place SL for remaining qty
```

**Wide Spread Guard** (SL exit pricing):
```python
if spread_pct >= 50 and last_price > 0:
    stc_price = last_price  # Use last trade, not stale bid
else:
    stc_price = hub_bid     # Normal: use bid
```

### Position Flow

```
Broker Positions (REST/streaming)
  → RiskManager._monitoring_cycle()
    → PositionCache.get_or_create(pos_key)
    → Load ChannelRiskSettings (from DB, cached)
    → Risk Evaluation (pure function → ExitDecision)
    │
    ├─ No exit needed → update cache (highest_price, etc.)
    │
    ├─ Partial exit → _execute_exit(is_partial=True)
    │   → Cancel all brackets
    │   → Queue STC order (partial qty)
    │   → Deferred SL re-place (15s delay)
    │
    └─ Full exit → _execute_exit(is_partial=False)
        → Cancel all brackets
        → Queue STC order (full qty)
        → Mark position closing

Bracket Placement (parallel):
  → _place_initial_broker_bracket()
    → place_oco_order() or place_stop_order() + place_limit_order()
    → Store order IDs in cache
    → Set broker_orders_placed = True

Scale-In Detection (parallel):
  → qty increased? → Cancel old brackets → Re-place for new qty
```

### Broker Sync Service

```
BrokerSyncService (15s interval)
  → Fetch live positions from each broker
  → Match to DB trades (symbol/expiry/strike)
  → Detect new positions → create trade records
  → Detect closed positions → mark trades closed
  → Reconcile pending orders (filled vs cancelled)
  → Notify RiskManager of fills
  → Update account balances (buying power, settled cash)
```

### UnifiedPriceHub Integration

```
UnifiedPriceHub (singleton)
  → Aggregates quotes from all data hubs
  → Index symbol canonicalization (SPX↔SPXW, NDX↔NDXP, VIX↔VIXW)
  → Freshness tracking: FRESH(3s) → PROBE(5s) → STALE(10s) → UNVERIFIED(30s)
  → Shadow comparison: validates risk engine prices against all sources
  → Used by both Conditional Orders and Risk Management
```

---

## Cross-System Integration

```
                    ┌─────────────────────────┐
                    │    Discord Signals       │
                    └──────────┬──────────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                  │
    ┌─────────▼──────────┐            ┌─────────▼──────────┐
    │ Conditional Orders │            │   Direct Trades     │
    │ (watch & fire)     │            │   (immediate BTO)   │
    └─────────┬──────────┘            └─────────┬──────────┘
              │ triggers BTO                     │
              └────────────────┬────────────────┘
                               │ position created
                    ┌──────────▼──────────────┐
                    │    BrokerSyncService     │
                    │  (detects new position)  │
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────┐
                    │    Risk Management       │
                    │  (monitors position)     │
                    │                          │
                    │  ├─ Place OCO brackets   │
                    │  ├─ Monitor SL/PT/trail  │
                    │  ├─ Cascade PT tiers     │
                    │  └─ Execute exits        │
                    └──────────┬──────────────┘
                               │
                    ┌──────────▼──────────────┐
                    │   UnifiedPriceHub        │
                    │  (cross-broker prices)   │
                    │                          │
                    │  ├─ Webull MQTT stream   │
                    │  ├─ Schwab WebSocket     │
                    │  ├─ IBKR TWS stream      │
                    │  ├─ Tastytrade DXLink    │
                    │  └─ REST fallback polls  │
                    └─────────────────────────┘
```

### Supported Brokers

| Broker | Execution | Streaming | OCO Brackets | Markets |
|--------|-----------|-----------|-------------|---------|
| Schwab | ✅ | ✅ WebSocket | ✅ Native OCO | US |
| Webull | ✅ | ✅ MQTT | ✅ | US |
| Alpaca | ✅ | ✅ WebSocket | ✅ | US |
| IBKR | ✅ | ✅ TWS | ✅ | US, Canada |
| Tastytrade | ✅ | ✅ DXLink | ❌ | US |
| Robinhood | ✅ | ❌ | ❌ | US |
| Trading212 | ✅ | ✅ | ❌ | UK/EU |

### Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/risk/position_monitor.py` | ~9000 | Core risk monitoring, bracket orders, exits |
| `src/risk/risk_types.py` | ~900 | PositionCacheEntry, ChannelRiskSettings dataclasses |
| `src/risk/position_cache.py` | ~500 | Persistent position state, atomic save |
| `src/risk/risk_engine.py` | ~400 | Pure evaluation logic, ExitDecision |
| `src/services/conditional_orders/base.py` | ~2000 | Base monitoring service, price monitors |
| `src/services/conditional_orders/us_service.py` | ~200 | US market service, P1-P6 priority chain |
| `src/services/conditional_orders/router.py` | ~150 | Market routing dispatcher |
| `src/services/unified_price_hub.py` | ~600 | Cross-broker price aggregation |
| `src/services/broker_sync_service.py` | ~3000 | Position reconciliation |
| `src/brokers/schwab_broker.py` | ~3000 | Schwab API, OCO orders, HTTP recovery |
