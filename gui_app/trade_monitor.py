"""
Trade Monitor Service v4 - Quiet Mode
Monitors broker accounts for new trades and posts them as signals to Discord

Features:
- Adaptive polling: 5s during market hours, 30s overnight
- Async HTTP for Discord webhooks to avoid blocking
- Order caching to skip already-processed orders
- Duplicate order prevention via database tracking
- Quiet logging: only important events are logged
- Rate limit enforcement via centralized RateLimitManager
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

try:
    from src.services.rate_limit_manager import get_rate_limit_manager
    RATE_LIMIT_AVAILABLE = True
except ImportError:
    RATE_LIMIT_AVAILABLE = False
    get_rate_limit_manager = None


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
    
    parsed_time_et = None

    # Try fromisoformat first — handles Z, +00:00, +0000, and offset-aware timestamps natively
    try:
        raw = filled_time_str.replace('Z', '+00:00')
        # fromisoformat in 3.11+ handles +0000 but not all edge cases — normalize
        import re
        raw = re.sub(r'([+-]\d{2})(\d{2})$', r'\1:\2', raw)
        dt_parsed = datetime.fromisoformat(raw)
        if dt_parsed.tzinfo is not None:
            parsed_time_et = dt_parsed.astimezone(et_tz)
        else:
            parsed_time_et = dt_parsed.replace(tzinfo=et_tz)
    except (ValueError, TypeError):
        pass

    # Fallback: strip timezone suffixes and try strptime formats
    if not parsed_time_et:
        clean_time_str = filled_time_str.replace(' EST', '').replace(' EDT', '').replace(' ET', '')
        formats = [
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
            '%m/%d/%Y %H:%M:%S',
        ]
        for fmt in formats:
            try:
                parsed_time = datetime.strptime(clean_time_str, fmt)
                parsed_time_et = parsed_time.replace(tzinfo=et_tz)
                break
            except ValueError:
                continue

    if not parsed_time_et:
        print(f"[TRADE MONITOR] Could not parse timestamp: {filled_time_str}", flush=True)
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
    """
    Monitors broker for new filled orders and posts to Discord.
    
    Enhanced with:
    - Thread-safe cancellation via asyncio.Event
    - Re-checks enable state each cycle
    - Standby mode when disabled (zero API calls)
    """
    
    def __init__(self, broker=None):
        self.broker = broker
        self._broker_manager = None
        self.running = False
        self._task = None
        self._last_poll_time = None
        self._tracked_pending_orders = {}
        self._http_session = None
        self._poll_count = 0
        self._last_status_log = None
        self._seeded = False
        self._stop_event = asyncio.Event()
        self._standby_mode = False
    
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
        """Set the broker instance to monitor (legacy single-broker)"""
        self.broker = broker
        broker_name = getattr(broker, 'name', type(broker).__name__)
        print(f"[TRADE MONITOR] Broker connected: {broker_name}", flush=True)

    def set_broker_manager(self, broker_manager):
        """Set broker manager for multi-broker monitoring"""
        self._broker_manager = broker_manager
        print(f"[TRADE MONITOR] ✓ Broker manager connected — multi-broker monitoring enabled", flush=True)

    def _get_brokers_to_monitor(self) -> list:
        """Get all connected US brokers as (name, instance) pairs"""
        brokers = []
        bm = self._broker_manager

        if not bm:
            if self.broker:
                name = getattr(self.broker, 'name', 'WEBULL')
                brokers.append((name, self.broker))
            return brokers

        if getattr(bm, 'webull_broker', None):
            brokers.append(('Webull', bm.webull_broker))

        schwab = getattr(bm, 'schwab_broker', None)
        if schwab:
            try:
                if schwab.is_authenticated() or getattr(schwab, 'connected', False):
                    brokers.append(('SCHWAB', schwab))
            except Exception:
                pass

        ibkr = getattr(bm, 'ibkr_broker', None)
        if ibkr and getattr(ibkr, 'connected', False):
            label = 'IBKR_LIVE' if not getattr(ibkr, 'paper_trade', True) else 'IBKR_PAPER'
            brokers.append((label, ibkr))

        tt = getattr(bm, 'tastytrade_broker', None)
        if tt and getattr(tt, 'session', None):
            label = 'TASTYTRADE_LIVE' if getattr(tt, 'is_live', False) else 'TASTYTRADE_PAPER'
            brokers.append((label, tt))

        alpaca = getattr(bm, 'alpaca_paper_broker', None)
        if alpaca:
            brokers.append(('ALPACA_PAPER', alpaca))

        wo = getattr(bm, 'webull_official_broker', None)
        if wo and getattr(wo, 'connected', False):
            label = 'WEBULL_OFFICIAL_LIVE' if not getattr(wo, 'paper_trade', True) else 'WEBULL_OFFICIAL_PAPER'
            brokers.append((label, wo))

        rh = getattr(bm, 'robinhood_broker', None)
        if rh and getattr(rh, 'connected', False):
            brokers.append(('ROBINHOOD', rh))

        return brokers

    async def _fetch_filled_orders(self, broker_name: str, broker_instance) -> list:
        """Fetch filled orders from any US broker, normalize to common format.
        Returns list of dicts with: order_id, symbol, quantity, filled_price,
        action, filled_time, asset_type, strike?, expiry?, direction?"""

        if broker_name in ('Webull', 'WEBULL_PAPER'):
            if hasattr(broker_instance, 'get_order_history'):
                return await broker_instance.get_order_history(count=20) or []

        elif broker_name == 'SCHWAB':
            if hasattr(broker_instance, 'get_order_history'):
                return await broker_instance.get_order_history(count=20) or []

        elif broker_name.startswith('IBKR'):
            if hasattr(broker_instance, 'ib') and broker_instance.ib.isConnected():
                orders = []
                for trade in broker_instance.ib.trades():
                    if not trade.orderStatus or trade.orderStatus.status != 'Filled':
                        continue
                    order = trade.order
                    contract = trade.contract
                    if not contract:
                        continue
                    filled_qty = int(trade.orderStatus.filled) if trade.orderStatus.filled else 0
                    avg_price = float(trade.orderStatus.avgFillPrice) if trade.orderStatus.avgFillPrice else 0
                    if filled_qty <= 0 or avg_price <= 0:
                        continue
                    action = getattr(order, 'action', '')
                    side = 'BUY' if action == 'BUY' else 'SELL'
                    asset_type = 'option' if contract.secType == 'OPT' else 'stock'
                    filled_time = None
                    if trade.fills:
                        filled_time = trade.fills[-1].time.isoformat() if trade.fills[-1].time else None
                    entry = {
                        'order_id': str(order.orderId),
                        'symbol': contract.symbol,
                        'quantity': filled_qty,
                        'filled_price': avg_price,
                        'action': side,
                        'filled_time': filled_time or datetime.now().isoformat(),
                        'asset_type': asset_type,
                    }
                    if asset_type == 'option':
                        expiry_raw = contract.lastTradeDateOrContractMonth or ''
                        if len(expiry_raw) == 8:
                            entry['expiry'] = f"{expiry_raw[:4]}-{expiry_raw[4:6]}-{expiry_raw[6:8]}"
                        else:
                            entry['expiry'] = expiry_raw
                        entry['strike'] = contract.strike
                        entry['direction'] = contract.right
                    orders.append(entry)
                return orders

        elif broker_name.startswith('TASTYTRADE'):
            if hasattr(broker_instance, 'get_filled_orders'):
                return await asyncio.to_thread(broker_instance.get_filled_orders, 20) or []

        elif 'ALPACA' in broker_name.upper():
            if hasattr(broker_instance, 'get_orders'):
                orders = []
                try:
                    from src.services.broker_sync_service import parse_occ_symbol
                except ImportError:
                    parse_occ_symbol = None
                try:
                    raw = broker_instance.get_orders(status='closed') or []
                    for o in raw:
                        if not (hasattr(o, 'status') and 'FILLED' in str(o.status).upper()):
                            continue
                        filled_time = o.filled_at.isoformat() if o.filled_at else None
                        if not filled_time:
                            continue
                        parsed = parse_occ_symbol(o.symbol) if parse_occ_symbol else None
                        entry = {
                            'order_id': str(o.id),
                            'symbol': parsed['symbol'] if parsed else o.symbol,
                            'quantity': int(float(o.filled_qty or o.qty)),
                            'filled_price': float(o.filled_avg_price or 0),
                            'action': 'BUY' if 'BUY' in str(o.side).upper() else 'SELL',
                            'filled_time': filled_time,
                            'asset_type': 'option' if parsed else 'stock',
                        }
                        if parsed:
                            entry['strike'] = parsed.get('strike')
                            entry['expiry'] = parsed.get('expiry')
                            entry['direction'] = parsed.get('call_put')
                        orders.append(entry)
                except Exception as e:
                    print(f"[TRADE MONITOR] Alpaca orders error: {e}", flush=True)
                return orders

        elif broker_name.startswith('WEBULL_OFFICIAL'):
            if hasattr(broker_instance, 'get_order_history'):
                orders = []
                raw = await broker_instance.get_order_history() or []
                for o in raw:
                    status = (o.get('status') or '').upper()
                    if status != 'FILLED':
                        continue
                    inst_type = o.get('instrument_type', 'EQUITY')
                    asset_type = 'option' if inst_type == 'OPTION' else 'stock'
                    side = (o.get('action') or '').upper()
                    orders.append({
                        'order_id': o.get('order_id') or o.get('broker_order_id'),
                        'symbol': o.get('symbol'),
                        'quantity': int(float(o.get('filled_quantity') or o.get('quantity', 0))),
                        'filled_price': float(o.get('filled_price', 0) or 0),
                        'action': side,
                        'filled_time': o.get('filled_time') or o.get('place_time', ''),
                        'asset_type': asset_type,
                    })
                return orders

        elif broker_name == 'ROBINHOOD':
            if hasattr(broker_instance, 'get_orders'):
                orders = []
                try:
                    raw = await asyncio.to_thread(broker_instance.get_orders, 'closed')
                    for o in (raw or []):
                        state = (o.get('state') or '').lower()
                        if state != 'filled':
                            continue
                        symbol = o.get('symbol') or o.get('chain_symbol', '')
                        if not symbol:
                            continue
                        is_option = bool(o.get('chain_symbol') and o.get('legs'))
                        side = (o.get('side') or 'buy').upper()
                        if is_option:
                            direction = (o.get('direction') or '').upper()
                            action = 'BUY' if 'DEBIT' in direction else 'SELL'
                        else:
                            action = 'BUY' if side == 'BUY' else 'SELL'
                        qty = float(o.get('cumulative_quantity', 0) or o.get('processed_quantity', 0) or o.get('quantity', 0))
                        price = float(o.get('average_price', 0) or o.get('price', 0) or 0)
                        filled_time = o.get('last_transaction_at') or o.get('updated_at', '')
                        entry = {
                            'order_id': o.get('id'),
                            'symbol': symbol,
                            'quantity': int(qty) if qty else 0,
                            'filled_price': price,
                            'action': action,
                            'filled_time': filled_time,
                            'asset_type': 'option' if is_option else 'stock',
                        }
                        if is_option and o.get('legs'):
                            leg = o['legs'][0]
                            entry['strike'] = float(leg.get('strike_price', 0) or 0) or None
                            entry['expiry'] = leg.get('expiration_date')
                            opt_type = (leg.get('option_type') or '').lower()
                            entry['direction'] = 'C' if opt_type == 'call' else ('P' if opt_type == 'put' else None)
                        orders.append(entry)
                except Exception as e:
                    print(f"[TRADE MONITOR] Robinhood orders error: {e}", flush=True)
                return orders

        return []

    async def start(self):
        """Start the trade monitor loop with enable gate"""
        if self.running:
            return

        settings = db.get_trade_monitor_settings()
        if not settings.get('enabled'):
            print("[TRADE MONITOR] Disabled in settings", flush=True)
            return

        if not self.broker and not self._broker_manager:
            print("[TRADE MONITOR] No broker connected", flush=True)
            return

        brokers = self._get_brokers_to_monitor()
        broker_names = [b[0] for b in brokers] if brokers else ['(none yet)']
        self.running = True
        self._stop_event.clear()
        self._standby_mode = False
        self._task = asyncio.create_task(self._poll_loop())
        print(f"[TRADE MONITOR] ✓ Started — monitoring {len(brokers)} broker(s): {broker_names}", flush=True)
        
    async def stop(self):
        """Stop the trade monitor with cooperative cancellation"""
        self.running = False
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[TRADE MONITOR] Stopped", flush=True)
    
    def request_stop(self):
        """Thread-safe request to stop the monitor (can be called from Flask thread)"""
        self._stop_event.set()
        self.running = False
        print("[TRADE MONITOR] Stop requested", flush=True)
        
    async def _poll_loop(self):
        """Main polling loop with enable gate and cooperative cancellation"""
        print("[TRADE MONITOR] Poll loop started with enable gate", flush=True)
        
        while self.running and not self._stop_event.is_set():
            try:
                settings = db.get_trade_monitor_settings()
                is_enabled = settings.get('enabled', False)
                
                if is_enabled:
                    if self._standby_mode:
                        print("[TRADE MONITOR] ✓ Resuming active monitoring", flush=True)
                        self._standby_mode = False
                    
                    base_interval = settings.get('poll_interval_seconds', 10)
                    poll_interval = get_adaptive_poll_interval(base_interval)
                    
                    self._poll_count += 1
                    
                    now = datetime.now()
                    if self._last_status_log is None or (now - self._last_status_log).seconds >= 300:
                        market_status = "OPEN" if is_market_open() else "CLOSED"
                        print(f"[TRADE MONITOR] Active (market={market_status}, poll={poll_interval}s, count={self._poll_count})", flush=True)
                        self._last_status_log = now
                    
                    await self._check_for_new_orders(settings)
                    
                    self._last_poll_time = now
                    
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=poll_interval)
                        break
                    except asyncio.TimeoutError:
                        pass
                else:
                    if not self._standby_mode:
                        print("[TRADE MONITOR] ⏸️ Entering standby - disabled in settings (zero API calls)", flush=True)
                        self._standby_mode = True
                    
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=5)
                        break
                    except asyncio.TimeoutError:
                        pass
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TRADE MONITOR] Error: {e}", flush=True)
                await asyncio.sleep(10)
        
        print("[TRADE MONITOR] Poll loop ended", flush=True)
                
    async def _check_for_new_orders(self, settings: Dict[str, Any]):
        """Check ALL connected brokers for new filled orders"""
        brokers = self._get_brokers_to_monitor()
        if not brokers:
            return

        test_mode_setting = db.get_setting('trade_monitor_test_mode', 'false')
        test_mode = test_mode_setting.lower() == 'true'
        include_stocks = settings.get('include_stocks', True)
        include_options = settings.get('include_options', True)
        post_bto = settings.get('post_bto_signals', True)
        post_stc = settings.get('post_stc_signals', True)
        target_channel = settings.get('target_webhook_channel_id')
        rate_manager = get_rate_limit_manager() if RATE_LIMIT_AVAILABLE else None

        for b_name, b_instance in brokers:
            b_key = b_name.lower()
            try:
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request(b_key)
                    if not can_proceed:
                        continue
                    rate_manager.record_request(b_key)

                filled_orders = await self._fetch_filled_orders(b_name, b_instance)
                orders = []
                if filled_orders:
                    for order in filled_orders:
                        order['_status'] = 'FILLED'
                    orders.extend(filled_orders)

                if test_mode and hasattr(b_instance, 'get_pending_orders'):
                    try:
                        if asyncio.iscoroutinefunction(getattr(b_instance, 'get_pending_orders', None)):
                            pending = await b_instance.get_pending_orders() or []
                        else:
                            pending = await asyncio.to_thread(b_instance.get_pending_orders) or []
                        for order in pending:
                            order['_status'] = 'PENDING'
                        orders.extend(pending)
                    except Exception:
                        pass

                if test_mode:
                    current_ids = {o.get('order_id') for o in orders if o.get('order_id')}
                    canceled_ids = {k for k in self._tracked_pending_orders if self._tracked_pending_orders[k].get('_broker') == b_key} - current_ids
                    for cid in canceled_ids:
                        canceled_order = self._tracked_pending_orders.pop(cid, None)
                        if canceled_order:
                            await self._post_canceled_order(canceled_order, b_key, target_channel)
                    for order in orders:
                        oid = order.get('order_id')
                        if oid and order.get('_status') == 'PENDING':
                            order['_broker'] = b_key
                            self._tracked_pending_orders[oid] = order

                if not orders:
                    continue

                # First poll: seed all existing orders into synced_orders without posting
                if not self._seeded:
                    seeded = 0
                    for order in orders:
                        oid = order.get('order_id')
                        if oid and not db.is_order_synced(b_key, oid):
                            filled_time = order.get('filled_time', '')
                            if is_recent_fill(filled_time, max_seconds=86400):
                                db.add_synced_order(
                                    broker=b_key, order_id=oid,
                                    symbol=order.get('symbol', ''),
                                    action=order.get('action', ''),
                                    quantity=order.get('quantity', 0),
                                    filled_price=order.get('filled_price', 0),
                                    asset_type=order.get('asset_type', 'stock'),
                                )
                                seeded += 1
                    if seeded:
                        print(f"[TRADE MONITOR] Seeded {seeded} existing order(s) from {b_name} (no webhook)", flush=True)
                    continue

                new_orders = []
                for order in orders:
                    order_id = order.get('order_id')
                    if not order_id:
                        continue
                    if db.is_order_synced(b_key, order_id):
                        continue
                    filled_time = order.get('filled_time', '')
                    if not is_recent_fill(filled_time, max_seconds=86400):
                        continue
                    asset_type = order.get('asset_type', 'stock')
                    if asset_type == 'stock' and not include_stocks:
                        continue
                    if asset_type == 'option' and not include_options:
                        continue
                    action = order.get('action', '').upper()
                    is_buy = action in ['BUY', 'BTO', 'BUY_TO_OPEN']
                    is_sell = action in ['SELL', 'STC', 'SELL_TO_CLOSE']
                    if is_buy and not post_bto:
                        continue
                    if is_sell and not post_stc:
                        continue
                    new_orders.append(order)

                if new_orders:
                    print(f"[TRADE MONITOR] Found {len(new_orders)} new order(s) from {b_name}", flush=True)

                for order in new_orders:
                    if target_channel:
                        await self._post_order_to_discord(order, b_key, target_channel)
                    else:
                        print(f"[TRADE MONITOR] ⚠️ No target webhook channel configured", flush=True)

            except Exception as e:
                print(f"[TRADE MONITOR] Error checking {b_name}: {e}", flush=True)

        if not self._seeded:
            self._seeded = True
            print("[TRADE MONITOR] ✓ Seed complete — now detecting new fills only", flush=True)
            
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
            direction = (order.get('direction') or 'C').upper()
            # Ensure direction is valid (C or P only)
            if direction not in ['C', 'P']:
                direction = 'C'
            
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
        
        if not webhook_url:
            print(f"[TRADE MONITOR] ⚠️ No webhook URL found for channel_id={target_channel}", flush=True)

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
        """Get webhook URL for a webhook channel (from webhook_channels table)"""
        if not channel_id:
            return None

        try:
            channel_id_int = int(channel_id)
        except (ValueError, TypeError):
            return None

        channel = webhook_service.get_webhook_channel(channel_id_int)
        if not channel:
            return None

        return channel.get('webhook_url')
    
    def _add_bto_to_trades_table(self, broker_name: str, symbol: str, strike: float,
                                  expiry: str, direction: str, quantity: int,
                                  entry_price: float, asset_type: str, order_id: str):
        """Add BTO entry to main trades table for P&L tracking"""
        try:
            # Dedup: skip if a trade with this order_id already exists
            if order_id:
                existing = db.get_trades(status='OPEN', limit=1000) + db.get_trades(status='PENDING', limit=500)
                for t in existing:
                    if t.get('order_id') == order_id:
                        print(f"[TRADE MONITOR] ⚠️ Skipping duplicate: {symbol} order_id={order_id} already exists (ID={t['id']})", flush=True)
                        return
                    if (t['symbol'] == symbol and
                        (t.get('broker') or '').upper() == broker_name.upper() and
                        t.get('direction') == 'BTO'):
                        if asset_type == 'stock' or (t.get('strike') == strike and t.get('call_put') == direction):
                            print(f"[TRADE MONITOR] ⚠️ Skipping duplicate: {symbol} already tracked (ID={t['id']}, broker={broker_name})", flush=True)
                            return

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
                'status': 'OPEN',
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
            
            try:
                from gui_app.database import get_connection as _get_fill_conn, update_closure_exit_fill
                _fill_conn = _get_fill_conn()
                _fill_cur = _fill_conn.cursor()
                _fill_cur.execute('''
                    SELECT lc.id FROM lot_closures lc
                    JOIN signal_lots sl ON lc.lot_id = sl.id
                    WHERE UPPER(sl.symbol) = UPPER(?) AND lc.exit_fill_price IS NULL
                    ORDER BY lc.closed_at DESC LIMIT 5
                ''', (symbol,))
                for row in _fill_cur.fetchall():
                    update_closure_exit_fill(row['id'], close_price, broker_name, exit_source='trade_monitor')
                    print(f"[TRADE MONITOR] ✓ Updated lot_closure #{row['id']} exit fill: ${close_price:.2f}", flush=True)
            except Exception as fill_err:
                print(f"[TRADE MONITOR] ⚠️ Lot closure fill update: {fill_err}", flush=True)
            
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
