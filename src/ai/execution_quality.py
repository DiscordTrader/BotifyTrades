"""Execution quality tracking — records fill data and analyzes per-broker performance.

Captures slippage, latency, and fill quality for every executed order.
Feature flag: 'execution_quality' (OFF by default).
"""
import time
from typing import Optional, Dict, Any, List

FEATURE_KEY = 'execution_quality'


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def _ensure_table():
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_execution_quality (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                broker TEXT NOT NULL,
                symbol TEXT NOT NULL,
                asset_type TEXT DEFAULT 'stock',
                order_type TEXT DEFAULT 'market',
                signal_price REAL,
                fill_price REAL,
                slippage_pct REAL DEFAULT 0,
                signal_to_fill_ms INTEGER DEFAULT 0,
                time_of_day TEXT,
                market_regime TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_eq_broker ON ai_execution_quality(broker)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_eq_created ON ai_execution_quality(created_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_eq_trade ON ai_execution_quality(trade_id)')
        conn.commit()
    except Exception as e:
        print(f'[AI_EXEC_Q] Table init error: {e}')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record_fill(trade_id: int, broker: str, signal_price: float, fill_price: float,
                latency_ms: int = 0, symbol: str = '', asset_type: str = 'stock',
                order_type: str = 'market') -> Optional[Dict[str, Any]]:
    """Record a single fill event. Called on every order fill."""
    try:
        from src.ai.feature_flags import is_enabled
        if not is_enabled(FEATURE_KEY):
            return None

        if not signal_price or signal_price <= 0 or not fill_price or fill_price <= 0:
            return None

        slippage_pct = round(((fill_price - signal_price) / signal_price) * 100, 4)

        # Determine time-of-day bucket
        from datetime import datetime
        now = datetime.now()
        hour = now.hour
        if hour < 10:
            tod = 'pre_market'
        elif hour < 11:
            tod = 'open_30min'
        elif hour < 15:
            tod = 'mid_day'
        elif hour < 16:
            tod = 'close_30min'
        else:
            tod = 'after_hours'

        # Get current market regime if available
        regime = None
        try:
            from src.ai.market_regime import get_current_regime
            r = get_current_regime()
            regime = r.get('regime')
        except Exception:
            pass

        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            INSERT INTO ai_execution_quality
                (trade_id, broker, symbol, asset_type, order_type,
                 signal_price, fill_price, slippage_pct, signal_to_fill_ms,
                 time_of_day, market_regime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (trade_id, broker, symbol, asset_type, order_type,
              signal_price, fill_price, slippage_pct, latency_ms,
              tod, regime))
        conn.commit()

        # Log significant slippage
        if abs(slippage_pct) > 1.0:
            print(f'[AI_EXEC_Q] ⚠ High slippage on {symbol} via {broker}: '
                  f'{slippage_pct:+.2f}% (signal=${signal_price:.2f} fill=${fill_price:.2f})')

        return {
            'trade_id': trade_id, 'broker': broker, 'symbol': symbol,
            'slippage_pct': slippage_pct, 'latency_ms': latency_ms,
        }
    except Exception as e:
        print(f'[AI_EXEC_Q] record_fill error: {e}')
        return None


def get_broker_stats(days: int = 30) -> Dict[str, Dict[str, Any]]:
    """Get aggregated execution stats per broker."""
    try:
        from src.ai.feature_flags import is_enabled
        if not is_enabled(FEATURE_KEY):
            return {}

        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT broker,
                   COUNT(*) as fill_count,
                   AVG(slippage_pct) as avg_slippage,
                   AVG(ABS(slippage_pct)) as avg_abs_slippage,
                   MAX(ABS(slippage_pct)) as max_slippage,
                   AVG(signal_to_fill_ms) as avg_latency,
                   MIN(signal_to_fill_ms) as min_latency,
                   MAX(signal_to_fill_ms) as max_latency,
                   SUM(CASE WHEN slippage_pct > 0 THEN 1 ELSE 0 END) as positive_slippage_count,
                   SUM(CASE WHEN slippage_pct < 0 THEN 1 ELSE 0 END) as negative_slippage_count
            FROM ai_execution_quality
            WHERE created_at > datetime('now', ? || ' days')
            GROUP BY broker
            ORDER BY fill_count DESC
        ''', (f'-{days}',))

        stats = {}
        for row in cursor.fetchall():
            stats[row[0]] = {
                'fill_count': row[1],
                'avg_slippage': round(row[2] or 0, 4),
                'avg_abs_slippage': round(row[3] or 0, 4),
                'max_slippage': round(row[4] or 0, 4),
                'avg_latency': round(row[5] or 0, 1),
                'min_latency': row[6] or 0,
                'max_latency': row[7] or 0,
                'positive_slippage_count': row[8] or 0,
                'negative_slippage_count': row[9] or 0,
            }
        return stats
    except Exception as e:
        print(f'[AI_EXEC_Q] get_broker_stats error: {e}')
        return {}


def get_worst_fills(limit: int = 10) -> List[Dict[str, Any]]:
    """Get the worst slippage fills for review."""
    try:
        from src.ai.feature_flags import is_enabled
        if not is_enabled(FEATURE_KEY):
            return []

        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT trade_id, broker, symbol, asset_type, order_type,
                   signal_price, fill_price, slippage_pct, signal_to_fill_ms,
                   time_of_day, market_regime, created_at
            FROM ai_execution_quality
            ORDER BY ABS(slippage_pct) DESC
            LIMIT ?
        ''', (limit,))
        cols = ['trade_id', 'broker', 'symbol', 'asset_type', 'order_type',
                'signal_price', 'fill_price', 'slippage_pct', 'latency_ms',
                'time_of_day', 'market_regime', 'created_at']
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    except Exception as e:
        print(f'[AI_EXEC_Q] get_worst_fills error: {e}')
        return []


def get_time_of_day_analysis(days: int = 30) -> List[Dict[str, Any]]:
    """Analyze execution quality by time of day."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT time_of_day,
                   COUNT(*) as fill_count,
                   AVG(slippage_pct) as avg_slippage,
                   AVG(signal_to_fill_ms) as avg_latency
            FROM ai_execution_quality
            WHERE created_at > datetime('now', ? || ' days')
            GROUP BY time_of_day
            ORDER BY avg_slippage ASC
        ''', (f'-{days}',))
        cols = ['time_of_day', 'fill_count', 'avg_slippage', 'avg_latency']
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    except Exception as e:
        print(f'[AI_EXEC_Q] get_time_of_day_analysis error: {e}')
        return []


def get_regime_analysis(days: int = 30) -> List[Dict[str, Any]]:
    """Analyze execution quality by market regime."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT market_regime,
                   COUNT(*) as fill_count,
                   AVG(slippage_pct) as avg_slippage,
                   AVG(signal_to_fill_ms) as avg_latency
            FROM ai_execution_quality
            WHERE created_at > datetime('now', ? || ' days')
                  AND market_regime IS NOT NULL
            GROUP BY market_regime
            ORDER BY avg_slippage ASC
        ''', (f'-{days}',))
        cols = ['market_regime', 'fill_count', 'avg_slippage', 'avg_latency']
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    except Exception as e:
        print(f'[AI_EXEC_Q] get_regime_analysis error: {e}')
        return []


# Bootstrap table on import
_ensure_table()
