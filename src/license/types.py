"""
License Types - Constants, URLs, and configuration for BotifyTrades License System
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Primary license server URL (production domain)
LICENSE_SERVER_URL_PRIMARY = "https://api.botifytrades.com"

# Fallback URL (Replit - used during migration or if primary is down)
LICENSE_SERVER_URL_FALLBACK = "https://92ef2f8a-9447-4d91-8823-2ac83e184d7a-00-384f7fcagd1yw.janeway.replit.dev"

# For backwards compatibility - defaults to primary, falls back automatically
LICENSE_SERVER_URL = LICENSE_SERVER_URL_PRIMARY

# All server URLs to try in order (primary first, then fallbacks)
LICENSE_SERVER_URLS = [
    LICENSE_SERVER_URL_PRIMARY,
    LICENSE_SERVER_URL_FALLBACK,
]

# RSA Public Key for verifying server-signed tokens
# This key is embedded in the client - only the server has the private key
RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAufORe8XZBuHWF3YucVf9
kKtvvS9qDW781npsrQ2Z5zjgt58Ug1oDhqVVB6e+JmABABjDXiRvw5iavCtmf1UJ
vJwBoesMKac3mSOATlqPsnkWfWopVYi4sA/lQarJsUTSJYVgajibTmOOvj/2UozX
Z9pKHD/3bTGA/DNgJjp+KVSTSdohxYORur90taKGnfrpZqHOuOyVRqkdt3TULFmH
JrUZ0AaSZYimK2NrZqsbx3TnNPCDGW635iB6A0q+bwGYLMv7yavLmjzrvKsY65YX
MPjAu364HaBXznRaW5RcBsOXaM02OOdP4gH79xrF4GjYrRJzLVsYJu4kEQaSCTwz
BwIDAQAB
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
