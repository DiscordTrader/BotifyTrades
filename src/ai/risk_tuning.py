"""AI-powered risk setting recommendations with backtesting.

Analyzes closed trades per channel, identifies sub-optimal SL/PT settings,
proposes improvements with backtested evidence. All recommendations require
Dashboard approval before being applied.

Feature flag: 'risk_tuning' (OFF by default).
"""
import json
import math
import time
import threading
from typing import Optional, Dict, Any, List

FEATURE_KEY = 'risk_tuning'

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def _ensure_table():
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_risk_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL,
                channel_name TEXT DEFAULT '',
                current_settings TEXT DEFAULT '{}',
                proposed_settings TEXT DEFAULT '{}',
                evidence TEXT DEFAULT '',
                backtested_improvement REAL DEFAULT 0,
                confidence REAL DEFAULT 0,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','dismissed')),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_rr_status ON ai_risk_recommendations(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_rr_channel ON ai_risk_recommendations(channel_id)')
        conn.commit()
    except Exception as e:
        print(f'[AI_RISK] Table init error: {e}')


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def backtest_settings(trades: list, sl_pct: float, pt1_pct: float = 0,
                      pt2_pct: float = 0, trailing_pct: float = 0) -> Dict[str, Any]:
    """Simulate P&L for a set of trades under given risk settings.

    Each trade dict needs: entry_price, exit_price, peak_price (high during hold),
    low_price (low during hold), pnl_percent (actual result).
    Returns simulated P&L and stats.
    """
    try:
        simulated_pnl = 0.0
        sim_wins = 0
        sim_losses = 0
        sl_exits = 0
        pt_exits = 0
        trailing_exits = 0
        actual_exits = 0

        for trade in trades:
            entry = trade.get('entry_price', 0)
            if not entry or entry <= 0:
                continue

            peak = trade.get('peak_price', entry)
            low = trade.get('low_price', entry)
            exit_price = trade.get('exit_price', entry)

            # Would SL have triggered?
            sl_price = entry * (1 - sl_pct / 100) if sl_pct > 0 else 0
            if sl_pct > 0 and low <= sl_price:
                trade_pnl = (sl_price - entry) / entry * 100
                sl_exits += 1
            # Would PT1 have triggered?
            elif pt1_pct > 0 and peak >= entry * (1 + pt1_pct / 100):
                trade_pnl = pt1_pct
                pt_exits += 1
            # Would trailing stop have triggered?
            elif trailing_pct > 0 and peak > entry:
                # Trailing activates after some profit, then trails from peak
                trail_price = peak * (1 - trailing_pct / 100)
                if trail_price > entry and exit_price <= trail_price:
                    trade_pnl = (trail_price - entry) / entry * 100
                    trailing_exits += 1
                else:
                    trade_pnl = (exit_price - entry) / entry * 100
                    actual_exits += 1
            else:
                trade_pnl = (exit_price - entry) / entry * 100
                actual_exits += 1

            simulated_pnl += trade_pnl
            if trade_pnl > 0:
                sim_wins += 1
            else:
                sim_losses += 1

        total = sim_wins + sim_losses
        actual_pnl = sum(t.get('pnl_percent', 0) or 0 for t in trades)
        improvement = simulated_pnl - actual_pnl

        return {
            'simulated_pnl': round(simulated_pnl, 2),
            'actual_pnl': round(actual_pnl, 2),
            'improvement': round(improvement, 2),
            'sim_win_rate': round(sim_wins / total, 4) if total > 0 else 0,
            'total_trades': total,
            'sl_exits': sl_exits,
            'pt_exits': pt_exits,
            'trailing_exits': trailing_exits,
            'actual_exits': actual_exits,
        }
    except Exception as e:
        print(f'[AI_RISK] backtest error: {e}')
        return {'simulated_pnl': 0, 'actual_pnl': 0, 'improvement': 0,
                'sim_win_rate': 0, 'total_trades': 0, 'sl_exits': 0,
                'pt_exits': 0, 'trailing_exits': 0, 'actual_exits': 0}


# ---------------------------------------------------------------------------
# Trade data fetching
# ---------------------------------------------------------------------------

def _fetch_channel_trades(channel_id: str, days: int = 90) -> list:
    """Fetch closed BTO trades with price extremes for backtesting."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, symbol, executed_price, current_price, pnl_percent,
                   highest_price, stop_loss_price, profit_target_price,
                   close_reason, closed_at, asset_type
            FROM trades
            WHERE channel_id = ? AND status = 'CLOSED' AND direction = 'BTO'
                  AND closed_at > datetime('now', ? || ' days')
            ORDER BY closed_at DESC
        ''', (channel_id, f'-{days}'))

        trades = []
        for row in cursor.fetchall():
            entry = row[2] or 0
            exit_p = row[3] or entry
            peak = row[5] or max(entry, exit_p)
            # Estimate low from SL or actual exit
            low_est = min(entry, exit_p)
            if row[6] and row[6] > 0:
                low_est = min(low_est, row[6])

            trades.append({
                'id': row[0],
                'symbol': row[1],
                'entry_price': entry,
                'exit_price': exit_p,
                'pnl_percent': row[4] or 0,
                'peak_price': peak,
                'low_price': low_est,
                'stop_loss_price': row[6],
                'profit_target_price': row[7],
                'close_reason': row[8],
                'closed_at': row[9],
                'asset_type': row[10],
            })
        return trades
    except Exception as e:
        print(f'[AI_RISK] trade fetch error for {channel_id}: {e}')
        return []


def _fetch_channel_settings(channel_id: str) -> Dict[str, Any]:
    """Get current risk settings for a channel from signal_routing_mappings."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT name, stop_loss_pct, pt1_pct, pt2_pct, pt3_pct, pt4_pct,
                   trailing_stop_pct, trailing_activation_pct, exit_strategy_mode
            FROM signal_routing_mappings
            WHERE source_channel_id = ? AND enabled = 1
            LIMIT 1
        ''', (channel_id,))
        row = cursor.fetchone()
        if row:
            return {
                'channel_name': row[0] or '',
                'stop_loss_pct': row[1] or 25.0,
                'pt1_pct': row[2] or 25.0,
                'pt2_pct': row[3] or 50.0,
                'pt3_pct': row[4] or 75.0,
                'pt4_pct': row[5] or 100.0,
                'trailing_stop_pct': row[6] or 0.0,
                'trailing_activation_pct': row[7] or 15.0,
                'exit_strategy_mode': row[8] or 'risk',
            }
        return {
            'channel_name': '', 'stop_loss_pct': 25.0, 'pt1_pct': 25.0,
            'pt2_pct': 50.0, 'pt3_pct': 75.0, 'pt4_pct': 100.0,
            'trailing_stop_pct': 0.0, 'trailing_activation_pct': 15.0,
            'exit_strategy_mode': 'risk',
        }
    except Exception as e:
        print(f'[AI_RISK] settings fetch error: {e}')
        return {'channel_name': '', 'stop_loss_pct': 25.0, 'pt1_pct': 25.0,
                'pt2_pct': 50.0, 'pt3_pct': 75.0, 'pt4_pct': 100.0,
                'trailing_stop_pct': 0.0, 'trailing_activation_pct': 15.0,
                'exit_strategy_mode': 'risk'}


def _get_active_channels() -> list:
    """Get all channel IDs that have closed trades."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT channel_id FROM trades
            WHERE status = 'CLOSED' AND direction = 'BTO' AND channel_id IS NOT NULL
                  AND closed_at > datetime('now', '-90 days')
        ''')
        return [row[0] for row in cursor.fetchall() if row[0]]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------

_SL_CANDIDATES = [5, 8, 10, 15, 20, 25, 30, 40, 50]
_PT_CANDIDATES = [10, 15, 20, 25, 30, 40, 50, 75, 100]
_TRAILING_CANDIDATES = [0, 3, 5, 8, 10, 15]

_MIN_TRADES = 10  # Need at least 10 trades for a meaningful recommendation


def _find_optimal(trades: list, current: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Search parameter space to find settings that outperform current ones."""
    if len(trades) < _MIN_TRADES:
        return None

    current_sl = current.get('stop_loss_pct', 25.0)
    current_pt1 = current.get('pt1_pct', 25.0)
    current_trailing = current.get('trailing_stop_pct', 0.0)

    # Backtest current settings
    current_result = backtest_settings(trades, current_sl, current_pt1, trailing_pct=current_trailing)

    best_improvement = 0.0
    best_settings = None
    best_result = None

    # Grid search over SL/PT/Trailing combinations
    for sl in _SL_CANDIDATES:
        for pt in _PT_CANDIDATES:
            if pt <= sl:
                continue  # PT must be > SL to make sense
            for trail in _TRAILING_CANDIDATES:
                result = backtest_settings(trades, sl, pt, trailing_pct=trail)
                imp = result['improvement']

                # Must improve by at least 2% total P&L
                if imp > best_improvement and imp > 2.0:
                    best_improvement = imp
                    best_settings = {'stop_loss_pct': sl, 'pt1_pct': pt, 'trailing_stop_pct': trail}
                    best_result = result

    if not best_settings:
        return None

    # Confidence based on trade count and improvement magnitude
    trade_conf = min(1.0, len(trades) / 50)
    imp_conf = min(1.0, best_improvement / 20)
    confidence = round(0.6 * trade_conf + 0.4 * imp_conf, 3)

    return {
        'proposed': best_settings,
        'result': best_result,
        'improvement': round(best_improvement, 2),
        'confidence': confidence,
    }


def generate_recommendations(channel_id: str = None) -> List[Dict[str, Any]]:
    """Analyze trades and propose risk setting changes.

    If channel_id is provided, analyze only that channel.
    Otherwise, analyze all active channels.
    """
    try:
        from src.ai.feature_flags import is_enabled
        if not is_enabled(FEATURE_KEY):
            return []

        channels = [channel_id] if channel_id else _get_active_channels()
        recommendations = []

        for ch_id in channels:
            try:
                trades = _fetch_channel_trades(ch_id)
                if len(trades) < _MIN_TRADES:
                    continue

                current = _fetch_channel_settings(ch_id)
                optimal = _find_optimal(trades, current)
                if not optimal:
                    continue

                # Build evidence string
                evidence_parts = [
                    f"Analyzed {len(trades)} trades over 90 days.",
                    f"Current settings: SL={current['stop_loss_pct']}%, PT1={current['pt1_pct']}%, "
                    f"Trail={current.get('trailing_stop_pct', 0)}%.",
                    f"Proposed: SL={optimal['proposed']['stop_loss_pct']}%, "
                    f"PT1={optimal['proposed']['pt1_pct']}%, "
                    f"Trail={optimal['proposed']['trailing_stop_pct']}%.",
                    f"Backtested improvement: {optimal['improvement']:+.1f}% total P&L.",
                    f"Simulated win rate: {optimal['result']['sim_win_rate']:.0%}.",
                    f"SL exits: {optimal['result']['sl_exits']}, "
                    f"PT exits: {optimal['result']['pt_exits']}, "
                    f"Trail exits: {optimal['result']['trailing_exits']}.",
                ]
                evidence = ' '.join(evidence_parts)

                rec = _store_recommendation(
                    channel_id=ch_id,
                    channel_name=current.get('channel_name', ''),
                    current_settings=current,
                    proposed_settings=optimal['proposed'],
                    evidence=evidence,
                    improvement=optimal['improvement'],
                    confidence=optimal['confidence'],
                )
                if rec:
                    recommendations.append(rec)
                    print(f'[AI_RISK] ✓ Recommendation for {current.get("channel_name", ch_id)}: '
                          f'{optimal["improvement"]:+.1f}% improvement (conf={optimal["confidence"]:.0%})')

            except Exception as e:
                print(f'[AI_RISK] Error analyzing channel {ch_id}: {e}')
                continue

        return recommendations
    except Exception as e:
        print(f'[AI_RISK] generate_recommendations error: {e}')
        return []


def _store_recommendation(channel_id: str, channel_name: str,
                          current_settings: dict, proposed_settings: dict,
                          evidence: str, improvement: float,
                          confidence: float) -> Optional[Dict[str, Any]]:
    """Persist a recommendation to the DB."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()

        # Dismiss any existing pending recommendations for this channel
        conn.execute('''
            UPDATE ai_risk_recommendations
            SET status = 'dismissed', reviewed_at = CURRENT_TIMESTAMP
            WHERE channel_id = ? AND status = 'pending'
        ''', (channel_id,))

        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO ai_risk_recommendations
                (channel_id, channel_name, current_settings, proposed_settings,
                 evidence, backtested_improvement, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        ''', (channel_id, channel_name,
              json.dumps(current_settings), json.dumps(proposed_settings),
              evidence, improvement, confidence))
        conn.commit()
        rec_id = cursor.lastrowid

        return {
            'id': rec_id, 'channel_id': channel_id, 'channel_name': channel_name,
            'current_settings': current_settings, 'proposed_settings': proposed_settings,
            'evidence': evidence, 'backtested_improvement': improvement,
            'confidence': confidence, 'status': 'pending',
        }
    except Exception as e:
        print(f'[AI_RISK] store recommendation error: {e}')
        return None


# ---------------------------------------------------------------------------
# Recommendation management
# ---------------------------------------------------------------------------

def get_pending_recommendations() -> List[Dict[str, Any]]:
    """Get all pending recommendations for Dashboard approval."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, channel_id, channel_name, current_settings, proposed_settings,
                   evidence, backtested_improvement, confidence, status, created_at
            FROM ai_risk_recommendations
            WHERE status = 'pending'
            ORDER BY backtested_improvement DESC
        ''')
        cols = ['id', 'channel_id', 'channel_name', 'current_settings', 'proposed_settings',
                'evidence', 'backtested_improvement', 'confidence', 'status', 'created_at']
        results = []
        for row in cursor.fetchall():
            rec = dict(zip(cols, row))
            # Parse JSON fields
            try:
                rec['current_settings'] = json.loads(rec['current_settings']) if isinstance(rec['current_settings'], str) else rec['current_settings']
            except Exception:
                rec['current_settings'] = {}
            try:
                rec['proposed_settings'] = json.loads(rec['proposed_settings']) if isinstance(rec['proposed_settings'], str) else rec['proposed_settings']
            except Exception:
                rec['proposed_settings'] = {}
            results.append(rec)
        return results
    except Exception as e:
        print(f'[AI_RISK] get_pending error: {e}')
        return []


def get_all_recommendations(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent recommendations regardless of status."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, channel_id, channel_name, current_settings, proposed_settings,
                   evidence, backtested_improvement, confidence, status, created_at, reviewed_at
            FROM ai_risk_recommendations
            ORDER BY created_at DESC LIMIT ?
        ''', (limit,))
        cols = ['id', 'channel_id', 'channel_name', 'current_settings', 'proposed_settings',
                'evidence', 'backtested_improvement', 'confidence', 'status', 'created_at', 'reviewed_at']
        results = []
        for row in cursor.fetchall():
            rec = dict(zip(cols, row))
            try:
                rec['current_settings'] = json.loads(rec['current_settings']) if isinstance(rec['current_settings'], str) else rec['current_settings']
            except Exception:
                rec['current_settings'] = {}
            try:
                rec['proposed_settings'] = json.loads(rec['proposed_settings']) if isinstance(rec['proposed_settings'], str) else rec['proposed_settings']
            except Exception:
                rec['proposed_settings'] = {}
            results.append(rec)
        return results
    except Exception as e:
        print(f'[AI_RISK] get_all error: {e}')
        return []


def apply_recommendation(rec_id: int) -> bool:
    """Apply an approved recommendation — updates channel risk settings.

    Returns True if settings were successfully updated.
    """
    try:
        from src.ai.feature_flags import is_enabled
        if not is_enabled(FEATURE_KEY):
            return False

        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()

        # Fetch the recommendation
        cursor.execute('''
            SELECT channel_id, proposed_settings, status
            FROM ai_risk_recommendations WHERE id = ?
        ''', (rec_id,))
        row = cursor.fetchone()
        if not row:
            print(f'[AI_RISK] Recommendation {rec_id} not found')
            return False

        channel_id = row[0]
        status = row[2]
        if status != 'pending':
            print(f'[AI_RISK] Recommendation {rec_id} already {status}')
            return False

        try:
            proposed = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        except Exception:
            proposed = {}

        if not proposed:
            return False

        # Build UPDATE for signal_routing_mappings
        update_parts = []
        update_values = []

        field_map = {
            'stop_loss_pct': 'stop_loss_pct',
            'pt1_pct': 'pt1_pct',
            'pt2_pct': 'pt2_pct',
            'pt3_pct': 'pt3_pct',
            'pt4_pct': 'pt4_pct',
            'trailing_stop_pct': 'trailing_stop_pct',
            'trailing_activation_pct': 'trailing_activation_pct',
        }
        for key, col in field_map.items():
            if key in proposed:
                update_parts.append(f'{col} = ?')
                update_values.append(proposed[key])

        if update_parts:
            update_parts.append('updated_at = CURRENT_TIMESTAMP')
            update_values.append(channel_id)
            conn.execute(f'''
                UPDATE signal_routing_mappings
                SET {', '.join(update_parts)}
                WHERE source_channel_id = ?
            ''', tuple(update_values))

        # Mark recommendation as approved
        conn.execute('''
            UPDATE ai_risk_recommendations
            SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (rec_id,))
        conn.commit()

        print(f'[AI_RISK] ✓ Applied recommendation {rec_id} for channel {channel_id}')
        return True
    except Exception as e:
        print(f'[AI_RISK] apply_recommendation error: {e}')
        return False


def dismiss_recommendation(rec_id: int) -> bool:
    """Dismiss a recommendation."""
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            UPDATE ai_risk_recommendations
            SET status = 'dismissed', reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'pending'
        ''', (rec_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f'[AI_RISK] dismiss error: {e}')
        return False


def backtest_channel(channel_id: str, sl_pct: float, pt1_pct: float,
                     trailing_pct: float = 0, days: int = 90) -> Dict[str, Any]:
    """Public backtest for a specific channel with custom settings.

    Can be used by the Dashboard for "what-if" analysis before approving.
    """
    try:
        trades = _fetch_channel_trades(channel_id, days)
        if not trades:
            return {'error': 'No trades found', 'total_trades': 0}

        result = backtest_settings(trades, sl_pct, pt1_pct, trailing_pct=trailing_pct)
        return result
    except Exception as e:
        print(f'[AI_RISK] backtest_channel error: {e}')
        return {'error': str(e), 'total_trades': 0}


# Bootstrap table on import
_ensure_table()
