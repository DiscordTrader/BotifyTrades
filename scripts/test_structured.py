"""Test ZZ structured entry detection for missed MTVA signals."""
import sys, os, re
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from src.services.signal_format_registry import SignalFormatRegistry

registry = SignalFormatRegistry()

messages = [
    # Bug 1: Was matching "IF" as ticker — should now be REJECTED
    ("If you missed my 2.07 alert on MTVA. Consider \n✅ 2.70\n❌ 2.50\n\U0001f3af 5% 10% 15%",
     "SHOULD NOT match (IF is reject word)"),
    # Bug 2: Overnight re-entry — should now MATCH $MTVA with re.MULTILINE
    ("Overnight trade idea \U0001f319 \n$MTVA re-entry\n✅ 2.60-2.65\n❌ 2.50\n\U0001f3af 2.75...3.00...3.12..3.30..3.60",
     "SHOULD match MTVA (re.MULTILINE fix)"),
    # Still works: standard examples
    ("$AREB <@&1330929339134640179> \n✅ 0.30\n❌ 0.28\n\U0001f3af 0.33...0.37...0.40",
     "SHOULD match AREB (existing)"),
    ("$OCG\n✅ 2.25\n\U0001f3af 5% 10% 15%",
     "SHOULD match OCG (existing)"),
    ("$MTVA\n✅ 2.70\n❌ 2.50\n\U0001f3af 5% 10% 15%",
     "SHOULD match MTVA (existing)"),
    # Re-entry variant without $
    ("MTVA re-entry\n✅ 2.60-2.65\n❌ 2.50\n\U0001f3af 2.75...3.00...3.12..3.30..3.60",
     "SHOULD match MTVA (re-entry without $)"),
]

print("=" * 90)
all_pass = True
for i, (msg, expected) in enumerate(messages):
    result = registry.parse(msg)
    matched = result is not None
    symbol = result.get('symbol') if result else None
    fmt = result.get('_format_name') if result else None

    if "SHOULD NOT match" in expected:
        passed = not matched or (matched and symbol in ('IF',))
        # Actually: should not match at all, or at least not match IF
        passed = not matched
    else:
        passed = matched and symbol not in ('IF',)

    status = "✅ PASS" if passed else "❌ FAIL"
    if not passed:
        all_pass = False
    print(f"\nTest {i+1}: {status}")
    print(f"  Expected: {expected}")
    print(f"  Got:      {'MATCHED' if matched else 'NO MATCH'} | symbol={symbol} | format={fmt}")
    if result:
        print(f"  Price={result.get('price')}, Targets={result.get('profit_targets')}, SL={result.get('stop_loss_value')}")

print(f"\n{'=' * 90}")
print(f"{'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")
sys.exit(0 if all_pass else 1)
