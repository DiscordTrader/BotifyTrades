"""
Temple of Boom Parser — QA Test Suite
======================================
Covers all 12 registered formats across stock and options channels.

Test Categories:
  1. Pattern matching (regex correctness)
  2. Parser output (dict field validation)
  3. Registry integration (end-to-end through SignalFormatRegistry)
  4. False positive rejection
  5. Edge cases and boundary conditions
  6. Pipeline source attribution
"""
import pytest
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.signals.temple_parser import (
    parse_temple_zz_emoji_entry, parse_temple_zz_emoji_exit,
    parse_temple_zz_emoji_target, parse_temple_zz_stock_entry,
    parse_temple_zz_stock_exit, parse_temple_zz_trim,
    parse_temple_rf_options, parse_temple_options_standard,
    parse_temple_zz_options_a, parse_temple_zz_options_b,
    parse_temple_ts_options, parse_temple_options_exit,
    TEMPLE_ZZ_EMOJI_ENTRY, TEMPLE_ZZ_EMOJI_EXIT, TEMPLE_ZZ_EMOJI_TARGET,
    TEMPLE_ZZ_STOCK_ENTRY, TEMPLE_ZZ_STOCK_EXIT, TEMPLE_ZZ_TRIM_PCT,
    TEMPLE_RF_OPTIONS, TEMPLE_OPTIONS_STANDARD,
    TEMPLE_ZZ_OPTIONS_A, TEMPLE_ZZ_OPTIONS_B,
    TEMPLE_TS_OPTIONS, TEMPLE_OPTIONS_EXIT,
)


# =========================================================================
# 1. STOCK CHANNEL — Pattern Matching
# =========================================================================

@pytest.mark.quick
@pytest.mark.signal
class TestTempleStockPatterns:
    """Test stock channel regex patterns compile and match correctly."""

    @pytest.mark.parametrize("text,expected_sym,expected_price", [
        ("▶ PLTR $22.50", "PLTR", "22.50"),
        ("▶ SOFI $8.30", "SOFI", "8.30"),
        ("▶ In MARA $18.50", "MARA", "18.50"),
        ("▶ RIVN $15", "RIVN", "15"),
    ])
    def test_emoji_entry_pattern(self, text, expected_sym, expected_price):
        m = TEMPLE_ZZ_EMOJI_ENTRY.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == expected_sym
        assert m.group(2) == expected_price

    @pytest.mark.parametrize("text,expected_sym", [
        ("⛔ PLTR", "PLTR"),
        ("⛔ Out SOFI", "SOFI"),
        ("⛔ SL out RIVN", "RIVN"),
        ("⛔ Cut MARA", "MARA"),
    ])
    def test_emoji_exit_pattern(self, text, expected_sym):
        m = TEMPLE_ZZ_EMOJI_EXIT.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == expected_sym

    @pytest.mark.parametrize("text,expected_sym", [
        ("\U0001f3af PLTR", "PLTR"),
        ("\U0001f3af SOFI", "SOFI"),
    ])
    def test_emoji_target_pattern(self, text, expected_sym):
        m = TEMPLE_ZZ_EMOJI_TARGET.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == expected_sym

    @pytest.mark.parametrize("text,expected_sym,expected_price", [
        ("In PLTR $22.50", "PLTR", "22.50"),
        ("In SOFI avg $8.30", "SOFI", "8.30"),
        ("In MARA avg $18.50", "MARA", "18.50"),
        ("in RIVN $15.00", "RIVN", "15.00"),
    ])
    def test_stock_entry_pattern(self, text, expected_sym, expected_price):
        m = TEMPLE_ZZ_STOCK_ENTRY.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == expected_sym
        assert m.group(2) == expected_price

    @pytest.mark.parametrize("text,expected_sym", [
        ("Out PLTR", "PLTR"),
        ("SL out SOFI", "SOFI"),
        ("Cut RIVN", "RIVN"),
    ])
    def test_stock_exit_pattern(self, text, expected_sym):
        m = TEMPLE_ZZ_STOCK_EXIT.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == expected_sym

    @pytest.mark.parametrize("text,expected_sym,expected_pct", [
        ("Trim 35%", None, "35"),
        ("Trim PLTR 50%", "PLTR", "50"),
        ("Trim SOFI 25.5%", "SOFI", "25.5"),
        ("trim 100%", None, "100"),
    ])
    def test_trim_pct_pattern(self, text, expected_sym, expected_pct):
        m = TEMPLE_ZZ_TRIM_PCT.search(text)
        assert m is not None, f"Should match: {text}"
        if expected_sym:
            assert m.group(1).upper() == expected_sym
        else:
            assert m.group(1) is None
        assert m.group(2) == expected_pct


# =========================================================================
# 2. OPTIONS CHANNEL — Pattern Matching
# =========================================================================

@pytest.mark.quick
@pytest.mark.signal
class TestTempleOptionsPatterns:
    """Test options channel regex patterns."""

    @pytest.mark.parametrize("text,sym,strike,opt,price,expiry", [
        ("buy QQQ 530+C at 2.50 for 5/16", "QQQ", "530", "C", "2.50", "5/16"),
        ("buy SPY 580+P at 1.20 for 5/9", "SPY", "580", "P", "1.20", "5/9"),
        ("Buy AAPL 230+C at 3.00 for 5/16/25", "AAPL", "230", "C", "3.00", "5/16/25"),
    ])
    def test_rf_options_pattern(self, text, sym, strike, opt, price, expiry):
        m = TEMPLE_RF_OPTIONS.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == sym
        assert m.group(2) == strike
        assert m.group(3).upper() == opt
        assert m.group(4) == price
        assert m.group(5) == expiry

    @pytest.mark.parametrize("text,sym,strike,opt,price", [
        ("TSLA 350c @.85", "TSLA", "350", "c", ".85"),
        ("NVDA 135c @1.20", "NVDA", "135", "c", "1.20"),
        ("SPY 580p @2.10", "SPY", "580", "p", "2.10"),
        ("AAPL 230c @$3.50", "AAPL", "230", "c", "3.50"),
    ])
    def test_standard_options_pattern(self, text, sym, strike, opt, price):
        m = TEMPLE_OPTIONS_STANDARD.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == sym.upper()
        assert m.group(2) == strike
        assert m.group(3) == opt
        assert m.group(4) == price

    @pytest.mark.parametrize("text,sym,opt,strike,expiry_raw", [
        ("SPY P 653 daily", "SPY", "P", "653", "daily"),
        ("QQQ C 480 5/16", "QQQ", "C", "480", "5/16"),
        ("AAPL C 230 weekly", "AAPL", "C", "230", "weekly"),
    ])
    def test_zz_options_a_pattern(self, text, sym, opt, strike, expiry_raw):
        m = TEMPLE_ZZ_OPTIONS_A.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == sym
        assert m.group(2).upper() == opt
        assert m.group(3) == strike
        assert m.group(4).lower() == expiry_raw.lower()

    @pytest.mark.parametrize("text,sym,strike,opt,price", [
        ("SPY 580c 1.80", "SPY", "580", "c", "1.80"),
        ("NVDA 135c 2.50", "NVDA", "135", "c", "2.50"),
        ("QQQ 480p 0.95", "QQQ", "480", "p", "0.95"),
    ])
    def test_zz_options_b_pattern(self, text, sym, strike, opt, price):
        m = TEMPLE_ZZ_OPTIONS_B.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == sym
        assert m.group(2) == strike
        assert m.group(3) == opt
        assert m.group(4) == price

    @pytest.mark.parametrize("text,sym,strike,opt_word,cost", [
        ("QQQ 579 Puts-.75 C SL .65", "QQQ", "579", "Puts", ".75"),
        ("AAPL 230 Calls-1.50 C SL 1.20", "AAPL", "230", "Calls", "1.50"),
        ("SPY 580 Put-.90 C", "SPY", "580", "Put", ".90"),
    ])
    def test_ts_options_pattern(self, text, sym, strike, opt_word, cost):
        m = TEMPLE_TS_OPTIONS.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == sym
        assert m.group(2) == strike
        assert m.group(3) == opt_word
        assert m.group(4) == cost

    @pytest.mark.parametrize("text,sym,strike,opt", [
        ("out TSLA 350c", "TSLA", "350", "c"),
        ("sold SPY 580c 2.50", "SPY", "580", "c"),
        ("SL out QQQ 480p", "QQQ", "480", "p"),
        ("cut NVDA 135c", "NVDA", "135", "c"),
    ])
    def test_options_exit_pattern(self, text, sym, strike, opt):
        m = TEMPLE_OPTIONS_EXIT.search(text)
        assert m is not None, f"Should match: {text}"
        assert m.group(1).upper() == sym
        assert m.group(2) == strike
        assert m.group(3) == opt


# =========================================================================
# 3. PARSER OUTPUT — Field Validation
# =========================================================================

@pytest.mark.quick
@pytest.mark.signal
class TestTempleParserOutput:
    """Test parser functions return correctly structured dicts."""

    REQUIRED_FIELDS = {'asset', 'action', 'qty', 'qty_specified', 'symbol',
                       'strike', 'opt_type', 'expiry', 'price', 'is_market_order', 'confidence'}

    def _parse(self, pattern, parser, text):
        m = pattern.search(text)
        assert m is not None, f"Pattern should match: {text}"
        result = parser(m, text)
        assert result is not None, f"Parser should return dict for: {text}"
        for field in self.REQUIRED_FIELDS:
            assert field in result, f"Missing field '{field}' in result for: {text}"
        return result

    def test_emoji_entry_output(self):
        r = self._parse(TEMPLE_ZZ_EMOJI_ENTRY, parse_temple_zz_emoji_entry,
                        "▶ PLTR $22.50 SL $21.00 PT $25.00")
        assert r['asset'] == 'stock'
        assert r['action'] == 'BTO'
        assert r['symbol'] == 'PLTR'
        assert r['price'] == 22.50
        assert r['stop_loss'] == 21.00
        assert r['take_profit'] == 25.00
        assert r['is_market_order'] is False
        assert r['_temple_entry'] is True

    def test_emoji_exit_output(self):
        r = self._parse(TEMPLE_ZZ_EMOJI_EXIT, parse_temple_zz_emoji_exit, "⛔ PLTR")
        assert r['asset'] == 'stock'
        assert r['action'] == 'STC'
        assert r['symbol'] == 'PLTR'
        assert r['is_full_exit'] is True
        assert r['is_market_order'] is True
        assert r['_temple_exit'] is True

    def test_emoji_target_output(self):
        r = self._parse(TEMPLE_ZZ_EMOJI_TARGET, parse_temple_zz_emoji_target, "\U0001f3af SOFI")
        assert r['asset'] == 'stock'
        assert r['action'] == 'STC'
        assert r['is_trim'] is True
        assert r['is_full_exit'] is False
        assert r['confidence'] == 0.9

    def test_stock_entry_output(self):
        r = self._parse(TEMPLE_ZZ_STOCK_ENTRY, parse_temple_zz_stock_entry, "In MARA $18.50")
        assert r['symbol'] == 'MARA'
        assert r['price'] == 18.50
        assert r['action'] == 'BTO'

    def test_stock_exit_output(self):
        r = self._parse(TEMPLE_ZZ_STOCK_EXIT, parse_temple_zz_stock_exit, "Cut RIVN")
        assert r['symbol'] == 'RIVN'
        assert r['action'] == 'STC'
        assert r['is_full_exit'] is True

    def test_trim_with_symbol_output(self):
        r = self._parse(TEMPLE_ZZ_TRIM_PCT, parse_temple_zz_trim, "Trim PLTR 35%")
        assert r['symbol'] == 'PLTR'
        assert r['action'] == 'STC'
        assert r['is_trim'] is True
        assert r['trim_percentage'] == 35.0
        assert r['confidence'] == 0.9

    def test_trim_without_symbol_output(self):
        r = self._parse(TEMPLE_ZZ_TRIM_PCT, parse_temple_zz_trim, "Trim 50%")
        assert r['symbol'] is None
        assert r['trim_percentage'] == 50.0
        assert r['confidence'] == 0.7

    def test_rf_options_output(self):
        r = self._parse(TEMPLE_RF_OPTIONS, parse_temple_rf_options,
                        "buy QQQ 530+C at 2.50 for 5/16")
        assert r['asset'] == 'option'
        assert r['action'] == 'BTO'
        assert r['symbol'] == 'QQQ'
        assert r['strike'] == 530.0
        assert r['opt_type'] == 'C'
        assert r['price'] == 2.50
        assert r['expiry'] == '5/16'
        assert r['_temple_rf_entry'] is True

    def test_standard_options_dot_price(self):
        r = self._parse(TEMPLE_OPTIONS_STANDARD, parse_temple_options_standard,
                        "TSLA 350c @.85")
        assert r['price'] == 0.85
        assert r['strike'] == 350.0
        assert r['opt_type'] == 'C'

    def test_standard_options_dollar_price(self):
        r = self._parse(TEMPLE_OPTIONS_STANDARD, parse_temple_options_standard,
                        "NVDA 135c @1.20")
        assert r['price'] == 1.20

    def test_zz_options_a_daily(self):
        r = self._parse(TEMPLE_ZZ_OPTIONS_A, parse_temple_zz_options_a,
                        "SPY P 653 daily")
        assert r['symbol'] == 'SPY'
        assert r['opt_type'] == 'P'
        assert r['strike'] == 653.0
        assert r['expiry'] is not None  # "daily" defaults to today (0DTE)
        assert r['_expiry_hint'] == 'daily'
        assert r['_expiry_defaulted'] is True

    def test_zz_options_a_with_date(self):
        r = self._parse(TEMPLE_ZZ_OPTIONS_A, parse_temple_zz_options_a,
                        "QQQ C 480 5/16")
        assert r['expiry'] == '5/16'

    def test_zz_options_b_output(self):
        r = self._parse(TEMPLE_ZZ_OPTIONS_B, parse_temple_zz_options_b,
                        "SPY 580c 1.80")
        assert r['symbol'] == 'SPY'
        assert r['strike'] == 580.0
        assert r['opt_type'] == 'C'
        assert r['price'] == 1.80

    def test_ts_options_puts(self):
        r = self._parse(TEMPLE_TS_OPTIONS, parse_temple_ts_options,
                        "QQQ 579 Puts-.75 C SL .65")
        assert r['symbol'] == 'QQQ'
        assert r['strike'] == 579.0
        assert r['opt_type'] == 'P'  # "Puts" → P
        assert r['price'] == 0.75
        assert r['stop_loss'] == 0.65

    def test_ts_options_calls(self):
        r = self._parse(TEMPLE_TS_OPTIONS, parse_temple_ts_options,
                        "AAPL 230 Calls-1.50 C SL 1.20")
        assert r['opt_type'] == 'C'  # "Calls" → C
        assert r['price'] == 1.50
        assert r['stop_loss'] == 1.20

    def test_options_exit_output(self):
        r = self._parse(TEMPLE_OPTIONS_EXIT, parse_temple_options_exit,
                        "sold SPY 580c 2.50")
        assert r['action'] == 'STC'
        assert r['symbol'] == 'SPY'
        assert r['strike'] == 580.0
        assert r['opt_type'] == 'C'
        assert r['is_full_exit'] is True


# =========================================================================
# 4. FALSE POSITIVE REJECTION
# =========================================================================

@pytest.mark.quick
@pytest.mark.signal
class TestTempleFalsePositives:
    """Ensure Temple patterns don't match non-Temple signals or chat."""

    def test_standard_bto_not_matched_by_zz_options_b(self):
        """Critical: BTO SPY 580c 5/16 must NOT match temple_zz_options_b."""
        text = "BTO SPY 580c 5/16 @ 1.80"
        m = TEMPLE_ZZ_OPTIONS_B.search(text)
        if m:
            result = parse_temple_zz_options_b(m, text)
            assert result is None, "Standard BTO format must be rejected by parser"

    def test_standard_stc_not_matched_by_zz_options_b(self):
        text = "STC SPY 580c 5/16 @ 2.50"
        m = TEMPLE_ZZ_OPTIONS_B.search(text)
        if m:
            result = parse_temple_zz_options_b(m, text)
            assert result is None, "Standard STC format must be rejected by parser"

    def test_common_words_rejected_by_stock_exit(self):
        """'Cut LOSSES' should not trigger stock exit for 'LOSSES'."""
        for word in ['HERE', 'THIS', 'LOSSES', 'BACK', 'EARLY', 'STILL']:
            text = f"Cut {word}"
            m = TEMPLE_ZZ_STOCK_EXIT.search(text)
            if m:
                result = parse_temple_zz_stock_exit(m, text)
                assert result is None, f"Common word '{word}' should be rejected"

    def test_common_words_rejected_by_stock_entry(self):
        """'In THE $5' should not trigger stock entry for 'THE'."""
        text = "In THE $5.00"
        m = TEMPLE_ZZ_STOCK_ENTRY.search(text)
        if m:
            result = parse_temple_zz_stock_entry(m, text)
            assert result is None, "Common word 'THE' should be rejected"

    @pytest.mark.parametrize("text", [
        "nice trade everyone",
        "good morning",
        "what do you think about SPY?",
        "SPY looking strong today",
        "market is crazy right now",
        "up 50%",
        "down 2.5",
        "580 seems like resistance",
        "In my opinion SPY is going up",
        "Looking at 580 calls",
        "I think C is going up",
    ])
    def test_chat_messages_no_match(self, text):
        """Generic chat should not match any Temple patterns."""
        patterns = [
            TEMPLE_ZZ_EMOJI_ENTRY, TEMPLE_ZZ_EMOJI_EXIT, TEMPLE_ZZ_EMOJI_TARGET,
            TEMPLE_RF_OPTIONS, TEMPLE_TS_OPTIONS, TEMPLE_OPTIONS_EXIT,
        ]
        for pat in patterns:
            m = pat.search(text)
            assert m is None, f"Chat '{text}' should not match {pat.pattern[:40]}"

    def test_expiry_date_not_captured_as_price(self):
        """'5/16' in 'SPY 580c 5/16' must NOT be captured as price by zz_options_b."""
        text = "SPY 580c 5/16"
        m = TEMPLE_ZZ_OPTIONS_B.search(text)
        if m:
            assert m.group(4) != "5", "Expiry fragment '5' must not be captured as price"


# =========================================================================
# 5. EDGE CASES AND BOUNDARY CONDITIONS
# =========================================================================

@pytest.mark.quick
@pytest.mark.signal
class TestTempleEdgeCases:
    """Test boundary conditions and unusual inputs."""

    def test_emoji_entry_no_price_returns_none(self):
        """Entry without price should still capture symbol."""
        text = "▶ PLTR"
        m = TEMPLE_ZZ_EMOJI_ENTRY.search(text)
        assert m is None, "Emoji entry without price should not match"

    def test_sl_pt_extraction_from_entry(self):
        """SL and PT should be extracted from same line as entry."""
        text = "▶ MARA $18.50 SL $17.80 PT $20.00"
        m = TEMPLE_ZZ_EMOJI_ENTRY.search(text)
        r = parse_temple_zz_emoji_entry(m, text)
        assert r['stop_loss'] == 17.80
        assert r['take_profit'] == 20.00

    def test_entry_without_sl_pt(self):
        """Entry without SL/PT should not have those keys."""
        text = "▶ PLTR $22.50"
        m = TEMPLE_ZZ_EMOJI_ENTRY.search(text)
        r = parse_temple_zz_emoji_entry(m, text)
        assert 'stop_loss' not in r
        assert 'take_profit' not in r

    def test_ts_options_without_sl(self):
        """Toughshit format without SL should have stop_loss absent."""
        text = "QQQ 579 Puts-.75 C"
        m = TEMPLE_TS_OPTIONS.search(text)
        assert m is not None
        r = parse_temple_ts_options(m, text)
        assert 'stop_loss' not in r
        assert r['price'] == 0.75

    def test_rf_options_with_year_in_expiry(self):
        """RF format with year in expiry: 5/16/25."""
        text = "buy AAPL 230+C at 3.00 for 5/16/25"
        m = TEMPLE_RF_OPTIONS.search(text)
        assert m is not None
        r = parse_temple_rf_options(m, text)
        assert r['expiry'] == '5/16/25'

    def test_dollar_sign_optional_in_symbol(self):
        """$SYMBOL and SYMBOL should both work."""
        for text in ["In $PLTR $22.50", "In PLTR $22.50"]:
            m = TEMPLE_ZZ_STOCK_ENTRY.search(text)
            assert m is not None, f"Should match: {text}"
            assert m.group(1).upper() == 'PLTR'

    def test_case_insensitivity(self):
        """All patterns should be case-insensitive."""
        text_pairs = [
            ("in pltr $22.50", TEMPLE_ZZ_STOCK_ENTRY),
            ("out PLTR", TEMPLE_ZZ_STOCK_EXIT),
            ("trim pltr 50%", TEMPLE_ZZ_TRIM_PCT),
            ("BUY QQQ 530+C at 2.50 for 5/16", TEMPLE_RF_OPTIONS),
        ]
        for text, pattern in text_pairs:
            m = pattern.search(text)
            assert m is not None, f"Case-insensitive match failed: {text}"

    def test_options_standard_put(self):
        """Standard format with put option."""
        text = "SPY 580p @2.10"
        m = TEMPLE_OPTIONS_STANDARD.search(text)
        assert m is not None
        r = parse_temple_options_standard(m, text)
        assert r['opt_type'] == 'P'
        assert r['price'] == 2.10

    def test_trim_percentage_key_name(self):
        """Trim must use 'trim_percentage' (not 'trim_pct') for pipeline compatibility."""
        text = "Trim PLTR 35%"
        m = TEMPLE_ZZ_TRIM_PCT.search(text)
        r = parse_temple_zz_trim(m, text)
        assert 'trim_percentage' in r, "Must use 'trim_percentage' key for forwarding engine"
        assert 'trim_pct' not in r, "Must NOT use legacy 'trim_pct' key"


# =========================================================================
# 6. REGISTRY INTEGRATION
# =========================================================================

@pytest.mark.quick
@pytest.mark.signal
class TestTempleRegistryIntegration:
    """Test end-to-end flow through SignalFormatRegistry."""

    @pytest.fixture(autouse=True)
    def setup_registry(self):
        from src.services.signal_format_registry import get_signal_format_registry
        self.registry = get_signal_format_registry()

    @pytest.mark.parametrize("text,expected_format,expected_action,expected_sym", [
        ("▶ PLTR $22.50", "temple_zz_emoji_entry", "BTO", "PLTR"),
        ("⛔ PLTR", "temple_zz_emoji_exit", "STC", "PLTR"),
        ("\U0001f3af SOFI", "temple_zz_emoji_target", "STC", "SOFI"),
        ("Cut RIVN", "temple_zz_stock_exit", "STC", "RIVN"),
        ("Trim PLTR 35%", "temple_zz_trim_pct", "STC", "PLTR"),
        ("buy QQQ 530+C at 2.50 for 5/16", "temple_rf_options", "BTO", "QQQ"),
        ("TSLA 350c @.85", "temple_options_standard", "BTO", "TSLA"),
        ("SPY P 653 daily", "temple_zz_options_a", "BTO", "SPY"),
        ("SPY 580c 1.80", "temple_zz_options_b", "BTO", "SPY"),
        ("QQQ 579 Puts-.75 C SL .65", "temple_ts_options", "BTO", "QQQ"),
        ("sold SPY 580c 2.50", "temple_options_exit", "STC", "SPY"),
    ])
    def test_registry_matches(self, text, expected_format, expected_action, expected_sym):
        result = self.registry.parse(text)
        assert result is not None, f"Registry should match: {text}"
        assert result.get('_format_name') == expected_format, \
            f"Expected format '{expected_format}', got '{result.get('_format_name')}' for: {text}"
        assert result.get('action') == expected_action
        assert result.get('symbol') == expected_sym

    def test_registry_standard_bto_not_temple(self):
        """Standard BTO format should NOT match any Temple format."""
        result = self.registry.parse("BTO SPY 580c 5/16 @ 1.80")
        if result:
            assert 'temple' not in result.get('_format_name', ''), \
                "Standard BTO must not match Temple format"

    def test_registry_standard_stc_not_temple(self):
        """Standard STC format should NOT match any Temple format."""
        result = self.registry.parse("STC SPY 580c 5/16 @ 2.50")
        if result:
            assert 'temple' not in result.get('_format_name', ''), \
                "Standard STC must not match Temple format"

    def test_registry_options_price_accuracy(self):
        """Verify @.85 parses to 0.85, not 85.0."""
        result = self.registry.parse("TSLA 350c @.85")
        assert result is not None
        assert result['price'] == pytest.approx(0.85), f"Price should be 0.85, got {result['price']}"

    def test_registry_ts_sl_accuracy(self):
        """Verify SL .65 parses to 0.65, not 65.0."""
        result = self.registry.parse("QQQ 579 Puts-.75 C SL .65")
        assert result is not None
        assert result['price'] == pytest.approx(0.75)
        assert result.get('stop_loss') == pytest.approx(0.65)


# =========================================================================
# 7. PIPELINE SOURCE ATTRIBUTION
# =========================================================================

@pytest.mark.quick
@pytest.mark.signal
class TestTemplePipelineSource:
    """Test that Temple formats map to REGISTRY_TEMPLE in the pipeline."""

    def test_source_mapping(self):
        from src.services.signal_parsing_pipeline import SignalParsingPipeline, SignalSource
        pipeline = SignalParsingPipeline()

        temple_format_names = [
            'temple_zz_emoji_entry', 'temple_zz_emoji_exit', 'temple_zz_emoji_target',
            'temple_zz_stock_entry', 'temple_zz_stock_exit', 'temple_zz_trim_pct',
            'temple_rf_options', 'temple_ts_options', 'temple_zz_options_a',
            'temple_zz_options_b', 'temple_options_standard', 'temple_options_exit',
        ]

        for fmt_name in temple_format_names:
            source = pipeline._map_registry_source(fmt_name)
            assert source == SignalSource.REGISTRY_TEMPLE, \
                f"'{fmt_name}' should map to REGISTRY_TEMPLE, got {source}"

    def test_registry_temple_enum_exists(self):
        from src.services.signal_parsing_pipeline import SignalSource
        assert hasattr(SignalSource, 'REGISTRY_TEMPLE')
        assert SignalSource.REGISTRY_TEMPLE.value == 'temple'


class TestTempleBrokerExecution:
    """Validate that all Temple options parsers produce fields required for broker execution.

    Broker place_option_order() requires: symbol, strike, expiry, option_type, action, price.
    _prefetch_option_id() bails if any of [symbol, strike, option_type, expiry] is falsy.
    """

    REQUIRED_FIELDS = {'symbol', 'strike', 'expiry', 'opt_type', 'action'}

    OPTIONS_SIGNALS = [
        ("buy QQQ 530+C at 2.50 for 5/16", TEMPLE_RF_OPTIONS, parse_temple_rf_options, "rf_options"),
        ("TSLA 350c @.85", TEMPLE_OPTIONS_STANDARD, parse_temple_options_standard, "options_standard"),
        ("NVDA 135c @1.20", TEMPLE_OPTIONS_STANDARD, parse_temple_options_standard, "options_standard_dollar"),
        ("SPY P 653 daily", TEMPLE_ZZ_OPTIONS_A, parse_temple_zz_options_a, "zz_options_a_daily"),
        ("QQQ C 480 5/16", TEMPLE_ZZ_OPTIONS_A, parse_temple_zz_options_a, "zz_options_a_date"),
        ("SPY 580c 1.80", TEMPLE_ZZ_OPTIONS_B, parse_temple_zz_options_b, "zz_options_b"),
        ("QQQ 579 Puts-.75 C SL .65", TEMPLE_TS_OPTIONS, parse_temple_ts_options, "ts_options"),
    ]

    EXIT_SIGNALS = [
        ("out TSLA 350c", TEMPLE_OPTIONS_EXIT, parse_temple_options_exit, "options_exit_out"),
        ("sold SPY 580c 2.50", TEMPLE_OPTIONS_EXIT, parse_temple_options_exit, "options_exit_sold"),
        ("SL out QQQ 480p", TEMPLE_OPTIONS_EXIT, parse_temple_options_exit, "options_exit_sl"),
    ]

    @pytest.mark.parametrize("text,pattern,parser,label", OPTIONS_SIGNALS,
                             ids=[s[3] for s in OPTIONS_SIGNALS])
    def test_entry_has_all_required_fields(self, text, pattern, parser, label):
        m = pattern.search(text)
        assert m is not None, f"Pattern did not match: {text}"
        result = parser(m, text)
        assert result is not None, f"Parser returned None: {text}"
        missing = self.REQUIRED_FIELDS - set(result.keys())
        assert not missing, f"Missing required fields {missing} for '{label}'"

    @pytest.mark.parametrize("text,pattern,parser,label", OPTIONS_SIGNALS,
                             ids=[s[3] for s in OPTIONS_SIGNALS])
    def test_entry_fields_are_truthy(self, text, pattern, parser, label):
        m = pattern.search(text)
        result = parser(m, text)
        for field in self.REQUIRED_FIELDS:
            assert result[field], f"Field '{field}' is falsy ({result[field]!r}) for '{label}'"

    MARKET_ORDER_FORMATS = {'zz_options_a_daily', 'zz_options_a_date'}

    @pytest.mark.parametrize("text,pattern,parser,label", OPTIONS_SIGNALS,
                             ids=[s[3] for s in OPTIONS_SIGNALS])
    def test_entry_has_price_or_market_order(self, text, pattern, parser, label):
        m = pattern.search(text)
        result = parser(m, text)
        assert 'price' in result, f"Missing 'price' field for '{label}'"
        if label in self.MARKET_ORDER_FORMATS:
            assert result['price'] is None, f"Market-order format should have price=None for '{label}'"
            assert result.get('is_market_order') is True, f"Market-order format missing is_market_order flag for '{label}'"
        else:
            assert isinstance(result['price'], (int, float)), f"Price not numeric for '{label}'"
            assert result['price'] > 0, f"Price not positive for '{label}'"

    @pytest.mark.parametrize("text,pattern,parser,label", OPTIONS_SIGNALS,
                             ids=[s[3] for s in OPTIONS_SIGNALS])
    def test_entry_action_is_bto(self, text, pattern, parser, label):
        m = pattern.search(text)
        result = parser(m, text)
        assert result['action'] == 'BTO', f"Entry action should be BTO, got {result['action']!r}"

    @pytest.mark.parametrize("text,pattern,parser,label", OPTIONS_SIGNALS,
                             ids=[s[3] for s in OPTIONS_SIGNALS])
    def test_entry_opt_type_normalized(self, text, pattern, parser, label):
        m = pattern.search(text)
        result = parser(m, text)
        assert result['opt_type'] in ('C', 'P'), \
            f"opt_type should be 'C' or 'P', got {result['opt_type']!r}"

    @pytest.mark.parametrize("text,pattern,parser,label", OPTIONS_SIGNALS,
                             ids=[s[3] for s in OPTIONS_SIGNALS])
    def test_entry_strike_is_numeric(self, text, pattern, parser, label):
        m = pattern.search(text)
        result = parser(m, text)
        assert isinstance(result['strike'], (int, float)), \
            f"Strike should be numeric, got {type(result['strike']).__name__}"

    @pytest.mark.parametrize("text,pattern,parser,label", OPTIONS_SIGNALS,
                             ids=[s[3] for s in OPTIONS_SIGNALS])
    def test_entry_expiry_defaulted_flag(self, text, pattern, parser, label):
        m = pattern.search(text)
        result = parser(m, text)
        if '_expiry_defaulted' in result and result['_expiry_defaulted']:
            assert result['expiry'] is not None, "Defaulted expiry should not be None"

    @pytest.mark.parametrize("text,pattern,parser,label", EXIT_SIGNALS,
                             ids=[s[3] for s in EXIT_SIGNALS])
    def test_exit_action_is_stc(self, text, pattern, parser, label):
        m = pattern.search(text)
        assert m is not None
        result = parser(m, text)
        assert result is not None
        assert result['action'] == 'STC', f"Exit action should be STC, got {result['action']!r}"

    @pytest.mark.parametrize("text,pattern,parser,label", EXIT_SIGNALS,
                             ids=[s[3] for s in EXIT_SIGNALS])
    def test_exit_has_symbol_and_opt_type(self, text, pattern, parser, label):
        m = pattern.search(text)
        result = parser(m, text)
        assert result.get('symbol'), f"Exit missing symbol for '{label}'"
        assert result.get('opt_type') in ('C', 'P'), \
            f"Exit missing/invalid opt_type for '{label}'"
