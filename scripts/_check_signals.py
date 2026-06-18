import sqlite3

conn = sqlite3.connect('bot_data.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Check last 10 signals
cur.execute("SELECT id, direction, asset_type, symbol, strike, call_put, price, received_at, execution_status FROM signals ORDER BY id DESC LIMIT 10")
rows = cur.fetchall()
print("=== RECENT SIGNALS ===")
for r in rows:
    d = dict(r)
    print(f"  #{d['id']} {d.get('direction','?')} {d['symbol']} @ {d['price']} | {d.get('execution_status','?')} | {d['received_at']}")

# Check last 10 order events
print("\n=== RECENT ORDER EVENTS ===")
cur.execute("SELECT id, timestamp, event_type, symbol, reason FROM order_events ORDER BY id DESC LIMIT 10")
for r in cur.fetchall():
    d = dict(r)
    reason = (d.get('reason') or '')[:120]
    print(f"  #{d['id']} {d['event_type']} {d['symbol']} | {reason} | {d['timestamp']}")

conn.close()
