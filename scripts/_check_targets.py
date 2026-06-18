"""Verify all target extraction from real signals."""
import json, sys, re
sys.path.insert(0, "src")
from signals.temple_parser import _parse_zz_targets

test_cases = [
    ("1 target", "3.00", None, [3.0]),
    ("2 range", "2.60-3.00", None, [2.6, 3.0]),
    ("3 pct", "5% 10% 15%", 1.50, [1.575, 1.65, 1.725]),
    ("3 ellipsis", "0.33...0.37...0.40", None, [0.33, 0.37, 0.4]),
    ("4 dash", "1.20-1.50-1.70-2.00", None, [1.2, 1.5, 1.7, 2.0]),
    ("4 ellipsis", "1.64...1.74...1.88...2.00", None, [1.64, 1.74, 1.88, 2.0]),
    ("5 ellipsis", "4.53...5.15...5.43...6.00..6.50+", None, [4.53, 5.15, 5.43, 6.0, 6.5]),
    ("5 ellipsis2", "2.21....2.35...2.43....2.53...3.00+", None, [2.21, 2.35, 2.43, 2.53, 3.0]),
    ("5 ellipsis3", "4.46...4.78...5.20...6.39....8.32", None, [4.46, 4.78, 5.2, 6.39, 8.32]),
    ("6 ellipsis", "0.35...0.39...0.42...0.49...0.55...0.60", None, [0.35, 0.39, 0.42, 0.49, 0.55, 0.6]),
    ("4 ellipsis+", "1.00...1.20...1.45...2.00", None, [1.0, 1.2, 1.45, 2.0]),
    ("3 dash", "0.10-0.12-0.15", None, [0.1, 0.12, 0.15]),
    ("2 slash", "1.50/1.70", None, [1.5, 1.7]),
    ("pct with +", "5% 10% 15%+", 2.0, [2.1, 2.2, 2.3]),
    ("range target", "7-10", None, [7.0, 10.0]),
    ("range target2", "3.90-5.00", None, [3.9, 5.0]),
    ("pct ellipsis", "5%...10%...15%", 3.50, [3.675, 3.85, 4.025]),
]

passed = 0
failed = 0
for name, inp, entry, expected in test_cases:
    result = _parse_zz_targets(inp, entry_price=entry)
    ok = result == expected
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {name}: input={inp!r} entry={entry}")
        print(f"  expected: {expected}")
        print(f"  got:      {result}")

print(f"\n{passed}/{passed+failed} passed, {failed} failed")
