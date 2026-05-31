"""
Risk Engine - Enhanced Exit Evaluation
=======================================
Industry-grade risk management with:
- Dynamic SL escalation after PT hits
- EMA-5 Candlestick Risk Engine (exit/escalation on EMA cross)
- Max Profit Giveback Guard
- Early Trailing Stop (percentage-based breakeven + profit locking)
- Priority-ordered exit evaluation
- Idempotent pure function design

Exit Priority Order:
1. Hard SL (immediate protection)
2. Dynamic SL (after PT hits)
2.5. EMA Exit/Escalation (candlestick-based trend monitoring)
3. Giveback Guard (max profit protection)
4. Early Trailing Stop (breakeven + profit locking)
5. Tiered Profit Targets (partial exits)
6. Legacy Trailing Stop (after activation)
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
    ACTIVATE_EARLY_TRAIL = "activate_early_trail"
    UPDATE_EARLY_STOP = "update_early_stop"
    EMA_EXIT = "ema_exit"
    EMA_ESCALATE_STOP = "ema_escalate_stop"
    EMA_NO_TREND_EXIT = "ema_no_trend_exit"


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
    
    # Early Trailing Stop state
    early_trailing_active: bool = False
    early_stop_price: Optional[float] = None
    early_steps_locked: int = 0
    
    last_evaluated_price: Optional[float] = None

    interval_high: Optional[float] = None
    interval_low: Optional[float] = None

    # EMA Risk state
    ema_value: Optional[float] = None
    ema_cross_state: str = 'seeding'
    ema_candles_count: int = 0
    ema_no_trend_count: int = 0
    ema_last_candle: Optional[Dict] = None
    ema_last_eval_candle_ts: Optional[float] = None
    ema_post_entry_candles: int = 0
    position_direction: str = 'stock'
    
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
        self.early_trailing_active = cache.early_trailing_active
        self.early_stop_price = cache.early_stop_price
        self.early_steps_locked = cache.early_steps_locked
        self.ema_no_trend_count = cache.ema_no_trend_count
        self.ema_last_eval_candle_ts = cache.ema_last_eval_candle_ts
        self.ema_post_entry_candles = cache.ema_post_entry_candles
        return self


DYNAMIC_SL_PROFILES = {
    'conservative': {
        'pt1_sl_pct': 0,
        'pt2_sl_pct': 3,
        'pt3_sl_pct': 8,
        'pt4_sl_pct': 15
    },
    'standard': {
        'pt1_sl_pct': 0,
        'pt2_sl_pct': 5,
        'pt3_sl_pct': 10,
        'pt4_sl_pct': 17
    },
    'aggressive': {
        'pt1_sl_pct': -2,
        'pt2_sl_pct': 0,
        'pt3_sl_pct': 8,
        'pt4_sl_pct': 15
    }
}


def calculate_dynamic_sl(
    entry_price: float,
    pts_hit: Dict[int, bool],
    profile: str = 'standard',
    current_price: float = None
) -> Optional[float]:
    """
    Calculate dynamic stop loss based on PT hits.
    Returns new SL price or None if no escalation.
    Safety: SL is capped below current_price to prevent immediate trigger.
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
    sl_price = entry_price * (1 + sl_pct / 100)
    
    if current_price is not None and sl_price >= current_price:
        buffer_pct = 0.02
        capped_sl = current_price * (1 - buffer_pct)
        if capped_sl > entry_price:
            import logging
            logging.getLogger('risk').warning(
                f"[DYN-SL] Capped SL from ${sl_price:.2f} (+{sl_pct}%) to ${capped_sl:.2f} "
                f"(current=${current_price:.2f}, entry=${entry_price:.2f}) — SL must stay below current price"
            )
            sl_price = capped_sl
        else:
            sl_price = entry_price
    
    return sl_price


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
    if leave_runner_pct > 0 and total_qty > 1 and runner_qty < 1:
        runner_qty = 1
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


def calculate_tier_quantities(
    total_qty: int,
    leave_runner_pct: float,
    enabled_tiers: List[int],
    custom_qtys: Optional[Dict[int, Optional[int]]] = None,
    custom_trim_pcts: Optional[Dict[int, Optional[float]]] = None,
) -> Dict[int, int]:
    """
    Unified tier quantity allocator. Priority: custom_qty > custom_trim_pct > auto_split.
    
    Args:
        total_qty: Total position size (contracts/shares)
        leave_runner_pct: Runner percentage (0 if disabled)
        enabled_tiers: List of enabled tier numbers [1,2,3,4]
        custom_qtys: Per-tier custom quantities {1: 5, 2: None, ...}
        custom_trim_pcts: Per-tier trim percentages {1: 80.0, 2: 10.0, ...}
    
    Returns:
        Dict mapping tier number to quantity to sell
    """
    if not enabled_tiers or total_qty <= 0:
        return {}

    custom_qtys = custom_qtys or {}
    custom_trim_pcts = custom_trim_pcts or {}

    runner_qty = math.floor(total_qty * (leave_runner_pct / 100))
    if leave_runner_pct > 0 and total_qty > 1 and runner_qty < 1:
        runner_qty = 1
    sellable_qty = total_qty - runner_qty

    if sellable_qty <= 0:
        return {tier: 0 for tier in enabled_tiers}

    tier_qtys = {}
    allocated = 0
    auto_tiers = []

    for tier in sorted(enabled_tiers):
        cq = custom_qtys.get(tier)
        cp = custom_trim_pcts.get(tier)

        if cq is not None and cq > 0:
            qty = min(cq, sellable_qty - allocated)
            tier_qtys[tier] = max(0, qty)
            allocated += tier_qtys[tier]
        elif cq is not None and cq == 0:
            tier_qtys[tier] = 0
        elif cp is not None and cp > 0:
            qty = math.floor(sellable_qty * (cp / 100.0))
            qty = min(qty, sellable_qty - allocated)
            tier_qtys[tier] = max(0, qty)
            allocated += tier_qtys[tier]
        elif cp is not None and cp == 0:
            tier_qtys[tier] = 0
        else:
            auto_tiers.append(tier)

    remaining = sellable_qty - allocated
    if auto_tiers and remaining > 0:
        base = remaining // len(auto_tiers)
        rem = remaining % len(auto_tiers)
        for i, tier in enumerate(auto_tiers):
            tier_qtys[tier] = base + (1 if i < rem else 0)
    elif not auto_tiers and remaining > 0:
        has_nonzero = any(tier_qtys.get(t, 0) > 0 for t in enabled_tiers)
        if has_nonzero:
            first_nonzero = next(t for t in sorted(enabled_tiers) if tier_qtys.get(t, 0) > 0)
            tier_qtys[first_nonzero] = tier_qtys[first_nonzero] + remaining

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
    4. Early Trailing Stop (breakeven + profit locking)
    5. Tiered Profit Targets
    6. Legacy Trailing Stop
    
    Returns:
        Tuple of (list of actions to execute, updated state)
    
    Idempotency: Calling repeatedly with same price won't duplicate actions.
    """
    actions: List[RiskAction] = []
    
    if state.remaining_qty <= 0:
        return actions, state
    
    ema_candle_ts = state.ema_last_candle.get('timestamp', 0) if state.ema_last_candle else 0
    has_new_ema_candle = (ema_candle_ts > 0 and ema_candle_ts != state.ema_last_eval_candle_ts)
    has_interval_extremes = (state.interval_high is not None or state.interval_low is not None)
    if state.last_evaluated_price == state.current_price and not has_new_ema_candle and not has_interval_extremes:
        return actions, state
    
    state.last_evaluated_price = state.current_price
    
    _sanity_ref = max(state.current_price, state.entry_price, 0.01)
    if state.interval_high and state.interval_high > 0:
        if state.interval_high > _sanity_ref * 10:
            if verbose:
                print(f"[RISK ENGINE] ⚠️ INTERVAL HIGH REJECTED: ${state.interval_high:.2f} is >10x reference ${_sanity_ref:.2f} (likely stock/option price mix)")
            state.interval_high = None
    if state.interval_low and state.interval_low > 0:
        if state.interval_low > _sanity_ref * 10 or (state.current_price > 0.01 and state.interval_low < state.current_price * 0.01):
            if verbose:
                print(f"[RISK ENGINE] ⚠️ INTERVAL LOW REJECTED: ${state.interval_low:.4f} vs reference ${_sanity_ref:.2f} (likely stock/option price mix)")
            state.interval_low = None

    if state.interval_high and state.interval_high > state.highest_price:
        state.highest_price = state.interval_high
    if state.current_price > state.highest_price:
        state.highest_price = state.current_price

    effective_low = state.current_price
    if state.interval_low and state.interval_low > 0 and state.interval_low < effective_low:
        effective_low = state.interval_low

    pnl_pct = state.pnl_pct

    interval_high_pnl = ((state.interval_high - state.entry_price) / state.entry_price * 100) if (state.interval_high and state.entry_price > 0) else pnl_pct
    if interval_high_pnl > state.max_pnl_seen:
        state.max_pnl_seen = interval_high_pnl
    if pnl_pct > state.max_pnl_seen:
        state.max_pnl_seen = pnl_pct
    
    if verbose:
        print(f"[RISK ENGINE] Evaluating: price=${state.current_price:.2f}, pnl={pnl_pct:.1f}%, max_pnl={state.max_pnl_seen:.1f}%")
    
    low_pnl_pct = ((effective_low - state.entry_price) / state.entry_price * 100) if state.entry_price > 0 else pnl_pct
    if config.stop_loss_pct > 0 and (pnl_pct <= -config.stop_loss_pct or low_pnl_pct <= -config.stop_loss_pct):
        _sl_pnl = min(pnl_pct, low_pnl_pct)
        actions.append(RiskAction(
            action_type=ActionType.SELL_ALL,
            reason=f"Hard SL hit ({_sl_pnl:.1f}% <= -{config.stop_loss_pct}%)",
            qty=state.remaining_qty,
            priority=1
        ))
        return actions, state
    
    if config.enable_dynamic_sl and state.pts_hit_count > 0:
        pts_hit = {1: state.pt1_hit, 2: state.pt2_hit, 3: state.pt3_hit, 4: state.pt4_hit}
        new_dynamic_sl = calculate_dynamic_sl(state.entry_price, pts_hit, config.dynamic_sl_profile, current_price=state.current_price)
        
        if new_dynamic_sl:
            if state.dynamic_sl_price is None or new_dynamic_sl > state.dynamic_sl_price:
                state.dynamic_sl_price = new_dynamic_sl
                actions.append(RiskAction(
                    action_type=ActionType.MOVE_STOP,
                    reason=f"Dynamic SL escalation after PT{state.pts_hit_count}",
                    new_stop_price=new_dynamic_sl,
                    priority=2
                ))
            
            if effective_low <= state.dynamic_sl_price:
                actions.append(RiskAction(
                    action_type=ActionType.SELL_ALL,
                    reason=f"Dynamic SL triggered (${effective_low:.2f} <= ${state.dynamic_sl_price:.2f})",
                    qty=state.remaining_qty,
                    priority=2
                ))
                return actions, state

    # 2.5. EMA Exit/Escalation (candlestick-based trend monitoring)
    if (config.ema_risk_enabled and 
        state.ema_cross_state not in ('seeding', 'frozen', '') and
        state.ema_candles_count >= config.ema_period and
        state.ema_value is not None):

        from .ema_engine import EMAExitEvaluator, EMADecision, EMAState, Candle

        ema_st = EMAState(
            value=state.ema_value,
            cross_state=state.ema_cross_state,
            candles_count=state.ema_candles_count,
            seeded=True
        )
        if state.ema_last_candle and isinstance(state.ema_last_candle, dict):
            ema_st.last_candle = Candle(
                open=state.ema_last_candle.get('open', 0),
                high=state.ema_last_candle.get('high', 0),
                low=state.ema_last_candle.get('low', 0),
                close=state.ema_last_candle.get('close', 0),
                timestamp=state.ema_last_candle.get('timestamp', 0),
                finalized=True
            )

        current_candle_ts = state.ema_last_candle.get('timestamp', 0) if state.ema_last_candle else 0
        is_new_candle = (current_candle_ts > 0 and 
                         current_candle_ts != state.ema_last_eval_candle_ts)

        if is_new_candle:
            state.ema_post_entry_candles += 1
            state.ema_last_eval_candle_ts = current_candle_ts

        EMA_WARMUP_CANDLES = 2

        ema_config = {
            'ema_buffer_pct': config.ema_buffer_pct,
            'ema_exit_enabled': config.ema_exit_enabled,
            'ema_escalation_enabled': config.ema_escalation_enabled,
            'ema_no_trend_candles': config.ema_no_trend_candles,
            'ema_no_trend_count': state.ema_no_trend_count
        }

        ema_result = EMAExitEvaluator.evaluate(state.position_direction, ema_st, ema_config)

        if ema_result.decision == EMADecision.EXIT:
            if state.ema_post_entry_candles < EMA_WARMUP_CANDLES:
                pass
            elif config.leave_runner_enabled and state.remaining_qty > 1:
                runner_qty = max(1, int(state.remaining_qty * config.leave_runner_pct / 100))
                sell_qty = state.remaining_qty - runner_qty
                if sell_qty > 0:
                    actions.append(RiskAction(
                        action_type=ActionType.EMA_EXIT,
                        reason=f"EMA Exit (Leave Runner): {ema_result.reason}",
                        qty=sell_qty,
                        priority=2
                    ))
                    state.remaining_qty -= sell_qty
            else:
                actions.append(RiskAction(
                    action_type=ActionType.EMA_EXIT,
                    reason=ema_result.reason,
                    qty=state.remaining_qty,
                    priority=2
                ))
                return actions, state

        elif ema_result.decision == EMADecision.ESCALATE and ema_result.new_stop_price:
            is_option = state.position_direction in ('C', 'P')
            if not is_option:
                current_stop = state.dynamic_sl_price or state.current_stop_price or 0
                ema_stop = ema_result.new_stop_price
                if state.entry_price > 0 and config.stop_loss_pct > 0:
                    channel_sl_floor = state.entry_price * (1 - config.stop_loss_pct / 100)
                    if ema_stop < state.entry_price and ema_stop > channel_sl_floor:
                        ema_stop = None
                if ema_stop and ema_stop > current_stop:
                    actions.append(RiskAction(
                        action_type=ActionType.EMA_ESCALATE_STOP,
                        reason=ema_result.reason,
                        new_stop_price=ema_stop,
                        priority=2
                    ))
            state.ema_no_trend_count = 0

        elif ema_result.decision in (EMADecision.NO_TREND_EXIT, EMADecision.NO_TREND_TICK):
            if is_new_candle:
                state.ema_no_trend_count += 1

            if (ema_result.decision == EMADecision.NO_TREND_EXIT and 
                    is_new_candle and
                    state.ema_post_entry_candles >= EMA_WARMUP_CANDLES):
                actions.append(RiskAction(
                    action_type=ActionType.EMA_NO_TREND_EXIT,
                    reason=f"{ema_result.reason} (after {state.ema_post_entry_candles} post-entry candles)",
                    qty=state.remaining_qty,
                    priority=2
                ))
                return actions, state

        elif ema_result.decision == EMADecision.HOLD:
            pass

    if config.enable_giveback_guard:
        if config.trailing_stop_pct > 0 and config.trailing_activation_pct > 0:
            activation_threshold = config.trailing_activation_pct
        elif config.enable_early_trailing and config.early_trailing_activation_pct > 0:
            activation_threshold = config.early_trailing_activation_pct
        else:
            activation_threshold = 30
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
    
    # 4. Early Trailing Stop (percentage-based breakeven + profit locking)
    # Mutually exclusive with legacy trailing stop
    if config.enable_early_trailing and config.early_trailing_activation_pct > 0:
        activation_pct = config.early_trailing_activation_pct
        step_pct = config.early_trailing_step_pct if config.early_trailing_step_pct > 0 else 3.0
        
        if not state.early_trailing_active:
            # Check if we should activate (move to breakeven)
            if pnl_pct >= activation_pct:
                state.early_trailing_active = True
                state.early_stop_price = state.entry_price
                state.early_steps_locked = 0
                actions.append(RiskAction(
                    action_type=ActionType.ACTIVATE_EARLY_TRAIL,
                    reason=f"Early trailing activated at +{pnl_pct:.1f}% (breakeven locked)",
                    new_stop_price=state.entry_price,
                    priority=4
                ))
        else:
            # Check if early stop hit
            if state.early_stop_price and effective_low <= state.early_stop_price:
                steps_desc = f"+{state.early_steps_locked * step_pct:.1f}%" if state.early_steps_locked > 0 else "breakeven"
                actions.append(RiskAction(
                    action_type=ActionType.SELL_ALL,
                    reason=f"Early trailing stop hit at ${state.early_stop_price:.2f} ({steps_desc})",
                    qty=state.remaining_qty,
                    priority=4
                ))
                return actions, state
            
            # Check if we should lock more profit
            expected_steps = int((pnl_pct - activation_pct) / step_pct)
            expected_steps = max(0, expected_steps)
            
            if expected_steps > state.early_steps_locked:
                new_stop_pct = expected_steps * step_pct
                new_stop_price = state.entry_price * (1 + new_stop_pct / 100)
                state.early_steps_locked = expected_steps
                state.early_stop_price = new_stop_price
                action = RiskAction(
                    action_type=ActionType.UPDATE_EARLY_STOP,
                    reason=f"Early trailing: +{new_stop_pct:.1f}% locked (Step {expected_steps})",
                    new_stop_price=new_stop_price,
                    priority=4
                )
                action.steps_locked = expected_steps
                actions.append(action)
    
    enabled_tiers = []
    tier_thresholds = {}
    
    for tier, pct_attr in [(1, 'profit_target_1_pct'), (2, 'profit_target_2_pct'), 
                           (3, 'profit_target_3_pct'), (4, 'profit_target_4_pct')]:
        pct = getattr(config, pct_attr, 0) or 0
        if pct > 0:
            enabled_tiers.append(tier)
            tier_thresholds[tier] = pct
    
    if enabled_tiers:
        escalation_only = getattr(config, 'escalation_only_mode', False)
        leave_runner = config.leave_runner_pct if config.leave_runner_enabled else 0
        custom_qtys = {
            t: getattr(config, f'profit_target_qty_{t}', None)
            for t in enabled_tiers
        }
        custom_trim_pcts = {
            t: getattr(config, f'profit_target_trim_pct_{t}', None)
            for t in enabled_tiers
        }
        tier_qtys = calculate_tier_quantities(state.qty, leave_runner, enabled_tiers, custom_qtys, custom_trim_pcts) if not escalation_only else {}
        
        peak_pnl = max(pnl_pct, state.max_pnl_seen)

        for tier in enabled_tiers:
            tier_hit_attr = f'pt{tier}_hit'
            already_hit = getattr(state, tier_hit_attr, False)
            threshold = tier_thresholds[tier]

            if not already_hit and peak_pnl >= threshold:
                setattr(state, tier_hit_attr, True)

                if not escalation_only and pnl_pct >= threshold:
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
    
    # 6. Legacy Trailing Stop - SKIP if Early Trailing is enabled (mutually exclusive)
    if config.trailing_stop_pct > 0 and not config.enable_early_trailing:
        _just_activated = False
        if not state.trailing_active and pnl_pct >= config.trailing_activation_pct:
            state.trailing_active = True
            _just_activated = True
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

            # Don't trigger on the same tick as activation — interval_low may predate the new high
            if not _just_activated and effective_low <= state.trailing_stop_price:
                actions.append(RiskAction(
                    action_type=ActionType.SELL_ALL,
                    reason=f"Trailing stop hit (${effective_low:.2f} <= ${state.trailing_stop_price:.2f})",
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
    cache.early_trailing_active = state.early_trailing_active
    cache.early_stop_price = state.early_stop_price
    cache.early_steps_locked = state.early_steps_locked
    cache.ema_no_trend_count = state.ema_no_trend_count
    if state.ema_cross_state and state.ema_cross_state not in ('seeding', 'frozen', ''):
        cache.ema_last_cross_state = state.ema_cross_state
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
    elif action.action_type == ActionType.ACTIVATE_EARLY_TRAIL:
        return f"{prefix}{symbol}: ✓ BREAKEVEN LOCKED - {action.reason}"
    elif action.action_type == ActionType.UPDATE_EARLY_STOP:
        return f"{prefix}{symbol}: 📈 EARLY TRAIL → ${action.new_stop_price:.2f} - {action.reason}"
    elif action.action_type == ActionType.EMA_EXIT:
        return f"{prefix}{symbol}: 📊 EMA EXIT - {action.reason}"
    elif action.action_type == ActionType.EMA_ESCALATE_STOP:
        return f"{prefix}{symbol}: 📊 EMA ESCALATE → ${action.new_stop_price:.2f} - {action.reason}"
    elif action.action_type == ActionType.EMA_NO_TREND_EXIT:
        return f"{prefix}{symbol}: ⚠️ EMA NO-TREND EXIT - {action.reason}"
    return f"{prefix}{symbol}: {action.action_type.value} - {action.reason}"
