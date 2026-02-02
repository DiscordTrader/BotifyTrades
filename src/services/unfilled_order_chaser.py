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
    status: OrderChaseStatus = OrderChaseStatus.PENDING
    chase_attempts: int = 0
    last_chase_at: Optional[datetime] = None
    replacement_order_id: Optional[str] = None
    final_fill_price: Optional[float] = None
    
    @property
    def max_chase_price(self) -> Optional[float]:
        """Calculate maximum allowed chase price based on slippage limit.
        
        Priority: Slippage limit > Entry range (slippage is the hard limit for chasing)
        Entry range is used for initial order placement, slippage is used for chasing.
        """
        # Use slippage limit as the primary limit for chasing
        if self.slippage_max_pct and self.signal_price:
            max_with_slippage = self.signal_price * (1 + self.slippage_max_pct / 100)
            return round(max_with_slippage, 2)
        
        # Fall back to entry range high if no slippage configured
        if self.entry_range_high:
            return self.entry_range_high
        
        return None


class UnfilledOrderChaser:
    """
    Industry-grade unfilled order management service.
    
    Monitors pending exit AND entry orders and replaces stale ones with better prices.
    - Exit orders: Replaced with mid-price for balanced fills
    - Entry orders: Replaced with ask price for aggressive fills
    """
    
    DEFAULT_CHASE_TIMEOUT_SECONDS = 30
    DEFAULT_MAX_CHASE_ATTEMPTS = 3
    DEFAULT_POLL_INTERVAL_SECONDS = 5
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
        call_put: Optional[str] = None
    ) -> None:
        """
        Register an exit order for monitoring.
        Called by RiskManager after placing an STC order.
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
                call_put=call_put
            )
            self._tracked_orders[order_id] = order
            print(f"[ORDER_CHASER] Tracking exit order: {order_id} | {symbol} {quantity}x @ ${price:.2f}")
    
    async def mark_filled(self, order_id: str, fill_price: Optional[float] = None):
        """Mark an order as filled and stop tracking it"""
        async with self._lock:
            if order_id in self._tracked_orders:
                order = self._tracked_orders[order_id]
                order.status = OrderChaseStatus.FILLED
                order.final_fill_price = fill_price
                del self._tracked_orders[order_id]
                print(f"[ORDER_CHASER] ✓ Order filled: {order_id} @ ${fill_price:.2f}" if fill_price else f"[ORDER_CHASER] ✓ Order filled: {order_id}")
    
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
        timeout_minutes: Optional[int] = None
    ) -> None:
        """
        Register an entry order (BTO) for monitoring.
        Called after placing a BTO order that might not fill immediately.
        
        Args:
            slippage_max_pct: Per-channel max slippage % (e.g., 10 means max 10% above signal price)
            signal_price: Original signal price for slippage calculation
            timeout_minutes: Per-channel timeout in minutes (from order_timeout_minutes)
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
                timeout_minutes=timeout_minutes
            )
            self._tracked_entry_orders[order_id] = order
            
            max_price = order.max_chase_price
            max_info = f"max ${max_price:.2f}" if max_price else "no limit"
            if slippage_max_pct:
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
        while self._running:
            try:
                if self._enabled and self._tracked_orders:
                    await self._check_and_chase_orders()
                if self._entry_chase_enabled and self._tracked_entry_orders:
                    await self._check_and_chase_entry_orders()
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
        now = datetime.now()
        orders_to_chase = []
        
        async with self._lock:
            for order_id, order in list(self._tracked_orders.items()):
                if order.status != OrderChaseStatus.PENDING:
                    continue
                
                age = now - order.placed_at
                if age > self.chase_timeout:
                    if order.chase_attempts < self.max_chase_attempts:
                        orders_to_chase.append(order)
                    else:
                        print(f"[ORDER_CHASER] ⚠️ Max chase attempts reached for {order_id}")
                        order.status = OrderChaseStatus.FAILED
        
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
            print(f"[ORDER_CHASER]   Original Price: ${order.original_price:.2f}")
            
            pending_orders = await broker.get_pending_orders()
            order_still_pending = any(
                str(po.get('order_id', '')) == str(order.order_id) 
                for po in pending_orders
            )
            
            if not order_still_pending:
                print(f"[ORDER_CHASER] Order {order.order_id} no longer pending - may have filled")
                await self.mark_filled(order.order_id)
                return
            
            mid_price = await self._get_mid_price(broker, order)
            if not mid_price:
                print(f"[ORDER_CHASER] ⚠️ Could not get mid-price for {order.symbol}")
                order.status = OrderChaseStatus.PENDING
                return
            
            print(f"[ORDER_CHASER]   Mid Price: ${mid_price:.2f}")
            
            cancel_result = await broker.cancel_order(order.order_id)
            if not cancel_result.get('success'):
                print(f"[ORDER_CHASER] ❌ Failed to cancel: {cancel_result.get('error')}")
                order.status = OrderChaseStatus.PENDING
                return
            
            print(f"[ORDER_CHASER] ✓ Cancelled original order")
            
            await asyncio.sleep(0.5)
            
            new_order_id = await self._place_replacement_order(broker, order, mid_price)
            
            if new_order_id:
                print(f"[ORDER_CHASER] ✓ Placed replacement order: {new_order_id} @ ${mid_price:.2f}")
                order.replacement_order_id = new_order_id
                order.status = OrderChaseStatus.REPLACED
                
                async with self._lock:
                    if order.order_id in self._tracked_orders:
                        del self._tracked_orders[order.order_id]
                    
                    new_tracked = TrackedExitOrder(
                        order_id=new_order_id,
                        broker_id=order.broker_id,
                        symbol=order.symbol,
                        asset_type=order.asset_type,
                        quantity=order.quantity,
                        original_price=mid_price,
                        action=order.action,
                        placed_at=datetime.now(),
                        position_key=order.position_key,
                        strike=order.strike,
                        expiry=order.expiry,
                        call_put=order.call_put,
                        chase_attempts=order.chase_attempts
                    )
                    self._tracked_orders[new_order_id] = new_tracked
            else:
                print(f"[ORDER_CHASER] ❌ Failed to place replacement order")
                order.status = OrderChaseStatus.FAILED
            
            print(f"[ORDER_CHASER] {'='*50}\n")
            
        except Exception as e:
            print(f"[ORDER_CHASER] Chase error for {order.order_id}: {e}")
            import traceback
            traceback.print_exc()
            order.status = OrderChaseStatus.PENDING
    
    async def _get_mid_price(self, broker, order: TrackedExitOrder) -> Optional[float]:
        """Get mid-price between bid and ask for the asset"""
        try:
            if order.asset_type == 'option' and order.strike and order.expiry and order.call_put:
                if hasattr(broker, 'get_option_quote'):
                    method = broker.get_option_quote
                    result = method(
                        symbol=order.symbol,
                        strike=order.strike,
                        expiry=order.expiry,
                        call_put=order.call_put
                    )
                    if inspect.iscoroutine(result):
                        quote = await result
                    else:
                        quote = result
                    if quote and quote.get('mid'):
                        return quote['mid']
                    elif quote:
                        bid = quote.get('bid', 0)
                        ask = quote.get('ask', 0)
                        if bid and ask:
                            return round((bid + ask) / 2, 2)
                        return quote.get('last')
            else:
                if hasattr(broker, 'get_quote_with_bid_ask'):
                    method = broker.get_quote_with_bid_ask
                    result = method(order.symbol)
                    if inspect.iscoroutine(result):
                        quote = await result
                    else:
                        quote = result
                    if quote and quote.get('mid'):
                        return quote['mid']
                
                if hasattr(broker, 'get_quote'):
                    method = broker.get_quote
                    result = method(order.symbol)
                    if inspect.iscoroutine(result):
                        price = await result
                    else:
                        price = result
                    return price
            
            return None
        except Exception as e:
            print(f"[ORDER_CHASER] Error getting mid-price: {e}")
            return None
    
    async def _place_replacement_order(
        self,
        broker,
        order: TrackedExitOrder,
        price: float
    ) -> Optional[str]:
        """Place a replacement order at the specified price"""
        try:
            if order.asset_type == 'option':
                result = await broker.place_option_order(
                    symbol=order.symbol,
                    quantity=int(order.quantity),
                    price=price,
                    action=order.action,
                    strike=order.strike,
                    expiry=order.expiry,
                    direction=order.call_put,
                    order_type='LIMIT'
                )
            else:
                result = await broker.place_order(
                    symbol=order.symbol,
                    quantity=int(order.quantity),
                    price=price,
                    action=order.action,
                    order_type='LIMIT'
                )
            
            if result and hasattr(result, 'order_id') and result.order_id:
                return result.order_id
            elif result and isinstance(result, dict) and result.get('order_id'):
                return result['order_id']
            
            return None
        except Exception as e:
            print(f"[ORDER_CHASER] Error placing replacement order: {e}")
            return None
    
    async def _check_and_chase_entry_orders(self):
        """Check all tracked entry orders and chase stale ones"""
        now = datetime.now()
        orders_to_chase = []
        orders_to_cancel = []
        
        async with self._lock:
            for order_id, order in list(self._tracked_entry_orders.items()):
                if order.status != OrderChaseStatus.PENDING:
                    continue
                
                age = now - order.placed_at
                age_seconds = age.total_seconds()
                
                # Check channel-level timeout (order_timeout_minutes) - CANCEL if exceeded
                if order.timeout_minutes:
                    timeout_seconds = order.timeout_minutes * 60
                    if age_seconds >= timeout_seconds:
                        print(f"[ORDER_CHASER] ⏰ Channel timeout ({order.timeout_minutes}min) reached for {order_id}")
                        order.status = OrderChaseStatus.FAILED
                        orders_to_cancel.append(order)
                        continue
                
                # Check chase timeout (30s default) - CHASE if exceeded but within channel timeout
                if age > self.chase_timeout:
                    if order.chase_attempts < self.max_chase_attempts:
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
            print(f"[ORDER_CHASER]   Original Price: ${order.original_price:.2f}")
            if order.entry_range_high:
                print(f"[ORDER_CHASER]   Max Entry Price: ${order.entry_range_high:.2f}")
            
            pending_orders = await broker.get_pending_orders()
            order_still_pending = any(
                str(po.get('order_id', '')) == str(order.order_id) 
                for po in pending_orders
            )
            
            if not order_still_pending:
                print(f"[ORDER_CHASER] Entry order {order.order_id} no longer pending - may have filled")
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
            
            cancel_result = await broker.cancel_order(order.order_id)
            if not cancel_result.get('success'):
                print(f"[ORDER_CHASER] ❌ Failed to cancel entry order: {cancel_result.get('error')}")
                order.status = OrderChaseStatus.PENDING
                return
            
            print(f"[ORDER_CHASER] ✓ Cancelled original entry order")
            
            await asyncio.sleep(0.5)
            
            new_order_id = await self._place_entry_replacement_order(broker, order, chase_price)
            
            if new_order_id:
                print(f"[ORDER_CHASER] ✓ Placed replacement entry order: {new_order_id} @ ${chase_price:.2f}")
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
                        quantity=order.quantity,
                        original_price=chase_price,
                        action=order.action,
                        placed_at=datetime.now(),
                        channel_id=order.channel_id,
                        strike=order.strike,
                        expiry=order.expiry,
                        call_put=order.call_put,
                        entry_range_high=order.entry_range_high,
                        chase_attempts=order.chase_attempts
                    )
                    self._tracked_entry_orders[new_order_id] = new_tracked
            else:
                print(f"[ORDER_CHASER] ❌ Failed to place entry replacement order")
                order.status = OrderChaseStatus.FAILED
            
            print(f"[ORDER_CHASER] {'='*50}\n")
            
        except Exception as e:
            print(f"[ORDER_CHASER] Entry chase error for {order.order_id}: {e}")
            import traceback
            traceback.print_exc()
            order.status = OrderChaseStatus.PENDING
    
    async def _get_entry_chase_price(self, broker, order: TrackedEntryOrder) -> Optional[float]:
        """Get chase price for entry orders - use mid-price or ask for better fills"""
        try:
            if order.asset_type == 'option' and order.strike and order.expiry and order.call_put:
                if hasattr(broker, 'get_option_quote'):
                    method = broker.get_option_quote
                    result = method(
                        symbol=order.symbol,
                        strike=order.strike,
                        expiry=order.expiry,
                        call_put=order.call_put
                    )
                    if inspect.iscoroutine(result):
                        quote = await result
                    else:
                        quote = result
                    if quote:
                        bid = quote.get('bid', 0)
                        ask = quote.get('ask', 0)
                        if bid and ask:
                            mid = round((bid + ask) / 2, 2)
                            print(f"[ORDER_CHASER]   Bid: ${bid:.2f} | Ask: ${ask:.2f} | Mid: ${mid:.2f}")
                            return mid
                        if ask:
                            return ask
                        return quote.get('last')
            else:
                if hasattr(broker, 'get_quote_with_bid_ask'):
                    method = broker.get_quote_with_bid_ask
                    result = method(order.symbol)
                    if inspect.iscoroutine(result):
                        quote = await result
                    else:
                        quote = result
                    if quote:
                        bid = quote.get('bid', 0)
                        ask = quote.get('ask', 0)
                        if bid and ask:
                            return round((bid + ask) / 2, 2)
                        if ask:
                            return ask
                
                if hasattr(broker, 'get_quote'):
                    method = broker.get_quote
                    result = method(order.symbol)
                    if inspect.iscoroutine(result):
                        price = await result
                    else:
                        price = result
                    return price
            
            return None
        except Exception as e:
            print(f"[ORDER_CHASER] Error getting entry chase price: {e}")
            return None
    
    async def _place_entry_replacement_order(
        self,
        broker,
        order: TrackedEntryOrder,
        price: float
    ) -> Optional[str]:
        """Place a replacement entry order at the specified price"""
        try:
            if order.asset_type == 'option':
                result = await broker.place_option_order(
                    symbol=order.symbol,
                    quantity=int(order.quantity),
                    price=price,
                    action=order.action,
                    strike=order.strike,
                    expiry=order.expiry,
                    direction=order.call_put,
                    order_type='LIMIT'
                )
            else:
                result = await broker.place_order(
                    symbol=order.symbol,
                    quantity=int(order.quantity),
                    price=price,
                    action=order.action,
                    order_type='LIMIT'
                )
            
            if result and hasattr(result, 'order_id') and result.order_id:
                return result.order_id
            elif result and isinstance(result, dict) and result.get('order_id'):
                return result['order_id']
            
            return None
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
            
            cancel_result = None
            if hasattr(broker, 'cancel_order'):
                result = broker.cancel_order(order.order_id)
                if inspect.iscoroutine(result):
                    cancel_result = await result
                else:
                    cancel_result = result
            
            if cancel_result:
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
