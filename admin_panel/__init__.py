"""
Admin License Server Panel - License Management Only

This is a lean Flask application for license management.
It does NOT include any trading functionality.

For trading features, use the User Bot Build.
"""

from .app import create_app

__all__ = ['create_app']
