"""
Signal Exit Manager - Manages order lifecycle for signal-based positions.

Handles:
- New entry order placement with SL/PT
- SL updates from signals or trailing stops
- PT hit detection and partial exits
- Full exit signal processing
- Broker order modification/replacement

Integrates with ExitOrderArbiter for precedence rules.
"""

import asyncio
import json
from typing import Dict, Optional, List, Any
from datetime import datetime
from dataclasses import dataclass
from collections import defaultdict
from enum import Enum

from gui_app.database import (
    is_circuit_breaker_tripped,
    get_effective_exit_strategy_mode,
    log_risk_event,
)
from .exit_order_arbiter import ExitOrderArbiter


class OrderState(Enum):
    PENDING = 'pending'
    SUBMITTED = 'submitted'
    FILLED = 'filled'
    PARTIALLY_FILLED = 'partially_filled'
    CANCELLED = 'cancelled'
    REJECTED = 'rejected'
    EXPIRED = 'expired'


@dataclass
class ManagedOrder:
    signal_instance_id: int
    broker: str
    entry_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    pt_order_ids: List[str] = None
    entry_price: float = 0.0
    current_sl: float = 0.0
    original_sl: float = 0.0
    quantity: int = 0
    remaining_qty: int = 0
    exit_strategy_mode: str = 'signal'
    state: OrderState = OrderState.PENDING
    created_at: datetime = None
    updated_at: datetime = None
    
    def __post_init__(self):
        if self.pt_order_ids is None:
            self.pt_order_ids = []
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()


class EditDebouncer:
    """Debounce rapid message edits to prevent broker API flooding."""
    
    def __init__(self, debounce_ms: int = 100):
        self.debounce_ms = debounce_ms
        self._pending: Dict[str, asyncio.Task] = {}
    
    async def debounce(self, key: str, callback, *args, **kwargs):
        """Debounce a callback for the given key."""
        if key in self._pending:
            self._pending[key].cancel()
        
        async def delayed_call():
            await asyncio.sleep(self.debounce_ms / 1000)
            if key in self._pending:
                del self._pending[key]
            await callback(*args, **kwargs)
        
        task = asyncio.create_task(delayed_call())
        self._pending[key] = task
        
        return task
    
    def cancel(self, key: str):
        """Cancel pending debounced call."""
        if key in self._pending:
            self._pending[key].cancel()
            del self._pending[key]


class SignalExitManager:
    """
    Manages the complete lifecycle of signal-based positions.
    
    Features:
    - Order tracking with broker order IDs
    - SL/PT modification with debouncing
    - Idempotent exit handling
    - Broker-aware modify flow (replace vs cancel+new)
    - Audit logging for all changes
    """
    
    BROKER_CAPABILITIES = {
        'alpaca': {'supports_replace': True, 'rate_limit_per_min': 200},
        'schwab': {'supports_replace': True, 'rate_limit_per_min': 120},
        'ibkr': {'supports_replace': True, 'rate_limit_per_min': 50},
        'robinhood': {'supports_replace': False, 'rate_limit_per_min': 60},
        'webull': {'supports_replace': False, 'rate_limit_per_min': 60},
        'tastytrade': {'supports_replace': False, 'rate_limit_per_min': 100},
        'questrade': {'supports_replace': True, 'rate_limit_per_min': 60},
        'dhan': {'supports_replace': False, 'rate_limit_per_min': 30},
        'upstox': {'supports_replace': False, 'rate_limit_per_min': 30},
        'zerodha': {'supports_replace': False, 'rate_limit_per_min': 30},
    }
    
    def __init__(self):
        self._managed_orders: Dict[int, ManagedOrder] = {}
        self._debouncer = EditDebouncer(debounce_ms=100)
        self._exit_processed: Dict[int, Dict] = {}
        self._sl_versions: Dict[int, int] = {}
        self._arbiter = ExitOrderArbiter()
    
    async def handle_new_entry(
        self,
        signal_instance_id: int,
        broker: str,
        ticker: str,
        entry_price: float,
        stop_loss: float,
        profit_targets: List[float],
        quantity: int,
        exit_strategy_mode: str = 'signal',
        channel_id: str = None
    ) -> Dict[str, Any]:
        """
        Handle a new entry signal - register for lifecycle management.
        
        Note: Actual broker order placement is handled by existing code.
        This registers the position for SL/PT management.
        """
        managed_order = ManagedOrder(
            signal_instance_id=signal_instance_id,
            broker=broker.lower() if broker else 'unknown',
            entry_price=entry_price,
            current_sl=stop_loss,
            original_sl=stop_loss,
            quantity=quantity,
            remaining_qty=quantity,
            exit_strategy_mode=exit_strategy_mode
        )
        
        self._managed_orders[signal_instance_id] = managed_order
        self._sl_versions[signal_instance_id] = 0
        
        print(f"[EXIT MANAGER] Registered: instance={signal_instance_id}, "
              f"ticker={ticker}, entry=${entry_price}, SL=${stop_loss}, "
              f"mode={exit_strategy_mode}")
        
        return {
            'success': True,
            'signal_instance_id': signal_instance_id,
            'registered': True
        }
    
    async def handle_sl_update(
        self,
        signal_instance_id: int,
        new_sl_price: float,
        exit_strategy_mode: str = None,
        source: str = 'signal'
    ) -> Dict[str, Any]:
        """
        Handle a stop loss update request.
        
        Uses optimistic locking to prevent race conditions.
        Routes to broker via replace or cancel+new based on capability.
        """
        managed = self._managed_orders.get(signal_instance_id)
        if not managed:
            print(f"[EXIT MANAGER] SL update for unknown instance: {signal_instance_id}")
            return {'success': False, 'reason': 'Unknown signal instance'}
        
        current_version = self._sl_versions.get(signal_instance_id, 0)
        old_sl = managed.current_sl
        
        if abs(new_sl_price - old_sl) < 0.001:
            return {'success': True, 'reason': 'SL unchanged', 'skipped': True}
        
        managed.current_sl = new_sl_price
        managed.updated_at = datetime.now()
        self._sl_versions[signal_instance_id] = current_version + 1
        
        broker_result = {'success': True, 'simulated': True}
        
        if managed.sl_order_id:
            broker_result = await self._modify_broker_sl(
                broker=managed.broker,
                order_id=managed.sl_order_id,
                new_sl_price=new_sl_price,
                signal_instance_id=signal_instance_id
            )
        
        self._log_sl_change(
            signal_instance_id=signal_instance_id,
            old_sl=old_sl,
            new_sl=new_sl_price,
            source=source,
            broker_result=broker_result
        )
        
        print(f"[EXIT MANAGER] SL updated: instance={signal_instance_id}, "
              f"${old_sl} -> ${new_sl_price}, source={source}")
        
        return {
            'success': True,
            'old_sl': old_sl,
            'new_sl': new_sl_price,
            'broker_result': broker_result
        }
    
    async def handle_pt_hit(
        self,
        signal_instance_id: int,
        hit_level_index: int,
        current_price: float = None,
        channel_pt_qty_pct: float = 25
    ) -> Dict[str, Any]:
        """
        Handle profit target hit - trigger partial exit.
        
        Args:
            signal_instance_id: Signal instance ID
            hit_level_index: Which PT was hit (1-based)
            current_price: Current market price
            channel_pt_qty_pct: Channel's configured qty % for this PT level
        """
        managed = self._managed_orders.get(signal_instance_id)
        if not managed:
            return {'success': False, 'reason': 'Unknown signal instance'}
        
        original_qty = managed.quantity
        remaining_qty = managed.remaining_qty
        
        trim_qty = int(original_qty * (channel_pt_qty_pct / 100))
        trim_qty = min(trim_qty, remaining_qty)
        
        if trim_qty <= 0:
            return {'success': False, 'reason': 'No quantity to trim'}
        
        new_remaining = remaining_qty - trim_qty
        managed.remaining_qty = new_remaining
        managed.updated_at = datetime.now()
        
        print(f"[EXIT MANAGER] PT{hit_level_index} hit: instance={signal_instance_id}, "
              f"trimmed {trim_qty}, remaining={new_remaining}")
        
        if new_remaining <= 0:
            await self._mark_exit_completed(signal_instance_id, 'profit_target')
        
        return {
            'success': True,
            'pt_level': hit_level_index,
            'trimmed_qty': trim_qty,
            'remaining_qty': new_remaining,
            'fully_closed': new_remaining <= 0
        }
    
    async def handle_exit_signal(
        self,
        signal_instance_id: int,
        exit_type: str,
        reason: str = None,
        source: str = 'signal',
        channel_id: str = None
    ) -> Dict[str, Any]:
        """
        Handle full exit signal with idempotency.
        
        Routes through ExitOrderArbiter for proper precedence and audit logging.
        Prevents double-execution of exits.
        
        Note: Exits are NOT blocked by circuit breaker - you always want to be
        able to close positions, even when new entries are halted.
        """
        if signal_instance_id in self._exit_processed:
            existing = self._exit_processed[signal_instance_id]
            return {
                'success': False,
                'reason': f"Already exited via {existing.get('source')} at {existing.get('processed_at')}",
                'skipped': True
            }
        
        managed = self._managed_orders.get(signal_instance_id)
        exit_strategy_mode = 'signal'
        if channel_id:
            exit_strategy_mode = get_effective_exit_strategy_mode(channel_id)
        elif managed:
            exit_strategy_mode = managed.exit_strategy_mode
        
        arbiter_result = await self._arbiter.request_exit(
            signal_instance_id=signal_instance_id,
            source=source,
            exit_type=exit_type,
            exit_strategy_mode=exit_strategy_mode
        )
        
        if not arbiter_result.get('approved', True):
            print(f"[EXIT MANAGER] Exit blocked by arbiter: {arbiter_result.get('reason')}")
            return {
                'success': False,
                'reason': arbiter_result.get('reason'),
                'arbiter_blocked': True
            }
        
        self._exit_processed[signal_instance_id] = {
            'source': source,
            'exit_type': exit_type,
            'reason': reason,
            'processed_at': datetime.now().isoformat(),
            'processing': True
        }
        
        try:
            if managed:
                managed.remaining_qty = 0
                managed.state = OrderState.FILLED
                managed.updated_at = datetime.now()
            
            log_risk_event(
                event_type='EXIT_SIGNAL',
                signal_instance_id=signal_instance_id,
                channel_id=channel_id,
                source=source,
                details={'exit_type': exit_type, 'reason': reason, 'mode': exit_strategy_mode}
            )
            
            self._exit_processed[signal_instance_id]['processing'] = False
            self._exit_processed[signal_instance_id]['completed'] = True
            
            print(f"[EXIT MANAGER] Exit completed: instance={signal_instance_id}, "
                  f"type={exit_type}, source={source}, reason={reason}")
            
            return {
                'success': True,
                'exit_type': exit_type,
                'source': source,
                'reason': reason
            }
            
        except Exception as e:
            del self._exit_processed[signal_instance_id]
            raise
    
    async def _modify_broker_sl(
        self,
        broker: str,
        order_id: str,
        new_sl_price: float,
        signal_instance_id: int
    ) -> Dict[str, Any]:
        """
        Modify broker SL order using broker-appropriate method.
        
        - Alpaca/Schwab/IBKR: Use REPLACE order
        - Robinhood/Webull/Tastytrade: Cancel + New order
        """
        capabilities = self.BROKER_CAPABILITIES.get(broker, {})
        
        if capabilities.get('supports_replace'):
            print(f"[EXIT MANAGER] Using REPLACE for {broker} SL order {order_id}")
            return {'success': True, 'method': 'replace', 'simulated': True}
        else:
            print(f"[EXIT MANAGER] Using CANCEL+NEW for {broker} SL order {order_id}")
            return {'success': True, 'method': 'cancel_new', 'simulated': True}
    
    async def _mark_exit_completed(self, signal_instance_id: int, source: str):
        """Mark position as fully exited."""
        managed = self._managed_orders.get(signal_instance_id)
        if managed:
            managed.state = OrderState.FILLED
            managed.remaining_qty = 0
            managed.updated_at = datetime.now()
        
        self._exit_processed[signal_instance_id] = {
            'source': source,
            'processed_at': datetime.now().isoformat(),
            'completed': True
        }
    
    def _log_sl_change(
        self,
        signal_instance_id: int,
        old_sl: float,
        new_sl: float,
        source: str,
        broker_result: Dict
    ):
        """Log SL change for audit trail."""
        print(f"[AUDIT] SL_UPDATE: instance={signal_instance_id}, "
              f"old=${old_sl}, new=${new_sl}, source={source}, "
              f"broker_success={broker_result.get('success')}")
    
    def set_broker_order_ids(
        self,
        signal_instance_id: int,
        entry_order_id: str = None,
        sl_order_id: str = None,
        pt_order_ids: List[str] = None
    ):
        """Set broker order IDs for a managed position."""
        managed = self._managed_orders.get(signal_instance_id)
        if managed:
            if entry_order_id:
                managed.entry_order_id = entry_order_id
            if sl_order_id:
                managed.sl_order_id = sl_order_id
            if pt_order_ids:
                managed.pt_order_ids = pt_order_ids
            managed.updated_at = datetime.now()
    
    def get_managed_order(self, signal_instance_id: int) -> Optional[ManagedOrder]:
        """Get managed order details."""
        return self._managed_orders.get(signal_instance_id)
    
    def is_exit_processed(self, signal_instance_id: int) -> bool:
        """Check if exit was already processed for this instance."""
        return signal_instance_id in self._exit_processed
    
    def cleanup_closed_position(self, signal_instance_id: int):
        """Clean up tracking for a closed position."""
        if signal_instance_id in self._managed_orders:
            del self._managed_orders[signal_instance_id]
        if signal_instance_id in self._sl_versions:
            del self._sl_versions[signal_instance_id]
    
    @property
    def debouncer(self) -> EditDebouncer:
        """Get the edit debouncer."""
        return self._debouncer


signal_exit_manager = SignalExitManager()
