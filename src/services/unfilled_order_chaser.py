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


class UnfilledOrderChaser:
    """
    Industry-grade unfilled order management service.
    
    Monitors pending exit orders and replaces stale ones with mid-price orders.
    """
    
    DEFAULT_CHASE_TIMEOUT_SECONDS = 30
    DEFAULT_MAX_CHASE_ATTEMPTS = 3
    DEFAULT_POLL_INTERVAL_SECONDS = 5
    
    def __init__(
        self,
        broker_manager,
        chase_timeout_seconds: int = DEFAULT_CHASE_TIMEOUT_SECONDS,
        max_chase_attempts: int = DEFAULT_MAX_CHASE_ATTEMPTS,
        poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    ):
        self.broker_manager = broker_manager
        self.chase_timeout = timedelta(seconds=chase_timeout_seconds)
        self.max_chase_attempts = max_chase_attempts
        self.poll_interval = poll_interval_seconds
        
        self._tracked_orders: Dict[str, TrackedExitOrder] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._enabled = True
        
        print(f"[ORDER_CHASER] Initialized (timeout={chase_timeout_seconds}s, max_attempts={max_chase_attempts})")
    
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
        self._task = asyncio.create_task(self._monitor_loop())
        print("[ORDER_CHASER] ✓ Monitoring loop started")
    
    async def stop(self):
        """Stop the order chaser"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[ORDER_CHASER] Stopped")
    
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
        """Stop tracking an order"""
        async with self._lock:
            if order_id in self._tracked_orders:
                del self._tracked_orders[order_id]
                print(f"[ORDER_CHASER] Untracked order: {order_id}")
    
    async def _monitor_loop(self):
        """Main monitoring loop - checks for stale orders and initiates chase"""
        while self._running:
            try:
                if self._enabled and self._tracked_orders:
                    await self._check_and_chase_orders()
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
                    quote = await broker.get_option_quote(
                        symbol=order.symbol,
                        strike=order.strike,
                        expiry=order.expiry,
                        call_put=order.call_put
                    )
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
                    quote = await broker.get_quote_with_bid_ask(order.symbol)
                    if quote and quote.get('mid'):
                        return quote['mid']
                
                if hasattr(broker, 'get_quote'):
                    price = await broker.get_quote(order.symbol)
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
        """Get list of currently tracked orders for API/GUI"""
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
                'position_key': o.position_key
            }
            for o in self._tracked_orders.values()
        ]
    
    @property
    def tracked_count(self) -> int:
        """Number of orders currently being tracked"""
        return len(self._tracked_orders)


unfilled_order_chaser: Optional[UnfilledOrderChaser] = None


def get_order_chaser() -> Optional[UnfilledOrderChaser]:
    """Get the global order chaser instance"""
    return unfilled_order_chaser


def init_order_chaser(broker_manager, **kwargs) -> UnfilledOrderChaser:
    """Initialize the global order chaser instance"""
    global unfilled_order_chaser
    unfilled_order_chaser = UnfilledOrderChaser(broker_manager, **kwargs)
    return unfilled_order_chaser
