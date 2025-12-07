"""
License Cache - Offline caching and grace period management
"""

import json
import builtins
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from .types import CACHE_DIR, CACHE_FILE, DEFAULT_OFFLINE_HOURS
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
        _print = getattr(builtins, '_original_print', builtins.print)
        
        try:
            _print(f"[LICENSE-SAVE] === SAVING NEW ACTIVATION TO CACHE ===", flush=True)
            _print(f"[LICENSE-SAVE] Result keys: {list(result.keys())}", flush=True)
            _print(f"[LICENSE-SAVE] Has signed_token: {bool(result.get('signed_token'))}", flush=True)
            _print(f"[LICENSE-SAVE] expires: {result.get('expires')}", flush=True)
            _print(f"[LICENSE-SAVE] days_remaining: {result.get('days_remaining')}", flush=True)
            sys.stdout.flush()
            
            cache_data = {
                'license_key': license_key,
                'machine_id': self.machine_id,
                'last_validated': datetime.now().isoformat(),
                'result': result,
                'expires_at': result.get('expires'),
                'days_remaining': result.get('days_remaining'),
                'signed_token': result.get('signed_token')
            }
            
            _print(f"[LICENSE-SAVE] Cache file: {self.cache_file}", flush=True)
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            _print(f"[LICENSE-SAVE] Cache saved successfully!", flush=True)
            _print(f"[LICENSE-SAVE] License: {license_key[:12]}...", flush=True)
            _print(f"[LICENSE-SAVE] Machine: {self.machine_id}", flush=True)
            if result.get('signed_token'):
                _print(f"[LICENSE-SAVE] Signed token length: {len(result.get('signed_token'))}", flush=True)
            sys.stdout.flush()
            
        except Exception as e:
            _print(f"[LICENSE-SAVE] ERROR saving cache: {e}", flush=True)
            import traceback
            traceback.print_exc()
    
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
        _print = getattr(builtins, '_original_print', builtins.print)
        
        try:
            if grace_hours is None:
                grace_hours = DEFAULT_OFFLINE_HOURS
            
            _print(f"[LICENSE] GRACE: Checking period (max {grace_hours}h)", flush=True)
            sys.stdout.flush()
            
            # Check for signed token (preferred method)
            signed_token = cache.get('signed_token')
            _print(f"[LICENSE] GRACE: Has signed_token: {bool(signed_token)}", flush=True)
            sys.stdout.flush()
            
            if not signed_token:
                # FALLBACK: Check time-based grace period
                return self._check_time_based_grace(cache, grace_hours)
            
            # Verify the signed token cryptographically
            _print(f"[LICENSE] GRACE: Verifying signed token...", flush=True)
            sys.stdout.flush()
            is_valid, payload = verify_signed_token(signed_token, self.machine_id)
            _print(f"[LICENSE] GRACE: Token verification result: valid={is_valid}", flush=True)
            sys.stdout.flush()
            
            if not is_valid:
                # Token verification failed - FALL BACK to time-based grace
                _print(f"[LICENSE] GRACE: Token verification failed, trying time-based fallback", flush=True)
                return self._check_time_based_grace(cache, grace_hours)
            
            _print(f"[LICENSE] GRACE: Token payload keys: {list(payload.keys()) if payload else 'None'}", flush=True)
            sys.stdout.flush()
            
            # Check license expiration
            is_expired, expire_msg = self._check_license_expiration(payload)
            if is_expired:
                return False, expire_msg
            
            # Use server-signed grace expiration (if available)
            grace_expires_str = payload.get('offline_grace_expires') if payload else None
            _print(f"[LICENSE] GRACE: offline_grace_expires in payload: {bool(grace_expires_str)}", flush=True)
            
            if not grace_expires_str:
                # FALLBACK: Use time-based grace if token doesn't have offline_grace_expires
                _print(f"[LICENSE] GRACE: No offline_grace_expires, using time-based fallback", flush=True)
                last_validated = cache.get('last_validated')
                if last_validated:
                    validated_dt = datetime.fromisoformat(last_validated)
                    hours_since = (datetime.now() - validated_dt).total_seconds() / 3600
                    if hours_since <= grace_hours:
                        hours_remaining = grace_hours - hours_since
                        _print(f"[LICENSE] GRACE: Time-based grace ({hours_remaining:.1f}h remaining)", flush=True)
                        sys.stdout.flush()
                        return True, f"Offline mode ({hours_remaining:.1f}h remaining) - verified token"
                _print(f"[LICENSE] GRACE: No grace expiry and time fallback failed", flush=True)
                return False, "Grace period expired - server connection required"
            
            grace_expires = datetime.fromisoformat(grace_expires_str)
            if datetime.now() < grace_expires:
                hours = int((grace_expires - datetime.now()).total_seconds() / 3600)
                _print(f"[LICENSE] GRACE: Signed grace valid ({hours}h remaining)", flush=True)
                return True, f"Offline mode (verified) - {hours}h grace remaining"
            else:
                _print(f"[LICENSE] GRACE: Signed grace expired", flush=True)
                return False, "Grace period expired - server connection required"
                
        except Exception as e:
            return False, f"Cache verification error: {e}"
    
    def _check_time_based_grace(self, cache: Dict, grace_hours: int) -> Tuple[bool, str]:
        """Fallback time-based grace period check."""
        _print = getattr(builtins, '_original_print', builtins.print)
        
        last_validated = cache.get('last_validated')
        _print(f"[LICENSE] GRACE: last_validated: {last_validated}", flush=True)
        sys.stdout.flush()
        
        if last_validated:
            try:
                validated_dt = datetime.fromisoformat(last_validated)
                hours_since = (datetime.now() - validated_dt).total_seconds() / 3600
                _print(f"[LICENSE] GRACE: Hours since validation: {hours_since:.1f}", flush=True)
                sys.stdout.flush()
                
                if hours_since <= grace_hours:
                    hours_remaining = grace_hours - hours_since
                    _print(f"[LICENSE] GRACE: Within time-based period ({hours_remaining:.1f}h remaining)", flush=True)
                    sys.stdout.flush()
                    return True, f"Offline mode ({hours_remaining:.1f}h remaining) - time-based"
                else:
                    _print(f"[LICENSE] GRACE: Time-based period expired", flush=True)
                    sys.stdout.flush()
                    return False, f"Grace period expired ({hours_since:.1f}h ago) - server connection required"
            except Exception as e:
                _print(f"[LICENSE] GRACE: Error parsing last_validated: {e}", flush=True)
                sys.stdout.flush()
        
        _print(f"[LICENSE] GRACE: No signed token and no valid last_validated", flush=True)
        sys.stdout.flush()
        return False, "No verified cache - server connection required (connect once to enable offline mode)"
    
    def _check_license_expiration(self, payload: dict) -> Tuple[bool, str]:
        """Check if the actual license has expired."""
        _print = getattr(builtins, '_original_print', builtins.print)
        
        license_expires_str = payload.get('expires') if payload else None
        if license_expires_str:
            try:
                if 'T' in license_expires_str:
                    license_expires = datetime.fromisoformat(license_expires_str.replace('Z', '+00:00'))
                else:
                    license_expires = datetime.strptime(license_expires_str, '%Y-%m-%d %H:%M:%S')
                
                if datetime.now() >= license_expires:
                    _print(f"[LICENSE] GRACE: License expired on {license_expires_str}", flush=True)
                    return True, "License has expired - please renew your subscription"
                
                # Calculate time remaining
                time_remaining = license_expires - datetime.now()
                hours_remaining = time_remaining.total_seconds() / 3600
                
                if hours_remaining <= 0:
                    _print(f"[LICENSE] GRACE: License expired ({hours_remaining:.1f}h ago)", flush=True)
                    return True, "License has expired - please renew your subscription"
                
                _print(f"[LICENSE] GRACE: License still valid ({hours_remaining:.1f}h remaining)", flush=True)
                
            except Exception as e:
                _print(f"[LICENSE] GRACE: Could not parse expiry: {e}", flush=True)
        
        return False, ""
