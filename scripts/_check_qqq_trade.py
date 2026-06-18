import sys, io, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
conn = sqlite3.connect('c:/VSCode/Cluade_Botify/BotifyTradesv2/bot_data.db')
conn.row_factory = sqlite3.Row

print('=== Trade #330 ===')
r = conn.execute('SELECT * FROM trades WHERE id=330').fetchone()
if r:
    for k in r.keys():
        print(f'  {k}: {r[k]}')

print()
print('=== All OPEN/PENDING QQQ trades ===')
rows = conn.execute(
    "SELECT id, symbol, asset_type, broker, status, direction, quantity, strike, expiry, call_put, order_id, executed_price FROM trades "
    "WHERE symbol='QQQ' AND status IN ('OPEN','PENDING','PARTIAL') ORDER BY id DESC LIMIT 10"
).fetchall()
for r in rows:
    print(f'  #{r["id"]} {r["status"]} {r["broker"]} {r["asset_type"]} strike={r["strike"]} expiry={r["expiry"]} cp={r["call_put"]} qty={r["quantity"]} dir={r["direction"]} order_id={r["order_id"]}')

print()
print('=== Recent QQQ trades (all statuses) ===')
rows2 = conn.execute(
    "SELECT id, symbol, status, broker, direction, quantity, strike, expiry, call_put, created_at FROM trades "
    "WHERE symbol='QQQ' ORDER BY id DESC LIMIT 15"
).fetchall()
for r in rows2:
    print(f'  #{r["id"]} {r["status"]} {r["broker"]} strike={r["strike"]} expiry={r["expiry"]} cp={r["call_put"]} qty={r["quantity"]} dir={r["direction"]} created={r["created_at"]}')

conn.close()
