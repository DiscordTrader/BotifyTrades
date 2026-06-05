# Client-Side License Code - Complete Reference

## Overview

This document contains all 7 files needed for client-side license validation. Copy these files to your project's `src/license/` directory.

---

## Directory Structure

```
src/license/
├── __init__.py          # Package exports
├── license_types.py     # Constants, URLs, RSA key
├── crypto.py            # Machine ID, RSA verification
├── cache.py             # Offline caching, grace period
├── client.py            # HTTP client, validation logic
├── heartbeat.py         # Background re-validation
└── network_monitor.py   # Connectivity detection
```

---

## File 1: `license_types.py` - Constants & Configuration

```python
"""
License Types - Constants, URLs, and configuration for License System
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ============================================================
# LICENSE SERVER URLS
# ============================================================

# Primary license server (your Replit app)
LICENSE_SERVER_URL_PRIMARY = "https://license-forge--uk15286.replit.app"

# Legacy servers (fallbacks for existing users during migration)
LICENSE_SERVER_URL_LEGACY_1 = "https://discord-trader-botify-trades-releases--uk15286.replit.app"
LICENSE_SERVER_URL_LEGACY_2 = "https://api.botifytrades.com"

# Backwards compatibility alias
LICENSE_SERVER_URL_FALLBACK = LICENSE_SERVER_URL_LEGACY_1

# For backwards compatibility - defaults to primary
LICENSE_SERVER_URL = LICENSE_SERVER_URL_PRIMARY

# All server URLs to try in order (primary first, then fallbacks)
LICENSE_SERVER_URLS = [
    LICENSE_SERVER_URL_PRIMARY,
    LICENSE_SERVER_URL_LEGACY_1,
    LICENSE_SERVER_URL_LEGACY_2,
]

# ============================================================
# RSA PUBLIC KEY (for verifying server-signed tokens)
# ============================================================
# IMPORTANT: This key is embedded in the client
# Only the server has the private key - users cannot forge tokens

RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA9xawPYXSBBAYFbA1FHGa
yh3w9kdrulymcC8eGayVlLNaObI0yx8TUaftxTpjHi5g+Bg/RLnHw+tNdxiktJv2
KYdiJO19CNx1B7yw6zGPU67vxEQC6xINVoUjaEmC2T7ePcTpXEwX0ioDYPn6MMOh
DqZlBzy+sUU/3qr7KBXFMlCMrNsAO5nhj4UIhYavwGx5tlyO4NdtW7UIjZJDweFd
+o6H+/DJo9khP4MyyTJMYEfJBgperSd4LkE4PIOs6vp6EGtT7a38AcYJyLdXVeTF
PtTq1yAH5XHPKkDBo2xzaGWC1zJdHNd9Fg2FET4wnoDjH0H7E8vSwcaS1yA9W2b3
nQIDAQAB
-----END PUBLIC KEY-----"""

# ============================================================
# OFFLINE CONFIGURATION
# ============================================================

# How many hours the bot can run offline before requiring server validation
DEFAULT_OFFLINE_HOURS = 48

# ============================================================
# CACHE PATHS
# ============================================================

# Cache directory (in user's home folder)
CACHE_DIR = Path.home() / '.discord_trading_bot'
# For India bot, use: Path.home() / '.india_trading_bot'

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
        bundle_dir = sys._MEIPASS
        cert_path = os.path.join(bundle_dir, 'certifi', 'cacert.pem')
        if os.path.exists(cert_path):
            return cert_path
    
    return None  # Use system default
```

---

## File 2: `crypto.py` - Machine ID & RSA Verification

```python
"""
License Crypto - RSA verification, machine ID generation, and integrity checks
"""

import json
import base64
import hashlib
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Tuple

from .license_types import RSA_PUBLIC_KEY_PEM


def get_machine_id() -> str:
    """
    Generate a unique machine identifier based on hardware.
    This ID is used to bind licenses to specific computers.
    
    Returns:
        16-character hex string unique to this machine
    """
    system = platform.system()
    
    try:
        if system == 'Windows':
            # Use BIOS UUID on Windows (most reliable)
            result = subprocess.run(
                ['wmic', 'csproduct', 'get', 'uuid'],
                capture_output=True, text=True, timeout=10
            )
            uuid_lines = [line.strip() for line in result.stdout.split('\n') 
                          if line.strip() and line.strip() != 'UUID']
            if uuid_lines:
                machine_uuid = uuid_lines[0]
            else:
                machine_uuid = platform.node()
                
        elif system == 'Linux':
            # Use /etc/machine-id on Linux
            try:
                with open('/etc/machine-id', 'r') as f:
                    machine_uuid = f.read().strip()
            except:
                machine_uuid = platform.node()
                
        elif system == 'Darwin':  # macOS
            # Use IOPlatformUUID on macOS
            try:
                result = subprocess.run(
                    ['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.split('\n'):
                    if 'IOPlatformUUID' in line:
                        machine_uuid = line.split('"')[-2]
                        break
                else:
                    machine_uuid = platform.node()
            except:
                machine_uuid = platform.node()
        else:
            machine_uuid = platform.node()
            
    except Exception:
        machine_uuid = platform.node()
    
    # Create deterministic hash from machine info
    raw = f"{machine_uuid}_{platform.system()}_{platform.machine()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_machine_info() -> dict:
    """Get machine info as dict for server API."""
    return {
        "hostname": platform.node(),
        "os": platform.system(),
        "arch": platform.machine()
    }


def get_machine_info_string() -> str:
    """Get human-readable machine info as string (legacy format)."""
    return f"{platform.node()} ({platform.system()} {platform.machine()})"


def verify_signed_token(token_str: str, expected_machine_id: str) -> Tuple[bool, dict]:
    """
    Verify RSA-signed token from server.
    This ensures the cache cannot be tampered with - only the server can sign valid tokens.
    
    Token format: "base64(payload).base64(signature)"
    
    Args:
        token_str: The signed token from server
        expected_machine_id: The current machine's ID to verify against
        
    Returns:
        Tuple of (is_valid, payload_dict)
    """
    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        
        # Load RSA public key (embedded in application)
        public_key = serialization.load_pem_public_key(
            RSA_PUBLIC_KEY_PEM.encode(),
            backend=default_backend()
        )
        
        # Split token into payload and signature
        parts = token_str.split('.')
        if len(parts) != 2:
            print("[LICENSE] Invalid token format - expected payload.signature")
            return False, {}
        
        payload_b64, signature_b64 = parts
        
        # Decode payload and signature (handle missing padding)
        try:
            payload_bytes = base64.urlsafe_b64decode(payload_b64 + '==')
            signature_bytes = base64.urlsafe_b64decode(signature_b64 + '==')
        except Exception as decode_err:
            print(f"[LICENSE] Token decode error: {decode_err}")
            return False, {}
        
        # ============================================================
        # CRITICAL: Verify signature using RSA public key
        # This is the core security check - without private key,
        # attackers CANNOT create valid signatures
        # ============================================================
        try:
            public_key.verify(
                signature_bytes,
                payload_bytes,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception as verify_err:
            print(f"[LICENSE] Signature verification failed: {verify_err}")
            print("[LICENSE] Token may have been tampered with!")
            return False, {}
        
        # Parse payload JSON
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        # Verify machine ID matches (prevents copying to another PC)
        if payload.get('machine_id') != expected_machine_id:
            print(f"[LICENSE] Machine ID mismatch - token for different machine")
            return False, {}
        
        # Check offline grace expiration
        if 'offline_grace_expires' in payload:
            grace_expires = datetime.fromisoformat(payload['offline_grace_expires'])
            if datetime.now() > grace_expires:
                print("[LICENSE] Offline grace period expired - server validation required")
                return False, {}
        
        print("[LICENSE] Token signature verified successfully")
        return True, payload
        
    except ImportError:
        print("[LICENSE] cryptography library not available - cannot verify token")
        return False, {}
    except Exception as e:
        print(f"[LICENSE] Token verification error: {e}")
        return False, {}


def compute_integrity_hash() -> str:
    """
    Compute hash of critical license-related code files.
    Used to detect if code has been tampered with.
    """
    critical_files = [
        'src/license/__init__.py',
        'src/license/license_types.py',
        'src/license/crypto.py',
        'src/license/cache.py',
        'src/license/client.py',
    ]
    
    hasher = hashlib.sha256()
    
    for filepath in critical_files:
        try:
            full_path = Path(filepath)
            if full_path.exists():
                with open(full_path, 'rb') as f:
                    hasher.update(f.read())
        except Exception:
            pass
    
    return hasher.hexdigest()[:32]


def verify_integrity(expected_hash: str = None) -> Tuple[bool, str]:
    """
    Verify that critical code files haven't been tampered with.
    
    Returns:
        Tuple of (is_valid, current_hash)
    """
    current_hash = compute_integrity_hash()
    
    if expected_hash:
        is_valid = current_hash == expected_hash
        return is_valid, current_hash
    
    return True, current_hash
```

---

## File 3: `cache.py` - Offline Caching & Grace Period

```python
"""
License Cache - Offline caching and grace period management
"""

import json
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
                'signed_token': result.get('signed_token')  # RSA-signed by server
            }
            
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            print(f"[LICENSE] Cache saved: {self.cache_file}")
            
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
        """
        Check if within offline grace period using signed token or time-based fallback.
        
        Priority:
        1. Signed token (most secure, server-verified)
        2. Time-based grace period (fallback)
        
        Returns:
            Tuple of (is_valid, message)
        """
        try:
            if grace_hours is None:
                grace_hours = DEFAULT_OFFLINE_HOURS
            
            # Check for signed token (preferred, most secure)
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
                # No server grace time - use time-based fallback
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
        """Fallback time-based grace period check (less secure)."""
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
        
        return False, "No verified cache - server connection required"
    
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
                
            except Exception:
                pass
        
        return False, ""
```

---

## File 4: `client.py` - HTTP Client & Validation Logic

```python
"""
License Client - HTTP client for License Server validation
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .license_types import (
    LICENSE_SERVER_URLS,
    DEFAULT_OFFLINE_HOURS,
    CACHE_DIR,
    CACHE_FILE,
    get_ssl_cert_path
)
from .crypto import get_machine_id, get_machine_info, get_machine_info_string
from .cache import LicenseCache


class LicenseClient:
    """Client for validating licenses against license server."""
    
    def __init__(self, license_server_url: str = None, server_urls: List[str] = None):
        """
        Initialize license client with fallback URL support.
        
        Args:
            license_server_url: Single URL (legacy compatibility)
            server_urls: List of URLs to try in order (primary first)
        """
        # Support both single URL and list of URLs
        if server_urls:
            self.server_urls = server_urls
        elif license_server_url:
            self.server_urls = [license_server_url]
        else:
            self.server_urls = LICENSE_SERVER_URLS.copy()
        
        # Current active server (last successful one)
        self.active_server_url = self.server_urls[0]
        self.server_url = self.active_server_url  # Backwards compatibility
        
        self.machine_id = get_machine_id()
        self.cache_dir = CACHE_DIR
        self.cache_file = CACHE_FILE
        self.cache_dir.mkdir(exist_ok=True)
        
        # Initialize cache manager
        self._cache = LicenseCache(self.machine_id, self.cache_dir, self.cache_file)
    
    def _make_request_single(self, url: str, method: str = 'POST', data: dict = None) -> Tuple[Dict, bool]:
        """Make HTTP request to a single server URL."""
        
        ssl_cert = get_ssl_cert_path()
        
        # Try requests library first (better SSL handling on Windows)
        try:
            import requests
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            headers = {'Content-Type': 'application/json', 'User-Agent': 'TradingBot/1.0'}
            verify = ssl_cert if ssl_cert else True
            
            try:
                if method == 'POST':
                    response = requests.post(url, json=data, headers=headers, timeout=30, verify=verify)
                else:
                    response = requests.get(url, headers=headers, timeout=30, verify=verify)
            except requests.exceptions.SSLError:
                # Retry without SSL verification
                if method == 'POST':
                    response = requests.post(url, json=data, headers=headers, timeout=30, verify=False)
                else:
                    response = requests.get(url, headers=headers, timeout=30, verify=False)
            
            if response.status_code == 200:
                return response.json(), True
            else:
                try:
                    return response.json(), False
                except:
                    return {'success': False, 'is_valid': False, 'error': f"HTTP {response.status_code}"}, False
                    
        except ImportError:
            pass  # Fall through to urllib
        except Exception as e:
            if 'ConnectionError' in str(type(e)):
                return {'success': False, 'is_valid': False, 'error': 'Connection failed', 'offline': True}, False
            pass
        
        # Fallback to urllib (built-in, always available)
        import urllib.request
        import urllib.error
        import ssl
        
        try:
            if data:
                json_data = json.dumps(data).encode('utf-8')
                req = urllib.request.Request(url, data=json_data, method=method)
                req.add_header('Content-Type', 'application/json')
            else:
                req = urllib.request.Request(url, method=method)
            
            req.add_header('User-Agent', 'TradingBot/1.0')
            
            try:
                context = ssl.create_default_context()
                if ssl_cert:
                    context.load_verify_locations(ssl_cert)
                with urllib.request.urlopen(req, timeout=30, context=context) as response:
                    return json.loads(response.read().decode('utf-8')), True
            except ssl.SSLError:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=30, context=context) as response:
                    return json.loads(response.read().decode('utf-8')), True
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            try:
                return json.loads(error_body), False
            except:
                return {'success': False, 'is_valid': False, 'error': f"HTTP {e.code}"}, False
        except urllib.error.URLError:
            return {'success': False, 'is_valid': False, 'error': 'Connection failed', 'offline': True}, False
        except Exception as e:
            return {'success': False, 'is_valid': False, 'error': str(e), 'offline': True}, False
    
    def _make_request(self, endpoint: str, method: str = 'POST', data: dict = None) -> Dict:
        """Make HTTP request with automatic fallback to backup servers."""
        last_error = None
        
        for server_url in self.server_urls:
            url = f"{server_url}/api/v1/license/{endpoint}"
            
            result, success = self._make_request_single(url, method, data)
            
            if success:
                self.active_server_url = server_url
                self.server_url = server_url
                return result
            
            # Only fallback on connection failures, not API rejections
            if not result.get('offline', False):
                return result
            
            last_error = result.get('error', 'Unknown error')
        
        return {'success': False, 'is_valid': False, 'error': f"All servers unreachable: {last_error}", 'offline': True}
    
    def request_trial(self) -> Dict:
        """Request a trial license from the server."""
        print(f"[LICENSE] Requesting trial license...")
        
        result = self._make_request('trial', 'POST', {
            'machine_id': self.machine_id,
            'machine_info': get_machine_info()
        })
        
        # Retry with legacy format if needed
        if result.get('error') == 'Invalid request':
            result = self._make_request('trial', 'POST', {
                'machine_id': self.machine_id,
                'machine_info': get_machine_info_string()
            })
        
        if result.get('success'):
            print(f"[LICENSE] Trial activated: {result['license_key']}")
            self._cache.save(result['license_key'], {
                'is_valid': True,
                'expires': result.get('expires_at'),
                'days_remaining': result.get('days_remaining'),
                'license_type': 'trial',
                'signed_token': result.get('signed_token')
            })
        else:
            print(f"[LICENSE] Trial request failed: {result.get('error')}")
        
        return result
    
    def activate_license(self, license_key: str) -> Dict:
        """Activate a license key on this machine."""
        print(f"[LICENSE] Activating license...")
        
        result = self._make_request('activate', 'POST', {
            'license_key': license_key,
            'machine_id': self.machine_id,
            'machine_info': get_machine_info()
        })
        
        # Retry with legacy format if needed
        if result.get('error') == 'Invalid request':
            result = self._make_request('activate', 'POST', {
                'license_key': license_key,
                'machine_id': self.machine_id,
                'machine_info': get_machine_info_string()
            })
        
        if result.get('success'):
            print(f"[LICENSE] License activated successfully")
            self._cache.save(license_key, result)
        else:
            print(f"[LICENSE] Activation failed: {result.get('error')}")
        
        return result
    
    def validate_license(self, license_key: str, max_offline_hours: int = None) -> Tuple[bool, dict]:
        """
        Validate a license against the server.
        
        Returns:
            Tuple of (is_valid, result_dict)
        """
        if max_offline_hours is None:
            max_offline_hours = DEFAULT_OFFLINE_HOURS
        
        # Send validation request to server
        result = self._make_request('validate', 'POST', {
            'license_key': license_key,
            'machine_id': self.machine_id
        })
        
        # ============================================================
        # OFFLINE HANDLING: Use cached validation if server unreachable
        # ============================================================
        if result.get('offline'):
            print("[LICENSE] Server unreachable - checking offline grace period...")
            cache = self._cache.load()
            
            if cache and cache.get('license_key') == license_key and cache.get('machine_id') == self.machine_id:
                is_grace_valid, message = self._cache.check_grace_period(cache, max_offline_hours)
                
                if is_grace_valid:
                    cached_result = cache.get('result', {})
                    cached_result['offline_mode'] = True
                    cached_result['grace_message'] = message
                    print(f"[LICENSE] {message}")
                    return True, cached_result
                else:
                    print(f"[LICENSE] {message}")
                    return False, {'error': message, 'offline': True}
            else:
                return False, {'error': 'No cached validation available', 'offline': True}
        
        # ============================================================
        # ONLINE: Server responded
        # ============================================================
        if result.get('is_valid'):
            if not result.get('signed_token'):
                print("[LICENSE] Warning: Server response missing signed token")
            self._cache.save(license_key, result)
            return True, result
        else:
            error_msg = result.get('error', 'Unknown validation error')
            print(f"[LICENSE] Server returned error: {error_msg}")
            
            # ============================================================
            # SECURITY: Hard rejections must NOT fall back to cache
            # These are explicit server rejections, not connectivity issues
            # ============================================================
            hard_rejection_keywords = ['revoked', 'expired', 'invalid', 'suspended', 
                                        'terminated', 'banned', 'not found']
            is_hard_rejection = any(keyword in error_msg.lower() for keyword in hard_rejection_keywords)
            
            if is_hard_rejection:
                print(f"[LICENSE] Hard rejection from server - clearing cache")
                self._cache.clear()  # SECURITY: Prevent using cached data
                return False, result
            
            # Only use cache for ambiguous errors (rate limits, etc)
            cache = self._cache.load()
            if cache and cache.get('license_key') == license_key and cache.get('machine_id') == self.machine_id:
                is_grace_valid, message = self._cache.check_grace_period(cache, max_offline_hours)
                if is_grace_valid:
                    print(f"[LICENSE] Using cached validation - {message}")
                    cached_result = cache.get('result', {})
                    cached_result['cached_mode'] = True
                    cached_result['grace_message'] = message
                    return True, cached_result
            
            return False, result
    
    def validate_cached(self, license_key: str, max_offline_hours: int = None) -> Tuple[bool, dict]:
        """Check if there's a valid cached validation (no server call)."""
        if max_offline_hours is None:
            max_offline_hours = DEFAULT_OFFLINE_HOURS
        
        cache = self._cache.load()
        
        if cache and cache.get('license_key') == license_key and cache.get('machine_id') == self.machine_id:
            is_grace_valid, message = self._cache.check_grace_period(cache, max_offline_hours)
            if is_grace_valid:
                cached_result = cache.get('result', {})
                cached_result['cached_mode'] = True
                cached_result['grace_message'] = message
                return True, cached_result
        
        return False, {}
    
    def clear_cache(self) -> bool:
        """Clear the local license cache file."""
        return self._cache.clear()
    
    def deactivate_license(self, license_key: str) -> Dict:
        """Deactivate license from this machine."""
        result = self._make_request('deactivate', 'POST', {
            'license_key': license_key,
            'machine_id': self.machine_id
        })
        
        if result.get('success'):
            self._cache.clear()
        
        return result


# Convenience function
def validate_with_server(license_key: str) -> Tuple[bool, Dict]:
    """Convenience function to validate license with server."""
    client = LicenseClient()
    return client.validate_license(license_key)
```

---

## File 5: `heartbeat.py` - Background Re-validation

```python
"""
License Heartbeat - Background license re-validation during operation
"""

import threading
import time
from datetime import datetime
from typing import Dict, Optional, Callable

from .client import LicenseClient


class LicenseHeartbeat:
    """
    Background license heartbeat - periodically re-validates license.
    Detects revocations that happen AFTER the bot starts.
    """
    
    def __init__(self, license_key: str, interval_minutes: int = 30, revoke_callback: Callable = None):
        self.license_key = license_key
        self.interval_minutes = interval_minutes
        self.client = LicenseClient()
        self._stop_event = None
        self._thread = None
        self._last_check = None
        self._consecutive_failures = 0
        self._max_failures = 3  # Stop bot after 3 consecutive failures
        self._revoke_callback = revoke_callback
    
    def start(self):
        """Start the heartbeat background thread."""
        if self._thread and self._thread.is_alive():
            return
        
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True, name="LicenseHeartbeat")
        self._thread.start()
        print(f"[LICENSE] Heartbeat started (every {self.interval_minutes} min)")
    
    def stop(self):
        """Stop the heartbeat thread."""
        if self._stop_event:
            self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
    
    def _heartbeat_loop(self):
        """Background loop for license re-validation."""
        interval_seconds = self.interval_minutes * 60
        
        while not self._stop_event.is_set():
            # Wait for interval
            self._stop_event.wait(interval_seconds)
            
            if self._stop_event.is_set():
                break
            
            try:
                is_valid, result = self.client.validate_license(self.license_key)
                self._last_check = datetime.now()
                
                if is_valid:
                    self._consecutive_failures = 0
                    days = result.get('days_remaining', '?')
                    print(f"[LICENSE] Heartbeat OK - {days} days remaining")
                else:
                    self._consecutive_failures += 1
                    print(f"[LICENSE] Heartbeat FAIL ({self._consecutive_failures}/{self._max_failures})")
                    
                    if self._consecutive_failures >= self._max_failures:
                        print("[LICENSE] Too many heartbeat failures - license revoked")
                        self._on_license_revoked()
                        
            except Exception as e:
                print(f"[LICENSE] Heartbeat error: {e}")
    
    def _on_license_revoked(self):
        """Called when license is detected as revoked during operation."""
        print("[LICENSE] ========================================")
        print("[LICENSE]      LICENSE REVOKED OR EXPIRED        ")
        print("[LICENSE] ========================================")
        print("[LICENSE] Trading functionality will be disabled.")
        print("[LICENSE] Please renew your license to continue.")
        
        if self._revoke_callback:
            try:
                self._revoke_callback()
            except Exception as e:
                print(f"[LICENSE] Revoke callback error: {e}")
    
    def get_status(self) -> Dict:
        """Get heartbeat status."""
        return {
            'running': self._thread and self._thread.is_alive(),
            'last_check': self._last_check.isoformat() if self._last_check else None,
            'failures': self._consecutive_failures,
            'max_failures': self._max_failures
        }


# Global heartbeat instance
_heartbeat_instance: Optional[LicenseHeartbeat] = None


def start_license_heartbeat(license_key: str, interval_minutes: int = 30, revoke_callback: Callable = None) -> LicenseHeartbeat:
    """Start the global license heartbeat."""
    global _heartbeat_instance
    
    if _heartbeat_instance:
        _heartbeat_instance.stop()
    
    _heartbeat_instance = LicenseHeartbeat(license_key, interval_minutes, revoke_callback)
    _heartbeat_instance.start()
    return _heartbeat_instance


def stop_license_heartbeat():
    """Stop the global license heartbeat."""
    global _heartbeat_instance
    
    if _heartbeat_instance:
        _heartbeat_instance.stop()
        _heartbeat_instance = None
```

---

## File 6: `network_monitor.py` - Connectivity Detection

```python
"""
Network Connectivity Monitor - Triggers license validation when internet returns
"""

import socket
import threading
import time
import os
from datetime import datetime
from typing import Callable, Optional

from .client import LicenseClient


class NetworkMonitor:
    """
    Monitors network connectivity and triggers license validation when internet returns.
    Prevents bypass by staying offline indefinitely.
    """
    
    def __init__(
        self, 
        license_key: str, 
        check_interval: int = 10,
        shutdown_callback: Optional[Callable] = None,
        show_message_callback: Optional[Callable[[str, str], None]] = None
    ):
        """
        Initialize network monitor.
        
        Args:
            license_key: The license key to validate
            check_interval: Seconds between network checks (default 10)
            shutdown_callback: Function to call when shutting down bot
            show_message_callback: Function to show popup message (title, message)
        """
        self.license_key = license_key
        self.check_interval = check_interval
        self.shutdown_callback = shutdown_callback
        self.show_message_callback = show_message_callback
        
        self.client = LicenseClient()
        self._stop_event = threading.Event()
        self._thread = None
        self._was_offline = False
        self._last_online_check = None
        self._validated_since_online = False
        self._initial_check_done = False
    
    def start(self):
        """Start the network monitoring thread."""
        if self._thread and self._thread.is_alive():
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="NetworkMonitor")
        self._thread.start()
        print("[LICENSE] Network monitor started")
    
    def stop(self):
        """Stop the network monitor thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        print("[LICENSE] Network monitor stopped")
    
    def _check_internet(self) -> bool:
        """Check if internet is available by testing DNS resolution."""
        test_hosts = [
            ("8.8.8.8", 53),      # Google DNS
            ("1.1.1.1", 53),      # Cloudflare DNS
        ]
        
        for host, port in test_hosts:
            try:
                socket.setdefaulttimeout(3)
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((host, port))
                sock.close()
                return True
            except (socket.error, socket.timeout, OSError):
                continue
        
        return False
    
    def _monitor_loop(self):
        """Main monitoring loop - detects connectivity changes."""
        print("[LICENSE] Network monitor loop started")
        
        while not self._stop_event.is_set():
            try:
                is_online = self._check_internet()
                
                if is_online:
                    # Just came back online OR initial check
                    if self._was_offline or not self._initial_check_done:
                        if self._was_offline:
                            print("[LICENSE] Internet connectivity RESTORED - validating license...")
                        self._on_connectivity_restored()
                    
                    self._was_offline = False
                    self._last_online_check = datetime.now()
                    self._initial_check_done = True
                else:
                    if not self._was_offline:
                        print("[LICENSE] Internet connectivity LOST - monitoring for restore...")
                    self._was_offline = True
                    self._validated_since_online = False
                    self._initial_check_done = True
                
            except Exception as e:
                print(f"[LICENSE] Network monitor error: {e}")
            
            self._stop_event.wait(self.check_interval)
        
        print("[LICENSE] Network monitor loop ended")
    
    def _on_connectivity_restored(self):
        """Called when internet connectivity is restored."""
        if self._validated_since_online:
            return
        
        self._validated_since_online = True
        
        try:
            print("[LICENSE] Performing post-reconnect license validation...")
            is_valid, result = self.client.validate_license(self.license_key)
            
            if is_valid:
                print("[LICENSE] License validation successful after reconnect")
                days_remaining = result.get('days_remaining', 'Unknown')
                print(f"[LICENSE] License valid - {days_remaining} days remaining")
            else:
                error = result.get('error', 'License validation failed')
                print(f"[LICENSE] License validation FAILED: {error}")
                self._handle_license_failure(error)
                
        except Exception as e:
            print(f"[LICENSE] Post-reconnect validation error: {e}")
    
    def _handle_license_failure(self, error_message: str):
        """Handle license validation failure - show message and shutdown."""
        print("[LICENSE] =========================================================")
        print("[LICENSE]              LICENSE EXPIRED OR REVOKED                  ")
        print("[LICENSE] =========================================================")
        print(f"[LICENSE] Error: {error_message}")
        print("[LICENSE] The bot will now shut down.")
        
        title = "License Expired"
        message = f"Your license has expired or been revoked.\n\nReason: {error_message}\n\nThe application will now close."
        
        if self.show_message_callback:
            try:
                self.show_message_callback(title, message)
            except Exception as e:
                print(f"[LICENSE] Could not show popup: {e}")
        
        if self.shutdown_callback:
            try:
                self.shutdown_callback()
            except Exception as e:
                print(f"[LICENSE] Shutdown callback error: {e}")
        
        print("[LICENSE] Forcing application exit...")
        time.sleep(2)
        os._exit(1)


# Global network monitor instance
_network_monitor: Optional[NetworkMonitor] = None


def start_network_monitor(
    license_key: str,
    check_interval: int = 10,
    shutdown_callback: Optional[Callable] = None,
    show_message_callback: Optional[Callable[[str, str], None]] = None
) -> NetworkMonitor:
    """Start the global network monitor."""
    global _network_monitor
    
    if _network_monitor:
        _network_monitor.stop()
    
    _network_monitor = NetworkMonitor(
        license_key=license_key,
        check_interval=check_interval,
        shutdown_callback=shutdown_callback,
        show_message_callback=show_message_callback
    )
    _network_monitor.start()
    return _network_monitor


def stop_network_monitor():
    """Stop the global network monitor."""
    global _network_monitor
    
    if _network_monitor:
        _network_monitor.stop()
        _network_monitor = None
```

---

## File 7: `__init__.py` - Package Exports

```python
"""
License Package - Server-side license validation with offline support

This package provides:
- License validation against your license server
- RSA signature verification for tamper-proof caching
- Offline grace period support (48 hours default)
- Machine ID binding (license locked to hardware)
- Background heartbeat validation
- Network connectivity monitoring

Usage:
    from src.license import LicenseClient, get_machine_id
    
    client = LicenseClient()
    is_valid, result = client.validate_license("XX-XXXX-XXXX-XXXX")
"""

# Re-export all public APIs
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
)

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
]
```

---

## Server API Endpoints

The client expects these endpoints on your license server:

| Endpoint | Method | Request Body | Response |
|----------|--------|--------------|----------|
| `/api/v1/license/validate` | POST | `{license_key, machine_id}` | `{is_valid, expires, days_remaining, signed_token}` |
| `/api/v1/license/activate` | POST | `{license_key, machine_id, machine_info}` | `{success, expires_at, days_remaining, signed_token}` |
| `/api/v1/license/trial` | POST | `{machine_id, machine_info}` | `{success, license_key, expires_at, days_remaining, signed_token}` |
| `/api/v1/license/deactivate` | POST | `{license_key, machine_id}` | `{success}` |
| `/api/v1/license/status` | GET | - | `{status: "online"}` |

---

## Token Format

Server-signed tokens use this format:

```
base64url(payload).base64url(signature)
```

### Payload Structure
```json
{
    "license_key": "BT-XXXX-XXXX-XXXX",
    "machine_id": "a1b2c3d4e5f67890",
    "expires": "2026-12-31T23:59:59",
    "license_type": "subscription",
    "days_remaining": 365,
    "offline_grace_expires": "2026-01-19T10:30:00"
}
```

### Signature
- Algorithm: RSA with PKCS1v15 padding
- Hash: SHA-256
- Key size: 2048 bits
- Only server has private key

---

## Cache File Format

Stored at: `~/.discord_trading_bot/license_cache.json`

```json
{
    "license_key": "BT-XXXX-XXXX-XXXX",
    "machine_id": "a1b2c3d4e5f67890",
    "last_validated": "2026-01-17T10:30:00",
    "result": {
        "is_valid": true,
        "expires": "2026-12-31",
        "days_remaining": 365,
        "license_type": "subscription"
    },
    "expires_at": "2026-12-31",
    "days_remaining": 365,
    "signed_token": "eyJsaWNlbnNlX2tleS..."
}
```

---

## Usage Examples

### Basic Validation
```python
from src.license import LicenseClient

client = LicenseClient()
is_valid, result = client.validate_license("BT-XXXX-XXXX-XXXX")

if is_valid:
    print(f"License valid - {result['days_remaining']} days remaining")
else:
    print(f"License invalid: {result.get('error')}")
```

### Start Background Monitoring
```python
from src.license import start_license_heartbeat, start_network_monitor

license_key = "BT-XXXX-XXXX-XXXX"

# Heartbeat every 30 minutes
start_license_heartbeat(license_key, interval_minutes=30)

# Monitor network connectivity
start_network_monitor(license_key, check_interval=10)
```

### Request Trial
```python
from src.license import LicenseClient

client = LicenseClient()
result = client.request_trial()

if result.get('success'):
    print(f"Trial activated: {result['license_key']}")
    print(f"Expires in: {result['days_remaining']} days")
```

---

## Required Dependencies

Add to `requirements.txt`:

```
cryptography>=41.0.0
requests>=2.28.0
```

The `cryptography` library is required for RSA signature verification.
