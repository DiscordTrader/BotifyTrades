"""
Tests for IBKR Data Hub GAPs 4, 5, 6:
  GAP 4: Farm status codes 2104/2106/2107/2108 handling
  GAP 5: Per-symbol dead subscription detection
  GAP 6: connectedEvent wiring and _on_connected handler
"""
import time
import threading
from unittest.mock import MagicMock, patch


def _make_hub():
    """Create a fresh IBKRDataHub for testing, bypassing singleton."""
    with patch('src.services.ibkr_data_hub.IBKRDataHub.__new__', lambda cls: object.__new__(cls)):
        from src.services.ibkr_data_hub import IBKRDataHub
        hub = object.__new__(IBKRDataHub)
        hub._initialized = False
        hub.__init__()
        return hub


def _make_hub_with_ib():
    """Create hub with a mocked IB connection."""
    hub = _make_hub()
    mock_ib = MagicMock()
    mock_ib.isConnected.return_value = True
    hub._ib = mock_ib
    hub._broker = MagicMock()
    return hub, mock_ib


# ─── GAP 4: Farm status codes ───


class TestFarmStatusCodes:
    def test_2104_market_data_farm_ok(self):
        hub = _make_hub()
        hub._streaming_active = False
        hub._on_error_event(reqId=-1, errorCode=2104,
                            errorString="Market data farm connection is OK:usfarm",
                            contract=None)
        assert hub._streaming_active is True

    def test_2106_hmds_farm_ok(self):
        hub = _make_hub()
        hub._streaming_active = False
        # 2106 does NOT set _streaming_active (it's HMDS, not market data)
        hub._on_error_event(reqId=-1, errorCode=2106,
                            errorString="HMDS data farm connection is OK:ushmds",
                            contract=None)
        assert hub._streaming_active is False  # unchanged

    def test_2107_hmds_farm_inactive(self):
        hub = _make_hub()
        hub._streaming_active = True
        # 2107 logs warning but does NOT change _streaming_active
        hub._on_error_event(reqId=-1, errorCode=2107,
                            errorString="HMDS data farm connection is inactive",
                            contract=None)
        assert hub._streaming_active is True  # unchanged

    def test_2108_market_data_farm_inactive(self):
        hub = _make_hub()
        hub._streaming_active = True
        emitted = []
        hub.on('data_farm_disconnected', lambda data: emitted.append(data))
        hub._on_error_event(reqId=-1, errorCode=2108,
                            errorString="Market data farm connection is inactive",
                            contract=None)
        assert hub._streaming_active is False
        assert len(emitted) == 1
        assert emitted[0]['errorCode'] == 2108

    def test_farm_codes_dont_crash(self):
        hub = _make_hub()
        for code in (2104, 2106, 2107, 2108):
            hub._on_error_event(reqId=-1, errorCode=code,
                                errorString=f"Test string for {code}",
                                contract=None)


# ─── GAP 5: Per-symbol dead subscription detection ───


class TestPerSymbolDeadDetection:
    def test_init_has_tracking_dict(self):
        hub = _make_hub()
        assert hasattr(hub, '_per_symbol_last_tick')
        assert isinstance(hub._per_symbol_last_tick, dict)
        assert hub._PER_SYMBOL_DEAD_THRESHOLD == 60.0

    def test_update_quote_tracks_symbol(self):
        hub = _make_hub()
        before = time.time()
        hub.update_quote('AAPL', {'last': 150.0}, source='test')
        after = time.time()
        assert 'AAPL' in hub._per_symbol_last_tick
        assert before <= hub._per_symbol_last_tick['AAPL'] <= after

    def test_process_pending_tickers_tracks_symbol(self):
        hub = _make_hub()
        # Set up conid mapping
        hub._conid_to_symbol[12345] = 'MSFT'
        # Create a mock ticker
        ticker = MagicMock()
        ticker.contract = MagicMock()
        ticker.contract.conId = 12345
        ticker.bid = 400.0
        ticker.ask = 401.0
        ticker.last = 400.5
        ticker.close = None
        ticker.volume = 1000
        ticker.high = 405.0
        ticker.low = 395.0
        ticker.contract.symbol = 'MSFT'
        ticker.contract.secType = 'STK'
        hub._process_pending_tickers([ticker])
        assert 'MSFT' in hub._per_symbol_last_tick

    def test_dead_symbol_detection_logic(self):
        """Verify that symbols exceeding the dead threshold are detected."""
        hub = _make_hub()
        now = time.time()
        # Symbol with recent tick — should NOT be dead
        hub._per_symbol_last_tick['AAPL'] = now - 10
        hub._subscribed_symbols.add('AAPL')
        # Symbol with old tick — should be dead
        hub._per_symbol_last_tick['DEAD'] = now - 120
        hub._subscribed_symbols.add('DEAD')

        dead_symbols = []
        for sym in list(hub._subscribed_symbols):
            last_tick = hub._per_symbol_last_tick.get(sym, 0)
            if last_tick > 0 and (now - last_tick) > hub._PER_SYMBOL_DEAD_THRESHOLD:
                dead_symbols.append(sym)

        assert 'DEAD' in dead_symbols
        assert 'AAPL' not in dead_symbols


# ─── GAP 6: connectedEvent wiring ───


class TestConnectedEvent:
    def test_on_connected_restores_streaming(self):
        hub = _make_hub()
        hub._streaming_active = False
        hub._consecutive_stale_checks = 5
        hub._on_connected()
        assert hub._streaming_active is True
        assert hub._consecutive_stale_checks == 0

    def test_on_connected_emits_event(self):
        hub = _make_hub()
        emitted = []
        hub.on('connected', lambda data: emitted.append(data))
        hub._on_connected()
        assert len(emitted) == 1

    def test_on_connected_resubscribes_pending(self):
        hub, mock_ib = _make_hub_with_ib()
        hub._streaming_active = False

        # Set up a pending subscription with a known contract
        mock_contract = MagicMock()
        hub._pending_subscriptions.add('AAPL')
        hub._symbol_to_contract['AAPL'] = mock_contract

        # Mock _start_market_data
        hub._start_market_data = MagicMock()

        hub._on_connected()

        hub._start_market_data.assert_called_once_with('AAPL', mock_contract)
        assert 'AAPL' not in hub._pending_subscriptions

    def test_attach_events_wires_connected(self):
        """Verify _attach_events calls connectedEvent += _on_connected."""
        hub = _make_hub()
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        # Use a real list to track += calls
        connected_handlers = []
        event_obj = MagicMock()
        event_obj.__iadd__ = lambda self_ev, handler: (connected_handlers.append(('add', handler)), self_ev)[1]
        event_obj.__isub__ = lambda self_ev, handler: (connected_handlers.append(('sub', handler)), self_ev)[1]
        mock_ib.connectedEvent = event_obj
        hub._ib = mock_ib
        hub._broker = MagicMock()
        hub._attach_events()
        add_calls = [h for op, h in connected_handlers if op == 'add']
        assert any(h == hub._on_connected for h in add_calls), f"_on_connected not wired via +=, got: {add_calls}"

    def test_detach_broker_unwires_connected(self):
        """Verify detach_broker calls connectedEvent -= _on_connected."""
        hub = _make_hub()
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        connected_handlers = []
        event_obj = MagicMock()
        event_obj.__iadd__ = lambda self_ev, handler: (connected_handlers.append(('add', handler)), self_ev)[1]
        event_obj.__isub__ = lambda self_ev, handler: (connected_handlers.append(('sub', handler)), self_ev)[1]
        mock_ib.connectedEvent = event_obj
        hub._ib = mock_ib
        hub._broker = MagicMock()
        hub._reconcile_task = None
        hub.detach_broker()
        sub_calls = [h for op, h in connected_handlers if op == 'sub']
        assert any(h == hub._on_connected for h in sub_calls), f"_on_connected not unwired via -=, got: {sub_calls}"
