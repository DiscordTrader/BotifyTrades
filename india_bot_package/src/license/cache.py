"""
License Cache - Offline caching and grace period management
"""

import json
import builtins
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from .license_types import CACHE_DIR, CACHE_FILE, DEFAULT_OFFLINE_HOURS
from .crypto import verify_signed_token


class LicenseCache:
    """Manages license validation caching for offline support."""
    
    def __init__(self, machine_id: str, cache_dir: Path = None, cache_file: Path = None):
        self.machine_id = machine_id
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_file = cache_file or CACHE_FILE
        self.cache_dir.mkdir(exist_ok=True)
    
    def save(self, license_key: str, result: Dict):
        """Save validation result with signed token for offline grace period."""
        try:
            cache_data = {
                'license_key': license_key,
                'machine_id': self.machine_id,
                'last_validated': datetime.now().isoformat(),
                'result': result,
                'expires_at': result.get('expires'),
                'days_remaining': result.get('days_remaining'),
                'signed_token': result.get('signed_token')
            }
            
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
        except Exception as e:
            print(f"[LICENSE] Error saving cache: {e}")
    
    def load(self) -> Optional[Dict]:
        """Load cached validation result."""
        try:
            if not self.cache_file.exists():
                return None
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        except Exception:
            return None
    
    def clear(self) -> bool:
        """Clear the local license cache file."""
        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
                print(f"[LICENSE] Cache cleared: {self.cache_file}")
            return True
        except Exception as e:
            print(f"[LICENSE] Warning: Could not clear cache: {e}")
            return False
    
    def check_grace_period(self, cache: Dict, grace_hours: int = None) -> Tuple[bool, str]:
        """Check if within offline grace period using signed token or time-based fallback.
        
        Priority:
        1. Signed token (most secure, server-verified)
        2. Time-based grace period (fallback for when server doesn't return tokens)
        """
        try:
            if grace_hours is None:
                grace_hours = DEFAULT_OFFLINE_HOURS
            
            # Check for signed token (preferred method)
            signed_token = cache.get('signed_token')
            
            if not signed_token:
                return self._check_time_based_grace(cache, grace_hours)
            
            # Verify the signed token cryptographically
            is_valid, payload = verify_signed_token(signed_token, self.machine_id)
            
            if not is_valid:
                return self._check_time_based_grace(cache, grace_hours)
            
            # Check license expiration
            is_expired, expire_msg = self._check_license_expiration(payload)
            if is_expired:
                return False, expire_msg
            
            # Use server-signed grace expiration (if available)
            grace_expires_str = payload.get('offline_grace_expires') if payload else None
            
            if not grace_expires_str:
                last_validated = cache.get('last_validated')
                if last_validated:
                    validated_dt = datetime.fromisoformat(last_validated)
                    hours_since = (datetime.now() - validated_dt).total_seconds() / 3600
                    if hours_since <= grace_hours:
                        hours_remaining = grace_hours - hours_since
                        return True, f"Offline mode ({hours_remaining:.1f}h remaining) - verified token"
                return False, "Grace period expired - server connection required"
            
            grace_expires = datetime.fromisoformat(grace_expires_str)
            if datetime.now() < grace_expires:
                hours = int((grace_expires - datetime.now()).total_seconds() / 3600)
                return True, f"Offline mode (verified) - {hours}h grace remaining"
            else:
                return False, "Grace period expired - server connection required"
                
        except Exception as e:
            return False, f"Cache verification error: {e}"
    
    def _check_time_based_grace(self, cache: Dict, grace_hours: int) -> Tuple[bool, str]:
        """Fallback time-based grace period check."""
        last_validated = cache.get('last_validated')
        
        if last_validated:
            try:
                validated_dt = datetime.fromisoformat(last_validated)
                hours_since = (datetime.now() - validated_dt).total_seconds() / 3600
                
                if hours_since <= grace_hours:
                    hours_remaining = grace_hours - hours_since
                    return True, f"Offline mode ({hours_remaining:.1f}h remaining) - time-based"
                else:
                    return False, f"Grace period expired ({hours_since:.1f}h ago) - server connection required"
            except Exception:
                pass
        
        return False, "No verified cache - server connection required (connect once to enable offline mode)"
    
    def _check_license_expiration(self, payload: dict) -> Tuple[bool, str]:
        """Check if the actual license has expired."""
        license_expires_str = payload.get('expires') if payload else None
        if license_expires_str:
            try:
                if 'T' in license_expires_str:
                    license_expires = datetime.fromisoformat(license_expires_str.replace('Z', '+00:00'))
                else:
                    license_expires = datetime.strptime(license_expires_str, '%Y-%m-%d %H:%M:%S')
                
                if datetime.now() >= license_expires:
                    return True, "License has expired - please renew your subscription"
                
                # Calculate time remaining
                time_remaining = license_expires - datetime.now()
                hours_remaining = time_remaining.total_seconds() / 3600
                
                if hours_remaining <= 0:
                    return True, "License has expired - please renew your subscription"
                
            except Exception:
                pass
        
        return False, ""
