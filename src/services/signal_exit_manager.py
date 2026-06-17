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
    get_effective_exit_strategy_mode,
    log_risk_event,
    find_matching_execution_lot,
    create_execution_closure,
    get_execution_lot_by_id,
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
        'webull_official': {'supports_replace': True, 'rate_limit_per_min': 60},
        'robinhood': {'supports_replace': False, 'rate_limit_per_min': 60},
        'webull': {'supports_replace': False, 'rate_limit_per_min': 60},
        'tastytrade': {'supports_replace': False, 'rate_limit_per_min': 100},
        'questrade': {'supports_replace': True, 'rate_limit_per_min': 60},
    }
    
    def __init__(self):
        self._managed_orders: Dict[int, ManagedOrder] = {}
        self._debouncer = EditDebouncer(debounce_ms=100)
        self._exit_processed: Dict[int, Dict] = {}
        self._sl_versions: Dict[int, int] = {}
        self._arbiter = ExitOrderArbiter()
        self._debounce_cache: Dict[str, datetime] = {}
    
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
        source: str = 'signal',
        broker: str = None,
        broker_instance: Any = None,
        symbol: str = None,
        quantity: int = None
    ) -> Dict[str, Any]:
        """
        Handle a stop loss update request.
        
        Uses optimistic locking to prevent race conditions.
        Routes to broker via replace or cancel+new based on capability.
        
        Args:
            signal_instance_id: Signal instance ID
            new_sl_price: New stop loss price
            exit_strategy_mode: 'signal', 'risk', or 'hybrid'
            source: Source of update ('signal', 'trailing', etc.)
            broker: Broker name for order modification
            broker_instance: Live broker adapter instance
            symbol: Ticker symbol (needed for cancel+new flows)
            quantity: Position quantity (needed for cancel+new flows)
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
        
        effective_broker = broker or managed.broker
        effective_symbol = symbol or getattr(managed, 'symbol', None)
        effective_qty = quantity or managed.remaining_qty
        
        if managed.sl_order_id:
            broker_result = await self._modify_broker_sl(
                broker=effective_broker,
                order_id=managed.sl_order_id,
                new_sl_price=new_sl_price,
                signal_instance_id=signal_instance_id,
                broker_instance=broker_instance,
                symbol=effective_symbol,
                quantity=effective_qty
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
    
    async def handle_partial_exit(
        self,
        signal_instance_id: int,
        closed_qty: int,
        fill_price: float,
        channel_id: str = None,
        broker: str = None,
        symbol: str = None,
        asset_type: str = None,
        exit_source: str = 'signal',
        strike: float = None,
        expiry: str = None,
        call_put: str = None
    ) -> Dict[str, Any]:
        """
        Handle partial exit (trim) with proper OMS state management and P&L recording.
        
        Routes through ExitOrderArbiter for precedence coordination.
        Updates ManagedOrder.remaining_qty and records to Execution P&L
        without finalizing the position (unless remaining becomes 0).
        
        Args:
            signal_instance_id: Signal instance ID
            closed_qty: Number of contracts/shares closed
            fill_price: Exit fill price
            channel_id: Channel ID for tracking
            broker: Broker name
            symbol: Ticker symbol
            asset_type: 'stock' or 'option'
            exit_source: 'signal', 'trailing', 'channel', etc.
            strike/expiry/call_put: Option details if applicable
        
        Returns:
            Dict with success status, remaining qty, and P&L info
        """
        managed = self._managed_orders.get(signal_instance_id)
        
        exit_strategy_mode = 'signal'
        if managed:
            exit_strategy_mode = managed.exit_strategy_mode
        elif channel_id:
            exit_strategy_mode = get_effective_exit_strategy_mode(channel_id)
        
        partial_key = f"partial_{signal_instance_id}_{closed_qty}_{fill_price}"
        if partial_key in self._debounce_cache:
            last_time = self._debounce_cache[partial_key]
            if (datetime.now() - last_time).total_seconds() < 0.5:
                print(f"[EXIT MANAGER] Partial exit debounced (duplicate within 500ms)")
                return {'success': False, 'reason': 'Debounced duplicate', 'skipped': True}
        self._debounce_cache[partial_key] = datetime.now()
        
        arbiter_result = await self._arbiter.request_exit(
            signal_instance_id=signal_instance_id,
            source=exit_source,
            exit_type='partial',
            exit_strategy_mode=exit_strategy_mode
        )
        
        if not arbiter_result.get('approved', True):
            print(f"[EXIT MANAGER] Partial exit blocked by arbiter: {arbiter_result.get('reason')}")
            return {
                'success': False,
                'reason': arbiter_result.get('reason'),
                'arbiter_blocked': True
            }
        
        if managed:
            old_remaining = managed.remaining_qty
            new_remaining = max(0, old_remaining - closed_qty)
            managed.remaining_qty = new_remaining
            managed.updated_at = datetime.now()
            
            print(f"[EXIT MANAGER] Partial exit: instance={signal_instance_id}, "
                  f"closed={closed_qty}, remaining={new_remaining}")
            
            fully_closed = new_remaining <= 0
            if fully_closed:
                managed.state = OrderState.FILLED
                self._exit_processed[signal_instance_id] = {
                    'source': exit_source,
                    'exit_type': 'partial_complete',
                    'processed_at': datetime.now().isoformat(),
                    'completed': True
                }
        else:
            old_remaining = closed_qty
            new_remaining = 0
            fully_closed = False
            print(f"[EXIT MANAGER] Partial exit for untracked position: {signal_instance_id}")
        
        pnl_result = None
        if broker and symbol and fill_price and closed_qty:
            pnl_result = await self.record_execution_pnl(
                broker=broker,
                symbol=symbol,
                asset_type=asset_type or ('option' if strike else 'stock'),
                closed_qty=closed_qty,
                fill_price=fill_price,
                channel_id=channel_id,
                exit_source=exit_source,
                strike=strike,
                expiry=expiry,
                call_put=call_put
            )
        
        log_risk_event(
            event_type='PARTIAL_EXIT',
            signal_instance_id=signal_instance_id,
            channel_id=channel_id,
            source=exit_source,
            details={
                'closed_qty': closed_qty,
                'fill_price': fill_price,
                'old_remaining': old_remaining,
                'new_remaining': new_remaining,
                'fully_closed': fully_closed,
                'arbiter_approved': True
            }
        )
        
        return {
            'success': True,
            'closed_qty': closed_qty,
            'remaining_qty': new_remaining,
            'fully_closed': fully_closed,
            'pnl_recorded': pnl_result.get('pnl_recorded') if pnl_result else False
        }
    
    async def handle_exit_signal(
        self,
        signal_instance_id: int,
        exit_type: str,
        reason: str = None,
        source: str = 'signal',
        channel_id: str = None,
        broker: str = None,
        symbol: str = None,
        asset_type: str = None,
        fill_price: float = None,
        closed_qty: int = None,
        broker_order_id: str = None,
        strike: float = None,
        expiry: str = None,
        call_put: str = None
    ) -> Dict[str, Any]:
        """
        Handle full exit signal with idempotency.
        
        Routes through ExitOrderArbiter for proper precedence and audit logging.
        Prevents double-execution of exits.
        
        If fill information is provided (broker, symbol, fill_price, closed_qty),
        also records the exit to Execution P&L for Two-Tier tracking.
        
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
            
            pnl_result = None
            if broker and symbol and fill_price and closed_qty:
                pnl_result = await self.record_execution_pnl(
                    broker=broker,
                    symbol=symbol,
                    asset_type=asset_type or ('option' if strike else 'stock'),
                    closed_qty=closed_qty,
                    fill_price=fill_price,
                    channel_id=channel_id,
                    exit_source=source,
                    broker_order_id=broker_order_id,
                    strike=strike,
                    expiry=expiry,
                    call_put=call_put
                )
                print(f"[EXIT MANAGER] P&L recorded: {pnl_result}")
            
            self._exit_processed[signal_instance_id]['processing'] = False
            self._exit_processed[signal_instance_id]['completed'] = True
            
            print(f"[EXIT MANAGER] Exit completed: instance={signal_instance_id}, "
                  f"type={exit_type}, source={source}, reason={reason}")
            
            return {
                'success': True,
                'exit_type': exit_type,
                'source': source,
                'reason': reason,
                'pnl_recorded': pnl_result.get('pnl_recorded') if pnl_result else False
            }
            
        except Exception as e:
            del self._exit_processed[signal_instance_id]
            raise
    
    async def _modify_broker_sl(
        self,
        broker: str,
        order_id: str,
        new_sl_price: float,
        signal_instance_id: int,
        broker_instance: Any = None,
        symbol: str = None,
        quantity: int = None
    ) -> Dict[str, Any]:
        """
        Modify broker SL order using broker-appropriate method.
        
        - Alpaca/Schwab/IBKR: Use REPLACE order
        - Robinhood/Webull/Tastytrade: Cancel + New order
        
        Args:
            broker: Broker name
            order_id: Original SL order ID
            new_sl_price: New stop loss price
            signal_instance_id: For tracking
            broker_instance: Broker adapter instance (optional)
            symbol: Ticker symbol (needed for cancel+new)
            quantity: Position quantity (needed for cancel+new)
        """
        import asyncio
        
        capabilities = self.BROKER_CAPABILITIES.get(broker, {})
        
        if not broker_instance:
            print(f"[EXIT MANAGER] No broker instance for {broker} SL modify - simulating")
            method = 'replace' if capabilities.get('supports_replace') else 'cancel_new'
            return {'success': True, 'method': method, 'simulated': True}
        
        loop = asyncio.get_event_loop()
        
        try:
            if capabilities.get('supports_replace'):
                print(f"[EXIT MANAGER] Using REPLACE for {broker} SL order {order_id}")
                
                if broker == 'alpaca':
                    if hasattr(broker_instance, 'replace_order'):
                        result = await loop.run_in_executor(None, lambda: broker_instance.replace_order(
                            order_id, stop_price=new_sl_price
                        ))
                        return {'success': True, 'method': 'replace', 'new_order_id': getattr(result, 'id', None)}
                
                elif broker == 'schwab':
                    if hasattr(broker_instance, 'replace_order'):
                        result = await loop.run_in_executor(None, lambda: broker_instance.replace_order(
                            order_id, stop_price=new_sl_price
                        ))
                        return {'success': True, 'method': 'replace', 'result': result}
                
                elif broker == 'ibkr':
                    if hasattr(broker_instance, 'modify_order'):
                        result = await broker_instance.modify_order(order_id, stop_price=new_sl_price)
                        return {'success': True, 'method': 'replace', 'result': result}

                elif broker == 'webull_official':
                    if hasattr(broker_instance, 'modify_order'):
                        result = await broker_instance.modify_order(order_id, stop_price=new_sl_price)
                        return {'success': result.get('success', False), 'method': 'replace', 'result': result}

                return {'success': True, 'method': 'replace', 'simulated': True}
            
            else:
                print(f"[EXIT MANAGER] Using CANCEL+NEW for {broker} SL order {order_id}")
                
                cancel_success = False
                new_order_id = None
                
                if hasattr(broker_instance, 'cancel_order'):
                    _cr = broker_instance.cancel_order(order_id)
                    if asyncio.iscoroutine(_cr):
                        cancel_result = await _cr
                    else:
                        cancel_result = await loop.run_in_executor(None, lambda: _cr)
                    if isinstance(cancel_result, dict):
                        cancel_success = cancel_result.get('success', False)
                    elif isinstance(cancel_result, bool):
                        cancel_success = cancel_result
                    elif hasattr(cancel_result, 'success'):
                        cancel_success = bool(cancel_result.success)
                    else:
                        cancel_success = False
                    
                    if cancel_success and symbol and quantity:
                        await asyncio.sleep(0.2)
                        
                        if hasattr(broker_instance, 'place_stop_order'):
                            stop_result = broker_instance.place_stop_order(
                                symbol=symbol, quantity=quantity, stop_price=new_sl_price, side='sell'
                            )
                            if asyncio.iscoroutine(stop_result) or asyncio.isfuture(stop_result):
                                new_order = await stop_result
                            else:
                                new_order = stop_result
                            new_order_id = getattr(new_order, 'order_id', None) or getattr(new_order, 'id', None) or (new_order.get('order_id') if isinstance(new_order, dict) else None) or (new_order.get('id') if isinstance(new_order, dict) else None)
                
                return {
                    'success': cancel_success,
                    'method': 'cancel_new',
                    'cancelled_order_id': order_id,
                    'new_order_id': new_order_id
                }
                
        except Exception as e:
            print(f"[EXIT MANAGER] Error modifying {broker} SL order: {e}")
            return {'success': False, 'method': None, 'error': str(e)}
    
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
    
    async def record_execution_pnl(
        self,
        broker: str,
        symbol: str,
        asset_type: str,
        closed_qty: int,
        fill_price: float,
        channel_id: str = None,
        exit_source: str = 'signal',
        broker_order_id: str = None,
        signal_exit_price: float = None,
        strike: float = None,
        expiry: str = None,
        call_put: str = None
    ) -> Dict[str, Any]:
        """
        Record execution P&L when a position is closed.
        
        This wires SignalExitManager exits to the Two-Tier P&L system:
        - Finds matching open execution lot (FIFO)
        - Creates execution_closure record with P&L
        - Updates execution_lot status (CLOSED/PARTIAL)
        
        Args:
            broker: Broker name (alpaca, schwab, etc.)
            symbol: Stock/option symbol
            asset_type: 'stock' or 'option'
            closed_qty: Number of shares/contracts closed
            fill_price: Actual fill price from broker
            channel_id: Discord channel ID
            exit_source: signal, trailing, channel, manual, circuit_breaker
            broker_order_id: Broker's order ID for the exit
            signal_exit_price: Expected price from signal (for slippage calc)
            strike, expiry, call_put: Option details if applicable
        
        Returns:
            Dict with success status, P&L details
        """
        exec_lot = find_matching_execution_lot(
            broker=broker,
            symbol=symbol,
            asset_type=asset_type,
            strike=strike,
            expiry=expiry,
            call_put=call_put
        )
        
        if not exec_lot:
            print(f"[EXIT MANAGER] No matching execution lot for {symbol}@{broker}")
            return {
                'success': False,
                'reason': f"No open execution lot found for {symbol}",
                'pnl_recorded': False
            }
        
        closure_id = create_execution_closure(
            execution_lot_id=exec_lot['id'],
            channel_id=channel_id or exec_lot.get('channel_id'),
            broker=broker,
            closed_qty=closed_qty,
            fill_price=fill_price,
            filled_at=datetime.now(),
            exit_source=exit_source,
            broker_order_id=broker_order_id,
            signal_exit_price=signal_exit_price
        )
        
        if closure_id:
            print(f"[EXIT MANAGER] Execution P&L recorded: lot={exec_lot['id']}, "
                  f"closure={closure_id}, qty={closed_qty}, price=${fill_price}")
            return {
                'success': True,
                'execution_lot_id': exec_lot['id'],
                'closure_id': closure_id,
                'pnl_recorded': True
            }
        else:
            return {
                'success': False,
                'reason': 'Failed to create execution closure',
                'pnl_recorded': False
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
