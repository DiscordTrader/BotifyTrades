"""
Imports module - Conditional imports and availability flags
Handles optional dependencies gracefully
"""

from typing import Optional, Any

AI_IMPORTS_AVAILABLE = False
ALPHA_VANTAGE_AVAILABLE = False
SWING_ANALYZER_AVAILABLE = False
NEWS_SERVICE_AVAILABLE = False
DATABASE_MODULE_AVAILABLE = False
BROKER_MANAGER_AVAILABLE = False
ALPACA_AVAILABLE = False

TradeAnalyzer: Optional[Any] = None
SentimentAnalyzer: Optional[Any] = None
TradeTracker: Optional[Any] = None
AlphaVantageScanner: Optional[Any] = None
SwingTradeAnalyzer: Optional[Any] = None
FundamentalAnalyzer: Optional[Any] = None
NewsService: Optional[Any] = None
BrokerManager: Optional[Any] = None
AlpacaBroker: Optional[Any] = None
db: Optional[Any] = None


def load_optional_imports() -> dict:
    """
    Load all optional imports and set availability flags.
    
    Returns:
        Dictionary of import status and loaded modules
    """
    global AI_IMPORTS_AVAILABLE, ALPHA_VANTAGE_AVAILABLE, SWING_ANALYZER_AVAILABLE
    global NEWS_SERVICE_AVAILABLE, DATABASE_MODULE_AVAILABLE, BROKER_MANAGER_AVAILABLE
    global ALPACA_AVAILABLE
    global TradeAnalyzer, SentimentAnalyzer, TradeTracker, AlphaVantageScanner
    global SwingTradeAnalyzer, FundamentalAnalyzer, NewsService, BrokerManager
    global AlpacaBroker, db
    
    try:
        from ai_analyzer import TradeAnalyzer as TA, SentimentAnalyzer as SA
        from trade_tracker import TradeTracker as TT
        TradeAnalyzer = TA
        SentimentAnalyzer = SA
        TradeTracker = TT
        AI_IMPORTS_AVAILABLE = True
    except ImportError:
        print("[STARTUP] AI analyzer not available (openai package not installed)")
    
    try:
        from alpha_vantage_scanner import AlphaVantageScanner as AVS
        AlphaVantageScanner = AVS
        ALPHA_VANTAGE_AVAILABLE = True
    except ImportError:
        print("[STARTUP] Alpha Vantage scanner not available")
    
    try:
        from swing_analyzer import SwingTradeAnalyzer as STA
        from fundamental_analyzer import FundamentalAnalyzer as FA
        SwingTradeAnalyzer = STA
        FundamentalAnalyzer = FA
        SWING_ANALYZER_AVAILABLE = True
    except ImportError:
        print("[STARTUP] Swing trading analyzer not available")
    
    try:
        from news_service import NewsService as NS
        NewsService = NS
        NEWS_SERVICE_AVAILABLE = True
    except ImportError:
        print("[STARTUP] News service not available")
    
    try:
        from gui_app import database as db_module
        db = db_module
        DATABASE_MODULE_AVAILABLE = True
        print("[STARTUP] Loaded database module from gui_app package")
    except ImportError:
        try:
            import database as db_module
            db = db_module
            DATABASE_MODULE_AVAILABLE = True
            print("[STARTUP] Loaded database module directly")
        except ImportError:
            print("[STARTUP] Database module not available")
    
    try:
        from broker_manager import BrokerManager as BM
        BrokerManager = BM
        BROKER_MANAGER_AVAILABLE = True
    except ImportError:
        print("[STARTUP] Broker manager not available")
    
    try:
        from src.brokers.alpaca_broker import AlpacaBroker as AB
        AlpacaBroker = AB
        ALPACA_AVAILABLE = True
    except ImportError as e:
        print(f"[WARNING] Could not import AlpacaBroker: {e}")
    
    return {
        'ai_imports': AI_IMPORTS_AVAILABLE,
        'alpha_vantage': ALPHA_VANTAGE_AVAILABLE,
        'swing_analyzer': SWING_ANALYZER_AVAILABLE,
        'news_service': NEWS_SERVICE_AVAILABLE,
        'database': DATABASE_MODULE_AVAILABLE,
        'broker_manager': BROKER_MANAGER_AVAILABLE,
        'alpaca': ALPACA_AVAILABLE,
    }


def is_available(module_name: str) -> bool:
    """
    Check if an optional module is available.
    
    Args:
        module_name: Name of the module to check
        
    Returns:
        True if module is available
    """
    availability_map = {
        'ai': AI_IMPORTS_AVAILABLE,
        'alpha_vantage': ALPHA_VANTAGE_AVAILABLE,
        'swing_analyzer': SWING_ANALYZER_AVAILABLE,
        'news_service': NEWS_SERVICE_AVAILABLE,
        'database': DATABASE_MODULE_AVAILABLE,
        'broker_manager': BROKER_MANAGER_AVAILABLE,
        'alpaca': ALPACA_AVAILABLE,
    }
    return availability_map.get(module_name, False)


def get_module(module_name: str) -> Optional[Any]:
    """
    Get an optional module if available.
    
    Args:
        module_name: Name of the module to get
        
    Returns:
        Module instance or None if not available
    """
    module_map = {
        'trade_analyzer': TradeAnalyzer,
        'sentiment_analyzer': SentimentAnalyzer,
        'trade_tracker': TradeTracker,
        'alpha_vantage_scanner': AlphaVantageScanner,
        'swing_analyzer': SwingTradeAnalyzer,
        'fundamental_analyzer': FundamentalAnalyzer,
        'news_service': NewsService,
        'broker_manager': BrokerManager,
        'alpaca_broker': AlpacaBroker,
        'database': db,
    }
    return module_map.get(module_name)
