"""
License Client Module
Runtime license validation for the trading bot application
"""

from .manager import LicenseManager
from .manager_secure import validate_license, validate_legacy_license, validate_machine_bound_license
from .manager_activation import activate_license, validate_activated_license, check_or_activate_license
from .client import LicenseClient

__all__ = [
    'LicenseManager',
    'validate_license',
    'validate_legacy_license', 
    'validate_machine_bound_license',
    'activate_license',
    'validate_activated_license',
    'check_or_activate_license',
    'LicenseClient',
]
