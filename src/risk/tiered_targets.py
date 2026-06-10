"""
Tiered Profit Targets Evaluation
================================
Per-channel T1/T2/T3/T4 profit target logic with partial exits and custom quantities.
"""
from typing import Optional, Tuple
from .risk_types import (
    PositionSnapshot, 
    ChannelRiskSettings, 
    PositionCacheEntry,
    ExitDecision
)


def calculate_tier_exit_qty(
    tier: int,
    current_qty: int,
    channel_settings: ChannelRiskSettings,
    cache: PositionCacheEntry
) -> Tuple[int, bool]:
    """
    Calculate exit quantity for a tier based on custom qty settings or auto-calculation.
    
    Args:
        tier: Tier number (1-4)
        current_qty: Current position quantity
        channel_settings: Channel risk settings with custom quantities
        cache: Position cache with tier hit flags
        
    Returns:
        Tuple of (exit_qty, is_partial)
    """
    qty_map = {
        1: channel_settings.profit_target_qty_1,
        2: channel_settings.profit_target_qty_2,
        3: channel_settings.profit_target_qty_3,
        4: channel_settings.profit_target_qty_4,
    }
    custom_qty = qty_map.get(tier)

    trim_pct_map = {
        1: channel_settings.profit_target_trim_pct_1,
        2: channel_settings.profit_target_trim_pct_2,
        3: channel_settings.profit_target_trim_pct_3,
        4: channel_settings.profit_target_trim_pct_4,
    }
    custom_trim_pct = trim_pct_map.get(tier)
    
    runner_qty = 0
    if channel_settings.leave_runner_enabled and current_qty > 1:
        runner_pct = channel_settings.leave_runner_pct / 100.0
        runner_qty = max(1, int(current_qty * runner_pct))
    
    max_sellable = current_qty - runner_qty
    
    if custom_qty is not None and custom_qty > 0:
        exit_qty = min(custom_qty, max_sellable)
        if exit_qty <= 0:
            return 0, False
        is_partial = exit_qty < current_qty
        return exit_qty, is_partial

    if custom_trim_pct is not None and custom_trim_pct == 0:
        return 0, False

    if custom_trim_pct is not None and custom_trim_pct > 0:
        import math
        exit_qty = math.floor(max_sellable * (custom_trim_pct / 100.0))
        exit_qty = min(exit_qty, max_sellable)
        if exit_qty <= 0 and max_sellable > 0:
            exit_qty = 1
        elif exit_qty <= 0:
            return 0, False
        is_partial = exit_qty < current_qty
        return exit_qty, is_partial
    
    if max_sellable <= 0:
        return 0, False

    active_tiers = []
    if channel_settings.profit_target_1_pct > 0:
        active_tiers.append(1)
    if channel_settings.profit_target_2_pct > 0:
        active_tiers.append(2)
    if channel_settings.profit_target_3_pct > 0:
        active_tiers.append(3)
    if channel_settings.profit_target_4_pct > 0:
        active_tiers.append(4)
    
    # Small positions handling
    if current_qty <= 2:
        if runner_qty > 0 and current_qty > runner_qty:
            return current_qty - runner_qty, True
        remaining_tiers = [t for t in active_tiers if t >= tier and not getattr(cache, f'tier{t}_hit', False)]
        if current_qty == 2 and len(remaining_tiers) >= 2:
            return 1, True
        if current_qty == 1:
            return 1, False
        return current_qty, False
    
    # For larger positions, calculate based on remaining tiers
    remaining_tiers = [t for t in active_tiers if t >= tier and not getattr(cache, f'tier{t}_hit', False)]
    if not remaining_tiers:
        return current_qty, False
    
    # Equal split for remaining tiers
    per_tier_qty = max(1, current_qty // len(remaining_tiers))
    
    # Last tier or leave runner adjustment
    if tier == max(active_tiers):
        if runner_qty > 0:
            exit_qty = max_sellable
            return max(0, exit_qty), exit_qty < current_qty
        return current_qty, False
    
    return per_tier_qty, per_tier_qty < current_qty


def evaluate_tiered_targets(
    position: PositionSnapshot,
    cache: PositionCacheEntry,
    channel_settings: ChannelRiskSettings
) -> ExitDecision:
    """
    Evaluate tiered profit targets for a position (supports up to 4 tiers).
    
    Rules:
    - For 2-contract positions with 2+ active tiers: Split 1 per tier (partial at T1, close at T2)
    - For 1-contract positions: Close at first target hit
    - For larger positions: Use custom quantities per tier or equal splits
    - Leave runner: Keep configured % after last tier hit
    - Trim order mode: 'market' or 'limit' (limit uses offset for better fills)
    
    Args:
        position: Current position snapshot
        cache: Cached position state (tier hit flags)
        channel_settings: Per-channel risk settings
        
    Returns:
        ExitDecision with should_exit, reason, qty, and partial flag
    """
    if not channel_settings or not channel_settings.has_tiered_targets:
        return ExitDecision.no_exit()
    
    pct_change = position.pct_change
    current_qty = int(position.quantity)
    channel_name = channel_settings.channel_name
    
    t1 = channel_settings.profit_target_1_pct
    t2 = channel_settings.profit_target_2_pct
    t3 = channel_settings.profit_target_3_pct
    t4 = channel_settings.profit_target_4_pct
    
    # Helper to check if tier has pending order awaiting fill
    def has_pending(tier: int) -> bool:
        return cache.has_pending_order_for_tier(tier)
    
    trim_pct_map = {
        1: channel_settings.profit_target_trim_pct_1,
        2: channel_settings.profit_target_trim_pct_2,
        3: channel_settings.profit_target_trim_pct_3,
        4: channel_settings.profit_target_trim_pct_4,
    }

    def _check_escalation_only(tier_num):
        """If trim_pct is explicitly 0, mark tier hit without selling (escalation-only)."""
        tp = trim_pct_map.get(tier_num)
        qty_map = {1: channel_settings.profit_target_qty_1, 2: channel_settings.profit_target_qty_2,
                   3: channel_settings.profit_target_qty_3, 4: channel_settings.profit_target_qty_4}
        if tp is not None and tp == 0 and not qty_map.get(tier_num):
            setattr(cache, f'tier{tier_num}_hit', True)
            print(f"[RISK] T{tier_num} ESCALATION ONLY ({pct_change:.2f}% >= target) — tier marked, no sell (trim=0%)")
            return True
        return False

    # Tier 1 check - skip if tier hit OR pending order exists
    if not cache.tier1_hit and not has_pending(1) and t1 > 0 and pct_change >= t1:
        if _check_escalation_only(1):
            pass
        else:
            exit_qty, is_partial = calculate_tier_exit_qty(1, current_qty, channel_settings, cache)
            if exit_qty > 0:
                qty_info = f"{exit_qty}" if channel_settings.profit_target_qty_1 else f"{exit_qty} of {current_qty}"
                return ExitDecision(
                    should_exit=True,
                    reason=f"({pct_change:.2f}% >= {t1}%) - Selling {qty_info}",
                    exit_qty=exit_qty,
                    is_partial=is_partial,
                    risk_trigger='profit_target',
                    tier_hit=1
                )

    # Tier 2 check - skip if tier hit OR pending order exists
    if cache.tier1_hit and not cache.tier2_hit and not has_pending(2) and t2 > 0 and pct_change >= t2:
        if _check_escalation_only(2):
            pass
        else:
            exit_qty, is_partial = calculate_tier_exit_qty(2, current_qty, channel_settings, cache)
            if exit_qty > 0:
                qty_info = f"{exit_qty}" if channel_settings.profit_target_qty_2 else f"{exit_qty} of {current_qty}"
                return ExitDecision(
                    should_exit=True,
                    reason=f"({pct_change:.2f}% >= {t2}%) - Selling {qty_info}",
                    exit_qty=exit_qty,
                    is_partial=is_partial,
                    risk_trigger='profit_target',
                    tier_hit=2
                )

    # Tier 3 check - skip if tier hit OR pending order exists
    if cache.tier2_hit and not cache.tier3_hit and not has_pending(3) and t3 > 0 and pct_change >= t3:
        if _check_escalation_only(3):
            pass
        elif t4 > 0:
            exit_qty, is_partial = calculate_tier_exit_qty(3, current_qty, channel_settings, cache)
            if exit_qty > 0:
                qty_info = f"{exit_qty}" if channel_settings.profit_target_qty_3 else f"{exit_qty} of {current_qty}"
                return ExitDecision(
                    should_exit=True,
                    reason=f"({pct_change:.2f}% >= {t3}%) - Selling {qty_info}",
                    exit_qty=exit_qty,
                    is_partial=is_partial,
                    risk_trigger='profit_target',
                    tier_hit=3
                )
        else:
            exit_qty, is_partial = calculate_tier_exit_qty(3, current_qty, channel_settings, cache)
            if exit_qty > 0:
                runner_info = ""
                if is_partial and channel_settings.leave_runner_enabled:
                    runner_qty = current_qty - exit_qty
                    runner_info = f", leaving {runner_qty} as runner"
                return ExitDecision(
                    should_exit=True,
                    reason=f"({pct_change:.2f}% >= {t3}%) - Selling {exit_qty}{runner_info}",
                    exit_qty=exit_qty,
                    is_partial=is_partial,
                    risk_trigger='profit_target',
                    tier_hit=3
                )

    # Tier 4 check - skip if tier hit OR pending order exists
    if cache.tier3_hit and not cache.tier4_hit and not has_pending(4) and t4 > 0 and pct_change >= t4:
        if _check_escalation_only(4):
            pass
        else:
            exit_qty, is_partial = calculate_tier_exit_qty(4, current_qty, channel_settings, cache)
            if exit_qty > 0:
                runner_info = ""
                if is_partial and channel_settings.leave_runner_enabled:
                    runner_qty = current_qty - exit_qty
                    runner_info = f", leaving {runner_qty} as runner"
                return ExitDecision(
                    should_exit=True,
                    reason=f"({pct_change:.2f}% >= {t4}%) - Selling {exit_qty}{runner_info}",
                    exit_qty=exit_qty,
                    is_partial=is_partial,
                    risk_trigger='profit_target',
                    tier_hit=4
                )
    
    return ExitDecision.no_exit()


def format_tier_reason(decision: ExitDecision, channel_name: str) -> str:
    """Format the exit reason with tier and channel info."""
    if decision.tier_hit:
        return f"TIER {decision.tier_hit} TARGET [{channel_name}] {decision.reason}"
    return f"PROFIT TARGET [{channel_name}] {decision.reason}"


def get_trim_order_price(
    current_price: float,
    channel_settings: ChannelRiskSettings,
    is_sell: bool = True
) -> Optional[float]:
    """
    Calculate limit order price for trim based on channel settings.
    
    Args:
        current_price: Current market price
        channel_settings: Channel risk settings with trim mode
        is_sell: True for sell orders (default), False for buy orders
        
    Returns:
        Limit price if mode is 'limit', None if mode is 'market'
    """
    if channel_settings.trim_order_mode != 'limit':
        return None
    
    offset_mode = getattr(channel_settings, 'trim_limit_offset_mode', 'dollar')
    
    _is_penny = current_price < 1.0
    _precision = 4 if _is_penny else 2

    if offset_mode == 'percent':
        pct = getattr(channel_settings, 'trim_limit_offset_pct', 2.0)
        if is_sell:
            limit_price = current_price * (1 - pct / 100)
        else:
            limit_price = current_price * (1 + pct / 100)
        return round(limit_price, _precision)
    else:
        offset = channel_settings.trim_limit_offset
        if _is_penny:
            if is_sell:
                _penny_limit = round(current_price - offset, _precision)
                if _penny_limit <= 0:
                    _penny_limit = round(current_price * 0.92, _precision)
                return _penny_limit
            else:
                return round(current_price + offset, _precision)
        if is_sell:
            base_price = current_price - offset
            cents = int((base_price * 100) % 10)
            if cents >= 5:
                limit_price = (int(base_price * 10) / 10) + 0.09
            else:
                limit_price = (int(base_price * 10) / 10) + 0.04
            return round(limit_price, 2)
        else:
            return round(current_price + offset, 2)


def evaluate_channel_stop_loss(
    position: PositionSnapshot,
    cache: PositionCacheEntry,
    channel_settings: ChannelRiskSettings
) -> ExitDecision:
    """
    Evaluate per-channel stop loss with manual override support.
    
    Precedence: manual_sl_price/manual_sl_pct > dynamic_sl_price > channel_settings.stop_loss_pct
    
    Args:
        position: Current position snapshot
        cache: Cached position state
        channel_settings: Per-channel risk settings
        
    Returns:
        ExitDecision with should_exit if stop loss hit
    """
    if not channel_settings:
        return ExitDecision.no_exit()
    
    pct_change = position.pct_change
    current_qty = int(position.quantity)
    channel_name = channel_settings.channel_name
    entry_price = cache.entry_price
    current_price = position.current_price
    
    sl_source = None
    stop_loss_pct = None
    stop_loss_price = None
    
    exit_mode = getattr(channel_settings, 'exit_strategy_mode', 'hybrid')
    
    if exit_mode != 'risk' and cache.manual_sl_price is not None:
        stop_loss_price = cache.manual_sl_price
        if entry_price > 0:
            stop_loss_pct = ((entry_price - stop_loss_price) / entry_price) * 100
        sl_source = "OVERRIDE"
    elif exit_mode != 'risk' and cache.manual_sl_pct is not None:
        stop_loss_pct = cache.manual_sl_pct
        if entry_price > 0:
            stop_loss_price = entry_price * (1 - stop_loss_pct / 100)
        sl_source = "OVERRIDE"
    elif channel_settings.enable_dynamic_sl and cache.dynamic_sl_price is not None:
        stop_loss_price = cache.dynamic_sl_price
        if entry_price > 0:
            stop_loss_pct = ((entry_price - stop_loss_price) / entry_price) * 100
        if stop_loss_price and entry_price > 0 and stop_loss_price < entry_price and channel_settings.stop_loss_pct > 0:
            channel_sl_floor = entry_price * (1 - channel_settings.stop_loss_pct / 100)
            if stop_loss_price > channel_sl_floor:
                stop_loss_pct = channel_settings.stop_loss_pct
                stop_loss_price = channel_sl_floor
                sl_source = "CHANNEL"
            else:
                sl_source = "DYNAMIC"
        else:
            sl_source = "DYNAMIC"
    else:
        stop_loss_pct = channel_settings.stop_loss_pct
        if entry_price > 0 and stop_loss_pct > 0:
            stop_loss_price = entry_price * (1 - stop_loss_pct / 100)
        sl_source = "CHANNEL"
    
    if not stop_loss_pct or stop_loss_pct <= 0:
        return ExitDecision.no_exit()
    
    if pct_change <= -stop_loss_pct:
        sl_label = f"STOP LOSS [{channel_name}]" if sl_source == "CHANNEL" else f"STOP LOSS [{sl_source}]"
        return ExitDecision(
            should_exit=True,
            reason=f"{sl_label} ({pct_change:.2f}% <= -{stop_loss_pct:.1f}%) - Closing all {current_qty}",
            exit_qty=current_qty,
            is_partial=False,
            risk_trigger='stop_loss'
        )
    
    return ExitDecision.no_exit()
