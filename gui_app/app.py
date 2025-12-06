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
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))
    app.config['JSON_SORT_KEYS'] = False
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 24 hours
    
    # Security settings for cookies
    app.config['SESSION_COOKIE_SECURE'] = True  # Only send over HTTPS
    app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
    
    # Determine if running as PyInstaller bundle
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        template_folder = Path(sys._MEIPASS) / 'gui_app' / 'templates'
        static_folder = Path(sys._MEIPASS) / 'gui_app' / 'static'
        app.template_folder = str(template_folder)
        app.static_folder = str(static_folder)
    
    # Import database and config services
    from . import database
    from . import config_service
    
    # Initialize database
    database.init_db()
    
    # Register routes
    from . import routes
    routes.register_routes(app)
    
    return app


def start_gui_server(host='0.0.0.0', port=5000):
    """Start Flask server in a separate thread"""
    app = create_app()
    
    def run():
        print(f"[GUI] Starting web control panel on http://{host}:{port}")
        print(f"[GUI] Open your browser to access the control panel")
        app.run(host=host, port=port, debug=True, use_reloader=False)
    
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    print(f"[GUI] Web server thread started")
    
    return thread
