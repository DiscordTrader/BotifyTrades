"""
Trailing Stop Evaluation
========================
Trailing stop activation and trigger logic.
"""
from typing import Optional, Tuple
from .types import (
    PositionSnapshot, 
    RiskSettings,
    ChannelRiskSettings,
    PositionCacheEntry,
    ExitDecision
)


def evaluate_trailing_stop(
    position: PositionSnapshot,
    cache: PositionCacheEntry,
    trailing_stop_pct: float,
    trailing_activation_pct: float,
    stop_loss_pct: float = 0.0,
    channel_name: str = "Global"
) -> Tuple[ExitDecision, bool]:
    """
    Evaluate trailing stop conditions.
    
    Rules:
    1. Trailing stop activates when profit >= trailing_activation_pct
    2. Once active, triggers if price drops trailing_stop_pct from highest
    3. Before activation, fixed stop loss still applies
    
    Args:
        position: Current position snapshot
        cache: Cached position state (trailing_activated, highest_price)
        trailing_stop_pct: Trailing stop percentage
        trailing_activation_pct: Activation threshold percentage
        stop_loss_pct: Fixed stop loss percentage (before trailing activates)
        channel_name: Channel name for logging
        
    Returns:
        Tuple of (ExitDecision, should_activate_trailing)
    """
    if trailing_stop_pct <= 0:
        return ExitDecision.no_exit(), False
    
    pct_change = position.pct_change
    current = position.current_price
    current_qty = int(position.quantity)
    
    should_activate = False
    if not cache.trailing_activated and pct_change >= trailing_activation_pct:
        should_activate = True
        print(f"[RISK] [{channel_name}] {position.position_key}: "
              f"Trailing stop ACTIVATED at {pct_change:.2f}% gain")
    
    if cache.trailing_activated or should_activate:
        trailing_stop_price = cache.highest_price * (1 - trailing_stop_pct / 100)
        
        if current <= trailing_stop_price:
            return ExitDecision.trailing_stop(
                reason=f"(${current:.2f} <= ${trailing_stop_price:.2f}, "
                       f"dropped {trailing_stop_pct}% from high ${cache.highest_price:.2f})",
                qty=current_qty,
                channel_name=channel_name
            ), should_activate
    
    if not cache.trailing_activated and stop_loss_pct > 0 and pct_change <= -stop_loss_pct:
        return ExitDecision.stop_loss(
            reason=f"({pct_change:.2f}% <= -{stop_loss_pct}%)",
            qty=current_qty,
            channel_name=channel_name
        ), False
    
    return ExitDecision.no_exit(), should_activate


def get_effective_trailing_settings(
    channel_settings: Optional[ChannelRiskSettings],
    global_settings: RiskSettings,
    default_activation: float = 15.0
) -> Tuple[float, float, float]:
    """
    Get effective trailing stop settings (channel > global).
    
    Returns:
        Tuple of (trailing_stop_pct, trailing_activation_pct, stop_loss_pct)
    """
    if channel_settings:
        return (
            channel_settings.trailing_stop_pct or global_settings.trailing_stop_percent,
            channel_settings.trailing_activation_pct or default_activation,
            channel_settings.stop_loss_pct or global_settings.stop_loss_percent
        )
    
    return (
        global_settings.trailing_stop_percent,
        default_activation,
        global_settings.stop_loss_percent
    )
