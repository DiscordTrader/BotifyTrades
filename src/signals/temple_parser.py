"""
Temple of Boom Signal Parser
=============================
Parses signals from Temple of Boom Discord server.

Two channels:
- ⚡│zz (stocks): traderzz1m's stock signals with emoji markers and natural language
- 🚨│options-alerts💰 (options): Multiple analysts with distinct formats

Stock Signal Formats (traderzz1m):
- Emoji markers: ▶ = entry, ⛔ = stop/exit, 🎯 = target hit
- "In SYMBOL $PRICE" / "In SYMBOL avg PRICE"
- "Out SYMBOL" / "SL out SYMBOL" / "Cut SYMBOL"
- "Trim X%" / "Trim SYMBOL X%"
- Multi-line: entry + SL + PT across 2-3 messages

Options Signal Formats (by analyst):
- RF: "buy TICKER STRIKE+C at PRICE for EXPIRY"
- Standard (Legacy/Kizzy/Dre): "TICKER STRIKEc @.PRICE" or "TICKER STRIKE C PRICE"
- traderzz1m options: "SPY P 653 daily" / "SPY 580c 1.80"
- Toughshit: "QQQ 579 Puts-.75 C SL .65" (C=cost, not call)
"""

import re
from datetime import datetime
from typing import Optional, Dict, Any


def _default_expiry_today() -> str:
    """Return today's date as MM/DD for 0DTE fallback."""
    return datetime.now().strftime("%m/%d")


# =============================================================================
# STOCK PATTERNS (⚡│zz channel — traderzz1m)
# =============================================================================

# Emoji-led entries: "▶ SYMBOL $PRICE" or "▶ In SYMBOL $PRICE"
TEMPLE_ZZ_EMOJI_ENTRY = re.compile(
    r'▶\s*(?:In\s+)?\$?([A-Z]{1,5})\s+\$?(\d+(?:\.\d+)?)',
    re.IGNORECASE
)

# Emoji-led exits: "⛔ SYMBOL" or "⛔ Out SYMBOL"
TEMPLE_ZZ_EMOJI_EXIT = re.compile(
    r'⛔\s*(?:Out\s+|SL\s+out\s+|Cut\s+)?\$?([A-Z]{1,5})',
    re.IGNORECASE
)

# Emoji-led target: "🎯 SYMBOL" (trim/partial)
TEMPLE_ZZ_EMOJI_TARGET = re.compile(
    r'🎯\s*\$?([A-Z]{1,5})',
    re.IGNORECASE
)

# Natural language entry: "In SYMBOL $PRICE" / "In SYMBOL avg PRICE"
TEMPLE_ZZ_STOCK_ENTRY = re.compile(
    r'\b[Ii]n\s+\$?([A-Z]{1,5})\s+(?:\$|avg\s*\$?)(\d+(?:\.\d+)?)',
    re.IGNORECASE
)

# Natural language exit: "Out SYMBOL" / "SL out SYMBOL" / "Cut SYMBOL"
TEMPLE_ZZ_STOCK_EXIT = re.compile(
    r'\b(?:Out|SL\s+out|Cut)\s+\$?([A-Z]{1,5})\b',
    re.IGNORECASE
)

# Trim with percentage: "Trim 35%" / "Trim SYMBOL 50%"
TEMPLE_ZZ_TRIM_PCT = re.compile(
    r'\b[Tt]rim\s+(?:\$?([A-Z]{1,5})\s+)?(\d+(?:\.\d+)?)\s*%',
    re.IGNORECASE
)

# SL level: "SL $PRICE" or "SL PRICE" (metadata, not actionable alone)
TEMPLE_ZZ_SL_LEVEL = re.compile(
    r'\bSL\s+\$?(\d+(?:\.\d+)?)\b',
    re.IGNORECASE
)

# PT level: "PT $PRICE" or "PT PRICE" (metadata, not actionable alone)
TEMPLE_ZZ_PT_LEVEL = re.compile(
    r'\bPT\s+\$?(\d+(?:\.\d+)?)\b',
    re.IGNORECASE
)

# =============================================================================
# OPTIONS PATTERNS (🚨│options-alerts💰 channel)
# =============================================================================

# RF structured: "buy TICKER STRIKE+C at PRICE for EXPIRY"
# e.g. "buy QQQ 530+C at 2.50 for 5/16"
TEMPLE_RF_OPTIONS = re.compile(
    r'\bbuy\s+\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*\+\s*([CcPp])\s+at\s+\$?(\d+(?:\.\d+)?)\s+for\s+(\d{1,2}/\d{1,2}(?:/\d{2,4})?)',
    re.IGNORECASE
)

# Standard options: "TICKER STRIKEc @.PRICE" or "TICKER STRIKE C @PRICE"
# e.g. "TSLA 350c @.85" / "SPY 580 C 1.80" / "NVDA 135c @1.20"
TEMPLE_OPTIONS_STANDARD = re.compile(
    r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])\s+@\s*\$?(\.?\d+(?:\.\d+)?)',
    re.IGNORECASE
)

# traderzz1m options: "SPY P 653 daily" / "SPY 580c 1.80"
# Two sub-patterns: "TICKER C/P STRIKE [expiry]" or "TICKER STRIKEc/p PRICE"
TEMPLE_ZZ_OPTIONS_A = re.compile(
    r'\$?([A-Z]{1,5})\s+([CcPp])\s+(\d+(?:\.\d+)?)\s+(daily|weekly|\d{1,2}/\d{1,2}(?:/\d{2,4})?)',
    re.IGNORECASE
)
TEMPLE_ZZ_OPTIONS_B = re.compile(
    r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])\s+(\d+(?:\.\d+)?)(?!\s*/)',
    re.IGNORECASE
)

# Toughshit options: "QQQ 579 Puts-.75 C SL .65"
# C = cost/entry price, NOT call. "Puts" or "Calls" spelled out.
TEMPLE_TS_OPTIONS = re.compile(
    r'\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s+(Puts?|Calls?)\s*[-–]?\s*(\.?\d+(?:\.\d+)?)\s+C\b',
    re.IGNORECASE
)

# Options exit: "out TICKER STRIKEc" / "sold TICKER STRIKEc PRICE"
TEMPLE_OPTIONS_EXIT = re.compile(
    r'\b(?:out|sold|cut|SL\s+out)\s+\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])',
    re.IGNORECASE
)

# Options exit range: "0.58-2.86" or "sold for 0.58-2.86" (profit range)
TEMPLE_OPTIONS_EXIT_RANGE = re.compile(
    r'\b(?:sold\s+(?:for\s+)?)?(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\b'
)


# =============================================================================
# PARSER FUNCTIONS (for SignalFormatRegistry callbacks)
# =============================================================================

def parse_temple_zz_emoji_entry(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse ▶ SYMBOL $PRICE stock entry."""
    groups = match.groups()
    symbol = groups[0].upper() if groups else None
    price = float(groups[1]) if len(groups) > 1 and groups[1] else None

    if not symbol:
        return None

    sl = None
    pt = None
    sl_match = TEMPLE_ZZ_SL_LEVEL.search(text)
    if sl_match:
        sl = float(sl_match.group(1))
    pt_match = TEMPLE_ZZ_PT_LEVEL.search(text)
    if pt_match:
        pt = float(pt_match.group(1))

    result = {
        "asset": "stock",
        "action": "BTO",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": None,
        "opt_type": None,
        "expiry": None,
        "price": price,
        "is_market_order": price is None,
        "confidence": 1.0,
        "_temple_entry": True,
    }
    if sl is not None:
        result["stop_loss"] = sl
    if pt is not None:
        result["take_profit"] = pt
    return result


def parse_temple_zz_emoji_exit(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse ⛔ SYMBOL stock exit."""
    symbol = match.group(1).upper() if match.groups() else None
    if not symbol:
        return None

    return {
        "asset": "stock",
        "action": "STC",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": None,
        "opt_type": None,
        "expiry": None,
        "price": None,
        "is_market_order": True,
        "is_full_exit": True,
        "confidence": 1.0,
        "_temple_exit": True,
    }


def parse_temple_zz_emoji_target(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 🎯 SYMBOL target hit (trim)."""
    symbol = match.group(1).upper() if match.groups() else None
    if not symbol:
        return None

    return {
        "asset": "stock",
        "action": "STC",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": None,
        "opt_type": None,
        "expiry": None,
        "price": None,
        "is_market_order": True,
        "is_trim": True,
        "is_full_exit": False,
        "confidence": 0.9,
        "_temple_trim": True,
    }


def parse_temple_zz_stock_entry(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'In SYMBOL $PRICE' stock entry."""
    groups = match.groups()
    symbol = groups[0].upper() if groups else None
    price = float(groups[1]) if len(groups) > 1 and groups[1] else None

    if not symbol:
        return None

    _COMMON_WORDS = {
        'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL',
        'CAN', 'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY', 'GET',
        'HAS', 'HIM', 'HIS', 'HOW', 'ITS', 'MAY', 'NEW', 'NOW',
        'OLD', 'SEE', 'WAY', 'WHO', 'DID', 'LET', 'SAY', 'SHE',
        'TOO', 'USE', 'THAT', 'THIS', 'JUST', 'SOME', 'WILL',
        'BEEN', 'HAVE', 'MUCH', 'THEN', 'WITH', 'FROM',
    }
    if symbol in _COMMON_WORDS:
        return None

    sl = None
    pt = None
    sl_match = TEMPLE_ZZ_SL_LEVEL.search(text)
    if sl_match:
        sl = float(sl_match.group(1))
    pt_match = TEMPLE_ZZ_PT_LEVEL.search(text)
    if pt_match:
        pt = float(pt_match.group(1))

    result = {
        "asset": "stock",
        "action": "BTO",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": None,
        "opt_type": None,
        "expiry": None,
        "price": price,
        "is_market_order": price is None,
        "confidence": 1.0,
        "_temple_entry": True,
    }
    if sl is not None:
        result["stop_loss"] = sl
    if pt is not None:
        result["take_profit"] = pt
    return result


_COMMON_EXIT_WORDS = {
    'HERE', 'MORE', 'SOME', 'THIS', 'THAT', 'JUST', 'BACK',
    'THE', 'AND', 'FOR', 'WITH', 'FROM', 'WILL', 'BEEN', 'HAVE',
    'ALL', 'NOW', 'STILL', 'ALSO', 'LOSSES', 'EARLY',
}


def parse_temple_zz_stock_exit(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'Out SYMBOL' / 'SL out SYMBOL' / 'Cut SYMBOL'."""
    symbol = match.group(1).upper() if match.groups() else None
    if not symbol:
        return None

    if symbol in _COMMON_EXIT_WORDS:
        return None

    return {
        "asset": "stock",
        "action": "STC",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": None,
        "opt_type": None,
        "expiry": None,
        "price": None,
        "is_market_order": True,
        "is_full_exit": True,
        "confidence": 1.0,
        "_temple_exit": True,
    }


def parse_temple_zz_trim(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'Trim 35%' / 'Trim SYMBOL 50%'."""
    groups = match.groups()
    symbol = groups[0].upper() if groups[0] else None
    trim_pct = float(groups[1]) if groups[1] else None

    result = {
        "asset": "stock",
        "action": "STC",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": None,
        "opt_type": None,
        "expiry": None,
        "price": None,
        "is_market_order": True,
        "is_trim": True,
        "is_full_exit": False,
        "confidence": 0.9 if symbol else 0.7,
        "_temple_trim": True,
    }
    if trim_pct is not None:
        result["trim_percentage"] = trim_pct
    return result


def parse_temple_rf_options(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse RF's 'buy QQQ 530+C at 2.50 for 5/16'."""
    groups = match.groups()
    symbol = groups[0].upper()
    strike = float(groups[1])
    opt_type = groups[2].upper()
    price = float(groups[3])
    expiry = groups[4]

    return {
        "asset": "option",
        "action": "BTO",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": strike,
        "opt_type": opt_type,
        "expiry": expiry,
        "price": price,
        "is_market_order": False,
        "confidence": 1.0,
        "_temple_rf_entry": True,
    }


def parse_temple_options_standard(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'TSLA 350c @.85' / 'SPY 580 C 1.80'."""
    groups = match.groups()
    symbol = groups[0].upper()
    strike = float(groups[1])
    opt_type = groups[2].upper()
    price = float(groups[3])

    return {
        "asset": "option",
        "action": "BTO",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": strike,
        "opt_type": opt_type,
        "expiry": _default_expiry_today(),
        "price": price,
        "is_market_order": False,
        "confidence": 0.95,
        "_temple_options_entry": True,
        "_expiry_defaulted": True,
    }


def parse_temple_zz_options_a(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'SPY P 653 daily' — TICKER C/P STRIKE expiry."""
    groups = match.groups()
    symbol = groups[0].upper()
    opt_type = groups[1].upper()
    strike = float(groups[2])
    expiry_raw = groups[3].lower()

    if expiry_raw in ('daily', 'weekly'):
        expiry = _default_expiry_today()
        expiry_defaulted = True
    else:
        expiry = groups[3]
        expiry_defaulted = False

    return {
        "asset": "option",
        "action": "BTO",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": strike,
        "opt_type": opt_type,
        "expiry": expiry,
        "price": None,
        "is_market_order": True,
        "confidence": 0.95,
        "_temple_zz_options_entry": True,
        "_expiry_hint": expiry_raw,
        "_expiry_defaulted": expiry_defaulted,
    }


def parse_temple_zz_options_b(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'SPY 580c 1.80' — TICKER STRIKEc/p PRICE."""
    text_upper = text.strip().upper()
    if text_upper.startswith(('BTO ', 'STC ', 'BUY ', 'SELL ')):
        return None

    groups = match.groups()
    symbol = groups[0].upper()
    strike = float(groups[1])
    opt_type = groups[2].upper()
    price = float(groups[3])

    return {
        "asset": "option",
        "action": "BTO",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": strike,
        "opt_type": opt_type,
        "expiry": _default_expiry_today(),
        "price": price,
        "is_market_order": False,
        "confidence": 0.95,
        "_temple_zz_options_entry": True,
        "_expiry_defaulted": True,
    }


def parse_temple_ts_options(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse Toughshit's 'QQQ 579 Puts-.75 C SL .65' (C=cost, not call)."""
    groups = match.groups()
    symbol = groups[0].upper()
    strike = float(groups[1])
    opt_word = groups[2].lower()
    cost = float(groups[3])

    opt_type = 'P' if opt_word.startswith('put') else 'C'

    sl = None
    sl_match = re.search(r'SL\s+(\.?\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if sl_match:
        sl = float(sl_match.group(1))

    result = {
        "asset": "option",
        "action": "BTO",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": strike,
        "opt_type": opt_type,
        "expiry": _default_expiry_today(),
        "price": cost,
        "is_market_order": False,
        "confidence": 0.95,
        "_temple_ts_entry": True,
        "_expiry_defaulted": True,
    }
    if sl is not None:
        result["stop_loss"] = sl
    return result


def parse_temple_options_exit(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'out TICKER STRIKEc' / 'sold TICKER STRIKEc PRICE'."""
    groups = match.groups()
    symbol = groups[0].upper()
    strike = float(groups[1])
    opt_type = groups[2].upper()

    return {
        "asset": "option",
        "action": "STC",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": strike,
        "opt_type": opt_type,
        "expiry": _default_expiry_today(),
        "price": None,
        "is_market_order": True,
        "is_full_exit": True,
        "confidence": 1.0,
        "_temple_options_exit": True,
        "_expiry_defaulted": True,
    }
