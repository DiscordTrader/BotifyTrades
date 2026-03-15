"""
Broker implementations package
Imports all broker implementations and registers them with the factory
"""

import sys
import os

# Add parent directory to path to allow absolute imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import base interface and factory (using absolute import)
from broker_interface import BrokerInterface, BrokerFactory, OrderResult

# Import all broker implementations
from .webull_broker import WebullBroker
from .alpaca_broker import AlpacaBroker
from .ibkr_broker import IBKRBroker
from .robinhood_broker import RobinhoodBroker
from .schwab_broker import SchwabBroker
from .trading212_broker import Trading212Broker

# Register broker implementations with factory
BrokerFactory.register_broker('WEBULL', WebullBroker)
BrokerFactory.register_broker('ALPACA', AlpacaBroker)
BrokerFactory.register_broker('IBKR', IBKRBroker)
BrokerFactory.register_broker('ROBINHOOD', RobinhoodBroker)
BrokerFactory.register_broker('SCHWAB', SchwabBroker)
BrokerFactory.register_broker('TRADING212', Trading212Broker)

__all__ = [
    'BrokerInterface',
    'BrokerFactory',
    'OrderResult',
    'WebullBroker',
    'AlpacaBroker',
    'IBKRBroker',
    'RobinhoodBroker',
    'SchwabBroker',
    'Trading212Broker'
]
