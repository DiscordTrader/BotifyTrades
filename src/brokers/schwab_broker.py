"""
Charles Schwab Broker Implementation
OAuth2 authentication with official Schwab API
"""

import os
import sys
import json
import asyncio
import logging
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
        self.dry_run = config.get('dry_run', True)
        self._token_refresh_lock = asyncio.Lock()
        self._token_refresh_failures = 0
        self._token_refresh_backoff_until = 0
        self._token_auth_dead = False
        
        self.client_id = config.get('client_id', '')
        self.client_secret = config.get('client_secret', '')
        self.redirect_uri = config.get('redirect_uri', 'https://127.0.0.1')
        self.token_file = config.get('token_file', 'schwab_token.json')
    
    async def connect(self) -> bool:
        """Connect to Schwab using stored tokens"""
        try:
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

    async def _make_request(self, method, url, **kwargs):
        """Make HTTP request with rate limit and token refresh handling"""
        import httpx

        headers = kwargs.pop('headers', {})
        if 'Authorization' not in headers:
            headers['Authorization'] = f'Bearer {self.access_token}'
        if 'Accept' not in headers:
            headers['Accept'] = 'application/json'

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, headers=headers, **kwargs)

            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', '60'))
                print(f"[{self.name}] Rate limited, waiting {retry_after}s...")
                await asyncio.sleep(retry_after)
                await self._ensure_valid_token()
                headers['Authorization'] = f'Bearer {self.access_token}'
                response = await client.request(method, url, headers=headers, **kwargs)

            elif response.status_code == 401:
                async with self._token_refresh_lock:
                    refreshed = await self._refresh_access_token()
                if refreshed:
                    headers['Authorization'] = f'Bearer {self.access_token}'
                    response = await client.request(method, url, headers=headers, **kwargs)

            return response
    
    def _get_session_type(self) -> str:
        """Get order session type based on extended hours setting.
        
        Schwab session types:
        - NORMAL: Regular market hours only (9:30 AM - 4:00 PM ET)
        - SEAMLESS: Extended hours (pre-market + regular + after-hours)
        - AM: Pre-market only
        - PM: After-hours only
        
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
    
    async def disconnect(self):
        """Disconnect from Schwab"""
        self.connected = False
        self.access_token = None
        print(f"[{self.name}] Disconnected")
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information including settled cash for good faith violation prevention"""
        try:
            if not await self._ensure_valid_token():
                return {'buying_power': 0, 'cash': 0, 'portfolio_value': 0, 'settled_cash': 0, 'unsettled_cash': 0}
            
            import httpx
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/accounts/{self.account_hash}",
                    headers=headers,
                    params={'fields': 'positions'}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    account = data.get('securitiesAccount', {})
                    balances = account.get('currentBalances', {})
                    
                    buying_power = float(balances.get('buyingPower', 0))
                    cash_balance = float(balances.get('cashBalance', 0))
                    portfolio_value = float(balances.get('liquidationValue', 0))
                    
                    # SETTLED CASH: Schwab provides several relevant fields
                    # - cashAvailableForTrading: Most conservative (settled funds)
                    # - availableFunds: May include unsettled
                    # - moneyMarketFund: Cash in money market
                    cash_available_for_trading = float(balances.get('cashAvailableForTrading', 0))
                    available_funds = float(balances.get('availableFunds', 0))
                    
                    # Use cashAvailableForTrading as settled cash if available, else fall back to availableFunds
                    if cash_available_for_trading > 0:
                        settled_cash = cash_available_for_trading
                    else:
                        # Fall back: use the more conservative of availableFunds or cashBalance
                        settled_cash = min(available_funds, cash_balance) if available_funds > 0 else cash_balance
                    
                    # Unsettled = total cash - settled
                    unsettled_cash = max(0, cash_balance - settled_cash)
                    
                    return {
                        'buying_power': buying_power,
                        'cash': cash_balance,
                        'cash_balance': cash_balance,
                        'portfolio_value': portfolio_value,
                        'settled_cash': settled_cash,
                        'unsettled_cash': unsettled_cash,
                        'cashAvailableForTrading': cash_available_for_trading,
                        'availableFunds': available_funds,
                        'options_buying_power': float(balances.get('optionBuyingPower', buying_power)),
                        'account_type': account.get('type', 'UNKNOWN'),
                        'account_id': self.account_number or ''
                    }
                    
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
        
        return {'buying_power': 0, 'cash': 0, 'portfolio_value': 0, 'settled_cash': 0, 'unsettled_cash': 0}
    
    async def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        try:
            if not await self._ensure_valid_token():
                return {}
            
            import httpx
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/accounts/{self.account_hash}",
                    headers=headers,
                    params={'fields': 'positions'}
                )
                
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
                    return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
        
        return {}
    
    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None
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
            
            response = await self._make_request(
                'POST',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
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
        price: Optional[float] = None
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
            order_type = "LIMIT" if price else "MARKET"
            
            session = self._get_session_type()
            
            is_exit = (instruction == "SELL_TO_CLOSE")
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
            
            response = await self._make_request(
                'POST',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
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
        """Get current price for a symbol"""
        try:
            if not await self._ensure_valid_token():
                return None
            
            import httpx
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.schwabapi.com/marketdata/v1/quotes",
                    headers=headers,
                    params={'symbols': symbol}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if symbol in data:
                        quote = data[symbol].get('quote', {})
                        return float(quote.get('lastPrice', 0))
                        
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
        
        return None
    
    async def get_quote_detailed(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get detailed quote data for signal verification (bid, ask, last, volume)"""
        try:
            if not await self._ensure_valid_token():
                return None
            
            import httpx
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.schwabapi.com/marketdata/v1/quotes",
                    headers=headers,
                    params={'symbols': symbol}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if symbol in data:
                        quote = data[symbol].get('quote', {})
                        return {
                            'bid': float(quote.get('bidPrice', 0) or 0),
                            'ask': float(quote.get('askPrice', 0) or 0),
                            'last': float(quote.get('lastPrice', 0) or 0),
                            'price': float(quote.get('lastPrice', 0) or 0),
                            'volume': int(quote.get('totalVolume', 0) or 0)
                        }
                        
        except Exception as e:
            print(f"[{self.name}] Error getting detailed quote for {symbol}: {e}")
        
        return None
    
    async def get_option_quote(self, underlying: str, strike: float, expiry: str, opt_type: str) -> Optional[Dict[str, Any]]:
        """Get option quote for signal verification"""
        try:
            if not await self._ensure_valid_token():
                return None
            
            option_symbol = self._build_option_symbol(underlying, expiry, strike, opt_type[0])
            
            import httpx
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.schwabapi.com/marketdata/v1/quotes",
                    headers=headers,
                    params={'symbols': option_symbol}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if option_symbol in data:
                        quote = data[option_symbol].get('quote', {})
                        return {
                            'bid': float(quote.get('bidPrice', 0) or 0),
                            'ask': float(quote.get('askPrice', 0) or 0),
                            'last': float(quote.get('lastPrice', 0) or 0),
                            'price': float(quote.get('lastPrice', 0) or 0),
                            'volume': int(quote.get('totalVolume', 0) or 0),
                            'open_interest': int(quote.get('openInterest', 0) or 0),
                            'implied_volatility': float(quote.get('volatility', 0) or 0)
                        }
                        
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
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get stock quote for current price
                stock_price = None
                try:
                    quote_response = await client.get(
                        f"https://api.schwabapi.com/marketdata/v1/quotes",
                        headers=headers,
                        params={'symbols': symbol}
                    )
                    if quote_response.status_code == 200:
                        quote_data = quote_response.json()
                        if symbol in quote_data:
                            stock_price = float(quote_data[symbol].get('quote', {}).get('lastPrice', 0) or 0)
                except:
                    pass
                
                # Get option chain
                response = await client.get(
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
                                calls.append({
                                    'strike': float(opt.get('strikePrice', 0)),
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
                                })
                    
                    # Parse put options
                    put_exp_map = data.get('putExpDateMap', {})
                    for exp_date, strikes in put_exp_map.items():
                        for strike_str, options in strikes.items():
                            for opt in options:
                                puts.append({
                                    'strike': float(opt.get('strikePrice', 0)),
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
            if not await self._ensure_valid_token():
                return []
            
            if not self.account_hash:
                print(f"[{self.name}] No account_hash - cannot fetch positions")
                return []
            
            import httpx
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/accounts/{self.account_hash}",
                    headers=headers,
                    params={'fields': 'positions'}
                )
                
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
                        
                        # For options, marketValue is total position value; divide by 100 to get per-contract price
                        if asset_type == 'option':
                            current_price = market_value / (qty * 100) if qty else 0
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
                    
                    return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting detailed positions: {e}")
        
        return []
    
    async def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Get open/pending orders"""
        try:
            if not await self._ensure_valid_token():
                return []
            
            if not self.account_hash:
                print(f"[{self.name}] No account_hash - cannot fetch pending orders")
                return []
            
            import httpx
            from datetime import datetime, timedelta
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            # Schwab requires date range for orders query
            to_date = datetime.now()
            from_date = to_date - timedelta(days=7)
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                    headers=headers,
                    params={
                        'fromEnteredTime': from_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                        'toEnteredTime': to_date.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                        'status': 'WORKING'  # Only get working/pending orders
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
                            'action': leg.get('instruction', ''),  # BUY/SELL
                            'status': order.get('status', ''),
                            'order_type': order.get('orderType', ''),
                            'entered_time': order.get('enteredTime', '')
                        })
                    
                    return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting pending orders: {e}")
        
        return []
    
    async def get_order_history(self, count: int = 50) -> List[Dict[str, Any]]:
        """Get filled order history for sync"""
        try:
            if not await self._ensure_valid_token():
                return []
            
            if not self.account_hash:
                print(f"[{self.name}] No account_hash - cannot fetch order history")
                return []
            
            import httpx
            from datetime import datetime, timedelta
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json'
            }
            
            # Query last 30 days of orders
            to_date = datetime.now()
            from_date = to_date - timedelta(days=30)
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                    headers=headers,
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
                        
                        # Get symbol - for options, extract underlying
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
                        
                        # Add option details
                        if asset_type == 'option':
                            order_data['strike'] = float(instrument.get('strikePrice', 0))
                            order_data['expiry'] = instrument.get('expirationDate', '')[:10] if instrument.get('expirationDate') else ''
                            order_data['direction'] = instrument.get('putCall', '')[0] if instrument.get('putCall') else ''
                        
                        result.append(order_data)
                    
                    return result
                    
        except Exception as e:
            print(f"[{self.name}] Error getting order history: {e}")
        
        return []

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an existing order"""
        try:
            if not await self._ensure_valid_token():
                return {'success': False, 'message': 'Not authenticated with Schwab'}

            response = await self._make_request(
                'DELETE',
                f"{self.BASE_URL}/accounts/{self.account_hash}/orders/{order_id}"
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
