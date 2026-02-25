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
import threading
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
        self._token_refresh_lock = asyncio.Lock()
        self._token_refresh_failures = 0
        self._token_refresh_backoff_until = 0
        self._token_auth_dead = False
        
        self.client_id = config.get('client_id', '')
        self.client_secret = config.get('client_secret', '')
        self.redirect_uri = config.get('redirect_uri', 'https://127.0.0.1')
        self.token_file = config.get('token_file', 'schwab_token.json')
        
        self._api_rate_lock = threading.Lock()
        self._last_api_call = 0
        self._min_api_interval = 1.0
        self._last_valid_positions = []
        self._last_valid_positions_time = 0
        self._position_cache_ttl = 60
        
        self._global_429_until = 0
        self._global_429_lock = threading.Lock()
        self._consecutive_429s = 0
        self._last_successful_call = 0

        self._streaming_client = None
        self._data_hub = None
        self._api_calls_this_minute = 0
        self._api_calls_minute_start = 0
        self._api_budget_lock = threading.Lock()
        self._API_BUDGET_LIMIT = 120
        self._API_BUDGET_THROTTLE = 96
        self._API_BUDGET_CRITICAL = 108
    
    async def connect(self) -> bool:
        """Connect to Schwab using stored tokens"""
        try:
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
            asset_type = pos.get('assetType', 'EQUITY') if isinstance(pos, dict) else 'EQUITY'
            if asset_type == 'OPTION' or len(symbol) > 10:
                option_symbols.append(symbol)
            else:
                equity_symbols.append(symbol)
        if equity_symbols:
            await self._streaming_client.subscribe_equities(equity_symbols)
        if option_symbols:
            await self._streaming_client.subscribe_options(option_symbols)

    def get_hub_quote(self, symbol: str) -> Optional[float]:
        if self._data_hub:
            price = self._data_hub.get_quote_price(symbol)
            if price and price > 0:
                return price
        return None

    def get_hub_quote_detailed(self, symbol: str) -> Optional[Dict[str, Any]]:
        if self._data_hub:
            return self._data_hub.get_quote_detailed(symbol)
        return None

    def _track_api_call(self) -> bool:
        with self._api_budget_lock:
            now = time.time()
            if now - self._api_calls_minute_start >= 60:
                self._api_calls_this_minute = 0
                self._api_calls_minute_start = now
            self._api_calls_this_minute += 1
            return self._api_calls_this_minute <= self._API_BUDGET_LIMIT

    def _get_api_usage(self) -> int:
        with self._api_budget_lock:
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
                    print(f"[{self.name}] Tokens loaded via token manager (auto-refresh enabled)")
                    return True
            except (ImportError, Exception) as e:
                # Token manager not available or error - fallback to file
                if not isinstance(e, ImportError):
                    print(f"[{self.name}] Token manager unavailable: {e}, using file fallback")
            
            # Fallback: load directly from file
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r') as f:
                    data = json.load(f)
                    self.access_token = data.get('access_token')
                    self.refresh_token = data.get('refresh_token')
                    self.token_expiry = data.get('token_expiry')
                    return bool(self.access_token)
        except Exception as e:
            print(f"[{self.name}] Error loading tokens: {e}")
        return False
    
    def _save_tokens(self):
        """Save tokens to file"""
        try:
            data = {
                'access_token': self.access_token,
                'refresh_token': self.refresh_token,
                'token_expiry': self.token_expiry
            }
            with open(self.token_file, 'w') as f:
                json.dump(data, f)
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
            
            async with httpx.AsyncClient() as client:
                response = await client.post(self.TOKEN_URL, headers=headers, data=data)
                
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
            
            async with httpx.AsyncClient() as client:
                response = await client.post(self.TOKEN_URL, headers=headers, data=data)
                
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
                    response = await client.post(self.TOKEN_URL, headers=headers, data=data)
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
                    if 'invalid_grant' in error_text:
                        self._token_auth_dead = True
                        self.connected = False
                        print(f"[{self.name}] ❌ Refresh token expired or revoked. Re-authentication required. (Token refresh suspended until re-auth)")
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
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/accounts/accountNumbers",
                    headers=headers
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
            async with self._token_refresh_lock:
                if self.token_expiry and datetime.now().timestamp() >= (self.token_expiry - 120):
                    return await self._refresh_access_token()
        return True

    def _format_price(self, price: float) -> str:
        """Format price for Schwab API.
        For prices < $1: truncate to 4 decimal places
        For prices >= $1: truncate to 2 decimal places
        """
        import math
        if price < 1.0:
            truncated = math.floor(price * 10000) / 10000
            return f"{truncated:.4f}"
        else:
            truncated = math.floor(price * 100) / 100
            return f"{truncated:.2f}"

    async def _make_request(self, method, url, is_exit_order: bool = False, is_entry_order: bool = False, **kwargs):
        """Make HTTP request with rate limit, budget tracking, and token refresh handling"""
        import httpx

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

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, headers=headers, **kwargs)

            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', '60'))
                self._register_429(retry_after)
                
                if is_exit_order:
                    wait = min(retry_after, 10)
                    print(f"[{self.name}] 🔴 EXIT ORDER 429 - short wait {wait}s then retry")
                    await asyncio.sleep(wait)
                elif is_entry_order:
                    wait = min(retry_after, 15)
                    print(f"[{self.name}] ⏳ BUY ORDER 429 - waiting {wait}s then retry")
                    await asyncio.sleep(wait)
                else:
                    await asyncio.sleep(retry_after)
                
                await self._ensure_valid_token()
                headers['Authorization'] = f'Bearer {self.access_token}'
                response = await client.request(method, url, headers=headers, **kwargs)
                
                if response.status_code == 429:
                    self._register_429(retry_after)
                    return response
                else:
                    self._register_success()

            elif response.status_code == 401:
                async with self._token_refresh_lock:
                    refreshed = await self._refresh_access_token()
                if refreshed:
                    headers['Authorization'] = f'Bearer {self.access_token}'
                    response = await client.request(method, url, headers=headers, **kwargs)
            
            elif response.status_code in [200, 201, 202]:
                self._register_success()

            return response
    
    def _get_session_type(self) -> str:
        """Get order session type based on extended hours setting.
        
        Schwab session types:
        - NORMAL: Regular market hours only (9:30 AM - 4:00 PM ET)
        - SEAMLESS: Extended hours (pre-market + regular + after-hours)
        - AM: Pre-market only (7:00 AM - 9:28 AM ET)
        - PM: After-hours only (4:02 PM - 8:00 PM ET)
        
        Returns:
            Session type string for order payload
        """
        try:
            from gui_app.database import get_broker_extended_hours
            if get_broker_extended_hours('schwab'):
                print(f"[{self.name}] Extended hours ENABLED - using SEAMLESS session")
                return "SEAMLESS"
        except ImportError:
            pass
        except Exception as e:
            print(f"[{self.name}] Error checking extended hours setting: {e}")
        return "NORMAL"

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
            if self._should_skip_non_critical():
                if hasattr(self, '_last_account_info') and self._last_account_info:
                    return dict(self._last_account_info)
            
            if not await self._ensure_valid_token():
                return {'buying_power': 0, 'cash': 0, 'portfolio_value': 0, 'settled_cash': 0, 'unsettled_cash': 0}
            
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
                return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
        
        return {'buying_power': 0, 'cash': 0, 'portfolio_value': 0, 'settled_cash': 0, 'unsettled_cash': 0}
    
    def _register_429(self, retry_after: int = 60):
        """Register a 429 error - sets global backoff for ALL Schwab API calls"""
        with self._global_429_lock:
            self._consecutive_429s += 1
            backoff = min(retry_after * (1 + 0.5 * (self._consecutive_429s - 1)), 180)
            self._global_429_until = time.time() + backoff
            print(f"[{self.name}] ⚠️ GLOBAL 429 BACKOFF: {backoff:.0f}s (consecutive: {self._consecutive_429s})")
    
    def _register_success(self):
        """Register a successful API call - resets 429 counter"""
        with self._global_429_lock:
            self._consecutive_429s = 0
            self._last_successful_call = time.time()
    
    def _is_in_429_backoff(self) -> float:
        """Check if we're in global 429 backoff. Returns seconds remaining, 0 if clear."""
        with self._global_429_lock:
            remaining = self._global_429_until - time.time()
            return max(0, remaining)
    
    def _rate_limit(self):
        """Enforce minimum interval between Schwab API calls to prevent 429 errors"""
        with self._api_rate_lock:
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
        
        with self._api_rate_lock:
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
                    if (time.time() - self._last_valid_positions_time) < self._position_cache_ttl:
                        print(f"[{self.name}] ⚠️ get_positions returned 0 but cache exists - using cached")
                        return dict(self._last_positions_simple)
                return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
        
        if hasattr(self, '_last_positions_simple') and self._last_positions_simple:
            return dict(self._last_positions_simple)
        return {}
    
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
            order_type = "LIMIT" if price else "MARKET"
            
            session = self._get_session_type()
            
            is_exit = instruction in ("SELL", "SELL_SHORT", "BUY_TO_COVER")
            duration = "GOOD_TILL_CANCEL" if is_exit else "DAY"
            
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
            
            is_exit = instruction in ("SELL", "SELL_SHORT", "BUY_TO_COVER")
            is_entry = instruction in ("BUY", "BUY_TO_COVER") and not is_exit
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
                return OrderResult(
                    success=False,
                    message=f"Order failed: {response.status_code} - {error_msg}",
                    symbol=symbol,
                    action=action
                )
                    
        except Exception as e:
            return OrderResult(
                success=False,
                message=f"Exception: {str(e)}",
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
            
            if "/" in expiry:
                parts = expiry.split("/")
                if len(parts) == 2:
                    m, d = parts
                    y = datetime.now().year
                    expiry_formatted = f"{y:04d}-{int(m):02d}-{int(d):02d}"
                elif len(parts) == 3:
                    m, d, y = parts
                    if len(y) == 2:
                        y = f"20{y}"
                    expiry_formatted = f"{y}-{int(m):02d}-{int(d):02d}"
                else:
                    expiry_formatted = expiry
            else:
                expiry_formatted = expiry
            
            call_put = "C" if option_type.upper().startswith("C") else "P"
            
            option_symbol = self._build_option_symbol(symbol, expiry_formatted, strike, call_put)
            
            instruction = "BUY_TO_OPEN" if action.upper() == "BTO" else "SELL_TO_CLOSE"
            
            if not price:
                print(f"[{self.name}] ⚠️ Options require LIMIT orders on Schwab - no price provided, attempting mid-price lookup")
                try:
                    quote = await self.get_option_quote(symbol, strike, expiry_formatted, option_type)
                    if quote and quote.get('bid') and quote.get('ask'):
                        mid_price = round((quote['bid'] + quote['ask']) / 2, 2)
                        price = mid_price
                        print(f"[{self.name}] ✓ Using mid-price ${mid_price:.2f} (bid: ${quote['bid']:.2f}, ask: ${quote['ask']:.2f})")
                    elif quote and quote.get('last'):
                        price = quote['last']
                        print(f"[{self.name}] ✓ Using last price ${price:.2f}")
                except Exception as quote_err:
                    print(f"[{self.name}] ⚠️ Quote lookup failed: {quote_err}")
            
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
            
            if is_near_expiry:
                duration = "DAY"
            elif is_exit:
                duration = "GOOD_TILL_CANCEL"
            else:
                duration = "DAY"
            
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
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    message=f"Option order placed: {action} {quantity} {option_symbol}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                error_msg = response.text
                return OrderResult(
                    success=False,
                    message=f"Order failed: {response.status_code} - {error_msg}",
                    symbol=symbol,
                    action=action
                )
                    
        except Exception as e:
            return OrderResult(
                success=False,
                message=f"Exception: {str(e)}",
                symbol=symbol,
                action=action
            )
    
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
        
        # OCC format requires underlying to be 6 characters, left-justified, space-padded
        underlying_padded = underlying.upper().ljust(6)
        
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
                params={'symbols': symbol}
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
                params={'symbols': symbol}
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
    
    async def get_option_quote(self, underlying: str, strike: float, expiry: str, opt_type: str) -> Optional[Dict[str, Any]]:
        """Get option quote for signal verification. Tries hub first."""
        try:
            option_symbol = self._build_option_symbol(underlying, expiry, strike, opt_type[0])

            hub_data = self.get_hub_quote_detailed(option_symbol)
            if hub_data and hub_data.get('last', 0) > 0:
                return hub_data

            if not await self._ensure_valid_token():
                return None
            
            response = await self._make_request(
                'GET',
                f"https://api.schwabapi.com/marketdata/v1/quotes",
                params={'symbols': option_symbol}
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
            
            import httpx
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
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
            
            async with httpx.AsyncClient(timeout=15.0) as client:
                import asyncio as _aio
                quote_task = client.get(
                    f"https://api.schwabapi.com/marketdata/v1/quotes",
                    headers=headers,
                    params={'symbols': symbol}
                )
                chain_task = client.get(
                    f"https://api.schwabapi.com/marketdata/v1/chains",
                    headers=headers,
                    params={
                        'symbol': symbol,
                        'contractType': 'ALL',
                        'fromDate': expiry,
                        'toDate': expiry,
                        'includeUnderlyingQuote': 'true'
                    }
                )
                quote_response, response = await _aio.gather(quote_task, chain_task, return_exceptions=True)
                
                stock_price = None
                if not isinstance(quote_response, Exception) and quote_response.status_code == 200:
                    try:
                        quote_data = quote_response.json()
                        if symbol in quote_data:
                            stock_price = float(quote_data[symbol].get('quote', {}).get('lastPrice', 0) or 0)
                    except:
                        pass
                
                if isinstance(response, Exception):
                    raise response
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Get stock price from underlying quote if not fetched
                    if not stock_price and data.get('underlyingPrice'):
                        stock_price = float(data.get('underlyingPrice', 0))
                    
                    calls = []
                    puts = []
                    
                    # Parse call options
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
                    
                    # Parse put options
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
                    
                    # Sort by strike
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
        try:
            if self._should_skip_non_critical():
                if self._data_hub:
                    cached = self._data_hub.get_positions(detailed=True)
                    if cached is not None:
                        return list(cached)
                if self._last_valid_positions and (time.time() - self._last_valid_positions_time) < self._position_cache_ttl:
                    return list(self._last_valid_positions)
            
            if not await self._ensure_valid_token():
                if self._last_valid_positions and (time.time() - self._last_valid_positions_time) < self._position_cache_ttl:
                    print(f"[{self.name}] Token refresh pending - returning {len(self._last_valid_positions)} cached positions")
                    return list(self._last_valid_positions)
                return []
            
            if not self.account_hash:
                print(f"[{self.name}] No account_hash - cannot fetch positions")
                return []
            
            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}",
                params={'fields': 'positions'}
            )
            
            if response.status_code in (429, 503) or getattr(response, '_budget_blocked', False):
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
                        position_data['symbol'] = underlying or symbol.split()[0] if symbol else symbol
                    
                    result.append(position_data)
                
                if len(result) > 0:
                    self._last_valid_positions = list(result)
                    self._last_valid_positions_time = time.time()
                    if self._data_hub:
                        try:
                            self._data_hub.update_positions(result, detailed=True, source="rest")
                        except Exception:
                            pass
                elif len(result) == 0 and self._last_valid_positions and (time.time() - self._last_valid_positions_time) < self._position_cache_ttl:
                    print(f"[{self.name}] ⚠️ API returned 0 positions but cache has {len(self._last_valid_positions)} - returning cached data")
                    return list(self._last_valid_positions)
                
                return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting detailed positions: {e}")
            if self._last_valid_positions and (time.time() - self._last_valid_positions_time) < self._position_cache_ttl:
                print(f"[{self.name}] Returning {len(self._last_valid_positions)} cached positions after error")
                return list(self._last_valid_positions)
        
        return []
    
    async def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Get open/pending orders"""
        try:
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
                return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting pending orders: {e}")
        
        return getattr(self, '_last_pending_orders', [])
    
    async def get_order_history(self, count: int = 50) -> List[Dict[str, Any]]:
        """Get filled order history for sync"""
        try:
            if not await self._ensure_valid_token():
                return []
            
            if not self.account_hash:
                print(f"[{self.name}] No account_hash - cannot fetch order history")
                return []
            
            from datetime import datetime, timedelta
            
            if self._should_skip_non_critical():
                return []
            
            to_date = datetime.now()
            from_date = to_date - timedelta(days=30)
            
            response = await self._make_request(
                'GET',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                params={
                    'fromEnteredTime': from_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'toEnteredTime': to_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                    'status': 'FILLED'
                }
            )
            
            if response.status_code == 200:
                orders = response.json()
                result = []
                
                for order in orders[:count]:
                    order_legs = order.get('orderLegCollection', [])
                    if not order_legs:
                        continue
                    
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
                            exec_legs = activity.get('executionLegs', [])
                            for exec_leg in exec_legs:
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
                    
                    instruction = leg.get('instruction', '') if leg else ''
                    
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
                    
                    result.append(order_data)
                
                return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting order history: {e}")
        
        return []

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
            order_duration = self._get_duration(duration_hint=duration, is_exit=True)

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
                    "session": session,
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
                    "session": session,
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
            entry_order_type = "LIMIT" if entry_price else "MARKET"

            entry_payload = {
                "orderStrategyType": "TRIGGER" if (stop_loss_price or profit_target_price) else "SINGLE",
                "orderType": entry_order_type,
                "session": session,
                "duration": "DAY",
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

            if has_both:
                profit_leg = {
                    "orderStrategyType": "SINGLE",
                    "session": session,
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
                    "session": session,
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
            elif has_sl_only:
                stop_child = {
                    "orderStrategyType": "SINGLE",
                    "session": session,
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
                    "session": session,
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
                return {'success': True, 'order_id': new_order_id, 'message': f'Order {order_id} replaced with {new_order_id}'}
            else:
                return {'success': False, 'order_id': None, 'message': f'Replace failed: {response.status_code} - {response.text}'}

        except Exception as e:
            return {'success': False, 'order_id': None, 'message': f'Exception replacing order: {str(e)}'}

    async def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific order"""
        try:
            if not await self._ensure_valid_token():
                return None

            import httpx

            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/accounts/{self.account_hash}/orders/{order_id}",
                    headers=headers
                )

                if response.status_code == 200:
                    order = response.json()

                    status_map = {
                        'WORKING': 'pending',
                        'FILLED': 'filled',
                        'CANCELED': 'cancelled',
                        'REJECTED': 'rejected',
                        'EXPIRED': 'expired',
                        'PENDING_ACTIVATION': 'pending',
                        'QUEUED': 'pending',
                        'ACCEPTED': 'pending'
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

                    return {
                        'status': mapped_status,
                        'filled_quantity': filled_quantity,
                        'remaining_quantity': remaining_quantity,
                        'average_price': avg_price
                    }

                else:
                    print(f"[{self.name}] Error getting order status: {response.status_code}")
                    return None

        except Exception as e:
            print(f"[{self.name}] Exception getting order status: {e}")
            return None


BrokerFactory.register_broker('SCHWAB', SchwabBroker)
