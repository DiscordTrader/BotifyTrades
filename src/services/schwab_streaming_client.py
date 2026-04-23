"""
Schwab WebSocket Streaming Client
=================================
Connects to Schwab's WebSocket streaming API for real-time quote data.
Eliminates REST polling for price data (saves ~60-120 API calls/min).

Protocol:
1. GET /trader/v1/userPreference to obtain streamerInfo (socket URL, token, credentials)
2. Connect to WebSocket at streamerSocketUrl
3. Send LOGIN request with credential string
4. Subscribe to LEVELONE_EQUITIES and LEVELONE_OPTIONS
5. Receive continuous push updates (no API calls consumed)

Fallback:
- If streaming fails, services fall back to REST polling (existing behavior)
- Auto-reconnect with exponential backoff on disconnect
"""

import json
import asyncio
import time
import threading
from typing import Dict, Optional, Set, Any

from src.services.schwab_data_hub import get_schwab_data_hub


EQUITY_FIELD_MAP = {
    '0': 'SYMBOL', '1': 'BID_PRICE', '2': 'ASK_PRICE', '3': 'LAST_PRICE',
    '4': 'BID_SIZE', '5': 'ASK_SIZE', '6': 'ASK_ID', '7': 'BID_ID',
    '8': 'TOTAL_VOLUME', '9': 'LAST_SIZE', '10': 'HIGH_PRICE',
    '11': 'LOW_PRICE', '12': 'CLOSE_PRICE', '13': 'EXCHANGE_ID',
    '14': 'MARGINAL', '15': 'DESCRIPTION', '24': 'VOLATILITY',
    '28': 'OPEN_PRICE', '29': 'NET_CHANGE', '48': 'SECURITY_STATUS'
}

OPTION_FIELD_MAP = {
    '0': 'SYMBOL', '1': 'DESCRIPTION', '2': 'BID_PRICE', '3': 'ASK_PRICE',
    '4': 'LAST_PRICE', '5': 'HIGH_PRICE', '6': 'LOW_PRICE',
    '7': 'CLOSE_PRICE', '8': 'TOTAL_VOLUME', '9': 'OPEN_INTEREST',
    '10': 'VOLATILITY', '11': 'MONEY_INTRINSIC_VALUE',
    '12': 'EXPIRATION_YEAR', '13': 'MULTIPLIER', '14': 'DIGITS',
    '15': 'OPEN_PRICE', '16': 'BID_SIZE', '17': 'ASK_SIZE',
    '18': 'LAST_SIZE', '19': 'NET_CHANGE', '20': 'STRIKE_PRICE',
    '21': 'CONTRACT_TYPE', '22': 'UNDERLYING', '23': 'EXPIRATION_MONTH',
    '24': 'DELIVERABLES', '25': 'TIME_VALUE', '26': 'EXPIRATION_DAY',
    '27': 'DAYS_TO_EXPIRATION', '28': 'DELTA', '29': 'GAMMA',
    '30': 'THETA', '31': 'VEGA', '32': 'RHO', '33': 'SECURITY_STATUS',
    '34': 'THEORETICAL_OPTION_VALUE', '35': 'UNDERLYING_PRICE',
    '36': 'UV_EXPIRATION_TYPE', '37': 'MARK', '38': 'QUOTE_TIME_MILLIS',
    '39': 'TRADE_TIME_MILLIS', '40': 'EXCHANGE_ID',
    '41': 'EXERCISE_TYPE', '42': 'PENNY_PILOT'
}


class SchwabStreamingClient:

    def __init__(self, broker_instance):
        self._broker = broker_instance
        self._hub = get_schwab_data_hub()
        self._ws = None
        self._running = False
        self._connected = False
        self._request_id = 0
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._streamer_info: Optional[Dict] = None
        self._account_id: Optional[str] = None
        self._app_id: Optional[str] = None
        self._subscribed_equities: Set[str] = set()
        self._subscribed_options: Set[str] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_heartbeat = time.time()
        self._last_pending_drain = 0.0

        print(f"[SCHWAB_STREAM] Streaming client created for {broker_instance.name}")

    def _next_request_id(self) -> str:
        self._request_id += 1
        return str(self._request_id)

    async def _fetch_streamer_info(self) -> bool:
        try:
            import httpx

            if not await self._broker._ensure_valid_token():
                print("[SCHWAB_STREAM] ❌ Cannot get streamer info - not authenticated")
                return False

            import asyncio as _aio
            def _sync_streamer_info(url, h):
                with httpx.Client(timeout=15.0) as c:
                    return c.get(url, headers=h)
            
            response = await _aio.to_thread(
                _sync_streamer_info,
                f"{self._broker.BASE_URL}/userPreference",
                {'Authorization': f'Bearer {self._broker.access_token}', 'Accept': 'application/json'}
            )

            if response.status_code != 200:
                print(f"[SCHWAB_STREAM] ❌ userPreference failed: {response.status_code}")
                return False

            data = response.json()
            streamer_info = data.get('streamerInfo', [{}])
            if isinstance(streamer_info, list) and len(streamer_info) > 0:
                self._streamer_info = streamer_info[0]
            elif isinstance(streamer_info, dict):
                self._streamer_info = streamer_info
            else:
                print("[SCHWAB_STREAM] ❌ No streamerInfo in userPreference response")
                return False

            accounts = data.get('accounts', [])
            if accounts:
                self._account_id = accounts[0].get('accountNumber') or accounts[0].get('accountId')

            self._app_id = self._streamer_info.get('schwabClientCustomerId', '') or self._streamer_info.get('appId', '')

            socket_url = self._streamer_info.get('streamerSocketUrl', '')
            if not socket_url:
                print("[SCHWAB_STREAM] ❌ No streamerSocketUrl found")
                return False

            si_keys = list(self._streamer_info.keys())
            print(f"[SCHWAB_STREAM] ✓ Streamer info obtained (socket: {socket_url[:50]}...) keys={si_keys}")
            return True

        except Exception as e:
            print(f"[SCHWAB_STREAM] ❌ Error fetching streamer info: {e}")
            return False

    def _build_login_request(self) -> Dict:
        si = self._streamer_info
        account_id = self._account_id or self._broker.account_number or ''
        app_id = self._app_id or si.get('appId', '')
        access_token = self._broker.access_token or ''

        schwab_client_channel = si.get('schwabClientChannel', '')
        schwab_client_function_id = si.get('schwabClientFunctionId', '')

        return {
            "requests": [{
                "service": "ADMIN",
                "requestid": "0",
                "command": "LOGIN",
                "SchwabClientCustomerId": si.get('schwabClientCustomerId', app_id),
                "SchwabClientCorrelId": si.get('schwabClientCorrelId', ''),
                "parameters": {
                    "Authorization": access_token,
                    "SchwabClientChannel": schwab_client_channel,
                    "SchwabClientFunctionId": schwab_client_function_id
                }
            }]
        }

    def _build_subscribe_request(self, service: str, symbols: list, fields: str) -> Dict:
        si = self._streamer_info or {}
        return {
            "requests": [{
                "service": service,
                "requestid": self._next_request_id(),
                "command": "SUBS",
                "SchwabClientCustomerId": si.get('schwabClientCustomerId', self._app_id or ''),
                "SchwabClientCorrelId": si.get('schwabClientCorrelId', ''),
                "parameters": {
                    "keys": ','.join(symbols),
                    "fields": fields
                }
            }]
        }

    def _build_add_request(self, service: str, symbols: list, fields: str) -> Dict:
        si = self._streamer_info or {}
        return {
            "requests": [{
                "service": service,
                "requestid": self._next_request_id(),
                "command": "ADD",
                "SchwabClientCustomerId": si.get('schwabClientCustomerId', self._app_id or ''),
                "SchwabClientCorrelId": si.get('schwabClientCorrelId', ''),
                "parameters": {
                    "keys": ','.join(symbols),
                    "fields": fields
                }
            }]
        }

    def _decode_message(self, raw_msg: str):
        try:
            data = json.loads(raw_msg)
        except json.JSONDecodeError:
            return

        if 'response' in data:
            for resp in data['response']:
                service = resp.get('service', '')
                command = resp.get('command', '')
                code = resp.get('content', {}).get('code', -1) if isinstance(resp.get('content'), dict) else -1
                if command == 'LOGIN':
                    if code == 0:
                        print("[SCHWAB_STREAM] ✓ Login successful")
                        self._connected = True
                    else:
                        print(f"[SCHWAB_STREAM] ❌ Login failed (code={code}): {resp.get('content', {}).get('msg', '')}")
                elif command == 'SUBS' or command == 'ADD':
                    if code == 0:
                        print(f"[SCHWAB_STREAM] ✓ Subscribed to {service}")
                    else:
                        print(f"[SCHWAB_STREAM] ⚠️ Subscribe {service} response code={code}")

        if 'notify' in data:
            for notify in data['notify']:
                if 'heartbeat' in notify:
                    self._last_heartbeat = time.time()

        if 'data' in data:
            self._last_heartbeat = time.time()
            if not hasattr(self, '_data_msg_count'):
                self._data_msg_count = 0
            self._data_msg_count += 1
            if self._data_msg_count <= 3 or self._data_msg_count % 1000 == 0:
                services = [item.get('service', '?') for item in data['data']]
                print(f"[SCHWAB_STREAM] Data msg #{self._data_msg_count}: {', '.join(services)}")
            for item in data['data']:
                service = item.get('service', '')
                content = item.get('content', [])

                if service == 'LEVELONE_EQUITIES':
                    self._process_equity_quotes(content)
                elif service == 'LEVELONE_OPTIONS':
                    self._process_option_quotes(content)

    def _process_equity_quotes(self, content: list):
        for entry in content:
            symbol = entry.get('key', '')
            if not symbol:
                continue

            decoded = {}
            for num_key, value in entry.items():
                if num_key == 'key':
                    continue
                label = EQUITY_FIELD_MAP.get(str(num_key), num_key)
                decoded[label] = value

            self._hub.update_quote(symbol, decoded, source="stream_equity")

    def _process_option_quotes(self, content: list):
        if not hasattr(self, '_option_quote_count'):
            self._option_quote_count = 0
        for entry in content:
            symbol = entry.get('key', '')
            if not symbol:
                continue

            decoded = {}
            for num_key, value in entry.items():
                if num_key == 'key':
                    continue
                label = OPTION_FIELD_MAP.get(str(num_key), num_key)
                decoded[label] = value

            self._option_quote_count += 1
            if self._option_quote_count <= 3 or self._option_quote_count % 500 == 0:
                bid = decoded.get('BID_PRICE', '?')
                ask = decoded.get('ASK_PRICE', '?')
                last = decoded.get('LAST_PRICE', '?')
                print(f"[SCHWAB_STREAM] Option quote #{self._option_quote_count}: {symbol} bid={bid} ask={ask} last={last}")

            self._hub.update_quote(symbol, decoded, source="stream_option")

    async def subscribe_equities(self, symbols: list):
        if not symbols or not self._ws or not self._connected:
            return

        new_symbols = [s for s in symbols if s not in self._subscribed_equities]
        if not new_symbols:
            return

        fields = "0,1,2,3,8,10,11,12,28,29"

        if not self._subscribed_equities:
            request = self._build_subscribe_request('LEVELONE_EQUITIES', new_symbols, fields)
        else:
            request = self._build_add_request('LEVELONE_EQUITIES', new_symbols, fields)

        try:
            await self._ws.send(json.dumps(request))
            self._subscribed_equities.update(new_symbols)
            self._hub.add_subscribed_symbols(set(new_symbols))
            print(f"[SCHWAB_STREAM] Subscribing to {len(new_symbols)} equities: {', '.join(new_symbols[:5])}{'...' if len(new_symbols) > 5 else ''}")
        except Exception as e:
            print(f"[SCHWAB_STREAM] Error subscribing equities: {e}")

    async def subscribe_options(self, symbols: list):
        if not symbols or not self._ws or not self._connected:
            return

        new_symbols = [s for s in symbols if s not in self._subscribed_options]
        if not new_symbols:
            return

        fields = "0,2,3,4,5,6,7,8,9,10,15,19,20,21,22,27,28,29,30,31,35,37"

        if not self._subscribed_options:
            request = self._build_subscribe_request('LEVELONE_OPTIONS', new_symbols, fields)
        else:
            request = self._build_add_request('LEVELONE_OPTIONS', new_symbols, fields)

        try:
            await self._ws.send(json.dumps(request))
            self._subscribed_options.update(new_symbols)
            self._hub.add_subscribed_symbols(set(new_symbols))
            print(f"[SCHWAB_STREAM] Subscribing to {len(new_symbols)} options: {', '.join(new_symbols[:3])}{'...' if len(new_symbols) > 3 else ''}")
        except Exception as e:
            print(f"[SCHWAB_STREAM] Error subscribing options: {e}")

    async def _connect_and_stream(self):
        try:
            import websockets
        except ImportError:
            print("[SCHWAB_STREAM] ❌ websockets library not installed, streaming disabled")
            return

        while self._running:
            try:
                if not await self._fetch_streamer_info():
                    wait = min(10 * (2 ** min(self._reconnect_attempts, 4)), 60)
                    print(f"[SCHWAB_STREAM] Retrying streamer info in {wait}s...")
                    await asyncio.sleep(wait)
                    self._reconnect_attempts += 1
                    continue

                socket_url = self._streamer_info.get('streamerSocketUrl', '')
                if not socket_url.startswith('wss://'):
                    socket_url = f"wss://{socket_url}/ws"

                print(f"[SCHWAB_STREAM] Connecting to {socket_url}...")

                async with websockets.connect(
                    socket_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                    max_size=2**20
                ) as ws:
                    self._ws = ws
                    self._reconnect_attempts = 0

                    login_request = self._build_login_request()
                    await ws.send(json.dumps(login_request))
                    print("[SCHWAB_STREAM] Login request sent, waiting for response...")

                    login_response = await asyncio.wait_for(ws.recv(), timeout=10)
                    self._decode_message(login_response)

                    if not self._connected:
                        print("[SCHWAB_STREAM] ❌ Login failed, will retry...")
                        await asyncio.sleep(10)
                        continue

                    self._hub.set_streaming_active(True)
                    self._last_heartbeat = time.time()
                    self._last_qos_time = time.time()
                    print("[SCHWAB_STREAM] ✓ Connected and streaming")

                    if self._subscribed_equities:
                        old_eq = list(self._subscribed_equities)
                        self._subscribed_equities.clear()
                        await self.subscribe_equities(old_eq)
                    if self._subscribed_options:
                        old_opt = list(self._subscribed_options)
                        self._subscribed_options.clear()
                        await self.subscribe_options(old_opt)

                    await self._auto_subscribe_positions()

                    msg_count = 0
                    _recv_timeouts = 0
                    while self._running:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=30)
                            self._decode_message(message)
                            msg_count += 1
                            _recv_timeouts = 0
                            if msg_count % 5 == 0:
                                await asyncio.sleep(0)
                        except asyncio.TimeoutError:
                            _recv_timeouts += 1
                            if _recv_timeouts == 1 or _recv_timeouts % 3 == 0:
                                print(f"[SCHWAB_STREAM] No data for {_recv_timeouts * 30}s ({msg_count} msgs received so far)")

                        now = time.time()
                        if now - self._last_qos_time >= 25:
                            try:
                                si = self._streamer_info or {}
                                qos_request = {
                                    "requests": [{
                                        "service": "ADMIN",
                                        "requestid": self._next_request_id(),
                                        "command": "QOS",
                                        "SchwabClientCustomerId": si.get('schwabClientCustomerId', self._app_id or ''),
                                        "SchwabClientCorrelId": si.get('schwabClientCorrelId', ''),
                                        "parameters": {"qoslevel": "0"}
                                    }]
                                }
                                await ws.send(json.dumps(qos_request))
                                self._last_qos_time = now
                            except Exception:
                                break

                        if now - self._last_heartbeat > 180:
                            print("[SCHWAB_STREAM] ⚠️ No heartbeat for 180s, reconnecting...")
                            break

                        if now - self._last_pending_drain >= 10:
                            self._last_pending_drain = now
                            pending = set()
                            try:
                                if self._hub:
                                    pending = self._hub.drain_pending_subscriptions()
                                    if pending:
                                        await self.subscribe_equities(list(pending))
                                        print(f"[SCHWAB_STREAM] ✓ Cross-broker subscribe: {', '.join(sorted(pending))}")
                            except Exception:
                                if pending and self._hub:
                                    self._hub.request_subscribe_equities(pending)

            except asyncio.CancelledError:
                break
            except Exception as e:
                error_str = str(e)
                if '1000' not in error_str and 'going away' not in error_str.lower() and 'normal closure' not in error_str.lower():
                    print(f"[SCHWAB_STREAM] Connection error: {e}")

            self._connected = False
            self._ws = None
            self._hub.set_streaming_active(False)

            if self._running:
                self._reconnect_attempts += 1
                if self._reconnect_attempts > self._max_reconnect_attempts:
                    wait = 60
                    print(f"[SCHWAB_STREAM] Max reconnect attempts reached, waiting {wait}s...")
                    self._reconnect_attempts = 0
                else:
                    wait = min(2 * (2 ** min(self._reconnect_attempts, 5)), 60)
                    print(f"[SCHWAB_STREAM] Reconnecting in {wait}s (attempt {self._reconnect_attempts})...")
                await asyncio.sleep(wait)

    async def _auto_subscribe_positions(self):
        try:
            if not self._broker or not self._connected:
                return
            if hasattr(self._broker, 'get_positions_detailed'):
                positions = await self._broker.get_positions_detailed()
            elif hasattr(self._broker, 'get_positions'):
                positions = await self._broker.get_positions()
            else:
                return
            if not positions:
                return
            equity_symbols = []
            option_symbols = []
            for pos in (positions or []):
                if isinstance(pos, dict):
                    sym = pos.get('symbol', '')
                    asset = pos.get('assetType', pos.get('asset', 'EQUITY'))
                    if asset == 'OPTION' or len(sym) > 10:
                        option_symbols.append(sym)
                    elif sym:
                        equity_symbols.append(sym)
            if equity_symbols:
                await self.subscribe_equities(equity_symbols)
            if option_symbols:
                await self.subscribe_options(option_symbols)
            total = len(equity_symbols) + len(option_symbols)
            if total > 0:
                print(f"[SCHWAB_STREAM] ✓ Auto-subscribed {total} position symbols ({len(equity_symbols)} equity, {len(option_symbols)} option)")
        except Exception as e:
            print(f"[SCHWAB_STREAM] Auto-subscribe positions skipped: {e}")

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        if self._running:
            print("[SCHWAB_STREAM] Already running")
            return

        self._running = True

        if loop:
            self._loop = loop
            asyncio.run_coroutine_threadsafe(self._connect_and_stream(), loop)
            print("[SCHWAB_STREAM] Started on existing event loop")
        else:
            self._thread = threading.Thread(target=self._run_in_thread, daemon=True, name="SchwabStreaming")
            self._thread.start()
            print("[SCHWAB_STREAM] Started in background thread")

    def _run_in_thread(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_stream())
        except Exception as e:
            print(f"[SCHWAB_STREAM] Thread error: {e}")
        finally:
            self._loop.close()

    def stop(self):
        self._running = False
        self._connected = False
        self._hub.set_streaming_active(False)
        print("[SCHWAB_STREAM] Stopping...")

    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    def get_status(self) -> Dict[str, Any]:
        return {
            'connected': self._connected,
            'running': self._running,
            'subscribed_equities': len(self._subscribed_equities),
            'subscribed_options': len(self._subscribed_options),
            'reconnect_attempts': self._reconnect_attempts,
            'streaming_active': self._hub.is_streaming()
        }
