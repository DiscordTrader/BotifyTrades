"""Test if Temple stock signals are intercepted by option parsers"""
import sys, os, re
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

from src.signals.parser import (
    normalize_bullwinkle_format, is_india_signal,
    is_conditional_order_signal, parse_conditional_order_signal,
    is_bracket_order_signal, is_jacob_signal, is_trade_idea_signal
)

test_msgs = [
    'WNW 4.00-6.37<a:4743_pink_flame:1154098186831536248>',
    'GTBP 0.36-0.42<a:4743_pink_flame:1154098186831536248>',
    'SNAL 0.80-1.11<a:4743_pink_flame:1154098186831536248>',
    'NXXT 0.75-0.88',
    'CODX 2.05-2.43<a:4743_pink_flame:1154098186831536248>',
    '$AREB <@&1330929339134640179> \n✅ 0.30\n❌ 0.28\n\U0001f3af 0.33...0.37...0.40',
    '▶ PLTR $22.50',
    '⛔ PLTR',
    'PMAX break 2.82 for 3.12',
]

print("=" * 80)
print("Testing if Temple signals are intercepted by non-registry parsers")
print("=" * 80)

for msg in test_msgs:
    norm = normalize_bullwinkle_format(msg)
    issues = []

    if is_india_signal(norm):
        issues.append("INTERCEPTED by is_india_signal")
    if is_conditional_order_signal(norm, require_sl_pt=False):
        issues.append("INTERCEPTED by is_conditional_order_signal")
    if is_bracket_order_signal(norm):
        issues.append("INTERCEPTED by is_bracket_order_signal")
    if is_jacob_signal(norm):
        issues.append("INTERCEPTED by is_jacob_signal")
    if is_trade_idea_signal(msg):
        issues.append("INTERCEPTED by is_trade_idea_signal")

    if issues:
        print(f"PROBLEM: {msg[:60]}")
        for issue in issues:
            print(f"  -> {issue}")
    else:
        print(f"OK: {msg[:60]}")

# Now test the registry flow end-to-end
print("\n" + "=" * 80)
print("Testing registry parse flow")
print("=" * 80)

from src.services.signal_format_registry import parse_with_registry

for msg in test_msgs:
    norm = normalize_bullwinkle_format(msg)
    result = parse_with_registry(norm)
    if result:
        act = result.get('action')
        sym = result.get('symbol')
        ast = result.get('asset')
        fmt = result.get('_format_name')
        cond = result.get('_conditional_order', False)
        print(f"MATCH: {msg[:50]} -> {act} {sym} asset={ast} fmt={fmt} cond={cond}")
    else:
        print(f"NO MATCH: {msg[:50]}")

# Test UPDATE_TARGETS action — these should NOT be intercepted
print("\n" + "=" * 80)
print("Testing UPDATE_TARGETS / SL_UPDATE actions")
print("=" * 80)

update_msgs = [
    '\U0001f3af 2.41...2.71',
    '5.50 should be your new ERNA SL',
    'Move your SL up to 5.00 if in',
]

for msg in update_msgs:
    result = parse_with_registry(msg)
    if result:
        act = result.get('action')
        sym = result.get('symbol')
        fmt = result.get('_format_name')
        print(f"MATCH: {msg[:50]} -> action={act} symbol={sym} fmt={fmt}")
    else:
        print(f"NO MATCH: {msg[:50]}")
