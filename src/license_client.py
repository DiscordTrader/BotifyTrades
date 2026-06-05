"""
License Client - Backward Compatibility Wrapper

This module re-exports all functionality from the new src/license/ package
to maintain backward compatibility with existing imports.

New code should import from: src.license
Legacy code can continue using: src.license_client
"""

# Re-export everything from the new package structure
from src.license import (
    # Types and constants
    LICENSE_SERVER_URL,
    LICENSE_SERVER_URL_PRIMARY,
    LICENSE_SERVER_URL_FALLBACK,
    LICENSE_SERVER_URLS,
    RSA_PUBLIC_KEY_PEM,
    DEFAULT_OFFLINE_HOURS,
    CACHE_DIR,
    CACHE_FILE,
    get_ssl_cert_path,
    
    # Crypto functions
    get_machine_id,
    get_machine_info,
    verify_signed_token,
    compute_integrity_hash,
    verify_integrity,
    
    # Cache
    LicenseCache,
    
    # Client
    LicenseClient,
    validate_with_server,
    
    # Heartbeat
    LicenseHeartbeat,
    start_license_heartbeat,
    stop_license_heartbeat,
    
    # Network Monitor
    NetworkMonitor,
    start_network_monitor,
    stop_network_monitor,
    show_license_expired_popup,
)

# Backward compatibility alias
_verify_signed_token = verify_signed_token

__all__ = [
    'LICENSE_SERVER_URL',
    'LICENSE_SERVER_URL_PRIMARY',
    'LICENSE_SERVER_URL_FALLBACK',
    'LICENSE_SERVER_URLS',
    'RSA_PUBLIC_KEY_PEM',
    'DEFAULT_OFFLINE_HOURS',
    'CACHE_DIR',
    'CACHE_FILE',
    'get_ssl_cert_path',
    'get_machine_id',
    'get_machine_info',
    'verify_signed_token',
    '_verify_signed_token',
    'compute_integrity_hash',
    'verify_integrity',
    'LicenseCache',
    'LicenseClient',
    'validate_with_server',
    'LicenseHeartbeat',
    'start_license_heartbeat',
    'stop_license_heartbeat',
    'NetworkMonitor',
    'start_network_monitor',
    'stop_network_monitor',
    'show_license_expired_popup',
]
