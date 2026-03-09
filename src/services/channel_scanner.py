"""
Channel Scanner Service - Pattern Discovery Engine
====================================================
Scans Discord channel message history and automatically discovers
signal formats using pure regex/heuristic analysis (no AI).

Detects: Entries (BTO), Exits (STC), Partial Exits (Trim),
         SL/PT Updates, and embed-based signals.
"""

import re
import hashlib
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime


TICKER_RE = re.compile(r'\$?[A-Z]{1,6}')
PRICE_RE = re.compile(r'\$?\d+(?:\.\d{1,4})?')
STRIKE_RE = re.compile(r'\d+(?:\.\d{1,2})?[CPcp]')
EXPIRY_SLASH_RE = re.compile(r'\d{1,2}/\d{1,2}(?:/\d{2,4})?')
EXPIRY_ALPHA_RE = re.compile(r'\d{1,2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2,4}', re.IGNORECASE)
PCT_RE = re.compile(r'\d+(?:\.\d+)?%')
QTY_RE = re.compile(r'(?:^|\s)(\d{1,4})(?:\s)')


ENTRY_KEYWORDS = [
    'bto', 'buy', 'buying', 'bought', 'entering', 'entry', 'opening',
    'taking a position', 'back in', 'adding', 'avg', 'average',
    'i\'m entering', 'im entering', 'long', 'calls', 'puts',
    'lotto', 'swing', 'day trade', 'scalp', 'alert'
]

EXIT_KEYWORDS = [
    'stc', 'sell', 'sold', 'selling', 'closing', 'exit', 'exiting',
    'out of', 'all out', 'closed', 'stopped out', 'done with',
    'flat', 'taking profits', 'profit taken'
]

TRIM_KEYWORDS = [
    'trim', 'trimming', 'trimmed', 'partial', 'half out',
    'took half', 'took some', 'scaling out', 'locking in',
    'runners', 'holding runners', 'holding most', 'holding half',
    '25%', '50%', '75%', 'took profits on half', 'reduced'
]

UPDATE_KEYWORDS = [
    'sl to', 'stop loss', 'stop to', 'moving stop', 'raise stop',
    'trail stop', 'trailing', 'pt to', 'target', 'profit target',
    'new sl', 'new stop', 'breakeven', 'b/e', 'move stop'
]


@dataclass
class ScannedMessage:
    content: str
    embed_text: str
    full_text: str
    has_embeds: bool
    timestamp: str
    message_id: str
    author_id: str
    author_name: str


@dataclass
class DetectedPattern:
    name: str
    action: str
    asset_type: str
    regex_pattern: str
    example_messages: List[str]
    match_count: int
    total_scanned: int
    confidence: float
    is_embed: bool
    description: str
    template: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'action': self.action,
            'asset_type': self.asset_type,
            'regex_pattern': self.regex_pattern,
            'example_messages': self.example_messages[:5],
            'match_count': self.match_count,
            'total_scanned': self.total_scanned,
            'confidence': round(self.confidence, 2),
            'is_embed': self.is_embed,
            'description': self.description,
            'template': self.template
        }


def flatten_embed(embed_data: Dict) -> str:
    parts = []
    if embed_data.get('title'):
        parts.append(embed_data['title'])
    if embed_data.get('description'):
        parts.append(embed_data['description'])
    for f in embed_data.get('fields', []):
        parts.append(f"{f.get('name', '')}: {f.get('value', '')}")
    return ' | '.join(parts)


def classify_action(text: str) -> str:
    lower = text.lower()

    for kw in TRIM_KEYWORDS:
        if kw in lower:
            return 'TRIM'

    for kw in UPDATE_KEYWORDS:
        if kw in lower:
            return 'UPDATE'

    for kw in EXIT_KEYWORDS:
        if kw in lower:
            return 'STC'

    for kw in ENTRY_KEYWORDS:
        if kw in lower:
            return 'BTO'

    return 'UNKNOWN'


def detect_asset_type(text: str) -> str:
    lower = text.lower()
    if STRIKE_RE.search(text):
        return 'option'
    if any(kw in lower for kw in ['call', 'put', 'calls', 'puts', 'strike', 'expir', 'c ', 'p ', '0dte']):
        return 'option'
    return 'stock'


def normalize_to_template(text: str) -> str:
    t = text.strip()
    t = re.sub(r'<@[!&]?\d+>', '', t)
    t = re.sub(r'<#\d+>', '', t)
    t = re.sub(r'https?://\S+', '', t)

    slots = []
    def _slot(tag):
        idx = len(slots)
        slots.append(tag)
        return f'\x00{idx}\x00'

    t = re.sub(r'\d{1,2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2,4}', lambda m: _slot('EXPIRY'), t, flags=re.IGNORECASE)
    t = re.sub(r'\d{1,2}/\d{1,2}(?:/\d{2,4})?', lambda m: _slot('EXPIRY'), t)
    t = re.sub(r'\d+(?:\.\d{1,2})?[CPcp](?=\s|$|@|\*)', lambda m: _slot('STRIKE'), t)
    t = re.sub(r'\$\d+(?:\.\d{1,4})?', lambda m: _slot('PRICE'), t)
    t = re.sub(r'(@\s?)\d+(?:\.\d{1,4})?', lambda m: m.group(1) + _slot('PRICE'), t)
    t = re.sub(r'(?:(?:^|(?<=\s))\.)?\d+(?:\.\d{1,4})?(?=\s|\*|$)', lambda m: _slot('PRICE') if m.group(0).strip() else m.group(0), t)
    t = re.sub(r'\d+(?:\.\d+)?%', lambda m: _slot('PCT'), t)
    t = re.sub(r'\$[A-Z]{1,6}', lambda m: _slot('TICKER'), t)

    SKIP_WORDS = {'ENTRY', 'TRIM', 'EXIT', 'BTO', 'STC', 'BUY', 'SELL', 'SL', 'PT', 'TP',
                  'OPEN', 'CLOSE', 'ALERT', 'SOLD', 'OUT', 'OF', 'THE', 'FOR', 'AND',
                  'IN', 'AT', 'TO', 'MY', 'IS', 'IT', 'OR', 'UP', 'BY', 'NO', 'ON',
                  'ALL', 'WITH', 'HERE', 'MORE', 'NOTES', 'VALUE', 'LOTTO', 'SMALL',
                  'SELLING', 'BUYING', 'TRIMMING', 'REMAINING', 'SHARES', 'LOSS',
                  'RUNNERS', 'HOLDING', 'HALF', 'TOOK', 'DONE', 'FLAT', 'HOW', 'TRADE',
                  'I', 'A', 'C', 'P'}
    def _replace_ticker(m):
        word = m.group(0)
        if word in SKIP_WORDS:
            return word
        return _slot('TICKER')
    t = re.sub(r'(?<![A-Za-z\x00])[A-Z]{1,6}(?![a-z\x00])', _replace_ticker, t)
    t = re.sub(r'(?:^|\s)\d{1,4}(?=\s)', lambda m: ' ' + _slot('QTY'), t)

    for i, tag in enumerate(slots):
        t = t.replace(f'\x00{i}\x00', '{' + tag + '}')
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def template_to_regex(template: str) -> str:
    r = re.escape(template)
    r = r.replace(r'\{TICKER\}', r'\$?([A-Za-z]{1,6})')
    r = r.replace(r'\{PRICE\}', r'\.?(\d+(?:\.\d{1,4})?)')
    r = r.replace(r'\{STRIKE\}', r'(\d+(?:\.\d{1,2})?[CPcp])')
    r = r.replace(r'\{EXPIRY\}', r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)')
    r = r.replace(r'\{PCT\}', r'(\d+(?:\.\d+)?%)')
    r = r.replace(r'\{QTY\}', r'(\d{1,4})')
    r = re.sub(r'(?:\\ )+', r'\\s+', r)
    r = re.sub(r'@everyone\\s\+', r'(?:@everyone\\s+)?', r)
    r = re.sub(r'^', r'(?:<@&\\d+>\\s+)?', r, count=1)
    return r


def generate_pattern_name(action: str, template: str, index: int) -> str:
    action_names = {
        'BTO': 'entry',
        'STC': 'exit',
        'TRIM': 'trim',
        'UPDATE': 'update'
    }
    action_label = action_names.get(action, 'signal')

    has_strike = '{STRIKE}' in template
    has_expiry = '{EXPIRY}' in template
    has_price = '{PRICE}' in template

    if has_strike and has_expiry:
        detail = 'option_full'
    elif has_strike:
        detail = 'option'
    elif has_price:
        detail = 'with_price'
    else:
        detail = 'basic'

    return f"scan_{action_label}_{detail}_{index}"


def scan_messages(messages: List[Dict[str, Any]]) -> List[DetectedPattern]:
    scanned: List[ScannedMessage] = []
    for msg in messages:
        content = msg.get('content', '') or ''
        embed_parts = []
        has_embeds = False

        for emb in msg.get('embeds', []):
            has_embeds = True
            embed_parts.append(flatten_embed(emb))

        embed_text = ' | '.join(embed_parts)
        full_text = f"{content} {embed_text}".strip() if embed_text else content.strip()

        if len(full_text) < 3:
            continue

        scanned.append(ScannedMessage(
            content=content,
            embed_text=embed_text,
            full_text=full_text,
            has_embeds=has_embeds,
            timestamp=msg.get('timestamp', ''),
            message_id=str(msg.get('message_id', '')),
            author_id=str(msg.get('author_id', '')),
            author_name=msg.get('author_name', '')
        ))

    if not scanned:
        return []

    classified: Dict[str, List[ScannedMessage]] = defaultdict(list)
    for sm in scanned:
        action = classify_action(sm.full_text)
        if action != 'UNKNOWN':
            classified[action].append(sm)

    template_groups: Dict[str, Dict[str, List[ScannedMessage]]] = defaultdict(lambda: defaultdict(list))
    for action, msgs in classified.items():
        for sm in msgs:
            tmpl = normalize_to_template(sm.full_text)
            if len(tmpl) < 5:
                continue
            template_groups[action][tmpl].append(sm)

    patterns: List[DetectedPattern] = []
    global_idx = 0

    for action in ['BTO', 'STC', 'TRIM', 'UPDATE']:
        if action not in template_groups:
            continue

        sorted_templates = sorted(
            template_groups[action].items(),
            key=lambda x: len(x[1]),
            reverse=True
        )

        seen_similar = set()

        for tmpl, msgs in sorted_templates:
            if len(msgs) < 2:
                continue

            simplified = re.sub(r'\{[A-Z]+\}', '*', tmpl)
            if simplified in seen_similar:
                continue
            seen_similar.add(simplified)

            global_idx += 1
            regex = template_to_regex(tmpl)

            try:
                re.compile(regex, re.IGNORECASE)
            except re.error:
                continue

            asset = detect_asset_type(msgs[0].full_text)
            examples = [m.full_text[:200] for m in msgs[:5]]
            confidence = min(len(msgs) / max(len(scanned), 1) * 10, 1.0)
            confidence = max(confidence, len(msgs) / 100.0)
            confidence = min(confidence, 0.99)

            is_embed = any(m.has_embeds for m in msgs)
            name = generate_pattern_name(action, tmpl, global_idx)

            has_ticker = '{TICKER}' in tmpl
            has_price = '{PRICE}' in tmpl or '{STRIKE}' in tmpl
            if not has_ticker and not has_price:
                continue

            patterns.append(DetectedPattern(
                name=name,
                action=action,
                asset_type=asset,
                regex_pattern=regex,
                example_messages=examples,
                match_count=len(msgs),
                total_scanned=len(scanned),
                confidence=confidence,
                is_embed=is_embed,
                description=f"Auto-detected {action} pattern ({len(msgs)} matches in {len(scanned)} messages)",
                template=tmpl
            ))

    patterns.sort(key=lambda p: p.match_count, reverse=True)
    return patterns[:30]


async def scan_channel_history(bot_instance, channel_id: int, limit: int = 1000, raw_only: bool = False) -> Dict[str, Any]:
    try:
        target_channel = bot_instance.get_channel(channel_id)
        if not target_channel:
            try:
                target_channel = await bot_instance.fetch_channel(channel_id)
            except Exception as e:
                return {'success': False, 'error': f'Cannot access channel {channel_id}: {e}'}

        messages_data = []
        count = 0

        async for msg in target_channel.history(limit=limit):
            count += 1

            embed_data = []
            if msg.embeds:
                for embed in msg.embeds:
                    embed_info = {}
                    if embed.title:
                        embed_info['title'] = embed.title
                    if embed.description:
                        embed_info['description'] = embed.description
                    if embed.fields:
                        embed_info['fields'] = [{'name': f.name, 'value': f.value} for f in embed.fields]
                    if embed_info:
                        embed_data.append(embed_info)

            messages_data.append({
                'content': msg.content or '',
                'embeds': embed_data,
                'timestamp': msg.created_at.isoformat() if msg.created_at else '',
                'message_id': str(msg.id),
                'author_id': str(msg.author.id) if msg.author else '',
                'author_name': str(msg.author) if msg.author else ''
            })

        print(f"[SCANNER] Fetched {count} messages from channel {channel_id}")

        channel_name = getattr(target_channel, 'name', str(channel_id))

        if raw_only:
            from datetime import datetime as _dt
            return {
                'success': True,
                'channel_id': str(channel_id),
                'channel_name': channel_name,
                'extracted_at': _dt.now().isoformat(),
                'message_count': count,
                'messages': messages_data
            }

        detected = scan_messages(messages_data)

        print(f"[SCANNER] Detected {len(detected)} patterns from {count} messages")
        for p in detected:
            print(f"[SCANNER]   {p.action} '{p.name}': {p.match_count} matches, confidence={p.confidence:.2f}")

        return {
            'success': True,
            'channel_id': str(channel_id),
            'channel_name': channel_name,
            'messages_scanned': count,
            'patterns': [p.to_dict() for p in detected],
            'summary': {
                'total_patterns': len(detected),
                'entry_patterns': sum(1 for p in detected if p.action == 'BTO'),
                'exit_patterns': sum(1 for p in detected if p.action == 'STC'),
                'trim_patterns': sum(1 for p in detected if p.action == 'TRIM'),
                'update_patterns': sum(1 for p in detected if p.action == 'UPDATE'),
            }
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e)}
