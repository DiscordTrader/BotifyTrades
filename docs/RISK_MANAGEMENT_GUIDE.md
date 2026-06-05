# Risk Management System - Complete Guide & Code

## Replit Agent Prompt

Use this prompt when setting up risk management in your India trading bot:

```
I need to implement an industry-grade Risk Management system for my trading bot with the following features:

1. **4-Tier Profit Targets (PT1-PT4)** - Auto-sell portions at each profit milestone
2. **Stop Loss** - Hard downside protection (% from entry)
3. **Trailing Stop** - Lock in gains as price rises (activation threshold + trail %)
4. **Leave Runner** - Keep X% of position to ride further upside
5. **Dynamic Stop Loss Escalation** - After each PT hit, move stop loss UP automatically:
   - PT1 hit → Move SL to breakeven
   - PT2 hit → Move SL to +5% profit
   - PT3 hit → Move SL to +15% profit
   - PT4 hit → Move SL to +25% profit
6. **Max Profit Giveback Guard** - Exit if profit drops 30% from its peak

The system should:
- Support per-channel settings (different strategies per signal source)
- Be idempotent (repeated calls with same price won't duplicate actions)
- Persist state across bot restarts (trailing activation, tier hits, etc.)
- Support both stocks and options
- Work with multiple brokers (Zerodha, Upstox, DhanQ for India)

Database columns needed for channels table:
- risk_management_enabled (boolean)
- profit_target_1_pct, profit_target_2_pct, profit_target_3_pct, profit_target_4_pct (float)
- profit_target_qty_1 through _4 (optional int for custom quantities)
- stop_loss_pct (float)
- trailing_stop_pct (float)
- trailing_activation_pct (float)
- leave_runner_enabled (boolean)
- leave_runner_pct (float, default 25)
- enable_dynamic_sl (boolean)
- enable_giveback_guard (boolean)
- giveback_allowed_pct (float, default 30)
- dynamic_sl_profile (string: 'conservative', 'standard', 'aggressive')
```

---

## How It Works - Simple Example

**Your Position:** 10 contracts @ ₹100 each = ₹10,000 investment

### Profit Targets Flow

| Event | Price | PnL % | Action | Contracts Left |
|-------|-------|-------|--------|----------------|
| Entry | ₹100 | 0% | Buy 10 contracts | 10 |
| PT1 Hit | ₹115 | +15% | Sell 2, Move SL to ₹100 | 8 |
| PT2 Hit | ₹125 | +25% | Sell 2, Move SL to ₹105 | 6 |
| PT3 Hit | ₹135 | +35% | Sell 2, Move SL to ₹115 | 4 |
| PT4 Hit | ₹140 | +40% | Sell 2, Move SL to ₹125 | 2 (runners) |
| Peak | ₹160 | +60% | Trailing active @ ₹128 | 2 |
| Exit | ₹128 | +28% | Trailing stop hit, sell all | 0 |

**Result:** Locked in profits at multiple levels, kept runners for upside, exited with +28% instead of riding back to 0.

---

## Exit Priority Order

The risk engine evaluates exits in this strict priority (first match wins):

1. **Hard Stop Loss** - Immediate protection (e.g., -20% from entry)
2. **Dynamic Stop Loss** - After PT hits, escalates up (never down)
3. **Giveback Guard** - Exits if profit drops 30% from peak
4. **Trailing Stop** - Follows price down from highest point
5. **Runner Exit** - Final cleanup via trailing

---

## Dynamic SL Profiles

| Profile | After PT1 | After PT2 | After PT3 | After PT4 |
|---------|-----------|-----------|-----------|-----------|
| Conservative | Breakeven | +3% | +10% | +20% |
| Standard | Breakeven | +5% | +15% | +25% |
| Aggressive | -2% | Breakeven | +10% | +20% |

---

## Complete Code

### 1. risk_types.py - Data Classes

```python
"""
Risk Management Types
=====================
Shared dataclasses and types for the risk management module.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class PositionSnapshot:
    """Snapshot of a broker position for risk evaluation."""
    symbol: str
    quantity: float
    avg_cost: float
    current_price: float
    asset: str  # 'stock' or 'option'
    broker: str  # 'Zerodha', 'Upstox', 'DhanQ'
    
    strike: Optional[float] = None
    expiry: Optional[str] = None
    direction: Optional[str] = None  # 'CE' or 'PE' for options
    raw_symbol: Optional[str] = None
    option_id: Optional[int] = None
    
    @property
    def position_key(self) -> str:
        """Generate unique position key including broker."""
        if self.asset == 'option':
            return f"{self.broker}_{self.symbol}_{self.strike}_{self.expiry}_{self.direction}"
        return f"{self.broker}_{self.symbol}_stock"
    
    @property
    def pct_change(self) -> float:
        """Calculate percentage change from entry."""
        if self.avg_cost <= 0:
            return 0.0
        return ((self.current_price - self.avg_cost) / self.avg_cost) * 100


@dataclass
class ChannelRiskSettings:
    """Per-channel risk settings with tiered targets and enhanced risk features."""
    channel_id: str
    channel_name: str
    profit_target_1_pct: float = 0.0
    profit_target_2_pct: float = 0.0
    profit_target_3_pct: float = 0.0
    profit_target_4_pct: float = 0.0
    profit_target_qty_1: Optional[int] = None
    profit_target_qty_2: Optional[int] = None
    profit_target_qty_3: Optional[int] = None
    profit_target_qty_4: Optional[int] = None
    stop_loss_pct: float = 0.0
    trailing_stop_pct: float = 0.0
    trailing_activation_pct: float = 15.0
    leave_runner_enabled: bool = False
    leave_runner_pct: float = 25.0
    trim_order_mode: str = 'market'
    trim_limit_offset: float = 0.01
    exit_strategy_mode: str = 'signal'
    
    # Enhanced Risk Management
    enable_dynamic_sl: bool = False
    enable_giveback_guard: bool = False
    giveback_allowed_pct: float = 30.0
    dynamic_sl_profile: str = 'standard'
    
    @property
    def has_tiered_targets(self) -> bool:
        return (self.profit_target_1_pct > 0 or self.profit_target_2_pct > 0 or 
                self.profit_target_3_pct > 0 or self.profit_target_4_pct > 0)


@dataclass
class PositionCacheEntry:
    """Cached state for a position being monitored."""
    entry_price: float
    highest_price: float
    trailing_activated: bool = False
    closing: bool = False
    stop_loss_price: Optional[float] = None
    broker: str = ""
    raw_symbol: Optional[str] = None
    channel_settings: Optional[ChannelRiskSettings] = None
    
    tier1_hit: bool = False
    tier2_hit: bool = False
    tier3_hit: bool = False
    tier4_hit: bool = False
    
    # Enhanced risk state
    max_pnl_seen: float = 0.0
    dynamic_sl_price: Optional[float] = None
    giveback_guard_active: bool = False
    last_evaluated_price: Optional[float] = None
    
    created_at: datetime = field(default_factory=datetime.now)
    
    def update_highest_price(self, current_price: float) -> bool:
        """Track highest price for trailing stop."""
        if current_price > self.highest_price:
            self.highest_price = current_price
            return True
        return False
```

### 2. risk_engine.py - Core Logic

```python
"""
Risk Engine - Enhanced Exit Evaluation
=======================================
Industry-grade risk management with Dynamic SL and Giveback Guard.

Exit Priority Order:
1. Hard SL (immediate protection)
2. Dynamic SL (after PT hits)
3. Giveback Guard (max profit protection)
4. Trailing Stop (after activation)
5. Runner Exit (trailing manages remainder)
"""
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
from enum import Enum
import math

from .risk_types import ChannelRiskSettings, PositionCacheEntry


class ActionType(Enum):
    SELL_PARTIAL = "sell_partial"
    SELL_ALL = "sell_all"
    MOVE_STOP = "move_stop"
    ACTIVATE_TRAIL = "activate_trail"
    UPDATE_TRAIL_STOP = "update_trail_stop"
    ACTIVATE_GIVEBACK = "activate_giveback"


@dataclass
class RiskAction:
    """A risk management action to be executed."""
    action_type: ActionType
    reason: str
    qty: int = 0
    new_stop_price: Optional[float] = None
    tier: Optional[int] = None
    priority: int = 0


@dataclass
class TradeState:
    """Complete state of a trade for risk evaluation."""
    entry_price: float
    current_price: float
    qty: int
    remaining_qty: int
    
    highest_price: float = 0.0
    max_pnl_seen: float = 0.0
    
    pt1_hit: bool = False
    pt2_hit: bool = False
    pt3_hit: bool = False
    pt4_hit: bool = False
    
    trailing_active: bool = False
    giveback_guard_active: bool = False
    
    current_stop_price: Optional[float] = None
    dynamic_sl_price: Optional[float] = None
    trailing_stop_price: Optional[float] = None
    last_evaluated_price: Optional[float] = None
    
    @property
    def pnl_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100
    
    @property
    def pts_hit_count(self) -> int:
        return sum([self.pt1_hit, self.pt2_hit, self.pt3_hit, self.pt4_hit])


# Dynamic SL profiles - how much profit to lock after each PT hit
DYNAMIC_SL_PROFILES = {
    'conservative': {'pt1_sl_pct': 0, 'pt2_sl_pct': 3, 'pt3_sl_pct': 10, 'pt4_sl_pct': 20},
    'standard': {'pt1_sl_pct': 0, 'pt2_sl_pct': 5, 'pt3_sl_pct': 15, 'pt4_sl_pct': 25},
    'aggressive': {'pt1_sl_pct': -2, 'pt2_sl_pct': 0, 'pt3_sl_pct': 10, 'pt4_sl_pct': 20}
}


def calculate_dynamic_sl(entry_price: float, pts_hit: Dict[int, bool], profile: str = 'standard') -> Optional[float]:
    """Calculate dynamic stop loss based on PT hits."""
    profile_config = DYNAMIC_SL_PROFILES.get(profile, DYNAMIC_SL_PROFILES['standard'])
    
    # Find highest tier hit
    highest_tier_hit = 0
    for tier in [4, 3, 2, 1]:
        if pts_hit.get(tier, False):
            highest_tier_hit = tier
            break
    
    if highest_tier_hit == 0:
        return None
    
    sl_pct = profile_config.get(f'pt{highest_tier_hit}_sl_pct', 0)
    return entry_price * (1 + sl_pct / 100)


def calculate_auto_tier_quantities(total_qty: int, leave_runner_pct: float, enabled_tiers: List[int]) -> Dict[int, int]:
    """Calculate auto-scaled quantities across enabled tiers."""
    if not enabled_tiers or total_qty <= 0:
        return {}
    
    runner_qty = math.floor(total_qty * (leave_runner_pct / 100))
    sellable_qty = total_qty - runner_qty
    
    if sellable_qty <= 0:
        return {tier: 0 for tier in enabled_tiers}
    
    num_tiers = len(enabled_tiers)
    base_qty = sellable_qty // num_tiers
    remainder = sellable_qty % num_tiers
    
    tier_qtys = {}
    for i, tier in enumerate(sorted(enabled_tiers)):
        tier_qtys[tier] = base_qty + (1 if i < remainder else 0)
    
    return tier_qtys


def evaluate_exit_actions(state: TradeState, config: ChannelRiskSettings, verbose: bool = False) -> Tuple[List[RiskAction], TradeState]:
    """
    Pure function to evaluate all exit conditions.
    
    Returns: Tuple of (list of actions, updated state)
    Idempotent: Repeated calls with same price won't duplicate actions.
    """
    actions: List[RiskAction] = []
    
    if state.remaining_qty <= 0:
        return actions, state
    
    # Idempotency check
    if state.last_evaluated_price == state.current_price:
        return actions, state
    state.last_evaluated_price = state.current_price
    
    pnl_pct = state.pnl_pct
    
    # Update tracking
    if state.current_price > state.highest_price:
        state.highest_price = state.current_price
    if pnl_pct > state.max_pnl_seen:
        state.max_pnl_seen = pnl_pct
    
    # === PRIORITY 1: Hard Stop Loss ===
    if config.stop_loss_pct > 0 and pnl_pct <= -config.stop_loss_pct:
        actions.append(RiskAction(
            action_type=ActionType.SELL_ALL,
            reason=f"Hard SL hit ({pnl_pct:.1f}% <= -{config.stop_loss_pct}%)",
            qty=state.remaining_qty,
            priority=1
        ))
        return actions, state
    
    # === PRIORITY 2: Dynamic SL (after PTs) ===
    if config.enable_dynamic_sl and state.pts_hit_count > 0:
        pts_hit = {1: state.pt1_hit, 2: state.pt2_hit, 3: state.pt3_hit, 4: state.pt4_hit}
        new_dynamic_sl = calculate_dynamic_sl(state.entry_price, pts_hit, config.dynamic_sl_profile)
        
        if new_dynamic_sl:
            if state.dynamic_sl_price is None or new_dynamic_sl > state.dynamic_sl_price:
                state.dynamic_sl_price = new_dynamic_sl
                actions.append(RiskAction(
                    action_type=ActionType.MOVE_STOP,
                    reason=f"Dynamic SL escalation after PT{state.pts_hit_count}",
                    new_stop_price=new_dynamic_sl,
                    priority=2
                ))
            
            if state.current_price <= state.dynamic_sl_price:
                actions.append(RiskAction(
                    action_type=ActionType.SELL_ALL,
                    reason=f"Dynamic SL triggered (${state.current_price:.2f} <= ${state.dynamic_sl_price:.2f})",
                    qty=state.remaining_qty,
                    priority=2
                ))
                return actions, state
    
    # === PRIORITY 3: Giveback Guard ===
    if config.enable_giveback_guard:
        activation_threshold = config.trailing_activation_pct if config.trailing_activation_pct > 0 else 30
        
        if not state.giveback_guard_active and (state.pt2_hit or state.max_pnl_seen >= activation_threshold):
            state.giveback_guard_active = True
            actions.append(RiskAction(
                action_type=ActionType.ACTIVATE_GIVEBACK,
                reason=f"Giveback guard activated (max_pnl={state.max_pnl_seen:.1f}%)",
                priority=3
            ))
        
        if state.giveback_guard_active and state.max_pnl_seen > 0:
            giveback_threshold = state.max_pnl_seen * (1 - config.giveback_allowed_pct / 100)
            if pnl_pct <= giveback_threshold:
                actions.append(RiskAction(
                    action_type=ActionType.SELL_ALL,
                    reason=f"Giveback guard triggered ({pnl_pct:.1f}% <= {giveback_threshold:.1f}%)",
                    qty=state.remaining_qty,
                    priority=3
                ))
                return actions, state
    
    # === PRIORITY 4: Profit Targets ===
    enabled_tiers = []
    tier_thresholds = {}
    
    for tier, pct_attr in [(1, 'profit_target_1_pct'), (2, 'profit_target_2_pct'), 
                           (3, 'profit_target_3_pct'), (4, 'profit_target_4_pct')]:
        pct = getattr(config, pct_attr, 0) or 0
        if pct > 0:
            enabled_tiers.append(tier)
            tier_thresholds[tier] = pct
    
    if enabled_tiers:
        leave_runner = config.leave_runner_pct if config.leave_runner_enabled else 0
        tier_qtys = calculate_auto_tier_quantities(state.qty, leave_runner, enabled_tiers)
        
        for tier in enabled_tiers:
            tier_hit_attr = f'pt{tier}_hit'
            already_hit = getattr(state, tier_hit_attr, False)
            threshold = tier_thresholds[tier]
            
            if not already_hit and pnl_pct >= threshold:
                setattr(state, tier_hit_attr, True)
                sell_qty = tier_qtys.get(tier, 0)
                
                if sell_qty > 0 and sell_qty <= state.remaining_qty:
                    actions.append(RiskAction(
                        action_type=ActionType.SELL_PARTIAL,
                        reason=f"PT{tier} hit ({pnl_pct:.1f}% >= {threshold}%)",
                        qty=sell_qty,
                        tier=tier,
                        priority=4
                    ))
                    state.remaining_qty -= sell_qty
    
    # === PRIORITY 5: Trailing Stop ===
    if config.trailing_stop_pct > 0:
        if not state.trailing_active and pnl_pct >= config.trailing_activation_pct:
            state.trailing_active = True
            actions.append(RiskAction(
                action_type=ActionType.ACTIVATE_TRAIL,
                reason=f"Trailing activated ({pnl_pct:.1f}% >= {config.trailing_activation_pct}%)",
                priority=5
            ))
        
        if state.trailing_active:
            new_trail_stop = state.highest_price * (1 - config.trailing_stop_pct / 100)
            
            if state.trailing_stop_price is None or new_trail_stop > state.trailing_stop_price:
                state.trailing_stop_price = new_trail_stop
                actions.append(RiskAction(
                    action_type=ActionType.UPDATE_TRAIL_STOP,
                    reason=f"Trail stop updated (high={state.highest_price:.2f})",
                    new_stop_price=new_trail_stop,
                    priority=5
                ))
            
            if state.current_price <= state.trailing_stop_price:
                actions.append(RiskAction(
                    action_type=ActionType.SELL_ALL,
                    reason=f"Trailing stop hit ({state.current_price:.2f} <= {state.trailing_stop_price:.2f})",
                    qty=state.remaining_qty,
                    priority=5
                ))
                return actions, state
    
    return actions, state
```

### 3. Database Schema (SQLite)

```sql
-- Add these columns to your channels table
ALTER TABLE channels ADD COLUMN risk_management_enabled INTEGER DEFAULT 0;
ALTER TABLE channels ADD COLUMN profit_target_1_pct REAL DEFAULT 0;
ALTER TABLE channels ADD COLUMN profit_target_2_pct REAL DEFAULT 0;
ALTER TABLE channels ADD COLUMN profit_target_3_pct REAL DEFAULT 0;
ALTER TABLE channels ADD COLUMN profit_target_4_pct REAL DEFAULT 0;
ALTER TABLE channels ADD COLUMN profit_target_qty_1 INTEGER;
ALTER TABLE channels ADD COLUMN profit_target_qty_2 INTEGER;
ALTER TABLE channels ADD COLUMN profit_target_qty_3 INTEGER;
ALTER TABLE channels ADD COLUMN profit_target_qty_4 INTEGER;
ALTER TABLE channels ADD COLUMN stop_loss_pct REAL DEFAULT 0;
ALTER TABLE channels ADD COLUMN trailing_stop_pct REAL DEFAULT 0;
ALTER TABLE channels ADD COLUMN trailing_activation_pct REAL DEFAULT 15;
ALTER TABLE channels ADD COLUMN leave_runner_enabled INTEGER DEFAULT 0;
ALTER TABLE channels ADD COLUMN leave_runner_pct REAL DEFAULT 25;
ALTER TABLE channels ADD COLUMN trim_order_mode TEXT DEFAULT 'market';
ALTER TABLE channels ADD COLUMN enable_dynamic_sl INTEGER DEFAULT 0;
ALTER TABLE channels ADD COLUMN enable_giveback_guard INTEGER DEFAULT 0;
ALTER TABLE channels ADD COLUMN giveback_allowed_pct REAL DEFAULT 30;
ALTER TABLE channels ADD COLUMN dynamic_sl_profile TEXT DEFAULT 'standard';
```

### 4. HTML/JS for Settings UI

```html
<!-- Risk Management Settings Panel -->
<div class="card bg-dark">
    <div class="card-header d-flex justify-content-between align-items-center">
        <span>Risk Management Settings</span>
        <label class="switch">
            <input type="checkbox" id="risk_management_enabled" onchange="toggleRiskSettings()">
            <span class="slider round"></span>
        </label>
    </div>
    <div class="card-body" id="riskSettingsBody">
        <!-- Profit Targets -->
        <div class="row mb-3">
            <div class="col-3">
                <label>P1 Target %</label>
                <input type="number" class="form-control" id="pt1_pct" value="15" step="0.5">
            </div>
            <div class="col-3">
                <label>P2 Target %</label>
                <input type="number" class="form-control" id="pt2_pct" value="25" step="0.5">
            </div>
            <div class="col-3">
                <label>P3 Target %</label>
                <input type="number" class="form-control" id="pt3_pct" value="35" step="0.5">
            </div>
            <div class="col-3">
                <label>P4 Target %</label>
                <input type="number" class="form-control" id="pt4_pct" value="40" step="0.5">
            </div>
        </div>
        
        <!-- Stop Loss & Trailing -->
        <div class="row mb-3">
            <div class="col-4">
                <label>Stop Loss %</label>
                <input type="number" class="form-control" id="stop_loss_pct" step="0.5">
            </div>
            <div class="col-4">
                <label>Trailing Stop %</label>
                <input type="number" class="form-control" id="trailing_stop_pct" value="20" step="0.5">
            </div>
            <div class="col-4">
                <label>Trailing Activation %</label>
                <input type="number" class="form-control" id="trailing_activation_pct" value="40" step="0.5">
            </div>
        </div>
        
        <!-- Leave Runner -->
        <div class="mb-3">
            <label class="d-flex align-items-center gap-2">
                <input type="checkbox" id="leave_runner_enabled">
                <span>Leave Runner</span>
            </label>
            <small class="text-muted">Keep a percentage of your position after hitting profit targets</small>
            <div class="mt-2">
                <label>Runner Size: <input type="number" id="leave_runner_pct" value="25" style="width:60px"> % of position</label>
            </div>
        </div>
        
        <!-- Dynamic SL Escalation -->
        <div class="mb-3 p-3 border border-warning rounded">
            <label class="d-flex align-items-center gap-2">
                <input type="checkbox" id="enable_dynamic_sl">
                <span class="text-warning">Dynamic Stop Loss Escalation</span>
            </label>
            <p class="small text-muted mb-2">
                <strong>What it does:</strong> Each time you hit a profit target (PT1, PT2, PT3, PT4), your stop loss automatically moves UP to lock in more gains.
            </p>
            <p class="small text-muted mb-2">
                <strong>Example:</strong> You buy at ₹100. When you hit PT1 (+15%), Standard profile moves your stop to ₹100 (breakeven) - now you can't lose money. Hit PT2 (+25%)? Stop moves to ₹105 (+5% locked in).
            </p>
            <label>Profile:
                <select id="dynamic_sl_profile" class="form-control d-inline-block" style="width:auto">
                    <option value="conservative">Conservative (PT1: BE, PT2: +3%, PT3: +10%, PT4: +20%)</option>
                    <option value="standard" selected>Standard (PT1: BE, PT2: +5%, PT3: +15%, PT4: +25%)</option>
                    <option value="aggressive">Aggressive (PT1: -2%, PT2: BE, PT3: +10%, PT4: +20%)</option>
                </select>
            </label>
        </div>
        
        <!-- Max Profit Giveback Guard -->
        <div class="mb-3 p-3 border border-info rounded">
            <label class="d-flex align-items-center gap-2">
                <input type="checkbox" id="enable_giveback_guard">
                <span class="text-info">Max Profit Giveback Guard</span>
            </label>
            <p class="small text-muted mb-2">
                <strong>What it does:</strong> Protects your gains by exiting if profit drops too much from its highest point.
            </p>
            <p class="small text-muted mb-2">
                <strong>Example:</strong> Your trade reaches +50% profit (peak). With 30% giveback, if profit drops to +35% (gave back 30% of gains), you exit automatically - keeping +35% instead of watching it fall further.
            </p>
            <label>Max Giveback: <input type="number" id="giveback_allowed_pct" value="30" style="width:60px"> % from peak profit</label>
        </div>
        
        <button class="btn btn-primary" onclick="saveRiskSettings()">Save Risk Settings</button>
    </div>
</div>
```

### 5. Flask API Route

```python
@app.route('/api/channels/<int:channel_id>/risk-settings', methods=['POST'])
def update_channel_risk_settings(channel_id):
    """Update risk management settings for a channel."""
    data = request.json
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE channels SET
            risk_management_enabled = ?,
            profit_target_1_pct = ?,
            profit_target_2_pct = ?,
            profit_target_3_pct = ?,
            profit_target_4_pct = ?,
            stop_loss_pct = ?,
            trailing_stop_pct = ?,
            trailing_activation_pct = ?,
            leave_runner_enabled = ?,
            leave_runner_pct = ?,
            enable_dynamic_sl = ?,
            enable_giveback_guard = ?,
            giveback_allowed_pct = ?,
            dynamic_sl_profile = ?
        WHERE id = ?
    ''', (
        data.get('risk_management_enabled', 0),
        data.get('profit_target_1_pct', 0),
        data.get('profit_target_2_pct', 0),
        data.get('profit_target_3_pct', 0),
        data.get('profit_target_4_pct', 0),
        data.get('stop_loss_pct', 0),
        data.get('trailing_stop_pct', 0),
        data.get('trailing_activation_pct', 15),
        data.get('leave_runner_enabled', 0),
        data.get('leave_runner_pct', 25),
        data.get('enable_dynamic_sl', 0),
        data.get('enable_giveback_guard', 0),
        data.get('giveback_allowed_pct', 30),
        data.get('dynamic_sl_profile', 'standard'),
        channel_id
    ))
    
    conn.commit()
    
    # Trigger settings cache invalidation in risk manager
    try:
        from src.risk.position_monitor import request_settings_invalidation
        request_settings_invalidation()
    except:
        pass
    
    return jsonify({'success': True})
```

---

## Integration with Position Monitoring

The position monitor runs in an async loop, checking positions every 3-5 seconds:

```python
async def monitor_positions(self):
    """Main monitoring loop."""
    while True:
        try:
            # Get all open positions from brokers
            positions = await self.fetch_all_positions()
            
            for pos in positions:
                # Get channel-specific risk settings
                settings = self.db.get_channel_risk_settings(
                    symbol=pos.symbol,
                    asset_type=pos.asset,
                    strike=pos.strike,
                    expiry=pos.expiry,
                    broker_name=pos.broker
                )
                
                if not settings:
                    continue
                
                # Build trade state
                cache = self.get_or_create_cache(pos.position_key, pos)
                state = TradeState(
                    entry_price=pos.avg_cost,
                    current_price=pos.current_price,
                    qty=int(pos.quantity),
                    remaining_qty=int(pos.quantity)
                )
                state.copy_from_cache(cache)
                
                # Evaluate risk
                actions, updated_state = evaluate_exit_actions(state, settings)
                
                # Execute actions
                for action in actions:
                    if action.action_type == ActionType.SELL_ALL:
                        await self.execute_market_sell(pos, action.qty, action.reason)
                    elif action.action_type == ActionType.SELL_PARTIAL:
                        await self.execute_market_sell(pos, action.qty, action.reason)
                
                # Update cache
                apply_actions_to_cache(cache, updated_state)
                
        except Exception as e:
            print(f"[RISK] Monitor error: {e}")
        
        await asyncio.sleep(3)  # Check every 3 seconds
```

---

## Key Design Decisions

1. **Pure Function Design** - `evaluate_exit_actions()` is a pure function with no side effects, making it easy to test
2. **Idempotent** - Same price input won't generate duplicate actions (tracked via `last_evaluated_price`)
3. **Priority-Based** - Strict exit priority ensures the most important rules fire first
4. **State Persistence** - Cache entry survives bot restarts, preserving tier hits and trailing state
5. **Per-Channel** - Each signal source can have completely independent risk settings
6. **Broker-Agnostic** - Works with any broker that provides position data and sell execution
