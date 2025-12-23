"""
Trade Monitor Service
Monitors broker accounts for new trades and posts them as signals to Discord

Optimizations:
- Adaptive polling: 3s during market hours, 30s overnight
- Async HTTP for Discord webhooks to avoid blocking
- Order caching to skip already-processed orders
"""

import sys
sys.stdout.write("[TRADE MONITOR MODULE] Loading trade_monitor.py - v3\n")
sys.stdout.flush()

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
    
    # Weekend check
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    
    # Market hours: 9:30 AM - 4:00 PM ET
    market_open = dt_time(9, 30)
    market_close = dt_time(16, 0)
    current_time = now_et.time()
    
    return market_open <= current_time <= market_close


def is_recent_fill(filled_time_str: str, max_seconds: int = 10) -> bool:
    """Check if the order was filled within the last N seconds (real-time detection)
    
    Args:
        filled_time_str: Fill time string from broker (e.g., '12/23/2025 10:07:38 EST')
        max_seconds: Maximum age in seconds for order to be considered "recent" (default: 10)
    
    Returns:
        True if order was filled within the last max_seconds, False otherwise
    """
    if not filled_time_str:
        return False
    
    try:
        from zoneinfo import ZoneInfo
        et_tz = ZoneInfo('America/New_York')
    except ImportError:
        import pytz
        et_tz = pytz.timezone('America/New_York')
    
    now_et = datetime.now(et_tz)
    
    # Parse various timestamp formats from brokers
    parsed_time = None
    
    # Try common formats
    formats = [
        '%m/%d/%Y %H:%M:%S EST',  # Webull: 12/23/2025 10:07:38 EST
        '%m/%d/%Y %H:%M:%S',      # Without timezone
        '%Y-%m-%d %H:%M:%S',      # ISO format
        '%Y-%m-%dT%H:%M:%S',      # ISO with T
        '%Y-%m-%dT%H:%M:%S.%fZ',  # ISO with milliseconds
    ]
    
    # Remove timezone suffix for parsing if present
    clean_time_str = filled_time_str.replace(' EST', '').replace(' EDT', '').replace(' ET', '')
    
    for fmt in formats:
        try:
            parsed_time = datetime.strptime(clean_time_str, fmt)
            break
        except ValueError:
            continue
    
    if not parsed_time:
        # Try extracting just the time portion for today's date comparison
        sys.stdout.write(f"[TRADE MONITOR] Could not parse fill time: {filled_time_str}\n")
        sys.stdout.flush()
        return False
    
    # Make parsed_time timezone aware (assume ET)
    try:
        parsed_time = parsed_time.replace(tzinfo=et_tz)
    except:
        pass
    
    # Check if fill is on current date
    if parsed_time.date() != now_et.date():
        return False
    
    # Calculate seconds since fill
    try:
        # For naive datetime comparison, strip timezone
        now_naive = now_et.replace(tzinfo=None)
        parsed_naive = parsed_time.replace(tzinfo=None)
        seconds_ago = (now_naive - parsed_naive).total_seconds()
        
        is_recent = 0 <= seconds_ago <= max_seconds
        if not is_recent and seconds_ago > 0:
            # Only log if it's an old order being skipped (not future orders)
            pass  # Reduce log spam
        return is_recent
    except Exception as e:
        sys.stdout.write(f"[TRADE MONITOR] Error calculating time diff: {e}\n")
        sys.stdout.flush()
        return False


def get_adaptive_poll_interval(base_interval: int) -> int:
    """Return faster polling during market hours, slower overnight"""
    if is_market_open():
        # During market hours: minimum 3 seconds for real-time detection
        return max(3, min(base_interval, 5))
    else:
        # After hours: slower polling to save API calls
        return max(base_interval, 30)


class TradeMonitor:
    """Monitors broker for new filled orders and posts to Discord"""
    
    def __init__(self, broker=None):
        self.broker = broker
        self.running = False
        self._task = None
        self._last_poll_time = None
        self._tracked_pending_orders = {}  # order_id -> order data for cancellation detection
        self._http_session = None  # Reusable aiohttp session
    
    async def _get_http_session(self):
        """Get or create reusable aiohttp session for non-blocking HTTP"""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)  # 5 second timeout
            )
        return self._http_session
    
    async def _async_post_webhook(self, webhook_url: str, content: str) -> bool:
        """Non-blocking async POST to Discord webhook"""
        import time
        request_id = f"{int(time.time() * 1000) % 100000}"  # Short unique ID for tracking
        sys.stdout.write(f"[TRADE MONITOR] >>> Webhook POST [{request_id}]: {content[:50]}...\n")
        sys.stdout.flush()
        try:
            session = await self._get_http_session()
            async with session.post(webhook_url, json={"content": content}) as resp:
                success = resp.status in [200, 204]
                sys.stdout.write(f"[TRADE MONITOR] <<< Webhook response [{request_id}]: {resp.status}\n")
                sys.stdout.flush()
                return success
        except Exception as e:
            sys.stdout.write(f"[TRADE MONITOR] !!! Webhook error [{request_id}]: {e}\n")
            sys.stdout.flush()
            return False
        
    def set_broker(self, broker):
        """Set the broker instance to monitor"""
        self.broker = broker
        sys.stdout.write(f"[TRADE MONITOR] Broker set: {type(broker).__name__}\n")
        sys.stdout.write(f"[TRADE MONITOR] has get_order_history: {hasattr(broker, 'get_order_history')}\n")
        sys.stdout.write(f"[TRADE MONITOR] has get_pending_orders: {hasattr(broker, 'get_pending_orders')}\n")
        sys.stdout.write(f"[TRADE MONITOR] Broker methods: {[m for m in dir(broker) if not m.startswith('_') and 'order' in m.lower()]}\n")
        sys.stdout.flush()
        
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
                    
                base_interval = settings.get('poll_interval_seconds', 10)
                poll_interval = get_adaptive_poll_interval(base_interval)
                test_mode_setting = db.get_setting('trade_monitor_test_mode', 'false')
                test_mode = test_mode_setting.lower() == 'true'
                
                market_status = "OPEN" if is_market_open() else "CLOSED"
                sys.stdout.write(f"[TRADE MONITOR] Polling... (market={market_status}, interval={poll_interval}s)\n")
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
            
            # Check for canceled orders FIRST (before early return)
            # This must run even when there are 0 current orders
            if test_mode:
                current_order_ids = {o.get('order_id') for o in orders if o.get('order_id')}
                sys.stdout.write(f"[TRADE MONITOR] Tracked orders: {list(self._tracked_pending_orders.keys())}\n")
                sys.stdout.write(f"[TRADE MONITOR] Current orders: {list(current_order_ids)}\n")
                sys.stdout.flush()
                
                canceled_order_ids = set(self._tracked_pending_orders.keys()) - current_order_ids
                
                if canceled_order_ids:
                    sys.stdout.write(f"[TRADE MONITOR] Canceled order IDs detected: {canceled_order_ids}\n")
                    sys.stdout.flush()
                
                target_channel = settings.get('target_webhook_channel_id')
                for canceled_id in canceled_order_ids:
                    canceled_order = self._tracked_pending_orders.pop(canceled_id, None)
                    if canceled_order:
                        sys.stdout.write(f"[TRADE MONITOR] Posting canceled order: {canceled_id}\n")
                        sys.stdout.flush()
                        await self._post_canceled_order(canceled_order, broker_name, target_channel)
                
                # Update tracked pending orders
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
                
                # LIVE FILL FILTER: Only post orders filled within the last 10 seconds
                # This prevents historical orders from being posted and only captures real-time fills
                filled_time = order.get('filled_time', '')
                if not is_recent_fill(filled_time, max_seconds=10):
                    # Silently skip old orders to reduce log spam
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
            sys.stdout.write(f"[TRADE MONITOR] Error checking orders: {e}\n")
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
            
    def _format_signal(self, order: Dict, signal_type: str, is_canceled: bool = False) -> str:
        """Format order as signal message: BTO ORCL 200C 12/26 @ 2.61 @everyone"""
        symbol = order.get('symbol', 'UNKNOWN')
        quantity = order.get('quantity', 0)
        filled_price = order.get('filled_price', order.get('limit_price', 0))
        asset_type = order.get('asset_type', 'stock')
        order_status = order.get('_status', 'FILLED')
        
        test_prefix = "[TEST] " if order_status == 'PENDING' else ""
        cancel_prefix = "[CANCELED] " if is_canceled else ""
        
        if asset_type == 'option':
            strike = order.get('strike', 0)
            expiry = order.get('expiry', '')
            direction = order.get('direction', 'C').upper()
            
            # Format expiry as MM/DD
            if expiry and '-' in expiry:
                try:
                    from datetime import datetime as dt
                    exp_date = dt.strptime(expiry, '%Y-%m-%d')
                    expiry = exp_date.strftime('%m/%d')
                except:
                    pass
            
            # Format strike without decimal if whole number
            strike_str = f"{int(strike)}" if strike == int(strike) else f"{strike}"
            
            # Format: BTO ORCL 200C 12/26 @ 2.61 @everyone
            signal_msg = f"{cancel_prefix}{test_prefix}{signal_type} {symbol} {strike_str}{direction} {expiry} @ {filled_price:.2f} @everyone"
        else:
            # Stock format: BTO 100 AAPL @ 150.00 @everyone
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
        
        # ALWAYS record to main trades table for PNL/leaderboard (regardless of webhook)
        if is_buy:
            # BTO: Add to main trades table
            self._add_bto_to_trades_table(
                broker_name, symbol, strike, expiry, direction,
                quantity, filled_price, asset_type, order_id
            )
        else:
            # STC: Close matching trade in main trades table with P&L
            pnl_data = self._close_stc_in_trades_table(
                broker_name, symbol, strike, expiry, direction,
                quantity, filled_price, asset_type
            )
        
        # Post to Discord webhook if configured
        if webhook_url:
            if asset_type == 'option':
                if is_buy:
                    # BTO: Open position for webhook P&L tracking and post signal (async)
                    signal_msg = self._format_signal(order, signal_type)
                    posted = await self._async_post_webhook(webhook_url, signal_msg)
                    if posted:
                        channel_id = target_channel
                        print(f"[TRADE MONITOR] Posted BTO {symbol} to webhook", flush=True)
                        
                        # Track position for webhook P&L calculation on STC
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
                        if position_id:
                            print(f"[TRADE MONITOR] Opened webhook position {position_id}", flush=True)
                else:
                    # STC: Use post_stc_signal for rich Trade Summary embed
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
                            print(f"[TRADE MONITOR] Posted STC {symbol} with Trade Summary", flush=True)
                        else:
                            # No webhook position - post simple STC signal (async)
                            signal_msg = self._format_signal(order, signal_type)
                            posted = await self._async_post_webhook(webhook_url, signal_msg)
                            if posted:
                                channel_id = target_channel
                                print(f"[TRADE MONITOR] Posted STC {symbol} (simple)", flush=True)
                    except Exception as e:
                        print(f"[TRADE MONITOR] Failed to post STC to webhook: {e}", flush=True)
            else:
                # Stocks - use simple format (async)
                signal_msg = self._format_signal(order, signal_type)
                posted = await self._async_post_webhook(webhook_url, signal_msg)
                if posted:
                    channel_id = target_channel
                    print(f"[TRADE MONITOR] Posted {signal_type} {symbol} to webhook", flush=True)
        
        # Record to synced_orders table
        db.add_synced_order(
            broker=broker_name,
            order_id=str(order_id) if order_id else '',
            symbol=symbol,
            action=signal_type,
            quantity=quantity,
            filled_price=filled_price,
            asset_type=asset_type,
            strike=strike or 0,
            expiry=expiry or '',
            direction=direction or '',
            discord_channel_id=str(channel_id) if channel_id else ''
        )
        
        if posted:
            print(f"[TRADE MONITOR] ✓ Synced {signal_type} {symbol} from {broker_name}", flush=True)
        else:
            print(f"[TRADE MONITOR] ✓ Recorded {signal_type} {symbol} (no webhook)", flush=True)
    
    def _add_bto_to_trades_table(self, broker_name: str, symbol: str, strike: Optional[float], 
                                  expiry: Optional[str], call_put: Optional[str], quantity: int, 
                                  filled_price: float, asset_type: str, 
                                  order_id: Optional[str]) -> Optional[int]:
        """Add a BTO order to the main trades table for PNL/leaderboard tracking"""
        try:
            from datetime import datetime
            trade_data = {
                'direction': 'BTO',
                'asset_type': asset_type,
                'symbol': symbol.upper(),
                'strike': strike,
                'expiry': expiry,
                'call_put': call_put[0].upper() if call_put else None,
                'quantity': quantity,
                'intended_price': filled_price,
                'executed_price': filled_price,
                'executed': True,
                'status': 'OPEN',
                'broker': broker_name,
                'order_id': str(order_id) if order_id else None,
                'channel_id': None,
                'source': 'TRADE_MONITOR'
            }
            trade_id = db.add_trade(trade_data)
            print(f"[TRADE MONITOR] ✓ Added BTO to trades table (ID: {trade_id})", flush=True)
            return trade_id
        except Exception as e:
            print(f"[TRADE MONITOR] Error adding BTO to trades table: {e}", flush=True)
            return None
    
    def _close_stc_in_trades_table(self, broker_name: str, symbol: str, strike: Optional[float],
                                    expiry: Optional[str], call_put: Optional[str], quantity: int,
                                    close_price: float, asset_type: str) -> Optional[Dict]:
        """Close a matching open trade in main trades table with P&L"""
        try:
            # Find matching open BTO trade
            open_trade = db.find_open_trade_for_stc(
                broker_name=broker_name,
                symbol=symbol,
                strike=strike,
                expiry=expiry,
                call_put=call_put,
                asset_type=asset_type
            )
            
            if open_trade:
                trade_id = open_trade['id']
                entry_price = open_trade.get('executed_price', 0)
                trade_qty = open_trade.get('quantity', quantity)
                
                # Calculate P&L - use 100x multiplier for options, 1x for stocks
                multiplier = 100 if asset_type == 'option' else 1
                pnl = (close_price - entry_price) * trade_qty * multiplier
                pnl_percent = ((close_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                
                # Close the trade
                db.close_trade(trade_id, close_price, pnl, pnl_percent)
                print(f"[TRADE MONITOR] ✓ Closed trade {trade_id} - P&L: ${pnl:.2f} ({pnl_percent:.1f}%)", flush=True)
                return {'profit': pnl, 'gain_pct': pnl_percent, 'entry_price': entry_price}
            else:
                print(f"[TRADE MONITOR] No matching open trade for STC {symbol}", flush=True)
                return None
        except Exception as e:
            print(f"[TRADE MONITOR] Error closing trade: {e}", flush=True)
            return None
    
    async def _post_canceled_order(self, order: Dict, broker_name: str, target_channel: str = None):
        """Post a canceled order notification to Discord"""
        symbol = order.get('symbol', 'UNKNOWN')
        action = order.get('action', '').upper()
        asset_type = order.get('asset_type', 'stock')
        quantity = order.get('quantity', 0)
        strike = order.get('strike', 0)
        expiry = order.get('expiry', '')
        direction = order.get('direction', 'C')
        
        is_buy = action in ['BUY', 'BTO']
        signal_type = 'BTO' if is_buy else 'STC'
        
        signal_msg = self._format_signal(order, signal_type, is_canceled=True)
        
        sys.stdout.write(f"[TRADE MONITOR] Posting canceled order: {signal_msg}\n")
        sys.stdout.flush()
        
        # If a BTO option order is canceled, remove from tracked positions
        if is_buy and asset_type == 'option':
            try:
                removed = webhook_service.cancel_webhook_position(
                    symbol=symbol,
                    strike=strike,
                    expiry=expiry,
                    call_put=direction,
                    qty=quantity
                )
                if removed:
                    print(f"[TRADE MONITOR] ✓ Removed canceled BTO from position tracking: {symbol} {strike}{direction}", flush=True)
            except Exception as e:
                print(f"[TRADE MONITOR] Error removing canceled position: {e}", flush=True)
        
        if target_channel:
            webhook_url = self._get_webhook_url(target_channel)
            if webhook_url:
                posted = await self._async_post_webhook(webhook_url, signal_msg)
                if posted:
                    print(f"[TRADE MONITOR] ✓ Posted CANCELED {symbol} to webhook", flush=True)
                else:
                    print(f"[TRADE MONITOR] Failed to post canceled order", flush=True)
            else:
                print(f"[TRADE MONITOR] No webhook configured for canceled order", flush=True)
            
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
