"""
Early Trailing Stop Module
==========================
Percentage-based breakeven + profit locking trailing stop.

Industry-standard day trading risk management:
- Move stop to breakeven after position gains X% (e.g., +5%)
- Lock profit in increments every additional Y% gain (e.g., +3% steps)
- Never give back a winning trade - profit or breakeven only

State Machine:
    INACTIVE -> BREAKEVEN_LOCKED -> PROFIT_LOCKED_1 -> PROFIT_LOCKED_2 -> ...

This is MUTUALLY EXCLUSIVE with the legacy trailing stop.
"""
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum

from .risk_types import PositionSnapshot, PositionCacheEntry, ChannelRiskSettings


class EarlyTrailingState(Enum):
    """States for the early trailing stop state machine."""
    INACTIVE = "inactive"
    BREAKEVEN_LOCKED = "breakeven_locked"
    PROFIT_LOCKED = "profit_locked"


@dataclass
class EarlyTrailingResult:
    """Result of early trailing evaluation."""
    should_exit: bool = False
    should_update_stop: bool = False
    new_stop_price: Optional[float] = None
    new_steps_locked: int = 0
    state: EarlyTrailingState = EarlyTrailingState.INACTIVE
    reason: str = ""
    
    @classmethod
    def no_action(cls) -> 'EarlyTrailingResult':
        return cls(should_exit=False, should_update_stop=False)
    
    @classmethod
    def update_stop(cls, new_price: float, steps: int, state: EarlyTrailingState, reason: str) -> 'EarlyTrailingResult':
        return cls(
            should_exit=False,
            should_update_stop=True,
            new_stop_price=new_price,
            new_steps_locked=steps,
            state=state,
            reason=reason
        )
    
    @classmethod
    def exit(cls, reason: str) -> 'EarlyTrailingResult':
        return cls(should_exit=True, reason=reason)


def evaluate_early_trailing(
    position: PositionSnapshot,
    cache: PositionCacheEntry,
    settings: ChannelRiskSettings,
    verbose: bool = True
) -> Tuple[EarlyTrailingResult, PositionCacheEntry]:
    """
    Evaluate early trailing stop conditions.
    
    Percentage-based breakeven and profit locking:
    1. Once price gains >= activation_pct, move stop to entry (breakeven)
    2. For each additional step_pct gain, move stop up by step_pct
    3. If price drops to or below early_stop_price, trigger exit
    
    Args:
        position: Current position snapshot with pct_change property
        cache: Cached position state (early_trailing_active, early_stop_price, etc.)
        settings: Channel risk settings with early trailing config
        
    Returns:
        Tuple of (EarlyTrailingResult, updated cache)
    """
    if not settings.enable_early_trailing:
        return EarlyTrailingResult.no_action(), cache
    
    if settings.early_trailing_activation_pct <= 0:
        return EarlyTrailingResult.no_action(), cache
    
    pct_change = position.pct_change
    entry_price = cache.entry_price if cache.entry_price > 0 else position.avg_cost
    current_price = position.current_price
    
    activation_pct = settings.early_trailing_activation_pct
    step_pct = settings.early_trailing_step_pct if settings.early_trailing_step_pct > 0 else 3.0
    
    if not cache.early_trailing_active:
        if pct_change >= activation_pct:
            cache.early_trailing_active = True
            cache.early_stop_price = entry_price
            cache.early_steps_locked = 0
            
            if verbose:
                print(f"[EARLY_TRAIL] ✓ BREAKEVEN LOCKED: {position.symbol} at +{pct_change:.1f}% | Stop → ${entry_price:.2f}")
            
            return EarlyTrailingResult.update_stop(
                new_price=entry_price,
                steps=0,
                state=EarlyTrailingState.BREAKEVEN_LOCKED,
                reason=f"Breakeven locked at +{activation_pct}%"
            ), cache
        else:
            return EarlyTrailingResult.no_action(), cache
    
    if cache.early_stop_price and current_price <= cache.early_stop_price:
        steps_desc = f"+{cache.early_steps_locked * step_pct:.1f}%" if cache.early_steps_locked > 0 else "breakeven"
        reason = f"Early trailing stop hit at ${cache.early_stop_price:.2f} ({steps_desc})"
        
        if verbose:
            print(f"[EARLY_TRAIL] 🛑 EXIT: {position.symbol} | Price ${current_price:.2f} <= Stop ${cache.early_stop_price:.2f}")
        
        return EarlyTrailingResult.exit(reason), cache
    
    expected_steps = int((pct_change - activation_pct) / step_pct)
    expected_steps = max(0, expected_steps)
    
    if expected_steps > cache.early_steps_locked:
        new_stop_pct = expected_steps * step_pct
        new_stop_price = entry_price * (1 + new_stop_pct / 100)
        
        cache.early_steps_locked = expected_steps
        cache.early_stop_price = new_stop_price
        
        if verbose:
            print(f"[EARLY_TRAIL] 📈 PROFIT LOCKED: {position.symbol} Step {expected_steps} | +{new_stop_pct:.1f}% | Stop → ${new_stop_price:.2f}")
        
        return EarlyTrailingResult.update_stop(
            new_price=new_stop_price,
            steps=expected_steps,
            state=EarlyTrailingState.PROFIT_LOCKED,
            reason=f"Profit locked: +{new_stop_pct:.1f}% (Step {expected_steps})"
        ), cache
    
    return EarlyTrailingResult.no_action(), cache


def get_early_trailing_status(cache: PositionCacheEntry, settings: ChannelRiskSettings) -> dict:
    """
    Get human-readable early trailing status for UI display.
    
    Args:
        cache: Position cache entry
        settings: Channel risk settings
        
    Returns:
        Dict with status information
    """
    if not settings.enable_early_trailing:
        return {
            'enabled': False,
            'state': 'disabled',
            'stop_price': None,
            'steps_locked': 0,
            'description': 'Early Trailing not enabled'
        }
    
    if not cache.early_trailing_active:
        return {
            'enabled': True,
            'state': 'inactive',
            'stop_price': None,
            'steps_locked': 0,
            'description': f'Waiting for +{settings.early_trailing_activation_pct}% to activate'
        }
    
    step_pct = settings.early_trailing_step_pct
    locked_pct = cache.early_steps_locked * step_pct if cache.early_steps_locked > 0 else 0
    
    if cache.early_steps_locked == 0:
        state = 'breakeven_locked'
        desc = 'Breakeven locked (zero risk)'
    else:
        state = 'profit_locked'
        desc = f'+{locked_pct:.1f}% profit locked (Step {cache.early_steps_locked})'
    
    return {
        'enabled': True,
        'state': state,
        'stop_price': cache.early_stop_price,
        'steps_locked': cache.early_steps_locked,
        'locked_pct': locked_pct,
        'description': desc
    }


def validate_early_trailing_settings(settings: ChannelRiskSettings) -> Tuple[bool, str]:
    """
    Validate early trailing settings for conflicts.
    
    Early Trailing is mutually exclusive with legacy Trailing Stop.
    
    Args:
        settings: Channel risk settings to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not settings.enable_early_trailing:
        return True, ""
    
    if settings.trailing_stop_pct > 0:
        return False, "Early Trailing and Trailing Stop cannot both be enabled. Please disable one."
    
    if settings.early_trailing_activation_pct <= 0:
        return False, "Early Trailing activation % must be greater than 0"
    
    if settings.early_trailing_step_pct <= 0:
        return False, "Early Trailing step % must be greater than 0"
    
    if settings.early_trailing_step_pct > settings.early_trailing_activation_pct:
        return False, "Step % should not exceed activation % for proper functioning"
    
    return True, ""
