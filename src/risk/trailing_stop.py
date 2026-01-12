"""
Trailing Stop Evaluation
========================
Trailing stop activation and trigger logic.
"""
from typing import Optional, Tuple
from .risk_types import (
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
    channel_name: str = "Global",
    verbose: bool = True
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
        verbose: Enable detailed trailing stop logging
        
    Returns:
        Tuple of (ExitDecision, should_activate_trailing)
    """
    if trailing_stop_pct <= 0:
        return ExitDecision.no_exit(), False
    
    pct_change = position.pct_change
    current = position.current_price
    current_qty = int(position.quantity)
    
    should_activate = False
    
    if not cache.trailing_activated:
        if pct_change >= trailing_activation_pct:
            should_activate = True
            print(f"[TRAIL] ✓ [{channel_name}] {position.position_key}: "
                  f"ACTIVATED at {pct_change:.2f}% (threshold: {trailing_activation_pct}%)")
        elif verbose:
            remaining = trailing_activation_pct - pct_change
            print(f"[TRAIL] [{channel_name}] {position.symbol}: "
                  f"+{pct_change:.1f}% | Activation at +{trailing_activation_pct}% | "
                  f"Need +{remaining:.1f}% more | NOT ACTIVE")
    
    if cache.trailing_activated or should_activate:
        trailing_stop_price = cache.highest_price * (1 - trailing_stop_pct / 100)
        distance_from_stop = ((current - trailing_stop_price) / trailing_stop_price) * 100
        
        if verbose:
            status = "✓ ACTIVE" if cache.trailing_activated else "→ ACTIVATING"
            print(f"[TRAIL] {status} [{channel_name}] {position.symbol}: "
                  f"${current:.2f} | High: ${cache.highest_price:.2f} | "
                  f"Stop: ${trailing_stop_price:.2f} ({trailing_stop_pct}% below high) | "
                  f"Buffer: {distance_from_stop:.1f}%")
        
        if current <= trailing_stop_price:
            print(f"[TRAIL] ⚠️  TRIGGERED [{channel_name}] {position.position_key}: "
                  f"${current:.2f} <= Stop ${trailing_stop_price:.2f} "
                  f"(dropped {trailing_stop_pct}% from high ${cache.highest_price:.2f})")
            return ExitDecision.trailing_stop(
                reason=f"(${current:.2f} <= ${trailing_stop_price:.2f}, "
                       f"dropped {trailing_stop_pct}% from high ${cache.highest_price:.2f})",
                qty=current_qty,
                channel_name=channel_name
            ), should_activate
    
    if not cache.trailing_activated and stop_loss_pct > 0:
        if pct_change <= -stop_loss_pct:
            print(f"[TRAIL] ⚠️  STOP LOSS [{channel_name}] {position.position_key}: "
                  f"{pct_change:.2f}% <= -{stop_loss_pct}%")
            return ExitDecision.stop_loss(
                reason=f"({pct_change:.2f}% <= -{stop_loss_pct}%)",
                qty=current_qty,
                channel_name=channel_name
            ), False
        elif verbose and pct_change < 0:
            remaining = stop_loss_pct + pct_change
            print(f"[TRAIL] [{channel_name}] {position.symbol}: "
                  f"{pct_change:.1f}% | SL at -{stop_loss_pct}% | "
                  f"Buffer: {remaining:.1f}%")
    
    return ExitDecision.no_exit(), should_activate


def get_effective_trailing_settings(
    channel_settings: Optional[ChannelRiskSettings],
    global_settings: RiskSettings,
    default_activation: float = 15.0
) -> Tuple[float, float, float]:
    """
    Get effective trailing stop settings (channel > global).
    
    CRITICAL: Only fall back to global settings if global risk is ENABLED.
    If global is disabled, do not apply global trailing/stop values.
    
    Returns:
        Tuple of (trailing_stop_pct, trailing_activation_pct, stop_loss_pct)
    """
    if channel_settings:
        # Channel settings exist - use channel values, 
        # only fall back to global if global is ENABLED
        if global_settings.enabled:
            return (
                channel_settings.trailing_stop_pct or global_settings.trailing_stop_percent,
                channel_settings.trailing_activation_pct or default_activation,
                channel_settings.stop_loss_pct or global_settings.stop_loss_percent
            )
        else:
            # Global is disabled - only use channel's own values, no global fallback
            return (
                channel_settings.trailing_stop_pct or 0,
                channel_settings.trailing_activation_pct or default_activation,
                channel_settings.stop_loss_pct or 0
            )
    
    # No channel settings - only apply global if enabled
    if global_settings.enabled:
        return (
            global_settings.trailing_stop_percent,
            default_activation,
            global_settings.stop_loss_percent
        )
    
    # Global disabled and no channel settings - return zeros (no trailing/stop loss)
    return (0, default_activation, 0)
