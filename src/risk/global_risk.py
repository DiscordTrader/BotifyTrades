"""
Global Risk Evaluation
======================
Global stop loss and profit target fallback for positions without channel settings.
"""
from typing import Optional
from .risk_types import (
    PositionSnapshot, 
    RiskSettings, 
    PositionCacheEntry,
    ExitDecision
)


def evaluate_global_risk(
    position: PositionSnapshot,
    cache: PositionCacheEntry,
    risk_settings: RiskSettings
) -> ExitDecision:
    """
    Evaluate global risk settings for a position.
    
    This is a fallback for positions without per-channel settings.
    
    Args:
        position: Current position snapshot
        cache: Cached position state
        risk_settings: Global risk management settings
        
    Returns:
        ExitDecision with should_exit, reason, and qty
    """
    if not risk_settings.enabled:
        return ExitDecision.no_exit()
    
    pct_change = position.pct_change
    current_qty = int(position.quantity)
    
    if risk_settings.profit_target_percent > 0 and pct_change >= risk_settings.profit_target_percent:
        return ExitDecision.profit_target(
            reason=f"({pct_change:.2f}% >= {risk_settings.profit_target_percent}%)",
            qty=current_qty,
            channel_name="Global"
        )
    
    if (risk_settings.trailing_stop_percent == 0 and 
        risk_settings.stop_loss_percent > 0 and 
        pct_change <= -risk_settings.stop_loss_percent):
        return ExitDecision.stop_loss(
            reason=f"({pct_change:.2f}% <= -{risk_settings.stop_loss_percent}%)",
            qty=current_qty,
            channel_name="Global"
        )
    
    return ExitDecision.no_exit()


def evaluate_price_based_stops(
    position: PositionSnapshot,
    cache: PositionCacheEntry
) -> ExitDecision:
    """
    Evaluate price-based stop loss and profit targets.
    
    These are per-signal overrides set during order entry.
    PRIORITY 1: Applied before percentage-based checks.
    
    Args:
        position: Current position snapshot
        cache: Cached position state with stop/target prices
        
    Returns:
        ExitDecision if triggered, else no_exit
    """
    current = position.current_price
    current_qty = int(position.quantity)
    
    target_price = cache.profit_target_price
    if target_price and current >= target_price:
        return ExitDecision(
            should_exit=True,
            reason=f"PROFIT TARGET PRICE (${current:.2f} >= ${target_price})",
            exit_qty=current_qty,
            is_partial=False,
            risk_trigger='profit_target'
        )
    
    sl_price = cache.stop_loss_price
    if sl_price and current <= sl_price:
        return ExitDecision(
            should_exit=True,
            reason=f"STOP LOSS PRICE (${current:.2f} <= ${sl_price})",
            exit_qty=current_qty,
            is_partial=False,
            risk_trigger='stop_loss'
        )
    
    return ExitDecision.no_exit()
