"""
Questrade Broker Implementation (Canada)
OAuth 2.0 based trading platform for Canadian markets
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
    from qtrade import Questrade
    QUESTRADE_AVAILABLE = True
except ImportError:
    try:
        from qt_api.qt import Questrade as QtApiQuestrade
        Questrade = QtApiQuestrade
        QUESTRADE_AVAILABLE = True
    except ImportError:
        QUESTRADE_AVAILABLE = False
        print("[QUESTRADE] Warning: qtrade/qt-api package not installed. Install with: pip install qtrade")


class QuestradeBroker(BrokerInterface):
    """Questrade broker implementation for Canadian markets"""
    
    COUNTRY_CODE = 'CA'
    CURRENCY = 'CAD'
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "QUESTRADE"
        self.client = None
        self.account_id = None
        self.accounts = []
    
    @property
    def is_live(self) -> bool:
        """Questrade doesn't have a paper trading mode via API"""
        return True
    
    async def connect(self) -> bool:
        """Connect to Questrade using refresh token"""
        try:
            if not QUESTRADE_AVAILABLE:
                print(f"[{self.name}] qtrade package not installed")
                return False
            
            refresh_token = self.config.get('refresh_token')
            if not refresh_token:
                print(f"[{self.name}] No refresh token provided")
                return False
            
            print(f"[{self.name}] Connecting with refresh token...")
            
            self.client = await asyncio.to_thread(
                Questrade, 
                access_code=refresh_token
            )
            
            self.accounts = await asyncio.to_thread(self.client.get_accounts)
            if self.accounts:
                self.account_id = self.accounts[0].get('number')
                print(f"[{self.name}] Connected! Account: {self.account_id}")
                print(f"[{self.name}] Found {len(self.accounts)} account(s)")
                self.connected = True
                return True
            else:
                print(f"[{self.name}] No accounts found")
                return False
                
        except Exception as e:
            print(f"[{self.name}] Connection failed: {e}")
            self.connected = False
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from Questrade"""
        self.client = None
        self.connected = False
        print(f"[{self.name}] Disconnected")
        return True
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        if not self.client:
            return {}
        
        try:
            balances = await asyncio.to_thread(
                self.client.get_account_balances, 
                self.account_id
            )
            return {
                'account_id': self.account_id,
                'currency': self.CURRENCY,
                'balances': balances
            }
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            return {}
    
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions"""
        if not self.client:
            return []
        
        try:
            positions = await asyncio.to_thread(
                self.client.get_account_positions,
                self.account_id
            )
            return positions if positions else []
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return []
    
    async def place_order(self, symbol: str, action: str, quantity: int,
                          order_type: str = 'market', price: float = None,
                          **kwargs) -> OrderResult:
        """Place an order on Questrade"""
        if not self.client:
            return OrderResult(success=False, message="Not connected")
        
        try:
            order_params = {
                'accountId': self.account_id,
                'symbolId': await self._get_symbol_id(symbol),
                'quantity': quantity,
                'action': 'Buy' if action.upper() == 'BTO' else 'Sell',
                'orderType': 'Market' if order_type == 'market' else 'Limit',
                'timeInForce': 'Day'
            }
            
            if order_type == 'limit' and price:
                order_params['limitPrice'] = price
            
            result = await asyncio.to_thread(
                self.client.place_order,
                **order_params
            )
            
            return OrderResult(
                success=True,
                order_id=str(result.get('orderId', '')),
                message=f"Order placed: {action} {quantity} {symbol}"
            )
            
        except Exception as e:
            return OrderResult(success=False, message=str(e))
    
    async def _get_symbol_id(self, symbol: str) -> int:
        """Get Questrade symbol ID for a given ticker"""
        try:
            search_results = await asyncio.to_thread(
                self.client.symbols_search,
                prefix=symbol
            )
            if search_results:
                return search_results[0].get('symbolId')
            return 0
        except Exception as e:
            print(f"[{self.name}] Error searching symbol {symbol}: {e}")
            return 0
    
    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get current quote for a symbol"""
        if not self.client:
            return {}
        
        try:
            symbol_id = await self._get_symbol_id(symbol)
            if symbol_id:
                quotes = await asyncio.to_thread(
                    self.client.get_quote,
                    [symbol_id]
                )
                return quotes[0] if quotes else {}
            return {}
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
            return {}

    @staticmethod
    def test_connection(refresh_token: str) -> Dict[str, Any]:
        """Test connection with provided credentials"""
        try:
            if not QUESTRADE_AVAILABLE:
                return {
                    'success': False,
                    'message': 'Questrade library not installed. Run: pip install qtrade'
                }
            
            client = Questrade(access_code=refresh_token)
            accounts = client.get_accounts()
            
            if accounts:
                account_info = []
                for acc in accounts:
                    account_info.append(f"{acc.get('type', 'Unknown')} ({acc.get('number', 'N/A')})")
                
                return {
                    'success': True,
                    'message': f"Connected! Found {len(accounts)} account(s): {', '.join(account_info)}",
                    'accounts': accounts
                }
            else:
                return {
                    'success': False,
                    'message': 'Connected but no accounts found'
                }
                
        except Exception as e:
            error_msg = str(e)
            if 'invalid_grant' in error_msg.lower():
                return {
                    'success': False,
                    'message': 'Refresh token expired or invalid. Generate a new one from Questrade API Hub.'
                }
            return {
                'success': False,
                'message': f'Connection failed: {error_msg}'
            }


BrokerFactory.register_broker('QUESTRADE', QuestradeBroker)
