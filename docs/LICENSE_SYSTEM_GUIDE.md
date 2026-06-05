# License System Guide - Complete Implementation

## Overview

This guide shows how to implement the same license validation system used by BotifyTrades in your India trading bot. The system connects to the same license server (`license-forge--uk15286.replit.app`).

---

## Replit Agent Prompt

```
I need to implement a license validation system that:

1. **Server Validation**
   - Connects to existing license server at license-forge--uk15286.replit.app
   - API endpoints: /api/v1/license/validate, activate, deactivate, trial
   - Machine ID binding (unique hardware fingerprint)
   - RSA signature verification for tamper-proof caching

2. **Offline Support**
   - 48-hour grace period when server unreachable
   - Signed tokens for secure offline validation
   - Time-based fallback when tokens unavailable

3. **Background Monitoring**
   - Network monitor: detects connectivity restore, re-validates
   - Heartbeat: periodic re-validation (every 30 min)
   - Auto-shutdown on license revocation

4. **Security Features**
   - Machine ID generated from hardware (BIOS UUID, MAC, etc.)
   - RSA public key embedded for token verification
   - Integrity hash of license code files
   - Cache cleared on hard rejections (expired, revoked)

5. **Integration Points**
   - Environment variable: LICENSE_KEY
   - Database setting: license_key
   - Setup wizard for first-time activation
   - GUI display of license status

Create these files in src/license/:
- __init__.py (exports)
- license_types.py (constants, URLs, keys)
- crypto.py (machine ID, RSA verification)
- cache.py (offline caching)
- client.py (HTTP client)
- heartbeat.py (background validation)
- network_monitor.py (connectivity detection)
```

---

## Project Structure

```
src/
└── license/
    ├── __init__.py          # Package exports
    ├── license_types.py     # Constants, URLs, RSA key
    ├── crypto.py            # Machine ID, RSA verification
    ├── cache.py             # Offline caching
    ├── client.py            # HTTP client for server API
    ├── heartbeat.py         # Background re-validation
    └── network_monitor.py   # Connectivity detection
```

---

## Complete Code Files

### 1. `src/license/license_types.py`

```python
"""
License Types - Constants and configuration for India Bot License System
"""
import os
import sys
from pathlib import Path
from typing import Optional

# License server URLs - SAME SERVER as BotifyTrades
LICENSE_SERVER_URL_PRIMARY = "https://license-forge--uk15286.replit.app"
LICENSE_SERVER_URL_LEGACY_1 = "https://discord-trader-botify-trades-releases--uk15286.replit.app"

LICENSE_SERVER_URL = LICENSE_SERVER_URL_PRIMARY

LICENSE_SERVER_URLS = [
    LICENSE_SERVER_URL_PRIMARY,
    LICENSE_SERVER_URL_LEGACY_1,
]

# RSA Public Key for verifying server-signed tokens
# IMPORTANT: This is the SAME key used by BotifyTrades
# The private key is only on the license server
RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA9xawPYXSBBAYFbA1FHGa
yh3w9kdrulymcC8eGayVlLNaObI0yx8TUaftxTpjHi5g+Bg/RLnHw+tNdxiktJv2
KYdiJO19CNx1B7yw6zGPU67vxEQC6xINVoUjaEmC2T7ePcTpXEwX0ioDYPn6MMOh
DqZlBzy+sUU/3qr7KBXFMlCMrNsAO5nhj4UIhYavwGx5tlyO4NdtW7UIjZJDweFd
+o6H+/DJo9khP4MyyTJMYEfJBgperSd4LkE4PIOs6vp6EGtT7a38AcYJyLdXVeTF
PtTq1yAH5XHPKkDBo2xzaGWC1zJdHNd9Fg2FET4wnoDjH0H7E8vSwcaS1yA9W2b3
nQIDAQAB
-----END PUBLIC KEY-----"""

# Offline grace period (hours)
DEFAULT_OFFLINE_HOURS = 48

# Cache directory - change for India bot
CACHE_DIR = Path.home() / '.india_trading_bot'
CACHE_FILE = CACHE_DIR / 'license_cache.json'


def get_ssl_cert_path() -> Optional[str]:
    """Get SSL certificate path, handling PyInstaller bundles."""
    try:
        import certifi
        return certifi.where()
    except ImportError:
        pass
    
    if getattr(sys, 'frozen', False):
        bundle_dir = sys._MEIPASS
        cert_path = os.path.join(bundle_dir, 'certifi', 'cacert.pem')
        if os.path.exists(cert_path):
            return cert_path
    
    return None
```

### 2. `src/license/crypto.py`

```python
"""
License Crypto - Machine ID generation and RSA verification
"""
import json
import base64
import hashlib
import platform
import subprocess
from datetime import datetime
from typing import Tuple

from .license_types import RSA_PUBLIC_KEY_PEM


def get_machine_id() -> str:
    """Generate unique machine identifier from hardware."""
    system = platform.system()
    
    try:
        if system == 'Windows':
            result = subprocess.run(
                ['wmic', 'csproduct', 'get', 'uuid'],
                capture_output=True, text=True, timeout=10
            )
            uuid_lines = [line.strip() for line in result.stdout.split('\n') 
                         if line.strip() and line.strip() != 'UUID']
            machine_uuid = uuid_lines[0] if uuid_lines else platform.node()
            
        elif system == 'Linux':
            try:
                with open('/etc/machine-id', 'r') as f:
                    machine_uuid = f.read().strip()
            except:
                machine_uuid = platform.node()
                
        elif system == 'Darwin':  # macOS
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
    """Get machine info as string (legacy format)."""
    return f"{platform.node()} ({platform.system()} {platform.machine()})"


def verify_signed_token(token_str: str, expected_machine_id: str) -> Tuple[bool, dict]:
    """
    Verify RSA-signed token from server.
    Ensures cache cannot be tampered with - only server can sign valid tokens.
    """
    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        
        public_key = serialization.load_pem_public_key(
            RSA_PUBLIC_KEY_PEM.encode(),
            backend=default_backend()
        )
        
        parts = token_str.split('.')
        if len(parts) != 2:
            return False, {}
        
        payload_b64, signature_b64 = parts
        
        try:
            payload_bytes = base64.urlsafe_b64decode(payload_b64 + '==')
            signature_bytes = base64.urlsafe_b64decode(signature_b64 + '==')
        except Exception:
            return False, {}
        
        try:
            public_key.verify(
                signature_bytes,
                payload_bytes,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
        except Exception:
            print("[LICENSE] Signature verification failed - token may be tampered!")
            return False, {}
        
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        if payload.get('machine_id') != expected_machine_id:
            print("[LICENSE] Machine ID mismatch - token for different machine")
            return False, {}
        
        if 'offline_grace_expires' in payload:
            grace_expires = datetime.fromisoformat(payload['offline_grace_expires'])
            if datetime.now() > grace_expires:
                print("[LICENSE] Offline grace period expired")
                return False, {}
        
        return True, payload
        
    except ImportError:
        print("[LICENSE] cryptography library not available")
        return False, {}
    except Exception as e:
        print(f"[LICENSE] Token verification error: {e}")
        return False, {}
```

### 3. `src/license/cache.py`

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
        """Save validation result with signed token."""
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
        """Clear the license cache file."""
        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
            return True
        except Exception:
            return False
    
    def check_grace_period(self, cache: Dict, grace_hours: int = None) -> Tuple[bool, str]:
        """Check if within offline grace period."""
        try:
            if grace_hours is None:
                grace_hours = DEFAULT_OFFLINE_HOURS
            
            signed_token = cache.get('signed_token')
            
            if not signed_token:
                return self._check_time_based_grace(cache, grace_hours)
            
            is_valid, payload = verify_signed_token(signed_token, self.machine_id)
            
            if not is_valid:
                return self._check_time_based_grace(cache, grace_hours)
            
            # Check license expiration
            license_expires_str = payload.get('expires')
            if license_expires_str:
                try:
                    if 'T' in license_expires_str:
                        license_expires = datetime.fromisoformat(license_expires_str.replace('Z', '+00:00'))
                    else:
                        license_expires = datetime.strptime(license_expires_str, '%Y-%m-%d %H:%M:%S')
                    
                    if datetime.now() >= license_expires:
                        return False, "License has expired - please renew"
                except:
                    pass
            
            grace_expires_str = payload.get('offline_grace_expires')
            
            if not grace_expires_str:
                last_validated = cache.get('last_validated')
                if last_validated:
                    validated_dt = datetime.fromisoformat(last_validated)
                    hours_since = (datetime.now() - validated_dt).total_seconds() / 3600
                    if hours_since <= grace_hours:
                        hours_remaining = grace_hours - hours_since
                        return True, f"Offline mode ({hours_remaining:.1f}h remaining)"
                return False, "Grace period expired - server connection required"
            
            grace_expires = datetime.fromisoformat(grace_expires_str)
            if datetime.now() < grace_expires:
                hours = int((grace_expires - datetime.now()).total_seconds() / 3600)
                return True, f"Offline mode (verified) - {hours}h remaining"
            else:
                return False, "Grace period expired"
                
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
                    return True, f"Offline mode ({hours_remaining:.1f}h remaining)"
                else:
                    return False, f"Grace period expired ({hours_since:.1f}h ago)"
            except:
                pass
        
        return False, "No cache - server connection required"
```

### 4. `src/license/client.py`

```python
"""
License Client - HTTP client for license server validation
"""
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .license_types import LICENSE_SERVER_URLS, CACHE_DIR, CACHE_FILE, DEFAULT_OFFLINE_HOURS, get_ssl_cert_path
from .crypto import get_machine_id, get_machine_info, get_machine_info_string
from .cache import LicenseCache


class LicenseClient:
    """Client for validating licenses against the license server."""
    
    def __init__(self, server_urls: List[str] = None):
        self.server_urls = server_urls or LICENSE_SERVER_URLS.copy()
        self.active_server_url = self.server_urls[0]
        self.machine_id = get_machine_id()
        self.cache_dir = CACHE_DIR
        self.cache_file = CACHE_FILE
        self.cache_dir.mkdir(exist_ok=True)
        self._cache = LicenseCache(self.machine_id, self.cache_dir, self.cache_file)
    
    def _make_request_single(self, url: str, method: str = 'POST', data: dict = None) -> Tuple[Dict, bool]:
        """Make HTTP request to a single server URL."""
        ssl_cert = get_ssl_cert_path()
        
        try:
            import requests
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            headers = {'Content-Type': 'application/json', 'User-Agent': 'IndiaTradingBot/1.0'}
            verify = ssl_cert if ssl_cert else True
            
            try:
                if method == 'POST':
                    response = requests.post(url, json=data, headers=headers, timeout=30, verify=verify)
                else:
                    response = requests.get(url, headers=headers, timeout=30, verify=verify)
            except requests.exceptions.SSLError:
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
                    return {'success': False, 'error': f"HTTP {response.status_code}"}, False
                    
        except ImportError:
            pass
        except Exception as e:
            return {'success': False, 'error': str(e), 'offline': True}, False
        
        # Fallback to urllib
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
            
            req.add_header('User-Agent', 'IndiaTradingBot/1.0')
            
            context = ssl.create_default_context()
            if ssl_cert:
                context.load_verify_locations(ssl_cert)
            
            with urllib.request.urlopen(req, timeout=30, context=context) as response:
                return json.loads(response.read().decode('utf-8')), True
                
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode('utf-8')), False
            except:
                return {'success': False, 'error': f"HTTP {e.code}"}, False
        except Exception as e:
            return {'success': False, 'error': str(e), 'offline': True}, False
    
    def _make_request(self, endpoint: str, method: str = 'POST', data: dict = None) -> Dict:
        """Make request with automatic fallback to backup servers."""
        last_error = None
        
        for server_url in self.server_urls:
            url = f"{server_url}/api/v1/license/{endpoint}"
            result, success = self._make_request_single(url, method, data)
            
            if success:
                self.active_server_url = server_url
                return result
            
            if not result.get('offline', False):
                return result
            
            last_error = result.get('error', 'Unknown error')
        
        return {'success': False, 'error': f"All servers unreachable: {last_error}", 'offline': True}
    
    def activate_license(self, license_key: str) -> Dict:
        """Activate a license key on this machine."""
        print(f"[LICENSE] Activating license...")
        
        result = self._make_request('activate', 'POST', {
            'license_key': license_key,
            'machine_id': self.machine_id,
            'machine_info': get_machine_info()
        })
        
        if result.get('error') == 'Invalid request':
            result = self._make_request('activate', 'POST', {
                'license_key': license_key,
                'machine_id': self.machine_id,
                'machine_info': get_machine_info_string()
            })
        
        if result.get('success'):
            self._cache.save(license_key, result)
        else:
            print(f"[LICENSE] Activation failed: {result.get('error')}")
        
        return result
    
    def validate_license(self, license_key: str, max_offline_hours: int = None) -> Tuple[bool, dict]:
        """Validate a license against the server."""
        if max_offline_hours is None:
            max_offline_hours = DEFAULT_OFFLINE_HOURS
        
        result = self._make_request('validate', 'POST', {
            'license_key': license_key,
            'machine_id': self.machine_id
        })
        
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
        
        if result.get('is_valid'):
            if not result.get('signed_token'):
                print("[LICENSE] Warning: Server response missing signed token")
            self._cache.save(license_key, result)
            return True, result
        else:
            error_msg = result.get('error', 'Unknown error')
            print(f"[LICENSE] Server error: {error_msg}")
            
            hard_rejection_keywords = ['revoked', 'expired', 'invalid', 'suspended', 'banned', 'not found']
            is_hard_rejection = any(kw in error_msg.lower() for kw in hard_rejection_keywords)
            
            if is_hard_rejection:
                self.clear_cache()
                return False, result
            
            cache = self._cache.load()
            if cache and cache.get('license_key') == license_key and cache.get('machine_id') == self.machine_id:
                is_grace_valid, message = self._cache.check_grace_period(cache, max_offline_hours)
                if is_grace_valid:
                    cached_result = cache.get('result', {})
                    cached_result['cached_mode'] = True
                    return True, cached_result
            
            return False, result
    
    def clear_cache(self) -> bool:
        """Clear the local license cache."""
        return self._cache.clear()
    
    def deactivate_license(self, license_key: str) -> Dict:
        """Deactivate license from this machine."""
        result = self._make_request('deactivate', 'POST', {
            'license_key': license_key,
            'machine_id': self.machine_id
        })
        
        if result.get('success'):
            self.clear_cache()
        
        return result


def validate_with_server(license_key: str) -> Tuple[bool, Dict]:
    """Convenience function to validate license."""
    client = LicenseClient()
    return client.validate_license(license_key)
```

### 5. `src/license/heartbeat.py`

```python
"""
License Heartbeat - Background license re-validation
"""
from datetime import datetime
from typing import Dict, Optional

from .client import LicenseClient


class LicenseHeartbeat:
    """Background heartbeat - periodically re-validates license."""
    
    def __init__(self, license_key: str, interval_minutes: int = 30, revoke_callback=None):
        self.license_key = license_key
        self.interval_minutes = interval_minutes
        self.client = LicenseClient()
        self._stop_event = None
        self._thread = None
        self._last_check = None
        self._consecutive_failures = 0
        self._max_failures = 3
        self._revoke_callback = revoke_callback
    
    def start(self):
        """Start the heartbeat thread."""
        import threading
        
        if self._thread and self._thread.is_alive():
            return
        
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
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
        import time
        
        interval_seconds = self.interval_minutes * 60
        
        while not self._stop_event.is_set():
            self._stop_event.wait(interval_seconds)
            
            if self._stop_event.is_set():
                break
            
            try:
                is_valid, result = self.client.validate_license(self.license_key)
                self._last_check = datetime.now()
                
                if is_valid:
                    self._consecutive_failures = 0
                    print("[LICENSE] Heartbeat OK")
                else:
                    self._consecutive_failures += 1
                    print(f"[LICENSE] Heartbeat FAIL ({self._consecutive_failures}/{self._max_failures})")
                    
                    if self._consecutive_failures >= self._max_failures:
                        self._on_license_revoked()
            except Exception as e:
                print(f"[LICENSE] Heartbeat error: {e}")
    
    def _on_license_revoked(self):
        """Called when license is detected as revoked."""
        print("[LICENSE] LICENSE REVOKED - shutting down")
        
        if self._revoke_callback:
            try:
                self._revoke_callback()
            except:
                pass


_heartbeat_instance: Optional[LicenseHeartbeat] = None


def start_license_heartbeat(license_key: str, interval_minutes: int = 30, revoke_callback=None) -> LicenseHeartbeat:
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

### 6. `src/license/network_monitor.py`

```python
"""
Network Monitor - Triggers license validation when internet returns
"""
import socket
import threading
import time
import os
from datetime import datetime
from typing import Callable, Optional

from .client import LicenseClient


class NetworkMonitor:
    """Monitors connectivity and triggers license validation on reconnect."""
    
    def __init__(self, license_key: str, check_interval: int = 10, shutdown_callback=None):
        self.license_key = license_key
        self.check_interval = check_interval
        self.shutdown_callback = shutdown_callback
        self.client = LicenseClient()
        self._stop_event = threading.Event()
        self._thread = None
        self._was_offline = False
        self._validated_since_online = False
    
    def start(self):
        """Start the network monitoring thread."""
        if self._thread and self._thread.is_alive():
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        print("[LICENSE] Network monitor started")
    
    def stop(self):
        """Stop the network monitor."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
    
    def _check_internet(self) -> bool:
        """Check if internet is available."""
        test_hosts = [("8.8.8.8", 53), ("1.1.1.1", 53)]
        
        for host, port in test_hosts:
            try:
                socket.setdefaulttimeout(3)
                socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
                return True
            except:
                continue
        return False
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            try:
                is_online = self._check_internet()
                
                if is_online:
                    if self._was_offline and not self._validated_since_online:
                        print("[LICENSE] Internet restored - validating license...")
                        self._on_connectivity_restored()
                    self._was_offline = False
                else:
                    if not self._was_offline:
                        print("[LICENSE] Internet connectivity LOST")
                    self._was_offline = True
                    self._validated_since_online = False
                    
            except Exception as e:
                print(f"[LICENSE] Network monitor error: {e}")
            
            self._stop_event.wait(self.check_interval)
    
    def _on_connectivity_restored(self):
        """Called when internet connectivity is restored."""
        if self._validated_since_online:
            return
        
        self._validated_since_online = True
        
        try:
            is_valid, result = self.client.validate_license(self.license_key)
            
            if is_valid:
                days = result.get('days_remaining', 'Unknown')
                print(f"[LICENSE] License valid - {days} days remaining")
            else:
                error = result.get('error', 'Validation failed')
                print(f"[LICENSE] License FAILED: {error}")
                self._handle_license_failure(error)
        except Exception as e:
            print(f"[LICENSE] Validation error: {e}")
    
    def _handle_license_failure(self, error_message: str):
        """Handle license validation failure."""
        print("[LICENSE] ========================================")
        print("[LICENSE]        LICENSE EXPIRED OR REVOKED       ")
        print("[LICENSE] ========================================")
        print(f"[LICENSE] Error: {error_message}")
        
        if self.shutdown_callback:
            try:
                self.shutdown_callback()
            except:
                pass
        
        time.sleep(2)
        os._exit(1)


_network_monitor: Optional[NetworkMonitor] = None


def start_network_monitor(license_key: str, check_interval: int = 10, shutdown_callback=None) -> NetworkMonitor:
    """Start the global network monitor."""
    global _network_monitor
    
    if _network_monitor:
        _network_monitor.stop()
    
    _network_monitor = NetworkMonitor(license_key, check_interval, shutdown_callback)
    _network_monitor.start()
    return _network_monitor


def stop_network_monitor():
    """Stop the global network monitor."""
    global _network_monitor
    
    if _network_monitor:
        _network_monitor.stop()
        _network_monitor = None
```

### 7. `src/license/__init__.py`

```python
"""
India Trading Bot License Package
Connects to same server as BotifyTrades
"""

from .license_types import (
    LICENSE_SERVER_URL,
    LICENSE_SERVER_URLS,
    RSA_PUBLIC_KEY_PEM,
    DEFAULT_OFFLINE_HOURS,
    CACHE_DIR,
    CACHE_FILE,
)

from .crypto import (
    get_machine_id,
    get_machine_info,
    verify_signed_token,
)

from .cache import LicenseCache
from .client import LicenseClient, validate_with_server
from .heartbeat import LicenseHeartbeat, start_license_heartbeat, stop_license_heartbeat
from .network_monitor import NetworkMonitor, start_network_monitor, stop_network_monitor

__all__ = [
    'LICENSE_SERVER_URL', 'LICENSE_SERVER_URLS', 'RSA_PUBLIC_KEY_PEM',
    'DEFAULT_OFFLINE_HOURS', 'CACHE_DIR', 'CACHE_FILE',
    'get_machine_id', 'get_machine_info', 'verify_signed_token',
    'LicenseCache', 'LicenseClient', 'validate_with_server',
    'LicenseHeartbeat', 'start_license_heartbeat', 'stop_license_heartbeat',
    'NetworkMonitor', 'start_network_monitor', 'stop_network_monitor',
]
```

---

## Usage in Main Bot

```python
import os
from src.license import LicenseClient, start_network_monitor, start_license_heartbeat

def check_license():
    """Check license on startup."""
    license_key = os.getenv('LICENSE_KEY') or get_license_from_database()
    
    if not license_key:
        print("[LICENSE] No license key found - please enter in setup wizard")
        return False
    
    client = LicenseClient()
    is_valid, result = client.validate_license(license_key)
    
    if is_valid:
        days = result.get('days_remaining', 'Unknown')
        print(f"[LICENSE] ✅ Valid - {days} days remaining")
        
        # Start background monitors
        start_network_monitor(license_key)
        start_license_heartbeat(license_key)
        
        return True
    else:
        error = result.get('error', 'Unknown error')
        print(f"[LICENSE] ❌ Invalid: {error}")
        return False

# In main.py
if __name__ == '__main__':
    if not check_license():
        print("License validation failed. Exiting.")
        exit(1)
    
    # Start your bot...
```

---

## Key Points

1. **Same Server** - Uses `license-forge--uk15286.replit.app` (same as BotifyTrades)
2. **Same RSA Key** - Tokens signed by server are verified with same public key
3. **Machine Binding** - License bound to specific hardware (UUID/machine-id)
4. **Offline Support** - 48-hour grace period with signed token verification
5. **Background Monitoring** - Network monitor + heartbeat prevent bypass attempts
6. **Hard Rejections** - Expired/revoked licenses clear cache, force re-auth
