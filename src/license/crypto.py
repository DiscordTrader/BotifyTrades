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
    """Generate a unique machine identifier based on hardware.
    
    Platform strategies (most stable → fallback):
      Windows: PowerShell Get-CimInstance → wmic → registry → hostname+MAC
      Linux:   /etc/machine-id → /var/lib/dbus/machine-id → hostname+MAC
      macOS:   ioreg IOPlatformUUID → system_profiler → hostname+MAC
    """
    system = platform.system()
    machine_uuid = None
    
    try:
        if system == 'Windows':
            machine_uuid = _get_windows_uuid()
        elif system == 'Linux':
            machine_uuid = _get_linux_uuid()
        elif system == 'Darwin':
            machine_uuid = _get_macos_uuid()
    except Exception:
        pass
    
    # Final fallback: hostname + first MAC address (better than hostname alone)
    if not machine_uuid or machine_uuid == 'FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF':
        machine_uuid = _get_fallback_id()
    
    raw = f"{machine_uuid}_{platform.system()}_{platform.machine()}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def _get_windows_uuid() -> str:
    """Windows: PowerShell CIM (future-proof) → wmic (legacy) → registry."""
    # Method 1: PowerShell Get-CimInstance (works on Windows 10/11, no deprecation)
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             '(Get-CimInstance Win32_ComputerSystemProduct).UUID'],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
        )
        uuid_val = result.stdout.strip()
        if uuid_val and len(uuid_val) >= 16 and uuid_val != 'FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF':
            return uuid_val
    except Exception:
        pass
    
    # Method 2: wmic (legacy, may not exist on Windows 11 24H2+)
    try:
        result = subprocess.run(
            ['wmic', 'csproduct', 'get', 'uuid'],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000),
        )
        uuid_lines = [line.strip() for line in result.stdout.split('\n')
                       if line.strip() and line.strip() != 'UUID']
        if uuid_lines and len(uuid_lines[0]) >= 16:
            return uuid_lines[0]
    except Exception:
        pass
    
    # Method 3: Windows Registry MachineGuid (always exists, survives hardware changes)
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r'SOFTWARE\Microsoft\Cryptography', 0, winreg.KEY_READ)
        guid, _ = winreg.QueryValueEx(key, 'MachineGuid')
        winreg.CloseKey(key)
        if guid:
            return guid
    except Exception:
        pass
    
    return None


def _get_linux_uuid() -> str:
    """Linux: /etc/machine-id → /var/lib/dbus/machine-id."""
    for path in ['/etc/machine-id', '/var/lib/dbus/machine-id']:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                mid = f.read().strip()
                if mid and len(mid) >= 16:
                    return mid
        except Exception:
            continue
    return None


def _get_macos_uuid() -> str:
    """macOS: ioreg IOPlatformUUID → system_profiler hardware UUID."""
    # Method 1: ioreg (fastest, most reliable)
    try:
        result = subprocess.run(
            ['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.split('\n'):
            if 'IOPlatformUUID' in line:
                uuid_val = line.split('"')[-2]
                if uuid_val and len(uuid_val) >= 16:
                    return uuid_val
    except Exception:
        pass
    
    # Method 2: system_profiler (slower but always available)
    try:
        result = subprocess.run(
            ['system_profiler', 'SPHardwareDataType'],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.split('\n'):
            if 'Hardware UUID' in line or 'UUID' in line:
                uuid_val = line.split(':')[-1].strip()
                if uuid_val and len(uuid_val) >= 16:
                    return uuid_val
    except Exception:
        pass
    
    return None


def _get_fallback_id() -> str:
    """Fallback: hostname + first non-loopback MAC address.
    
    Better than hostname alone — two machines named 'DESKTOP-ABC' with different
    network cards will get different IDs. Not perfect (MAC can change) but much
    more unique than hostname-only.
    """
    hostname = platform.node()
    mac = ''
    try:
        import uuid as _uuid_mod
        mac_int = _uuid_mod.getnode()
        # getnode() returns a random if no MAC found — check bit 0 (multicast flag)
        if not (mac_int >> 40) & 1:  # bit 40 = locally administered, not real MAC
            mac = format(mac_int, '012x')
    except Exception:
        pass
    return f"{hostname}_{mac}" if mac else hostname


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
