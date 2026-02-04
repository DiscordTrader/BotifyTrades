"""
Sir Goldman Signal Parser
=========================
Parses Sir Goldman format trading signals from Discord embed-based messages.

Format:
- Messages have embed.title = ENTRY, EXIT, TRIM, or COMMENT
- Content is in embed.description wrapped in **...**

Examples:
  ENTRY: **$SPX 6860p @ 2.6**
  TRIM:  **$SPX 4.1! +58%**
  EXIT:  **Out rest here at BE**
  COMMENT: **Watching puts off 5m 9ema** (skipped)

Note: Sir Goldman signals typically don't include expiry dates.
For "lotto" plays, these are assumed to be 0DTE (same-day expiry).
"""

import re
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from enum import Enum
from datetime import datetime


class SirGoldmanSignalType(Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    TRIM = "TRIM"
    COMMENT = "COMMENT"
    UNKNOWN = "UNKNOWN"


def get_today_expiry() -> str:
    """Get today's date in MM/DD format for 0DTE options."""
    return datetime.now().strftime('%m/%d')


@dataclass
class SirGoldmanSignal:
    """Parsed Sir Goldman signal."""
    signal_type: SirGoldmanSignalType
    action: Optional[str] = None
    symbol: Optional[str] = None
    strike: Optional[str] = None
    option_type: Optional[str] = None
    expiry: Optional[str] = None
    price: Optional[float] = None
    is_market_exit: bool = False
    is_breakeven: bool = False
    loss_pct: Optional[float] = None
    gain_pct: Optional[float] = None
    raw_description: str = ""
    is_futures: bool = False
    is_ambiguous: bool = False


ENTRY_PATTERN = re.compile(
    r'\$?([A-Z]{2,5})\s+(\d+(?:\.\d+)?)\s*([cpCP])\s*@\s*(\d*\.?\d+)',
    re.IGNORECASE
)

TRIM_PATTERN = re.compile(
    r'\$([A-Z]{2,5})\s+(\d*\.?\d+)!?\s*(?:\+(\d+(?:\.\d+)?)%)?',
    re.IGNORECASE
)

EXIT_PRICE_PATTERN = re.compile(
    r'(?:at|@|here)\s*(\d+\.?\d*)',
    re.IGNORECASE
)

EXIT_TRIM_STYLE_PATTERN = re.compile(
    r'\$([A-Z]{2,5})\s+(\d*\.?\d+)!?\s*(?:\+(\d+(?:\.\d+)?)%)?',
    re.IGNORECASE
)

BE_PATTERN = re.compile(r'\bBE\b', re.IGNORECASE)

LOSS_PATTERN = re.compile(r'-(\d+(?:\.\d+)?)%', re.IGNORECASE)

FUTURES_KEYWORDS = ['NQ', 'SMS', 'ES', 'MNQ', 'MES', 'RTY', 'YM', 'GC', 'CL', 'SI', 'ZB', 'ZN']

NON_TICKER_WORDS = {'OFF', 'FREE', 'ASFF', 'HERE', 'NICE', 'BANG', 'LETS', 'THAT', 'WILL', 'DONE', 'BACK', 'JUST', 'MORE'}

AMBIGUOUS_PATTERNS = [
    re.compile(r'^Adding\s+here', re.IGNORECASE),
    re.compile(r'^In\s+at', re.IGNORECASE),
    re.compile(r'Straddle', re.IGNORECASE),
    re.compile(r'Stop\s+(?:buys?|sells?)', re.IGNORECASE),
]


def is_sir_goldman_message(embeds: List[Dict[str, Any]]) -> bool:
    """
    Check if a message is a Sir Goldman formatted signal.
    
    Args:
        embeds: List of embed dicts from Discord message
        
    Returns:
        True if message matches Sir Goldman embed format
    """
    if not embeds or len(embeds) == 0:
        return False
    
    embed = embeds[0]
    title = embed.get('title', '').upper().strip()
    description = embed.get('description', '')
    
    if title in ['ENTRY', 'EXIT', 'TRIM', 'COMMENT']:
        if description.startswith('**') and description.endswith('**'):
            return True
        if description.strip():
            return True
    
    return False


def parse_sir_goldman_signal(embeds: List[Dict[str, Any]]) -> Optional[SirGoldmanSignal]:
    """
    Parse a Sir Goldman signal from Discord embeds.
    
    Args:
        embeds: List of embed dicts from Discord message
        
    Returns:
        SirGoldmanSignal if parseable, None otherwise
    """
    if not is_sir_goldman_message(embeds):
        return None
    
    embed = embeds[0]
    title = embed.get('title', '').upper().strip()
    description = embed.get('description', '').strip()
    
    description = description.strip('*').strip()
    
    signal = SirGoldmanSignal(
        signal_type=SirGoldmanSignalType(title) if title in ['ENTRY', 'EXIT', 'TRIM', 'COMMENT'] else SirGoldmanSignalType.UNKNOWN,
        raw_description=description
    )
    
    if signal.signal_type == SirGoldmanSignalType.COMMENT:
        return None
    
    if signal.signal_type == SirGoldmanSignalType.ENTRY:
        return _parse_entry(signal, description)
    
    elif signal.signal_type == SirGoldmanSignalType.TRIM:
        return _parse_trim(signal, description)
    
    elif signal.signal_type == SirGoldmanSignalType.EXIT:
        return _parse_exit(signal, description)
    
    return None


def _parse_entry(signal: SirGoldmanSignal, description: str) -> Optional[SirGoldmanSignal]:
    """Parse an ENTRY signal.
    
    Note: Sir Goldman signals don't include expiry dates. For "lotto" plays,
    these are assumed to be 0DTE (same-day expiry).
    """
    for pattern in AMBIGUOUS_PATTERNS:
        if pattern.search(description):
            signal.is_ambiguous = True
            return None
    
    for kw in FUTURES_KEYWORDS:
        if re.search(rf'\b{kw}\b', description, re.IGNORECASE):
            if not re.search(r'\$[A-Z]{2,5}', description):
                signal.is_futures = True
                return None
    
    match = ENTRY_PATTERN.search(description)
    if match:
        signal.action = 'BTO'
        signal.symbol = match.group(1).upper()
        signal.strike = match.group(2)
        signal.option_type = match.group(3).upper()
        signal.expiry = get_today_expiry()
        signal.price = float(match.group(4))
        return signal
    
    return None


def _parse_trim(signal: SirGoldmanSignal, description: str) -> Optional[SirGoldmanSignal]:
    """Parse a TRIM signal (partial exit).
    
    Valid TRIM formats:
    - $SPX 3.2! +31%  (symbol with $ prefix)
    - $SPY 4.1! +58%
    
    Invalid (rejected):
    - Taking another off 3.5 (no $ prefix, 'off' is not a ticker)
    - FREE ASFF 3.3! (no $ prefix, non-ticker words)
    """
    match = TRIM_PATTERN.search(description)
    if match:
        symbol = match.group(1).upper()
        if symbol in NON_TICKER_WORDS:
            return None
        signal.action = 'STC'
        signal.symbol = symbol
        signal.price = float(match.group(2))
        if match.group(3):
            signal.gain_pct = float(match.group(3))
        return signal
    
    return None


def _parse_exit(signal: SirGoldmanSignal, description: str) -> Optional[SirGoldmanSignal]:
    """Parse an EXIT signal (full exit).
    
    Handles multiple EXIT formats:
    - Out rest here at BE (breakeven)
    - Out here at 1.2 -25% (price with loss)
    - $SPY 3.78! +385% (TRIM-style in EXIT)
    - SL Be hit! +53% (stop loss hit)
    """
    signal.action = 'STC'
    
    if BE_PATTERN.search(description):
        signal.is_breakeven = True
    
    loss_match = LOSS_PATTERN.search(description)
    if loss_match:
        signal.loss_pct = float(loss_match.group(1))
    
    trim_style_match = EXIT_TRIM_STYLE_PATTERN.search(description)
    if trim_style_match:
        symbol = trim_style_match.group(1).upper()
        if symbol not in NON_TICKER_WORDS:
            signal.symbol = symbol
            signal.price = float(trim_style_match.group(2))
            if trim_style_match.group(3):
                signal.gain_pct = float(trim_style_match.group(3))
            return signal
    
    price_match = EXIT_PRICE_PATTERN.search(description)
    if price_match:
        price_str = price_match.group(1)
        if price_str and price_str != '':
            try:
                signal.price = float(price_str)
            except ValueError:
                pass
    
    if signal.price is None and not signal.is_breakeven:
        signal.is_market_exit = True
    
    return signal


def format_bto_signal(signal: SirGoldmanSignal, quantity: int = 1) -> str:
    """
    Format a Sir Goldman ENTRY as a standard BTO signal.
    
    Args:
        signal: Parsed SirGoldmanSignal
        quantity: Number of contracts
        
    Returns:
        Formatted BTO string like "BTO SPX 6860P @ 2.6"
    """
    if not signal or signal.action != 'BTO':
        return ""
    
    return f"BTO {signal.symbol} {signal.strike}{signal.option_type} @ {signal.price}"


def format_stc_signal(
    signal: SirGoldmanSignal, 
    symbol: Optional[str] = None,
    strike: Optional[str] = None,
    option_type: Optional[str] = None,
    is_trim: bool = False
) -> str:
    """
    Format a Sir Goldman EXIT/TRIM as a standard STC signal.
    
    Args:
        signal: Parsed SirGoldmanSignal
        symbol: Override symbol (for matching to open position)
        strike: Override strike
        option_type: Override option type
        is_trim: Whether this is a partial exit (TRIM)
        
    Returns:
        Formatted STC string like "STC SPX 6860P @ 4.1"
    """
    if not signal or signal.action != 'STC':
        return ""
    
    sym = symbol or signal.symbol or "???"
    stk = strike or signal.strike or ""
    opt = option_type or signal.option_type or ""
    
    if stk and opt:
        contract = f"{sym} {stk}{opt}"
    else:
        contract = sym
    
    if signal.price:
        price_str = f"@ {signal.price}"
    elif signal.is_breakeven:
        price_str = "@ BE"
    else:
        price_str = "@ m"
    
    suffix = " (trim)" if is_trim else ""
    
    return f"STC {contract} {price_str}{suffix}"


def format_forwarding_message(signal: SirGoldmanSignal, quantity: int = 1, 
                               open_position: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Format a Sir Goldman signal for webhook forwarding.
    
    Args:
        signal: Parsed SirGoldmanSignal
        quantity: Contract quantity
        open_position: Optional dict with current open position info (symbol, strike, option_type)
        
    Returns:
        Formatted message with @everyone and disclaimer, or None if not forwardable
    """
    if not signal:
        return None
    
    if signal.action == 'BTO':
        signal_text = format_bto_signal(signal, quantity)
    elif signal.action == 'STC':
        is_trim = signal.signal_type == SirGoldmanSignalType.TRIM
        if open_position:
            signal_text = format_stc_signal(
                signal,
                symbol=open_position.get('symbol'),
                strike=open_position.get('strike'),
                option_type=open_position.get('option_type'),
                is_trim=is_trim
            )
        else:
            signal_text = format_stc_signal(signal, is_trim=is_trim)
    else:
        return None
    
    if not signal_text:
        return None
    
    return f"@everyone\n{signal_text}\n*Not financial advice, for educational purposes only.*"


def convert_to_standard_signal(signal: SirGoldmanSignal, open_position: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Convert a Sir Goldman signal to standard signal dict format for bot execution.
    
    Args:
        signal: Parsed SirGoldmanSignal
        open_position: Optional open position for STC signals (must include expiry)
        
    Returns:
        Standard signal dict compatible with existing bot parsers
    """
    if not signal or not signal.action:
        return None
    
    result: Dict[str, Any] = {
        'action': signal.action,
        'asset_type': 'option',
        'source': 'sir_goldman',
    }
    
    if signal.action == 'BTO':
        result.update({
            'symbol': signal.symbol,
            'strike': signal.strike,
            'option_type': 'CALL' if signal.option_type == 'C' else 'PUT',
            'expiry': signal.expiry,
            'price': signal.price,
            'order_type': 'limit',
        })
    elif signal.action == 'STC':
        if open_position:
            result.update({
                'symbol': open_position.get('symbol', signal.symbol),
                'strike': open_position.get('strike', signal.strike),
                'option_type': open_position.get('option_type', 'CALL' if signal.option_type == 'C' else 'PUT'),
                'expiry': open_position.get('expiry', signal.expiry),
            })
        else:
            result.update({
                'symbol': signal.symbol,
                'strike': signal.strike,
                'option_type': 'CALL' if signal.option_type == 'C' else 'PUT',
                'expiry': signal.expiry,
            })
        
        if signal.price:
            result['price'] = signal.price
            result['order_type'] = 'limit'
        else:
            result['order_type'] = 'market'
        
        result['is_trim'] = signal.signal_type == SirGoldmanSignalType.TRIM
    
    return result
