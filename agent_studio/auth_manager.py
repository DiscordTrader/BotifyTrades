"""
Authentication manager — supports Anthropic OAuth (Pro subscription) and API key.
OAuth is the recommended method; API key is the optional fallback.
"""
import os
import json
import hashlib
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from .config import AgentConfig


class AuthManager:
    AUTH_METHOD_OAUTH = "oauth"
    AUTH_METHOD_API_KEY = "api_key"

    OAUTH_AUTHORIZE_URL = "https://console.anthropic.com/oauth/authorize"
    OAUTH_TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"

    def __init__(self, db=None):
        self._db = db
        self._lock = threading.Lock()
        self._cached_client = None
        self._cached_method = None
        self._oauth_states = {}

    def set_db(self, db):
        self._db = db

    def get_auth_method(self) -> str:
        settings = self._load_settings()
        return settings.get("method", self.AUTH_METHOD_OAUTH)

    def get_auth_status(self) -> dict:
        settings = self._load_settings()
        method = settings.get("method", self.AUTH_METHOD_OAUTH)

        if method == self.AUTH_METHOD_API_KEY:
            has_key = bool(settings.get("api_key")) or bool(os.environ.get(AgentConfig.ANTHROPIC_API_KEY_ENV))
            return {
                "method": "api_key",
                "configured": has_key,
                "display": "API Key" + (" (env var)" if os.environ.get(AgentConfig.ANTHROPIC_API_KEY_ENV) else " (saved)") if has_key else "API Key (not set)",
            }

        has_token = bool(settings.get("oauth_access_token"))
        expired = False
        if has_token and settings.get("oauth_expires_at"):
            expired = time.time() > settings["oauth_expires_at"]

        return {
            "method": "oauth",
            "configured": has_token and not expired,
            "has_refresh_token": bool(settings.get("oauth_refresh_token")),
            "expired": expired,
            "display": "Anthropic Pro (OAuth)" if has_token and not expired else "OAuth (not connected)",
        }

    def get_client(self):
        import anthropic

        settings = self._load_settings()
        method = settings.get("method", self.AUTH_METHOD_OAUTH)

        if method == self.AUTH_METHOD_API_KEY:
            api_key = settings.get("api_key") or os.environ.get(AgentConfig.ANTHROPIC_API_KEY_ENV, "")
            if not api_key:
                raise ValueError(
                    "No API key configured. Set ANTHROPIC_API_KEY in .env or enter one in Settings."
                )
            return anthropic.Anthropic(api_key=api_key)

        access_token = settings.get("oauth_access_token")
        if not access_token:
            raise ValueError(
                "OAuth not connected. Click 'Connect with Anthropic' in the dashboard settings."
            )

        if settings.get("oauth_expires_at") and time.time() > settings["oauth_expires_at"]:
            refresh_token = settings.get("oauth_refresh_token")
            if refresh_token:
                new_tokens = self._refresh_oauth_token(refresh_token, settings)
                if new_tokens:
                    access_token = new_tokens["access_token"]
                else:
                    raise ValueError("OAuth token expired and refresh failed. Please reconnect.")
            else:
                raise ValueError("OAuth token expired. Please reconnect.")

        return anthropic.Anthropic(
            api_key=access_token,
            default_headers={"Authorization": f"Bearer {access_token}"},
        )

    # ── Auth Method Configuration ──

    def set_auth_method(self, method: str) -> dict:
        if method not in (self.AUTH_METHOD_OAUTH, self.AUTH_METHOD_API_KEY):
            return {"success": False, "error": f"Invalid method: {method}"}

        settings = self._load_settings()
        settings["method"] = method
        self._save_settings(settings)
        self._cached_client = None
        return {"success": True, "method": method}

    def set_api_key(self, api_key: str) -> dict:
        if not api_key or len(api_key) < 10:
            return {"success": False, "error": "Invalid API key"}

        settings = self._load_settings()
        settings["method"] = self.AUTH_METHOD_API_KEY
        settings["api_key"] = api_key
        self._save_settings(settings)
        self._cached_client = None

        try:
            client = self.get_client()
            return {"success": True, "method": "api_key"}
        except Exception as e:
            return {"success": True, "method": "api_key", "warning": "Key saved but not validated"}

    def clear_api_key(self):
        settings = self._load_settings()
        settings.pop("api_key", None)
        self._save_settings(settings)
        self._cached_client = None

    # ── OAuth Flow ──

    def start_oauth_flow(self, redirect_uri: str) -> dict:
        settings = self._load_settings()
        client_id = settings.get("oauth_client_id") or os.environ.get("ANTHROPIC_OAUTH_CLIENT_ID", "")

        if not client_id:
            return {
                "success": False,
                "error": "OAuth client ID not configured. Set ANTHROPIC_OAUTH_CLIENT_ID or enter it in Settings.",
            }

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = hashlib.sha256(code_verifier.encode()).hexdigest()

        with self._lock:
            self._oauth_states[state] = {
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
                "created_at": time.time(),
            }

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "messages:create",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        from urllib.parse import urlencode
        auth_url = f"{self.OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

        return {"success": True, "auth_url": auth_url, "state": state}

    def handle_oauth_callback(self, code: str, state: str) -> dict:
        with self._lock:
            state_data = self._oauth_states.pop(state, None)

        if not state_data:
            return {"success": False, "error": "Invalid or expired OAuth state"}

        if time.time() - state_data["created_at"] > 600:
            return {"success": False, "error": "OAuth state expired (10 min limit)"}

        settings = self._load_settings()
        client_id = settings.get("oauth_client_id") or os.environ.get("ANTHROPIC_OAUTH_CLIENT_ID", "")
        client_secret = settings.get("oauth_client_secret") or os.environ.get("ANTHROPIC_OAUTH_CLIENT_SECRET", "")

        token_data = self._exchange_code(
            code=code,
            redirect_uri=state_data["redirect_uri"],
            client_id=client_id,
            client_secret=client_secret,
            code_verifier=state_data["code_verifier"],
        )

        if not token_data.get("access_token"):
            return {"success": False, "error": token_data.get("error", "Token exchange failed")}

        settings["method"] = self.AUTH_METHOD_OAUTH
        settings["oauth_access_token"] = token_data["access_token"]
        settings["oauth_refresh_token"] = token_data.get("refresh_token", "")
        settings["oauth_expires_at"] = time.time() + token_data.get("expires_in", 3600)
        settings["oauth_connected_at"] = datetime.now(timezone.utc).isoformat()
        self._save_settings(settings)
        self._cached_client = None

        return {"success": True, "method": "oauth"}

    def disconnect_oauth(self):
        settings = self._load_settings()
        settings.pop("oauth_access_token", None)
        settings.pop("oauth_refresh_token", None)
        settings.pop("oauth_expires_at", None)
        settings.pop("oauth_connected_at", None)
        self._save_settings(settings)
        self._cached_client = None

    def set_oauth_credentials(self, client_id: str, client_secret: str = "") -> dict:
        settings = self._load_settings()
        settings["oauth_client_id"] = client_id
        if client_secret:
            settings["oauth_client_secret"] = client_secret
        self._save_settings(settings)
        return {"success": True}

    # ── Token Exchange & Refresh ──

    def _exchange_code(self, code: str, redirect_uri: str,
                       client_id: str, client_secret: str,
                       code_verifier: str) -> dict:
        import urllib.request
        import urllib.parse

        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }).encode()

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if client_secret:
            import base64
            creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"

        try:
            req = urllib.request.Request(self.OAUTH_TOKEN_URL, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"error": str(e)}

    def _refresh_oauth_token(self, refresh_token: str, settings: dict) -> Optional[dict]:
        import urllib.request
        import urllib.parse

        client_id = settings.get("oauth_client_id") or os.environ.get("ANTHROPIC_OAUTH_CLIENT_ID", "")
        client_secret = settings.get("oauth_client_secret") or os.environ.get("ANTHROPIC_OAUTH_CLIENT_SECRET", "")

        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }).encode()

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if client_secret:
            import base64
            creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"

        try:
            req = urllib.request.Request(self.OAUTH_TOKEN_URL, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                token_data = json.loads(resp.read().decode())

            if token_data.get("access_token"):
                settings["oauth_access_token"] = token_data["access_token"]
                if token_data.get("refresh_token"):
                    settings["oauth_refresh_token"] = token_data["refresh_token"]
                settings["oauth_expires_at"] = time.time() + token_data.get("expires_in", 3600)
                self._save_settings(settings)
                self._cached_client = None
                return token_data
        except Exception:
            pass
        return None

    # ── Persistence ──

    def _load_settings(self) -> dict:
        if not self._db:
            return {}
        return self._db.get_auth_settings()

    def _save_settings(self, settings: dict):
        if self._db:
            self._db.save_auth_settings(settings)
