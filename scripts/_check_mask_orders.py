import sys, io, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
conn = sqlite3.connect('c:/VSCode/Cluade_Botify/BotifyTradesv2/bot_data.db')
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT id, symbol, status, trigger_price, trigger_type, stop_loss_value, take_profit_targets, created_at "
    "FROM conditional_orders WHERE symbol='MASK' ORDER BY id DESC LIMIT 5"
).fetchall()
print(f'Conditional orders for MASK: {len(rows)}')
for r in rows:
    print(f'  id={r["id"]} status={r["status"]} trigger={r["trigger_price"]} ({r["trigger_type"]}) sl={r["stop_loss_value"]} pts={r["take_profit_targets"]} created={r["created_at"]}')

rows2 = conn.execute(
    "SELECT id, symbol, status, broker, created_at FROM trades WHERE symbol='MASK' ORDER BY id DESC LIMIT 5"
).fetchall()
print(f'Trades for MASK: {len(rows2)}')
for r in rows2:
    print(f'  id={r["id"]} status={r["status"]} broker={r["broker"]} created={r["created_at"]}')

conn.close()
