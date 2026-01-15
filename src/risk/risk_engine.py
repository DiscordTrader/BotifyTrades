"""
Risk Engine - Enhanced Exit Evaluation
=======================================
Industry-grade risk management with:
- Dynamic SL escalation after PT hits
- Max Profit Giveback Guard
- Priority-ordered exit evaluation
- Idempotent pure function design

Exit Priority Order:
1. Hard SL (immediate protection)
2. Dynamic SL (after PT hits)
3. Giveback Guard (max profit protection)
4. Trailing Stop (after activation)
5. Runner Exit (trailing manages remainder)
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum
import math

from .risk_types import ChannelRiskSettings, PositionCacheEntry


class ActionType(Enum):
    """Types of risk actions that can be taken."""
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
    
    def __repr__(self):
        if self.action_type == ActionType.SELL_PARTIAL:
            return f"SELL_PARTIAL({self.qty}, tier={self.tier}, reason='{self.reason}')"
        elif self.action_type == ActionType.SELL_ALL:
            return f"SELL_ALL(reason='{self.reason}')"
        elif self.action_type == ActionType.MOVE_STOP:
            return f"MOVE_STOP(${self.new_stop_price:.2f}, reason='{self.reason}')"
        elif self.action_type == ActionType.ACTIVATE_TRAIL:
            return f"ACTIVATE_TRAIL(reason='{self.reason}')"
        elif self.action_type == ActionType.UPDATE_TRAIL_STOP:
            return f"UPDATE_TRAIL_STOP(${self.new_stop_price:.2f})"
        elif self.action_type == ActionType.ACTIVATE_GIVEBACK:
            return f"ACTIVATE_GIVEBACK(reason='{self.reason}')"
        return f"{self.action_type.value}(reason='{self.reason}')"


@dataclass
class TradeState:
    """
    Complete state of a trade for risk evaluation.
    This captures all information needed to make exit decisions.
    """
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
        """Current PnL percentage."""
        if self.entry_price <= 0:
            return 0.0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100
    
    @property
    def pts_hit_count(self) -> int:
        """Count of profit targets hit."""
        return sum([self.pt1_hit, self.pt2_hit, self.pt3_hit, self.pt4_hit])
    
    def copy_from_cache(self, cache: PositionCacheEntry) -> 'TradeState':
        """Update state from cache entry."""
        self.highest_price = cache.highest_price
        self.max_pnl_seen = cache.max_pnl_seen
        self.pt1_hit = cache.tier1_hit
        self.pt2_hit = cache.tier2_hit
        self.pt3_hit = cache.tier3_hit
        self.pt4_hit = cache.tier4_hit
        self.trailing_active = cache.trailing_activated
        self.giveback_guard_active = cache.giveback_guard_active
        self.current_stop_price = cache.stop_loss_price
        self.dynamic_sl_price = cache.dynamic_sl_price
        self.last_evaluated_price = cache.last_evaluated_price
        return self


DYNAMIC_SL_PROFILES = {
    'conservative': {
        'pt1_sl_pct': 0,
        'pt2_sl_pct': 3,
        'pt3_sl_pct': 10,
        'pt4_sl_pct': 20
    },
    'standard': {
        'pt1_sl_pct': 0,
        'pt2_sl_pct': 5,
        'pt3_sl_pct': 15,
        'pt4_sl_pct': 25
    },
    'aggressive': {
        'pt1_sl_pct': -2,
        'pt2_sl_pct': 0,
        'pt3_sl_pct': 10,
        'pt4_sl_pct': 20
    }
}


def calculate_dynamic_sl(
    entry_price: float,
    pts_hit: Dict[int, bool],
    profile: str = 'standard'
) -> Optional[float]:
    """
    Calculate dynamic stop loss based on PT hits.
    Returns new SL price or None if no escalation.
    """
    profile_config = DYNAMIC_SL_PROFILES.get(profile, DYNAMIC_SL_PROFILES['standard'])
    
    highest_tier_hit = 0
    for tier in [4, 3, 2, 1]:
        if pts_hit.get(tier, False):
            highest_tier_hit = tier
            break
    
    if highest_tier_hit == 0:
        return None
    
    sl_pct = profile_config.get(f'pt{highest_tier_hit}_sl_pct', 0)
    return entry_price * (1 + sl_pct / 100)


def calculate_auto_tier_quantities(
    total_qty: int,
    leave_runner_pct: float,
    enabled_tiers: List[int]
) -> Dict[int, int]:
    """
    Calculate auto-scaled quantities across enabled tiers.
    Reserves leave_runner_pct for runner position.
    """
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


def evaluate_exit_actions(
    state: TradeState,
    config: ChannelRiskSettings,
    verbose: bool = False
) -> Tuple[List[RiskAction], TradeState]:
    """
    Pure function to evaluate all exit conditions and return actions.
    
    Priority Order:
    1. Hard SL
    2. Dynamic SL (after PTs)
    3. Giveback Guard
    4. Trailing Stop
    5. Runner Exit via trailing
    
    Returns:
        Tuple of (list of actions to execute, updated state)
    
    Idempotency: Calling repeatedly with same price won't duplicate actions.
    """
    actions: List[RiskAction] = []
    
    if state.remaining_qty <= 0:
        return actions, state
    
    if state.last_evaluated_price == state.current_price:
        return actions, state
    
    state.last_evaluated_price = state.current_price
    
    pnl_pct = state.pnl_pct
    
    if state.current_price > state.highest_price:
        state.highest_price = state.current_price
    
    if pnl_pct > state.max_pnl_seen:
        state.max_pnl_seen = pnl_pct
    
    if verbose:
        print(f"[RISK ENGINE] Evaluating: price=${state.current_price:.2f}, pnl={pnl_pct:.1f}%, max_pnl={state.max_pnl_seen:.1f}%")
    
    if config.stop_loss_pct > 0 and pnl_pct <= -config.stop_loss_pct:
        actions.append(RiskAction(
            action_type=ActionType.SELL_ALL,
            reason=f"Hard SL hit ({pnl_pct:.1f}% <= -{config.stop_loss_pct}%)",
            qty=state.remaining_qty,
            priority=1
        ))
        return actions, state
    
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
    
    if config.enable_giveback_guard:
        activation_threshold = config.trailing_activation_pct if config.trailing_activation_pct > 0 else 30
        pt2_activated = state.pt2_hit
        
        if not state.giveback_guard_active and (pt2_activated or state.max_pnl_seen >= activation_threshold):
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
                    reason=f"Giveback guard triggered ({pnl_pct:.1f}% <= {giveback_threshold:.1f}% threshold, max was {state.max_pnl_seen:.1f}%)",
                    qty=state.remaining_qty,
                    priority=3
                ))
                return actions, state
    
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
                    reason=f"Trail stop updated (high=${state.highest_price:.2f})",
                    new_stop_price=new_trail_stop,
                    priority=5
                ))
            
            if state.current_price <= state.trailing_stop_price:
                actions.append(RiskAction(
                    action_type=ActionType.SELL_ALL,
                    reason=f"Trailing stop hit (${state.current_price:.2f} <= ${state.trailing_stop_price:.2f})",
                    qty=state.remaining_qty,
                    priority=5
                ))
                return actions, state
    
    return actions, state


def apply_actions_to_cache(
    cache: PositionCacheEntry,
    state: TradeState
) -> PositionCacheEntry:
    """
    Apply state changes back to cache entry for persistence.
    """
    cache.highest_price = state.highest_price
    cache.max_pnl_seen = state.max_pnl_seen
    cache.tier1_hit = state.pt1_hit
    cache.tier2_hit = state.pt2_hit
    cache.tier3_hit = state.pt3_hit
    cache.tier4_hit = state.pt4_hit
    cache.trailing_activated = state.trailing_active
    cache.giveback_guard_active = state.giveback_guard_active
    cache.dynamic_sl_price = state.dynamic_sl_price
    cache.last_evaluated_price = state.last_evaluated_price
    return cache


def format_action_log(action: RiskAction, symbol: str, channel_name: str = "") -> str:
    """Format action for logging."""
    prefix = f"[{channel_name}] " if channel_name else ""
    if action.action_type == ActionType.SELL_ALL:
        return f"{prefix}{symbol}: EXIT ALL - {action.reason}"
    elif action.action_type == ActionType.SELL_PARTIAL:
        return f"{prefix}{symbol}: TRIM {action.qty} (T{action.tier}) - {action.reason}"
    elif action.action_type == ActionType.MOVE_STOP:
        return f"{prefix}{symbol}: MOVE SL → ${action.new_stop_price:.2f} - {action.reason}"
    elif action.action_type == ActionType.ACTIVATE_TRAIL:
        return f"{prefix}{symbol}: TRAILING ACTIVATED - {action.reason}"
    elif action.action_type == ActionType.UPDATE_TRAIL_STOP:
        return f"{prefix}{symbol}: TRAIL → ${action.new_stop_price:.2f}"
    elif action.action_type == ActionType.ACTIVATE_GIVEBACK:
        return f"{prefix}{symbol}: GIVEBACK GUARD ARMED - {action.reason}"
    return f"{prefix}{symbol}: {action.action_type.value} - {action.reason}"
