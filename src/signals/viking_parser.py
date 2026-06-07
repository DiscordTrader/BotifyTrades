"""
Viking Plays signal parser.

Parses stock signals from the ⚔│viking-plays Discord channel (viking9496).
All entries route through conditional orders.

Entry formats (BUY):
  1. $SYMBOL PRICE @role          — "$MWC 6.68 @role"
  2. $SYMBOL loto PRICE @role     — "$Elpw loto .80 @role"
  3. $SYMBOL starter PRICE @role  — "$UK starter 2.90$ @role"
  4. $SYMBOL took [some/a starter] PRICE — "$FCHL took some 2.60 @role"
  5. $SYMBOL PRICE entry           — "$GLE .46$ entry"
  6. @role $SYMBOL PRICE           — "@role $Anpa 6.5$"
  7. $SYMBOL added/adding PRICE    — "$Hkit adding again .66-68"
  8. $SYMBOL joined [name] PRICE   — "$GIG joined beeples $6.75"

Exit formats (SELL):
  - "SYMBOL all out"
  - "sold/scaling most/all SYMBOL"

All entries are stock only (no options). Prices use both $1.50 and 1.50$ formats.
Two Discord roles mark signal type:
  - 1330929339134640179 = day trade
  - 1330915546513805463 = swing
"""

import re
from typing import Optional, Dict, Any

DISCORD_ROLE_RE = r'<@&\d+>'

# --- ENTRY patterns ---

# Pattern 1: $SYMBOL [loto/starter/took some/took a starter] PRICE [@role]
# Covers: "$MWC 6.68 @role", "$Elpw loto .80 @role", "$UK starter 2.90$ @role",
#         "$FCHL took some 2.60 @role", "$Mask took a starter 1.32$"
# Price must be realistic (<=500) to avoid matching "500k float" as price
VIKING_ENTRY_MAIN_RE = re.compile(
    r'\$([A-Za-z]{1,5})\s+'
    r'(?:(?:took\s+(?:some|a\s+starter)|loto|starter|added|adding(?:\s+(?:more|again|down))?|joined\s+\w+)\s+)?'
    r'\$?(\.?\d+(?:\.\d+)?)\$?'
    r'(?![kmKM\d])',
    re.IGNORECASE
)

# Pattern 2: @role $SYMBOL PRICE — role mention first
VIKING_ENTRY_ROLE_FIRST_RE = re.compile(
    r'<@&\d+>\s+(?:.*?\s+)?\$([A-Za-z]{1,5})\s+\$?(\.?\d+(?:\.\d+)?)\$?',
    re.IGNORECASE
)

# Pattern 3: $SYMBOL PRICE entry — explicit "entry" keyword
VIKING_ENTRY_EXPLICIT_RE = re.compile(
    r'\$([A-Za-z]{1,5})\s+\$?(\d+(?:\.\d+)?)\$?\s+entry',
    re.IGNORECASE
)

# --- EXIT patterns ---

# "SYMBOL all out" / "all out SYMBOL"
VIKING_EXIT_ALL_OUT_RE = re.compile(
    r'(?:'
    r'\$?([A-Za-z]{1,5})\s+all\s+out'
    r'|'
    r'all\s+out\s+\$?([A-Za-z]{1,5})'
    r')',
    re.IGNORECASE
)

# "sold most/all" / "scaling out"
VIKING_EXIT_SOLD_RE = re.compile(
    r'(?:sold|scaling)\s+(?:most|all|out)\s*\$?([A-Za-z]{1,5})?',
    re.IGNORECASE
)

# --- SL pattern ---
VIKING_SL_RE = re.compile(
    r'(?:s\.?l\.?|stop\s*loss)\s+(?:under\s+)?\$?(\.?\d+(?:\.\d+)?)\$?',
    re.IGNORECASE
)

# --- Commentary filters (NOT signals) ---
_COMMENTARY_PATTERNS = [
    re.compile(r'^\s*(?:boom|banger|nice|amazing|beautiful|stay green|easy|steady)', re.IGNORECASE),
    re.compile(r'^\s*(?:hit|nhod|key|\d+%|x\d+|round \d)', re.IGNORECASE),
    re.compile(r'^\s*(?:holding|will hold|heating|slow day|dont chase|not bad)', re.IGNORECASE),
    re.compile(r'parabolic|so far|potential|similar|went from|what a day', re.IGNORECASE),
    re.compile(r'^\s*\.\d+\$?\s*$'),  # bare price like ".80-1$"
    re.compile(r'^\s*\d+(?:\.\d+)?\$?\+?\s*(?:nhod|so far|locked|move)?\s*$', re.IGNORECASE),
]

_NON_TICKER_WORDS = {
    'THE', 'FOR', 'AND', 'BUT', 'NOT', 'HAS', 'WAS', 'ARE', 'CAN', 'MAY',
    'ALL', 'OUT', 'HIT', 'KEY', 'BIG', 'LOW', 'NEW', 'OIL', 'RUN', 'DAY',
    'AH', 'PM', 'AM', 'UP', 'ON', 'AT', 'IF', 'RS', 'PR', 'SL', 'PT',
    'CEO', 'CTB', 'IPO', 'ATH', 'HOD', 'LOD', 'WOW', 'OMG', 'EPS', 'FDA',
    'REST', 'NICE', 'BOOM', 'SOLD', 'TOOK', 'WILL', 'SOME', 'HOLD', 'FAST',
    'LOTO', 'STOP', 'LOSS', 'GAIN', 'MOVE', 'RISK', 'SWAP', 'LETS', 'ENTRY',
    'LIKE', 'MORE', 'MOST', 'BEEN', 'JUST', 'SAME', 'ALSO', 'WHAT', 'THAT',
    'THIS', 'WITH', 'FROM', 'THEM', 'WHEN', 'THEN', 'THAN', 'ONLY', 'VERY',
    'HONG', 'KONG', 'PENNY',
}


def _is_commentary(text: str) -> bool:
    for pat in _COMMENTARY_PATTERNS:
        if pat.search(text):
            return True
    return False


def _is_valid_ticker(sym: str) -> bool:
    return sym.upper() not in _NON_TICKER_WORDS and 1 <= len(sym) <= 5


def _extract_sl(text: str) -> Optional[float]:
    m = VIKING_SL_RE.search(text)
    if m:
        return float(m.group(1))
    return None


def _detect_trade_type(text: str) -> str:
    if re.search(r'<@&1330915546513805463>', text):
        return 'swing'
    if re.search(r'swing|overnight|short\s+term|next\s+week|hold', text, re.IGNORECASE):
        return 'swing'
    return 'day'


def parse_viking_entry(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse viking entry signal."""
    symbol = match.group(1).upper()
    price_str = match.group(2)
    price = float(price_str)

    if not _is_valid_ticker(symbol):
        return None
    if price <= 0 or price > 200:
        return None
    if _is_commentary(text):
        return None

    price_end = match.end(2)
    after_price = text[price_end:price_end+5].strip().lower()
    if after_price and after_price[0] in ('k', 'm', 'w', '%'):
        return None
    before_match = text[:match.start(2)].rstrip().lower()
    if before_match.endswith(('float', 'volume', 'vol', 'shares')):
        return None

    has_role = bool(re.search(DISCORD_ROLE_RE, text))
    has_entry_keyword = bool(re.search(
        r'\b(?:took|loto|starter|entry|added|adding|joined)\b', text, re.IGNORECASE
    ))
    if not has_role and not has_entry_keyword:
        return None

    sl = _extract_sl(text)
    trade_type = _detect_trade_type(text)

    result = {
        'asset': 'stock',
        'action': 'BTO',
        'symbol': symbol,
        'price': price,
        'qty': 1,
        'qty_specified': False,
        'is_market_order': False,
        'confidence': 0.85 if has_role else 0.75,
        '_conditional_order': True,
        'trigger_type': 'over',
        'trigger_price': price,
        '_viking_entry': True,
        '_viking_trade_type': trade_type,
    }

    if sl:
        result['stop_loss'] = sl
        result['stop_loss_type'] = 'fixed'
        result['stop_loss_value'] = sl
        result['stop_loss_fixed'] = sl

    return result


def parse_viking_entry_role_first(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse viking entry with role mention first: @role $SYMBOL PRICE."""
    symbol = match.group(1).upper()
    price = float(match.group(2))

    if not _is_valid_ticker(symbol):
        return None
    if price <= 0 or price > 200 or _is_commentary(text):
        return None
    price_end = match.end(2)
    after_price = text[price_end:price_end+5].strip().lower()
    if after_price and after_price[0] in ('k', 'm', 'w', '%'):
        return None

    sl = _extract_sl(text)
    trade_type = _detect_trade_type(text)

    return {
        'asset': 'stock',
        'action': 'BTO',
        'symbol': symbol,
        'price': price,
        'qty': 1,
        'qty_specified': False,
        'is_market_order': False,
        'confidence': 0.85,
        '_conditional_order': True,
        'trigger_type': 'over',
        'trigger_price': price,
        '_viking_entry': True,
        '_viking_trade_type': trade_type,
        'stop_loss': sl,
        'stop_loss_type': 'fixed' if sl else None,
        'stop_loss_value': sl,
        'stop_loss_fixed': sl,
    }


def parse_viking_exit(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse viking exit signal — 'SYMBOL all out' or 'all out SYMBOL'."""
    symbol = (match.group(1) or match.group(2) or '').upper()
    if not symbol or not _is_valid_ticker(symbol):
        return None

    return {
        'asset': 'stock',
        'action': 'STC',
        'symbol': symbol,
        'qty': 0,
        'is_full_exit': True,
        'is_market_order': True,
        'confidence': 0.9,
        '_viking_exit': True,
    }
