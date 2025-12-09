#!/usr/bin/env python3
"""
Admin License Server - LEAN License Management Only

This is the Admin License Server for managing BotifyTrades licenses.
It does NOT include any trading functionality.

Features:
- Admin authentication
- License creation, viewing, revocation
- Device activation management
- License validation API for clients

For trading functionality, use the User Bot Build (selfbot_webull.py).
"""

import os
import sys

os.environ['LICENSE_SERVER_MODE'] = 'true'
os.environ['BUILD_TARGET'] = 'admin'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from admin_panel import create_app

app = create_app()

def main():
    """Run the admin server directly."""
    print("=" * 60)
    print("ADMIN LICENSE SERVER")
    print("=" * 60)
    print("[ADMIN] License Management Only - No Trading Features")
    print("[ADMIN] Starting lean admin panel...")
    print("=" * 60)
    
    port = int(os.getenv('PORT', 5000))
    
    print(f"[ADMIN] Server starting on http://0.0.0.0:{port}")
    print(f"[ADMIN] License Panel: http://0.0.0.0:{port}/licenses")
    print(f"[ADMIN] API Endpoint: http://0.0.0.0:{port}/api/validate")
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

if __name__ == '__main__':
    try:
        main()
    except ImportError as e:
        print(f"[ADMIN] FATAL: Could not import admin panel: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"[ADMIN] Error starting server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
