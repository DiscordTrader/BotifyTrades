"""Track AI API usage and costs."""

def _ensure_table():
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT,
                model TEXT,
                feature TEXT,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    except Exception:
        pass

def track_usage(provider: str, model: str, feature: str, tokens_in: int = 0,
                tokens_out: int = 0, cost_usd: float = 0, latency_ms: int = 0):
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            INSERT INTO ai_api_usage (provider, model, feature, tokens_in, tokens_out, cost_usd, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (provider, model, feature, tokens_in, tokens_out, cost_usd, latency_ms))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_usage_summary(days: int = 30) -> dict:
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT provider, model, feature, COUNT(*) as calls,
                   SUM(tokens_in) as total_in, SUM(tokens_out) as total_out,
                   SUM(cost_usd) as total_cost, AVG(latency_ms) as avg_latency
            FROM ai_api_usage
            WHERE created_at > datetime('now', ? || ' days')
            GROUP BY provider, model, feature
            ORDER BY total_cost DESC
        ''', (f'-{days}',))
        rows = [dict(zip(['provider','model','feature','calls','total_in','total_out','total_cost','avg_latency'], r)) for r in cursor.fetchall()]
        conn.close()
        return {'usage': rows, 'total_cost': sum(r['total_cost'] or 0 for r in rows)}
    except Exception:
        return {'usage': [], 'total_cost': 0}

_ensure_table()
