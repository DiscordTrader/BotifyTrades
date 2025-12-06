"""
Tiered Profit Targets Evaluation
================================
Per-channel T1/T2/T3 profit target logic with partial exits.
"""
from typing import Optional
from .types import (
    PositionSnapshot, 
    ChannelRiskSettings, 
    PositionCacheEntry,
    ExitDecision
)


def evaluate_tiered_targets(
    position: PositionSnapshot,
    cache: PositionCacheEntry,
    channel_settings: ChannelRiskSettings
) -> ExitDecision:
    """
    Evaluate tiered profit targets for a position.
    
    Rules:
    - For small positions (1-2 contracts): Close all at first target hit
    - For larger positions: Scale out 1/3 at T1, 1/2 at T2, all at T3
    
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
    
    if not cache.tier1_hit and t1 > 0 and pct_change >= t1:
        if current_qty <= 2:
            return ExitDecision(
                should_exit=True,
                reason=f"({pct_change:.2f}% >= {t1}%) - Closing all {current_qty} (small position)",
                exit_qty=current_qty,
                is_partial=False,
                risk_trigger='profit_target',
                tier_hit=1
            )
        else:
            exit_qty = max(1, current_qty // 3)
            return ExitDecision(
                should_exit=True,
                reason=f"({pct_change:.2f}% >= {t1}%) - Selling {exit_qty} of {current_qty}",
                exit_qty=exit_qty,
                is_partial=True,
                risk_trigger='profit_target',
                tier_hit=1
            )
    
    elif cache.tier1_hit and not cache.tier2_hit and t2 > 0 and pct_change >= t2:
        if current_qty <= 1:
            return ExitDecision(
                should_exit=True,
                reason=f"({pct_change:.2f}% >= {t2}%) - Closing remaining {current_qty}",
                exit_qty=current_qty,
                is_partial=False,
                risk_trigger='profit_target',
                tier_hit=2
            )
        else:
            exit_qty = max(1, current_qty // 2)
            return ExitDecision(
                should_exit=True,
                reason=f"({pct_change:.2f}% >= {t2}%) - Selling {exit_qty} of {current_qty}",
                exit_qty=exit_qty,
                is_partial=True,
                risk_trigger='profit_target',
                tier_hit=2
            )
    
    elif cache.tier2_hit and not cache.tier3_hit and t3 > 0 and pct_change >= t3:
        return ExitDecision(
            should_exit=True,
            reason=f"({pct_change:.2f}% >= {t3}%) - Closing remaining {current_qty}",
            exit_qty=current_qty,
            is_partial=False,
            risk_trigger='profit_target',
            tier_hit=3
        )
    
    return ExitDecision.no_exit()


def format_tier_reason(decision: ExitDecision, channel_name: str) -> str:
    """Format the exit reason with tier and channel info."""
    if decision.tier_hit:
        return f"TIER {decision.tier_hit} TARGET [{channel_name}] {decision.reason}"
    return f"PROFIT TARGET [{channel_name}] {decision.reason}"
