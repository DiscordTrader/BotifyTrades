"""Channel performance scoring — computes live 0-100 scores per channel.

Scores drive automatic position sizing adjustments.
Feature flag: 'channel_scoring' (OFF by default).
"""
import math
import time
import threading
from typing import Optional, Dict, Any, List

FEATURE_KEY = 'channel_scoring'

_score_cache: Dict[str, Dict[str, Any]] = {}
_cache_ts = 0.0
_CACHE_TTL = 60  # 1 minute
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def _ensure_table():
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_channel_scores (
                channel_id TEXT PRIMARY KEY,
                score INTEGER DEFAULT 50,
                win_rate_7d REAL DEFAULT 0,
                win_rate_30d REAL DEFAULT 0,
                win_rate_all REAL DEFAULT 0,
                avg_pnl_pct REAL DEFAULT 0,
                avg_win_pct REAL DEFAULT 0,
                avg_loss_pct REAL DEFAULT 0,
                profit_factor REAL DEFAULT 0,
                sharpe_ratio REAL DEFAULT 0,
                total_trades INTEGER DEFAULT 0,
                streak_current INTEGER DEFAULT 0,
                auto_sizing_multiplier REAL DEFAULT 1.0,
                last_computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'[AI_SCORING] Table init error: {e}')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def _normalize_win_rate(wr: float) -> float:
    """Map win rate 0-1 → 0-100 with S-curve centered at 0.50."""
    if wr <= 0:
        return 0.0
    if wr >= 1:
        return 100.0
    # Logistic transform: steepens around 50%
    return _clamp(100.0 / (1.0 + math.exp(-12 * (wr - 0.5))))


def _normalize_profit_factor(pf: float) -> float:
    """Map profit factor → 0-100. PF=1 → 40, PF=2 → 75, PF≥4 → 100."""
    if pf <= 0:
        return 0.0
    return _clamp(100.0 * (1.0 - math.exp(-0.5 * pf)))


def _normalize_sharpe(sr: float) -> float:
    """Map Sharpe ratio → 0-100. SR=0 → 30, SR=2 → 80, SR≥4 → ~100."""
    if sr <= -2:
        return 0.0
    return _clamp(50.0 + 25.0 * sr)


def _trend_score(wr_7d: float, wr_30d: float) -> float:
    """Positive if recent performance > longer-term. Range -100..100 → 0..100."""
    if wr_30d <= 0:
        return 50.0  # neutral when no 30d data
    delta = wr_7d - wr_30d  # e.g. +0.10 means 10pp improvement
    return _clamp(50.0 + delta * 500.0)  # ±0.10 → ±50 points


def _sample_size_score(n: int) -> float:
    """More trades → higher confidence. 50+ trades = full score."""
    if n <= 0:
        return 0.0
    return _clamp(100.0 * min(1.0, n / 50.0))


def _sizing_multiplier(score: int) -> float:
    """Map score → sizing multiplier. 90-100 → 1.2, 70-89 → 1.0, etc."""
    if score >= 90:
        return 1.2
    if score >= 70:
        return 1.0
    if score >= 50:
        return 0.7
    if score >= 30:
        return 0.3
    return 0.0  # 0-29 → effectively alert/disable


# ---------------------------------------------------------------------------
# Core compute
# ---------------------------------------------------------------------------

def _fetch_trades(channel_id: str, days: Optional[int] = None) -> list:
    """Fetch closed trades for a channel."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        if days:
            cursor.execute('''
                SELECT pnl_percent, closed_at FROM trades
                WHERE channel_id = ? AND status = 'CLOSED' AND direction = 'BTO'
                      AND closed_at > datetime('now', ? || ' days')
                ORDER BY closed_at DESC
            ''', (channel_id, f'-{days}'))
        else:
            cursor.execute('''
                SELECT pnl_percent, closed_at FROM trades
                WHERE channel_id = ? AND status = 'CLOSED' AND direction = 'BTO'
                ORDER BY closed_at DESC
            ''', (channel_id,))
        rows = [{'pnl_percent': r[0] or 0.0, 'closed_at': r[1]} for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f'[AI_SCORING] Trade fetch error: {e}')
        return []


def _compute_metrics(trades: list) -> Dict[str, float]:
    """Compute win rate, avg P&L, profit factor, Sharpe from a trade list."""
    if not trades:
        return {'win_rate': 0, 'avg_pnl': 0, 'avg_win': 0, 'avg_loss': 0,
                'profit_factor': 0, 'sharpe': 0, 'count': 0, 'streak': 0}

    wins = [t['pnl_percent'] for t in trades if t['pnl_percent'] > 0]
    losses = [t['pnl_percent'] for t in trades if t['pnl_percent'] <= 0]
    pnls = [t['pnl_percent'] for t in trades]

    win_rate = len(wins) / len(trades) if trades else 0
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 0)

    # Sharpe: mean / stdev of returns
    if len(pnls) >= 2:
        mean_r = sum(pnls) / len(pnls)
        variance = sum((p - mean_r) ** 2 for p in pnls) / (len(pnls) - 1)
        stdev = math.sqrt(variance) if variance > 0 else 1.0
        sharpe = mean_r / stdev
    else:
        sharpe = 0

    # Current streak (wins positive, losses negative)
    streak = 0
    for t in trades:  # already ordered by closed_at DESC
        if streak == 0:
            streak = 1 if t['pnl_percent'] > 0 else -1
        elif (streak > 0 and t['pnl_percent'] > 0):
            streak += 1
        elif (streak < 0 and t['pnl_percent'] <= 0):
            streak -= 1
        else:
            break

    return {
        'win_rate': win_rate, 'avg_pnl': avg_pnl, 'avg_win': avg_win,
        'avg_loss': avg_loss, 'profit_factor': profit_factor,
        'sharpe': sharpe, 'count': len(trades), 'streak': streak,
    }


def _compute_score(channel_id: str) -> Dict[str, Any]:
    """Full score computation for a single channel."""
    trades_7d = _fetch_trades(channel_id, 7)
    trades_30d = _fetch_trades(channel_id, 30)
    trades_all = _fetch_trades(channel_id)

    m7 = _compute_metrics(trades_7d)
    m30 = _compute_metrics(trades_30d)
    mall = _compute_metrics(trades_all)

    # Scoring formula
    wr_norm = _normalize_win_rate(m30['win_rate'])
    pf_norm = _normalize_profit_factor(m30['profit_factor'])
    sh_norm = _normalize_sharpe(m30['sharpe'])
    tr_norm = _trend_score(m7['win_rate'], m30['win_rate'])
    sz_norm = _sample_size_score(mall['count'])

    raw_score = (0.30 * wr_norm + 0.25 * pf_norm + 0.20 * sh_norm
                 + 0.15 * tr_norm + 0.10 * sz_norm)
    score = int(_clamp(round(raw_score), 0, 100))
    multiplier = _sizing_multiplier(score)

    return {
        'channel_id': channel_id,
        'score': score,
        'win_rate_7d': round(m7['win_rate'], 4),
        'win_rate_30d': round(m30['win_rate'], 4),
        'win_rate_all': round(mall['win_rate'], 4),
        'avg_pnl_pct': round(mall['avg_pnl'], 2),
        'avg_win_pct': round(mall['avg_win'], 2),
        'avg_loss_pct': round(mall['avg_loss'], 2),
        'profit_factor': round(m30['profit_factor'], 2),
        'sharpe_ratio': round(m30['sharpe'], 2),
        'total_trades': mall['count'],
        'streak_current': mall['streak'],
        'auto_sizing_multiplier': multiplier,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_score(channel_id: str) -> Optional[Dict[str, Any]]:
    """Recompute and persist score for a channel. Called on trade close."""
    try:
        from src.ai.feature_flags import is_enabled
        if not is_enabled(FEATURE_KEY):
            return None

        result = _compute_score(channel_id)

        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            INSERT INTO ai_channel_scores
                (channel_id, score, win_rate_7d, win_rate_30d, win_rate_all,
                 avg_pnl_pct, avg_win_pct, avg_loss_pct, profit_factor, sharpe_ratio,
                 total_trades, streak_current, auto_sizing_multiplier, last_computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(channel_id) DO UPDATE SET
                score=excluded.score, win_rate_7d=excluded.win_rate_7d,
                win_rate_30d=excluded.win_rate_30d, win_rate_all=excluded.win_rate_all,
                avg_pnl_pct=excluded.avg_pnl_pct, avg_win_pct=excluded.avg_win_pct,
                avg_loss_pct=excluded.avg_loss_pct, profit_factor=excluded.profit_factor,
                sharpe_ratio=excluded.sharpe_ratio, total_trades=excluded.total_trades,
                streak_current=excluded.streak_current,
                auto_sizing_multiplier=excluded.auto_sizing_multiplier,
                last_computed_at=CURRENT_TIMESTAMP
        ''', (result['channel_id'], result['score'], result['win_rate_7d'],
              result['win_rate_30d'], result['win_rate_all'], result['avg_pnl_pct'],
              result['avg_win_pct'], result['avg_loss_pct'], result['profit_factor'],
              result['sharpe_ratio'], result['total_trades'], result['streak_current'],
              result['auto_sizing_multiplier']))
        conn.commit()
        conn.close()

        # Invalidate cache
        with _lock:
            _score_cache.pop(channel_id, None)

        if result['score'] < 30:
            print(f'[AI_SCORING] ⚠ Channel {channel_id} score={result["score"]} — LOW PERFORMANCE ALERT')
        return result
    except Exception as e:
        print(f'[AI_SCORING] update_score error: {e}')
        return None


def get_score(channel_id: str) -> int:
    """Get cached score for a channel. Returns 50 (neutral) if unknown."""
    try:
        _maybe_refresh_cache()
        with _lock:
            entry = _score_cache.get(channel_id)
        if entry:
            return entry.get('score', 50)
        return 50
    except Exception:
        return 50


def get_all_scores() -> List[Dict[str, Any]]:
    """Return all channel scores for Dashboard display."""
    try:
        from src.ai.feature_flags import is_enabled
        if not is_enabled(FEATURE_KEY):
            return []

        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT channel_id, score, win_rate_7d, win_rate_30d, win_rate_all,
                   avg_pnl_pct, avg_win_pct, avg_loss_pct, profit_factor, sharpe_ratio,
                   total_trades, streak_current, auto_sizing_multiplier, last_computed_at
            FROM ai_channel_scores ORDER BY score DESC
        ''')
        cols = ['channel_id', 'score', 'win_rate_7d', 'win_rate_30d', 'win_rate_all',
                'avg_pnl_pct', 'avg_win_pct', 'avg_loss_pct', 'profit_factor', 'sharpe_ratio',
                'total_trades', 'streak_current', 'auto_sizing_multiplier', 'last_computed_at']
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f'[AI_SCORING] get_all_scores error: {e}')
        return []


def get_sizing_multiplier(channel_id: str) -> float:
    """Get the auto sizing multiplier for a channel. 1.0 = neutral."""
    try:
        from src.ai.feature_flags import is_enabled
        if not is_enabled(FEATURE_KEY):
            return 1.0

        _maybe_refresh_cache()
        with _lock:
            entry = _score_cache.get(channel_id)
        if entry:
            return entry.get('auto_sizing_multiplier', 1.0)
        return 1.0
    except Exception:
        return 1.0


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _maybe_refresh_cache():
    global _cache_ts
    now = time.time()
    if now - _cache_ts < _CACHE_TTL:
        return
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT channel_id, score, auto_sizing_multiplier FROM ai_channel_scores')
        new_cache = {}
        for row in cursor.fetchall():
            new_cache[row[0]] = {'score': row[1], 'auto_sizing_multiplier': row[2]}
        conn.close()
        with _lock:
            _score_cache.update(new_cache)
            _cache_ts = time.time()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Event bus integration
# ---------------------------------------------------------------------------

def _on_trade_close(trade_data: dict):
    """Event handler: auto-update channel score when a trade closes."""
    try:
        channel_id = trade_data.get('channel_id')
        if channel_id:
            update_score(str(channel_id))
    except Exception:
        pass


def _register_events():
    try:
        from src.ai.event_bus import on, EVENT_TRADE_CLOSE
        on(EVENT_TRADE_CLOSE, _on_trade_close)
    except Exception:
        pass


# Bootstrap
_ensure_table()
_register_events()
