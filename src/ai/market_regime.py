"""Market regime detection — classifies current conditions from VIX/SPY data.

Updates every 5 minutes via background task. Provides regime-aware sizing.
Feature flag: 'market_regime' (OFF by default).
"""
import time
import threading
from typing import Optional, Dict, Any

FEATURE_KEY = 'market_regime'

# Regime constants
TRENDING_UP = 'TRENDING_UP'
TRENDING_DOWN = 'TRENDING_DOWN'
CHOPPY = 'CHOPPY'
HIGH_VOL = 'HIGH_VOL'
LOW_VOL = 'LOW_VOL'
NORMAL = 'NORMAL'

ALL_REGIMES = (TRENDING_UP, TRENDING_DOWN, CHOPPY, HIGH_VOL, LOW_VOL, NORMAL)

# Sizing multiplier by regime
_REGIME_SIZING = {
    TRENDING_UP: 1.1,
    TRENDING_DOWN: 0.7,
    CHOPPY: 0.5,
    HIGH_VOL: 0.6,
    LOW_VOL: 1.0,
    NORMAL: 1.0,
}

_cached_regime: Optional[Dict[str, Any]] = None
_cache_ts = 0.0
_CACHE_TTL = 120  # 2 minutes
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def _ensure_table():
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_market_regime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                regime TEXT NOT NULL,
                vix_level REAL,
                spy_range_pct REAL,
                confidence REAL DEFAULT 0.5,
                sizing_multiplier REAL DEFAULT 1.0,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_regime_detected ON ai_market_regime(detected_at)')
        conn.commit()
    except Exception as e:
        print(f'[AI_REGIME] Table init error: {e}')


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _get_vix_price() -> Optional[float]:
    """Fetch latest VIX level from Unified Price Hub."""
    try:
        from src.services.unified_price_hub import get_unified_price_hub
        uph = get_unified_price_hub()
        price = uph.get_quote_price('VIX', allow_stale=True)
        return price
    except Exception:
        return None


def _get_spy_quote() -> Optional[Dict[str, float]]:
    """Fetch SPY quote (last, high, low, open) from UPH."""
    try:
        from src.services.unified_price_hub import get_unified_price_hub
        uph = get_unified_price_hub()
        quote = uph.get_quote('SPY')
        if quote and quote.last > 0:
            return {
                'last': quote.last,
                'high': quote.high if quote.high > 0 else quote.last,
                'low': quote.low if quote.low > 0 else quote.last,
                'open': quote.open_price if quote.open_price > 0 else quote.last,
            }
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify(vix: Optional[float], spy: Optional[Dict[str, float]]) -> Dict[str, Any]:
    """Determine market regime from VIX level and SPY intraday range."""
    regime = NORMAL
    confidence = 0.5
    spy_range_pct = 0.0

    # VIX-based classification
    if vix is not None:
        if vix >= 30:
            regime = HIGH_VOL
            confidence = min(0.95, 0.7 + (vix - 30) * 0.01)
        elif vix >= 22:
            regime = HIGH_VOL
            confidence = 0.6 + (vix - 22) * 0.0125
        elif vix <= 13:
            regime = LOW_VOL
            confidence = min(0.9, 0.6 + (13 - vix) * 0.03)

    # SPY trend/choppiness overlay
    if spy:
        day_range = spy['high'] - spy['low']
        mid = (spy['high'] + spy['low']) / 2 if (spy['high'] + spy['low']) > 0 else 1
        spy_range_pct = (day_range / mid) * 100 if mid > 0 else 0

        change_pct = ((spy['last'] - spy['open']) / spy['open'] * 100) if spy['open'] > 0 else 0

        # Trend detection overrides VIX-only when VIX is in normal range
        if vix is None or (13 < vix < 22):
            if change_pct > 0.8:
                regime = TRENDING_UP
                confidence = min(0.9, 0.5 + abs(change_pct) * 0.15)
            elif change_pct < -0.8:
                regime = TRENDING_DOWN
                confidence = min(0.9, 0.5 + abs(change_pct) * 0.15)
            elif spy_range_pct > 1.5 and abs(change_pct) < 0.3:
                regime = CHOPPY
                confidence = min(0.85, 0.5 + spy_range_pct * 0.1)

    sizing = _REGIME_SIZING.get(regime, 1.0)

    return {
        'regime': regime,
        'vix': round(vix, 2) if vix is not None else None,
        'spy_range_pct': round(spy_range_pct, 3),
        'confidence': round(confidence, 3),
        'sizing_multiplier': sizing,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_regime() -> Optional[Dict[str, Any]]:
    """Recompute market regime from live data. Called every 5 min."""
    global _cached_regime, _cache_ts
    try:
        from src.ai.feature_flags import is_enabled
        if not is_enabled(FEATURE_KEY):
            return None

        vix = _get_vix_price()
        spy = _get_spy_quote()

        result = _classify(vix, spy)

        # Persist
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            INSERT INTO ai_market_regime (regime, vix_level, spy_range_pct, confidence, sizing_multiplier)
            VALUES (?, ?, ?, ?, ?)
        ''', (result['regime'], result['vix'], result['spy_range_pct'],
              result['confidence'], result['sizing_multiplier']))
        conn.commit()

        # Prune old entries — keep last 2000
        try:
            conn.execute('''
                DELETE FROM ai_market_regime
                WHERE id NOT IN (SELECT id FROM ai_market_regime ORDER BY id DESC LIMIT 2000)
            ''')
            conn.commit()
        except Exception:
            pass

        with _lock:
            _cached_regime = result
            _cache_ts = time.time()

        print(f'[AI_REGIME] {result["regime"]} (VIX={result["vix"]}, SPY range={result["spy_range_pct"]}%, '
              f'conf={result["confidence"]}, sizing={result["sizing_multiplier"]}x)')
        return result
    except Exception as e:
        print(f'[AI_REGIME] update_regime error: {e}')
        return None


def get_current_regime() -> Dict[str, Any]:
    """Get current market regime. Returns cached or loads from DB."""
    global _cached_regime, _cache_ts
    try:
        now = time.time()
        if _cached_regime and (now - _cache_ts) < _CACHE_TTL:
            return _cached_regime

        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT regime, vix_level, spy_range_pct, confidence, sizing_multiplier, detected_at
            FROM ai_market_regime ORDER BY id DESC LIMIT 1
        ''')
        row = cursor.fetchone()
        if row:
            result = {
                'regime': row[0],
                'vix': row[1],
                'spy_range_pct': row[2],
                'confidence': row[3],
                'sizing_multiplier': row[4],
                'detected_at': row[5],
            }
            with _lock:
                _cached_regime = result
                _cache_ts = time.time()
            return result

        return {'regime': NORMAL, 'vix': None, 'spy_range_pct': 0, 'confidence': 0.3, 'sizing_multiplier': 1.0}
    except Exception as e:
        print(f'[AI_REGIME] get_current_regime error: {e}')
        return {'regime': NORMAL, 'vix': None, 'spy_range_pct': 0, 'confidence': 0.3, 'sizing_multiplier': 1.0}


def get_regime_history(hours: int = 24) -> list:
    """Get recent regime history for Dashboard charts."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT regime, vix_level, spy_range_pct, confidence, sizing_multiplier, detected_at
            FROM ai_market_regime
            WHERE detected_at > datetime('now', ? || ' hours')
            ORDER BY detected_at ASC
        ''', (f'-{hours}',))
        cols = ['regime', 'vix', 'spy_range_pct', 'confidence', 'sizing_multiplier', 'detected_at']
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    except Exception as e:
        print(f'[AI_REGIME] get_regime_history error: {e}')
        return []


def get_sizing_multiplier() -> float:
    """Get current regime sizing multiplier. 1.0 = neutral."""
    try:
        from src.ai.feature_flags import is_enabled
        if not is_enabled(FEATURE_KEY):
            return 1.0
        regime = get_current_regime()
        return regime.get('sizing_multiplier', 1.0)
    except Exception:
        return 1.0


# Bootstrap table on import
_ensure_table()
