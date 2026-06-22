"""Cross-channel consensus detection — boost sizing when multiple channels agree."""
import time
import threading
from typing import Optional, Dict, Any

_recent_signals = []  # list of (timestamp, symbol, strike, expiry, channel_id, action)
_lock = threading.Lock()
_WINDOW_SECONDS = 600  # 10 minutes
_MAX_RECENT = 500


def _ensure_table():
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_consensus_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                asset_type TEXT DEFAULT 'option',
                strike REAL,
                expiry TEXT,
                channel_count INTEGER,
                channel_ids TEXT,
                first_signal_at TIMESTAMP,
                consensus_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sizing_boost REAL DEFAULT 1.0,
                outcome_pnl_pct REAL
            )
        ''')
        conn.commit()
        conn.close()
    except Exception:
        pass


def record_signal(symbol: str, strike: float = None, expiry: str = None,
                  channel_id: str = '', action: str = 'BTO'):
    """Record a signal for consensus tracking. Called on every BTO signal."""
    if action.upper() != 'BTO':
        return
    with _lock:
        _recent_signals.append((time.time(), symbol.upper(), strike, expiry, str(channel_id), action))
        # Prune old
        cutoff = time.time() - _WINDOW_SECONDS
        while _recent_signals and _recent_signals[0][0] < cutoff:
            _recent_signals.pop(0)
        if len(_recent_signals) > _MAX_RECENT:
            _recent_signals[:] = _recent_signals[-_MAX_RECENT:]


def check_consensus(symbol: str, strike: float = None, expiry: str = None) -> Optional[Dict[str, Any]]:
    """Check if multiple channels recently signaled the same symbol."""
    cutoff = time.time() - _WINDOW_SECONDS
    sym = symbol.upper()
    matching_channels = set()

    with _lock:
        for ts, s_sym, s_strike, s_expiry, s_ch, s_action in _recent_signals:
            if ts < cutoff:
                continue
            if s_sym != sym:
                continue
            # For options: require same strike + expiry
            if strike is not None and s_strike is not None:
                if abs(s_strike - strike) > 0.5:
                    continue
                if expiry and s_expiry and expiry != s_expiry:
                    continue
            matching_channels.add(s_ch)

    if len(matching_channels) < 2:
        return None

    count = len(matching_channels)
    boost = 1.5 if count == 2 else min(2.0, 1.0 + count * 0.3)

    # Store consensus event
    try:
        import json
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            INSERT INTO ai_consensus_events (symbol, asset_type, strike, expiry, channel_count, channel_ids, sizing_boost)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (sym, 'option' if strike else 'stock', strike, expiry, count, json.dumps(list(matching_channels)), boost))
        conn.commit()
        conn.close()
    except Exception:
        pass

    print(f'[AI_CONSENSUS] ✓ {count} channels agree on {sym}: boost={boost}x')
    return {'symbol': sym, 'channel_count': count, 'channels': list(matching_channels), 'sizing_boost': boost}


def get_active_consensus() -> list:
    """Get recent consensus events for Dashboard."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT symbol, channel_count, sizing_boost, consensus_at
            FROM ai_consensus_events
            WHERE consensus_at > datetime('now', '-1 hour')
            ORDER BY consensus_at DESC LIMIT 20
        ''')
        rows = [dict(zip(['symbol','channel_count','sizing_boost','consensus_at'], r)) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []

_ensure_table()
