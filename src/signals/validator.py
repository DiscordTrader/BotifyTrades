"""
Signal validation utilities.
Validates trading signals before execution.
"""

import re
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

VALID_ACTIONS = {'BTO', 'STC', 'BUY', 'SELL'}

INVALID_SYMBOLS = {
    'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL',
    'CAN', 'HAD', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'HAS',
    'BTO', 'STC', 'BUY', 'SELL', 'CALL', 'PUT', 'STOP'
}

SYMBOL_PATTERN = re.compile(r'^[A-Z]{1,5}$')


def is_valid_action(action: str) -> bool:
    """
    Check if action is valid (BTO, STC, BUY, SELL).
    
    Args:
        action: Trading action string
        
    Returns:
        True if valid, False otherwise
    """
    return action.upper() in VALID_ACTIONS


def is_valid_symbol(symbol: str) -> bool:
    """
    Check if symbol is a valid stock ticker.
    
    Args:
        symbol: Stock ticker symbol
        
    Returns:
        True if valid, False otherwise
    """
    symbol = symbol.upper()
    
    if symbol in INVALID_SYMBOLS:
        return False
    
    if not SYMBOL_PATTERN.match(symbol):
        return False
    
    return True


def is_valid_strike(strike: float) -> bool:
    """
    Check if strike price is valid.
    
    Args:
        strike: Option strike price
        
    Returns:
        True if valid, False otherwise
    """
    if strike <= 0:
        return False
    
    if strike > 10000:
        return False
    
    return True


def is_valid_expiry(expiry: str) -> Tuple[bool, Optional[str]]:
    """
    Check if expiry date is valid and not expired.
    
    Args:
        expiry: Expiry date in MM/DD format
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        parts = expiry.split('/')
        if len(parts) != 2:
            return False, "Invalid expiry format (expected MM/DD)"
        
        month = int(parts[0])
        day = int(parts[1])
        
        if month < 1 or month > 12:
            return False, f"Invalid month: {month}"
        
        if day < 1 or day > 31:
            return False, f"Invalid day: {day}"
        
        today = datetime.now()
        year = today.year
        
        expiry_date = datetime(year, month, day)
        if expiry_date < today:
            expiry_date = datetime(year + 1, month, day)
        
        return True, None
        
    except (ValueError, TypeError) as e:
        return False, f"Invalid expiry: {str(e)}"


def is_valid_price(price: Optional[float], is_market_order: bool = False) -> bool:
    """
    Check if price is valid.
    
    Args:
        price: Limit price (None for market orders)
        is_market_order: Whether this is a market order
        
    Returns:
        True if valid, False otherwise
    """
    if is_market_order:
        return price is None
    
    if price is None:
        return False
    
    if price <= 0:
        return False
    
    if price > 100000:
        return False
    
    return True


def is_valid_quantity(qty: int) -> bool:
    """
    Check if quantity is valid.
    
    Args:
        qty: Number of contracts or shares
        
    Returns:
        True if valid, False otherwise
    """
    if qty <= 0:
        return False
    
    if qty > 10000:
        return False
    
    return True


def validate_signal(signal: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate a complete trading signal.
    
    Args:
        signal: Parsed signal dictionary
        
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    if 'action' not in signal:
        errors.append("Missing action")
    elif not is_valid_action(signal['action']):
        errors.append(f"Invalid action: {signal['action']}")
    
    if 'symbol' not in signal:
        errors.append("Missing symbol")
    elif not is_valid_symbol(signal['symbol']):
        errors.append(f"Invalid symbol: {signal['symbol']}")
    
    if 'qty' not in signal:
        errors.append("Missing quantity")
    elif not is_valid_quantity(signal['qty']):
        errors.append(f"Invalid quantity: {signal['qty']}")
    
    is_market = signal.get('is_market_order', False)
    if not is_valid_price(signal.get('price'), is_market):
        errors.append(f"Invalid price: {signal.get('price')}")
    
    if signal.get('asset') == 'option':
        if 'strike' not in signal:
            errors.append("Missing strike price")
        elif not is_valid_strike(signal['strike']):
            errors.append(f"Invalid strike: {signal['strike']}")
        
        if 'expiry' not in signal:
            errors.append("Missing expiry date")
        else:
            valid, error = is_valid_expiry(signal['expiry'])
            if not valid:
                errors.append(error)
        
        if 'opt_type' not in signal:
            errors.append("Missing option type (C/P)")
        elif signal['opt_type'].upper() not in ('C', 'P'):
            errors.append(f"Invalid option type: {signal['opt_type']}")
    
    return len(errors) == 0, errors


def normalize_signal(signal: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize signal fields to consistent format.
    
    Args:
        signal: Parsed signal dictionary
        
    Returns:
        Normalized signal dictionary
    """
    normalized = signal.copy()
    
    if 'action' in normalized:
        normalized['action'] = normalized['action'].upper()
    
    if 'symbol' in normalized:
        normalized['symbol'] = normalized['symbol'].upper()
    
    if 'opt_type' in normalized:
        normalized['opt_type'] = normalized['opt_type'].upper()
    
    if 'qty' in normalized:
        normalized['qty'] = int(normalized['qty'])
    
    if 'strike' in normalized:
        normalized['strike'] = float(normalized['strike'])
    
    if 'price' in normalized and normalized['price'] is not None:
        normalized['price'] = float(normalized['price'])
    
    if 'is_market_order' not in normalized:
        normalized['is_market_order'] = normalized.get('price') is None
    
    return normalized
