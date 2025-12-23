"""
Signal pattern definitions for parsing trading signals.
Contains regex patterns for options and stocks with various formats.
"""

import re
from typing import Optional

FLEXIBLE_OPT_PATTERN = r'(?:^|\s)(BTO|STC)\s+(?:(\d+)\s+)?\$?([A-Za-z]+)\s+\$?([\d.]+)\s*([CPcp])\s*(\d{1,2}/\d{1,2})\s*@?\s*([\d.]+|[mM])'

DEFAULT_STK_PATTERN = r'(?:^|\s)(BTO|STC)\s+(?:(\d+)\s+)?\$?([A-Za-z]+)\s*@?\s*([\d.]+|[mM])'

ADVANCED_OPT_PATTERNS = [
    r'(?:^|\s)(BTO|STC)\s+(?:(\d+)\s+)?\$?([A-Za-z]+)\s+\$?([\d.]+)\s*([CPcp])\s*(\d{1,2}/\d{1,2})\s*@?\s*([\d.]+|[mM])',
    r'(?:^|\s)(BTO|STC)\s+(?:(\d+)\s+)?\$?([A-Za-z]+)\s+(\d{1,2}/\d{1,2})\s+\$?([\d.]+)\s*([CPcp])\s*@?\s*([\d.]+|[mM])',
    r'(?:^|\s)(BTO|STC)\s+(?:(\d+)\s+)?(\d{1,2}/\d{1,2})\s+\$?([A-Za-z]+)\s+\$?([\d.]+)\s*([CPcp])\s*@?\s*([\d.]+|[mM])',
]

OCC_PATTERN = r'([A-Z]+)(\d{6})([CP])(\d{8})'


def create_option_regex(pattern: Optional[str] = None, ignore_case: bool = True) -> re.Pattern:
    """
    Create a compiled regex pattern for option signals.
    
    Args:
        pattern: Custom regex pattern (uses default if None)
        ignore_case: Whether to ignore case in matching
        
    Returns:
        Compiled regex pattern
    """
    if pattern is None:
        pattern = FLEXIBLE_OPT_PATTERN
    
    flags = re.MULTILINE
    if ignore_case:
        flags |= re.IGNORECASE
    
    return re.compile(pattern, flags)


def create_stock_regex(pattern: Optional[str] = None, ignore_case: bool = True) -> re.Pattern:
    """
    Create a compiled regex pattern for stock signals.
    
    Args:
        pattern: Custom regex pattern (uses default if None)
        ignore_case: Whether to ignore case in matching
        
    Returns:
        Compiled regex pattern
    """
    if pattern is None:
        pattern = DEFAULT_STK_PATTERN
    
    flags = re.MULTILINE
    if ignore_case:
        flags |= re.IGNORECASE
    
    return re.compile(pattern, flags)


def parse_occ_symbol(symbol: str) -> Optional[dict]:
    """
    Parse OCC option symbol format (e.g., ONDS251205C00009000).
    
    OCC format: ROOT + YYMMDD + C/P + PRICE (8 digits, no decimal)
    
    Args:
        symbol: OCC format option symbol
        
    Returns:
        Dictionary with parsed components or None if invalid
    """
    match = re.match(OCC_PATTERN, symbol.upper())
    if not match:
        return None
    
    root, date_str, opt_type, price_str = match.groups()
    
    year = int('20' + date_str[:2])
    month = int(date_str[2:4])
    day = int(date_str[4:6])
    
    strike = int(price_str) / 1000.0
    
    expiry = f"{month:02d}/{day:02d}"
    
    return {
        'symbol': root,
        'expiry': expiry,
        'expiry_year': str(year),
        'opt_type': opt_type,
        'strike': strike,
    }


def convert_expiry_to_occ(expiry_mmdd: str, expiry_year: Optional[str] = None) -> str:
    """
    Convert MM/DD expiry format to OCC date format (YYMMDD).
    
    Args:
        expiry_mmdd: Expiry in MM/DD format
        expiry_year: Year as YYYY or YY (defaults to current/next year)
        
    Returns:
        Expiry in YYMMDD format
    """
    from datetime import datetime
    
    parts = expiry_mmdd.split('/')
    month = int(parts[0])
    day = int(parts[1])
    
    if expiry_year:
        year = int(expiry_year) if len(expiry_year) == 4 else int('20' + expiry_year)
    else:
        now = datetime.now()
        year = now.year
        if month < now.month or (month == now.month and day < now.day):
            year += 1
    
    return f"{year % 100:02d}{month:02d}{day:02d}"
