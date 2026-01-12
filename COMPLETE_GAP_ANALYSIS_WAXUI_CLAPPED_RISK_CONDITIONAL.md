# 🔍 Complete Gap Analysis: WaxUI, C1apped, Risk Management & Conditional Orders

## Industry-Standard Implementation Plan for BotifyTrades

---

## EXECUTIVE SUMMARY

| Component | Current State | Gaps Found | Priority | Breaking Risk |
|-----------|---------------|------------|----------|---------------|
| **WaxUI Parsing** | Entry/Trim/Close only | 7 major gaps | P0 | Low |
| **C1apped/TRADE IDEA** | Basic parsing | 6 major gaps | P0 | Medium |
| **Risk Management** | Settings stored, not enforced | 9 major gaps | P0 | Medium |
| **Conditional Orders** | Basic monitoring | 5 major gaps | P1 | Medium |
| **Trailing Stop** | Column exists, not executed | 4 major gaps | P0 | Medium |

---

## 1. WAXUI SIGNAL FORMAT - COMPLETE GAP ANALYSIS

### Current WaxUI Parsing (What Works)

| Pattern | Status | Example |
|---------|--------|---------|
| Entry | ✅ Works | `SPX here 12/05 6880C Avg. 4.00` |
| Trim | ⚠️ Partial | `Trim SPX here` (no profit % extracted) |
| Close | ✅ Works | `Closed SPX here` |

### WaxUI Gaps Identified (From Screenshot)

| Gap | Signal Format | Current Handling | Fix Required |
|-----|---------------|------------------|--------------|
| **Gap 1: Profit Ladder** | `4.00 - 5.50 ✓ 38%` | ❌ Not parsed | Extract entry, current, profit % |
| **Gap 2: Trim with %** | `Trim SPX here 4.00 - 4.80 ✓ 20%` | ❌ Only ticker | Extract trim %, new price |
| **Gap 3: More/Update** | `More SPX here 4.00 - 5.50 ✓ 38%` | ❌ Not detected | Add "More" pattern |
| **Gap 4: Hold States** | `Holding most.`, `Holding 1/2!`, `Holding runners only.` | ❌ Not parsed | Track position % remaining |
| **Gap 5: Trail Stops** | `Trail stops set @B/E` | ❌ Not detected | Set trailing stop to break-even |
| **Gap 6: Entry Linking** | Updates don't link to entry | ❌ No registry | WaxUI Entry Registry by ticker+expiry |
| **Gap 7: LOTTO Tag** | `@waxui LOTTO` | ⚠️ Partial | Flag as high-risk lotto play |

### WaxUI Patterns to Add

```python
# File: src/selfbot_webull.py (add after existing WAXUI patterns ~line 1369)

# Gap 1 & 2: Profit ladder with percentage
# Matches: "4.00 - 5.50 ✓ 38%" or "4.00 - 4.80 ✓ 20%"
WAXUI_PROFIT_LADDER_PATTERN = r'(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*[✓✔️☑]?\s*(\d+)%'

# Gap 3: "More" update pattern
# Matches: "More SPX here" with profit ladder
WAXUI_MORE_PATTERN = r'[Mm]ore\s+([A-Za-z]+)\s+here'

# Gap 4: Holding states
WAXUI_HOLDING_PATTERNS = {
    'holding_most': r'[Hh]olding\s+most',
    'holding_majority': r'[Hh]olding\s+majority',
    'holding_half': r'[Hh]olding\s+1/2|[Hh]olding\s+half',
    'holding_runners': r'[Hh]olding\s+runners\s+only',
}

# Gap 5: Trail stops
# Matches: "Trail stops set @B/E" or "Trail stops @breakeven"
WAXUI_TRAIL_STOPS_PATTERN = r'[Tt]rail\s*stops?\s+(?:set\s+)?@\s*([Bb]/[Ee]|[Bb]reak\s*even|[0-9.]+)'

# Gap 7: LOTTO tag detection
WAXUI_LOTTO_PATTERN = r'LOTTO|[Ll]otto'
```

### WaxUI Entry Registry (New)

```python
# File: src/services/waxui_entry_registry.py (NEW FILE)

"""
WaxUI Entry Registry - Links updates to original entries.

Tracks active WaxUI positions to enable:
- Update signals to reference correct position
- Trim percentages to calculate quantities
- Trail stops to use correct entry price for B/E
"""

from typing import Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field


@dataclass
class WaxUIEntry:
    ticker: str
    expiry: str
    strike: float
    opt_type: str
    entry_price: float
    quantity: int
    channel_id: str
    signal_instance_id: Optional[int] = None
    current_price: Optional[float] = None
    profit_pct: float = 0.0
    holding_state: str = 'full'  # full, most, majority, half, runners
    trailing_stop_enabled: bool = False
    trailing_stop_price: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.now)


class WaxUIEntryRegistry:
    """Registry for active WaxUI positions."""
    
    def __init__(self):
        self._entries: Dict[str, WaxUIEntry] = {}  # key = ticker_expiry_strike
        self._ttl_hours = 48  # Auto-expire after 48 hours
    
    def _make_key(self, ticker: str, expiry: str = None, strike: float = None) -> str:
        """Create lookup key. Expiry/strike optional for fuzzy matching."""
        if expiry and strike:
            return f"{ticker}_{expiry}_{strike}"
        return ticker  # Fallback to ticker-only for updates
    
    def register_entry(self, entry: WaxUIEntry) -> str:
        """Register a new WaxUI entry."""
        key = self._make_key(entry.ticker, entry.expiry, entry.strike)
        self._entries[key] = entry
        self._cleanup_expired()
        return key
    
    def find_by_ticker(self, ticker: str) -> Optional[WaxUIEntry]:
        """Find most recent entry by ticker (for updates without expiry/strike)."""
        matches = [e for k, e in self._entries.items() if e.ticker.upper() == ticker.upper()]
        if matches:
            return max(matches, key=lambda e: e.created_at)
        return None
    
    def update_holding_state(self, ticker: str, state: str, current_price: float = None, profit_pct: float = None):
        """Update holding state from trim/more signals."""
        entry = self.find_by_ticker(ticker)
        if entry:
            entry.holding_state = state
            if current_price:
                entry.current_price = current_price
            if profit_pct:
                entry.profit_pct = profit_pct
    
    def set_trailing_stop(self, ticker: str, price: float = None, at_breakeven: bool = False):
        """Set trailing stop. If at_breakeven, use entry price."""
        entry = self.find_by_ticker(ticker)
        if entry:
            entry.trailing_stop_enabled = True
            if at_breakeven:
                entry.trailing_stop_price = entry.entry_price
            elif price:
                entry.trailing_stop_price = price
    
    def close_entry(self, ticker: str) -> Optional[WaxUIEntry]:
        """Mark entry as closed and return it."""
        entry = self.find_by_ticker(ticker)
        if entry:
            key = self._make_key(entry.ticker, entry.expiry, entry.strike)
            del self._entries[key]
            return entry
        return None
    
    def _cleanup_expired(self):
        """Remove entries older than TTL."""
        cutoff = datetime.now() - timedelta(hours=self._ttl_hours)
        expired = [k for k, e in self._entries.items() if e.created_at < cutoff]
        for k in expired:
            del self._entries[k]


# Global instance
waxui_registry = WaxUIEntryRegistry()
```

### WaxUI Parser Updates (File: src/selfbot_webull.py)

```python
# Add to WAXUI parsing section (~line 4067)

def parse_waxui_signal(text: str, channel_id: str) -> Optional[Dict]:
    """
    Complete WaxUI signal parser with update linking.
    
    Handles:
    - Entry: "SPX here 12/05 6880C Avg. 4.00"
    - Trim: "Trim SPX here 4.00 - 4.80 ✓ 20% Holding most."
    - More: "More SPX here 4.00 - 5.50 ✓ 38%"
    - Hold: "Holding runners only."
    - Trail: "Trail stops set @B/E"
    - Close: "Closed SPX here"
    """
    from src.services.waxui_entry_registry import waxui_registry, WaxUIEntry
    
    result = {
        'type': 'waxui',
        'action': None,
        'symbol': None,
        'entry_price': None,
        'current_price': None,
        'profit_pct': None,
        'holding_state': None,
        'trailing_stop': None,
    }
    
    # Check for LOTTO tag
    is_lotto = bool(re.search(WAXUI_LOTTO_PATTERN, text))
    result['is_lotto'] = is_lotto
    
    # 1. Check for ENTRY
    m = WAXUI_ENTRY_REGEX.search(text)
    if m:
        symbol, month, day, strike, opt_type, price = m.groups()
        result['action'] = 'BTO'
        result['symbol'] = symbol.upper()
        result['expiry'] = f"{month}/{day}"
        result['strike'] = float(strike)
        result['opt_type'] = opt_type.upper()
        result['entry_price'] = float(price.lstrip('.'))
        
        # Register in WaxUI registry
        entry = WaxUIEntry(
            ticker=result['symbol'],
            expiry=result['expiry'],
            strike=result['strike'],
            opt_type=result['opt_type'],
            entry_price=result['entry_price'],
            quantity=0,  # Will be calculated
            channel_id=channel_id
        )
        waxui_registry.register_entry(entry)
        return result
    
    # 2. Check for CLOSE
    m = WAXUI_CLOSE_REGEX.search(text)
    if m:
        symbol = m.group(1).upper()
        result['action'] = 'STC'
        result['symbol'] = symbol
        result['exit_type'] = 'close'
        
        # Get entry from registry for context
        entry = waxui_registry.close_entry(symbol)
        if entry:
            result['signal_instance_id'] = entry.signal_instance_id
        return result
    
    # 3. Check for TRIM
    m = WAXUI_TRIM_REGEX.search(text)
    if m:
        symbol = m.group(1).upper()
        result['action'] = 'TRIM'
        result['symbol'] = symbol
        
        # Extract profit ladder if present
        ladder = re.search(WAXUI_PROFIT_LADDER_PATTERN, text)
        if ladder:
            result['entry_price'] = float(ladder.group(1))
            result['current_price'] = float(ladder.group(2))
            result['profit_pct'] = float(ladder.group(3))
        
        # Check holding state
        for state, pattern in WAXUI_HOLDING_PATTERNS.items():
            if re.search(pattern, text):
                result['holding_state'] = state
                waxui_registry.update_holding_state(
                    symbol, state, 
                    result.get('current_price'),
                    result.get('profit_pct')
                )
                break
        
        return result
    
    # 4. Check for MORE (update)
    m = re.search(WAXUI_MORE_PATTERN, text)
    if m:
        symbol = m.group(1).upper()
        result['action'] = 'UPDATE'
        result['symbol'] = symbol
        
        # Extract profit ladder
        ladder = re.search(WAXUI_PROFIT_LADDER_PATTERN, text)
        if ladder:
            result['entry_price'] = float(ladder.group(1))
            result['current_price'] = float(ladder.group(2))
            result['profit_pct'] = float(ladder.group(3))
        
        # Check holding state
        for state, pattern in WAXUI_HOLDING_PATTERNS.items():
            if re.search(pattern, text):
                result['holding_state'] = state
                waxui_registry.update_holding_state(
                    symbol, state,
                    result.get('current_price'),
                    result.get('profit_pct')
                )
                break
        
        return result
    
    # 5. Check for TRAIL STOPS
    m = re.search(WAXUI_TRAIL_STOPS_PATTERN, text)
    if m:
        trail_value = m.group(1)
        
        # Find ticker in preceding text
        ticker_match = re.search(r'([A-Z]{1,5})', text)
        symbol = ticker_match.group(1) if ticker_match else None
        
        result['action'] = 'TRAIL_STOP'
        result['symbol'] = symbol
        
        if 'B/E' in trail_value.upper() or 'BREAK' in trail_value.upper():
            result['trailing_stop'] = 'breakeven'
            if symbol:
                waxui_registry.set_trailing_stop(symbol, at_breakeven=True)
        else:
            try:
                result['trailing_stop'] = float(trail_value)
                if symbol:
                    waxui_registry.set_trailing_stop(symbol, price=float(trail_value))
            except:
                pass
        
        return result
    
    # 6. Check for standalone holding state (no action word)
    for state, pattern in WAXUI_HOLDING_PATTERNS.items():
        if re.search(pattern, text):
            # Try to find ticker
            ticker_match = re.search(r'([A-Z]{2,5})', text)
            if ticker_match:
                symbol = ticker_match.group(1)
                result['action'] = 'HOLD_UPDATE'
                result['symbol'] = symbol
                result['holding_state'] = state
                
                # Extract profit ladder if present
                ladder = re.search(WAXUI_PROFIT_LADDER_PATTERN, text)
                if ladder:
                    result['entry_price'] = float(ladder.group(1))
                    result['current_price'] = float(ladder.group(2))
                    result['profit_pct'] = float(ladder.group(3))
                
                waxui_registry.update_holding_state(symbol, state)
                return result
    
    return None
```

---

## 2. C1APPED/TRADE IDEA - COMPLETE GAP ANALYSIS

### Current TRADE IDEA Handling (What Works)

| Feature | Status |
|---------|--------|
| Parse entry price | ✅ Works |
| Parse SL price | ✅ Works |
| Parse PT levels | ✅ Works |
| Strikethrough detection | ✅ Fixed recently |
| Store in signal_instances | ✅ Works |

### C1apped Gaps Identified

| Gap | Description | Impact | Priority |
|-----|-------------|--------|----------|
| **Gap 1: No Order ID Tracking** | Don't store broker order IDs | Can't modify SL orders | P0 |
| **Gap 2: No SL Modification** | SL changes in signal aren't sent to broker | Users miss updates | P0 |
| **Gap 3: No Debouncing** | Rapid SL updates can flood broker API | Rate limit errors | P0 |
| **Gap 4: No Exit Arbiter** | Signal and risk settings can conflict | Unexpected exits | P0 |
| **Gap 5: No Hybrid Mode** | Can't use both signal SL and trailing stop | Limited flexibility | P1 |
| **Gap 6: No Exit Signal Detection** | "All out", "Closed" not parsed | Manual close needed | P0 |

### C1apped Fixes Required

#### Fix 1: Add Order ID Columns (Database)

```python
# File: gui_app/database.py - Add to signal_instances table

# Already covered in Phase 1 schema:
# - sl_order_id TEXT
# - pt_order_ids TEXT (JSON array)
# - current_sl_price REAL
# - remaining_qty INTEGER
# - exit_strategy_mode TEXT
# - broker TEXT
```

#### Fix 2: SignalExitManager Integration

```python
# File: src/selfbot_webull.py - In TRADE IDEA handling (~line 8180)

# After parsing TRADE IDEA signal:
if is_trade_idea_signal(combined_content):
    trade_idea = parse_trade_idea(combined_content)
    if trade_idea:
        # Check if this is an UPDATE (existing position)
        existing_instance = get_open_signal_instance_by_fingerprint(fingerprint)
        
        if existing_instance:
            # This is an UPDATE - handle SL/PT changes
            old_sl = existing_instance.get('stop_loss')
            new_sl = trade_idea.get('stop_loss')
            
            if new_sl and old_sl and new_sl != old_sl:
                # Get exit strategy mode for this channel
                exit_strategy_mode = channel_info.get('exit_strategy_mode', 'signal')
                
                if exit_strategy_mode in ['signal', 'hybrid']:
                    # Route through ExitOrderArbiter
                    from src.services.exit_order_arbiter import exit_order_arbiter
                    from src.services.signal_exit_manager import signal_exit_manager
                    
                    arbiter_result = await exit_order_arbiter.request_sl_update(
                        signal_instance_id=existing_instance['id'],
                        source='signal',
                        new_sl_price=new_sl,
                        current_sl_price=old_sl,
                        exit_strategy_mode=exit_strategy_mode
                    )
                    
                    if arbiter_result['approved']:
                        sl_result = await signal_exit_manager.handle_sl_update(
                            signal_instance_id=existing_instance['id'],
                            new_sl_price=new_sl,
                            exit_strategy_mode=exit_strategy_mode
                        )
                        print(f"[TRADE IDEA] SL updated: ${old_sl} -> ${new_sl} ({sl_result.get('action')})")
        else:
            # This is a NEW ENTRY
            # ... existing entry logic ...
            
            # After placing order, register with SignalExitManager
            if get_feature_flag('enable_signal_exit_manager'):
                entry_result = await signal_exit_manager.handle_new_entry(
                    signal_instance_id=instance_id,
                    broker=broker_name,
                    ticker=ticker,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    profit_targets=profit_targets,
                    quantity=qty,
                    exit_strategy_mode=channel_info.get('exit_strategy_mode', 'signal')
                )
```

#### Fix 3: Exit Signal Detection

```python
# File: src/signals/parser.py - Add exit detection

TRADE_IDEA_EXIT_PATTERNS = [
    r'all\s*out',
    r'closed?\s+(?:this\s+)?(?:trade|position)',
    r'sold?\s+(?:all|everything)',
    r'exited?\s+(?:this\s+)?(?:trade|position)',
    r'stopped?\s+out',
    r'took\s+(?:the\s+)?loss',
]

def is_trade_idea_exit(text: str) -> bool:
    """Check if text indicates an exit signal."""
    for pattern in TRADE_IDEA_EXIT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False

def parse_trade_idea_exit(text: str) -> Optional[Dict]:
    """Parse exit signal to extract ticker and exit type."""
    # Extract ticker
    ticker_match = re.search(r'\$?([A-Z]{1,5})\b', text)
    if not ticker_match:
        return None
    
    ticker = ticker_match.group(1)
    
    # Determine exit type
    if re.search(r'stopped?\s*out|took.*loss', text, re.IGNORECASE):
        exit_type = 'stop_loss'
    elif re.search(r'target|profit', text, re.IGNORECASE):
        exit_type = 'profit_target'
    else:
        exit_type = 'manual'
    
    return {
        'ticker': ticker,
        'exit_type': exit_type,
        'action': 'STC',
        'is_exit': True
    }
```

---

## 3. RISK MANAGEMENT SETTINGS - COMPLETE GAP ANALYSIS

### Current Risk Settings (What Exists)

| Setting | Table | Column | Status |
|---------|-------|--------|--------|
| Stop Loss % | channels | stop_loss_pct | ✅ Stored |
| Trailing Stop % | channels | trailing_stop_pct | ✅ Stored |
| Trailing Activation % | channels | trailing_activation_pct | ✅ Stored |
| Profit Target 1-4 | channels | profit_target_*_pct | ✅ Stored |
| PT Trim Quantities | channels | profit_target_qty_* | ✅ Stored |
| Exit Strategy Mode | channels | exit_strategy_mode | ✅ Stored |
| Global Risk Settings | risk_management_settings | * | ✅ Stored |

### Risk Management Gaps Identified

| Gap | Description | Impact | Priority |
|-----|-------------|--------|----------|
| **Gap 1: Stop Loss Type** | Only % supported, not fixed or from_signal | Limited flexibility | P1 |
| **Gap 2: Trailing Not Enforced** | Settings stored but not executed | Feature doesn't work | P0 |
| **Gap 3: No Daily Loss Limit** | No per-channel or global limit | Unlimited losses | P0 |
| **Gap 4: No Circuit Breaker** | No kill switch | Can't stop in emergency | P0 |
| **Gap 5: No Order Timeout** | Orders can hang indefinitely | Stuck orders | P1 |
| **Gap 6: No Position Limits** | Can open unlimited positions | Over-exposure | P1 |
| **Gap 7: Broker Capability Unknown** | UI shows all options regardless of broker | User confusion | P2 |
| **Gap 8: Exit Mode Not Enforced** | Stored but not respected during execution | Unexpected behavior | P0 |
| **Gap 9: No Risk Event Logging** | No audit trail for risk decisions | No debugging | P1 |

### Risk Management Fixes Required

#### Fix 1: Add Missing Columns

```python
# File: gui_app/database.py - Add to channels table

channel_new_columns = [
    ('stop_loss_type', "TEXT DEFAULT 'percentage'"),  # percentage, fixed, from_signal
    ('stop_loss_fixed', 'REAL DEFAULT NULL'),
    ('max_daily_loss', 'REAL DEFAULT NULL'),
    ('max_positions', 'INTEGER DEFAULT 10'),
    ('order_timeout_minutes', 'INTEGER DEFAULT 5'),
    ('circuit_breaker_enabled', 'INTEGER DEFAULT 1'),
]
```

#### Fix 2: Trailing Stop Execution

```python
# File: src/services/trailing_stop_executor.py (NEW FILE)

"""
Trailing Stop Executor - Actually enforces trailing stop settings.

Current problem: trailing_stop_pct and trailing_activation_pct are stored
but never checked during position lifecycle.

Solution: Monitor positions and update broker SL when trailing conditions met.
"""

import asyncio
from typing import Dict, Optional
from datetime import datetime

class TrailingStopExecutor:
    """
    Executes trailing stop logic for open positions.
    
    Workflow:
    1. Position opens at entry_price
    2. Monitor current_price vs entry_price
    3. When profit >= trailing_activation_pct, activate trailing
    4. Calculate trailing_stop_price = current_price * (1 - trailing_stop_pct/100)
    5. If trailing_stop_price > current_sl, update SL via SignalExitManager
    """
    
    def __init__(self, signal_exit_manager, exit_order_arbiter):
        self.sem = signal_exit_manager
        self.arbiter = exit_order_arbiter
        self._active_trails = {}  # signal_instance_id -> trail state
    
    async def check_and_update(
        self,
        signal_instance_id: int,
        entry_price: float,
        current_price: float,
        current_sl_price: float,
        trailing_activation_pct: float,
        trailing_stop_pct: float,
        exit_strategy_mode: str
    ) -> Optional[Dict]:
        """
        Check if trailing stop should be updated.
        
        Returns update result if SL was modified, None otherwise.
        """
        # Calculate profit percentage
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Check if trailing is activated
        is_activated = signal_instance_id in self._active_trails
        should_activate = profit_pct >= trailing_activation_pct
        
        if not is_activated and should_activate:
            # Activate trailing
            self._active_trails[signal_instance_id] = {
                'activated_at': datetime.now(),
                'activation_price': current_price,
                'highest_price': current_price
            }
            print(f"[TRAILING] Activated for {signal_instance_id} at {profit_pct:.1f}% profit")
        
        if not is_activated and not should_activate:
            # Not yet at activation threshold
            return None
        
        # Update highest price
        trail_state = self._active_trails.get(signal_instance_id, {})
        highest = max(trail_state.get('highest_price', current_price), current_price)
        trail_state['highest_price'] = highest
        self._active_trails[signal_instance_id] = trail_state
        
        # Calculate new trailing stop
        new_trailing_sl = highest * (1 - trailing_stop_pct / 100)
        
        # Only update if new SL is higher (tighter for long)
        if new_trailing_sl > current_sl_price:
            # Request update through arbiter
            arbiter_result = await self.arbiter.request_sl_update(
                signal_instance_id=signal_instance_id,
                source='trailing',
                new_sl_price=new_trailing_sl,
                current_sl_price=current_sl_price,
                exit_strategy_mode=exit_strategy_mode
            )
            
            if arbiter_result['approved']:
                # Execute the update
                result = await self.sem.handle_sl_update(
                    signal_instance_id=signal_instance_id,
                    new_sl_price=new_trailing_sl,
                    exit_strategy_mode=exit_strategy_mode,
                    source='trailing'
                )
                print(f"[TRAILING] SL raised: ${current_sl_price:.2f} -> ${new_trailing_sl:.2f}")
                return result
        
        return None
    
    def deactivate(self, signal_instance_id: int):
        """Remove trailing tracking for a closed position."""
        if signal_instance_id in self._active_trails:
            del self._active_trails[signal_instance_id]


# Global instance (initialize after SignalExitManager)
trailing_executor = None
```

#### Fix 3: Circuit Breaker & Daily Loss Limit

See Phase 4 in INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md for complete CircuitBreaker implementation.

---

## 4. CONDITIONAL ORDERS - COMPLETE GAP ANALYSIS

### Current Conditional Order System (What Works)

| Feature | Status |
|---------|--------|
| Create conditional order | ✅ Works |
| Price monitoring (Finnhub/Broker) | ✅ Works |
| Trigger on price condition | ✅ Works |
| Execute order on trigger | ✅ Works |
| Three-tier fallback | ✅ Works |

### Conditional Order Gaps Identified

| Gap | Description | Impact | Priority |
|-----|-------------|--------|----------|
| **Gap 1: No Risk Gate** | Bypasses circuit breaker | Trades during halt | P0 |
| **Gap 2: No Daily Limit Check** | Bypasses daily loss limit | Over-loss | P0 |
| **Gap 3: No Order Timeout/Expiry** | Stale triggers never expire | Outdated executions | P1 |
| **Gap 4: No Hybrid Exit** | Doesn't coordinate with ExitArbiter | Conflicting exits | P1 |
| **Gap 5: No Order State Tracking** | No broker order ID storage | Can't modify orders | P1 |

### Conditional Order Fixes Required

```python
# File: src/services/conditional_order_service.py - Add to execute_order method

async def execute_order(self, order: ConditionalOrder) -> bool:
    """Execute a triggered conditional order with risk checks."""
    
    # NEW: Check circuit breaker first
    from src.services.circuit_breaker import circuit_breaker
    if circuit_breaker.is_halted:
        print(f"[CONDITIONAL] ❌ Order blocked: Trading halted")
        await self._update_status(order.id, OrderStatus.CANCELED, 'circuit_breaker_halt')
        return False
    
    # NEW: Check daily loss limit
    trade_check = await circuit_breaker.check_trade_allowed(
        channel_id=order.channel_id,
        trade_value=order.quantity * order.limit_price if order.limit_price else 0
    )
    
    if not trade_check['allowed']:
        print(f"[CONDITIONAL] ❌ Order blocked: {trade_check['reason']}")
        await self._update_status(order.id, OrderStatus.CANCELED, trade_check['reason'])
        return False
    
    # NEW: Route through SignalExitManager if enabled
    if get_feature_flag('enable_signal_exit_manager'):
        from src.services.signal_exit_manager import signal_exit_manager
        
        result = await signal_exit_manager.handle_new_entry(
            signal_instance_id=None,  # Will be created
            broker=order.broker,
            ticker=order.symbol,
            entry_price=order.limit_price or order.trigger_price,
            stop_loss=order.stop_loss,
            profit_targets=[order.profit_target] if order.profit_target else [],
            quantity=order.quantity,
            exit_strategy_mode=order.exit_strategy_mode or 'signal'
        )
        
        if result['success']:
            order.broker_order_id = result['entry_order_id']
            await self._update_status(order.id, OrderStatus.TRACKING)
            return True
    
    # Fallback to direct broker execution
    # ... existing code ...
```

---

## 5. TRAILING STOP ACTIVATION - COMPLETE GAP ANALYSIS

### Current Trailing Stop State

| Component | Status |
|-----------|--------|
| trailing_stop_pct column | ✅ Exists in channels |
| trailing_activation_pct column | ✅ Exists in channels |
| UI to set values | ✅ Works |
| API to save values | ✅ Works |
| Actual execution | ❌ NOT IMPLEMENTED |

### Trailing Stop Gaps

| Gap | Description | Fix Required |
|-----|-------------|--------------|
| **Gap 1: No Price Monitoring** | Don't track current price vs entry | Add price feed integration |
| **Gap 2: No Activation Check** | Never check if activation % reached | Add check in monitoring loop |
| **Gap 3: No SL Update Logic** | Never calculate trailing SL | Add TrailingStopExecutor |
| **Gap 4: No Broker SL Modification** | Never send SL update to broker | Route through SignalExitManager |

### Complete Trailing Stop Implementation

```python
# File: src/services/position_monitor.py (NEW FILE)

"""
Position Monitor - Tracks open positions for trailing stops and risk management.

Runs as background task, polling positions every 5 seconds.
"""

import asyncio
from typing import Dict, List
from datetime import datetime


class PositionMonitor:
    """
    Monitors open positions for:
    1. Trailing stop activation and updates
    2. Profit target hits
    3. Stop loss proximity warnings
    """
    
    def __init__(self, db_path: str = 'bot_data.db'):
        self.db_path = db_path
        self._running = False
        self._interval_seconds = 5
    
    async def start(self):
        """Start position monitoring loop."""
        self._running = True
        print("[POSITION MONITOR] Started")
        
        while self._running:
            try:
                await self._check_all_positions()
            except Exception as e:
                print(f"[POSITION MONITOR] Error: {e}")
            
            await asyncio.sleep(self._interval_seconds)
    
    async def stop(self):
        """Stop monitoring."""
        self._running = False
        print("[POSITION MONITOR] Stopped")
    
    async def _check_all_positions(self):
        """Check all open positions for trailing stop updates."""
        from gui_app.database import get_open_signal_instances
        from src.services.trailing_stop_executor import trailing_executor
        from src.services.price_service import get_current_price
        
        positions = get_open_signal_instances()
        
        for pos in positions:
            # Skip if no trailing stop configured
            if not pos.get('trailing_stop_pct') or pos.get('trailing_stop_pct') <= 0:
                continue
            
            # Get current price
            ticker = pos.get('ticker')
            current_price = await get_current_price(ticker)
            
            if not current_price:
                continue
            
            # Get channel settings
            channel_id = pos.get('channel_id')
            channel_info = get_channel_info(channel_id)
            
            trailing_activation_pct = pos.get('trailing_activation_pct') or channel_info.get('trailing_activation_pct') or 5.0
            trailing_stop_pct = pos.get('trailing_stop_pct') or channel_info.get('trailing_stop_pct') or 3.0
            exit_strategy_mode = pos.get('exit_strategy_mode') or channel_info.get('exit_strategy_mode') or 'risk'
            
            # Only apply trailing in risk or hybrid mode
            if exit_strategy_mode not in ['risk', 'hybrid']:
                continue
            
            # Check and update trailing stop
            await trailing_executor.check_and_update(
                signal_instance_id=pos['id'],
                entry_price=pos['entry_price'],
                current_price=current_price,
                current_sl_price=pos.get('current_sl_price') or pos.get('stop_loss'),
                trailing_activation_pct=trailing_activation_pct,
                trailing_stop_pct=trailing_stop_pct,
                exit_strategy_mode=exit_strategy_mode
            )


# Global instance
position_monitor = PositionMonitor()
```

---

## FILE REFERENCE MATRIX

### New Files to Create

| File | Description | Priority |
|------|-------------|----------|
| `src/services/waxui_entry_registry.py` | WaxUI position tracking | P0 |
| `src/services/signal_exit_manager.py` | Order lifecycle manager | P0 |
| `src/services/exit_order_arbiter.py` | Exit precedence rules | P0 |
| `src/services/circuit_breaker.py` | Kill switch & limits | P0 |
| `src/services/trailing_stop_executor.py` | Trailing stop logic | P0 |
| `src/services/position_monitor.py` | Position monitoring loop | P0 |
| `src/services/broker_integration.py` | Broker registry | P1 |
| `src/services/event_bus.py` | Event pub/sub | P2 |

### Files to Modify

| File | Changes | Priority |
|------|---------|----------|
| `src/selfbot_webull.py` | Add WaxUI patterns, SignalExitManager integration | P0 |
| `src/signals/parser.py` | Add exit signal detection | P0 |
| `src/services/conditional_order_service.py` | Add risk gate checks | P1 |
| `gui_app/database.py` | Add new columns and tables | P0 |
| `gui_app/routes.py` | Add risk management endpoints | P1 |

---

## IMPLEMENTATION ORDER

### Phase 1: Database Schema (Day 1)
1. Add columns to channels table
2. Add columns to signal_instances table
3. Create order_states table
4. Create risk_events table
5. Create broker_capabilities table
6. Create global_risk_settings table
7. Create feature_flags table

### Phase 2: Core Services (Days 2-3)
1. Implement CircuitBreaker (safety first)
2. Implement SignalExitManager
3. Implement ExitOrderArbiter
4. Implement TrailingStopExecutor
5. Implement PositionMonitor

### Phase 3: WaxUI Enhancement (Day 4)
1. Add new WaxUI patterns
2. Create WaxUIEntryRegistry
3. Implement parse_waxui_signal
4. Wire into selfbot_webull.py

### Phase 4: C1apped/TRADE IDEA Integration (Day 5)
1. Add exit signal detection
2. Integrate SignalExitManager into TRADE IDEA flow
3. Implement SL update propagation
4. Add debouncing

### Phase 5: Conditional Orders V2 (Day 6)
1. Add risk gate checks
2. Add timeout/expiry
3. Integrate with SignalExitManager
4. Add order state tracking

### Phase 6: Testing & Rollout (Days 7-8)
1. Paper trading validation
2. Enable feature flags one by one
3. Monitor logs for issues
4. Gradual live rollout

---

## FEATURE FLAGS FOR SAFE ROLLOUT

```python
# Enable one at a time, test thoroughly before next

FEATURE_FLAGS = {
    'enable_circuit_breaker': True,      # Safe, just adds checks
    'enable_signal_exit_manager': False, # Medium risk
    'enable_exit_arbiter': False,        # Medium risk
    'enable_waxui_v2': False,            # Low risk
    'enable_trailing_executor': False,   # Medium risk
    'enable_conditional_v2': False,      # Medium risk
}
```

---

*Generated: January 12, 2026*
*Scope: Complete Gap Analysis for WaxUI, C1apped, Risk Management, Conditional Orders*
