"""
Dhan Broker Implementation (India)
Simple token-based trading platform for Indian markets (NSE/BSE)
"""

import sys
import os
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory

try:
    from dhanhq import dhanhq, DhanContext
    DHAN_AVAILABLE = True
    DHAN_V2 = True
except ImportError:
    try:
        from dhanhq import dhanhq
        DHAN_AVAILABLE = True
        DHAN_V2 = False
    except ImportError:
        DHAN_AVAILABLE = False
        DHAN_V2 = False
        print("[DHAN] Warning: dhanhq not installed. Install with: pip install dhanhq")


class DhanBroker(BrokerInterface):
    """Dhan broker implementation for Indian markets"""
    
    COUNTRY_CODE = 'IN'
    CURRENCY = 'INR'
    
    NSE = dhanhq.NSE if DHAN_AVAILABLE else 'NSE'
    BSE = dhanhq.BSE if DHAN_AVAILABLE else 'BSE'
    NSE_FNO = dhanhq.NSE_FNO if DHAN_AVAILABLE else 'NSE_FNO'
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "DHAN"
        self.dhan = None
        self.client_id = None
    
    @property
    def is_live(self) -> bool:
        """Dhan is always live trading"""
        return True
    
    async def connect(self) -> bool:
        """Connect to Dhan using client ID and access token"""
        try:
            if not DHAN_AVAILABLE:
                print(f"[{self.name}] dhanhq not installed")
                return False
            
            client_id = self.config.get('client_id')
            access_token = self.config.get('access_token')
            
            if not client_id or not access_token:
                print(f"[{self.name}] Client ID and access token required")
                return False
            
            print(f"[{self.name}] Connecting...")
            
            if DHAN_V2:
                context = DhanContext(client_id, access_token)
                self.dhan = dhanhq(context)
            else:
                self.dhan = dhanhq(client_id, access_token)
            
            self.client_id = client_id
            
            holdings = await asyncio.to_thread(self.dhan.get_holdings)
            
            if holdings is not None:
                print(f"[{self.name}] Connected! Client: {self.client_id}")
                self.connected = True
                return True
            else:
                print(f"[{self.name}] Connection test failed")
                return False
                
        except Exception as e:
            print(f"[{self.name}] Connection failed: {e}")
            self.connected = False
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from Dhan"""
        self.dhan = None
        self.connected = False
        print(f"[{self.name}] Disconnected")
        return True
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        if not self.dhan:
            return {}
        
        try:
            fund_limits = await asyncio.to_thread(self.dhan.get_fund_limits)
            return {
                'client_id': self.client_id,
                'currency': self.CURRENCY,
                'fund_limits': fund_limits
            }
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            return {}
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions"""
        if not self.dhan:
            return []
        
        try:
            positions = await asyncio.to_thread(self.dhan.get_positions)
            return positions if positions else []
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return []
    
    async def get_holdings(self) -> List[Dict[str, Any]]:
        """Get current holdings"""
        if not self.dhan:
            return []
        
        try:
            holdings = await asyncio.to_thread(self.dhan.get_holdings)
            return holdings if holdings else []
        except Exception as e:
            print(f"[{self.name}] Error getting holdings: {e}")
            return []
    
    async def place_order(self, security_id: str, action: str, quantity: int,
                          order_type: str = 'market', price: float = None,
                          exchange_segment: str = None, product_type: str = 'INTRA',
                          **kwargs) -> OrderResult:
        """Place an order on Dhan"""
        if not self.dhan:
            return OrderResult(success=False, message="Not connected")
        
        try:
            if exchange_segment is None:
                exchange_segment = self.dhan.NSE if DHAN_AVAILABLE else 'NSE'
            
            order_params = {
                'security_id': security_id,
                'exchange_segment': exchange_segment,
                'transaction_type': self.dhan.BUY if action.upper() == 'BTO' else self.dhan.SELL,
                'quantity': quantity,
                'order_type': self.dhan.MARKET if order_type == 'market' else self.dhan.LIMIT,
                'product_type': product_type,
                'price': price if price else 0
            }
            
            result = await asyncio.to_thread(
                self.dhan.place_order,
                **order_params
            )
            
            if result and result.get('status') == 'success':
                return OrderResult(
                    success=True,
                    order_id=str(result.get('data', {}).get('orderId', '')),
                    message=f"Order placed: {action} {quantity} {security_id}"
                )
            else:
                return OrderResult(
                    success=False,
                    message=result.get('remarks', 'Order failed') if result else 'No response'
                )
            
        except Exception as e:
            return OrderResult(success=False, message=str(e))
    
    async def get_orders(self) -> List[Dict[str, Any]]:
        """Get all orders for the day"""
        if not self.dhan:
            return []
        
        try:
            orders = await asyncio.to_thread(self.dhan.get_order_list)
            return orders if orders else []
        except Exception as e:
            print(f"[{self.name}] Error getting orders: {e}")
            return []

    @staticmethod
    def test_connection(client_id: str, access_token: str) -> Dict[str, Any]:
        """Test connection with provided credentials"""
        try:
            if not DHAN_AVAILABLE:
                return {
                    'success': False,
                    'message': 'Dhan library not installed. Run: pip install dhanhq'
                }
            
            if DHAN_V2:
                context = DhanContext(client_id, access_token)
                dhan = dhanhq(context)
            else:
                dhan = dhanhq(client_id, access_token)
            
            holdings = dhan.get_holdings()
            
            if holdings is not None:
                holdings_count = len(holdings) if isinstance(holdings, list) else 0
                
                try:
                    fund_limits = dhan.get_fund_limits()
                    available = fund_limits.get('data', {}).get('availabelBalance', 'N/A') if fund_limits else 'N/A'
                except:
                    available = 'N/A'
                
                return {
                    'success': True,
                    'message': f"Connected! Client: {client_id} | Holdings: {holdings_count} | Available: {available}",
                    'client_id': client_id,
                    'holdings_count': holdings_count
                }
            else:
                return {
                    'success': False,
                    'message': 'Connected but failed to fetch holdings. Check if token is valid.'
                }
                
        except Exception as e:
            error_msg = str(e)
            if 'unauthorized' in error_msg.lower() or '401' in error_msg:
                return {
                    'success': False,
                    'message': 'Access token expired or invalid. Tokens are valid for 24 hours only.'
                }
            return {
                'success': False,
                'message': f'Connection failed: {error_msg}'
            }


BrokerFactory.register_broker('DHAN', DhanBroker)
