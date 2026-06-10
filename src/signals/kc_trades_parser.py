"""
KC Trades Embed Parser
=======================
Parses Discord embed signals from KC Trades bot (author_id: 954609923189248053).

Entry Format (in embed title OR description):
    TICKER STRIKEc/p EXPIRY [qualifier] @ PRICE
    TICKER STRIKEc/p EXPIRY [qualifier] at PRICE

    Examples:
        SPY 600c 4/17 lotto @ 1.50
        AAPL 230p May 15 swing @ 3.20
        QQQ 500c 0DTE day trade at 2.80
        PLTR 30c 1DTE @ 0.45

Exit Format (in embed title or description):
    trimmed TICKER @ PRICE
    out half TICKER @ PRICE
    out majority TICKER @ PRICE
    all out TICKER @ PRICE
    closed TICKER @ PRICE
    closing TICKER at PRICE
    stopped on TICKER @ PRICE

Features:
- Author ID gating (954609923189248053) — only parses KC Trades bot embeds
- Supports both @ and at as price anchors
- Handles expiry formats: M/D, Month D, 0DTE, 1DTE, NDTE
- Handles "back in" as re-entry (BTO)
- Handles "added"/"added to" as BTO add
- Strips + prefix from trim prices
- Skips commentary, corrections, and ambiguous messages
"""

import re
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta

KC_TRADES_AUTHOR_ID = 954609923189248053

MONTH_MAP = {
    'jan': 1, 'january': 1,
    'feb': 2, 'february': 2,
    'mar': 3, 'march': 3,
    'apr': 4, 'april': 4,
    'may': 5,
    'jun': 6, 'june': 6,
    'jul': 7, 'july': 7,
    'aug': 8, 'august': 8,
    'sep': 9, 'september': 9, 'sept': 9,
    'oct': 10, 'october': 10,
    'nov': 11, 'november': 11,
    'dec': 12, 'december': 12,
}

PRICE_NUM = r'\d+(?:\.\d+)?'

ENTRY_PATTERN = re.compile(
    r'([A-Z]{1,5})\s+'
    r'(\d+(?:\.\d+)?)\s*([cCpP])\s+'
    r'(\S+(?:\s+\d{1,2})?)\s+'
    r'(?:[\w\s]*?)'
    r'(?:@|at)\s+'
    r'\+?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

DTE_PATTERN = re.compile(r'^(\d+)\s*DTE$', re.IGNORECASE)
MONTH_DAY_PATTERN = re.compile(r'^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$')
MONTH_NAME_PATTERN = re.compile(
    r'^(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})$',
    re.IGNORECASE
)

TRIM_PATTERN = re.compile(
    r'(?:trimmed|trim)\s+([A-Z]{1,5})\s*(?:@|at)\s*\+?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

EXIT_PARTIAL_PATTERN = re.compile(
    r'(?:out\s+(?:half|majority|some|most|partial))\s+(?:of\s+)?([A-Z]{1,5})\s*(?:@|at)\s*\+?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

EXIT_FULL_PATTERN = re.compile(
    r'(?:all\s+out|closed|closing|stopped\s+on)\s+(?:my\s+)?(?:the\s+)?(?:rest\s+of\s+)?([A-Z]{1,5})\s*(?:@|at)?\s*\+?(' + PRICE_NUM + r')?',
    re.IGNORECASE
)

ADD_PATTERN = re.compile(
    r'(?:added|added\s+to|back\s+in)\s+'
    r'([A-Z]{1,5})\s+'
    r'(\d+(?:\.\d+)?)\s*([cCpP])\s+'
    r'(\S+(?:\s+\d{1,2})?)\s+'
    r'(?:[\w\s]*?)'
    r'(?:@|at)\s+'
    r'\+?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

ADD_SIMPLE_PATTERN = re.compile(
    r'(?:added|added\s+to|back\s+in)\s+'
    r'([A-Z]{1,5})\s*(?:@|at)\s*\+?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

BARE_ENTRY_PATTERN = re.compile(
    r'^(\d+(?:\.\d+)?)\s*([cCpP])\s+'
    r'(\S+(?:\s+\d{1,2})?)\s+'
    r'(?:[\w\s]*?)'
    r'(?:@|at)\s+'
    r'\+?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

SKIP_PATTERNS = [
    re.compile(r'^\*', re.IGNORECASE),
    re.compile(r'^filled\s', re.IGNORECASE),
    re.compile(r'^entering\s+into', re.IGNORECASE),
    re.compile(r'^rolled\s', re.IGNORECASE),
    re.compile(r'^watching\s', re.IGNORECASE),
    re.compile(r'^looking\s+at\s', re.IGNORECASE),
]


def is_kc_trades_embed(author_id: int, embeds: list) -> bool:
    if author_id != KC_TRADES_AUTHOR_ID:
        return False
    if not embeds:
        return False
    for embed in embeds:
        title = (embed.get('title') or '').strip()
        desc = (embed.get('description') or '').strip()
        if title or desc:
            return True
    return False


def _normalize_expiry(raw_expiry: str) -> Optional[str]:
    from src.core.expiry import normalize_expiry_iso

    raw = raw_expiry.strip()

    dte_m = DTE_PATTERN.match(raw)
    if dte_m:
        days = int(dte_m.group(1))
        target = datetime.now() + timedelta(days=days)
        return target.strftime('%Y-%m-%d')

    try:
        return normalize_expiry_iso(raw)
    except ValueError:
        return raw


def _parse_price(text: str) -> Optional[float]:
    if not text:
        return None
    try:
        val = float(text.strip().lstrip('+'))
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def _should_skip(text: str) -> bool:
    for pat in SKIP_PATTERNS:
        if pat.search(text):
            return True
    return False


def parse_kc_trades_embed(embeds: list) -> List[Dict[str, Any]]:
    results = []

    for embed in embeds:
        title = (embed.get('title') or '').strip()
        desc = (embed.get('description') or '').strip()

        combined = f"{title}\n{desc}".strip()
        if not combined:
            continue

        if _should_skip(combined):
            print(f"[KC-TRADES] ⏭️ Skipping (matched skip pattern): {combined[:80]}")
            continue

        for line in combined.split('\n'):
            line = line.strip()
            if not line:
                continue

            parsed = _parse_line(line, title)
            if parsed:
                results.extend(parsed)

    if results:
        for r in results:
            action = r.get('action', 'BTO')
            symbol = r.get('symbol', '?')
            strike = r.get('strike', '')
            opt_type = r.get('opt_type', '')
            price = r.get('price', 0)
            expiry = r.get('expiry', '')
            is_trim = r.get('is_trim', False)
            is_exit = r.get('is_exit', False)
            label = 'TRIM' if is_trim else ('STC' if is_exit else 'BTO')
            if strike:
                print(f"[KC-TRADES] ✓ {label}: {symbol} {strike}{opt_type} {expiry} @ ${price}")
            else:
                print(f"[KC-TRADES] ✓ {label}: {symbol} @ ${price}")

    return results


def _parse_line(line: str, title_context: str = '') -> List[Dict[str, Any]]:
    results = []

    if _should_skip(line):
        return results

    trim_m = TRIM_PATTERN.search(line)
    if trim_m:
        symbol = trim_m.group(1).upper()
        price = _parse_price(trim_m.group(2))
        if symbol and price:
            results.append({
                'action': 'STC',
                'symbol': symbol,
                'price': price,
                'is_trim': True,
                'is_exit': True,
                'is_full_exit': False,
                'asset_type': 'option',
                'format': 'KC_TRADES',
                '_kc_trades': True,
            })
        return results

    exit_p = EXIT_PARTIAL_PATTERN.search(line)
    if exit_p:
        symbol = exit_p.group(1).upper()
        price = _parse_price(exit_p.group(2))
        if symbol:
            results.append({
                'action': 'STC',
                'symbol': symbol,
                'price': price,
                'is_trim': True,
                'is_exit': True,
                'is_full_exit': False,
                'asset_type': 'option',
                'format': 'KC_TRADES',
                '_kc_trades': True,
            })
        return results

    exit_f = EXIT_FULL_PATTERN.search(line)
    if exit_f:
        symbol = exit_f.group(1).upper()
        price = _parse_price(exit_f.group(2)) if exit_f.group(2) else None
        skip_words = {'MY', 'THE', 'REST', 'HALF', 'SOME'}
        if symbol and symbol not in skip_words:
            results.append({
                'action': 'STC',
                'symbol': symbol,
                'price': price,
                'is_trim': False,
                'is_exit': True,
                'is_full_exit': True,
                'asset_type': 'option',
                'format': 'KC_TRADES',
                '_kc_trades': True,
            })
        return results

    add_m = ADD_PATTERN.search(line)
    if add_m:
        symbol = add_m.group(1).upper()
        strike = float(add_m.group(2))
        opt_type = add_m.group(3).upper()
        raw_expiry = add_m.group(4)
        price = _parse_price(add_m.group(5))
        expiry = _normalize_expiry(raw_expiry)
        if symbol and strike and price:
            results.append({
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
                'format': 'KC_TRADES',
                '_kc_trades': True,
                '_is_add': True,
            })
        return results

    add_s = ADD_SIMPLE_PATTERN.search(line)
    if add_s:
        symbol = add_s.group(1).upper()
        price = _parse_price(add_s.group(2))
        if symbol and price:
            results.append({
                'action': 'BTO',
                'symbol': symbol,
                'price': price,
                'is_exit': False,
                'is_trim': False,
                'is_full_exit': False,
                'asset_type': 'option',
                'format': 'KC_TRADES',
                '_kc_trades': True,
                '_is_add': True,
            })
        return results

    entry_m = ENTRY_PATTERN.search(line)
    if entry_m:
        symbol = entry_m.group(1).upper()
        strike = float(entry_m.group(2))
        opt_type = entry_m.group(3).upper()
        raw_expiry = entry_m.group(4)
        price = _parse_price(entry_m.group(5))
        expiry = _normalize_expiry(raw_expiry)

        if symbol and strike and price:
            results.append({
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
                'format': 'KC_TRADES',
                '_kc_trades': True,
            })
        return results

    bare_m = BARE_ENTRY_PATTERN.search(line)
    if bare_m and title_context:
        ticker = _extract_ticker_from_title(title_context)
        if ticker:
            strike = float(bare_m.group(1))
            opt_type = bare_m.group(2).upper()
            raw_expiry = bare_m.group(3)
            price = _parse_price(bare_m.group(4))
            expiry = _normalize_expiry(raw_expiry)

            if strike and price:
                results.append({
                    'action': 'BTO',
                    'symbol': ticker,
                    'strike': strike,
                    'opt_type': opt_type,
                    'expiry': expiry,
                    'price': price,
                    'is_exit': False,
                    'is_trim': False,
                    'is_full_exit': False,
                    'asset_type': 'option',
                    'format': 'KC_TRADES',
                    '_kc_trades': True,
                })
            return results

    return results


def _extract_ticker_from_title(title: str) -> Optional[str]:
    if not title:
        return None
    title_upper = title.upper().strip()
    qualifiers = {'SWING', 'LOTTO', 'LOTTOS', 'SMALL', 'STARTER', 'DAY', 'TRADE', 'DTE', '0DTE', '1DTE',
                  'NEW', 'ENTRY', 'EXIT', 'TRIM', 'ADD', 'ALERT', 'UPDATE'}
    words = title_upper.split()
    for w in words:
        clean = re.sub(r'[^A-Z]', '', w)
        if clean and 1 <= len(clean) <= 5 and clean not in qualifiers:
            return clean
    return None
