"""
Signal Correction Service — typo/fuzzy ticker correction for exit signals.

Two-layer approach:
  Layer 1: Levenshtein fuzzy match against open positions in same channel (stdlib, free)
  Layer 2: AI exit-intent parsing with position context (focused prompt, not general parser)

Six safety gates:
  1. Exit intent keyword required before any correction fires
  2. Fuzzy ambiguity: 2+ candidates at same min distance → hard reject
  3. AI output symbol must exist in open positions (hard post-validation)
  4. Minimum position age 60s (prevents BTO fill message misread as exit)
  5. Channel scope only (never cross-channel matching)
  6. Per-channel opt-out via ChannelRiskSettings.typo_correction_enabled
  + Short tickers (≤2 chars) exempt from fuzzy (AA/AI/MA too short to correct safely)
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ── Exit intent detection ─────────────────────────────────────────────────────
_EXIT_INTENT_RE = re.compile(
    r'\b(out|sold|sell(?:ing)?|exit(?:ed|ing)?|clos(?:e[sd]?|ing)|'
    r'STC|stop\s*hit|SL\s*hit|hit\s*my\s*SL|took\s*the\s*loss|'
    r'stopped\s*out|dumped|trim(?:med)?|locked)\b',
    re.IGNORECASE,
)

# Max Levenshtein distance allowed per ticker length (gate: short tickers → 0 = no fuzzy)
_MAX_DIST_BY_LEN: Dict[int, int] = {1: 0, 2: 0, 3: 1, 4: 1}
_MAX_DIST_DEFAULT = 2  # length >= 5


# ── Core data type ────────────────────────────────────────────────────────────
@dataclass
class CorrectionResult:
    corrected_symbol: Optional[str] = None   # None = no correction found/safe
    original_symbol: str = ''
    correction_method: str = 'none'           # 'fuzzy' | 'ai' | 'none' | 'ambiguous'
    edit_distance: Optional[int] = None
    confidence: float = 0.0
    rejected: bool = False                    # True = ambiguous, caller must NOT execute
    reason: str = ''
    _cached_at: float = 0.0


# ── Pure functions (testable, no side effects) ────────────────────────────────
def levenshtein_distance(a: str, b: str) -> int:
    """Standard DP Levenshtein — stdlib only, no external deps."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for ca in a:
        curr = [prev[0] + 1] + [0] * lb
        for j, cb in enumerate(b, 1):
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = curr
    return prev[lb]


def has_exit_intent(text: str) -> bool:
    return bool(_EXIT_INTENT_RE.search(text))


def _max_dist(ticker: str) -> int:
    return _MAX_DIST_BY_LEN.get(len(ticker), _MAX_DIST_DEFAULT)


def _position_age_ok(entry_time: str) -> bool:
    """Gate 4: position must be older than 60s before it can be an exit candidate."""
    if not entry_time:
        return True
    try:
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S.%f'):
            try:
                dt = datetime.strptime(entry_time[:19], fmt[:19])
                return (datetime.utcnow() - dt).total_seconds() >= 60
            except ValueError:
                continue
    except Exception:
        pass
    return True


def compute_fuzzy_candidates(
    ticker: str, open_positions: List[Dict[str, Any]]
) -> List[Tuple[str, int]]:
    """
    Returns [(symbol, distance), ...] sorted ascending by distance.
    Only includes candidates within the threshold for the ticker length.
    Empty list = no correction needed (exact match found or no candidates).
    """
    t = ticker.upper()
    threshold = _max_dist(t)
    if threshold == 0:
        return []

    exact = any(p['symbol'] == t for p in open_positions)
    if exact:
        return []

    candidates = []
    for pos in open_positions:
        sym = pos['symbol']
        d = levenshtein_distance(t, sym)
        if d <= threshold:
            candidates.append((sym, d))

    candidates.sort(key=lambda x: x[1])
    return candidates


def get_open_symbols_for_channel(channel_id: str) -> List[Dict[str, Any]]:
    """Load open positions for channel from DB. Returns [{symbol, asset_type, entry_time, trade_id}]."""
    try:
        from gui_app.database import get_open_trades_by_channel
        rows = get_open_trades_by_channel(channel_id)
        result = []
        for row in rows:
            sym = (row.get('symbol') or '').upper().strip()
            if sym:
                result.append({
                    'symbol': sym,
                    'asset_type': row.get('asset_type', 'option'),
                    'entry_time': row.get('entry_time') or row.get('executed_at') or '',
                    'trade_id': row.get('id'),
                })
        return result
    except Exception as e:
        print(f'[CORRECTION] ⚠️ get_open_symbols_for_channel({channel_id}) failed: {e}')
        return []


# ── Layer 1: Fuzzy correction ─────────────────────────────────────────────────
async def try_fuzzy_correct_exit(
    parsed_symbol: str,
    channel_id: str,
    message_text: str,
    typo_correction_enabled: bool = True,
) -> CorrectionResult:
    """
    Fuzzy Levenshtein correction for an STC signal whose symbol has no open position.
    Returns CorrectionResult — caller checks .corrected_symbol and .rejected.
    """
    original = parsed_symbol.upper()

    if not typo_correction_enabled:
        return CorrectionResult(original_symbol=original, reason='correction disabled for channel')

    if not has_exit_intent(message_text):
        return CorrectionResult(original_symbol=original, reason='no exit intent in message')

    open_positions = get_open_symbols_for_channel(channel_id)
    if not open_positions:
        return CorrectionResult(original_symbol=original, reason='no open positions in channel')

    candidates = compute_fuzzy_candidates(original, open_positions)

    if not candidates:
        return CorrectionResult(original_symbol=original, reason=f'no fuzzy candidate within threshold for {original!r}')

    min_dist = candidates[0][1]
    top = [c for c in candidates if c[1] == min_dist]

    # Gate 2: ambiguity — multiple positions at same edit distance
    if len(top) > 1:
        syms = [c[0] for c in top]
        print(f'[CORRECTION] ⛔ AMBIGUOUS: {original!r} matches {syms} (all dist={min_dist}) — refusing to execute')
        return CorrectionResult(
            original_symbol=original,
            correction_method='ambiguous',
            rejected=True,
            reason=f"ambiguous: {original!r} could be {syms} (all distance {min_dist})",
        )

    corrected_sym, dist = top[0]

    # Gate 4: position must be older than 60s
    pos_entry = next((p for p in open_positions if p['symbol'] == corrected_sym), {})
    if not _position_age_ok(pos_entry.get('entry_time', '')):
        return CorrectionResult(
            original_symbol=original,
            reason=f'{corrected_sym} position too new (<60s) — skipping correction to avoid BTO/STC race',
        )

    print(f'[CORRECTION] ✅ Layer1 fuzzy: {original!r} → {corrected_sym!r} (dist={dist}, channel={channel_id})')
    return CorrectionResult(
        corrected_symbol=corrected_sym,
        original_symbol=original,
        correction_method='fuzzy',
        edit_distance=dist,
        confidence=round(1.0 - dist * 0.2, 2),
        reason=f'Levenshtein distance {dist}',
    )


# ── Layer 2: AI exit-intent correction ───────────────────────────────────────
async def try_ai_correct_exit(
    message_text: str,
    channel_id: str,
    typo_correction_enabled: bool = True,
) -> CorrectionResult:
    """
    AI-powered exit-intent detection with open position context.
    Uses a focused exit-intent prompt — NOT the general signal parser.
    Called when message has exit language but no ticker was parseable.
    """
    if not typo_correction_enabled:
        return CorrectionResult(reason='correction disabled for channel')

    if not has_exit_intent(message_text):
        return CorrectionResult(reason='no exit intent in message')

    open_positions = get_open_symbols_for_channel(channel_id)
    if not open_positions:
        return CorrectionResult(reason='no open positions in channel')

    try:
        from src.services.ai_signal_parser import get_ai_signal_parser
        parser = get_ai_signal_parser()
        return await parser.parse_exit_intent(message_text, open_positions)
    except Exception as e:
        print(f'[CORRECTION] ⚠️ AI exit-intent parse error: {e}')
        return CorrectionResult(reason=f'AI error: {e}')


# ── Singleton service (adds 5-min cache for fuzzy results) ───────────────────
class SignalCorrectionService:
    def __init__(self):
        self._cache: Dict[str, CorrectionResult] = {}
        self._ttl: float = 300.0

    def _cache_get(self, key: str) -> Optional[CorrectionResult]:
        r = self._cache.get(key)
        if r and (time.monotonic() - r._cached_at) < self._ttl:
            return r
        return None

    async def fuzzy_correct(
        self, parsed_symbol: str, channel_id: str,
        message_text: str, typo_correction_enabled: bool = True,
    ) -> CorrectionResult:
        key = f'fuzzy:{parsed_symbol.upper()}:{channel_id}'
        cached = self._cache_get(key)
        if cached:
            return cached
        result = await try_fuzzy_correct_exit(
            parsed_symbol, channel_id, message_text, typo_correction_enabled
        )
        result._cached_at = time.monotonic()
        self._cache[key] = result
        return result

    async def ai_correct(
        self, message_text: str, channel_id: str,
        typo_correction_enabled: bool = True,
    ) -> CorrectionResult:
        return await try_ai_correct_exit(message_text, channel_id, typo_correction_enabled)


_service_instance: Optional[SignalCorrectionService] = None


def get_signal_correction_service() -> SignalCorrectionService:
    global _service_instance
    if _service_instance is None:
        _service_instance = SignalCorrectionService()
    return _service_instance
