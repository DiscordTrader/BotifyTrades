"""
Mock Broker implementations for testing
Simulates broker behavior without actual API calls
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import asyncio


@dataclass
class MockOrderResult:
    """Mock order execution result"""
    success: bool
    order_id: str = None
    message: str = ""
    filled_price: float = 0.0
    filled_quantity: int = 0
    status: str = "PENDING"
    broker: str = ""


@dataclass
class MockPosition:
    """Mock broker position"""
    symbol: str
    quantity: float
    avg_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    asset_type: str = "option"
    strike: float = None
    expiry: str = None
    opt_type: str = None


class MockBroker:
    """Base mock broker class"""
    
    def __init__(self, name: str = "MOCK", paper_trade: bool = True):
        self.name = name
        self.paper_trade = paper_trade
        self.connected = False
        self.positions: Dict[str, MockPosition] = {}
        self.orders: List[Dict[str, Any]] = []
        self.order_counter = 0
        self.balance = 100000.0
        self.buying_power = 100000.0
        
        self._should_fail_next_order = False
        self._fail_reason = ""
        self._execution_delay = 0.0
        self._connection_delay = 0.0
    
    async def connect(self) -> bool:
        """Simulate broker connection"""
        if self._connection_delay > 0:
            await asyncio.sleep(self._connection_delay)
        self.connected = True
        return True
    
    async def disconnect(self):
        """Simulate broker disconnection"""
        self.connected = False
    
    def set_connection_delay(self, seconds: float):
        """Set artificial connection delay for testing timing issues"""
        self._connection_delay = seconds
    
    def set_next_order_fail(self, reason: str = "Mock failure"):
        """Make the next order fail for testing error handling"""
        self._should_fail_next_order = True
        self._fail_reason = reason
    
    async def place_option_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        strike: float,
        expiry: str,
        opt_type: str,
        price: float = None,
        order_type: str = "LIMIT"
    ) -> MockOrderResult:
        """Simulate placing an option order"""
        if self._execution_delay > 0:
            await asyncio.sleep(self._execution_delay)
        
        if self._should_fail_next_order:
            self._should_fail_next_order = False
            return MockOrderResult(
                success=False,
                message=self._fail_reason,
                broker=self.name
            )
        
        if not self.connected:
            return MockOrderResult(
                success=False,
                message="Broker not connected",
                broker=self.name
            )
        
        self.order_counter += 1
        order_id = f"{self.name}-{self.order_counter:06d}"
        
        order = {
            'order_id': order_id,
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'strike': strike,
            'expiry': expiry,
            'opt_type': opt_type,
            'price': price,
            'status': 'FILLED',
            'filled_price': price,
            'created_at': datetime.now().isoformat()
        }
        self.orders.append(order)
        
        position_key = f"{symbol}_{strike}_{expiry}_{opt_type}"
        if action == 'BTO':
            self.positions[position_key] = MockPosition(
                symbol=symbol,
                quantity=quantity,
                avg_price=price,
                current_price=price,
                strike=strike,
                expiry=expiry,
                opt_type=opt_type
            )
        elif action == 'STC' and position_key in self.positions:
            del self.positions[position_key]
        
        return MockOrderResult(
            success=True,
            order_id=order_id,
            message="Order filled",
            filled_price=price,
            filled_quantity=quantity,
            status="FILLED",
            broker=self.name
        )
    
    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: float = None
    ) -> MockOrderResult:
        """Simulate placing a stock order"""
        if self._should_fail_next_order:
            self._should_fail_next_order = False
            return MockOrderResult(
                success=False,
                message=self._fail_reason,
                broker=self.name
            )
        
        self.order_counter += 1
        order_id = f"{self.name}-STK-{self.order_counter:06d}"
        
        return MockOrderResult(
            success=True,
            order_id=order_id,
            filled_price=price,
            filled_quantity=quantity,
            status="FILLED",
            broker=self.name
        )
    
    def get_positions(self) -> List[MockPosition]:
        """Get all open positions"""
        return list(self.positions.values())
    
    def get_account_balance(self) -> Dict[str, float]:
        """Get account balance info"""
        return {
            'balance': self.balance,
            'buying_power': self.buying_power,
            'cash': self.balance
        }
    
    def reset(self):
        """Reset mock state for new test"""
        self.positions.clear()
        self.orders.clear()
        self.order_counter = 0
        self._should_fail_next_order = False
        self._fail_reason = ""


class MockAlpacaBroker(MockBroker):
    """Mock Alpaca broker with Alpaca-specific behavior"""
    
    def __init__(self, name: str = "ALPACA_PAPER", paper_trade: bool = True):
        super().__init__(name=name, paper_trade=paper_trade)
        self.connected = True


class MockWebullBroker(MockBroker):
    """Mock Webull broker with Webull-specific behavior"""
    
    def __init__(self, name: str = "WEBULL", paper_trade: bool = False):
        super().__init__(name=name, paper_trade=paper_trade)
        self._requires_2fa = False
        self._device_id = "mock-device-123"
    
    async def connect(self) -> bool:
        """Webull connection with optional delay to simulate async login"""
        if self._connection_delay > 0:
            await asyncio.sleep(self._connection_delay)
        self.connected = True
        return True


class MockIBKRBroker(MockBroker):
    """Mock Interactive Brokers"""
    
    def __init__(self, name: str = "IBKR", paper_trade: bool = True):
        super().__init__(name=name, paper_trade=paper_trade)


class MockTastytradeBroker(MockBroker):
    """Mock Tastytrade broker"""
    
    def __init__(self, name: str = "TASTYTRADE", paper_trade: bool = False):
        super().__init__(name=name, paper_trade=paper_trade)
        self.is_live = not paper_trade


class MockRobinhoodBroker(MockBroker):
    """Mock Robinhood broker (live only)"""
    
    def __init__(self, name: str = "ROBINHOOD"):
        super().__init__(name=name, paper_trade=False)
