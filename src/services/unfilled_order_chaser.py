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


class UnfilledOrderChaser:
    """
    Industry-grade unfilled order management service.
    
    Monitors pending exit AND entry orders and replaces stale ones with better prices.
    - Exit orders: Replaced with mid-price for balanced fills
    - Entry orders: Replaced with ask price for aggressive fills
    """
    
    DEFAULT_CHASE_TIMEOUT_SECONDS = 4
    DEFAULT_MAX_CHASE_ATTEMPTS = 3
    DEFAULT_POLL_INTERVAL_SECONDS = 1
    DEFAULT_CANCEL_ON_MAX_ATTEMPTS = True
    
    def __init__(
        self,
        broker_manager,
        chase_timeout_seconds: int = DEFAULT_CHASE_TIMEOUT_SECONDS,
        max_chase_attempts: int = DEFAULT_MAX_CHASE_ATTEMPTS,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
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
            
            max_price = order.max_chase_price
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
            _orig_price_str = f"${order.original_price:.2f}" if order.original_price is not None else "MKT"
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
                        except Exception as e:
                            print(f"[ORDER_CHASER] ⚠️ Could not clear exit lock after rejection: {e}")
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

            mid_price = await self._get_mid_price(broker, order)
            if not mid_price:
                print(f"[ORDER_CHASER] ⚠️ Could not get exit price for {order.symbol} — keeping existing order alive")
                order.status = OrderChaseStatus.PENDING
                return
            
            print(f"[ORDER_CHASER]   Exit Price (bid): ${mid_price:.2f}")

            cancel_ok = await self._cancel_broker_order(broker, order.order_id, order.asset_type, order.broker_id)
            if not cancel_ok:
                print(f"[ORDER_CHASER] ❌ Failed to cancel exit order — keeping existing order")
                order.status = OrderChaseStatus.PENDING
                return
            
            print(f"[ORDER_CHASER] ✓ Cancelled original order")
            
            await asyncio.sleep(0.5)
            
            replace_qty = remaining_qty
            new_order_id = await self._place_replacement_order(broker, order, mid_price, quantity_override=replace_qty)
            
            if new_order_id:
                print(f"[ORDER_CHASER] ✓ Placed replacement order: {new_order_id} @ ${mid_price:.2f} qty={replace_qty}")
                order.replacement_order_id = new_order_id
                order.status = OrderChaseStatus.REPLACED
                try:
                    from gui_app.database import record_order_event
                    _orig_p = f"${order.original_price:.2f}" if order.original_price is not None else "MKT"
                    record_order_event('CHASER_REPLACED', symbol=order.symbol, broker=order.broker_id, direction=order.action, quantity=replace_qty, price=mid_price, order_id=new_order_id, reason=f"Stale order replaced: {_orig_p} → ${mid_price:.2f} (attempt {order.chase_attempts}, qty {replace_qty}/{int(order.quantity)})", severity='warning', source='order_chaser', position_key=order.position_key)
                except Exception:
                    pass
                
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
                        chase_attempts=order.chase_attempts,
                        is_risk_order=order.is_risk_order
                    )
                    self._tracked_orders[new_order_id] = new_tracked
            else:
                print(f"[ORDER_CHASER] ❌ Failed to place replacement exit order — immediate retry at same price")
                await asyncio.sleep(0.5)
                retry_order_id = await self._place_replacement_order(broker, order, mid_price, quantity_override=replace_qty)
                if retry_order_id:
                    print(f"[ORDER_CHASER] ✓ Retry succeeded: {retry_order_id} @ ${mid_price:.2f}")
                    order.replacement_order_id = retry_order_id
                    order.status = OrderChaseStatus.REPLACED
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
                            chase_attempts=order.chase_attempts,
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
        return None

    def _check_streaming_hubs_stock(self, symbol: str) -> Optional[dict]:
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming():
                data = hub.get_quote_detailed(symbol)
                if data and (data.get('bid', 0) > 0 or data.get('last', 0) > 0):
                    print(f"[ORDER_CHASER] ⚡ Got stock quote from Webull hub")
                    return data
        except Exception:
            pass
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            hub = get_schwab_data_hub()
            if hub.is_streaming():
                data = hub.get_quote_detailed(symbol)
                if data and (data.get('bid', 0) > 0 or data.get('last', 0) > 0):
                    print(f"[ORDER_CHASER] ⚡ Got stock quote from Schwab hub")
                    return data
        except Exception:
            pass
        return None

    async def _get_mid_price(self, broker, order: TrackedExitOrder) -> Optional[float]:
        """Get exit price for STC orders — uses BID for fast fills.
        
        Exit orders are sells: hitting the bid fills instantly.
        Streaming hubs are checked first (zero API cost), then REST fallback.
        """
        try:
            if order.asset_type == 'option':
                if not (order.strike and order.expiry and order.call_put):
                    print(f"[ORDER_CHASER] ⚠️ Exit option order missing fields: strike={order.strike}, expiry={order.expiry}, call_put={order.call_put} — cannot get option price")
                    return None
                hub_data = self._check_streaming_hubs_option(order.symbol, order.strike, order.expiry, order.call_put)
                if hub_data:
                    bid = float(hub_data.get('bid', 0) or 0)
                    ask = float(hub_data.get('ask', 0) or 0)
                    last = float(hub_data.get('last', 0) or 0)
                    if bid > 0:
                        print(f"[ORDER_CHASER] 💰 Exit price: BID ${bid:.2f} (ask ${ask:.2f}, last ${last:.2f}) — fills instantly")
                        return bid
                    elif last > 0:
                        return last
                quote = await self._safe_get_option_quote(broker, order.symbol, order.strike, order.expiry, order.call_put)
                if quote:
                    bid = quote.get('bid', 0)
                    ask = quote.get('ask', 0)
                    if bid and bid > 0:
                        print(f"[ORDER_CHASER] 💰 Exit price: BID ${bid:.2f} (ask ${ask:.2f}) via REST — fills instantly")
                        return bid
                    last = quote.get('last')
                    if last and last > 0:
                        return last
                return None
            else:
                hub_data = self._check_streaming_hubs_stock(order.symbol)
                if hub_data:
                    bid = float(hub_data.get('bid', 0) or 0)
                    close = float(hub_data.get('close', 0) or 0)
                    last = float(hub_data.get('last', 0) or 0)
                    if bid > 0:
                        print(f"[ORDER_CHASER] 💰 Exit price: BID ${bid:.2f} — fills instantly")
                        return bid
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
                        bid = float(quote.get('bid', 0) or 0)
                        if bid > 0:
                            return bid
                        close = float(quote.get('close', 0) or 0)
                        if close > 0:
                            return close
                        return quote.get('last') or quote.get('mid')
                
                if hasattr(broker, 'get_quote'):
                    method = broker.get_quote
                    result = method(order.symbol)
                    if inspect.iscoroutine(result):
                        price = await result
                    else:
                        price = result
                    if isinstance(price, dict):
                        bid_val = float(price.get('bid', 0) or 0)
                        if bid_val > 0:
                            return bid_val
                        close_val = float(price.get('close', 0) or 0)
                        if close_val > 0:
                            return close_val
                        price = (price.get('last') or
                                 price.get('price') or price.get('latestPrice'))
                    return float(price) if price is not None else None
            
            return None
        except Exception as e:
            print(f"[ORDER_CHASER] Error getting exit price: {e}")
            return None
    
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
                result = await broker.place_option_order(
                    symbol=order.symbol,
                    quantity=qty,
                    price=price,
                    action=order.action,
                    strike=order.strike,
                    expiry=order.expiry,
                    option_type=order.call_put
                )
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
            _entry_orig_str = f"${order.original_price:.2f}" if order.original_price is not None else "MKT"
            print(f"[ORDER_CHASER]   Original Price: {_entry_orig_str}")
            if order.entry_range_high:
                print(f"[ORDER_CHASER]   Max Entry Price: ${order.entry_range_high:.2f}")
            
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
            
            await asyncio.sleep(0.5)
            
            replace_qty = remaining_qty
            new_order_id = await self._place_entry_replacement_order(broker, order, chase_price, quantity_override=replace_qty)
            
            if new_order_id:
                print(f"[ORDER_CHASER] ✓ Placed replacement entry order: {new_order_id} @ ${chase_price:.2f} qty={replace_qty}")
                order.replacement_order_id = new_order_id
                order.status = OrderChaseStatus.REPLACED
                
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
                await asyncio.sleep(0.5)
                retry_order_id = await self._place_entry_replacement_order(broker, order, chase_price, quantity_override=replace_qty)
                if retry_order_id:
                    print(f"[ORDER_CHASER] ✓ Entry retry succeeded: {retry_order_id} @ ${chase_price:.2f}")
                    order.replacement_order_id = retry_order_id
                    order.status = OrderChaseStatus.REPLACED
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
                hub_data = self._check_streaming_hubs_stock(order.symbol)
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
                result = await broker.place_option_order(
                    symbol=order.symbol,
                    quantity=qty,
                    price=price,
                    action=order.action,
                    strike=order.strike,
                    expiry=order.expiry,
                    option_type=order.call_put
                )
            else:
                has_bracket = order.stop_loss_price or order.profit_target_price
                if has_bracket and hasattr(broker, 'place_bracket_order'):
                    try:
                        print(f"[ORDER_CHASER] Placing bracket replacement: SL=${order.stop_loss_price} PT=${order.profit_target_price}")
                        result = await broker.place_bracket_order(
                            symbol=order.symbol,
                            action=order.action,
                            quantity=qty,
                            stop_loss_price=order.stop_loss_price,
                            profit_target_price=order.profit_target_price,
                            entry_price=price
                        )
                        bracket_ok = result and (
                            (hasattr(result, 'success') and result.success) or
                            (isinstance(result, dict) and result.get('orderId'))
                        )
                        if not bracket_ok:
                            err_msg = getattr(result, 'message', str(result)) if result else 'No response'
                            print(f"[ORDER_CHASER] Bracket replacement returned failure ({err_msg}), falling back to simple order")
                            result = await broker.place_stock_order(
                                symbol=order.symbol,
                                quantity=qty,
                                price=price,
                                action=order.action
                            )
                    except Exception as bracket_err:
                        print(f"[ORDER_CHASER] Bracket replacement exception ({bracket_err}), falling back to simple order")
                        result = await broker.place_stock_order(
                            symbol=order.symbol,
                            quantity=qty,
                            price=price,
                            action=order.action
                        )
                else:
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
