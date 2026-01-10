"""
Charles Schwab Broker Implementation
OAuth2 authentication with official Schwab API
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

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
            'redirect_uri': self.redirect_uri,
            'scope': 'readonly'
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
        """Refresh the access token using refresh token"""
        try:
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
                    print(f"[{self.name}] ✓ Access token refreshed")
                    return True
                else:
                    print(f"[{self.name}] ❌ Token refresh failed: {response.status_code}")
                    return False
                    
        except Exception as e:
            print(f"[{self.name}] ❌ Error refreshing token: {e}")
            return False
    
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
    
    async def _ensure_valid_token(self) -> bool:
        """Ensure we have a valid access token"""
        if self.token_expiry and datetime.now().timestamp() >= (self.token_expiry - 60):
            return await self._refresh_access_token()
        return bool(self.access_token)
    
    async def disconnect(self):
        """Disconnect from Schwab"""
        self.connected = False
        self.access_token = None
        print(f"[{self.name}] Disconnected")
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        try:
            if not await self._ensure_valid_token():
                return {'buying_power': 0, 'cash': 0, 'portfolio_value': 0}
            
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
                    
                    return {
                        'buying_power': float(balances.get('buyingPower', 0)),
                        'cash': float(balances.get('cashBalance', 0)),
                        'portfolio_value': float(balances.get('liquidationValue', 0))
                    }
                    
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
        
        return {'buying_power': 0, 'cash': 0, 'portfolio_value': 0}
    
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
            
            instruction = "BUY" if action.upper() == "BTO" else "SELL"
            order_type = "LIMIT" if price else "MARKET"
            
            order_payload = {
                "orderStrategyType": "SINGLE",
                "orderType": order_type,
                "session": "NORMAL",
                "duration": "DAY",
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
                order_payload["price"] = price
            
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
            
            import httpx
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                    headers=headers,
                    json=order_payload
                )
                
                if response.status_code in [200, 201]:
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
            
            order_payload = {
                "orderStrategyType": "SINGLE",
                "orderType": order_type,
                "session": "NORMAL",
                "duration": "DAY",
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
                order_payload["price"] = price
            
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
            
            import httpx
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.BASE_URL}/accounts/{self.account_hash}/orders",
                    headers=headers,
                    json=order_payload
                )
                
                if response.status_code in [200, 201]:
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
        Format: SYMBOL + YYMMDD + C/P + strike*1000 (8 digits)
        Example: AAPL 240119C00150000 = AAPL Jan 19 2024 $150 Call
        """
        parts = expiry.split("-")
        if len(parts) == 3:
            year = parts[0][2:]
            month = parts[1]
            day = parts[2]
        else:
            return f"{underlying}_INVALID_EXPIRY"
        
        strike_int = int(strike * 1000)
        strike_str = f"{strike_int:08d}"
        
        return f"{underlying.upper()}{year}{month}{day}{call_put.upper()}{strike_str}"
    
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
                        current_price = pos.get('marketValue', 0) / qty if qty else 0
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
                        
                        # Parse option details if applicable
                        if asset_type == 'option':
                            position_data['strike'] = float(instrument.get('strikePrice', 0))
                            position_data['expiry'] = instrument.get('expirationDate', '')[:10] if instrument.get('expirationDate') else ''
                            position_data['direction'] = instrument.get('putCall', '')[0] if instrument.get('putCall') else ''
                            position_data['symbol'] = instrument.get('underlyingSymbol', symbol)
                        
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
                        
                        # Get fill info from order activities
                        activities = order.get('orderActivityCollection', [])
                        filled_price = 0
                        filled_qty = 0
                        filled_time = order.get('closeTime', '') or order.get('enteredTime', '')
                        
                        for activity in activities:
                            if activity.get('activityType') == 'EXECUTION':
                                exec_legs = activity.get('executionLegs', [])
                                for exec_leg in exec_legs:
                                    filled_price = float(exec_leg.get('price', 0))
                                    filled_qty = int(exec_leg.get('quantity', 0))
                                    filled_time = exec_leg.get('time', filled_time)
                        
                        if filled_qty == 0:
                            filled_qty = int(order.get('filledQuantity', leg.get('quantity', 0)))
                        if filled_price == 0:
                            filled_price = float(order.get('price', 0))
                        
                        order_data = {
                            'order_id': str(order.get('orderId', '')),
                            'symbol': underlying,
                            'quantity': filled_qty,
                            'filled_price': filled_price,
                            'action': leg.get('instruction', ''),  # BUY/SELL
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


BrokerFactory.register_broker('SCHWAB', SchwabBroker)
