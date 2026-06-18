import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.signal_format_registry import get_signal_format_registry
registry = get_signal_format_registry()

tests = [
    # P0 broken formats
    ("temple_zz_ticker_price_now", "$EZGO 3.28 now"),
    ("temple_zz_ticker_price_now", "ERNA 5.50 now"),
    ("viking_entry_role_first", "<@&1330929339134640179> $Anpa 6.5$"),
    ("viking_entry_role_first", "<@&1330929339134640179> $Dxf .4450"),
    ("viking_entry_role_first", "<@&1330915546513805463> $Anpa 6.50 short term swing"),
    ("jake_option_exp", "$BBAI $8c 16JAN2026 @lim0.59"),
    ("jake_order_executed", "Sold -1 Single MSTR 1/2/2026 150 PUT @1.38"),
    ("temple_zz_ciss_reversal", "ASBP 0.32 for the reversal"),
    ("temple_zz_ciss_reversal", "$CISS for the reversal here at 2.55. SL -10%"),
    ("temple_zz_structured_entry_no_targets", "$ACXP <@&1330915546513805463> ✅ 1.75-1.80"),
    ("temple_zz_inline_role_entry", "CTNT <@&1330929339134640179> <@&1330915546513805463> 2.18"),
    ("temple_zz_will_enter_if_breaks", "$MIMI will enter at a $4.00 clear break for 4.25-4.70-5.20"),
    ("temple_zz_will_enter_if_breaks", "$DRTS good news - will enter a strong 10.19 break for 11.10-11.97"),
    ("temple_zz_will_enter_if_breaks", "SMTK will enter only if it breaks 0.55 for 0.60...0.65....0.68 retest"),
    ("temple_zz_i_will_take_break", "$DARE I will buy if it breaks 2.80 for 3.00+"),
    ("temple_zz_i_will_take_break", "DRCT I will take 3.67 break"),
    # P1 priority conflicts
    ("abtrades_trim", "$MSFT 450c 40%"),
    ("abtrades_trim", "$IREN 50c 100%"),
    ("abtrades_exit", "ALL OUT: **$FROG**\n6/18 70c 100%"),
    ("abtrades_trim", "$MRVL 110c 200%\nI'm all OUT."),
    ("slem_lotto", "$MDB 422.5c 2.20 1/9 @Lottos"),
    ("slem_lotto", "$IREN 60c 1.45 1/30 @Leaps"),
    ("slem_option", "$TSLA 445p 4.18 1/9 exp"),
    # Verify no regressions
    ("temple_zz_options_b", "SPY 580c 1.80"),
    ("temple_options_standard", "TSLA 350c @.85"),
    ("abtrades_entry", "**$MCHP 6/18 100c 3.65**"),
    ("temple_rf_options", "buy QQQ 530+C at 2.50 for 5/16"),
]

passed = 0
failed = 0
for expected_fmt, text in tests:
    result = registry.parse(text)
    actual_fmt = result.get('_format_name', 'NO MATCH') if result else 'NO MATCH'
    ok = actual_fmt == expected_fmt
    status = "OK" if ok else "FAIL"
    if not ok:
        failed += 1
        print(f"  {status}: expected={expected_fmt}, got={actual_fmt}")
        print(f"         text: {text[:80]}")
    else:
        passed += 1

print(f"\nResults: {passed} passed, {failed} failed out of {len(tests)}")
