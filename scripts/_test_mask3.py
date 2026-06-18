import sys, os, io
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')

import builtins, re
_real_print = builtins.print
def _quiet(msg='', *a, **kw):
    s = str(msg)
    if any(x in s for x in ['[DATABASE]','[LICENSE]','[GUI]','[CONTRACT','[RATE_LIMIT','ExpiryResolver','INFO:','WARNING:']):
        return
    _real_print(msg, *a, **kw)
builtins.print = _quiet

from src.services.signal_format_registry import parse_all_with_registry, get_signal_format_registry

builtins.print = _real_print

ALLOWED = {
    'temple_zz_structured_entry', 'temple_zz_inline_role_entry',
    'temple_zz_plain_entry', 'temple_zz_stock_exit', 'temple_zz_emoji_exit',
    'temple_zz_emoji_target', 'temple_zz_trim_pct', 'temple_zz_sl_update_new',
    'temple_zz_sl_update_move', 'temple_zz_swing_update', 'temple_zz_vertical_entry',
}

sig = 'MASK \n✅ 2.60\n❌ 2.40\n\U0001f3af 2.73....2.84...2.90...3.00+'

all_results = parse_all_with_registry(sig)

def fmt_allowed(fname, allowed):
    if not fname: return False
    if fname in allowed: return True
    if fname.startswith('learned_') and fname[8:] in allowed: return True
    if f'learned_{fname}' in allowed: return True
    return False

filtered = [r for r in all_results if fmt_allowed(r.get('_format_name'), ALLOWED)]
blocked  = [r for r in all_results if not fmt_allowed(r.get('_format_name'), ALLOWED)]

print(f'Registry returned {len(all_results)} result(s)')
for r in all_results:
    fn = r.get('_format_name','?')
    status = 'ALLOW' if fmt_allowed(fn, ALLOWED) else 'BLOCK'
    print(f'  [{status}] {fn} -> {r.get("action")} {r.get("symbol")}')

print()
if filtered:
    r = filtered[0]
    print('=== FINAL PARSED RESULT ===')
    print(f'  format:          {r.get("_format_name")}')
    print(f'  action:          {r.get("action")}')
    print(f'  symbol:          {r.get("symbol")}')
    print(f'  trigger_price:   {r.get("trigger_price")}')
    print(f'  entry_high:      {r.get("entry_high")}')
    print(f'  stop_loss_fixed: {r.get("stop_loss_fixed")}')
    print(f'  profit_targets:  {r.get("profit_targets")}')
    print(f'  is_conditional:  {r.get("is_conditional")}')
    print(f'  _conditional_order: {r.get("_conditional_order")}')
    print(f'  asset:           {r.get("asset")}')
    print()
    print('Bot will process this as: is_phoenix_registry=True, is_protrader_conditional=True (conditional BTO)')
else:
    print('SIGNAL BLOCKED - no allowed format matched')
    for r in blocked:
        print(f'  Blocked: {r.get("_format_name")}')
