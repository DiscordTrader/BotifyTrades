"""Tests for AbTrades signal parser."""

import re
import pytest
from src.signals.abtrades_parser import (
    ABTRADES_ENTRY_RE,
    ABTRADES_TRIM_RE,
    ABTRADES_EXIT_RE,
    parse_abtrades_entry,
    parse_abtrades_trim,
    parse_abtrades_exit,
    _normalize_expiry,
    _find_all_entries,
)


# ── Entry pattern tests ─────────────────────────────────────────────

class TestEntryPattern:
    def test_basic_entry(self):
        m = ABTRADES_ENTRY_RE.search("**$MCHP 6/18 100c 3.65**")
        assert m
        assert m.group(1) == "MCHP"
        assert m.group(2) == "6/18"
        assert m.group(3) == "100"
        assert m.group(4) == "c"
        assert m.group(5) == "3.65"

    def test_entry_with_quantity(self):
        m = ABTRADES_ENTRY_RE.search("**$OKLO 6/18 70c 1.85x10**")
        assert m
        assert m.group(1) == "OKLO"
        assert m.group(5) == "1.85"
        assert m.group(6) == "10"

    def test_full_year_expiry(self):
        m = ABTRADES_ENTRY_RE.search("**$MTCH 1/15/2027 40c 3.2**")
        assert m
        assert m.group(2) == "1/15/2027"

    def test_decimal_strike(self):
        m = ABTRADES_ENTRY_RE.search("**$BAC 6/18 52.5c 1.06**")
        assert m
        assert m.group(3) == "52.5"

    def test_leading_dot_price(self):
        m = ABTRADES_ENTRY_RE.search("**$BAC 7/17 55c .93**")
        assert m
        assert m.group(5) == ".93"

    def test_parenthetical_note(self):
        m = ABTRADES_ENTRY_RE.search("**$LOW 5/22 225c 1.1 (this is more of a lotto)**")
        assert m
        assert m.group(1) == "LOW"
        assert m.group(5) == "1.1"

    def test_no_match_non_bold(self):
        m = ABTRADES_ENTRY_RE.search("$MSFT 450c 40%")
        assert m is None

    def test_no_match_commentary(self):
        m = ABTRADES_ENTRY_RE.search("I really like this setup for next week")
        assert m is None


class TestEntryParser:
    def test_basic_parse(self):
        m = ABTRADES_ENTRY_RE.search("**$TSLA 6/18 420c 8.1**")
        result = parse_abtrades_entry(m, "**$TSLA 6/18 420c 8.1**")
        assert result["symbol"] == "TSLA"
        assert result["action"] == "BTO"
        assert result["asset"] == "option"
        assert result["strike"] == 420.0
        assert result["opt_type"] == "C"
        assert result["expiry"] == "06/18"
        assert result["price"] == 8.1
        assert result["_format_name"] == "abtrades_entry"

    def test_quantity_parsing(self):
        text = "**$OKLO 6/18 70c 1.85x10**"
        m = ABTRADES_ENTRY_RE.search(text)
        result = parse_abtrades_entry(m, text)
        assert result["qty"] == 10
        assert result["qty_specified"] is True

    def test_no_quantity(self):
        text = "**$SMCI 6/18 31c 2.18**"
        m = ABTRADES_ENTRY_RE.search(text)
        result = parse_abtrades_entry(m, text)
        assert "qty" not in result

    def test_sl_pt_extraction(self):
        text = """**$AMZN 6/5 270c 4.15**
PT: 269, 271, 274, 280
SL: 258"""
        m = ABTRADES_ENTRY_RE.search(text)
        result = parse_abtrades_entry(m, text)
        assert result["stop_loss"] == 258.0
        assert result["take_profit"] == [269.0, 271.0, 274.0, 280.0]

    def test_multi_entry(self):
        text = """**$BAC 6/18 52.5c 1.06**
**$BAC 7/17 55c .93**

Chart is in updates"""
        m = ABTRADES_ENTRY_RE.search(text)
        result = parse_abtrades_entry(m, text)
        assert result["symbol"] == "BAC"
        assert result["strike"] == 52.5
        extras = result.get("_abtrades_extra_entries", [])
        assert len(extras) == 1
        assert extras[0]["symbol"] == "BAC"
        assert extras[0]["strike"] == 55.0
        assert extras[0]["price"] == 0.93

    def test_full_year_expiry_normalized(self):
        text = "**$MTCH 1/15/2027 40c 3.2**"
        m = ABTRADES_ENTRY_RE.search(text)
        result = parse_abtrades_entry(m, text)
        assert result["expiry"] == "01/15/27"
        assert result["expiry_year"] == "2027"

    def test_single_digit_month(self):
        text = "**$QQQ 4/17 615c 3.25**"
        m = ABTRADES_ENTRY_RE.search(text)
        result = parse_abtrades_entry(m, text)
        assert result["expiry"] == "04/17"


# ── Trim pattern tests ──────────────────────────────────────────────

class TestTrimPattern:
    def test_basic_trim(self):
        m = ABTRADES_TRIM_RE.search("$MSFT 450c 40%")
        assert m
        assert m.group(1) == "MSFT"
        assert m.group(2) == "450"
        assert m.group(3) == "c"
        assert m.group(4) == "40"

    def test_decimal_strike_trim(self):
        m = ABTRADES_TRIM_RE.search("$AMZN 287.5c 50%")
        assert m
        assert m.group(2) == "287.5"

    def test_no_match_bold_entry(self):
        m = ABTRADES_TRIM_RE.search("**$MCHP 6/18 100c 3.65**")
        assert m is None

    def test_no_match_commentary(self):
        m = ABTRADES_TRIM_RE.search("Take some trims here")
        assert m is None


class TestTrimParser:
    def test_basic_trim_parse(self):
        text = "$MSFT 450c 40%\nStart getting under half size"
        m = ABTRADES_TRIM_RE.search(text)
        result = parse_abtrades_trim(m, text)
        assert result["action"] == "STC"
        assert result["symbol"] == "MSFT"
        assert result["strike"] == 450.0
        assert result["opt_type"] == "C"
        assert result["trim_percentage"] == 40.0
        assert result["is_trim"] is True
        assert result["is_full_exit"] is False
        assert result["price"] is None
        assert result["is_market_order"] is True
        assert result["_format_name"] == "abtrades_trim"

    def test_trim_with_all_out(self):
        text = "$MRVL 110c 200%\nI'm all OUT."
        m = ABTRADES_TRIM_RE.search(text)
        result = parse_abtrades_trim(m, text)
        assert result["is_full_exit"] is True
        assert result["is_trim"] is False


# ── Exit pattern tests ──────────────────────────────────────────────

class TestExitPattern:
    def _get_symbol(self, m):
        return (m.group(1) or m.group(2)).upper() if m else None

    def test_all_out_bold(self):
        m = ABTRADES_EXIT_RE.search("ALL OUT: **$FROG**")
        assert self._get_symbol(m) == "FROG"

    def test_all_out_no_dollar(self):
        m = ABTRADES_EXIT_RE.search("ALL OUT: **$OKLO**\n6/18 70c 325%")
        assert self._get_symbol(m) == "OKLO"

    def test_closing_remaining(self):
        m = ABTRADES_EXIT_RE.search("Closing the remaining 5 $FSLR 9/18 280c for 500%")
        assert self._get_symbol(m) == "FSLR"

    def test_im_all_out(self):
        m = ABTRADES_EXIT_RE.search("Im all out of $NVDA remaining")
        assert self._get_symbol(m) == "NVDA"

    def test_reversed_all_out_same_line(self):
        m = ABTRADES_EXIT_RE.search("$GLW 150c all OUT for 550%")
        assert self._get_symbol(m) == "GLW"

    def test_reversed_all_out_colon(self):
        m = ABTRADES_EXIT_RE.search("$RGTI 20c: All out for 150%")
        assert self._get_symbol(m) == "RGTI"

    def test_reversed_all_out_multiline(self):
        m = ABTRADES_EXIT_RE.search("$MRVL 110c 200%\n**10 ITM**\nI'm all OUT.")
        assert self._get_symbol(m) == "MRVL"

    def test_closing_remaining_newline(self):
        m = ABTRADES_EXIT_RE.search("**Closing the remaining**\n$QQQ 615c 200%")
        assert self._get_symbol(m) == "QQQ"

    def test_closing_last_batches(self):
        m = ABTRADES_EXIT_RE.search("I'm also closing the last two batches of runners on $OKLO")
        assert self._get_symbol(m) == "OKLO"


class TestExitParser:
    def test_all_out_with_details(self):
        text = "ALL OUT: **$IREN**\n5/29 50c 400%\n6/18 60c 255%"
        m = ABTRADES_EXIT_RE.search(text)
        result = parse_abtrades_exit(m, text)
        assert result["action"] == "STC"
        assert result["symbol"] == "IREN"
        assert result["expiry"] == "05/29"
        assert result["strike"] == 50.0
        assert result["opt_type"] == "C"
        assert result["is_full_exit"] is True
        assert result["_format_name"] == "abtrades_exit"

    def test_closing_remaining_parse(self):
        text = "Closing the remaining 5 $FSLR 9/18 280c for 500%"
        m = ABTRADES_EXIT_RE.search(text)
        result = parse_abtrades_exit(m, text)
        assert result["symbol"] == "FSLR"
        assert result["strike"] == 280.0
        assert result["expiry"] == "09/18"


# ── Expiry normalization ────────────────────────────────────────────

class TestNormalizeExpiry:
    def test_mm_dd(self):
        exp, yr = _normalize_expiry("6/18")
        assert exp == "06/18"
        assert yr is None

    def test_already_padded(self):
        exp, yr = _normalize_expiry("12/05")
        assert exp == "12/05"
        assert yr is None

    def test_full_year(self):
        exp, yr = _normalize_expiry("1/15/2027")
        assert exp == "01/15/27"
        assert yr == "2027"

    def test_short_year(self):
        exp, yr = _normalize_expiry("4/10/27")
        assert exp == "04/10/27"
        assert yr == "2027"


# ── False positive rejection ────────────────────────────────────────

class TestFalsePositives:
    @pytest.mark.parametrize("text", [
        "See yall at 460+",
        "Love yall!",
        "50 wins and 6 losses for the month of May!",
        "I just want to have the freedom to live my life",
        "Swing Trade <@&986834388044095498>",
        "Into the final hour I will be grabbing $SLV 80c 6/18",
        "Another one for the books!",
    ])
    def test_entry_no_false_positive(self, text):
        m = ABTRADES_ENTRY_RE.search(text)
        assert m is None, f"False positive on: {text}"

    @pytest.mark.parametrize("text", [
        "See yall at 460+",
        "**$MCHP 6/18 100c 3.65**",
        "Swing Trade",
    ])
    def test_trim_no_false_positive(self, text):
        m = ABTRADES_TRIM_RE.search(text)
        assert m is None, f"False positive on: {text}"


# ── Registry integration ────────────────────────────────────────────

class TestRegistryIntegration:
    def test_formats_registered(self):
        from src.services.signal_format_registry import get_signal_format_registry
        registry = get_signal_format_registry()
        format_names = [f['name'] for f in registry.list_formats()]
        assert "abtrades_entry" in format_names
        assert "abtrades_trim" in format_names
        assert "abtrades_exit" in format_names

    def test_entry_via_registry(self):
        from src.services.signal_format_registry import parse_all_with_registry
        results = parse_all_with_registry("**$TSLA 6/18 420c 8.1**\nSL: 348")
        ab_results = [r for r in results if r.get("_format_name") == "abtrades_entry"]
        assert len(ab_results) >= 1
        assert ab_results[0]["symbol"] == "TSLA"
        assert ab_results[0]["price"] == 8.1

    def test_entry_priority_correct(self):
        from src.services.signal_format_registry import get_signal_format_registry
        registry = get_signal_format_registry()
        fmt = next(f for f in registry.list_formats() if f['name'] == 'abtrades_entry')
        assert fmt['priority'] == 82
        assert fmt['enabled'] is True
