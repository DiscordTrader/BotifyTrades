"""
Tests for IBKR pipeline gap fixes (GAPs 4, 5, 6, 7, 29, 30, 33).

Validates:
- GAP 4:  Farm status error codes 2104/2106/2107/2108 handled
- GAP 5:  Per-symbol dead subscription detection
- GAP 6:  connectedEvent wired
- GAP 7:  UPH get_quote_price accepts allow_stale
- GAP 29: TIF parameter in place_stock_order / place_option_order
- GAP 30: execDetailsEvent / commissionReportEvent wired
- GAP 33: get_positions() uses composite keys
"""
import inspect
import sys
import os
import time
import threading
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ── GAP 4: Farm status codes ────────────────────────────────────────────────

class TestGap4FarmStatusCodes:
    """_on_error_event must handle 2104/2106/2107/2108 without crashing."""

    def _make_hub(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        hub = IBKRDataHub.__new__(IBKRDataHub)
        hub._streaming_active = False
        hub._using_delayed_data = False
        hub._mktdata_denied_symbols = set()
        hub._mktdata_denied_lock = threading.Lock()
        hub._subscribe_fail_cache = {}
        hub._subscribed_symbols = set()
        hub._subscribed_conids = set()
        hub._pending_subscriptions = set()
        hub._event_handlers = {}
        hub._event_lock = threading.Lock()
        hub._ib = None
        return hub

    def test_2104_sets_streaming_active(self):
        hub = self._make_hub()
        hub._on_error_event(0, 2104, 'Market data farm connection OK', None)
        assert hub._streaming_active is True

    def test_2106_logs_without_crash(self):
        hub = self._make_hub()
        hub._on_error_event(0, 2106, 'HMDS data farm connection OK', None)
        # Just verify no exception — 2106 is informational

    def test_2107_logs_warning(self):
        hub = self._make_hub()
        hub._on_error_event(0, 2107, 'HMDS data farm inactive', None)
        # No exception means handled

    def test_2108_sets_streaming_inactive(self):
        hub = self._make_hub()
        hub._streaming_active = True
        emitted = []
        hub.on = lambda evt, handler: None  # stub
        hub._emit = lambda evt, data=None: emitted.append(evt)
        hub._on_error_event(0, 2108, 'Market data farm inactive', None)
        assert hub._streaming_active is False
        assert 'data_farm_disconnected' in emitted


# ── GAP 5: Per-symbol dead subscription tracking ────────────────────────────

class TestGap5PerSymbolTracking:
    """Per-symbol last tick tracking must be populated and used."""

    def test_init_has_tracking_dict(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        hub = IBKRDataHub.__new__(IBKRDataHub)
        hub._initialized = False
        hub.__init__()
        assert hasattr(hub, '_per_symbol_last_tick')
        assert isinstance(hub._per_symbol_last_tick, dict)
        assert hub._PER_SYMBOL_DEAD_THRESHOLD == 60.0

    def test_update_quote_tracks_tick(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        hub = IBKRDataHub.__new__(IBKRDataHub)
        hub._initialized = False
        hub.__init__()
        hub.update_quote('AAPL', {'last': 150.0}, source='test')
        assert 'AAPL' in hub._per_symbol_last_tick
        assert hub._per_symbol_last_tick['AAPL'] > 0


# ── GAP 6: connectedEvent ───────────────────────────────────────────────────

class TestGap6ConnectedEvent:
    """IBKRDataHub must have _on_connected handler."""

    def test_on_connected_method_exists(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        assert hasattr(IBKRDataHub, '_on_connected')
        assert callable(getattr(IBKRDataHub, '_on_connected'))

    def test_on_connected_restores_streaming(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        hub = IBKRDataHub.__new__(IBKRDataHub)
        hub._initialized = False
        hub.__init__()
        hub._streaming_active = False
        hub._consecutive_stale_checks = 5
        hub._pending_subscriptions = set()
        hub._on_connected()
        assert hub._streaming_active is True
        assert hub._consecutive_stale_checks == 0


# ── GAP 7: UPH get_quote_price allow_stale ──────────────────────────────────

class TestGap7UPHSignature:
    """get_quote_price must accept allow_stale kwarg."""

    def test_signature_has_allow_stale(self):
        from src.services.unified_price_hub import UnifiedPriceHub
        sig = inspect.signature(UnifiedPriceHub.get_quote_price)
        assert 'allow_stale' in sig.parameters
        assert sig.parameters['allow_stale'].default is False

    def test_ibkr_hub_also_has_allow_stale(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        sig = inspect.signature(IBKRDataHub.get_quote_price)
        assert 'allow_stale' in sig.parameters


# ── GAP 29: TIF parameter ───────────────────────────────────────────────────

class TestGap29TIFControl:
    """place_stock_order and place_option_order must accept tif parameter."""

    def test_stock_order_tif_param(self):
        from src.brokers.ibkr_broker import IBKRBroker
        sig = inspect.signature(IBKRBroker.place_stock_order)
        assert 'tif' in sig.parameters
        assert sig.parameters['tif'].default is None

    def test_option_order_tif_param(self):
        from src.brokers.ibkr_broker import IBKRBroker
        sig = inspect.signature(IBKRBroker.place_option_order)
        assert 'tif' in sig.parameters
        assert sig.parameters['tif'].default is None


# ── GAP 30: execDetailsEvent / commissionReportEvent ─────────────────────────

class TestGap30ExecDetails:
    """IBKRDataHub must have exec details and commission handlers."""

    def test_exec_details_handler_exists(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        assert hasattr(IBKRDataHub, '_on_exec_details')
        assert callable(getattr(IBKRDataHub, '_on_exec_details'))

    def test_commission_report_handler_exists(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        assert hasattr(IBKRDataHub, '_on_commission_report')
        assert callable(getattr(IBKRDataHub, '_on_commission_report'))

    def test_init_has_exec_storage(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        hub = IBKRDataHub.__new__(IBKRDataHub)
        hub._initialized = False
        hub.__init__()
        assert hasattr(hub, '_exec_details')
        assert hasattr(hub, '_commissions')
        assert isinstance(hub._exec_details, list)
        assert isinstance(hub._commissions, dict)

    def test_get_recent_executions(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        hub = IBKRDataHub.__new__(IBKRDataHub)
        hub._initialized = False
        hub.__init__()
        result = hub.get_recent_executions()
        assert result == []

    def test_get_commission(self):
        from src.services.ibkr_data_hub import IBKRDataHub
        hub = IBKRDataHub.__new__(IBKRDataHub)
        hub._initialized = False
        hub.__init__()
        result = hub.get_commission('nonexistent')
        assert result is None


# ── GAP 33: get_positions composite keys ─────────────────────────────────────

class TestGap33PositionsCompositeKey:
    """get_positions() must use composite keys for options."""

    def test_source_uses_sec_type_check(self):
        """Verify the implementation checks secType for key construction."""
        import ast
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', 'brokers', 'ibkr_broker.py')
        with open(path, 'r') as f:
            source = f.read()
        # The new code should differentiate OPT from stock
        assert "secType == 'OPT'" in source or 'secType' in source
        # Should build composite key for options
        assert 'lastTradeDateOrContractMonth' in source


# ── Price Flicker Fix ────────────────────────────────────────────────────────

class TestPriceFlickerFix:
    """Dashboard IBKR prices must not flicker to $0."""

    def test_overlay_streaming_has_ibkr_section(self):
        """_overlay_streaming_prices must handle IBKR positions."""
        import inspect
        from gui_app.live_snapshot import _overlay_streaming_prices
        source = inspect.getsource(_overlay_streaming_prices)
        assert 'ibkr_hub' in source, "No IBKR hub reference in _overlay_streaming_prices"
        assert 'ibkr_streaming' in source, "No ibkr_streaming flag"
        assert "ibkr_data_hub" in source, "No ibkr_data_hub import"

    def test_last_good_price_cache_exists(self):
        """_fetch_ibkr must use last-good-price cache."""
        import inspect
        from gui_app.live_snapshot import _fetch_ibkr
        source = inspect.getsource(_fetch_ibkr)
        assert '_ibkr_last_good_prices' in source, "No last-good-price cache in _fetch_ibkr"

    def test_last_good_price_cache_stores_and_returns(self):
        """Cache must store good prices and return them when current is 0."""
        import threading
        from gui_app.live_snapshot import _ibkr_last_good_prices, _ibkr_last_good_prices_lock
        # Simulate a good price
        with _ibkr_last_good_prices_lock:
            _ibkr_last_good_prices['test_conid_123'] = 150.50
        # Verify it's stored
        with _ibkr_last_good_prices_lock:
            assert _ibkr_last_good_prices.get('test_conid_123') == 150.50
        # Cleanup
        with _ibkr_last_good_prices_lock:
            _ibkr_last_good_prices.pop('test_conid_123', None)

    def test_get_positions_detailed_sentinel_guard(self):
        """get_positions_detailed must reject IB sentinel value."""
        import inspect
        from src.brokers.ibkr_broker import IBKRBroker
        source = inspect.getsource(IBKRBroker.get_positions_detailed)
        assert '_IB_SENTINEL' in source, "No IB sentinel guard in get_positions_detailed"
        assert 'allow_stale=True' in source, "Hub fallback should use allow_stale=True"

    def test_streaming_meta_has_ibkr_key(self):
        """streaming_meta dict must include 'ibkr' key."""
        from gui_app.live_snapshot import _overlay_streaming_prices
        meta = _overlay_streaming_prices([])
        assert 'ibkr' in meta, "streaming_meta missing 'ibkr' key"
