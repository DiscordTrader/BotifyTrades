"""
License System Constants
All sensitive keys and configuration in one place
IMPORTANT: This file should be obfuscated with PyArmor before distribution
"""

import os
from pathlib import Path

def _get_secret_key() -> bytes:
    """Get SECRET_KEY from environment or fallback to default (for development only)"""
    env_key = os.getenv('LICENSE_SECRET_KEY')
    if env_key:
        return env_key.encode('utf-8')
    return b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0744e429edb8c876dd2d8e227a16f4d3b09beac10c9c2984a"

SECRET_KEY = _get_secret_key()

RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1234567890ABCDEFGHIJK
LMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuvwxyz1234567890ABCD
EFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuvwxyz12345678
90ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuvwxyz123
4567890ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuvwxy
z1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuv
wxyz1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ==
-----END PUBLIC KEY-----"""

ACTIVATED_LICENSE_FILE = Path.home() / ".tradingbot_license"

LICENSE_SERVER_URL = os.getenv("LICENSE_SERVER_URL", "https://your-license-server.com")

DEFAULT_OFFLINE_HOURS = 6

LICENSE_CACHE_DIR = Path.home() / '.discord_trading_bot'
LICENSE_CACHE_FILE = LICENSE_CACHE_DIR / 'license_cache.json'
