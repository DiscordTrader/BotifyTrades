"""
BotifyTrades License Package - Server-side license validation with offline support

This package provides:
- License validation against api.botifytrades.com
- RSA signature verification for tamper-proof caching
- Offline grace period support
- Machine ID binding
- Background heartbeat validation

Usage (backward compatible with old license_client.py):
    from src.license import LicenseClient, get_machine_id
    
    client = LicenseClient()
    is_valid, result = client.validate_license("BT-XXXX-XXXX-XXXX-XXXX")
"""

# Re-export all public APIs for backward compatibility
from .license_types import (
    LICENSE_SERVER_URL,
    LICENSE_SERVER_URL_PRIMARY,
    LICENSE_SERVER_URL_FALLBACK,
    LICENSE_SERVER_URLS,
    RSA_PUBLIC_KEY_PEM,
    DEFAULT_OFFLINE_HOURS,
    CACHE_DIR,
    CACHE_FILE,
    get_ssl_cert_path,
)

from .crypto import (
    get_machine_id,
    get_machine_info,
    verify_signed_token,
    compute_integrity_hash,
    verify_integrity,
)

from .cache import LicenseCache

from .client import (
    LicenseClient,
    validate_with_server,
)

from .heartbeat import (
    LicenseHeartbeat,
    start_license_heartbeat,
    stop_license_heartbeat,
)

from .network_monitor import (
    NetworkMonitor,
    start_network_monitor,
    stop_network_monitor,
    show_license_expired_popup,
)

# For backward compatibility with old imports
_verify_signed_token = verify_signed_token

__all__ = [
    # Types and constants
    'LICENSE_SERVER_URL',
    'LICENSE_SERVER_URL_PRIMARY',
    'LICENSE_SERVER_URL_FALLBACK',
    'LICENSE_SERVER_URLS',
    'RSA_PUBLIC_KEY_PEM',
    'DEFAULT_OFFLINE_HOURS',
    'CACHE_DIR',
    'CACHE_FILE',
    'get_ssl_cert_path',
    
    # Crypto functions
    'get_machine_id',
    'get_machine_info',
    'verify_signed_token',
    '_verify_signed_token',
    'compute_integrity_hash',
    'verify_integrity',
    
    # Cache
    'LicenseCache',
    
    # Client
    'LicenseClient',
    'validate_with_server',
    
    # Heartbeat
    'LicenseHeartbeat',
    'start_license_heartbeat',
    'stop_license_heartbeat',
    
    # Network Monitor
    'NetworkMonitor',
    'start_network_monitor',
    'stop_network_monitor',
    'show_license_expired_popup',
]
