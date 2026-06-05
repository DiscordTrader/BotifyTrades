"""
Bronze Swings Signal Parser

Parses natural language stock swing signals from bronze-swings channel.
Patterns detected:
- ENTRY: "Taken a position on SYMBOL", "Starter position on SYMBOL", "Entered SYMBOL", "Long swing"
- EXIT: "Closed position on SYMBOL", "SYMBOL position closed", "Closed SYMBOL"
- ADD: "Added to SYMBOL", "Added average price"
- TRIM: "taken profits", "secured profits"
"""

import re
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass


@dataclass
class BronzeSwingsSignal:
    """Parsed signal from bronze-swings channel."""
    action: str  # ENTRY, EXIT, ADD, TRIM
    symbol: str
    price: Optional[float] = None
    percentage: Optional[float] = None  # For profit taking
    size_info: Optional[str] = None  # "starter", "half size", "full position", etc.
    raw_message: str = ""
    confidence: float = 0.9


# Regex patterns for bronze-swings signals
BRONZE_SWINGS_PATTERNS: List[Tuple[str, str, re.Pattern]] = [
    # ENTRY patterns
    ("ENTRY", "starter_position", re.compile(
        r"(?:taken\s+a\s+)?starter\s+position\s+on\s+\$?([A-Z]{1,5})\s*(?:@?\s*\$?([\d.]+))?",
        re.IGNORECASE
    )),
    ("ENTRY", "position_on", re.compile(
        r"taken\s+a\s+(?:swing\s+)?position\s+on\s+\$?([A-Z]{1,5})\s*(?:@?\s*\$?([\d.]+))?",
        re.IGNORECASE
    )),
    ("ENTRY", "entered", re.compile(
        r"entered\s+\$?([A-Z]{1,5})\s*(?:@?\s*\$?([\d.]+))?\s*(?:average\s+price)?",
        re.IGNORECASE
    )),
    ("ENTRY", "half_size", re.compile(
        r"(?:\$?([A-Z]{1,5})\s+)?.*?half\s+size\s+position\s*(?:@?\s*\$?([\d.]+))?",
        re.IGNORECASE
    )),
    ("ENTRY", "size_position", re.compile(
        r"(\d+%?)\s+size\s+position\s+(?:now\s+)?(?:on\s+)?\$?([A-Z]{1,5})?",
        re.IGNORECASE
    )),
    ("ENTRY", "long_swing", re.compile(
        r"\$?([A-Z]{1,5})\s+(?:long\s+swing|for\s+a\s+long\s+swing)",
        re.IGNORECASE
    )),
    ("ENTRY", "swing_position", re.compile(
        r"swing\s+position\s+on\s+\$?([A-Z]{1,5})\s*.*?average\s+price\s*\$?([\d.]+)?",
        re.IGNORECASE
    )),
    
    # EXIT patterns
    ("EXIT", "closed_position_on", re.compile(
        r"closed\s+(?:his\s+)?position\s+(?:now\s+)?(?:on|in)\s+\$?([A-Z]{1,5})",
        re.IGNORECASE
    )),
    ("EXIT", "position_closed", re.compile(
        r"\$?([A-Z]{1,5})\s+position\s+closed",
        re.IGNORECASE
    )),
    ("EXIT", "closed_symbol", re.compile(
        r"closed\s+\$?([A-Z]{1,5})\s*(?:position)?\s*(?:@?\s*\$?([\d.]+))?",
        re.IGNORECASE
    )),
    ("EXIT", "closed_at", re.compile(
        r"closed\s+(?:position\s+)?(?:at|@)\s*\$?([\d.]+)",
        re.IGNORECASE
    )),
    
    # ADD patterns
    ("ADD", "added_to", re.compile(
        r"added\s+to\s+\$?([A-Z]{1,5})\s*(?:@?\s*\$?([\d.]+))?(?:\s*average\s+price)?",
        re.IGNORECASE
    )),
    ("ADD", "symbol_added", re.compile(
        r"\$?([A-Z]{1,5})\s+added\s+(?:average\s+price\s*)?\$?([\d.]+)?",
        re.IGNORECASE
    )),
    ("ADD", "added_average", re.compile(
        r"added\s+(?:same\s+)?average\s+price\s*\$?([\d.]+)?",
        re.IGNORECASE
    )),
    ("ADD", "added_another", re.compile(
        r"added\s+another\s+(\d+%?)\s+to\s+(?:my\s+)?position\s+(?:on\s+)?\$?([A-Z]{1,5})",
        re.IGNORECASE
    )),
    
    # TRIM patterns
    ("TRIM", "taken_profits", re.compile(
        r"\$?([A-Z]{1,5})\s+taken\s+profits?\s*(?:@?\s*(\d+)%)?",
        re.IGNORECASE
    )),
    ("TRIM", "secured_profits", re.compile(
        r"(?:\$?([A-Z]{1,5})\s+.*?)?secured\s+profits?\s*(?:on\s+\$?([A-Z]{1,5}))?",
        re.IGNORECASE
    )),
    ("TRIM", "sold_for", re.compile(
        r"\$?([A-Z]{1,5})\s+sold\s+.*?for\s+(\d+(?:\.\d+)?%?)",
        re.IGNORECASE
    )),
]

# Common stock symbols to validate
COMMON_WORDS_TO_EXCLUDE = {
    'THE', 'AND', 'FOR', 'WITH', 'FROM', 'THIS', 'THAT', 'WILL', 'HAVE',
    'BEEN', 'WHEN', 'ALSO', 'JUST', 'LIKE', 'MAKE', 'SURE', 'TAKE', 'KEEP',
    'HOLD', 'LOOK', 'GOOD', 'BACK', 'OVER', 'VERY', 'SOME', 'ONLY', 'WANT',
    'NEED', 'WELL', 'STILL', 'LONG', 'RISK', 'FREE', 'NEW', 'NOW', 'ALL',
    'UP', 'OUT', 'IN', 'ON', 'AT', 'TO', 'MY', 'IF', 'IT', 'AS', 'SO'
}


def _is_valid_symbol(symbol: Optional[str]) -> bool:
    """Validate if a string looks like a stock symbol."""
    if not symbol:
        return False
    symbol = symbol.upper().strip()
    if len(symbol) < 1 or len(symbol) > 5:
        return False
    if not symbol.isalpha():
        return False
    if symbol in COMMON_WORDS_TO_EXCLUDE:
        return False
    return True


def _extract_symbol_from_context(text: str) -> Optional[str]:
    """Try to extract a stock symbol from surrounding context."""
    dollar_match = re.search(r'\$([A-Z]{1,5})\b', text, re.IGNORECASE)
    if dollar_match:
        symbol = dollar_match.group(1).upper()
        if _is_valid_symbol(symbol):
            return symbol
    
    words = re.findall(r'\b([A-Z]{2,5})\b', text)
    for word in words:
        if _is_valid_symbol(word):
            return word
    
    return None


def _extract_price(text: str) -> Optional[float]:
    """Extract price from text."""
    price_match = re.search(r'\$\s*([\d.]+)', text)
    if price_match:
        try:
            return float(price_match.group(1))
        except ValueError:
            pass
    
    avg_match = re.search(r'average\s+price\s*\$?\s*([\d.]+)', text, re.IGNORECASE)
    if avg_match:
        try:
            return float(avg_match.group(1))
        except ValueError:
            pass
    
    return None


def parse_bronze_swings_signal(content: str) -> Optional[BronzeSwingsSignal]:
    """
    Parse a bronze-swings signal from message content.
    
    Args:
        content: Raw message content
        
    Returns:
        BronzeSwingsSignal if detected, None otherwise
    """
    if not content or len(content) < 10:
        return None
    
    content_clean = content.strip()
    
    for action, pattern_name, pattern in BRONZE_SWINGS_PATTERNS:
        match = pattern.search(content_clean)
        if match:
            groups = match.groups()
            symbol = None
            price = None
            percentage = None
            size_info = None
            
            if pattern_name == "starter_position":
                symbol = groups[0] if groups else None
                price = float(groups[1]) if len(groups) > 1 and groups[1] else None
                size_info = "starter"
                
            elif pattern_name == "position_on":
                symbol = groups[0] if groups else None
                price = float(groups[1]) if len(groups) > 1 and groups[1] else None
                
            elif pattern_name == "entered":
                symbol = groups[0] if groups else None
                price = float(groups[1]) if len(groups) > 1 and groups[1] else None
                
            elif pattern_name == "half_size":
                symbol = groups[0] if groups and groups[0] else None
                price = float(groups[1]) if len(groups) > 1 and groups[1] else None
                size_info = "half size"
                if not symbol:
                    symbol = _extract_symbol_from_context(content_clean)
                    
            elif pattern_name == "size_position":
                size_info = groups[0] if groups else None
                symbol = groups[1] if len(groups) > 1 else None
                if not symbol:
                    symbol = _extract_symbol_from_context(content_clean)
                    
            elif pattern_name == "long_swing":
                symbol = groups[0] if groups else None
                size_info = "long swing"
                
            elif pattern_name == "swing_position":
                symbol = groups[0] if groups else None
                price = float(groups[1]) if len(groups) > 1 and groups[1] else None
                
            elif pattern_name == "closed_position_on":
                symbol = groups[0] if groups else None
                
            elif pattern_name == "position_closed":
                symbol = groups[0] if groups else None
                
            elif pattern_name == "closed_symbol":
                symbol = groups[0] if groups else None
                price = float(groups[1]) if len(groups) > 1 and groups[1] else None
                
            elif pattern_name == "closed_at":
                price = float(groups[0]) if groups and groups[0] else None
                symbol = _extract_symbol_from_context(content_clean)
                
            elif pattern_name == "added_to":
                symbol = groups[0] if groups else None
                price = float(groups[1]) if len(groups) > 1 and groups[1] else None
                
            elif pattern_name == "symbol_added":
                symbol = groups[0] if groups else None
                price = float(groups[1]) if len(groups) > 1 and groups[1] else None
                
            elif pattern_name == "added_average":
                price = float(groups[0]) if groups and groups[0] else None
                symbol = _extract_symbol_from_context(content_clean)
                
            elif pattern_name == "added_another":
                size_info = groups[0] if groups else None
                symbol = groups[1] if len(groups) > 1 else None
                
            elif pattern_name == "taken_profits":
                symbol = groups[0] if groups else None
                percentage = float(groups[1]) if len(groups) > 1 and groups[1] else None
                
            elif pattern_name == "secured_profits":
                symbol = groups[0] if groups and groups[0] else None
                if not symbol and len(groups) > 1:
                    symbol = groups[1]
                
            elif pattern_name == "sold_for":
                symbol = groups[0] if groups else None
                pct_str = groups[1] if len(groups) > 1 else None
                if pct_str:
                    try:
                        percentage = float(pct_str.replace('%', ''))
                    except ValueError:
                        pass
            
            if not symbol:
                symbol = _extract_symbol_from_context(content_clean)
            
            if symbol and _is_valid_symbol(symbol):
                if not price:
                    price = _extract_price(content_clean)
                
                return BronzeSwingsSignal(
                    action=action,
                    symbol=symbol.upper(),
                    price=price,
                    percentage=percentage,
                    size_info=size_info,
                    raw_message=content_clean[:200],
                    confidence=0.9
                )
    
    return None


def test_parser():
    """Test the parser with sample messages."""
    test_messages = [
        "Taken a starter position on DUOL $177.69",
        "Added to SRFM average price $1.97",
        "Closed position now on SRFM",
        "SRFM taken profits @55%",
        "Entered LFST @$6.02 average price for a long swing!",
        "Half size position @$5.91",
        "CYBN position closed",
        "Closed LCID position at $2.32",
        "BGC added average price $9.28",
        "Added to RXRX full position now average price $4.80",
        "secured profits on BITF",
        "swing position on OLO average price $8.73",
    ]
    
    print("=== Bronze Swings Parser Test ===\n")
    for msg in test_messages:
        result = parse_bronze_swings_signal(msg)
        if result:
            print(f"[{result.action}] {result.symbol}")
            print(f"  Price: {result.price}, Size: {result.size_info}")
            print(f"  Message: {msg[:60]}...")
        else:
            print(f"[NOT DETECTED] {msg[:60]}...")
        print()


if __name__ == "__main__":
    test_parser()
