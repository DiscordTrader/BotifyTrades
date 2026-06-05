"""
License Configuration Module
Centralized configuration for the licensing system
"""

from .constants import (
    SECRET_KEY,
    RSA_PUBLIC_KEY_PEM,
    ACTIVATED_LICENSE_FILE,
    LICENSE_SERVER_URL,
    DEFAULT_OFFLINE_HOURS,
)

__all__ = [
    'SECRET_KEY',
    'RSA_PUBLIC_KEY_PEM', 
    'ACTIVATED_LICENSE_FILE',
    'LICENSE_SERVER_URL',
    'DEFAULT_OFFLINE_HOURS',
]
