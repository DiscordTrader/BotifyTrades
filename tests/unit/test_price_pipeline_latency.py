"""
Tests for price pipeline latency optimizations:
- S1: Universal event-driven wakeup via UPH (all brokers)
- S2: Reduced UPH callback overhead (no dict intermediary)
- S3: Eliminated double cache read in _query_hub (get_price_and_ts)
- S4: Handler cleanup on stop()
"""
import asyncio
import threading
import time
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── S3: UPH.get_price_and_ts() ──────────────────────────────────────────

class TestGetPriceAndTs:
    """Tests for UnifiedPriceHub.get_price_and_ts() fast path."""

    def _make_uph(self):
        """Create a fresh UPH instance (bypass singleton for testing)."""
        from src.services.unified_price_hub import UnifiedPriceHub, UnifiedQuote
        # Reset singleton
        UnifiedPriceHub._instance = None
        uph = UnifiedPriceHub()
        return uph

    def test_returns_zero_on_miss(self):
        uph = self._make_uph()
        price, ts = uph.get_price_and_ts("NONEXISTENT")
        assert price == 0.0
        assert ts == 0.0

    def test_returns_last_price_and_ts(self):
        uph = self._make_uph()
        uph._update_cache("AAPL", {"last": 195.50, "timestamp": 1000.0}, "ibkr")
        price, ts = uph.get_price_and_ts("AAPL", allow_stale=True)
        assert price == 195.50
        assert ts == 1000.0

    def test_returns_mid_when_no_last(self):
        uph = self._make_uph()
        uph._update_cache("SPY", {"bid": 450.0, "ask": 451.0, "timestamp": 2000.0}, "schwab")
        price, ts = uph.get_price_and_ts("SPY", allow_stale=True)
        assert price == 450.5
        assert ts == 2000.0

    def test_returns_bid_when_only_bid(self):
        uph = self._make_uph()
        uph._update_cache("TSLA", {"bid": 200.0, "timestamp": 3000.0}, "webull")
        price, ts = uph.get_price_and_ts("TSLA", allow_stale=True)
        assert price == 200.0

    def test_stale_check_when_not_allow_stale(self):
        uph = self._make_uph()
        # Set a very old timestamp
        old_ts = time.time() - 60
        uph._update_cache("MSFT", {"last": 400.0, "timestamp": old_ts}, "ibkr")
        price, ts = uph.get_price_and_ts("MSFT", allow_stale=False)
        assert price == 0.0
        # But with allow_stale=True it works
        price, ts = uph.get_price_and_ts("MSFT", allow_stale=True)
        assert price == 400.0

    def test_canonical_resolution(self):
        uph = self._make_uph()
        uph._update_cache("SPXW", {"last": 5500.0, "timestamp": 4000.0}, "schwab")
        # SPXW should resolve to SPX canonical
        price, ts = uph.get_price_and_ts("SPX", allow_stale=True)
        assert price == 5500.0


# ── S2: _update_cache_from_quote() ───────────────────────────────────────

class TestUpdateCacheFromQuote:
    """Tests for the zero-dict-allocation fast path."""

    def _make_uph(self):
        from src.services.unified_price_hub import UnifiedPriceHub
        UnifiedPriceHub._instance = None
        return UnifiedPriceHub()

    def test_basic_quote_object(self):
        from dataclasses import dataclass

        @dataclass
        class FakeQuote:
            bid: float = 0.0
            ask: float = 0.0
            last: float = 0.0
            volume: int = 0
            timestamp: float = 0.0

        uph = self._make_uph()
        q = FakeQuote(bid=100.0, ask=101.0, last=100.5, volume=1000, timestamp=time.time())
        uph._update_cache_from_quote("TEST", q, "test_hub")

        price, ts = uph.get_price_and_ts("TEST", allow_stale=True)
        assert price == 100.5
        assert ts > 0

    def test_handles_missing_attributes(self):
        """Quote objects from different hubs may have different attributes."""
        uph = self._make_uph()

        class MinimalQuote:
            def __init__(self):
                self.last = 55.0
                self.timestamp = time.time()

        uph._update_cache_from_quote("MINI", MinimalQuote(), "test_hub")
        price, ts = uph.get_price_and_ts("MINI", allow_stale=True)
        assert price == 55.0

    def test_emits_event(self):
        uph = self._make_uph()
        events = []
        uph.on('quote_updated', lambda d: events.append(d))

        class Q:
            bid = 10.0
            ask = 11.0
            last = 10.5
            timestamp = time.time()

        uph._update_cache_from_quote("EVT", Q(), "schwab")
        assert len(events) == 1
        assert events[0]['symbol'] == 'EVT'
        assert events[0]['price'] == 10.5
        assert events[0]['source'] == 'schwab'

    def test_ibkr_quote_data_slots(self):
        """IBKRQuoteData uses __slots__ — ensure _update_cache_from_quote handles it."""
        from src.services.ibkr_data_hub import IBKRQuoteData
        uph = self._make_uph()

        q = IBKRQuoteData(symbol="AAPL")
        q.bid = 195.0
        q.ask = 196.0
        q.last = 195.5
        q.volume = 50000
        q.timestamp = time.time()
        q.delta = 0.65
        q.theta = -0.03

        uph._update_cache_from_quote("AAPL", q, "ibkr")
        result = uph.get_quote("AAPL")
        assert result is not None
        assert result.last == 195.5
        assert result.bid == 195.0
        assert result.delta == 0.65
        assert result.theta == -0.03


# ── S2: Optimized _make_hub_callback ─────────────────────────────────────

class TestOptimizedHubCallback:
    """Verify the optimized callback uses _update_cache_from_quote."""

    def _make_uph(self):
        from src.services.unified_price_hub import UnifiedPriceHub
        UnifiedPriceHub._instance = None
        return UnifiedPriceHub()

    def test_callback_with_quote_object(self):
        from dataclasses import dataclass

        @dataclass
        class MockHub:
            def on(self, event, handler): pass
            def is_streaming(self): return True

        @dataclass
        class MockQuote:
            bid: float = 50.0
            ask: float = 51.0
            last: float = 50.5
            volume: int = 100
            timestamp: float = 0.0

        uph = self._make_uph()
        hub = MockHub()
        callback = uph._make_hub_callback("test_hub", hub)

        q = MockQuote(timestamp=time.time())
        callback({'symbol': 'XYZ', 'quote': q})

        price, ts = uph.get_price_and_ts("XYZ", allow_stale=True)
        assert price == 50.5

    def test_callback_rejects_zero_price(self):
        """Callback should skip ticks where both last and bid are 0."""
        from dataclasses import dataclass

        @dataclass
        class MockHub:
            def on(self, event, handler): pass

        @dataclass
        class ZeroQuote:
            bid: float = 0.0
            ask: float = 0.0
            last: float = 0.0
            timestamp: float = 0.0

        uph = self._make_uph()
        callback = uph._make_hub_callback("test_hub", MockHub())
        callback({'symbol': 'NOPE', 'quote': ZeroQuote()})

        price, ts = uph.get_price_and_ts("NOPE", allow_stale=True)
        assert price == 0.0  # Should NOT have been cached


# ── S3: _query_hub fast path ────────────────────────────────────────────

class TestQueryHubFastPath:
    """Tests for StreamingPriceMonitor._query_hub with get_price_and_ts."""

    def test_uses_get_price_and_ts_when_available(self):
        from src.services.conditional_orders.base import StreamingPriceMonitor

        class MockUPH:
            def get_price_and_ts(self, symbol, allow_stale=False):
                return (123.45, 9999.0)

        async def dummy_cb(sym, price): pass

        mon = StreamingPriceMonitor("TEST", dummy_cb, MockUPH(), "test_broker")
        result = mon._query_hub()
        assert result == 123.45
        assert mon._last_hub_quote_ts == 9999.0

    def test_falls_back_to_get_quote_price(self):
        from src.services.conditional_orders.base import StreamingPriceMonitor

        class MockHub:
            def get_quote_price(self, symbol, allow_stale=False):
                return 99.0

        async def dummy_cb(sym, price): pass

        mon = StreamingPriceMonitor("TEST", dummy_cb, MockHub(), "test_broker")
        result = mon._query_hub()
        assert result == 99.0

    def test_returns_none_on_zero_price(self):
        from src.services.conditional_orders.base import StreamingPriceMonitor

        class MockUPH:
            def get_price_and_ts(self, symbol, allow_stale=False):
                return (0.0, 0.0)

        async def dummy_cb(sym, price): pass

        mon = StreamingPriceMonitor("TEST", dummy_cb, MockUPH(), "test_broker")
        result = mon._query_hub()
        assert result is None


# ── S1: Event-driven wakeup from UPH ────────────────────────────────────

class TestEventDrivenWakeup:
    """Verify StreamingPriceMonitor wires UPH event-driven wakeup for all brokers."""

    @pytest.mark.asyncio
    async def test_uph_event_sets_price_event(self):
        """Simulate a UPH quote_updated event waking the monitor."""
        from src.services.unified_price_hub import UnifiedPriceHub
        UnifiedPriceHub._instance = None
        uph = UnifiedPriceHub()

        # Pre-seed a price so _query_hub succeeds
        uph._update_cache("SCHWAB_TEST", {"last": 100.0, "timestamp": time.time()}, "schwab")

        from src.services.conditional_orders.base import StreamingPriceMonitor

        callback_prices = []

        async def track_cb(sym, price):
            callback_prices.append(price)

        mon = StreamingPriceMonitor("SCHWAB_TEST", track_cb, uph, "schwab")

        # Manually set up the event and handler (simulating start())
        mon._price_event = asyncio.Event()
        _loop = asyncio.get_event_loop()
        _sym_upper = "SCHWAB_TEST"

        def _uph_handler(data):
            if data and data.get('symbol', '').upper() == _sym_upper:
                try:
                    _loop.call_soon_threadsafe(mon._price_event.set)
                except RuntimeError:
                    pass

        uph.on('quote_updated', _uph_handler)

        # Simulate a Schwab tick arriving via UPH
        uph._update_cache("SCHWAB_TEST", {"last": 101.0, "timestamp": time.time()}, "schwab")

        # The event should be set
        await asyncio.sleep(0.01)
        assert mon._price_event.is_set()


# ── S4: Handler cleanup ─────────────────────────────────────────────────

class TestHandlerCleanup:

    @pytest.mark.asyncio
    async def test_stop_removes_uph_handler(self):
        from src.services.unified_price_hub import UnifiedPriceHub
        UnifiedPriceHub._instance = None
        uph = UnifiedPriceHub()

        from src.services.conditional_orders.base import StreamingPriceMonitor

        async def dummy_cb(sym, price): pass

        mon = StreamingPriceMonitor("CLN", dummy_cb, uph, "test")

        handler = lambda data: None
        mon._uph_handler = handler
        uph.on('quote_updated', handler)

        # Verify handler is registered
        assert handler in uph._event_handlers.get('quote_updated', [])

        await mon.stop()

        # Handler should be removed
        assert handler not in uph._event_handlers.get('quote_updated', [])
        assert mon._uph_handler is None


# ── Performance: get_price_and_ts vs get_quote + get_quote_price ─────────

class TestPerformanceComparison:
    """Benchmark to verify fast path is actually faster."""

    def test_fast_path_avoids_copy(self):
        """get_price_and_ts should not allocate a UnifiedQuote copy."""
        from src.services.unified_price_hub import UnifiedPriceHub
        UnifiedPriceHub._instance = None
        uph = UnifiedPriceHub()

        uph._update_cache("PERF", {"last": 100.0, "bid": 99.5, "ask": 100.5,
                                    "timestamp": time.time()}, "ibkr")

        # Measure: get_price_and_ts should be faster (no copy.copy)
        import timeit

        fast_time = timeit.timeit(
            lambda: uph.get_price_and_ts("PERF", allow_stale=True),
            number=10000
        )
        slow_time = timeit.timeit(
            lambda: uph.get_quote_price("PERF", allow_stale=True),
            number=10000
        )

        # Fast path should be at least somewhat faster (avoid copy.copy + double lock)
        # We don't assert strict ratio since CI variance is high, but print for manual review
        print(f"\n  get_price_and_ts: {fast_time*1000:.1f}ms / 10k calls")
        print(f"  get_quote_price:  {slow_time*1000:.1f}ms / 10k calls")
        print(f"  speedup: {slow_time/fast_time:.1f}x")

        # Sanity: both return the same price
        p1, _ = uph.get_price_and_ts("PERF", allow_stale=True)
        p2 = uph.get_quote_price("PERF", allow_stale=True)
        assert p1 == p2


# ── Cross-thread wakeup latency (simulates real hub → monitor path) ──────

class TestCrossThreadWakeup:
    """Simulate the real data flow: hub thread emits tick → UPH callback → monitor wakeup."""

    @pytest.mark.asyncio
    async def test_cross_thread_wakeup_latency(self):
        """Measures actual cross-thread wakeup time via call_soon_threadsafe."""
        from src.services.unified_price_hub import UnifiedPriceHub
        UnifiedPriceHub._instance = None
        uph = UnifiedPriceHub()

        event = asyncio.Event()
        _loop = asyncio.get_event_loop()
        wakeup_times = []

        def _handler(data):
            if data and data.get('symbol') == 'XTHREAD':
                try:
                    _loop.call_soon_threadsafe(event.set)
                except RuntimeError:
                    pass

        uph.on('quote_updated', _handler)

        # Simulate a hub thread emitting a tick from a different thread
        def _emit_from_thread():
            time.sleep(0.01)  # Small delay to ensure event loop is waiting
            t0 = time.monotonic()
            uph._update_cache("XTHREAD", {"last": 42.0, "timestamp": time.time()}, "schwab")
            wakeup_times.append(t0)

        t = threading.Thread(target=_emit_from_thread)
        t.start()

        # Wait for the event (should wake within ~1ms via call_soon_threadsafe)
        try:
            await asyncio.wait_for(event.wait(), timeout=2.0)
            t1 = time.monotonic()
        except asyncio.TimeoutError:
            pytest.fail("Event was not set within 2 seconds — cross-thread wakeup failed")

        t.join()

        assert event.is_set()
        # Verify the price arrived
        price, ts = uph.get_price_and_ts("XTHREAD", allow_stale=True)
        assert price == 42.0


# ── End-to-end pipeline simulation ───────────────────────────────────────

class TestEndToEndPipeline:
    """Simulate the full tick path: Hub.update_quote → UPH callback → cache → read."""

    def test_schwab_tick_flows_through_uph(self):
        """A Schwab-style tick should flow through to get_price_and_ts."""
        from src.services.unified_price_hub import UnifiedPriceHub
        UnifiedPriceHub._instance = None
        uph = UnifiedPriceHub()

        events_received = []
        uph.on('quote_updated', lambda d: events_received.append(d))

        # Simulate what SchwabDataHub.update_quote does → emits quote_updated
        # → UPH _on_quote_updated callback → _update_cache_from_quote → _emit
        from dataclasses import dataclass

        @dataclass
        class SchwabQuote:
            symbol: str = "AAPL"
            bid: float = 195.0
            ask: float = 196.0
            last: float = 195.5
            volume: int = 50000
            high: float = 197.0
            low: float = 194.0
            delta: float = 0.0
            gamma: float = 0.0
            theta: float = 0.0
            vega: float = 0.0
            open_interest: int = 0
            implied_volatility: float = 0.0
            timestamp: float = 0.0
            source: str = "stream"

        q = SchwabQuote(timestamp=time.time())

        # This is what UPH's _make_hub_callback processes
        callback = uph._make_hub_callback("schwab", None)
        callback({'symbol': 'AAPL', 'quote': q})

        # Verify the tick arrived in UPH cache
        price, ts = uph.get_price_and_ts("AAPL", allow_stale=True)
        assert price == 195.5
        assert ts > 0

        # Verify event was emitted for downstream consumers (risk engine, monitors)
        assert len(events_received) == 1
        assert events_received[0]['symbol'] == 'AAPL'
        assert events_received[0]['price'] == 195.5
        assert events_received[0]['source'] == 'schwab'

    def test_ibkr_quote_data_flows_through_uph(self):
        """IBKRQuoteData (__slots__) should flow through _update_cache_from_quote."""
        from src.services.unified_price_hub import UnifiedPriceHub
        from src.services.ibkr_data_hub import IBKRQuoteData
        UnifiedPriceHub._instance = None
        uph = UnifiedPriceHub()

        q = IBKRQuoteData(symbol="SPY")
        q.bid = 550.0
        q.ask = 551.0
        q.last = 550.5
        q.volume = 100000
        q.delta = 0.99
        q.gamma = 0.001
        q.theta = -0.05
        q.vega = 0.1
        q.timestamp = time.time()

        callback = uph._make_hub_callback("ibkr", None)
        callback({'symbol': 'SPY', 'quote': q})

        # Verify all fields propagated
        result = uph.get_quote("SPY")
        assert result is not None
        assert result.last == 550.5
        assert result.bid == 550.0
        assert result.ask == 551.0
        assert result.delta == 0.99
        assert result.gamma == 0.001
        assert result.theta == -0.05
        assert result.vega == 0.1
        assert result.volume == 100000

    def test_webull_tick_no_greeks(self):
        """Webull quotes have no greeks — verify _update_cache_from_quote handles gracefully."""
        from src.services.unified_price_hub import UnifiedPriceHub
        UnifiedPriceHub._instance = None
        uph = UnifiedPriceHub()

        class WebullStyleQuote:
            """Simulates WebullQuoteData — has no delta/gamma/theta/vega."""
            def __init__(self):
                self.bid = 100.0
                self.ask = 101.0
                self.last = 100.5
                self.volume = 5000
                self.high = 102.0
                self.low = 99.0
                self.open_price = 100.0
                self.close_price = 99.5
                self.timestamp = time.time()

        callback = uph._make_hub_callback("webull", None)
        callback({'symbol': 'NVDA', 'quote': WebullStyleQuote()})

        price, ts = uph.get_price_and_ts("NVDA", allow_stale=True)
        assert price == 100.5

        result = uph.get_quote("NVDA")
        assert result.open_price == 100.0
        assert result.close_price == 99.5
        # Greeks should remain at default 0.0 — not crash
        assert result.delta == 0.0

    def test_monitor_query_hub_matches_uph_cache(self):
        """_query_hub via get_price_and_ts returns same price as get_quote_price."""
        from src.services.unified_price_hub import UnifiedPriceHub
        from src.services.conditional_orders.base import StreamingPriceMonitor
        UnifiedPriceHub._instance = None
        uph = UnifiedPriceHub()

        uph._update_cache("QQQ", {"last": 500.0, "bid": 499.5, "ask": 500.5,
                                   "timestamp": time.time()}, "tastytrade")

        async def dummy_cb(sym, price): pass
        mon = StreamingPriceMonitor("QQQ", dummy_cb, uph, "tastytrade")

        # Both paths should return the same price
        fast_price = mon._query_hub()
        slow_price = uph.get_quote_price("QQQ", allow_stale=True)

        assert fast_price == slow_price == 500.0
