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

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self._broker.BASE_URL}/userPreference",
                    headers={
                        'Authorization': f'Bearer {self._broker.access_token}',
                        'Accept': 'application/json'
                    }
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

                print(f"[SCHWAB_STREAM] ✓ Streamer info obtained (socket: {socket_url[:50]}...)")
                return True

        except Exception as e:
            print(f"[SCHWAB_STREAM] ❌ Error fetching streamer info: {e}")
            return False

    def _build_login_request(self) -> Dict:
        si = self._streamer_info
        account_id = self._account_id or self._broker.account_number or ''
        app_id = self._app_id or si.get('appId', '')

        credential_parts = {
            'userid': account_id,
            'token': si.get('token', ''),
            'company': si.get('company', ''),
            'segment': si.get('segment', ''),
            'cddomain': si.get('cddomain', si.get('accountCdDomainId', '')),
            'usergroup': si.get('userGroup', ''),
            'accesslevel': si.get('accessLevel', ''),
            'authorized': 'Y',
            'timestamp': str(si.get('tokenTimestamp', int(time.time() * 1000))),
            'appid': app_id,
            'acl': si.get('acl', '')
        }

        credential = '&'.join(f'{k}={v}' for k, v in credential_parts.items())

        return {
            "requests": [{
                "service": "ADMIN",
                "requestid": "0",
                "command": "LOGIN",
                "account": account_id,
                "source": app_id,
                "parameters": {
                    "credential": credential,
                    "token": si.get('token', ''),
                    "version": "1.0",
                    "qoslevel": "0"
                }
            }]
        }

    def _build_subscribe_request(self, service: str, symbols: list, fields: str) -> Dict:
        return {
            "requests": [{
                "service": service,
                "requestid": self._next_request_id(),
                "command": "SUBS",
                "account": self._account_id or '',
                "source": self._app_id or '',
                "parameters": {
                    "keys": ','.join(symbols),
                    "fields": fields
                }
            }]
        }

    def _build_add_request(self, service: str, symbols: list, fields: str) -> Dict:
        return {
            "requests": [{
                "service": service,
                "requestid": self._next_request_id(),
                "command": "ADD",
                "account": self._account_id or '',
                "source": self._app_id or '',
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
                    pass

        if 'data' in data:
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
                    wait = min(30 * (2 ** self._reconnect_attempts), 300)
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
                    ping_interval=30,
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
                    print("[SCHWAB_STREAM] ✓ Connected and streaming")

                    if self._subscribed_equities:
                        old_eq = list(self._subscribed_equities)
                        self._subscribed_equities.clear()
                        await self.subscribe_equities(old_eq)
                    if self._subscribed_options:
                        old_opt = list(self._subscribed_options)
                        self._subscribed_options.clear()
                        await self.subscribe_options(old_opt)

                    async for message in ws:
                        if not self._running:
                            break
                        self._decode_message(message)

            except asyncio.CancelledError:
                break
            except Exception as e:
                error_str = str(e)
                if 'going away' not in error_str.lower() and 'normal closure' not in error_str.lower():
                    print(f"[SCHWAB_STREAM] Connection error: {e}")

            self._connected = False
            self._ws = None
            self._hub.set_streaming_active(False)

            if self._running:
                self._reconnect_attempts += 1
                if self._reconnect_attempts > self._max_reconnect_attempts:
                    wait = 300
                    print(f"[SCHWAB_STREAM] Max reconnect attempts reached, waiting {wait}s...")
                    self._reconnect_attempts = 0
                else:
                    wait = min(5 * (2 ** min(self._reconnect_attempts, 6)), 120)
                    print(f"[SCHWAB_STREAM] Reconnecting in {wait}s (attempt {self._reconnect_attempts})...")
                await asyncio.sleep(wait)

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
