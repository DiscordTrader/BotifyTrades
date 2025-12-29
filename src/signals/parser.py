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


# Bullwinkle format patterns - comprehensive support
# Entry emoji indicators: :green_alert: or 🟢
BULLWINKLE_ENTRY_INDICATORS = [':green_alert:', '🟢', ':greenalert:']
BULLWINKLE_EXIT_INDICATORS = [':SirenRed:', ':sirenred:', '🔴', ':red_circle:']

# Entry patterns (multiple variants)
# Pattern 1: :green_alert: BTO 3 AMPX | $11 C .95 2/20 (with BTO keyword and qty prefix)
BULLWINKLE_ENTRY_BTO_QTY = re.compile(
    r'(?::?green_alert:?|🟢)\s*BTO\s+(\d+)\s+\$?([A-Z]+)\s*\|\s*\$?([\d.]+)\s*([CP])\s*([\d.]+)(?:\s+(.+?))?$',
    re.IGNORECASE
)

# Pattern 2: 🟢BTO $RKT | 21.2 C JAN/16 .56 5 cons (with BTO, expiry, qty at end)
BULLWINKLE_ENTRY_BTO_QTY_END = re.compile(
    r'(?::?green_alert:?|🟢)\s*BTO\s+\$?([A-Z]+)\s*\|\s*\$?([\d.]+)\s*([CP])\s+([A-Z]+\s*/?\s*\d+|\d+/\d+|NEXT\s*WEEK)\s+([\d.]+)\s+(\d+)\s*(?:cons?|contracts?)?',
    re.IGNORECASE
)

# Pattern 3: :green_alert: SYMBOL | $STRIKE C/P PRICE EXPIRY (standard scalp - price before expiry text)
BULLWINKLE_ENTRY_STANDARD = re.compile(
    r'(?::?green_alert:?|🟢)\s*\$?([A-Z]+)\s*\|\s*\$?([\d.]+)\s*([CP])\s+([\d.]+)(?:\s+(.+?))?$',
    re.IGNORECASE
)

# Pattern 4: :green_alert: SYMBOL | STRIKE C EXPIRY PRICE (price at end after expiry)
BULLWINKLE_ENTRY_PRICE_END = re.compile(
    r'(?::?green_alert:?|🟢)\s*\$?([A-Z]+)\s*\|\s*\$?([\d.]+)\s*([CP])\s+([A-Z]+\s*/?\s*\d+|\d+/\d+|NEXT\s*WEEK|[A-Z]+\s*/?\s*\d{4}|[A-Z]+\s+\d{4}|[A-Z]+)\s+([\d.]+)$',
    re.IGNORECASE
)

# Pattern 5: :green_alert: SYMBOL | $STRIKE PRICE EXPIRY (no C/P, assume call)
# Example: :green_alert: TSLA | $492.5 10.10 JAN 2ND
BULLWINKLE_ENTRY_NO_CP = re.compile(
    r'(?::?green_alert:?|🟢)\s*\$?([A-Z]+)\s*\|\s*\$?([\d.]+)\s+([\d.]+)\s+([A-Z]+\s*\d+(?:ST|ND|RD|TH)?|[A-Z]+\s*/?\s*\d+|\d+/\d+)',
    re.IGNORECASE
)

# Exit patterns (multiple variants)
# Pattern 1: :SirenRed: STC ALL $AMPX ✅ (STC keyword without price)
BULLWINKLE_EXIT_STC_ALL = re.compile(
    r'(?::?SirenRed:?|🔴)\s*STC\s+(?:ALL|\d+)\s+\$?([A-Z]+)',
    re.IGNORECASE
)

# Pattern 2: :SirenRed: STC 4 RKT @ .75 SL .70 (STC with qty and price)
BULLWINKLE_EXIT_STC_QTY_PRICE = re.compile(
    r'(?::?SirenRed:?|🔴)\s*STC\s+(\d+)\s+\$?([A-Z]+)\s*@?\s*([\d.]+)',
    re.IGNORECASE
)

# Pattern 3: :SirenRed: STC $SYMBOL | .70 OUT ALL ✅ (STC with pipe and OUT)
BULLWINKLE_EXIT_STC_PIPE = re.compile(
    r'(?::?SirenRed:?|🔴)\s*STC\s+\$?([A-Z]+)\s*\|\s*([\d.]+)\s*OUT',
    re.IGNORECASE
)

# Pattern 4: :SirenRed: SYMBOL | PRICE OUT ... (original pattern)
BULLWINKLE_EXIT_PIPE_PRICE = re.compile(
    r'(?::?SirenRed:?|🔴)\s*\$?([A-Z]+)\s*\|\s*([\d.]+)\s*OUT',
    re.IGNORECASE
)

# Pattern 5: :SirenRed: SYMBOL | OUT @ PRICE ... (OUT @ format)
BULLWINKLE_EXIT_OUT_AT = re.compile(
    r'(?::?SirenRed:?|🔴)\s*\$?([A-Z]+)\s*\|\s*OUT\s*@?\s*([\d.]+)',
    re.IGNORECASE
)

# Pattern 6: :SirenRed: PLTR 1.40OUT ALL (no space before OUT)
BULLWINKLE_EXIT_NO_SPACE = re.compile(
    r'(?::?SirenRed:?|🔴)\s*\$?([A-Z]+)\s+([\d.]+)OUT',
    re.IGNORECASE
)

# Pattern 7: :SirenRed: STC $SYMBOL OUT ALL BUT 1 $PRICE (complex format)
BULLWINKLE_EXIT_COMPLEX = re.compile(
    r'(?::?SirenRed:?|🔴)\s*STC\s+\$?([A-Z]+)\s+OUT\s+.*?\$?([\d.]+)',
    re.IGNORECASE
)

# Legacy patterns for backward compatibility
BULLWINKLE_ENTRY_PATTERN = BULLWINKLE_ENTRY_STANDARD
BULLWINKLE_EXIT_PATTERN = BULLWINKLE_EXIT_PIPE_PRICE

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

# Bracket order format patterns (stock signals with targets and stop loss)
# Example: BTO ENSC @ $2.02 (break)\nTargets: $2.1, $2.16, $2.22\nSL: $1.78
BRACKET_BTO_PATTERN = re.compile(
    r'BTO\s+\$?([A-Z]+)\s*@\s*\$?([\d.]+)(?:\s*\(([^)]+)\))?',
    re.IGNORECASE
)
BRACKET_TARGETS_PATTERN = re.compile(
    r'Targets?:\s*([\d.$,\s]+)',
    re.IGNORECASE
)
BRACKET_SL_PATTERN = re.compile(
    r'SL:\s*\$?([\d.]+)',
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


def parse_bracket_order_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse bracket order format signals with targets and stop loss.
    
    Example:
    BTO ENSC @ $2.02 (break)
    Targets: $2.1, $2.16, $2.22
    SL: $1.78
    
    Returns dict with parsed components or None if not a bracket order.
    """
    bto_match = BRACKET_BTO_PATTERN.search(text)
    if not bto_match:
        return None
    
    ticker = bto_match.group(1).upper()
    entry_price = float(bto_match.group(2))
    qualifier = bto_match.group(3) if bto_match.group(3) else None
    
    # Parse targets
    targets = []
    targets_match = BRACKET_TARGETS_PATTERN.search(text)
    if targets_match:
        targets_str = targets_match.group(1)
        for target in re.split(r'[,\s]+', targets_str):
            target_clean = re.sub(r'[^\d.]', '', target.strip())
            if target_clean:
                try:
                    targets.append(float(target_clean))
                except ValueError:
                    pass
    
    # Parse stop loss
    stop_loss = None
    sl_match = BRACKET_SL_PATTERN.search(text)
    if sl_match:
        stop_loss = float(sl_match.group(1))
    
    result = {
        'format': 'BRACKET_ORDER',
        'ticker': ticker,
        'symbol': ticker,
        'entry_price': entry_price,
        'price': entry_price,
        'entry_qualifier': qualifier,
        'profit_targets': targets,
        'stop_loss': stop_loss,
        'action': 'BTO',
        'asset': 'stock',
        'asset_type': 'stock',
        'qty': 1,
        '_qty_from_signal': False,
        '_bracket_order': True,
    }
    
    print(f"[BRACKET ORDER] ✓ Parsed: {ticker} @ {entry_price}, SL={stop_loss}, PTs={targets}")
    return result


def is_bracket_order_signal(text: str) -> bool:
    """Check if text is a bracket order format signal with targets/SL."""
    has_bto = BRACKET_BTO_PATTERN.search(text) is not None
    has_targets = BRACKET_TARGETS_PATTERN.search(text) is not None
    has_sl = BRACKET_SL_PATTERN.search(text) is not None
    return has_bto and (has_targets or has_sl)


def _parse_bullwinkle_expiry(expiry_text: str) -> str:
    """
    Parse Bullwinkle expiry text into MM/DD format.
    
    Supports:
    - "2/20", "12/12" (direct MM/DD)
    - "JAN/16", "JAN / 23" (month/day)
    - "NEXT WEEK" (next Friday)
    - "JAN 2027", "JAN / 2027", "MARCH 2026" (month year - use 3rd Friday)
    - "JAN", "MARCH" (just month - assume current year, 3rd Friday)
    """
    from datetime import datetime, timedelta
    import calendar
    
    if not expiry_text:
        # Default to today for 0DTE scalps
        return datetime.now().strftime("%m/%d")
    
    expiry_text = expiry_text.strip().upper()
    
    # Direct MM/DD format
    if re.match(r'^\d{1,2}/\d{1,2}$', expiry_text):
        parts = expiry_text.split('/')
        return f"{int(parts[0]):02d}/{int(parts[1]):02d}"
    
    # NEXT WEEK - find next Friday
    if 'NEXT' in expiry_text and 'WEEK' in expiry_text:
        today = datetime.now()
        days_until_friday = (4 - today.weekday()) % 7
        if days_until_friday == 0:
            days_until_friday = 7  # Next Friday, not today
        next_friday = today + timedelta(days=days_until_friday)
        return next_friday.strftime("%m/%d")
    
    # Month name mapping
    month_map = {
        'JAN': 1, 'JANUARY': 1, 'FEB': 2, 'FEBRUARY': 2,
        'MAR': 3, 'MARCH': 3, 'APR': 4, 'APRIL': 4,
        'MAY': 5, 'JUN': 6, 'JUNE': 6, 'JUL': 7, 'JULY': 7,
        'AUG': 8, 'AUGUST': 8, 'SEP': 9, 'SEPTEMBER': 9,
        'OCT': 10, 'OCTOBER': 10, 'NOV': 11, 'NOVEMBER': 11,
        'DEC': 12, 'DECEMBER': 12
    }
    
    # JAN/16, JAN / 23 format
    month_day_match = re.match(r'([A-Z]+)\s*/?\s*(\d{1,2})$', expiry_text)
    if month_day_match:
        month_str, day = month_day_match.groups()
        month = month_map.get(month_str)
        if month:
            return f"{month:02d}/{int(day):02d}"
    
    # JAN 2ND, DEC 15TH, MAR 3RD format (ordinal dates)
    ordinal_match = re.match(r'([A-Z]+)\s*(\d{1,2})(?:ST|ND|RD|TH)?$', expiry_text)
    if ordinal_match:
        month_str, day = ordinal_match.groups()
        month = month_map.get(month_str)
        if month:
            return f"{month:02d}/{int(day):02d}"
    
    # JAN 2027, MARCH 2026, JAN / 2027 format - use 3rd Friday of month
    month_year_match = re.match(r'([A-Z]+)\s*/?\s*(\d{4})$', expiry_text)
    if month_year_match:
        month_str, year = month_year_match.groups()
        month = month_map.get(month_str)
        if month:
            # Find 3rd Friday of that month
            year_int = int(year)
            first_day = datetime(year_int, month, 1)
            first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
            third_friday = first_friday + timedelta(weeks=2)
            return third_friday.strftime("%m/%d")
    
    # Just month name (JAN, MARCH) - assume current/next occurrence, 3rd Friday
    for month_name, month_num in month_map.items():
        if month_name in expiry_text:
            today = datetime.now()
            year = today.year
            # If month already passed, use next year
            if month_num < today.month:
                year += 1
            first_day = datetime(year, month_num, 1)
            first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
            third_friday = first_friday + timedelta(weeks=2)
            return third_friday.strftime("%m/%d")
    
    # Fallback to today
    return datetime.now().strftime("%m/%d")


def is_bullwinkle_signal(text: str) -> bool:
    """Check if text is a Bullwinkle format signal."""
    text_lower = text.lower()
    for indicator in BULLWINKLE_ENTRY_INDICATORS:
        if indicator.lower() in text_lower:
            return True
    for indicator in BULLWINKLE_EXIT_INDICATORS:
        if indicator.lower() in text_lower:
            return True
    return False


def parse_bullwinkle_signal(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Bullwinkle format signals into structured dict.
    
    Supports multiple entry/exit formats including:
    - :green_alert: BTO 3 AMPX | $11 C .95 2/20
    - 🟢BTO $RKT | 21.2 C JAN/16 .56 5 cons
    - :green_alert: NVDA | $177.5 C 1.32
    - :green_alert: PLTR | 200 C NEXT WEEK .80
    - :SirenRed: STC ALL $AMPX ✅
    - :SirenRed: NVDA | 1.44 OUT ALL ✅
    
    Returns structured dict with symbol, strike, opt_type, expiry, price, qty, action.
    """
    if not is_bullwinkle_signal(text):
        return None
    
    # Clean text - remove @everyone and checkmark
    clean_text = re.sub(r'@everyone|✅|✔|@here', '', text).strip()
    
    # Try exit patterns first (more specific)
    
    # Exit Pattern 1: :SirenRed: STC ALL $AMPX
    match = BULLWINKLE_EXIT_STC_ALL.search(clean_text)
    if match:
        symbol = match.group(1).upper()
        return {
            'action': 'STC',
            'symbol': symbol,
            'price': None,  # Will need position lookup
            'qty': None,  # ALL = close full position
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 2: :SirenRed: STC 4 RKT @ .75
    match = BULLWINKLE_EXIT_STC_QTY_PRICE.search(clean_text)
    if match:
        qty, symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': int(qty),
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 3: :SirenRed: STC $SYMBOL | .70 OUT
    match = BULLWINKLE_EXIT_STC_PIPE.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 4: :SirenRed: SYMBOL | PRICE OUT
    match = BULLWINKLE_EXIT_PIPE_PRICE.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 5: :SirenRed: SYMBOL | OUT @ PRICE
    match = BULLWINKLE_EXIT_OUT_AT.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 6: :SirenRed: PLTR 1.40OUT
    match = BULLWINKLE_EXIT_NO_SPACE.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Exit Pattern 7: :SirenRed: STC $SYMBOL OUT ALL BUT 1 $PRICE
    match = BULLWINKLE_EXIT_COMPLEX.search(clean_text)
    if match:
        symbol, price = match.groups()
        return {
            'action': 'STC',
            'symbol': symbol.upper(),
            'price': float(price) if price else None,
            'qty': None,
            'is_exit': True,
            '_bullwinkle': True,
            '_needs_position_lookup': True,
        }
    
    # Now try entry patterns
    
    # Entry Pattern 1: :green_alert: BTO 3 AMPX | $11 C .95 2/20
    match = BULLWINKLE_ENTRY_BTO_QTY.search(clean_text)
    if match:
        qty, symbol, strike, opt_type, price, expiry_text = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': int(qty),
            '_qty_from_signal': True,
            '_bullwinkle': True,
        }
    
    # Entry Pattern 2: 🟢BTO $RKT | 21.2 C JAN/16 .56 5 cons
    match = BULLWINKLE_ENTRY_BTO_QTY_END.search(clean_text)
    if match:
        symbol, strike, opt_type, expiry_text, price, qty = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': int(qty),
            '_qty_from_signal': True,
            '_bullwinkle': True,
        }
    
    # Entry Pattern 4 (before 3): :green_alert: SYMBOL | STRIKE C EXPIRY PRICE (price at end)
    match = BULLWINKLE_ENTRY_PRICE_END.search(clean_text)
    if match:
        symbol, strike, opt_type, expiry_text, price = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': None,  # Will use defaults
            '_qty_from_signal': False,
            '_bullwinkle': True,
        }
    
    # Entry Pattern 3: :green_alert: SYMBOL | $STRIKE C PRICE (standard - price after C/P)
    match = BULLWINKLE_ENTRY_STANDARD.search(clean_text)
    if match:
        symbol, strike, opt_type, price, expiry_text = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': opt_type.upper(),
            'expiry': expiry,
            'price': float(price),
            'qty': None,  # Will use defaults
            '_qty_from_signal': False,
            '_bullwinkle': True,
        }
    
    # Entry Pattern 5: :green_alert: SYMBOL | $STRIKE PRICE EXPIRY (no C/P, assume call)
    # Example: :green_alert: TSLA | $492.5 10.10 JAN 2ND
    match = BULLWINKLE_ENTRY_NO_CP.search(clean_text)
    if match:
        symbol, strike, price, expiry_text = match.groups()
        expiry = _parse_bullwinkle_expiry(expiry_text)
        return {
            'asset': 'option',
            'action': 'BTO',
            'symbol': symbol.upper(),
            'strike': float(strike),
            'opt_type': 'C',  # Default to call when not specified
            'expiry': expiry,
            'price': float(price),
            'qty': None,
            '_qty_from_signal': False,
            '_bullwinkle': True,
        }
    
    return None


def strip_bullwinkle_emojis(text: str) -> str:
    """
    Strip emojis and Discord custom emotes from Bullwinkle signals.
    
    Removes:
    - Unicode emojis: 🟢, 🔴, ✅, etc.
    - Discord custom emotes: :green_alert:, :SirenRed:, :greenalert:, etc.
    - Discord animated emotes: <a:name:id> or <:name:id>
    
    Returns cleaned text suitable for webhook forwarding.
    """
    import re
    
    # Remove Discord custom animated emotes <a:name:id> and static <:name:id>
    clean = re.sub(r'<a?:[a-zA-Z0-9_]+:\d+>', '', text)
    
    # Remove Discord colon-coded emotes (:name: or :name_name:)
    clean = re.sub(r':[a-zA-Z0-9_]+:', '', clean)
    
    # Remove common Unicode emojis used in trading signals
    emoji_pattern = re.compile(
        "["
        "\U0001F7E2"  # 🟢 green circle
        "\U0001F534"  # 🔴 red circle
        "\U00002705"  # ✅ check mark
        "\U0001F6A8"  # 🚨 siren
        "\U0001F4C8"  # 📈 chart
        "\U0001F4CC"  # 📌 pin
        "\U0001F4B0"  # 💰 money bag
        "\U000026D4"  # ⛔ no entry
        "\U0001F525"  # 🔥 fire
        "\U0001F680"  # 🚀 rocket
        "\U0001F4A1"  # 💡 light bulb
        "\U0001F4AF"  # 💯 hundred
        "\U00002757"  # ❗ exclamation
        "\U00002B06"  # ⬆️ up arrow
        "\U00002B07"  # ⬇️ down arrow
        "]+",
        flags=re.UNICODE
    )
    clean = emoji_pattern.sub('', clean)
    
    # Clean up extra whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    
    return clean


def format_bullwinkle_for_webhook(parsed: dict) -> str:
    """
    Format a parsed Bullwinkle signal for clean webhook forwarding.
    
    Entry: BTO NVDA 177.5C 12/29 @ 1.32
    Exit: STC NVDA @ 1.44
    
    No emojis, clean format.
    """
    action = parsed.get('action', 'BTO')
    symbol = parsed.get('symbol', 'UNKNOWN')
    price = parsed.get('price', 0)
    
    if parsed.get('is_exit'):
        # Exit signal
        return f"STC {symbol} @ {price}"
    else:
        # Entry signal
        strike = parsed.get('strike', '')
        opt_type = parsed.get('opt_type', 'C')
        expiry = parsed.get('expiry', '')
        qty = parsed.get('qty')
        
        msg = f"BTO"
        if qty:
            msg += f" {qty}"
        msg += f" {symbol} {strike}{opt_type}"
        if expiry:
            msg += f" {expiry}"
        msg += f" @ {price}"
        
        return msg


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
