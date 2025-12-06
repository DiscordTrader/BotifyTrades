"""
Signal parser for trading signals.
Parses option and stock signals from text messages.
"""

import re
from typing import Optional, Dict, Any

from .patterns import (
    FLEXIBLE_OPT_PATTERN,
    DEFAULT_STK_PATTERN,
    create_option_regex,
    create_stock_regex,
)


_option_regex = None
_stock_regex = None


def _get_option_regex():
    """Get or create the option regex pattern."""
    global _option_regex
    if _option_regex is None:
        pattern = None
        try:
            from gui_app.database import get_discord_settings
            discord_settings = get_discord_settings()
            db_pattern = discord_settings.get('option_pattern', '').strip()
            if db_pattern:
                pattern = db_pattern
        except Exception:
            pass
        
        if pattern is None:
            try:
                import configparser
                cfg = configparser.ConfigParser()
                cfg.read('config.ini')
                cfg.read('config.ini.example')
                pattern = cfg.get('signals', 'pattern', fallback=FLEXIBLE_OPT_PATTERN)
            except Exception:
                pattern = FLEXIBLE_OPT_PATTERN
        
        _option_regex = create_option_regex(pattern)
    
    return _option_regex


def _get_stock_regex():
    """Get or create the stock regex pattern."""
    global _stock_regex
    if _stock_regex is None:
        pattern = None
        try:
            from gui_app.database import get_discord_settings
            discord_settings = get_discord_settings()
            db_pattern = discord_settings.get('stock_pattern', '').strip()
            if db_pattern:
                pattern = db_pattern
        except Exception:
            pass
        
        if pattern is None:
            try:
                import configparser
                cfg = configparser.ConfigParser()
                cfg.read('config.ini')
                cfg.read('config.ini.example')
                pattern = cfg.get('signals', 'stock_pattern', fallback=DEFAULT_STK_PATTERN)
            except Exception:
                pattern = DEFAULT_STK_PATTERN
        
        _stock_regex = create_stock_regex(pattern)
    
    return _stock_regex


def get_default_option_pattern() -> str:
    """Get the default option signal pattern."""
    return FLEXIBLE_OPT_PATTERN


def get_default_stock_pattern() -> str:
    """Get the default stock signal pattern."""
    return DEFAULT_STK_PATTERN


def _get_max_position_size() -> float:
    """Get the max position size from settings."""
    try:
        from src.core import get_trading_settings
        settings = get_trading_settings()
        return settings.get('max_position_size', 1000)
    except ImportError:
        return 1000


def parse_option_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse an option trading signal from text.
    
    Expected format: BTO/STC [QTY] SYMBOL STRIKE C/P MM/DD @ PRICE
    Example: "BTO 5 AAPL 150 C 12/20 @ 2.50"
    Example: "STC TSLA 200 P 01/15 @ m" (market order)
    
    Args:
        text: Raw message text to parse
        
    Returns:
        Dictionary with signal details or None if not matched
    """
    regex = _get_option_regex()
    m = regex.search(text.strip())
    
    if not m:
        print(f"[SIGNAL] ❌ Option pattern NOT matched: '{text.strip()[:80]}'")
        print(f"[SIGNAL]    Expected format: BTO/STC QTY SYMBOL STRIKE C/P MM/DD @ PRICE")
        return None
    
    direction, qty_str, symbol, strike, opt_type, expiry, price_str = m.groups()
    
    is_market_order = price_str.lower() == 'm'
    if is_market_order:
        price = None
        print(f"[SIGNAL] Market order detected for {symbol} {strike}{opt_type} {expiry}")
    else:
        price = float(price_str)
    
    if qty_str is None:
        if is_market_order:
            qty = 1
            print(f"[AUTO-QTY] Market order: defaulting to 1 contract")
        else:
            max_position_size = _get_max_position_size()
            actual_cost_per_contract = price * 100
            if actual_cost_per_contract <= 0:
                print(f"[AUTO-QTY] ✗ Invalid option price: ${price}, skipping")
                return None
            qty = max(1, int(max_position_size / actual_cost_per_contract))
            print(f"[AUTO-QTY] Option: ${price} x 100 = ${actual_cost_per_contract}/contract, buying {qty} (max ${max_position_size})")
    else:
        qty = int(qty_str)
    
    return {
        "asset": "option",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "strike": float(strike),
        "opt_type": opt_type.upper(),
        "expiry": expiry,
        "price": price,
        "is_market_order": is_market_order
    }


def parse_stock_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a stock trading signal from text.
    
    Expected format: BTO/STC [QTY] SYMBOL @ PRICE
    Example: "BTO 100 AAPL @ 150.00"
    Example: "STC TSLA @ m" (market order)
    
    Args:
        text: Raw message text to parse
        
    Returns:
        Dictionary with signal details or None if not matched
    """
    regex = _get_stock_regex()
    m = regex.search(text.strip())
    
    if not m:
        return None
    
    direction, qty_str, symbol, price_str = m.groups()
    
    is_market_order = price_str.lower() == 'm'
    if is_market_order:
        price = None
        print(f"[SIGNAL] Market order detected for {symbol}")
    else:
        price = float(price_str)
    
    if qty_str is None:
        if is_market_order:
            qty = 1
            print(f"[AUTO-QTY] Market order: defaulting to 1 share")
        else:
            max_position_size = _get_max_position_size()
            if price <= 0:
                print(f"[AUTO-QTY] ✗ Invalid stock price: ${price}, skipping")
                return None
            qty = max(1, int(max_position_size / price))
            print(f"[AUTO-QTY] Stock: ${price}/share, buying {qty} shares (max ${max_position_size})")
    else:
        qty = int(qty_str)
    
    return {
        "asset": "stock",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "price": price,
        "is_market_order": is_market_order
    }


class SignalParser:
    """
    Signal parser with customizable patterns and settings.
    Use this for more control over parsing behavior.
    """
    
    def __init__(
        self,
        option_pattern: Optional[str] = None,
        stock_pattern: Optional[str] = None,
        max_position_size: float = 1000,
        ignore_case: bool = True
    ):
        """
        Initialize the signal parser.
        
        Args:
            option_pattern: Custom option regex pattern
            stock_pattern: Custom stock regex pattern
            max_position_size: Max dollar amount per position
            ignore_case: Whether to ignore case in matching
        """
        self.option_regex = create_option_regex(option_pattern, ignore_case)
        self.stock_regex = create_stock_regex(stock_pattern, ignore_case)
        self.max_position_size = max_position_size
    
    def parse(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse a trading signal from text.
        Tries option format first, then stock format.
        
        Args:
            text: Raw message text to parse
            
        Returns:
            Dictionary with signal details or None if not matched
        """
        result = self.parse_option(text)
        if result:
            return result
        
        return self.parse_stock(text)
    
    def parse_option(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse an option signal."""
        m = self.option_regex.search(text.strip())
        if not m:
            return None
        
        direction, qty_str, symbol, strike, opt_type, expiry, price_str = m.groups()
        
        is_market_order = price_str.lower() == 'm'
        price = None if is_market_order else float(price_str)
        
        if qty_str is None:
            if is_market_order:
                qty = 1
            else:
                actual_cost = price * 100
                if actual_cost <= 0:
                    return None
                qty = max(1, int(self.max_position_size / actual_cost))
        else:
            qty = int(qty_str)
        
        return {
            "asset": "option",
            "action": direction.upper(),
            "qty": qty,
            "symbol": symbol.upper(),
            "strike": float(strike),
            "opt_type": opt_type.upper(),
            "expiry": expiry,
            "price": price,
            "is_market_order": is_market_order
        }
    
    def parse_stock(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse a stock signal."""
        m = self.stock_regex.search(text.strip())
        if not m:
            return None
        
        direction, qty_str, symbol, price_str = m.groups()
        
        is_market_order = price_str.lower() == 'm'
        price = None if is_market_order else float(price_str)
        
        if qty_str is None:
            if is_market_order:
                qty = 1
            elif price and price > 0:
                qty = max(1, int(self.max_position_size / price))
            else:
                return None
        else:
            qty = int(qty_str)
        
        return {
            "asset": "stock",
            "action": direction.upper(),
            "qty": qty,
            "symbol": symbol.upper(),
            "price": price,
            "is_market_order": is_market_order
        }


def reload_patterns():
    """Force reload of regex patterns from database/config."""
    global _option_regex, _stock_regex
    _option_regex = None
    _stock_regex = None
