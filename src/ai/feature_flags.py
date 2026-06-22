"""Feature flag service for AI modules. All flags OFF by default."""
import threading
import time

_cache = {}
_cache_ts = 0
_CACHE_TTL = 30  # seconds
_lock = threading.Lock()

def _ensure_table():
    try:
        from gui_app.database import get_connection
        conn = get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS ai_feature_flags (
                feature_key TEXT PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                config_json TEXT DEFAULT '{}',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    except Exception:
        pass

def is_enabled(feature_key: str) -> bool:
    """Check if an AI feature is enabled. Cached for 30s."""
    global _cache, _cache_ts
    now = time.time()
    if now - _cache_ts > _CACHE_TTL:
        _refresh_cache()
    return _cache.get(feature_key, False)

def get_config(feature_key: str) -> dict:
    """Get feature-specific configuration."""
    global _cache, _cache_ts
    import json
    now = time.time()
    if now - _cache_ts > _CACHE_TTL:
        _refresh_cache()
    config_str = _cache.get(f'{feature_key}_config', '{}')
    try:
        return json.loads(config_str) if isinstance(config_str, str) else config_str
    except Exception:
        return {}

def set_enabled(feature_key: str, enabled: bool, config: dict = None):
    """Set feature flag. Creates row if not exists."""
    import json
    try:
        _ensure_table()
        from gui_app.database import get_connection
        conn = get_connection()
        config_json = json.dumps(config) if config else '{}'
        conn.execute('''
            INSERT INTO ai_feature_flags (feature_key, enabled, config_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(feature_key) DO UPDATE SET enabled=?, config_json=?, updated_at=CURRENT_TIMESTAMP
        ''', (feature_key, 1 if enabled else 0, config_json, 1 if enabled else 0, config_json))
        conn.commit()
        conn.close()
        _refresh_cache()
    except Exception as e:
        print(f'[AI_FLAGS] Error setting {feature_key}: {e}')

def _refresh_cache():
    global _cache, _cache_ts
    try:
        _ensure_table()
        from gui_app.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT feature_key, enabled, config_json FROM ai_feature_flags')
        new_cache = {}
        for row in cursor.fetchall():
            new_cache[row[0]] = bool(row[1])
            new_cache[f"{row[0]}_config"] = row[2] or '{}'
        conn.close()
        with _lock:
            _cache = new_cache
            _cache_ts = time.time()
    except Exception:
        pass

def get_all_flags() -> dict:
    """Return all flags with their status."""
    _refresh_cache()
    return {k: v for k, v in _cache.items() if not k.endswith('_config')}

# Ensure table exists on import
_ensure_table()
