"""
Upstox Broker Implementation (India)
OAuth 2.0 based trading platform for Indian markets (NSE/BSE)
"""

import sys
import os
import asyncio
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory

try:
    from upstox_client import Configuration, ApiClient, UserApi, OrderApi, PortfolioApi, MarketQuoteApi, OptionsApi
    UPSTOX_AVAILABLE = True
except ImportError:
    UPSTOX_AVAILABLE = False
    print("[UPSTOX] Warning: upstox-python-sdk not installed. Install with: pip install upstox-python-sdk")


class UpstoxBroker(BrokerInterface):
    """Upstox broker implementation for Indian markets"""
    
    COUNTRY_CODE = 'IN'
    CURRENCY = 'INR'
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "UPSTOX"
        self.api_client = None
        self.user_api = None
        self.order_api = None
        self.portfolio_api = None
        self.quote_api = None
        self.options_api = None
        self.user_id = None
    
    @property
    def is_live(self) -> bool:
        """Upstox is always live trading"""
        return True
    
    async def connect(self) -> bool:
        """Connect to Upstox using access token"""
        try:
            if not UPSTOX_AVAILABLE:
                print(f"[{self.name}] upstox-python-sdk not installed")
                return False
            
            access_token = self.config.get('access_token')
            if not access_token:
                print(f"[{self.name}] No access token provided")
                return False
            
            print(f"[{self.name}] Connecting with access token...")
            
            configuration = Configuration()
            configuration.access_token = access_token
            
            self.api_client = ApiClient(configuration)
            self.user_api = UserApi(self.api_client)
            self.order_api = OrderApi(self.api_client)
            self.portfolio_api = PortfolioApi(self.api_client)
            self.quote_api = MarketQuoteApi(self.api_client)
            self.options_api = OptionsApi(self.api_client)
            
            profile = await asyncio.to_thread(
                self.user_api.get_profile,
                api_version='2.0'
            )
            
            if profile and profile.data:
                self.user_id = profile.data.user_id
                print(f"[{self.name}] Connected! User: {self.user_id}")
                print(f"[{self.name}] Name: {profile.data.user_name}")
                self.connected = True
                return True
            else:
                print(f"[{self.name}] Failed to get user profile")
                return False
                
        except Exception as e:
            print(f"[{self.name}] Connection failed: {e}")
            self.connected = False
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from Upstox"""
        self.api_client = None
        self.connected = False
        print(f"[{self.name}] Disconnected")
        return True
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        if not self.user_api:
            return {}
        
        try:
            funds = await asyncio.to_thread(
                self.user_api.get_fund_and_margin,
                api_version='2.0'
            )
            return {
                'user_id': self.user_id,
                'currency': self.CURRENCY,
                'funds': funds.data if funds else None
            }
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            return {}
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions"""
        if not self.portfolio_api:
            return []
        
        try:
            positions = await asyncio.to_thread(
                self.portfolio_api.get_positions,
                api_version='2.0'
            )
            return positions.data if positions and positions.data else []
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return []
    
    async def place_order(self, symbol: str, action: str, quantity: int,
                          order_type: str = 'market', price: float = None,
                          product_type: str = 'INTRADAY', **kwargs) -> OrderResult:
        """Place an order on Upstox using PlaceOrderRequest body"""
        if not self.order_api:
            return OrderResult(success=False, message="Not connected")
        
        try:
            from upstox_client import PlaceOrderRequest
            
            transaction_type = 'BUY' if action.upper() in ('BTO', 'BUY') else 'SELL'
            upstox_order_type = 'MARKET' if order_type == 'market' else 'LIMIT'
            product = 'I' if product_type == 'INTRADAY' else 'D'
            
            body = PlaceOrderRequest(
                quantity=int(quantity),
                product=product,
                validity='DAY',
                price=float(price) if price and upstox_order_type == 'LIMIT' else 0.0,
                instrument_token=symbol,
                order_type=upstox_order_type,
                transaction_type=transaction_type,
                disclosed_quantity=0,
                trigger_price=0.0,
                is_amo=False
            )
            
            print(f"[{self.name}] Order body: {transaction_type} {quantity} {symbol} @ {price or 'MARKET'}")
            
            result = await asyncio.to_thread(
                self.order_api.place_order,
                body,
                api_version='2.0'
            )
            
            order_id = ''
            if result and hasattr(result, 'data') and result.data:
                order_id = str(getattr(result.data, 'order_id', ''))
            
            print(f"[{self.name}] ✓ Order placed successfully! Order ID: {order_id}")
            
            return OrderResult(
                success=True,
                order_id=order_id,
                message=f"Order placed: {action} {quantity} {symbol}"
            )
            
        except Exception as e:
            print(f"[{self.name}] ❌ Option order FAILED: {e}")
            return OrderResult(success=False, message=str(e))
    
    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None
    ) -> OrderResult:
        """Place a stock order on Upstox"""
        order_type = 'limit' if price else 'market'
        return await self.place_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type=order_type,
            price=price,
            product_type='INTRADAY'
        )
    
    async def place_option_order(
        self,
        symbol: str = None,
        strike: float = None,
        expiry: str = None,
        option_type: str = None,
        action: str = None,
        quantity: int = None,
        price: Optional[float] = None,
        qty: int = None,
        opt_type: str = None,
        expiry_mmdd: str = None,
        limit_price: float = None,
        **kwargs
    ) -> OrderResult:
        """
        Place an option order on Upstox
        
        Supports both Alpaca-style and Webull-style parameters.
        Looks up the actual Upstox instrument key from API.
        """
        actual_qty = quantity or qty or 1
        actual_opt_type = option_type or opt_type or 'CE'
        actual_expiry = expiry or expiry_mmdd or ''
        actual_price = price or limit_price
        
        opt_suffix = 'CE' if actual_opt_type.lower() in ('c', 'call', 'ce') else 'PE'
        
        lookup_result = await self._lookup_instrument_key(
            symbol=symbol.upper(),
            strike=float(strike),
            opt_type=opt_suffix,
            expiry=actual_expiry
        )
        
        instrument_token, lot_size = lookup_result
        
        if not instrument_token:
            formatted_expiry = self._format_expiry_for_upstox(actual_expiry)
            instrument_token = f"NSE_FO|{symbol.upper()}{formatted_expiry}{int(strike)}{opt_suffix}"
            lot_size = 75
            print(f"[UPSTOX] ⚠️ Could not lookup instrument, using fallback: {instrument_token} (lot_size={lot_size})")
        
        order_qty = actual_qty * lot_size
        print(f"[UPSTOX] Quantity: {actual_qty} lots x {lot_size} = {order_qty} units")
        
        print(f"[UPSTOX] Placing option: {action} {order_qty} {instrument_token} @ {actual_price}")
        
        order_type = 'limit' if actual_price else 'market'
        return await self.place_order(
            symbol=instrument_token,
            action=action,
            quantity=order_qty,
            order_type=order_type,
            price=actual_price,
            product_type='INTRADAY'
        )
    
    async def _lookup_instrument_key(self, symbol: str, strike: float, opt_type: str, expiry: str) -> Optional[str]:
        """
        Look up the actual Upstox instrument key from the option contracts API.
        
        Args:
            symbol: Underlying symbol (NIFTY, BANKNIFTY, etc.)
            strike: Strike price
            opt_type: CE or PE
            expiry: Expiry date in any format
            
        Returns:
            Instrument key like 'NSE_FO|37590' or None if not found
        """
        try:
            underlying_keys = {
                'NIFTY': 'NSE_INDEX|Nifty 50',
                'BANKNIFTY': 'NSE_INDEX|Nifty Bank',
                'FINNIFTY': 'NSE_INDEX|Nifty Fin Service',
                'SENSEX': 'BSE_INDEX|SENSEX',
            }
            
            underlying_key = underlying_keys.get(symbol.upper())
            if not underlying_key:
                print(f"[UPSTOX] Unknown underlying: {symbol}")
                return None
            
            formatted_expiry = self._format_expiry_to_date(expiry)
            
            print(f"[UPSTOX] Looking up: {symbol} {strike} {opt_type} expiry={formatted_expiry}")
            
            access_token = self.config.get('access_token')
            url = f"https://api.upstox.com/v2/option/contract"
            
            from urllib.parse import quote
            encoded_key = quote(underlying_key, safe='')
            
            full_url = f"{url}?instrument_key={encoded_key}"
            print(f"[UPSTOX] Fetching contracts from: {full_url}")
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
            
            response = await asyncio.to_thread(
                requests.get, full_url, headers=headers
            )
            
            if response.status_code != 200:
                print(f"[UPSTOX] Option contracts API error: {response.status_code}")
                return None
            
            data = response.json()
            print(f"[UPSTOX] Option contracts API response status: {data.get('status')}")
            
            if data.get('status') != 'success':
                print(f"[UPSTOX] API error: {data}")
                return None
            
            contracts = data.get('data', [])
            print(f"[UPSTOX] Found {len(contracts)} contracts for expiry {formatted_expiry}")
            
            for contract in contracts:
                if (contract.get('strike_price') == strike and 
                    contract.get('instrument_type') == opt_type):
                    instrument_key = contract.get('instrument_key')
                    lot_size = contract.get('lot_size', 1)
                    print(f"[UPSTOX] ✓ Found instrument key: {instrument_key} (lot_size={lot_size})")
                    return instrument_key, lot_size
            
            matching_type = [c for c in contracts if c.get('instrument_type') == opt_type]
            if matching_type:
                closest = min(matching_type, key=lambda c: abs(c.get('strike_price', 0) - strike))
                closest_strike = closest.get('strike_price')
                if abs(closest_strike - strike) <= 100:
                    instrument_key = closest.get('instrument_key')
                    lot_size = closest.get('lot_size', 1)
                    print(f"[UPSTOX] ✓ Using nearest strike {closest_strike} (requested {strike}): {instrument_key} (lot_size={lot_size})")
                    return instrument_key, lot_size
                else:
                    print(f"[UPSTOX] ⚠️ Nearest strike {closest_strike} too far from {strike}")
            
            print(f"[UPSTOX] ⚠️ No matching contract found for {symbol} {strike} {opt_type}")
            return None, 1
            
        except Exception as e:
            print(f"[UPSTOX] Error looking up instrument: {e}")
            return None, 1
    
    def _format_expiry_to_date(self, expiry: str) -> str:
        """Convert expiry to YYYY-MM-DD format for API"""
        from datetime import datetime
        import re
        
        if not expiry:
            return datetime.now().strftime('%Y-%m-%d')
        
        try:
            if re.match(r'^\d{1,2}/\d{1,2}$', expiry):
                month, day = expiry.split('/')
                year = datetime.now().year
                return f"{year}-{int(month):02d}-{int(day):02d}"
            
            elif re.match(r'^\d{4}-\d{2}-\d{2}$', expiry):
                return expiry
            
            elif re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}$', expiry):
                parts = expiry.split('/')
                if len(parts[2]) == 2:
                    dt = datetime.strptime(expiry, '%m/%d/%y')
                else:
                    dt = datetime.strptime(expiry, '%m/%d/%Y')
                return dt.strftime('%Y-%m-%d')
            
            else:
                return datetime.now().strftime('%Y-%m-%d')
                
        except Exception:
            return datetime.now().strftime('%Y-%m-%d')
    
    def _format_expiry_for_upstox(self, expiry: str) -> str:
        """
        Convert expiry from various formats to Upstox format (DDMMMYY)
        Input formats: 01/08, 1/8, 2024-01-08, 01/08/24
        Output format: 08JAN24
        """
        from datetime import datetime
        import re
        
        if not expiry:
            today = datetime.now()
            return today.strftime('%d%b%y').upper()
        
        try:
            if re.match(r'^\d{1,2}/\d{1,2}$', expiry):
                month, day = expiry.split('/')
                year = datetime.now().year
                dt = datetime(year, int(month), int(day))
                return dt.strftime('%d%b%y').upper()
            
            elif re.match(r'^\d{4}-\d{2}-\d{2}$', expiry):
                dt = datetime.strptime(expiry, '%Y-%m-%d')
                return dt.strftime('%d%b%y').upper()
            
            elif re.match(r'^\d{1,2}/\d{1,2}/\d{2,4}$', expiry):
                parts = expiry.split('/')
                if len(parts[2]) == 2:
                    dt = datetime.strptime(expiry, '%m/%d/%y')
                else:
                    dt = datetime.strptime(expiry, '%m/%d/%Y')
                return dt.strftime('%d%b%y').upper()
            
            elif re.match(r'^\d{2}[A-Z]{3}\d{2}$', expiry.upper()):
                return expiry.upper()
            
            else:
                print(f"[UPSTOX] Unknown expiry format: {expiry}, using as-is")
                return expiry.upper().replace('/', '')
                
        except Exception as e:
            print(f"[UPSTOX] Error parsing expiry '{expiry}': {e}")
            return expiry.upper().replace('/', '')
    
    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get current quote for a symbol"""
        if not self.quote_api:
            return {}
        
        try:
            quote = await asyncio.to_thread(
                self.quote_api.get_full_market_quote,
                symbol=symbol,
                api_version='2.0'
            )
            return quote.data if quote and quote.data else {}
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
            return {}
    
    async def get_option_chain(self, instrument_key: str, expiry_date: str) -> Dict[str, Any]:
        """
        Get option chain for a symbol
        
        Args:
            instrument_key: Upstox instrument key (e.g., 'NSE_INDEX|Nifty 50', 'NSE_INDEX|Nifty Bank')
            expiry_date: Expiry date in YYYY-MM-DD format (e.g., '2024-03-28')
        
        Returns:
            Option chain data with put/call options and Greeks
        """
        if not self.options_api:
            return {'error': 'Not connected'}
        
        try:
            result = await asyncio.to_thread(
                self.options_api.get_put_call_option_chain,
                instrument_key,
                expiry_date
            )
            
            if result and result.data:
                return {
                    'success': True,
                    'data': result.data,
                    'count': len(result.data) if isinstance(result.data, list) else 1
                }
            return {'success': False, 'message': 'No option chain data returned'}
            
        except Exception as e:
            print(f"[{self.name}] Error getting option chain: {e}")
            return {'success': False, 'error': str(e)}
    
    async def get_option_contracts(self, instrument_key: str) -> Dict[str, Any]:
        """
        Get available option contracts for a symbol
        
        Args:
            instrument_key: Upstox instrument key (e.g., 'NSE_INDEX|Nifty 50')
        
        Returns:
            Available option contracts with expiry dates
        """
        if not self.options_api:
            return {'error': 'Not connected'}
        
        try:
            result = await asyncio.to_thread(
                self.options_api.get_option_contracts,
                instrument_key
            )
            
            if result and result.data:
                return {
                    'success': True,
                    'data': result.data,
                    'count': len(result.data) if isinstance(result.data, list) else 1
                }
            return {'success': False, 'message': 'No contracts data returned'}
            
        except Exception as e:
            print(f"[{self.name}] Error getting option contracts: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def get_common_instrument_keys() -> Dict[str, str]:
        """Get common Upstox instrument keys for Indian markets"""
        return {
            'NIFTY': 'NSE_INDEX|Nifty 50',
            'BANKNIFTY': 'NSE_INDEX|Nifty Bank',
            'FINNIFTY': 'NSE_INDEX|Nifty Fin Service',
            'SENSEX': 'BSE_INDEX|SENSEX',
            'BANKEX': 'BSE_INDEX|BANKEX',
        }

    @staticmethod
    def get_authorization_url(api_key: str, redirect_uri: str) -> str:
        """Generate OAuth authorization URL"""
        return f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={api_key}&redirect_uri={redirect_uri}"
    
    @staticmethod
    def exchange_code_for_token(api_key: str, api_secret: str, redirect_uri: str, auth_code: str) -> Dict[str, Any]:
        """Exchange authorization code for access token"""
        try:
            url = "https://api.upstox.com/v2/login/authorization/token"
            headers = {
                'accept': 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            data = {
                'code': auth_code,
                'client_id': api_key,
                'client_secret': api_secret,
                'redirect_uri': redirect_uri,
                'grant_type': 'authorization_code'
            }
            
            response = requests.post(url, headers=headers, data=data)
            return response.json()
        except Exception as e:
            return {'error': str(e)}
    
    @staticmethod
    def test_connection(access_token: str) -> Dict[str, Any]:
        """Test connection with provided credentials"""
        try:
            if not UPSTOX_AVAILABLE:
                return {
                    'success': False,
                    'message': 'Upstox library not installed. Run: pip install upstox-python-sdk'
                }
            
            configuration = Configuration()
            configuration.access_token = access_token
            
            api_client = ApiClient(configuration)
            user_api = UserApi(api_client)
            
            profile = user_api.get_profile(api_version='2.0')
            
            if profile and profile.data:
                return {
                    'success': True,
                    'message': f"Connected! User: {profile.data.user_name} ({profile.data.user_id})",
                    'user_id': profile.data.user_id,
                    'user_name': profile.data.user_name
                }
            else:
                return {
                    'success': False,
                    'message': 'Connected but no profile data returned'
                }
                
        except Exception as e:
            error_msg = str(e)
            if 'unauthorized' in error_msg.lower() or '401' in error_msg:
                return {
                    'success': False,
                    'message': 'Access token expired or invalid. Generate a new one via OAuth flow.'
                }
            return {
                'success': False,
                'message': f'Connection failed: {error_msg}'
            }


BrokerFactory.register_broker('UPSTOX', UpstoxBroker)
