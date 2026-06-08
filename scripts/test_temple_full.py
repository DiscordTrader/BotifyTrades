"""Comprehensive Temple of Boom format validation — stocks vs options alignment."""
import sys, os
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from src.services.signal_format_registry import SignalFormatRegistry

registry = SignalFormatRegistry()

# Each test: (message, expected_action, expected_asset, expected_symbol, description)
# expected_action: 'BTO'/'STC'/'SL_UPDATE'/'UPDATE_TARGETS'/None (None = should NOT match)
# expected_asset: 'stock'/'option'/None

tests = [
    # =========================================================================
    # STOCK ENTRIES — Range format (traderzz1m main format)
    # =========================================================================
    ("NXXT 0.75-0.88", "BTO", "stock", "NXXT", "Range entry — basic"),
    ("HCWB 0.99-1.76.... all fibs hit", "BTO", "stock", "HCWB", "Range entry — trailing text"),
    ("CODX 2.05-2.43<a:4743_pink_flame:1154098186831536248>", "BTO", "stock", "CODX", "Range entry — flame emoji"),
    ("PHGE 0.55-0.67<a:4743_pink_flame:1154098186831536248>", "BTO", "stock", "PHGE", "Range entry — penny stock"),
    ("MTVA 2.70-2.96<a:4743_pink_flame:1154098186831536248>", "BTO", "stock", "MTVA", "Range entry — mid-price"),
    ("VIDA 2.86-3.64<a:4743_pink_flame:1154098186831536248>", "BTO", "stock", "VIDA", "Range entry — flame no space"),
    ("WNW 4.00-6.54. Over 7.25 we have 8.39 <a:4743_pink_flame:1154098186831536248>", "BTO", "stock", "WNW", "Range + extended targets"),
    ("CRE 2.80-3.91", "BTO", "stock", "CRE", "Range entry — 3-char symbol"),
    ("SDOT 0.36-0.50", "BTO", "stock", "SDOT", "Range entry — 4-char symbol"),
    ("$SLXN 0.62-0.72", "BTO", "stock", "SLXN", "Range entry — with $ prefix"),

    # =========================================================================
    # STOCK ENTRIES — Emoji format
    # =========================================================================
    ("▶ PLTR $22.50", "BTO", "stock", "PLTR", "Emoji entry — ▶ SYMBOL $PRICE"),
    ("▶ In SOFI $8.30 SL $7.90 PT $9.50", "BTO", "stock", "SOFI", "Emoji entry — with SL/PT"),

    # =========================================================================
    # STOCK ENTRIES — Natural language
    # =========================================================================
    ("In PLTR $22.50", "BTO", "stock", "PLTR", "NL entry — In SYMBOL $PRICE"),
    ("In SOFI avg $8.30", "BTO", "stock", "SOFI", "NL entry — In SYMBOL avg $PRICE"),

    # =========================================================================
    # STOCK ENTRIES — Breakout / Conditional
    # =========================================================================
    ("PMAX break 2.82 for 3.12", "BTO", "stock", "PMAX", "Breakout — break PRICE for TARGET"),
    ("EZGO 3.11 break takes it to 3.41", "BTO", "stock", "EZGO", "Breakout — PRICE break takes to TARGET"),
    ("2.50 must break for 2.71 OCG", "BTO", "stock", "OCG", "Breakout reverse — PRICE break for TARGET SYMBOL"),

    # =========================================================================
    # STOCK ENTRIES — Immediate
    # =========================================================================
    ("$EZGO 3.28 now", "BTO", "stock", "EZGO", "Immediate entry — SYMBOL PRICE now"),

    # =========================================================================
    # STOCK ENTRIES — Structured emoji (✅/❌/\U0001f3af)
    # =========================================================================
    ("$AREB <@&1330929339134640179> \n✅ 0.30\n❌ 0.28\n\U0001f3af 0.33...0.37...0.40", "BTO", "stock", "AREB", "Structured — with role + all fields"),
    ("$BIYA\n✅ 1.55\n❌ 1.45\n\U0001f3af 1.64...1.74...1.88...2.00", "BTO", "stock", "BIYA", "Structured — no role"),
    ("$OCG\n✅ 2.25\n\U0001f3af 5% 10% 15%", "BTO", "stock", "OCG", "Structured — % targets, no SL"),
    ("$MTVA re-entry\n✅ 2.60-2.65\n❌ 2.50\n\U0001f3af 2.75...3.00...3.12..3.30..3.60", "BTO", "stock", "MTVA", "Structured — re-entry text (Bug 2 fix)"),
    ("Overnight trade idea \U0001f319 \n$MTVA re-entry\n✅ 2.60-2.65\n❌ 2.50\n\U0001f3af 2.75...3.00...3.12..3.30..3.60", "BTO", "stock", "MTVA", "Structured — multiline prefix (Bug 2 fix)"),
    ("YOOV\n✅ 1.90 clear break\n❌ 1.75\n\U0001f3af 5%-10% -15%+", "BTO", "stock", "YOOV", "Structured — 'clear break' in entry"),
    ("$AIIO\n✅ 5.00 break\n❌ 4.5\n\U0001f3af 5% 10% 15%+", "BTO", "stock", "AIIO", "Structured — 'break' in entry"),
    ("$WNW <@&1330929339134640179>\n✅ $4.00-4.20\n❌ 3.75\n\U0001f3af 4.46...4.78...5.20", "BTO", "stock", "WNW", "Structured — $ in entry, role"),
    ("$FUSE <@&1330915546513805463>\n✅ around 1.70\n❌ 1.50\n\U0001f3af 2.00-3.50", "BTO", "stock", "FUSE", "Structured — 'around' in entry"),

    # =========================================================================
    # STOCK ENTRIES — Inline with role
    # =========================================================================
    ("OCG  in at 2.12 <@&1330929339134640179>", "BTO", "stock", "OCG", "Inline role — in at PRICE @Momentum"),
    ("MNTS 4.8 <@&1330929339134640179>", "BTO", "stock", "MNTS", "Inline role — PRICE @Momentum"),
    ("$EDHL <@&1330929339134640179> 2.67", "BTO", "stock", "EDHL", "Inline role — @Momentum PRICE"),

    # =========================================================================
    # STOCK EXITS
    # =========================================================================
    ("⛔ PLTR", "STC", "stock", "PLTR", "Emoji exit — ⛔ SYMBOL"),
    ("⛔ Out SOFI", "STC", "stock", "SOFI", "Emoji exit — ⛔ Out SYMBOL"),
    ("⛔ SL out RIVN", "STC", "stock", "RIVN", "Emoji exit — ⛔ SL out"),
    ("Out PLTR", "STC", "stock", "PLTR", "NL exit — Out SYMBOL"),
    ("SL out SOFI", "STC", "stock", "SOFI", "NL exit — SL out SYMBOL"),
    ("Cut RIVN", "STC", "stock", "RIVN", "NL exit — Cut SYMBOL"),
    ("Trim 35%", "STC", "stock", None, "Trim — percentage only (no symbol)"),
    ("Trim PLTR 50%", "STC", "stock", "PLTR", "Trim — with symbol"),
    ("\U0001f3af PLTR", "STC", "stock", "PLTR", "Target hit emoji — trim"),

    # =========================================================================
    # STOCK SL UPDATES
    # =========================================================================
    ("5.50 should be your new ERNA SL", "SL_UPDATE", "stock", "ERNA", "SL update — should be your new SL"),
    ("Move your SL up to 5.00 if in", "SL_UPDATE", "stock", None, "SL update — move your SL (no symbol)"),
    ("You can move your mental stop loss for ERNA to 5.30", "SL_UPDATE", "stock", "ERNA", "SL update — mental stop loss for SYMBOL"),

    # =========================================================================
    # OPTIONS ENTRIES — RF format
    # =========================================================================
    ("buy QQQ 530+C at 2.50 for 5/16", "BTO", "option", "QQQ", "RF options — buy TICKER STRIKE+C at PRICE for EXPIRY"),
    ("buy SPY 580+P at 1.20 for 5/9", "BTO", "option", "SPY", "RF options — put variant"),

    # =========================================================================
    # OPTIONS ENTRIES — Standard format
    # =========================================================================
    ("TSLA 350c @.85", "BTO", "option", "TSLA", "Standard options — STRIKEc @.PRICE"),
    ("SPY 580 C @1.80", "BTO", "option", "SPY", "Standard options — STRIKE C @PRICE"),
    ("NVDA 135c @1.20", "BTO", "option", "NVDA", "Standard options — STRIKEc @PRICE"),

    # =========================================================================
    # OPTIONS ENTRIES — traderzz1m format
    # =========================================================================
    ("SPY P 653 daily", "BTO", "option", "SPY", "ZZ options A — TICKER C/P STRIKE daily"),
    ("QQQ C 480 5/16", "BTO", "option", "QQQ", "ZZ options A — TICKER C/P STRIKE expiry"),
    ("SPY 580c 1.80", "BTO", "option", "SPY", "ZZ options B — TICKER STRIKEc PRICE"),
    ("NVDA 135c 2.50", "BTO", "option", "NVDA", "ZZ options B — STRIKEc PRICE"),

    # =========================================================================
    # OPTIONS ENTRIES — Toughshit format
    # =========================================================================
    ("QQQ 579 Puts-.75 C SL .65", "BTO", "option", "QQQ", "Toughshit — Puts cost format"),
    ("SPY 580 Calls-1.20 C", "BTO", "option", "SPY", "Toughshit — Calls cost format"),

    # =========================================================================
    # OPTIONS EXITS
    # =========================================================================
    ("out TSLA 350c", "STC", "option", "TSLA", "Options exit — out TICKER STRIKEc"),
    ("sold SPY 580c 2.50", "STC", "option", "SPY", "Options exit — sold TICKER STRIKEc PRICE"),
    ("SL out QQQ 480p", "STC", "option", "QQQ", "Options exit — SL out TICKER STRIKEp"),

    # =========================================================================
    # SHOULD NOT MATCH — Commentary / Info messages
    # =========================================================================
    ("SLXN 0.78 tapped", None, None, None, "Commentary — 'tapped' (no range)"),
    ("VIDA in small on that 9ema bounce", None, None, None, "Commentary — no price"),
    ("NXXT you are green on this idea", None, None, None, "Commentary — 'you are green'"),
    ("AMST day 3.. I will enter if it get a clear 2.00 break", None, None, None, "Commentary — future conditional"),
    ("MTVA all PTs hit 2.07-2.73<a:4743_pink_flame:1154098186831536248>", None, None, None, "Commentary — 'all PTs hit' prefix"),

    # =========================================================================
    # FALSE POSITIVE GUARDS — should NOT match wrong ticker
    # =========================================================================
    ("If you missed my 2.07 alert on MTVA. Consider \n✅ 2.70\n❌ 2.50\n\U0001f3af 5% 10% 15%", None, None, None, "False positive guard — 'If' as ticker (Bug 1 fix)"),

    # =========================================================================
    # CROSS-CONTAMINATION GUARDS — stock should NOT parse as option
    # =========================================================================
    ("PHGE 0.55-0.67", "BTO", "stock", "PHGE", "Stock range must NOT be option"),
    ("CAPS 0.35-0.43", "BTO", "stock", "CAPS", "Stock range must NOT be option"),

    # =========================================================================
    # STANDALONE TARGETS
    # =========================================================================
    ("\U0001f3af 2.41...2.71", "UPDATE_TARGETS", "stock", None, "Standalone targets — no ticker"),
    ("\U0001f3af 0.33...0.37...0.40", "UPDATE_TARGETS", "stock", None, "Standalone targets — 3 levels"),
]

# =========================================================================
# RUN ALL TESTS
# =========================================================================
passed = 0
failed = 0
failures = []

for i, (msg, exp_action, exp_asset, exp_symbol, desc) in enumerate(tests, 1):
    result = registry.parse(msg)

    ok = True
    issues = []

    if exp_action is None:
        # Should NOT match at all
        if result is not None:
            ok = False
            sym = result.get('symbol')
            act = result.get('action')
            fmt = result.get('_format_name')
            issues.append(f"Expected NO MATCH, got {act} {sym} via '{fmt}'")
    else:
        if result is None:
            ok = False
            issues.append(f"Expected {exp_action} {exp_symbol}, got NO MATCH")
        else:
            got_action = result.get('action')
            got_asset = result.get('asset')
            got_symbol = result.get('symbol')

            if got_action != exp_action:
                ok = False
                issues.append(f"Action: expected {exp_action}, got {got_action}")
            if exp_asset and got_asset != exp_asset:
                ok = False
                issues.append(f"Asset: expected {exp_asset}, got {got_asset}")
            if exp_symbol and got_symbol != exp_symbol:
                ok = False
                issues.append(f"Symbol: expected {exp_symbol}, got {got_symbol}")

    if ok:
        passed += 1
    else:
        failed += 1
        failures.append((i, desc, issues, msg[:80]))

# =========================================================================
# REPORT
# =========================================================================
print(f"\n{'='*90}")
print(f"TEMPLE OF BOOM FORMAT VALIDATION — {passed + failed} tests")
print(f"{'='*90}")

if failures:
    print(f"\n❌ FAILURES ({failed}):\n")
    for num, desc, issues, msg_preview in failures:
        print(f"  Test {num}: {desc}")
        print(f"    Message: {msg_preview}")
        for issue in issues:
            print(f"    ❌ {issue}")
        print()

print(f"\n  ✅ Passed: {passed}")
print(f"  ❌ Failed: {failed}")
print(f"  Total:  {passed + failed}")
print(f"\n{'='*90}")

if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
    sys.exit(0)
