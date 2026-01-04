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
        """Place an order on Upstox"""
        if not self.order_api:
            return OrderResult(success=False, message="Not connected")
        
        try:
            order_params = {
                'instrument_token': symbol,
                'quantity': quantity,
                'transaction_type': 'BUY' if action.upper() == 'BTO' else 'SELL',
                'order_type': 'MARKET' if order_type == 'market' else 'LIMIT',
                'product': product_type,
                'validity': 'DAY',
                'disclosed_quantity': 0,
                'trigger_price': 0,
                'is_amo': False
            }
            
            if order_type == 'limit' and price:
                order_params['price'] = price
            else:
                order_params['price'] = 0
            
            result = await asyncio.to_thread(
                self.order_api.place_order,
                api_version='2.0',
                **order_params
            )
            
            return OrderResult(
                success=True,
                order_id=str(result.data.order_id) if result and result.data else '',
                message=f"Order placed: {action} {quantity} {symbol}"
            )
            
        except Exception as e:
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
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str,
        action: str,
        quantity: int,
        price: Optional[float] = None
    ) -> OrderResult:
        """
        Place an option order on Upstox
        
        For Indian markets, the option symbol format is:
        {underlying}|{expiry}{strike}{CE/PE}
        Example: NIFTY|24JAN26000CE
        """
        opt_suffix = 'CE' if option_type.lower() in ('c', 'call', 'ce') else 'PE'
        instrument_token = f"{symbol}|{expiry}{int(strike)}{opt_suffix}"
        
        order_type = 'limit' if price else 'market'
        return await self.place_order(
            symbol=instrument_token,
            action=action,
            quantity=quantity,
            order_type=order_type,
            price=price,
            product_type='INTRADAY'
        )
    
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
