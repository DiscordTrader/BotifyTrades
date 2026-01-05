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

INDIA_OPT_PATTERN_1 = r'(?:^|\s)(BUY|SELL)\s+([A-Za-z]+)\s+(\d+)\s*(CE|PE)\s*(?:@|AT)?\s*[₹]?([\d.]+)'

INDIA_OPT_PATTERN_2 = r'(?:^|\s)([A-Za-z]+)\s+(\d+)\s*(CE|PE)\s*(BUY|SELL)\s*(?:@|AT)?\s*[₹]?([\d.]+)'

INDIA_OPT_PATTERN_3 = r'(?:^|\s)(BUY|SELL)\s+([A-Za-z]+)\s+(\d+)\s*(CE|PE)\s+(\d{1,2}\s*(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*\d{2,4})?\s*(?:@|AT)?\s*[₹]?([\d.]+)'

INDIA_OPT_PATTERN_4 = r'(?:^|\s)(BUY|SELL)\s+(?:(\d+)\s+(?:LOT|LOTS|QTY)\s+)?([A-Za-z]+)\s+(\d+)\s*(CE|PE)\s*(?:@|AT)?\s*[₹]?([\d.]+)'

INDIA_OPT_PATTERN_5 = r'(?:^|\s)(BUY|SELL)\s+(\d+)\s+([A-Za-z]+)\s+(\d+)\s*(CE|PE)\s*(?:@|AT)?\s*[₹]?([\d.]+)'

INDIA_OPT_PATTERN_ABOVE = r'(?:^|\s)(BUY|SELL)\s+([A-Za-z]+)\s+(\d+)\s*(CE|PE)\s+(?:ABOVE|BELOW)\s*[₹]?([\d.]+)'

INDIA_OPT_PATTERN_EXPIRY_FIRST = r'(?:^|\s)(BUY|SELL)\s+(\d+)\s+([A-Za-z]+)\s+(\d{1,2}[A-Z]{3}\d{2})\s+(\d+)\s*(CE|PE)(?:\s*(?:@|AT)?\s*[₹]?([\d.]+))?'

INDIA_OPT_PATTERN_NO_PRICE = r'(?:^|\s)(BUY|SELL)\s+(\d+)\s+([A-Za-z]+)\s+(\d+)\s*(CE|PE)\s+(\d{1,2}[A-Z]{3}\d{2})'

INDIA_STK_PATTERN = r'(?:^|\s)(BUY|SELL)\s+([A-Za-z]+)\s*(?:@|AT)?\s*[₹]?([\d.]+)'

INDIA_PATTERNS = [
    INDIA_OPT_PATTERN_ABOVE,
    INDIA_OPT_PATTERN_EXPIRY_FIRST,
    INDIA_OPT_PATTERN_NO_PRICE,
    INDIA_OPT_PATTERN_1,
    INDIA_OPT_PATTERN_2,
    INDIA_OPT_PATTERN_3,
    INDIA_OPT_PATTERN_4,
    INDIA_OPT_PATTERN_5,
]

INDIA_MONTH_MAP = {
    'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
    'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
}

NSE_LOT_SIZES = {
    'NIFTY': 25,
    'BANKNIFTY': 15,
    'FINNIFTY': 25,
    'MIDCPNIFTY': 50,
    'SENSEX': 10,
    'BANKEX': 15,
    'RELIANCE': 250,
    'TCS': 150,
    'INFY': 300,
    'HDFCBANK': 550,
    'ICICIBANK': 1375,
    'SBIN': 1500,
    'TATAMOTORS': 1425,
    'TATASTEEL': 1500,
    'ITC': 1600,
    'HINDUNILVR': 300,
    'BAJFINANCE': 125,
    'LT': 150,
    'AXISBANK': 600,
    'KOTAKBANK': 400,
    'MARUTI': 100,
    'BHARTIARTL': 950,
    'ASIANPAINT': 200,
    'WIPRO': 1500,
    'HCLTECH': 350,
    'ADANIENT': 250,
    'ADANIPORTS': 1250,
    'COALINDIA': 2100,
    'ONGC': 3850,
    'POWERGRID': 2700,
    'NTPC': 2925,
}


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
