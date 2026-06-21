import asyncio
import time
from collections import defaultdict


class RateLimiter:
    """Per-category rate limiter for Webull Official API.

    WO-7 fix: Uses per-category locks so that sleeping on account_data (2/2s)
    never blocks concurrent order placement (600/60s).
    """

    LIMITS = {
        "order": (600, 60),
        "account_data": (2, 2),
        "token": (10, 30),
        "account_list": (10, 30),
        "subscribe": (600, 60),
        "quote": (120, 60),
    }

    ENDPOINT_CATEGORY = {
        "/openapi/trade/order/place": "order",
        "/openapi/trade/order/cancel": "order",
        "/openapi/trade/order/replace": "order",
        "/openapi/trade/order/batch-place": "order",
        "/openapi/trade/order/preview": "order",
        "/openapi/assets/balance": "account_data",
        "/openapi/assets/positions": "account_data",
        "/openapi/trade/order/history": "account_data",
        "/openapi/trade/order/open": "account_data",
        "/openapi/trade/order/detail": "account_data",
        "/openapi/account/list": "account_list",
        "/openapi/auth/token/create": "token",
        "/openapi/auth/token/check": "token",
        "/openapi/auth/token/refresh": "token",
        "/openapi/market-data/streaming/subscribe": "subscribe",
        "/openapi/market-data/streaming/unsubscribe": "subscribe",
        "/openapi/quote/option/query": "quote",
    }

    def __init__(self):
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, category: str) -> asyncio.Lock:
        if category not in self._locks:
            self._locks[category] = asyncio.Lock()
        return self._locks[category]

    async def acquire(self, path: str):
        category = self.ENDPOINT_CATEGORY.get(path)
        if not category:
            return

        max_requests, window_seconds = self.LIMITS[category]
        lock = self._get_lock(category)

        async with lock:
            now = time.monotonic()
            timestamps = self._timestamps[category]

            timestamps[:] = [t for t in timestamps if now - t < window_seconds]

            if len(timestamps) >= max_requests:
                wait_time = timestamps[0] + window_seconds - now
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    now = time.monotonic()
                    timestamps[:] = [t for t in timestamps if now - t < window_seconds]

            timestamps.append(time.monotonic())
