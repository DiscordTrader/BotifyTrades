import json
import logging
from typing import Optional
from urllib.parse import urlparse

import httpx

from .auth import WebullAuth
from .config import WebullConfig
from .exceptions import WebullAPIError, WebullAuthError, WebullOrderError
from .rate_limiter import RateLimiter

log = logging.getLogger("webull_official")


class WebullClient:
    def __init__(self, config: WebullConfig):
        self._config = config
        self._auth = WebullAuth(config.app_key, config.app_secret)
        self._rate_limiter = RateLimiter()
        self._http: Optional[httpx.AsyncClient] = None

    async def start(self):
        self._http = httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None

    async def get(self, path: str, params: dict = None) -> dict:
        await self._rate_limiter.acquire(path)
        host = urlparse(self._config.base_url).hostname
        headers = self._auth.sign_request("GET", path, host, query_params=params)

        resp = await self._http.get(path, params=params, headers=headers)
        return self._handle_response(resp, path)

    async def post(self, path: str, body: dict = None) -> dict:
        await self._rate_limiter.acquire(path)
        host = urlparse(self._config.base_url).hostname
        headers = self._auth.sign_request("POST", path, host, body=body)

        raw_body = json.dumps(body, separators=(",", ":")) if body else None
        resp = await self._http.post(path, content=raw_body, headers=headers)
        return self._handle_response(resp, path)

    def _handle_response(self, resp: httpx.Response, path: str) -> dict:
        if resp.status_code == 200:
            if not resp.content:
                return {}
            return resp.json()

        try:
            error_data = resp.json()
        except Exception:
            error_data = {"error_code": "UNKNOWN", "message": resp.text}

        error_code = error_data.get("error_code", "UNKNOWN")
        message = error_data.get("message", "")

        if resp.status_code == 401:
            raise WebullAuthError(resp.status_code, error_code, message)

        if "order" in path:
            raise WebullOrderError(resp.status_code, error_code, message)

        raise WebullAPIError(resp.status_code, error_code, message)
