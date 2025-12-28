"""
DhanQ Broker Implementation (India)
DhanHQ v2 API trading platform for Indian markets (NSE/BSE/MCX)
Documentation: https://dhanhq.co/docs/v2/
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
    from dhanhq import dhanhq
    DHANHQ_AVAILABLE = True
except ImportError:
    DHANHQ_AVAILABLE = False
    print("[DHANQ] Warning: dhanhq not installed. Install with: pip install dhanhq")


class DhanQBroker(BrokerInterface):
    """DhanQ broker implementation for Indian markets using DhanHQ v2 API"""
    
    COUNTRY_CODE = 'IN'
    CURRENCY = 'INR'
    API_BASE_URL = 'https://api.dhan.co/v2'
    
    EXCHANGE_SEGMENTS = {
        'NSE_EQ': 'NSE_EQ',
        'NSE_FNO': 'NSE_FNO',
        'NSE_CURRENCY': 'NSE_CURRENCY',
        'BSE_EQ': 'BSE_EQ',
        'BSE_FNO': 'BSE_FNO',
        'BSE_CURRENCY': 'BSE_CURRENCY',
        'MCX_COMM': 'MCX_COMM'
    }
    
    PRODUCT_TYPES = {
        'CNC': 'CNC',
        'INTRADAY': 'INTRADAY',
        'MARGIN': 'MARGIN',
        'MTF': 'MTF',
        'CO': 'CO',
        'BO': 'BO'
    }
    
    ORDER_TYPES = {
        'LIMIT': 'LIMIT',
        'MARKET': 'MARKET',
        'STOP_LOSS': 'STOP_LOSS',
        'STOP_LOSS_MARKET': 'STOP_LOSS_MARKET'
    }
    
    NSE_SECURITY_IDS = {
        'NIFTY': 26000,
        'BANKNIFTY': 26009,
        'FINNIFTY': 26037,
        'MIDCPNIFTY': 26074,
        'RELIANCE': 2885,
        'TCS': 11536,
        'INFY': 1594,
        'HDFCBANK': 1333,
        'ICICIBANK': 4963,
        'SBIN': 3045,
        'TATAMOTORS': 3456,
        'TATASTEEL': 3499,
        'ITC': 1660,
        'HINDUNILVR': 1394,
        'BAJFINANCE': 317,
        'LT': 11483,
        'AXISBANK': 5900,
        'KOTAKBANK': 1922,
        'MARUTI': 10999,
        'BHARTIARTL': 10604,
        'ASIANPAINT': 236,
        'WIPRO': 3787,
        'HCLTECH': 7229,
        'ADANIENT': 25,
        'ADANIPORTS': 15083,
        'COALINDIA': 20374,
        'ONGC': 2475,
        'POWERGRID': 14977,
        'NTPC': 11630,
        'SUNPHARMA': 3351,
        'TITAN': 3506,
        'TECHM': 13538,
        'ULTRACEMCO': 11532,
        'NESTLEIND': 17963,
        'DRREDDY': 881,
        'CIPLA': 694,
        'M&M': 2031,
        'BAJAJFINSV': 16675,
        'EICHERMOT': 910,
        'GRASIM': 1232,
        'JSWSTEEL': 11723,
        'BRITANNIA': 547,
        'HINDALCO': 1363,
        'DIVISLAB': 10940,
        'APOLLOHOSP': 157,
        'SBILIFE': 21808,
    }
    
    NSE_LOT_SIZES = {
        'NIFTY': 25,
        'BANKNIFTY': 15,
        'FINNIFTY': 25,
        'MIDCPNIFTY': 50,
        'SENSEX': 10,
        'BANKEX': 15,
        'RELIANCE': 250,
        'TCS': 150,
        'INFY': 300,
        'HDFCBANK': 550,
        'ICICIBANK': 1375,
        'SBIN': 1500,
        'TATAMOTORS': 1425,
        'TATASTEEL': 1500,
        'ITC': 1600,
        'HINDUNILVR': 300,
        'BAJFINANCE': 125,
        'LT': 150,
        'AXISBANK': 600,
        'KOTAKBANK': 400,
        'MARUTI': 100,
        'BHARTIARTL': 950,
        'ASIANPAINT': 200,
        'WIPRO': 1500,
        'HCLTECH': 350,
        'ADANIENT': 250,
        'ADANIPORTS': 1250,
        'COALINDIA': 2100,
        'ONGC': 3850,
        'POWERGRID': 2700,
        'NTPC': 2925,
    }
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "DHANQ"
        self.dhan = None
        self.client_id = None
        self.access_token = None
        self.session = requests.Session()
    
    @property
    def is_live(self) -> bool:
        """DhanQ is always live trading"""
        return True
    
    def _get_headers(self) -> Dict[str, str]:
        """Get API request headers"""
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'access-token': self.access_token or ''
        }
    
    def get_security_id(self, symbol: str) -> Optional[int]:
        """
        Get security ID for a symbol.
        
        Args:
            symbol: Trading symbol (e.g., NIFTY, BANKNIFTY, RELIANCE)
            
        Returns:
            Security ID or None if not found
        """
        return self.NSE_SECURITY_IDS.get(symbol.upper())
    
    def get_lot_size(self, symbol: str) -> int:
        """
        Get lot size for F&O symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Lot size (defaults to 1 for unknown symbols)
        """
        return self.NSE_LOT_SIZES.get(symbol.upper(), 1)
    
    def build_option_security_id(self, symbol: str, strike: float, option_type: str, expiry_date: str) -> Optional[str]:
        """
        Build option security ID for F&O trading.
        
        DhanQ option format: SYMBOL EXPIRY STRIKE OPTTYPE
        Example: NIFTY 02JAN25 24000 CE
        
        Args:
            symbol: Underlying symbol (e.g., NIFTY, BANKNIFTY)
            strike: Strike price
            option_type: CE or PE (Call/Put European)
            expiry_date: Expiry in MM/DD or DD MMM YY format
            
        Returns:
            Option trading symbol for DhanQ
        """
        symbol = symbol.upper()
        opt_type = 'CE' if option_type.upper() in ('C', 'CE', 'CALL') else 'PE'
        
        try:
            from datetime import datetime
            
            if '/' in expiry_date:
                parts = expiry_date.split('/')
                month = int(parts[0])
                day = int(parts[1])
                year = datetime.now().year
                if month < datetime.now().month:
                    year += 1
                expiry_dt = datetime(year, month, day)
            else:
                expiry_dt = datetime.strptime(expiry_date, '%d %b %Y')
            
            expiry_str = expiry_dt.strftime('%d%b%y').upper()
            
            strike_str = str(int(strike)) if strike == int(strike) else str(strike)
            
            option_symbol = f"{symbol} {expiry_str} {strike_str} {opt_type}"
            print(f"[{self.name}] Built option symbol: {option_symbol}")
            return option_symbol
            
        except Exception as e:
            print(f"[{self.name}] Error building option security ID: {e}")
            return None
    
    async def connect(self) -> bool:
        """Connect to DhanQ using client ID and access token"""
        try:
            self.client_id = self.config.get('client_id')
            self.access_token = self.config.get('access_token')
            
            if not self.client_id or not self.access_token:
                print(f"[{self.name}] Client ID and access token required")
                return False
            
            print(f"[{self.name}] Connecting to DhanHQ v2 API...")
            
            if DHANHQ_AVAILABLE:
                self.dhan = dhanhq(self.client_id, self.access_token)
            
            fund_limits = await self._get_fund_limits()
            
            if fund_limits:
                available = fund_limits.get('availabelBalance', 'N/A')
                print(f"[{self.name}] Connected! Client: {self.client_id} | Available: ₹{available}")
                self.connected = True
                return True
            else:
                print(f"[{self.name}] Connection test failed - unable to fetch fund limits")
                return False
                
        except Exception as e:
            print(f"[{self.name}] Connection failed: {e}")
            self.connected = False
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from DhanQ"""
        self.dhan = None
        self.access_token = None
        self.connected = False
        print(f"[{self.name}] Disconnected")
        return True
    
    async def _get_fund_limits(self) -> Optional[Dict]:
        """Get fund limits from API"""
        try:
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.API_BASE_URL}/fundlimit",
                headers=self._get_headers()
            )
            
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting fund limits: {e}")
            return None
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information including fund limits"""
        if not self.access_token:
            return {}
        
        try:
            fund_limits = await self._get_fund_limits()
            return {
                'client_id': self.client_id,
                'currency': self.CURRENCY,
                'available_balance': fund_limits.get('availabelBalance', 0) if fund_limits else 0,
                'sod_limit': fund_limits.get('sodLimit', 0) if fund_limits else 0,
                'collateral_amount': fund_limits.get('collateralAmount', 0) if fund_limits else 0,
                'utilized_amount': fund_limits.get('utilizedAmount', 0) if fund_limits else 0,
                'withdrawable_balance': fund_limits.get('withdrawableBalance', 0) if fund_limits else 0,
                'fund_limits': fund_limits
            }
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            return {}
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions"""
        if not self.access_token:
            return []
        
        try:
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.API_BASE_URL}/positions",
                headers=self._get_headers()
            )
            
            if response.status_code == 200:
                positions = response.json()
                return self._normalize_positions(positions) if positions else []
            return []
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return []
    
    def _normalize_positions(self, positions: List[Dict]) -> List[Dict]:
        """Normalize position data to standard format"""
        normalized = []
        for pos in positions:
            normalized.append({
                'symbol': pos.get('tradingSymbol', ''),
                'security_id': pos.get('securityId', ''),
                'exchange': pos.get('exchangeSegment', ''),
                'position_type': pos.get('positionType', ''),
                'product_type': pos.get('productType', ''),
                'quantity': pos.get('netQty', 0),
                'buy_qty': pos.get('buyQty', 0),
                'sell_qty': pos.get('sellQty', 0),
                'buy_avg': pos.get('buyAvg', 0),
                'sell_avg': pos.get('sellAvg', 0),
                'cost_price': pos.get('costPrice', 0),
                'realized_pnl': pos.get('realizedProfit', 0),
                'unrealized_pnl': pos.get('unrealizedProfit', 0),
                'expiry': pos.get('drvExpiryDate'),
                'option_type': pos.get('drvOptionType'),
                'strike_price': pos.get('drvStrikePrice', 0),
                'raw': pos
            })
        return normalized
    
    async def get_holdings(self) -> List[Dict[str, Any]]:
        """Get current holdings (delivery positions)"""
        if not self.access_token:
            return []
        
        try:
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.API_BASE_URL}/holdings",
                headers=self._get_headers()
            )
            
            if response.status_code == 200:
                holdings = response.json()
                return self._normalize_holdings(holdings) if holdings else []
            return []
        except Exception as e:
            print(f"[{self.name}] Error getting holdings: {e}")
            return []
    
    def _normalize_holdings(self, holdings: List[Dict]) -> List[Dict]:
        """Normalize holdings data to standard format"""
        normalized = []
        for holding in holdings:
            normalized.append({
                'symbol': holding.get('tradingSymbol', ''),
                'security_id': holding.get('securityId', ''),
                'isin': holding.get('isin', ''),
                'exchange': holding.get('exchange', ''),
                'quantity': holding.get('totalQty', 0),
                'available_qty': holding.get('availableQty', 0),
                't1_qty': holding.get('t1Qty', 0),
                'collateral_qty': holding.get('collateralQty', 0),
                'avg_cost_price': holding.get('avgCostPrice', 0),
                'raw': holding
            })
        return normalized
    
    async def place_order(self, security_id: str, action: str, quantity: int,
                          order_type: str = 'MARKET', price: float = None,
                          exchange_segment: str = 'NSE_EQ', product_type: str = 'INTRADAY',
                          validity: str = 'DAY', trigger_price: float = None,
                          disclosed_quantity: int = None, correlation_id: str = None,
                          **kwargs) -> OrderResult:
        """
        Place an order on DhanQ
        
        Args:
            security_id: Exchange standard ID for the scrip
            action: BTO/BUY or STC/SELL
            quantity: Number of shares
            order_type: LIMIT, MARKET, STOP_LOSS, STOP_LOSS_MARKET
            price: Price for limit orders
            exchange_segment: NSE_EQ, NSE_FNO, BSE_EQ, MCX_COMM, etc.
            product_type: CNC, INTRADAY, MARGIN, MTF, CO, BO
            validity: DAY or IOC
            trigger_price: For stop loss orders
            disclosed_quantity: Visible quantity (min 30% of quantity)
            correlation_id: User tracking ID
        """
        if not self.access_token:
            return OrderResult(success=False, message="Not connected to DhanQ")
        
        try:
            transaction_type = 'BUY' if action.upper() in ['BTO', 'BUY'] else 'SELL'
            
            order_data = {
                'dhanClientId': self.client_id,
                'transactionType': transaction_type,
                'exchangeSegment': exchange_segment,
                'productType': product_type,
                'orderType': order_type.upper(),
                'validity': validity,
                'securityId': str(security_id),
                'quantity': int(quantity),
                'price': float(price) if price else 0,
                'afterMarketOrder': False
            }
            
            if correlation_id:
                order_data['correlationId'] = correlation_id
            
            if trigger_price:
                order_data['triggerPrice'] = float(trigger_price)
            
            if disclosed_quantity:
                order_data['disclosedQuantity'] = int(disclosed_quantity)
            
            if kwargs.get('bo_profit'):
                order_data['boProfitValue'] = float(kwargs['bo_profit'])
            if kwargs.get('bo_stop_loss'):
                order_data['boStopLossValue'] = float(kwargs['bo_stop_loss'])
            
            response = await asyncio.to_thread(
                self.session.post,
                f"{self.API_BASE_URL}/orders",
                headers=self._get_headers(),
                json=order_data
            )
            
            result = response.json()
            
            if response.status_code in [200, 201] and result.get('orderId'):
                return OrderResult(
                    success=True,
                    order_id=str(result.get('orderId')),
                    message=f"Order placed: {transaction_type} {quantity} {security_id}",
                    data={'order_status': result.get('orderStatus')}
                )
            else:
                error_msg = result.get('errorMessage') or result.get('remarks') or 'Order failed'
                return OrderResult(success=False, message=error_msg, data=result)
            
        except Exception as e:
            return OrderResult(success=False, message=str(e))
    
    async def place_slice_order(self, security_id: str, action: str, quantity: int,
                                order_type: str = 'MARKET', price: float = None,
                                exchange_segment: str = 'NSE_FNO', product_type: str = 'INTRADAY',
                                **kwargs) -> List[OrderResult]:
        """
        Place sliced orders for quantities over freeze limit (F&O)
        Automatically slices into multiple legs
        """
        if not self.access_token:
            return [OrderResult(success=False, message="Not connected to DhanQ")]
        
        try:
            transaction_type = 'BUY' if action.upper() in ['BTO', 'BUY'] else 'SELL'
            
            order_data = {
                'dhanClientId': self.client_id,
                'transactionType': transaction_type,
                'exchangeSegment': exchange_segment,
                'productType': product_type,
                'orderType': order_type.upper(),
                'validity': 'DAY',
                'securityId': str(security_id),
                'quantity': int(quantity),
                'price': float(price) if price else 0,
                'afterMarketOrder': False
            }
            
            response = await asyncio.to_thread(
                self.session.post,
                f"{self.API_BASE_URL}/orders/slicing",
                headers=self._get_headers(),
                json=order_data
            )
            
            results = response.json()
            
            if response.status_code in [200, 201] and isinstance(results, list):
                return [
                    OrderResult(
                        success=True,
                        order_id=str(r.get('orderId')),
                        message=f"Slice order: {r.get('orderStatus')}",
                        data=r
                    ) for r in results
                ]
            else:
                error_msg = results.get('errorMessage', 'Slice order failed') if isinstance(results, dict) else 'Slice order failed'
                return [OrderResult(success=False, message=error_msg)]
            
        except Exception as e:
            return [OrderResult(success=False, message=str(e))]
    
    async def modify_order(self, order_id: str, quantity: int = None,
                           price: float = None, order_type: str = None,
                           trigger_price: float = None, validity: str = 'DAY',
                           leg_name: str = None, **kwargs) -> OrderResult:
        """Modify a pending order"""
        if not self.access_token:
            return OrderResult(success=False, message="Not connected to DhanQ")
        
        try:
            modify_data = {
                'dhanClientId': self.client_id,
                'orderId': str(order_id),
                'validity': validity
            }
            
            if quantity:
                modify_data['quantity'] = int(quantity)
            if price:
                modify_data['price'] = float(price)
            if order_type:
                modify_data['orderType'] = order_type.upper()
            if trigger_price:
                modify_data['triggerPrice'] = float(trigger_price)
            if leg_name:
                modify_data['legName'] = leg_name
            
            response = await asyncio.to_thread(
                self.session.put,
                f"{self.API_BASE_URL}/orders/{order_id}",
                headers=self._get_headers(),
                json=modify_data
            )
            
            result = response.json()
            
            if response.status_code in [200, 202]:
                return OrderResult(
                    success=True,
                    order_id=str(result.get('orderId', order_id)),
                    message=f"Order modified: {result.get('orderStatus', 'Updated')}"
                )
            else:
                error_msg = result.get('errorMessage', 'Modification failed')
                return OrderResult(success=False, message=error_msg)
            
        except Exception as e:
            return OrderResult(success=False, message=str(e))
    
    async def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel a pending order"""
        if not self.access_token:
            return OrderResult(success=False, message="Not connected to DhanQ")
        
        try:
            response = await asyncio.to_thread(
                self.session.delete,
                f"{self.API_BASE_URL}/orders/{order_id}",
                headers=self._get_headers()
            )
            
            if response.status_code in [200, 202]:
                result = response.json() if response.text else {}
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    message=f"Order cancelled: {result.get('orderStatus', 'CANCELLED')}"
                )
            else:
                result = response.json() if response.text else {}
                return OrderResult(
                    success=False,
                    message=result.get('errorMessage', 'Cancellation failed')
                )
            
        except Exception as e:
            return OrderResult(success=False, message=str(e))
    
    async def get_orders(self) -> List[Dict[str, Any]]:
        """Get all orders for the day"""
        if not self.access_token:
            return []
        
        try:
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.API_BASE_URL}/orders",
                headers=self._get_headers()
            )
            
            if response.status_code == 200:
                orders = response.json()
                return self._normalize_orders(orders) if orders else []
            return []
        except Exception as e:
            print(f"[{self.name}] Error getting orders: {e}")
            return []
    
    def _normalize_orders(self, orders: List[Dict]) -> List[Dict]:
        """Normalize order data to standard format"""
        normalized = []
        for order in orders:
            normalized.append({
                'order_id': order.get('orderId', ''),
                'correlation_id': order.get('correlationId', ''),
                'symbol': order.get('tradingSymbol', ''),
                'security_id': order.get('securityId', ''),
                'exchange': order.get('exchangeSegment', ''),
                'transaction_type': order.get('transactionType', ''),
                'product_type': order.get('productType', ''),
                'order_type': order.get('orderType', ''),
                'validity': order.get('validity', ''),
                'status': order.get('orderStatus', ''),
                'quantity': order.get('quantity', 0),
                'filled_qty': order.get('filledQty', 0),
                'remaining_qty': order.get('remainingQuantity', 0),
                'price': order.get('price', 0),
                'trigger_price': order.get('triggerPrice', 0),
                'avg_price': order.get('averageTradedPrice', 0),
                'expiry': order.get('drvExpiryDate'),
                'option_type': order.get('drvOptionType'),
                'strike_price': order.get('drvStrikePrice', 0),
                'create_time': order.get('createTime'),
                'update_time': order.get('updateTime'),
                'exchange_time': order.get('exchangeTime'),
                'error_code': order.get('omsErrorCode'),
                'error_message': order.get('omsErrorDescription'),
                'raw': order
            })
        return normalized
    
    async def get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order details by order ID"""
        if not self.access_token:
            return None
        
        try:
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.API_BASE_URL}/orders/{order_id}",
                headers=self._get_headers()
            )
            
            if response.status_code == 200:
                order = response.json()
                normalized = self._normalize_orders([order])
                return normalized[0] if normalized else None
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting order {order_id}: {e}")
            return None
    
    async def get_trades(self) -> List[Dict[str, Any]]:
        """Get all trades for the day"""
        if not self.access_token:
            return []
        
        try:
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.API_BASE_URL}/trades",
                headers=self._get_headers()
            )
            
            if response.status_code == 200:
                trades = response.json()
                return trades if trades else []
            return []
        except Exception as e:
            print(f"[{self.name}] Error getting trades: {e}")
            return []
    
    async def get_margin_calculator(self, security_id: str, exchange_segment: str,
                                     transaction_type: str, quantity: int,
                                     product_type: str, price: float,
                                     trigger_price: float = None) -> Optional[Dict]:
        """Calculate margin requirements for an order"""
        if not self.access_token:
            return None
        
        try:
            margin_data = {
                'dhanClientId': self.client_id,
                'exchangeSegment': exchange_segment,
                'transactionType': transaction_type,
                'quantity': quantity,
                'productType': product_type,
                'securityId': str(security_id),
                'price': price
            }
            
            if trigger_price:
                margin_data['triggerPrice'] = trigger_price
            
            response = await asyncio.to_thread(
                self.session.post,
                f"{self.API_BASE_URL}/margincalculator",
                headers=self._get_headers(),
                json=margin_data
            )
            
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"[{self.name}] Error calculating margin: {e}")
            return None
    
    async def convert_position(self, security_id: str, exchange_segment: str,
                               position_type: str, from_product: str,
                               to_product: str, quantity: int,
                               trading_symbol: str = '') -> bool:
        """Convert position from one product type to another"""
        if not self.access_token:
            return False
        
        try:
            convert_data = {
                'dhanClientId': self.client_id,
                'fromProductType': from_product,
                'exchangeSegment': exchange_segment,
                'positionType': position_type,
                'securityId': str(security_id),
                'tradingSymbol': trading_symbol,
                'convertQty': str(quantity),
                'toProductType': to_product
            }
            
            response = await asyncio.to_thread(
                self.session.post,
                f"{self.API_BASE_URL}/positions/convert",
                headers=self._get_headers(),
                json=convert_data
            )
            
            return response.status_code == 202
        except Exception as e:
            print(f"[{self.name}] Error converting position: {e}")
            return False
    
    async def refresh_token(self) -> bool:
        """Refresh the access token for another 24 hours"""
        if not self.access_token or not self.client_id:
            return False
        
        try:
            headers = {
                'access-token': self.access_token,
                'dhanClientId': self.client_id
            }
            
            response = await asyncio.to_thread(
                self.session.get,
                f"{self.API_BASE_URL}/RenewToken",
                headers=headers
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('accessToken'):
                    self.access_token = result['accessToken']
                    print(f"[{self.name}] Token refreshed successfully")
                    return True
            
            print(f"[{self.name}] Token refresh failed")
            return False
        except Exception as e:
            print(f"[{self.name}] Error refreshing token: {e}")
            return False

    @staticmethod
    def test_connection(client_id: str, access_token: str) -> Dict[str, Any]:
        """Test connection with provided credentials"""
        try:
            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'access-token': access_token
            }
            
            response = requests.get(
                f'https://api.dhan.co/v2/fundlimit',
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                fund_limits = response.json()
                available = fund_limits.get('availabelBalance', 'N/A')
                withdrawable = fund_limits.get('withdrawableBalance', 'N/A')
                
                holdings_resp = requests.get(
                    f'https://api.dhan.co/v2/holdings',
                    headers=headers,
                    timeout=10
                )
                holdings_count = len(holdings_resp.json()) if holdings_resp.status_code == 200 and holdings_resp.json() else 0
                
                return {
                    'success': True,
                    'message': f"Connected! Client: {client_id} | Available: ₹{available} | Holdings: {holdings_count}",
                    'client_id': client_id,
                    'available_balance': available,
                    'withdrawable_balance': withdrawable,
                    'holdings_count': holdings_count
                }
            elif response.status_code == 401:
                return {
                    'success': False,
                    'message': 'Access token expired or invalid. Tokens are valid for 24 hours only. Generate new token from web.dhan.co'
                }
            else:
                error = response.json() if response.text else {}
                return {
                    'success': False,
                    'message': f"Connection failed: {error.get('errorMessage', response.status_code)}"
                }
                
        except requests.Timeout:
            return {
                'success': False,
                'message': 'Connection timeout - DhanHQ API not responding'
            }
        except Exception as e:
            error_msg = str(e)
            if 'unauthorized' in error_msg.lower() or '401' in error_msg:
                return {
                    'success': False,
                    'message': 'Access token expired or invalid. Generate new token from web.dhan.co'
                }
            return {
                'success': False,
                'message': f'Connection failed: {error_msg}'
            }


BrokerFactory.register_broker('DHANQ', DhanQBroker)
