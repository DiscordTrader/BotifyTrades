"""
Trade Monitor Service v4 - Quiet Mode
Monitors broker accounts for new trades and posts them as signals to Discord

Features:
- Adaptive polling: 5s during market hours, 30s overnight
- Async HTTP for Discord webhooks to avoid blocking
- Order caching to skip already-processed orders
- Duplicate order prevention via database tracking
- Quiet logging: only important events are logged
"""

import sys
import asyncio
import requests
import aiohttp
from datetime import datetime, time as dt_time
from typing import Optional, Dict, Any, List

try:
    from gui_app import database as db
    from gui_app import webhook_service
except ImportError:
    import database as db
    import webhook_service


def is_market_open() -> bool:
    """Check if US stock market is currently open (9:30 AM - 4:00 PM ET)"""
    try:
        from zoneinfo import ZoneInfo
        et_tz = ZoneInfo('America/New_York')
    except ImportError:
        import pytz
        et_tz = pytz.timezone('America/New_York')
    
    now_et = datetime.now(et_tz)
    
    if now_et.weekday() >= 5:
        return False
    
    market_open = dt_time(9, 30)
    market_close = dt_time(16, 0)
    current_time = now_et.time()
    
    return market_open <= current_time <= market_close


def is_recent_fill(filled_time_str: str, max_seconds: int = 120) -> bool:
    """Check if the order was filled within the last N seconds (real-time detection)
    
    Properly handles timezone-aware timestamps including:
    - UTC timestamps ending with 'Z' (ISO8601)
    - EST/EDT/ET suffixed timestamps
    - Naive timestamps (assumed to be ET)
    
    Default window increased to 120 seconds to avoid missing fills between polls.
    """
    if not filled_time_str:
        return False
    
    try:
        from zoneinfo import ZoneInfo
        et_tz = ZoneInfo('America/New_York')
        utc_tz = ZoneInfo('UTC')
    except ImportError:
        import pytz
        et_tz = pytz.timezone('America/New_York')
        utc_tz = pytz.UTC
    
    now_et = datetime.now(et_tz)
    
    parsed_time = None
    is_utc = False
    
    # Check if this is a UTC timestamp (ends with Z)
    if filled_time_str.endswith('Z'):
        is_utc = True
        clean_time_str = filled_time_str[:-1]  # Remove trailing Z
    else:
        # Check for ET timezone suffixes
        clean_time_str = filled_time_str.replace(' EST', '').replace(' EDT', '').replace(' ET', '')
    
    # Formats to try (without timezone suffix)
    formats = [
        '%Y-%m-%dT%H:%M:%S.%f',  # ISO8601 with microseconds
        '%Y-%m-%dT%H:%M:%S',     # ISO8601 without microseconds
        '%Y-%m-%d %H:%M:%S',     # Standard datetime
        '%m/%d/%Y %H:%M:%S',     # US format
    ]
    
    for fmt in formats:
        try:
            parsed_time = datetime.strptime(clean_time_str, fmt)
            break
        except ValueError:
            continue
    
    if not parsed_time:
        # Log unparseable timestamp for debugging
        print(f"[TRADE MONITOR] Could not parse timestamp: {filled_time_str}", flush=True)
        return False
    
    # Apply correct timezone
    try:
        if is_utc:
            # Timestamp was UTC - attach UTC timezone then convert to ET
            parsed_time = parsed_time.replace(tzinfo=utc_tz)
            parsed_time_et = parsed_time.astimezone(et_tz)
        else:
            # Timestamp was ET or naive (assume ET)
            parsed_time_et = parsed_time.replace(tzinfo=et_tz)
    except Exception as e:
        print(f"[TRADE MONITOR] Timezone conversion error: {e}", flush=True)
        return False
    
    # Check if same day
    if parsed_time_et.date() != now_et.date():
        return False
    
    # Calculate seconds difference
    try:
        seconds_ago = (now_et - parsed_time_et).total_seconds()
        # Allow small negative values (-5s) for clock skew
        return -5 <= seconds_ago <= max_seconds
    except Exception as e:
        print(f"[TRADE MONITOR] Time comparison error: {e}", flush=True)
        return False


def get_adaptive_poll_interval(base_interval: int) -> int:
    """Return faster polling during market hours, slower overnight"""
    if is_market_open():
        return max(3, min(base_interval, 5))
    else:
        return max(base_interval, 30)


_trade_monitor_instance = None

def get_trade_monitor() -> 'TradeMonitor':
    """Get or create the singleton trade monitor instance"""
    global _trade_monitor_instance
    if _trade_monitor_instance is None:
        _trade_monitor_instance = TradeMonitor()
    return _trade_monitor_instance


class TradeMonitor:
    """Monitors broker for new filled orders and posts to Discord"""
    
    def __init__(self, broker=None):
        self.broker = broker
        self.running = False
        self._task = None
        self._last_poll_time = None
        self._tracked_pending_orders = {}
        self._http_session = None
        self._poll_count = 0
        self._last_status_log = None
    
    async def _get_http_session(self):
        """Get or create reusable aiohttp session for non-blocking HTTP"""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            )
        return self._http_session
    
    async def _async_post_webhook(self, webhook_url: str, content: str) -> bool:
        """Non-blocking async POST to Discord webhook"""
        try:
            session = await self._get_http_session()
            async with session.post(webhook_url, json={"content": content}) as resp:
                return resp.status in [200, 204]
        except Exception as e:
            print(f"[TRADE MONITOR] Webhook error: {e}", flush=True)
            return False
    
    async def _async_post_webhook_with_name(self, webhook_url: str, content: str, bot_name: str = 'BotifyTrades') -> bool:
        """Non-blocking async POST to Discord webhook with custom bot name"""
        try:
            session = await self._get_http_session()
            payload = {
                "content": content,
                "username": bot_name
            }
            async with session.post(webhook_url, json=payload) as resp:
                return resp.status in [200, 204]
        except Exception as e:
            print(f"[TRADE MONITOR] Webhook error: {e}", flush=True)
            return False
        
    def set_broker(self, broker):
        """Set the broker instance to monitor"""
        self.broker = broker
        broker_name = getattr(broker, 'name', type(broker).__name__)
        print(f"[TRADE MONITOR] Broker connected: {broker_name}", flush=True)
        
    async def start(self):
        """Start the trade monitor loop"""
        if self.running:
            return
            
        settings = db.get_trade_monitor_settings()
        if not settings.get('enabled'):
            print("[TRADE MONITOR] Disabled in settings", flush=True)
            return
            
        if not self.broker:
            print("[TRADE MONITOR] No broker connected", flush=True)
            return
        
        broker_name = getattr(self.broker, 'name', type(self.broker).__name__)
        self.running = True
        self._task = asyncio.create_task(self._poll_loop())
        print(f"[TRADE MONITOR] ✓ Started - monitoring {broker_name}", flush=True)
        
    async def stop(self):
        """Stop the trade monitor"""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[TRADE MONITOR] Stopped", flush=True)
        
    async def _poll_loop(self):
        """Main polling loop - quiet mode"""
        print("[TRADE MONITOR] Poll loop started", flush=True)
        while self.running:
            try:
                settings = db.get_trade_monitor_settings()
                if not settings.get('enabled'):
                    print("[TRADE MONITOR] Disabled, stopping...", flush=True)
                    self.running = False
                    break
                    
                base_interval = settings.get('poll_interval_seconds', 10)
                poll_interval = get_adaptive_poll_interval(base_interval)
                
                self._poll_count += 1
                
                now = datetime.now()
                # Log status every 5 minutes (300 seconds)
                if self._last_status_log is None or (now - self._last_status_log).seconds >= 300:
                    market_status = "OPEN" if is_market_open() else "CLOSED"
                    print(f"[TRADE MONITOR] Active (market={market_status}, poll={poll_interval}s, count={self._poll_count})", flush=True)
                    self._last_status_log = now
                
                await self._check_for_new_orders(settings)
                
                self._last_poll_time = now
                await asyncio.sleep(poll_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TRADE MONITOR] Error: {e}", flush=True)
                await asyncio.sleep(10)
                
    async def _check_for_new_orders(self, settings: Dict[str, Any]):
        """Check broker for new filled orders - quiet mode"""
        if not self.broker:
            return
            
        broker_name = getattr(self.broker, 'name', 'UNKNOWN')
        test_mode_setting = db.get_setting('trade_monitor_test_mode', 'false')
        test_mode = test_mode_setting.lower() == 'true'
        
        try:
            orders = []
            
            if hasattr(self.broker, 'get_order_history'):
                filled_orders = await self.broker.get_order_history(count=20)
                if filled_orders:
                    for order in filled_orders:
                        order['_status'] = 'FILLED'
                    orders.extend(filled_orders)
            
            if test_mode and hasattr(self.broker, 'get_pending_orders'):
                pending_orders = await self.broker.get_pending_orders()
                if pending_orders:
                    for order in pending_orders:
                        order['_status'] = 'PENDING'
                    orders.extend(pending_orders)
            
            if test_mode:
                current_order_ids = {o.get('order_id') for o in orders if o.get('order_id')}
                canceled_order_ids = set(self._tracked_pending_orders.keys()) - current_order_ids
                
                target_channel = settings.get('target_webhook_channel_id')
                for canceled_id in canceled_order_ids:
                    canceled_order = self._tracked_pending_orders.pop(canceled_id, None)
                    if canceled_order:
                        print(f"[TRADE MONITOR] Order canceled: {canceled_id}", flush=True)
                        await self._post_canceled_order(canceled_order, broker_name, target_channel)
                
                for order in orders:
                    order_id = order.get('order_id')
                    if order_id and order.get('_status') == 'PENDING':
                        self._tracked_pending_orders[order_id] = order
                
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
                
                filled_time = order.get('filled_time', '')
                if not is_recent_fill(filled_time, max_seconds=10):
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
            
            if new_orders:
                print(f"[TRADE MONITOR] Found {len(new_orders)} new order(s) to post", flush=True)
            
            for order in new_orders:
                if target_channel:
                    await self._post_order_to_discord(order, broker_name, target_channel)
                else:
                    print(f"[TRADE MONITOR] ⚠️  No target webhook channel configured in Trade Monitor settings", flush=True)
                
        except Exception as e:
            print(f"[TRADE MONITOR] Error checking orders: {e}", flush=True)
            
    def _format_signal(self, order: Dict, signal_type: str, is_canceled: bool = False) -> str:
        """Format order as signal message: BTO 3 ORCL 200C 12/26 @ 2.61 @everyone"""
        symbol = order.get('symbol', 'UNKNOWN')
        quantity = order.get('quantity', 0)
        filled_price = order.get('filled_price', order.get('limit_price', 0))
        asset_type = order.get('asset_type', 'stock')
        order_status = order.get('_status', 'FILLED')
        
        test_prefix = "[TEST] " if order_status == 'PENDING' else ""
        cancel_prefix = "[CANCELED] " if is_canceled else ""
        
        strike = order.get('strike', 0)
        
        if asset_type == 'option' and strike and strike > 0:
            expiry = order.get('expiry', '')
            direction = order.get('direction', 'C').upper()
            
            if expiry and '-' in expiry:
                try:
                    from datetime import datetime as dt
                    exp_date = dt.strptime(expiry, '%Y-%m-%d')
                    expiry = exp_date.strftime('%m/%d')
                except:
                    pass
            
            strike_str = f"{int(strike)}" if strike == int(strike) else f"{strike}"
            signal_msg = f"{cancel_prefix}{test_prefix}{signal_type} {quantity} {symbol} {strike_str}{direction} {expiry} @ {filled_price:.2f} @everyone"
        else:
            signal_msg = f"{cancel_prefix}{test_prefix}{signal_type} {quantity} {symbol} @ {filled_price:.2f} @everyone"
        
        return signal_msg
    
    async def _post_order_to_discord(self, order: Dict, broker_name: str, target_channel: str = None):
        """Post a filled order as a signal to Discord and record to trades table"""
        order_id = order.get('order_id')
        symbol = order.get('symbol', 'UNKNOWN')
        action = order.get('action', '').upper()
        quantity = order.get('quantity', 0)
        filled_price = order.get('filled_price', order.get('limit_price', 0))
        asset_type = order.get('asset_type', 'stock')
        strike = order.get('strike', 0) if asset_type == 'option' else None
        expiry = order.get('expiry', '') if asset_type == 'option' else None
        direction = order.get('direction', 'C') if asset_type == 'option' else None
        
        is_buy = action in ['BUY', 'BTO']
        signal_type = 'BTO' if is_buy else 'STC'
        
        posted = False
        channel_id = None
        webhook_url = self._get_webhook_url(target_channel) if target_channel else None
        pnl_data = None
        
        if is_buy:
            self._add_bto_to_trades_table(
                broker_name, symbol, strike, expiry, direction,
                quantity, filled_price, asset_type, order_id
            )
            print(f"[TRADE MONITOR] BTO recorded: {quantity} {symbol} @ ${filled_price:.2f}", flush=True)
        else:
            pnl_data = self._close_stc_in_trades_table(
                broker_name, symbol, strike, expiry, direction,
                quantity, filled_price, asset_type
            )
            if pnl_data:
                print(f"[TRADE MONITOR] STC recorded: {quantity} {symbol} @ ${filled_price:.2f} (P&L: ${pnl_data.get('pnl', 0):.2f})", flush=True)
            else:
                print(f"[TRADE MONITOR] STC recorded: {quantity} {symbol} @ ${filled_price:.2f}", flush=True)
        
        if webhook_url:
            if asset_type == 'option':
                if is_buy:
                    signal_msg = self._format_signal(order, signal_type)
                    posted = await self._async_post_webhook(webhook_url, signal_msg)
                    if posted:
                        channel_id = target_channel
                        print(f"[TRADE MONITOR] Posted to Discord: {signal_msg[:50]}...", flush=True)
                        
                        position_id = webhook_service.open_webhook_position(
                            symbol=symbol,
                            strike=strike,
                            expiry=expiry,
                            call_put=direction,
                            qty=quantity,
                            entry_price=filled_price,
                            trade_type='BTO',
                            webhook_url=webhook_url
                        )
                else:
                    try:
                        success, message, _ = webhook_service.post_stc_signal(
                            webhook_url=webhook_url,
                            symbol=symbol,
                            strike=strike,
                            expiry=expiry,
                            call_put=direction,
                            qty=quantity,
                            close_price=filled_price
                        )
                        if success:
                            posted = True
                            channel_id = target_channel
                            print(f"[TRADE MONITOR] Posted STC to Discord: {symbol}", flush=True)
                        else:
                            signal_msg = self._format_signal(order, signal_type)
                            posted = await self._async_post_webhook(webhook_url, signal_msg)
                            if posted:
                                channel_id = target_channel
                    except Exception as e:
                        signal_msg = self._format_signal(order, signal_type)
                        posted = await self._async_post_webhook(webhook_url, signal_msg)
                        if posted:
                            channel_id = target_channel
            else:
                signal_msg = self._format_signal(order, signal_type)
                posted = await self._async_post_webhook(webhook_url, signal_msg)
                if posted:
                    channel_id = target_channel
        
        db.add_synced_order(
            broker=broker_name,
            order_id=order_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            filled_price=filled_price,
            asset_type=asset_type,
            strike=strike,
            expiry=expiry,
            direction=direction,
            discord_channel_id=channel_id
        )
    
    async def _post_order_to_all_webhooks(self, order: Dict, broker_name: str, webhooks: List[Dict[str, str]]):
        """Post a filled order to all configured webhook destinations with position tracking"""
        order_id = order.get('order_id')
        symbol = order.get('symbol', 'UNKNOWN')
        action = order.get('action', '').upper()
        quantity = order.get('quantity', 0)
        filled_price = order.get('filled_price', order.get('limit_price', 0))
        asset_type = order.get('asset_type', 'stock')
        strike = order.get('strike', 0) if asset_type == 'option' else None
        expiry = order.get('expiry', '') if asset_type == 'option' else None
        direction = order.get('direction', 'C') if asset_type == 'option' else None
        
        is_buy = action in ['BUY', 'BTO']
        signal_type = 'BTO' if is_buy else 'STC'
        
        if is_buy:
            self._add_bto_to_trades_table(
                broker_name, symbol, strike, expiry, direction,
                quantity, filled_price, asset_type, order_id
            )
            print(f"[TRADE MONITOR] BTO recorded: {quantity} {symbol} @ ${filled_price:.2f}", flush=True)
        else:
            pnl_data = self._close_stc_in_trades_table(
                broker_name, symbol, strike, expiry, direction,
                quantity, filled_price, asset_type
            )
            if pnl_data:
                print(f"[TRADE MONITOR] STC recorded: {quantity} {symbol} @ ${filled_price:.2f} (P&L: ${pnl_data.get('pnl', 0):.2f})", flush=True)
            else:
                print(f"[TRADE MONITOR] STC recorded: {quantity} {symbol} @ ${filled_price:.2f}", flush=True)
        
        posted_count = 0
        for wh in webhooks:
            webhook_url = wh.get('webhook_url')
            webhook_name = wh.get('webhook_name', 'Unnamed')
            bot_name = wh.get('bot_name', webhook_name) or 'BotifyTrades'
            if not webhook_url:
                continue
                
            if asset_type == 'option':
                if is_buy:
                    signal_msg = self._format_signal(order, signal_type)
                    success = await self._async_post_webhook_with_name(webhook_url, signal_msg, bot_name)
                    if success:
                        posted_count += 1
                        webhook_service.open_webhook_position(
                            symbol=symbol,
                            strike=strike or 0,
                            expiry=expiry or '',
                            call_put=direction or 'C',
                            qty=quantity,
                            entry_price=filled_price,
                            trade_type='BTO',
                            webhook_url=webhook_url
                        )
                else:
                    try:
                        success, message, _ = webhook_service.post_stc_signal(
                            webhook_url=webhook_url,
                            symbol=symbol,
                            strike=strike or 0,
                            expiry=expiry or '',
                            call_put=direction or 'C',
                            qty=quantity,
                            close_price=filled_price,
                            bot_name=bot_name
                        )
                        if success:
                            posted_count += 1
                    except Exception:
                        signal_msg = self._format_signal(order, signal_type)
                        success = await self._async_post_webhook_with_name(webhook_url, signal_msg, bot_name)
                        if success:
                            posted_count += 1
            else:
                signal_msg = self._format_signal(order, signal_type)
                success = await self._async_post_webhook_with_name(webhook_url, signal_msg, bot_name)
                if success:
                    posted_count += 1
        
        if posted_count > 0:
            print(f"[TRADE MONITOR] ✓ Posted {signal_type} {symbol} to {posted_count} webhook(s)", flush=True)
        
        db.add_synced_order(
            broker=broker_name,
            order_id=order_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            filled_price=filled_price,
            asset_type=asset_type,
            strike=strike,
            expiry=expiry,
            direction=direction,
            discord_channel_id=None
        )

    async def _post_canceled_order(self, order: Dict, broker_name: str, target_channel: str = None):
        """Post notification when a pending order is canceled"""
        order_id = order.get('order_id')
        action = order.get('action', '').upper()
        is_buy = action in ['BUY', 'BTO']
        signal_type = 'BTO' if is_buy else 'STC'
        
        webhook_url = self._get_webhook_url(target_channel) if target_channel else None
        
        if webhook_url:
            signal_msg = self._format_signal(order, signal_type, is_canceled=True)
            await self._async_post_webhook(webhook_url, signal_msg)
            print(f"[TRADE MONITOR] Posted canceled: {order_id}", flush=True)
    
    def _get_webhook_url(self, channel_id: str) -> Optional[str]:
        """Get webhook URL for a channel"""
        if not channel_id:
            return None
        
        try:
            channel_id_int = int(channel_id)
        except (ValueError, TypeError):
            return None
            
        channel = db.get_channel_by_id(channel_id_int)
        if not channel:
            return None
            
        return channel.get('webhook_url')
    
    def _add_bto_to_trades_table(self, broker_name: str, symbol: str, strike: float,
                                  expiry: str, direction: str, quantity: int,
                                  entry_price: float, asset_type: str, order_id: str):
        """Add BTO entry to main trades table for P&L tracking"""
        try:
            signal_data = {
                'symbol': symbol,
                'strike': strike,
                'expiry': expiry,
                'call_put': direction,
                'quantity': quantity,
                'intended_price': entry_price,
                'executed_price': entry_price,
                'direction': 'BTO',
                'asset_type': asset_type,
                'broker': broker_name,
                'channel_id': None,
                'message_id': None,
                'status': 'executed',
                'order_id': order_id,
                'source': 'trade_monitor'
            }
            db.add_trade(signal_data)
        except Exception as e:
            print(f"[TRADE MONITOR] Error adding BTO to trades: {e}", flush=True)
    
    def _close_stc_in_trades_table(self, broker_name: str, symbol: str, strike: float,
                                    expiry: str, direction: str, quantity: int,
                                    close_price: float, asset_type: str) -> Optional[Dict]:
        """Close matching trade in main trades table with P&L calculation"""
        try:
            trade = db.find_open_trade_for_stc(
                broker_name=broker_name,
                symbol=symbol,
                strike=strike,
                expiry=expiry,
                call_put=direction,
                asset_type=asset_type
            )
            
            if not trade:
                return None
            
            trade_id = trade.get('id')
            entry_price = trade.get('entry_price', 0)
            trade_qty = trade.get('qty', quantity)
            
            if asset_type == 'option':
                pnl = (close_price - entry_price) * trade_qty * 100
            else:
                pnl = (close_price - entry_price) * trade_qty
            
            pnl_percent = ((close_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
            
            db.close_trade(trade_id, close_price, pnl, pnl_percent)
            
            return {
                'trade_id': trade_id,
                'entry_price': entry_price,
                'close_price': close_price,
                'pnl': pnl,
                'pnl_percent': pnl_percent
            }
            
        except Exception as e:
            print(f"[TRADE MONITOR] Error closing trade: {e}", flush=True)
            return None
