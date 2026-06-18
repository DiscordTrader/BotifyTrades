import sqlite3
conn = sqlite3.connect('bot_data.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Check if viking channel exists
cur.execute("SELECT discord_channel_id, name, execute_enabled, track_enabled FROM channels WHERE discord_channel_id = '1330305940569853962' OR name LIKE '%viking%'")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"Channel: {dict(r)}")
else:
    print("viking-plays channel NOT configured — need to add it")

# Check new tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('channel_learning_state','format_candidates')")
tables = [r['name'] for r in cur.fetchall()]
print(f"New tables: {tables if tables else 'NOT CREATED YET (will create on restart)'}")

# Check buffered messages for viking
cur.execute("SELECT COUNT(*) as cnt FROM channel_messages WHERE channel_id = '1330305940569853962'")
row = cur.fetchone()
print(f"Buffered messages for viking-plays: {row['cnt']}")

# Check AI provider
try:
    cur.execute("SELECT key, value FROM config WHERE key = 'ai_provider'")
    row = cur.fetchone()
    print(f"AI provider: {row['value'] if row else 'not set'}")
except Exception:
    print("AI provider: unknown")

conn.close()
