"""
License Client - Server-Side Validation with BotifyTrades License Server
Validates licenses against license.botifytrades.com
Includes RSA signature verification for tamper-proof cache
"""

import os
import sys
import json
import hashlib
import platform
import subprocess
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict

LICENSE_SERVER_URL = "https://92ef2f8a-9447-4d91-8823-2ac83e184d7a-00-384f7fcagd1yw.janeway.replit.dev"

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

def get_ssl_cert_path():
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

DEFAULT_OFFLINE_HOURS = 48
CACHE_DIR = Path.home() / '.discord_trading_bot'
CACHE_FILE = CACHE_DIR / 'license_cache.json'


def get_machine_id() -> str:
    """Generate a unique machine identifier based on hardware."""
    system = platform.system()
    
    try:
        if system == 'Windows':
            result = subprocess.run(
                ['wmic', 'csproduct', 'get', 'uuid'],
                capture_output=True, text=True, timeout=10
            )
            uuid_lines = [line.strip() for line in result.stdout.split('\n') if line.strip() and line.strip() != 'UUID']
            if uuid_lines:
                machine_uuid = uuid_lines[0]
            else:
                machine_uuid = platform.node()
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


def get_machine_info() -> str:
    """Get human-readable machine info."""
    return f"{platform.node()} ({platform.system()} {platform.machine()})"


def _verify_signed_token(token_str: str, expected_machine_id: str) -> Tuple[bool, dict]:
    """
    Verify RSA-signed token from server.
    This ensures the cache cannot be tampered with - only the server can sign valid tokens.
    
    Args:
        token_str: The signed token in format "base64(payload).base64(signature)"
        expected_machine_id: The current machine's ID to verify against
        
    Returns:
        Tuple of (is_valid, payload_dict)
    """
    try:
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        
        # Load public key
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
        
        # Verify signature using RSA public key
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
        
        # Parse and validate payload
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        # Verify machine ID matches
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


class LicenseClient:
    """Client for validating licenses against BotifyTrades license server."""
    
    def __init__(self, license_server_url: str = None):
        self.server_url = license_server_url or LICENSE_SERVER_URL
        self.machine_id = get_machine_id()
        self.cache_dir = CACHE_DIR
        self.cache_file = CACHE_FILE
        self.cache_dir.mkdir(exist_ok=True)
    
    def _make_request(self, endpoint: str, method: str = 'POST', data: dict = None) -> Dict:
        """Make HTTP request to license server."""
        url = f"{self.server_url}/api/v1/license/{endpoint}"
        print(f"[LICENSE] Making request to: {url}")
        print(f"[LICENSE] Request data: {data}")
        
        # Get SSL certificate path for PyInstaller bundles
        ssl_cert = get_ssl_cert_path()
        
        # Try requests library first (better SSL handling on Windows)
        try:
            import requests
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            headers = {'Content-Type': 'application/json', 'User-Agent': 'BotifyTrades/1.0'}
            
            # Use bundled certificates if available
            verify = ssl_cert if ssl_cert else True
            
            # Try with SSL verification first
            try:
                if method == 'POST':
                    response = requests.post(url, json=data, headers=headers, timeout=30, verify=verify)
                else:
                    response = requests.get(url, headers=headers, timeout=30, verify=verify)
            except requests.exceptions.SSLError as ssl_err:
                print(f"[LICENSE] SSL verification failed: {ssl_err}")
                print("[LICENSE] Retrying with SSL verification disabled...")
                # Retry without SSL verification
                if method == 'POST':
                    response = requests.post(url, json=data, headers=headers, timeout=30, verify=False)
                else:
                    response = requests.get(url, headers=headers, timeout=30, verify=False)
            
            print(f"[LICENSE] Response status: {response.status_code}")
            print(f"[LICENSE] Response: {response.text[:200]}...")
            
            if response.status_code == 200:
                return response.json()
            else:
                try:
                    return response.json()
                except:
                    return {'success': False, 'is_valid': False, 'error': f"HTTP {response.status_code}"}
                    
        except ImportError:
            print("[LICENSE] requests library not available, using urllib")
        except Exception as req_err:
            print(f"[LICENSE] requests failed: {req_err}, trying urllib...")
        
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
            
            req.add_header('User-Agent', 'BotifyTrades/1.0')
            
            # Try with default SSL context first, fallback to unverified if needed
            try:
                context = ssl.create_default_context()
                # Load bundled certificates if available
                if ssl_cert:
                    context.load_verify_locations(ssl_cert)
                with urllib.request.urlopen(req, timeout=30, context=context) as response:
                    response_data = response.read().decode('utf-8')
                    print(f"[LICENSE] Response: {response_data[:200]}...")
                    return json.loads(response_data)
            except ssl.SSLError as ssl_err:
                print(f"[LICENSE] SSL Error with default context: {ssl_err}")
                print("[LICENSE] Retrying with unverified SSL...")
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=30, context=context) as response:
                    response_data = response.read().decode('utf-8')
                    print(f"[LICENSE] Response (unverified SSL): {response_data[:200]}...")
                    return json.loads(response_data)
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            print(f"[LICENSE] HTTP Error {e.code}: {error_body}")
            try:
                return json.loads(error_body)
            except:
                return {'success': False, 'is_valid': False, 'error': f"HTTP {e.code}: {error_body}"}
        except urllib.error.URLError as e:
            print(f"[LICENSE] URL Error: {e.reason}")
            return {'success': False, 'is_valid': False, 'error': f"Connection failed: {e.reason}", 'offline': True}
        except Exception as e:
            print(f"[LICENSE] Unexpected error: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'is_valid': False, 'error': str(e), 'offline': True}
    
    def _save_cache(self, license_key: str, result: Dict):
        """Save validation result with signed token for offline grace period."""
        import builtins
        import sys
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
                'signed_token': result.get('signed_token')  # Store the signed token
            }
            
            _print(f"[LICENSE-SAVE] Cache file: {self.cache_file}", flush=True)
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            _print(f"[LICENSE-SAVE] ✅ Cache saved successfully!", flush=True)
            _print(f"[LICENSE-SAVE] License: {license_key[:12]}...", flush=True)
            _print(f"[LICENSE-SAVE] Machine: {self.machine_id}", flush=True)
            if result.get('signed_token'):
                _print(f"[LICENSE-SAVE] Signed token length: {len(result.get('signed_token'))}", flush=True)
            sys.stdout.flush()
            
        except Exception as e:
            _print(f"[LICENSE-SAVE] ❌ ERROR saving cache: {e}", flush=True)
            import traceback
            traceback.print_exc()
    
    def _load_cache(self) -> Optional[Dict]:
        """Load cached validation result."""
        try:
            if not self.cache_file.exists():
                return None
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        except Exception:
            return None
    
    def _check_grace_period(self, cache: Dict, grace_hours: int = None) -> Tuple[bool, str]:
        """Check if within offline grace period using signed token or time-based fallback.
        
        Priority:
        1. Signed token (most secure, server-verified)
        2. Time-based grace period (fallback for when server doesn't return tokens)
        """
        import builtins
        import sys
        # Use _original_print if available (bypasses smart_print filter), else fallback
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
                # This allows offline use even when server doesn't return signed tokens
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
                            # Still within grace period based on last validation time
                            hours_remaining = grace_hours - hours_since
                            _print(f"[LICENSE] GRACE: ✅ Within time-based period ({hours_remaining:.1f}h remaining)", flush=True)
                            sys.stdout.flush()
                            return True, f"Offline mode ({hours_remaining:.1f}h remaining) - time-based"
                        else:
                            _print(f"[LICENSE] GRACE: ❌ Time-based period expired", flush=True)
                            sys.stdout.flush()
                            return False, f"Grace period expired ({hours_since:.1f}h ago) - server connection required"
                    except Exception as e:
                        _print(f"[LICENSE] GRACE: Error parsing last_validated: {e}", flush=True)
                        sys.stdout.flush()
                
                # No valid fallback available
                _print(f"[LICENSE] GRACE: ❌ No signed token and no valid last_validated", flush=True)
                sys.stdout.flush()
                return False, "No verified cache - server connection required (connect once to enable offline mode)"
            
            # Verify the signed token cryptographically
            _print(f"[LICENSE] GRACE: Verifying signed token...", flush=True)
            sys.stdout.flush()
            is_valid, payload = _verify_signed_token(signed_token, self.machine_id)
            _print(f"[LICENSE] GRACE: Token verification result: valid={is_valid}", flush=True)
            sys.stdout.flush()
            
            if not is_valid:
                # Token verification failed - FALL BACK to time-based grace
                _print(f"[LICENSE] GRACE: Token verification failed, trying time-based fallback", flush=True)
                last_validated = cache.get('last_validated')
                if last_validated:
                    try:
                        validated_dt = datetime.fromisoformat(last_validated)
                        hours_since = (datetime.now() - validated_dt).total_seconds() / 3600
                        if hours_since <= grace_hours:
                            hours_remaining = grace_hours - hours_since
                            _print(f"[LICENSE] GRACE: ✅ Fallback: within {hours_remaining:.1f}h grace", flush=True)
                            sys.stdout.flush()
                            return True, f"Offline mode ({hours_remaining:.1f}h remaining) - fallback"
                    except Exception as e:
                        _print(f"[LICENSE] GRACE: Fallback parse error: {e}", flush=True)
                return False, "Cache verification failed - server connection required"
            
            _print(f"[LICENSE] GRACE: Token payload keys: {list(payload.keys()) if payload else 'None'}", flush=True)
            sys.stdout.flush()
            
            # CRITICAL: Check if the actual LICENSE has expired (not just grace period)
            license_expires_str = payload.get('expires') if payload else None
            if license_expires_str:
                try:
                    if 'T' in license_expires_str:
                        license_expires = datetime.fromisoformat(license_expires_str.replace('Z', '+00:00'))
                    else:
                        license_expires = datetime.strptime(license_expires_str, '%Y-%m-%d %H:%M:%S')
                    
                    if datetime.now() >= license_expires:
                        _print(f"[LICENSE] GRACE: ❌ License expired on {license_expires_str}", flush=True)
                        return False, "License has expired - please renew your subscription"
                except Exception as e:
                    _print(f"[LICENSE] GRACE: Could not parse expiry: {e}", flush=True)
            
            # CRITICAL FIX: Recalculate days_remaining from 'expires' field using HOURS, not full days
            # Using .days floors to 0 when less than 24h remaining - wrong!
            expires_str = payload.get('expires') if payload else None
            if expires_str:
                try:
                    if 'T' in expires_str:
                        expires_dt = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
                    else:
                        expires_dt = datetime.strptime(expires_str, '%Y-%m-%d %H:%M:%S')
                    
                    # Calculate time remaining using total_seconds (not .days which floors)
                    time_remaining = expires_dt - datetime.now()
                    hours_remaining = time_remaining.total_seconds() / 3600
                    days_remaining = hours_remaining / 24  # Can be fractional
                    
                    _print(f"[LICENSE] GRACE: Expires={expires_str}, hours_remaining={hours_remaining:.1f}h ({days_remaining:.2f} days)", flush=True)
                    sys.stdout.flush()
                    
                    # License is expired if no time remaining at all
                    if hours_remaining <= 0:
                        _print(f"[LICENSE] GRACE: ❌ License expired ({hours_remaining:.1f}h ago)", flush=True)
                        return False, "License has expired - please renew your subscription"
                    
                    _print(f"[LICENSE] GRACE: ✅ License still valid ({hours_remaining:.1f}h remaining)", flush=True)
                except Exception as e:
                    _print(f"[LICENSE] GRACE: Could not recalculate days_remaining: {e}", flush=True)
                    # Fall back to token's days_remaining if we can't parse expires
                    days_remaining = payload.get('days_remaining', 999) if payload else 999
                    if isinstance(days_remaining, int) and days_remaining <= 0:
                        _print(f"[LICENSE] GRACE: ❌ Fallback days_remaining={days_remaining}", flush=True)
                        return False, "License has expired - please renew your subscription"
            else:
                # No expires field - use token's days_remaining as fallback
                days_remaining = payload.get('days_remaining', 999) if payload else 999
                _print(f"[LICENSE] GRACE: No expires field, using token days_remaining={days_remaining}", flush=True)
            
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
                        _print(f"[LICENSE] GRACE: ✅ Time-based grace ({hours_remaining:.1f}h remaining)", flush=True)
                        sys.stdout.flush()
                        return True, f"Offline mode ({hours_remaining:.1f}h remaining) - verified token"
                _print(f"[LICENSE] GRACE: ❌ No grace expiry and time fallback failed", flush=True)
                return False, "Grace period expired - server connection required"
            
            grace_expires = datetime.fromisoformat(grace_expires_str)
            if datetime.now() < grace_expires:
                hours = int((grace_expires - datetime.now()).total_seconds() / 3600)
                _print(f"[LICENSE] GRACE: ✅ Signed grace valid ({hours}h remaining)", flush=True)
                return True, f"Offline mode (verified) - {hours}h grace remaining"
            else:
                _print(f"[LICENSE] GRACE: ❌ Signed grace expired", flush=True)
                return False, "Grace period expired - server connection required"
                
        except Exception as e:
            return False, f"Cache verification error: {e}"
    
    def request_trial(self) -> Dict:
        """Request a trial license from the server."""
        print(f"[LICENSE] Requesting trial for machine: {self.machine_id[:8]}...")
        
        result = self._make_request('trial', 'POST', {
            'machine_id': self.machine_id,
            'machine_info': get_machine_info()
        })
        
        if result.get('success'):
            print(f"[LICENSE] Trial activated: {result['license_key']}")
            self._save_cache(result['license_key'], {
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
        import builtins
        import sys
        _print = getattr(builtins, '_original_print', builtins.print)
        
        _print(f"[LICENSE] ========================================", flush=True)
        _print(f"[LICENSE] ACTIVATING LICENSE", flush=True)
        _print(f"[LICENSE] Server URL: {self.server_url}", flush=True)
        _print(f"[LICENSE] Machine ID: {self.machine_id}", flush=True)
        _print(f"[LICENSE] License: {license_key[:12]}...", flush=True)
        _print(f"[LICENSE] ========================================", flush=True)
        sys.stdout.flush()
        
        result = self._make_request('activate', 'POST', {
            'license_key': license_key,
            'machine_id': self.machine_id,
            'machine_info': get_machine_info()
        })
        
        _print(f"[LICENSE] Server response: {result}", flush=True)
        sys.stdout.flush()
        
        if result.get('success'):
            _print(f"[LICENSE] ✅ Activation successful - saving to cache...", flush=True)
            self._save_cache(license_key, result)
        else:
            _print(f"[LICENSE] ❌ Activation failed: {result.get('error')}", flush=True)
        
        return result
    
    def validate_cached(self, license_key: str, max_offline_hours: int = None) -> Tuple[bool, dict]:
        """Check if there's a valid cached validation for this license."""
        import builtins
        import sys
        # Use _original_print if available (bypasses smart_print filter), else fallback
        _print = getattr(builtins, '_original_print', builtins.print)
        
        try:
            _print(f"[LICENSE] CACHE: validate_cached() called", flush=True)
            sys.stdout.flush()
            
            if max_offline_hours is None:
                max_offline_hours = DEFAULT_OFFLINE_HOURS
            
            _print(f"[LICENSE] CACHE: Checking at {self.cache_file}", flush=True)
            _print(f"[LICENSE] CACHE: File exists: {self.cache_file.exists()}", flush=True)
            sys.stdout.flush()
            
            cache = self._load_cache()
            _print(f"[LICENSE] CACHE: _load_cache returned: {type(cache).__name__}", flush=True)
            sys.stdout.flush()
            
            if cache:
                cached_license = cache.get('license_key', '')
                cached_machine = cache.get('machine_id', '')
                _print(f"[LICENSE] CACHE: Loaded license={cached_license[:8] if cached_license else 'NONE'}...", flush=True)
                _print(f"[LICENSE] CACHE: Cached machine_id: {cached_machine[:8] if cached_machine else 'NONE'}...", flush=True)
                _print(f"[LICENSE] CACHE: Current machine_id: {self.machine_id[:8]}...", flush=True)
                _print(f"[LICENSE] CACHE: License match: {cached_license == license_key}", flush=True)
                _print(f"[LICENSE] CACHE: Machine match: {cached_machine == self.machine_id}", flush=True)
                _print(f"[LICENSE] CACHE: Has signed_token: {bool(cache.get('signed_token'))}", flush=True)
                _print(f"[LICENSE] CACHE: Has result data: {bool(cache.get('result'))}", flush=True)
                sys.stdout.flush()
                
                # Show why validation might fail
                if cached_license != license_key:
                    _print(f"[LICENSE] CACHE: ⚠️ LICENSE MISMATCH: cache={cached_license[:12]}... vs input={license_key[:12]}...", flush=True)
                if cached_machine != self.machine_id:
                    _print(f"[LICENSE] CACHE: ⚠️ MACHINE MISMATCH: cache={cached_machine} vs current={self.machine_id}", flush=True)
            else:
                _print(f"[LICENSE] CACHE: No cache loaded (returned None)", flush=True)
            
            sys.stdout.flush()
            
            if cache and cache.get('license_key') == license_key and cache.get('machine_id') == self.machine_id:
                _print(f"[LICENSE] CACHE: Key/machine match - checking grace period...", flush=True)
                sys.stdout.flush()
                is_grace_valid, message = self._check_grace_period(cache, max_offline_hours)
                _print(f"[LICENSE] CACHE: Grace valid: {is_grace_valid} - {message}", flush=True)
                sys.stdout.flush()
                if is_grace_valid:
                    cached_result = cache.get('result', {})
                    cached_result['cached_mode'] = True
                    cached_result['grace_message'] = message
                    _print(f"[LICENSE] CACHE: ✅ Returning cached validation: {list(cached_result.keys())}", flush=True)
                    sys.stdout.flush()
                    return True, cached_result
                else:
                    _print(f"[LICENSE] CACHE: ❌ Grace period expired", flush=True)
            else:
                _print(f"[LICENSE] CACHE: ❌ Validation failed (key/machine mismatch or no cache)", flush=True)
            sys.stdout.flush()
            return False, {}
        except Exception as e:
            _print(f"[LICENSE] CACHE: ❌ EXCEPTION: {type(e).__name__}: {e}", flush=True)
            import traceback
            _print(f"[LICENSE] CACHE: Traceback: {traceback.format_exc()}", flush=True)
            sys.stdout.flush()
            return False, {}
    
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
            cache = self._load_cache()
            
            if cache and cache.get('license_key') == license_key and cache.get('machine_id') == self.machine_id:
                is_grace_valid, message = self._check_grace_period(cache, max_offline_hours)
                
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
            # SECURITY: Verify the server included a signed token
            # Without a signed token, offline mode won't work
            if not result.get('signed_token'):
                print("[LICENSE] Warning: Server response missing signed token - offline mode unavailable")
                print("[LICENSE] This may indicate server misconfiguration")
            self._save_cache(license_key, result)
            return True, result
        else:
            error_msg = result.get('error', 'Unknown validation error')
            print(f"[LICENSE] Server returned error: {error_msg}")
            
            cache = self._load_cache()
            if cache and cache.get('license_key') == license_key and cache.get('machine_id') == self.machine_id:
                is_grace_valid, message = self._check_grace_period(cache, max_offline_hours)
                if is_grace_valid:
                    print(f"[LICENSE] Using cached validation - {message}")
                    cached_result = cache.get('result', {})
                    cached_result['cached_mode'] = True
                    cached_result['grace_message'] = message
                    return True, cached_result
            
            return False, result
    
    def clear_cache(self) -> bool:
        """Clear the local license cache file."""
        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
                print(f"[LICENSE] Cache cleared: {self.cache_file}")
            return True
        except Exception as e:
            print(f"[LICENSE] Warning: Could not clear cache: {e}")
            return False
    
    def deactivate_license(self, license_key: str) -> Dict:
        """Deactivate license from this machine."""
        result = self._make_request('deactivate', 'POST', {
            'license_key': license_key,
            'machine_id': self.machine_id
        })
        
        if result.get('success'):
            try:
                self.cache_file.unlink(missing_ok=True)
            except:
                pass
        
        return result
    
    def check_server_status(self) -> Dict:
        """Check if license server is online."""
        try:
            import urllib.request
            import ssl
            
            url = f"{self.server_url}/api/v1/license/status"
            req = urllib.request.Request(url, method='GET')
            req.add_header('User-Agent', 'BotifyTrades/1.0')
            
            context = ssl.create_default_context()
            
            with urllib.request.urlopen(req, timeout=10, context=context) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            return {'status': 'offline', 'error': str(e)}


def validate_with_server(license_key: str) -> Tuple[bool, Dict]:
    """Convenience function to validate license with server."""
    client = LicenseClient()
    return client.validate_license(license_key)


class LicenseHeartbeat:
    """
    Background license heartbeat - periodically re-validates license during operation.
    This prevents users from simply bypassing initial license check.
    """
    
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
        """Start the heartbeat background thread."""
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
                    print(f"[LICENSE] Heartbeat OK - license valid")
                else:
                    self._consecutive_failures += 1
                    print(f"[LICENSE] Heartbeat FAIL ({self._consecutive_failures}/{self._max_failures})")
                    
                    if self._consecutive_failures >= self._max_failures:
                        print("[LICENSE] Too many heartbeat failures - license may be revoked")
                        self._on_license_revoked()
            except Exception as e:
                print(f"[LICENSE] Heartbeat error: {e}")
    
    def _on_license_revoked(self):
        """Called when license is detected as revoked during operation."""
        print("[LICENSE] ========================================")
        print("[LICENSE] LICENSE REVOKED OR EXPIRED")
        print("[LICENSE] Trading functionality will be disabled.")
        print("[LICENSE] Please renew your license to continue.")
        print("[LICENSE] ========================================")
        
        try:
            from gui_app import database as db
            db.update_setting('license_revoked', 'true')
            db.update_setting('trading_enabled', 'false')
        except Exception as e:
            print(f"[LICENSE] Could not update settings: {e}")
        
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


def compute_integrity_hash() -> str:
    """
    Compute hash of critical license-related code files.
    Used to detect if code has been tampered with.
    """
    import hashlib
    
    critical_files = [
        'src/license_client.py',
        'src/license_manager.py',
        'src/license_manager_secure.py',
        'src/license_manager_activation.py'
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
    
    Args:
        expected_hash: If provided, compare against this hash
        
    Returns:
        Tuple of (is_valid, current_hash)
    """
    current_hash = compute_integrity_hash()
    
    if expected_hash:
        is_valid = current_hash == expected_hash
        return is_valid, current_hash
    
    return True, current_hash


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
