"""
Charles Schwab Broker Implementation
OAuth2 authentication with official Schwab API
"""

import os
import sys
import json
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory


class SchwabBroker(BrokerInterface):
    """Charles Schwab broker implementation using official OAuth2 API"""
    
    BASE_URL = "https://api.schwabapi.com/trader/v1"
    AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
    TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "SCHWAB"
        self.client = None
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        self.account_hash = None
        self.account_number = None
        self.dry_run = config.get('dry_run', False)
        self._token_refresh_lock = None
        self._token_refresh_failures = 0
        self._token_refresh_backoff_until = 0
        self._token_auth_dead = False
        
        self.client_id = config.get('client_id', '')
        self.client_secret = config.get('client_secret', '')
        self.redirect_uri = config.get('redirect_uri', 'https://127.0.0.1')
        self.token_file = config.get('token_file', 'schwab_token.json')
        
        self._api_rate_lock = None
        self._last_api_call = 0
        self._min_api_interval = 0.5
        self._http_client = None
        self._http_client_loop_id = None
        self._token_refresh_lock_loop_id = None
        self._last_valid_positions = []
        self._last_valid_positions_time = 0
        self._position_cache_ttl = 60
        self._consecutive_zero_positions = 0
        self._position_cache_invalidated = False
        self._last_fetch_had_error = False
        
        self._global_429_until = 0
        self._consecutive_429s = 0
        self._last_successful_call = 0

        self._streaming_client = None
        self._data_hub = None
        self._api_calls_this_minute = 0
        self._api_calls_minute_start = 0
        self._API_BUDGET_LIMIT = 120
        self._API_BUDGET_THROTTLE = 96
        self._API_BUDGET_CRITICAL = 108

    def _get_token_refresh_lock(self):
        try:
            current_loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            current_loop_id = None
        if self._token_refresh_lock is None or self._token_refresh_lock_loop_id != current_loop_id:
            self._token_refresh_lock = asyncio.Lock()
            self._token_refresh_lock_loop_id = current_loop_id
        return self._token_refresh_lock

    async def connect(self) -> bool:
        """Connect to Schwab using stored tokens"""
        try:
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._event_loop = None
            self._init_data_hub()

            if not self.client_id or not self.client_secret:
                print(f"[{self.name}] ❌ Missing Client ID or Client Secret")
                return False
            
            if self._load_tokens():
                if await self._verify_connection():
                    self.connected = True
                    print(f"[{self.name}] ✓ Connected successfully using stored tokens")
                    return True
                else:
                    if await self._refresh_access_token():
                        if await self._verify_connection():
                            self.connected = True
                            print(f"[{self.name}] ✓ Connected after token refresh")
                            return True
            
            print(f"[{self.name}] ⚠️  Not authenticated. Please use 'Re-authenticate with Schwab' button in Settings.")
            return False
            
        except Exception as e:
            print(f"[{self.name}] ❌ Connection error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _init_data_hub(self):
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            self._data_hub = get_schwab_data_hub()
        except Exception as e:
            print(f"[{self.name}] Data hub init skipped: {e}")

    def start_streaming(self, loop=None):
        try:
            if self._streaming_client:
                return
            self._init_data_hub()
            from src.services.schwab_streaming_client import SchwabStreamingClient
            self._streaming_client = SchwabStreamingClient(self)
            self._streaming_client.start(loop=loop)
            print(f"[{self.name}] ✓ WebSocket streaming started")
        except Exception as e:
            print(f"[{self.name}] Streaming start failed (will use REST fallback): {e}")

    def stop_streaming(self):
        if self._streaming_client:
            self._streaming_client.stop()
            self._streaming_client = None

    async def subscribe_position_symbols(self, positions: list):
        if not self._streaming_client or not self._streaming_client.is_connected():
            return
        equity_symbols = []
        option_symbols = []
        for pos in positions:
            symbol = pos.get('symbol', '') if isinstance(pos, dict) else str(pos)
            asset_type = pos.get('assetType', pos.get('asset', 'EQUITY')) if isinstance(pos, dict) else 'EQUITY'
            if asset_type in ('OPTION', 'option') or len(symbol) > 10:
                option_symbols.append(symbol)
            else:
                equity_symbols.append(symbol)

        streaming_loop = getattr(self._streaming_client, '_loop', None)
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if streaming_loop and current_loop and streaming_loop is not current_loop:
            if streaming_loop.is_closed():
                return
            async def _subscribe():
                if equity_symbols:
                    await self._streaming_client.subscribe_equities(equity_symbols)
                if option_symbols:
                    await self._streaming_client.subscribe_options(option_symbols)
            try:
                fut = asyncio.run_coroutine_threadsafe(_subscribe(), streaming_loop)
                fut.add_done_callback(lambda f: print(f"[{self.name}] ⚠️ Cross-loop subscription error: {f.exception()}") if f.exception() else None)
            except RuntimeError:
                pass
        else:
            if equity_symbols:
                await self._streaming_client.subscribe_equities(equity_symbols)
            if option_symbols:
                await self._streaming_client.subscribe_options(option_symbols)

    async def _safe_stream_subscribe(self, symbols: list, asset_type: str = 'equity'):
        if not self._streaming_client or not self._streaming_client.is_connected():
            return
        streaming_loop = getattr(self._streaming_client, '_loop', None)
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        sub_fn = self._streaming_client.subscribe_options if asset_type == 'option' else self._streaming_client.subscribe_equities
        if streaming_loop and current_loop and streaming_loop is not current_loop:
            if streaming_loop.is_closed():
                return
            try:
                asyncio.run_coroutine_threadsafe(sub_fn(symbols), streaming_loop)
            except RuntimeError:
                pass
        else:
            await sub_fn(symbols)

    def get_hub_quote(self, symbol: str) -> Optional[float]:
        if self._data_hub:
            price = self._data_hub.get_quote_price(symbol)
            if price and price > 0:
                return price
        return None

    def get_hub_quote_detailed(self, symbol: str, max_age: Optional[float] = None) -> Optional[Dict[str, Any]]:
        if self._data_hub:
            return self._data_hub.get_quote_detailed(symbol, max_age=max_age)
        return None

    def _track_api_call(self) -> bool:
        now = time.time()
        if now - self._api_calls_minute_start >= 60:
            self._api_calls_this_minute = 0
            self._api_calls_minute_start = now
        self._api_calls_this_minute += 1
        return self._api_calls_this_minute <= self._API_BUDGET_LIMIT

    def _get_api_usage(self) -> int:
        now = time.time()
        if now - self._api_calls_minute_start >= 60:
            return 0
        return self._api_calls_this_minute

    def _should_throttle_non_critical(self) -> bool:
        usage = self._get_api_usage()
        return usage >= self._API_BUDGET_THROTTLE

    def _should_block_non_order(self) -> bool:
        usage = self._get_api_usage()
        return usage >= self._API_BUDGET_CRITICAL
    
    def _load_tokens(self) -> bool:
        """Load tokens from file, using token manager if available"""
        try:
            # Try to use the centralized token manager first (handles auto-refresh)
            try:
                from gui_app.schwab_auth import get_token_manager
                token_manager = get_token_manager()
                access_token = token_manager.get_access_token()
                if access_token:
                    self.access_token = access_token
                    self.refresh_token = token_manager.get_refresh_token()
                    if token_manager._token_data:
                        self.token_expiry = token_manager._token_data.get('token_expiry')
                    token_manager.start_auto_refresh()
                    print(f"[{self.name}] Tokens loaded via token manager (auto-refresh enabled)")
                    return True
            except (ImportError, Exception) as e:
                # Token manager not available or error - fallback to file
                if not isinstance(e, ImportError):
                    print(f"[{self.name}] Token manager unavailable: {e}, using file fallback")
            
            # Fallback: load directly from file
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.access_token = data.get('access_token')
                    self.refresh_token = data.get('refresh_token')
                    self.token_expiry = data.get('token_expiry')
                    return bool(self.access_token)
        except Exception as e:
            print(f"[{self.name}] Error loading tokens: {e}")
        return False
    
    def _save_tokens(self):
        """Save tokens to file and sync with token manager"""
        try:
            data = {
                'access_token': self.access_token,
                'refresh_token': self.refresh_token,
                'token_expiry': self.token_expiry
            }
            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump(data, f)
            try:
                from gui_app.schwab_auth import get_token_manager
                tm = get_token_manager()
                expires_in = int(self.token_expiry - datetime.now().timestamp()) if self.token_expiry else 1800
                tm.save_tokens(self.access_token, self.refresh_token, max(expires_in, 60))
            except Exception:
                pass
            print(f"[{self.name}] Tokens saved to {self.token_file}")
        except Exception as e:
            print(f"[{self.name}] Error saving tokens: {e}")
    
    def get_auth_url(self) -> str:
        """Generate OAuth authorization URL for user login"""
        import urllib.parse
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri
        }
        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"
    
    async def exchange_code_for_tokens(self, auth_code: str) -> bool:
        """Exchange authorization code for access/refresh tokens"""
        try:
            import httpx
            import base64
            
            credentials = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            
            headers = {
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'authorization_code',
                'code': auth_code,
                'redirect_uri': self.redirect_uri
            }
            
            async def _async_exchange(h, d, url):
                async with httpx.AsyncClient(timeout=15.0) as c:
                    return await c.post(url, headers=h, data=d)
            
            response = await asyncio.wait_for(
                _async_exchange(headers, data, self.TOKEN_URL),
                timeout=20.0
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get('access_token')
                self.refresh_token = token_data.get('refresh_token')
                expires_in = token_data.get('expires_in', 1800)
                self.token_expiry = (datetime.now().timestamp() + expires_in)
                self._save_tokens()
                print(f"[{self.name}] ✓ Tokens obtained successfully")
                return True
            else:
                print(f"[{self.name}] ❌ Token exchange failed: {response.status_code}")
                print(f"[{self.name}] Response: {response.text}")
                return False
                    
        except Exception as e:
            print(f"[{self.name}] ❌ Error exchanging code: {e}")
            return False
    
    async def _refresh_access_token(self) -> bool:
        """Refresh the access token using refresh token with exponential backoff"""
        try:
            if self._token_auth_dead:
                return False
            
            now = datetime.now().timestamp()
            if now < self._token_refresh_backoff_until:
                return False
            
            if not self.refresh_token:
                print(f"[{self.name}] No refresh token available")
                return False
            
            import httpx
            import base64
            
            credentials = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            
            headers = {
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token,
                'client_id': self.client_id
            }
            
            async def _async_token_post(h, d, token_url):
                async with httpx.AsyncClient(timeout=15.0) as c:
                    return await c.post(token_url, headers=h, data=d)
            
            response = await asyncio.wait_for(
                _async_token_post(headers, data, self.TOKEN_URL),
                timeout=20.0
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data.get('access_token')
                if token_data.get('refresh_token'):
                    self.refresh_token = token_data.get('refresh_token')
                expires_in = token_data.get('expires_in', 1800)
                self.token_expiry = (datetime.now().timestamp() + expires_in)
                self._save_tokens()
                self._token_refresh_failures = 0
                self._token_refresh_backoff_until = 0
                self._token_auth_dead = False
                print(f"[{self.name}] ✓ Access token refreshed (expires in {expires_in}s)")
                return True
            elif response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', '30'))
                print(f"[{self.name}] Token refresh rate limited, waiting {retry_after}s...")
                await asyncio.sleep(retry_after)
                response = await asyncio.wait_for(
                    _async_token_post(headers, data, self.TOKEN_URL),
                    timeout=20.0
                )
                if response.status_code == 200:
                    token_data = response.json()
                    self.access_token = token_data.get('access_token')
                    if token_data.get('refresh_token'):
                        self.refresh_token = token_data.get('refresh_token')
                    expires_in = token_data.get('expires_in', 1800)
                    self.token_expiry = (datetime.now().timestamp() + expires_in)
                    self._save_tokens()
                    self._token_refresh_failures = 0
                    self._token_refresh_backoff_until = 0
                    print(f"[{self.name}] ✓ Access token refreshed after rate limit wait")
                    return True
                self._apply_token_backoff()
                print(f"[{self.name}] ❌ Token refresh failed after rate limit: {response.status_code}")
                return False
            elif response.status_code == 400:
                error_text = response.text
                if 'invalid_grant' in error_text or 'refresh_token_authentication_error' in error_text or 'unsupported_token_type' in error_text:
                    self._token_auth_dead = True
                    self.connected = False
                    print(f"[{self.name}] ❌ Refresh token expired or revoked. Re-authentication required via Settings → Brokers. (Token refresh suspended until re-auth)")
                else:
                    self._apply_token_backoff()
                    if self._token_refresh_failures <= 3:
                        print(f"[{self.name}] ❌ Token refresh failed: {response.status_code} - {error_text}")
                    else:
                        backoff_remaining = int(self._token_refresh_backoff_until - datetime.now().timestamp())
                        print(f"[{self.name}] ❌ Token refresh still failing (attempt {self._token_refresh_failures}). Next retry in {backoff_remaining}s. Re-authenticate via Settings.")
                return False
            else:
                self._apply_token_backoff()
                print(f"[{self.name}] ❌ Token refresh failed: {response.status_code}")
                return False
                    
        except Exception as e:
            self._apply_token_backoff()
            print(f"[{self.name}] ❌ Error refreshing token: {e}")
            return False
    
    def _apply_token_backoff(self):
        """Apply exponential backoff after token refresh failure"""
        self._token_refresh_failures += 1
        backoff = min(300, 15 * (2 ** min(self._token_refresh_failures - 1, 5)))
        self._token_refresh_backoff_until = datetime.now().timestamp() + backoff
    
    def reset_token_auth(self):
        """Reset token auth state after re-authentication (call from auth flow)"""
        self._token_auth_dead = False
        self._token_refresh_failures = 0
        self._token_refresh_backoff_until = 0
    
    async def _verify_connection(self) -> bool:
        """Verify connection by fetching account info"""
        try:
            import httpx
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            async def _async_verify(url, h):
                async with httpx.AsyncClient(timeout=15.0) as c:
                    return await c.get(url, headers=h)
            
            response = await asyncio.wait_for(
                _async_verify(f"{self.BASE_URL}/accounts/accountNumbers", headers),
                timeout=20.0
            )
            
            if response.status_code == 200:
                accounts = response.json()
                if accounts:
                    self.account_hash = accounts[0].get('hashValue')
                    self.account_number = accounts[0].get('accountNumber')
                    print(f"[{self.name}] Account: {self.account_number}")
                    return True
            elif response.status_code == 401:
                print(f"[{self.name}] Token expired, needs refresh")
                return False
            else:
                print(f"[{self.name}] Verification failed: {response.status_code}")
                return False
                    
        except Exception as e:
            print(f"[{self.name}] ❌ Verification error: {e}")
            return False
    
    def _parse_occ_symbol(self, occ_symbol: str) -> Optional[Dict[str, Any]]:
        """Parse OCC option symbol format into components.
        
        OCC format: UNDERLYING + YYMMDD + C/P + STRIKE*1000 (8 digits, zero-padded)
        Example: "QQQ   260128P00630000" -> QQQ, 2026-01-28, P, 630.00
        """
        import re
        
        if not occ_symbol:
            return None
        
        occ_symbol = occ_symbol.strip()
        
        pattern = r'^([A-Z]+)\s*(\d{6})([CP])(\d{8})$'
        match = re.match(pattern, occ_symbol)
        
        if match:
            underlying = match.group(1)
            date_str = match.group(2)
            option_type = match.group(3)
            strike_raw = match.group(4)
            
            year = int('20' + date_str[:2])
            month = int(date_str[2:4])
            day = int(date_str[4:6])
            expiry = f"{year:04d}-{month:02d}-{day:02d}"
            
            strike = int(strike_raw) / 1000.0
            
            return {
                'underlying': underlying,
                'expiry': expiry,
                'option_type': option_type,
                'strike': strike
            }
        
        return None
    
    async def _ensure_valid_token(self) -> bool:
        """Ensure we have a valid access token with thread-safe refresh"""
        if not self.access_token:
            return False
        if self.token_expiry and datetime.now().timestamp() >= (self.token_expiry - 120):
            async with self._get_token_refresh_lock():
                if self.token_expiry and datetime.now().timestamp() >= (self.token_expiry - 120):
                    return await self._refresh_access_token()
        return True

    @staticmethod
    def _round_to_cboe_increment(price: float, is_sell: bool = False, is_stop_trigger: bool = False) -> float:
        """Round option price to valid CBOE penny increment.
        
        CBOE rules:
        - Options priced UNDER $3.00: $0.05 increments (e.g. 1.45, 1.50, 1.55)
        - Options priced AT/OVER $3.00: $0.10 increments (e.g. 3.10, 3.20, 3.30)
        
        For limit prices:
          - Sell orders: round DOWN to improve fill probability
          - Buy orders: round UP to improve fill probability
        For stop trigger prices (protective direction):
          - Sell-stop (protecting long): round UP so stop triggers sooner
          - Buy-stop (protecting short): round DOWN so stop triggers sooner
        """
        import math
        if price <= 0:
            return 0.05
        
        if price < 3.00:
            increment = 0.05
        else:
            increment = 0.10
        
        ticks = round(price / increment, 8)
        
        if is_stop_trigger:
            if is_sell:
                rounded = math.ceil(ticks) * increment
            else:
                rounded = math.floor(ticks) * increment
        else:
            if is_sell:
                rounded = math.floor(ticks) * increment
            else:
                rounded = math.ceil(ticks) * increment
        
        rounded = round(rounded, 2)
        if rounded <= 0:
            rounded = increment
        return rounded

    def _format_price(self, price: float) -> str:
        """Format price for Schwab API.
        Sub-$1 (OTC/penny): 4-decimal sub-penny allowed by SEC Rule 612.
        $1+: penny increments only — round to nearest cent (not floor).
        """
        import math
        if price < 1.0:
            truncated = math.floor(price * 10000) / 10000
            return f"{truncated:.4f}"
        else:
            return f"{round(price, 2):.2f}"

    def _create_http_client(self):
        """Create a fresh httpx AsyncClient."""
        import httpx
        return httpx.AsyncClient(
            timeout=8.0, http2=False,
            limits=httpx.Limits(max_connections=15, max_keepalive_connections=8)
        )

    async def _reset_http_client(self, reason: str = ""):
        """Close and recreate the HTTP client to recover from pool exhaustion."""
        import httpx
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
        self._http_client = self._create_http_client()
        try:
            self._http_client_loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            self._http_client_loop_id = None
        if not hasattr(self, '_pool_reset_count'):
            self._pool_reset_count = 0
        self._pool_reset_count += 1
        print(f"[{self.name}] 🔄 HTTP client reset #{self._pool_reset_count}: {reason}")

    async def _make_request(self, method, url, is_exit_order: bool = False, is_entry_order: bool = False, **kwargs):
        """Make HTTP request with rate limit, budget tracking, and token refresh handling"""
        import httpx
        short_url = url.split('/')[-1] if '/' in url else url
        if not is_exit_order and not is_entry_order:
            if self._should_block_non_order():
                print(f"[{self.name}] ⚠️ API budget critical ({self._get_api_usage()}/{self._API_BUDGET_LIMIT}/min) - blocking non-order call")
                return type('BudgetBlockedResponse', (), {'status_code': 503, 'text': 'Budget exceeded', 'json': lambda: {}, 'headers': {}, '_budget_blocked': True})()

        self._track_api_call()
        await self._async_rate_limit(is_exit_order=is_exit_order, is_entry_order=is_entry_order)

        headers = kwargs.pop('headers', {})
        if 'Authorization' not in headers:
            headers['Authorization'] = f'Bearer {self.access_token}'
        if 'Accept' not in headers:
            headers['Accept'] = 'application/json'

        try:
            current_loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            current_loop_id = None
        needs_new_client = (
            self._http_client is None
            or self._http_client.is_closed
            or self._http_client_loop_id != current_loop_id
        )
        if needs_new_client:
            if self._http_client is not None and not self._http_client.is_closed:
                try:
                    await self._http_client.aclose()
                except Exception:
                    pass
            self._http_client = self._create_http_client()
            self._http_client_loop_id = current_loop_id

        try:
            response = await asyncio.wait_for(
                self._http_client.request(method, url, headers=headers, **kwargs),
                timeout=10.0
            )
        except (httpx.PoolTimeout, httpx.ConnectTimeout, httpx.ReadTimeout) as pool_err:
            await self._reset_http_client(f"{type(pool_err).__name__} on {method} {short_url}")
            response = await asyncio.wait_for(
                self._http_client.request(method, url, headers=headers, **kwargs),
                timeout=10.0
            )
        except (asyncio.TimeoutError, TimeoutError) as timeout_err:
            await self._reset_http_client(f"TimeoutError on {method} {short_url}")
            raise

        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', '60'))
            self._register_429(retry_after)
            
            if is_exit_order:
                wait = min(retry_after, 10)
                print(f"[{self.name}] EXIT ORDER 429 - short wait {wait}s then retry")
                await asyncio.sleep(wait)
            elif is_entry_order:
                wait = min(retry_after, 15)
                print(f"[{self.name}] BUY ORDER 429 - waiting {wait}s then retry")
                await asyncio.sleep(wait)
            else:
                await asyncio.sleep(min(retry_after, 30))
            
            await self._ensure_valid_token()
            headers['Authorization'] = f'Bearer {self.access_token}'
            response = await asyncio.wait_for(
                self._http_client.request(method, url, headers=headers, **kwargs),
                timeout=20.0
            )
            
            if response.status_code == 429:
                self._register_429(retry_after)
                return response
            else:
                self._register_success()

        elif response.status_code == 401:
            async with self._get_token_refresh_lock():
                refreshed = await self._refresh_access_token()
            if refreshed:
                headers['Authorization'] = f'Bearer {self.access_token}'
                response = await asyncio.wait_for(
                    self._http_client.request(method, url, headers=headers, **kwargs),
                    timeout=20.0
                )
        
        elif response.status_code in [200, 201, 202]:
            self._register_success()

        return response
    
    def _get_session_type(self) -> str:
        """Get order session type based on extended hours setting and current market state.
        
        Schwab session types:
        - NORMAL: Regular market hours only (9:30 AM - 4:00 PM ET)
        - SEAMLESS: Extended hours (pre-market + regular + after-hours)
        
        Policy: 
        1. If user explicitly enabled extended hours → SEAMLESS
        2. If currently outside regular market hours → SEAMLESS (auto-detect)
        3. Otherwise → NORMAL
        
        Returns:
            Session type string for order payload
        """
        try:
            from gui_app.database import get_broker_extended_hours
            if get_broker_extended_hours('schwab'):
                return "SEAMLESS"
        except ImportError:
            pass
        except Exception as e:
            print(f"[{self.name}] Error checking extended hours setting: {e}")
        
        if not self._is_regular_market_hours():
            return "SEAMLESS"
        
        return "NORMAL"

    def _is_regular_market_hours(self) -> bool:
        """Check if current time is within regular US market hours (9:30 AM - 4:00 PM ET)."""
        try:
            from datetime import datetime
            import pytz
            et = pytz.timezone('US/Eastern')
            now = datetime.now(et)
            if now.weekday() >= 5:
                return False
            market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
            market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
            return market_open <= now <= market_close
        except Exception:
            return True

    def _get_duration(self, duration_hint: Optional[str] = None, is_exit: bool = False, is_near_expiry: bool = False) -> str:
        """Get order duration/time-in-force.
        
        Schwab duration types:
        - DAY: Day order (default)
        - GOOD_TILL_CANCEL: GTC
        - FILL_OR_KILL: FOK - fill entire order immediately or cancel
        - IMMEDIATE_OR_CANCEL: IOC - fill what you can immediately, cancel rest
        
        Args:
            duration_hint: Explicit duration override (DAY, GOOD_TILL_CANCEL, FILL_OR_KILL, IMMEDIATE_OR_CANCEL)
            is_exit: Whether this is an exit/sell order (defaults to GTC)
            is_near_expiry: Whether option is expiring today (forces DAY)
        """
        valid_durations = {"DAY", "GOOD_TILL_CANCEL", "FILL_OR_KILL", "IMMEDIATE_OR_CANCEL"}
        if duration_hint and duration_hint.upper() in valid_durations:
            return duration_hint.upper()
        if is_near_expiry:
            return "DAY"
        if is_exit:
            return "GOOD_TILL_CANCEL"
        return "DAY"
    
    async def disconnect(self):
        """Disconnect from Schwab"""
        self.connected = False
        self.access_token = None
        print(f"[{self.name}] Disconnected")
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information including settled cash for good faith violation prevention"""
        try:
            if self._data_hub:
                cached = self._data_hub.get_account_info()
                if cached is not None:
                    return dict(cached)

            if self._should_skip_non_critical():
                if hasattr(self, '_last_account_info') and self._last_account_info:
                    return dict(self._last_account_info)
            
            if not await self._ensure_valid_token():
                if hasattr(self, '_last_account_info') and self._last_account_info:
                    print(f"[{self.name}] Token refresh pending - returning last known good account info")
                    return dict(self._last_account_info)
                return None
            
            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}",
                params={'fields': 'positions'}
            )
            
            if response.status_code == 200:
                data = response.json()
                account = data.get('securitiesAccount', {})
                balances = account.get('currentBalances', {})
                
                print(f"[{self.name}] Raw currentBalances keys: {list(balances.keys())}")
                
                raw_buying_power = float(balances.get('buyingPower', 0))
                cash_balance = float(balances.get('cashBalance', 0))
                portfolio_value = float(balances.get('liquidationValue', 0))
                
                cash_available_for_trading = float(balances.get('cashAvailableForTrading', 0))
                available_funds = float(balances.get('availableFunds', 0))
                available_funds_non_margin = float(balances.get('availableFundsNonMarginableTrade', 0))
                option_buying_power = float(balances.get('optionBuyingPower', 0))
                buying_power_non_margin = float(balances.get('buyingPowerNonMarginableTrade', 0))
                
                buying_power = raw_buying_power
                if buying_power <= 0:
                    for fallback_name, fallback_val in [
                        ('availableFunds', available_funds),
                        ('cashAvailableForTrading', cash_available_for_trading),
                        ('availableFundsNonMarginableTrade', available_funds_non_margin),
                        ('buyingPowerNonMarginableTrade', buying_power_non_margin),
                        ('optionBuyingPower', option_buying_power),
                    ]:
                        if fallback_val > 0:
                            print(f"[{self.name}] buyingPower=0, using fallback '{fallback_name}'=${fallback_val:.2f}")
                            buying_power = fallback_val
                            break
                
                if option_buying_power <= 0:
                    option_buying_power = buying_power
                
                if cash_available_for_trading > 0:
                    settled_cash = cash_available_for_trading
                elif available_funds > 0:
                    settled_cash = available_funds
                elif available_funds_non_margin > 0:
                    settled_cash = available_funds_non_margin
                else:
                    settled_cash = min(buying_power, cash_balance) if buying_power > 0 else cash_balance
                
                unsettled_cash = max(0, cash_balance - settled_cash)
                
                print(f"[{self.name}] Account: BP=${buying_power:.2f}, Cash=${cash_balance:.2f}, Settled=${settled_cash:.2f}, Unsettled=${unsettled_cash:.2f}, OptionsBP=${option_buying_power:.2f}")
                
                result = {
                    'buying_power': buying_power,
                    'cash': cash_balance,
                    'cash_balance': cash_balance,
                    'portfolio_value': portfolio_value,
                    'settled_cash': settled_cash,
                    'unsettled_cash': unsettled_cash,
                    'cashAvailableForTrading': cash_available_for_trading,
                    'availableFunds': available_funds,
                    'options_buying_power': option_buying_power,
                    'account_type': account.get('type', 'UNKNOWN'),
                    'account_id': self.account_number or ''
                }
                self._last_account_info = result
                if self._data_hub:
                    self._data_hub.update_account_info(result)
                return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {type(e).__name__}: {e}")
            if hasattr(self, '_last_account_info') and self._last_account_info:
                print(f"[{self.name}] Returning last known good account info (BP=${self._last_account_info.get('buying_power', 0):.2f})")
                return dict(self._last_account_info)
        
        return None
    
    def _register_429(self, retry_after: int = 60):
        """Register a 429 error - sets global backoff for ALL Schwab API calls"""
        self._consecutive_429s += 1
        backoff = min(retry_after * (1 + 0.5 * (self._consecutive_429s - 1)), 180)
        self._global_429_until = time.time() + backoff
        print(f"[{self.name}] ⚠️ GLOBAL 429 BACKOFF: {backoff:.0f}s (consecutive: {self._consecutive_429s})")
    
    def _register_success(self):
        """Register a successful API call - resets 429 counter"""
        self._consecutive_429s = 0
        self._last_successful_call = time.time()
    
    def _is_in_429_backoff(self) -> float:
        """Check if we're in global 429 backoff. Returns seconds remaining, 0 if clear."""
        remaining = self._global_429_until - time.time()
        return max(0, remaining)
    
    def _rate_limit(self):
        """Enforce minimum interval between Schwab API calls to prevent 429 errors (sync version)"""
        now = time.time()
        elapsed = now - self._last_api_call
        if elapsed < self._min_api_interval:
            self._last_api_call = now + self._min_api_interval
        else:
            self._last_api_call = now
    
    async def _async_rate_limit(self, is_exit_order: bool = False, is_entry_order: bool = False):
        """Non-blocking rate limit for async contexts with global 429 awareness"""
        backoff_remaining = self._is_in_429_backoff()
        if backoff_remaining > 0:
            if is_exit_order:
                reduced_wait = min(backoff_remaining, 5.0)
                print(f"[{self.name}] 🔴 EXIT ORDER waiting {reduced_wait:.0f}s (429 backoff, {backoff_remaining:.0f}s remaining)")
                await asyncio.sleep(reduced_wait)
            elif is_entry_order:
                capped_wait = min(backoff_remaining, 15.0)
                print(f"[{self.name}] ⏳ BUY ORDER waiting {capped_wait:.0f}s (429 backoff, {backoff_remaining:.0f}s remaining)")
                await asyncio.sleep(capped_wait)
            else:
                print(f"[{self.name}] Rate limited (global 429 backoff), waiting {backoff_remaining:.0f}s...")
                await asyncio.sleep(backoff_remaining)
        
        now = time.time()
        wait_time = self._min_api_interval - (now - self._last_api_call)
        self._last_api_call = max(now, self._last_api_call + self._min_api_interval)
        if wait_time > 0:
            await asyncio.sleep(wait_time)
    
    def _should_skip_non_critical(self) -> bool:
        """Check if non-critical API calls should be skipped due to heavy rate limiting"""
        return self._is_in_429_backoff() > 30
    
    async def get_positions(self) -> Dict[str, Any]:
        """Get current positions. Uses hub cache when available to reduce API calls."""
        try:
            if self._should_skip_non_critical() or self._should_throttle_non_critical():
                if self._data_hub:
                    cached = self._data_hub.get_positions(detailed=False)
                    if cached is not None:
                        return {p.get('symbol', ''): int(p.get('quantity', 0)) for p in cached if p.get('symbol')}
                if hasattr(self, '_last_positions_simple') and self._last_positions_simple:
                    return dict(self._last_positions_simple)
                if self._last_valid_positions:
                    return {p.get('symbol', ''): int(p.get('quantity', 0)) for p in self._last_valid_positions if p.get('symbol')}
            
            if not await self._ensure_valid_token():
                return {}
            
            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}",
                params={'fields': 'positions'}
            )
            
            if response.status_code in (429, 503) or getattr(response, '_budget_blocked', False):
                return {p.get('symbol', ''): int(p.get('quantity', 0)) for p in self._last_valid_positions if p.get('symbol')}
            
            if response.status_code == 200:
                data = response.json()
                account = data.get('securitiesAccount', {})
                positions = account.get('positions', [])
                
                result = {}
                for pos in positions:
                    symbol = pos.get('instrument', {}).get('symbol', '')
                    qty = pos.get('longQuantity', 0) - pos.get('shortQuantity', 0)
                    if symbol:
                        result[symbol] = int(qty)
                
                if len(result) > 0 or not self._last_valid_positions:
                    self._last_positions_simple = dict(result)
                elif len(result) == 0 and hasattr(self, '_last_positions_simple') and self._last_positions_simple:
                    if self._position_cache_invalidated or self._consecutive_zero_positions >= 2:
                        self._last_positions_simple = {}
                    elif (time.time() - self._last_valid_positions_time) < self._position_cache_ttl:
                        print(f"[{self.name}] ⚠️ get_positions returned 0 but cache exists - using cached")
                        return dict(self._last_positions_simple)
                return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {type(e).__name__}: {e}")
        
        if hasattr(self, '_last_positions_simple') and self._last_positions_simple:
            return dict(self._last_positions_simple)
        return {}
    
    def _stock_tick_below(self, price: float) -> float:
        import math
        if price < 1.0:
            return math.floor((price - 0.0001) * 10000) / 10000
        else:
            return math.floor((price - 0.01) * 100) / 100

    def _clamp_to_last_band(self, aggressive: float, last: float, price_for_log: float) -> float:
        if last <= 0:
            return aggressive
        if last < 1.0:
            floor = round(last * 0.98, 4)
        elif last < 5.0:
            floor = round(last * 0.97, 4)
        else:
            floor = round(last * 0.95, 2)
        if aggressive < floor:
            print(f"[{self.name}] 🛡️ Exit price ${aggressive:.4f} clamped up to ${floor:.4f} (last-trade band, last=${last:.4f})")
            return floor
        return aggressive

    def _parse_schwab_error(self, raw_text: str) -> str:
        """Extract human-readable error from Schwab API response body."""
        try:
            import json
            data = json.loads(raw_text)
            for key in ('message', 'error', 'errors', 'description'):
                val = data.get(key)
                if val:
                    if isinstance(val, list):
                        return '; '.join(str(v.get('message', v) if isinstance(v, dict) else v) for v in val)
                    return str(val)
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        return raw_text[:300] if raw_text else 'Unknown error'

    async def _get_aggressive_exit_price(self, symbol: str, asset_type: str = 'stock',
                                         strike: float = None, expiry: str = None,
                                         call_put: str = None) -> Optional[float]:
        """Get aggressive exit price for STC orders — near-touch limit for instant fill.
        
        Schwab rejects MARKET orders in SEAMLESS session and for OTC stocks.
        Uses bid (or 1 tick below bid) as limit, clamped to a last-trade band
        to avoid Schwab price-band rejections on low-priced stocks.
        """
        import math
        try:
            if asset_type == 'option' and strike and expiry and call_put:
                quote = await self.get_option_quote(symbol, strike, expiry, call_put, max_age=10)
                if quote:
                    bid = float(quote.get('bid', 0) or 0)
                    last = float(quote.get('last', 0) or 0)
                    if bid > 0:
                        aggressive = max(0.01, round(bid, 2))
                        aggressive = self._round_to_cboe_increment(aggressive, is_sell=True)
                        print(f"[{self.name}] 💰 Option exit: bid=${bid:.2f} → LIMIT ${aggressive:.2f}")
                        return aggressive
                    if last > 0:
                        aggressive = max(0.01, round(last * 0.95, 2))
                        aggressive = self._round_to_cboe_increment(aggressive, is_sell=True)
                        print(f"[{self.name}] 💰 Option exit: last=${last:.2f} → LIMIT ${aggressive:.2f}")
                        return aggressive
            else:
                hub_price = self.get_hub_quote(symbol)
                last_price = 0.0
                bid_price = 0.0
                if hub_price and hub_price > 0:
                    hub_detailed = self.get_hub_quote_detailed(symbol, max_age=10)
                    if hub_detailed:
                        bid_price = float(hub_detailed.get('bid', 0) or 0)
                        last_price = float(hub_detailed.get('last', 0) or hub_detailed.get('price', 0) or 0)

                    if bid_price > 0:
                        aggressive = self._stock_tick_below(bid_price)
                        aggressive = self._clamp_to_last_band(aggressive, last_price or hub_price, bid_price)
                        aggressive = max(0.0001, aggressive)
                        print(f"[{self.name}] 💰 Stock exit: bid=${bid_price:.4f} → near-touch LIMIT ${aggressive:.4f} (hub)")
                        return aggressive

                    aggressive = self._stock_tick_below(hub_price)
                    aggressive = self._clamp_to_last_band(aggressive, last_price or hub_price, hub_price)
                    aggressive = max(0.0001, aggressive)
                    print(f"[{self.name}] 💰 Stock exit: hub=${hub_price:.4f} → near-touch LIMIT ${aggressive:.4f}")
                    return aggressive
                
                try:
                    rest_price = await self.get_quote(symbol)
                    if rest_price and rest_price > 0:
                        aggressive = self._stock_tick_below(rest_price)
                        aggressive = self._clamp_to_last_band(aggressive, rest_price, rest_price)
                        aggressive = max(0.0001, aggressive)
                        print(f"[{self.name}] 💰 Stock exit: REST=${rest_price:.4f} → near-touch LIMIT ${aggressive:.4f}")
                        return aggressive
                except Exception as rest_err:
                    print(f"[{self.name}] ⚠️ REST quote for exit price failed: {rest_err}")
        except Exception as e:
            print(f"[{self.name}] ⚠️ Aggressive exit price lookup failed: {e}")
        return None

    async def _cancel_conflicting_sell_orders(self, symbol: str, asset_type: str = 'EQUITY', option_symbol: str = None):
        """Cancel any pending sell orders for a symbol before placing a new STC.
        
        When bracket orders (BUY + OCO SL/PT) are active, Schwab will reject
        a new sell order for the same position. This method walks into nested
        childOrderStrategies to find hidden OCO/TRIGGER children and cancels them.
        """
        try:
            if self.dry_run:
                return
            
            if not self.account_hash:
                return
            
            if not await self._ensure_valid_token():
                return
            
            from datetime import datetime, timedelta
            import asyncio
            to_date = datetime.now()
            from_date = to_date - timedelta(days=7)
            
            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                params={
                    'fromEnteredTime': from_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'toEnteredTime': to_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                }
            )
            
            if response.status_code != 200:
                return
            
            orders = response.json()
            cancelled_count = 0
            cancelled_ids = set()
            
            if asset_type == 'EQUITY':
                sell_instructions = {'SELL', 'SELL_SHORT'}
            else:
                sell_instructions = {'SELL_TO_CLOSE'}
            
            cancellable_statuses = {'WORKING', 'ACCEPTED', 'QUEUED', 'PENDING_ACTIVATION', 'AWAITING_PARENT_ORDER', 'AWAITING_CONDITION', 'AWAITING_STOP_CONDITION', 'PENDING_ACKNOWLEDGEMENT'}
            
            lookup_symbol = symbol.upper()
            if asset_type != 'EQUITY' and option_symbol:
                lookup_symbol = option_symbol.upper()
            
            for order in orders:
                all_matches = self._extract_orders_recursive(order, lookup_symbol)
                for match in all_matches:
                    match_status = match.get('status', '')
                    match_id = str(match.get('id', ''))
                    instruction = match.get('instruction', '')
                    
                    if match_status in cancellable_statuses and instruction in sell_instructions and match_id not in cancelled_ids:
                        qty = match.get('qty', 0)
                        strategy = match.get('strategy', 'SINGLE')
                        stop_price = match.get('stop_price', '')
                        limit_price = match.get('limit_price', '')
                        price_info = f"stop=${stop_price}" if stop_price else f"limit=${limit_price}" if limit_price else "MARKET"
                        print(f"[{self.name}] 🔄 Cancelling conflicting {strategy} {instruction} order {match_id} for {symbol} ({price_info}) — clearing for new STC")
                        
                        cancel_resp = await self._make_request(
                            'DELETE',
                            f"{self.BASE_URL}/accounts/{self.account_hash}/orders/{match_id}",
                            is_exit_order=True
                        )
                        
                        if cancel_resp.status_code in [200, 201, 202, 204]:
                            cancelled_ids.add(match_id)
                            cancelled_count += 1
                            print(f"[{self.name}] ✓ Cancelled bracket/OCO leg {match_id}")
                        else:
                            print(f"[{self.name}] ⚠️ Cancel failed for {match_id}: {cancel_resp.status_code} - {cancel_resp.text[:200]}")
            
            if cancelled_count > 0:
                if self._data_hub:
                    self._data_hub.invalidate_all()
                print(f"[{self.name}] ✓ Cleared {cancelled_count} conflicting sell order(s) for {symbol} — waiting 2s for Schwab to process")
                await asyncio.sleep(2.0)
                
        except asyncio.TimeoutError:
            print(f"[{self.name}] ⚠️ Timeout cancelling conflicting orders for {symbol} — will retry in pre-exit block")
        except Exception as e:
            print(f"[{self.name}] ⚠️ Error cancelling conflicting orders for {symbol}: {type(e).__name__}: {e}")

    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        **kwargs
    ) -> OrderResult:
        """Place a stock order"""
        try:
            if not await self._ensure_valid_token():
                return OrderResult(
                    success=False,
                    message="Not authenticated with Schwab",
                    symbol=symbol,
                    action=action
                )
            
            _skip_cancel = kwargs.get('_skip_cancel_check', False)
            if action.upper() in ("STC", "SELL") and not _skip_cancel:
                await self._cancel_conflicting_sell_orders(symbol, 'EQUITY')
            
            if action.upper() == "BTO":
                instruction = "BUY"
            elif action.upper() == "STC":
                instruction = "SELL"
            elif action.upper() == "SHORT":
                instruction = "SELL_SHORT"
            elif action.upper() == "COVER":
                instruction = "BUY_TO_COVER"
            else:
                instruction = "SELL" if "SELL" in action.upper() or "STC" in action.upper() else "BUY"
            
            session = self._get_session_type()
            is_exit = instruction in ("SELL", "BUY_TO_COVER")
            
            if not price and is_exit:
                aggressive_price = await self._get_aggressive_exit_price(symbol, 'stock')
                if aggressive_price and aggressive_price > 0:
                    price = aggressive_price
                    print(f"[{self.name}] 🎯 STC MARKET→aggressive LIMIT ${price:.4f} (session={session}, fills instantly at bid)")
                else:
                    if session == "NORMAL":
                        print(f"[{self.name}] 🎯 STC using true MARKET order (session=NORMAL, no quote available)")
                    else:
                        print(f"[{self.name}] ⚠️ STC MARKET in {session} session with no quote — may pend as PENDING_ACTIVATION")
            
            order_type = "LIMIT" if price else "MARKET"
            
            if order_type == "MARKET":
                duration = "DAY"
            elif is_exit:
                if session == "SEAMLESS":
                    duration = "DAY"
                else:
                    duration = "GOOD_TILL_CANCEL"
            elif session == "SEAMLESS":
                duration = "DAY"
            else:
                duration = "DAY"
            
            is_entry = instruction in ("BUY", "SELL_SHORT")
            if is_entry and price and price > 0:
                try:
                    acct = await self.get_account_info()
                    if acct:
                        bp = float(acct.get('buying_power', 0))
                        settled = float(acct.get('settled_cash', 0))
                        order_cost = quantity * price
                        effective_bp = min(bp, settled) if settled > 0 else bp
                        print(f"[{self.name}] [FUNDS] BP=${bp:.2f}, Settled=${settled:.2f}, Order cost=${order_cost:.2f}")
                        if effective_bp <= 0:
                            return OrderResult(
                                success=False,
                                message=f"No buying power available: BP=${bp:.2f}, Settled=${settled:.2f}",
                                symbol=symbol, action=action
                            )
                        if order_cost > effective_bp:
                            max_qty = int(effective_bp / price)
                            if max_qty > 0:
                                print(f"[{self.name}] [FUNDS] Insufficient funds for {quantity} shares — adjusting to {max_qty}")
                                quantity = max_qty
                            else:
                                return OrderResult(
                                    success=False,
                                    message=f"Insufficient buying power: have ${effective_bp:.2f}, need ${order_cost:.2f}",
                                    symbol=symbol, action=action
                                )
                except Exception as bp_err:
                    print(f"[{self.name}] [FUNDS] Warning: Could not check buying power: {bp_err}")

            print(f"[{self.name}] 📋 Stock order: {instruction} {quantity} {symbol} | type={order_type} | session={session} | duration={duration}" + (f" | price=${price:.4f}" if price else ""))

            order_payload = {
                "orderStrategyType": "SINGLE",
                "orderType": order_type,
                "session": session,
                "duration": duration,
                "orderLegCollection": [{
                    "instruction": instruction,
                    "quantity": quantity,
                    "instrument": {
                        "symbol": symbol,
                        "assetType": "EQUITY"
                    }
                }]
            }
            
            if price:
                order_payload["price"] = self._format_price(price)
            
            if self.dry_run:
                print(f"[{self.name}] DRY RUN - Would place order: {json.dumps(order_payload, indent=2)}")
                return OrderResult(
                    success=True,
                    order_id="DRY_RUN",
                    message=f"DRY RUN: {action} {quantity} {symbol} @ {'$' + str(price) if price else 'MARKET'}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            is_entry = instruction in ("BUY", "SELL_SHORT")
            response = await self._make_request(
                'POST',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                is_exit_order=is_exit,
                is_entry_order=is_entry,
                headers=headers,
                json=order_payload
            )
            
            if response.status_code in [200, 201, 202]:
                order_id = response.headers.get('Location', '').split('/')[-1]
                if self._data_hub:
                    self._data_hub.invalidate_all()
                if is_exit:
                    self._position_cache_invalidated = True
                    self._consecutive_zero_positions = 0
                
                if is_exit and order_id:
                    try:
                        await asyncio.sleep(1.5)
                        status_result = await self.get_order_status(order_id, is_critical=True)
                        if status_result and isinstance(status_result, dict):
                            schwab_status = str(status_result.get('status', '')).upper()
                            if schwab_status == 'REJECTED':
                                reject_reason = status_result.get('status_description', '') or status_result.get('statusDescription', 'unknown')
                                close_time = status_result.get('close_time', '') or status_result.get('closeTime', '')
                                print(f"[{self.name}] ❌ EXCHANGE REJECTED order {order_id}: {reject_reason} | closeTime={close_time}")
                                import json as _json
                                safe_keys = {k: v for k, v in status_result.items() if k not in ('orderLegCollection',)}
                                print(f"[{self.name}] 🔍 RAW ORDER RESPONSE: {_json.dumps(safe_keys, default=str)}")
                                for key in ('cancelledReason', 'statusDescription', 'tag', 'releaseTime'):
                                    val = status_result.get(key)
                                    if val:
                                        print(f"[{self.name}]   {key}: {val}")
                                legs = status_result.get('orderLegCollection', [])
                                for leg in legs:
                                    print(f"[{self.name}]   leg: {leg.get('instruction')} {leg.get('quantity')} {leg.get('instrument', {}).get('symbol')} assetType={leg.get('instrument', {}).get('assetType')}")

                                if not kwargs.get('_price_band_retry') and 'significantly higher or lower' in reject_reason.lower():
                                    print(f"[{self.name}] 🔄 PRICE BAND RETRY: Fetching fresh quote for {symbol}...")
                                    retry_price = None
                                    try:
                                        if is_exit:
                                            retry_price = await self._get_aggressive_exit_price(symbol, 'stock')
                                        else:
                                            fresh_quote = await self.get_quote(symbol)
                                            if fresh_quote and fresh_quote > 0:
                                                retry_price = round(fresh_quote * 1.005, 4) if instruction == "BUY" else round(fresh_quote * 0.995, 4)
                                    except Exception as rq_err:
                                        print(f"[{self.name}] ⚠️ Fresh quote failed: {rq_err}")

                                    if retry_price and retry_price > 0:
                                        print(f"[{self.name}] 🔄 PRICE BAND RETRY: old=${price:.4f} → new=${retry_price:.4f}")
                                        return await self.place_stock_order(
                                            symbol=symbol, action=action, quantity=quantity,
                                            price=retry_price, _price_band_retry=True,
                                            _skip_cancel_check=True, **{k: v for k, v in kwargs.items() if k not in ('_price_band_retry', '_skip_cancel_check')}
                                        )
                                    print(f"[{self.name}] ⚠️ Price band retry skipped — no fresh quote available")

                                return OrderResult(
                                    success=False,
                                    order_id=order_id,
                                    message=f"Exchange rejected: {reject_reason}",
                                    symbol=symbol,
                                    action=action
                                )
                            elif schwab_status == 'FILLED':
                                fill_price = status_result.get('price', price)
                                print(f"[{self.name}] ✅ Order {order_id} FILLED immediately @ ${fill_price}")
                    except Exception as verify_err:
                        print(f"[{self.name}] ⚠️ Post-order verify failed (non-critical): {verify_err}")
                
                if action.upper() == "BTO" and self._streaming_client:
                    try:
                        await self._safe_stream_subscribe([symbol], 'equity')
                        print(f"[{self.name}] ✓ Immediate stream subscribe: {symbol}")
                    except Exception:
                        pass
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    message=f"Order placed: {action} {quantity} {symbol}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                error_msg = response.text

                if not kwargs.get('_price_band_retry') and 'significantly higher or lower' in error_msg.lower():
                    print(f"[{self.name}] 🔄 STOCK PRICE BAND RETRY (HTTP {response.status_code}): Fetching fresh quote for {symbol}...")
                    retry_price = None
                    try:
                        if is_exit:
                            retry_price = await self._get_aggressive_exit_price(symbol, 'stock')
                        else:
                            fresh_quote = await self.get_quote(symbol)
                            if fresh_quote and fresh_quote > 0:
                                retry_price = round(fresh_quote * 1.005, 4) if instruction == "BUY" else round(fresh_quote * 0.995, 4)
                    except Exception as rq_err:
                        print(f"[{self.name}] ⚠️ Fresh quote failed: {rq_err}")
                    if retry_price and retry_price > 0:
                        print(f"[{self.name}] 🔄 STOCK PRICE BAND RETRY: old=${price:.4f} → new=${retry_price:.4f}")
                        return await self.place_stock_order(
                            symbol=symbol, action=action, quantity=quantity,
                            price=retry_price, _price_band_retry=True,
                            _skip_cancel_check=True, **{k: v for k, v in kwargs.items() if k not in ('_price_band_retry', '_skip_cancel_check')}
                        )

                return OrderResult(
                    success=False,
                    message=f"Schwab rejected (HTTP {response.status_code}): {self._parse_schwab_error(error_msg)}",
                    symbol=symbol,
                    action=action
                )
                    
        except Exception as e:
            err_detail = str(e) or type(e).__name__
            return OrderResult(
                success=False,
                message=f"Schwab error: {err_detail}",
                symbol=symbol,
                action=action
            )

    async def place_option_order(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        **kwargs
    ) -> OrderResult:
        """Place an options order"""
        try:
            if not await self._ensure_valid_token():
                return OrderResult(
                    success=False,
                    message="Not authenticated with Schwab",
                    symbol=symbol,
                    action=action
                )
            
            from src.core.expiry import normalize_expiry_iso
            try:
                expiry_formatted = normalize_expiry_iso(expiry)
            except ValueError:
                expiry_formatted = expiry
            
            call_put = "C" if option_type.upper().startswith("C") else "P"
            
            original_strike = strike
            strike = self._snap_index_strike(symbol, strike)
            
            option_symbol = self._build_option_symbol(symbol, expiry_formatted, strike, call_put)
            
            instruction = "BUY_TO_OPEN" if action.upper() == "BTO" else "SELL_TO_CLOSE"
            
            _fallback_price = kwargs.get('_signal_price_fallback')
            _skip_cancel = kwargs.get('_skip_cancel_check', False)
            is_stc = action.upper() in ('STC', 'SELL_TO_CLOSE')
            
            if is_stc and not _skip_cancel:
                await self._cancel_conflicting_sell_orders(symbol, 'OPTION', option_symbol=option_symbol)
            
            if not price:
                print(f"[{self.name}] ⚠️ Options require LIMIT orders on Schwab - no price provided, attempting mid-price lookup")
                try:
                    quote = await self.get_option_quote(symbol, strike, expiry_formatted, option_type, max_age=10)
                    if quote and quote.get('bid') and quote.get('ask'):
                        mid_price = round((quote['bid'] + quote['ask']) / 2, 2)
                        bid_price = quote['bid']
                        ask_price = quote['ask']
                        
                        if _fallback_price and _fallback_price > 0 and mid_price > _fallback_price * 5:
                            print(f"[{self.name}] ⚠️ SANITY CHECK FAILED: mid-price ${mid_price:.2f} is >5x fallback ${_fallback_price:.4f} — stale hub data?")
                            print(f"[{self.name}] Bypassing hub, fetching fresh REST quote...")
                            fresh_quote = None
                            try:
                                if await self._ensure_valid_token():
                                    option_sym_fresh = self._build_option_symbol(symbol, expiry_formatted, strike, call_put)
                                    resp = await self._make_request(
                                        'GET',
                                        f"https://api.schwabapi.com/marketdata/v1/quotes",
                                        params={'symbols': option_sym_fresh, 'indicative': 'false',
                                                'needExtendedHoursData': 'true', 'needPreviousClose': 'true'}
                                    )
                                    if resp.status_code == 200:
                                        data = resp.json()
                                        if option_sym_fresh in data:
                                            q = data[option_sym_fresh].get('quote', {})
                                            fresh_bid = float(q.get('bidPrice', 0) or 0)
                                            fresh_ask = float(q.get('askPrice', 0) or 0)
                                            if fresh_bid > 0 or fresh_ask > 0:
                                                fresh_quote = {'bid': fresh_bid, 'ask': fresh_ask}
                                                print(f"[{self.name}] ✓ Fresh REST quote: bid=${fresh_bid:.2f}, ask=${fresh_ask:.2f}")
                                            else:
                                                print(f"[{self.name}] ⚠️ REST quote returned zero bid/ask")
                            except Exception as rest_err:
                                print(f"[{self.name}] ⚠️ Fresh REST quote failed: {rest_err}")
                            
                            if fresh_quote and fresh_quote['bid'] > 0:
                                if is_stc:
                                    if _fallback_price and 0 < _fallback_price < fresh_quote['bid']:
                                        price = max(0.01, round(_fallback_price, 2))
                                        print(f"[{self.name}] ✓ STC using signal price ${price:.2f} (below fresh bid ${fresh_quote['bid']:.2f})")
                                    else:
                                        price = max(0.01, round(fresh_quote['bid'], 2))
                                        print(f"[{self.name}] ✓ STC at fresh bid: ${price:.2f}")
                                else:
                                    fresh_ask = fresh_quote['ask']
                                    if fresh_ask > 0:
                                        price = round(fresh_ask, 2)
                                        print(f"[{self.name}] ✓ BTO at fresh ask: ${price:.2f} (bid: ${fresh_quote['bid']:.2f}, mid: ${(fresh_quote['bid'] + fresh_ask) / 2:.2f})")
                                    else:
                                        price = round(fresh_quote['bid'] * 1.03, 2)
                                        print(f"[{self.name}] ✓ BTO fallback (ask=0): bid+3% ${price:.2f} (bid: ${fresh_quote['bid']:.2f})")
                            elif _fallback_price:
                                if is_stc:
                                    price = max(0.01, round(_fallback_price * 0.80, 2))
                                    print(f"[{self.name}] ✓ STC using fallback: ${_fallback_price:.4f} × 0.80 = ${price:.2f}")
                                else:
                                    price = round(_fallback_price * 1.03, 2)
                                    print(f"[{self.name}] ✓ BTO using fallback: ${_fallback_price:.4f} × 1.03 = ${price:.2f}")
                        elif is_stc:
                            if _fallback_price and 0 < _fallback_price < bid_price:
                                price = max(0.01, round(_fallback_price, 2))
                                print(f"[{self.name}] ✓ STC using signal price ${price:.2f} (below bid ${bid_price:.2f}) for quick fill")
                            else:
                                price = max(0.01, round(bid_price, 2))
                                print(f"[{self.name}] ✓ STC at bid: ${price:.2f} (mid was ${mid_price:.2f})")
                        else:
                            price = round(ask_price, 2)
                            print(f"[{self.name}] ✓ BTO at ask: ${price:.2f} (bid: ${bid_price:.2f}, mid: ${mid_price:.2f})")
                    elif quote and quote.get('last'):
                        price = quote['last']
                        print(f"[{self.name}] ✓ Using last price ${price:.2f}")
                    elif _fallback_price and _fallback_price > 0:
                        if is_stc:
                            price = max(0.01, round(_fallback_price * 0.80, 2))
                        else:
                            price = round(_fallback_price * 1.03, 2)
                        print(f"[{self.name}] ✓ No quote available, using fallback-based price ${price:.2f}")
                except Exception as quote_err:
                    print(f"[{self.name}] ⚠️ Quote lookup failed: {quote_err}")
                    if _fallback_price and _fallback_price > 0:
                        if is_stc:
                            price = max(0.01, round(_fallback_price * 0.80, 2))
                        else:
                            price = round(_fallback_price * 1.03, 2)
                        print(f"[{self.name}] ✓ Using fallback price after error: ${price:.2f}")
            
            if price and price > 0:
                is_sell = (instruction == "SELL_TO_CLOSE")
                original_price = price
                price = self._round_to_cboe_increment(price, is_sell=is_sell)
                if price != original_price:
                    print(f"[{self.name}] 📐 CBOE increment: ${original_price:.4f} → ${price:.2f} "
                          f"({'$0.05' if price < 3.00 else '$0.10'} increment, "
                          f"{'rounded down for sell' if is_sell else 'rounded up for buy'})")
            
            order_type = "LIMIT" if price else "MARKET"
            
            session = self._get_session_type()
            
            is_exit = (instruction == "SELL_TO_CLOSE")
            
            is_near_expiry = False
            try:
                expiry_date = datetime.strptime(expiry_formatted, "%Y-%m-%d").date()
                days_to_expiry = (expiry_date - datetime.now().date()).days
                is_near_expiry = days_to_expiry <= 0
            except Exception:
                pass
            
            if order_type == "MARKET" or is_near_expiry:
                duration = "DAY"
            elif is_exit:
                duration = "GOOD_TILL_CANCEL"
            else:
                duration = "DAY"
            
            if instruction == "BUY_TO_OPEN" and price and price > 0:
                try:
                    acct = await self.get_account_info()
                    if acct:
                        opt_bp = float(acct.get('options_buying_power', 0))
                        settled = float(acct.get('settled_cash', 0))
                        order_cost = quantity * price * 100
                        effective_bp = min(opt_bp, settled) if settled > 0 else opt_bp
                        print(f"[{self.name}] [FUNDS] Options BP=${opt_bp:.2f}, Settled=${settled:.2f}, Order cost=${order_cost:.2f} ({quantity}x${price:.2f}x100)")
                        if effective_bp <= 0:
                            return OrderResult(
                                success=False,
                                message=f"No options buying power available: BP=${opt_bp:.2f}, Settled=${settled:.2f}",
                                symbol=symbol, action=action
                            )
                        if order_cost > effective_bp:
                            max_qty = int(effective_bp / (price * 100))
                            if max_qty > 0:
                                print(f"[{self.name}] [FUNDS] Insufficient funds for {quantity} contracts — adjusting to {max_qty}")
                                quantity = max_qty
                            else:
                                return OrderResult(
                                    success=False,
                                    message=f"Insufficient options buying power: have ${effective_bp:.2f}, need ${order_cost:.2f}",
                                    symbol=symbol, action=action
                                )
                except Exception as bp_err:
                    print(f"[{self.name}] [FUNDS] Warning: Could not check options buying power: {bp_err}")

            order_payload = {
                "orderStrategyType": "SINGLE",
                "orderType": order_type,
                "session": session,
                "duration": duration,
                "orderLegCollection": [{
                    "instruction": instruction,
                    "quantity": quantity,
                    "instrument": {
                        "symbol": option_symbol,
                        "assetType": "OPTION"
                    }
                }]
            }
            
            if price:
                order_payload["price"] = self._format_price(price)
            
            if self.dry_run:
                print(f"[{self.name}] DRY RUN - Would place option order: {json.dumps(order_payload, indent=2)}")
                return OrderResult(
                    success=True,
                    order_id="DRY_RUN",
                    message=f"DRY RUN: {action} {quantity} {option_symbol} @ {'$' + str(price) if price else 'MARKET'}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            is_exit = (instruction == "SELL_TO_CLOSE")
            is_entry = (instruction == "BUY_TO_OPEN")
            response = await self._make_request(
                'POST',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                is_exit_order=is_exit,
                is_entry_order=is_entry,
                headers=headers,
                json=order_payload
            )
            
            if response.status_code in [200, 201, 202]:
                order_id = response.headers.get('Location', '').split('/')[-1]
                print(f"[{self.name}] ✅ Order accepted by Schwab (order_id={order_id})")
                if self._data_hub:
                    self._data_hub.invalidate_all()
                if is_exit:
                    self._position_cache_invalidated = True
                    self._consecutive_zero_positions = 0

                is_exit_opt = (instruction == "SELL_TO_CLOSE")
                if is_exit_opt and order_id:
                    try:
                        await asyncio.sleep(1.5)
                        status_result = await self.get_order_status(order_id, is_critical=True)
                        if status_result and isinstance(status_result, dict):
                            schwab_status = str(status_result.get('status', '')).upper()
                            if schwab_status == 'REJECTED':
                                reject_reason = status_result.get('status_description', '') or status_result.get('statusDescription', 'unknown')
                                print(f"[{self.name}] ❌ OPTION EXCHANGE REJECTED order {order_id}: {reject_reason}")

                                if not kwargs.get('_price_band_retry') and 'significantly higher or lower' in reject_reason.lower():
                                    print(f"[{self.name}] 🔄 OPTION PRICE BAND RETRY: Fetching fresh quote for {symbol} ${strike}{call_put} {expiry_formatted}...")
                                    retry_price = None
                                    try:
                                        retry_price = await self._get_aggressive_exit_price(
                                            symbol, 'option', strike=strike, expiry=expiry_formatted, call_put=option_type)
                                    except Exception as rq_err:
                                        print(f"[{self.name}] ⚠️ Fresh option quote failed: {rq_err}")

                                    if retry_price and retry_price > 0:
                                        print(f"[{self.name}] 🔄 OPTION PRICE BAND RETRY: old=${price:.2f} → new=${retry_price:.2f}")
                                        return await self.place_option_order(
                                            symbol=symbol, strike=strike, expiry=expiry,
                                            option_type=option_type, action=action, quantity=quantity,
                                            price=retry_price, _price_band_retry=True,
                                            _skip_cancel_check=True,
                                            **{k: v for k, v in kwargs.items() if k not in ('_price_band_retry', '_skip_cancel_check')}
                                        )
                                    print(f"[{self.name}] ⚠️ Option price band retry skipped — no fresh quote available")

                                return OrderResult(
                                    success=False,
                                    order_id=order_id,
                                    message=f"Exchange rejected: {reject_reason}",
                                    symbol=symbol,
                                    action=action
                                )
                            elif schwab_status == 'FILLED':
                                fill_price = status_result.get('price', price)
                                print(f"[{self.name}] ✅ Option order {order_id} FILLED immediately @ ${fill_price:.2f}")
                    except Exception as verify_err:
                        print(f"[{self.name}] ⚠️ Option post-order verify failed (non-critical): {verify_err}")

                if not is_exit_opt and order_id:
                    try:
                        await asyncio.sleep(1.5)
                        status_result = await self.get_order_status(order_id)
                        if status_result and isinstance(status_result, dict):
                            schwab_status = str(status_result.get('status', '')).upper()
                            if schwab_status == 'REJECTED':
                                reject_reason = status_result.get('status_description', '') or status_result.get('statusDescription', 'unknown')
                                print(f"[{self.name}] ❌ OPTION ENTRY REJECTED order {order_id}: {reject_reason}")

                                if not kwargs.get('_price_band_retry') and 'significantly higher or lower' in reject_reason.lower():
                                    print(f"[{self.name}] 🔄 OPTION ENTRY PRICE BAND RETRY: Fetching fresh quote...")
                                    retry_price = None
                                    try:
                                        quote = await self.get_option_quote(symbol, strike, expiry_formatted, option_type, max_age=5)
                                        if quote:
                                            ask = float(quote.get('ask', 0) or 0)
                                            mid = round((float(quote.get('bid', 0) or 0) + ask) / 2, 2) if ask > 0 else 0
                                            retry_price = mid if mid > 0 else ask
                                            if retry_price > 0:
                                                retry_price = self._round_to_cboe_increment(retry_price, is_sell=False)
                                    except Exception as rq_err:
                                        print(f"[{self.name}] ⚠️ Fresh option entry quote failed: {rq_err}")

                                    if retry_price and retry_price > 0:
                                        print(f"[{self.name}] 🔄 OPTION ENTRY PRICE BAND RETRY: old=${price:.2f} → new=${retry_price:.2f}")
                                        return await self.place_option_order(
                                            symbol=symbol, strike=strike, expiry=expiry,
                                            option_type=option_type, action=action, quantity=quantity,
                                            price=retry_price, _price_band_retry=True,
                                            _skip_cancel_check=True,
                                            **{k: v for k, v in kwargs.items() if k not in ('_price_band_retry', '_skip_cancel_check')}
                                        )
                                    print(f"[{self.name}] ⚠️ Option entry price band retry skipped — no fresh quote")

                                return OrderResult(
                                    success=False,
                                    order_id=order_id,
                                    message=f"Exchange rejected: {reject_reason}",
                                    symbol=symbol,
                                    action=action
                                )
                    except Exception as verify_err:
                        print(f"[{self.name}] ⚠️ Option entry verify failed (non-critical): {verify_err}")

                _pos_key = kwargs.get('position_key') or kwargs.get('_exit_marker_key')
                _verify_coro = self._background_verify_order(order_id, action, option_symbol, symbol, price, quantity, position_key=_pos_key)
                _scheduled = False
                try:
                    running_loop = asyncio.get_running_loop()
                    main_loop = getattr(self, '_event_loop', None)
                    if main_loop and main_loop is not running_loop and not main_loop.is_closed():
                        asyncio.run_coroutine_threadsafe(_verify_coro, main_loop)
                    else:
                        running_loop.create_task(_verify_coro)
                    _scheduled = True
                except RuntimeError:
                    main_loop = getattr(self, '_event_loop', None)
                    if main_loop and not main_loop.is_closed():
                        try:
                            asyncio.run_coroutine_threadsafe(_verify_coro, main_loop)
                            _scheduled = True
                        except Exception:
                            pass
                except Exception:
                    pass
                if not _scheduled:
                    _verify_coro.close()

                if action.upper() == "BTO" and self._streaming_client:
                    try:
                        await self._safe_stream_subscribe([option_symbol], 'option')
                        print(f"[{self.name}] ✓ Immediate stream subscribe: {option_symbol} (option)")
                    except Exception:
                        pass
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    message=f"Option order placed: {action} {quantity} {option_symbol} @ ${price:.2f}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                error_msg = response.text
                
                is_index = symbol.upper() in self._INDEX_OPTION_MAP or symbol.upper() in self._INDEX_STRIKE_INCREMENT
                is_entry = (instruction == "BUY_TO_OPEN")
                if 'Could not resolve instrument' in error_msg and is_index and is_entry:
                    increment = self._INDEX_STRIKE_INCREMENT.get(symbol.upper(), 5.0)
                    nearby_strikes = [
                        round(strike - increment, 2),
                        round(strike + increment, 2),
                    ]
                    if original_strike != strike:
                        nearby_strikes = [round(original_strike, 2)] + nearby_strikes
                    
                    for alt_strike in nearby_strikes:
                        alt_symbol = self._build_option_symbol(symbol, expiry_formatted, alt_strike, call_put)
                        print(f"[{self.name}] ⚠️ Strike ${strike} not found on Schwab, trying nearest ${alt_strike} ({alt_symbol})")
                        alt_payload = dict(order_payload)
                        alt_payload['orderLegCollection'] = [{
                            'instruction': instruction,
                            'quantity': quantity,
                            'instrument': {
                                'symbol': alt_symbol,
                                'assetType': 'OPTION'
                            }
                        }]
                        retry_resp = await self._make_request(
                            'POST',
                            f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                            is_exit_order=(instruction == "SELL_TO_CLOSE"),
                            is_entry_order=(instruction == "BUY_TO_OPEN"),
                            headers=headers,
                            json=alt_payload
                        )
                        if retry_resp.status_code in [200, 201, 202]:
                            order_id = retry_resp.headers.get('Location', '').split('/')[-1]
                            print(f"[{self.name}] ✅ Order accepted with alt strike ${alt_strike} (order_id={order_id})")
                            if self._data_hub:
                                self._data_hub.invalidate_all()
                            if instruction == "SELL_TO_CLOSE":
                                self._position_cache_invalidated = True
                                self._consecutive_zero_positions = 0
                            _pos_key = kwargs.get('position_key') or kwargs.get('_exit_marker_key')
                            _verify_coro2 = self._background_verify_order(order_id, action, alt_symbol, symbol, price, quantity, position_key=_pos_key)
                            _sched2 = False
                            try:
                                running_loop = asyncio.get_running_loop()
                                main_loop = getattr(self, '_event_loop', None)
                                if main_loop and main_loop is not running_loop and not main_loop.is_closed():
                                    asyncio.run_coroutine_threadsafe(_verify_coro2, main_loop)
                                else:
                                    running_loop.create_task(_verify_coro2)
                                _sched2 = True
                            except Exception:
                                main_loop = getattr(self, '_event_loop', None)
                                if main_loop and not main_loop.is_closed():
                                    try:
                                        asyncio.run_coroutine_threadsafe(_verify_coro2, main_loop)
                                        _sched2 = True
                                    except Exception:
                                        pass
                            if not _sched2:
                                _verify_coro2.close()
                            if action.upper() == "BTO" and self._streaming_client:
                                try:
                                    await self._safe_stream_subscribe([alt_symbol], 'option')
                                    print(f"[{self.name}] ✓ Immediate stream subscribe: {alt_symbol} (option, alt strike)")
                                except Exception:
                                    pass
                            return OrderResult(
                                success=True,
                                order_id=order_id,
                                message=f"Option order placed (alt strike ${alt_strike}): {action} {quantity} {alt_symbol} @ ${price:.2f}" if price else f"Option order placed (alt strike ${alt_strike}): {action} {quantity} {alt_symbol}",
                                price=price,
                                quantity=quantity,
                                symbol=symbol,
                                action=action
                            )
                    
                    print(f"[{self.name}] ❌ All nearby strikes also failed for {symbol}")

                if not kwargs.get('_price_band_retry') and 'significantly higher or lower' in error_msg.lower():
                    print(f"[{self.name}] 🔄 OPTION PRICE BAND RETRY (HTTP {response.status_code}): Fetching fresh quote...")
                    retry_price = None
                    is_exit_http = (instruction == "SELL_TO_CLOSE")
                    try:
                        if is_exit_http:
                            retry_price = await self._get_aggressive_exit_price(
                                symbol, 'option', strike=strike, expiry=expiry_formatted, call_put=option_type)
                        else:
                            quote = await self.get_option_quote(symbol, strike, expiry_formatted, option_type, max_age=5)
                            if quote:
                                ask = float(quote.get('ask', 0) or 0)
                                mid = round((float(quote.get('bid', 0) or 0) + ask) / 2, 2) if ask > 0 else 0
                                retry_price = mid if mid > 0 else ask
                                if retry_price > 0:
                                    retry_price = self._round_to_cboe_increment(retry_price, is_sell=is_exit_http)
                    except Exception as rq_err:
                        print(f"[{self.name}] ⚠️ Fresh option quote failed: {rq_err}")
                    if retry_price and retry_price > 0:
                        print(f"[{self.name}] 🔄 OPTION PRICE BAND RETRY: old=${price:.2f} → new=${retry_price:.2f}")
                        return await self.place_option_order(
                            symbol=symbol, strike=strike, expiry=expiry,
                            option_type=option_type, action=action, quantity=quantity,
                            price=retry_price, _price_band_retry=True,
                            _skip_cancel_check=True,
                            **{k: v for k, v in kwargs.items() if k not in ('_price_band_retry', '_skip_cancel_check')}
                        )

                return OrderResult(
                    success=False,
                    message=f"Schwab rejected (HTTP {response.status_code}): {self._parse_schwab_error(error_msg)}",
                    symbol=symbol,
                    action=action
                )
                    
        except Exception as e:
            return OrderResult(
                success=False,
                message=f"Schwab error: {str(e)}",
                symbol=symbol,
                action=action
            )
    
    async def _verify_order_fill(self, order_id: str, action: str, option_symbol: str, 
                                max_checks: int = 6, interval: float = 0.5) -> Dict[str, Any]:
        """Verify order fill status by polling Schwab order status API.
        
        Checks order status up to max_checks times with interval seconds between checks.
        Returns dict with 'status' key: 'filled', 'rejected', 'cancelled', 'expired', 'pending'
        """
        import asyncio as _aio
        
        for check_num in range(1, max_checks + 1):
            try:
                if self._is_in_429_backoff() > 0:
                    return {'status': 'pending', 'reason': '429 backoff active, deferring to sync service'}
                status_result = await self.get_order_status(order_id)
                if not status_result:
                    if check_num < max_checks:
                        await _aio.sleep(interval)
                        continue
                    print(f"[{self.name}] ⚠️ Could not retrieve order status after {max_checks} checks")
                    return {'status': 'pending', 'reason': 'Status check failed'}
                
                status = status_result.get('status', 'unknown')
                
                if status == 'filled':
                    return {
                        'status': 'filled',
                        'average_price': status_result.get('average_price', 0),
                        'filled_quantity': status_result.get('filled_quantity', 0)
                    }
                elif status == 'rejected':
                    desc = status_result.get('status_description', '')
                    reason_str = f'Exchange rejected order {order_id}'
                    if desc:
                        reason_str += f' ({desc})'
                    return {'status': 'rejected', 'reason': reason_str}
                elif status == 'cancelled':
                    desc = status_result.get('status_description', '')
                    cancel_time = status_result.get('cancel_time', '')
                    reason_str = f'Order {order_id} was cancelled'
                    if desc:
                        reason_str += f' ({desc})'
                    if cancel_time:
                        reason_str += f' at {cancel_time}'
                    return {'status': 'cancelled', 'reason': reason_str}
                elif status == 'expired':
                    desc = status_result.get('status_description', '')
                    reason_str = f'Order {order_id} expired'
                    if desc:
                        reason_str += f' ({desc})'
                    return {'status': 'expired', 'reason': reason_str}
                elif status == 'pending_activation':
                    return {'status': 'pending_activation', 'reason': f'Order parked in PENDING_ACTIVATION (waiting for regular market hours)'}
                elif status == 'pending':
                    if check_num < max_checks:
                        await _aio.sleep(interval)
                        continue
                    return {'status': 'pending', 'reason': f'Order still working after {max_checks * interval:.1f}s'}
                else:
                    if check_num < max_checks:
                        await _aio.sleep(interval)
                        continue
                    return {'status': status, 'reason': f'Unexpected status: {status}'}
                    
            except Exception as e:
                print(f"[{self.name}] ⚠️ Fill verification check {check_num} error: {e}")
                if check_num < max_checks:
                    await _aio.sleep(interval)
                    continue
                return {'status': 'pending', 'reason': f'Verification error: {e}'}
        
        return {'status': 'pending', 'reason': 'Verification exhausted'}

    async def _background_verify_order(self, order_id: str, action: str, option_symbol: str,
                                        symbol: str, price: float, quantity: int, position_key: str = None):
        """Background task: verify order fill status after placement.
        
        Runs asynchronously — does not block the caller. If order is rejected/cancelled/expired,
        logs the failure. The broker sync service will reconcile DB state on its next cycle.
        """
        await asyncio.sleep(2.0)

        if self._is_in_429_backoff() > 0:
            print(f"[{self.name}] ⏳ Background verify skipped — in 429 backoff, sync service will reconcile")
            return

        verified = await self._verify_order_fill(order_id, action, option_symbol, max_checks=3, interval=2.0)
        status = verified.get('status', 'pending')

        if status == 'filled':
            fill_price = verified.get('average_price', price)
            filled_qty = verified.get('filled_quantity', quantity)
            print(f"[{self.name}] ✅ Background verify: Order {order_id} FILLED {filled_qty}x @ ${fill_price:.2f}")
        elif status == 'pending_activation':
            print(f"[{self.name}] ⏳ Background verify: Order {order_id} PENDING_ACTIVATION — parked until regular market hours, chaser will handle")
        elif status in ('rejected', 'cancelled', 'expired'):
            reason = verified.get('reason', status)
            print(f"[{self.name}] ❌ Background verify: Order {order_id} {status.upper()}: {reason}")
            if action and action.upper() in ('STC', 'SELL_TO_CLOSE', 'SELL'):
                try:
                    from src.risk.position_monitor import risk_manager_instance
                    rm = risk_manager_instance
                    if rm and position_key and hasattr(rm, '_exit_executed_keys') and hasattr(rm, '_exit_executed_lock'):
                        with rm._exit_executed_lock:
                            rm._exit_executed_keys.discard(position_key)
                        if hasattr(rm, 'cache'):
                            rm.cache.record_exit_failure(position_key, f"Exchange {status}: {reason}", is_stop_loss=True)
                        print(f"[{self.name}] ✓ Cleared exit lock for {position_key} after exchange {status} — retry enabled")
                    elif rm and not position_key:
                        print(f"[{self.name}] ⚠️ Exchange {status} but no position_key available — order chaser will handle")
                    elif not rm:
                        print(f"[{self.name}] ⚠️ Exchange {status} but risk manager not available — order chaser will handle")
                except Exception as bg_err:
                    print(f"[{self.name}] ⚠️ Could not clear exit lock after {status}: {bg_err}")
            else:
                print(f"[{self.name}] ⚠️ Sync service will reconcile trade status on next cycle")
        else:
            print(f"[{self.name}] ⏳ Background verify: Order {order_id} still {status} — sync service will track")

    _INDEX_OPTION_MAP = {
        'SPX': 'SPXW',
        'NDX': 'NDXP',
        'RUT': 'RUTW',
        'DJX': 'DJXW',
    }

    _INDEX_OPTION_REVERSE_MAP = {v: k for k, v in _INDEX_OPTION_MAP.items()}

    _INDEX_STRIKE_INCREMENT = {
        'SPX': 5.0,
        'SPXW': 5.0,
        'NDX': 5.0,
        'NDXP': 5.0,
        'RUT': 5.0,
        'RUTW': 5.0,
        'DJX': 1.0,
        'DJXW': 1.0,
    }

    def _snap_index_strike(self, underlying: str, strike: float) -> float:
        key = underlying.upper()
        increment = self._INDEX_STRIKE_INCREMENT.get(key)
        if increment is None:
            mapped = self._INDEX_OPTION_MAP.get(key)
            if mapped:
                increment = self._INDEX_STRIKE_INCREMENT.get(mapped)
        if increment and increment >= 1:
            snapped = round(round(strike / increment) * increment, 2)
            if snapped != strike:
                print(f"[{self.name}] ⚠️ Index strike snap: {underlying} ${strike} → ${snapped} (nearest ${increment} increment)")
            return snapped
        return strike

    def _build_option_symbol(self, underlying: str, expiry: str, strike: float, call_put: str) -> str:
        """Build OCC option symbol format
        Format: SYMBOL (6 chars, left-padded) + YYMMDD + C/P + strike*1000 (8 digits)
        Example: AAPL  240119C00150000 = AAPL Jan 19 2024 $150 Call
        Note: Underlying symbol must be left-justified and space-padded to 6 characters
        """
        parts = expiry.split("-")
        if len(parts) == 3:
            year = parts[0][2:]
            month = parts[1]
            day = parts[2]
        else:
            return f"{underlying}_INVALID_EXPIRY"
        
        mapped = self._INDEX_OPTION_MAP.get(underlying.upper(), underlying)
        if mapped != underlying:
            print(f"[{self.name}] Index symbol mapped: {underlying} → {mapped}")
        underlying_padded = mapped.upper().ljust(6)
        
        strike_int = int(strike * 1000)
        strike_str = f"{strike_int:08d}"
        
        return f"{underlying_padded}{year}{month}{day}{call_put.upper()}{strike_str}"
    
    async def get_quote(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol. Tries streaming hub first, REST fallback."""
        try:
            hub_price = self.get_hub_quote(symbol)
            if hub_price is not None:
                return hub_price

            if self._should_skip_non_critical():
                return None
            
            if not await self._ensure_valid_token():
                return None
            
            response = await self._make_request(
                'GET',
                f"https://api.schwabapi.com/marketdata/v1/quotes",
                params={'symbols': symbol, 'indicative': 'false',
                        'needExtendedHoursData': 'true', 'needPreviousClose': 'true'}
            )
            
            if response.status_code == 200:
                data = response.json()
                if symbol in data:
                    quote = data[symbol].get('quote', {})
                    price = float(quote.get('lastPrice', 0))
                    if self._data_hub and price > 0:
                        self._data_hub.update_quote(symbol, {
                            'bid': float(quote.get('bidPrice', 0) or 0),
                            'ask': float(quote.get('askPrice', 0) or 0),
                            'last': price,
                            'volume': int(quote.get('totalVolume', 0) or 0),
                        }, source="rest")
                    return price
                        
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
        
        return None
    
    async def get_quote_detailed(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get detailed quote data for signal verification (bid, ask, last, volume). Tries hub first."""
        try:
            hub_data = self.get_hub_quote_detailed(symbol)
            if hub_data and hub_data.get('last', 0) > 0:
                return hub_data

            if self._should_skip_non_critical():
                return None
            
            if not await self._ensure_valid_token():
                return None
            
            response = await self._make_request(
                'GET',
                f"https://api.schwabapi.com/marketdata/v1/quotes",
                params={'symbols': symbol, 'indicative': 'false',
                        'needExtendedHoursData': 'true', 'needPreviousClose': 'true'}
            )
            
            if response.status_code == 200:
                data = response.json()
                if symbol in data:
                    quote = data[symbol].get('quote', {})
                    result = {
                        'bid': float(quote.get('bidPrice', 0) or 0),
                        'ask': float(quote.get('askPrice', 0) or 0),
                        'last': float(quote.get('lastPrice', 0) or 0),
                        'price': float(quote.get('lastPrice', 0) or 0),
                        'volume': int(quote.get('totalVolume', 0) or 0)
                    }
                    if self._data_hub and result['last'] > 0:
                        self._data_hub.update_quote(symbol, result, source="rest")
                    return result
                        
        except Exception as e:
            print(f"[{self.name}] Error getting detailed quote for {symbol}: {e}")
        
        return None
    
    async def get_option_quote(self, underlying: str, strike: float, expiry: str, opt_type: str, max_age: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Get option quote for signal verification. Tries hub first."""
        try:
            option_symbol = self._build_option_symbol(underlying, expiry, strike, opt_type[0])

            hub_data = self.get_hub_quote_detailed(option_symbol, max_age=max_age)
            if hub_data and hub_data.get('last', 0) > 0:
                return hub_data

            if not await self._ensure_valid_token():
                return None
            
            response = await self._make_request(
                'GET',
                f"https://api.schwabapi.com/marketdata/v1/quotes",
                params={'symbols': option_symbol, 'indicative': 'false',
                        'needExtendedHoursData': 'true', 'needPreviousClose': 'true'}
            )
            
            if response.status_code == 200:
                data = response.json()
                if option_symbol in data:
                    quote = data[option_symbol].get('quote', {})
                    result = {
                        'bid': float(quote.get('bidPrice', 0) or 0),
                        'ask': float(quote.get('askPrice', 0) or 0),
                        'last': float(quote.get('lastPrice', 0) or 0),
                        'price': float(quote.get('lastPrice', 0) or 0),
                        'volume': int(quote.get('totalVolume', 0) or 0),
                        'open_interest': int(quote.get('openInterest', 0) or 0),
                        'implied_volatility': float(quote.get('volatility', 0) or 0)
                    }
                    if self._data_hub and result['last'] > 0:
                        self._data_hub.update_quote(option_symbol, result, source="rest")
                    return result
                        
        except Exception as e:
            print(f"[{self.name}] Error getting option quote: {e}")
        
        return None
    
    def is_authenticated(self) -> bool:
        """Check if we have valid tokens"""
        return bool(self.access_token and self.refresh_token)
    
    async def get_option_chain(self, symbol: str, expiry: str) -> Dict[str, Any]:
        """Get option chain for a symbol and expiry date.
        
        Args:
            symbol: Underlying stock symbol
            expiry: Expiration date in YYYY-MM-DD format
            
        Returns:
            Dict with 'calls', 'puts', 'stock_price', 'data_source' keys
        """
        try:
            if not await self._ensure_valid_token():
                return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': 'Error: Not authenticated'}

            # Convert expiry format if needed (YYYY-MM-DD to YYYY-MM-DD)
            if "/" in expiry:
                parts = expiry.split("/")
                if len(parts) == 2:
                    m, d = parts
                    y = datetime.now().year
                    expiry = f"{y:04d}-{int(m):02d}-{int(d):02d}"
                elif len(parts) == 3:
                    m, d, y = parts
                    if len(y) == 2:
                        y = f"20{y}"
                    expiry = f"{y}-{int(m):02d}-{int(d):02d}"
            
            _INDEX_SYMBOLS = {'SPX', 'SPXW', 'NDX', 'NDXP', 'RUT', 'RUTW', 'DJX', 'DJXW', 'VIX', 'XSP'}
            _CHAIN_SYMBOL_NORMALIZE = {'SPXW': 'SPX', 'NDXP': 'NDX', 'RUTW': 'RUT', 'DJXW': 'DJX'}
            chain_symbol = symbol.upper()
            quote_symbol = symbol.upper()
            if chain_symbol in _INDEX_SYMBOLS or chain_symbol.startswith('$'):
                clean = chain_symbol.lstrip('$')
                clean = _CHAIN_SYMBOL_NORMALIZE.get(clean, clean)
                chain_symbol = f"${clean}"
                quote_symbol = f"${clean}"
            
            quote_response = await self._make_request('GET', "https://api.schwabapi.com/marketdata/v1/quotes", params={
                'symbols': quote_symbol, 'indicative': 'false',
                'needExtendedHoursData': 'true', 'needPreviousClose': 'true'})
            response = await self._make_request('GET', "https://api.schwabapi.com/marketdata/v1/chains", params={
                'symbol': chain_symbol, 'contractType': 'ALL', 'fromDate': expiry, 'toDate': expiry, 'includeUnderlyingQuote': 'true'
            })

            stock_price = None
            if quote_response.status_code == 200:
                try:
                    quote_data = quote_response.json()
                    for q_key in [quote_symbol, symbol, f"${symbol}"]:
                        if q_key in quote_data:
                            stock_price = float(quote_data[q_key].get('quote', {}).get('lastPrice', 0) or 0)
                            break
                except:
                    pass
            
            if response.status_code == 200:
                data = response.json()
                
                if not stock_price and data.get('underlyingPrice'):
                    stock_price = float(data.get('underlyingPrice', 0))
                
                calls = []
                puts = []
                
                call_exp_map = data.get('callExpDateMap', {})
                for exp_date, strikes in call_exp_map.items():
                    for strike_str, options in strikes.items():
                        for opt in options:
                            strike_val = float(opt.get('strikePrice', 0))
                            occ = self._build_option_symbol(symbol, expiry, strike_val, 'C')
                            calls.append({
                                'strike': strike_val,
                                'bid': float(opt.get('bid', 0) or 0),
                                'ask': float(opt.get('ask', 0) or 0),
                                'last': float(opt.get('last', 0) or 0),
                                'volume': int(opt.get('totalVolume', 0) or 0),
                                'open_interest': int(opt.get('openInterest', 0) or 0),
                                'iv': float(opt.get('volatility', 0) or 0),
                                'delta': float(opt.get('delta', 0) or 0),
                                'gamma': float(opt.get('gamma', 0) or 0),
                                'theta': float(opt.get('theta', 0) or 0),
                                'vega': float(opt.get('vega', 0) or 0),
                                'option_id': occ,
                            })
                
                put_exp_map = data.get('putExpDateMap', {})
                for exp_date, strikes in put_exp_map.items():
                    for strike_str, options in strikes.items():
                        for opt in options:
                            strike_val = float(opt.get('strikePrice', 0))
                            occ = self._build_option_symbol(symbol, expiry, strike_val, 'P')
                            puts.append({
                                'strike': strike_val,
                                'bid': float(opt.get('bid', 0) or 0),
                                'ask': float(opt.get('ask', 0) or 0),
                                'last': float(opt.get('last', 0) or 0),
                                'volume': int(opt.get('totalVolume', 0) or 0),
                                'open_interest': int(opt.get('openInterest', 0) or 0),
                                'iv': float(opt.get('volatility', 0) or 0),
                                'delta': float(opt.get('delta', 0) or 0),
                                'gamma': float(opt.get('gamma', 0) or 0),
                                'theta': float(opt.get('theta', 0) or 0),
                                'vega': float(opt.get('vega', 0) or 0),
                                'option_id': occ,
                            })
                
                calls.sort(key=lambda x: x['strike'])
                puts.sort(key=lambda x: x['strike'])
                
                return {
                    'calls': calls,
                    'puts': puts,
                    'stock_price': stock_price,
                    'data_source': 'Schwab'
                }
            else:
                print(f"[{self.name}] Option chain error: {response.status_code} - {response.text}")
                return {'calls': [], 'puts': [], 'stock_price': stock_price, 'data_source': f'Error: {response.status_code}'}
                    
        except Exception as e:
            print(f"[{self.name}] Error getting option chain: {e}")
            return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': f'Error: {str(e)}'}
    
    async def get_positions_detailed(self) -> List[Dict[str, Any]]:
        """Get detailed positions for sync service"""
        self._last_fetch_had_error = False
        try:
            if self._should_skip_non_critical():
                if self._data_hub:
                    cached = self._data_hub.get_positions(detailed=True)
                    if cached is not None:
                        return list(cached)
                if self._last_valid_positions and (time.time() - self._last_valid_positions_time) < self._position_cache_ttl:
                    return list(self._last_valid_positions)
            
            if not await self._ensure_valid_token():
                self._last_fetch_had_error = True
                if self._last_valid_positions and (time.time() - self._last_valid_positions_time) < self._position_cache_ttl:
                    print(f"[{self.name}] Token refresh pending - returning {len(self._last_valid_positions)} cached positions")
                    return list(self._last_valid_positions)
                return []
            
            if not self.account_hash:
                print(f"[{self.name}] No account_hash - cannot fetch positions")
                self._last_fetch_had_error = True
                return []
            

            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}",
                params={'fields': 'positions'}
            )

            
            if response.status_code in (429, 503) or getattr(response, '_budget_blocked', False):
                self._last_fetch_had_error = True
                print(f"[{self.name}] ⚠️ Rate limited/throttled on get_positions_detailed - returning {len(self._last_valid_positions)} cached positions")
                return list(self._last_valid_positions)
            
            if response.status_code == 200:
                data = response.json()
                account = data.get('securitiesAccount', {})
                positions = account.get('positions', [])
                
                result = []
                for pos in positions:
                    instrument = pos.get('instrument', {})
                    symbol = instrument.get('symbol', '')
                    asset_type = instrument.get('assetType', 'EQUITY').lower()
                    
                    qty = pos.get('longQuantity', 0) - pos.get('shortQuantity', 0)
                    if qty == 0:
                        continue
                    
                    avg_price = pos.get('averagePrice', 0)
                    market_value = pos.get('marketValue', 0)
                    
                    if asset_type == 'option':
                        current_price = market_value / (qty * 100) if qty else 0
                        if avg_price > 0 and current_price > 0 and avg_price > current_price * 50:
                            avg_price = avg_price / 100.0
                    else:
                        current_price = market_value / qty if qty else 0
                    
                    unrealized_pnl = pos.get('longOpenProfitLoss', 0) + pos.get('shortOpenProfitLoss', 0)
                    
                    position_data = {
                        'symbol': symbol,
                        'quantity': int(qty),
                        'avg_cost': float(avg_price),
                        'current_price': float(current_price),
                        'unrealized_pl': float(unrealized_pnl),
                        'asset': 'option' if asset_type == 'option' else 'stock',
                        'position_id': instrument.get('cusip', symbol)
                    }
                    
                    if asset_type == 'option':
                        position_data['raw_symbol'] = symbol
                        
                        strike_price = instrument.get('strikePrice', 0)
                        expiration = instrument.get('expirationDate', '')
                        put_call = instrument.get('putCall', '')
                        underlying = instrument.get('underlyingSymbol', '')
                        
                        if (not strike_price or strike_price == 0) and symbol:
                            parsed = self._parse_occ_symbol(symbol)
                            if parsed:
                                underlying = parsed.get('underlying', underlying) or underlying
                                strike_price = parsed.get('strike', 0)
                                expiration = parsed.get('expiry', '')
                                put_call = parsed.get('option_type', put_call)
                        
                        position_data['strike'] = float(strike_price) if strike_price else 0.0
                        position_data['expiry'] = expiration[:10] if expiration else ''
                        position_data['direction'] = put_call[0].upper() if put_call else ''
                        raw_underlying = underlying or symbol.split()[0] if symbol else symbol
                        normalized_underlying = self._INDEX_OPTION_REVERSE_MAP.get(raw_underlying.upper(), raw_underlying) if raw_underlying else raw_underlying
                        if normalized_underlying != raw_underlying:
                            print(f"[{self.name}] Position symbol normalized: {raw_underlying} → {normalized_underlying}")
                        position_data['symbol'] = normalized_underlying
                    
                    result.append(position_data)
                
                if len(result) > 0:
                    self._last_valid_positions = list(result)
                    self._last_valid_positions_time = time.time()
                    self._consecutive_zero_positions = 0
                    self._position_cache_invalidated = False
                    self._last_fetch_had_error = False
                    if self._data_hub:
                        try:
                            self._data_hub.update_positions(result, detailed=True, source="rest")
                        except Exception:
                            pass
                elif len(result) == 0 and self._last_valid_positions:
                    self._consecutive_zero_positions += 1
                    if self._position_cache_invalidated or self._consecutive_zero_positions >= 2:
                        print(f"[{self.name}] ✓ Accepting 0 positions (consecutive={self._consecutive_zero_positions}, invalidated={self._position_cache_invalidated})")
                        self._last_valid_positions = []
                        self._last_valid_positions_time = 0
                        if hasattr(self, '_last_positions_simple'):
                            self._last_positions_simple = {}
                        if self._data_hub:
                            try:
                                self._data_hub.update_positions([], detailed=True, source="rest_cleared")
                            except Exception:
                                pass
                    elif (time.time() - self._last_valid_positions_time) < self._position_cache_ttl:
                        print(f"[{self.name}] ⚠️ API returned 0 positions but cache has {len(self._last_valid_positions)} - returning cached data (consecutive={self._consecutive_zero_positions})")
                        return list(self._last_valid_positions)
                
                return result
                    
        except Exception as e:
            err_msg = str(e) or type(e).__name__
            print(f"[{self.name}] Error getting detailed positions: {err_msg}")
            self._last_fetch_had_error = True
            if self._last_valid_positions and (time.time() - self._last_valid_positions_time) < self._position_cache_ttl:
                print(f"[{self.name}] Returning {len(self._last_valid_positions)} cached positions after error")
                return list(self._last_valid_positions)
        
        return []
    
    async def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Get open/pending orders"""
        try:
            if self._data_hub:
                cached = self._data_hub.get_pending_orders()
                if cached is not None:
                    return list(cached)

            if self._should_skip_non_critical():
                return getattr(self, '_last_pending_orders', [])
            
            if not await self._ensure_valid_token():
                return []
            
            if not self.account_hash:
                print(f"[{self.name}] No account_hash - cannot fetch pending orders")
                return []
            
            from datetime import datetime, timedelta
            
            to_date = datetime.now()
            from_date = to_date - timedelta(days=7)
            
            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                params={
                    'fromEnteredTime': from_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'toEnteredTime': to_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'status': 'WORKING'
                }
            )
            if response.status_code == 200:
                orders = response.json()
                result = []
                
                for order in orders:
                    order_legs = order.get('orderLegCollection', [])
                    if not order_legs:
                        continue
                    
                    leg = order_legs[0]
                    instrument = leg.get('instrument', {})
                    
                    result.append({
                        'order_id': str(order.get('orderId', '')),
                        'symbol': instrument.get('symbol', ''),
                        'quantity': int(leg.get('quantity', 0)),
                        'limit_price': float(order.get('price', 0)) if order.get('price') else None,
                        'action': leg.get('instruction', ''),
                        'status': order.get('status', ''),
                        'order_type': order.get('orderType', ''),
                        'entered_time': order.get('enteredTime', '')
                    })
                
                self._last_pending_orders = list(result)
                if self._data_hub:
                    self._data_hub.update_pending_orders(result)
                return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting pending orders: {e}")
            import traceback
            traceback.print_exc()
        
        return getattr(self, '_last_pending_orders', [])
    
    async def get_order_history(self, count: int = 50) -> List[Dict[str, Any]]:
        """Get filled order history for sync"""
        try:
            if self._data_hub:
                cached = self._data_hub.get_order_history()
                if cached is not None:
                    return list(cached[:count])

            if not await self._ensure_valid_token():
                return []
            
            if not self.account_hash:
                print(f"[{self.name}] No account_hash - cannot fetch order history")
                return []
            
            from datetime import datetime, timedelta
            
            if self._should_skip_non_critical():
                return []
            
            to_date = datetime.now()
            from_date = to_date - timedelta(days=7)

            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                params={
                    'fromEnteredTime': from_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'toEnteredTime': to_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                }
            )
            
            if response.status_code == 200:
                orders = response.json()
                result = []

                for order in orders[:count]:
                    self._extract_filled_from_order(order, result)

                if self._data_hub:
                    self._data_hub.update_order_history(result)
                return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting order history: {e}")
        
        return []

    def _extract_filled_from_order(self, order: Dict, result: List):
        """Extract filled order entries, walking into childOrderStrategies for TRIGGER/OCO."""
        seen_ids = {r['order_id'] for r in result}
        order_legs = order.get('orderLegCollection', [])
        strategy = order.get('orderStrategyType', 'SINGLE')
        status = order.get('status', '')

        if order_legs and status == 'FILLED':
            parsed = self._parse_order_fill(order)
            if parsed and parsed['order_id'] not in seen_ids:
                result.append(parsed)

        for child in order.get('childOrderStrategies', []):
            child_status = child.get('status', '')
            child_legs = child.get('orderLegCollection', [])

            if child_legs and child_status == 'FILLED':
                parsed = self._parse_order_fill(child)
                if parsed and parsed['order_id'] not in seen_ids:
                    result.append(parsed)
                    seen_ids.add(parsed['order_id'])

            for grandchild in child.get('childOrderStrategies', []):
                gc_status = grandchild.get('status', '')
                gc_legs = grandchild.get('orderLegCollection', [])

                if gc_legs and gc_status == 'FILLED':
                    parsed = self._parse_order_fill(grandchild)
                    if parsed and parsed['order_id'] not in seen_ids:
                        result.append(parsed)
                        seen_ids.add(parsed['order_id'])

    def _parse_order_fill(self, order: Dict) -> Optional[Dict]:
        """Parse a single Schwab order node into a fill dict."""
        order_legs = order.get('orderLegCollection', [])
        if not order_legs:
            return None

        leg = order_legs[0]
        instrument = leg.get('instrument', {})
        asset_type = instrument.get('assetType', 'EQUITY').lower()
        symbol = instrument.get('symbol', '')
        underlying = instrument.get('underlyingSymbol', symbol) if asset_type == 'option' else symbol

        activities = order.get('orderActivityCollection', [])
        total_filled_qty = 0
        total_cost = 0.0
        filled_time = order.get('closeTime', '') or order.get('enteredTime', '')

        for activity in activities:
            if activity.get('activityType') == 'EXECUTION':
                for exec_leg in activity.get('executionLegs', []):
                    leg_qty = int(exec_leg.get('quantity', 0))
                    leg_price = float(exec_leg.get('price', 0))
                    total_filled_qty += leg_qty
                    total_cost += leg_qty * leg_price
                    leg_time = exec_leg.get('time', '')
                    if leg_time and leg_time > filled_time:
                        filled_time = leg_time

        filled_qty = total_filled_qty
        filled_price = (total_cost / total_filled_qty) if total_filled_qty > 0 else 0

        if filled_qty == 0:
            filled_qty = int(order.get('filledQuantity', 0)) or int(leg.get('quantity', 0))
        if filled_price == 0:
            filled_price = float(order.get('price', 0))

        instruction = leg.get('instruction', '')

        order_data = {
            'order_id': str(order.get('orderId', '')),
            'symbol': underlying,
            'quantity': filled_qty,
            'filled_price': filled_price,
            'action': instruction,
            'filled_time': filled_time,
            'asset_type': 'option' if asset_type == 'option' else 'stock',
            'order_type': order.get('orderType', '')
        }

        if asset_type == 'option':
            order_data['strike'] = float(instrument.get('strikePrice', 0))
            order_data['expiry'] = instrument.get('expirationDate', '')[:10] if instrument.get('expirationDate') else ''
            order_data['direction'] = instrument.get('putCall', '')[0] if instrument.get('putCall') else ''

        return order_data

    async def place_stop_order(
        self,
        symbol: str,
        quantity: int,
        stop_price: float,
        side: str = 'sell',
        asset_type: str = 'EQUITY',
        duration: str = 'GOOD_TILL_CANCEL'
    ) -> OrderResult:
        """Place a STOP order (broker-side stop loss).
        
        When the market price hits the stop_price, a MARKET order is triggered.
        
        Args:
            symbol: Ticker symbol (equity or OCC option symbol)
            quantity: Number of shares/contracts
            stop_price: The trigger price
            side: 'sell' for protective stop on long, 'buy' for stop on short
            asset_type: 'EQUITY' or 'OPTION'
            duration: Order duration (DAY, GOOD_TILL_CANCEL)
        """
        try:
            if not await self._ensure_valid_token():
                return OrderResult(success=False, message="Not authenticated with Schwab", symbol=symbol, action=side)

            instruction_map = {
                'sell': 'SELL',
                'buy': 'BUY',
                'sell_to_close': 'SELL_TO_CLOSE',
                'buy_to_close': 'BUY_TO_CLOSE',
            }
            instruction = instruction_map.get(side.lower(), 'SELL')

            session = self._get_session_type()
            if session == "SEAMLESS":
                session = "NORMAL"
                print(f"[{self.name}] ℹ️ STOP order forced to NORMAL session (SEAMLESS doesn't support STOP orders)")
            order_duration = self._get_duration(duration_hint=duration, is_exit=True)

            if asset_type.upper() == 'OPTION':
                original_stop = stop_price
                is_sell = instruction in ('SELL', 'SELL_TO_CLOSE')
                stop_price = self._round_to_cboe_increment(stop_price, is_sell=is_sell, is_stop_trigger=True)
                if stop_price != original_stop:
                    print(f"[{self.name}] 📐 STOP CBOE snap: ${original_stop:.4f} → ${stop_price:.2f} (protective {'up' if is_sell else 'down'})")

            order_payload = {
                "orderStrategyType": "SINGLE",
                "orderType": "STOP",
                "stopPrice": self._format_price(stop_price),
                "session": session,
                "duration": order_duration,
                "orderLegCollection": [{
                    "instruction": instruction,
                    "quantity": quantity,
                    "instrument": {
                        "symbol": symbol,
                        "assetType": asset_type.upper()
                    }
                }]
            }

            if self.dry_run:
                print(f"[{self.name}] DRY RUN - STOP order: {instruction} {quantity} {symbol} @ stop ${stop_price}")
                return OrderResult(
                    success=True, order_id="DRY_RUN",
                    message=f"DRY RUN: STOP {instruction} {quantity} {symbol} @ ${stop_price}",
                    price=stop_price, quantity=quantity, symbol=symbol, action=side
                )

            headers = {'Content-Type': 'application/json'}
            is_exit = instruction in ('SELL', 'SELL_TO_CLOSE')
            response = await self._make_request(
                'POST', f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                is_exit_order=is_exit,
                headers=headers, json=order_payload
            )

            if response.status_code in [200, 201, 202]:
                order_id = response.headers.get('Location', '').split('/')[-1]
                if self._data_hub:
                    self._data_hub.invalidate_all()
                print(f"[{self.name}] ✓ STOP order placed: {instruction} {quantity} {symbol} @ ${stop_price} (ID: {order_id})")
                return OrderResult(
                    success=True, order_id=order_id,
                    message=f"STOP order placed: {instruction} {quantity} {symbol} @ ${stop_price}",
                    price=stop_price, quantity=quantity, symbol=symbol, action=side
                )
            else:
                error_msg = response.text
                print(f"[{self.name}] ❌ STOP order failed: {response.status_code} - {error_msg}")
                return OrderResult(success=False, message=f"STOP order failed: {response.status_code} - {error_msg}", symbol=symbol, action=side)

        except Exception as e:
            return OrderResult(success=False, message=f"STOP order exception: {str(e)}", symbol=symbol, action=side)

    async def place_stop_limit_order(
        self,
        symbol: str,
        quantity: int,
        stop_price: float,
        limit_price: float,
        side: str = 'sell',
        asset_type: str = 'EQUITY',
        duration: str = 'GOOD_TILL_CANCEL'
    ) -> OrderResult:
        """Place a STOP_LIMIT order.
        
        When the market price hits stop_price, a LIMIT order at limit_price is placed.
        Provides price protection vs pure STOP (market) orders.
        
        Args:
            symbol: Ticker symbol
            quantity: Number of shares/contracts
            stop_price: The trigger price
            limit_price: The limit price after trigger
            side: 'sell' or 'buy'
            asset_type: 'EQUITY' or 'OPTION'
            duration: Order duration
        """
        try:
            if not await self._ensure_valid_token():
                return OrderResult(success=False, message="Not authenticated with Schwab", symbol=symbol, action=side)

            instruction_map = {
                'sell': 'SELL',
                'buy': 'BUY',
                'sell_to_close': 'SELL_TO_CLOSE',
                'buy_to_close': 'BUY_TO_CLOSE',
            }
            instruction = instruction_map.get(side.lower(), 'SELL')

            session = self._get_session_type()
            order_duration = self._get_duration(duration_hint=duration, is_exit=True)

            if asset_type.upper() == 'OPTION':
                is_sell = instruction in ('SELL', 'SELL_TO_CLOSE')
                original_stop, original_limit = stop_price, limit_price
                stop_price = self._round_to_cboe_increment(stop_price, is_sell=is_sell, is_stop_trigger=True)
                limit_price = self._round_to_cboe_increment(limit_price, is_sell=is_sell)
                if stop_price != original_stop or limit_price != original_limit:
                    print(f"[{self.name}] 📐 STOP_LIMIT CBOE snap: stop ${original_stop:.4f}→${stop_price:.2f}, limit ${original_limit:.4f}→${limit_price:.2f}")

            order_payload = {
                "orderStrategyType": "SINGLE",
                "orderType": "STOP_LIMIT",
                "stopPrice": self._format_price(stop_price),
                "price": self._format_price(limit_price),
                "session": session,
                "duration": order_duration,
                "orderLegCollection": [{
                    "instruction": instruction,
                    "quantity": quantity,
                    "instrument": {
                        "symbol": symbol,
                        "assetType": asset_type.upper()
                    }
                }]
            }

            if self.dry_run:
                print(f"[{self.name}] DRY RUN - STOP_LIMIT order: {instruction} {quantity} {symbol} stop=${stop_price} limit=${limit_price}")
                return OrderResult(
                    success=True, order_id="DRY_RUN",
                    message=f"DRY RUN: STOP_LIMIT {instruction} {quantity} {symbol} stop=${stop_price} limit=${limit_price}",
                    price=limit_price, quantity=quantity, symbol=symbol, action=side
                )

            headers = {'Content-Type': 'application/json'}
            is_exit = instruction in ('SELL', 'SELL_TO_CLOSE')
            response = await self._make_request(
                'POST', f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                is_exit_order=is_exit,
                headers=headers, json=order_payload
            )

            if response.status_code in [200, 201, 202]:
                order_id = response.headers.get('Location', '').split('/')[-1]
                if self._data_hub:
                    self._data_hub.invalidate_all()
                print(f"[{self.name}] ✓ STOP_LIMIT order placed: {instruction} {quantity} {symbol} stop=${stop_price} limit=${limit_price} (ID: {order_id})")
                return OrderResult(
                    success=True, order_id=order_id,
                    message=f"STOP_LIMIT order placed: {instruction} {quantity} {symbol}",
                    price=limit_price, quantity=quantity, symbol=symbol, action=side
                )
            else:
                error_msg = response.text
                print(f"[{self.name}] ❌ STOP_LIMIT order failed: {response.status_code} - {error_msg}")
                return OrderResult(success=False, message=f"STOP_LIMIT order failed: {response.status_code} - {error_msg}", symbol=symbol, action=side)

        except Exception as e:
            return OrderResult(success=False, message=f"STOP_LIMIT order exception: {str(e)}", symbol=symbol, action=side)

    async def place_trailing_stop_order(
        self,
        symbol: str,
        quantity: int,
        trail_offset: float,
        trail_type: str = 'VALUE',
        price_basis: str = 'BID',
        side: str = 'sell',
        asset_type: str = 'EQUITY',
        duration: str = 'DAY'
    ) -> OrderResult:
        """Place a TRAILING_STOP order.
        
        Stop price dynamically adjusts as price moves favorably.
        
        Args:
            symbol: Ticker symbol
            quantity: Number of shares/contracts
            trail_offset: Trailing distance (dollar amount or percentage)
            trail_type: 'VALUE' (dollar amount) or 'PERCENT'
            price_basis: 'BID', 'ASK', or 'LAST' - reference price for trailing
            side: 'sell' for protective trail on long positions
            asset_type: 'EQUITY' or 'OPTION'
            duration: Order duration (trailing stops typically DAY only)
        """
        try:
            if not await self._ensure_valid_token():
                return OrderResult(success=False, message="Not authenticated with Schwab", symbol=symbol, action=side)

            instruction_map = {
                'sell': 'SELL',
                'buy': 'BUY',
                'sell_to_close': 'SELL_TO_CLOSE',
                'buy_to_close': 'BUY_TO_CLOSE',
            }
            instruction = instruction_map.get(side.lower(), 'SELL')

            session = self._get_session_type()
            if session == "SEAMLESS":
                session = "NORMAL"
                print(f"[{self.name}] ℹ️ TRAILING_STOP order forced to NORMAL session (SEAMLESS doesn't support STOP-type orders)")
            valid_basis = {'BID', 'ASK', 'LAST'}
            valid_type = {'VALUE', 'PERCENT'}
            price_basis = price_basis.upper() if price_basis.upper() in valid_basis else 'BID'
            trail_type = trail_type.upper() if trail_type.upper() in valid_type else 'VALUE'

            order_payload = {
                "orderStrategyType": "SINGLE",
                "orderType": "TRAILING_STOP",
                "complexOrderStrategyType": "NONE",
                "stopPriceLinkBasis": price_basis,
                "stopPriceLinkType": trail_type,
                "stopPriceOffset": trail_offset,
                "session": session,
                "duration": self._get_duration(duration_hint=duration),
                "orderLegCollection": [{
                    "instruction": instruction,
                    "quantity": quantity,
                    "instrument": {
                        "symbol": symbol,
                        "assetType": asset_type.upper()
                    }
                }]
            }

            if self.dry_run:
                print(f"[{self.name}] DRY RUN - TRAILING_STOP: {instruction} {quantity} {symbol} trail={trail_offset} ({trail_type})")
                return OrderResult(
                    success=True, order_id="DRY_RUN",
                    message=f"DRY RUN: TRAILING_STOP {instruction} {quantity} {symbol} trail={trail_offset} ({trail_type})",
                    quantity=quantity, symbol=symbol, action=side
                )

            headers = {'Content-Type': 'application/json'}
            response = await self._make_request(
                'POST', f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                headers=headers, json=order_payload
            )

            if response.status_code in [200, 201, 202]:
                order_id = response.headers.get('Location', '').split('/')[-1]
                if self._data_hub:
                    self._data_hub.invalidate_all()
                print(f"[{self.name}] ✓ TRAILING_STOP placed: {instruction} {quantity} {symbol} trail={trail_offset} ({trail_type}) (ID: {order_id})")
                return OrderResult(
                    success=True, order_id=order_id,
                    message=f"TRAILING_STOP placed: {instruction} {quantity} {symbol}",
                    quantity=quantity, symbol=symbol, action=side
                )
            else:
                error_msg = response.text
                print(f"[{self.name}] ❌ TRAILING_STOP failed: {response.status_code} - {error_msg}")
                return OrderResult(success=False, message=f"TRAILING_STOP failed: {response.status_code} - {error_msg}", symbol=symbol, action=side)

        except Exception as e:
            return OrderResult(success=False, message=f"TRAILING_STOP exception: {str(e)}", symbol=symbol, action=side)

    async def place_oco_order(
        self,
        symbol: str,
        quantity: int,
        stop_loss_price: float,
        profit_target_price: float,
        side: str = 'sell',
        asset_type: str = 'EQUITY',
        stop_limit_price: Optional[float] = None
    ) -> OrderResult:
        """Place an OCO (One-Cancels-Other) order.
        
        Two exit orders linked together - when one fills, the other cancels.
        Typically used for stop loss + profit target on existing position.
        
        Args:
            symbol: Ticker symbol
            quantity: Number of shares/contracts
            stop_loss_price: Stop loss trigger price
            profit_target_price: Profit target limit price
            side: Exit side ('sell' for long positions)
            asset_type: 'EQUITY' or 'OPTION'
            stop_limit_price: Optional limit price for stop (uses STOP_LIMIT instead of STOP)
        """
        try:
            if not await self._ensure_valid_token():
                return OrderResult(success=False, message="Not authenticated with Schwab", symbol=symbol, action='OCO')

            instruction_map = {
                'sell': 'SELL',
                'buy': 'BUY',
                'sell_to_close': 'SELL_TO_CLOSE',
                'buy_to_close': 'BUY_TO_CLOSE',
            }
            instruction = instruction_map.get(side.lower(), 'SELL')
            session = self._get_session_type()
            stop_session = "NORMAL" if session == "SEAMLESS" else session

            if asset_type.upper() == 'OPTION':
                is_sell = instruction in ('SELL', 'SELL_TO_CLOSE')
                original_sl, original_pt = stop_loss_price, profit_target_price
                stop_loss_price = self._round_to_cboe_increment(stop_loss_price, is_sell=is_sell, is_stop_trigger=True)
                profit_target_price = self._round_to_cboe_increment(profit_target_price, is_sell=is_sell)
                if stop_limit_price:
                    stop_limit_price = self._round_to_cboe_increment(stop_limit_price, is_sell=is_sell)
                if stop_loss_price != original_sl or profit_target_price != original_pt:
                    print(f"[{self.name}] 📐 OCO CBOE snap: SL ${original_sl:.4f}→${stop_loss_price:.2f}, PT ${original_pt:.4f}→${profit_target_price:.2f}")

            profit_leg = {
                "orderStrategyType": "SINGLE",
                "orderType": "LIMIT",
                "session": session,
                "duration": "GOOD_TILL_CANCEL",
                "price": self._format_price(profit_target_price),
                "orderLegCollection": [{
                    "instruction": instruction,
                    "quantity": quantity,
                    "instrument": {
                        "symbol": symbol,
                        "assetType": asset_type.upper()
                    }
                }]
            }

            if stop_limit_price:
                stop_leg = {
                    "orderStrategyType": "SINGLE",
                    "orderType": "STOP_LIMIT",
                    "session": stop_session,
                    "duration": "GOOD_TILL_CANCEL",
                    "stopPrice": self._format_price(stop_loss_price),
                    "price": self._format_price(stop_limit_price),
                    "orderLegCollection": [{
                        "instruction": instruction,
                        "quantity": quantity,
                        "instrument": {
                            "symbol": symbol,
                            "assetType": asset_type.upper()
                        }
                    }]
                }
            else:
                stop_leg = {
                    "orderStrategyType": "SINGLE",
                    "orderType": "STOP",
                    "session": stop_session,
                    "duration": "GOOD_TILL_CANCEL",
                    "stopPrice": self._format_price(stop_loss_price),
                    "orderLegCollection": [{
                        "instruction": instruction,
                        "quantity": quantity,
                        "instrument": {
                            "symbol": symbol,
                            "assetType": asset_type.upper()
                        }
                    }]
                }

            oco_payload = {
                "orderStrategyType": "OCO",
                "childOrderStrategies": [profit_leg, stop_leg]
            }

            if self.dry_run:
                print(f"[{self.name}] DRY RUN - OCO: {instruction} {quantity} {symbol} PT=${profit_target_price} SL=${stop_loss_price}")
                return OrderResult(
                    success=True, order_id="DRY_RUN",
                    message=f"DRY RUN: OCO {instruction} {quantity} {symbol} PT=${profit_target_price} SL=${stop_loss_price}",
                    quantity=quantity, symbol=symbol, action='OCO'
                )

            headers = {'Content-Type': 'application/json'}
            response = await self._make_request(
                'POST', f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                headers=headers, json=oco_payload
            )

            if response.status_code in [200, 201, 202]:
                order_id = response.headers.get('Location', '').split('/')[-1]
                if self._data_hub:
                    self._data_hub.invalidate_all()
                print(f"[{self.name}] ✓ OCO order placed: {instruction} {quantity} {symbol} PT=${profit_target_price} SL=${stop_loss_price} (ID: {order_id})")
                return OrderResult(
                    success=True, order_id=order_id,
                    message=f"OCO placed: PT=${profit_target_price} SL=${stop_loss_price}",
                    quantity=quantity, symbol=symbol, action='OCO'
                )
            else:
                error_msg = response.text
                print(f"[{self.name}] ❌ OCO order failed: {response.status_code} - {error_msg}")
                return OrderResult(success=False, message=f"OCO failed: {response.status_code} - {error_msg}", symbol=symbol, action='OCO')

        except Exception as e:
            return OrderResult(success=False, message=f"OCO exception: {str(e)}", symbol=symbol, action='OCO')

    async def place_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        stop_loss_price: Optional[float] = None,
        profit_target_price: Optional[float] = None,
        entry_price: Optional[float] = None,
        asset_type: str = 'EQUITY',
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        option_type: Optional[str] = None
    ) -> OrderResult:
        """Place a bracket order (entry + stop loss + profit target).
        
        Uses Schwab's TRIGGER orderStrategyType with nested OCO child orders.
        Entry order triggers, then OCO (stop loss + profit target) activates.
        Supports both stocks (EQUITY) and options (OPTION).
        
        Args:
            symbol: Stock ticker or OCC option symbol
            action: BTO (buy) or STC (sell)
            quantity: Number of shares/contracts
            stop_loss_price: Stop loss price
            profit_target_price: Profit target price
            entry_price: Entry limit price (None for market order)
            asset_type: 'EQUITY' or 'OPTION'
            strike: Option strike price (required for options)
            expiry: Option expiry in YYYY-MM-DD format (required for options)
            option_type: 'C' or 'P' (required for options)
        """
        try:
            if not await self._ensure_valid_token():
                return OrderResult(success=False, message="Not authenticated with Schwab", symbol=symbol, action=action)

            is_option = asset_type.upper() == 'OPTION'

            if is_option:
                if action.upper() == "BTO":
                    entry_instruction = "BUY_TO_OPEN"
                    exit_instruction = "SELL_TO_CLOSE"
                else:
                    entry_instruction = "SELL_TO_OPEN"
                    exit_instruction = "BUY_TO_CLOSE"
                occ_symbol = self._build_option_symbol(symbol, expiry, strike, option_type)
                instrument_symbol = occ_symbol
                instrument_asset_type = "OPTION"
                print(f"[{self.name}] Option bracket: {occ_symbol} ({symbol} ${strike}{option_type} {expiry})")
            else:
                if action.upper() == "BTO":
                    entry_instruction = "BUY"
                    exit_instruction = "SELL"
                else:
                    entry_instruction = "SELL"
                    exit_instruction = "BUY"
                instrument_symbol = symbol
                instrument_asset_type = "EQUITY"

            session = self._get_session_type()
            if is_option:
                if entry_price:
                    original_entry = entry_price
                    entry_price = self._round_to_cboe_increment(entry_price, is_sell=(entry_instruction in ('SELL_TO_OPEN',)))
                    if entry_price != original_entry:
                        print(f"[{self.name}] 📐 BRACKET entry CBOE snap: ${original_entry:.4f}→${entry_price:.2f}")
                if stop_loss_price is not None:
                    original_sl = stop_loss_price
                    stop_loss_price = self._round_to_cboe_increment(stop_loss_price, is_sell=(exit_instruction in ('SELL_TO_CLOSE',)), is_stop_trigger=True)
                    if stop_loss_price != original_sl:
                        print(f"[{self.name}] 📐 BRACKET SL CBOE snap: ${original_sl:.4f}→${stop_loss_price:.2f}")
                if profit_target_price is not None:
                    original_pt = profit_target_price
                    profit_target_price = self._round_to_cboe_increment(profit_target_price, is_sell=(exit_instruction in ('SELL_TO_CLOSE',)))
                    if profit_target_price != original_pt:
                        print(f"[{self.name}] 📐 BRACKET PT CBOE snap: ${original_pt:.4f}→${profit_target_price:.2f}")

            entry_order_type = "LIMIT" if entry_price else "MARKET"
            entry_duration = "DAY"

            entry_payload = {
                "orderStrategyType": "TRIGGER" if (stop_loss_price or profit_target_price) else "SINGLE",
                "orderType": entry_order_type,
                "session": session,
                "duration": entry_duration,
                "orderLegCollection": [{
                    "instruction": entry_instruction,
                    "quantity": quantity,
                    "instrument": {
                        "symbol": instrument_symbol,
                        "assetType": instrument_asset_type
                    }
                }]
            }

            if entry_price:
                entry_payload["price"] = self._format_price(entry_price)

            has_both = stop_loss_price is not None and profit_target_price is not None
            has_sl_only = stop_loss_price is not None and profit_target_price is None
            has_pt_only = profit_target_price is not None and stop_loss_price is None

            child_session = "NORMAL" if session == "SEAMLESS" else session

            if has_both:
                profit_leg = {
                    "orderStrategyType": "SINGLE",
                    "session": child_session,
                    "duration": "GOOD_TILL_CANCEL",
                    "orderType": "LIMIT",
                    "price": self._format_price(profit_target_price),
                    "orderLegCollection": [{
                        "instruction": exit_instruction,
                        "quantity": quantity,
                        "instrument": {"assetType": instrument_asset_type, "symbol": instrument_symbol}
                    }]
                }
                stop_leg = {
                    "orderStrategyType": "SINGLE",
                    "session": child_session,
                    "duration": "GOOD_TILL_CANCEL",
                    "orderType": "STOP",
                    "stopPrice": self._format_price(stop_loss_price),
                    "orderLegCollection": [{
                        "instruction": exit_instruction,
                        "quantity": quantity,
                        "instrument": {"assetType": instrument_asset_type, "symbol": instrument_symbol}
                    }]
                }
                entry_payload["childOrderStrategies"] = [{
                    "orderStrategyType": "OCO",
                    "childOrderStrategies": [profit_leg, stop_leg]
                }]
                print(f"[{self.name}] Full BRACKET order: Entry + OCO(PT=${profit_target_price} / SL=${stop_loss_price})")
                if session == "SEAMLESS":
                    print(f"[{self.name}] ℹ️ Child orders use NORMAL session (SEAMLESS doesn't support STOP orders)")
            elif has_sl_only:
                stop_child = {
                    "orderStrategyType": "SINGLE",
                    "session": child_session,
                    "duration": "GOOD_TILL_CANCEL",
                    "orderType": "STOP",
                    "stopPrice": self._format_price(stop_loss_price),
                    "orderLegCollection": [{
                        "instruction": exit_instruction,
                        "quantity": quantity,
                        "instrument": {"assetType": instrument_asset_type, "symbol": instrument_symbol}
                    }]
                }
                entry_payload["childOrderStrategies"] = [stop_child]
                print(f"[{self.name}] TRIGGER order: Entry + SL=${stop_loss_price}")
            elif has_pt_only:
                pt_child = {
                    "orderStrategyType": "SINGLE",
                    "session": child_session,
                    "duration": "GOOD_TILL_CANCEL",
                    "orderType": "LIMIT",
                    "price": self._format_price(profit_target_price),
                    "orderLegCollection": [{
                        "instruction": exit_instruction,
                        "quantity": quantity,
                        "instrument": {"assetType": instrument_asset_type, "symbol": instrument_symbol}
                    }]
                }
                entry_payload["childOrderStrategies"] = [pt_child]
                print(f"[{self.name}] TRIGGER order: Entry + PT=${profit_target_price}")

            if self.dry_run:
                sl_str = f" SL=${stop_loss_price}" if stop_loss_price else ""
                pt_str = f" PT=${profit_target_price}" if profit_target_price else ""
                print(f"[{self.name}] DRY RUN - BRACKET: {entry_instruction} {quantity} {symbol}{sl_str}{pt_str}")
                return OrderResult(
                    success=True, order_id="DRY_RUN",
                    message=f"DRY RUN: BRACKET {entry_instruction} {quantity} {symbol}{sl_str}{pt_str}",
                    price=entry_price, quantity=quantity, symbol=symbol, action=action
                )

            headers = {'Content-Type': 'application/json'}
            response = await self._make_request(
                'POST', f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                headers=headers, json=entry_payload
            )

            if response.status_code in [200, 201, 202]:
                order_id = response.headers.get('Location', '').split('/')[-1]
                if self._data_hub:
                    self._data_hub.invalidate_all()
                sl_str = f" SL=${stop_loss_price}" if stop_loss_price else ""
                pt_str = f" PT=${profit_target_price}" if profit_target_price else ""
                print(f"[{self.name}] ✓ BRACKET order placed: {entry_instruction} {quantity} {symbol}{sl_str}{pt_str} (ID: {order_id})")
                return OrderResult(
                    success=True, order_id=order_id,
                    message=f"BRACKET placed: {entry_instruction} {quantity} {symbol}{sl_str}{pt_str}",
                    price=entry_price, quantity=quantity, symbol=symbol, action=action
                )
            else:
                error_msg = response.text
                print(f"[{self.name}] ❌ BRACKET order failed: {response.status_code} - {error_msg}")
                return OrderResult(success=False, message=f"BRACKET failed: {response.status_code} - {error_msg}", symbol=symbol, action=action)

        except Exception as e:
            return OrderResult(success=False, message=f"BRACKET exception: {str(e)}", symbol=symbol, action=action)

    async def get_transactions(self, days: int = 30, transaction_types: str = 'TRADE') -> List[Dict[str, Any]]:
        """Get account transaction history.
        
        Args:
            days: Number of days to look back (max 365)
            transaction_types: Comma-separated types: TRADE, RECEIVE_AND_DELIVER,
                             DIVIDEND_OR_INTEREST, ACH_RECEIPT, ACH_DISBURSEMENT,
                             CASH_RECEIPT, CASH_DISBURSEMENT, ELECTRONIC_FUND, WIRE_IN,
                             WIRE_OUT, JOURNAL, MEMORANDUM, MARGIN_CALL, MONEY_MARKET, SMA_ADJUSTMENT
        """
        try:
            if not await self._ensure_valid_token():
                return []

            if not self.account_hash:
                print(f"[{self.name}] No account_hash - cannot fetch transactions")
                return []

            import httpx
            from datetime import timedelta

            to_date = datetime.now()
            from_date = to_date - timedelta(days=min(days, 365))

            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}/transactions",
                params={
                    'startDate': from_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'endDate': to_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'types': transaction_types
                }
            )

            if response.status_code == 200:
                transactions = response.json()
                result = []
                for txn in transactions:
                    transfer_items = txn.get('transferItems', [])
                    for item in transfer_items:
                        instrument = item.get('instrument', {})
                        result.append({
                            'transaction_id': str(txn.get('activityId', '')),
                            'type': txn.get('type', ''),
                            'date': txn.get('tradeDate', '') or txn.get('settlementDate', ''),
                            'settlement_date': txn.get('settlementDate', ''),
                            'symbol': instrument.get('symbol', ''),
                            'asset_type': instrument.get('assetType', ''),
                            'description': txn.get('description', ''),
                            'amount': float(item.get('amount', 0)),
                            'price': float(item.get('price', 0)),
                            'cost': float(item.get('cost', 0)),
                            'instruction': item.get('instruction', ''),
                            'position_effect': item.get('positionEffect', ''),
                            'net_amount': float(txn.get('netAmount', 0)),
                        })
                return result
            else:
                print(f"[{self.name}] Transactions error: {response.status_code} - {response.text}")
                return []

        except Exception as e:
            print(f"[{self.name}] Error getting transactions: {e}")
            return []

    async def _verify_position_for_sell(self, symbol: str, qty: int) -> dict:
        """Verify position exists on Schwab before selling - returns position details."""
        try:
            if not await self._ensure_valid_token():
                return {}
            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}",
                params={'fields': 'positions'}
            )
            if response.status_code != 200:
                return {'error': f'HTTP {response.status_code}'}
            data = response.json()
            positions = data.get('securitiesAccount', {}).get('positions', [])
            acct_type = data.get('securitiesAccount', {}).get('type', 'unknown')
            acct_num = data.get('securitiesAccount', {}).get('accountNumber', 'unknown')
            for pos in positions:
                inst = pos.get('instrument', {})
                if inst.get('symbol', '').upper() == symbol.upper():
                    return {
                        'symbol': symbol,
                        'long_qty': pos.get('longQuantity', 0),
                        'short_qty': pos.get('shortQuantity', 0),
                        'settled_long': pos.get('settledLongQuantity', 0),
                        'settled_short': pos.get('settledShortQuantity', 0),
                        'avg_price': pos.get('averagePrice', 0),
                        'acct_type': acct_type,
                        'acct_num': acct_num[-4:] if len(str(acct_num)) > 4 else acct_num,
                        'sell_qty': qty,
                    }
            return {'error': f'{symbol} not found in {len(positions)} positions', 'acct_type': acct_type}
        except Exception as e:
            return {'error': str(e)}

    def _extract_orders_recursive(self, order, symbol: str, include_children: bool = True) -> list:
        """Extract all order entries for a symbol, walking into nested childOrderStrategies.
        Returns list of dicts with order info including nested OCO/TRIGGER children."""
        results = []
        sym_upper = symbol.upper()
        
        legs = order.get('orderLegCollection', [])
        for leg in legs:
            inst = leg.get('instrument', {})
            if inst.get('symbol', '').upper() == sym_upper:
                results.append({
                    'id': order.get('orderId'),
                    'status': order.get('status'),
                    'instruction': leg.get('instruction'),
                    'qty': leg.get('quantity'),
                    'type': order.get('orderType'),
                    'strategy': order.get('orderStrategyType', 'SINGLE'),
                    'entered': order.get('enteredTime', '')[-12:],
                    'closed': order.get('closeTime', '')[-12:],
                    'stop_price': order.get('stopPrice', ''),
                    'limit_price': order.get('price', ''),
                })
                break
        
        if include_children:
            for child in order.get('childOrderStrategies', []):
                child_results = self._extract_orders_recursive(child, symbol, include_children=True)
                results.extend(child_results)
        
        return results

    async def _dump_all_orders_for_symbol(self, symbol: str) -> list:
        """Dump all orders for a symbol from last 24h for debugging, including nested OCO/bracket children."""
        try:
            if not await self._ensure_valid_token():
                return []
            from datetime import datetime, timedelta
            to_date = datetime.now()
            from_date = to_date - timedelta(days=1)
            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                params={
                    'fromEnteredTime': from_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'toEnteredTime': to_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                }
            )
            if response.status_code != 200:
                return []
            orders = response.json()
            results = []
            for order in orders:
                results.extend(self._extract_orders_recursive(order, symbol))
            return results
        except Exception:
            return []

    async def _cancel_all_open_orders_for_symbol(self, symbol: str) -> int:
        """Cancel ALL non-terminal orders for a symbol, including nested OCO/bracket children.
        Walks into childOrderStrategies to find hidden WORKING OCO legs.
        Returns the number of orders cancelled."""
        try:
            if not await self._ensure_valid_token():
                return 0
            
            import time as _time
            if hasattr(self, '_global_429_until') and _time.time() < self._global_429_until:
                wait_remaining = self._global_429_until - _time.time()
                if wait_remaining > 10:
                    print(f"[{self.name}] ⚠️ Skipping cancel check — 429 backoff ({wait_remaining:.0f}s remaining)")
                    return 0
                else:
                    await asyncio.sleep(min(wait_remaining, 5))
            
            from datetime import datetime, timedelta
            to_date = datetime.now()
            from_date = to_date - timedelta(days=7)
            
            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                params={
                    'fromEnteredTime': from_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'toEnteredTime': to_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                }
            )
            
            if response.status_code != 200:
                print(f"[{self.name}] ⚠️ Failed to fetch orders for cancel check: {response.status_code}")
                return 0
            
            orders = response.json()
            cancellable_statuses = {'WORKING', 'ACCEPTED', 'QUEUED', 'PENDING_ACTIVATION', 'AWAITING_PARENT_ORDER', 'AWAITING_CONDITION', 'AWAITING_STOP_CONDITION', 'PENDING_ACKNOWLEDGEMENT'}
            cancelled_count = 0
            cancelled_ids = set()
            
            for order in orders:
                all_matches = self._extract_orders_recursive(order, symbol)
                for match in all_matches:
                    match_status = match.get('status', '')
                    match_id = str(match.get('id', ''))
                    if match_status in cancellable_statuses and match_id not in cancelled_ids:
                        instruction = match.get('instruction', '')
                        qty = match.get('qty', 0)
                        strategy = match.get('strategy', 'SINGLE')
                        stop_price = match.get('stop_price', '')
                        limit_price = match.get('limit_price', '')
                        price_info = f"stop=${stop_price}" if stop_price else f"limit=${limit_price}" if limit_price else "MARKET"
                        print(f"[{self.name}] 🧹 Cancelling {match_status} {strategy} order {match_id}: {instruction} {qty} {symbol} ({price_info})")
                        cancel_result = await self.cancel_order(match_id)
                        print(f"[{self.name}]   Result: {cancel_result.get('message', '')}")
                        cancelled_ids.add(match_id)
                        cancelled_count += 1
            
            return cancelled_count
        except asyncio.TimeoutError:
            print(f"[{self.name}] ⚠️ _cancel_all_open_orders_for_symbol({symbol}) timed out — API overloaded")
            return 0
        except Exception as e:
            print(f"[{self.name}] ⚠️ _cancel_all_open_orders_for_symbol({symbol}) failed: {type(e).__name__}: {e}")
            return 0

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an existing order"""
        try:
            if not await self._ensure_valid_token():
                return {'success': False, 'message': 'Not authenticated with Schwab'}

            response = await self._make_request(
                'DELETE',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders/{order_id}",
                is_exit_order=True
            )

            if response.status_code in [200, 201, 202, 204]:
                if self._data_hub:
                    self._data_hub.invalidate_all()
                return {'success': True, 'message': f'Order {order_id} cancelled successfully'}
            else:
                return {'success': False, 'message': f'Cancel failed: {response.status_code} - {response.text}'}

        except Exception as e:
            return {'success': False, 'message': f'Exception cancelling order: {str(e)}'}

    async def replace_order(self, order_id: str, new_order_payload: Dict) -> Dict[str, Any]:
        """Replace an existing order with a new one"""
        try:
            if not await self._ensure_valid_token():
                return {'success': False, 'order_id': None, 'message': 'Not authenticated with Schwab'}

            headers = {
                'Content-Type': 'application/json'
            }

            response = await self._make_request(
                'PUT',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders/{order_id}",
                is_exit_order=True,
                headers=headers,
                json=new_order_payload
            )

            if response.status_code in [200, 201, 202, 204]:
                new_order_id = response.headers.get('Location', '').split('/')[-1] if response.headers.get('Location') else order_id
                if self._data_hub:
                    self._data_hub.invalidate_all()
                return {'success': True, 'order_id': new_order_id, 'message': f'Order {order_id} replaced with {new_order_id}'}
            else:
                return {'success': False, 'order_id': None, 'message': f'Replace failed: {response.status_code} - {response.text}'}

        except Exception as e:
            return {'success': False, 'order_id': None, 'message': f'Exception replacing order: {str(e)}'}

    async def get_order_status(self, order_id: str, is_critical: bool = False) -> Optional[Dict[str, Any]]:
        """Get status of a specific order"""
        try:
            if not await self._ensure_valid_token():
                return None

            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders/{order_id}",
                is_exit_order=is_critical
            )

            if response.status_code == 200:
                order = response.json()

                status_map = {
                    'WORKING': 'pending',
                    'FILLED': 'filled',
                    'CANCELED': 'cancelled',
                    'REJECTED': 'rejected',
                    'EXPIRED': 'expired',
                    'PENDING_ACTIVATION': 'pending_activation',
                    'QUEUED': 'pending',
                    'ACCEPTED': 'pending',
                    'PENDING_CANCEL': 'pending',
                    'PENDING_REPLACE': 'pending',
                    'AWAITING_PARENT_ORDER': 'pending',
                    'AWAITING_CONDITION': 'pending',
                    'AWAITING_STOP_CONDITION': 'pending',
                    'AWAITING_MANUAL_REVIEW': 'pending',
                    'PARTIALLY_FILLED': 'partial',
                    'REPLACED': 'cancelled',
                }

                schwab_status = order.get('status', 'UNKNOWN')
                mapped_status = status_map.get(schwab_status, schwab_status.lower())

                filled_quantity = int(order.get('filledQuantity', 0))
                total_quantity = int(order.get('quantity', 0))
                remaining_quantity = total_quantity - filled_quantity

                avg_price = 0.0
                total_cost = 0.0
                total_filled = 0
                activities = order.get('orderActivityCollection', [])
                for activity in activities:
                    if activity.get('activityType') == 'EXECUTION':
                        for exec_leg in activity.get('executionLegs', []):
                            leg_qty = int(exec_leg.get('quantity', 0))
                            leg_price = float(exec_leg.get('price', 0))
                            total_filled += leg_qty
                            total_cost += leg_qty * leg_price
                if total_filled > 0:
                    avg_price = total_cost / total_filled
                elif filled_quantity > 0:
                    avg_price = float(order.get('price', 0))

                result = {
                    'status': mapped_status,
                    'filled_quantity': filled_quantity,
                    'remaining_quantity': remaining_quantity,
                    'average_price': avg_price
                }
                if mapped_status in ('rejected', 'cancelled'):
                    cancel_time = order.get('cancelTime', '')
                    status_desc = order.get('statusDescription', '')
                    close_time = order.get('closeTime', '')
                    result['cancel_time'] = cancel_time
                    result['status_description'] = status_desc
                    result['close_time'] = close_time
                    result['schwab_raw_status'] = schwab_status

                if order.get('orderStrategyType') == 'OCO':
                    children = order.get('childOrderStrategies', [])
                    for child in children:
                        child_status = (child.get('status') or '').upper()
                        child_type = (child.get('orderType') or '').upper()
                        if child_status == 'FILLED':
                            result['fill_leg'] = 'pt' if child_type == 'LIMIT' else 'sl'
                            child_activities = child.get('orderActivityCollection', [])
                            child_cost, child_filled = 0.0, 0
                            for act in child_activities:
                                if act.get('activityType') == 'EXECUTION':
                                    for el in act.get('executionLegs', []):
                                        child_filled += int(el.get('quantity', 0))
                                        child_cost += int(el.get('quantity', 0)) * float(el.get('price', 0))
                            if child_filled > 0:
                                result['fill_leg_qty'] = child_filled
                                result['fill_leg_price'] = child_cost / child_filled
                            break

                return result

            else:
                print(f"[{self.name}] Error getting order status: {response.status_code}")
                return None

        except Exception as e:
            print(f"[{self.name}] Exception getting order status: {e}")
            return None


BrokerFactory.register_broker('SCHWAB', SchwabBroker)
