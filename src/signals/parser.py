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
    INDIA_PATTERNS,
    INDIA_STK_PATTERN,
    INDIA_MONTH_MAP,
    NSE_LOT_SIZES,
)


# Bullwinkle format patterns
# Entry: :green_alert: NVDA | $177.5 C 1.32
BULLWINKLE_ENTRY_PATTERN = re.compile(
    r':?green_alert:?\s*([A-Z]+)\s*\|\s*\$?([\d.]+)\s*([CP])\s*([\d.]+)',
    re.IGNORECASE
)

# Exit: :SirenRed: NVDA | 1.44 OUT ALL ✅  or  :SirenRed: TSLA | 5.00 OUT ✅
BULLWINKLE_EXIT_PATTERN = re.compile(
    r':?SirenRed:?\s*([A-Z]+)\s*\|\s*([\d.]+)\s*OUT',
    re.IGNORECASE
)

# TRADE IDEA format patterns (C1apped style)
TRADE_IDEA_TICKER_PATTERN = re.compile(
    r'(?:📌\s*)?(?:Ticker|Symbol):\s*\$?([A-Z]+)',
    re.IGNORECASE
)
TRADE_IDEA_ENTRY_PATTERN = re.compile(
    r'(?:💰\s*)?Entry:\s*\$?([\d.]+)',
    re.IGNORECASE
)
TRADE_IDEA_LEVELS_PATTERN = re.compile(
    r'(?:📈\s*)?(?:Levels|Targets|PTs?):\s*([\d.\s\-\+]+)',
    re.IGNORECASE
)
TRADE_IDEA_SL_PATTERN = re.compile(
    r'(?:⛔\s*)?(?:SL|Stop\s*Loss|Stop):\s*\$?([\d.]+)',
    re.IGNORECASE
)


def parse_trade_idea(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse TRADE IDEA format signals (C1apped style).
    
    Example:
    | TRADE IDEA
    📌 Ticker: TRIB
    💰 Entry: 1.36
    📈 Levels: 1.45 - 1.49 - 1.56 - 1.65 - 1.77+
    ⛔ SL: 1.22
    
    Returns dict with parsed components or None if not a TRADE IDEA.
    """
    if 'TRADE IDEA' not in text.upper():
        return None
    
    ticker_match = TRADE_IDEA_TICKER_PATTERN.search(text)
    entry_match = TRADE_IDEA_ENTRY_PATTERN.search(text)
    levels_match = TRADE_IDEA_LEVELS_PATTERN.search(text)
    sl_match = TRADE_IDEA_SL_PATTERN.search(text)
    
    if not ticker_match or not entry_match:
        return None
    
    ticker = ticker_match.group(1).upper()
    entry_price = float(entry_match.group(1))
    
    stop_loss = float(sl_match.group(1)) if sl_match else None
    
    profit_targets = []
    if levels_match:
        levels_str = levels_match.group(1)
        levels_str = re.sub(r'[+\s]+$', '', levels_str)
        for level in re.split(r'\s*[-–]\s*', levels_str):
            try:
                level_clean = re.sub(r'[^\d.]', '', level.strip())
                if level_clean:
                    profit_targets.append(float(level_clean))
            except ValueError:
                pass
    
    is_exit = 'all out' in text.lower() or 'closed' in text.lower() or 'exited' in text.lower()
    
    result = {
        'format': 'TRADE_IDEA',
        'ticker': ticker,
        'symbol': ticker,
        'entry_price': entry_price,
        'price': entry_price,
        'stop_loss': stop_loss,
        'profit_targets': profit_targets,
        'is_exit': is_exit,
        'action': 'STC' if is_exit else 'BTO',
        'asset': 'stock',
        'asset_type': 'stock',
        'qty': 1,
        '_qty_from_signal': False,
        '_trade_idea': True,
    }
    
    print(f"[TRADE IDEA] ✓ Parsed: {ticker} @ {entry_price}, SL={stop_loss}, PTs={profit_targets}")
    return result


def is_trade_idea_signal(text: str) -> bool:
    """Check if text is a TRADE IDEA format signal."""
    return 'TRADE IDEA' in text.upper() and (
        TRADE_IDEA_TICKER_PATTERN.search(text) is not None or
        TRADE_IDEA_ENTRY_PATTERN.search(text) is not None
    )


def normalize_bullwinkle_format(text: str) -> str:
    """
    Convert Bullwinkle scalp format to standard BTO/STC format.
    
    Entry: :green_alert: NVDA | $177.5 C 1.32 → BTO NVDA 177.5 C @ 1.32
    Exit: :SirenRed: NVDA | 1.44 OUT ALL ✅ → STC NVDA @ 1.44
    
    Note: Exit signals don't include strike/expiry, so they need position lookup.
    """
    # Check for exit signal first (more specific pattern)
    exit_match = BULLWINKLE_EXIT_PATTERN.search(text)
    if exit_match:
        symbol, price = exit_match.groups()
        # Return as stock-style STC - the caller will need to find the matching position
        normalized = f"STC {symbol.upper()} @ {price}"
        print(f"[BULLWINKLE] Converted exit: '{text[:60]}' → '{normalized}'")
        return normalized
    
    # Check for entry signal
    entry_match = BULLWINKLE_ENTRY_PATTERN.search(text)
    if entry_match:
        symbol, strike, opt_type, price = entry_match.groups()
        # Get current expiry (assume 0DTE or next trading day)
        from datetime import datetime, timedelta
        now = datetime.now()
        # Default to today's date for 0DTE scalps
        expiry = now.strftime("%m/%d")
        
        normalized = f"BTO {symbol.upper()} {strike} {opt_type.upper()} {expiry} @ {price}"
        print(f"[BULLWINKLE] Converted entry: '{text[:60]}' → '{normalized}'")
        return normalized
    
    # Not Bullwinkle format, return original
    return text


def parse_india_option_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse an Indian option trading signal from text.
    
    Supported formats:
    - "BUY NIFTY 24000 CE @ 145"
    - "SELL BANKNIFTY 49500 PE @ 220"
    - "NIFTY 24100 CE BUY @ 130"
    - "BUY 2 LOT NIFTY 24000 CE @ 145"
    - "BUY NIFTY 24000 CE 28 DEC @ 145"
    
    Args:
        text: Raw message text to parse
        
    Returns:
        Dictionary with signal details or None if not matched
    """
    from datetime import datetime
    
    text_clean = text.strip()
    
    for pattern in INDIA_PATTERNS:
        regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        m = regex.search(text_clean)
        
        if m:
            groups = m.groups()
            
            if 'INDIA_OPT_PATTERN_1' in pattern or pattern == INDIA_PATTERNS[0]:
                direction, symbol, strike, opt_type, price_str = groups[0], groups[1], groups[2], groups[3], groups[4]
                expiry_str = None
                qty = None
            elif pattern == INDIA_PATTERNS[1]:
                symbol, strike, opt_type, direction, price_str = groups[0], groups[1], groups[2], groups[3], groups[4]
                expiry_str = None
                qty = None
            elif pattern == INDIA_PATTERNS[2]:
                direction, symbol, strike, opt_type, expiry_str, price_str = groups[0], groups[1], groups[2], groups[3], groups[4], groups[5]
                qty = None
            elif pattern == INDIA_PATTERNS[3]:
                direction, qty_str, symbol, strike, opt_type, price_str = groups[0], groups[1], groups[2], groups[3], groups[4], groups[5]
                qty = int(qty_str) if qty_str else None
                expiry_str = None
            else:
                continue
            
            symbol = symbol.upper()
            direction = direction.upper()
            opt_type = opt_type.upper()
            
            action = 'BTO' if direction == 'BUY' else 'STC'
            call_put = 'C' if opt_type == 'CE' else 'P'
            
            if expiry_str:
                expiry = _parse_india_expiry(expiry_str)
            else:
                expiry = _get_next_nse_expiry(symbol)
            
            lot_size = NSE_LOT_SIZES.get(symbol, 1)
            quantity = (qty * lot_size) if qty else lot_size
            
            try:
                price = float(price_str)
            except (ValueError, TypeError):
                price = None
            
            result = {
                'asset': 'option',
                'action': action,
                'direction': action,
                'symbol': symbol,
                'strike': float(strike),
                'opt_type': call_put,
                'call_put': call_put,
                'expiry': expiry,
                'price': price,
                'qty': quantity,
                '_qty_from_signal': qty is not None,
                'lots': qty or 1,
                'lot_size': lot_size,
                'asset_type': 'option',
                'market': 'INDIA',
                'exchange_segment': 'NSE_FNO',
                'is_market_order': price is None,
                'original_format': 'INDIA',
            }
            
            print(f"[INDIA] ✓ Parsed: {action} {quantity} {symbol} {strike}{opt_type} {expiry} @ {price}")
            return result
    
    return None


def parse_india_stock_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse an Indian stock trading signal from text.
    
    Supported formats:
    - "BUY RELIANCE @ 2500"
    - "SELL TCS @ 3800"
    
    Args:
        text: Raw message text to parse
        
    Returns:
        Dictionary with signal details or None if not matched
    """
    regex = re.compile(INDIA_STK_PATTERN, re.IGNORECASE | re.MULTILINE)
    m = regex.search(text.strip())
    
    if not m:
        return None
    
    direction, symbol, price_str = m.groups()
    
    symbol = symbol.upper()
    direction = direction.upper()
    action = 'BTO' if direction == 'BUY' else 'STC'
    
    try:
        price = float(price_str)
    except (ValueError, TypeError):
        price = None
    
    result = {
        'asset': 'stock',
        'action': action,
        'direction': action,
        'symbol': symbol,
        'price': price,
        'qty': 1,
        '_qty_from_signal': False,
        'asset_type': 'stock',
        'market': 'INDIA',
        'exchange_segment': 'NSE_EQ',
        'is_market_order': price is None,
        'original_format': 'INDIA',
    }
    
    print(f"[INDIA] ✓ Parsed stock: {action} {symbol} @ {price}")
    return result


def _parse_india_expiry(expiry_str: str) -> str:
    """
    Parse Indian date format (DD MMM YYYY) to MM/DD format.
    
    Examples:
    - "28 DEC 2025" -> "12/28"
    - "28 DEC" -> "12/28"
    - "28DEC25" -> "12/28"
    """
    from datetime import datetime
    import re
    
    if not expiry_str:
        return _get_next_nse_expiry('NIFTY')
    
    expiry_clean = expiry_str.upper().strip()
    
    match = re.match(r'(\d{1,2})\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*(\d{2,4})?', expiry_clean)
    
    if match:
        day = int(match.group(1))
        month = INDIA_MONTH_MAP.get(match.group(2), 1)
        return f"{month:02d}/{day:02d}"
    
    return _get_next_nse_expiry('NIFTY')


def _get_next_nse_expiry(symbol: str) -> str:
    """
    Get the next expiry date for NSE F&O.
    
    - NIFTY/BANKNIFTY/FINNIFTY: Weekly (Thursday)
    - Others: Monthly (last Thursday)
    """
    from datetime import datetime, timedelta
    
    now = datetime.now()
    
    weekly_symbols = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'BANKEX']
    
    if symbol.upper() in weekly_symbols:
        days_ahead = 3 - now.weekday()
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0 and now.hour >= 15:
            days_ahead = 7
        
        next_thursday = now + timedelta(days=days_ahead)
        return next_thursday.strftime("%m/%d")
    else:
        year = now.year
        month = now.month
        
        last_day = (datetime(year, month % 12 + 1, 1) - timedelta(days=1)).day if month < 12 else 31
        last_thursday = None
        
        for day in range(last_day, 0, -1):
            test_date = datetime(year, month, day)
            if test_date.weekday() == 3:
                last_thursday = test_date
                break
        
        if last_thursday and last_thursday <= now:
            if month == 12:
                month = 1
                year += 1
            else:
                month += 1
            last_day = (datetime(year, month % 12 + 1, 1) - timedelta(days=1)).day if month < 12 else 31
            for day in range(last_day, 0, -1):
                test_date = datetime(year, month, day)
                if test_date.weekday() == 3:
                    last_thursday = test_date
                    break
        
        return last_thursday.strftime("%m/%d") if last_thursday else now.strftime("%m/%d")


def is_india_signal(text: str) -> bool:
    """
    Check if the text appears to be an Indian market signal.
    
    Looks for:
    - CE/PE option types
    - BUY/SELL (not BTO/STC)
    - Indian symbols like NIFTY, BANKNIFTY
    - ₹ symbol
    """
    text_upper = text.upper()
    
    if 'CE' in text_upper or 'PE' in text_upper:
        return True
    
    if ('BUY ' in text_upper or 'SELL ' in text_upper) and ('BTO ' not in text_upper and 'STC ' not in text_upper):
        india_symbols = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX', 'BANKEX', 'RELIANCE', 'TCS', 'INFY', 'HDFCBANK']
        for sym in india_symbols:
            if sym in text_upper:
                return True
    
    if '₹' in text:
        return True
    
    return False


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
    
    qty_from_signal = False
    if qty_str is None:
        # Don't calculate qty here - let the handler apply tiered defaults
        # (channel default → global default → max_position_size if enabled → 1)
        qty = None
        print(f"[SIGNAL] No quantity specified - handler will apply tiered defaults")
    else:
        qty = int(qty_str)
        qty_from_signal = True
    
    return {
        "asset": "option",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "strike": float(strike),
        "opt_type": opt_type.upper(),
        "expiry": expiry,
        "price": price,
        "is_market_order": is_market_order,
        "_qty_from_signal": qty_from_signal
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
    
    qty_from_signal = False
    if qty_str is None:
        # Don't calculate qty here - let the handler apply tiered defaults
        qty = None
        print(f"[SIGNAL] No quantity specified - handler will apply tiered defaults")
    else:
        qty = int(qty_str)
        qty_from_signal = True
    
    return {
        "asset": "stock",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "price": price,
        "is_market_order": is_market_order,
        "_qty_from_signal": qty_from_signal
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
