# Broker-Side Stop Loss with Continuous Escalation
## BotifyTrades — Industry-Grade Architecture Plan

**Date**: February 19, 2026
**Status**: Planning (Not Yet Implemented)
**Scope**: All 10 brokers in the BotifyTrades system

---

## 1. Executive Summary

This plan introduces broker-side stop loss (SL) placement and continuous escalation for BotifyTrades. Instead of relying solely on software-side price monitoring to trigger exits, the system will:

1. Place a protective stop loss order directly at the broker when a position opens
2. Continuously modify/escalate that broker-side SL as the risk engine (early trailing, trailing stop, dynamic SL, giveback guard) updates the stop level
3. Provide a safety net: if the bot crashes or disconnects, the broker-side SL still protects the position

The architecture uses a **hybrid approach** — broker-side SL as a safety net with software-side monitoring remaining the authoritative risk engine.

---

## 2. Current Architecture

### 2.1 Risk Engine (`src/risk/risk_engine.py`)

Pure function `evaluate_exit_actions()` returns `List[RiskAction]` with these action types:

| ActionType | Description | Has `new_stop_price` |
|---|---|---|
| `MOVE_STOP` | Dynamic SL escalation after PT hits | Yes |
| `UPDATE_TRAIL_STOP` | Legacy trailing stop ratchets up | Yes |
| `UPDATE_EARLY_STOP` | Early trailing locks profit at next step | Yes |
| `ACTIVATE_TRAIL` | Legacy trailing stop activates | No |
| `ACTIVATE_EARLY_TRAIL` | Early trailing activates (breakeven locked) | Yes (entry price) |
| `ACTIVATE_GIVEBACK` | Giveback guard arms | No |
| `SELL_PARTIAL` | Profit target trim | No |
| `SELL_ALL` | Full exit (SL, trailing, giveback) | No |

**Exit Priority Order:**
1. Hard SL (immediate protection)
2. Dynamic SL (after PT hits)
3. Giveback Guard (max profit protection)
4. Early Trailing Stop (breakeven + profit locking)
5. Tiered Profit Targets (partial exits)
6. Legacy Trailing Stop (after activation)

### 2.2 Position Monitor (`src/risk/position_monitor.py`)

- Async polling loop fetching broker positions and running risk engine
- `_execute_exit()` places market/limit sell orders when risk triggers fire
- Exit Order Arbiter integration with `threading.Lock` for cross-thread safety
- Retry logic with fast retries then extended 5-min intervals

### 2.3 Position Cache (`src/risk/position_cache.py`)

- Thread-safe cache with per-position state (trailing, early trailing, dynamic SL, giveback)
- File persistence + database persistence via trade_id mapping
- Broker name normalization across all 10 brokers

### 2.4 Exit Order Arbiter (`src/services/exit_order_arbiter.py`)

- Arbitrates between signal-driven and risk-driven exits
- HYBRID mode: uses TIGHTER protection (SL can NEVER be lowered)
- Precedence: Manual Override > Circuit Breaker > Signal/Risk rules

### 2.5 Unfilled Order Chaser (`src/services/unfilled_order_chaser.py`)

- Monitors pending exit orders and replaces stale ones with mid-price limit orders
- Has startup restoration for pending orders

### 2.6 Key Gap in Current System

**`MOVE_STOP`, `UPDATE_TRAIL_STOP`, and `UPDATE_EARLY_STOP` actions are emitted by the risk engine but only update the internal cache — no broker-side order is ever placed or modified.** The system is entirely "software-side SL" today.

---

## 3. Broker API Compatibility Matrix

### 3.1 Full Capability Matrix

| Broker | SDK | Stop Orders | Modify/Replace | Method | Options SL | GTC Support | Paper Mode | Market |
|---|---|---|---|---|---|---|---|---|
| **Alpaca** | alpaca-py | Stop, StopLimit | Native replace | `replace_order_by_id(ReplaceOrderRequest)` | Stocks only | Yes | Yes | US |
| **Webull** | tedchou12/webull | STP via place_order | Cancel + New | `cancel_order()` + `place_order(orderType='STP')` | Limited | Yes | Yes | US |
| **Schwab** | httpx (direct API) | Stop, StopLimit | Atomic replace | `PUT /accounts/{hash}/orders/{id}` | Yes | Yes | No | US |
| **Robinhood** | robin-stocks | Stop | Cancel + New | `cancel_stock_order()` + `order_sell_stop_loss()` | Stocks only | Yes (GTC) | No | US |
| **IBKR** | ib-insync | Stop, StopLimit, Trailing | Native modify | Re-call `ib.placeOrder(contract, order)` | Full | Yes | Yes | US/Global |
| **Tastytrade** | tastytrade SDK | Stop (stop_trigger) | Native replace | `account.replace_order(session, id, new_order)` | Full | Yes | Yes | US |
| **Questrade** | qtrade | Stop, StopLimit, Trailing | Replace via POST | `POST /accounts/{id}/orders` with orderId | Yes | Yes | Yes | Canada |
| **Upstox** | Upstox API v3 | SL, SL-M, GTT | Native modify | `modify_order(order_id, trigger_price=...)` | Yes (F&O) | GTT = GTC | No | India |
| **Zerodha** | KiteConnect | SL, SL-M | Native modify | `kite.modify_order(order_id, trigger_price=...)` | Yes (F&O) | DAY only | No | India |
| **DhanQ** | DhanHQ API | SL | Native modify | `modify_order(order_id, trigger_price=...)` | Yes (F&O) | DAY only | No | India |

### 3.2 Broker Tiers

**Tier 1 — Native Replace/Modify (8 brokers):**
- Alpaca, IBKR, Schwab, Tastytrade, Questrade, Upstox, Zerodha, DhanQ
- These brokers can modify stop price in-place without cancel/recreate race conditions

**Tier 2 — Cancel + New Required (2 brokers):**
- Webull, Robinhood
- Must cancel existing SL and place a new one, with race condition mitigation

### 3.3 Special Capabilities

| Broker | Native Trailing Stop | Bracket/OCO | Atomic Replace | Best For |
|---|---|---|---|---|
| **IBKR** | TrailingStopOrder | Full bracket leg modify | Yes (same orderId) | Most reliable SL management |
| **Schwab** | No | No | Yes (PUT) | Atomic replace eliminates race |
| **Alpaca** | No (bracket only) | Bracket (but not replaceable) | Yes (simple orders) | Paper testing |
| **Tastytrade** | No | OCO via NewComplexOrder | Yes | Options-focused trading |
| **Upstox** | GTT with trailing_gap | GTT multi-leg | Yes | India market with native trail |
| **Questrade** | Trailing Stop, Trailing StopLimit | Bracket orders | Yes | Canada market |

---

## 4. Proposed Architecture

### 4.1 Hybrid Model

```
┌─────────────────────────────────────────────────────────────────┐
│                     RISK ENGINE (existing)                       │
│  evaluate_exit_actions() → List[RiskAction]                     │
│  MOVE_STOP / UPDATE_TRAIL_STOP / UPDATE_EARLY_STOP / SELL_ALL   │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   POSITION MONITOR (existing)                    │
│  Processes RiskActions:                                          │
│  • SELL_ALL/SELL_PARTIAL → _execute_exit() (existing)           │
│  • MOVE_STOP/UPDATE_* → StopOrderManager.escalate() (NEW)      │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│              STOP ORDER MANAGER (NEW SERVICE)                    │
│                                                                  │
│  Responsibilities:                                               │
│  1. Place initial SL when BTO fills                             │
│  2. Escalate SL when risk engine updates stop level             │
│  3. Cancel SL before software-side exits (prevent double-sell)  │
│  4. Sync quantity after partial exits (PT trims)                │
│  5. Recover/reconcile on startup                                │
│  6. Debounce rapid updates (rate limit protection)              │
│                                                                  │
│  State: Dict[position_key, StopOrderHandle]                     │
│                                                                  │
│  Per-broker adapter pattern:                                     │
│  ├── Tier 1: broker.replace_stop(handle, new_price)             │
│  └── Tier 2: broker.cancel_stop(handle) + broker.place_stop()   │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│              BROKER STOP ADAPTER (per-broker)                    │
│                                                                  │
│  Interface methods (added to BrokerInterface):                   │
│  • place_stop_loss(symbol, qty, stop_price, ...) → handle       │
│  • modify_stop_loss(handle, new_stop_price) → handle            │
│  • cancel_stop_loss(handle) → bool                              │
│  • get_stop_order_status(handle) → status                       │
│  • get_open_stop_orders() → List[handle]  (for recovery)        │
│                                                                  │
│  Capability flags:                                               │
│  • supports_stop_replace: bool                                   │
│  • supports_options_sl: bool                                     │
│  • supports_gtc_stops: bool                                      │
│  • supports_native_trailing: bool                                │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Data Model: StopOrderHandle

```python
@dataclass
class StopOrderHandle:
    """Tracks a broker-side protective stop loss order."""
    broker_order_id: str              # Broker's order ID
    client_order_id: str              # Our internal tracking ID
    position_key: str                 # Links to PositionCache entry
    broker_name: str                  # Which broker holds this order
    symbol: str                       # Ticker symbol
    asset_type: str                   # 'stock' or 'option'
    stop_price: float                 # Current stop price at broker
    quantity: int                     # Order quantity
    order_type: str                   # 'stop', 'stop_limit', 'trailing'
    time_in_force: str                # 'GTC', 'DAY'
    status: str                       # 'active', 'filled', 'cancelled', 'pending', 'rejected'
    revision: int                     # Incremented on each modify (race detection)
    created_at: datetime
    last_modified_at: datetime
    
    # Option-specific fields
    strike: Optional[float] = None
    expiry: Optional[str] = None
    option_type: Optional[str] = None  # 'C' or 'P'
    raw_symbol: Optional[str] = None   # OCC format for Alpaca, etc.
```

### 4.3 StopOrderManager Service

```python
class StopOrderManager:
    """
    Orchestrates broker-side stop loss placement and escalation.
    
    Lifecycle:
    1. on_position_opened() → place initial SL at broker
    2. on_risk_action(MOVE_STOP/UPDATE_*) → escalate SL at broker
    3. on_partial_exit() → reduce SL quantity to match remaining position
    4. on_full_exit() → cancel broker-side SL (prevent orphan orders)
    5. on_startup() → recover and reconcile existing broker SL orders
    """
    
    def __init__(self):
        self._handles: Dict[str, StopOrderHandle] = {}  # position_key → handle
        self._debounce_timers: Dict[str, float] = {}     # position_key → last_update_time
        self._lock = threading.Lock()
    
    # Core methods:
    async def place_initial_stop(self, position, broker, stop_price, channel_settings)
    async def escalate_stop(self, position_key, new_stop_price, reason)
    async def sync_quantity(self, position_key, new_quantity)
    async def cancel_stop(self, position_key, reason)
    async def recover_on_startup(self, brokers)
    
    # Internal:
    def _should_debounce(self, position_key) -> bool
    def _get_broker_adapter(self, broker_name) -> BrokerStopAdapter
    async def _handle_fill_detection(self, handle)
```

---

## 5. Critical Gap Analysis

### 5.1 CRITICAL Severity

| # | Gap | Risk | Solution |
|---|---|---|---|
| G1 | MOVE_STOP actions emitted but never consumed for broker orders | Positions have NO broker-side protection | StopOrderManager consumes MOVE_STOP/UPDATE_* actions and translates to broker API calls |
| G2 | No stop order tracking infrastructure | Can't track broker SL state, detect fills, or reconcile | StopOrderHandle data model in PositionCache with broker_order_id, status, revision |
| G3 | Double-sell race: software exit vs broker SL | Position sold twice (2x loss or margin violation) | Before SELL_ALL, StopOrderManager cancels broker SL first. Atomic "closing" flag in cache. Integrate with Exit Order Arbiter |

### 5.2 HIGH Severity

| # | Gap | Risk | Solution |
|---|---|---|---|
| G4 | Cancel-while-filling race (Webull, Robinhood) | Orphan SL orders or missed position closure | "Place-then-cancel" pattern: place new SL first, then cancel old. If cancel fails (already filled), cancel new SL and mark position closed |
| G5 | Partial fill quantity sync after PT trims | SL quantity exceeds actual position → rejection or over-sell | After every SELL_PARTIAL, StopOrderManager modifies SL quantity to match remaining position |
| G6 | Startup recovery and reconciliation | Duplicate SLs or unprotected positions after restart | On boot, fetch open orders from all brokers, match against cache, adopt/modify/cancel as needed |

### 5.3 MEDIUM Severity

| # | Gap | Risk | Solution |
|---|---|---|---|
| G7 | Options SL support varies by broker | Some positions unprotected at broker level | Capability flag per broker. Fall back to software-only exits for unsupported brokers. Show in UI |
| G8 | API rate limits from rapid escalation | Rate limit violations, temporary broker API bans | Per-position debouncing: min 2-3 sec between broker updates, coalesce rapid MOVE_STOP actions |
| G9 | GTC vs DAY expiry handling | Overnight gap downs unprotected if DAY stops expired | Always use GTC. For brokers with DAY-only (Zerodha, DhanQ), implement pre-market SL re-placement check |
| G10 | Unfilled Order Chaser interference | Chaser could modify/replace protective SL orders | Tag broker-side SLs as "protective" — exclude from chaser's jurisdiction |

### 5.4 LOW Severity / Enhancements

| # | Gap/Enhancement | Description | Solution |
|---|---|---|---|
| E1 | Native trailing stops (IBKR, Questrade, Upstox) | Reduces API calls during trailing | Use broker's native TrailingStopOrder for legacy trailing mode. Keep cancel+replace for early trailing (more precise) |
| E2 | Per-channel toggle | Not all users want broker-side SL | Add `enable_broker_side_sl: bool` to ChannelRiskSettings |
| E3 | UI indicators for broker SL | Users can't see broker SL status | Add "Broker SL: $X.XX" badge to Live Trading Monitor risk status column (extends existing implementation) |
| E4 | Schwab atomic replace advantage | Schwab's PUT is truly atomic (no race) | Mark as "preferred" for reliability. No cancel-while-filling gap |
| E5 | Multi-broker position SL tracking | Channel routing to multiple brokers | StopOrderManager maintains per-position per-broker handles: `Dict[position_key + broker, StopOrderHandle]` |

---

## 6. Race Condition Solutions (Detailed)

### 6.1 Double-Sell Prevention (G3)

**Scenario**: Risk engine fires `SELL_ALL` (e.g., giveback guard) while a broker-side SL is sitting on the books.

**Solution Flow**:
```
1. Risk engine emits SELL_ALL action
2. Position Monitor calls StopOrderManager.cancel_stop(position_key)
3. StopOrderManager checks handle status:
   a. If handle.status == 'active': cancel broker order, wait for confirmation
   b. If handle.status == 'filled': SL already executed → skip software exit, mark position closed
   c. If handle.status == 'cancelled': already cancelled → proceed with software exit
4. Only after SL is confirmed cancelled → execute software-side STC
5. Set cache.closing = True to prevent re-entry
```

**Integration with Exit Order Arbiter**:
- Add `broker_sl_active: bool` to arbiter context
- Arbiter checks: if broker SL is active and close to triggering, prefer letting broker SL handle exit (less latency)

### 6.2 Cancel-While-Filling (Webull, Robinhood) (G4)

**Scenario**: Old SL fills between our cancel request and new SL placement.

**"Place-Then-Cancel" Pattern**:
```
1. Generate new client_order_id = f"{position_key}_rev{revision+1}"
2. Place NEW stop order at new_stop_price (with new client_order_id)
3. Confirm new order accepted (status = 'active' or 'pending')
4. Cancel OLD stop order (using old handle.broker_order_id)
5. Check cancel result:
   a. Cancel succeeded → update handle to new order. Done.
   b. Cancel failed (already filled) → 
      - Old SL executed, position is closed
      - Cancel the NEW stop order (it's now an orphan)
      - Mark position as closed in cache
      - Log: "Broker SL filled during escalation"
6. Update handle revision
```

**Why "place-then-cancel" is safer than "cancel-then-place"**:
- In "cancel-then-place": if cancel succeeds but new placement fails (API error), position is temporarily unprotected
- In "place-then-cancel": position is always protected by at least one SL order at all times
- Worst case: briefly two SL orders exist (double protection, not double risk)

### 6.3 Partial Exit Quantity Sync (G5)

**Scenario**: PT1 fires, selling 3 of 10 contracts. Broker SL still shows qty=10.

**Solution**:
```
1. After SELL_PARTIAL executes and fills:
2. remaining_qty = position.remaining_qty  (e.g., 7)
3. StopOrderManager.sync_quantity(position_key, remaining_qty)
4. Manager modifies broker SL order: qty=10 → qty=7
5. If modify fails: cancel old SL, place new SL with qty=7
```

---

## 7. Debounce & Rate Limit Strategy (G8)

### 7.1 Debounce Rules

```python
DEBOUNCE_CONFIG = {
    'min_interval_seconds': 2.0,        # Min time between broker updates
    'min_price_change_pct': 0.1,        # Min % change to trigger update
    'min_price_change_ticks': 0.01,     # Min absolute $ change
    'max_coalesce_seconds': 10.0,       # Max time to hold a pending update
}
```

### 7.2 Coalescing Logic

```
1. Risk engine emits UPDATE_EARLY_STOP with new_stop_price=$5.15
2. StopOrderManager checks debounce:
   - Last broker update was 0.3s ago → too soon
   - Store pending_update = $5.15
3. 0.5s later: Another UPDATE_EARLY_STOP with new_stop_price=$5.18
   - Still debouncing → overwrite pending_update = $5.18
4. 2.0s after last broker update: debounce timer fires
   - Send pending_update $5.18 to broker (skipped $5.15 entirely)
   - Reset debounce timer
```

### 7.3 Per-Broker Rate Limits

| Broker | Rate Limit | Recommended Interval |
|---|---|---|
| Alpaca | ~200/min | 2s |
| Webull | 1 req/sec | 3s |
| Schwab | 2-4 trades/sec | 2s |
| Robinhood | ~6/min for trades | 10s |
| IBKR | 50/sec (but throttled) | 1s |
| Tastytrade | ~120/min | 2s |
| Questrade | ~30/sec | 2s |
| Upstox | ~25/sec | 2s |
| Zerodha | ~10/sec | 3s |
| DhanQ | ~20/sec | 2s |

---

## 8. Startup Recovery Protocol (G6)

### 8.1 Recovery Flow

```
On bot startup:
1. Load position cache from file/database (existing behavior)
2. Load StopOrderHandle records from database
3. For each connected broker:
   a. Fetch all open orders via broker API
   b. Filter for stop/stop-limit sell orders
   c. Match against StopOrderHandle records:
      
      CASE 1: Handle exists + Broker order exists + Prices match
      → Adopt: update handle status to 'active'. No action needed.
      
      CASE 2: Handle exists + Broker order exists + Price is stale
      → Modify: escalate broker SL to current risk engine level.
      
      CASE 3: Handle exists + Broker order NOT found
      → SL was filled or cancelled externally:
        - Check if position still exists at broker
        - If position gone: mark trade as closed, clean up
        - If position exists: re-place SL at current risk level
      
      CASE 4: No handle + Broker order exists (manual SL?)
      → Ignore (user-placed order) or adopt with warning
      
      CASE 5: Position exists + No handle + No broker order
      → Place new SL at current risk engine level
```

### 8.2 Database Schema for StopOrderHandle Persistence

```sql
CREATE TABLE broker_stop_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_key TEXT NOT NULL,
    trade_id INTEGER REFERENCES trades(id),
    broker_name TEXT NOT NULL,
    broker_order_id TEXT,
    client_order_id TEXT,
    symbol TEXT NOT NULL,
    asset_type TEXT DEFAULT 'stock',
    stop_price REAL NOT NULL,
    quantity INTEGER NOT NULL,
    order_type TEXT DEFAULT 'stop',
    time_in_force TEXT DEFAULT 'GTC',
    status TEXT DEFAULT 'pending',
    revision INTEGER DEFAULT 0,
    strike REAL,
    expiry TEXT,
    option_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE(position_key, broker_name)
);

CREATE INDEX idx_broker_stops_status ON broker_stop_orders(status);
CREATE INDEX idx_broker_stops_position ON broker_stop_orders(position_key);
```

---

## 9. Options Stop Loss Capability (G7)

### 9.1 Per-Broker Options SL Support

| Broker | Stock SL | Options SL | Notes |
|---|---|---|---|
| **IBKR** | Full | Full | StopOrder works on any instrument |
| **Tastytrade** | Full | Full | Stop with stop_trigger on option legs |
| **Schwab** | Full | Full | Stop/StopLimit on equity options |
| **Alpaca** | Full | Limited | Options stops may not be supported via alpaca-py |
| **Robinhood** | Full | No | robin-stocks only has stock stop functions |
| **Webull** | Full | Limited | Unofficial SDK limited for option stops |
| **Questrade** | Full | Yes | Stop orders on options supported |
| **Upstox** | Full | Yes (F&O) | SL orders on futures and options |
| **Zerodha** | Full | Yes (F&O) | SL/SL-M on F&O segments |
| **DhanQ** | Full | Yes (F&O) | SL on options via order API |

### 9.2 Fallback Strategy for Unsupported Brokers

For brokers that don't support options stop orders:
1. Continue using software-side monitoring and exits (current behavior)
2. Show a warning indicator in the UI: "Broker SL: N/A (options not supported)"
3. Log: `[STOP_MGR] ⚠️ {broker} does not support options SL — using software-side protection`
4. Consider using a lower polling interval for these positions (faster software detection)

---

## 10. Integration Points

### 10.1 Where StopOrderManager Hooks Into Existing Code

**Position Monitor — Action Processing** (`position_monitor.py`):
```python
# In the action processing loop (after evaluate_exit_actions):
for action in actions:
    if action.action_type in (ActionType.MOVE_STOP, ActionType.UPDATE_TRAIL_STOP, 
                               ActionType.UPDATE_EARLY_STOP):
        # NEW: Escalate broker-side SL
        await self.stop_manager.escalate_stop(
            position_key=pos_key,
            new_stop_price=action.new_stop_price,
            reason=action.reason
        )
    
    elif action.action_type == ActionType.SELL_ALL:
        # NEW: Cancel broker-side SL before executing exit
        await self.stop_manager.cancel_stop(pos_key, reason="Software exit triggered")
        await self._execute_exit(position, cache, decision, channel_settings)
    
    elif action.action_type == ActionType.SELL_PARTIAL:
        await self._execute_exit(position, cache, decision, channel_settings)
        # NEW: Sync SL quantity after partial exit
        await self.stop_manager.sync_quantity(pos_key, state.remaining_qty)
```

**BTO Fill Detection** (where positions are first tracked):
```python
# After BTO order fills and position is added to cache:
initial_sl_price = entry_price * (1 - channel_settings.stop_loss_pct / 100)
await self.stop_manager.place_initial_stop(
    position=position,
    broker=broker_instance,
    stop_price=initial_sl_price,
    channel_settings=channel_settings
)
```

**Exit Order Arbiter** (`exit_order_arbiter.py`):
```python
# Add broker SL awareness:
class ArbiterResult:
    approved: bool
    final_sl: float
    reason: str
    source_used: Optional[str] = None
    requires_broker_update: bool = False  # Already exists!
    broker_sl_active: bool = False        # NEW
```

**Unfilled Order Chaser** (`unfilled_order_chaser.py`):
```python
# Exclude protective SL orders from chasing:
# Filter: only chase orders NOT in StopOrderManager's handle registry
```

### 10.2 Broker Interface Extension (`src/broker_interface.py`)

```python
class BrokerInterface(ABC):
    # ... existing methods ...
    
    # NEW: Stop Loss Management (optional — default implementations provided)
    
    @property
    def stop_loss_capabilities(self) -> Dict[str, bool]:
        """Return broker's stop loss capabilities."""
        return {
            'supports_stop_orders': False,
            'supports_stop_replace': False,
            'supports_options_sl': False,
            'supports_gtc_stops': False,
            'supports_native_trailing': False,
        }
    
    async def place_stop_loss(self, symbol, quantity, stop_price, ...) -> Optional[StopOrderHandle]:
        """Place a protective stop loss order. Returns handle or None if unsupported."""
        return None  # Default: not implemented
    
    async def modify_stop_loss(self, handle, new_stop_price) -> Optional[StopOrderHandle]:
        """Modify an existing stop loss order. Returns updated handle."""
        return None
    
    async def cancel_stop_loss(self, handle) -> bool:
        """Cancel an existing stop loss order. Returns success."""
        return False
    
    async def get_stop_order_status(self, handle) -> str:
        """Get current status of a stop order. Returns status string."""
        return 'unknown'
    
    async def get_open_stop_orders(self) -> List[Dict]:
        """Get all open stop orders for recovery. Returns list of order dicts."""
        return []
```

---

## 11. Per-Broker Implementation Details

### 11.1 Alpaca

```python
# Place: StopOrderRequest with stop_price
# Modify: trading_client.replace_order_by_id(order_id, ReplaceOrderRequest(stop_price=new))
# Cancel: trading_client.cancel_order_by_id(order_id)
# Note: Bracket order legs CANNOT be replaced — use cancel+new
# Options SL: Limited — use software fallback
# GTC: Supported
```

### 11.2 Webull (Tier 2 — Cancel+New)

```python
# Place: wb.place_order(stock=symbol, price=stop_price, action='SELL', orderType='STP', enforce='GTC', quant=qty)
# Modify: NOT AVAILABLE → use place-then-cancel pattern
# Cancel: wb.cancel_order(order_id)
# Options SL: Limited via unofficial SDK
# GTC: Supported
# Rate limit: 1 req/sec — use 3s debounce
```

### 11.3 Schwab

```python
# Place: POST /accounts/{hash}/orders with orderType='STOP'
# Modify: PUT /accounts/{hash}/orders/{id} (atomic replace — BEST)
# Cancel: DELETE /accounts/{hash}/orders/{id}
# Options SL: Full support
# GTC: Supported (GOOD_TILL_CANCEL)
# Advantage: Atomic replace eliminates cancel-while-filling race entirely
```

### 11.4 Robinhood (Tier 2 — Cancel+New)

```python
# Place: rh.orders.order_sell_stop_loss(symbol, quantity, stopPrice, timeInForce='gtc')
# Modify: NOT AVAILABLE → use place-then-cancel pattern
# Cancel: rh.orders.cancel_stock_order(order_id)
# Options SL: NOT SUPPORTED (stocks only)
# GTC: Supported
# Rate limit: ~6 trades/min — use 10s debounce
# WARNING: Robinhood has NO paper mode — all trades are REAL
```

### 11.5 Interactive Brokers

```python
# Place: ib.placeOrder(contract, StopOrder('SELL', qty, stop_price))
# Modify: order.auxPrice = new_price; ib.placeOrder(contract, order)  # Same object = modify
# Cancel: ib.cancelOrder(order)
# Options SL: FULL support (any instrument)
# GTC: Supported
# Native trailing: TrailingStopOrder available
# Bracket: bracketOrder() with individual leg modification
# BEST broker for SL management
```

### 11.6 Tastytrade

```python
# Place: NewOrder(order_type=OrderType.STOP, stop_trigger=Decimal(price), legs=[leg])
# Modify: account.replace_order(session, order_id, new_order)
# Cancel: account.delete_order(session, order_id)
# Options SL: FULL support
# OCO: NewComplexOrder for bracket-style orders
# GTC: Supported (OrderTimeInForce.GTC)
```

### 11.7 Questrade

```python
# Place: POST /accounts/{id}/orders with orderType='Stop', stopPrice=price
# Modify: POST /accounts/{id}/orders with orderId=existing_id
# Cancel: DELETE /accounts/{id}/orders/{id}
# Options SL: Supported
# Native trailing: TrailingStop and TrailingStopLimit supported
# GTC: Supported
# Note: Trading API restricted to partner developers
```

### 11.8 Upstox (India)

```python
# Place: place_order(trigger_price=stop_price, order_type='SL' or 'SL-M')
# Modify: modify_order(order_id, trigger_price=new_price)
# Cancel: cancel_order(order_id)
# Options SL: Yes (F&O segment)
# GTT: place_gtt_order() with trailing_gap for native trailing
# GTC: GTT orders persist until triggered
# Enhancement: Use GTT with trailing_gap for automatic trailing
```

### 11.9 Zerodha (India)

```python
# Place: kite.place_order(trigger_price=stop_price, order_type='SL' or 'SL-M')
# Modify: kite.modify_order(order_id, trigger_price=new_price)
# Cancel: kite.cancel_order(order_id)
# Options SL: Yes (F&O segment)
# GTC: DAY only — need pre-market re-placement
# Note: SL-M (stop loss market) is fastest exit, SL (stop loss limit) allows price control
```

### 11.10 DhanQ (India)

```python
# Place: place_order(trigger_price=stop_price, order_type='SL')
# Modify: modify_order(order_id, trigger_price=new_price)
# Cancel: cancel_order(order_id)
# Options SL: Yes (F&O segment)
# GTC: DAY only — need pre-market re-placement
```

---

## 12. Implementation Phases

### Phase 1: Foundation (Critical)
- [ ] Define `StopOrderHandle` data model
- [ ] Create `StopOrderManager` service skeleton
- [ ] Add `broker_stop_orders` database table
- [ ] Add stop loss capability flags to `BrokerInterface`
- [ ] Wire `StopOrderManager` into `PositionMonitor` action processing

### Phase 2: Core Broker Implementations (Critical)
- [ ] Alpaca: `place_stop_loss()`, `modify_stop_loss()`, `cancel_stop_loss()`
- [ ] IBKR: Full implementation with native modify
- [ ] Schwab: Full implementation with atomic replace
- [ ] Tastytrade: Full implementation with `replace_order()`

### Phase 3: Tier 2 Brokers with Race Protection (High)
- [ ] Webull: Cancel+new with place-then-cancel pattern
- [ ] Robinhood: Cancel+new with place-then-cancel pattern
- [ ] Implement race condition detection and recovery

### Phase 4: Safety Mechanisms (High)
- [ ] Double-sell prevention (cancel broker SL before software exit)
- [ ] PT trim quantity sync
- [ ] Startup recovery and reconciliation
- [ ] Debounce and rate limiting

### Phase 5: India & Canada Brokers (Medium)
- [ ] Zerodha: Native modify with DAY expiry handling
- [ ] Upstox: Native modify + GTT trailing enhancement
- [ ] DhanQ: Native modify with DAY expiry handling
- [ ] Questrade: Replace via POST

### Phase 6: Enhancements (Low)
- [ ] Per-channel `enable_broker_side_sl` setting in UI
- [ ] Broker SL status indicators in Live Trading Monitor
- [ ] Native trailing stop for IBKR/Questrade/Upstox
- [ ] Options SL capability detection and UI warnings

---

## 13. Testing Strategy

### 13.1 Paper Trading Validation
- **Alpaca Paper**: Full SL placement, escalation, cancel, quantity sync
- **IBKR Paper**: Full SL with native modify, bracket leg modification
- **Webull Paper**: Cancel+new pattern with race simulation
- **Tastytrade Paper**: Full SL with replace_order

### 13.2 Simulated Race Conditions
- Simulate SL fill during cancel+new (Webull/Robinhood)
- Simulate concurrent software exit + broker SL trigger
- Simulate API timeout during modify (fallback to cancel+new)
- Simulate broker disconnect during escalation

### 13.3 Edge Cases
- Position with qty=1 (can't partially exit + maintain SL)
- Very rapid price movement (debounce validation)
- Bot restart with active broker SL orders
- Channel broker switch mid-position
- Multiple channels routing to same broker with overlapping symbols

---

## 14. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Double-sell (software + broker SL) | Medium | Critical (2x loss) | Cancel broker SL before software exit + Exit Order Arbiter |
| Orphan SL after position closed | Medium | High (unexpected exit later) | Reconciliation on startup + fill detection |
| API rate limit violation | Medium | Medium (temporary block) | Per-broker debouncing + rate limit manager |
| Broker API down during escalation | Low | Medium (stale SL) | Software-side exits remain active as fallback |
| Options SL rejected by broker | Medium | Low (falls back to software) | Capability detection + graceful fallback |
| DAY stops expire overnight (India) | High for ZER/DHAN | High (gap down unprotected) | Pre-market re-placement cron job |

---

## 15. Success Criteria

1. Every open position has a corresponding broker-side SL order (where supported)
2. SL price at broker is always within 1 debounce cycle of the risk engine's calculated level
3. Zero double-sells across all exit scenarios
4. Zero orphan SL orders after positions close
5. Bot restart recovers all broker SL state within 30 seconds
6. UI shows real-time broker SL status for every monitored position
7. Fallback to software-only exits works seamlessly for unsupported brokers/options
