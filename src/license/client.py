"""
License Client - HTTP client for BotifyTrades License Server validation
"""

import json
import builtins
import sys
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
    """Client for validating licenses against BotifyTrades license server."""
    
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
        """
        Make HTTP request to a single server URL.
        
        Returns:
            Tuple of (response_dict, success_bool)
        """
        
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
        except requests.exceptions.ConnectionError:
            return {'success': False, 'is_valid': False, 'error': 'Connection failed', 'offline': True}, False
        except requests.exceptions.Timeout:
            return {'success': False, 'is_valid': False, 'error': 'Request timeout', 'offline': True}, False
        except Exception:
            pass  # Fall through to urllib
        
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
                    return json.loads(response_data), True
            except ssl.SSLError:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=30, context=context) as response:
                    response_data = response.read().decode('utf-8')
                    return json.loads(response_data), True
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            try:
                return json.loads(error_body), False
            except:
                return {'success': False, 'is_valid': False, 'error': f"HTTP {e.code}: {error_body}"}, False
        except urllib.error.URLError as e:
            return {'success': False, 'is_valid': False, 'error': f"Connection failed: {e.reason}", 'offline': True}, False
        except Exception as e:
            return {'success': False, 'is_valid': False, 'error': str(e), 'offline': True}, False
    
    def _make_request(self, endpoint: str, method: str = 'POST', data: dict = None) -> Dict:
        """
        Make HTTP request with automatic fallback to backup servers.
        
        Tries each server URL in order until one succeeds.
        """
        last_error = None
        
        for i, server_url in enumerate(self.server_urls):
            url = f"{server_url}/api/v1/license/{endpoint}"
            
            result, success = self._make_request_single(url, method, data)
            
            # Check if this was a connection/network failure vs a valid API response
            if success:
                # Update active server for future requests
                self.active_server_url = server_url
                self.server_url = server_url
                return result
            
            # If we got a valid API response (even an error), don't try fallback
            # Only fallback on connection failures
            if not result.get('offline', False):
                # This is a valid API response (license invalid, etc) - don't fallback
                return result
            
            # Connection failed - save error and try next server
            last_error = result.get('error', 'Unknown error')
        
        # All servers failed
        return {'success': False, 'is_valid': False, 'error': f"All servers unreachable: {last_error}", 'offline': True}
    
    def _save_cache(self, license_key: str, result: Dict):
        """Save validation result with signed token for offline grace period."""
        self._cache.save(license_key, result)
    
    def _load_cache(self) -> Optional[Dict]:
        """Load cached validation result."""
        return self._cache.load()
    
    def _check_grace_period(self, cache: Dict, grace_hours: int = None) -> Tuple[bool, str]:
        """Check if within offline grace period."""
        return self._cache.check_grace_period(cache, grace_hours)
    
    def request_trial(self) -> Dict:
        """Request a trial license from the server."""
        print(f"[LICENSE] Requesting trial license...")
        
        # Try dict format first (new servers), fall back to string (legacy servers)
        result = self._make_request('trial', 'POST', {
            'machine_id': self.machine_id,
            'machine_info': get_machine_info()
        })
        
        # If "Invalid request", retry with string format for legacy servers
        if result.get('error') == 'Invalid request':
            result = self._make_request('trial', 'POST', {
                'machine_id': self.machine_id,
                'machine_info': get_machine_info_string()
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
        _print = getattr(builtins, '_original_print', builtins.print)
        
        _print(f"[LICENSE] Activating license...", flush=True)
        sys.stdout.flush()
        
        # Try dict format first (new servers), fall back to string (legacy servers)
        result = self._make_request('activate', 'POST', {
            'license_key': license_key,
            'machine_id': self.machine_id,
            'machine_info': get_machine_info()
        })
        
        # If "Invalid request", retry with string format for legacy servers
        if result.get('error') == 'Invalid request':
            result = self._make_request('activate', 'POST', {
                'license_key': license_key,
                'machine_id': self.machine_id,
                'machine_info': get_machine_info_string()
            })
        
        if result.get('success'):
            self._save_cache(license_key, result)
        else:
            _print(f"[LICENSE] Activation failed: {result.get('error')}", flush=True)
        
        return result
    
    def validate_cached(self, license_key: str, max_offline_hours: int = None) -> Tuple[bool, dict]:
        """Check if there's a valid cached validation for this license."""
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
                
                if cached_license != license_key:
                    _print(f"[LICENSE] CACHE: LICENSE MISMATCH: cache={cached_license[:12]}... vs input={license_key[:12]}...", flush=True)
                if cached_machine != self.machine_id:
                    _print(f"[LICENSE] CACHE: MACHINE MISMATCH: cache={cached_machine} vs current={self.machine_id}", flush=True)
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
                    _print(f"[LICENSE] CACHE: Returning cached validation: {list(cached_result.keys())}", flush=True)
                    sys.stdout.flush()
                    return True, cached_result
                else:
                    _print(f"[LICENSE] CACHE: Grace period expired", flush=True)
            else:
                _print(f"[LICENSE] CACHE: Validation failed (key/machine mismatch or no cache)", flush=True)
            sys.stdout.flush()
            return False, {}
        except Exception as e:
            _print(f"[LICENSE] CACHE: EXCEPTION: {type(e).__name__}: {e}", flush=True)
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
            if not result.get('signed_token'):
                print("[LICENSE] Warning: Server response missing signed token - offline mode unavailable")
                print("[LICENSE] This may indicate server misconfiguration")
            self._save_cache(license_key, result)
            return True, result
        else:
            error_msg = result.get('error', 'Unknown validation error')
            print(f"[LICENSE] Server returned error: {error_msg}")
            
            # SECURITY: Explicit rejections should NOT fall back to cache
            # These are hard rejections from the server, not connectivity issues
            hard_rejection_keywords = ['revoked', 'expired', 'invalid', 'suspended', 'terminated', 'banned', 'not found']
            is_hard_rejection = any(keyword in error_msg.lower() for keyword in hard_rejection_keywords)
            
            if is_hard_rejection:
                print(f"[LICENSE] Hard rejection from server - cache bypass enforced")
                # Clear any existing cache to prevent future use
                self.clear_cache()
                return False, result
            
            # Only use cache for ambiguous errors (rate limits, temporary issues, etc.)
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
        return self._cache.clear()
    
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
