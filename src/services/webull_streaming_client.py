"""
Webull MQTT Streaming Client
=============================
Connects to Webull's MQTT streaming service for real-time quote and order data.
Eliminates REST polling for price data during position monitoring.

Protocol:
1. Connect to wspush.webullbroker.com:443 via MQTT over WebSocket (TLS)
2. Subscribe to ticker IDs for price updates (topic 105)
3. Optionally subscribe to order updates via platpush.webullbroker.com
4. Receive continuous push updates (no API calls consumed)

Fallback:
- If streaming fails, services fall back to REST polling (existing behavior)
- Auto-reconnect with exponential backoff on disconnect
"""

import json
import time
import threading
from typing import Dict, Optional, Set, Any

from src.services.webull_data_hub import get_webull_data_hub


class WebullStreamingClient:

    def __init__(self, broker_instance):
        self._broker = broker_instance
        self._hub = get_webull_data_hub()
        self._running = False
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._subscribed_ticker_ids: Set[str] = set()
        self._subscription_levels: Dict[str, int] = {}
        self._symbol_to_ticker_id: Dict[str, str] = {}
        self._ticker_id_to_symbol: Dict[str, str] = {}
        self._conn = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._did: Optional[str] = None
        self._access_token: Optional[str] = None
        self._wb_instance = None

        print(f"[WEBULL_STREAM] Streaming client created for {broker_instance.name}")

    def set_wb_instance(self, wb_instance):
        self._wb_instance = wb_instance

    def _on_price_message(self, topic, data):
        try:
            ticker_id = str(topic.get('tickerId', ''))
            if not ticker_id:
                return

            symbol = self._ticker_id_to_symbol.get(ticker_id)
            if not symbol:
                symbol = self._hub.get_symbol_by_ticker_id(ticker_id)
            if not symbol:
                return

            quote_update = {'ticker_id': ticker_id}

            if 'deal' in data:
                deal = data['deal']
                if 'price' in deal:
                    quote_update['last'] = float(deal['price'])
                    quote_update['price'] = float(deal['price'])
                if 'volume' in deal:
                    quote_update['deal_volume'] = int(deal['volume'])

            _has_pPrice = 'pPrice' in data and float(data.get('pPrice', 0) or 0) > 0
            if 'close' in data:
                quote_update['close'] = float(data['close'])
                if not _has_pPrice:
                    if 'deal' not in data:
                        quote_update.setdefault('last', float(data['close']))
                        quote_update.setdefault('price', float(data['close']))
                    else:
                        pass
                else:
                    pass
            if 'high' in data:
                quote_update['high'] = float(data['high'])
            if 'low' in data:
                quote_update['low'] = float(data['low'])
            if 'open' in data:
                quote_update['open'] = float(data['open'])
            if 'volume' in data:
                quote_update['volume'] = int(data['volume'])
            if 'change' in data:
                quote_update['change'] = float(data['change'])
            if 'changeRatio' in data:
                quote_update['changeRatio'] = float(data['changeRatio'])
            if _has_pPrice:
                pp = float(data['pPrice'])
                if 0 < pp < 500000:
                    quote_update['last'] = pp
                    quote_update['price'] = pp

            if 'askList' in data and data['askList']:
                best_ask = data['askList'][0]
                quote_update['ask'] = float(best_ask.get('price', 0))
            if 'bidList' in data and data['bidList']:
                best_bid = data['bidList'][0]
                quote_update['bid'] = float(best_bid.get('price', 0))

            if len(quote_update) > 1:
                self._hub.update_quote(symbol, quote_update, source="stream")

        except Exception as e:
            print(f"[WEBULL_STREAM] Error processing price message: {e}")

    def _on_order_message(self, topic, data):
        try:
            order_status = data.get('orderStatus', '')
            order_id = data.get('orderId', '')
            ticker_id = data.get('tickerId', '')
            filled_qty = data.get('filledQuantity', 0)

            status_str = order_status if order_status else 'unknown'
            print(f"[WEBULL_STREAM] Order update: id={order_id}, status={status_str}, filled={filled_qty}")

            if order_status in ('Filled', 'Cancelled', 'PartialFilled'):
                self._hub.invalidate_positions()
                self._hub.invalidate_orders()
                self._hub.request_risk_eval()
                self._hub._emit('order_event', {
                    'order_id': order_id,
                    'status': order_status,
                    'ticker_id': ticker_id,
                    'filled_quantity': filled_qty,
                    'raw': data
                })

                now = time.time()
                last_refresh = getattr(self, '_last_order_refresh_ts', 0)
                if now - last_refresh < 5.0:
                    pass
                else:
                    self._last_order_refresh_ts = now
                    wb = self._wb_instance or getattr(self._broker, 'wb', None)
                    if wb is not None:
                        try:
                            import asyncio as _aio
                            loop = _aio.get_event_loop()
                            if loop.is_running():
                                _aio.ensure_future(self._hub.refresh_positions_once(wb))
                                _aio.ensure_future(self._hub.refresh_orders_once(wb))
                        except Exception:
                            pass

                if order_status == 'Filled':
                    self._hub.invalidate_account()
                    if now - last_refresh >= 5.0:
                        wb = self._wb_instance or getattr(self._broker, 'wb', None)
                        if wb is not None:
                            try:
                                import asyncio as _aio
                                loop = _aio.get_event_loop()
                                if loop.is_running():
                                    _aio.ensure_future(self._hub.refresh_account_once(wb))
                            except Exception:
                                pass
                    try:
                        from src.services.daily_pnl_limit_service import get_daily_pnl_service
                        broker_name = getattr(self._broker, 'name', 'WEBULL')
                        broker_ref = self._broker
                        def _pnl_refresh(bn=broker_name, bi=broker_ref):
                            try:
                                import asyncio as _aio
                                pnl_svc = get_daily_pnl_service()
                                ai = None
                                if hasattr(bi, 'get_account_info'):
                                    loop = _aio.new_event_loop()
                                    try:
                                        coro = bi.get_account_info()
                                        if _aio.iscoroutine(coro):
                                            ai = loop.run_until_complete(coro)
                                        else:
                                            ai = coro
                                    finally:
                                        loop.close()
                                if ai:
                                    pv = float(ai.get('portfolio_value', 0) or ai.get('totalAccountValue', 0) or ai.get('netLiquidation', 0) or 0)
                                    if pv > 0:
                                        print(f"[DAILY_PNL] Real-time fill detected for {bn} — refreshing P&L (equity=${pv:,.2f})")
                                        pnl_svc.update_broker_pnl(bn, pv)
                            except Exception as ex:
                                print(f"[DAILY_PNL] Real-time P&L refresh error: {ex}")
                        threading.Thread(target=_pnl_refresh, daemon=True).start()
                    except ImportError:
                        pass

        except Exception as e:
            print(f"[WEBULL_STREAM] Error processing order message: {e}")

    def _patch_paho_mqtt(self):
        try:
            import paho.mqtt.client as mqtt
            if hasattr(mqtt, 'CallbackAPIVersion'):
                _OriginalClient = mqtt.Client
                _patched = getattr(mqtt.Client, '_botify_patched', False)
                if _patched:
                    return
                class PatchedClient(_OriginalClient):
                    _botify_patched = True
                    def __init__(self, *args, **kwargs):
                        if 'callback_api_version' not in kwargs:
                            kwargs['callback_api_version'] = mqtt.CallbackAPIVersion.VERSION1
                        if args and isinstance(args[0], str) and 'client_id' not in kwargs:
                            kwargs['client_id'] = args[0]
                            args = args[1:]
                        super().__init__(*args, **kwargs)
                mqtt.Client = PatchedClient
                print("[WEBULL_STREAM] ✓ Patched paho-mqtt v2.0 compatibility")
        except Exception as e:
            print(f"[WEBULL_STREAM] paho-mqtt patch skipped: {e}")

    def _connect_streaming(self):
        self._patch_paho_mqtt()
        try:
            from webull import StreamConn
        except ImportError:
            print("[WEBULL_STREAM] ❌ webull StreamConn not available")
            return

        while self._running:
            try:
                self._conn = StreamConn(debug_flg=False)
                self._conn.price_func = self._on_price_message
                self._conn.order_func = self._on_order_message

                did = self._did or getattr(self._broker, 'did', None) or getattr(self._broker.wb, '_did', None) or getattr(self._broker.wb, 'did', None)
                if not did:
                    print("[WEBULL_STREAM] ❌ No device ID available, cannot connect")
                    time.sleep(30)
                    continue

                access_token = self._access_token or getattr(self._broker.wb, '_access_token', None) or getattr(self._broker.wb, 'access_token', None)

                print(f"[WEBULL_STREAM] Connecting to Webull MQTT (did={did[:8]}...)")

                if access_token and len(access_token) > 1:
                    self._conn.connect(did, access_token=access_token)
                    print("[WEBULL_STREAM] ✓ Connected with order updates enabled")
                else:
                    self._conn.connect(did)
                    print("[WEBULL_STREAM] ✓ Connected (quotes only, no order updates)")

                self._connected = True
                self._reconnect_attempts = 0
                self._hub.set_streaming_active(True)

                if self._subscribed_ticker_ids:
                    for tid in list(self._subscribed_ticker_ids):
                        try:
                            level = self._subscription_levels.get(tid, 105)
                            self._conn.subscribe(tId=tid, level=level)
                        except Exception as e:
                            print(f"[WEBULL_STREAM] Error resubscribing {tid}: {e}")

                print(f"[WEBULL_STREAM] ✓ Streaming active, {len(self._subscribed_ticker_ids)} subscriptions")

                self._conn.run_blocking_loop()

            except Exception as e:
                error_str = str(e)
                if 'connection refused' not in error_str.lower():
                    print(f"[WEBULL_STREAM] Connection error: {e}")

            self._connected = False
            self._hub.set_streaming_active(False)

            if self._running:
                self._reconnect_attempts += 1
                if self._reconnect_attempts > self._max_reconnect_attempts:
                    wait = 60
                    print(f"[WEBULL_STREAM] Max reconnect attempts reached, waiting {wait}s...")
                    self._reconnect_attempts = 0
                else:
                    wait = min(2 * (2 ** min(self._reconnect_attempts, 5)), 60)
                    print(f"[WEBULL_STREAM] Reconnecting in {wait}s (attempt {self._reconnect_attempts})...")
                time.sleep(wait)

    def subscribe_symbol(self, symbol: str, ticker_id: str, is_option: bool = False):
        with self._lock:
            ticker_id = str(ticker_id)
            if not ticker_id or ticker_id == '0':
                return

            level = 106 if is_option else 105

            self._symbol_to_ticker_id[symbol.upper()] = ticker_id
            self._ticker_id_to_symbol[ticker_id] = symbol.upper()
            self._hub.register_ticker_id(symbol, ticker_id)

            if ticker_id in self._subscribed_ticker_ids:
                existing_level = self._subscription_levels.get(ticker_id, 105)
                if existing_level == level:
                    return
                self._subscription_levels[ticker_id] = level
                if self._connected and self._conn:
                    try:
                        self._conn.subscribe(tId=ticker_id, level=level)
                        print(f"[WEBULL_STREAM] Re-subscribed {symbol} at level {level}")
                    except Exception:
                        pass
                return

            self._subscribed_ticker_ids.add(ticker_id)
            self._subscription_levels[ticker_id] = level
            self._hub._subscribed_ticker_ids.add(ticker_id)
            self._hub.add_subscribed_symbols({symbol.upper()})

            if self._connected and self._conn:
                try:
                    self._conn.subscribe(tId=ticker_id, level=level)
                    print(f"[WEBULL_STREAM] Subscribed: {symbol} (tid={ticker_id}, level={level})")
                except Exception as e:
                    print(f"[WEBULL_STREAM] Error subscribing {symbol}: {e}")

    def subscribe_positions(self, positions: list):
        for pos in positions:
            symbol = pos.get('symbol', '') or pos.get('ticker', {}).get('symbol', '')
            ticker_id = pos.get('ticker_id', 0) or pos.get('ticker', {}).get('tickerId', 0)
            if not ticker_id:
                ticker_id = pos.get('tickerId', 0)
            is_option = ('optionId' in pos or 'option_id' in pos
                         or 'strikePrice' in pos or 'strike' in pos
                         or 'expireDate' in pos or 'expiry' in pos
                         or pos.get('assetType', '').upper() in ('OPTION', 'OPT')
                         or pos.get('asset', '').lower() == 'option')
            if symbol and ticker_id:
                self.subscribe_symbol(symbol, str(ticker_id), is_option=is_option)

    def unsubscribe_symbol(self, symbol: str):
        with self._lock:
            ticker_id = self._symbol_to_ticker_id.pop(symbol.upper(), None)
            if ticker_id:
                self._ticker_id_to_symbol.pop(ticker_id, None)
                self._subscribed_ticker_ids.discard(ticker_id)
                self._hub._subscribed_ticker_ids.discard(ticker_id)
                self._hub.remove_subscribed_symbols({symbol.upper()})
                if self._connected and self._conn:
                    try:
                        self._conn.unsubscribe(tId=ticker_id, level=105)
                    except Exception:
                        pass

    def start(self):
        if self._running:
            print("[WEBULL_STREAM] Already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._connect_streaming,
            daemon=True,
            name="WebullStreaming"
        )
        self._thread.start()
        print("[WEBULL_STREAM] Started in background thread")

    def stop(self):
        self._running = False
        self._connected = False
        self._hub.set_streaming_active(False)

        if self._conn:
            try:
                if self._conn.client_streaming_quotes:
                    self._conn.client_streaming_quotes.disconnect()
                if self._conn.client_order_upd:
                    self._conn.client_order_upd.disconnect()
            except Exception:
                pass

        print("[WEBULL_STREAM] Stopping...")

    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> Dict[str, Any]:
        return {
            'connected': self._connected,
            'running': self._running,
            'subscribed_symbols': len(self._subscribed_ticker_ids),
            'reconnect_attempts': self._reconnect_attempts,
            'streaming_active': self._hub.is_streaming(),
            'symbol_map_size': len(self._symbol_to_ticker_id)
        }
