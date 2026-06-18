import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, '.')

import builtins
_rp = builtins.print
def _q(msg='', *a, **kw):
    s = str(msg)
    if any(x in s for x in ['[DATABASE]','[LICENSE]','[GUI]','INFO:','WARNING:','[CONTRACT']):
        return
    _rp(msg, *a, **kw)
builtins.print = _q

from src.services.schwab_data_hub import get_schwab_data_hub
builtins.print = _rp

hub = get_schwab_data_hub()
print('=== Schwab Data Hub State ===')
stats = hub.get_stats()
for k, v in stats.items():
    print(f'  {k}: {v}')

print()
print('=== Hub Cached Positions (detailed) ===')
pos = hub.get_positions(detailed=True)
if pos is None:
    print('  CACHE EXPIRED or never populated (positions_detailed_age > 30s)')
else:
    print(f'  {len(pos)} positions cached')
    for p in pos:
        sym = p.get('symbol', '?')
        raw = p.get('raw_symbol', '')
        asset = p.get('asset', 'stock')
        qty = p.get('quantity', 0)
        avg = p.get('avg_cost', 0)
        price = p.get('current_price', 0)
        upl = p.get('unrealized_pl', 0)
        print(f'  {sym} ({asset}) qty={qty} avg=${avg:.2f} price=${price:.2f} upl=${upl:.2f}', end='')
        if raw:
            print(f' [OCC: {raw}]', end='')
        print()

print()
print('=== Hub Streaming Quotes (for position symbols) ===')
all_quotes = hub.get_all_quotes()
print(f'  Total cached quotes: {len(all_quotes)}')
for sym, q in list(all_quotes.items())[:20]:
    import time
    age = round(time.time() - q.timestamp, 1)
    print(f'  {sym}: last=${q.last:.2f} bid=${q.bid:.2f} ask=${q.ask:.2f} age={age}s')

print()
print('=== Hub Positions (non-detailed) ===')
pos2 = hub.get_positions(detailed=False)
if pos2 is None:
    print('  CACHE EXPIRED or never populated')
else:
    print(f'  {len(pos2)} simple positions cached')
