"""
GUI Application Package
Flask-based web control panel for Discord Trading Bot
"""
import sys
import os

# Handle PyInstaller GUI mode where stdout/stderr may be None
# This MUST happen before any imports that use print()
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8', errors='replace')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8', errors='replace')

from .app import create_app, start_gui_server, get_gui_port
from . import database

__all__ = ['create_app', 'start_gui_server', 'get_gui_port', 'database']
