"""
JPM Investments Embed Parser
=============================
Parses Discord embed signals from JpmInvestments (author_id: 1367190877419602011).

Signal Format (all via embeds):
    title="Open"   → BTO entry
    title="Close"  → STC exit
    title="Update" → price update (log only, no trade action)
    title=None     → SL update / correction / noise (log only)

Description pattern (Open / Close / Update):
    SYMBOL MM/DD STRIKE C/P @PRICE [(comment)]
    Examples:
        SPY 06/20 590P @.85 (SL 587.5)
        QQQ 05/05 680P @.79
        NVDA 04/17 120C @2.50 (SL $175)

Freeform Close:
    All out of SYMBOL @ PRICE/LOD/BE/HOD/under $X/over $X

No-title SL updates (ignored for trading, logged):
    SL $734.75  |  SL BE  |  SL LOD  |  SL over $618.00

Special no-title entries (handled as Open):
    Open —— QQQ 05/05 680P @.79

Corrections (ignored):
    Correction - 633P  |  Correction - 04/07
"""

import re
from typing import Optional, Dict, Any, List
from datetime import datetime

JPM_AUTHOR_ID = 1367190877419602011

PRICE_NUM = r'(?:\d+(?:\.\d+)?|\.\d+)'

# Core option signal: SYMBOL MM/DD STRIKEc/p @PRICE
OPT_PATTERN = re.compile(
    r'([A-Z]{1,5})\s+'
    r'(\d{1,2}/\d{1,2})\s+'
    r'(\d+(?:\.\d+)?)\s*([CPcp])\s*'
    r'@\s*(' + PRICE_NUM + r')',
    re.IGNORECASE
)

# Freeform close: All out of SYMBOL ...
ALL_OUT_PATTERN = re.compile(
    r'[Aa]ll\s+out\s+(?:of\s+)?([A-Z]{1,5})',
    re.IGNORECASE
)

# SL in parentheses: (SL $734.75) or (SL HOD) etc.
SL_PAREN_PATTERN = re.compile(
    r'\(SL\s+\$?(' + PRICE_NUM + r')\)',
    re.IGNORECASE
)

# SL in markdown quote: > SL under $616.00
SL_QUOTE_PATTERN = re.compile(
    r'>\s*SL\s+(?:under\s+|above\s+|over\s+)?\$?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

# No-title special: "Open —— SYMBOL ..." treat as Open
NO_TITLE_OPEN_PATTERN = re.compile(
    r'^Open\s*[-—]+\s*',
    re.IGNORECASE
)

# Correction noise
CORRECTION_PATTERN = re.compile(r'^Correction\s*[-–—]', re.IGNORECASE)

# Price close with freeform target (LOD/BE/HOD/market)
FREEFORM_PRICE_PATTERN = re.compile(
    r'@\s*(' + PRICE_NUM + r'|LOD|HOD|BE|market)',
    re.IGNORECASE
)


def is_jpm_investments_embed(author_id: int, embeds: list) -> bool:
    if author_id != JPM_AUTHOR_ID:
        return False
    for embed in embeds:
        title = (embed.get('title') or '').strip()
        desc = (embed.get('description') or '').strip()
        if title in ('Open', 'Close', 'Update') or desc:
            return True
    return False


def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    text = text.strip().lstrip('+$')
    try:
        val = float(text)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def _normalize_expiry(mm_dd: str) -> str:
    """Convert MM/DD to YYYY-MM-DD using current or next year."""
    try:
        month, day = map(int, mm_dd.split('/'))
        now = datetime.now()
        year = now.year
        candidate = datetime(year, month, day)
        if candidate.date() < now.date():
            candidate = datetime(year + 1, month, day)
        return candidate.strftime('%Y-%m-%d')
    except (ValueError, AttributeError):
        return mm_dd


def _extract_sl(desc: str) -> Optional[float]:
    m = SL_PAREN_PATTERN.search(desc)
    if m:
        return _parse_price(m.group(1))
    m = SL_QUOTE_PATTERN.search(desc)
    if m:
        return _parse_price(m.group(1))
    return None


def parse_jpm_investments_embed(embeds: list) -> List[Dict[str, Any]]:
    results = []

    for embed in embeds:
        title = (embed.get('title') or '').strip()
        desc = (embed.get('description') or '').strip()

        if not desc:
            continue

        if CORRECTION_PATTERN.match(desc):
            print(f"[JPM] ⏭️ Skipping correction: {desc[:60]}")
            continue

        effective_title = title
        if not title and NO_TITLE_OPEN_PATTERN.match(desc):
            effective_title = 'Open'
            desc = NO_TITLE_OPEN_PATTERN.sub('', desc).strip()

        if effective_title == 'Update':
            print(f"[JPM] ℹ️ Update signal (no trade action): {desc[:80]}")
            continue

        if not effective_title:
            # SL update or noise — log and skip
            print(f"[JPM] ℹ️ No-title message (SL update/noise): {desc[:80]}")
            continue

        action = 'BTO' if effective_title == 'Open' else 'STC'

        # Try standard option format first
        m = OPT_PATTERN.search(desc)
        if m:
            symbol = m.group(1).upper()
            mm_dd = m.group(2)
            strike = float(m.group(3))
            opt_type = m.group(4).upper()
            price = _parse_price(m.group(5))
            expiry = _normalize_expiry(mm_dd)
            sl_price = _extract_sl(desc)

            sig = {
                'action': action,
                'symbol': symbol,
                'strike': strike,
                'opt_type': opt_type,
                'expiry': expiry,
                'price': price,
                'is_exit': action == 'STC',
                'is_trim': False,
                'is_full_exit': action == 'STC',
                'asset_type': 'option',
                'format': 'JPM_INVESTMENTS',
                '_jpm': True,
            }
            if sl_price is not None:
                sig['stop_loss'] = sl_price

            label = f"{action}: {symbol} {strike}{opt_type} {expiry} @ ${price}"
            if sl_price:
                label += f" SL=${sl_price}"
            print(f"[JPM] ✓ {label}")
            results.append(sig)
            continue

        # Freeform close: "All out of SYMBOL ..."
        if action == 'STC':
            all_out_m = ALL_OUT_PATTERN.search(desc)
            if all_out_m:
                symbol = all_out_m.group(1).upper()
                price = None
                price_m = FREEFORM_PRICE_PATTERN.search(desc)
                if price_m:
                    raw_price = price_m.group(1)
                    price = _parse_price(raw_price) if raw_price not in ('LOD', 'HOD', 'BE', 'market') else None
                print(f"[JPM] ✓ STC (all-out): {symbol} @ {price or 'market'}")
                results.append({
                    'action': 'STC',
                    'symbol': symbol,
                    'strike': None,
                    'opt_type': None,
                    'expiry': None,
                    'price': price,
                    'is_exit': True,
                    'is_trim': False,
                    'is_full_exit': True,
                    'asset_type': 'option',
                    'format': 'JPM_INVESTMENTS',
                    '_jpm': True,
                    '_all_out': True,
                })
                continue

        print(f"[JPM] ⚠️ Could not parse {effective_title} signal: {desc[:80]}")

    return results
