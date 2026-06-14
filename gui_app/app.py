"""
Flask Web GUI Application
Main control panel for Discord Trading Bot
"""
import threading
import os
import secrets
from flask import Flask, render_template, jsonify, request
from pathlib import Path
import sys

def create_app():
    """Create and configure Flask application"""
    # Determine template and static folders based on runtime environment
    if getattr(sys, 'frozen', False):
        # Running as compiled exe - use PyInstaller bundle path
        base_path = Path(getattr(sys, '_MEIPASS', '.'))
        template_folder = str(base_path / 'gui_app' / 'templates')
        static_folder = str(base_path / 'gui_app' / 'static')
        
        # Debug logging for PyInstaller builds
        print(f"[FLASK] PyInstaller mode - base_path: {base_path}")
        print(f"[FLASK] Template folder: {template_folder}")
        print(f"[FLASK] Template folder exists: {os.path.exists(template_folder)}")
        
        # Verify templates exist
        if os.path.exists(template_folder):
            templates = os.listdir(template_folder)
            print(f"[FLASK] Found {len(templates)} templates: {templates[:5]}...")
        else:
            print(f"[FLASK] WARNING: Template folder not found!")
            # Try alternate path - look for gui_app as sibling
            alt_base = Path(sys.executable).parent
            alt_template = str(alt_base / 'gui_app' / 'templates')
            if os.path.exists(alt_template):
                print(f"[FLASK] Using alternate path: {alt_template}")
                template_folder = alt_template
                static_folder = str(alt_base / 'gui_app' / 'static')
    else:
        # Running from source - use default relative paths
        template_folder = None  # Flask default
        static_folder = None  # Flask default
    
    # Create Flask app with correct folders from the start
    if template_folder and static_folder:
        app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    else:
        app = Flask(__name__)
    
    # Persist SECRET_KEY in DB so sessions survive bot restarts
    _env_key = os.environ.get('FLASK_SECRET_KEY')
    if _env_key:
        _secret_key = _env_key
    else:
        try:
            import sqlite3 as _sqlite3
            from pathlib import Path as _Path
            _db_candidates = [_Path('bot_data.db'), _Path(__file__).parent.parent / 'bot_data.db']
            _db_path = next((str(p) for p in _db_candidates if p.exists()), 'bot_data.db')
            _conn = _sqlite3.connect(_db_path)
            _row = _conn.execute("SELECT value FROM settings WHERE key='flask_secret_key'").fetchone()
            if _row:
                _secret_key = _row[0]
            else:
                _secret_key = secrets.token_hex(32)
                _conn.execute("INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('flask_secret_key', ?, CURRENT_TIMESTAMP)", (_secret_key,))
                _conn.commit()
            _conn.close()
        except Exception:
            _secret_key = secrets.token_hex(32)
    app.config['SECRET_KEY'] = _secret_key
    app.config['JSON_SORT_KEYS'] = False
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours
    app.config['TEMPLATES_AUTO_RELOAD'] = True  # Force template reload
    app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25MB max upload

    # Security settings for cookies
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Import database and config services
    from . import database
    try:
        from . import config_service  # requires cryptography — may fail on mismatched OpenSSL builds
    except Exception as _cs_err:
        import logging
        logging.warning(f"[FLASK] config_service unavailable (cryptography error): {_cs_err}")
        logging.warning("[FLASK] Settings encryption disabled — GUI will still start")
    try:
        from . import webhook_service
    except Exception as _ws_err:
        import logging
        logging.warning(f"[FLASK] webhook_service unavailable: {_ws_err}")
        webhook_service = None

    # Initialize database
    database.init_db()

    # Initialize webhook tables (uses same database)
    if webhook_service is not None:
        webhook_service.init_webhook_tables()
    
    # Register routes
    from . import routes
    routes.register_routes(app)

    @app.after_request
    def add_no_cache_headers(response):
        if response.content_type and 'text/html' in response.content_type:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    @app.errorhandler(413)
    def request_entity_too_large(error):
        from flask import jsonify
        return jsonify({'success': False, 'error': 'File too large. Maximum upload size is 20MB.'}), 413

    return app


def get_gui_port():
    """Get GUI port from environment variable or default to 5000"""
    return int(os.environ.get('GUI_PORT', 5000))


def _find_available_port(start_port, max_attempts=10):
    """Find an available port starting from start_port, incrementing on conflict."""
    import socket
    for offset in range(max_attempts):
        port = start_port + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return port
        except OSError:
            if offset == 0:
                print(f"[GUI] ⚠️ Port {port} is in use (macOS AirPlay, another app, etc.)")
            else:
                print(f"[GUI] ⚠️ Port {port} also in use, trying next...")
    return None


def start_gui_server(host='0.0.0.0', port=None):
    """Start Flask server in a separate thread

    Args:
        host: Host to bind to (default: 0.0.0.0)
        port: Port to bind to (default: GUI_PORT env var or 5000)
    """
    if port is None:
        port = get_gui_port()

    available_port = _find_available_port(port)
    if available_port is None:
        print(f"[GUI] ❌ No available port found in range {port}-{port + 9}")
        available_port = port
    elif available_port != port:
        print(f"[GUI] ✓ Using port {available_port} instead of {port}")
    port = available_port

    # Update env so get_gui_port() and any downstream code sees the actual port
    os.environ['GUI_PORT'] = str(port)

    app = create_app()

    def run():
        import logging
        logging.info(f"[GUI] Starting Flask on http://{host}:{port}")
        print(f"[GUI] Starting web control panel on http://{host}:{port}")
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    import logging
    logging.info(f"[GUI] Web server thread started on port {port}")
    print(f"[GUI] Web server thread started on port {port}")

    return thread, port
