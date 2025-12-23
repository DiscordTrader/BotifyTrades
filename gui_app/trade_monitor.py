"""
Trade Monitor Service
Monitors broker accounts for new trades and posts them as signals to Discord
"""

import sys
sys.stdout.write("[TRADE MONITOR MODULE] Loading trade_monitor.py - v2\n")
sys.stdout.flush()

import asyncio
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List

try:
    from gui_app import database as db
except ImportError:
    import database as db


class TradeMonitor:
    """Monitors broker for new filled orders and posts to Discord"""
    
    def __init__(self, broker=None):
        self.broker = broker
        self.running = False
        self._task = None
        self._last_poll_time = None
        
    def set_broker(self, broker):
        """Set the broker instance to monitor"""
        self.broker = broker
        
    async def start(self):
        """Start the trade monitor loop"""
        sys.stdout.write(f"[TRADE MONITOR] start() called, running={self.running}, broker={self.broker is not None}\n")
        sys.stdout.flush()
        if self.running:
            sys.stdout.write("[TRADE MONITOR] Already running\n")
            sys.stdout.flush()
            return
            
        settings = db.get_trade_monitor_settings()
        if not settings.get('enabled'):
            sys.stdout.write("[TRADE MONITOR] Disabled in settings, not starting\n")
            sys.stdout.flush()
            return
            
        if not self.broker:
            sys.stdout.write("[TRADE MONITOR] No broker connected, cannot start\n")
            sys.stdout.flush()
            return
        
        broker_name = getattr(self.broker, 'name', type(self.broker).__name__)
        sys.stdout.write(f"[TRADE MONITOR] Broker: {broker_name}\n")
        sys.stdout.flush()
            
        self.running = True
        sys.stdout.write("[TRADE MONITOR] Starting trade monitor poll loop...\n")
        sys.stdout.flush()
        self._task = asyncio.create_task(self._poll_loop())
        sys.stdout.write("[TRADE MONITOR] Poll task created\n")
        sys.stdout.flush()
        
    async def stop(self):
        """Stop the trade monitor"""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[TRADE MONITOR] Stopped")
        
    async def _poll_loop(self):
        """Main polling loop"""
        sys.stdout.write("[TRADE MONITOR] Poll loop started\n")
        sys.stdout.flush()
        while self.running:
            try:
                settings = db.get_trade_monitor_settings()
                if not settings.get('enabled'):
                    sys.stdout.write("[TRADE MONITOR] Disabled, stopping...\n")
                    sys.stdout.flush()
                    self.running = False
                    break
                    
                poll_interval = settings.get('poll_interval_seconds', 10)
                test_mode_setting = db.get_setting('trade_monitor_test_mode', 'false')
                test_mode = test_mode_setting.lower() == 'true'
                
                sys.stdout.write(f"[TRADE MONITOR] Polling... (test_mode={test_mode}, interval={poll_interval}s)\n")
                sys.stdout.flush()
                
                await self._check_for_new_orders(settings)
                
                self._last_poll_time = datetime.now()
                await asyncio.sleep(poll_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                sys.stdout.write(f"[TRADE MONITOR] Error in poll loop: {e}\n")
                sys.stdout.flush()
                import traceback
                traceback.print_exc()
                await asyncio.sleep(10)
                
    async def _check_for_new_orders(self, settings: Dict[str, Any]):
        """Check broker for new filled orders (and pending orders in test mode)"""
        if not self.broker:
            sys.stdout.write("[TRADE MONITOR] No broker set, skipping order check\n")
            sys.stdout.flush()
            return
            
        broker_name = getattr(self.broker, 'name', 'UNKNOWN')
        test_mode_setting = db.get_setting('trade_monitor_test_mode', 'false')
        test_mode = test_mode_setting.lower() == 'true'
        
        sys.stdout.write(f"[TRADE MONITOR] Checking orders for {broker_name} (test_mode={test_mode})\n")
        sys.stdout.flush()
        
        try:
            orders = []
            
            has_order_history = hasattr(self.broker, 'get_order_history')
            sys.stdout.write(f"[TRADE MONITOR] has_order_history={has_order_history}\n")
            sys.stdout.flush()
            
            if has_order_history:
                filled_orders = await self.broker.get_order_history(count=20)
                sys.stdout.write(f"[TRADE MONITOR] get_order_history returned: {type(filled_orders)}, count={len(filled_orders) if filled_orders else 0}\n")
                sys.stdout.flush()
                if filled_orders:
                    for order in filled_orders:
                        order['_status'] = 'FILLED'
                    orders.extend(filled_orders)
            
            has_pending_orders = hasattr(self.broker, 'get_pending_orders')
            sys.stdout.write(f"[TRADE MONITOR] has_pending_orders={has_pending_orders}, test_mode={test_mode}\n")
            sys.stdout.flush()
            
            if test_mode and has_pending_orders:
                pending_orders = await self.broker.get_pending_orders()
                sys.stdout.write(f"[TRADE MONITOR] get_pending_orders returned: {type(pending_orders)}, count={len(pending_orders) if pending_orders else 0}\n")
                sys.stdout.flush()
                if pending_orders:
                    for order in pending_orders:
                        order['_status'] = 'PENDING'
                    orders.extend(pending_orders)
                    sys.stdout.write(f"[TRADE MONITOR] Test mode: Found {len(pending_orders)} pending orders\n")
                    sys.stdout.flush()
                
            sys.stdout.write(f"[TRADE MONITOR] Total orders to process: {len(orders)}\n")
            sys.stdout.flush()
                
            if not orders:
                return
                
            include_stocks = settings.get('include_stocks', True)
            include_options = settings.get('include_options', True)
            post_bto = settings.get('post_bto_signals', True)
            post_stc = settings.get('post_stc_signals', True)
            target_channel = settings.get('target_webhook_channel_id')
            
            new_orders = []
            for order in orders:
                order_id = order.get('order_id')
                sys.stdout.write(f"[TRADE MONITOR] Processing order: {order}\n")
                sys.stdout.flush()
                
                if not order_id:
                    sys.stdout.write(f"[TRADE MONITOR] Skipping order - no order_id\n")
                    sys.stdout.flush()
                    continue
                    
                if db.is_order_synced(broker_name, order_id):
                    sys.stdout.write(f"[TRADE MONITOR] Skipping order {order_id} - already synced\n")
                    sys.stdout.flush()
                    continue
                    
                asset_type = order.get('asset_type', 'stock')
                if asset_type == 'stock' and not include_stocks:
                    sys.stdout.write(f"[TRADE MONITOR] Skipping order {order_id} - stocks not included\n")
                    sys.stdout.flush()
                    continue
                if asset_type == 'option' and not include_options:
                    sys.stdout.write(f"[TRADE MONITOR] Skipping order {order_id} - options not included\n")
                    sys.stdout.flush()
                    continue
                    
                action = order.get('action', '').upper()
                is_buy = action in ['BUY', 'BTO']
                is_sell = action in ['SELL', 'STC']
                
                if is_buy and not post_bto:
                    sys.stdout.write(f"[TRADE MONITOR] Skipping order {order_id} - BTO not enabled\n")
                    sys.stdout.flush()
                    continue
                if is_sell and not post_stc:
                    sys.stdout.write(f"[TRADE MONITOR] Skipping order {order_id} - STC not enabled\n")
                    sys.stdout.flush()
                    continue
                
                sys.stdout.write(f"[TRADE MONITOR] Order {order_id} passed filters, adding to new_orders\n")
                sys.stdout.flush()
                new_orders.append(order)
            
            sys.stdout.write(f"[TRADE MONITOR] New orders to post: {len(new_orders)}\n")
            sys.stdout.flush()
                
            for order in new_orders:
                sys.stdout.write(f"[TRADE MONITOR] Posting order to Discord: {order.get('order_id')}\n")
                sys.stdout.flush()
                await self._post_order_to_discord(order, broker_name, target_channel)
                
        except Exception as e:
            print(f"[TRADE MONITOR] Error checking orders: {e}", flush=True)
            
    async def _post_order_to_discord(self, order: Dict, broker_name: str, target_channel: str = None):
        """Post a filled order as a signal to Discord"""
        order_id = order.get('order_id')
        symbol = order.get('symbol', 'UNKNOWN')
        action = order.get('action', '').upper()
        quantity = order.get('quantity', 0)
        filled_price = order.get('filled_price', order.get('limit_price', 0))
        asset_type = order.get('asset_type', 'stock')
        order_status = order.get('_status', 'FILLED')
        
        is_buy = action in ['BUY', 'BTO']
        signal_type = 'BTO' if is_buy else 'STC'
        
        test_prefix = "[TEST] " if order_status == 'PENDING' else ""
        
        if asset_type == 'option':
            strike = order.get('strike', 0)
            expiry = order.get('expiry', '')
            direction = order.get('direction', 'C').lower()
            
            if expiry and '-' in expiry:
                try:
                    from datetime import datetime as dt
                    exp_date = dt.strptime(expiry, '%Y-%m-%d')
                    expiry = exp_date.strftime('%m/%d')
                except:
                    pass
            
            strike_str = f"{int(strike)}" if strike == int(strike) else f"{strike}"
            signal_msg = f"{test_prefix}{signal_type} {quantity} {symbol} {strike_str}{direction} {expiry} @ {filled_price:.2f}"
        else:
            signal_msg = f"{test_prefix}{signal_type} {quantity} {symbol} @ {filled_price:.2f}"
        
        posted = False
        channel_id = None
        
        if target_channel:
            webhook_url = self._get_webhook_url(target_channel)
            if webhook_url:
                try:
                    resp = requests.post(webhook_url, json={"content": signal_msg}, timeout=10)
                    if resp.status_code in [200, 204]:
                        posted = True
                        channel_id = target_channel
                        print(f"[TRADE MONITOR] Posted {signal_type} {symbol} to webhook", flush=True)
                except Exception as e:
                    print(f"[TRADE MONITOR] Failed to post to webhook: {e}", flush=True)
        
        db.add_synced_order(
            broker=broker_name,
            order_id=order_id,
            symbol=symbol,
            action=signal_type,
            quantity=quantity,
            filled_price=filled_price,
            asset_type=asset_type,
            strike=order.get('strike'),
            expiry=order.get('expiry'),
            direction=order.get('direction'),
            discord_channel_id=channel_id
        )
        
        if posted:
            print(f"[TRADE MONITOR] ✓ Synced {signal_type} {symbol} from {broker_name}", flush=True)
        else:
            print(f"[TRADE MONITOR] Recorded {signal_type} {symbol} (no webhook configured)", flush=True)
            
    def _get_webhook_url(self, channel_id: str) -> Optional[str]:
        """Get webhook URL for a channel from webhook_channels table"""
        try:
            from gui_app import webhook_service
            channel = webhook_service.get_webhook_channel(int(channel_id))
            if channel and channel.get('enabled'):
                return channel.get('webhook_url')
            return None
        except Exception as e:
            print(f"[TRADE MONITOR] Error getting webhook: {e}", flush=True)
            return None


_trade_monitor_instance = None

def get_trade_monitor() -> TradeMonitor:
    """Get the singleton trade monitor instance"""
    global _trade_monitor_instance
    if _trade_monitor_instance is None:
        _trade_monitor_instance = TradeMonitor()
    return _trade_monitor_instance


async def start_trade_monitor(broker=None):
    """Start the trade monitor with the given broker"""
    monitor = get_trade_monitor()
    if broker:
        monitor.set_broker(broker)
    await monitor.start()
    

async def stop_trade_monitor():
    """Stop the trade monitor"""
    monitor = get_trade_monitor()
    await monitor.stop()
