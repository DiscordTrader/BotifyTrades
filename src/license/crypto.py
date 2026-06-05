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
                with open('/etc/machine-id', 'r', encoding='utf-8') as f:
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
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


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
        
        # CRITICAL: Check if the license itself has expired
        if 'expires' in payload:
            try:
                expires_str = payload['expires']
                if 'T' in expires_str:
                    license_expires = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
                else:
                    license_expires = datetime.strptime(expires_str, '%Y-%m-%d %H:%M:%S')
                
                # Handle timezone-aware datetime comparison
                now = datetime.now()
                if license_expires.tzinfo is not None:
                    from datetime import timezone
                    now = datetime.now(timezone.utc)
                
                if now >= license_expires:
                    print("[LICENSE] License has EXPIRED - please renew your subscription")
                    return False, {}
            except Exception as exp_err:
                print(f"[LICENSE] Error checking license expiry: {exp_err}")
        
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
        'src/license/types.py',
        'src/license/crypto.py',
        'src/license/cache.py',
        'src/license/client.py',
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
