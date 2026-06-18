import sqlite3
conn = sqlite3.connect('bot_data.db')
cur = conn.cursor()
cur.execute(
    "INSERT INTO channels (discord_channel_id, name, category, execute_enabled, track_enabled, is_active, allowed_signal_formats) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ('1330305940569853962', 'viking-plays', 'EXECUTE', 1, 1, 1, '["viking_entry","viking_entry_role_first","viking_exit"]')
)
conn.commit()
print(f"Added: {cur.rowcount}")
cur.execute("SELECT id, name, execute_enabled, track_enabled, allowed_signal_formats FROM channels WHERE discord_channel_id = '1330305940569853962'")
row = cur.fetchone()
print(f"Verified: id={row[0]} name={row[1]} exec={row[2]} track={row[3]} formats={row[4]}")
conn.close()
