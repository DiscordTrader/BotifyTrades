"""
Foxtrades Natural Language Signal Parser
=========================================
Parses natural language trading signals from foxtradez channel.

Signal Formats:
- ENTRY: "Taking a position in $SYMBOL average $PRICE"
- EXIT: "All out of $SYMBOL with profits"
- TRIM: "Taking some profits on SYMBOL"

Note: Foxtrades primarily posts STOCK signals (not options).
"""

import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum


class FoxtradesSignalType(Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    TRIM = "TRIM"
    ADD = "ADD"  # Adding to existing position
    COMMENT = "COMMENT"


@dataclass
class FoxtradesSignal:
    """Parsed Foxtrades signal."""
    signal_type: FoxtradesSignalType
    action: str  # BTO or STC
    symbol: str
    price: Optional[float] = None
    is_partial: bool = False  # For trims
    is_add: bool = False  # Adding to position
    raw_text: str = ""
    confidence: float = 1.0


# Entry patterns - Taking a position / Adding
ENTRY_PATTERNS = [
    # "Taking a position in $NAMM average $2.38"
    (r"[Tt]aking\s+a\s+(?:small\s+)?position\s+in\s+\$?([A-Za-z]+).*?average\s+\$?([0-9.]+)", False),
    # "Adding more to IBRX" + "Average is now 6.65"
    (r"[Aa]dding\s+(?:more\s+)?(?:to\s+)?\$?([A-Za-z]+)", True),
    # "Buying SIDU average 2.30"
    (r"[Bb]uying\s+\$?([A-Za-z]+).*?average\s+\$?([0-9.]+)", False),
    # "Back in on ROLR average 18.59"
    (r"[Bb]ack\s+in\s+on\s+\$?([A-Za-z]+).*?average\s+\$?([0-9.]+)", False),
    # "Getting back in on ROLR" + "Added average $14.5"
    (r"[Gg]etting\s+back\s+in\s+on\s+\$?([A-Za-z]+)", True),
    # "Entering IRBT again average 4.5"
    (r"[Ee]ntering\s+\$?([A-Za-z]+)\s+again.*?average\s+\$?([0-9.]+)", False),
]

# Exit patterns - All out / Out of / Stopped out
EXIT_PATTERNS = [
    # "All out of $ROLR now with profits"
    r"[Aa]ll\s+out\s+of\s+\$?([A-Za-z]+)",
    # "Out of LAZR at a loss"
    r"[Oo]ut\s+of\s+\$?([A-Za-z]+)",
    # "Stopped out of IRBT long with a loss"
    r"[Ss]topped\s+out\s+of\s+\$?([A-Za-z]+)",
    # "I'm all out of IRBT with small profits"
    r"[Ii]'?m\s+all\s+out\s+of\s+\$?([A-Za-z]+)",
]

# Trim patterns - Taking profits / Securing profits
TRIM_PATTERNS = [
    # "Taking some profits on SIDU"
    r"[Tt]aking\s+(?:some\s+)?profits\s+on\s+\$?([A-Za-z]+)",
    # "Securing some profits on BEAT"
    r"[Ss]ecuring\s+(?:some\s+)?profits\s+on\s+\$?([A-Za-z]+)",
    # "Ive taken some profits" (no symbol - needs context)
    r"[Ii]'?ve?\s+taken\s+(?:some\s+)?profits",
    # "Securing some profits here" (no symbol)
    r"[Ss]ecuring\s+(?:some\s+)?profits\s+here",
    # "Taking profits on IRBT"
    r"[Tt]aking\s+profits\s+on\s+\$?([A-Za-z]+)",
]

# Average price pattern (for multi-line messages)
AVERAGE_PATTERN = r"[Aa]verage\s+(?:is\s+now\s+)?\$?([0-9.]+)"


def is_foxtrades_signal(text: str) -> bool:
    """Check if text matches Foxtrades signal patterns."""
    text_lower = text.lower()
    
    keywords = [
        'taking a position',
        'adding more',
        'adding to',
        'buying',
        'back in on',
        'getting back in',
        'entering',
        'all out of',
        'out of',
        'stopped out',
        'taking profits',
        'taking some profits',
        'securing profits',
        'securing some profits',
        'ive taken',
        "i've taken"
    ]
    
    return any(kw in text_lower for kw in keywords)


def parse_foxtrades_signal(text: str) -> Optional[FoxtradesSignal]:
    """
    Parse Foxtrades natural language signal.
    
    Args:
        text: Message content
        
    Returns:
        FoxtradesSignal if detected, None otherwise
    """
    if not is_foxtrades_signal(text):
        return None
    
    # Try entry patterns
    for pattern, is_add in ENTRY_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            symbol = groups[0].upper() if groups else None
            price = None
            
            # Extract price if in pattern
            if len(groups) > 1 and groups[1]:
                try:
                    price = float(groups[1])
                except ValueError:
                    pass
            
            # If no price in pattern, try to find it separately
            if price is None:
                avg_match = re.search(AVERAGE_PATTERN, text)
                if avg_match:
                    try:
                        price = float(avg_match.group(1))
                    except ValueError:
                        pass
            
            if symbol:
                return FoxtradesSignal(
                    signal_type=FoxtradesSignalType.ADD if is_add else FoxtradesSignalType.ENTRY,
                    action='BTO',
                    symbol=symbol,
                    price=price,
                    is_add=is_add,
                    raw_text=text,
                    confidence=1.0
                )
    
    # Try exit patterns
    for pattern in EXIT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            symbol = match.group(1).upper() if match.groups() else None
            if symbol:
                return FoxtradesSignal(
                    signal_type=FoxtradesSignalType.EXIT,
                    action='STC',
                    symbol=symbol,
                    is_partial=False,
                    raw_text=text,
                    confidence=1.0
                )
    
    # Try trim patterns
    for pattern in TRIM_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            symbol = groups[0].upper() if groups else None
            return FoxtradesSignal(
                signal_type=FoxtradesSignalType.TRIM,
                action='STC',
                symbol=symbol,  # May be None for generic "taking profits"
                is_partial=True,
                raw_text=text,
                confidence=0.9 if symbol else 0.7  # Lower confidence without symbol
            )
    
    return None


def convert_to_standard_signal(signal: FoxtradesSignal) -> Optional[Dict[str, Any]]:
    """
    Convert FoxtradesSignal to standard signal dict format.
    
    Args:
        signal: Parsed Foxtrades signal
        
    Returns:
        Standard signal dict compatible with bot execution
    """
    if not signal or not signal.symbol:
        return None
    
    return {
        'action': signal.action,
        'asset': 'stock',  # Foxtrades is primarily stocks
        'symbol': signal.symbol,
        'strike': None,
        'opt_type': None,
        'expiry': None,
        'price': signal.price,
        'qty': 1,
        'qty_specified': False,
        'is_market_order': signal.price is None,
        'confidence': signal.confidence,
        'is_trim': signal.is_partial,
        'is_add': signal.is_add,
        '_foxtrades_format': True,
        '_foxtrades_signal_type': signal.signal_type.value
    }


def format_as_bto_stc(signal: FoxtradesSignal) -> Optional[str]:
    """
    Format Foxtrades signal as standard BTO/STC for forwarding.
    
    Args:
        signal: Parsed Foxtrades signal
        
    Returns:
        Formatted signal string
    """
    if not signal or not signal.symbol:
        return None
    
    if signal.action == 'BTO':
        if signal.price:
            return f"BTO ${signal.symbol} @ {signal.price}"
        else:
            return f"BTO ${signal.symbol} @ m"
    else:  # STC
        if signal.is_partial:
            return f"TRIM ${signal.symbol}"
        else:
            return f"STC ${signal.symbol} @ m"
