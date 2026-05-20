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
# TRADING-FLOOR PATTERNS (🔥│trading-floor — traderzz1m conversational style)
# =============================================================================

# Conditional breakout: "SYMBOL break PRICE for TARGET" / "SYMBOL PRICE break takes it to TARGET"
# Requires SYMBOL at start of line or after $, excludes common words
TEMPLE_ZZ_BREAKOUT = re.compile(
    r'(?:^|\n)\s*\$?([A-Z]{2,5})\s+(?:(\d+(?:\.\d+)?)\s+)?(?:only\s+if\s+(?:it\s+)?)?break(?:s)?\s*(?:of\s+)?(?:(\d+(?:\.\d+)?)\s+)?(?:for\s+|takes?\s+(?:it\s+)?to\s+)\$?(\d+(?:\.\d+)?)',
    re.IGNORECASE
)

# Reverse breakout: "PRICE break for TARGET SYMBOL" (price-first, symbol at end)
TEMPLE_ZZ_BREAKOUT_REVERSE = re.compile(
    r'(?:^|\n)\s*\$?(\d+(?:\.\d+)?)\s+(?:has\s+to\s+|must\s+)?break(?:s)?\s+(?:only\s+)?(?:for\s+|takes?\s+(?:it\s+)?to\s+)\$?(\d+(?:\.\d+)?)\s+\$?([A-Z]{2,5})\b',
    re.IGNORECASE
)

# Ticker + price + "now": "$EZGO 3.28 now"
TEMPLE_ZZ_TICKER_PRICE_NOW = re.compile(
    r'^\$?([A-Z]{2,5})\s+(\d+(?:\.\d+)?)\s+now$',
    re.IGNORECASE
)

# Range entry: "SYMBOL LOW-HIGH" (with optional flame emoji and trailing text)
TEMPLE_ZZ_RANGE_ENTRY = re.compile(
    r'^\$?([A-Z]{2,5})\s+(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(?:<[^>]*>|[^\x00-\x7F]|[.,;!\s])*(?:\S.*)?$',
    re.IGNORECASE
)

# SL update: "PRICE should be your new SYMBOL SL" / "Move your SL up to PRICE"
TEMPLE_ZZ_SL_UPDATE_NEW = re.compile(
    r'(\d+(?:\.\d+)?)\s+should\s+be\s+your\s+(?:new\s+)?\$?([A-Z]{2,5})\s+SL',
    re.IGNORECASE
)
TEMPLE_ZZ_SL_UPDATE_MOVE = re.compile(
    r'[Mm]ove\s+your\s+(?:mental\s+)?(?:stop\s+loss|SL)\s+(?:up\s+)?(?:for\s+\$?([A-Z]{2,5})\s+)?to\s+\$?(\d+(?:\.\d+)?)',
    re.IGNORECASE
)

# =============================================================================
# ZZ STRUCTURED EMOJI PATTERNS (✅/❌/🎯 format — author "ZZ")
# =============================================================================

# Role mention IDs → trade type tags
ZZ_ROLE_MOMENTUM = '1330929339134640179'
ZZ_ROLE_SWING = '1330915546513805463'

# Structured entry: "$TICKER <@&role>\n✅ PRICE\n❌ PRICE (optional)\n🎯 T1...T2...T3"
TEMPLE_ZZ_STRUCTURED_ENTRY = re.compile(
    r'^\$?([A-Z]{1,5})[ \t]*(?:<@&\d+>[ \t]*(?:/\w+)?[ \t]*)*\n'
    r'✅[ \t]*(?:around[ \t]+|break[ \t]+(?:of[ \t]+)?)?(?:\$[ \t]*)?(\d+(?:\.\d+)?)[ \t]*(?:-[ \t]*(\d+(?:\.\d+)?))?[^\n]*\n'
    r'(?:(?:❌|➕)[ \t]*(\d+(?:\.\d+)?)[ \t]*\n)?'
    r'🎯[ \t]*([\d.,\s%+\-]+(?:\.{2,3}[\d.,\s%+\-]+)*)',
    re.IGNORECASE
)

# Inline entry with role: "SYMBOL in at PRICE <@&role>" or "$SYMBOL <@&role> PRICE"
TEMPLE_ZZ_INLINE_ROLE_ENTRY_A = re.compile(
    r'^\$?([A-Z]{1,5})\s+(?:in\s+(?:small\s+)?(?:at\s+)?)?\$?(\d+(?:\.\d+)?)\s*(?:!?\s*)?<@&(\d+)>',
    re.IGNORECASE
)
TEMPLE_ZZ_INLINE_ROLE_ENTRY_B = re.compile(
    r'^\$?([A-Z]{1,5})\s*<@&(\d+)>\s*(?:/\w+\s*)?\$?(\d+(?:\.\d+)?)',
    re.IGNORECASE
)

# Swing update with targets/SL: "$TICKER <@&swing>\ntext 🎯 T1-T2 ❌ below PRICE"
TEMPLE_ZZ_SWING_UPDATE = re.compile(
    r'\$?([A-Z]{1,5})\s*<@&(\d+)>.*?🎯\s*([\d.]+(?:\s*[-–]\s*[\d.]+)*)\s*❌\s*(?:below\s+)?\$?(\d+(?:\.\d+)?)',
    re.IGNORECASE | re.DOTALL
)

# Standalone targets: "🎯 T1...T2...T3" (no ticker — links to prior ZZ message)
TEMPLE_ZZ_STANDALONE_TARGETS = re.compile(
    r'^🎯\s*([\d.]+(?:\s*\.{2,3}\s*[\d.]+)+)\s*$',
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


def parse_temple_zz_breakout(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'SYMBOL break PRICE for TARGET' conditional entry."""
    groups = match.groups()
    symbol = groups[0].upper() if groups else None
    pre_break_price = float(groups[1]) if len(groups) > 1 and groups[1] else None
    post_break_price = float(groups[2]) if len(groups) > 2 and groups[2] else None
    target_price = float(groups[3]) if len(groups) > 3 and groups[3] else None
    trigger_price = post_break_price or pre_break_price

    if not symbol or not trigger_price:
        return None

    _REJECT_WORDS = {'OR', 'IF', 'IT', 'THE', 'AND', 'BUT', 'FOR', 'CAN', 'HAS', 'HIS',
                     'HER', 'NOT', 'YOU', 'ALL', 'ARE', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY',
                     'GET', 'HOW', 'ITS', 'MAY', 'NEW', 'NOW', 'OLD', 'SEE', 'WAY', 'WHO'}
    if symbol in _REJECT_WORDS:
        return None

    result = {
        'format': 'TEMPLE_ZZ_BREAKOUT',
        'is_conditional': True,
        '_conditional_order': True,
        '_temple_entry': True,
        'asset': 'stock',
        'asset_type': 'stock',
        'action': 'BTO',
        'ticker': symbol,
        'symbol': symbol,
        'trigger_type': 'over',
        'trigger_price': trigger_price,
        'entry_high': trigger_price,
        'entry_low': None,
        'stop_loss_type': None,
        'stop_loss_value': None,
        'stop_loss_fixed': None,
        'stop_loss_pct': None,
        'profit_targets': [target_price] if target_price else [],
        'target_ranges': [],
        'position_size_pct': None,
        'fixed_qty': None,
        'size_mode': None,
        'qty': 1,
        'qty_specified': False,
        'confidence': 0.95,
    }

    additional_targets = re.findall(r'\.{2,}\s*(\d+(?:\.\d+)?)', text)
    for t in additional_targets:
        tv = float(t)
        if tv not in result['profit_targets']:
            result['profit_targets'].append(tv)

    sl_match = TEMPLE_ZZ_SL_LEVEL.search(text)
    if sl_match:
        result['stop_loss_type'] = 'fixed'
        result['stop_loss_value'] = float(sl_match.group(1))
        result['stop_loss_fixed'] = result['stop_loss_value']

    return result


def parse_temple_zz_breakout_reverse(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'PRICE break for TARGET SYMBOL' — price-first, symbol at end."""
    groups = match.groups()
    trigger_price = float(groups[0]) if groups and groups[0] else None
    target_price = float(groups[1]) if len(groups) > 1 and groups[1] else None
    symbol = groups[2].upper() if len(groups) > 2 and groups[2] else None

    if not symbol or not trigger_price:
        return None

    _REJECT_WORDS = {'OR', 'IF', 'IT', 'THE', 'AND', 'BUT', 'FOR', 'CAN', 'HAS', 'HIS',
                     'HER', 'NOT', 'YOU', 'ALL', 'ARE', 'WAS', 'ONE', 'OUR', 'OUT', 'DAY',
                     'GET', 'HOW', 'ITS', 'MAY', 'NEW', 'NOW', 'OLD', 'SEE', 'WAY', 'WHO'}
    if symbol in _REJECT_WORDS:
        return None

    result = {
        'format': 'TEMPLE_ZZ_BREAKOUT_REVERSE',
        'is_conditional': True,
        '_conditional_order': True,
        '_temple_entry': True,
        'asset': 'stock',
        'asset_type': 'stock',
        'action': 'BTO',
        'ticker': symbol,
        'symbol': symbol,
        'trigger_type': 'over',
        'trigger_price': trigger_price,
        'entry_high': trigger_price,
        'entry_low': None,
        'stop_loss_type': None,
        'stop_loss_value': None,
        'stop_loss_fixed': None,
        'stop_loss_pct': None,
        'profit_targets': [target_price] if target_price else [],
        'target_ranges': [],
        'position_size_pct': None,
        'fixed_qty': None,
        'size_mode': None,
        'qty': 1,
        'qty_specified': False,
        'confidence': 0.90,
    }

    sl_match = TEMPLE_ZZ_SL_LEVEL.search(text)
    if sl_match:
        result['stop_loss_type'] = 'fixed'
        result['stop_loss_value'] = float(sl_match.group(1))
        result['stop_loss_fixed'] = result['stop_loss_value']

    return result


def parse_temple_zz_ticker_price_now(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse '$EZGO 3.28 now' — immediate entry."""
    groups = match.groups()
    symbol = groups[0].upper() if groups else None
    price = float(groups[1]) if len(groups) > 1 and groups[1] else None

    if not symbol or not price:
        return None

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
        "is_market_order": False,
        "confidence": 0.95,
        "_temple_entry": True,
    }
    sl_match = TEMPLE_ZZ_SL_LEVEL.search(text)
    if sl_match:
        result["stop_loss"] = float(sl_match.group(1))
    return result


def parse_temple_zz_range_entry(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'CRE 2.80-3.91' — range entry (low=entry, high=PT)."""
    groups = match.groups()
    symbol = groups[0].upper() if groups else None
    low = float(groups[1]) if len(groups) > 1 and groups[1] else None
    high = float(groups[2]) if len(groups) > 2 and groups[2] else None

    if not symbol or not low or not high:
        return None
    if low >= high:
        return None

    result = {
        "asset": "stock",
        "action": "BTO",
        "qty": 1,
        "qty_specified": False,
        "symbol": symbol,
        "strike": None,
        "opt_type": None,
        "expiry": None,
        "price": low,
        "is_market_order": False,
        "confidence": 0.85,
        "take_profit": high,
        "profit_targets": [high],
        "profit_target_price": high,
        "_temple_entry": True,
    }
    return result


def parse_temple_zz_sl_update_new(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'PRICE should be your new SYMBOL SL'."""
    groups = match.groups()
    new_sl = float(groups[0]) if groups and groups[0] else None
    symbol = groups[1].upper() if len(groups) > 1 and groups[1] else None

    if not new_sl:
        return None

    return {
        "action": "SL_UPDATE",
        "symbol": symbol,
        "sl_update_type": "price",
        "new_stop_loss": new_sl,
        "asset": "stock",
        "confidence": 0.95,
        "is_sl_update": True,
        "_temple_sl_update": True,
    }


def parse_temple_zz_sl_update_move(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse 'Move your SL up to PRICE' / 'Move your stop loss for SYMBOL to PRICE'."""
    groups = match.groups()
    symbol = groups[0].upper() if groups and groups[0] else None
    new_sl = float(groups[1]) if len(groups) > 1 and groups[1] else None

    if not new_sl:
        return None

    return {
        "action": "SL_UPDATE",
        "symbol": symbol,
        "sl_update_type": "price",
        "new_stop_loss": new_sl,
        "asset": "stock",
        "confidence": 0.95,
        "is_sl_update": True,
        "_temple_sl_update": True,
    }


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


# =============================================================================
# ZZ STRUCTURED EMOJI PARSER FUNCTIONS
# =============================================================================

def _parse_zz_targets(targets_str: str, entry_price: float = None) -> list:
    """Parse targets from '0.33...0.37...0.40', '2.60-3.00', or '5% 10% 15%' format."""
    targets_str = targets_str.strip().rstrip('​').rstrip('+')
    pct_parts = re.findall(r'(\d+(?:\.\d+)?)\s*%', targets_str)
    if pct_parts and entry_price and entry_price > 0:
        return [round(entry_price * (1 + float(p) / 100), 4) for p in pct_parts]
    parts = re.split(r'\.{2,3}|/|,', targets_str)
    targets = []
    for part in parts:
        part = part.strip().rstrip('%+')
        if not part:
            continue
        range_match = re.match(r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)', part)
        if range_match:
            targets.append(float(range_match.group(1)))
            targets.append(float(range_match.group(2)))
        else:
            try:
                targets.append(float(part))
            except ValueError:
                continue
    return targets


def _detect_zz_trade_type(text: str) -> str:
    """Detect trade type from role mentions in text."""
    if ZZ_ROLE_SWING in text:
        return 'swing'
    if ZZ_ROLE_MOMENTUM in text:
        return 'momentum'
    if '/swing' in text.lower():
        return 'swing'
    return 'day'


def parse_temple_zz_structured_entry(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse structured ZZ entry: $TICKER @role / ✅ entry / ❌ stoploss (optional) / 🎯 targets."""
    symbol = match.group(1).upper()
    entry_price = float(match.group(2))
    entry_low = float(match.group(3)) if match.group(3) else None
    stop_loss = float(match.group(4)) if match.group(4) else None
    targets = _parse_zz_targets(match.group(5), entry_price=entry_price)

    trade_type = _detect_zz_trade_type(text)
    entry_high = entry_price
    if entry_low and entry_low > entry_high:
        entry_high, entry_low = entry_low, entry_high

    result = {
        'format': 'TEMPLE_ZZ_STRUCTURED',
        'is_conditional': True,
        '_conditional_order': True,
        '_temple_zz_structured': True,
        'asset': 'stock',
        'asset_type': 'stock',
        'action': 'BTO',
        'ticker': symbol,
        'symbol': symbol,
        'trigger_type': 'over',
        'trigger_price': entry_low if entry_low else entry_high,
        'entry_high': entry_high,
        'entry_low': entry_low,
        'stop_loss_type': 'fixed' if stop_loss else None,
        'stop_loss_value': stop_loss,
        'stop_loss_fixed': stop_loss,
        'stop_loss_pct': None,
        'profit_targets': targets,
        'target_ranges': [],
        'position_size_pct': None,
        'fixed_qty': None,
        'size_mode': None,
        'qty': 1,
        'qty_specified': False,
        'price': entry_high,
        'confidence': 1.0,
        '_trade_type': trade_type,
    }
    return result


def parse_temple_zz_inline_role_entry(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse inline ZZ entry with role: 'OCG in at 2.12 @Momentum' or '$EDHL @Momentum 2.67'."""
    symbol = match.group(1).upper()

    m_a = TEMPLE_ZZ_INLINE_ROLE_ENTRY_A.search(text)
    m_b = TEMPLE_ZZ_INLINE_ROLE_ENTRY_B.search(text)

    if m_a:
        price = float(m_a.group(2))
        role_id = m_a.group(3)
    elif m_b:
        role_id = m_b.group(2)
        price = float(m_b.group(3))
    else:
        price = float(match.group(2))
        role_id = match.group(3) if match.lastindex >= 3 else None

    trade_type = 'swing' if role_id == ZZ_ROLE_SWING else 'momentum'

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
        "is_market_order": False,
        "confidence": 1.0,
        "_temple_entry": True,
        "_temple_zz_role_entry": True,
        "_trade_type": trade_type,
    }
    return result


def parse_temple_zz_swing_update(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse ZZ swing update: '$TRUG @Swing ... 🎯 2.60-3.00 ❌ below 2.00'."""
    symbol = match.group(1).upper()
    role_id = match.group(2)
    targets = _parse_zz_targets(match.group(3))
    stop_loss = float(match.group(4))

    trade_type = 'swing' if role_id == ZZ_ROLE_SWING else 'momentum'

    return {
        'format': 'TEMPLE_ZZ_SWING_UPDATE',
        'is_conditional': True,
        '_conditional_order': True,
        '_temple_zz_structured': True,
        'asset': 'stock',
        'asset_type': 'stock',
        'action': 'BTO',
        'ticker': symbol,
        'symbol': symbol,
        'trigger_type': 'over',
        'trigger_price': targets[0] if targets else None,
        'entry_high': None,
        'entry_low': None,
        'stop_loss_type': 'fixed',
        'stop_loss_value': stop_loss,
        'stop_loss_fixed': stop_loss,
        'stop_loss_pct': None,
        'profit_targets': targets,
        'target_ranges': [],
        'position_size_pct': None,
        'fixed_qty': None,
        'size_mode': None,
        'qty': 1,
        'qty_specified': False,
        'price': None,
        'confidence': 0.9,
        '_trade_type': trade_type,
    }


def parse_temple_zz_standalone_targets(match: re.Match, text: str) -> Optional[Dict[str, Any]]:
    """Parse standalone ZZ targets: '🎯 2.41...2.71' (no ticker)."""
    targets = _parse_zz_targets(match.group(1))
    if not targets:
        return None

    return {
        "asset": "stock",
        "action": "UPDATE_TARGETS",
        "symbol": None,
        "profit_targets": targets,
        "confidence": 0.7,
        "_temple_zz_standalone_targets": True,
        "_needs_context_symbol": True,
    }
