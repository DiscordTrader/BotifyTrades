"""
License Client - Server-Side Validation with RSA Signature Verification
Contacts license server for validation instead of local HMAC
Implements offline grace period with cryptographically signed tokens
Server signs with RSA private key, client verifies with public key (cannot be forged)
"""

import os
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path
import time
from typing import Optional, Tuple
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
import base64

try:
    from license.config import RSA_PUBLIC_KEY_PEM, LICENSE_SERVER_URL, DEFAULT_OFFLINE_HOURS
except ImportError:
    RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1234567890ABCDEFGHIJK
LMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuvwxyz1234567890ABCD
EFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuvwxyz12345678
90ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuvwxyz123
4567890ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuvwxy
z1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890abcdefghijklmnopqrstuv
wxyz1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ==
-----END PUBLIC KEY-----"""
    LICENSE_SERVER_URL = "https://your-license-server.com"
    DEFAULT_OFFLINE_HOURS = 6

try:
    from src.machine_fingerprint import get_machine_id
except ImportError:
    try:
        from machine_fingerprint import get_machine_id
    except ImportError:
        def get_machine_id():
            return "UNKNOWN_MACHINE"


class LicenseClient:
    def __init__(self, license_server_url: str = None):
        """
        Initialize license client
        
        Args:
            license_server_url: URL of license validation server
                               Defaults to LICENSE_SERVER_URL env var
        """
        self.server_url = license_server_url or os.getenv(
            "LICENSE_SERVER_URL",
            LICENSE_SERVER_URL
        )
        self.machine_id = get_machine_id()
        self.cache_dir = Path.home() / '.discord_trading_bot'
        self.cache_file = self.cache_dir / 'license_cache.json'
        self.cache_dir.mkdir(exist_ok=True)
    
    def validate_license(self, license_key: str, max_offline_hours: int = None) -> Tuple[bool, dict]:
        """
        Validate license key via server or cryptographically verified cached token
        
        Args:
            license_key: License key to validate
            max_offline_hours: Maximum hours to allow offline operation
            
        Returns:
            Tuple of (is_valid, license_data)
        """
        if max_offline_hours is None:
            max_offline_hours = DEFAULT_OFFLINE_HOURS
            
        cached_data = self._get_cached_token()
        
        if cached_data:
            token_valid, payload = self._verify_signed_token(cached_data['token'])
            
            if token_valid and payload.get('machine_id') == self.machine_id:
                exp_time = datetime.fromtimestamp(payload['exp'])
                hours_left = (exp_time - datetime.utcnow()).seconds // 3600
                
                if datetime.utcnow() < exp_time:
                    print(f"[LICENSE] Using cryptographically verified cached token ({hours_left}h remaining)")
                    return True, {
                        "customer_id": payload.get('customer_id'),
                        "source": "verified_cache",
                        "expires_at": exp_time.isoformat()
                    }
        
        try:
            return self._validate_with_server(license_key, max_offline_hours)
        except requests.exceptions.RequestException as e:
            print(f"[LICENSE] Server unreachable: {e}")
            
            if cached_data:
                token_valid, payload = self._verify_signed_token(cached_data['token'])
                
                if token_valid and payload.get('machine_id') == self.machine_id:
                    exp_time = datetime.fromtimestamp(payload['exp'])
                    cached_time = datetime.fromisoformat(cached_data['cached_at'])
                    offline_duration = (datetime.utcnow() - cached_time).total_seconds() / 3600
                    
                    if datetime.utcnow() < exp_time and offline_duration <= max_offline_hours:
                        hours_remaining = max_offline_hours - offline_duration
                        print(f"[LICENSE] Offline mode: {hours_remaining:.1f}h grace remaining")
                        return True, {
                            "customer_id": payload.get('customer_id'),
                            "source": "offline_grace",
                            "offline_hours_left": hours_remaining
                        }
                    elif datetime.utcnow() >= exp_time:
                        print("[LICENSE] Cached token expired")
                    else:
                        print(f"[LICENSE] Offline grace period exceeded ({offline_duration:.1f}h > {max_offline_hours}h)")
            
            print("[LICENSE] License validation failed - server unreachable and no valid offline token")
            return False, {"error": "Server unreachable, please connect to internet to validate license"}
    
    def _verify_signed_token(self, token_str: str) -> Tuple[bool, dict]:
        """
        Verify RSA-signed token from server
        Client cannot forge this without server's private key
        """
        try:
            public_key = serialization.load_pem_public_key(
                RSA_PUBLIC_KEY_PEM.encode(),
                backend=default_backend()
            )
            
            parts = token_str.split('.')
            if len(parts) != 2:
                return False, {}
            
            payload_b64, signature_b64 = parts
            
            payload_bytes = base64.urlsafe_b64decode(payload_b64 + '==')
            signature_bytes = base64.urlsafe_b64decode(signature_b64 + '==')
            
            public_key.verify(
                signature_bytes,
                payload_bytes,
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            
            payload = json.loads(payload_bytes.decode('utf-8'))
            return True, payload
            
        except Exception as e:
            print(f"[LICENSE] Token verification failed: {e}")
            return False, {}
    
    def _validate_with_server(self, license_key: str, max_offline_hours: int) -> Tuple[bool, dict]:
        """
        Validate license with server and cache signed token
        """
        response = requests.post(
            f"{self.server_url}/api/validate",
            json={
                "license_key": license_key,
                "machine_id": self.machine_id
            },
            timeout=10
        )
        
        if response.status_code != 200:
            return False, {"error": f"Server returned {response.status_code}"}
        
        data = response.json()
        
        if not data.get('valid'):
            return False, {"error": data.get('error', 'Invalid license')}
        
        if data.get('token'):
            self._cache_token(data['token'])
        
        return True, {
            "customer_id": data.get('customer_id'),
            "source": "server",
            "expires": data.get('expires')
        }
    
    def _get_cached_token(self) -> Optional[dict]:
        """Get cached token if exists"""
        try:
            if self.cache_file.exists():
                return json.loads(self.cache_file.read_text(encoding='utf-8'))
        except Exception:
            pass
        return None
    
    def _cache_token(self, token: str):
        """Cache signed token from server"""
        try:
            cache_data = {
                "token": token,
                "cached_at": datetime.utcnow().isoformat()
            }
            self.cache_file.write_text(json.dumps(cache_data), encoding='utf-8')
        except Exception as e:
            print(f"[LICENSE] Failed to cache token: {e}")
