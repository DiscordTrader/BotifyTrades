"""
Tastytrade Broker Implementation
Options-focused trading platform with official API
"""

import sys
import os
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory

try:
    from tastytrade import Session, Account
    from tastytrade.instruments import Equity, Option, get_option_chain
    from tastytrade.order import NewOrder, OrderAction, OrderTimeInForce, OrderType
    TASTYTRADE_AVAILABLE = True
except ImportError as e:
    print(f"[TASTYTRADE] Warning: tastytrade package not available: {e}")
    TASTYTRADE_AVAILABLE = False


class TastytradeBroker(BrokerInterface):
    """Tastytrade broker implementation using official tastytrade SDK"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "TASTYTRADE"
        self.session = None
        self.account = None
        self.paper_trade = config.get('paper_trade', True)
    
    @property
    def is_live(self) -> bool:
        """Returns True if broker is in live trading mode (not paper/sandbox)"""
        return not self.paper_trade
    
    async def connect(self) -> bool:
        """Connect to Tastytrade using username/password or OAuth"""
        try:
            if not TASTYTRADE_AVAILABLE:
                print(f"[{self.name}] ❌ tastytrade package not installed")
                return False
            
            username = self.config.get('username')
            password = self.config.get('password')
            
            if not username or not password:
                print(f"[{self.name}] ❌ Missing credentials (username/password)")
                return False
            
            mode = "SANDBOX" if self.paper_trade else "LIVE"
            print(f"[{self.name}] Connecting to {mode} account...")
            
            self.session = await asyncio.to_thread(
                Session,
                username,
                password,
                is_test=self.paper_trade
            )
            
            accounts = await asyncio.to_thread(Account.get, self.session)
            
            if not accounts:
                print(f"[{self.name}] ❌ No accounts found")
                return False
            
            self.account = accounts[0]
            self.connected = True
            
            balances = await asyncio.to_thread(self.account.get_balances, self.session)
            
            print(f"[{self.name}] ✓ Connected successfully ({mode} trading)")
            print(f"[{self.name}]   Account #: {self.account.account_number}")
            if hasattr(balances, 'net_liquidating_value'):
                print(f"[{self.name}]   Net Liquidating Value: ${float(balances.net_liquidating_value):,.2f}")
            if hasattr(balances, 'cash_balance'):
                print(f"[{self.name}]   Cash Balance: ${float(balances.cash_balance):,.2f}")
            
            return True
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            print(f"[{self.name}] ❌ Connection error: {error_msg}")
            
            if 'invalid' in error_msg.lower() or '401' in error_msg or 'unauthorized' in error_msg.lower():
                print(f"[{self.name}] ⚠️  AUTHENTICATION FAILED - Check that:")
                print(f"[{self.name}]    1. Username and password are correct")
                print(f"[{self.name}]    2. Account has API access enabled")
                print(f"[{self.name}]    3. For sandbox, use sandbox credentials")
            
            traceback.print_exc()
            return False
    
    async def disconnect(self):
        """Disconnect from Tastytrade"""
        self.connected = False
        self.session = None
        self.account = None
        print(f"[{self.name}] Disconnected")
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        try:
            if not self.account or not self.session:
                return {'buying_power': 0, 'options_buying_power': 0, 'cash': 0, 'portfolio_value': 0}
            
            balances = await asyncio.to_thread(self.account.get_balances, self.session)
            
            nlv = float(getattr(balances, 'net_liquidating_value', 0) or 0)
            cash = float(getattr(balances, 'cash_balance', 0) or 0)
            derivative_bp = float(getattr(balances, 'derivative_buying_power', 0) or 0)
            equity_bp = float(getattr(balances, 'equity_buying_power', 0) or 0)
            
            return {
                'buying_power': equity_bp,
                'options_buying_power': derivative_bp,
                'cash': cash,
                'portfolio_value': nlv
            }
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            return {'buying_power': 0, 'options_buying_power': 0, 'cash': 0, 'portfolio_value': 0}
    
    async def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        try:
            if not self.account or not self.session:
                return {}
            
            positions = await asyncio.to_thread(self.account.get_positions, self.session)
            result = {}
            for pos in positions:
                symbol = getattr(pos, 'symbol', None)
                qty = getattr(pos, 'quantity', 0)
                if symbol:
                    result[symbol] = int(float(qty))
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return {}
    
    def get_all_positions(self) -> list:
        """Get all positions as raw objects for sync service (synchronous)"""
        try:
            if not self.account or not self.session:
                print(f"[{self.name}] Not connected")
                return []
            positions = self.account.get_positions(self.session)
            print(f"[{self.name}] get_all_positions returned {len(positions)} positions")
            return positions
        except Exception as e:
            print(f"[{self.name}] Error getting all positions: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_orders(self, status: str = 'open') -> list:
        """Get orders by status for sync service (synchronous)"""
        try:
            if not self.account or not self.session:
                print(f"[{self.name}] Not connected")
                return []
            
            orders = self.account.get_live_orders(self.session)
            return orders
        except Exception as e:
            print(f"[{self.name}] Error getting orders: {e}")
            return []
    
    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        stop_price: Optional[float] = None
    ) -> OrderResult:
        """Place a stock order"""
        try:
            if not self.account or not self.session:
                return OrderResult(
                    success=False,
                    message="Not connected to Tastytrade",
                    symbol=symbol,
                    action=action
                )
            
            equity = await asyncio.to_thread(Equity.get, self.session, symbol)
            
            if action.upper() == 'BTO':
                order_action = OrderAction.BUY_TO_OPEN
            elif action.upper() == 'STC':
                order_action = OrderAction.SELL_TO_CLOSE
            elif action.upper() == 'STO':
                order_action = OrderAction.SELL_TO_OPEN
            elif action.upper() == 'BTC':
                order_action = OrderAction.BUY_TO_CLOSE
            else:
                order_action = OrderAction.BUY_TO_OPEN if 'B' in action.upper() else OrderAction.SELL_TO_CLOSE
            
            leg = equity.build_leg(Decimal(str(quantity)), order_action)
            
            if price is not None and price > 0:
                price_decimal = Decimal(str(-price)) if 'B' in action.upper() else Decimal(str(price))
                order = NewOrder(
                    time_in_force=OrderTimeInForce.DAY,
                    order_type=OrderType.LIMIT,
                    legs=[leg],
                    price=price_decimal
                )
            else:
                order = NewOrder(
                    time_in_force=OrderTimeInForce.DAY,
                    order_type=OrderType.MARKET,
                    legs=[leg]
                )
            
            print(f"[{self.name}] Placing stock order: {action} {quantity} {symbol} @ ${price or 'MARKET'}")
            
            response = await asyncio.to_thread(
                self.account.place_order,
                self.session,
                order,
                dry_run=False
            )
            
            if response and hasattr(response, 'order') and response.order:
                return OrderResult(
                    success=True,
                    order_id=str(response.order.id),
                    message=f"Stock order placed: {action} {quantity} {symbol}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                return OrderResult(
                    success=True,
                    order_id="submitted",
                    message=f"Stock order submitted: {action} {quantity} {symbol}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            error_msg = str(e)
            print(f"[{self.name}] ❌ Stock order failed: {error_msg}")
            import traceback
            traceback.print_exc()
            return OrderResult(
                success=False,
                message=f"Exception: {error_msg}",
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
            if not self.account or not self.session:
                return OrderResult(
                    success=False,
                    message="Not connected to Tastytrade",
                    symbol=symbol,
                    action=action
                )
            
            if "/" in expiry:
                parts = expiry.split("/")
                if len(parts) == 2:
                    m, d = parts
                    y = datetime.now().year
                    expiry_date = datetime(y, int(m), int(d)).date()
                elif len(parts) == 3:
                    m, d, y = parts
                    if len(y) == 2:
                        y = f"20{y}"
                    expiry_date = datetime(int(y), int(m), int(d)).date()
                else:
                    expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            else:
                expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            
            print(f"[{self.name}] Looking up option chain for {symbol} expiry {expiry_date}")
            
            try:
                chain = await asyncio.to_thread(get_option_chain, self.session, symbol)
                
                if expiry_date not in chain:
                    available_expiries = list(chain.keys())[:5]
                    return OrderResult(
                        success=False,
                        message=f"Expiry {expiry_date} not found. Available: {available_expiries}",
                        symbol=symbol,
                        action=action
                    )
                
                options = chain[expiry_date]
                opt_type = 'C' if option_type.upper().startswith('C') else 'P'
                
                target_option = None
                for opt in options:
                    if abs(float(opt.strike_price) - strike) < 0.01:
                        if (opt_type == 'C' and opt.option_type.value == 'C') or \
                           (opt_type == 'P' and opt.option_type.value == 'P'):
                            target_option = opt
                            break
                
                if not target_option:
                    return OrderResult(
                        success=False,
                        message=f"Could not find {symbol} ${strike}{opt_type} {expiry_date}",
                        symbol=symbol,
                        action=action
                    )
                
            except Exception as chain_err:
                print(f"[{self.name}] Option chain lookup failed: {chain_err}")
                return OrderResult(
                    success=False,
                    message=f"Could not find option contract: {chain_err}",
                    symbol=symbol,
                    action=action
                )
            
            if action.upper() == 'BTO':
                order_action = OrderAction.BUY_TO_OPEN
            elif action.upper() == 'STC':
                order_action = OrderAction.SELL_TO_CLOSE
            elif action.upper() == 'STO':
                order_action = OrderAction.SELL_TO_OPEN
            elif action.upper() == 'BTC':
                order_action = OrderAction.BUY_TO_CLOSE
            else:
                order_action = OrderAction.BUY_TO_OPEN if 'B' in action.upper() else OrderAction.SELL_TO_CLOSE
            
            leg = target_option.build_leg(Decimal(str(quantity)), order_action)
            
            if price is not None and price > 0:
                price_decimal = Decimal(str(-price)) if 'B' in action.upper() else Decimal(str(price))
                order = NewOrder(
                    time_in_force=OrderTimeInForce.DAY,
                    order_type=OrderType.LIMIT,
                    legs=[leg],
                    price=price_decimal
                )
            else:
                order = NewOrder(
                    time_in_force=OrderTimeInForce.DAY,
                    order_type=OrderType.MARKET,
                    legs=[leg]
                )
            
            print(f"[{self.name}] Placing option order: {action} {quantity} {target_option.symbol} @ ${price or 'MARKET'}")
            
            response = await asyncio.to_thread(
                self.account.place_order,
                self.session,
                order,
                dry_run=False
            )
            
            if response and hasattr(response, 'order') and response.order:
                return OrderResult(
                    success=True,
                    order_id=str(response.order.id),
                    message=f"Option order placed: {action} {quantity} {symbol} ${strike}{opt_type} {expiry}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                return OrderResult(
                    success=True,
                    order_id="submitted",
                    message=f"Option order submitted: {action} {quantity} {symbol} ${strike}{opt_type} {expiry}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            error_msg = str(e)
            print(f"[{self.name}] ❌ Option order failed: {error_msg}")
            import traceback
            traceback.print_exc()
            return OrderResult(
                success=False,
                message=f"Exception: {error_msg}",
                symbol=symbol,
                action=action
            )
    
    async def get_quote(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol"""
        try:
            if not self.session:
                return None
            
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
            return None


BrokerFactory.register_broker('TASTYTRADE', TastytradeBroker)
BrokerFactory.register_broker('TASTYTRADE_LIVE', TastytradeBroker)
BrokerFactory.register_broker('TASTYTRADE_PAPER', TastytradeBroker)
