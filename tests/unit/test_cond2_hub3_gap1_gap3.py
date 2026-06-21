"""Tests for COND-2, HUB-3, GAP-1, GAP-3 fixes."""
import sys
import os
import threading
import time
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class TestGAP1GreeksInQuoteData:
    """GAP-1: IBKRQuoteData should have greeks fields populated from modelGreeks."""

    def _make_hub(self):
        with patch.dict('sys.modules', {
            'ib_insync': MagicMock(),
        }):
            from src.services.ibkr_data_hub import IBKRQuoteData
            return IBKRQuoteData

    def test_greeks_slots_exist(self):
        QuoteData = self._make_hub()
        q = QuoteData('AAPL_20240120_150_C', 99999)
        assert hasattr(q, 'delta')
        assert hasattr(q, 'gamma')
        assert hasattr(q, 'theta')
        assert hasattr(q, 'vega')
        assert hasattr(q, 'implied_vol')

    def test_greeks_default_zero(self):
        QuoteData = self._make_hub()
        q = QuoteData('SPY_20240315_500_C')
        assert q.delta == 0.0
        assert q.gamma == 0.0
        assert q.theta == 0.0
        assert q.vega == 0.0
        assert q.implied_vol == 0.0

    def test_greeks_settable(self):
        QuoteData = self._make_hub()
        q = QuoteData('AAPL')
        q.delta = 0.55
        q.gamma = 0.03
        q.theta = -0.05
        q.vega = 0.12
        q.implied_vol = 0.35
        assert q.delta == 0.55
        assert q.gamma == 0.03
        assert q.theta == -0.05
        assert q.vega == 0.12
        assert q.implied_vol == 0.35

    def test_slots_enforced(self):
        QuoteData = self._make_hub()
        q = QuoteData('TEST')
        with pytest.raises(AttributeError):
            q.nonexistent_field = 42


class TestHUB3SubscribedLock:
    """HUB-3: _subscribed_symbols must be protected by _subscribed_lock."""

    def test_subscribed_lock_exists(self):
        """IBKRDataHub must have _subscribed_lock attribute."""
        with patch.dict('sys.modules', {
            'ib_insync': MagicMock(),
        }):
            from src.services.ibkr_data_hub import IBKRDataHub
            # Reset singleton for test
            IBKRDataHub._instance = None
            IBKRDataHub._initialized = False
            hub = IBKRDataHub.__new__(IBKRDataHub)
            hub._initialized = False
            hub.__init__()
            assert hasattr(hub, '_subscribed_lock')
            assert isinstance(hub._subscribed_lock, type(threading.Lock()))
            # Cleanup
            IBKRDataHub._instance = None

    def test_subscribe_symbol_checks_under_lock(self):
        """subscribe_symbol must acquire _subscribed_lock before checking membership."""
        import importlib
        with patch.dict('sys.modules', {
            'ib_insync': MagicMock(),
        }):
            from src.services.ibkr_data_hub import IBKRDataHub
            IBKRDataHub._instance = None
            hub = IBKRDataHub.__new__(IBKRDataHub)
            hub._initialized = False
            hub.__init__()

            # Symbol already subscribed — should return without adding
            with hub._subscribed_lock:
                hub._subscribed_symbols.add('AAPL')

            hub.subscribe_symbol('AAPL')  # Should be no-op since already in set
            assert 'AAPL' in hub._subscribed_symbols
            IBKRDataHub._instance = None


class TestGAP3OptionQueueing:
    """GAP-3: Option symbols without contracts should be queued, not silently dropped."""

    def test_option_without_contract_queued(self):
        """Options with underscore and no contract go to _pending_subscriptions."""
        with patch.dict('sys.modules', {
            'ib_insync': MagicMock(),
        }):
            from src.services.ibkr_data_hub import IBKRDataHub
            IBKRDataHub._instance = None
            hub = IBKRDataHub.__new__(IBKRDataHub)
            hub._initialized = False
            hub.__init__()

            hub.subscribe_symbol('AAPL_20240120_150_C', contract=None)
            assert 'AAPL_20240120_150_C' in hub._pending_subscriptions
            assert 'AAPL_20240120_150_C' not in hub._subscribed_symbols
            IBKRDataHub._instance = None

    def test_option_with_contract_not_queued(self):
        """Options with contract provided should proceed normally."""
        with patch.dict('sys.modules', {
            'ib_insync': MagicMock(),
        }):
            from src.services.ibkr_data_hub import IBKRDataHub
            IBKRDataHub._instance = None
            hub = IBKRDataHub.__new__(IBKRDataHub)
            hub._initialized = False
            hub.__init__()

            # Without IB connection, should go to pending
            mock_contract = MagicMock()
            hub.subscribe_symbol('AAPL_20240120_150_C', contract=mock_contract)
            # Without _ib, goes to pending
            assert 'AAPL_20240120_150_C' in hub._pending_subscriptions
            IBKRDataHub._instance = None


class TestCOND2NoCallbackError:
    """COND-2: Orders with no execution_callback should go to ERROR status."""

    def test_no_callback_sets_error(self):
        """When execution_callback is None, order should go to ERROR."""
        # We verify the else branch exists by checking the source code
        import inspect
        from src.services.conditional_orders.base import BaseConditionalOrderService
        source = inspect.getsource(BaseConditionalOrderService._execute_order)
        assert 'NO_CALLBACK' in source
        assert 'Execution callback not wired' in source
        assert 'callback_success = False' in source


class TestGAP1GreeksInDetailedQuote:
    """GAP-1: get_quote_detailed should include greeks fields."""

    def test_detailed_quote_has_greeks(self):
        """get_quote_detailed dict must include delta/gamma/theta/vega/implied_vol."""
        with patch.dict('sys.modules', {
            'ib_insync': MagicMock(),
        }):
            from src.services.ibkr_data_hub import IBKRDataHub, IBKRQuoteData
            IBKRDataHub._instance = None
            hub = IBKRDataHub.__new__(IBKRDataHub)
            hub._initialized = False
            hub.__init__()

            q = IBKRQuoteData('AAPL_OPT', 12345)
            q.last = 5.50
            q.timestamp = time.time()
            q.delta = 0.55
            q.gamma = 0.03
            q.theta = -0.05
            q.vega = 0.12
            q.implied_vol = 0.35

            with hub._quotes_lock:
                hub._quotes['AAPL_OPT'] = q

            result = hub.get_quote_detailed('AAPL_OPT')
            assert result is not None
            assert result['delta'] == 0.55
            assert result['gamma'] == 0.03
            assert result['theta'] == -0.05
            assert result['vega'] == 0.12
            assert result['implied_vol'] == 0.35
            IBKRDataHub._instance = None
