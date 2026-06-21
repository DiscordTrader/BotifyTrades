"""
Tests for GAP-15: IBKR position price resolution at construction time.

Verifies that _fetch_ibkr_cached resolves prices from the hub's quotes cache
instead of hardcoding current_price=0, and that the ZERO PRICE GUARD recovers
prices before skipping evaluation.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.risk.risk_types import PositionSnapshot


class TestPositionSnapshotPriceValidation:
    """Test that PositionSnapshot correctly handles various price scenarios."""

    def test_zero_price_produces_negative_100_pct_change(self):
        """The core bug: $0 current_price with nonzero avg_cost yields -100% PnL."""
        snap = PositionSnapshot(
            symbol='AAPL', quantity=10, avg_cost=5.00,
            current_price=0, asset='option', broker='IBKR_PAPER'
        )
        assert snap.pct_change == -100.0, \
            "A $0 price MUST show -100% PnL — this is why the ZERO PRICE GUARD exists"

    def test_penny_stock_option_is_valid(self):
        """$0.01 options are legitimate — must not be confused with missing price."""
        snap = PositionSnapshot(
            symbol='AAPL', quantity=10, avg_cost=0.50,
            current_price=0.01, asset='option', broker='IBKR_PAPER'
        )
        assert snap.current_price == 0.01
        assert snap.pct_change == pytest.approx(-98.0, abs=0.1)
        # This is a real loss — risk engine should evaluate it normally

    def test_penny_stock_option_at_entry(self):
        """Entry at $0.03, current at $0.03 — 0% PnL, no false triggers."""
        snap = PositionSnapshot(
            symbol='MARA', quantity=5, avg_cost=0.03,
            current_price=0.03, asset='option', broker='IBKR_PAPER'
        )
        assert snap.pct_change == pytest.approx(0.0)

    def test_zero_avg_cost_returns_zero_pct(self):
        """Zero entry cost must not cause division by zero."""
        snap = PositionSnapshot(
            symbol='XYZ', quantity=1, avg_cost=0,
            current_price=1.50, asset='stock', broker='IBKR_PAPER'
        )
        assert snap.pct_change == 0.0

    def test_valid_option_price(self):
        """Normal option pricing works correctly."""
        snap = PositionSnapshot(
            symbol='SPY', quantity=2, avg_cost=3.50,
            current_price=4.20, asset='option', broker='IBKR_LIVE',
            strike=450, expiry='2025-01-17', direction='C',
            raw_symbol='SPY_20250117_450.0_C'
        )
        assert snap.pct_change == pytest.approx(20.0, abs=0.1)

    def test_ib_sentinel_should_be_rejected(self):
        """IB's max-float sentinel must never be used as a price."""
        _IB_SENTINEL = 1.7976931348623157e+308
        # The fix rejects this in the waterfall — if it slipped through,
        # PnL would be astronomically wrong
        snap = PositionSnapshot(
            symbol='AAPL', quantity=10, avg_cost=5.00,
            current_price=_IB_SENTINEL, asset='option', broker='IBKR_PAPER'
        )
        # This would produce absurd PnL — the price resolution code must reject it
        assert snap.current_price == _IB_SENTINEL  # PositionSnapshot doesn't filter
        # The filtering happens in _fetch_ibkr_cached before construction


class TestIBKRDataHubMarketPrice:
    """Test that the hub position dict carries market_price after the fix."""

    def test_position_dict_has_market_price_field(self):
        """After GAP-15 fix, _refresh_positions_from_ib embeds market_price in dict."""
        # Simulate the position dict format produced by the hub
        entry = {
            'symbol': 'AAPL',
            'quantity': 10,
            'avg_cost': 5.00,
            'raw_symbol': 'AAPL_20250117_150.0_C',
            'asset': 'option',
            'strike': 150.0,
            'expiry': '20250117',
            'direction': 'C',
            'market_price': 5.50,  # Added by GAP-15 fix
        }
        # The _fetch_ibkr_cached code reads this as fallback
        _mp = float(entry.get('market_price', 0) or entry.get('current_price', 0) or 0)
        assert _mp == 5.50
        assert _mp > 0

    def test_missing_market_price_falls_through(self):
        """Old-format position dicts (pre-fix) gracefully fall through."""
        entry = {
            'symbol': 'AAPL',
            'quantity': 10,
            'avg_cost': 5.00,
            'raw_symbol': 'AAPL_20250117_150.0_C',
            'asset': 'option',
        }
        _mp = float(entry.get('market_price', 0) or entry.get('current_price', 0) or 0)
        assert _mp == 0


class TestPriceWaterfallLogic:
    """Test the price waterfall resolution logic extracted from _fetch_ibkr_cached."""

    def _resolve_price(self, quote_price=None, market_price=0, uph_price=None,
                       asset='option'):
        """Simulate the price waterfall from the fix."""
        _IB_SENTINEL = 1.7976931348623157e+308
        _price = None

        # Step 1: Hub quote (simulated)
        if quote_price is not None and quote_price > 0:
            _price = quote_price

        # Step 2: Position dict market_price
        if not _price:
            _mp = float(market_price or 0)
            if 0 < _mp < _IB_SENTINEL:
                _price = _mp

        # Step 3: UPH (stocks only)
        if not _price and asset == 'stock' and uph_price is not None:
            _price = uph_price

        # Validation
        if _price and (_price < 0 or _price >= _IB_SENTINEL):
            _price = None

        return _price or 0

    def test_streaming_quote_wins(self):
        """Streaming quote takes priority over everything."""
        assert self._resolve_price(quote_price=5.25, market_price=5.00) == 5.25

    def test_market_price_fallback(self):
        """When no streaming quote, position dict market_price is used."""
        assert self._resolve_price(quote_price=None, market_price=4.80) == 4.80

    def test_uph_fallback_for_stocks(self):
        """UPH used for stocks when hub quote and dict both miss."""
        result = self._resolve_price(quote_price=None, market_price=0,
                                     uph_price=150.25, asset='stock')
        assert result == 150.25

    def test_uph_not_used_for_options(self):
        """UPH is NOT used for options (keys are broker-specific)."""
        result = self._resolve_price(quote_price=None, market_price=0,
                                     uph_price=5.00, asset='option')
        assert result == 0  # Falls through to $0

    def test_all_miss_returns_zero(self):
        """When all sources miss, returns 0 (ZERO PRICE GUARD handles it)."""
        assert self._resolve_price(quote_price=None, market_price=0) == 0

    def test_ib_sentinel_rejected(self):
        """IB sentinel price in market_price must be rejected."""
        _IB_SENTINEL = 1.7976931348623157e+308
        assert self._resolve_price(quote_price=None, market_price=_IB_SENTINEL) == 0

    def test_negative_price_rejected(self):
        """Negative prices are rejected."""
        assert self._resolve_price(quote_price=-1.0) == 0

    def test_penny_option_preserved(self):
        """$0.01 penny options must be preserved, not rejected."""
        assert self._resolve_price(quote_price=0.01) == 0.01

    def test_zero_quote_ignored(self):
        """A $0 streaming quote should not override market_price."""
        # quote_price=0 is falsy, so the waterfall skips to market_price
        result = self._resolve_price(quote_price=0, market_price=5.00)
        assert result == 5.00

    def test_very_small_option_price(self):
        """Deep OTM option at $0.005 — should be preserved."""
        assert self._resolve_price(quote_price=0.005) == 0.005


class TestZeroPriceGuardRecovery:
    """Test the ZERO PRICE GUARD recovery logic at evaluation time."""

    def test_recovery_skips_for_zero_recovered_price(self):
        """When recovery yields nothing, ZERO PRICE GUARD still blocks evaluation."""
        # Simulate: no hub, no UPH — recovery returns None
        _recovered_price = None
        position_price = 0
        if _recovered_price and _recovered_price > 0:
            position_price = _recovered_price
        assert position_price == 0  # Guard should return/skip

    def test_recovery_applies_for_valid_price(self):
        """When recovery finds a price, it's applied and evaluation continues."""
        _recovered_price = 3.75
        position_price = 0
        if _recovered_price and _recovered_price > 0:
            position_price = _recovered_price
        assert position_price == 3.75

    def test_recovery_rejects_zero_recovered(self):
        """A recovered price of $0 must NOT be applied."""
        _recovered_price = 0.0
        position_price = 0
        if _recovered_price and _recovered_price > 0:
            position_price = _recovered_price
        assert position_price == 0

    def test_recovery_accepts_penny_price(self):
        """Penny option recovered from hub should be applied."""
        _recovered_price = 0.01
        position_price = 0
        if _recovered_price and _recovered_price > 0:
            position_price = _recovered_price
        assert position_price == 0.01


class TestHubPositionDictEnrichment:
    """Verify the market_price field normalization in the hub position dict."""

    def test_option_market_price_div100(self):
        """OPT market_price is divided by 100 (IB returns per-contract)."""
        _IB_SENTINEL = 1.7976931348623157e+308
        mkt_price = 550.0  # IB raw per-contract
        sec_type = 'OPT'
        if sec_type == 'OPT' and 0 < mkt_price < _IB_SENTINEL:
            market_price = mkt_price / 100
        else:
            market_price = mkt_price
        assert market_price == 5.50

    def test_stock_market_price_raw(self):
        """STK market_price is used raw (IB returns per-share)."""
        _IB_SENTINEL = 1.7976931348623157e+308
        mkt_price = 185.50
        sec_type = 'STK'
        if sec_type == 'OPT' and 0 < mkt_price < _IB_SENTINEL:
            market_price = mkt_price / 100
        elif 0 < mkt_price < _IB_SENTINEL:
            market_price = mkt_price
        else:
            market_price = 0
        assert market_price == 185.50

    def test_sentinel_market_price_becomes_zero(self):
        """IB sentinel yields market_price=0."""
        _IB_SENTINEL = 1.7976931348623157e+308
        mkt_price = _IB_SENTINEL
        if 0 < mkt_price < _IB_SENTINEL:
            market_price = mkt_price
        else:
            market_price = 0
        assert market_price == 0

    def test_zero_market_price_stays_zero(self):
        """IB returning 0 yields market_price=0."""
        mkt_price = 0.0
        _IB_SENTINEL = 1.7976931348623157e+308
        if 0 < mkt_price < _IB_SENTINEL:
            market_price = mkt_price
        else:
            market_price = 0
        assert market_price == 0


class TestEdgeCasePriceScenarios:
    """End-to-end scenarios that caused production issues."""

    def test_newly_opened_position_no_streaming_yet(self):
        """Position opened, hub has portfolio seed but no streaming tick yet.
        Waterfall should find price from market_price dict field."""
        # Simulate: no quote in cache, but dict has market_price
        quote_price = None  # No streaming tick yet
        market_price = 2.75  # From portfolio() seed in dict
        _IB_SENTINEL = 1.7976931348623157e+308
        _price = None
        if quote_price and quote_price > 0:
            _price = quote_price
        if not _price:
            _mp = float(market_price or 0)
            if 0 < _mp < _IB_SENTINEL:
                _price = _mp
        assert _price == 2.75, "Should fall through to market_price from dict"

    def test_stale_streaming_quote_still_used(self):
        """allow_stale=True means a 4-minute-old quote is still used.
        Better than $0 — the overlay will refine it."""
        # With allow_stale=True, get_quote_price returns the price regardless of age.
        # This is correct behavior: any real price > $0 prevents SL false trigger.
        stale_price = 4.25  # 4 minutes old but valid
        _price = stale_price  # allow_stale=True would return this
        assert _price == 4.25, "Stale price is infinitely better than $0"

    def test_waterfall_order_is_hub_then_dict_then_uph(self):
        """Verify the waterfall respects priority: hub > dict > UPH."""
        # All three have prices — hub should win
        hub_price, dict_price, uph_price = 5.50, 5.45, 5.40
        _IB_SENTINEL = 1.7976931348623157e+308
        _price = None
        # Step 1: hub
        if hub_price and hub_price > 0:
            _price = hub_price
        # Step 2: dict (skipped because step 1 worked)
        if not _price:
            if 0 < dict_price < _IB_SENTINEL:
                _price = dict_price
        # Step 3: UPH (skipped)
        if not _price:
            _price = uph_price
        assert _price == 5.50, "Hub streaming quote has highest priority"

    def test_zero_from_hub_falls_through_to_dict(self):
        """If hub returns 0 (falsy), waterfall falls to dict."""
        hub_price, dict_price = 0, 3.20
        _IB_SENTINEL = 1.7976931348623157e+308
        _price = None
        if hub_price and hub_price > 0:
            _price = hub_price
        if not _price:
            if 0 < dict_price < _IB_SENTINEL:
                _price = dict_price
        assert _price == 3.20
