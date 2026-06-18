"""Validate all registered signal formats — check regex + parser integrity."""
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.signal_format_registry import get_signal_format_registry

registry = get_signal_format_registry()
fmts = registry.list_formats()
print(f"Total registered formats: {len(fmts)}\n")

# Group by category
categories = {}
for f in fmts:
    name = f['name']
    if name.startswith('temple_'):
        cat = 'TEMPLE'
    elif name.startswith('phoenix_'):
        cat = 'PHOENIX'
    elif name.startswith('foxtrades_'):
        cat = 'FOXTRADES'
    elif name.startswith('bronze_'):
        cat = 'BRONZE'
    elif name.startswith('jacob_'):
        cat = 'JACOB'
    elif name.startswith('abtrades_'):
        cat = 'ABTRADES'
    elif name.startswith('viking_'):
        cat = 'VIKING'
    elif name.startswith('jake_'):
        cat = 'JAKE'
    elif name.startswith('rocky_'):
        cat = 'ROCKY'
    elif name.startswith('ashley_'):
        cat = 'ASHLEY'
    elif name.startswith('angela_'):
        cat = 'ANGELA'
    elif name.startswith('slem_'):
        cat = 'SLEM'
    elif name.startswith('stack_'):
        cat = 'STACK'
    elif name.startswith('infra_'):
        cat = 'INFRA'
    elif name.startswith('protrader_'):
        cat = 'PROTRADER'
    elif name.startswith('quick_swing_'):
        cat = 'QUICK_SWING'
    elif name.startswith('learned_'):
        cat = 'LEARNED'
    else:
        cat = 'OTHER'
    categories.setdefault(cat, []).append(f)

for cat in sorted(categories.keys()):
    items = categories[cat]
    print(f"=== {cat} ({len(items)} formats) ===")
    for f in items:
        print(f"  {f['priority']:3d} | {f['name']}")
    print()

# Test each format against its own examples
print("=" * 70)
print("EXAMPLE VALIDATION (each format tested against its examples)")
print("=" * 70)
pass_count = 0
fail_count = 0
no_example = 0

for f in fmts:
    name = f['name']
    examples = f.get('examples', [])
    if not examples:
        no_example += 1
        continue
    for ex in examples:
        if not ex.strip():
            continue
        result = registry.parse(ex)
        if result and result.get('_format_name') == name:
            pass_count += 1
        else:
            fail_count += 1
            matched = result.get('_format_name', 'NO MATCH') if result else 'NO MATCH'
            print(f"  FAIL: {name}")
            print(f"    Example: {ex[:80]}")
            print(f"    Matched: {matched}")

print(f"\nResults: {pass_count} passed, {fail_count} failed, {no_example} formats without examples")

# Check for options formats that produce expiry
print("\n" + "=" * 70)
print("OPTIONS EXPIRY FORMAT CHECK")
print("=" * 70)
options_tests = [
    # (description, signal_text)
    ("AbTrades entry", "**$TSLA 6/18 420c 8.1**"),
    ("AbTrades LEAPS", "**$MTCH 1/15/2027 40c 3.2**"),
    ("Temple RF options", "buy QQQ 530+C at 2.50 for 5/16"),
    ("Temple RF with year", "buy AAPL 230+C at 3.00 for 5/16/25"),
    ("Temple standard", "TSLA 350c @.85"),
    ("Temple ZZ-A daily", "SPY P 653 daily"),
    ("Temple ZZ-A date", "QQQ C 480 5/16"),
    ("Temple ZZ-B", "SPY 580c 1.80"),
    ("Temple TS", "QQQ 579 Puts-.75 C SL .65"),
    ("Temple exit", "out TSLA 350c"),
    ("Jake full", "+1 $GRAB $7c 17APR2026 @ lim0.65"),
    ("Slem option", "NVDA 6/20 140C @2.50"),
    ("Stack option", "SPY 580C 6/13 @1.50"),
    ("Stack 0dte", "SPY 580C @1.50"),
    ("Rocky entry", "$AAPL 230c 6/20 @3.50"),
    ("Ashley entry", "MSFT 450c 6/20 2.50"),
    ("Angela entry", "BTO TSLA 350c 6/20 @1.50"),
]

for desc, text in options_tests:
    result = registry.parse(text)
    if result:
        expiry = result.get('expiry', 'NONE')
        fmt = result.get('_format_name', '?')
        iso_ok = bool(re.match(r'\d{4}-\d{2}-\d{2}', str(expiry))) if expiry and expiry != 'NONE' else False
        status = "OK" if iso_ok else "NOT ISO"
        print(f"  {status:7s} | {desc:25s} | expiry={str(expiry):12s} | fmt={fmt}")
    else:
        print(f"  NO HIT | {desc:25s} | text={text[:50]}")

# Check stock formats
print("\n" + "=" * 70)
print("STOCK FORMAT CHECK")
print("=" * 70)
stock_tests = [
    ("Temple emoji entry", "▶ PLTR $22.50"),
    ("Temple emoji exit", "⛔ PLTR"),
    ("Temple stock entry", "In MARA $18.50"),
    ("Temple stock exit", "Cut RIVN"),
    ("Temple trim", "Trim PLTR 35%"),
    ("Phoenix entry over", "PLTR over 22.50 SL 21.00"),
    ("Phoenix trim", "Trim PLTR here 50%"),
    ("Phoenix exit", "Out of PLTR"),
    ("Bronze entry", "Position on PLTR 22.50"),
    ("Foxtrades entry", "Taking a position in $PLTR average $22.50"),
    ("Foxtrades exit", "Out of $PLTR"),
    ("Viking entry", "$MWC 6.68 <@&1330929339134640179>"),
    ("Viking exit", "Elpw all out banger"),
]

for desc, text in stock_tests:
    result = registry.parse(text)
    if result:
        sym = result.get('symbol', '?')
        action = result.get('action', '?')
        fmt = result.get('_format_name', '?')
        print(f"  OK    | {desc:25s} | {action} {sym:6s} | fmt={fmt}")
    else:
        print(f"  MISS  | {desc:25s} | text={text[:50]}")
