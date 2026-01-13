"""
Conditional Order Cooldown Manager

Prevents duplicate trades when a conditional order triggers and
the trader posts a follow-up "ENTERED LONG" signal shortly after.

When a conditional order executes, the symbol+channel is added to a cooldown cache.
Any BTO signals for the same symbol+channel within the cooldown period are blocked.
"""

import time
import threading
from typing import Dict, Tuple, Optional

COOLDOWN_SECONDS = 120

_cooldown_cache: Dict[Tuple[str, str], float] = {}
_lock = threading.Lock()


def add_cooldown(symbol: str, channel_id: str) -> None:
    """
    Add a symbol+channel to cooldown after conditional order execution.
    
    Args:
        symbol: Stock/option symbol (e.g., 'XAIR')
        channel_id: Discord/Telegram channel ID
    """
    key = (symbol.upper(), str(channel_id))
    with _lock:
        _cooldown_cache[key] = time.time()
        _cleanup_expired()


def is_on_cooldown(symbol: str, channel_id: str) -> Tuple[bool, Optional[float]]:
    """
    Check if a symbol+channel is on cooldown.
    
    Args:
        symbol: Stock/option symbol
        channel_id: Discord/Telegram channel ID
        
    Returns:
        Tuple of (is_blocked, seconds_remaining)
        - (False, None) if not blocked
        - (True, remaining_seconds) if blocked
    """
    key = (symbol.upper(), str(channel_id))
    with _lock:
        if key not in _cooldown_cache:
            return (False, None)
        
        elapsed = time.time() - _cooldown_cache[key]
        if elapsed >= COOLDOWN_SECONDS:
            del _cooldown_cache[key]
            return (False, None)
        
        remaining = COOLDOWN_SECONDS - elapsed
        return (True, remaining)


def clear_cooldown(symbol: str, channel_id: str) -> bool:
    """
    Manually clear a cooldown (e.g., if user cancels the conditional order).
    
    Returns:
        True if cooldown was cleared, False if not found
    """
    key = (symbol.upper(), str(channel_id))
    with _lock:
        if key in _cooldown_cache:
            del _cooldown_cache[key]
            return True
        return False


def get_active_cooldowns() -> Dict[Tuple[str, str], float]:
    """Get all active cooldowns with remaining seconds."""
    with _lock:
        _cleanup_expired()
        current_time = time.time()
        return {
            key: COOLDOWN_SECONDS - (current_time - ts)
            for key, ts in _cooldown_cache.items()
        }


def _cleanup_expired():
    """Remove expired cooldowns (called within lock)."""
    current_time = time.time()
    expired = [
        key for key, ts in _cooldown_cache.items()
        if current_time - ts >= COOLDOWN_SECONDS
    ]
    for key in expired:
        del _cooldown_cache[key]
