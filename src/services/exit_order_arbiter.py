"""
Exit Order Arbiter - Arbitrates between signal-driven and risk-driven exit requests.

Implements precedence rules for exit strategy modes:
- SIGNAL: Exits follow trader signals exactly
- RISK: Exits follow channel risk settings (trailing stop, etc.)
- HYBRID: Uses TIGHTER protection (never less protected)

Critical Rule: SL can NEVER be lowered in hybrid mode (only raised)
"""

import asyncio
from typing import Dict, Optional, Any
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field


class ExitSource(Enum):
    SIGNAL = 'signal'
    TRAILING = 'trailing'
    CHANNEL = 'channel'
    MANUAL = 'manual'
    CIRCUIT_BREAKER = 'circuit_breaker'


class ExitStrategyMode(Enum):
    SIGNAL = 'signal'
    RISK = 'risk'
    HYBRID = 'hybrid'


@dataclass
class ArbiterResult:
    approved: bool
    final_sl: float
    reason: str
    source_used: Optional[str] = None
    requires_broker_update: bool = False


class ExitOrderArbiter:
    """
    Arbitrates between signal-driven and risk-driven exit requests.
    
    Precedence Rules:
    1. Manual override > All (user can always force exit)
    2. Circuit breaker > All (emergency halt)
    3. In SIGNAL mode: Signal SL always wins, trailing/channel ignored
    4. In RISK mode: Trailing/channel SL wins, signal ignored
    5. In HYBRID mode: TIGHTER (higher for long, lower for short) SL wins
    6. CRITICAL: SL can NEVER be lowered in hybrid mode (only raised)
    """
    
    PRECEDENCE_MATRIX = {
        ExitStrategyMode.SIGNAL: {
            ExitSource.SIGNAL: 100,
            ExitSource.TRAILING: 0,
            ExitSource.CHANNEL: 0,
            ExitSource.MANUAL: 999,
            ExitSource.CIRCUIT_BREAKER: 1000,
        },
        ExitStrategyMode.RISK: {
            ExitSource.SIGNAL: 0,
            ExitSource.TRAILING: 100,
            ExitSource.CHANNEL: 50,
            ExitSource.MANUAL: 999,
            ExitSource.CIRCUIT_BREAKER: 1000,
        },
        ExitStrategyMode.HYBRID: {
            ExitSource.SIGNAL: 100,
            ExitSource.TRAILING: 100,
            ExitSource.CHANNEL: 50,
            ExitSource.MANUAL: 999,
            ExitSource.CIRCUIT_BREAKER: 1000,
        },
    }
    
    def __init__(self):
        self._pending_requests: Dict[int, Dict] = {}
        self._last_decisions: Dict[int, ArbiterResult] = {}
    
    async def request_sl_update(
        self,
        signal_instance_id: int,
        source: str,
        new_sl_price: float,
        current_sl_price: float,
        exit_strategy_mode: str,
        position_direction: str = 'long'
    ) -> Dict[str, Any]:
        """
        Request an SL update. Returns approval status and final SL.
        
        Args:
            signal_instance_id: ID of the signal instance
            source: 'signal', 'trailing', 'channel', 'manual', 'circuit_breaker'
            new_sl_price: Requested new stop loss price
            current_sl_price: Current stop loss price
            exit_strategy_mode: 'signal', 'risk', or 'hybrid'
            position_direction: 'long' or 'short'
        
        Returns:
            Dict with 'approved', 'final_sl', 'reason', 'source_used'
        """
        try:
            source_enum = ExitSource(source.lower())
        except ValueError:
            return {
                'approved': False,
                'final_sl': current_sl_price,
                'reason': f'Unknown source: {source}',
                'source_used': None
            }
        
        try:
            mode_enum = ExitStrategyMode(exit_strategy_mode.lower())
        except ValueError:
            mode_enum = ExitStrategyMode.SIGNAL
        
        if source_enum == ExitSource.CIRCUIT_BREAKER:
            return {
                'approved': True,
                'final_sl': new_sl_price,
                'reason': 'Circuit breaker override',
                'source_used': 'circuit_breaker',
                'requires_broker_update': True
            }
        
        if source_enum == ExitSource.MANUAL:
            return {
                'approved': True,
                'final_sl': new_sl_price,
                'reason': 'Manual override',
                'source_used': 'manual',
                'requires_broker_update': True
            }
        
        precedence = self.PRECEDENCE_MATRIX.get(mode_enum, {})
        source_priority = precedence.get(source_enum, 0)
        
        if source_priority == 0:
            return {
                'approved': False,
                'final_sl': current_sl_price,
                'reason': f'{mode_enum.value} mode: {source} SL ignored',
                'source_used': None,
                'requires_broker_update': False
            }
        
        if mode_enum == ExitStrategyMode.HYBRID:
            if position_direction == 'long':
                is_tighter = new_sl_price > current_sl_price
            else:
                is_tighter = new_sl_price < current_sl_price
            
            if not is_tighter:
                return {
                    'approved': False,
                    'final_sl': current_sl_price,
                    'reason': f'Hybrid mode: {source} SL (${new_sl_price}) not tighter than current (${current_sl_price})',
                    'source_used': None,
                    'requires_broker_update': False
                }
        
        if position_direction == 'long' and new_sl_price < current_sl_price:
            if mode_enum != ExitStrategyMode.SIGNAL:
                return {
                    'approved': False,
                    'final_sl': current_sl_price,
                    'reason': f'SL cannot be lowered for long position (${new_sl_price} < ${current_sl_price})',
                    'source_used': None,
                    'requires_broker_update': False
                }
        
        result = {
            'approved': True,
            'final_sl': new_sl_price,
            'reason': f'{source} SL approved: ${current_sl_price} -> ${new_sl_price}',
            'source_used': source,
            'requires_broker_update': True
        }
        
        self._last_decisions[signal_instance_id] = ArbiterResult(**result)
        
        print(f"[ARBITER] SL update approved: instance={signal_instance_id}, "
              f"source={source}, mode={exit_strategy_mode}, "
              f"${current_sl_price} -> ${new_sl_price}")
        
        return result
    
    async def request_exit(
        self,
        signal_instance_id: int,
        source: str,
        exit_type: str,
        exit_strategy_mode: str,
        reason: str = None
    ) -> Dict[str, Any]:
        """
        Request a full position exit.
        
        Args:
            signal_instance_id: ID of the signal instance
            source: 'signal', 'trailing', 'channel', 'manual', 'circuit_breaker'
            exit_type: 'stop_loss', 'profit_target', 'manual', 'signal'
            exit_strategy_mode: 'signal', 'risk', or 'hybrid'
            reason: Optional reason for exit
        
        Returns:
            Dict with 'approved', 'reason'
        """
        try:
            source_enum = ExitSource(source.lower())
        except ValueError:
            return {
                'approved': False,
                'reason': f'Unknown source: {source}'
            }
        
        try:
            mode_enum = ExitStrategyMode(exit_strategy_mode.lower())
        except ValueError:
            mode_enum = ExitStrategyMode.SIGNAL
        
        if source_enum in [ExitSource.MANUAL, ExitSource.CIRCUIT_BREAKER]:
            return {
                'approved': True,
                'reason': f'{source} exit approved',
                'source_used': source
            }
        
        precedence = self.PRECEDENCE_MATRIX.get(mode_enum, {})
        source_priority = precedence.get(source_enum, 0)
        
        if source_priority == 0:
            return {
                'approved': False,
                'reason': f'{mode_enum.value} mode: {source} exit ignored',
                'source_used': None
            }
        
        print(f"[ARBITER] Exit approved: instance={signal_instance_id}, "
              f"source={source}, type={exit_type}, reason={reason}")
        
        return {
            'approved': True,
            'reason': f'{source} exit approved: {reason or exit_type}',
            'source_used': source
        }
    
    async def request_partial_exit(
        self,
        signal_instance_id: int,
        source: str,
        quantity_pct: float,
        exit_strategy_mode: str,
        pt_level: int = None
    ) -> Dict[str, Any]:
        """
        Request a partial position exit (trim).
        
        Args:
            signal_instance_id: ID of the signal instance
            source: 'signal', 'trailing', 'channel', 'manual'
            quantity_pct: Percentage of position to exit (0-100)
            exit_strategy_mode: 'signal', 'risk', or 'hybrid'
            pt_level: Optional profit target level (1, 2, 3, 4)
        
        Returns:
            Dict with 'approved', 'quantity_pct', 'reason'
        """
        try:
            source_enum = ExitSource(source.lower())
        except ValueError:
            return {
                'approved': False,
                'quantity_pct': 0,
                'reason': f'Unknown source: {source}'
            }
        
        try:
            mode_enum = ExitStrategyMode(exit_strategy_mode.lower())
        except ValueError:
            mode_enum = ExitStrategyMode.SIGNAL
        
        if source_enum == ExitSource.MANUAL:
            return {
                'approved': True,
                'quantity_pct': quantity_pct,
                'reason': 'Manual partial exit approved'
            }
        
        precedence = self.PRECEDENCE_MATRIX.get(mode_enum, {})
        source_priority = precedence.get(source_enum, 0)
        
        if source_priority == 0:
            return {
                'approved': False,
                'quantity_pct': 0,
                'reason': f'{mode_enum.value} mode: {source} partial exit ignored'
            }
        
        print(f"[ARBITER] Partial exit approved: instance={signal_instance_id}, "
              f"source={source}, qty={quantity_pct}%, pt_level={pt_level}")
        
        return {
            'approved': True,
            'quantity_pct': quantity_pct,
            'reason': f'{source} partial exit approved',
            'pt_level': pt_level
        }
    
    def get_last_decision(self, signal_instance_id: int) -> Optional[ArbiterResult]:
        """Get the last decision for a signal instance."""
        return self._last_decisions.get(signal_instance_id)
    
    def clear_decisions(self, signal_instance_id: int):
        """Clear cached decisions for a signal instance (on position close)."""
        if signal_instance_id in self._last_decisions:
            del self._last_decisions[signal_instance_id]
        if signal_instance_id in self._pending_requests:
            del self._pending_requests[signal_instance_id]


exit_order_arbiter = ExitOrderArbiter()
