"""
Interactive Brokers (IBKR) Implementation
Professional-grade multi-asset trading
"""

import sys
import os
import asyncio
from typing import Optional, Dict, Any
from ib_insync import IB, Stock, Option, MarketOrder, LimitOrder, util
from datetime import datetime

# Add parent directory to path for absolute imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory


class IBKRBroker(BrokerInterface):
    """Interactive Brokers implementation using ib_insync"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "IBKR"
        self.ib = IB()
        self.paper_trade = config.get('paper_trade', True)
        self.host = config.get('host', '127.0.0.1')
        # Paper trading: 7497, Live trading: 7496
        self.port = config.get('port', 7497 if self.paper_trade else 7496)
        self.client_id = config.get('client_id', 1)
    
    async def connect(self) -> bool:
        """Connect to Interactive Brokers TWS/Gateway"""
        try:
            # Connect to TWS or IB Gateway
            await self.ib.connectAsync(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                timeout=20
            )
            
            if self.ib.isConnected():
                self.connected = True
                mode = "PAPER" if self.paper_trade else "LIVE"
                print(f"[{self.name}] ✓ Connected successfully ({mode} trading)")
                
                # Get account summary
                account_summary = self.ib.accountSummary()
                for item in account_summary:
                    if item.tag == 'BuyingPower':
                        print(f"[{self.name}]   Buying power: ${float(item.value):,.2f}")
                        break
                
                return True
            
            print(f"[{self.name}] ❌ Failed to connect to TWS/Gateway")
            return False
            
        except Exception as e:
            print(f"[{self.name}] ❌ Connection error: {e}")
            print(f"[{self.name}] Make sure TWS or IB Gateway is running on {self.host}:{self.port}")
            return False
    
    async def disconnect(self):
        """Disconnect from Interactive Brokers"""
        if self.ib.isConnected():
            self.ib.disconnect()
        self.connected = False
        print(f"[{self.name}] Disconnected")
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        try:
            account_summary = self.ib.accountSummary()
            result = {'buying_power': 0, 'cash': 0, 'portfolio_value': 0}
            
            for item in account_summary:
                if item.tag == 'BuyingPower':
                    result['buying_power'] = float(item.value)
                elif item.tag == 'TotalCashValue':
                    result['cash'] = float(item.value)
                elif item.tag == 'NetLiquidation':
                    result['portfolio_value'] = float(item.value)
            
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            return {'buying_power': 0, 'cash': 0, 'portfolio_value': 0}
    
    async def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        try:
            positions = self.ib.positions()
            result = {}
            for pos in positions:
                if hasattr(pos.contract, 'symbol'):
                    symbol = pos.contract.symbol
                    quantity = int(pos.position)
                    result[symbol] = quantity
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return {}
    
    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None
    ) -> OrderResult:
        """Place a stock order"""
        try:
            # Create contract
            contract = Stock(symbol, 'SMART', 'USD')
            
            # Qualify contract (get full details from IB)
            self.ib.qualifyContracts(contract)
            
            # Create order
            side = 'BUY' if action == 'BTO' else 'SELL'
            
            if price is None:
                # Market order
                order = MarketOrder(side, quantity)
            else:
                # Limit order
                order = LimitOrder(side, quantity, price)
            
            # Place order
            trade = self.ib.placeOrder(contract, order)
            
            # Wait for order to be acknowledged
            await asyncio.sleep(1)
            
            if trade and trade.orderStatus.status != 'Cancelled':
                return OrderResult(
                    success=True,
                    order_id=str(trade.order.orderId),
                    message=f"Stock order placed: {action} {quantity} {symbol}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                status = trade.orderStatus.status if trade else 'Unknown'
                return OrderResult(
                    success=False,
                    message=f"Order failed with status: {status}",
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            error_msg = str(e)
            
            # Handle insufficient funds
            if 'insufficient' in error_msg.lower():
                try:
                    account_info = await self.get_account_info()
                    buying_power = account_info['buying_power']
                    
                    # Get current price
                    current_price = await self.get_quote(symbol)
                    
                    if current_price and buying_power > 0:
                        # Calculate max quantity
                        max_qty = int(buying_power / current_price)
                        
                        if max_qty > 0:
                            print(f"[{self.name}] Auto-adjusting: {quantity} → {max_qty} shares")
                            return await self.place_stock_order(symbol, action, max_qty, price)
                except Exception as adjust_error:
                    print(f"[{self.name}] Auto-adjust failed: {adjust_error}")
            
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
            # Parse expiry date to YYYYMMDD format
            if '/' in expiry or '-' in expiry:
                from datetime import datetime
                sep = '/' if '/' in expiry else '-'
                parts = expiry.split(sep)
                if len(parts) == 3:
                    year, month, day = parts
                    expiry_formatted = f"{year}{month.zfill(2)}{day.zfill(2)}"
                else:
                    raise ValueError(f"Invalid expiry format: {expiry}")
            else:
                expiry_formatted = expiry
            
            # Create option contract
            right = 'C' if option_type.lower() in ['c', 'call'] else 'P'
            contract = Option(symbol, expiry_formatted, strike, right, 'SMART')
            
            # Qualify contract
            self.ib.qualifyContracts(contract)
            
            # Create order
            side = 'BUY' if action == 'BTO' else 'SELL'
            
            if price is None:
                # Market order
                order = MarketOrder(side, quantity)
            else:
                # Limit order
                order = LimitOrder(side, quantity, price)
            
            # Place order
            trade = self.ib.placeOrder(contract, order)
            
            # Wait for acknowledgment
            await asyncio.sleep(1)
            
            if trade and trade.orderStatus.status != 'Cancelled':
                return OrderResult(
                    success=True,
                    order_id=str(trade.order.orderId),
                    message=f"Option order placed: {action} {quantity} {symbol} ${strike}{option_type} {expiry}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                status = trade.orderStatus.status if trade else 'Unknown'
                return OrderResult(
                    success=False,
                    message=f"Order failed with status: {status}",
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            return OrderResult(
                success=False,
                message=f"Exception: {str(e)}",
                symbol=symbol,
                action=action
            )
    
    async def get_quote(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol"""
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            self.ib.qualifyContracts(contract)
            
            # Request market data
            ticker = self.ib.reqMktData(contract, '', False, False)
            await asyncio.sleep(2)  # Wait for data
            
            # Get last price or close price
            if ticker.last and ticker.last > 0:
                price = float(ticker.last)
            elif ticker.close and ticker.close > 0:
                price = float(ticker.close)
            else:
                price = None
            
            # Cancel market data
            self.ib.cancelMktData(contract)
            
            return price
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
            return None


# Register this broker with the factory
BrokerFactory.register_broker('IBKR', IBKRBroker)
