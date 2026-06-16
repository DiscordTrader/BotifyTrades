"""
Namrood Trades Embed Parser
============================
Parses Discord embed signals from Namrood-Trades bot (author_id: 1182389736904593510).

Signal Types (by embed title):
─────────────────────────────
BTO — title="Buy To Open"
    ANSI codeblock: SYMBOL STRIKE[CP] (DTE|DATE) PRICE
    Examples:
        SPY 733C 0DTE 0.89
        SPY 747C 0DTE 0.75
        UNH 420C 06-12-2026  $2.4
        GOOGL377.5C 06-18-2026  3.5      ← no space between ticker and strike

BTO (Lotto) — title="⚠️ Lotto Trade — RISKY"
    Plain codeblock: SYMBOL STRIKE[CP] (DTE|DATE) $PRICE
    Examples:
        SPY 745C 0DTE $1.7
        QQQ 721C 0DTE $2.3
        GOOGL 370C 06/18/2026 $2.75

STC/Trim — title="Close or Trim & Set SL to BE"
    ANSI codeblock (green):
        SYMBOL STRIKE[CP] DATE
        ENTRY  →  CURRENT   P/L: +XX.XX% ($XXX.XX)
    is_trim=True (partial exit — trader holds runners)

STC/Stop — title="Trade Update - Manage your risk"
    ANSI codeblock (red = loss):
        SYMBOL STRIKE[CP] DATE
        ENTRY  →  CURRENT   P/L: -XX.XX% ($-XXX.XX)
    is_full_exit=True (forced stop/cut)

STC — title="Sell To Close"
    Freeform price in description: "Close the lotto 0.54" / "I ll cut here $1.0"
    is_full_exit=True — looks up open position for symbol/strike/expiry

Skip — title="Idea" / "📊 Trade Breakdown..." / "Namrood Trades Performance Recap..."
    Commentary/recap — no trade action.

Date formats observed:
    0DTE → today | 1DTE / NDTE → N days from today
    2026-06-09  (YYYY-MM-DD)
    06-12-2026  (MM-DD-YYYY)
    06/18/2026  (MM/DD/YYYY)
"""

import re
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

NAMROOD_AUTHOR_ID = 1182389736904593510

PRICE_NUM = r'(?:\d+(?:\.\d+)?|\.\d+)'

ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')

# Matches: SYMBOL STRIKE[CP] DATE_OR_DTE PRICE
# Handles optional space between ticker and strike (GOOGL377.5C vs SPY 733C)
OPT_ENTRY_PATTERN = re.compile(
    r'([A-Z]{1,5})\s*(\d+(?:\.\d+)?)\s*([CPcp])\s+'
    r'(\S+)\s+'
    r'\$?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

# Matches ANSI exit block line 1: SYMBOL STRIKE[CP] DATE
OPT_EXIT_HEADER = re.compile(
    r'([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CPcp])\s+(\S+)'
)

# Matches ANSI exit block line 2: ENTRY  →  CURRENT_PRICE   P/L: ...
OPT_EXIT_PL = re.compile(
    r'([\d.]+)\s+[→\-\>]+\s+([\d.]+)'
)

# Freeform STC price: "$1.0" or "0.54" or "1 " at word boundary
STC_PRICE_PATTERN = re.compile(r'\$(' + PRICE_NUM + r')|\b(' + PRICE_NUM + r')\b')

DTE_PATTERN = re.compile(r'^(\d+)\s*DTE$', re.IGNORECASE)

BTO_TITLES = {'Buy To Open'}
LOTTO_TITLES = {'⚠️ Lotto Trade — RISKY'}
TRIM_TITLES = {'Close or Trim & Set SL to BE'}
STOP_TITLES = {'Trade Update - Manage your risk'}
STC_TITLES = {'Sell To Close'}
SKIP_TITLE_PREFIXES = ('Idea', '📊 Trade Breakdown', 'Namrood Trades Performance Recap')

ACTIONABLE_TITLES = BTO_TITLES | LOTTO_TITLES | TRIM_TITLES | STOP_TITLES | STC_TITLES


def is_namrood_embed(author_id: int, embeds: list) -> bool:
    if author_id != NAMROOD_AUTHOR_ID:
        return False
    for embed in embeds:
        title = (embed.get('title') or '').strip()
        if title in ACTIONABLE_TITLES:
            return True
    return False


def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    try:
        val = float(str(text).strip().lstrip('$+'))
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def _normalize_expiry(raw: str) -> str:
    """Convert any observed date format to YYYY-MM-DD, or N-DTE to relative date."""
    raw = raw.strip()

    dte_m = DTE_PATTERN.match(raw)
    if dte_m:
        days = int(dte_m.group(1))
        return (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')

    # YYYY-MM-DD already
    if re.match(r'^\d{4}-\d{2}-\d{2}$', raw):
        return raw

    # MM-DD-YYYY or MM/DD/YYYY
    m = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$', raw)
    if m:
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            pass

    # MM/DD (no year) — infer year
    m = re.match(r'^(\d{1,2})/(\d{1,2})$', raw)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        now = datetime.now()
        for yr in (now.year, now.year + 1):
            try:
                d = datetime(yr, month, day)
                if d.date() >= now.date():
                    return d.strftime('%Y-%m-%d')
            except ValueError:
                pass

    return raw


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub('', text)


def _extract_codeblock(desc: str) -> str:
    """Extract content from ```ansi...``` or ```...``` block."""
    m = re.search(r'```(?:ansi)?\n?(.*?)```', desc, re.DOTALL)
    if m:
        return _strip_ansi(m.group(1)).strip()
    return _strip_ansi(desc).strip()


def _parse_bto_block(block: str) -> Optional[Dict[str, Any]]:
    """Parse BTO entry from a codeblock line like 'SPY 733C 0DTE 0.89'."""
    m = OPT_ENTRY_PATTERN.search(block)
    if not m:
        return None
    symbol = m.group(1).upper()
    strike = float(m.group(2))
    opt_type = m.group(3).upper()
    raw_expiry = m.group(4)
    price = _parse_price(m.group(5))
    expiry = _normalize_expiry(raw_expiry)
    if not symbol or not strike or not price:
        return None
    return {
        'action': 'BTO',
        'symbol': symbol,
        'strike': strike,
        'opt_type': opt_type,
        'expiry': expiry,
        'price': price,
        'is_exit': False,
        'is_trim': False,
        'is_full_exit': False,
        'asset_type': 'option',
        'format': 'NAMROOD',
        '_namrood': True,
    }


def _parse_exit_block(block: str, is_full_exit: bool) -> Optional[Dict[str, Any]]:
    """Parse exit/trim from ANSI block with header + P/L line.

    Format:
        SYMBOL STRIKEC/P DATE
        ENTRY  →  CURRENT   P/L: +XX%
    """
    lines = [l.strip() for l in block.split('\n') if l.strip()]
    if not lines:
        return None

    header_m = OPT_EXIT_HEADER.search(lines[0])
    if not header_m:
        return None
    symbol = header_m.group(1).upper()
    strike = float(header_m.group(2))
    opt_type = header_m.group(3).upper()
    raw_expiry = header_m.group(4)
    expiry = _normalize_expiry(raw_expiry)

    current_price = None
    for line in lines[1:]:
        pl_m = OPT_EXIT_PL.search(line)
        if pl_m:
            current_price = _parse_price(pl_m.group(2))
            break

    return {
        'action': 'STC',
        'symbol': symbol,
        'strike': strike,
        'opt_type': opt_type,
        'expiry': expiry,
        'price': current_price,
        'is_exit': True,
        'is_trim': not is_full_exit,
        'is_full_exit': is_full_exit,
        'asset_type': 'option',
        'format': 'NAMROOD',
        '_namrood': True,
    }


def _parse_stc_freeform(desc: str) -> Optional[float]:
    """Extract price from freeform STC description like 'Close the lotto 0.54'."""
    matches = list(STC_PRICE_PATTERN.finditer(desc))
    for m in reversed(matches):
        raw = m.group(1) or m.group(2)
        price = _parse_price(raw)
        if price and 0.01 <= price <= 9999:
            return price
    return None


def parse_namrood_embed(embeds: list) -> List[Dict[str, Any]]:
    results = []

    for embed in embeds:
        title = (embed.get('title') or '').strip()
        desc = (embed.get('description') or '').strip()

        if not title or not desc:
            continue

        if any(title.startswith(pfx) for pfx in SKIP_TITLE_PREFIXES):
            print(f"[NAMROOD] Skipping: {title[:60]}")
            continue

        if title in BTO_TITLES:
            block = _extract_codeblock(desc)
            sig = _parse_bto_block(block)
            if sig:
                print(f"[NAMROOD] BTO: {sig['symbol']} {sig['strike']}{sig['opt_type']} {sig['expiry']} @ ${sig['price']}")
                results.append(sig)
            else:
                print(f"[NAMROOD] BTO parse failed: {block[:80]}")

        elif title in LOTTO_TITLES:
            block = _extract_codeblock(desc)
            sig = _parse_bto_block(block)
            if sig:
                sig['_lotto'] = True
                print(f"[NAMROOD] BTO (lotto): {sig['symbol']} {sig['strike']}{sig['opt_type']} {sig['expiry']} @ ${sig['price']}")
                results.append(sig)
            else:
                print(f"[NAMROOD] Lotto BTO parse failed: {block[:80]}")

        elif title in TRIM_TITLES:
            block = _extract_codeblock(desc)
            sig = _parse_exit_block(block, is_full_exit=False)
            if sig:
                print(f"[NAMROOD] STC (trim): {sig['symbol']} {sig['strike']}{sig['opt_type']} {sig['expiry']} @ ${sig['price']}")
                results.append(sig)
            else:
                print(f"[NAMROOD] Trim parse failed: {block[:80]}")

        elif title in STOP_TITLES:
            block = _extract_codeblock(desc)
            # Red P/L = stop loss / forced exit — treat as full exit
            sig = _parse_exit_block(block, is_full_exit=True)
            if sig:
                print(f"[NAMROOD] STC (stop/update): {sig['symbol']} {sig['strike']}{sig['opt_type']} {sig['expiry']} @ ${sig['price']}")
                results.append(sig)
            else:
                print(f"[NAMROOD] Stop/update parse failed: {block[:80]}")

        elif title in STC_TITLES:
            price = _parse_stc_freeform(desc)
            # Symbol/strike/expiry must be resolved from open position at execution time
            results.append({
                'action': 'STC',
                'symbol': None,
                'strike': None,
                'opt_type': None,
                'expiry': None,
                'price': price,
                'is_exit': True,
                'is_trim': False,
                'is_full_exit': True,
                'asset_type': 'option',
                'format': 'NAMROOD',
                '_namrood': True,
                '_stc_freeform': True,
                '_raw_desc': desc,
            })
            print(f"[NAMROOD] STC (sell-to-close, freeform): price=${price or 'market'} — will resolve symbol from open position")

    return results
