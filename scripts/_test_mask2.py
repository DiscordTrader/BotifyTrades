import sys, os, io
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')

# Simulate the exact parse_all_with_registry call with the allowed-formats filter
sig = 'MASK \n✅ 2.60\n❌ 2.40\n\U0001f3af 2.73....2.84...2.90...3.00+'

ALLOWED = {
    'temple_zz_structured_entry', 'temple_zz_inline_role_entry',
    'temple_zz_plain_entry', 'temple_zz_stock_exit', 'temple_zz_emoji_exit',
    'temple_zz_emoji_target', 'temple_zz_trim_pct', 'temple_zz_sl_update_new',
    'temple_zz_sl_update_move', 'temple_zz_swing_update', 'temple_zz_vertical_entry',
}

# Patch print to suppress DB init noise
import builtins
_real_print = builtins.print
def _quiet_print(*a, **kw):
    msg = str(a[0]) if a else ''
    if '[DATABASE]' not in msg and '[LICENSE]' not in msg and '[GUI]' not in msg:
        _real_print(*a, **kw)
builtins.print = _quiet_print

try:
    from src.services.signal_format_registry import get_signal_format_registry
    reg = get_signal_format_registry()
    builtins.print = _real_print

    # Check ALL formats that match, in priority order
    print(f'Signal: {repr(sig)}')
    print(f'Allowed: {sorted(ALLOWED)}')
    print()
    print('All matching formats in priority order:')

    raw_text = sig.strip()
    import re
    clean_text = re.sub(r'<@[!&]?\d+>', '', raw_text).strip()

    matches = []
    for fmt in reg._sorted_formats:
        if not fmt.enabled:
            continue
        match_text = raw_text if fmt.name in reg._ROLE_AWARE_FORMATS else clean_text
        m = fmt.pattern.search(match_text)
        if m:
            try:
                result = fmt.parser(m, match_text)
                if result:
                    allowed = fmt.name in ALLOWED
                    matches.append((fmt.priority, fmt.name, allowed, result.get('action'), result.get('symbol')))
            except Exception as e:
                matches.append((fmt.priority, fmt.name, False, f'ERROR:{e}', ''))

    for pri, name, allowed, action, sym in matches:
        status = 'ALLOW' if allowed else 'BLOCK'
        print(f'  [{status}] pri={pri} {name} -> {action} {sym}')

    print()
    if matches:
        first_pri, first_name, first_allowed, first_action, first_sym = matches[0]
        if first_allowed:
            print(f'RESULT: Signal ACCEPTED as {first_name} -> {first_action} {first_sym}')
        else:
            print(f'RESULT: Signal BLOCKED — first match is "{first_name}" which is NOT in allowed list')
    else:
        print('RESULT: No format matched at all')

except Exception as e:
    builtins.print = _real_print
    import traceback
    traceback.print_exc()
