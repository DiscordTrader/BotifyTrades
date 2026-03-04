"""
Hengy Alerts Embed Parser
==========================
Parses Discord embed signals from Hengy Alerts channels.

Signal Format (TRADE IDEA - new entries):
    Embed title: 🔮 | TRADE IDEA
    Embed description:
        📈 **TICKER**: $PRICE break
        🎯  $PT1 - $PT2 - $PT3 +
        ❌ under $SL_PRICE

Signal Format (TRADE UPDATE - updates with results):
    Embed title: 🔮 | TRADE UPDATE
    Embed description:
        📈 **TICKER**: $PRICE break / XX% ✅
        🎯  ~~$PT1~~ - ~~$PT2~~ - $PT3 +
        ❌ under $SL_PRICE

Features:
- Multi-ticker watchlist parsing (PM/MO watchlists)
- Breakout trigger detection ("$X break" / "$X clean break")
- Entry range parsing ("$X-$Y Entries")
- Profit target extraction (up to 4 PTs from 🎯 line)
- Stop loss extraction from ❌ under line
- Handles sub-dollar prices ($.31, $.325, etc.)
- Skips update messages with results (/ XX% ✅ or ❌)
- Skips NO ENTRY tickers
- Compatible with conditional_order_router.create_order() dict format
"""

import re
from typing import Optional, Dict, Any, List

PRICE_NUM = r'(?:\d+(?:\.\d+)?|\.\d+)'

HENGY_EMBED_TITLE_PATTERN = re.compile(
    r'TRADE\s+IDEA|TRADE\s+UPDATE',
    re.IGNORECASE
)

HENGY_BREAK_PRICE_PATTERN = re.compile(
    r'\$(' + PRICE_NUM + r')\s*(?:clean\s+)?break',
    re.IGNORECASE
)

HENGY_ENTRY_RANGE_PATTERN = re.compile(
    r'\$(' + PRICE_NUM + r')\s*[-–—]\s*\$?(' + PRICE_NUM + r')\s*entr',
    re.IGNORECASE
)

HENGY_PT_LINE_PATTERN = re.compile(
    r'🎯\s*(.*)',
    re.IGNORECASE
)

HENGY_SL_PATTERN = re.compile(
    r'❌\s*(?:(?:under|below|strict\s+cut)\s+)?\$?(' + PRICE_NUM + r')(?:\s+(?:strict\s+cut))?',
    re.IGNORECASE
)

HENGY_RESULT_PATTERN = re.compile(
    r'/\s*[\d]+(?:\.[\d]+)?%\s*[✅❌]',
)

HENGY_NO_ENTRY_PATTERN = re.compile(
    r'NO\s+ENTRY',
    re.IGNORECASE
)


def is_hengy_embed(embed_title: str, embed_description: str) -> bool:
    if not embed_title or not embed_description:
        return False
    if not HENGY_EMBED_TITLE_PATTERN.search(embed_title):
        return False
    if '📈' not in embed_description:
        return False
    has_break = bool(HENGY_BREAK_PRICE_PATTERN.search(embed_description))
    has_entry_range = bool(HENGY_ENTRY_RANGE_PATTERN.search(embed_description))
    return has_break or has_entry_range


def _parse_price(text: str) -> Optional[float]:
    try:
        val = float(text)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def parse_hengy_embed(embed_title: str, embed_description: str) -> List[Dict[str, Any]]:
    if not is_hengy_embed(embed_title, embed_description):
        return []

    is_update = 'UPDATE' in embed_title.upper()

    clean_desc = embed_description.replace('**', '')

    results = []

    parts = re.split(r'(?=📈)', clean_desc)

    for part in parts:
        if '📈' not in part:
            continue

        ticker_match = re.search(
            r'📈\s*\$?([A-Z]{1,5})\s*[:\-–—]\s*(.*)',
            part,
            re.DOTALL | re.IGNORECASE
        )
        if not ticker_match:
            continue

        symbol = ticker_match.group(1).upper()
        block_text = ticker_match.group(2)

        if HENGY_NO_ENTRY_PATTERN.search(block_text):
            print(f"[HENGY] ⚠️ Skipping {symbol} — NO ENTRY")
            continue

        if is_update and HENGY_RESULT_PATTERN.search(block_text):
            print(f"[HENGY] ⚠️ Skipping {symbol} — already has result (update)")
            continue

        trigger_price = None
        trigger_type = 'over'

        break_match = HENGY_BREAK_PRICE_PATTERN.search(block_text)
        if break_match:
            trigger_price = _parse_price(break_match.group(1))

        if trigger_price is None:
            range_match = HENGY_ENTRY_RANGE_PATTERN.search(block_text)
            if range_match:
                trigger_price = _parse_price(range_match.group(1))

        if trigger_price is None:
            continue

        profit_targets = []
        pt_line_match = HENGY_PT_LINE_PATTERN.search(block_text)
        if pt_line_match:
            pt_text = pt_line_match.group(1)
            pt_text_clean = pt_text.replace('~~', '')
            for pt_match in re.finditer(r'\$(' + PRICE_NUM + r')', pt_text_clean):
                pt_val = _parse_price(pt_match.group(1))
                if pt_val is not None:
                    profit_targets.append(pt_val)

        stop_loss_value = None
        stop_loss_type = None
        sl_match = HENGY_SL_PATTERN.search(block_text)
        if sl_match:
            stop_loss_value = _parse_price(sl_match.group(1))
            if stop_loss_value is not None:
                stop_loss_type = 'fixed'

        signal = {
            'format': 'HENGY_ALERTS',
            'is_conditional': True,
            'ticker': symbol,
            'symbol': symbol,
            'trigger_type': trigger_type,
            'trigger_price': trigger_price,
            'stop_loss_type': stop_loss_type,
            'stop_loss_value': stop_loss_value,
            'stop_loss_fixed': stop_loss_value,
            'stop_loss_pct': None,
            'profit_targets': profit_targets[:4],
            'target_ranges': [],
            'position_size_pct': None,
            'fixed_qty': None,
            'size_mode': None,
            'asset': 'stock',
            'asset_type': 'stock',
            '_conditional_order': True,
            '_original_message': part.strip(),
            '_hengy_alerts': True,
        }

        pt_str = ', '.join([f"${pt}" for pt in profit_targets[:4]]) if profit_targets else "None"
        sl_str = f"${stop_loss_value}" if stop_loss_value else "None"
        print(f"[HENGY] ✓ Parsed: {symbol} over ${trigger_price} | PTs: {pt_str} | SL: {sl_str}")

        results.append(signal)

    return results
