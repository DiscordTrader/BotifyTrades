"""
Mock Market Data provider for testing
Simulates real-time market data without actual API calls
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, time
import random


@dataclass
class MockQuote:
    """Mock market quote"""
    symbol: str
    bid: float
    ask: float
    last: float
    volume: int = 0
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass
class MockOptionQuote(MockQuote):
    """Mock option quote with Greeks"""
    strike: float = 0.0
    expiry: str = ""
    opt_type: str = "C"
    delta: float = 0.5
    gamma: float = 0.05
    theta: float = -0.02
    vega: float = 0.1
    iv: float = 0.3
    open_interest: int = 1000


class MockMarketData:
    """Mock market data provider"""
    
    def __init__(self):
        self._quotes: Dict[str, MockQuote] = {}
        self._option_chains: Dict[str, List[MockOptionQuote]] = {}
        self._market_open = True
        self._current_time = datetime.now()
        
        self._setup_default_quotes()
    
    def _setup_default_quotes(self):
        """Setup common stock quotes"""
        defaults = {
            'SPY': 450.0,
            'QQQ': 380.0,
            'AAPL': 185.0,
            'TSLA': 245.0,
            'NVDA': 480.0,
            'META': 350.0,
            'GOOGL': 140.0,
            'AMZN': 155.0,
            'MSFT': 375.0,
            'AMD': 120.0,
        }
        
        for symbol, price in defaults.items():
            spread = price * 0.001
            self._quotes[symbol] = MockQuote(
                symbol=symbol,
                bid=price - spread,
                ask=price + spread,
                last=price,
                volume=random.randint(100000, 10000000)
            )
    
    def set_quote(self, symbol: str, price: float, spread: float = 0.01):
        """Set a custom quote for a symbol"""
        self._quotes[symbol] = MockQuote(
            symbol=symbol,
            bid=price - spread,
            ask=price + spread,
            last=price
        )
    
    def get_quote(self, symbol: str) -> Optional[MockQuote]:
        """Get quote for a symbol"""
        return self._quotes.get(symbol.upper())
    
    def get_option_quote(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        opt_type: str
    ) -> MockOptionQuote:
        """Get option quote"""
        underlying = self.get_quote(symbol)
        if not underlying:
            underlying_price = 100.0
        else:
            underlying_price = underlying.last
        
        moneyness = (underlying_price - strike) / underlying_price
        if opt_type.upper() == 'P':
            moneyness = -moneyness
        
        if moneyness > 0.05:
            base_price = abs(underlying_price - strike) + random.uniform(0.1, 0.5)
            delta = 0.7 + moneyness * 0.3 if opt_type.upper() == 'C' else -(0.7 + moneyness * 0.3)
        elif moneyness < -0.05:
            base_price = random.uniform(0.05, 0.50)
            delta = 0.3 - abs(moneyness) * 0.2 if opt_type.upper() == 'C' else -(0.3 - abs(moneyness) * 0.2)
        else:
            base_price = random.uniform(0.50, 2.00)
            delta = 0.5 if opt_type.upper() == 'C' else -0.5
        
        spread = base_price * 0.05
        
        return MockOptionQuote(
            symbol=symbol,
            strike=strike,
            expiry=expiry,
            opt_type=opt_type,
            bid=max(0.01, base_price - spread),
            ask=base_price + spread,
            last=base_price,
            delta=delta,
            gamma=random.uniform(0.01, 0.10),
            theta=random.uniform(-0.05, -0.01),
            vega=random.uniform(0.05, 0.20),
            iv=random.uniform(0.20, 0.60)
        )
    
    def move_price(self, symbol: str, percent_change: float):
        """Move a symbol's price by a percentage"""
        quote = self._quotes.get(symbol.upper())
        if quote:
            new_price = quote.last * (1 + percent_change / 100)
            spread = new_price * 0.001
            self._quotes[symbol.upper()] = MockQuote(
                symbol=symbol.upper(),
                bid=new_price - spread,
                ask=new_price + spread,
                last=new_price,
                volume=quote.volume
            )
    
    def set_market_hours(self, is_open: bool):
        """Set market open/closed state"""
        self._market_open = is_open
    
    def is_market_open(self) -> bool:
        """Check if market is open"""
        return self._market_open
    
    def get_current_time(self) -> datetime:
        """Get simulated current time"""
        return self._current_time
    
    def set_time(self, dt: datetime):
        """Set simulated time"""
        self._current_time = dt
    
    def reset(self):
        """Reset to default state"""
        self._quotes.clear()
        self._option_chains.clear()
        self._market_open = True
        self._setup_default_quotes()
