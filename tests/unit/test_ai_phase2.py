"""Tests for AI Phase 2 modules: channel_scoring, market_regime, execution_quality, risk_tuning."""
import json
import sqlite3
import pytest
import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ─── Channel Scoring ────────────────────────────────────────

class TestChannelScoring:
    """Test channel performance scoring logic."""

    def test_normalize_win_rate_midpoint(self):
        from src.ai.channel_scoring import _normalize_win_rate
        mid = _normalize_win_rate(0.5)
        assert 45 < mid < 55, f"50% WR should be ~50, got {mid}"

    def test_normalize_win_rate_extremes(self):
        from src.ai.channel_scoring import _normalize_win_rate
        assert _normalize_win_rate(0.0) == 0.0
        assert _normalize_win_rate(1.0) == 100.0
        assert _normalize_win_rate(0.7) > 80
        assert _normalize_win_rate(0.3) < 20

    def test_normalize_profit_factor(self):
        from src.ai.channel_scoring import _normalize_profit_factor
        assert _normalize_profit_factor(0) == 0
        pf1 = _normalize_profit_factor(1.0)
        pf2 = _normalize_profit_factor(2.0)
        assert 30 < pf1 < 50, f"PF=1 should be 30-50, got {pf1}"
        assert pf2 > pf1, "PF=2 should score higher than PF=1"
        assert _normalize_profit_factor(10) > 99

    def test_normalize_sharpe(self):
        from src.ai.channel_scoring import _normalize_sharpe
        assert _normalize_sharpe(-2) == 0
        assert _normalize_sharpe(0) == 50
        assert _normalize_sharpe(2) == 100
        assert _normalize_sharpe(1) == 75

    def test_trend_score_improving(self):
        from src.ai.channel_scoring import _trend_score
        # 7d better than 30d → above 50
        assert _trend_score(0.7, 0.5) > 50

    def test_trend_score_declining(self):
        from src.ai.channel_scoring import _trend_score
        # 7d worse than 30d → below 50
        assert _trend_score(0.3, 0.5) < 50

    def test_trend_score_no_data(self):
        from src.ai.channel_scoring import _trend_score
        assert _trend_score(0.5, 0) == 50.0

    def test_sample_size_score(self):
        from src.ai.channel_scoring import _sample_size_score
        assert _sample_size_score(0) == 0
        assert _sample_size_score(25) == 50
        assert _sample_size_score(50) == 100
        assert _sample_size_score(100) == 100

    def test_sizing_multiplier_tiers(self):
        from src.ai.channel_scoring import _sizing_multiplier
        assert _sizing_multiplier(95) == 1.2
        assert _sizing_multiplier(90) == 1.2
        assert _sizing_multiplier(89) == 1.0
        assert _sizing_multiplier(70) == 1.0
        assert _sizing_multiplier(69) == 0.7
        assert _sizing_multiplier(50) == 0.7
        assert _sizing_multiplier(49) == 0.3
        assert _sizing_multiplier(30) == 0.3
        assert _sizing_multiplier(29) == 0.0
        assert _sizing_multiplier(0) == 0.0

    def test_compute_metrics_empty(self):
        from src.ai.channel_scoring import _compute_metrics
        m = _compute_metrics([])
        assert m['count'] == 0
        assert m['win_rate'] == 0

    def test_compute_metrics_all_wins(self):
        from src.ai.channel_scoring import _compute_metrics
        trades = [{'pnl_percent': 10}, {'pnl_percent': 5}, {'pnl_percent': 20}]
        m = _compute_metrics(trades)
        assert m['win_rate'] == 1.0
        assert m['avg_pnl'] == pytest.approx(11.667, abs=0.01)
        assert m['profit_factor'] == 10.0  # no losses → capped at 10
        assert m['streak'] == 3

    def test_compute_metrics_mixed(self):
        from src.ai.channel_scoring import _compute_metrics
        trades = [
            {'pnl_percent': 10}, {'pnl_percent': -5},
            {'pnl_percent': 20}, {'pnl_percent': -3}, {'pnl_percent': 15}
        ]
        m = _compute_metrics(trades)
        assert m['count'] == 5
        assert m['win_rate'] == 0.6
        assert m['avg_win'] == pytest.approx(15.0, abs=0.01)
        assert m['avg_loss'] == pytest.approx(-4.0, abs=0.01)
        assert m['streak'] == 1  # last trade is a win

    def test_compute_metrics_losing_streak(self):
        from src.ai.channel_scoring import _compute_metrics
        trades = [{'pnl_percent': -5}, {'pnl_percent': -10}, {'pnl_percent': 20}]
        m = _compute_metrics(trades)
        assert m['streak'] == -2  # 2 consecutive losses (most recent)

    def test_feature_flag_guard(self):
        from src.ai.channel_scoring import get_sizing_multiplier, get_all_scores
        # Flag is OFF by default → safe defaults
        assert get_sizing_multiplier('nonexistent') == 1.0
        assert get_all_scores() == []

    def test_get_score_unknown_channel(self):
        from src.ai.channel_scoring import get_score
        assert get_score('nonexistent_channel_xyz') == 50

    def test_table_created(self):
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='ai_channel_scores'")
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        schema = row[0]
        assert 'channel_id TEXT PRIMARY KEY' in schema
        assert 'score INTEGER' in schema
        assert 'auto_sizing_multiplier REAL' in schema

    def test_event_handler_registered(self):
        import src.ai.channel_scoring  # noqa: F401 - triggers registration
        from src.ai.event_bus import _handlers
        assert 'trade_close' in _handlers
        assert len(_handlers['trade_close']) >= 1


# ─── Market Regime ───────────────────────────────────────────

class TestMarketRegime:
    """Test market regime classification."""

    def test_high_vol_from_vix(self):
        from src.ai.market_regime import _classify, HIGH_VOL
        r = _classify(35, None)
        assert r['regime'] == HIGH_VOL
        assert r['confidence'] > 0.7

    def test_moderate_high_vol(self):
        from src.ai.market_regime import _classify, HIGH_VOL
        r = _classify(24, None)
        assert r['regime'] == HIGH_VOL
        assert r['confidence'] >= 0.6

    def test_low_vol(self):
        from src.ai.market_regime import _classify, LOW_VOL
        r = _classify(11, None)
        assert r['regime'] == LOW_VOL

    def test_trending_up(self):
        from src.ai.market_regime import _classify, TRENDING_UP
        r = _classify(16, {'last': 455, 'high': 456, 'low': 449, 'open': 450})
        assert r['regime'] == TRENDING_UP

    def test_trending_down(self):
        from src.ai.market_regime import _classify, TRENDING_DOWN
        r = _classify(18, {'last': 440, 'high': 451, 'low': 439, 'open': 450})
        assert r['regime'] == TRENDING_DOWN

    def test_choppy(self):
        from src.ai.market_regime import _classify, CHOPPY
        # Wide range (>1.5%), small net change (<0.3%)
        r = _classify(17, {'last': 450.5, 'high': 457, 'low': 445, 'open': 450})
        assert r['regime'] == CHOPPY
        assert r['spy_range_pct'] > 1.5

    def test_normal_default(self):
        from src.ai.market_regime import _classify, NORMAL
        r = _classify(None, None)
        assert r['regime'] == NORMAL
        assert r['confidence'] == 0.5

    def test_regime_sizing_multipliers(self):
        from src.ai.market_regime import _REGIME_SIZING, TRENDING_UP, TRENDING_DOWN, CHOPPY, HIGH_VOL
        assert _REGIME_SIZING[TRENDING_UP] == 1.1
        assert _REGIME_SIZING[TRENDING_DOWN] == 0.7
        assert _REGIME_SIZING[CHOPPY] == 0.5
        assert _REGIME_SIZING[HIGH_VOL] == 0.6

    def test_feature_flag_guard(self):
        from src.ai.market_regime import get_sizing_multiplier
        assert get_sizing_multiplier() == 1.0  # flag OFF

    def test_get_current_regime_returns_valid(self):
        from src.ai.market_regime import get_current_regime, ALL_REGIMES
        r = get_current_regime()
        assert r['regime'] in ALL_REGIMES
        assert 'sizing_multiplier' in r

    def test_table_created(self):
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='ai_market_regime'")
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        schema = row[0]
        assert 'regime TEXT' in schema
        assert 'vix_level REAL' in schema
        assert 'sizing_multiplier REAL' in schema

    def test_vix_overrides_spy_in_extreme_vol(self):
        from src.ai.market_regime import _classify, HIGH_VOL
        # VIX=35 should override any SPY trend
        r = _classify(35, {'last': 460, 'high': 461, 'low': 450, 'open': 450})
        assert r['regime'] == HIGH_VOL


# ─── Execution Quality ──────────────────────────────────────

class TestExecutionQuality:
    """Test execution quality recording and analysis."""

    def test_record_fill_flag_off(self):
        from src.ai.execution_quality import record_fill
        result = record_fill(1, 'Schwab', 100.0, 100.5)
        assert result is None  # flag OFF

    def test_record_fill_invalid_prices(self):
        from src.ai.execution_quality import record_fill
        # Even if flag were on, zero prices should be rejected
        result = record_fill(1, 'Schwab', 0, 50.0)
        assert result is None

    def test_get_broker_stats_flag_off(self):
        from src.ai.execution_quality import get_broker_stats
        assert get_broker_stats() == {}

    def test_get_worst_fills_flag_off(self):
        from src.ai.execution_quality import get_worst_fills
        assert get_worst_fills() == []

    def test_table_created(self):
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='ai_execution_quality'")
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        schema = row[0]
        assert 'slippage_pct REAL' in schema
        assert 'signal_to_fill_ms INTEGER' in schema
        assert 'market_regime TEXT' in schema

    def test_event_handler_registered(self):
        import src.ai.execution_quality  # noqa: F401
        from src.ai.event_bus import _handlers
        assert 'fill_detected' in _handlers
        assert len(_handlers['fill_detected']) >= 1

    def test_time_of_day_analysis_empty(self):
        from src.ai.execution_quality import get_time_of_day_analysis
        result = get_time_of_day_analysis()
        assert isinstance(result, list)

    def test_regime_analysis_empty(self):
        from src.ai.execution_quality import get_regime_analysis
        result = get_regime_analysis()
        assert isinstance(result, list)


# ─── Risk Tuning ─────────────────────────────────────────────

class TestBacktestSettings:
    """Test backtest engine logic."""

    def _sample_trades(self):
        return [
            {'entry_price': 100, 'exit_price': 110, 'peak_price': 115, 'low_price': 95, 'pnl_percent': 10},
            {'entry_price': 50,  'exit_price': 45,  'peak_price': 52,  'low_price': 40,  'pnl_percent': -10},
            {'entry_price': 200, 'exit_price': 230, 'peak_price': 240, 'low_price': 190, 'pnl_percent': 15},
            {'entry_price': 80,  'exit_price': 72,  'peak_price': 84,  'low_price': 68,  'pnl_percent': -10},
            {'entry_price': 120, 'exit_price': 140, 'peak_price': 145, 'low_price': 118, 'pnl_percent': 16.67},
        ]

    def test_sl_exits(self):
        from src.ai.risk_tuning import backtest_settings
        r = backtest_settings(self._sample_trades(), sl_pct=10, pt1_pct=20)
        # trade2: low=40 <= SL=45 → SL exit
        # trade4: low=68 <= SL=72 → SL exit
        assert r['sl_exits'] == 2

    def test_pt_exits(self):
        from src.ai.risk_tuning import backtest_settings
        r = backtest_settings(self._sample_trades(), sl_pct=10, pt1_pct=20)
        # trade3: peak=240 >= PT=240 → PT exit
        # trade5: peak=145 >= PT=144 → PT exit
        assert r['pt_exits'] == 2

    def test_actual_exits(self):
        from src.ai.risk_tuning import backtest_settings
        r = backtest_settings(self._sample_trades(), sl_pct=10, pt1_pct=20)
        # trade1: low=95 > SL=90, peak=115 < PT=120 → actual exit
        assert r['actual_exits'] == 1

    def test_simulated_pnl(self):
        from src.ai.risk_tuning import backtest_settings
        r = backtest_settings(self._sample_trades(), sl_pct=10, pt1_pct=20)
        # trade1: actual=(110-100)/100*100 = +10
        # trade2: SL=(45-50)/50*100 = -10
        # trade3: PT=+20
        # trade4: SL=(72-80)/80*100 = -10
        # trade5: PT=+20
        assert r['simulated_pnl'] == pytest.approx(30.0, abs=0.1)

    def test_improvement_over_actual(self):
        from src.ai.risk_tuning import backtest_settings
        r = backtest_settings(self._sample_trades(), sl_pct=10, pt1_pct=20)
        actual = 10 + (-10) + 15 + (-10) + 16.67
        assert r['actual_pnl'] == pytest.approx(actual, abs=0.01)
        assert r['improvement'] == pytest.approx(30.0 - actual, abs=0.1)

    def test_trailing_stop_logic(self):
        from src.ai.risk_tuning import backtest_settings
        trades = [
            {'entry_price': 100, 'exit_price': 95, 'peak_price': 120, 'low_price': 90, 'pnl_percent': -5},
        ]
        # Trailing=5%: trail_price = 120 * 0.95 = 114. 114 > 100 (entry) and exit=95 <= 114
        r = backtest_settings(trades, sl_pct=50, pt1_pct=0, trailing_pct=5)
        assert r['trailing_exits'] == 1
        # Trail exit PnL: (114-100)/100*100 = 14%
        assert r['simulated_pnl'] == pytest.approx(14.0, abs=0.1)

    def test_empty_trades(self):
        from src.ai.risk_tuning import backtest_settings
        r = backtest_settings([], sl_pct=10, pt1_pct=20)
        assert r['total_trades'] == 0
        assert r['simulated_pnl'] == 0

    def test_zero_entry_price_skipped(self):
        from src.ai.risk_tuning import backtest_settings
        trades = [{'entry_price': 0, 'exit_price': 50, 'peak_price': 60, 'low_price': 40, 'pnl_percent': 10}]
        r = backtest_settings(trades, sl_pct=10, pt1_pct=20)
        assert r['total_trades'] == 0

    def test_sl_only_no_pt(self):
        from src.ai.risk_tuning import backtest_settings
        trades = [
            {'entry_price': 100, 'exit_price': 110, 'peak_price': 130, 'low_price': 85, 'pnl_percent': 10},
        ]
        # SL=10%: SL_price=90, low=85 <= 90 → SL exit at -10%
        r = backtest_settings(trades, sl_pct=10, pt1_pct=0)
        assert r['sl_exits'] == 1
        assert r['simulated_pnl'] == pytest.approx(-10.0, abs=0.1)


class TestRiskTuningRecommendations:
    """Test recommendation engine."""

    def test_generate_flag_off(self):
        from src.ai.risk_tuning import generate_recommendations
        assert generate_recommendations() == []

    def test_get_pending_empty(self):
        from src.ai.risk_tuning import get_pending_recommendations
        result = get_pending_recommendations()
        assert isinstance(result, list)

    def test_get_all_empty(self):
        from src.ai.risk_tuning import get_all_recommendations
        result = get_all_recommendations()
        assert isinstance(result, list)

    def test_dismiss_nonexistent(self):
        from src.ai.risk_tuning import dismiss_recommendation
        result = dismiss_recommendation(999999)
        assert result is True  # no-op, but doesn't crash

    def test_apply_flag_off(self):
        from src.ai.risk_tuning import apply_recommendation
        assert apply_recommendation(1) is False

    def test_backtest_channel_no_trades(self):
        from src.ai.risk_tuning import backtest_channel
        result = backtest_channel('nonexistent_channel', 10, 20)
        assert result.get('total_trades', 0) == 0

    def test_table_created(self):
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='ai_risk_recommendations'")
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        schema = row[0]
        assert 'channel_id TEXT' in schema
        assert 'proposed_settings TEXT' in schema
        assert 'backtested_improvement REAL' in schema
        assert 'status TEXT' in schema

    def test_find_optimal_insufficient_trades(self):
        from src.ai.risk_tuning import _find_optimal
        # Less than 10 trades → None
        trades = [{'entry_price': 100, 'exit_price': 110, 'peak_price': 115,
                    'low_price': 95, 'pnl_percent': 10}] * 5
        result = _find_optimal(trades, {'stop_loss_pct': 25, 'pt1_pct': 25})
        assert result is None
