"""
License Types - Constants, URLs, and configuration for BotifyTrades License System
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# License server URLs in priority order
# New license server (primary)
LICENSE_SERVER_URL_PRIMARY = "https://license-forge--uk15286.replit.app"

# Legacy servers (fallbacks for existing users during migration)
LICENSE_SERVER_URL_LEGACY_1 = "https://discord-trader-botify-trades-releases--uk15286.replit.app"
LICENSE_SERVER_URL_LEGACY_2 = "https://api.botifytrades.com"

# Backwards compatibility alias
LICENSE_SERVER_URL_FALLBACK = LICENSE_SERVER_URL_LEGACY_1

# For backwards compatibility - defaults to primary
LICENSE_SERVER_URL = LICENSE_SERVER_URL_PRIMARY

# All server URLs to try in order (primary first, then fallbacks)
# Once all users migrate to new server, remove legacy URLs
LICENSE_SERVER_URLS = [
    LICENSE_SERVER_URL_PRIMARY,
    LICENSE_SERVER_URL_LEGACY_1,
    LICENSE_SERVER_URL_LEGACY_2,
]

# RSA Public Key for verifying server-signed tokens
# This key is embedded in the client - only the server has the private key
RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA9xawPYXSBBAYFbA1FHGa
yh3w9kdrulymcC8eGayVlLNaObI0yx8TUaftxTpjHi5g+Bg/RLnHw+tNdxiktJv2
KYdiJO19CNx1B7yw6zGPU67vxEQC6xINVoUjaEmC2T7ePcTpXEwX0ioDYPn6MMOh
DqZlBzy+sUU/3qr7KBXFMlCMrNsAO5nhj4UIhYavwGx5tlyO4NdtW7UIjZJDweFd
+o6H+/DJo9khP4MyyTJMYEfJBgperSd4LkE4PIOs6vp6EGtT7a38AcYJyLdXVeTF
PtTq1yAH5XHPKkDBo2xzaGWC1zJdHNd9Fg2FET4wnoDjH0H7E8vSwcaS1yA9W2b3
nQIDAQAB
-----END PUBLIC KEY-----"""

# Offline grace period configuration
DEFAULT_OFFLINE_HOURS = 48

# Cache directory and file paths
CACHE_DIR = Path.home() / '.discord_trading_bot'
CACHE_FILE = CACHE_DIR / 'license_cache.json'


def get_ssl_cert_path() -> Optional[str]:
    """Get SSL certificate path, handling PyInstaller bundles."""
    try:
        import certifi
        return certifi.where()
    except ImportError:
        pass
    
    # Check if running from PyInstaller bundle
    if getattr(sys, 'frozen', False):
        # Running as compiled EXE
        bundle_dir = sys._MEIPASS
        cert_path = os.path.join(bundle_dir, 'certifi', 'cacert.pem')
        if os.path.exists(cert_path):
            return cert_path
    
    return None  # Use system default
