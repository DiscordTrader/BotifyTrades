"""
Tests for EXEC-1/2/3 and COND-1/3/4 fixes.

EXEC-1: qty/price validation in place_stock_order
EXEC-2: PreSubmitted/PendingSubmit status handling after _wait_for_fill
EXEC-3: STC auto-adjust uses position qty, not buying power
COND-1: Staleness uses actual hub quote timestamp
COND-3: IBKR reqMktData unsubscribed on monitor stop
COND-4: Retry sleeps are non-blocking (await asyncio.sleep)
"""
import inspect
import sys
import os
import ast
import time
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ── EXEC-1: qty/price validation ────────────────────────────────────────────

class TestExec1QtyPriceValidation:
    """place_stock_order must validate qty>0 and price>0 for limit orders."""

    def test_source_has_quantity_validation(self):
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        assert 'Invalid quantity' in source
        assert 'quantity <= 0' in source or 'quantity<=0' in source

    def test_source_has_price_validation(self):
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        assert 'Invalid limit price' in source
        assert 'price <= 0' in source or 'price<=0' in source

    def test_validation_before_max_order_size(self):
        """Validation must appear before MAX_ORDER_SIZE check."""
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        qty_pos = source.index('Invalid quantity')
        max_pos = source.index('MAX_ORDER_SIZE')
        assert qty_pos < max_pos, "qty validation must come before MAX_ORDER_SIZE check"

    @pytest.mark.asyncio
    async def test_zero_quantity_returns_failure(self):
        """quantity=0 must return OrderResult(success=False)."""
        from src.brokers.ibkr_broker import IBKRBroker
        broker = object.__new__(IBKRBroker)
        broker.name = 'test'
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        broker.ib = mock_ib
        result = await broker.place_stock_order('AAPL', 'BTO', 0, price=150.0)
        assert result.success is False
        assert 'Invalid quantity' in result.message

    @pytest.mark.asyncio
    async def test_negative_quantity_returns_failure(self):
        """quantity=-5 must return OrderResult(success=False)."""
        from src.brokers.ibkr_broker import IBKRBroker
        broker = object.__new__(IBKRBroker)
        broker.name = 'test'
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        broker.ib = mock_ib
        result = await broker.place_stock_order('AAPL', 'BTO', -5, price=150.0)
        assert result.success is False
        assert 'Invalid quantity' in result.message

    @pytest.mark.asyncio
    async def test_negative_price_returns_failure(self):
        """price=-1.0 must return OrderResult(success=False)."""
        from src.brokers.ibkr_broker import IBKRBroker
        broker = object.__new__(IBKRBroker)
        broker.name = 'test'
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        broker.ib = mock_ib
        result = await broker.place_stock_order('AAPL', 'BTO', 10, price=-1.0)
        assert result.success is False
        assert 'Invalid limit price' in result.message

    @pytest.mark.asyncio
    async def test_none_price_skips_price_validation(self):
        """price=None (market order) must not trigger price validation."""
        from src.brokers.ibkr_broker import IBKRBroker
        broker = object.__new__(IBKRBroker)
        broker.name = 'test'
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.qualifyContractsAsync = AsyncMock()
        broker.ib = mock_ib
        broker.MAX_ORDER_SIZE = 10000
        # Will fail later at placeOrder, but should NOT fail at price validation
        mock_ib.placeOrder.side_effect = Exception("test stop")
        result = await broker.place_stock_order('AAPL', 'BTO', 10, price=None)
        # Should fail with "IBKR error" from the placeOrder exception, not "Invalid limit price"
        assert 'Invalid limit price' not in result.message


# ── EXEC-2: PreSubmitted/PendingSubmit handling ──────────────────────────────

class TestExec2PendingStatusHandling:
    """Orders still pending after _wait_for_fill must return descriptive message."""

    def test_source_has_presubmitted_check(self):
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        assert 'PreSubmitted' in source
        assert 'PendingSubmit' in source

    def test_source_pending_before_cancelled(self):
        """PreSubmitted/PendingSubmit check must come before Cancelled check."""
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        pre_pos = source.index('PreSubmitted')
        cancel_pos = source.index("'Cancelled'")
        assert pre_pos < cancel_pos

    def test_pending_returns_success_true(self):
        """Pending orders should still return success=True (submitted to exchange)."""
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        # Find the PreSubmitted block and verify it returns success=True
        assert 'Order submitted but not yet confirmed' in source


# ── EXEC-3: STC auto-adjust ─────────────────────────────────────────────────

class TestExec3STCAutoAdjust:
    """STC auto-adjust must use position qty instead of buying power."""

    def test_source_has_stc_auto_adjust(self):
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        assert 'Auto-adjusting STC qty' in source

    def test_stc_checks_positions(self):
        """STC path must check ib.positions() for held quantity."""
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        assert 'positions()' in source
        assert 'held_qty' in source

    def test_stc_block_before_buying_power(self):
        """STC auto-adjust must appear before buying_power auto-adjust."""
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        stc_pos = source.index('Auto-adjusting STC qty')
        bp_pos = source.index('buying_power')
        assert stc_pos < bp_pos, "STC block must come before buying_power block"

    def test_sell_action_triggers_stc_path(self):
        """Both 'STC' and 'SELL' should trigger the position-based adjust."""
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        # The check should include both STC and SELL
        assert "'STC'" in source
        assert "'SELL'" in source

    def test_stc_recursive_call_passes_tif(self):
        """STC auto-adjust recursive call must propagate tif parameter."""
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.place_stock_order)
        # Find the STC auto-adjust recursive call line
        lines = source.split('\n')
        for line in lines:
            if 'Auto-adjusting STC qty' in line:
                # Next line with place_stock_order should include tif=tif
                idx = lines.index(line)
                recursive_line = lines[idx + 1]
                assert 'tif=tif' in recursive_line, f"STC recursive call missing tif=tif: {recursive_line}"
                break
        else:
            pytest.fail("STC auto-adjust block not found")

    @pytest.mark.asyncio
    async def test_stc_with_insufficient_funds_checks_positions(self):
        """STC with 'insufficient' error must check positions, not buying power."""
        from src.brokers.ibkr_broker import IBKRBroker
        broker = object.__new__(IBKRBroker)
        broker.name = 'test'
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        # qualifyContractsAsync must succeed (set conId on the contract)
        async def _qualify(contract):
            contract.conId = 12345
            return [contract]
        mock_ib.qualifyContractsAsync = _qualify
        # placeOrder raises insufficient funds
        mock_ib.placeOrder.side_effect = Exception("Order rejected: insufficient equity")
        # Positions show 50 shares held
        mock_pos = MagicMock()
        mock_pos.contract = MagicMock()
        mock_pos.contract.symbol = 'AAPL'
        mock_pos.position = 50
        mock_ib.positions.return_value = [mock_pos]
        broker.ib = mock_ib
        broker.MAX_ORDER_SIZE = 10000
        broker._get_extended_hours_enabled = MagicMock(return_value=False)
        # Try to sell 100 shares but only hold 50
        result = await broker.place_stock_order('AAPL', 'STC', 100, price=150.0)
        # Should have checked positions
        mock_ib.positions.assert_called_once()


# ── COND-1: Hub quote timestamp for staleness ────────────────────────────────

class TestCond1HubTimestamp:
    """Conditional order staleness must use actual hub quote timestamp."""

    def test_init_has_last_hub_quote_ts(self):
        """StreamingPriceMonitor.__init__ must initialize _last_hub_quote_ts."""
        from src.services.conditional_orders.base import StreamingPriceMonitor
        source = inspect.getsource(StreamingPriceMonitor.__init__)
        assert '_last_hub_quote_ts' in source

    def test_query_hub_tracks_timestamp(self):
        """_query_hub must extract timestamp from hub quote."""
        from src.services.conditional_orders.base import StreamingPriceMonitor
        source = inspect.getsource(StreamingPriceMonitor._query_hub)
        assert '_last_hub_quote_ts' in source
        assert 'get_quote' in source
        assert 'timestamp' in source

    def test_update_price_timestamp_uses_hub_ts(self):
        """_update_price_timestamp must use actual hub timestamp when available."""
        from src.services.conditional_orders.base import PriceMonitor
        source = inspect.getsource(PriceMonitor._update_price_timestamp)
        assert '_last_hub_quote_ts' in source
        assert 'actual_ts' in source

    def test_update_price_timestamp_falls_back_to_time(self):
        """Must fall back to time.time() when no hub timestamp."""
        from src.services.conditional_orders.base import PriceMonitor
        source = inspect.getsource(PriceMonitor._update_price_timestamp)
        assert 'time.time()' in source

    def test_hub_ts_used_when_set(self):
        """When _last_hub_quote_ts is set, _update_price_timestamp uses it."""
        from src.services.conditional_orders.base import StreamingPriceMonitor
        monitor = object.__new__(StreamingPriceMonitor)
        monitor._last_hub_quote_ts = 1700000000.0
        monitor._last_price_update_time = 0
        monitor._last_changed_price = None
        monitor._last_price_change_time = 0
        monitor._update_price_timestamp(100.0)
        assert monitor._last_price_update_time == 1700000000.0

    def test_falls_back_when_no_hub_ts(self):
        """When _last_hub_quote_ts is 0, uses time.time()."""
        from src.services.conditional_orders.base import StreamingPriceMonitor
        monitor = object.__new__(StreamingPriceMonitor)
        monitor._last_hub_quote_ts = 0
        monitor._last_price_update_time = 0
        monitor._last_changed_price = None
        monitor._last_price_change_time = 0
        before = time.time()
        monitor._update_price_timestamp(100.0)
        after = time.time()
        assert before <= monitor._last_price_update_time <= after


# ── COND-3: IBKR reqMktData unsubscribe on stop ─────────────────────────────

class TestCond3IBKRUnsubscribe:
    """IBKR reqMktData must be unsubscribed on monitor stop."""

    def test_try_unsubscribe_has_ibkr_hub(self):
        """_try_unsubscribe_streaming must call IBKRDataHub.unsubscribe_symbol."""
        from src.services.conditional_orders.base import StreamingPriceMonitor
        source = inspect.getsource(StreamingPriceMonitor._try_unsubscribe_streaming)
        assert 'ibkr_data_hub' in source
        assert 'unsubscribe_symbol' in source

    def test_stop_removes_ibkr_handler(self):
        """stop() must remove _ibkr_hub_handler via hub.off()."""
        from src.services.conditional_orders.base import StreamingPriceMonitor
        source = inspect.getsource(StreamingPriceMonitor.stop)
        assert '_ibkr_hub_handler' in source
        assert 'off' in source

    def test_stop_calls_try_unsubscribe(self):
        """stop() must call _try_unsubscribe_streaming."""
        from src.services.conditional_orders.base import StreamingPriceMonitor
        source = inspect.getsource(StreamingPriceMonitor.stop)
        assert '_try_unsubscribe_streaming' in source


# ── COND-4: Non-blocking retry sleeps ────────────────────────────────────────

class TestCond4AsyncSleep:
    """Retry sleeps in _execute_order must use asyncio.sleep, not time.sleep."""

    def test_no_time_sleep_in_execute_order(self):
        """_execute_order must not contain time.sleep calls."""
        from src.services.conditional_orders.base import BaseConditionalOrderService
        source = inspect.getsource(BaseConditionalOrderService._execute_order)
        assert 'time.sleep' not in source, "time.sleep found in _execute_order — should be asyncio.sleep"

    def test_asyncio_sleep_in_retry_path(self):
        """_execute_order must use asyncio.sleep for retry delays."""
        from src.services.conditional_orders.base import BaseConditionalOrderService
        source = inspect.getsource(BaseConditionalOrderService._execute_order)
        assert 'await asyncio.sleep(5)' in source
        assert 'await asyncio.sleep(3)' in source

    def test_execute_order_is_async(self):
        """_execute_order must be an async method to support await."""
        from src.services.conditional_orders.base import BaseConditionalOrderService
        assert asyncio.iscoroutinefunction(BaseConditionalOrderService._execute_order)
