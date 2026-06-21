"""
IBKR Data Hub
=============
Centralized cache and event bus for all IBKR data.
All services read from this hub instead of polling TWS/Gateway.

Architecture:
- Single source of truth for IBKR positions, orders, quotes, account info
- Event-driven: uses ib_insync native events (pendingTickersEvent, positionEvent, etc.)
- Quote data populated by reqMktData streaming (continuous, not snapshot)
- Position updates via positionEvent + periodic reconciliation
- Mirrors WebullDataHub/SchwabDataHub architecture for consistency
"""

import time
import asyncio
import threading
import logging
import copy
from typing import Dict, Optional, List, Any, Callable, Set

logger = logging.getLogger(__name__)


class IBKRQuoteData:
    __slots__ = ('symbol', 'contract_id', 'bid', 'ask', 'last', 'volume',
                 'high', 'low', 'open_price', 'close_price', 'change',
                 'change_pct', 'timestamp', 'source',
                 'delta', 'gamma', 'theta', 'vega', 'implied_vol')

    def __init__(self, symbol: str = '', contract_id: int = 0):
        self.symbol = symbol
        self.contract_id = contract_id
        self.bid = 0.0
        self.ask = 0.0
        self.last = 0.0
        self.volume = 0
        self.high = 0.0
        self.low = 0.0
        self.open_price = 0.0
        self.close_price = 0.0
        self.change = 0.0
        self.change_pct = 0.0
        self.timestamp = 0.0
        self.source = 'stream'
        self.delta = 0.0
        self.gamma = 0.0
        self.theta = 0.0
        self.vega = 0.0
        self.implied_vol = 0.0


class IBKRDataHub:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._quotes: Dict[str, IBKRQuoteData] = {}
        self._quotes_lock = threading.Lock()

        self._conid_to_symbol: Dict[int, str] = {}
        self._symbol_to_contract: Dict[str, Any] = {}
        self._contract_lock = threading.Lock()

        self._positions: List[Dict[str, Any]] = []
        self._positions_lock = threading.Lock()
        self._positions_time: float = 0

        self._account_info: Dict[str, Any] = {}
        self._account_lock = threading.Lock()
        self._account_time: float = 0

        self._event_handlers: Dict[str, List[Callable]] = {}
        self._event_lock = threading.Lock()

        self._streaming_active = False
        self._last_quote_ts: float = 0
        self._subscribed_symbols: Set[str] = set()
        self._subscribed_lock = threading.Lock()
        self._subscribed_conids: Set[int] = set()
        self._pending_subscriptions: Set[str] = set()

        self._ib = None
        self._broker = None
        self._loop = None

        self.POSITION_CACHE_TTL = 15
        self.ACCOUNT_CACHE_TTL = 30
        self.QUOTE_STALE_THRESHOLD = 300

        self._risk_eval_requested = threading.Event()
        self._reconcile_task = None

        self._mktdata_denied_symbols: Set[str] = set()
        self._mktdata_denied_lock = threading.Lock()
        self._subscribe_fail_cache: Dict[str, float] = {}
        self._qualify_in_progress: Set[str] = set()
        self._using_delayed_data = False

        # reqTickByTickData — bypasses IB internal aggregation for sub-ms delivery
        self._tick_by_tick_tickers: Dict[int, Any] = {}  # conId -> ib_insync Ticker
        self._tick_by_tick_count: int = 0
        self._TICK_BY_TICK_LIMIT = 20

        self._reconnect_in_progress = False
        self._reconnect_lock = threading.Lock()
        self._last_reconnect_ts: float = 0
        self._RECONNECT_COOLDOWN = 15.0
        self._consecutive_stale_checks = 0
        self._STALE_CHECK_THRESHOLD = 2

        self._exec_details: List[Dict[str, Any]] = []
        self._exec_details_lock = threading.Lock()
        self._commissions: Dict[str, Dict[str, Any]] = {}  # execId -> commission data
        self._commissions_lock = threading.Lock()
        self._per_symbol_last_tick: Dict[str, float] = {}
        self._PER_SYMBOL_DEAD_THRESHOLD = 60.0

        print("[IBKR_HUB] ✓ IBKRDataHub initialized (singleton)")

    def on(self, event: str, handler: Callable):
        with self._event_lock:
            if event not in self._event_handlers:
                self._event_handlers[event] = []
            self._event_handlers[event].append(handler)

    def off(self, event: str, handler: Callable):
        with self._event_lock:
            if event in self._event_handlers:
                self._event_handlers[event] = [h for h in self._event_handlers[event] if h != handler]

    def _emit(self, event: str, data: Any = None):
        with self._event_lock:
            handlers = list(self._event_handlers.get(event, []))
        for handler in handlers:
            try:
                handler(data)
            except Exception as e:
                print(f"[IBKR_HUB] Event handler error ({event}): {e}")

    def attach_broker(self, broker, loop=None):
        self._broker = broker
        self._ib = broker.ib
        self._loop = loop
        self._attach_events()
        try:
            self._ib.reqMarketDataType(1)
            print("[IBKR_HUB] ✓ Requested LIVE market data (type 1)")
        except Exception as e:
            print(f"[IBKR_HUB] ⚠️ reqMarketDataType failed: {e}")
        self._streaming_active = True
        if self._reconcile_task is None or self._reconcile_task.done():
            if self._loop and not self._loop.is_closed():
                self._reconcile_task = self._loop.create_task(self.start_reconciliation_loop(interval=10.0))
        self._tick_pump_task = None
        if self._loop and not self._loop.is_closed():
            self._tick_pump_task = self._loop.create_task(self._tick_pump_loop())
        print("[IBKR_HUB] ✓ Attached to IBKRBroker — streaming events active")

    def detach_broker(self):
        old_ib = self._ib
        self._streaming_active = False
        self._cancel_all_subscriptions()
        if old_ib:
            try:
                old_ib.pendingTickersEvent -= self._on_pending_tickers
                old_ib.positionEvent -= self._on_position_event
                old_ib.orderStatusEvent -= self._on_order_status
                old_ib.errorEvent -= self._on_error_event
                old_ib.disconnectedEvent -= self._on_disconnected
                old_ib.timeoutEvent -= self._on_timeout
                old_ib.execDetailsEvent -= self._on_exec_details
                old_ib.commissionReportEvent -= self._on_commission_report
                old_ib.connectedEvent -= self._on_connected
            except Exception:
                pass
        self._ib = None
        self._broker = None
        if self._reconcile_task and not self._reconcile_task.done():
            self._reconcile_task.cancel()
            self._reconcile_task = None
        print("[IBKR_HUB] Detached from broker — streaming stopped")

    def _attach_events(self):
        if not self._ib:
            return
        # Detach first — prevents duplicate handlers if attach_broker() is called
        # multiple times on the same IB object (e.g., after broker reconnect re-calls attach_broker).
        try:
            self._ib.pendingTickersEvent -= self._on_pending_tickers
            self._ib.positionEvent -= self._on_position_event
            self._ib.orderStatusEvent -= self._on_order_status
            self._ib.errorEvent -= self._on_error_event
            self._ib.disconnectedEvent -= self._on_disconnected
            self._ib.timeoutEvent -= self._on_timeout
            self._ib.execDetailsEvent -= self._on_exec_details
            self._ib.commissionReportEvent -= self._on_commission_report
            self._ib.connectedEvent -= self._on_connected
        except Exception:
            pass
        self._ib.pendingTickersEvent += self._on_pending_tickers
        self._ib.positionEvent += self._on_position_event
        self._ib.orderStatusEvent += self._on_order_status
        self._ib.errorEvent += self._on_error_event
        self._ib.disconnectedEvent += self._on_disconnected
        self._ib.timeoutEvent += self._on_timeout
        self._ib.execDetailsEvent += self._on_exec_details
        self._ib.commissionReportEvent += self._on_commission_report
        self._ib.connectedEvent += self._on_connected
        self._ib.setTimeout(30)
        print("[IBKR_HUB] ✓ Event handlers attached (tickers, positions, orders, errors, disconnect, timeout=30s)")

    def _on_error_event(self, reqId, errorCode, errorString, contract):
        if errorCode in (1100, 1101, 1102):
            if errorCode == 1100:
                print(f"[IBKR_HUB] ⚠️ TWS connectivity lost (error 1100: {errorString})")
                self._streaming_active = False
            elif errorCode == 1101:
                print(f"[IBKR_HUB] ✓ TWS connectivity restored — data lost (error 1101). Will re-subscribe.")
                self._streaming_active = True
                with self._subscribed_lock:
                    old_symbols = set(self._subscribed_symbols)
                    self._subscribed_symbols.clear()
                self._subscribed_conids.clear()
                for sym in old_symbols:
                    self._pending_subscriptions.add(sym)
            elif errorCode == 1102:
                print(f"[IBKR_HUB] ✓ TWS connectivity restored — data maintained (error 1102)")
                self._streaming_active = True
        elif errorCode == 504:
            print(f"[IBKR_HUB] ⚠️ Not connected to TWS (error 504)")
        elif errorCode == 502:
            print(f"[IBKR_HUB] ⚠️ Could not connect to TWS (error 502)")
        elif errorCode == 10167:
            if not self._using_delayed_data:
                self._using_delayed_data = True
                print("[IBKR_HUB] ⚠️ Using delayed market data (no real-time subscription)")
                try:
                    self._ib.reqMarketDataType(4)
                    print("[IBKR_HUB] ✓ Switched to delayed-frozen data (type 4)")
                except Exception:
                    pass
        elif errorCode in (10089, 10168):
            symbol = ''
            if contract:
                symbol = getattr(contract, 'symbol', '') or ''
            if symbol:
                with self._mktdata_denied_lock:
                    already_denied = symbol in self._mktdata_denied_symbols
                    self._mktdata_denied_symbols.add(symbol)
                if not already_denied:
                    logger.warning(f"[IBKR_HUB] ⚠️ Market data denied for {symbol} (error {errorCode}) — requesting delayed data and retrying")
                    try:
                        self._ib.reqMarketDataType(4)
                        with self._subscribed_lock:
                            self._subscribed_symbols.discard(symbol)
                        self._pending_subscriptions.add(symbol)
                    except Exception as e:
                        logger.warning(f"[IBKR_HUB] Delayed data retry failed for {symbol}: {e}")
                        self._subscribe_fail_cache[symbol] = time.time() + 3600
                        with self._subscribed_lock:
                            self._subscribed_symbols.discard(symbol)
                else:
                    self._subscribe_fail_cache[symbol] = time.time() + 3600
                    with self._subscribed_lock:
                        self._subscribed_symbols.discard(symbol)
        elif errorCode in (2104, 2106):
            # Farm connection OK — informational
            if errorCode == 2104:
                print(f"[IBKR_HUB] ✓ Market data farm connection OK (code 2104: {errorString})")
                self._streaming_active = True
            else:
                print(f"[IBKR_HUB] ✓ HMDS data farm connection OK (code 2106: {errorString})")
        elif errorCode in (2107, 2108):
            # Farm connection inactive — warning
            if errorCode == 2107:
                print(f"[IBKR_HUB] ⚠️ HMDS data farm connection is INACTIVE (code 2107: {errorString})")
            else:
                print(f"[IBKR_HUB] ⚠️ Market data farm connection is INACTIVE (code 2108: {errorString})")
                self._streaming_active = False
                self._emit('data_farm_disconnected', {'errorCode': errorCode, 'errorString': errorString})

    def _on_disconnected(self):
        print(f"[IBKR_HUB] ⚠️ TWS/Gateway DISCONNECTED — streaming prices will stop. Auto-reconnect will attempt in reconciliation loop.")
        self._streaming_active = False
        self._emit('disconnected', {})

    def _on_connected(self):
        print(f"[IBKR_HUB] ✓ TWS/Gateway CONNECTED event — streaming restored immediately")
        self._streaming_active = True
        self._consecutive_stale_checks = 0
        # Re-subscribe all symbols that were pending
        old_pending = set(self._pending_subscriptions)
        for sym in old_pending:
            with self._contract_lock:
                contract = self._symbol_to_contract.get(sym)
            if contract:
                self._start_market_data(sym, contract)
                self._pending_subscriptions.discard(sym)
        self._emit('connected', {})

    def _on_timeout(self, idlePeriod):
        is_connected = self._ib and self._ib.isConnected()
        if is_connected:
            print(f"[IBKR_HUB] ⚠️ TWS timeout — no data received for {idlePeriod:.0f}s (connection alive, keeping streaming active)")
            self._consecutive_stale_checks += 1
        else:
            print(f"[IBKR_HUB] ⚠️ TWS timeout — no data received for {idlePeriod:.0f}s. Connection lost, marking stale.")
            self._streaming_active = False
            self._consecutive_stale_checks = self._STALE_CHECK_THRESHOLD

    async def _attempt_reconnect(self):
        now = time.time()
        with self._reconnect_lock:
            if self._reconnect_in_progress:
                return False
            if now - self._last_reconnect_ts < self._RECONNECT_COOLDOWN:
                return False
            self._reconnect_in_progress = True
            self._last_reconnect_ts = now

        try:
            if not self._broker:
                print("[IBKR_HUB] Cannot reconnect — no broker reference")
                return False

            # If broker already reconnected with a new IB object, just re-attach to it.
            # Check self._ib is broker.ib — if broker reconnected it set self.ib = new IB().
            # self._ib still points to the OLD disconnected object until attach_broker() updates it.
            _broker_ib = getattr(self._broker, 'ib', None)
            if _broker_ib and _broker_ib is not self._ib and _broker_ib.isConnected():
                print("[IBKR_HUB] ✓ Broker already reconnected — re-attaching to new IB object")
                self._ib = _broker_ib
                self._attach_events()
                self._streaming_active = True
                return True

            # Defer to broker if it's mid-reconnect — avoid two IB() objects racing
            if getattr(self._broker, '_reconnect_in_progress', False):
                print("[IBKR_HUB] Broker reconnect in progress — deferring hub reconnect")
                return False

            print("[IBKR_HUB] 🔄 Attempting auto-reconnect to TWS/Gateway...")

            old_ib = self._ib
            if old_ib:
                try:
                    old_ib.pendingTickersEvent -= self._on_pending_tickers
                    old_ib.positionEvent -= self._on_position_event
                    old_ib.orderStatusEvent -= self._on_order_status
                    old_ib.errorEvent -= self._on_error_event
                    old_ib.disconnectedEvent -= self._on_disconnected
                    old_ib.timeoutEvent -= self._on_timeout
                    old_ib.execDetailsEvent -= self._on_exec_details
                    old_ib.commissionReportEvent -= self._on_commission_report
                    old_ib.connectedEvent -= self._on_connected
                except Exception:
                    pass
                try:
                    old_ib.disconnect()
                except Exception:
                    pass

            from ib_insync import IB
            new_ib = IB()
            host = getattr(self._broker, 'host', '127.0.0.1')
            port = getattr(self._broker, 'port', 7497)
            client_id = getattr(self._broker, 'client_id', 1)
            paper = getattr(self._broker, 'paper_trade', False)

            # Try primary port, then alternate (TWS↔Gateway) so reconnect survives
            # user switching between TWS and IB Gateway without restarting the bot.
            _GW = {True: 4002, False: 4001}
            _TWS = {True: 7497, False: 7496}
            _alt_port = _TWS[paper] if port in _GW.values() else _GW[paper]
            _ports = [port] if _alt_port == port else [port, _alt_port]

            connected_port = None
            for _p in _ports:
                try:
                    _label = "Gateway" if _p in _GW.values() else "TWS"
                    await new_ib.connectAsync(host=host, port=_p, clientId=client_id, timeout=15)
                    if new_ib.isConnected():
                        connected_port = _p
                        if _p != port:
                            self._broker.port = _p
                            print(f"[IBKR_HUB] 🔄 Reconnected via alternate {_label} port {_p}")
                        break
                except Exception as _ce:
                    _refused = 'refused' in str(_ce).lower() or '10061' in str(_ce) or '111' in str(_ce)
                    if _refused and _p != _ports[-1]:
                        print(f"[IBKR_HUB] Port {_p} refused — trying alternate port {_ports[1]}")
                        continue
                    raise

            if not connected_port or not new_ib.isConnected():
                print("[IBKR_HUB] ❌ Auto-reconnect failed — TWS/Gateway not responding")
                return False

            self._broker.ib = new_ib
            self._broker.connected = True
            self._ib = new_ib
            self._attach_events()
            self._streaming_active = True
            self._consecutive_stale_checks = 0
            self._using_delayed_data = False

            with self._quotes_lock:
                for q in self._quotes.values():
                    q.timestamp = 0

            with self._subscribed_lock:
                old_symbols = set(self._subscribed_symbols)
                self._subscribed_symbols.clear()
            self._subscribed_conids.clear()

            resubscribed = 0
            for sym in old_symbols:
                with self._contract_lock:
                    contract = self._symbol_to_contract.get(sym)
                if contract:
                    try:
                        _gtl = '233,426' if getattr(contract, 'secType', '') == 'OPT' else ''
                        self._ib.reqMktData(contract, _gtl, False, False)
                        with self._subscribed_lock:
                            self._subscribed_symbols.add(sym)
                        con_id = contract.conId if contract else 0
                        if con_id:
                            self._subscribed_conids.add(con_id)
                        resubscribed += 1
                    except Exception as e:
                        self._pending_subscriptions.add(sym)
                else:
                    self._pending_subscriptions.add(sym)

            print(f"[IBKR_HUB] ✅ Auto-reconnect SUCCESS — re-subscribed {resubscribed}/{len(old_symbols)} symbols")
            self._emit('reconnected', {'resubscribed': resubscribed})
            return True
        except Exception as e:
            print(f"[IBKR_HUB] ❌ Auto-reconnect error: {e}")
            return False
        finally:
            with self._reconnect_lock:
                self._reconnect_in_progress = False

    def is_symbol_denied(self, symbol: str) -> bool:
        with self._mktdata_denied_lock:
            return symbol.upper() in self._mktdata_denied_symbols

    def _on_tick_by_tick(self, ticker, tick):
        try:
            price = getattr(tick, 'price', None)
            if not price or price <= 0:
                return
            con_id = ticker.contract.conId if ticker.contract else 0
            symbol = self._conid_to_symbol.get(con_id)
            if not symbol and ticker.contract:
                symbol = self._build_symbol_key(ticker.contract)
            if not symbol:
                return
            self.update_quote(symbol, {'last': float(price)}, source='tick_by_tick')
        except Exception as e:
            print(f"[IBKR_HUB] ⚠️ _on_tick_by_tick error: {e}")

    def _on_pending_tickers(self, tickers):
        try:
            self._process_pending_tickers(tickers)
        except Exception as e:
            print(f"[IBKR_HUB] ⚠️ _on_pending_tickers error (ticks may be lost): {e}")

    def _process_pending_tickers(self, tickers):
        now = time.time()
        updated_symbols = []
        try:
            ticker_list = list(tickers) if not isinstance(tickers, list) else tickers
        except Exception:
            return
        conid_updates = {}
        with self._quotes_lock:
            for ticker in ticker_list:
                try:
                    con_id = ticker.contract.conId if ticker.contract else 0
                except Exception:
                    continue
                symbol = self._conid_to_symbol.get(con_id)
                if not symbol:
                    if ticker.contract:
                        symbol = self._build_symbol_key(ticker.contract)
                        if symbol:
                            conid_updates[con_id] = symbol
                if not symbol:
                    continue

                is_new = symbol not in self._quotes
                if is_new:
                    self._quotes[symbol] = IBKRQuoteData(symbol=symbol, contract_id=con_id)
                q = self._quotes[symbol]
                has_real_data = False
                if ticker.bid is not None and ticker.bid > 0:
                    q.bid = float(ticker.bid)
                    has_real_data = True
                if ticker.ask is not None and ticker.ask > 0:
                    q.ask = float(ticker.ask)
                    has_real_data = True
                if ticker.last is not None and ticker.last > 0:
                    q.last = float(ticker.last)
                    has_real_data = True
                elif q.bid > 0 and q.ask > 0:
                    q.last = round((q.bid + q.ask) / 2, 4)
                    has_real_data = True
                elif ticker.close is not None and ticker.close > 0:
                    q.close_price = float(ticker.close)
                if ticker.volume is not None:
                    q.volume = int(ticker.volume)
                if ticker.high is not None and ticker.high > 0:
                    q.high = float(ticker.high)
                if ticker.low is not None and ticker.low > 0:
                    q.low = float(ticker.low)
                # Mark price via modelGreeks (tick 233) — fills bid/ask gap for illiquid options
                try:
                    _mg = getattr(ticker, 'modelGreeks', None)
                    if _mg:
                        if not has_real_data and q.last == 0:
                            if getattr(_mg, 'optPrice', None) and _mg.optPrice > 0:
                                q.last = float(_mg.optPrice)
                                has_real_data = True
                        # GAP-1: Extract greeks
                        if _mg.delta is not None:
                            q.delta = float(_mg.delta)
                        if _mg.gamma is not None:
                            q.gamma = float(_mg.gamma)
                        if _mg.theta is not None:
                            q.theta = float(_mg.theta)
                        if _mg.vega is not None:
                            q.vega = float(_mg.vega)
                        if getattr(_mg, 'impliedVol', None) is not None and _mg.impliedVol > 0:
                            q.implied_vol = float(_mg.impliedVol)
                except Exception:
                    pass
                if has_real_data or is_new:
                    q.timestamp = now
                    updated_symbols.append(symbol)
                    self._per_symbol_last_tick[symbol] = now

        if conid_updates:
            with self._contract_lock:
                self._conid_to_symbol.update(conid_updates)
        self._last_quote_ts = now
        if not self._streaming_active:
            self._streaming_active = True
        for sym in updated_symbols:
            self._emit('quote_updated', {'symbol': sym, 'source': 'ibkr_stream', 'quote': self._quotes.get(sym)})

    def _on_position_event(self, *args):
        self._risk_eval_requested.set()
        try:
            if self._loop and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(
                    lambda: self._loop.create_task(self._refresh_positions_from_ib(from_event_callback=True))
                )
        except Exception as e:
            print(f"[IBKR_HUB] Position event refresh error: {e}")

    def _on_order_status(self, trade):
        try:
            status = trade.orderStatus.status if trade.orderStatus else ''
            if status in ('Filled', 'Cancelled'):
                self._risk_eval_requested.set()
                if self._loop and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(
                        lambda: self._loop.create_task(self._refresh_positions_from_ib(from_event_callback=True))
                    )
                self._emit('order_event', {
                    'status': status,
                    'order_id': trade.order.orderId if trade.order else None,
                    'symbol': trade.contract.symbol if trade.contract else ''
                })
        except Exception as e:
            print(f"[IBKR_HUB] Order status event error: {e}")

    def _on_exec_details(self, trade, fill):
        """Capture execution details: exact fill price, time, exchange, shares."""
        try:
            exec_data = {
                'exec_id': fill.execution.execId if fill.execution else '',
                'order_id': trade.order.orderId if trade.order else 0,
                'symbol': trade.contract.symbol if trade.contract else '',
                'sec_type': trade.contract.secType if trade.contract else '',
                'side': fill.execution.side if fill.execution else '',
                'shares': float(fill.execution.shares) if fill.execution else 0,
                'price': float(fill.execution.price) if fill.execution else 0,
                'exchange': fill.execution.exchange if fill.execution else '',
                'time': str(fill.execution.time) if fill.execution else '',
                'avg_price': float(fill.execution.avgPrice) if fill.execution and hasattr(fill.execution, 'avgPrice') else 0,
                'cum_qty': float(fill.execution.cumQty) if fill.execution and hasattr(fill.execution, 'cumQty') else 0,
            }
            with self._exec_details_lock:
                self._exec_details.append(exec_data)
                # Keep last 500 executions
                if len(self._exec_details) > 500:
                    self._exec_details = self._exec_details[-500:]
            self._emit('exec_details', exec_data)
            logger.info(f"[IBKR_HUB] Fill: {exec_data['side']} {exec_data['shares']} {exec_data['symbol']} @ ${exec_data['price']:.4f} on {exec_data['exchange']}")
        except Exception as e:
            logger.warning(f"[IBKR_HUB] execDetails handler error: {e}")

    def _on_commission_report(self, trade, fill, report):
        """Capture commission report: cost per fill for accurate P&L."""
        try:
            exec_id = report.execId if report else ''
            comm_data = {
                'exec_id': exec_id,
                'commission': float(report.commission) if report and report.commission else 0,
                'currency': report.currency if report else 'USD',
                'realized_pnl': float(report.realizedPNL) if report and hasattr(report, 'realizedPNL') and report.realizedPNL else 0,
            }
            with self._commissions_lock:
                self._commissions[exec_id] = comm_data
                # Keep last 500 commission reports
                if len(self._commissions) > 500:
                    oldest_keys = list(self._commissions.keys())[:len(self._commissions) - 500]
                    for k in oldest_keys:
                        del self._commissions[k]
            self._emit('commission_report', comm_data)
            logger.info(f"[IBKR_HUB] Commission: ${comm_data['commission']:.2f} {comm_data['currency']} (realized P&L: ${comm_data['realized_pnl']:.2f})")
        except Exception as e:
            logger.warning(f"[IBKR_HUB] commissionReport handler error: {e}")

    def _build_symbol_key(self, contract) -> str:
        if not contract:
            return ''
        if contract.secType == 'OPT':
            exp = contract.lastTradeDateOrContractMonth or ''
            right = contract.right or ''
            strike = contract.strike or 0
            return f"{contract.symbol}_{exp}_{strike}_{right}"
        return contract.symbol or ''

    def update_quote(self, symbol: str, quote_data: Dict[str, Any], source: str = "stream"):
        now = time.time()
        with self._quotes_lock:
            if symbol not in self._quotes:
                self._quotes[symbol] = IBKRQuoteData(symbol=symbol)
            q = self._quotes[symbol]
            q.bid = float(quote_data.get('bid', q.bid) or q.bid)
            q.ask = float(quote_data.get('ask', q.ask) or q.ask)
            q.last = float(quote_data.get('last', q.last) or q.last)
            q.volume = int(quote_data.get('volume', q.volume) or q.volume)
            q.timestamp = now
            q.source = source
        self._per_symbol_last_tick[symbol] = now
        self._last_quote_ts = now
        self._emit('quote_updated', {'symbol': symbol, 'source': source, 'quote': q})

    def get_quote(self, symbol: str, max_age: Optional[float] = None) -> Optional[IBKRQuoteData]:
        with self._quotes_lock:
            q = self._quotes.get(symbol)
            if not q:
                return None
            # HUB-5: Reject quotes with no real price data
            if q.last <= 0 and q.bid <= 0 and q.ask <= 0:
                return None
            effective_max_age = max_age if max_age is not None else self.QUOTE_STALE_THRESHOLD
            if (time.time() - q.timestamp) > effective_max_age:
                return None
            # HUB-1: Return defensive copy — prevents data race with streaming thread
            return copy.copy(q)

    def get_quote_price(self, symbol: str, allow_stale: bool = False) -> Optional[float]:
        with self._quotes_lock:
            q = self._quotes.get(symbol)
            if not q:
                return None
            if not allow_stale and (time.time() - q.timestamp) > self.QUOTE_STALE_THRESHOLD:
                return None
            if q.last and q.last > 0:
                return q.last
            if q.bid > 0 and q.ask > 0:
                return round((q.bid + q.ask) / 2, 4)
            if q.bid > 0:
                return q.bid
            if q.ask > 0:
                return q.ask
            return None

    def get_all_quotes(self) -> Dict[str, 'IBKRQuoteData']:
        """Return a snapshot of all fresh cached quotes — used by UPH poll_all_hubs."""
        now = time.time()
        with self._quotes_lock:
            return {
                sym: q for sym, q in self._quotes.items()
                if (q.last > 0 or q.bid > 0)
                and (now - q.timestamp) < self.QUOTE_STALE_THRESHOLD
            }

    def get_quote_detailed(self, symbol: str, max_age: Optional[float] = None) -> Optional[Dict[str, Any]]:
        with self._quotes_lock:
            q = self._quotes.get(symbol)
            if not q:
                return None
            if max_age and (time.time() - q.timestamp) > max_age:
                return None
            return {
                'symbol': q.symbol,
                'bid': q.bid,
                'ask': q.ask,
                'last': q.last,
                'volume': q.volume,
                'high': q.high,
                'low': q.low,
                'timestamp': q.timestamp,
                'source': q.source,
                'delta': q.delta,
                'gamma': q.gamma,
                'theta': q.theta,
                'vega': q.vega,
                'implied_vol': q.implied_vol,
            }

    def get_recent_executions(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._exec_details_lock:
            return list(self._exec_details[-limit:])

    def get_commission(self, exec_id: str) -> Optional[Dict[str, Any]]:
        with self._commissions_lock:
            return self._commissions.get(exec_id)

    def get_positions(self, max_age_seconds: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        with self._positions_lock:
            age = time.time() - self._positions_time
            ttl = max_age_seconds if max_age_seconds is not None else self.POSITION_CACHE_TTL
            if age > ttl:
                return None
            return list(self._positions)

    def get_positions_age(self) -> float:
        return time.time() - self._positions_time

    def update_positions(self, positions: List[Dict[str, Any]]):
        with self._positions_lock:
            self._positions = positions
            self._positions_time = time.time()
        current_symbols = set()
        for p in positions:
            sym = p.get('symbol', '')
            if sym:
                current_symbols.add(sym)
            raw = p.get('raw_symbol', '')
            if raw:
                current_symbols.add(raw)
        self._sync_subscriptions(current_symbols)
        self._emit('positions_updated', positions)

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        with self._account_lock:
            if not self._account_info:
                return None
            if (time.time() - self._account_time) > self.ACCOUNT_CACHE_TTL:
                return None
            return dict(self._account_info)

    def update_account_info(self, info: Dict[str, Any]):
        with self._account_lock:
            self._account_info = info
            self._account_time = time.time()

    def is_streaming(self) -> bool:
        if not self._streaming_active or self._ib is None:
            return False
        try:
            if hasattr(self._ib, 'isConnected') and not self._ib.isConnected():
                return False
        except Exception:
            pass
        return True

    def is_delayed(self) -> bool:
        return self._using_delayed_data

    def request_risk_eval(self):
        self._risk_eval_requested.set()

    def check_risk_eval_requested(self) -> bool:
        if self._risk_eval_requested.is_set():
            self._risk_eval_requested.clear()
            return True
        return False

    def _is_on_ib_loop(self) -> bool:
        if not self._loop:
            return False
        try:
            return asyncio.get_running_loop() is self._loop
        except RuntimeError:
            return False

    def subscribe_symbol(self, symbol: str, contract=None):
        with self._subscribed_lock:
            if symbol in self._subscribed_symbols:
                return
        # Option keys (e.g. "AAPL_20240120_150_C") must not be auto-queued for qualification —
        # their contract arrives via _refresh_positions_from_ib. If no contract is provided,
        # we must not mark them as subscribed since reqMktData will never fire for them.
        if '_' in symbol and contract is None:
            # GAP-3: Queue for subscription when contract becomes available (via portfolio refresh)
            self._pending_subscriptions.add(symbol)
            print(f"[IBKR_HUB] ⚠️ Option {symbol} queued for subscription (no contract yet — will subscribe on next portfolio refresh)")
            return
        if not self._ib or not self._streaming_active:
            self._pending_subscriptions.add(symbol)
            return
        with self._subscribed_lock:
            self._subscribed_symbols.add(symbol)
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._subscribe_on_loop(symbol, contract), self._loop
            )
        else:
            with self._subscribed_lock:
                self._subscribed_symbols.discard(symbol)
            self._pending_subscriptions.add(symbol)

    async def _subscribe_on_loop(self, symbol: str, contract=None):
        if contract:
            self._start_market_data(symbol, contract)
        else:
            await self._qualify_and_subscribe(symbol)

    _subscribe_fail_cache: dict = {}
    _SUBSCRIBE_FAIL_BACKOFF = 120.0

    async def _qualify_and_subscribe(self, symbol: str):
        import time as _time
        # Option keys contain '_' — they must have their contract registered by
        # _refresh_positions_from_ib before subscription. Auto-qualify only for plain tickers.
        if '_' in symbol:
            with self._subscribed_lock:
                self._subscribed_symbols.discard(symbol)
            logger.debug(f"[IBKR_HUB] Skipping auto-qualify for option key '{symbol}' — contract must come from positions")
            return
        # Prevent concurrent qualifications of the same symbol — two callers racing through
        # subscribe_symbol before either conId is registered causes duplicate reqMktData.
        if symbol in self._qualify_in_progress:
            return
        self._qualify_in_progress.add(symbol)
        try:
            with self._mktdata_denied_lock:
                if symbol in self._mktdata_denied_symbols:
                    with self._subscribed_lock:
                        self._subscribed_symbols.discard(symbol)
                    return
            fail_ts = self._subscribe_fail_cache.get(symbol, 0)
            if fail_ts and _time.time() - fail_ts < self._SUBSCRIBE_FAIL_BACKOFF:
                with self._subscribed_lock:
                    self._subscribed_symbols.discard(symbol)
                return
            try:
                from ib_insync import Stock
                auto_contract = Stock(symbol, 'SMART', 'USD')
                await self._ib.qualifyContractsAsync(auto_contract)
                self._start_market_data(symbol, auto_contract)
                self._subscribe_fail_cache.pop(symbol, None)
                logger.info(f"[IBKR_HUB] Auto-created Stock contract for {symbol} (conId={auto_contract.conId})")
            except Exception as e:
                self._subscribe_fail_cache[symbol] = _time.time()
                with self._subscribed_lock:
                    self._subscribed_symbols.discard(symbol)
                if 'event loop' in str(e).lower():
                    pass
                else:
                    logger.warning(f"[IBKR_HUB] Could not auto-create contract for {symbol}: {e}")
                    self._pending_subscriptions.add(symbol)
        finally:
            self._qualify_in_progress.discard(symbol)

    def _start_market_data(self, symbol: str, contract):
        if not self._ib:
            with self._subscribed_lock:
                self._subscribed_symbols.discard(symbol)
            return
        try:
            con_id = contract.conId if contract else 0
            # Atomically check-and-register the conId so concurrent callers (two qualify
            # coroutines both resuming at nearly the same time) can't both slip past the
            # duplicate check before either has added to _subscribed_conids.
            with self._contract_lock:
                if con_id in self._subscribed_conids:
                    return
                with self._subscribed_lock:
                    self._subscribed_symbols.add(symbol)
                self._subscribed_conids.add(con_id)
                self._conid_to_symbol[con_id] = symbol
                self._symbol_to_contract[symbol] = contract
            # Generic tick 233 = mark price, 426 = last yield — useful for illiquid options
            _gtl = '233,426' if getattr(contract, 'secType', '') == 'OPT' else ''
            self._ib.reqMktData(contract, _gtl, False, False)
            # reqTickByTickData bypasses IB internal aggregation — each exchange tick
            # arrives in ~100-300µs vs ~200-300ms from reqMktData batching.
            # AllLast includes OTC/grey-market prints important for illiquid small-caps.
            if self._tick_by_tick_count < self._TICK_BY_TICK_LIMIT:
                try:
                    tbt_ticker = self._ib.reqTickByTickData(contract, 'AllLast', 0, True)
                    tbt_ticker.tickByTickEvent += self._on_tick_by_tick
                    self._tick_by_tick_tickers[con_id] = tbt_ticker
                    self._tick_by_tick_count += 1
                    print(f"[IBKR_HUB] ✓ reqTickByTickData ({self._tick_by_tick_count}/{self._TICK_BY_TICK_LIMIT}) for {symbol}")
                except Exception as _tbt_e:
                    print(f"[IBKR_HUB] ⚠️ reqTickByTickData failed for {symbol}: {_tbt_e}")
        except Exception as e:
            with self._subscribed_lock:
                self._subscribed_symbols.discard(symbol)
            print(f"[IBKR_HUB] Failed to subscribe {symbol}: {e}")

    def unsubscribe_symbol(self, symbol: str):
        with self._contract_lock:
            contract = self._symbol_to_contract.pop(symbol, None)
        if not contract:
            with self._subscribed_lock:
                self._subscribed_symbols.discard(symbol)
            return
        con_id = contract.conId if contract else 0
        self._subscribed_conids.discard(con_id)
        with self._contract_lock:
            self._conid_to_symbol.pop(con_id, None)
        with self._subscribed_lock:
            self._subscribed_symbols.discard(symbol)
        tbt_ticker = self._tick_by_tick_tickers.pop(con_id, None)
        if tbt_ticker is not None:
            self._tick_by_tick_count = max(0, self._tick_by_tick_count - 1)
        if self._ib and self._loop and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(
                    lambda c=contract: self._ib.cancelMktData(c) if self._ib else None
                )
            except Exception:
                pass
            if tbt_ticker is not None:
                try:
                    self._loop.call_soon_threadsafe(
                        lambda t=tbt_ticker: self._ib.cancelTickByTickData(t) if self._ib else None
                    )
                except Exception:
                    pass

    def _cancel_all_subscriptions(self):
        with self._contract_lock:
            contracts = list(self._symbol_to_contract.values())
            self._symbol_to_contract.clear()
            self._conid_to_symbol.clear()
        with self._subscribed_lock:
            self._subscribed_symbols.clear()
        self._subscribed_conids.clear()
        tbt_tickers = list(self._tick_by_tick_tickers.values())
        self._tick_by_tick_tickers.clear()
        self._tick_by_tick_count = 0
        if self._ib and self._loop and not self._loop.is_closed():
            for contract in contracts:
                try:
                    self._loop.call_soon_threadsafe(
                        lambda c=contract: self._ib.cancelMktData(c) if self._ib else None
                    )
                except Exception:
                    pass
            for tbt in tbt_tickers:
                try:
                    self._loop.call_soon_threadsafe(
                        lambda t=tbt: self._ib.cancelTickByTickData(t) if self._ib else None
                    )
                except Exception:
                    pass

    def _sync_subscriptions(self, current_symbols: Set[str]):
        if not self._ib or not self._streaming_active:
            return
        with self._subscribed_lock:
            new_symbols = current_symbols - self._subscribed_symbols
            stale_symbols = self._subscribed_symbols - current_symbols

        for sym in stale_symbols:
            self.unsubscribe_symbol(sym)

        for sym in new_symbols:
            with self._contract_lock:
                contract = self._symbol_to_contract.get(sym)
            if contract:
                self._start_market_data(sym, contract)
            else:
                self._pending_subscriptions.add(sym)

    async def _refresh_positions_from_ib(self, from_event_callback=False):
        if not self._ib or not self._ib.isConnected():
            return
        try:
            # Always use portfolio() — it includes marketPrice (IB's mark price) in addition to
            # position/avgCost data. This ensures prices are available even for illiquid symbols
            # that don't receive frequent reqMktData ticks (e.g. low-volume penny stocks).
            raw_positions = await asyncio.to_thread(self._ib.portfolio)
            parsed = []
            _IB_SENTINEL = 1.7976931348623157e+308  # IB uses max float when price unavailable
            for pos in raw_positions:
                contract = pos.contract
                symbol = contract.symbol
                quantity = abs(int(pos.position))
                if quantity == 0:
                    continue
                avg_cost = float(pos.averageCost if hasattr(pos, 'averageCost') else pos.avgCost) if (getattr(pos, 'averageCost', None) or getattr(pos, 'avgCost', None)) else 0
                sym_key = self._build_symbol_key(contract)

                with self._contract_lock:
                    if contract.conId not in self._conid_to_symbol:
                        self._conid_to_symbol[contract.conId] = sym_key
                    if sym_key not in self._symbol_to_contract:
                        self._symbol_to_contract[sym_key] = contract

                entry = {
                    'symbol': symbol,
                    'quantity': quantity,
                    'avg_cost': avg_cost / 100 if contract.secType == 'OPT' and avg_cost > 0 else avg_cost,
                    'contract': contract,
                    'con_id': contract.conId,
                    'sec_type': contract.secType,
                    'raw_symbol': sym_key,
                }
                if contract.secType == 'OPT':
                    entry['strike'] = contract.strike
                    entry['expiry'] = contract.lastTradeDateOrContractMonth
                    entry['direction'] = contract.right
                    entry['asset'] = 'option'
                else:
                    entry['asset'] = 'stock'
                parsed.append(entry)

                # Market price from IB portfolio — used for both position dict and quote seed
                mkt_price = float(getattr(pos, 'marketPrice', 0) or 0)

                # Embed market_price in position dict — stored in SAME units as
                # hub quote cache (per-share). IB's marketPrice is already per-share
                # (no multiplier), unlike averageCost which includes 100x for options.
                # MUST match get_quote_price() return value to avoid false SL triggers.
                if 0 < mkt_price < _IB_SENTINEL:
                    entry['market_price'] = mkt_price
                else:
                    entry['market_price'] = 0

                # Seed IB's mark price into quotes so risk engine has a valid price even
                # when reqMktData ticks are sparse (illiquid symbols like low-volume stocks).
                if 0 < mkt_price < _IB_SENTINEL:
                    self.update_quote(sym_key, {'last': mkt_price}, source='portfolio')

            self.update_positions(parsed)

            for p in parsed:
                sym_key = p.get('raw_symbol', p['symbol'])
                contract = p.get('contract')
                with self._subscribed_lock:
                    already_subscribed = sym_key in self._subscribed_symbols
                if contract and not already_subscribed:
                    self._start_market_data(sym_key, contract)

        except Exception as e:
            print(f"[IBKR_HUB] Position refresh error: {e}")

    async def _tick_pump_loop(self):
        """Yield to the event loop so ib_insync's socket reader fires promptly.
        10ms yield keeps reqTickByTickData latency near the IB Gateway TCP delivery
        time (~100-300µs). Without any yield, ticks queue while risk/sync tasks run."""
        logged = False
        while True:
            try:
                await asyncio.sleep(0.01)
                if not logged and self._ib and self._ib.isConnected():
                    logged = True
                    print("[IBKR_HUB] ✓ Tick pump active — event loop yields every 10ms (reqTickByTickData enabled)")
            except Exception:
                await asyncio.sleep(1)

    async def start_reconciliation_loop(self, interval: float = 5.0):
        print(f"[IBKR_HUB] ✓ Position reconciliation loop started ({interval}s)")
        while True:
            try:
                await asyncio.sleep(interval)

                is_connected = self._ib and self._ib.isConnected()
                with self._subscribed_lock:
                    has_subs = len(self._subscribed_symbols) > 0
                quote_age = (time.time() - self._last_quote_ts) if self._last_quote_ts > 0 else 0

                if not is_connected and self._broker:
                    print(f"[IBKR_HUB] ⚠️ Connection lost detected in reconciliation loop — attempting reconnect")
                    reconnected = await self._attempt_reconnect()
                    if reconnected:
                        continue
                    else:
                        await asyncio.sleep(self._RECONNECT_COOLDOWN)
                        continue

                if is_connected and has_subs and self._last_quote_ts > 0 and quote_age > 30:
                    self._consecutive_stale_checks += 1
                    if self._consecutive_stale_checks >= self._STALE_CHECK_THRESHOLD:
                        with self._subscribed_lock:
                            print(f"[IBKR_HUB] ⚠️ Price data stale for {quote_age:.0f}s with {len(self._subscribed_symbols)} active subscriptions — connection may be zombie, attempting reconnect")
                        reconnected = await self._attempt_reconnect()
                        if reconnected:
                            continue
                else:
                    self._consecutive_stale_checks = 0

                if is_connected:
                    if not self._streaming_active:
                        self._streaming_active = True
                        print("[IBKR_HUB] ✓ Connection alive — restored streaming_active after timeout")

                    # Per-symbol dead subscription detection — re-subscribe symbols that stopped receiving ticks
                    now_dead_check = time.time()
                    if self._per_symbol_last_tick:
                        dead_symbols = []
                        with self._subscribed_lock:
                            check_syms = list(self._subscribed_symbols)
                        for sym in check_syms:
                            last_tick = self._per_symbol_last_tick.get(sym, 0)
                            if last_tick > 0 and (now_dead_check - last_tick) > self._PER_SYMBOL_DEAD_THRESHOLD:
                                dead_symbols.append(sym)
                        if dead_symbols:
                            print(f"[IBKR_HUB] ⚠️ Dead subscriptions detected ({len(dead_symbols)} symbols, >{self._PER_SYMBOL_DEAD_THRESHOLD:.0f}s no ticks): {dead_symbols[:5]}")
                            for sym in dead_symbols:
                                with self._subscribed_lock:
                                    self._subscribed_symbols.discard(sym)
                                with self._contract_lock:
                                    contract = self._symbol_to_contract.get(sym)
                                if contract:
                                    try:
                                        self._ib.cancelMktData(contract)
                                    except Exception:
                                        pass
                                    self._pending_subscriptions.add(sym)
                                self._per_symbol_last_tick.pop(sym, None)

                    await self._refresh_positions_from_ib()

                    for sym in list(self._pending_subscriptions):
                        with self._contract_lock:
                            contract = self._symbol_to_contract.get(sym)
                        if contract:
                            self._start_market_data(sym, contract)
                            self._pending_subscriptions.discard(sym)
                        elif '_' not in sym:
                            # Route through _qualify_and_subscribe so the _qualify_in_progress
                            # guard prevents a duplicate reqMktData from running concurrently
                            # with subscribe_symbol's own _qualify_and_subscribe call.
                            self._pending_subscriptions.discard(sym)
                            with self._subscribed_lock:
                                self._subscribed_symbols.add(sym)
                            await self._qualify_and_subscribe(sym)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[IBKR_HUB] Reconciliation error: {e}")
                await asyncio.sleep(5)


_ibkr_hub_instance: Optional[IBKRDataHub] = None
_ibkr_hub_lock = threading.Lock()

def get_ibkr_data_hub() -> IBKRDataHub:
    global _ibkr_hub_instance
    if _ibkr_hub_instance is None:
        with _ibkr_hub_lock:
            if _ibkr_hub_instance is None:
                _ibkr_hub_instance = IBKRDataHub()
    return _ibkr_hub_instance
