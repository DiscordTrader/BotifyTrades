"""
Tests for RISK-1 (bracket placeOrder not wrapped in to_thread)
and SYNC-1 (broker_sync uses ib.portfolio() with marketPrice).
"""
import ast
import os
import sys
import re

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ── RISK-1: No asyncio.to_thread wrapping placeOrder/cancelOrder ────────────

class TestRisk1NoToThreadPlaceOrder:
    """position_monitor must call ib.placeOrder directly, not via to_thread."""

    def _get_source(self):
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', 'risk', 'position_monitor.py')
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_no_to_thread_placeOrder(self):
        source = self._get_source()
        matches = re.findall(r'to_thread\(.*placeOrder', source)
        assert len(matches) == 0, (
            f"Found {len(matches)} asyncio.to_thread wrapping placeOrder — "
            f"ib_insync requires main event loop: {matches}"
        )

    def test_no_to_thread_cancelOrder(self):
        source = self._get_source()
        matches = re.findall(r'to_thread\(.*cancelOrder', source)
        assert len(matches) == 0, (
            f"Found {len(matches)} asyncio.to_thread wrapping cancelOrder — "
            f"ib_insync requires main event loop: {matches}"
        )

    def test_direct_placeOrder_calls_exist(self):
        """Verify placeOrder calls exist and are direct (not wrapped)."""
        source = self._get_source()
        # Should have direct placeOrder calls (without to_thread)
        direct_calls = re.findall(r'\.ib\.placeOrder\(', source)
        assert len(direct_calls) >= 4, (
            f"Expected at least 4 direct ib.placeOrder calls, found {len(direct_calls)}"
        )


# ── SYNC-1: broker_sync uses ib.portfolio() first with marketPrice ──────────

class TestSync1PortfolioFirst:
    """broker_sync must fetch ib.portfolio() first for marketPrice/P&L data."""

    def _get_source(self):
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'src', 'services', 'broker_sync_service.py')
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_portfolio_called_before_positions(self):
        """ib.portfolio() must be attempted before ib.positions()."""
        source = self._get_source()
        portfolio_idx = source.find('ib.portfolio')
        positions_idx = source.find('ib.positions')
        assert portfolio_idx != -1, "ib.portfolio() call not found"
        assert positions_idx != -1, "ib.positions() fallback not found"
        assert portfolio_idx < positions_idx, (
            "ib.portfolio() must be called before ib.positions() "
            f"(portfolio at {portfolio_idx}, positions at {positions_idx})"
        )

    def test_market_price_extraction_stock(self):
        """Stock positions must extract marketPrice from portfolio items."""
        source = self._get_source()
        # Find IBKR block
        ibkr_block_start = source.find("elif broker_name.startswith('IBKR')")
        assert ibkr_block_start != -1
        # Find next broker block to bound our search
        ibkr_block = source[ibkr_block_start:ibkr_block_start + 3000]
        assert "'current_price': _mkt_price" in ibkr_block, (
            "Stock position dict must use _mkt_price from marketPrice attribute"
        )
        assert "'unrealized_pnl': _unrealized" in ibkr_block, (
            "Stock position dict must use _unrealized from unrealizedPNL attribute"
        )

    def test_market_price_extraction_option(self):
        """Option positions must extract marketPrice from portfolio items."""
        source = self._get_source()
        ibkr_block_start = source.find("elif broker_name.startswith('IBKR')")
        ibkr_block = source[ibkr_block_start:ibkr_block_start + 3000]
        # Should have marketPrice extraction for options too
        assert "getattr(pos, 'marketPrice'" in ibkr_block, (
            "Must extract marketPrice via getattr for IBKR positions"
        )

    def test_ib_sentinel_guard(self):
        """IB sentinel value (max float) must be filtered to 0."""
        source = self._get_source()
        ibkr_block_start = source.find("elif broker_name.startswith('IBKR')")
        ibkr_block = source[ibkr_block_start:ibkr_block_start + 3000]
        assert '1.7976931348623157e+308' in ibkr_block, (
            "Must guard against IB sentinel value 1.7976931348623157e+308"
        )

    def test_no_hardcoded_zero_pnl(self):
        """IBKR positions must NOT have hardcoded 'unrealized_pnl': 0."""
        source = self._get_source()
        ibkr_block_start = source.find("elif broker_name.startswith('IBKR')")
        ibkr_block = source[ibkr_block_start:ibkr_block_start + 3000]
        # Should NOT have literal 0 for unrealized_pnl
        assert "'unrealized_pnl': 0" not in ibkr_block, (
            "IBKR position dicts must use extracted unrealizedPNL, not hardcoded 0"
        )

    def test_no_hardcoded_zero_price(self):
        """IBKR positions must NOT have hardcoded 'current_price': 0."""
        source = self._get_source()
        ibkr_block_start = source.find("elif broker_name.startswith('IBKR')")
        ibkr_block = source[ibkr_block_start:ibkr_block_start + 3000]
        assert "'current_price': 0" not in ibkr_block, (
            "IBKR position dicts must use extracted marketPrice, not hardcoded 0"
        )
