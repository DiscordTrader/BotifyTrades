"""Tests for src/core/expiry.py — centralized expiry normalizer."""

import sys
import os
from datetime import date, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core.expiry import (
    normalize_expiry_iso,
    expiry_to_yyyymmdd,
    expiry_to_date,
    expiry_to_mmdd,
    expiry_to_occ,
    expiry_year,
    is_expired,
    is_same_day,
)

TODAY = date.today()
THIS_YEAR = TODAY.year
NEXT_YEAR = THIS_YEAR + 1
TODAY_ISO = TODAY.strftime('%Y-%m-%d')


# ─── Core normalize_expiry_iso tests ────────────────────────────────────────

class TestMMDDSlash:
    """MM/DD and MM/DD/YY and MM/DD/YYYY formats."""

    def test_zero_padded_mmdd(self):
        # "06/09" — future or today should stay this year, past rolls
        result = normalize_expiry_iso("06/09")
        assert result.endswith("-06-09")
        y = int(result[:4])
        if date(THIS_YEAR, 6, 9) >= TODAY:
            assert y == THIS_YEAR
        else:
            assert y == NEXT_YEAR

    def test_single_digit_month(self):
        result = normalize_expiry_iso("6/12")
        assert result.endswith("-06-12")

    def test_mmdd_two_digit_year(self):
        assert normalize_expiry_iso("06/12/26") == "2026-06-12"

    def test_mmdd_four_digit_year(self):
        assert normalize_expiry_iso("06/12/2026") == "2026-06-12"


class TestSpecialKeywords:
    """daily, weekly, 0dte → today."""

    def test_daily(self):
        assert normalize_expiry_iso("daily") == TODAY_ISO

    def test_weekly(self):
        assert normalize_expiry_iso("weekly") == TODAY_ISO

    def test_0dte(self):
        assert normalize_expiry_iso("0dte") == TODAY_ISO

    def test_0_dte_with_space(self):
        assert normalize_expiry_iso("0 dte") == TODAY_ISO


class TestISOPassthrough:
    """Already-normalized formats."""

    def test_iso_passthrough(self):
        assert normalize_expiry_iso("2026-06-09") == "2026-06-09"

    def test_compact_yyyymmdd(self):
        assert normalize_expiry_iso("20260609") == "2026-06-09"


class TestMonthName:
    """Month name + day, with optional year."""

    def test_full_month_name(self):
        result = normalize_expiry_iso("June 10")
        assert result.endswith("-06-10")

    def test_abbreviated_month(self):
        result = normalize_expiry_iso("Jun 18")
        assert result.endswith("-06-18")

    def test_full_month_different(self):
        result = normalize_expiry_iso("July 17")
        assert result.endswith("-07-17")

    def test_month_name_with_year(self):
        assert normalize_expiry_iso("Jun 18 2026") == "2026-06-18"


class TestEuropeanDDMM:
    """DD.MM European format (ZZ style)."""

    def test_ddmm_dot(self):
        result = normalize_expiry_iso("17.07")
        assert result.endswith("-07-17")

    def test_ddmm_dot_september(self):
        result = normalize_expiry_iso("18.09")
        assert result.endswith("-09-18")

    def test_ddmm_with_exp_suffix(self):
        result = normalize_expiry_iso("17.07 exp")
        assert result.endswith("-07-17")


class TestEmptyAndNone:
    """Empty/None-like inputs → today."""

    def test_empty_string(self):
        assert normalize_expiry_iso("") == TODAY_ISO

    def test_whitespace_only(self):
        assert normalize_expiry_iso("   ") == TODAY_ISO


# ─── Output adapter tests ──────────────────────────────────────────────────

class TestOutputAdapters:

    def test_to_yyyymmdd(self):
        assert expiry_to_yyyymmdd("2026-06-09") == "20260609"

    def test_to_date(self):
        assert expiry_to_date("2026-06-09") == date(2026, 6, 9)

    def test_to_mmdd(self):
        assert expiry_to_mmdd("2026-06-09") == "06/09"

    def test_to_occ(self):
        assert expiry_to_occ("2026-06-09") == "260609"

    def test_expiry_year(self):
        assert expiry_year("2026-06-09") == "2026"

    def test_is_expired_past(self):
        assert is_expired("2020-01-01") is True

    def test_is_expired_future(self):
        assert is_expired("2030-01-01") is False

    def test_is_same_day_today(self):
        assert is_same_day(TODAY_ISO) is True

    def test_is_same_day_other(self):
        assert is_same_day("2020-01-01") is False


# ─── year_hint parameter tests ─────────────────────────────────────────────

class TestYearHint:

    def test_mmdd_with_year_hint(self):
        assert normalize_expiry_iso("06/09", year_hint="2027") == "2027-06-09"

    def test_ddmm_dot_with_year_hint(self):
        assert normalize_expiry_iso("17.07", year_hint="2027") == "2027-07-17"

    def test_month_name_with_year_hint(self):
        result = normalize_expiry_iso("Jun 18", year_hint="2027")
        assert result == "2027-06-18"


# ─── Edge cases ─────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_invalid_input_raises(self):
        with pytest.raises(ValueError):
            normalize_expiry_iso("not-a-date")

    def test_january_rollover_from_december(self):
        """If we're in December and get '01/15', it should roll to next year."""
        fake_today = date(2026, 12, 15)
        with patch('core.expiry.date') as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *a, **k: date(*a, **k)
            result = normalize_expiry_iso("01/15")
            assert result == "2027-01-15"

    def test_iso_passthrough_with_extra(self):
        """ISO date with trailing content should still parse."""
        result = normalize_expiry_iso("2026-06-09T00:00:00")
        assert result == "2026-06-09"
