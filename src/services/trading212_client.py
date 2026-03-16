import asyncio
import aiohttp
import time
import hashlib
import collections
from typing import Optional, Dict, Any, List


class Trading212RateLimiter:
    ENDPOINT_LIMITS = {
        'portfolio': (1, 5),
        'orders': (1, 5),
        'account': (1, 5),
        'instruments': (1, 30),
        'history': (6, 60),
        'default': (1, 5),
    }

    def __init__(self):
        self._last_call = {}
        self._lock = asyncio.Lock()

    def _classify(self, path: str) -> str:
        if '/portfolio' in path:
            return 'portfolio'
        if '/orders' in path:
            return 'orders'
        if '/account' in path:
            return 'account'
        if '/instruments' in path or '/metadata' in path:
            return 'instruments'
        if '/history' in path:
            return 'history'
        return 'default'

    async def acquire(self, path: str):
        category = self._classify(path)
        max_calls, window = self.ENDPOINT_LIMITS.get(category, (1, 5))
        min_interval = window / max_calls

        async with self._lock:
            now = time.monotonic()
            last = self._last_call.get(category, 0)
            wait = min_interval - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call[category] = time.monotonic()


class SoftThrottleDetector:
    def __init__(self, window_size: int = 20):
        self._response_times = collections.deque(maxlen=window_size)
        self._baseline_median = None
        self._is_throttled = False

    def record(self, response_time_ms: float):
        self._response_times.append(response_time_ms)
        if len(self._response_times) >= 10:
            sorted_times = sorted(self._response_times)
            median = sorted_times[len(sorted_times) // 2]
            p99 = sorted_times[int(len(sorted_times) * 0.95)]

            if self._baseline_median is None:
                self._baseline_median = median

            self._is_throttled = p99 > (self._baseline_median * 2.5)

    @property
    def is_throttled(self) -> bool:
        return self._is_throttled


class Trading212Client:
    LIVE_BASE = 'https://live.trading212.com/api/v0'
    DEMO_BASE = 'https://demo.trading212.com/api/v0'

    def __init__(self, api_key: str, environment: str = 'demo', api_secret: str = ''):
        self._api_key = api_key
        self._api_secret = api_secret
        self._environment = environment.lower()
        self._base_url = self.LIVE_BASE if self._environment == 'live' else self.DEMO_BASE
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limiter = Trading212RateLimiter()
        self._throttle_detector = SoftThrottleDetector()

    def _build_auth_header(self) -> str:
        if self._api_secret:
            import base64
            credentials = f"{self._api_key}:{self._api_secret}"
            encoded = base64.b64encode(credentials.encode()).decode()
            return f"Basic {encoded}"
        return self._api_key

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    'Authorization': self._build_auth_header(),
                    'Content-Type': 'application/json',
                },
                timeout=aiohttp.ClientTimeout(total=15)
            )

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(self, method: str, path: str, json_data: dict = None, params: dict = None) -> Dict[str, Any]:
        await self._ensure_session()
        await self._rate_limiter.acquire(path)

        url = f'{self._base_url}{path}'
        start = time.monotonic()

        try:
            async with self._session.request(method, url, json=json_data, params=params) as resp:
                elapsed_ms = (time.monotonic() - start) * 1000
                self._throttle_detector.record(elapsed_ms)

                if resp.status == 429:
                    retry_after = int(resp.headers.get('Retry-After', '10'))
                    print(f"[T212-CLIENT] Rate limited (429). Retry after {retry_after}s")
                    return {'success': False, 'error': 'rate_limited', 'retry_after': retry_after}

                if resp.status == 204:
                    return {'success': True, 'data': None}

                content_type = resp.headers.get('Content-Type', '')
                if resp.content_length == 0:
                    body = {}
                elif 'application/json' in content_type:
                    body = await resp.json()
                else:
                    raw_text = await resp.text()
                    if resp.status == 401:
                        print(f"[T212-CLIENT] Authentication failed (401): {raw_text.strip()}")
                        return {'success': False, 'error': 'Invalid API key', 'status': 401}
                    body = {'message': raw_text.strip()}

                if resp.status >= 400:
                    error_msg = body.get('message', '') if isinstance(body, dict) else str(body)
                    print(f"[T212-CLIENT] API error {resp.status}: {error_msg} ({method} {path})")
                    return {'success': False, 'error': error_msg, 'status': resp.status}

                return {'success': True, 'data': body}

        except asyncio.TimeoutError:
            print(f"[T212-CLIENT] Timeout on {method} {path}")
            return {'success': False, 'error': 'timeout'}
        except aiohttp.ClientError as e:
            print(f"[T212-CLIENT] Connection error: {e}")
            return {'success': False, 'error': f'connection_error: {e}'}
        except Exception as e:
            print(f"[T212-CLIENT] Unexpected error: {e}")
            return {'success': False, 'error': str(e)}

    async def get(self, path: str, params: dict = None) -> Dict[str, Any]:
        return await self._request('GET', path, params=params)

    async def post(self, path: str, json_data: dict = None) -> Dict[str, Any]:
        return await self._request('POST', path, json_data=json_data)

    async def delete(self, path: str) -> Dict[str, Any]:
        return await self._request('DELETE', path)

    @property
    def is_soft_throttled(self) -> bool:
        return self._throttle_detector.is_throttled

    async def get_account_summary(self) -> Dict[str, Any]:
        return await self.get('/equity/account/cash')

    async def get_portfolio(self) -> Dict[str, Any]:
        return await self.get('/equity/portfolio')

    async def get_orders(self) -> Dict[str, Any]:
        return await self.get('/equity/orders')

    async def place_market_order(self, ticker: str, quantity: float) -> Dict[str, Any]:
        return await self.post('/equity/orders/market', {
            'ticker': ticker,
            'quantity': quantity,
        })

    async def place_limit_order(self, ticker: str, quantity: float, limit_price: float, time_validity: str = 'DAY') -> Dict[str, Any]:
        return await self.post('/equity/orders/limit', {
            'ticker': ticker,
            'quantity': quantity,
            'limitPrice': limit_price,
            'timeValidity': time_validity,
        })

    async def cancel_order(self, order_id: int) -> Dict[str, Any]:
        return await self.delete(f'/equity/orders/{order_id}')

    async def get_instruments(self) -> Dict[str, Any]:
        return await self.get('/equity/metadata/instruments')

    async def get_order_history(self, cursor: int = None, limit: int = 50) -> Dict[str, Any]:
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        return await self.get('/equity/history/orders', params=params)

    async def get_account_metadata(self) -> Dict[str, Any]:
        return await self.get('/equity/account/info')


class DuplicateOrderGuard:
    def __init__(self, ttl_seconds: int = 10):
        self._ttl = ttl_seconds
        self._fingerprints: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _make_fingerprint(self, broker: str, channel: str, action: str, symbol: str, quantity: float) -> str:
        bucket = int(time.time() / 5)
        raw = f"{broker}|{channel}|{action}|{symbol}|{quantity}|{bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    async def check_and_mark(self, broker: str, channel: str, action: str, symbol: str, quantity: float) -> bool:
        fp = self._make_fingerprint(broker, channel, action, symbol, quantity)
        async with self._lock:
            now = time.time()
            expired = [k for k, v in self._fingerprints.items() if now - v > self._ttl]
            for k in expired:
                del self._fingerprints[k]

            if fp in self._fingerprints:
                print(f"[DUPLICATE-GUARD] Blocked duplicate order: {broker} {action} {symbol} x{quantity}")
                return True

            self._fingerprints[fp] = now
            return False


_duplicate_guard = None

def get_duplicate_guard() -> DuplicateOrderGuard:
    global _duplicate_guard
    if _duplicate_guard is None:
        _duplicate_guard = DuplicateOrderGuard()
    return _duplicate_guard
