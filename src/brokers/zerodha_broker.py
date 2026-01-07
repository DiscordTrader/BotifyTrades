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
    EXCHANGE_CDS = 'CDS'
    EXCHANGE_MCX = 'MCX'
    
    PRODUCT_CNC = 'CNC'
    PRODUCT_MIS = 'MIS'
    PRODUCT_NRML = 'NRML'
    
    VARIETY_REGULAR = 'regular'
    VARIETY_AMO = 'amo'
    VARIETY_CO = 'co'
    VARIETY_ICEBERG = 'iceberg'
    VARIETY_AUCTION = 'auction'
    
    ORDER_TYPE_MARKET = 'MARKET'
    ORDER_TYPE_LIMIT = 'LIMIT'
    ORDER_TYPE_SL = 'SL'
    ORDER_TYPE_SLM = 'SL-M'
    
    VALIDITY_DAY = 'DAY'
    VALIDITY_IOC = 'IOC'
    VALIDITY_TTL = 'TTL'
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "ZERODHA"
        self.kite = None
        self.user_id = None
        self._instruments_cache = {}
    
    @property
    def is_live(self) -> bool:
        """Zerodha is always live trading"""
        return True
    
    async def connect(self) -> bool:
        """Connect to Zerodha using API key and access token, with fallback to request_token"""
        try:
            if not KITE_AVAILABLE:
                print(f"[{self.name}] kiteconnect not installed")
                return False
            
            api_key = self.config.get('api_key')
            api_secret = self.config.get('api_secret')
            access_token = self.config.get('access_token')
            request_token = self.config.get('request_token')
            
            if not api_key:
                print(f"[{self.name}] No API key provided")
                return False
            
            print(f"[{self.name}] Connecting...")
            
            self.kite = KiteConnect(api_key=api_key)
            
            access_token_worked = False
            if access_token:
                try:
                    print(f"[{self.name}] Trying stored access_token...")
                    self.kite.set_access_token(access_token)
                    profile = await asyncio.to_thread(self.kite.profile)
                    if profile:
                        access_token_worked = True
                        self.user_id = profile.get('user_id')
                        print(f"[{self.name}] Connected! User: {self.user_id}")
                        print(f"[{self.name}] Name: {profile.get('user_name', 'N/A')}")
                        self.connected = True
                        return True
                except Exception as token_err:
                    print(f"[{self.name}] Access token failed: {token_err}")
                    print(f"[{self.name}] Will try request_token fallback...")
            
            if not access_token_worked and request_token and api_secret:
                try:
                    print(f"[{self.name}] Trying request_token + api_secret flow...")
                    data = self.kite.generate_session(request_token, api_secret=api_secret)
                    new_access_token = data["access_token"]
                    self.kite.set_access_token(new_access_token)
                    
                    profile = await asyncio.to_thread(self.kite.profile)
                    if profile:
                        self.user_id = profile.get('user_id')
                        print(f"[{self.name}] Connected via request_token! User: {self.user_id}")
                        print(f"[{self.name}] Name: {profile.get('user_name', 'N/A')}")
                        self.connected = True
                        return True
                except Exception as req_err:
                    print(f"[{self.name}] Request token flow failed: {req_err}")
            
            if not access_token and not (request_token and api_secret):
                print(f"[{self.name}] No access token or request token provided")
            
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
                          variety: str = None, validity: str = None,
                          trigger_price: float = None, disclosed_quantity: int = None,
                          tag: str = None, **kwargs) -> OrderResult:
        """
        Place an order on Zerodha
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'NIFTY23JAN18000CE')
            action: 'BTO' (buy) or 'STC' (sell)
            quantity: Number of shares/lots
            order_type: 'market', 'limit', 'sl', 'sl-m'
            price: Limit price (required for limit orders)
            exchange: NSE, BSE, NFO, BFO, CDS, MCX
            product: CNC (delivery), MIS (intraday), NRML (F&O normal)
            variety: regular, amo, co, iceberg (defaults to regular)
            validity: DAY, IOC, TTL (defaults to DAY)
            trigger_price: For SL/SL-M orders
            disclosed_quantity: For iceberg orders
            tag: Optional order tag for tracking
        """
        if not self.kite:
            return OrderResult(success=False, message="Not connected")
        
        try:
            transaction_type = 'BUY' if action.upper() in ('BTO', 'BUY') else 'SELL'
            
            order_type_map = {
                'market': self.ORDER_TYPE_MARKET,
                'limit': self.ORDER_TYPE_LIMIT,
                'sl': self.ORDER_TYPE_SL,
                'sl-m': self.ORDER_TYPE_SLM,
            }
            kite_order_type = order_type_map.get(order_type.lower(), self.ORDER_TYPE_MARKET)
            
            order_params = {
                'tradingsymbol': symbol,
                'exchange': exchange.upper(),
                'transaction_type': transaction_type,
                'quantity': quantity,
                'order_type': kite_order_type,
                'product': product.upper(),
                'validity': validity or self.VALIDITY_DAY
            }
            
            if order_type.lower() == 'limit' and price:
                order_params['price'] = price
            
            if order_type.lower() in ('sl', 'sl-m') and trigger_price:
                order_params['trigger_price'] = trigger_price
                if order_type.lower() == 'sl' and price:
                    order_params['price'] = price
            
            if disclosed_quantity:
                order_params['disclosed_quantity'] = disclosed_quantity
            
            if tag:
                order_params['tag'] = tag[:20]
            
            order_variety = variety or self.VARIETY_REGULAR
            
            order_id = await asyncio.to_thread(
                self.kite.place_order,
                variety=order_variety,
                **order_params
            )
            
            print(f"[{self.name}] Order placed: {transaction_type} {quantity} {symbol} @ {order_type} (ID: {order_id})")
            
            return OrderResult(
                success=True,
                order_id=str(order_id),
                message=f"Order placed: {action} {quantity} {symbol}"
            )
            
        except Exception as e:
            print(f"[{self.name}] Order failed: {e}")
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
    
    async def get_ltp(self, symbol: str, exchange: str = 'NSE') -> Optional[float]:
        """Get last traded price for a symbol"""
        if not self.kite:
            return None
        
        try:
            instrument = f"{exchange}:{symbol}"
            ltp_data = await asyncio.to_thread(self.kite.ltp, [instrument])
            if instrument in ltp_data:
                return ltp_data[instrument].get('last_price')
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting LTP for {symbol}: {e}")
            return None
    
    async def get_ohlc(self, symbol: str, exchange: str = 'NSE') -> Dict[str, Any]:
        """Get OHLC data for a symbol"""
        if not self.kite:
            return {}
        
        try:
            instrument = f"{exchange}:{symbol}"
            ohlc_data = await asyncio.to_thread(self.kite.ohlc, [instrument])
            return ohlc_data.get(instrument, {})
        except Exception as e:
            print(f"[{self.name}] Error getting OHLC for {symbol}: {e}")
            return {}
    
    async def get_orders(self) -> List[Dict[str, Any]]:
        """Get all orders for the day"""
        if not self.kite:
            return []
        
        try:
            orders = await asyncio.to_thread(self.kite.orders)
            return orders if orders else []
        except Exception as e:
            print(f"[{self.name}] Error getting orders: {e}")
            return []
    
    async def get_order_history(self, order_id: str) -> List[Dict[str, Any]]:
        """Get history/status updates for a specific order"""
        if not self.kite:
            return []
        
        try:
            history = await asyncio.to_thread(self.kite.order_history, order_id)
            return history if history else []
        except Exception as e:
            print(f"[{self.name}] Error getting order history for {order_id}: {e}")
            return []
    
    async def get_trades(self) -> List[Dict[str, Any]]:
        """Get all trades for the day"""
        if not self.kite:
            return []
        
        try:
            trades = await asyncio.to_thread(self.kite.trades)
            return trades if trades else []
        except Exception as e:
            print(f"[{self.name}] Error getting trades: {e}")
            return []
    
    async def cancel_order(self, order_id: str, variety: str = None) -> OrderResult:
        """Cancel an open order"""
        if not self.kite:
            return OrderResult(success=False, message="Not connected")
        
        try:
            order_variety = variety or self.VARIETY_REGULAR
            result = await asyncio.to_thread(
                self.kite.cancel_order,
                variety=order_variety,
                order_id=order_id
            )
            print(f"[{self.name}] Order cancelled: {order_id}")
            return OrderResult(
                success=True,
                order_id=str(result) if result else order_id,
                message=f"Order {order_id} cancelled"
            )
        except Exception as e:
            print(f"[{self.name}] Cancel order failed: {e}")
            return OrderResult(success=False, message=str(e))
    
    async def modify_order(self, order_id: str, quantity: int = None,
                           price: float = None, order_type: str = None,
                           trigger_price: float = None, validity: str = None,
                           disclosed_quantity: int = None, variety: str = None) -> OrderResult:
        """Modify an open order"""
        if not self.kite:
            return OrderResult(success=False, message="Not connected")
        
        try:
            order_variety = variety or self.VARIETY_REGULAR
            
            modify_params = {'order_id': order_id}
            
            if quantity is not None:
                modify_params['quantity'] = quantity
            if price is not None:
                modify_params['price'] = price
            if order_type is not None:
                order_type_map = {
                    'market': self.ORDER_TYPE_MARKET,
                    'limit': self.ORDER_TYPE_LIMIT,
                    'sl': self.ORDER_TYPE_SL,
                    'sl-m': self.ORDER_TYPE_SLM,
                }
                modify_params['order_type'] = order_type_map.get(order_type.lower(), order_type.upper())
            if trigger_price is not None:
                modify_params['trigger_price'] = trigger_price
            if validity is not None:
                modify_params['validity'] = validity.upper()
            if disclosed_quantity is not None:
                modify_params['disclosed_quantity'] = disclosed_quantity
            
            result = await asyncio.to_thread(
                self.kite.modify_order,
                variety=order_variety,
                **modify_params
            )
            
            print(f"[{self.name}] Order modified: {order_id}")
            return OrderResult(
                success=True,
                order_id=str(result) if result else order_id,
                message=f"Order {order_id} modified"
            )
        except Exception as e:
            print(f"[{self.name}] Modify order failed: {e}")
            return OrderResult(success=False, message=str(e))
    
    async def get_holdings(self) -> List[Dict[str, Any]]:
        """Get delivery holdings (long-term portfolio)"""
        if not self.kite:
            return []
        
        try:
            holdings = await asyncio.to_thread(self.kite.holdings)
            return holdings if holdings else []
        except Exception as e:
            print(f"[{self.name}] Error getting holdings: {e}")
            return []
    
    async def get_instruments(self, exchange: str = None) -> List[Dict[str, Any]]:
        """
        Get instrument master for an exchange
        
        Args:
            exchange: NSE, BSE, NFO, BFO, CDS, MCX (or None for all)
        
        Returns list of instruments with fields: instrument_token, exchange_token,
        tradingsymbol, name, last_price, expiry, strike, tick_size, lot_size, 
        instrument_type, segment, exchange
        """
        if not self.kite:
            return []
        
        try:
            cache_key = exchange or 'ALL'
            if cache_key in self._instruments_cache:
                return self._instruments_cache[cache_key]
            
            if exchange:
                instruments = await asyncio.to_thread(self.kite.instruments, exchange)
            else:
                instruments = await asyncio.to_thread(self.kite.instruments)
            
            self._instruments_cache[cache_key] = instruments
            print(f"[{self.name}] Loaded {len(instruments)} instruments for {cache_key}")
            return instruments if instruments else []
        except Exception as e:
            print(f"[{self.name}] Error getting instruments: {e}")
            return []
    
    def clear_instruments_cache(self):
        """Clear the instruments cache"""
        self._instruments_cache = {}
    
    async def get_instrument_token(self, symbol: str, exchange: str = 'NFO') -> Optional[int]:
        """Get instrument token for a trading symbol"""
        instruments = await self.get_instruments(exchange)
        for inst in instruments:
            if inst.get('tradingsymbol') == symbol:
                return inst.get('instrument_token')
        return None
    
    async def get_margins_order(self, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Get required margins for a list of orders (basket order margin)"""
        if not self.kite:
            return {}
        
        try:
            margins = await asyncio.to_thread(self.kite.order_margins, orders)
            return margins if margins else {}
        except Exception as e:
            print(f"[{self.name}] Error getting order margins: {e}")
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
            new_access_token = None
            used_request_token_flow = False
            
            if access_token:
                try:
                    kite.set_access_token(access_token)
                    profile = kite.profile()
                    if profile:
                        return {
                            'success': True,
                            'message': f"Connected! User: {profile.get('user_name', 'N/A')} ({profile.get('user_id', 'N/A')})",
                            'user_id': profile.get('user_id'),
                            'user_name': profile.get('user_name'),
                            'access_token': access_token
                        }
                except Exception as token_err:
                    if request_token and api_secret:
                        pass
                    else:
                        error_msg = str(token_err)
                        if 'TokenException' in error_msg or 'expired' in error_msg.lower():
                            return {
                                'success': False,
                                'message': 'Access token expired. Tokens expire daily at 6 AM IST. Please provide a new request_token.'
                            }
                        raise
            
            if request_token and api_secret:
                data = kite.generate_session(request_token, api_secret=api_secret)
                new_access_token = data["access_token"]
                kite.set_access_token(new_access_token)
                used_request_token_flow = True
            elif not access_token:
                return {
                    'success': False,
                    'message': 'Access token or request_token + api_secret required'
                }
            else:
                return {
                    'success': False,
                    'message': 'Access token expired and no request_token available. Please provide a new request_token.'
                }
            
            profile = kite.profile()
            
            if profile:
                result = {
                    'success': True,
                    'message': f"Connected! User: {profile.get('user_name', 'N/A')} ({profile.get('user_id', 'N/A')})",
                    'user_id': profile.get('user_id'),
                    'user_name': profile.get('user_name')
                }
                if new_access_token:
                    result['access_token'] = new_access_token
                    result['used_request_token_flow'] = True
                return result
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
                    'message': 'Access token expired. Tokens expire daily at 6 AM IST. Please provide a new request_token.'
                }
            return {
                'success': False,
                'message': f'Connection failed: {error_msg}'
            }


BrokerFactory.register_broker('ZERODHA', ZerodhaBroker)
