"""
AbTrades signal parser.

Handles three signal types from the AbTrades Discord channel:
  1. BTO entries:  **$SYMBOL MM/DD STRIKEc PRICE**
  2. Trim updates: $SYMBOL STRIKEc NN%
  3. Full exits:   ALL OUT: **$SYMBOL** / closing remaining
"""

import re
from typing import Optional, Dict, List


ABTRADES_ENTRY_RE = re.compile(
    r'\*\*\$([A-Z]{1,5})\s+'
    r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+'
    r'(\d+(?:\.\d+)?)'
    r'([cpCP])\s+'
    r'(\d*\.?\d+)'
    r'(?:x(\d+))?'
    r'\s*(?:\([^)]*\))?'
    r'\s*\*\*'
)

ABTRADES_TRIM_RE = re.compile(
    r'(?<!\*)\$([A-Z]{1,5})\s+'
    r'(\d+(?:\.\d+)?)'
    r'([cpCP])\s+'
    r'(\d+(?:\.\d+)?)%'
)

ABTRADES_EXIT_RE = re.compile(
    r'(?:'
    r'(?:ALL\s+OUT|(?:I|i)(?:\'?m|m)\s+all\s+out'
    r'|[Cc]losing\s+(?:the\s+)?(?:remaining|last\b[^$]*?\bon\b))'
    r'[\s\S]{0,60}?'
    r'\$([A-Z]{1,5})'
    r'|'
    r'\$([A-Z]{1,5})[^\n]{0,40}?(?:\n[^\n]{0,60}){0,2}?'
    r'(?:all\s+out|(?:I|i)(?:\'?m|m)\s+all\s+out'
    r'|closing\s+(?:the\s+)?remaining)'
    r')',
    re.IGNORECASE
)

_SL_RE = re.compile(r'SL[:\s]+\$?([\d.]+)', re.IGNORECASE)
_PT_RE = re.compile(r'PT[:\s]+\$?([\d.,\s]+)', re.IGNORECASE)


def _normalize_expiry(raw: str) -> tuple:
    from src.core.expiry import normalize_expiry_iso, expiry_year
    iso = normalize_expiry_iso(raw)
    return iso, expiry_year(iso)


def _extract_sl_pt(text: str) -> tuple:
    sl_val = None
    pt_vals = None
    sl_m = _SL_RE.search(text)
    if sl_m:
        try:
            sl_val = float(sl_m.group(1))
        except ValueError:
            pass
    pt_m = _PT_RE.search(text)
    if pt_m:
        raw = pt_m.group(1)
        prices = re.findall(r'[\d.]+', raw)
        if prices:
            pt_vals = []
            for p in prices:
                try:
                    v = float(p)
                    if v > 0:
                        pt_vals.append(v)
                except ValueError:
                    continue
    return sl_val, pt_vals


def _find_all_entries(text: str) -> List[Dict]:
    results = []
    for m in ABTRADES_ENTRY_RE.finditer(text):
        symbol = m.group(1).upper()
        expiry, expiry_year = _normalize_expiry(m.group(2))
        strike = float(m.group(3))
        opt_type = m.group(4).upper()
        raw_price = m.group(5)
        price = float(raw_price)
        qty_raw = m.group(6)
        qty = int(qty_raw) if qty_raw else None

        result = {
            "asset": "option",
            "action": "BTO",
            "symbol": symbol,
            "expiry": expiry,
            "strike": strike,
            "opt_type": opt_type,
            "price": price,
            "is_market_order": False,
            "confidence": 1.0,
        }
        if expiry_year:
            result["expiry_year"] = expiry_year
        if qty:
            result["qty"] = qty
            result["qty_specified"] = True
        results.append(result)
    return results


def parse_abtrades_entry(match: re.Match, text: str) -> Optional[Dict]:
    all_entries = _find_all_entries(text)
    if not all_entries:
        return None

    result = all_entries[0]
    result["_format_name"] = "abtrades_entry"

    sl_val, pt_vals = _extract_sl_pt(text)
    if sl_val:
        result["stop_loss"] = sl_val
    if pt_vals:
        result["take_profit"] = pt_vals

    if len(all_entries) > 1:
        extras = all_entries[1:]
        for ex in extras:
            ex["_format_name"] = "abtrades_entry"
        result["_abtrades_extra_entries"] = extras

    return result


def parse_abtrades_trim(match: re.Match, text: str) -> Optional[Dict]:
    symbol = match.group(1).upper()
    strike = float(match.group(2))
    opt_type = match.group(3).upper()
    pct = float(match.group(4))

    text_lower = text.lower()
    is_full_exit = 'all out' in text_lower or "i'm all out" in text_lower or 'im all out' in text_lower

    return {
        "asset": "option",
        "action": "STC",
        "symbol": symbol,
        "strike": strike,
        "opt_type": opt_type,
        "expiry": None,
        "price": None,
        "is_market_order": True,
        "is_trim": not is_full_exit,
        "is_full_exit": is_full_exit,
        "trim_percentage": pct,
        "confidence": 0.8,
        "_format_name": "abtrades_trim",
    }


def parse_abtrades_exit(match: re.Match, text: str) -> Optional[Dict]:
    symbol = (match.group(1) or match.group(2)).upper()

    expiry = None
    strike = None
    opt_type = None
    detail_m = re.search(
        r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+(\d+(?:\.\d+)?)([cpCP])',
        text
    )
    expiry_year = None
    if detail_m:
        expiry, expiry_year = _normalize_expiry(detail_m.group(1))
        strike = float(detail_m.group(2))
        opt_type = detail_m.group(3).upper()

    result = {
        "asset": "option",
        "action": "STC",
        "symbol": symbol,
        "strike": strike,
        "opt_type": opt_type,
        "expiry": expiry,
        "price": None,
        "is_market_order": True,
        "is_full_exit": True,
        "confidence": 0.9,
        "_format_name": "abtrades_exit",
    }
    if expiry_year:
        result["expiry_year"] = expiry_year
    return result
