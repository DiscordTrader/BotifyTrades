"""
Broker Interface and Implementations
Multi-broker support for Discord Trading Bot
Supports: Webull, Alpaca, Interactive Brokers (IBKR)
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass


@dataclass
class OrderResult:
    """Standardized order result across all brokers"""
    success: bool
    order_id: Optional[str] = None
    message: str = ""
    price: Optional[float] = None
    quantity: Optional[int] = None
    symbol: str = ""
    action: str = ""


class BrokerInterface(ABC):
    """
    Abstract base class for all broker implementations
    All brokers must implement these methods
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize broker with configuration"""
        self.config = config
        self.name = "Unknown"
        self.connected = False
    
    @abstractmethod
    async def connect(self) -> bool:
        """
        Connect/login to the broker
        Returns: True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def disconnect(self):
        """Disconnect from broker"""
        pass
    
    @abstractmethod
    async def get_account_info(self) -> Dict[str, Any]:
        """
        Get account information
        Returns: Dict with keys: buying_power, cash, portfolio_value
        """
        pass
    
    @abstractmethod
    async def get_positions(self) -> Dict[str, Any]:
        """
        Get current positions
        Returns: Dict mapping symbol -> quantity
        """
        pass
    
    @abstractmethod
    async def place_stock_order(
        self,
        symbol: str,
        action: str,  # BTO or STC
        quantity: int,
        price: Optional[float] = None
    ) -> OrderResult:
        """
        Place a stock order
        
        Args:
            symbol: Stock ticker (e.g., "AAPL")
            action: BTO (buy) or STC (sell)
            quantity: Number of shares
            price: Limit price (None for market order)
        
        Returns:
            OrderResult with success status and details
        """
        pass
    
    @abstractmethod
    async def place_option_order(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str,  # call or put
        action: str,  # BTO or STC
        quantity: int,
        price: Optional[float] = None
    ) -> OrderResult:
        """
        Place an options order
        
        Args:
            symbol: Underlying ticker (e.g., "AAPL")
            strike: Strike price
            expiry: Expiration date (YYYY-MM-DD)
            option_type: "call" or "put"
            action: BTO (buy) or STC (sell)
            quantity: Number of contracts
            price: Limit price (None for market order)
        
        Returns:
            OrderResult with success status and details
        """
        pass
    
    @abstractmethod
    async def get_quote(self, symbol: str) -> Optional[float]:
        """
        Get current price for a symbol
        
        Args:
            symbol: Stock ticker
        
        Returns:
            Current price or None if not available
        """
        pass
    
    def is_connected(self) -> bool:
        """Check if broker is connected"""
        return self.connected
    
    def get_name(self) -> str:
        """Get broker name"""
        return self.name


class BrokerFactory:
    """Factory class to create broker instances"""
    
    _brokers = {}
    
    @classmethod
    def register_broker(cls, name: str, broker_class):
        """Register a broker implementation"""
        cls._brokers[name.upper()] = broker_class
    
    @classmethod
    def create_broker(cls, name: str, config: Dict[str, Any]) -> Optional[BrokerInterface]:
        """
        Create a broker instance
        
        Args:
            name: Broker name (WEBULL, ALPACA, IBKR)
            config: Broker-specific configuration
        
        Returns:
            Broker instance or None if not found
        """
        broker_class = cls._brokers.get(name.upper())
        if broker_class:
            return broker_class(config)
        return None
    
    @classmethod
    def get_available_brokers(cls) -> list:
        """Get list of available broker names"""
        return list(cls._brokers.keys())
