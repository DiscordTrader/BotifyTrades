"""Tests for COND-2, HUB-3, GAP-1, GAP-3 fixes."""
import sys
import os
import threading
import time
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ---------- GAP-1: Greeks in IBKRQuoteData ----------

class TestGAP1GreeksInQuoteData:
    """GAP-1: IBKRQuoteData should have greeks fields populated from modelGreeks."""

    def test_greeks_slots_exist(self):
        from src.services.ibkr_data_hub import IBKRQuoteData
        q = IBKRQuoteData('AAPL_20240120_150_C', 99999)
        for attr in ('delta', 'gamma', 'theta', 'vega', 'implied_vol'):
            assert hasattr(q, attr), f"Missing slot: {attr}"

    def test_greeks_default_zero(self):
        from src.services.ibkr_data_hub import IBKRQuoteData
        q = IBKRQuoteData('SPY_20240315_500_C')
        assert q.delta == 0.0
        assert q.gamma == 0.0
        assert q.theta == 0.0
        assert q.vega == 0.0
        assert q.implied_vol == 0.0

    def test_greeks_settable(self):
        from src.services.ibkr_data_hub import IBKRQuoteData
        q = IBKRQuoteData('AAPL')
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
        from src.services.ibkr_data_hub import IBKRQuoteData
        q = IBKRQuoteData('TEST')
        with pytest.raises(AttributeError):
            q.nonexistent_field = 42


# ---------- HUB-3: _subscribed_lock ----------

class TestHUB3SubscribedLock:
    """HUB-3: _subscribed_symbols must be protected by _subscribed_lock."""

    def _make_hub(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        IBKRDataHub._instance = None
        try:
            hub = object.__new__(IBKRDataHub)
            hub._initialized = False
            hub.__init__()
            return hub
        finally:
            IBKRDataHub._instance = None

    def test_subscribed_lock_exists(self):
        hub = self._make_hub()
        assert hasattr(hub, '_subscribed_lock')
        assert isinstance(hub._subscribed_lock, type(threading.Lock()))

    def test_subscribe_already_subscribed_noop(self):
        hub = self._make_hub()
        hub._subscribed_symbols.add('AAPL')
        hub.subscribe_symbol('AAPL')
        assert 'AAPL' in hub._subscribed_symbols


# ---------- GAP-3: Option queue ----------

class TestGAP3OptionQueueing:
    """GAP-3: Option symbols without contracts should be queued, not silently dropped."""

    def _make_hub(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        IBKRDataHub._instance = None
        try:
            hub = object.__new__(IBKRDataHub)
            hub._initialized = False
            hub.__init__()
            return hub
        finally:
            IBKRDataHub._instance = None

    def test_option_without_contract_queued(self):
        hub = self._make_hub()
        hub.subscribe_symbol('AAPL_20240120_150_C', contract=None)
        assert 'AAPL_20240120_150_C' in hub._pending_subscriptions
        assert 'AAPL_20240120_150_C' not in hub._subscribed_symbols

    def test_option_with_contract_no_ib_goes_pending(self):
        hub = self._make_hub()
        mock_contract = MagicMock()
        hub.subscribe_symbol('AAPL_20240120_150_C', contract=mock_contract)
        # Without _ib connected, goes to pending
        assert 'AAPL_20240120_150_C' in hub._pending_subscriptions

    def test_stock_without_ib_goes_pending(self):
        hub = self._make_hub()
        hub.subscribe_symbol('MSFT')
        assert 'MSFT' in hub._pending_subscriptions


# ---------- COND-2: No callback → ERROR ----------

class TestCOND2NoCallbackError:
    """COND-2: Orders with no execution_callback should go to ERROR status."""

    def test_else_branch_exists_in_source(self):
        """Verify the else branch with NO_CALLBACK event exists."""
        import inspect
        from src.services.conditional_orders.base import BaseConditionalOrderService
        source = inspect.getsource(BaseConditionalOrderService._execute_order)
        assert 'NO_CALLBACK' in source, "NO_CALLBACK event not found in _execute_order"
        assert 'Execution callback not wired' in source, "Error message not found"
        assert 'callback_success = False' in source, "callback_success not set to False"
        # Must clean up executing state
        assert '_executing_orders.discard(order_id)' in source, "executing cleanup missing"
        assert '_execution_locks.pop(order_id' in source, "lock cleanup missing"
        # Must notify on failure
        assert 'notify_conditional_failed' in source, "failure notification missing"


# ---------- GAP-1: Greeks in detailed quote ----------

class TestGAP1GreeksInDetailedQuote:
    """GAP-1: get_quote_detailed should include greeks fields."""

    def test_detailed_quote_has_greeks(self):
        from src.services.ibkr_data_hub import IBKRDataHub, IBKRQuoteData
        IBKRDataHub._instance = None
        try:
            hub = object.__new__(IBKRDataHub)
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

            hub._quotes['AAPL_OPT'] = q

            result = hub.get_quote_detailed('AAPL_OPT')
            assert result is not None
            assert result['delta'] == 0.55
            assert result['gamma'] == 0.03
            assert result['theta'] == -0.05
            assert result['vega'] == 0.12
            assert result['implied_vol'] == 0.35
        finally:
            IBKRDataHub._instance = None
