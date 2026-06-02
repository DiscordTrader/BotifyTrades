"""
UnfilledOrderChaser - Industry-grade unfilled order management
Monitors pending exit orders and replaces stale ones with mid-price orders for better fills.

Key Features:
- Tracks risk-triggered STC orders
- Monitors pending orders across all brokers
- Detects stale orders (unfilled beyond timeout threshold)
- Calculates mid-price from current bid/ask spread
- Cancels stale orders and replaces with mid-price limit orders
- Configurable chase timeout and retry limits
"""

import asyncio
import inspect
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

try:
    from gui_app.database import Database
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


class OrderChaseStatus(Enum):
    PENDING = "pending"
    CHASING = "chasing"
    REPLACED = "replaced"
    FILLED = "filled"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TrackedExitOrder:
    order_id: str
    broker_id: str
    symbol: str
    asset_type: str
    quantity: float
    original_price: float
    action: str
    placed_at: datetime
    position_key: str
    strike: Optional[float] = None
    expiry: Optional[str] = None
    call_put: Optional[str] = None
    status: OrderChaseStatus = OrderChaseStatus.PENDING
    chase_attempts: int = 0
    last_chase_at: Optional[datetime] = None
    replacement_order_id: Optional[str] = None
    final_fill_price: Optional[float] = None
    is_risk_order: bool = True


@dataclass
class TrackedEntryOrder:
    """Track pending BTO (entry) orders for chase monitoring"""
    order_id: str
    broker_id: str
    symbol: str
    asset_type: str
    quantity: float
    original_price: float
    action: str  # BTO or BUY
    placed_at: datetime
    channel_id: Optional[str] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None
    call_put: Optional[str] = None
    entry_range_high: Optional[float] = None  # Upper limit of entry range from signal
    slippage_max_pct: Optional[float] = None  # Per-channel slippage limit %
    signal_price: Optional[float] = None  # Original signal price for slippage calc
    timeout_minutes: Optional[int] = None  # Per-channel timeout in minutes (order_timeout_minutes)
    limit_cap_price: Optional[float] = None  # Limit cap price (absolute ceiling from conditional order)
    stop_loss_price: Optional[float] = None  # Bracket SL price (preserved for replacement orders)
    profit_target_price: Optional[float] = None  # Bracket PT price (preserved for replacement orders)
    status: OrderChaseStatus = OrderChaseStatus.PENDING
    chase_attempts: int = 0
    last_chase_at: Optional[datetime] = None
    replacement_order_id: Optional[str] = None
    final_fill_price: Optional[float] = None
    
    @property
    def max_chase_price(self) -> Optional[float]:
        """Calculate maximum allowed chase price.
        
        Priority: 
        1. Limit cap price (absolute ceiling from conditional order, cannot be exceeded)
        2. Slippage limit (percentage-based ceiling for normal signals)
        3. Entry range high (from signal entry range)
        
        If limit_cap_price is set, it acts as an absolute ceiling.
        The returned value is the minimum of all applicable limits.
        """
        limits = []
        
        # Limit cap price is an absolute ceiling (from conditional orders)
        if self.limit_cap_price:
            limits.append(self.limit_cap_price)
        
        # Slippage limit as a percentage-based ceiling
        if self.slippage_max_pct and self.signal_price:
            max_with_slippage = self.signal_price * (1 + self.slippage_max_pct / 100)
            limits.append(round(max_with_slippage, 2))
        
        # Entry range high as a fallback
        if self.entry_range_high:
            limits.append(self.entry_range_high)
        
        # Return the most restrictive (lowest) limit
        if limits:
            return min(limits)
        
        return None


def _to_price(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in ('price', 'bid', 'last', 'mid', 'latestPrice'):
            v = value.get(key)
            if v is not None and not isinstance(v, dict):
                try:
                    f = float(v)
                    if f > 0:
                        return f
                except (TypeError, ValueError):
                    continue
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class UnfilledOrderChaser:
    """
    Industry-grade unfilled order management service.
    
    Monitors pending exit AND entry orders and replaces stale ones with better prices.
    - Exit orders: Replaced with mid-price for balanced fills
    - Entry orders: Replaced with ask price for aggressive fills
    """
    
    DEFAULT_CHASE_TIMEOUT_SECONDS = 1
    DEFAULT_MAX_CHASE_ATTEMPTS = 3
    DEFAULT_POLL_INTERVAL_SECONDS = 0.5
    DEFAULT_CANCEL_ON_MAX_ATTEMPTS = True
    
    def __init__(
        self,
        broker_manager,
        chase_timeout_seconds: float = DEFAULT_CHASE_TIMEOUT_SECONDS,
        max_chase_attempts: int = DEFAULT_MAX_CHASE_ATTEMPTS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        cancel_entry_on_max_attempts: bool = DEFAULT_CANCEL_ON_MAX_ATTEMPTS
    ):
        self.broker_manager = broker_manager
        self.chase_timeout = timedelta(seconds=chase_timeout_seconds)
        self.max_chase_attempts = max_chase_attempts
        self.poll_interval = poll_interval_seconds
        self.cancel_entry_on_max_attempts = cancel_entry_on_max_attempts
        
        self._tracked_orders: Dict[str, TrackedExitOrder] = {}
        self._tracked_entry_orders: Dict[str, TrackedEntryOrder] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._enabled = True
        self._entry_chase_enabled = True
        
        print(f"[ORDER_CHASER] Initialized (timeout={chase_timeout_seconds}s, max_attempts={max_chase_attempts}, cancel_on_fail={cancel_entry_on_max_attempts})")

    def _get_position_lock(self, position_key: str):
        try:
            bot = self.broker_manager
            rm = None
            if bot:
                rm = getattr(bot, '_risk_manager', None) or getattr(bot, 'risk_manager', None)
            if rm and hasattr(rm, '_broker_stop_locks'):
                if position_key not in rm._broker_stop_locks:
                    rm._broker_stop_locks[position_key] = asyncio.Lock()
                return rm._broker_stop_locks[position_key]
        except Exception:
            pass
        return None

    def _sync_broker_pt_order_id(self, position_key: str, old_order_id: str, new_order_id: str):
        try:
            bot = self.broker_manager
            rm = None
            if bot:
                rm = getattr(bot, '_risk_manager', None) or getattr(bot, 'risk_manager', None)
            if rm and hasattr(rm, 'cache'):
                pos_cache = rm.cache.get(position_key)
                if pos_cache:
                    current_id = getattr(pos_cache, 'broker_pt_order_id', None)
                    if current_id == old_order_id or current_id is None:
                        pos_cache.broker_pt_order_id = new_order_id
                        print(f"[ORDER_CHASER] ✓ Synced broker_pt_order_id: {old_order_id} → {new_order_id} for {position_key}")
                    else:
                        print(f"[ORDER_CHASER] ⚠️ PT order ID mismatch: expected {old_order_id}, found {current_id} — skipping sync (position_monitor may have updated)")
        except Exception as e:
            print(f"[ORDER_CHASER] ⚠️ Could not sync broker_pt_order_id: {e}")

    async def _atomic_pt_id_swap(self, position_key: str, old_order_id: str, new_order_id: str):
        pos_lock = self._get_position_lock(position_key)
        if pos_lock:
            async with pos_lock:
                self._sync_broker_pt_order_id(position_key, old_order_id, new_order_id)
        else:
            self._sync_broker_pt_order_id(position_key, old_order_id, new_order_id)

    def _update_db_trade_order_id(self, old_order_id: str, new_order_id: str, symbol: str):
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE trades SET order_id = ? WHERE order_id = ? AND status = 'PENDING'",
                (new_order_id, old_order_id)
            )
            if cursor.rowcount > 0:
                conn.commit()
                print(f"[ORDER_CHASER] ✓ Updated DB trade order_id: {old_order_id} → {new_order_id} ({symbol})")
            else:
                conn.commit()
                print(f"[ORDER_CHASER] ⚠️ No PENDING trade found with order_id {old_order_id} to update ({symbol})")
        except Exception as e:
            print(f"[ORDER_CHASER] ⚠️ Failed to update DB trade order_id: {e}")

    def is_actively_chasing_order(self, order_id: str) -> bool:
        if order_id in self._tracked_entry_orders:
            entry = self._tracked_entry_orders[order_id]
            if entry.status in (OrderChaseStatus.PENDING, OrderChaseStatus.CHASING):
                return True
        return False

    def is_chasing_symbol(self, symbol: str, broker: str) -> bool:
        symbol_upper = symbol.upper()
        broker_upper = broker.upper()
        for oid, entry in self._tracked_entry_orders.items():
            if (entry.symbol.upper() == symbol_upper and
                entry.broker_id.upper() == broker_upper and
                entry.status in (OrderChaseStatus.PENDING, OrderChaseStatus.CHASING, OrderChaseStatus.REPLACED)):
                return True
        return False

    async def _atomic_pt_id_clear_and_cancel(self, position_key: str, order_id: str, broker, asset_type: str, broker_id: str) -> bool:
        pos_lock = self._get_position_lock(position_key)
        if pos_lock:
            async with pos_lock:
                self._set_pt_order_id(position_key, order_id, '_CHASER_CANCELLING_')
                cancel_ok = await self._cancel_broker_order(broker, order_id, asset_type, broker_id)
                if not cancel_ok:
                    self._set_pt_order_id(position_key, '_CHASER_CANCELLING_', order_id)
                return cancel_ok
        else:
            self._set_pt_order_id(position_key, order_id, '_CHASER_CANCELLING_')
            cancel_ok = await self._cancel_broker_order(broker, order_id, asset_type, broker_id)
            if not cancel_ok:
                self._set_pt_order_id(position_key, '_CHASER_CANCELLING_', order_id)
            return cancel_ok

    def _set_pt_order_id(self, position_key: str, expected_current: str, new_value: str):
        try:
            bot = self.broker_manager
            rm = None
            if bot:
                rm = getattr(bot, '_risk_manager', None) or getattr(bot, 'risk_manager', None)
            if rm and hasattr(rm, 'cache'):
                pos_cache = rm.cache.get(position_key)
                if pos_cache:
                    current = getattr(pos_cache, 'broker_pt_order_id', None)
                    if current == expected_current or current is None:
                        pos_cache.broker_pt_order_id = new_value if new_value != '_CHASER_CANCELLING_' else None
        except Exception:
            pass

    async def _wait_for_cancel_settlement(self, broker, order_id: str, max_checks: int = 3) -> tuple:
        for i in range(max_checks):
            await asyncio.sleep(0.2)
            pending = []
            if hasattr(broker, 'get_pending_orders'):
                _result = broker.get_pending_orders()
                if inspect.iscoroutine(_result):
                    pending = await _result
                else:
                    pending = _result
            still_active = any(
                str(po.get('order_id', '')) == str(order_id)
                for po in (pending or [])
            )
            if not still_active:
                return pending, True
            if i < max_checks - 1:
                print(f"[ORDER_CHASER] ⚠️ Order {order_id} still active after cancel (check {i+1}/{max_checks}) — retrying")
        return pending, False

    def _get_remaining_qty(self, pending_orders: list, order_id: str, original_qty: int) -> int:
        """Extract remaining unfilled quantity from pending order data.
        Returns original_qty if no partial fill info is available (safe default)."""
        try:
            for po in (pending_orders or []):
                if str(po.get('order_id', '')) != str(order_id):
                    continue
                filled = 0
                for key in ('filled_quantity', 'filledQuantity', 'filled_qty', 'executedQty', 'filledQty'):
                    val = po.get(key)
                    if val is not None and int(val) > 0:
                        filled = int(val)
                        break
                if filled > 0:
                    remaining = max(0, original_qty - filled)
                    print(f"[ORDER_CHASER] Partial fill detected: {filled}/{original_qty} filled, remaining={remaining}")
                    return remaining
                for key in ('remaining_qty', 'remainingQuantity', 'leavesQty'):
                    val = po.get(key)
                    if val is not None:
                        remaining = max(0, min(int(val), original_qty))
                        if remaining < original_qty:
                            print(f"[ORDER_CHASER] Partial fill detected: remaining={remaining}/{original_qty}")
                        return remaining
                return original_qty
        except Exception as e:
            print(f"[ORDER_CHASER] ⚠️ Error computing remaining qty: {e}")
        return original_qty

    async def _safe_get_option_quote(self, broker, symbol: str, strike: float, expiry: str, call_put: str) -> Optional[dict]:
        """Get option quote with cross-broker parameter compatibility."""
        try:
            if not hasattr(broker, 'get_option_quote'):
                return None
            method = broker.get_option_quote
            try:
                result = method(symbol=symbol, strike=strike, expiry=expiry, call_put=call_put)
                if inspect.iscoroutine(result):
                    return await result
                return result
            except TypeError:
                pass
            try:
                result = method(symbol=symbol, strike=strike, expiry=expiry, opt_type=call_put)
                if inspect.iscoroutine(result):
                    return await result
                return result
            except TypeError:
                pass
            try:
                result = method(symbol=symbol, strike=strike, expiry=expiry, option_type=call_put)
                if inspect.iscoroutine(result):
                    return await result
                return result
            except TypeError:
                pass
            return None
        except Exception as e:
            print(f"[ORDER_CHASER] ⚠️ Error getting option quote: {e}")
            return None

    async def _cancel_broker_order(self, broker, order_id: str, asset_type: str = 'option', broker_id: str = '') -> bool:
        try:
            broker_upper = broker_id.upper() if broker_id else ''
            if 'ROBINHOOD' in broker_upper:
                cancel_result = await broker.cancel_order(order_id, order_type=asset_type)
            else:
                cancel_result = await broker.cancel_order(order_id)
            if isinstance(cancel_result, bool):
                return cancel_result
            if isinstance(cancel_result, dict):
                return cancel_result.get('success', False)
            return bool(cancel_result)
        except Exception as e:
            print(f"[ORDER_CHASER] ⚠️ Cancel error: {e}")
            return False
    
    def set_enabled(self, enabled: bool):
        """Enable or disable the order chaser"""
        self._enabled = enabled
        print(f"[ORDER_CHASER] {'Enabled' if enabled else 'Disabled'}")
    
    async def start(self):
        """Start the order chaser monitoring loop"""
        if self._running:
            print("[ORDER_CHASER] Already running")
            return
        
        self._running = True
        
        # Restore tracking for pending orders from database
        await self._restore_pending_orders()
        
        self._task = asyncio.create_task(self._monitor_loop())
        print("[ORDER_CHASER] ✓ Monitoring loop started")
    
    async def _restore_pending_orders(self):
        """Restore tracking for pending entry orders from database on startup"""
        import builtins
        _print = getattr(builtins, '_original_print', print)
        _print("[ORDER_CHASER] Starting pending order restore...", flush=True)
        
        if not DB_AVAILABLE:
            _print("[ORDER_CHASER] ⚠️ Database not available for restore", flush=True)
            return
        
        try:
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            
            # Get pending BTO orders (status = 'PENDING' and direction in BTO/BUY)
            cursor.execute('''
                SELECT 
                    id, order_id, broker, symbol, asset_type, direction,
                    quantity, intended_price, channel_id
                FROM trades 
                WHERE status = 'PENDING' 
                AND upper(direction) IN ('BTO', 'BUY')
                AND order_id IS NOT NULL
            ''')
            
            rows = cursor.fetchall()
            restored_count = 0
            
            for row in rows:
                order_id = row['order_id']
                if not order_id or order_id in self._tracked_entry_orders:
                    continue
                
                # Get channel slippage settings if available
                slippage_max_pct = None
                channel_id = row['channel_id']
                if channel_id:
                    try:
                        cursor.execute('''
                            SELECT slippage_protection_enabled, slippage_max_pct
                            FROM channels WHERE discord_channel_id = ?
                        ''', (channel_id,))
                        ch_row = cursor.fetchone()
                        if ch_row and ch_row['slippage_protection_enabled']:
                            slippage_max_pct = ch_row['slippage_max_pct']
                    except Exception:
                        pass
                
                # Determine asset type
                asset_type = row['asset_type'] or 'option'
                intended_price = float(row['intended_price'] or 0) if row['intended_price'] else 0
                
                # Create tracked order
                order = TrackedEntryOrder(
                    order_id=order_id,
                    broker_id=row['broker'] or 'UNKNOWN',
                    symbol=row['symbol'] or '',
                    asset_type=asset_type,
                    quantity=float(row['quantity'] or 1),
                    original_price=intended_price,
                    action='BTO',
                    placed_at=datetime.now(),  # Use now since we don't know exact placement time
                    channel_id=str(channel_id) if channel_id else None,
                    slippage_max_pct=slippage_max_pct,
                    signal_price=intended_price
                )
                
                self._tracked_entry_orders[order_id] = order
                restored_count += 1
                
                max_price = order.max_chase_price
                max_info = f"max ${max_price:.2f}" if max_price else "no limit"
                _print(f"[ORDER_CHASER] Restored entry: {order_id} | {order.symbol} @ ${order.original_price:.2f} | {max_info}", flush=True)
            
            if restored_count > 0:
                _print(f"[ORDER_CHASER] ✓ Restored {restored_count} pending entry orders from database", flush=True)
            else:
                _print("[ORDER_CHASER] No pending entry orders to restore", flush=True)
            
            exit_cursor = conn.cursor()
            exit_cursor.execute('''
                SELECT 
                    id, order_id, broker, symbol, asset_type, direction,
                    quantity, intended_price, channel_id, strike, expiry, call_put
                FROM trades 
                WHERE status = 'PENDING' 
                AND upper(direction) IN ('STC', 'SELL')
                AND order_id IS NOT NULL
            ''')
            
            exit_rows = exit_cursor.fetchall()
            exit_restored = 0
            
            for erow in exit_rows:
                e_order_id = erow['order_id']
                if not e_order_id or e_order_id in self._tracked_orders:
                    continue
                
                e_asset_type = erow['asset_type'] or 'option'
                e_price = float(erow['intended_price'] or 0) if erow['intended_price'] else 0
                e_symbol = erow['symbol'] or ''
                e_broker = erow['broker'] or 'UNKNOWN'
                
                pos_key_parts = [e_symbol, e_broker]
                if e_asset_type == 'option':
                    if erow['strike']:
                        pos_key_parts.append(str(erow['strike']))
                    if erow['expiry']:
                        pos_key_parts.append(str(erow['expiry']))
                    if erow['call_put']:
                        pos_key_parts.append(str(erow['call_put']))
                e_pos_key = '_'.join(pos_key_parts)
                
                order = TrackedExitOrder(
                    order_id=e_order_id,
                    broker_id=e_broker,
                    symbol=e_symbol,
                    asset_type=e_asset_type,
                    quantity=float(erow['quantity'] or 1),
                    original_price=e_price,
                    action='STC',
                    placed_at=datetime.now(),
                    position_key=e_pos_key,
                    strike=float(erow['strike']) if erow['strike'] else None,
                    expiry=erow['expiry'],
                    call_put=erow['call_put'],
                    is_risk_order=True
                )
                
                self._tracked_orders[e_order_id] = order
                exit_restored += 1
                _print(f"[ORDER_CHASER] Restored exit: {e_order_id} | {e_symbol} STC @ ${e_price:.2f}", flush=True)
            
            if exit_restored > 0:
                _print(f"[ORDER_CHASER] ✓ Restored {exit_restored} pending exit orders from database", flush=True)
                
        except Exception as e:
            _print(f"[ORDER_CHASER] ⚠️ Failed to restore pending orders: {e}", flush=True)
            import traceback
            traceback.print_exc()
    
    async def stop(self):
        """Stop the order chaser and clear tracked orders"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        async with self._lock:
            tracked_count = len(self._tracked_orders)
            self._tracked_orders.clear()
        
        print(f"[ORDER_CHASER] Stopped (cleared {tracked_count} tracked orders)")
    
    async def track_exit_order(
        self,
        order_id: str,
        broker_id: str,
        symbol: str,
        asset_type: str,
        quantity: float,
        price: float,
        action: str,
        position_key: str,
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        call_put: Optional[str] = None,
        is_risk_order: bool = True
    ) -> None:
        """
        Register an exit order for monitoring.
        Called after placing any STC order (risk management or signal-initiated).
        """
        price = _to_price(price)
        async with self._lock:
            order = TrackedExitOrder(
                order_id=order_id,
                broker_id=broker_id,
                symbol=symbol,
                asset_type=asset_type,
                quantity=quantity,
                original_price=price,
                action=action,
                placed_at=datetime.now(),
                position_key=position_key,
                strike=strike,
                expiry=expiry,
                call_put=call_put,
                is_risk_order=is_risk_order
            )
            self._tracked_orders[order_id] = order
            _source = "risk" if is_risk_order else "signal"
            _price_str = f"${price:.2f}" if price is not None else "MKT"
            print(f"[ORDER_CHASER] Tracking {_source} exit order: {order_id} | {symbol} {quantity}x @ {_price_str}")
            try:
                from gui_app.database import record_order_event
                record_order_event('CHASER_TRACKING', symbol=symbol, broker=broker_id, direction='STC', quantity=quantity, price=price, order_id=order_id, reason=f"Tracking exit order for fill confirmation", severity='info', source='order_chaser', position_key=position_key)
            except Exception:
                pass
    
    async def mark_filled(self, order_id: str, fill_price: Optional[float] = None):
        """Mark an order as filled and stop tracking it"""
        async with self._lock:
            if order_id in self._tracked_orders:
                order = self._tracked_orders[order_id]
                order.status = OrderChaseStatus.FILLED
                order.final_fill_price = fill_price
                position_key = order.position_key
                quantity = order.quantity
                del self._tracked_orders[order_id]
                print(f"[ORDER_CHASER] ✓ Order filled: {order_id} @ ${fill_price:.2f}" if fill_price else f"[ORDER_CHASER] ✓ Order filled: {order_id}")
                try:
                    from gui_app.database import record_order_event
                    record_order_event('ORDER_FILLED', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=quantity, price=fill_price or order.original_price, order_id=order_id, status='FILLED', reason=f"Order confirmed filled", severity='info', source='order_chaser', position_key=position_key)
                except Exception:
                    pass
                if position_key and order.action == 'STC' and order.is_risk_order:
                    try:
                        from src.risk.position_cache import get_position_cache
                        cache = get_position_cache()
                        if cache:
                            confirmed = cache.confirm_order_fill(position_key, order_id, int(quantity or 1))
                            if confirmed:
                                print(f"[ORDER_CHASER] ✓ Risk tier confirmed via chaser fill for {position_key}")
                    except Exception as e:
                        print(f"[ORDER_CHASER] Warning: Could not confirm risk tier: {e}")
                    try:
                        from src.risk.exit_lease_manager import get_exit_lease_manager
                        get_exit_lease_manager().force_release(position_key)
                    except Exception:
                        pass
                elif position_key and order.action == 'STC' and not order.is_risk_order:
                    print(f"[ORDER_CHASER] ✓ Signal STC filled for {position_key} — skipping risk state updates")
    
    async def untrack_order(self, order_id: str):
        """Stop tracking an order (exit or entry)"""
        async with self._lock:
            if order_id in self._tracked_orders:
                del self._tracked_orders[order_id]
                print(f"[ORDER_CHASER] Untracked exit order: {order_id}")
            if order_id in self._tracked_entry_orders:
                del self._tracked_entry_orders[order_id]
                print(f"[ORDER_CHASER] Untracked entry order: {order_id}")
    
    async def track_entry_order(
        self,
        order_id: str,
        broker_id: str,
        symbol: str,
        asset_type: str,
        quantity: float,
        price: float,
        action: str,
        channel_id: Optional[str] = None,
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        call_put: Optional[str] = None,
        entry_range_high: Optional[float] = None,
        slippage_max_pct: Optional[float] = None,
        signal_price: Optional[float] = None,
        timeout_minutes: Optional[int] = None,
        limit_cap_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        profit_target_price: Optional[float] = None
    ) -> None:
        """
        Register an entry order (BTO) for monitoring.
        Called after placing a BTO order that might not fill immediately.
        
        Args:
            slippage_max_pct: Per-channel max slippage % (e.g., 10 means max 10% above signal price)
            signal_price: Original signal price for slippage calculation
            timeout_minutes: Per-channel timeout in minutes (from order_timeout_minutes)
            limit_cap_price: Absolute ceiling price (from conditional order limit cap)
            stop_loss_price: Bracket order SL price (preserved for replacement orders)
            profit_target_price: Bracket order PT price (preserved for replacement orders)
        """
        price = _to_price(price) or 0.0
        entry_range_high = _to_price(entry_range_high)
        signal_price = _to_price(signal_price)
        limit_cap_price = _to_price(limit_cap_price)
        async with self._lock:
            order = TrackedEntryOrder(
                order_id=order_id,
                broker_id=broker_id,
                symbol=symbol,
                asset_type=asset_type,
                quantity=quantity,
                original_price=price,
                action=action,
                placed_at=datetime.now(),
                channel_id=channel_id,
                strike=strike,
                expiry=expiry,
                call_put=call_put,
                entry_range_high=entry_range_high,
                slippage_max_pct=slippage_max_pct,
                signal_price=signal_price or price,
                timeout_minutes=timeout_minutes,
                limit_cap_price=limit_cap_price,
                stop_loss_price=stop_loss_price,
                profit_target_price=profit_target_price
            )
            self._tracked_entry_orders[order_id] = order
            
            max_price = _to_price(order.max_chase_price)
            max_info = f"max ${max_price:.2f}" if max_price else "no limit"
            if limit_cap_price:
                max_info += f" (limit cap ${limit_cap_price:.2f})"
            elif slippage_max_pct:
                max_info += f" (slippage {slippage_max_pct}%)"
            print(f"[ORDER_CHASER] Tracking entry order: {order_id} | {symbol} {quantity}x @ ${price:.2f} | {max_info}")
    
    async def mark_entry_filled(self, order_id: str, fill_price: Optional[float] = None):
        """Mark an entry order as filled and stop tracking it"""
        async with self._lock:
            if order_id in self._tracked_entry_orders:
                order = self._tracked_entry_orders[order_id]
                order.status = OrderChaseStatus.FILLED
                order.final_fill_price = fill_price
                del self._tracked_entry_orders[order_id]
                msg = f"[ORDER_CHASER] ✓ Entry order filled: {order_id}"
                if fill_price:
                    msg += f" @ ${fill_price:.2f}"
                print(msg)
    
    def set_entry_chase_enabled(self, enabled: bool):
        """Enable or disable entry order chasing"""
        self._entry_chase_enabled = enabled
        print(f"[ORDER_CHASER] Entry chase {'enabled' if enabled else 'disabled'}")
    
    async def _monitor_loop(self):
        """Main monitoring loop - checks for stale orders and initiates chase"""
        _entry_log_counter = 0
        while self._running:
            try:
                if self._enabled and self._tracked_orders:
                    await self._check_and_chase_orders()
                if self._entry_chase_enabled and self._tracked_entry_orders:
                    _entry_log_counter += 1
                    if _entry_log_counter <= 3 or _entry_log_counter % 30 == 0:
                        entry_ids = list(self._tracked_entry_orders.keys())
                        entry_statuses = [o.status.value for o in self._tracked_entry_orders.values()]
                        print(f"[ORDER_CHASER] Entry check #{_entry_log_counter}: {len(entry_ids)} orders, statuses={entry_statuses}")
                    await self._check_and_chase_entry_orders()
                else:
                    if _entry_log_counter > 0:
                        _entry_log_counter = 0
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ORDER_CHASER] Monitor error: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(self.poll_interval)
    
    async def _check_and_chase_orders(self):
        """Check all tracked orders and chase stale ones"""
        if not self._is_market_active():
            print("[ORDER_CHASER] Market closed — skipping exit chase cycle")
            return

        now = datetime.now()
        orders_to_chase = []
        failed_orders = []
        
        async with self._lock:
            for order_id, order in list(self._tracked_orders.items()):
                if order.status != OrderChaseStatus.PENDING:
                    continue
                
                age = now - order.placed_at
                if age > self.chase_timeout:
                    if order.chase_attempts < self.max_chase_attempts:
                        orders_to_chase.append(order)
                    else:
                        print(f"[ORDER_CHASER] ⚠️ Max chase attempts reached for {order_id} — releasing exit lease")
                        order.status = OrderChaseStatus.FAILED
                        failed_orders.append(order)
        
        for order in failed_orders:
            async with self._lock:
                if order.order_id in self._tracked_orders:
                    del self._tracked_orders[order.order_id]
            if order.position_key and order.is_risk_order:
                already_market = (order.original_price is not None and float(order.original_price) == 0)
                if already_market:
                    print(f"[ORDER_CHASER] ⚠️ Market order already placed for {order.symbol} — skipping duplicate market fallback")
                    market_sent = False
                else:
                    market_sent = await self._attempt_market_fallback(order)
                if not market_sent:
                    try:
                        from src.risk.exit_lease_manager import get_exit_lease_manager
                        get_exit_lease_manager().force_release(order.position_key)
                        print(f"[ORDER_CHASER] ✓ Released exit lease for {order.position_key}")
                    except Exception:
                        pass
                    try:
                        bot = self.broker_manager
                        rm = None
                        if bot:
                            rm = getattr(bot, 'risk_manager', None) or getattr(bot, '_risk_manager', None)
                        if rm:
                            rm.cache.record_exit_failure(order.position_key, "Order chaser max attempts exhausted", is_stop_loss=True)
                            print(f"[ORDER_CHASER] ✓ Recorded exit failure for {order.position_key} — risk engine will retry")
                            pos_cache = rm.cache.get(order.position_key)
                            if pos_cache and getattr(pos_cache, 'broker_pt_order_id', None) == order.order_id:
                                pos_cache.broker_pt_order_id = None
                                print(f"[ORDER_CHASER] ✓ Cleared stale broker_pt_order_id for {order.position_key}")
                    except Exception:
                        pass
            elif order.position_key and not order.is_risk_order:
                print(f"[ORDER_CHASER] ⚠️ Signal STC chase failed for {order.symbol} — no risk lease to release")
            _fail_source = "risk" if order.is_risk_order else "signal"
            try:
                from gui_app.database import record_order_event
                record_order_event('ORDER_CHASE_FAILED', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=order.quantity, price=order.original_price, order_id=order.order_id, status='FAILED', reason=f"Max chase attempts exhausted ({_fail_source} STC)", severity='error', source='order_chaser', position_key=order.position_key)
            except Exception:
                pass
        
        for order in orders_to_chase:
            await self._chase_order(order)
    
    async def _chase_order(self, order: TrackedExitOrder):
        """Chase a stale order - cancel and replace with mid-price"""
        try:
            broker = self._get_broker(order.broker_id)
            if not broker:
                print(f"[ORDER_CHASER] ❌ Broker {order.broker_id} not available")
                return
            
            order.status = OrderChaseStatus.CHASING
            order.chase_attempts += 1
            order.last_chase_at = datetime.now()
            
            print(f"\n[ORDER_CHASER] {'='*50}")
            print(f"[ORDER_CHASER] 🔄 CHASING ORDER (attempt {order.chase_attempts}/{self.max_chase_attempts})")
            print(f"[ORDER_CHASER]   Order ID: {order.order_id}")
            print(f"[ORDER_CHASER]   Symbol: {order.symbol}")
            _orig_p = _to_price(order.original_price)
            order.original_price = _orig_p
            _orig_price_str = f"${_orig_p:.2f}" if _orig_p is not None else "MKT"
            print(f"[ORDER_CHASER]   Original Price: {_orig_price_str}")
            
            pending_orders = []
            if hasattr(broker, 'get_pending_orders'):
                _result = broker.get_pending_orders()
                if inspect.iscoroutine(_result):
                    pending_orders = await _result
                else:
                    pending_orders = _result
            order_still_pending = any(
                str(po.get('order_id', '')) == str(order.order_id) 
                for po in (pending_orders or [])
            )
            
            if not order_still_pending:
                print(f"[ORDER_CHASER] Order {order.order_id} no longer pending — verifying fill status...")
                verified = await self._verify_order_fill(broker, order.order_id, order.symbol, order.asset_type, order.action)
                if verified == 'PENDING_ACTIVATION':
                    print(f"[ORDER_CHASER] Order {order.order_id} is PENDING_ACTIVATION — waiting for market open, not chasing")
                    order.status = OrderChaseStatus.PENDING
                    order.chase_attempts = max(0, order.chase_attempts - 1)
                    return
                if verified == 'CANCELLED':
                    print(f"[ORDER_CHASER] Order {order.order_id} was CANCELLED/REJECTED by broker — not marking as filled")
                    async with self._lock:
                        if order.order_id in self._tracked_orders:
                            self._tracked_orders[order.order_id].status = OrderChaseStatus.CANCELLED
                            del self._tracked_orders[order.order_id]
                    try:
                        from gui_app.database import record_order_event
                        record_order_event('ORDER_CANCELLED', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=order.quantity, price=order.original_price, order_id=order.order_id, status='CANCELLED', reason="Order verified as cancelled/rejected by broker", severity='warning', source='order_chaser', position_key=order.position_key)
                    except Exception:
                        pass
                    if order.position_key and order.is_risk_order:
                        try:
                            from src.risk.exit_lease_manager import get_exit_lease_manager
                            get_exit_lease_manager().force_release(order.position_key)
                        except Exception:
                            pass
                        try:
                            bot = self.broker_manager
                            rm = None
                            if bot:
                                rm = getattr(bot, '_risk_manager', None) or getattr(bot, 'risk_manager', None)
                            if rm and hasattr(rm, '_exit_executed_keys') and hasattr(rm, '_exit_executed_lock'):
                                with rm._exit_executed_lock:
                                    if order.position_key in rm._exit_executed_keys:
                                        rm._exit_executed_keys.discard(order.position_key)
                                        print(f"[ORDER_CHASER] ✓ Cleared exit-executed lock for {order.position_key} — retry enabled after exchange rejection")
                            if rm and hasattr(rm, 'cache'):
                                rm.cache.record_exit_failure(order.position_key, f"Exchange rejected order {order.order_id}", is_stop_loss=True)
                                print(f"[ORDER_CHASER] ✓ Recorded exit failure for {order.position_key} — risk engine will retry")
                                pos_cache = rm.cache.get(order.position_key)
                                if pos_cache and getattr(pos_cache, 'broker_pt_order_id', None) == order.order_id:
                                    pos_cache.broker_pt_order_id = None
                                    print(f"[ORDER_CHASER] ✓ Cleared stale broker_pt_order_id for {order.position_key}")
                        except Exception as e:
                            print(f"[ORDER_CHASER] ⚠️ Could not clear exit lock after rejection: {e}")
                        try:
                            from gui_app.database import get_connection as _oc_gc
                            _oc_conn = _oc_gc()
                            _oc_cur = _oc_conn.cursor()
                            _oc_cur.execute(
                                "SELECT id, origin_trade_id FROM trades WHERE order_id = ? AND direction = 'STC' AND status = 'CLOSED'",
                                (str(order.order_id),)
                            )
                            phantom_rows = _oc_cur.fetchall()
                            for phantom in phantom_rows:
                                phantom_id = phantom['id']
                                origin_id = phantom['origin_trade_id']
                                _oc_cur.execute("DELETE FROM trades WHERE id = ?", (phantom_id,))
                                print(f"[ORDER_CHASER] 🗑️ Deleted phantom STC trade #{phantom_id} (order {order.order_id} was rejected)")
                                if origin_id:
                                    _oc_cur.execute(
                                        "SELECT id, status FROM trades WHERE id = ? AND direction = 'BTO'",
                                        (origin_id,)
                                    )
                                    origin_row = _oc_cur.fetchone()
                                    if origin_row and origin_row['status'] == 'CLOSED':
                                        _oc_cur.execute(
                                            "UPDATE trades SET status = 'OPEN', closed_at = NULL WHERE id = ?",
                                            (origin_id,)
                                        )
                                        print(f"[ORDER_CHASER] ✅ Reopened origin BTO trade #{origin_id} (was closed by phantom STC)")
                            _oc_conn.commit()
                        except Exception as db_err:
                            print(f"[ORDER_CHASER] ⚠️ Could not clean up phantom trades after rejection: {db_err}")
                    return
                if verified == 'UNKNOWN':
                    print(f"[ORDER_CHASER] Order {order.order_id} status UNKNOWN — treating as cancelled (safe default, will retry)")
                    order.status = OrderChaseStatus.PENDING
                    try:
                        from gui_app.database import record_order_event
                        record_order_event('ORDER_STATUS_UNKNOWN', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=order.quantity, price=order.original_price, order_id=order.order_id, status='UNKNOWN', reason="Exit order status unknown — not marking as filled", severity='warning', source='order_chaser', position_key=order.position_key)
                    except Exception:
                        pass
                    return
                else:
                    print(f"[ORDER_CHASER] Order {order.order_id} verified as filled")
                await self.mark_filled(order.order_id)
                return
            
            remaining_qty = self._get_remaining_qty(pending_orders, order.order_id, int(order.quantity))
            if remaining_qty <= 0:
                print(f"[ORDER_CHASER] Order fully filled (partial fills consumed all qty) — marking filled")
                await self.mark_filled(order.order_id)
                return

            chase_price = await self._get_mid_price(broker, order)
            if chase_price is None:
                print(f"[ORDER_CHASER] ⚠️ Could not get exit price for {order.symbol} — keeping existing order alive")
                order.status = OrderChaseStatus.PENDING
                return

            is_market = (chase_price == 0)
            mid_price = chase_price

            if not is_market and order.is_risk_order and order.original_price is not None:
                _orig = _to_price(order.original_price)
                if _orig and _orig > 0 and mid_price < _orig * 0.90:
                    print(f"[ORDER_CHASER] ⚠️ Chase price ${mid_price:.4f} is >10% below PT price ${_orig:.4f} for {order.symbol} — skipping chase (stale/after-hours quote)")
                    order.status = OrderChaseStatus.PENDING
                    order.chase_attempts = max(0, order.chase_attempts - 1)
                    return

            if is_market:
                print(f"[ORDER_CHASER]   Strategy: MARKET ORDER (attempt {order.chase_attempts})")
            else:
                print(f"[ORDER_CHASER]   Exit Price: ${mid_price:.2f} (attempt {order.chase_attempts})")

            if order.position_key and order.is_risk_order:
                cancel_ok = await self._atomic_pt_id_clear_and_cancel(order.position_key, order.order_id, broker, order.asset_type, order.broker_id)
            else:
                cancel_ok = await self._cancel_broker_order(broker, order.order_id, order.asset_type, order.broker_id)
            if not cancel_ok:
                print(f"[ORDER_CHASER] ❌ Failed to cancel exit order — keeping existing order")
                order.status = OrderChaseStatus.PENDING
                return
            
            print(f"[ORDER_CHASER] ✓ Cancelled original order")

            post_cancel_pending, settled = await self._wait_for_cancel_settlement(broker, order.order_id, max_checks=3)
            if not settled:
                print(f"[ORDER_CHASER] ⚠️ Order {order.order_id} still active after 3 settlement checks — aborting replacement to prevent duplicate")
                order.status = OrderChaseStatus.PENDING
                return

            original_total_qty = int(order.quantity)
            order_in_pending = any(
                str(po.get('order_id', '')) == str(order.order_id)
                for po in (post_cancel_pending or [])
            )
            if not order_in_pending:
                verified = await self._verify_order_fill(broker, order.order_id, order.symbol, order.asset_type, order.action)
                if verified == 'PENDING_ACTIVATION':
                    print(f"[ORDER_CHASER] Order {order.order_id} is PENDING_ACTIVATION during cancel window — not replacing")
                    order.status = OrderChaseStatus.PENDING
                    return
                if verified and verified not in ('CANCELLED', 'UNKNOWN'):
                    print(f"[ORDER_CHASER] Order {order.order_id} verified as filled during cancel window")
                    await self.mark_filled(order.order_id)
                    return
                replace_qty = original_total_qty
            else:
                replace_qty = self._get_remaining_qty(post_cancel_pending, order.order_id, original_total_qty)

            if replace_qty <= 0:
                print(f"[ORDER_CHASER] Order fully filled during cancel window — marking filled")
                await self.mark_filled(order.order_id)
                return
            if is_market:
                new_order_id = await self._place_market_replacement(broker, order, quantity_override=replace_qty)
            else:
                new_order_id = await self._place_replacement_order(broker, order, mid_price, quantity_override=replace_qty)
            
            if new_order_id:
                _price_str = "MKT" if is_market else f"${mid_price:.2f}"
                print(f"[ORDER_CHASER] ✓ Placed replacement order: {new_order_id} @ {_price_str} qty={replace_qty}")
                order.replacement_order_id = new_order_id
                order.status = OrderChaseStatus.REPLACED
                try:
                    from gui_app.database import record_order_event
                    _orig_p = f"${order.original_price:.2f}" if order.original_price is not None else "MKT"
                    record_order_event('CHASER_REPLACED', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=replace_qty, price=mid_price, order_id=new_order_id, reason=f"Stale order replaced: {_orig_p} → {_price_str} (attempt {order.chase_attempts}, qty {replace_qty}/{int(order.quantity)})", severity='warning', source='order_chaser', position_key=order.position_key)
                except Exception:
                    pass
                
                if order.position_key and order.is_risk_order:
                    await self._atomic_pt_id_swap(order.position_key, order.order_id, new_order_id)

                async with self._lock:
                    if order.order_id in self._tracked_orders:
                        del self._tracked_orders[order.order_id]
                    
                    new_tracked = TrackedExitOrder(
                        order_id=new_order_id,
                        broker_id=order.broker_id,
                        symbol=order.symbol,
                        asset_type=order.asset_type,
                        quantity=replace_qty,
                        original_price=mid_price,
                        action=order.action,
                        placed_at=datetime.now(),
                        position_key=order.position_key,
                        strike=order.strike,
                        expiry=order.expiry,
                        call_put=order.call_put,
                        chase_attempts=self.max_chase_attempts if is_market else order.chase_attempts,
                        is_risk_order=order.is_risk_order
                    )
                    self._tracked_orders[new_order_id] = new_tracked
            else:
                _retry_price_str = "MKT" if is_market else f"${mid_price:.2f}"
                print(f"[ORDER_CHASER] ❌ Failed to place replacement exit order — immediate retry at {_retry_price_str}")
                await asyncio.sleep(0.2)
                if is_market:
                    retry_order_id = await self._place_market_replacement(broker, order, quantity_override=replace_qty)
                else:
                    retry_order_id = await self._place_replacement_order(broker, order, mid_price, quantity_override=replace_qty)
                if retry_order_id:
                    print(f"[ORDER_CHASER] ✓ Retry succeeded: {retry_order_id} @ {_retry_price_str}")
                    order.replacement_order_id = retry_order_id
                    order.status = OrderChaseStatus.REPLACED
                    if order.position_key and order.is_risk_order:
                        await self._atomic_pt_id_swap(order.position_key, order.order_id, retry_order_id)
                    async with self._lock:
                        if order.order_id in self._tracked_orders:
                            del self._tracked_orders[order.order_id]
                        new_tracked = TrackedExitOrder(
                            order_id=retry_order_id,
                            broker_id=order.broker_id,
                            symbol=order.symbol,
                            asset_type=order.asset_type,
                            quantity=replace_qty,
                            original_price=mid_price,
                            action=order.action,
                            placed_at=datetime.now(),
                            position_key=order.position_key,
                            strike=order.strike,
                            expiry=order.expiry,
                            call_put=order.call_put,
                            chase_attempts=self.max_chase_attempts if is_market else order.chase_attempts,
                            is_risk_order=order.is_risk_order
                        )
                        self._tracked_orders[retry_order_id] = new_tracked
                else:
                    print(f"[ORDER_CHASER] ❌ Retry also failed — releasing for risk engine retry")
                    async with self._lock:
                        if order.order_id in self._tracked_orders:
                            del self._tracked_orders[order.order_id]
                    if order.position_key and order.is_risk_order:
                        try:
                            from src.risk.exit_lease_manager import get_exit_lease_manager
                            get_exit_lease_manager().force_release(order.position_key)
                        except Exception:
                            pass
                        try:
                            bot = self.broker_manager
                            rm = None
                            if bot:
                                rm = getattr(bot, '_risk_manager', None) or getattr(bot, 'risk_manager', None)
                            if rm and hasattr(rm, '_exit_executed_keys') and hasattr(rm, '_exit_executed_lock'):
                                with rm._exit_executed_lock:
                                    rm._exit_executed_keys.discard(order.position_key)
                            if rm and hasattr(rm, 'cache'):
                                rm.cache.record_exit_failure(order.position_key, "Chaser cancel+replace both failed", is_stop_loss=True)
                                print(f"[ORDER_CHASER] ✓ Recorded exit failure for {order.position_key} — risk engine will retry")
                        except Exception as e:
                            print(f"[ORDER_CHASER] ⚠️ Could not record exit failure: {e}")
                    elif order.position_key and not order.is_risk_order:
                        print(f"[ORDER_CHASER] ⚠️ Signal STC replace failed for {order.symbol} — no risk lease to release")
                    _fail_source = "risk" if order.is_risk_order else "signal"
                    try:
                        from gui_app.database import record_order_event
                        record_order_event('CHASER_REPLACE_FAILED', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=replace_qty, price=mid_price, order_id=order.order_id, reason=f"Cancel succeeded but both replacement attempts failed ({_fail_source} STC, attempt {order.chase_attempts})", severity='error', source='order_chaser', position_key=order.position_key)
                    except Exception:
                        pass
            
            print(f"[ORDER_CHASER] {'='*50}\n")
            
        except Exception as e:
            print(f"[ORDER_CHASER] Chase error for {order.order_id}: {e}")
            import traceback
            traceback.print_exc()
            order.status = OrderChaseStatus.PENDING
    
    def _normalize_expiry(self, expiry: str) -> list:
        """Return list of possible expiry format variants for DB matching."""
        if not expiry:
            return []
        variants = [expiry]
        if '/' in expiry:
            parts = expiry.split('/')
            if len(parts) == 2:
                from datetime import datetime as dt
                variants.append(f"{dt.now().year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}")
                variants.append(f"{parts[0].zfill(2)}/{parts[1].zfill(2)}")
            elif len(parts) == 3:
                variants.append(f"20{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}" if len(parts[2]) == 2 else f"{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}")
                variants.append(f"{parts[0].zfill(2)}/{parts[1].zfill(2)}/{parts[2]}")
                variants.append(f"{parts[0]}/{parts[1]}")
        elif '-' in expiry:
            parts = expiry.split('-')
            if len(parts) == 3:
                variants.append(f"{parts[1]}/{parts[2]}/{parts[0][2:]}")
                variants.append(f"{parts[1]}/{parts[2]}")
        return list(set(variants))

    def _check_streaming_hubs_option(self, symbol: str, strike: float, expiry: str, call_put: str) -> Optional[dict]:
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming():
                try:
                    from gui_app.database import get_db
                    db = get_db()
                    expiry_variants = self._normalize_expiry(expiry) if expiry else []
                    row = None
                    if expiry_variants:
                        placeholders = ','.join(['?'] * len(expiry_variants))
                        cursor = db.execute(
                            f"SELECT option_id FROM trades WHERE symbol=? AND strike=? AND call_put=? AND expiry IN ({placeholders}) AND status='OPEN' LIMIT 1",
                            [symbol, strike, call_put] + expiry_variants
                        )
                        row = cursor.fetchone()
                    if not row:
                        cursor = db.execute(
                            "SELECT option_id, expiry FROM trades WHERE symbol=? AND strike=? AND call_put=? AND status='OPEN' LIMIT 1",
                            (symbol, strike, call_put)
                        )
                        row = cursor.fetchone()
                        if row and row[0] and expiry:
                            print(f"[ORDER_CHASER] ⚠️ Webull hub: expiry mismatch (wanted={expiry}, found={row[1]}) — using fallback match")
                    if row and row[0]:
                        data = hub.get_quote_detailed(str(row[0]))
                        if data and (data.get('bid', 0) > 0 or data.get('ask', 0) > 0):
                            print(f"[ORDER_CHASER] ⚡ Got option quote from Webull hub (ticker_id={row[0]})")
                            return data
                except Exception:
                    pass
        except Exception:
            pass
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            schwab_hub = get_schwab_data_hub()
            if schwab_hub.is_streaming() and expiry and strike:
                iso_expiry = expiry
                if '/' in expiry:
                    parts = expiry.split('/')
                    if len(parts) == 3:
                        iso_expiry = f"20{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                    elif len(parts) == 2:
                        from datetime import datetime as dt
                        iso_expiry = f"{dt.now().year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                if '-' in iso_expiry:
                    opt_type = (call_put or 'C').upper()
                    if opt_type == 'CALL': opt_type = 'C'
                    elif opt_type == 'PUT': opt_type = 'P'
                    from src.brokers.schwab_broker import SchwabBroker
                    occ = SchwabBroker._build_option_symbol(None, symbol, iso_expiry, strike, opt_type)
                    data = schwab_hub.get_quote_detailed(occ)
                    if data and (data.get('bid', 0) > 0 or data.get('ask', 0) > 0):
                        print(f"[ORDER_CHASER] ⚡ Got option quote from Schwab hub (OCC={occ})")
                        return data
        except Exception:
            pass
        try:
            from src.services.ibkr_data_hub import get_ibkr_data_hub
            ibkr_hub = get_ibkr_data_hub()
            if ibkr_hub.is_streaming() and strike and expiry:
                iso_expiry = expiry
                if '/' in expiry:
                    parts = expiry.split('/')
                    if len(parts) == 3:
                        iso_expiry = f"20{parts[2]}{parts[0].zfill(2)}{parts[1].zfill(2)}"
                    elif len(parts) == 2:
                        from datetime import datetime as dt
                        iso_expiry = f"{dt.now().year}{parts[0].zfill(2)}{parts[1].zfill(2)}"
                elif '-' in iso_expiry:
                    iso_expiry = iso_expiry.replace('-', '')
                opt_type = (call_put or 'C').upper()
                if opt_type == 'CALL': opt_type = 'C'
                elif opt_type == 'PUT': opt_type = 'P'
                raw_key = f"{symbol}_{iso_expiry}_{strike}_{opt_type}"
                data = ibkr_hub.get_quote_detailed(raw_key)
                if data and (data.get('bid', 0) > 0 or data.get('ask', 0) > 0):
                    print(f"[ORDER_CHASER] ⚡ Got option quote from IBKR hub (key={raw_key})")
                    return data
        except Exception:
            pass
        return None

    _INDEX_VARIANTS = {
        'SPX': ['SPX', 'SPXW'], 'SPXW': ['SPXW', 'SPX'],
        'NDX': ['NDX', 'NDXP'], 'NDXP': ['NDXP', 'NDX'],
        'VIX': ['VIX', 'VIXW'], 'VIXW': ['VIXW', 'VIX'],
        'RUT': ['RUT', 'RUTW'], 'RUTW': ['RUTW', 'RUT'],
        'DJX': ['DJX', 'DJXW'], 'DJXW': ['DJXW', 'DJX'],
    }

    def _check_streaming_hubs_stock(self, symbol: str, order_broker: str = None) -> Optional[dict]:
        syms = self._INDEX_VARIANTS.get(symbol.upper(), [symbol])
        broker_upper = (order_broker or '').upper()
        hub_list = []
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming():
                hub_list.append(('Webull', hub, 'WEBULL' in broker_upper))
        except Exception:
            pass
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            hub = get_schwab_data_hub()
            if hub.is_streaming():
                hub_list.append(('Schwab', hub, 'SCHWAB' in broker_upper))
        except Exception:
            pass
        try:
            from src.services.ibkr_data_hub import get_ibkr_data_hub
            hub = get_ibkr_data_hub()
            if hub.is_streaming():
                hub_list.append(('IBKR', hub, 'IBKR' in broker_upper))
        except Exception:
            pass
        try:
            from src.services.tastytrade_data_hub import get_tastytrade_data_hub
            hub = get_tastytrade_data_hub()
            if hub and hub.is_streaming():
                hub_list.append(('Tastytrade', hub, 'TASTYTRADE' in broker_upper or 'TASTY' in broker_upper))
        except Exception:
            pass
        best_bid_ask = None
        best_bid_ask_name = None
        best_last_only = None
        best_last_only_name = None
        for hub_name, hub, is_own_broker in hub_list:
            for _s in syms:
                data = hub.get_quote_detailed(_s)
                if not data:
                    continue
                has_bid = data.get('bid', 0) > 0
                has_last = data.get('last', 0) > 0
                if has_bid:
                    if not is_own_broker:
                        print(f"[ORDER_CHASER] ⚡ Got stock quote from {hub_name} hub (cross-broker)")
                        return data
                    if best_bid_ask is None:
                        best_bid_ask = data
                        best_bid_ask_name = hub_name
                elif has_last:
                    if best_last_only is None or (not is_own_broker and best_last_only_name and '(cross-broker)' not in best_last_only_name):
                        best_last_only = data
                        best_last_only_name = f"{hub_name} (cross-broker)" if not is_own_broker else hub_name
        if best_bid_ask:
            print(f"[ORDER_CHASER] ⚡ Got stock quote from {best_bid_ask_name} hub")
            return best_bid_ask
        if best_last_only:
            print(f"[ORDER_CHASER] ⚡ Got stock quote from {best_last_only_name} hub")
            return best_last_only
        return None

    async def _get_exit_bid_ask(self, broker, order: TrackedExitOrder) -> dict:
        result = {'bid': None, 'ask': None, 'last': None}
        try:
            if order.asset_type == 'option':
                if not (order.strike and order.expiry and order.call_put):
                    return result
                hub_data = self._check_streaming_hubs_option(order.symbol, order.strike, order.expiry, order.call_put)
                if hub_data:
                    result['bid'] = _to_price(hub_data.get('bid')) or None
                    result['ask'] = _to_price(hub_data.get('ask')) or None
                    result['last'] = _to_price(hub_data.get('last')) or None
                    if result['bid'] and result['bid'] > 0:
                        return result
                quote = await self._safe_get_option_quote(broker, order.symbol, order.strike, order.expiry, order.call_put)
                if quote:
                    result['bid'] = _to_price(quote.get('bid')) or result['bid']
                    result['ask'] = _to_price(quote.get('ask')) or result['ask']
                    result['last'] = _to_price(quote.get('last')) or result['last']
            else:
                hub_data = self._check_streaming_hubs_stock(order.symbol, order.broker_id)
                if hub_data:
                    result['bid'] = _to_price(hub_data.get('bid')) or None
                    result['ask'] = _to_price(hub_data.get('ask')) or None
                    result['last'] = _to_price(hub_data.get('last')) or None
                    if result['bid'] and result['bid'] > 0:
                        return result

                quote_data = None
                if hasattr(broker, 'get_quote_with_bid_ask'):
                    method = broker.get_quote_with_bid_ask
                    r = method(order.symbol)
                    if inspect.iscoroutine(r):
                        quote_data = await r
                    else:
                        quote_data = r
                elif hasattr(broker, 'get_quote'):
                    method = broker.get_quote
                    r = method(order.symbol)
                    if inspect.iscoroutine(r):
                        quote_data = await r
                    else:
                        quote_data = r

                if quote_data and isinstance(quote_data, dict):
                    result['bid'] = _to_price(quote_data.get('bid')) or result['bid']
                    result['ask'] = _to_price(quote_data.get('ask')) or result['ask']
                    result['last'] = _to_price(quote_data.get('last') or quote_data.get('price') or quote_data.get('latestPrice')) or result['last']
                elif quote_data is not None:
                    scalar = _to_price(quote_data)
                    if scalar and scalar > 0:
                        result['last'] = scalar
        except Exception as e:
            print(f"[ORDER_CHASER] Error getting bid/ask: {e}")
        return result

    def _calc_chase_price(self, chase_attempt: int, bid: float, ask: float, last: float) -> tuple:
        if chase_attempt <= 1:
            if bid and bid > 0 and ask and ask > 0:
                mid = round((bid + ask) / 2, 2)
                return mid, 'MID'
            elif last and last > 0:
                return last, 'LAST'
            elif bid and bid > 0:
                return bid, 'BID'
            return None, None
        elif chase_attempt == 2:
            if bid and bid > 0:
                return bid, 'BID'
            elif last and last > 0:
                return last, 'LAST'
            return None, None
        else:
            return 0, 'MARKET'

    async def _get_mid_price(self, broker, order: TrackedExitOrder) -> Optional[float]:
        ba = await self._get_exit_bid_ask(broker, order)
        bid = ba.get('bid') or 0
        ask = ba.get('ask') or 0
        last = ba.get('last') or 0

        price, label = self._calc_chase_price(order.chase_attempts, bid, ask, last)
        if price is None:
            print(f"[ORDER_CHASER] ⚠️ No price available for {order.symbol}")
            return None
        if label == 'MARKET':
            print(f"[ORDER_CHASER] 🚨 Chase attempt {order.chase_attempts}: MARKET ORDER for {order.symbol}")
            return 0
        print(f"[ORDER_CHASER] 💰 Chase attempt {order.chase_attempts}: {label} ${price:.2f} for {order.symbol} (bid=${bid:.2f}, ask=${ask:.2f})")
        return price
    
    def _extract_order_id(self, result) -> Optional[str]:
        if not result:
            return None
        if hasattr(result, 'order_id') and result.order_id:
            return str(result.order_id)
        if isinstance(result, dict):
            oid = result.get('orderId') or result.get('order_id')
            if not oid and isinstance(result.get('data'), dict):
                oid = result['data'].get('orderId') or result['data'].get('order_id')
            if oid:
                return str(oid)
        if isinstance(result, str) and len(result) > 3:
            return result
        return None

    async def _place_replacement_order(
        self,
        broker,
        order: TrackedExitOrder,
        price: float,
        quantity_override: Optional[int] = None
    ) -> Optional[str]:
        """Place a replacement order at the specified price"""
        try:
            qty = quantity_override if quantity_override is not None else int(order.quantity)
            if qty <= 0:
                print(f"[ORDER_CHASER] ❌ Cannot place replacement with qty={qty}")
                return None
            if order.asset_type == 'option':
                if not order.call_put:
                    print(f"[ORDER_CHASER] ❌ Cannot place exit option replacement — call_put is None for {order.symbol}")
                    return None
                opt_kwargs = dict(
                    symbol=order.symbol,
                    quantity=qty,
                    price=price,
                    action=order.action,
                    strike=order.strike,
                    expiry=order.expiry,
                    option_type=order.call_put
                )
                _wb_oid = self._resolve_webull_option_id(broker, order)
                if _wb_oid:
                    opt_kwargs['option_id'] = _wb_oid
                result = await broker.place_option_order(**opt_kwargs)
            else:
                result = await broker.place_stock_order(
                    symbol=order.symbol,
                    quantity=qty,
                    price=price,
                    action=order.action
                )
            
            return self._extract_order_id(result)
        except Exception as e:
            print(f"[ORDER_CHASER] Error placing replacement order: {e}")
            return None
    
    async def _place_market_replacement(
        self,
        broker,
        order: TrackedExitOrder,
        quantity_override: Optional[int] = None
    ) -> Optional[str]:
        try:
            qty = quantity_override if quantity_override is not None else int(order.quantity)
            if qty <= 0:
                return None
            if order.asset_type == 'option':
                if not order.call_put:
                    print(f"[ORDER_CHASER] ❌ Cannot place market exit — call_put is None for {order.symbol}")
                    return None
                opt_kwargs = dict(
                    symbol=order.symbol,
                    quantity=qty,
                    price=0,
                    action=order.action,
                    strike=order.strike,
                    expiry=order.expiry,
                    option_type=order.call_put
                )
                _wb_oid = self._resolve_webull_option_id(broker, order)
                if _wb_oid:
                    opt_kwargs['option_id'] = _wb_oid
                result = await broker.place_option_order(**opt_kwargs)
            else:
                result = await broker.place_stock_order(
                    symbol=order.symbol,
                    quantity=qty,
                    price=0,
                    action=order.action
                )
            return self._extract_order_id(result)
        except Exception as e:
            print(f"[ORDER_CHASER] Error placing market replacement: {e}")
            return None

    async def _attempt_market_fallback(self, order: TrackedExitOrder) -> bool:
        try:
            broker = self._get_broker(order.broker_id)
            if not broker:
                print(f"[ORDER_CHASER] ❌ Market fallback: broker {order.broker_id} not available")
                return False

            qty = int(order.quantity)
            if qty <= 0:
                return False

            print(f"[ORDER_CHASER] 🚨 MARKET FALLBACK: Placing market STC for {order.symbol} qty={qty} after all chase attempts exhausted")

            if order.asset_type == 'option':
                if not order.call_put:
                    print(f"[ORDER_CHASER] ❌ Market fallback: call_put is None for {order.symbol}")
                    return False
                opt_kwargs = dict(
                    symbol=order.symbol,
                    quantity=qty,
                    price=0,
                    action=order.action,
                    strike=order.strike,
                    expiry=order.expiry,
                    option_type=order.call_put
                )
                _wb_oid = self._resolve_webull_option_id(broker, order)
                if _wb_oid:
                    opt_kwargs['option_id'] = _wb_oid
                result = await broker.place_option_order(**opt_kwargs)
            else:
                result = await broker.place_stock_order(
                    symbol=order.symbol,
                    quantity=qty,
                    price=0,
                    action=order.action
                )

            mkt_order_id = self._extract_order_id(result)
            if mkt_order_id:
                print(f"[ORDER_CHASER] ✅ Market fallback order placed: {mkt_order_id} for {order.symbol}")
                if order.position_key and order.is_risk_order:
                    await self._atomic_pt_id_swap(order.position_key, order.order_id, mkt_order_id)
                try:
                    from gui_app.database import record_order_event
                    record_order_event('CHASER_MARKET_FALLBACK', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=qty, price=0, order_id=mkt_order_id, reason=f"Market fallback after {order.chase_attempts} chase attempts", severity='warning', source='order_chaser', position_key=order.position_key)
                except Exception:
                    pass
                async with self._lock:
                    new_tracked = TrackedExitOrder(
                        order_id=mkt_order_id,
                        broker_id=order.broker_id,
                        symbol=order.symbol,
                        asset_type=order.asset_type,
                        quantity=qty,
                        original_price=0,
                        action=order.action,
                        placed_at=datetime.now(),
                        position_key=order.position_key,
                        strike=order.strike,
                        expiry=order.expiry,
                        call_put=order.call_put,
                        chase_attempts=self.max_chase_attempts,
                        is_risk_order=order.is_risk_order
                    )
                    self._tracked_orders[mkt_order_id] = new_tracked
                return True
            else:
                print(f"[ORDER_CHASER] ❌ Market fallback failed for {order.symbol} — no order ID returned")
                return False
        except Exception as e:
            print(f"[ORDER_CHASER] ❌ Market fallback error for {order.symbol}: {e}")
            return False

    async def _check_and_chase_entry_orders(self):
        """Check all tracked entry orders and chase stale ones"""
        if not self._is_market_active():
            return

        now = datetime.now()
        orders_to_chase = []
        orders_to_cancel = []
        
        async with self._lock:
            for order_id, order in list(self._tracked_entry_orders.items()):
                if order.status != OrderChaseStatus.PENDING:
                    continue
                
                age = now - order.placed_at
                age_seconds = age.total_seconds()
                
                if order.timeout_minutes:
                    timeout_seconds = order.timeout_minutes * 60
                    if age_seconds >= timeout_seconds:
                        print(f"[ORDER_CHASER] ⏰ Channel timeout ({order.timeout_minutes}min) reached for {order_id}")
                        order.status = OrderChaseStatus.FAILED
                        orders_to_cancel.append(order)
                        continue
                
                if age > self.chase_timeout:
                    if order.chase_attempts < self.max_chase_attempts:
                        print(f"[ORDER_CHASER] Entry order {order_id} ({order.symbol}) age={age_seconds:.1f}s, attempts={order.chase_attempts}/{self.max_chase_attempts} — scheduling chase")
                        orders_to_chase.append(order)
                    else:
                        print(f"[ORDER_CHASER] ⚠️ Max entry chase attempts reached for {order_id}")
                        order.status = OrderChaseStatus.FAILED
                        if self.cancel_entry_on_max_attempts:
                            orders_to_cancel.append(order)
        
        # Cancel timed-out orders
        for order in orders_to_cancel:
            await self._cancel_unfilled_entry_order(order)
        
        # Chase stale orders
        for order in orders_to_chase:
            await self._chase_entry_order(order)
    
    async def _chase_entry_order(self, order: TrackedEntryOrder):
        """Chase a stale entry order - cancel and replace with ask price for better fill"""
        try:
            try:
                from src.services.daily_pnl_limit_service import get_daily_pnl_service
                pnl_service = get_daily_pnl_service()
                pnl_check = pnl_service.check_broker_locked(order.broker_id)
                if pnl_check.get('locked'):
                    print(f"[ORDER_CHASER] ⛔ {order.broker_id} daily P&L locked ({pnl_check.get('lock_type')}) — skipping BTO chase for {order.symbol}")
                    order.status = OrderChaseStatus.PENDING
                    return
            except ImportError:
                pass
            except Exception:
                pass

            broker = self._get_broker(order.broker_id)
            if not broker:
                print(f"[ORDER_CHASER] ❌ Broker {order.broker_id} not available for entry chase")
                return
            
            order.status = OrderChaseStatus.CHASING
            order.chase_attempts += 1
            order.last_chase_at = datetime.now()
            
            print(f"\n[ORDER_CHASER] {'='*50}")
            print(f"[ORDER_CHASER] 🔄 CHASING ENTRY ORDER (attempt {order.chase_attempts}/{self.max_chase_attempts})")
            print(f"[ORDER_CHASER]   Order ID: {order.order_id}")
            print(f"[ORDER_CHASER]   Symbol: {order.symbol}")
            _entry_orig = _to_price(order.original_price)
            order.original_price = _entry_orig if _entry_orig else order.original_price
            _entry_orig_str = f"${_entry_orig:.2f}" if _entry_orig is not None else "MKT"
            print(f"[ORDER_CHASER]   Original Price: {_entry_orig_str}")
            _erh = _to_price(order.entry_range_high)
            if _erh:
                print(f"[ORDER_CHASER]   Max Entry Price: ${_erh:.2f}")
            
            pending_orders = []
            if hasattr(broker, 'get_pending_orders'):
                _result = broker.get_pending_orders()
                if inspect.iscoroutine(_result):
                    pending_orders = await _result
                else:
                    pending_orders = _result
            order_still_pending = any(
                str(po.get('order_id', '')) == str(order.order_id) 
                for po in (pending_orders or [])
            )
            
            if not order_still_pending:
                print(f"[ORDER_CHASER] Entry order {order.order_id} no longer pending — verifying fill status...")
                verified = await self._verify_order_fill(broker, order.order_id, order.symbol, order.asset_type, order.action)
                if verified == 'PENDING_ACTIVATION':
                    print(f"[ORDER_CHASER] Entry order {order.order_id} is PENDING_ACTIVATION — waiting for market open, not chasing")
                    order.status = OrderChaseStatus.PENDING
                    order.chase_attempts = max(0, order.chase_attempts - 1)
                    return
                if verified == 'CANCELLED':
                    print(f"[ORDER_CHASER] Entry order {order.order_id} was CANCELLED/REJECTED by broker — not marking as filled")
                    async with self._lock:
                        if order.order_id in self._tracked_entry_orders:
                            self._tracked_entry_orders[order.order_id].status = OrderChaseStatus.CANCELLED
                            del self._tracked_entry_orders[order.order_id]
                    try:
                        from gui_app.database import record_order_event
                        record_order_event('ORDER_CANCELLED', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=order.quantity, price=order.original_price, order_id=order.order_id, status='CANCELLED', reason="Entry order verified as cancelled/rejected by broker", severity='warning', source='order_chaser')
                    except Exception:
                        pass
                    return
                if verified == 'UNKNOWN':
                    _unknown_count = getattr(order, '_unknown_count', 0) + 1
                    order._unknown_count = _unknown_count
                    if _unknown_count >= 3:
                        print(f"[ORDER_CHASER] Entry order {order.order_id} status UNKNOWN {_unknown_count}x — removing (persistent failure)")
                        async with self._lock:
                            if order.order_id in self._tracked_entry_orders:
                                self._tracked_entry_orders[order.order_id].status = OrderChaseStatus.CANCELLED
                                del self._tracked_entry_orders[order.order_id]
                        try:
                            from gui_app.database import record_order_event
                            record_order_event('ORDER_CANCELLED', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=order.quantity, price=order.original_price, order_id=order.order_id, status='CANCELLED', reason=f"Entry order status unknown {_unknown_count}x — assumed cancelled", severity='warning', source='order_chaser')
                        except Exception:
                            pass
                    else:
                        print(f"[ORDER_CHASER] Entry order {order.order_id} status UNKNOWN ({_unknown_count}/3) — keeping tracked (may be API issue)")
                        order.status = OrderChaseStatus.PENDING
                    return
                else:
                    print(f"[ORDER_CHASER] Entry order {order.order_id} verified as filled")
                await self.mark_entry_filled(order.order_id)
                return
            
            chase_price = await self._get_entry_chase_price(broker, order)
            if not chase_price:
                print(f"[ORDER_CHASER] ⚠️ Could not get chase price for {order.symbol}")
                order.status = OrderChaseStatus.PENDING
                return
            
            # Check against max chase price (slippage limit or entry range)
            max_allowed = order.max_chase_price
            if max_allowed and chase_price > max_allowed:
                if order.slippage_max_pct and order.signal_price:
                    print(f"[ORDER_CHASER] ⚠️ Chase price ${chase_price:.2f} exceeds slippage limit {order.slippage_max_pct}% (${max_allowed:.2f}) - skipping")
                else:
                    print(f"[ORDER_CHASER] ⚠️ Chase price ${chase_price:.2f} exceeds entry range ${max_allowed:.2f} - skipping")
                order.status = OrderChaseStatus.PENDING
                return
            
            print(f"[ORDER_CHASER]   New Chase Price: ${chase_price:.2f}")

            remaining_qty = self._get_remaining_qty(pending_orders, order.order_id, int(order.quantity))
            if remaining_qty <= 0:
                print(f"[ORDER_CHASER] Entry order fully filled (partial fills consumed all qty) — marking filled")
                await self.mark_entry_filled(order.order_id)
                return

            cancel_ok = await self._cancel_broker_order(broker, order.order_id, order.asset_type, order.broker_id)
            if not cancel_ok:
                print(f"[ORDER_CHASER] ❌ Failed to cancel entry order")
                order.status = OrderChaseStatus.PENDING
                return
            
            print(f"[ORDER_CHASER] ✓ Cancelled original entry order")

            post_cancel_pending, settled = await self._wait_for_cancel_settlement(broker, order.order_id, max_checks=3)
            if not settled:
                print(f"[ORDER_CHASER] ⚠️ Entry order {order.order_id} still active after 3 settlement checks — aborting replacement")
                order.status = OrderChaseStatus.PENDING
                return

            original_total_qty = int(order.quantity)
            order_in_pending = any(
                str(po.get('order_id', '')) == str(order.order_id)
                for po in (post_cancel_pending or [])
            )
            if not order_in_pending:
                verified = await self._verify_order_fill(broker, order.order_id, order.symbol, order.asset_type, order.action)
                if verified == 'PENDING_ACTIVATION':
                    print(f"[ORDER_CHASER] Entry order {order.order_id} is PENDING_ACTIVATION during cancel window — not replacing")
                    order.status = OrderChaseStatus.PENDING
                    return
                if verified and verified not in ('CANCELLED', 'UNKNOWN'):
                    print(f"[ORDER_CHASER] Entry order {order.order_id} verified as filled during cancel window")
                    await self.mark_entry_filled(order.order_id)
                    return
                replace_qty = original_total_qty
            else:
                replace_qty = self._get_remaining_qty(post_cancel_pending, order.order_id, original_total_qty)

            if replace_qty <= 0:
                print(f"[ORDER_CHASER] Entry order fully filled during cancel window — marking filled")
                await self.mark_entry_filled(order.order_id)
                return
            new_order_id = await self._place_entry_replacement_order(broker, order, chase_price, quantity_override=replace_qty)
            
            if new_order_id:
                print(f"[ORDER_CHASER] ✓ Placed replacement entry order: {new_order_id} @ ${chase_price:.2f} qty={replace_qty}")
                order.replacement_order_id = new_order_id
                order.status = OrderChaseStatus.REPLACED

                self._update_db_trade_order_id(order.order_id, new_order_id, order.symbol)
                
                async with self._lock:
                    if order.order_id in self._tracked_entry_orders:
                        del self._tracked_entry_orders[order.order_id]
                    
                    new_tracked = TrackedEntryOrder(
                        order_id=new_order_id,
                        broker_id=order.broker_id,
                        symbol=order.symbol,
                        asset_type=order.asset_type,
                        quantity=replace_qty,
                        original_price=chase_price,
                        action=order.action,
                        placed_at=datetime.now(),
                        channel_id=order.channel_id,
                        strike=order.strike,
                        expiry=order.expiry,
                        call_put=order.call_put,
                        entry_range_high=order.entry_range_high,
                        slippage_max_pct=order.slippage_max_pct,
                        signal_price=order.signal_price,
                        timeout_minutes=order.timeout_minutes,
                        limit_cap_price=order.limit_cap_price,
                        stop_loss_price=order.stop_loss_price,
                        profit_target_price=order.profit_target_price,
                        chase_attempts=order.chase_attempts
                    )
                    self._tracked_entry_orders[new_order_id] = new_tracked
            else:
                print(f"[ORDER_CHASER] ❌ Failed to place entry replacement order — immediate retry")
                await asyncio.sleep(0.2)
                retry_order_id = await self._place_entry_replacement_order(broker, order, chase_price, quantity_override=replace_qty)
                if retry_order_id:
                    print(f"[ORDER_CHASER] ✓ Entry retry succeeded: {retry_order_id} @ ${chase_price:.2f}")
                    order.replacement_order_id = retry_order_id
                    order.status = OrderChaseStatus.REPLACED
                    self._update_db_trade_order_id(order.order_id, retry_order_id, order.symbol)
                    async with self._lock:
                        if order.order_id in self._tracked_entry_orders:
                            del self._tracked_entry_orders[order.order_id]
                        new_tracked = TrackedEntryOrder(
                            order_id=retry_order_id,
                            broker_id=order.broker_id,
                            symbol=order.symbol,
                            asset_type=order.asset_type,
                            quantity=replace_qty,
                            original_price=chase_price,
                            action=order.action,
                            placed_at=datetime.now(),
                            channel_id=order.channel_id,
                            strike=order.strike,
                            expiry=order.expiry,
                            call_put=order.call_put,
                            entry_range_high=order.entry_range_high,
                            slippage_max_pct=order.slippage_max_pct,
                            signal_price=order.signal_price,
                            timeout_minutes=order.timeout_minutes,
                            limit_cap_price=order.limit_cap_price,
                            stop_loss_price=order.stop_loss_price,
                            profit_target_price=order.profit_target_price,
                            chase_attempts=order.chase_attempts
                        )
                        self._tracked_entry_orders[retry_order_id] = new_tracked
                else:
                    print(f"[ORDER_CHASER] ❌ Entry retry also failed — untracking cancelled order")
                    async with self._lock:
                        if order.order_id in self._tracked_entry_orders:
                            del self._tracked_entry_orders[order.order_id]
                    try:
                        from gui_app.database import record_order_event
                        record_order_event('CHASER_ENTRY_REPLACE_FAILED', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=replace_qty, price=chase_price, order_id=order.order_id, reason=f"Cancel succeeded but both entry replacement attempts failed (attempt {order.chase_attempts})", severity='error', source='order_chaser')
                    except Exception:
                        pass
            
            print(f"[ORDER_CHASER] {'='*50}\n")
            
        except Exception as e:
            print(f"[ORDER_CHASER] Entry chase error for {order.order_id}: {e}")
            import traceback
            traceback.print_exc()
            order.status = OrderChaseStatus.PENDING
    
    async def _get_entry_chase_price(self, broker, order: TrackedEntryOrder) -> Optional[float]:
        """Get chase price for entry orders — uses ASK for fast fills.
        
        Entry orders are buys: hitting the ask fills instantly.
        Streaming hubs checked first (zero API cost), then REST fallback.
        """
        try:
            if order.asset_type == 'option':
                if not (order.strike and order.expiry and order.call_put):
                    print(f"[ORDER_CHASER] ⚠️ Option order missing fields: strike={order.strike}, expiry={order.expiry}, call_put={order.call_put} — cannot get option chase price")
                    return None
                hub_data = self._check_streaming_hubs_option(order.symbol, order.strike, order.expiry, order.call_put)
                if hub_data:
                    bid = float(hub_data.get('bid', 0) or 0)
                    ask = float(hub_data.get('ask', 0) or 0)
                    last = float(hub_data.get('last', 0) or 0)
                    if bid > 0 and ask > 0:
                        mid = round((bid + ask) / 2, 2)
                        print(f"[ORDER_CHASER]   Hub: Bid ${bid:.2f} | Ask ${ask:.2f} | Mid ${mid:.2f}")
                        return ask
                    elif ask > 0:
                        return ask
                    elif last > 0:
                        return last
                quote = await self._safe_get_option_quote(broker, order.symbol, order.strike, order.expiry, order.call_put)
                if quote:
                    bid = quote.get('bid', 0)
                    ask = quote.get('ask', 0)
                    if bid and ask:
                        print(f"[ORDER_CHASER]   REST: Bid ${bid:.2f} | Ask ${ask:.2f}")
                        return ask
                    if ask:
                        return ask
                    return quote.get('last')
                return None
            else:
                hub_data = self._check_streaming_hubs_stock(order.symbol, order.broker_id)
                if hub_data:
                    ask = float(hub_data.get('ask', 0) or 0)
                    close = float(hub_data.get('close', 0) or 0)
                    last = float(hub_data.get('last', 0) or 0)
                    if ask > 0:
                        return ask
                    elif close > 0:
                        return close
                    elif last > 0:
                        return last

                if hasattr(broker, 'get_quote_with_bid_ask'):
                    method = broker.get_quote_with_bid_ask
                    result = method(order.symbol)
                    if inspect.iscoroutine(result):
                        quote = await result
                    else:
                        quote = result
                    if quote:
                        ask = float(quote.get('ask', 0) or 0)
                        if ask > 0:
                            return ask
                        close = float(quote.get('close', 0) or 0)
                        if close > 0:
                            return close
                
                if hasattr(broker, 'get_quote'):
                    method = broker.get_quote
                    result = method(order.symbol)
                    if inspect.iscoroutine(result):
                        price = await result
                    else:
                        price = result
                    if isinstance(price, dict):
                        ask_val = float(price.get('ask', 0) or 0)
                        if ask_val > 0:
                            return ask_val
                        close_val = float(price.get('close', 0) or 0)
                        if close_val > 0:
                            return close_val
                        price = (price.get('last') or
                                 price.get('price') or price.get('latestPrice'))
                    return float(price) if price is not None else None
            
            return None
        except Exception as e:
            print(f"[ORDER_CHASER] Error getting entry chase price: {e}")
            return None
    
    async def _place_entry_replacement_order(
        self,
        broker,
        order: TrackedEntryOrder,
        price: float,
        quantity_override: Optional[int] = None
    ) -> Optional[str]:
        """Place a replacement entry order at the specified price.
        
        If the original order had bracket metadata (SL/PT), attempts to place
        a bracket order to preserve risk protections. Falls back to simple
        order if broker doesn't support bracket or if bracket placement fails.
        """
        try:
            qty = quantity_override if quantity_override is not None else int(order.quantity)
            if qty <= 0:
                print(f"[ORDER_CHASER] ❌ Cannot place entry replacement with qty={qty}")
                return None
            if order.asset_type == 'option':
                if not order.call_put:
                    print(f"[ORDER_CHASER] ❌ Cannot place option replacement — call_put is None for {order.symbol}")
                    return None
                opt_kwargs = dict(
                    symbol=order.symbol,
                    quantity=qty,
                    price=price,
                    action=order.action,
                    strike=order.strike,
                    expiry=order.expiry,
                    option_type=order.call_put
                )
                _wb_oid = self._resolve_webull_option_id(broker, order)
                if _wb_oid:
                    opt_kwargs['option_id'] = _wb_oid
                result = await broker.place_option_order(**opt_kwargs)
            else:
                if order.stop_loss_price or order.profit_target_price:
                    print(f"[ORDER_CHASER] SL/PT on entry order — Risk Engine will place brackets after fill (SL=${order.stop_loss_price} PT=${order.profit_target_price})")
                result = await broker.place_stock_order(
                    symbol=order.symbol,
                    quantity=qty,
                    price=price,
                    action=order.action
                )
            
            return self._extract_order_id(result)
        except Exception as e:
            print(f"[ORDER_CHASER] Error placing entry replacement order: {e}")
            return None
    
    async def _cancel_unfilled_entry_order(self, order: TrackedEntryOrder):
        """Cancel an unfilled entry order after max chase attempts"""
        try:
            broker = self._get_broker(order.broker_id)
            if not broker:
                print(f"[ORDER_CHASER] ❌ Broker {order.broker_id} not available for cancel")
                return
            
            print(f"\n[ORDER_CHASER] {'='*50}")
            print(f"[ORDER_CHASER] 🚫 CANCELLING UNFILLED ENTRY ORDER")
            print(f"[ORDER_CHASER]   Order ID: {order.order_id}")
            print(f"[ORDER_CHASER]   Symbol: {order.symbol}")
            print(f"[ORDER_CHASER]   Reason: Max chase attempts ({self.max_chase_attempts}) exhausted")
            
            pending_orders = []
            if hasattr(broker, 'get_pending_orders'):
                result = broker.get_pending_orders()
                if inspect.iscoroutine(result):
                    pending_orders = await result
                else:
                    pending_orders = result
            
            order_still_pending = any(
                str(po.get('order_id', '')) == str(order.order_id)
                for po in pending_orders
            )
            
            if not order_still_pending:
                print(f"[ORDER_CHASER]   Order no longer pending (may have filled)")
                order.status = OrderChaseStatus.FILLED
                return
            
            _cancel_ok = False
            if hasattr(broker, 'cancel_order'):
                _cancel_ok = await self._cancel_broker_order(broker, order.order_id, order.asset_type, order.broker_id)
            
            if _cancel_ok:
                print(f"[ORDER_CHASER] ✅ Entry order cancelled successfully")
                order.status = OrderChaseStatus.CANCELLED
                
                async with self._lock:
                    if order.order_id in self._tracked_entry_orders:
                        del self._tracked_entry_orders[order.order_id]
            else:
                print(f"[ORDER_CHASER] ⚠️ Failed to cancel entry order")
                
            print(f"[ORDER_CHASER] {'='*50}\n")
            
        except Exception as e:
            print(f"[ORDER_CHASER] Error cancelling entry order: {e}")
            import traceback
            traceback.print_exc()
    
    async def _verify_order_fill(self, broker, order_id: str, symbol: str, asset_type: str = 'option', action: str = 'BTO') -> str:
        """Verify whether an order that left pending was actually filled.
        
        Returns: 'FILLED', 'CANCELLED', or 'UNKNOWN'
        """
        try:
            if hasattr(broker, 'get_order_status'):
                result = broker.get_order_status(order_id)
                if inspect.iscoroutine(result):
                    result = await result
                if result:
                    status_str = ''
                    if isinstance(result, str):
                        status_str = result.upper()
                    elif isinstance(result, dict):
                        status_str = str(result.get('status', '') or result.get('orderStatus', '') or '').upper()
                    if status_str:
                        if status_str in ('FILLED', 'COMPLETE', 'COMPLETED'):
                            print(f"[ORDER_CHASER] ✓ Order {order_id} verified as filled via get_order_status")
                            return 'FILLED'
                        elif status_str in ('CANCELLED', 'CANCELED', 'REJECTED', 'EXPIRED', 'FAILED'):
                            print(f"[ORDER_CHASER] Order {order_id} verified as {status_str} via get_order_status")
                            return 'CANCELLED'
                        elif status_str in ('PENDING_ACTIVATION',):
                            print(f"[ORDER_CHASER] Order {order_id} is PENDING_ACTIVATION — parked until regular market hours, do not chase")
                            return 'PENDING_ACTIVATION'
        except Exception as e:
            print(f"[ORDER_CHASER] get_order_status check failed for {order_id}: {e}")

        try:
            if hasattr(broker, 'get_positions') or hasattr(broker, 'get_positions_detailed'):
                positions = None
                if hasattr(broker, 'get_positions_detailed'):
                    result = broker.get_positions_detailed()
                    if inspect.iscoroutine(result):
                        positions = await result
                    else:
                        positions = result
                elif hasattr(broker, 'get_positions'):
                    result = broker.get_positions()
                    if inspect.iscoroutine(result):
                        positions = await result
                    else:
                        positions = result
                
                if positions is not None:
                    pos_list = positions if isinstance(positions, list) else [positions] if positions else []
                    symbol_upper = symbol.upper()
                    found = any(
                        symbol_upper in str(p.get('symbol', '') or p.get('ticker', '')).upper()
                        for p in pos_list
                    )
                    
                    if action.upper() in ('BTO', 'BUY'):
                        if len(pos_list) == 0:
                            print(f"[ORDER_CHASER] Order {order_id}: no positions at all on broker — BTO was not filled")
                            return 'CANCELLED'
                        if found:
                            print(f"[ORDER_CHASER] ✓ Order {order_id} verified as filled — {symbol} found in positions")
                            return 'FILLED'
                        else:
                            print(f"[ORDER_CHASER] Order {order_id} not found in positions — marking cancelled")
                            return 'CANCELLED'
                    elif action.upper() in ('STC', 'SELL'):
                        if found:
                            print(f"[ORDER_CHASER] Order {order_id}: {symbol} still in positions — could be partial exit, cannot confirm fill from positions alone")
                            pass
                        else:
                            print(f"[ORDER_CHASER] ✓ Order {order_id} verified as filled — {symbol} no longer in positions")
                            return 'FILLED'
        except Exception as e:
            print(f"[ORDER_CHASER] Position verification failed for {order_id}: {e}")

        print(f"[ORDER_CHASER] ⚠️ Could not verify order {order_id} status — assuming filled (fallback)")
        return 'UNKNOWN'

    def _resolve_webull_option_id(self, broker, order):
        try:
            if not hasattr(broker, 'get_cached_option_id'):
                return None
            if not order.strike or not order.expiry or not order.call_put:
                return None
            cached = broker.get_cached_option_id(
                order.symbol,
                order.strike,
                order.expiry,
                order.call_put
            )
            return str(cached) if cached else None
        except Exception:
            return None

    def _get_broker(self, broker_id: str):
        """Get broker instance by ID"""
        if not self.broker_manager:
            return None
        
        broker_map = {
            'webull': 'webull_broker',
            'Webull': 'webull_broker',
            'WEBULL': 'webull_broker',
            'alpaca': 'alpaca_paper_broker',
            'ALPACA_PAPER': 'alpaca_paper_broker',
            'ALPACA_LIVE': 'alpaca_live_broker',
            'robinhood': 'robinhood_broker',
            'Robinhood': 'robinhood_broker',
            'ROBINHOOD': 'robinhood_broker',
            'schwab': 'schwab_broker',
            'Schwab': 'schwab_broker',
            'SCHWAB': 'schwab_broker',
            'tastytrade': 'tastytrade_broker',
            'TASTYTRADE': 'tastytrade_broker',
            'tastytrade_live': 'tastytrade_broker',
            'tastytrade_paper': 'tastytrade_broker',
            'ibkr': 'ibkr_broker',
            'IBKR': 'ibkr_broker',
            'ibkr_live': 'ibkr_broker',
            'IBKR_LIVE': 'ibkr_broker',
            'ibkr_paper': 'ibkr_broker',
            'IBKR_PAPER': 'ibkr_broker',
            'trading212': 'trading212_broker',
            'TRADING212': 'trading212_broker',
            'Trading212': 'trading212_broker',
        }
        
        attr_name = broker_map.get(broker_id, f"{broker_id.lower()}_broker")
        return getattr(self.broker_manager, attr_name, None)
    
    def get_tracked_orders(self) -> List[Dict[str, Any]]:
        """Get list of currently tracked exit orders for API/GUI"""
        return [
            {
                'order_id': o.order_id,
                'broker': o.broker_id,
                'symbol': o.symbol,
                'quantity': o.quantity,
                'original_price': o.original_price,
                'status': o.status.value,
                'chase_attempts': o.chase_attempts,
                'age_seconds': (datetime.now() - o.placed_at).total_seconds(),
                'position_key': o.position_key,
                'order_type': 'exit'
            }
            for o in self._tracked_orders.values()
        ]
    
    def get_tracked_entry_orders(self) -> List[Dict[str, Any]]:
        """Get list of currently tracked entry orders for API/GUI"""
        return [
            {
                'order_id': o.order_id,
                'broker': o.broker_id,
                'symbol': o.symbol,
                'quantity': o.quantity,
                'original_price': o.original_price,
                'entry_range_high': o.entry_range_high,
                'status': o.status.value,
                'chase_attempts': o.chase_attempts,
                'age_seconds': (datetime.now() - o.placed_at).total_seconds(),
                'channel_id': o.channel_id,
                'order_type': 'entry'
            }
            for o in self._tracked_entry_orders.values()
        ]
    
    def get_all_tracked_orders(self) -> List[Dict[str, Any]]:
        """Get all tracked orders (exit + entry)"""
        return self.get_tracked_orders() + self.get_tracked_entry_orders()
    
    @property
    def tracked_count(self) -> int:
        """Number of exit orders currently being tracked"""
        return len(self._tracked_orders)
    
    @staticmethod
    def _is_market_active() -> bool:
        """Check if market is active (weekday, 4 AM - 8 PM ET).
        
        During off-hours, GTC limit orders should sit undisturbed.
        No point chasing or cancelling when market is closed.
        Returns False on exceptions (fail-safe: don't chase if unsure).
        """
        try:
            try:
                import zoneinfo
                et = zoneinfo.ZoneInfo("America/New_York")
            except (ImportError, Exception):
                from datetime import timezone
                et = timezone(timedelta(hours=-5))
            now = datetime.now(et)
            if now.weekday() >= 5:
                return False
            return 4 <= now.hour < 20
        except Exception:
            return False

    @property
    def tracked_entry_count(self) -> int:
        """Number of entry orders currently being tracked"""
        return len(self._tracked_entry_orders)
    
    @property
    def total_tracked_count(self) -> int:
        """Total number of orders being tracked"""
        return len(self._tracked_orders) + len(self._tracked_entry_orders)


unfilled_order_chaser: Optional[UnfilledOrderChaser] = None


def get_order_chaser() -> Optional[UnfilledOrderChaser]:
    """Get the global order chaser instance"""
    return unfilled_order_chaser


def init_order_chaser(broker_manager, **kwargs) -> UnfilledOrderChaser:
    """Initialize the global order chaser instance"""
    global unfilled_order_chaser
    unfilled_order_chaser = UnfilledOrderChaser(broker_manager, **kwargs)
    return unfilled_order_chaser
