import asyncio
import time
from collections import defaultdict
from typing import Optional


class RateLimiter:
    LIMITS = {
        "order": (600, 60),
        "account_data": (2, 2),
        "token": (10, 30),
        "account_list": (10, 30),
        "subscribe": (600, 60),
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
        "/openapi/market-data/streaming/subscribe": "subscribe",
        "/openapi/market-data/streaming/unsubscribe": "subscribe",
    }

    def __init__(self):
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._lock: Optional[asyncio.Lock] = None

    async def acquire(self, path: str):
        category = self.ENDPOINT_CATEGORY.get(path)
        if not category:
            return
        if self._lock is None:
            self._lock = asyncio.Lock()

        max_requests, window_seconds = self.LIMITS[category]

        async with self._lock:
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
