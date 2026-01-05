"""
Secure License Manager - Machine-Bound HMAC Validation
Licenses are tied to specific hardware and cryptographically signed
This version will be OBFUSCATED with PyArmor before distribution
"""

import hmac
import hashlib
import json
import base64
from datetime import datetime
from typing import Tuple

try:
    from license.config import SECRET_KEY
except ImportError:
    # SECURITY: Never hardcode SECRET_KEY - require proper configuration
    SECRET_KEY = None
    print("[LICENSE] WARNING: No SECRET_KEY configured - legacy validation disabled")

try:
    from src.machine_fingerprint import get_machine_id
except ImportError:
    try:
        from machine_fingerprint import get_machine_id
    except ImportError:
        def get_machine_id():
            return "UNKNOWN_MACHINE"

def get_current_machine_id():
    """Alias for get_machine_id for backward compatibility"""
    return get_machine_id()


def validate_legacy_license(license_key: str) -> Tuple[bool, dict]:
    """
    Validate legacy license format (non-machine-bound)
    
    Legacy format: base64(json_data::signature_bytes)
    Payload: {customer_id, days, expires (ISO datetime), issued}
    
    Returns:
        Tuple of (is_valid, license_data)
    """
    # SECURITY: Require SECRET_KEY to be configured
    if SECRET_KEY is None:
        return False, {"error": "License validation not configured - contact support"}
    
    try:
        combined = base64.b64decode(license_key.encode('utf-8'))
        
        if b'::' not in combined:
            return False, {"error": "Invalid legacy license format - missing separator"}
        
        json_data, signature = combined.rsplit(b'::', 1)
        
        expected_signature = hmac.new(
            SECRET_KEY,
            json_data,
            hashlib.sha256
        ).digest()
        
        if not hmac.compare_digest(signature, expected_signature):
            return False, {"error": "Invalid license signature - license may be tampered"}
        
        payload = json.loads(json_data.decode('utf-8'))
        
        customer_id = payload.get('customer_id')
        expires_str = payload.get('expires')
        
        if not all([customer_id, expires_str]):
            return False, {"error": "Malformed legacy license data"}
        
        expires_dt = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
        
        if datetime.now() >= expires_dt:
            return False, {
                "error": "License expired",
                "expired_on": expires_dt.strftime("%Y-%m-%d")
            }
        
        days_remaining = (expires_dt - datetime.now()).days
        
        return True, {
            "customer_id": customer_id,
            "machine_id": "LEGACY (not machine-bound)",
            "expires": expires_dt.strftime("%Y-%m-%d %H:%M"),
            "days_remaining": days_remaining,
            "license_type": "legacy"
        }
        
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        return False, {"error": f"Legacy license parsing error: {str(e)}"}
    except Exception as e:
        return False, {"error": f"Legacy license validation error: {str(e)}"}


def validate_machine_bound_license(license_key: str) -> Tuple[bool, dict]:
    """
    Validate machine-bound license key
    
    License format: base64(json_payload):hmac_signature
    Payload: {customer_id, machine_id, expires_timestamp}
    
    Returns:
        Tuple of (is_valid, license_data)
    """
    try:
        if ':' not in license_key:
            return False, {"error": "Invalid license format"}
        
        payload_b64, signature = license_key.rsplit(':', 1)
        
        expected_sig = hmac.new(
            SECRET_KEY,
            payload_b64.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_sig):
            return False, {"error": "Invalid license signature - license may be tampered"}
        
        payload_json = base64.b64decode(payload_b64).decode('utf-8')
        payload = json.loads(payload_json)
        
        customer_id = payload.get('customer_id')
        license_machine_id = payload.get('machine_id')
        expires_ts = payload.get('expires')
        
        if not all([customer_id, license_machine_id, expires_ts]):
            return False, {"error": "Malformed license data"}
        
        current_machine_id = get_machine_id()
        
        if license_machine_id != current_machine_id:
            return False, {
                "error": "License machine mismatch - this license is bound to different hardware",
                "license_machine": license_machine_id[:8] + "...",
                "current_machine": current_machine_id[:8] + "..."
            }
        
        expires_dt = datetime.fromtimestamp(expires_ts)
        
        if datetime.now() >= expires_dt:
            return False, {
                "error": "License expired",
                "expired_on": expires_dt.strftime("%Y-%m-%d")
            }
        
        days_remaining = (expires_dt - datetime.now()).days
        
        return True, {
            "customer_id": customer_id,
            "machine_id": current_machine_id,
            "expires": expires_dt.strftime("%Y-%m-%d %H:%M"),
            "days_remaining": days_remaining,
            "license_type": "machine-bound"
        }
        
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        return False, {"error": f"License parsing error: {str(e)}"}
    except Exception as e:
        return False, {"error": f"License validation error: {str(e)}"}


def validate_license(license_key: str) -> Tuple[bool, dict]:
    """
    Dual-format license validator with auto-detection
    
    Supports both:
    1. Current format: base64(json):signature - machine-bound (PRIMARY)
    2. Legacy format: base64(json_data::signature) - non-machine-bound (FALLBACK)
    
    Returns:
        Tuple of (is_valid, license_data)
    """
    if not license_key or not isinstance(license_key, str):
        return False, {"error": "Invalid license key format"}
    
    if ':' in license_key and '::' not in license_key:
        return validate_machine_bound_license(license_key)
    
    if '::' in license_key or (license_key and ':' not in license_key):
        try:
            return validate_legacy_license(license_key)
        except Exception:
            pass
    
    return False, {"error": "Invalid license format - unrecognized structure"}
