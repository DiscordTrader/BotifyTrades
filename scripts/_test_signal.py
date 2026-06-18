import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PYTHONIOENCODING"] = "utf-8"

sig = "$SDOT will buy if it breaks 1.42 for 1.72 @Momentum"

from src.signals.parser import (
    is_bullwinkle_signal, is_jacob_signal, is_zscalps_signal,
    is_jake_signal, is_order_executed_signal
)

print(f"Signal: {sig}")
print(f"is_bullwinkle: {is_bullwinkle_signal(sig)}")
print(f"is_jacob: {is_jacob_signal(sig)}")
print(f"is_zscalps: {is_zscalps_signal(sig)}")
print(f"is_jake: {is_jake_signal(sig)}")
print(f"is_order_executed: {is_order_executed_signal(sig)}")

content_upper = sig.upper()
print(f"is_bto_stc: {content_upper.startswith('BTO ') or content_upper.startswith('STC ') or ' BTO ' in content_upper or ' STC ' in content_upper}")

from src.services.signal_format_registry import SignalFormatRegistry
registry = SignalFormatRegistry()
results = registry.parse_all(sig)
print(f"registry matches: {len(results)}")
for r in results:
    print(f"  {r.get('_format_name')}: action={r.get('action')} asset={r.get('asset')} cond={r.get('_conditional_order')}")
