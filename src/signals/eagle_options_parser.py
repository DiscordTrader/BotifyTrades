"""
Eagle Options Chat Signal Parser
==================================
Parses option signals from the 🦅options-chat channel.

Two distinct trader styles supported:

MBA (mbatrades) — compact inline format:
  "AMZN 280C JUNE 18"         SYMBOL STRIKEC MONTH DAY
  "MSFT 800C JAN 15"          (LEAPS — short day = year rollover)
  "MARA 25C Jan 15 27"        SYMBOL STRIKEC MONTH DAY 2DIGIT-YEAR
  "NIO 7C Jan 15 2027"        SYMBOL STRIKEC MONTH DAY 4DIGIT-YEAR
  "$IMSR 15C JULY 17"         optional $ prefix
  "BYND $3 Jan 27"            no C/P → implied call

Nina (ninag_27842) — structured CALL/PUT keyword format:
  "$RGTI 22 CALL MAY 8"       $SYMBOL STRIKE CALL MONTH DAY
  "$GME 28 CALL MAY 8TH"      ordinal suffix stripped before parse
  "$POET 20 CALL JUNE 18TH    may have newline SWING tag
   Swing"
  "$SMR $20 CALL NOV 20TH"    $ on strike too

Exit (mbatrades):
  "Sold QCOM"                  plain text exit, symbol only
"""

import re
from typing import Optional, Dict, Any

from src.core.expiry import normalize_expiry_iso


_MONTH_PAT = (
    r'(?:JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?'
    r'|JUL(?:Y)?|AUG(?:UST)?|SEP(?:T(?:EMBER)?)?|OCT(?:OBER)?'
    r'|NOV(?:EMBER)?|DEC(?:EMBER)?)'
)

# SYMBOL STRIKEC/P MONTH DAY [2-4digit-year]
# e.g. "AMZN 280C JUNE 18", "MARA 25C Jan 15 27", "BYND $3 Jan 27"
EAGLE_MBA_ENTRY = re.compile(
    r'(?:^|\n)\$?([A-Z]{1,5})\s+\$?(\d+(?:\.\d+)?)(C|P)?\s+'
    r'(' + _MONTH_PAT + r'\s+\d{1,2}(?:ST|ND|RD|TH)?(?:\s+\d{2,4})?)',
    re.IGNORECASE | re.MULTILINE
)

# $SYMBOL STRIKE CALL/PUT MONTH DAY[ORDINAL] [year]
# e.g. "$RGTI 22 CALL MAY 8", "$POET 20 CALL JUNE 18TH"
EAGLE_NINA_ENTRY = re.compile(
    r'(?:^|\n)\$?([A-Z]{1,5})\s+\$?(\d+(?:\.\d+)?)\s+(CALL|PUT)\s+'
    r'(' + _MONTH_PAT + r'\s+\d{1,2}(?:ST|ND|RD|TH)?(?:\s+\d{2,4})?)',
    re.IGNORECASE | re.MULTILINE
)

# "Sold SYMBOL"
EAGLE_EXIT = re.compile(
    r'(?:^|\n)Sold\s+\$?([A-Z]{1,5})\b',
    re.IGNORECASE | re.MULTILINE
)

_COMMON_WORDS = {
    'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL',
    'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'GET',
    'HAS', 'HIM', 'HIS', 'HOW', 'ITS', 'MAY', 'NEW', 'NOW',
    'OLD', 'SEE', 'WAY', 'WHO', 'DID', 'LET', 'SAY', 'SHE',
    'TOO', 'USE', 'THAT', 'THIS', 'JUST', 'SOME', 'WILL',
    'BEEN', 'HAVE', 'MUCH', 'THEN', 'WITH', 'FROM',
    'CALL', 'PUT', 'BUY', 'SELL', 'STC', 'BTO',
}

_SWING_RE = re.compile(r'\b(?:swing|look\s+for\s+entry)\b', re.IGNORECASE)


def _parse_expiry(raw: str) -> str:
    # Strip ordinal suffixes so normalize_expiry_iso can parse "15TH" as 15
    cleaned = re.sub(r'(\d+)(?:ST|ND|RD|TH)\b', r'\1', raw, flags=re.IGNORECASE)
    return normalize_expiry_iso(cleaned)


def parse_eagle_mba_entry(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse MBA-style: SYMBOL STRIKEC MONTH DAY [YEAR]."""
    symbol = match.group(1).upper()
    if symbol in _COMMON_WORDS:
        return None

    strike_raw = match.group(2)
    opt_type_raw = match.group(3)
    expiry_raw = match.group(4)

    strike = float(strike_raw)
    opt_type = opt_type_raw.upper() if opt_type_raw else 'C'

    try:
        expiry = _parse_expiry(expiry_raw)
    except ValueError:
        return None

    is_swing = bool(_SWING_RE.search(text))

    return {
        'asset': 'option',
        'asset_type': 'option',
        'action': 'BTO',
        'qty': 1,
        'qty_specified': False,
        'symbol': symbol,
        'strike': strike,
        'opt_type': opt_type,
        'expiry': expiry,
        'price': None,
        'is_market_order': True,
        'confidence': 0.90,
        '_eagle_mba_entry': True,
        '_is_swing': is_swing,
        '_expiry_defaulted': False,
    }


def parse_eagle_nina_entry(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse Nina-style: $SYMBOL STRIKE CALL/PUT MONTH DAY[ORDINAL]."""
    symbol = match.group(1).upper()
    if symbol in _COMMON_WORDS:
        return None

    strike = float(match.group(2))
    opt_type = 'C' if match.group(3).upper() == 'CALL' else 'P'
    expiry_raw = match.group(4)

    try:
        expiry = _parse_expiry(expiry_raw)
    except ValueError:
        return None

    is_swing = bool(_SWING_RE.search(text))

    return {
        'asset': 'option',
        'asset_type': 'option',
        'action': 'BTO',
        'qty': 1,
        'qty_specified': False,
        'symbol': symbol,
        'strike': strike,
        'opt_type': opt_type,
        'expiry': expiry,
        'price': None,
        'is_market_order': True,
        'confidence': 0.95,
        '_eagle_nina_entry': True,
        '_is_swing': is_swing,
        '_expiry_defaulted': False,
    }


def parse_eagle_options_exit(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'Sold SYMBOL' exit."""
    symbol = match.group(1).upper()
    if symbol in _COMMON_WORDS:
        return None

    return {
        'asset': 'option',
        'asset_type': 'option',
        'action': 'STC',
        'qty': 1,
        'qty_specified': False,
        'symbol': symbol,
        'strike': None,
        'opt_type': None,
        'expiry': None,
        'price': None,
        'is_market_order': True,
        'is_full_exit': True,
        'confidence': 0.85,
        '_eagle_exit': True,
        '_expiry_defaulted': False,
    }
