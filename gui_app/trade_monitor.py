"""
Trade Monitor Service
Monitors broker accounts for new trades and posts them as signals to Discord
"""

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
        if self.running:
            print("[TRADE MONITOR] Already running")
            return
            
        settings = db.get_trade_monitor_settings()
        if not settings.get('enabled'):
            print("[TRADE MONITOR] Disabled in settings, not starting")
            return
            
        if not self.broker:
            print("[TRADE MONITOR] No broker connected, cannot start")
            return
            
        self.running = True
        print("[TRADE MONITOR] Starting trade monitor...")
        self._task = asyncio.create_task(self._poll_loop())
        
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
        while self.running:
            try:
                settings = db.get_trade_monitor_settings()
                if not settings.get('enabled'):
                    print("[TRADE MONITOR] Disabled, stopping...")
                    self.running = False
                    break
                    
                poll_interval = settings.get('poll_interval_seconds', 10)
                
                await self._check_for_new_orders(settings)
                
                self._last_poll_time = datetime.now()
                await asyncio.sleep(poll_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TRADE MONITOR] Error in poll loop: {e}")
                await asyncio.sleep(10)
                
    async def _check_for_new_orders(self, settings: Dict[str, Any]):
        """Check broker for new filled orders"""
        if not self.broker or not self.broker.connected:
            return
            
        broker_name = getattr(self.broker, 'name', 'UNKNOWN')
        
        try:
            if hasattr(self.broker, 'get_order_history'):
                orders = await self.broker.get_order_history(count=20)
            else:
                return
                
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
                if not order_id:
                    continue
                    
                if db.is_order_synced(broker_name, order_id):
                    continue
                    
                asset_type = order.get('asset_type', 'stock')
                if asset_type == 'stock' and not include_stocks:
                    continue
                if asset_type == 'option' and not include_options:
                    continue
                    
                action = order.get('action', '').upper()
                is_buy = action in ['BUY', 'BTO']
                is_sell = action in ['SELL', 'STC']
                
                if is_buy and not post_bto:
                    continue
                if is_sell and not post_stc:
                    continue
                    
                new_orders.append(order)
                
            for order in new_orders:
                await self._post_order_to_discord(order, broker_name, target_channel)
                
        except Exception as e:
            print(f"[TRADE MONITOR] Error checking orders: {e}")
            
    async def _post_order_to_discord(self, order: Dict, broker_name: str, target_channel: str = None):
        """Post a filled order as a signal to Discord"""
        order_id = order.get('order_id')
        symbol = order.get('symbol', 'UNKNOWN')
        action = order.get('action', '').upper()
        quantity = order.get('quantity', 0)
        filled_price = order.get('filled_price', 0)
        asset_type = order.get('asset_type', 'stock')
        
        is_buy = action in ['BUY', 'BTO']
        signal_type = 'BTO' if is_buy else 'STC'
        
        if asset_type == 'option':
            strike = order.get('strike', 0)
            expiry = order.get('expiry', '')
            direction = order.get('direction', 'C')
            
            if expiry and '-' in expiry:
                try:
                    from datetime import datetime as dt
                    exp_date = dt.strptime(expiry, '%Y-%m-%d')
                    expiry = exp_date.strftime('%m/%d')
                except:
                    pass
            
            signal_msg = f"**{signal_type} {symbol} ${strike}{direction} {expiry}**"
            if filled_price > 0:
                signal_msg += f" @ ${filled_price:.2f}"
            if quantity > 1:
                signal_msg += f" x{quantity}"
        else:
            signal_msg = f"**{signal_type} {symbol}**"
            if filled_price > 0:
                signal_msg += f" @ ${filled_price:.2f}"
            if quantity > 1:
                signal_msg += f" x{quantity}"
        
        emoji = "🟢" if is_buy else "🔴"
        signal_msg = f"{emoji} {signal_msg}"
        signal_msg += f"\n📊 *Synced from {broker_name}*"
        
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
                        print(f"[TRADE MONITOR] Posted {signal_type} {symbol} to webhook")
                except Exception as e:
                    print(f"[TRADE MONITOR] Failed to post to webhook: {e}")
        
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
            print(f"[TRADE MONITOR] ✓ Synced {signal_type} {symbol} from {broker_name}")
        else:
            print(f"[TRADE MONITOR] Recorded {signal_type} {symbol} (no webhook configured)")
            
    def _get_webhook_url(self, channel_id: str) -> Optional[str]:
        """Get webhook URL for a channel from webhook_channels table"""
        try:
            from gui_app import database as db
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT webhook_url FROM webhook_channels 
                WHERE id = ? OR discord_channel_id = ?
            ''', (channel_id, channel_id))
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            print(f"[TRADE MONITOR] Error getting webhook: {e}")
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
