import json
import logging
import asyncio
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from .auth import WebullAuth
from .config import WebullConfig
from .exceptions import WebullAPIError, WebullAuthError, WebullOrderError
from .rate_limiter import RateLimiter

log = logging.getLogger("webull_official")

TOKEN_APPROVAL_TIMEOUT = 120
TOKEN_POLL_INTERVAL = 5


class WebullClient:
    def __init__(self, config: WebullConfig, token_file: Path = None):
        self._config = config
        self._auth = WebullAuth(config.app_key, config.app_secret)
        self._rate_limiter = RateLimiter()
        self._http: Optional[httpx.AsyncClient] = None
        self._access_token: Optional[str] = None
        self._token_file = token_file or Path("webull_official_token.json")

    def set_access_token(self, token: str):
        self._access_token = token

    def get_access_token(self) -> Optional[str]:
        return self._access_token

    def _token_headers(self, signed: dict) -> dict:
        if self._access_token:
            signed["x-access-token"] = self._access_token
        return signed

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
        headers = self._token_headers(self._auth.sign_request("GET", path, host, query_params=params))
        resp = await self._http.get(path, params=params, headers=headers)
        return self._handle_response(resp, path)

    async def post(self, path: str, body: dict = None) -> dict:
        await self._rate_limiter.acquire(path)
        host = urlparse(self._config.base_url).hostname
        headers = self._token_headers(self._auth.sign_request("POST", path, host, body=body))
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

    # ── Token management ──────────────────────────────────────────────────────

    def load_saved_token(self) -> Optional[str]:
        """Load previously approved token from file."""
        try:
            if self._token_file.exists():
                data = json.loads(self._token_file.read_text())
                return data.get("token")
        except Exception:
            pass
        return None

    def save_token(self, token: str):
        try:
            self._token_file.parent.mkdir(parents=True, exist_ok=True)
            self._token_file.write_text(json.dumps({"token": token}))
        except Exception as e:
            log.warning("Failed to save token: %s", e)

    def clear_saved_token(self):
        try:
            if self._token_file.exists():
                self._token_file.unlink()
        except Exception:
            pass

    async def init_token(self) -> bool:
        """
        Initialize x-access-token required by Webull API.
        1. Try saved token → check if still NORMAL
        2. Try refresh of saved token
        3. Create new token → poll for user approval in Webull app (up to 120s)
        Returns True if token is ready, raises on failure.
        """
        saved = self.load_saved_token()

        if saved:
            status = await self._check_token(saved)
            if status == "NORMAL":
                self._access_token = saved
                log.info("[TOKEN] Reused saved token (NORMAL)")
                return True
            # Try refresh
            try:
                refreshed = await self._refresh_token(saved)
                if refreshed:
                    self._access_token = refreshed
                    self.save_token(refreshed)
                    log.info("[TOKEN] Token refreshed successfully")
                    return True
            except Exception:
                pass
            self.clear_saved_token()

        # Create new token — requires Webull app approval
        pending_token = await self._create_token(None)
        print("[WEBULL_OFFICIAL] 📱 Token approval required — open Webull mobile app and approve the login request")
        print(f"[WEBULL_OFFICIAL] Polling for approval (up to {TOKEN_APPROVAL_TIMEOUT}s)...")

        elapsed = 0
        while elapsed < TOKEN_APPROVAL_TIMEOUT:
            await asyncio.sleep(TOKEN_POLL_INTERVAL)
            elapsed += TOKEN_POLL_INTERVAL
            status = await self._check_token(pending_token)
            print(f"[WEBULL_OFFICIAL] Token status: {status} ({elapsed}s/{TOKEN_APPROVAL_TIMEOUT}s)")
            if status == "NORMAL":
                self._access_token = pending_token
                self.save_token(pending_token)
                print("[WEBULL_OFFICIAL] ✅ Token approved and saved")
                return True
            if status in ("INVALID", "EXPIRED"):
                raise RuntimeError(f"Token {status} — please retry")

        raise RuntimeError(
            f"Token approval timed out after {TOKEN_APPROVAL_TIMEOUT}s. "
            "Check your Webull mobile app for the approval notification and click Connect again."
        )

    async def _create_token(self, existing_token: Optional[str]) -> str:
        body = {}
        if existing_token:
            body["token"] = existing_token
        resp = await self.post("/openapi/auth/token/create", body or None)
        token = resp.get("token") if isinstance(resp, dict) else None
        if not token:
            raise RuntimeError(f"Token creation failed: {resp}")
        return token

    async def _check_token(self, token: str) -> str:
        try:
            resp = await self.post("/openapi/auth/token/check", {"token": token})
            return (resp.get("status") or "UNKNOWN") if isinstance(resp, dict) else "UNKNOWN"
        except Exception:
            return "UNKNOWN"

    async def _refresh_token(self, token: str) -> Optional[str]:
        resp = await self.post("/openapi/auth/token/refresh", {"token": token})
        return resp.get("token") if isinstance(resp, dict) else None
