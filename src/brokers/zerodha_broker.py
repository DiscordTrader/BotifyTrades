"""
Zerodha (Kite Connect) Broker Implementation (India)
OAuth 2.0 based trading platform for Indian markets (NSE/BSE)
"""

import sys
import os
import asyncio
import requests
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory

try:
    from kiteconnect import KiteConnect
    KITE_AVAILABLE = True
except ImportError:
    KITE_AVAILABLE = False
    print("[ZERODHA] Warning: kiteconnect not installed. Install with: pip install kiteconnect")

try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False


class ZerodhaBroker(BrokerInterface):
    """Zerodha Kite Connect broker implementation for Indian markets"""
    
    COUNTRY_CODE = 'IN'
    CURRENCY = 'INR'
    
    EXCHANGE_NSE = 'NSE'
    EXCHANGE_BSE = 'BSE'
    EXCHANGE_NFO = 'NFO'
    EXCHANGE_BFO = 'BFO'
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "ZERODHA"
        self.kite = None
        self.user_id = None
    
    @property
    def is_live(self) -> bool:
        """Zerodha is always live trading"""
        return True
    
    async def connect(self) -> bool:
        """Connect to Zerodha using API key and access token"""
        try:
            if not KITE_AVAILABLE:
                print(f"[{self.name}] kiteconnect not installed")
                return False
            
            api_key = self.config.get('api_key')
            api_secret = self.config.get('api_secret')
            access_token = self.config.get('access_token')
            
            if not api_key:
                print(f"[{self.name}] No API key provided")
                return False
            
            print(f"[{self.name}] Connecting...")
            
            self.kite = KiteConnect(api_key=api_key)
            
            if access_token:
                self.kite.set_access_token(access_token)
            else:
                request_token = self.config.get('request_token')
                if request_token and api_secret:
                    data = self.kite.generate_session(request_token, api_secret=api_secret)
                    access_token = data["access_token"]
                    self.kite.set_access_token(access_token)
                else:
                    print(f"[{self.name}] No access token or request token provided")
                    return False
            
            profile = await asyncio.to_thread(self.kite.profile)
            
            if profile:
                self.user_id = profile.get('user_id')
                print(f"[{self.name}] Connected! User: {self.user_id}")
                print(f"[{self.name}] Name: {profile.get('user_name', 'N/A')}")
                self.connected = True
                return True
            else:
                print(f"[{self.name}] Failed to get profile")
                return False
                
        except Exception as e:
            print(f"[{self.name}] Connection failed: {e}")
            self.connected = False
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from Zerodha"""
        if self.kite:
            try:
                await asyncio.to_thread(self.kite.invalidate_access_token)
            except:
                pass
        self.kite = None
        self.connected = False
        print(f"[{self.name}] Disconnected")
        return True
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        if not self.kite:
            return {}
        
        try:
            margins = await asyncio.to_thread(self.kite.margins)
            profile = await asyncio.to_thread(self.kite.profile)
            return {
                'user_id': self.user_id,
                'currency': self.CURRENCY,
                'profile': profile,
                'margins': margins
            }
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            return {}
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions"""
        if not self.kite:
            return []
        
        try:
            positions = await asyncio.to_thread(self.kite.positions)
            return positions.get('net', []) if positions else []
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return []
    
    async def place_order(self, symbol: str, action: str, quantity: int,
                          order_type: str = 'market', price: float = None,
                          exchange: str = 'NSE', product: str = 'CNC',
                          **kwargs) -> OrderResult:
        """Place an order on Zerodha"""
        if not self.kite:
            return OrderResult(success=False, message="Not connected")
        
        try:
            order_params = {
                'tradingsymbol': symbol,
                'exchange': exchange,
                'transaction_type': self.kite.TRANSACTION_TYPE_BUY if action.upper() == 'BTO' else self.kite.TRANSACTION_TYPE_SELL,
                'quantity': quantity,
                'order_type': self.kite.ORDER_TYPE_MARKET if order_type == 'market' else self.kite.ORDER_TYPE_LIMIT,
                'product': product,
                'validity': self.kite.VALIDITY_DAY
            }
            
            if order_type == 'limit' and price:
                order_params['price'] = price
            
            order_id = await asyncio.to_thread(
                self.kite.place_order,
                variety=self.kite.VARIETY_REGULAR,
                **order_params
            )
            
            return OrderResult(
                success=True,
                order_id=str(order_id),
                message=f"Order placed: {action} {quantity} {symbol}"
            )
            
        except Exception as e:
            return OrderResult(success=False, message=str(e))
    
    async def get_quote(self, symbol: str, exchange: str = 'NSE') -> Dict[str, Any]:
        """Get current quote for a symbol"""
        if not self.kite:
            return {}
        
        try:
            instrument = f"{exchange}:{symbol}"
            quote = await asyncio.to_thread(self.kite.quote, [instrument])
            return quote.get(instrument, {})
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
            return {}
    
    def get_login_url(self) -> str:
        """Get Kite login URL for OAuth flow"""
        if self.kite:
            return self.kite.login_url()
        return ""
    
    @staticmethod
    def auto_login(api_key: str, api_secret: str, user_id: str, 
                   password: str, totp_secret: str) -> Dict[str, Any]:
        """Automated login with TOTP (requires pyotp)"""
        try:
            if not KITE_AVAILABLE:
                return {'success': False, 'message': 'kiteconnect not installed'}
            
            if not PYOTP_AVAILABLE:
                return {'success': False, 'message': 'pyotp not installed for TOTP generation'}
            
            session = requests.Session()
            
            login_url = f"https://kite.trade/connect/login?v=3&api_key={api_key}"
            session.get(login_url)
            
            login_resp = session.post(
                "https://kite.zerodha.com/api/login",
                data={"user_id": user_id, "password": password}
            )
            login_data = login_resp.json()
            
            if login_data.get('status') != 'success':
                return {'success': False, 'message': f"Login failed: {login_data.get('message', 'Unknown error')}"}
            
            request_id = login_data["data"]["request_id"]
            
            totp = pyotp.TOTP(totp_secret).now()
            twofa_resp = session.post(
                "https://kite.zerodha.com/api/twofa",
                data={"request_id": request_id, "twofa_value": totp, "user_id": user_id}
            )
            
            redirect_url = twofa_resp.url
            if 'request_token=' not in redirect_url:
                return {'success': False, 'message': 'Failed to get request token after 2FA'}
            
            request_token = redirect_url.split("request_token=")[1].split("&")[0]
            
            kite = KiteConnect(api_key=api_key)
            data = kite.generate_session(request_token, api_secret=api_secret)
            access_token = data["access_token"]
            
            return {
                'success': True,
                'message': 'Auto-login successful',
                'access_token': access_token,
                'request_token': request_token
            }
            
        except Exception as e:
            return {'success': False, 'message': f'Auto-login failed: {str(e)}'}
    
    @staticmethod
    def test_connection(api_key: str, access_token: str = None, 
                        api_secret: str = None, request_token: str = None) -> Dict[str, Any]:
        """Test connection with provided credentials"""
        try:
            if not KITE_AVAILABLE:
                return {
                    'success': False,
                    'message': 'Kite Connect library not installed. Run: pip install kiteconnect'
                }
            
            kite = KiteConnect(api_key=api_key)
            
            if access_token:
                kite.set_access_token(access_token)
            elif request_token and api_secret:
                data = kite.generate_session(request_token, api_secret=api_secret)
                kite.set_access_token(data["access_token"])
            else:
                return {
                    'success': False,
                    'message': 'Access token or request_token + api_secret required'
                }
            
            profile = kite.profile()
            
            if profile:
                return {
                    'success': True,
                    'message': f"Connected! User: {profile.get('user_name', 'N/A')} ({profile.get('user_id', 'N/A')})",
                    'user_id': profile.get('user_id'),
                    'user_name': profile.get('user_name')
                }
            else:
                return {
                    'success': False,
                    'message': 'Connected but no profile data returned'
                }
                
        except Exception as e:
            error_msg = str(e)
            if 'TokenException' in error_msg or 'expired' in error_msg.lower():
                return {
                    'success': False,
                    'message': 'Access token expired. Tokens expire daily at 6 AM IST. Re-login required.'
                }
            return {
                'success': False,
                'message': f'Connection failed: {error_msg}'
            }


BrokerFactory.register('zerodha', ZerodhaBroker)
