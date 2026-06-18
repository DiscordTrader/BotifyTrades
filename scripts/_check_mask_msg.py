import sys, io, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
conn = sqlite3.connect('c:/VSCode/Cluade_Botify/BotifyTradesv2/bot_data.db')
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT id, channel_id, author_name, message_content FROM channel_messages "
    "WHERE message_content LIKE '%MASK%' ORDER BY id DESC LIMIT 5"
).fetchall()
print(f'Messages with MASK: {len(rows)}')
for r in rows:
    print(f'  ch={r["channel_id"]} author={r["author_name"]}')
    print(f'  content={repr(r["message_content"][:200])}')
    print()

# Also check signals
rows2 = conn.execute(
    "SELECT id, channel_id, action, symbol, raw_message FROM signals "
    "WHERE symbol='MASK' OR raw_message LIKE '%MASK%' ORDER BY id DESC LIMIT 5"
).fetchall()
print(f'Signals with MASK: {len(rows2)}')
for r in rows2:
    print(f'  id={r["id"]} ch={r["channel_id"]} {r["action"]} {r["symbol"]}')
    print(f'  raw={repr(str(r["raw_message"])[:150])}')
    print()
conn.close()
