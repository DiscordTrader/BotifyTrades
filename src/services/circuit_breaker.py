"""
Circuit Breaker - Emergency trading halt and risk limit controls.

Features:
- Global trading halt (kill switch)
- Per-channel trading halt
- Daily loss limit enforcement
- Position count limits
- Rate limiting
"""

import asyncio
from typing import Dict, Optional, List, Any
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict


class HaltReason(Enum):
    MANUAL = 'manual'
    DAILY_LOSS_LIMIT = 'daily_loss_limit'
    POSITION_LIMIT = 'position_limit'
    ERROR_THRESHOLD = 'error_threshold'
    API_RATE_LIMIT = 'api_rate_limit'


@dataclass
class HaltState:
    is_halted: bool = False
    reason: Optional[HaltReason] = None
    halted_at: Optional[datetime] = None
    halted_by: Optional[str] = None
    auto_resume_at: Optional[datetime] = None


@dataclass
class DailyLossTracker:
    date: date
    realized_loss: float = 0.0
    unrealized_loss: float = 0.0
    trade_count: int = 0
    limit: float = 0.0
    
    @property
    def total_loss(self) -> float:
        return self.realized_loss + self.unrealized_loss
    
    @property
    def limit_remaining(self) -> float:
        if self.limit <= 0:
            return float('inf')
        return max(0, self.limit - self.total_loss)
    
    @property
    def limit_pct_used(self) -> float:
        if self.limit <= 0:
            return 0.0
        return (self.total_loss / self.limit) * 100


class CircuitBreaker:
    """
    Circuit breaker for emergency trading controls.
    
    Provides:
    - Global kill switch
    - Per-channel halt
    - Daily loss limit tracking
    - Position count limits
    - Trade gating (check before execution)
    """
    
    def __init__(self):
        self._global_halt = HaltState()
        self._channel_halts: Dict[str, HaltState] = {}
        self._daily_losses: Dict[str, DailyLossTracker] = {}
        self._position_counts: Dict[str, int] = {}
        self._error_counts: Dict[str, int] = defaultdict(int)
        self._rate_limiters: Dict[str, List[float]] = defaultdict(list)
    
    @property
    def is_halted(self) -> bool:
        """Check if trading is globally halted."""
        return self._global_halt.is_halted
    
    def halt_global(self, reason: HaltReason = HaltReason.MANUAL, halted_by: str = None):
        """Halt all trading globally."""
        self._global_halt = HaltState(
            is_halted=True,
            reason=reason,
            halted_at=datetime.now(),
            halted_by=halted_by
        )
        print(f"[CIRCUIT BREAKER] 🛑 GLOBAL HALT: reason={reason.value}, by={halted_by}")
    
    def resume_global(self, resumed_by: str = None):
        """Resume global trading."""
        old_reason = self._global_halt.reason
        self._global_halt = HaltState(is_halted=False)
        print(f"[CIRCUIT BREAKER] ✅ GLOBAL RESUME: was_halted_for={old_reason}, by={resumed_by}")
    
    def halt_channel(self, channel_id: str, reason: HaltReason = HaltReason.MANUAL, halted_by: str = None):
        """Halt trading for a specific channel."""
        self._channel_halts[channel_id] = HaltState(
            is_halted=True,
            reason=reason,
            halted_at=datetime.now(),
            halted_by=halted_by
        )
        print(f"[CIRCUIT BREAKER] 🛑 CHANNEL HALT: channel={channel_id}, reason={reason.value}")
    
    def resume_channel(self, channel_id: str, resumed_by: str = None):
        """Resume trading for a specific channel."""
        if channel_id in self._channel_halts:
            del self._channel_halts[channel_id]
            print(f"[CIRCUIT BREAKER] ✅ CHANNEL RESUME: channel={channel_id}, by={resumed_by}")
    
    def is_channel_halted(self, channel_id: str) -> bool:
        """Check if a specific channel is halted."""
        return self._global_halt.is_halted or self._channel_halts.get(channel_id, HaltState()).is_halted
    
    def get_channel_state(self, channel_id: str) -> Optional[HaltState]:
        """Get the halt state for a specific channel."""
        return self._channel_halts.get(channel_id)
    
    def get_halt_reason(self, channel_id: str = None) -> Optional[str]:
        """Get the reason for halt (global or channel)."""
        if self._global_halt.is_halted:
            return f"Global: {self._global_halt.reason.value}"
        if channel_id and channel_id in self._channel_halts:
            halt = self._channel_halts[channel_id]
            if halt.is_halted:
                return f"Channel: {halt.reason.value}"
        return None
    
    def set_daily_loss_limit(self, channel_id: str, limit: float):
        """Set daily loss limit for a channel."""
        today = date.today()
        if channel_id not in self._daily_losses or self._daily_losses[channel_id].date != today:
            self._daily_losses[channel_id] = DailyLossTracker(date=today, limit=limit)
        else:
            self._daily_losses[channel_id].limit = limit
        print(f"[CIRCUIT BREAKER] Daily loss limit set: channel={channel_id}, limit=${limit}")
    
    def record_loss(self, channel_id: str, amount: float, is_realized: bool = True):
        """Record a loss for daily limit tracking."""
        today = date.today()
        if channel_id not in self._daily_losses:
            self._daily_losses[channel_id] = DailyLossTracker(date=today)
        
        tracker = self._daily_losses[channel_id]
        if tracker.date != today:
            tracker = DailyLossTracker(date=today)
            self._daily_losses[channel_id] = tracker
        
        if is_realized:
            tracker.realized_loss += abs(amount)
        else:
            tracker.unrealized_loss = abs(amount)
        
        tracker.trade_count += 1
        
        if tracker.limit > 0 and tracker.total_loss >= tracker.limit:
            self.halt_channel(channel_id, HaltReason.DAILY_LOSS_LIMIT, 'system')
            print(f"[CIRCUIT BREAKER] ⚠️ Daily loss limit reached: channel={channel_id}, "
                  f"loss=${tracker.total_loss}, limit=${tracker.limit}")
    
    def get_daily_loss_status(self, channel_id: str) -> Dict[str, Any]:
        """Get daily loss status for a channel."""
        today = date.today()
        tracker = self._daily_losses.get(channel_id)
        
        if not tracker or tracker.date != today:
            return {
                'date': today.isoformat(),
                'realized_loss': 0.0,
                'unrealized_loss': 0.0,
                'total_loss': 0.0,
                'limit': 0.0,
                'limit_remaining': float('inf'),
                'limit_pct_used': 0.0,
                'trade_count': 0
            }
        
        return {
            'date': tracker.date.isoformat(),
            'realized_loss': tracker.realized_loss,
            'unrealized_loss': tracker.unrealized_loss,
            'total_loss': tracker.total_loss,
            'limit': tracker.limit,
            'limit_remaining': tracker.limit_remaining,
            'limit_pct_used': tracker.limit_pct_used,
            'trade_count': tracker.trade_count
        }
    
    def set_position_limit(self, channel_id: str, max_positions: int):
        """Set max position limit for a channel."""
        self._position_counts[f"{channel_id}_limit"] = max_positions
    
    def record_position_opened(self, channel_id: str):
        """Record a new position opened."""
        key = f"{channel_id}_count"
        self._position_counts[key] = self._position_counts.get(key, 0) + 1
    
    def record_position_closed(self, channel_id: str):
        """Record a position closed."""
        key = f"{channel_id}_count"
        self._position_counts[key] = max(0, self._position_counts.get(key, 0) - 1)
    
    def get_position_count(self, channel_id: str) -> int:
        """Get current position count for a channel."""
        return self._position_counts.get(f"{channel_id}_count", 0)
    
    def get_position_limit(self, channel_id: str) -> int:
        """Get position limit for a channel."""
        return self._position_counts.get(f"{channel_id}_limit", 10)
    
    async def check_trade_allowed(
        self,
        channel_id: str,
        trade_value: float = 0,
        is_entry: bool = True
    ) -> Dict[str, Any]:
        """
        Check if a trade is allowed based on all circuit breaker rules.
        
        Returns:
            Dict with 'allowed', 'reason', and 'warnings'
        """
        warnings = []
        
        if self._global_halt.is_halted:
            return {
                'allowed': False,
                'reason': f'Trading halted: {self._global_halt.reason.value}',
                'warnings': []
            }
        
        channel_halt = self._channel_halts.get(channel_id)
        if channel_halt and channel_halt.is_halted:
            return {
                'allowed': False,
                'reason': f'Channel halted: {channel_halt.reason.value}',
                'warnings': []
            }
        
        if is_entry:
            current_count = self.get_position_count(channel_id)
            limit = self.get_position_limit(channel_id)
            if current_count >= limit:
                return {
                    'allowed': False,
                    'reason': f'Position limit reached: {current_count}/{limit}',
                    'warnings': []
                }
            if current_count >= limit * 0.8:
                warnings.append(f'Approaching position limit: {current_count}/{limit}')
        
        loss_status = self.get_daily_loss_status(channel_id)
        if loss_status['limit'] > 0:
            if loss_status['total_loss'] >= loss_status['limit']:
                return {
                    'allowed': False,
                    'reason': f"Daily loss limit reached: ${loss_status['total_loss']:.2f}/${loss_status['limit']:.2f}",
                    'warnings': []
                }
            if loss_status['limit_pct_used'] >= 80:
                warnings.append(f"Daily loss at {loss_status['limit_pct_used']:.0f}% of limit")
        
        return {
            'allowed': True,
            'reason': 'Trade allowed',
            'warnings': warnings
        }
    
    def record_error(self, channel_id: str, error_type: str = 'general'):
        """Record an error for threshold tracking."""
        key = f"{channel_id}_{error_type}"
        self._error_counts[key] += 1
        
        if self._error_counts[key] >= 10:
            self.halt_channel(channel_id, HaltReason.ERROR_THRESHOLD, 'system')
            print(f"[CIRCUIT BREAKER] ⚠️ Error threshold reached: channel={channel_id}, "
                  f"type={error_type}, count={self._error_counts[key]}")
    
    def reset_error_count(self, channel_id: str, error_type: str = 'general'):
        """Reset error count for a channel."""
        key = f"{channel_id}_{error_type}"
        self._error_counts[key] = 0
    
    def get_status(self) -> Dict[str, Any]:
        """Get overall circuit breaker status."""
        return {
            'global_halted': self._global_halt.is_halted,
            'global_halt_reason': self._global_halt.reason.value if self._global_halt.reason else None,
            'global_halted_at': self._global_halt.halted_at.isoformat() if self._global_halt.halted_at else None,
            'channel_halts': {
                k: {
                    'reason': v.reason.value if v.reason else None,
                    'halted_at': v.halted_at.isoformat() if v.halted_at else None
                }
                for k, v in self._channel_halts.items() if v.is_halted
            },
            'active_channels': len([h for h in self._channel_halts.values() if h.is_halted])
        }
    
    def reset_daily_limits(self):
        """Reset all daily loss trackers (call at midnight)."""
        today = date.today()
        for channel_id in list(self._daily_losses.keys()):
            if self._daily_losses[channel_id].date != today:
                del self._daily_losses[channel_id]
        print("[CIRCUIT BREAKER] Daily limits reset")


circuit_breaker = CircuitBreaker()
