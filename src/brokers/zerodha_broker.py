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
    
    @staticmethod
    def check_token_expiry(token_issued_at: str = None) -> Dict[str, Any]:
        """
        Check if the Zerodha access token is likely expired.
        Tokens expire daily at 6 AM IST (00:30 UTC).
        
        Args:
            token_issued_at: ISO format timestamp when token was obtained
            
        Returns:
            dict with 'expired' boolean, 'hours_remaining', 'message'
        """
        from datetime import datetime, timedelta
        import pytz
        
        try:
            ist = pytz.timezone('Asia/Kolkata')
            now_ist = datetime.now(ist)
            
            today_6am_ist = now_ist.replace(hour=6, minute=0, second=0, microsecond=0)
            if now_ist.hour < 6:
                expiry_time = today_6am_ist
            else:
                expiry_time = today_6am_ist + timedelta(days=1)
            
            time_remaining = expiry_time - now_ist
            hours_remaining = time_remaining.total_seconds() / 3600
            
            if hours_remaining <= 0:
                return {
                    'expired': True,
                    'hours_remaining': 0,
                    'message': 'Token has expired. Please login again to get a new request_token.'
                }
            elif hours_remaining <= 1:
                return {
                    'expired': False,
                    'hours_remaining': round(hours_remaining, 1),
                    'message': f'Token expiring soon! Only {round(hours_remaining * 60)} minutes remaining until 6 AM IST.'
                }
            else:
                return {
                    'expired': False,
                    'hours_remaining': round(hours_remaining, 1),
                    'message': f'Token valid. Expires in {round(hours_remaining, 1)} hours at 6 AM IST.'
                }
        except Exception as e:
            return {
                'expired': False,
                'hours_remaining': -1,
                'message': f'Could not determine token status: {e}'
            }
    
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
            
            expiry_status = self.check_token_expiry()
            if expiry_status.get('expired'):
                print(f"[{self.name}] ⚠️ {expiry_status['message']}")
            elif expiry_status.get('hours_remaining', 99) <= 2:
                print(f"[{self.name}] ⚠️ {expiry_status['message']}")
            
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
    
    async def get_account_balance(self) -> Dict[str, Any]:
        """Get account balance for India Markets page - calls Zerodha margins API"""
        if not self.kite:
            return {'available': 0, 'margin_used': 0, 'currency': self.CURRENCY}
        
        try:
            print(f"[{self.name}] Fetching account balance from Zerodha API...")
            margins = await asyncio.to_thread(self.kite.margins)
            
            equity = margins.get('equity', {})
            commodity = margins.get('commodity', {})
            
            available = equity.get('available', {}).get('cash', 0) + commodity.get('available', {}).get('cash', 0)
            margin_used = equity.get('utilised', {}).get('debits', 0) + commodity.get('utilised', {}).get('debits', 0)
            
            print(f"[{self.name}] Balance fetched: available=₹{available}, margin_used=₹{margin_used}")
            
            return {
                'available': available,
                'margin_used': margin_used,
                'equity_available': equity.get('available', {}).get('cash', 0),
                'equity_net': equity.get('net', 0),
                'commodity_available': commodity.get('available', {}).get('cash', 0),
                'commodity_net': commodity.get('net', 0),
                'currency': self.CURRENCY
            }
        except Exception as e:
            print(f"[{self.name}] Error getting account balance: {e}")
            return {'available': 0, 'margin_used': 0, 'currency': self.CURRENCY}
    
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
    
    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        exchange: str = 'NSE',
        product: str = 'CNC'
    ) -> OrderResult:
        """
        Place a stock order on Zerodha (standardized interface)
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'SBIN')
            action: 'BTO' (buy) or 'STC' (sell)
            quantity: Number of shares
            price: Limit price (None for market order)
            exchange: NSE or BSE (default: NSE)
            product: CNC (delivery) or MIS (intraday)
        """
        order_type = 'limit' if price else 'market'
        return await self.place_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type=order_type,
            price=price,
            exchange=exchange,
            product=product
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
        Place an option order on Zerodha (standardized interface)
        
        Supports both Alpaca-style and Webull-style parameters.
        Builds the Zerodha trading symbol and submits order.
        
        Args:
            symbol: Underlying symbol (e.g., 'NIFTY', 'BANKNIFTY')
            strike: Strike price
            expiry: Expiry date (various formats supported)
            option_type/opt_type: 'CE' (call) or 'PE' (put)
            action: 'BTO' (buy) or 'STC' (sell)
            quantity/qty: Number of contracts
            price/limit_price: Limit price (None for market order)
            lots: Number of lots (multiplied by lot size)
        """
        actual_opt_type = option_type or opt_type or 'CE'
        actual_expiry = expiry or expiry_mmdd or ''
        actual_price = price or limit_price
        actual_qty = quantity or qty or 1
        
        opt_suffix = 'CE' if actual_opt_type.upper() in ('C', 'CALL', 'CE') else 'PE'
        
        LOT_SIZES = {
            'NIFTY': 25, 'BANKNIFTY': 15, 'FINNIFTY': 25, 'MIDCPNIFTY': 50,
            'RELIANCE': 250, 'TCS': 150, 'INFY': 300, 'HDFCBANK': 550,
            'ICICIBANK': 1375, 'SBIN': 1500, 'TATAMOTORS': 1425
        }
        lot_size = LOT_SIZES.get(symbol.upper(), 50)
        
        if lots is not None:
            order_qty = lots * lot_size
            print(f"[{self.name}] Quantity: {lots} lots x {lot_size} = {order_qty} units")
        elif actual_qty < lot_size:
            order_qty = lot_size
            print(f"[{self.name}] Quantity: {actual_qty} < lot_size({lot_size}), using 1 lot")
        else:
            calculated_lots = max(1, round(actual_qty / lot_size))
            order_qty = calculated_lots * lot_size
            print(f"[{self.name}] Quantity: {actual_qty} → {calculated_lots} lots = {order_qty} units")
        
        try:
            expiry_formatted = ''
            if actual_expiry:
                from datetime import datetime
                MONTH_MAP = {
                    1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN',
                    7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'O', 11: 'N', 12: 'D'
                }
                WEEK_MONTH_MAP = {
                    1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6',
                    7: '7', 8: '8', 9: '9', 10: 'O', 11: 'N', 12: 'D'
                }
                
                if '/' in actual_expiry:
                    parts = actual_expiry.split('/')
                    if len(parts) == 2:
                        month, day = int(parts[0]), int(parts[1])
                        year = datetime.now().year % 100
                        month_code = WEEK_MONTH_MAP.get(month, str(month))
                        expiry_formatted = f"{year}{month_code}{day:02d}"
                elif '-' in actual_expiry:
                    exp_date = datetime.strptime(actual_expiry, '%Y-%m-%d')
                    year = exp_date.year % 100
                    month_code = WEEK_MONTH_MAP.get(exp_date.month, str(exp_date.month))
                    expiry_formatted = f"{year}{month_code}{exp_date.day:02d}"
                else:
                    expiry_formatted = actual_expiry
            
            trading_symbol = f"{symbol.upper()}{expiry_formatted}{int(strike)}{opt_suffix}"
            print(f"[{self.name}] Built trading symbol: {trading_symbol}")
        except Exception as e:
            print(f"[{self.name}] Error building trading symbol: {e}")
            trading_symbol = f"{symbol.upper()}{int(strike)}{opt_suffix}"
        
        order_type = 'limit' if actual_price else 'market'
        
        print(f"[{self.name}] Placing option: {action} {order_qty} {trading_symbol} @ {actual_price or 'MARKET'}")
        
        return await self.place_order(
            symbol=trading_symbol,
            action=action,
            quantity=order_qty,
            order_type=order_type,
            price=actual_price,
            exchange='NFO',
            product='NRML'
        )
    
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
            print(f"[ZERODHA DEBUG] test_connection called")
            print(f"[ZERODHA DEBUG]   api_key: {'***' + api_key[-4:] if api_key and len(api_key) > 4 else 'NONE'}")
            print(f"[ZERODHA DEBUG]   access_token: {'***' + access_token[-8:] if access_token and len(access_token) > 8 else 'NONE'}")
            print(f"[ZERODHA DEBUG]   api_secret: {'***' + api_secret[-4:] if api_secret and len(api_secret) > 4 else 'NONE'}")
            print(f"[ZERODHA DEBUG]   request_token: {'***' + request_token[-8:] if request_token and len(request_token) > 8 else 'NONE'}")
            
            if not KITE_AVAILABLE:
                print(f"[ZERODHA DEBUG] KITE_AVAILABLE=False")
                return {
                    'success': False,
                    'message': 'Kite Connect library not installed. Run: pip install kiteconnect'
                }
            
            kite = KiteConnect(api_key=api_key)
            new_access_token = None
            used_request_token_flow = False
            
            if access_token:
                print(f"[ZERODHA DEBUG] Trying access_token flow...")
                try:
                    kite.set_access_token(access_token)
                    profile = kite.profile()
                    if profile:
                        print(f"[ZERODHA DEBUG] Access token worked! User: {profile.get('user_id')}")
                        return {
                            'success': True,
                            'message': f"Connected! User: {profile.get('user_name', 'N/A')} ({profile.get('user_id', 'N/A')})",
                            'user_id': profile.get('user_id'),
                            'user_name': profile.get('user_name'),
                            'access_token': access_token
                        }
                except Exception as token_err:
                    print(f"[ZERODHA DEBUG] Access token failed: {token_err}")
                    if request_token and api_secret:
                        print(f"[ZERODHA DEBUG] Will try request_token flow as fallback...")
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
                print(f"[ZERODHA DEBUG] Trying request_token + api_secret flow...")
                print(f"[ZERODHA DEBUG] Calling kite.generate_session()...")
                data = kite.generate_session(request_token, api_secret=api_secret)
                print(f"[ZERODHA DEBUG] generate_session returned: {list(data.keys()) if data else 'None'}")
                new_access_token = data["access_token"]
                kite.set_access_token(new_access_token)
                used_request_token_flow = True
                print(f"[ZERODHA DEBUG] Request token flow succeeded, got new access_token")
            elif not access_token:
                print(f"[ZERODHA DEBUG] FAILED: No access_token and no (request_token + api_secret)")
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
                    'message': f"Connected! User: {profile.get('user_name', 'N/A')} ({profile.get('user_id', 'N/A')}). Token expires 6 AM IST.",
                    'user_id': profile.get('user_id'),
                    'user_name': profile.get('user_name'),
                    'token_expiry': '6 AM IST daily'
                }
                if new_access_token:
                    result['access_token'] = new_access_token
                    result['used_request_token_flow'] = True
                    if 'login_time' in data:
                        result['login_time'] = data['login_time']
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
