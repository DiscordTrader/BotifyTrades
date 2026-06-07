"""
Format Learning Pipeline
========================
Industry-grade auto-learning pipeline for Discord trading signal formats.

Flow:
  1. Extract channel history (1000 msgs) into channel_messages DB
  2. Buffer live messages continuously
  3. User triggers analysis → hybrid heuristic + AI discovery
  4. Present candidates for user approval
  5. Approved formats register into SignalFormatRegistry

All entries require user approval before execution.
"""

import json
import re
from datetime import datetime
from typing import Optional, Dict, List, Any


def extract_history_to_db(bot_client, channel_id: int, limit: int = 1000) -> Dict:
    """Extract channel history and save to channel_messages DB.
    Must be called from async context via asyncio.to_thread or similar.
    Returns stats dict."""
    import asyncio

    async def _extract():
        from gui_app import database as db

        target_channel = bot_client.get_channel(channel_id)
        if not target_channel:
            try:
                target_channel = await bot_client.fetch_channel(channel_id)
            except Exception:
                pass
        if not target_channel:
            for guild in bot_client.guilds:
                try:
                    target_channel = guild.get_thread(channel_id)
                    if target_channel:
                        break
                    target_channel = await guild.fetch_channel(channel_id)
                    if target_channel:
                        break
                except Exception:
                    continue

        if not target_channel:
            return {'success': False, 'error': f'Cannot access channel {channel_id}'}

        channel_name = getattr(target_channel, 'name', str(channel_id))
        count = 0
        saved = 0

        async for msg in target_channel.history(limit=limit):
            count += 1
            if msg.content and msg.content.strip():
                ok = db.save_channel_message(
                    channel_id=str(channel_id),
                    message_content=msg.content.strip(),
                    channel_name=channel_name,
                    author_id=str(msg.author.id),
                    author_name=msg.author.name,
                    message_id=str(msg.id)
                )
                if ok:
                    saved += 1

        db.set_learning_state(
            str(channel_id), 'buffering',
            history_extracted=1,
            messages_buffered=saved
        )

        return {
            'success': True,
            'channel_name': channel_name,
            'total_fetched': count,
            'messages_saved': saved,
        }

    loop = asyncio.get_event_loop()
    if loop.is_running():
        raise RuntimeError("Use async_extract_history_to_db() in async context instead")
    return loop.run_until_complete(_extract())


async def async_extract_history_to_db(bot_client, channel_id: int, limit: int = 1000) -> Dict:
    """Async version: extract channel history into channel_messages DB."""
    from gui_app import database as db

    target_channel = bot_client.get_channel(channel_id)
    if not target_channel:
        try:
            target_channel = await bot_client.fetch_channel(channel_id)
        except Exception:
            pass
    if not target_channel:
        for guild in bot_client.guilds:
            try:
                target_channel = guild.get_thread(channel_id)
                if target_channel:
                    break
                target_channel = await guild.fetch_channel(channel_id)
                if target_channel:
                    break
            except Exception:
                continue

    if not target_channel:
        return {'success': False, 'error': f'Cannot access channel {channel_id}'}

    channel_name = getattr(target_channel, 'name', str(channel_id))
    count = 0
    saved = 0

    async for msg in target_channel.history(limit=limit):
        count += 1
        if msg.content and msg.content.strip():
            ok = db.save_channel_message(
                channel_id=str(channel_id),
                message_content=msg.content.strip(),
                channel_name=channel_name,
                author_id=str(msg.author.id),
                author_name=msg.author.name,
                message_id=str(msg.id)
            )
            if ok:
                saved += 1

    db.set_learning_state(
        str(channel_id), 'buffering',
        history_extracted=1,
        messages_buffered=saved
    )

    print(f"[FORMAT_LEARN] Extracted {saved}/{count} messages from {channel_name} into DB")
    return {
        'success': True,
        'channel_name': channel_name,
        'total_fetched': count,
        'messages_saved': saved,
    }


def analyze_channel_formats(channel_id: str) -> Dict:
    """Run hybrid analysis (heuristic + AI) on buffered messages.
    Returns discovered format candidates."""
    from gui_app import database as db
    from gui_app.format_trainer import get_format_trainer
    from gui_app.config_service import get_ai_provider

    messages = db.get_recent_channel_messages(str(channel_id), limit=1000)
    if not messages:
        return {'success': False, 'error': 'No messages buffered for this channel. Extract history first.'}

    msg_count = len(messages)
    channels_info = db.get_all_channels_with_messages()
    channel_name = next((ch['channel_name'] for ch in channels_info if ch['channel_id'] == str(channel_id)), 'Unknown')

    print(f"[FORMAT_LEARN] Analyzing {msg_count} messages from {channel_name}")

    # Phase 1: Heuristic scan (free, fast)
    heuristic_results = _run_heuristic_scan(messages)
    print(f"[FORMAT_LEARN] Heuristic: {len(heuristic_results)} patterns found")

    # Phase 2: AI scan (smart, uses API)
    ai_results = []
    ai_provider = get_ai_provider()
    if ai_provider != 'disabled':
        try:
            trainer = get_format_trainer()
            if trainer.is_ai_available():
                ai_batch_size = 100
                for i in range(0, min(len(messages), 500), ai_batch_size):
                    batch = messages[i:i + ai_batch_size]
                    result = trainer.discover_formats_from_messages(batch, channel_name)
                    if result.get('success'):
                        for fs in result.get('formats_saved', []):
                            ai_results.append({
                                'format_name': fs.get('name', f'ai_format_{len(ai_results)}'),
                                'confidence': fs.get('confidence', 0.7),
                                'example_message': fs.get('example', ''),
                                'action': 'BTO',
                                'method': 'ai',
                            })
                print(f"[FORMAT_LEARN] AI: {len(ai_results)} patterns found (provider={ai_provider})")
        except Exception as e:
            print(f"[FORMAT_LEARN] AI analysis error: {e}")
    else:
        print(f"[FORMAT_LEARN] AI disabled, using heuristic only")

    # Phase 3: Cross-validate and merge
    candidates = _merge_and_score(heuristic_results, ai_results, messages, ai_provider)
    print(f"[FORMAT_LEARN] Merged: {len(candidates)} candidates")

    # Phase 4: Deduplicate against existing registry
    candidates = _deduplicate_against_registry(candidates, messages)
    print(f"[FORMAT_LEARN] After dedup: {len(candidates)} candidates")

    # Phase 5: Save candidates to DB
    saved_count = 0
    for c in candidates:
        if c['confidence'] < 0.40:
            continue
        cid = db.save_format_candidate(
            channel_id=str(channel_id),
            format_name=c['format_name'],
            action=c['action'],
            asset_type=c.get('asset_type', 'stock'),
            regex_pattern=c.get('regex_pattern', ''),
            example_messages=json.dumps(c.get('examples', [])[:5]),
            parsed_example=json.dumps(c.get('parsed_example', {})),
            confidence=c['confidence'],
            match_count=c.get('match_count', 0),
            total_scanned=msg_count,
            discovery_method=c.get('method', 'hybrid'),
            ai_provider=ai_provider if ai_provider != 'disabled' else None,
        )
        if cid:
            saved_count += 1

    db.set_learning_state(
        str(channel_id), 'pending_approval',
        last_analysis_at=datetime.now().isoformat(),
        analysis_count=(db.get_learning_state(str(channel_id)) or {}).get('analysis_count', 0) + 1,
    )

    return {
        'success': True,
        'channel_name': channel_name,
        'messages_analyzed': msg_count,
        'heuristic_patterns': len(heuristic_results),
        'ai_patterns': len(ai_results),
        'candidates_saved': saved_count,
        'candidates': candidates,
    }


def _run_heuristic_scan(messages: List[str]) -> List[Dict]:
    """Run rule-based pattern detection on messages."""
    patterns = {}

    entry_re = re.compile(
        r'(?:BTO|BUY|BUYING|LONG|BOUGHT|ENTRY|ENTERING)\s+'
        r'\$?([A-Z]{1,5})',
        re.IGNORECASE
    )
    exit_re = re.compile(
        r'(?:STC|SELL|SELLING|SOLD|OUT|EXIT|EXITING|CLOSING|CLOSED|TRIM)\s+'
        r'\$?([A-Z]{1,5})',
        re.IGNORECASE
    )
    emoji_entry_re = re.compile(r'[✅▶🟢]\s*\$?([A-Z]{1,5})(?:\s|$)', re.IGNORECASE)
    emoji_exit_re = re.compile(r'[❌⛔🔴]\s*\$?([A-Z]{1,5})(?:\s|$)', re.IGNORECASE)
    dollar_ticker_re = re.compile(r'\$([A-Za-z]{1,5})\s+', re.IGNORECASE)
    option_re = re.compile(
        r'\$?([A-Z]{1,5})\s+\$?(\d+(?:\.\d+)?)\s*([CcPp])\s',
        re.IGNORECASE
    )

    non_tickers = {'THE', 'FOR', 'AND', 'ALL', 'OUT', 'BTO', 'STC', 'BUY', 'SELL',
                   'SL', 'PT', 'TP', 'NOT', 'HAS', 'WAS', 'ARE', 'CAN', 'MAY',
                   'CEO', 'IPO', 'ATH', 'FDA', 'NEW', 'OIL', 'DAY', 'AH',
                   'USD', 'GET', 'SET', 'NOW', 'RUN', 'TOP', 'RED', 'HOT', 'BIG', 'LOW',
                   'LET', 'PUT', 'GOT', 'DID', 'SAY', 'USE', 'TRY', 'ANY', 'FEW'}

    for msg in messages:
        if not msg or len(msg) < 3:
            continue

        if entry_re.search(msg):
            _add_pattern(patterns, 'heuristic_bto_keyword', 'BTO', msg, 'stock')
        if exit_re.search(msg):
            _add_pattern(patterns, 'heuristic_stc_keyword', 'STC', msg, 'stock')
        if emoji_entry_re.search(msg):
            sym = emoji_entry_re.search(msg).group(1).upper()
            if sym not in non_tickers:
                _add_pattern(patterns, 'heuristic_emoji_entry', 'BTO', msg, 'stock')
        if emoji_exit_re.search(msg):
            _add_pattern(patterns, 'heuristic_emoji_exit', 'STC', msg, 'stock')
        if option_re.search(msg):
            opt_action = 'STC' if exit_re.search(msg) else 'BTO'
            _add_pattern(patterns, f'heuristic_option_{opt_action.lower()}', opt_action, msg, 'option')
        if dollar_ticker_re.search(msg) and re.search(r'\d+(?:\.\d+)?', msg):
            sym = dollar_ticker_re.search(msg).group(1).upper()
            if sym not in non_tickers and len(sym) >= 2:
                _add_pattern(patterns, 'heuristic_dollar_ticker', 'BTO', msg, 'stock')

    results = []
    for name, data in patterns.items():
        if data['count'] >= 3:
            results.append({
                'format_name': name,
                'action': data['action'],
                'asset_type': data['asset_type'],
                'examples': data['examples'][:5],
                'match_count': data['count'],
                'confidence': min(0.5 + (data['count'] / 100), 0.80),
                'method': 'heuristic',
            })
    return results


def _add_pattern(patterns, name, action, msg, asset_type):
    if name not in patterns:
        patterns[name] = {'action': action, 'asset_type': asset_type, 'count': 0, 'examples': []}
    patterns[name]['count'] += 1
    if len(patterns[name]['examples']) < 10:
        patterns[name]['examples'].append(msg[:150])


def _merge_and_score(heuristic: List[Dict], ai: List[Dict],
                     messages: List[str], ai_provider: str) -> List[Dict]:
    """Merge heuristic and AI results, cross-validate, score."""
    candidates = {}

    for h in heuristic:
        name = h['format_name']
        candidates[name] = {
            **h,
            'found_by': ['heuristic'],
        }

    for a in ai:
        name = a.get('name', a.get('format_name', f'ai_format_{len(candidates)}'))
        if name in candidates:
            candidates[name]['confidence'] = min(
                candidates[name]['confidence'] + 0.15, 0.99
            )
            candidates[name]['found_by'].append('ai')
            candidates[name]['method'] = 'hybrid'
            if a.get('suggested_regex'):
                candidates[name]['regex_pattern'] = a['suggested_regex']
            if a.get('parsed_example'):
                candidates[name]['parsed_example'] = a['parsed_example']
        else:
            candidates[name] = {
                'format_name': name,
                'action': a.get('action', a.get('parsed_example', {}).get('action', 'BTO')).upper(),
                'asset_type': a.get('asset_type', a.get('format_type', 'stock')),
                'examples': [a.get('example_message', '')] if a.get('example_message') else [],
                'match_count': a.get('message_count', 1),
                'confidence': a.get('confidence', 0.70),
                'method': 'ai',
                'regex_pattern': a.get('suggested_regex', ''),
                'parsed_example': a.get('parsed_example', {}),
                'found_by': ['ai'],
            }

    return list(candidates.values())


def _deduplicate_against_registry(candidates: List[Dict], messages: List[str]) -> List[Dict]:
    """Remove candidates that match existing builtin formats."""
    try:
        from src.services.signal_format_registry import SignalFormatRegistry
        registry = SignalFormatRegistry()

        builtin_matched = set()
        for msg in messages[:200]:
            results = registry.parse_all(msg)
            for r in results:
                fmt_name = r.get('_format_name', '')
                if fmt_name and not fmt_name.startswith('learned_'):
                    builtin_matched.add(fmt_name)

        if builtin_matched:
            print(f"[FORMAT_LEARN] Existing builtins already matching: {builtin_matched}")

        filtered = []
        for c in candidates:
            if c.get('match_count', 0) < 3:
                continue
            if c.get('format_name', '') in builtin_matched:
                print(f"[FORMAT_LEARN] Skipping '{c['format_name']}' — builtin already covers this")
                continue
            filtered.append(c)
        return filtered
    except Exception as e:
        print(f"[FORMAT_LEARN] Dedup error: {e}")
        return candidates


def format_candidates_for_display(channel_id: str) -> str:
    """Format candidates as readable text for chatbot display."""
    from gui_app import database as db
    candidates = db.get_format_candidates(channel_id, status='pending')

    if not candidates:
        return "No pending format candidates for this channel."

    lines = [f"**Format Candidates ({len(candidates)} pending)**\n"]
    for c in candidates:
        conf_pct = c['confidence'] * 100
        conf_color = "🟢" if conf_pct >= 80 else "🟡" if conf_pct >= 60 else "🔴"
        try:
            raw = c.get('example_messages') or '[]'
            examples = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (json.JSONDecodeError, TypeError):
            examples = []

        lines.append(f"**#{c['id']}** — {c['format_name']} {conf_color} {conf_pct:.0f}%")
        lines.append(f"  Action: {c['action']} | Asset: {c['asset_type']} | Method: {c['discovery_method']}")
        lines.append(f"  Matches: {c['match_count']}/{c['total_scanned']} messages")
        if examples:
            lines.append(f"  Examples:")
            for ex in examples[:3]:
                lines.append(f"    `{ex[:80]}`")
        lines.append("")

    lines.append("**Commands:**")
    lines.append("- `approve format #ID` — Approve a format for this channel")
    lines.append("- `reject format #ID` — Reject a format")
    lines.append("- `approve all formats` — Approve all pending formats")

    return "\n".join(lines)
