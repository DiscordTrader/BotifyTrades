"""
Equity Genie Embed Parser
===========================
Parses Discord embed signals from Equity Genie channels.

ENTRY Signal Format (embed title: OPEN / ENTRY):
    **TICKER $PRICE BREAK**
    🎯 PT 6 6.50+
    **TICKER | $PRICE BREAK**
    🎯 PT: 2.20 2.40
    **TICKER | Break of PRICE**
    🎯 PT: 9.50 10+
    **$TICKER | $PRICE** (price-only, no BREAK keyword — valid when PT follows)
    **$TICKER | Over $PRICE**

EXIT Signal Format (embed title: EXIT / CLOSE):
    Actionable:
        **TICKER | PRICE OUT**
        **$TICKER | Sold here $PRICE**
        **TICKER | Closing here $PRICE**
        **$TICKER | OUT MOST SL ENTRY**
    Partial:
        **$TICKER | PT 1 HIT! OUT HALF**
        **$TICKER | PRICE!!! Trimmed**
        **$TICKER | OUT 3/4**
        **$TICKER | OUT 1/3**
    Informational (logged, not acted on):
        **TICKER | PT 1 HIT** (no exit instruction)
        **TICKER | ALL PT'S HIT!** (celebratory)
        **TICKER | BOOM!** (celebratory)

IGNORED embed titles: WATCHING, UPDATE, SCANNER, RECAP

Features:
- Multi-ticker entry parsing (each ticker line = separate conditional order)
- Breakout trigger detection ("BREAK", "Break of", "Over", price-only)
- Profit target extraction (up to 4 PTs) with 6+ format variants
- Sub-dollar price handling ($.975, .12, etc.)
- Exit action detection with partial exit percentage (OUT HALF=50%, etc.)
- SL update detection from EXIT embeds
- Conservative exit logic: only acts on explicit keywords
- Compatible with conditional_order_router.create_order() dict format
"""

import re
from typing import Optional, Dict, Any, List, Tuple

PRICE_NUM = r'(?:\d+(?:\.\d+)?|\.\d+)'

VALID_ENTRY_TITLES = {'OPEN', 'ENTRY'}
VALID_EXIT_TITLES = {'EXIT', 'CLOSE'}
IGNORED_TITLES = {'WATCHING', 'UPDATE', 'SCANNER', 'RECAP', 'SCANNER RESULTS',
                  'SCANNER WATCHLIST', 'SCANNER WATCHLIST (UPDATED)'}

TICKER_PATTERN = re.compile(r'\$?([A-Z]{2,5})', re.IGNORECASE)

BREAK_PRICE_PATTERN = re.compile(
    r'\$?(' + PRICE_NUM + r')\s+BREAK',
    re.IGNORECASE
)

BREAK_OF_PATTERN = re.compile(
    r'Break\s+of\s+\$?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

ON_THE_BREAK_PATTERN = re.compile(
    r'ON\s+THE\s+\$?(' + PRICE_NUM + r')\s+BREAK',
    re.IGNORECASE
)

OVER_PRICE_PATTERN = re.compile(
    r'Over\s+\$?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

PRICE_ONLY_PATTERN = re.compile(
    r'[|]\s*\$?(' + PRICE_NUM + r')\s*\**\s*$',
    re.IGNORECASE
)

PT_LINE_PATTERNS = [
    re.compile(r'🎯\s*PT[:\s]*(.+)', re.IGNORECASE),
    re.compile(r'(?:^|\s)PT[:\s]+(.+)', re.IGNORECASE),
    re.compile(r'(?:^|\s)PT\s+((?:\$?' + PRICE_NUM + r'[\s,]+)*\$?' + PRICE_NUM + r')', re.IGNORECASE),
]

EXIT_OUT_PATTERN = re.compile(
    r'\$?(' + PRICE_NUM + r')\s+OUT\b',
    re.IGNORECASE
)

EXIT_SOLD_PATTERN = re.compile(
    r'(?:Sold|Closing)\s+here\s+\$?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

EXIT_SOLD_HALF_PATTERN = re.compile(
    r'Sold\s+Half!?\s+\$?(' + PRICE_NUM + r')',
    re.IGNORECASE
)

EXIT_OUT_KEYWORD = re.compile(
    r'\bOUT\b(?!\s*(?:STANDING|LOOK|SIDE|PERFORM))',
    re.IGNORECASE
)

PARTIAL_EXIT_PATTERNS = [
    (re.compile(r'Sold\s+Half', re.IGNORECASE), 50),
    (re.compile(r'OUT\s+HALF', re.IGNORECASE), 50),
    (re.compile(r'OUT\s+MOST', re.IGNORECASE), 75),
    (re.compile(r'OUT\s+ALL\s+BUT\s+1/3', re.IGNORECASE), 67),
    (re.compile(r'OUT\s+3/4', re.IGNORECASE), 75),
    (re.compile(r'OUT\s+2/3', re.IGNORECASE), 67),
    (re.compile(r'OUT\s+1/3', re.IGNORECASE), 33),
    (re.compile(r'OUT\s+1/4', re.IGNORECASE), 25),
    (re.compile(r'TRIMMED?\s+1/4', re.IGNORECASE), 25),
    (re.compile(r'TRIMMED?\s+1/3', re.IGNORECASE), 33),
    (re.compile(r'TRIMMED?\s+1/2', re.IGNORECASE), 50),
    (re.compile(r'TRIMMED', re.IGNORECASE), 50),
    (re.compile(r'Trim\s+1/4', re.IGNORECASE), 25),
    (re.compile(r'Trim\s+1/3', re.IGNORECASE), 33),
    (re.compile(r'Trim\s+1/2', re.IGNORECASE), 50),
]

SL_ENTRY_PATTERN = re.compile(r'\bSL\s+(?:ENTRY|AT\s+ENTRY)', re.IGNORECASE)

SL_PRICE_PATTERN = re.compile(r'\bSL\s+\$?(' + PRICE_NUM + r')', re.IGNORECASE)

CELEBRATORY_ONLY_PATTERNS = [
    re.compile(r'BOOM', re.IGNORECASE),
    re.compile(r'HOLY\s+CRAP', re.IGNORECASE),
    re.compile(r'BANGER', re.IGNORECASE),
    re.compile(r'OH\s+MY\s+GOD', re.IGNORECASE),
    re.compile(r'WINNER', re.IGNORECASE),
    re.compile(r'BANGIN', re.IGNORECASE),
    re.compile(r'FAT\s+WIN', re.IGNORECASE),
    re.compile(r'RIPPING', re.IGNORECASE),
    re.compile(r'WOOO', re.IGNORECASE),
    re.compile(r'NICE\s+WIN', re.IGNORECASE),
]


def _parse_price(text: str) -> Optional[float]:
    try:
        val = float(text)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def _extract_ticker(line: str) -> Optional[str]:
    cleaned = line.strip().strip('*').strip()
    m = TICKER_PATTERN.match(cleaned)
    if m:
        sym = m.group(1).upper()
        if len(sym) >= 2 and sym not in {'PT', 'SL', 'HIT', 'ALL', 'THE', 'OUT', 'AND', 'FOR', 'BUT'}:
            return sym
    return None


def _extract_trigger_price(line: str) -> Tuple[Optional[float], str]:
    m = ON_THE_BREAK_PATTERN.search(line)
    if m:
        return _parse_price(m.group(1)), 'over'

    m = BREAK_PRICE_PATTERN.search(line)
    if m:
        return _parse_price(m.group(1)), 'over'

    m = BREAK_OF_PATTERN.search(line)
    if m:
        return _parse_price(m.group(1)), 'over'

    m = OVER_PRICE_PATTERN.search(line)
    if m:
        return _parse_price(m.group(1)), 'over'

    m = PRICE_ONLY_PATTERN.search(line)
    if m:
        return _parse_price(m.group(1)), 'over'

    price_match = re.search(r'\$(' + PRICE_NUM + r')', line)
    if price_match:
        cleaned = line.strip().strip('*').strip()
        if 'SWING' in cleaned.upper() or 'WATCH' in cleaned.upper() or 'RADAR' in cleaned.upper():
            return None, 'over'
        parts_after_ticker = re.sub(r'^\$?[A-Z]{2,5}\s*[|]?\s*', '', cleaned, flags=re.IGNORECASE)
        price_candidates = re.findall(r'\$?(' + PRICE_NUM + r')', parts_after_ticker)
        if price_candidates:
            price = _parse_price(price_candidates[0])
            if price:
                return price, 'over'

    return None, 'over'


def _extract_profit_targets(text: str) -> List[float]:
    for pattern in PT_LINE_PATTERNS:
        m = pattern.search(text)
        if m:
            pt_text = m.group(1)
            pt_text_clean = pt_text.replace('+', '').replace('!', '').strip()
            targets = []
            for pt_match in re.finditer(r'\$?(' + PRICE_NUM + r')', pt_text_clean):
                pt_val = _parse_price(pt_match.group(1))
                if pt_val is not None:
                    targets.append(pt_val)
            if targets:
                return targets[:4]
    return []


def _is_sir_goldman_content(desc: str) -> bool:
    cleaned = desc.strip().strip('*').strip()
    if re.match(r'^(?:BTO|STC)\s+[A-Z]{1,5}\s+\d', cleaned, re.IGNORECASE):
        return True
    if re.search(r'\d+[CPcp]\s', cleaned):
        return True
    if re.search(r'@\s*\$?\d+\.?\d*', cleaned):
        return True
    if re.search(r'\b(?:lotto|debit\s+spread|iron\s+condor|straddle|strangle)\b', cleaned, re.IGNORECASE):
        return True
    if re.search(r'\b(?:Out\s+rest|Out\s+here\s+at\s+BE|adding\s+here)\b', cleaned, re.IGNORECASE):
        return True
    return False


def is_equity_genie_embed(embed_title: str, embed_description: str) -> bool:
    if not embed_title:
        return False

    title_upper = embed_title.upper().strip()

    if title_upper in VALID_ENTRY_TITLES:
        if _is_sir_goldman_content(embed_description or ''):
            return False
        if embed_description:
            desc = embed_description.strip()
            has_break = bool(BREAK_PRICE_PATTERN.search(desc) or BREAK_OF_PATTERN.search(desc)
                           or ON_THE_BREAK_PATTERN.search(desc))
            has_over = bool(OVER_PRICE_PATTERN.search(desc))
            has_price_with_pt = bool(re.search(r'\$' + PRICE_NUM, desc)) and bool(
                re.search(r'PT', desc, re.IGNORECASE))
            has_bold_ticker = bool(re.search(r'\*\*\$?[A-Z]{2,5}', desc, re.IGNORECASE))
            if has_break or has_over or has_price_with_pt or has_bold_ticker:
                return True
        return False

    if title_upper in VALID_EXIT_TITLES:
        if _is_sir_goldman_content(embed_description or ''):
            return False
        if embed_description and re.search(r'\*\*', embed_description):
            return True
        return False

    return False


def parse_equity_genie_entries(embed_title: str, embed_description: str) -> List[Dict[str, Any]]:
    if not embed_description:
        return []

    title_upper = (embed_title or '').upper().strip()
    if title_upper not in VALID_ENTRY_TITLES:
        return []

    if _is_sir_goldman_content(embed_description):
        return []

    results = []

    desc_clean = embed_description.replace('```', '\n')

    lines = desc_clean.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if not line or line.startswith('[') or line.startswith('http'):
            i += 1
            continue

        if re.match(r'^🎯', line) or re.match(r'^PT[\s:]', line, re.IGNORECASE):
            i += 1
            continue

        ticker = _extract_ticker(line)
        if not ticker:
            i += 1
            continue

        cleaned_line = line.strip('*').strip()
        if re.match(r'^(WATCHLIST|SCANNER)\b', cleaned_line, re.IGNORECASE):
            i += 1
            continue
        if 'WATCHING' in cleaned_line.upper() and 'BREAK' not in cleaned_line.upper():
            i += 1
            continue

        trigger_price, trigger_type = _extract_trigger_price(line)

        lookahead = ''
        for j in range(i + 1, min(i + 4, len(lines))):
            next_line = lines[j].strip()
            if next_line.startswith('**') and _extract_ticker(next_line):
                break
            if next_line.startswith('[') or next_line.startswith('http'):
                break
            lookahead += ' ' + next_line

        profit_targets = _extract_profit_targets(lookahead)

        if not profit_targets:
            profit_targets = _extract_profit_targets(line)

        if trigger_price is None and not profit_targets:
            i += 1
            continue

        if trigger_price is None and profit_targets:
            i += 1
            continue

        sl_value = None
        sl_type = None
        sl_match = SL_PRICE_PATTERN.search(lookahead)
        if sl_match:
            sl_value = _parse_price(sl_match.group(1))
            if sl_value:
                sl_type = 'fixed'

        signal = {
            'format': 'EQUITY_GENIE',
            'is_conditional': True,
            'ticker': ticker,
            'symbol': ticker,
            'trigger_type': trigger_type,
            'trigger_price': trigger_price,
            'stop_loss_type': sl_type,
            'stop_loss_value': sl_value,
            'stop_loss_fixed': sl_value,
            'stop_loss_pct': None,
            'profit_targets': profit_targets,
            'target_ranges': [],
            'position_size_pct': None,
            'fixed_qty': None,
            'size_mode': None,
            'asset': 'stock',
            'asset_type': 'stock',
            '_conditional_order': True,
            '_original_message': line.strip(),
            '_equity_genie': True,
        }

        if profit_targets and trigger_price:
            valid_pts = [pt for pt in profit_targets if pt > trigger_price]
            if len(valid_pts) < len(profit_targets):
                bad_pts = [pt for pt in profit_targets if pt <= trigger_price]
                print(f"[EQUITY-GENIE] ⚠️ PT sanity: {ticker} trigger=${trigger_price}, dropping PTs below trigger: {bad_pts}")
                signal['profit_targets'] = valid_pts

        pt_str = ', '.join([f"${pt}" for pt in signal['profit_targets']]) if signal['profit_targets'] else "None"
        sl_str = f"${sl_value}" if sl_value else "None"
        print(f"[EQUITY-GENIE] ✓ Parsed ENTRY: {ticker} over ${trigger_price} | PTs: {pt_str} | SL: {sl_str}")

        results.append(signal)
        i += 1

    return results


def parse_equity_genie_exits(embed_title: str, embed_description: str) -> List[Dict[str, Any]]:
    if not embed_description:
        return []

    title_upper = (embed_title or '').upper().strip()
    if title_upper not in VALID_EXIT_TITLES:
        return []

    if _is_sir_goldman_content(embed_description):
        return []

    results = []
    desc = embed_description.strip()

    bold_blocks = re.findall(r'\*\*(.*?)\*\*', desc)
    if not bold_blocks:
        bold_blocks = [desc]

    for block in bold_blocks:
        block_clean = block.strip()

        ticker = None
        anchor_match = re.match(r'^\$([A-Z]{2,5})\b', block_clean)
        if anchor_match:
            ticker = anchor_match.group(1).upper()
        if not ticker:
            pipe_match = re.match(r'^([A-Z]{2,5})\s*[|}\s]', block_clean)
            if pipe_match:
                sym = pipe_match.group(1).upper()
                if sym not in {'PT', 'SL', 'HIT', 'ALL', 'THE', 'OUT', 'AND', 'FOR', 'BUT',
                              'FAT', 'HOLY', 'BOOM', 'WIN', 'WOW', 'GOD', 'NICE', 'LETS',
                              'REST', 'HERE', 'BE', 'AT', 'THIS', 'THAT', 'JUST', 'WENT'}:
                    ticker = sym

        if not ticker:
            continue

        block_upper = block_clean.upper()

        exit_price = None
        m = EXIT_OUT_PATTERN.search(block_clean)
        if m:
            exit_price = _parse_price(m.group(1))
        if exit_price is None:
            m = EXIT_SOLD_PATTERN.search(block_clean)
            if m:
                exit_price = _parse_price(m.group(1))
        if exit_price is None:
            m = EXIT_SOLD_HALF_PATTERN.search(block_clean)
            if m:
                exit_price = _parse_price(m.group(1))

        sell_pct = None
        is_partial = False
        for pat, pct in PARTIAL_EXIT_PATTERNS:
            if pat.search(block_clean):
                sell_pct = pct
                is_partial = True
                break

        has_out_keyword = bool(EXIT_OUT_KEYWORD.search(block_clean))

        sl_update = None
        if SL_ENTRY_PATTERN.search(block_clean):
            sl_update = 'entry'
        else:
            sl_m = SL_PRICE_PATTERN.search(block_clean)
            if sl_m:
                sl_update = _parse_price(sl_m.group(1))

        is_all_pts = bool(re.search(r"ALL\s+(?:PT'?S?|PRICE\s+TARGETS?)\s+HIT", block_upper))
        is_pt_hit = bool(re.search(r'PT\s*\d\s*(?:&\s*\d\s*)?HIT|HIT\s+PT\s*\d', block_upper))

        is_celebratory = False
        if not has_out_keyword and not exit_price and not is_partial and not sl_update:
            if any(p.search(block_clean) for p in CELEBRATORY_ONLY_PATTERNS):
                is_celebratory = True
            if is_pt_hit and not has_out_keyword:
                is_celebratory = True
            if is_all_pts and not has_out_keyword:
                is_celebratory = True

        if is_celebratory:
            print(f"[EQUITY-GENIE] ℹ️ EXIT celebratory/informational for {ticker}: {block_clean[:80]}")
            continue

        is_actionable = has_out_keyword or exit_price is not None or is_partial

        if not is_actionable and not sl_update:
            print(f"[EQUITY-GENIE] ℹ️ EXIT skipped (not actionable) for {ticker}: {block_clean[:80]}")
            continue

        if not is_actionable and sl_update:
            action_type = 'SL_UPDATE'
        elif is_partial and sell_pct:
            action_type = 'STC_PARTIAL'
        else:
            action_type = 'STC'

        signal = {
            'format': 'EQUITY_GENIE',
            'action': action_type,
            'ticker': ticker,
            'symbol': ticker,
            'exit_price': exit_price,
            'sell_pct': sell_pct,
            'is_partial': is_partial,
            'asset': 'stock',
            'asset_type': 'stock',
            '_equity_genie': True,
            '_equity_genie_exit': True,
            '_original_message': block_clean,
        }

        if sl_update is not None:
            signal['sl_update'] = sl_update

        exit_desc = f"${exit_price}" if exit_price else "market"
        partial_desc = f" ({sell_pct}%)" if sell_pct else ""
        sl_desc = f" | SL→{sl_update}" if sl_update else ""
        print(f"[EQUITY-GENIE] ✓ Parsed EXIT: {action_type} {ticker} @ {exit_desc}{partial_desc}{sl_desc}")

        results.append(signal)

    return results


def parse_equity_genie_embed(embed_title: str, embed_description: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    title_upper = (embed_title or '').upper().strip()

    if title_upper in VALID_ENTRY_TITLES:
        entries = parse_equity_genie_entries(embed_title, embed_description)
        return entries, []

    if title_upper in VALID_EXIT_TITLES:
        exits = parse_equity_genie_exits(embed_title, embed_description)
        return [], exits

    return [], []
