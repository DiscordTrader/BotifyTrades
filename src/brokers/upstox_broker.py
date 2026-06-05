"""
Upstox Broker Implementation (India)
OAuth 2.0 based trading platform for Indian markets (NSE/BSE)
Includes automatic token refresh functionality
"""

import sys
import os

# Handle PyInstaller GUI mode where stdout/stderr may be None
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8', errors='replace')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8', errors='replace')

import asyncio
import requests
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
gui_app_dir = os.path.join(parent_dir, 'gui_app')
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if gui_app_dir not in sys.path:
    sys.path.insert(0, gui_app_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory

try:
    from gui_app import database as db
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    print("[UPSTOX] Warning: Database module not available - pending orders will be in-memory only")

try:
    from upstox_client import Configuration, ApiClient, UserApi, OrderApi, PortfolioApi, MarketQuoteApi, OptionsApi
    UPSTOX_AVAILABLE = True
except ImportError:
    UPSTOX_AVAILABLE = False
    print("[UPSTOX] Warning: upstox-python-sdk not installed. Install with: pip install upstox-python-sdk")


class UpstoxBroker(BrokerInterface):
    """Upstox broker implementation for Indian markets with automatic token refresh"""
    
    COUNTRY_CODE = 'IN'
    CURRENCY = 'INR'
    TOKEN_REFRESH_URL = 'https://api.upstox.com/v2/login/authorization/token'
    TOKEN_EXPIRY_HOURS = 24
    REFRESH_BUFFER_HOURS = 2
    
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
        self.token_issued_at = None
        self.token_expires_at = None
        self._refresh_scheduler_running = False
        self._refresh_lock = threading.Lock()
        self._pending_orders = []
        self._pending_order_lock = threading.Lock()
        self._pending_order_scheduler_running = False
    
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
                
                token_issued_at = self.config.get('token_issued_at')
                if token_issued_at:
                    try:
                        if isinstance(token_issued_at, str):
                            self.token_issued_at = datetime.fromisoformat(token_issued_at)
                        else:
                            self.token_issued_at = token_issued_at
                        self.token_expires_at = self.token_issued_at + timedelta(hours=self.TOKEN_EXPIRY_HOURS)
                        time_left = self.get_time_until_expiry()
                        if time_left:
                            hours = int(time_left.total_seconds() // 3600)
                            mins = int((time_left.total_seconds() % 3600) // 60)
                            print(f"[{self.name}] Token expires in: {hours}h {mins}m")
                    except Exception as e:
                        print(f"[{self.name}] Could not parse token_issued_at: {e}")
                
                if self.config.get('refresh_token'):
                    print(f"[{self.name}] ✓ Auto-refresh enabled (refresh_token available)")
                else:
                    print(f"[{self.name}] ⚠️  No refresh_token - manual re-auth needed when token expires")
                
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
        self._refresh_scheduler_running = False
        print(f"[{self.name}] Disconnected")
        return True
    
    def is_token_expired(self) -> bool:
        """Check if the access token is expired or about to expire"""
        if not self.token_expires_at:
            issued_at = self.config.get('token_issued_at')
            if issued_at:
                try:
                    if isinstance(issued_at, str):
                        self.token_issued_at = datetime.fromisoformat(issued_at)
                    else:
                        self.token_issued_at = issued_at
                    self.token_expires_at = self.token_issued_at + timedelta(hours=self.TOKEN_EXPIRY_HOURS)
                except:
                    return True
            else:
                return True
        
        buffer = timedelta(hours=self.REFRESH_BUFFER_HOURS)
        return datetime.now() >= (self.token_expires_at - buffer)
    
    def get_time_until_expiry(self) -> Optional[timedelta]:
        """Get time remaining until token expires"""
        if not self.token_expires_at:
            return None
        return self.token_expires_at - datetime.now()
    
    async def refresh_access_token(self) -> bool:
        """
        Refresh the access token using the refresh token.
        Upstox refresh tokens are single-use and return a new refresh token.
        """
        with self._refresh_lock:
            try:
                api_key = self.config.get('api_key')
                api_secret = self.config.get('api_secret')
                refresh_token = self.config.get('refresh_token')
                
                if not all([api_key, api_secret, refresh_token]):
                    print(f"[{self.name}] Cannot refresh - missing api_key, api_secret, or refresh_token")
                    return False
                
                print(f"[{self.name}] Refreshing access token...")
                
                data = {
                    'client_id': api_key,
                    'client_secret': api_secret,
                    'refresh_token': refresh_token,
                    'grant_type': 'refresh_token'
                }
                
                headers = {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Accept': 'application/json'
                }
                
                response = await asyncio.to_thread(
                    requests.post,
                    self.TOKEN_REFRESH_URL,
                    data=data,
                    headers=headers
                )
                
                if response.status_code == 200:
                    token_data = response.json()
                    new_access_token = token_data.get('access_token')
                    new_refresh_token = token_data.get('refresh_token')
                    expires_in = token_data.get('expires_in', 86400)
                    
                    if new_access_token:
                        self.config['access_token'] = new_access_token
                        if new_refresh_token:
                            self.config['refresh_token'] = new_refresh_token
                        
                        self.token_issued_at = datetime.now()
                        self.token_expires_at = self.token_issued_at + timedelta(seconds=expires_in)
                        
                        if self.api_client and hasattr(self.api_client, 'configuration'):
                            self.api_client.configuration.access_token = new_access_token
                        
                        self._save_tokens_to_database(new_access_token, new_refresh_token)
                        
                        print(f"[{self.name}] ✓ Token refreshed successfully!")
                        print(f"[{self.name}]   Expires at: {self.token_expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
                        return True
                    else:
                        print(f"[{self.name}] Token refresh failed - no access_token in response")
                        return False
                else:
                    error_msg = response.text[:200] if response.text else 'Unknown error'
                    print(f"[{self.name}] Token refresh failed: {response.status_code} - {error_msg}")
                    if response.status_code == 401:
                        print(f"[{self.name}] ⚠️  Refresh token may be expired. Manual re-authentication required.")
                    return False
                    
            except Exception as e:
                print(f"[{self.name}] Token refresh error: {e}")
                return False
    
    def _save_tokens_to_database(self, access_token: str, refresh_token: Optional[str] = None):
        """Save refreshed tokens to the database"""
        try:
            gui_app_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'gui_app')
            sys.path.insert(0, gui_app_path)
            from database import get_db
            
            conn = get_db()
            cursor = conn.cursor()
            
            update_fields = ['access_token = ?', 'token_issued_at = ?']
            values = [access_token, datetime.now().isoformat()]
            
            if refresh_token:
                update_fields.append('refresh_token = ?')
                values.append(refresh_token)
            
            values.append('upstox')
            
            cursor.execute(f'''
                UPDATE broker_credentials 
                SET {', '.join(update_fields)}
                WHERE broker_id = ?
            ''', values)
            conn.commit()
            print(f"[{self.name}] ✓ Tokens saved to database")
            
        except Exception as e:
            print(f"[{self.name}] Warning: Could not save tokens to database: {e}")
    
    async def start_token_refresh_scheduler(self):
        """Start a background scheduler to automatically refresh tokens before expiry"""
        if self._refresh_scheduler_running:
            print(f"[{self.name}] Token refresh scheduler already running")
            return
        
        self._refresh_scheduler_running = True
        print(f"[{self.name}] ✓ Token auto-refresh scheduler started")
        
        async def refresh_loop():
            while self._refresh_scheduler_running and self.connected:
                try:
                    time_until_expiry = self.get_time_until_expiry()
                    
                    if time_until_expiry and time_until_expiry.total_seconds() > 0:
                        refresh_in = time_until_expiry.total_seconds() - (self.REFRESH_BUFFER_HOURS * 3600)
                        
                        if refresh_in > 0:
                            hours = int(refresh_in // 3600)
                            mins = int((refresh_in % 3600) // 60)
                            print(f"[{self.name}] Next token refresh in {hours}h {mins}m")
                            await asyncio.sleep(min(refresh_in, 3600))
                        else:
                            print(f"[{self.name}] Token nearing expiry, refreshing now...")
                            success = await self.refresh_access_token()
                            if not success:
                                print(f"[{self.name}] ⚠️  Auto-refresh failed, will retry in 5 minutes")
                                await asyncio.sleep(300)
                    else:
                        print(f"[{self.name}] Token expired, attempting refresh...")
                        success = await self.refresh_access_token()
                        if success:
                            await self.connect()
                        else:
                            print(f"[{self.name}] ⚠️  Token refresh failed, manual re-auth needed")
                            self._refresh_scheduler_running = False
                            break
                            
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[{self.name}] Refresh scheduler error: {e}")
                    await asyncio.sleep(300)
        
        self._refresh_task = asyncio.create_task(refresh_loop())
    
    async def ensure_valid_token(self) -> bool:
        """Ensure we have a valid token before making API calls"""
        if self.is_token_expired():
            print(f"[{self.name}] Token expired, attempting refresh...")
            return await self.refresh_access_token()
        return True
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information using REST API"""
        try:
            access_token = self.config.get('access_token')
            url = "https://api.upstox.com/v2/user/get-funds-and-margin"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            response = await asyncio.to_thread(requests.get, url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    funds_data = data.get('data', {})
                    equity = funds_data.get('equity', {})
                    
                    return {
                        'user_id': self.user_id,
                        'currency': self.CURRENCY,
                        'available_balance': equity.get('available_margin', 0),
                        'buying_power': equity.get('available_margin', 0),
                        'portfolio_value': equity.get('available_margin', 0) + equity.get('used_margin', 0)
                    }
            return {'user_id': self.user_id, 'currency': self.CURRENCY}
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            return {'user_id': self.user_id, 'currency': self.CURRENCY}
    
    async def get_account_balance(self) -> Dict[str, Any]:
        """Get account balance for India Markets page - calls Upstox funds API"""
        try:
            access_token = self.config.get('access_token')
            url = "https://api.upstox.com/v2/user/get-funds-and-margin"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            print(f"[{self.name}] Fetching account balance from Upstox API...")
            response = await asyncio.to_thread(requests.get, url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                print(f"[{self.name}] Funds API response status: {data.get('status')}")
                
                if data.get('status') == 'success':
                    funds_data = data.get('data', {})
                    equity = funds_data.get('equity', {})
                    commodity = funds_data.get('commodity', {})
                    
                    available = equity.get('available_margin', 0) + commodity.get('available_margin', 0)
                    margin_used = equity.get('used_margin', 0) + commodity.get('used_margin', 0)
                    
                    print(f"[{self.name}] Balance fetched: available=₹{available}, margin_used=₹{margin_used}")
                    
                    return {
                        'available': available,
                        'margin_used': margin_used,
                        'equity_available': equity.get('available_margin', 0),
                        'equity_used': equity.get('used_margin', 0),
                        'commodity_available': commodity.get('available_margin', 0),
                        'commodity_used': commodity.get('used_margin', 0),
                        'payin_amount': equity.get('payin_amount', 0),
                        'currency': self.CURRENCY
                    }
                else:
                    print(f"[{self.name}] Funds API error: {data.get('errors', data.get('message', 'Unknown error'))}")
            elif response.status_code == 423:
                print(f"[{self.name}] Funds API HTTP 423 - API locked (may be outside market hours 9:15AM-3:30PM IST)")
                return {'available': None, 'margin_used': None, 'currency': self.CURRENCY, 'error': 'API locked (outside market hours)'}
            elif response.status_code == 401:
                print(f"[{self.name}] Funds API HTTP 401 - Access token expired, re-authenticate required")
                return {'available': None, 'margin_used': None, 'currency': self.CURRENCY, 'error': 'Token expired'}
            else:
                print(f"[{self.name}] Funds API HTTP error: {response.status_code}")
            
            return {'available': 0, 'margin_used': 0, 'currency': self.CURRENCY}
        except Exception as e:
            print(f"[{self.name}] Error getting account balance: {e}")
            return {'available': 0, 'margin_used': 0, 'currency': self.CURRENCY}
    
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
    
    async def get_funds(self) -> Dict[str, Any]:
        """Get fund and margin details"""
        if not self.user_api:
            return {}
        
        try:
            access_token = self.config.get('access_token')
            url = "https://api.upstox.com/v2/user/get-funds-and-margin"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            response = await asyncio.to_thread(requests.get, url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    funds_data = data.get('data', {})
                    equity = funds_data.get('equity', {})
                    commodity = funds_data.get('commodity', {})
                    
                    return {
                        'currency': self.CURRENCY,
                        'equity': {
                            'available_margin': equity.get('available_margin', 0),
                            'used_margin': equity.get('used_margin', 0),
                            'payin_amount': equity.get('payin_amount', 0),
                            'span_margin': equity.get('span_margin', 0),
                            'exposure_margin': equity.get('exposure_margin', 0),
                        },
                        'commodity': {
                            'available_margin': commodity.get('available_margin', 0),
                            'used_margin': commodity.get('used_margin', 0),
                        },
                        'total_available': equity.get('available_margin', 0) + commodity.get('available_margin', 0),
                        'total_used': equity.get('used_margin', 0) + commodity.get('used_margin', 0)
                    }
            return {}
        except Exception as e:
            print(f"[{self.name}] Error getting funds: {e}")
            return {}
    
    async def get_order_book(self) -> List[Dict[str, Any]]:
        """Get all orders for today"""
        try:
            access_token = self.config.get('access_token')
            url = "https://api.upstox.com/v2/order/retrieve-all"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            print(f"[{self.name}] Fetching order book...")
            response = await asyncio.to_thread(requests.get, url, headers=headers)
            
            print(f"[{self.name}] Order book response: status={response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"[{self.name}] Order book API status: {data.get('status')}")
                if data.get('status') == 'success':
                    orders = data.get('data', [])
                    print(f"[{self.name}] Found {len(orders)} orders")
                    if orders:
                        print(f"[{self.name}] Sample order statuses: {[o.get('status') for o in orders[:5]]}")
                    result = [{
                        'order_id': o.get('order_id'),
                        'trading_symbol': o.get('trading_symbol'),
                        'instrument_token': o.get('instrument_token'),
                        'transaction_type': o.get('transaction_type'),
                        'quantity': o.get('quantity'),
                        'price': o.get('price'),
                        'trigger_price': o.get('trigger_price'),
                        'order_type': o.get('order_type'),
                        'product': o.get('product'),
                        'status': o.get('status'),
                        'filled_quantity': o.get('filled_quantity', 0),
                        'pending_quantity': o.get('pending_quantity', 0),
                        'average_price': o.get('average_price'),
                        'order_timestamp': o.get('order_timestamp'),
                        'exchange_timestamp': o.get('exchange_timestamp'),
                        'exchange': o.get('exchange'),
                        'validity': o.get('validity'),
                    } for o in orders]
                    return result
                else:
                    print(f"[{self.name}] Order book API error: {data}")
            else:
                print(f"[{self.name}] Order book HTTP error: {response.text}")
            return []
        except Exception as e:
            print(f"[{self.name}] Error getting orders: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    async def get_trades(self) -> List[Dict[str, Any]]:
        """Get all trades for today"""
        try:
            access_token = self.config.get('access_token')
            url = "https://api.upstox.com/v2/order/trades/get-trades-for-day"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            response = await asyncio.to_thread(requests.get, url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    trades = data.get('data', [])
                    return [{
                        'trade_id': t.get('trade_id'),
                        'order_id': t.get('order_id'),
                        'trading_symbol': t.get('trading_symbol'),
                        'instrument_token': t.get('instrument_token'),
                        'transaction_type': t.get('transaction_type'),
                        'quantity': t.get('quantity'),
                        'price': t.get('average_price') or t.get('price'),
                        'exchange': t.get('exchange'),
                        'product': t.get('product'),
                        'order_timestamp': t.get('order_timestamp'),
                        'exchange_timestamp': t.get('exchange_timestamp'),
                    } for t in trades]
            return []
        except Exception as e:
            print(f"[{self.name}] Error getting trades: {e}")
            return []
    
    async def get_holdings(self) -> List[Dict[str, Any]]:
        """Get holdings (delivery positions)"""
        if not self.portfolio_api:
            return []
        
        try:
            access_token = self.config.get('access_token')
            url = "https://api.upstox.com/v2/portfolio/long-term-holdings"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            response = await asyncio.to_thread(requests.get, url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    holdings = data.get('data', [])
                    return [{
                        'trading_symbol': h.get('trading_symbol'),
                        'instrument_token': h.get('instrument_token'),
                        'quantity': h.get('quantity'),
                        'average_price': h.get('average_price'),
                        'last_price': h.get('last_price'),
                        'close_price': h.get('close_price'),
                        'pnl': h.get('pnl'),
                        'day_change': h.get('day_change'),
                        'day_change_percentage': h.get('day_change_percentage'),
                        'exchange': h.get('exchange'),
                        'isin': h.get('isin'),
                    } for h in holdings]
            return []
        except Exception as e:
            print(f"[{self.name}] Error getting holdings: {e}")
            return []
    
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open order"""
        try:
            access_token = self.config.get('access_token')
            url = f"https://api.upstox.com/v2/order/cancel"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
            params = {'order_id': order_id}
            
            print(f"[{self.name}] Cancelling order: {order_id}")
            response = await asyncio.to_thread(requests.delete, url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    print(f"[{self.name}] ✓ Order {order_id} cancelled successfully")
                    return {'success': True, 'message': 'Order cancelled successfully', 'data': data.get('data')}
                else:
                    print(f"[{self.name}] ✗ Failed to cancel order: {data}")
                    return {'success': False, 'message': data.get('message', 'Cancel failed')}
            else:
                error_msg = response.text
                print(f"[{self.name}] ✗ Cancel order HTTP error: {response.status_code} - {error_msg}")
                return {'success': False, 'message': f'HTTP {response.status_code}: {error_msg}'}
        except Exception as e:
            print(f"[{self.name}] Error cancelling order: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': str(e)}
    
    def _is_blackout_window(self) -> bool:
        """Check if current time is in Upstox API blackout window (12:00 AM - 5:30 AM IST)"""
        try:
            import pytz
            ist = pytz.timezone('Asia/Kolkata')
            now_ist = datetime.now(ist)
            hour = now_ist.hour
            minute = now_ist.minute
            
            if hour < 5 or (hour == 5 and minute < 30):
                return True
            return False
        except Exception:
            return False
    
    def _get_market_session(self) -> str:
        """Get current market session for logging"""
        try:
            import pytz
            ist = pytz.timezone('Asia/Kolkata')
            now_ist = datetime.now(ist)
            hour = now_ist.hour
            minute = now_ist.minute
            
            if hour < 5 or (hour == 5 and minute < 30):
                return "BLACKOUT (12:00 AM - 5:30 AM IST)"
            elif hour < 9 or (hour == 9 and minute < 15):
                return "PRE-MARKET (AMO Window)"
            elif hour < 15 or (hour == 15 and minute < 30):
                return "MARKET HOURS"
            else:
                return "POST-MARKET (AMO Window)"
        except Exception:
            return "UNKNOWN"

    def _queue_pending_order(self, order_params: Dict[str, Any]) -> Optional[str]:
        """Queue an order for execution after blackout window ends.
        Returns None if AMO queue is disabled."""
        import uuid
        
        if DB_AVAILABLE:
            if not db.get_upstox_amo_queue_enabled():
                print(f"[{self.name}] ❌ AMO queue is disabled - order rejected during blackout")
                return None
        
        with self._pending_order_lock:
            order_id = f"PENDING_{uuid.uuid4().hex[:8]}"
            order_params['pending_order_id'] = order_id
            order_params['queued_at'] = datetime.now().isoformat()
            self._pending_orders.append(order_params)
            
            if DB_AVAILABLE:
                db.save_upstox_pending_order(order_params)
            
            print(f"[{self.name}] 📋 Order queued for AMO submission: {order_id}")
            print(f"[{self.name}]    Pending orders count: {len(self._pending_orders)}")
            
            if not self._pending_order_scheduler_running:
                self._start_pending_order_scheduler()
            
            return order_id
    
    def _start_pending_order_scheduler(self):
        """Start background scheduler to process pending orders after blackout"""
        if self._pending_order_scheduler_running:
            return
        
        self._pending_order_scheduler_running = True
        
        def scheduler_loop():
            import time
            print(f"[{self.name}] ⏰ Pending order scheduler started - checking every 60 seconds")
            while self._pending_order_scheduler_running:
                try:
                    if not self._is_blackout_window():
                        with self._pending_order_lock:
                            if self._pending_orders:
                                print(f"[{self.name}] 🌅 Blackout ended - processing {len(self._pending_orders)} pending orders")
                                self._process_pending_orders_sync()
                    time.sleep(60)
                except Exception as e:
                    print(f"[{self.name}] Pending order scheduler error: {e}")
                    time.sleep(60)
        
        thread = threading.Thread(target=scheduler_loop, daemon=True, name="UpstoxPendingOrderScheduler")
        thread.start()
    
    def _process_pending_orders_sync(self):
        """Process all pending orders synchronously (called from scheduler thread)"""
        if DB_AVAILABLE:
            db_orders = db.get_upstox_pending_orders('PENDING')
            for db_order in db_orders:
                found = any(o.get('pending_order_id') == db_order['pending_order_id'] for o in self._pending_orders)
                if not found:
                    self._pending_orders.append(db_order)
        
        orders_to_process = list(self._pending_orders)
        self._pending_orders.clear()
        
        for order in orders_to_process:
            try:
                pending_id = order.get('pending_order_id', 'unknown')
                print(f"[{self.name}] 📤 Submitting queued order: {pending_id}")
                
                access_token = self.config.get('access_token')
                if not access_token:
                    print(f"[{self.name}] ❌ No access token - cannot submit pending order")
                    if DB_AVAILABLE:
                        db.update_upstox_pending_order_status(pending_id, 'FAILED', error='No access token')
                    continue
                
                order_body = {
                    'quantity': order['quantity'],
                    'product': order['product'],
                    'validity': 'DAY',
                    'price': order.get('price', 0),
                    'instrument_token': order['instrument_token'],
                    'order_type': order['order_type'],
                    'transaction_type': order['transaction_type'],
                    'disclosed_quantity': 0,
                    'trigger_price': 0.0,
                    'is_amo': True,
                    'slice': order.get('slice', True)
                }
                
                url = "https://api-hft.upstox.com/v3/order/place"
                headers = {
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                }
                
                response = requests.post(url, json=order_body, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'success':
                        order_ids = data.get('data', {}).get('order_ids', [])
                        order_ids_str = ','.join(order_ids)
                        print(f"[{self.name}] ✓ Pending order {pending_id} submitted! IDs: {order_ids_str}")
                        if DB_AVAILABLE:
                            db.update_upstox_pending_order_status(pending_id, 'SUBMITTED', order_ids=order_ids_str)
                    else:
                        error_msg = data.get('message', 'Unknown error')
                        print(f"[{self.name}] ❌ Pending order {pending_id} failed: {error_msg}")
                        if DB_AVAILABLE:
                            db.update_upstox_pending_order_status(pending_id, 'FAILED', error=error_msg)
                else:
                    error_msg = f"HTTP error {response.status_code}"
                    print(f"[{self.name}] ❌ Pending order {pending_id}: {error_msg}")
                    if DB_AVAILABLE:
                        db.update_upstox_pending_order_status(pending_id, 'FAILED', error=error_msg)
                    
            except Exception as e:
                print(f"[{self.name}] ❌ Error processing pending order: {e}")
                if DB_AVAILABLE:
                    db.update_upstox_pending_order_status(pending_id, 'FAILED', error=str(e))
    
    def get_pending_orders(self) -> List[Dict]:
        """Get list of pending orders waiting for blackout to end"""
        with self._pending_order_lock:
            if DB_AVAILABLE:
                return db.get_upstox_pending_orders('PENDING')
            return list(self._pending_orders)
    
    def cancel_pending_order(self, pending_order_id: str) -> bool:
        """Cancel a pending order before it's submitted"""
        with self._pending_order_lock:
            self._pending_orders = [o for o in self._pending_orders if o.get('pending_order_id') != pending_order_id]
            
            if DB_AVAILABLE:
                return db.cancel_upstox_pending_order(pending_order_id)
            return True

    async def place_order(self, symbol: str, action: str, quantity: int,
                          order_type: str = 'market', price: float = None,
                          product_type: str = 'INTRADAY', slice_order: bool = True,
                          tag: str = None, symbol_display: str = None, **kwargs) -> OrderResult:
        """Place an order on Upstox using V3 HFT API with auto-slicing support"""
        access_token = self.config.get('access_token')
        if not access_token:
            return OrderResult(success=False, message="Not connected")
        
        session = self._get_market_session()
        print(f"[{self.name}] Market session: {session}")
        
        transaction_type = 'BUY' if action.upper() in ('BTO', 'BUY') else 'SELL'
        upstox_order_type = 'MARKET' if order_type == 'market' else 'LIMIT'
        product = 'I' if product_type == 'INTRADAY' else 'D'
        
        if self._is_blackout_window():
            order_params = {
                'quantity': int(quantity),
                'product': product,
                'price': float(price) if price and upstox_order_type == 'LIMIT' else 0.0,
                'instrument_token': symbol,
                'order_type': upstox_order_type,
                'transaction_type': transaction_type,
                'slice': slice_order,
                'action': action,
                'symbol_display': symbol_display or symbol
            }
            pending_id = self._queue_pending_order(order_params)
            
            if pending_id is None:
                msg = "Order rejected - AMO queue is disabled. Enable AMO queue in settings or wait until 5:30 AM IST."
                print(f"[{self.name}] ❌ {msg}")
                return OrderResult(success=False, message=msg)
            
            msg = f"Order queued (ID: {pending_id}). Will auto-submit after 5:30 AM IST."
            print(f"[{self.name}] ⏳ {msg}")
            return OrderResult(success=True, order_id=pending_id, message=msg)
        
        try:
            order_body = {
                'quantity': int(quantity),
                'product': product,
                'validity': 'DAY',
                'price': float(price) if price and upstox_order_type == 'LIMIT' else 0.0,
                'instrument_token': symbol,
                'order_type': upstox_order_type,
                'transaction_type': transaction_type,
                'disclosed_quantity': 0,
                'trigger_price': 0.0,
                'is_amo': False,
                'slice': slice_order
            }
            
            if tag:
                order_body['tag'] = tag[:40]
            
            print(f"[{self.name}] V3 Order: {transaction_type} {quantity} {symbol} @ {price or 'MARKET'} (slice={slice_order})")
            
            url = "https://api-hft.upstox.com/v3/order/place"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
            
            response = await asyncio.to_thread(requests.post, url, json=order_body, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    order_ids = data.get('data', {}).get('order_ids', [])
                    latency = data.get('metadata', {}).get('latency', 0)
                    order_id_str = ','.join(order_ids) if order_ids else ''
                    print(f"[{self.name}] ✓ Order placed! IDs: {order_id_str} (latency: {latency}ms)")
                    return OrderResult(
                        success=True,
                        order_id=order_id_str,
                        message=f"Order placed: {action} {quantity} {symbol}"
                    )
                else:
                    error_msg = data.get('message', 'Order failed')
                    print(f"[{self.name}] ❌ Order failed: {error_msg}")
                    return OrderResult(success=False, message=error_msg)
            else:
                error_data = {}
                try:
                    error_data = response.json()
                except:
                    pass
                errors = error_data.get('errors', [])
                if errors:
                    error_code = errors[0].get('errorCode', errors[0].get('error_code', ''))
                    error_msg = errors[0].get('message', response.text)
                    print(f"[{self.name}] ❌ Order HTTP {response.status_code} [{error_code}]: {error_msg}")
                    
                    if error_code == 'UDAPI100074':
                        return OrderResult(success=False, message="API blackout (12:00 AM - 5:30 AM IST). Try after 5:30 AM.")
                    elif error_code == 'UDAPI100039':
                        return OrderResult(success=False, message="AMO not allowed during market hours")
                else:
                    error_msg = response.text
                    print(f"[{self.name}] ❌ Order HTTP {response.status_code}: {error_msg}")
                
                return OrderResult(success=False, message=error_msg)
            
        except Exception as e:
            print(f"[{self.name}] ❌ Order FAILED: {e}")
            import traceback
            traceback.print_exc()
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
        lots: int = None,
        **kwargs
    ) -> OrderResult:
        """
        Place an option order on Upstox
        
        Supports both Alpaca-style and Webull-style parameters.
        Looks up the actual Upstox instrument key from API.
        Uses ExpiryResolver to auto-pick next valid expiry when not specified.
        
        For INDIA signals, use 'lots' parameter (raw lot count) to avoid double multiplication.
        If 'lots' is provided, we multiply by lot_size from API.
        If only 'qty' is provided and it's already in units (pre-multiplied), we use it directly.
        """
        actual_opt_type = option_type or opt_type or 'CE'
        actual_expiry = expiry or expiry_mmdd or ''
        actual_price = price or limit_price
        
        opt_suffix = 'CE' if actual_opt_type.lower() in ('c', 'call', 'ce') else 'PE'
        
        if not actual_expiry:
            try:
                from src.services.expiry_resolver import expiry_resolver
                resolved = expiry_resolver.resolve_option(
                    underlying=symbol.upper(),
                    strike=float(strike),
                    option_type=opt_suffix,
                    expiry=None,
                    broker='upstox'
                )
                if resolved:
                    actual_expiry = resolved.expiry_date
                    print(f"[UPSTOX] Auto-resolved expiry: {actual_expiry}")
                    if resolved.instrument_key:
                        instrument_token = resolved.instrument_key
                        api_lot_size = resolved.lot_size
                        print(f"[UPSTOX] ✓ Using resolved instrument: {instrument_token} (lot_size={api_lot_size})")
                        
                        if lots is not None:
                            order_qty = lots * api_lot_size
                            print(f"[UPSTOX] Quantity: {lots} lots x {api_lot_size} = {order_qty} units")
                        elif quantity or qty:
                            raw_qty = quantity or qty
                            if raw_qty < api_lot_size:
                                calculated_lots = 1
                                order_qty = api_lot_size
                                print(f"[UPSTOX] Quantity: {raw_qty} < lot_size({api_lot_size}), using 1 lot = {order_qty} units")
                            else:
                                calculated_lots = max(1, round(raw_qty / api_lot_size))
                                order_qty = calculated_lots * api_lot_size
                                print(f"[UPSTOX] Quantity: {raw_qty} → {calculated_lots} lots x {api_lot_size} = {order_qty} units")
                        else:
                            order_qty = api_lot_size
                            print(f"[UPSTOX] Quantity: defaulting to 1 lot = {order_qty} units")
                        
                        symbol_display = f"{symbol.upper()} {int(strike)} {opt_suffix} {actual_expiry}"
                        print(f"[UPSTOX] Placing option: {action} {order_qty} {instrument_token} @ {actual_price}")
                        
                        order_type = 'limit' if actual_price else 'market'
                        return await self.place_order(
                            symbol=instrument_token,
                            action=action,
                            quantity=order_qty,
                            order_type=order_type,
                            price=actual_price,
                            product_type='INTRADAY',
                            symbol_display=symbol_display
                        )
            except ImportError:
                print("[UPSTOX] ExpiryResolver not available, using fallback lookup")
            except Exception as e:
                print(f"[UPSTOX] ExpiryResolver error: {e}, using fallback lookup")
        
        lookup_result = await self._lookup_instrument_key(
            symbol=symbol.upper(),
            strike=float(strike),
            opt_type=opt_suffix,
            expiry=actual_expiry
        )
        
        instrument_token, api_lot_size = lookup_result
        
        if not instrument_token:
            formatted_expiry = self._format_expiry_for_upstox(actual_expiry)
            instrument_token = f"NSE_FO|{symbol.upper()}{formatted_expiry}{int(strike)}{opt_suffix}"
            api_lot_size = 75
            print(f"[UPSTOX] ⚠️ Could not lookup instrument, using fallback: {instrument_token} (lot_size={api_lot_size})")
        
        if lots is not None:
            order_qty = lots * api_lot_size
            print(f"[UPSTOX] Quantity: {lots} lots x {api_lot_size} = {order_qty} units")
        elif quantity or qty:
            raw_qty = quantity or qty
            if raw_qty < api_lot_size:
                calculated_lots = 1
                order_qty = api_lot_size
                print(f"[UPSTOX] Quantity: {raw_qty} < lot_size({api_lot_size}), using 1 lot = {order_qty} units")
            else:
                calculated_lots = max(1, round(raw_qty / api_lot_size))
                order_qty = calculated_lots * api_lot_size
                print(f"[UPSTOX] Quantity: {raw_qty} → {calculated_lots} lots x {api_lot_size} = {order_qty} units")
        else:
            order_qty = api_lot_size
            print(f"[UPSTOX] Quantity: defaulting to 1 lot = {order_qty} units")
        
        symbol_display = f"{symbol.upper()} {int(strike)} {opt_suffix} {actual_expiry}"
        print(f"[UPSTOX] Placing option: {action} {order_qty} {instrument_token} @ {actual_price}")
        
        order_type = 'limit' if actual_price else 'market'
        return await self.place_order(
            symbol=instrument_token,
            action=action,
            quantity=order_qty,
            order_type=order_type,
            price=actual_price,
            product_type='INTRADAY',
            symbol_display=symbol_display
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
            
            full_url = f"{url}?instrument_key={encoded_key}&expiry_date={formatted_expiry}"
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
            print(f"[UPSTOX] Found {len(contracts)} total contracts")
            
            expiry_contracts = [c for c in contracts if c.get('expiry') == formatted_expiry]
            print(f"[UPSTOX] Filtered to {len(expiry_contracts)} contracts for expiry {formatted_expiry}")
            
            strike_int = int(float(strike)) if strike else 0
            opt_type_normalized = opt_type.upper()
            if opt_type_normalized == 'C':
                opt_type_normalized = 'CE'
            elif opt_type_normalized == 'P':
                opt_type_normalized = 'PE'
            
            print(f"[UPSTOX] Looking for strike={strike_int}, opt_type={opt_type_normalized}")
            
            if expiry_contracts:
                sample_types = list(set([c.get('instrument_type', '') for c in expiry_contracts[:20]]))
                sample_strikes = sorted(list(set([int(float(c.get('strike_price', 0))) for c in expiry_contracts[:20]])))
                print(f"[UPSTOX] Sample types: {sample_types}, Sample strikes: {sample_strikes[:10]}...")
            
            for contract in expiry_contracts:
                contract_strike = int(float(contract.get('strike_price', 0)))
                contract_type = contract.get('instrument_type', '')
                if contract_strike == strike_int and contract_type == opt_type_normalized:
                    instrument_key = contract.get('instrument_key')
                    lot_size = contract.get('lot_size', 1)
                    print(f"[UPSTOX] ✓ Found instrument key: {instrument_key} (lot_size={lot_size})")
                    return instrument_key, lot_size
            
            matching_type = [c for c in expiry_contracts if c.get('instrument_type') == opt_type_normalized]
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
    
    async def get_ltp(self, instrument_key: str) -> Optional[float]:
        """Get last traded price for an instrument key using V3 API.
        
        Uses the V3 LTP endpoint: /v3/market-quote/ltp
        Docs: https://upstox.com/developer/api-documentation/ltp-v3
        """
        access_token = self.config.get('access_token')
        if not access_token:
            print(f"[{self.name}] No access token for LTP fetch")
            return None
        
        try:
            import requests
            from urllib.parse import quote
            
            encoded_key = quote(instrument_key, safe='')
            url = f"https://api.upstox.com/v3/market-quote/ltp?instrument_key={encoded_key}"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
            
            response = await asyncio.to_thread(
                requests.get, url, headers=headers, timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success' and data.get('data'):
                    for key, quote_data in data['data'].items():
                        if isinstance(quote_data, dict) and 'last_price' in quote_data:
                            ltp = float(quote_data['last_price'])
                            print(f"[{self.name}] V3 LTP for {instrument_key}: ₹{ltp:.2f}")
                            return ltp
            else:
                print(f"[{self.name}] LTP V3 API error: {response.status_code} - {response.text[:200]}")
            
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting LTP for {instrument_key}: {e}")
            return None
    
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
    
    async def place_gtt_order(
        self,
        instrument_key: str,
        quantity: int,
        transaction_type: str,  # 'BUY' or 'SELL'
        trigger_type: str,      # 'ABOVE' or 'BELOW'
        trigger_price: float,
        product: str = 'D',     # 'I' (Intraday), 'D' (Delivery), 'MTF'
        stop_loss_price: Optional[float] = None,
        target_price: Optional[float] = None,
        trailing_gap: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Place a GTT (Good Till Triggered) order using V3 API.
        
        Docs: https://upstox.com/developer/api-documentation/place-gtt-order
        
        Args:
            instrument_key: Upstox instrument key (e.g., 'NSE_FO|40477')
            quantity: Order quantity
            transaction_type: 'BUY' or 'SELL'
            trigger_type: 'ABOVE' or 'BELOW' for ENTRY
            trigger_price: Price at which to trigger the order
            product: 'I' (Intraday), 'D' (Delivery), 'MTF'
            stop_loss_price: Optional stop loss trigger price
            target_price: Optional target price
            trailing_gap: Optional trailing stop gap (for TSL orders)
        
        Returns:
            Dict with order result
        """
        access_token = self.config.get('access_token')
        if not access_token:
            return {'success': False, 'error': 'No access token'}
        
        try:
            import requests
            
            rules = [
                {
                    'strategy': 'ENTRY',
                    'trigger_type': trigger_type.upper(),
                    'trigger_price': trigger_price
                }
            ]
            
            gtt_type = 'SINGLE'
            
            if stop_loss_price or target_price:
                gtt_type = 'MULTIPLE'
                
                if target_price:
                    rules.append({
                        'strategy': 'TARGET',
                        'trigger_type': 'IMMEDIATE',
                        'trigger_price': target_price
                    })
                
                if stop_loss_price:
                    sl_rule = {
                        'strategy': 'STOPLOSS',
                        'trigger_type': 'IMMEDIATE',
                        'trigger_price': stop_loss_price
                    }
                    if trailing_gap:
                        sl_rule['trailing_gap'] = trailing_gap
                    rules.append(sl_rule)
            
            payload = {
                'type': gtt_type,
                'quantity': quantity,
                'product': product,
                'instrument_token': instrument_key,
                'transaction_type': transaction_type.upper(),
                'rules': rules
            }
            
            url = 'https://api.upstox.com/v3/order/gtt/place'
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            }
            
            print(f"[{self.name}] Placing GTT order: {payload}")
            
            response = await asyncio.to_thread(
                requests.post, url, json=payload, headers=headers, timeout=30
            )
            
            result = response.json()
            
            if response.status_code in [200, 201] and result.get('status') == 'success':
                gtt_order_ids = result.get('data', {}).get('gtt_order_ids', [])
                print(f"[{self.name}] ✓ GTT order placed: {gtt_order_ids}")
                return {
                    'success': True,
                    'gtt_order_ids': gtt_order_ids,
                    'latency': result.get('metadata', {}).get('latency')
                }
            else:
                error_msg = result.get('errors', [{}])[0].get('message', 'Unknown error')
                print(f"[{self.name}] ❌ GTT order failed: {error_msg}")
                return {'success': False, 'error': error_msg}
                
        except Exception as e:
            print(f"[{self.name}] Error placing GTT order: {e}")
            return {'success': False, 'error': str(e)}

    async def cancel_gtt_order(self, gtt_order_id: str) -> Dict[str, Any]:
        """Cancel a GTT order."""
        access_token = self.config.get('access_token')
        if not access_token:
            return {'success': False, 'error': 'No access token'}
        
        try:
            import requests
            
            url = f'https://api.upstox.com/v3/order/gtt/cancel?gtt_order_id={gtt_order_id}'
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            response = await asyncio.to_thread(
                requests.delete, url, headers=headers, timeout=10
            )
            
            result = response.json()
            
            if response.status_code == 200 and result.get('status') == 'success':
                print(f"[{self.name}] ✓ GTT order cancelled: {gtt_order_id}")
                return {'success': True}
            else:
                error_msg = result.get('errors', [{}])[0].get('message', 'Unknown error')
                return {'success': False, 'error': error_msg}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def get_gtt_order_details(self, gtt_order_id: str) -> Dict[str, Any]:
        """Get details of a GTT order."""
        access_token = self.config.get('access_token')
        if not access_token:
            return {'success': False, 'error': 'No access token'}
        
        try:
            import requests
            
            url = f'https://api.upstox.com/v3/order/gtt/details?gtt_order_id={gtt_order_id}'
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            response = await asyncio.to_thread(
                requests.get, url, headers=headers, timeout=10
            )
            
            result = response.json()
            
            if response.status_code == 200 and result.get('status') == 'success':
                return {'success': True, 'data': result.get('data')}
            else:
                error_msg = result.get('errors', [{}])[0].get('message', 'Unknown error')
                return {'success': False, 'error': error_msg}
                
        except Exception as e:
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
