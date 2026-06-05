#!/usr/bin/env python3
"""
WSGI entry point for Admin License Server.
Sets environment variables before importing the Flask app.
"""

import os
import sys

os.environ.setdefault('LICENSE_SERVER_MODE', 'true')
os.environ.setdefault('BUILD_TARGET', 'admin')
os.environ.setdefault('ADMIN_MODE', 'true')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from admin_panel import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
