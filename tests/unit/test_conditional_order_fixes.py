"""
Tests for GAP 7/11/14 fixes in conditional orders and UPH.

GAP 7:  UPH get_quote_price accepts allow_stale kwarg without TypeError
GAP 11: Frozen feed detection runs outside market hours with relaxed threshold
GAP 14: Execution callback has 2 retries (not 1) before ERROR state
"""
import inspect
import sys
import os
import time
import asyncio
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ── GAP 7: UPH get_quote_price allow_stale ──────────────────────────────────

class TestGap7UPHAllowStale:
    """get_quote_price must accept allow_stale=True without TypeError."""

    def test_signature_has_allow_stale(self):
        from src.services.unified_price_hub import UnifiedPriceHub
        sig = inspect.signature(UnifiedPriceHub.get_quote_price)
        assert 'allow_stale' in sig.parameters

    def test_allow_stale_defaults_false(self):
        from src.services.unified_price_hub import UnifiedPriceHub
        sig = inspect.signature(UnifiedPriceHub.get_quote_price)
        assert sig.parameters['allow_stale'].default is False

    def test_call_with_allow_stale_no_typeerror(self):
        """Calling with allow_stale=True must not raise TypeError."""
        from src.services.unified_price_hub import UnifiedPriceHub
        hub = UnifiedPriceHub.__new__(UnifiedPriceHub)
        hub.get_quote = MagicMock(return_value=None)
        # Should not raise TypeError
        result = hub.get_quote_price('AAPL', allow_stale=True)
        assert result is None

    def test_call_without_allow_stale_still_works(self):
        """Old callers omitting allow_stale must still work."""
        from src.services.unified_price_hub import UnifiedPriceHub, UnifiedQuote
        hub = UnifiedPriceHub.__new__(UnifiedPriceHub)
        import time as _t
        fake_quote = UnifiedQuote(symbol='AAPL', last=150.25, timestamp=_t.time())
        hub.get_quote = MagicMock(return_value=fake_quote)
        result = hub.get_quote_price('AAPL')
        assert result == 150.25

    def test_returns_price_when_quote_exists(self):
        """get_quote_price returns last price from cached quote."""
        from src.services.unified_price_hub import UnifiedPriceHub, UnifiedQuote
        hub = UnifiedPriceHub.__new__(UnifiedPriceHub)
        fake_quote = UnifiedQuote(symbol='TSLA', last=420.69)
        hub.get_quote = MagicMock(return_value=fake_quote)
        result = hub.get_quote_price('TSLA', allow_stale=True)
        assert result == 420.69


# ── GAP 11: Frozen feed detection extended hours ─────────────────────────────

class TestGap11FrozenFeedExtendedHours:
    """Frozen feed detection must run during extended hours with relaxed threshold."""

    def _get_source(self):
        base_path = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'src', 'services', 'conditional_orders', 'base.py'
        )
        with open(base_path, 'r') as f:
            return f.read()

    def test_no_market_hours_gate_on_frozen_if(self):
        """The frozen detection if-line must NOT gate on _is_us_market_hours()."""
        source = self._get_source()
        # Old pattern: single line with frozen_seconds AND _is_us_market_hours()
        lines = source.split('\n')
        for line in lines:
            if 'frozen_seconds >=' in line and '_is_us_market_hours()' in line:
                pytest.fail(
                    "Frozen detection if-condition still gates on _is_us_market_hours()"
                )

    def test_uses_effective_frozen_threshold(self):
        """Should compute _effective_frozen_threshold based on market hours."""
        source = self._get_source()
        assert '_effective_frozen_threshold' in source

    def test_5x_multiplier_for_off_hours(self):
        """Off-hours threshold should be 5x the normal FROZEN_THRESHOLD."""
        source = self._get_source()
        assert 'FROZEN_THRESHOLD * 5' in source

    def test_condition_uses_effective_threshold(self):
        """The if-condition must compare against _effective_frozen_threshold."""
        source = self._get_source()
        assert 'frozen_seconds >= _effective_frozen_threshold' in source


# ── GAP 14: Execution callback second retry ──────────────────────────────────

class TestGap14ExecutionRetry:
    """Execution callback must have 2 retries before going to ERROR state."""

    def _get_source(self):
        base_path = os.path.join(
            os.path.dirname(__file__), '..', '..',
            'src', 'services', 'conditional_orders', 'base.py'
        )
        with open(base_path, 'r') as f:
            return f.read()

    def test_has_second_retry_variable(self):
        source = self._get_source()
        assert 'retry2_result' in source
        assert 'retry2_future' in source

    def test_second_retry_uses_45s_timeout(self):
        source = self._get_source()
        assert 'timeout=45' in source

    def test_first_retry_still_30s(self):
        source = self._get_source()
        # retry_future.result(timeout=30) for first retry
        assert 'retry_future.result(timeout=30)' in source

    def test_logs_all_retries_failed(self):
        source = self._get_source()
        assert 'All retries failed' in source

    def test_error_message_mentions_2_retries(self):
        source = self._get_source()
        assert '2 retries failed' in source

    def test_retry2_success_logged(self):
        source = self._get_source()
        assert 'Retry 2 succeeded' in source
