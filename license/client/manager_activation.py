"""
Activation-Based License Manager
Licenses auto-bind to customer's machine on first run (no Machine ID needed upfront)
This version will be OBFUSCATED with PyArmor before distribution
"""

import hmac
import hashlib
import json
import base64
import os
from datetime import datetime
from pathlib import Path
from typing import Tuple

try:
    from license.config import SECRET_KEY, ACTIVATED_LICENSE_FILE
except ImportError:
    SECRET_KEY = b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0744e429edb8c876dd2d8e227a16f4d3b09beac10c9c2984a"
    ACTIVATED_LICENSE_FILE = Path.home() / ".tradingbot_license"

try:
    from src.machine_fingerprint import get_machine_id
except ImportError:
    try:
        from machine_fingerprint import get_machine_id
    except ImportError:
        def get_machine_id():
            return "UNKNOWN_MACHINE"


def activate_license(license_key: str) -> Tuple[bool, dict]:
    """
    Activate a license on first run (binds to current machine)
    
    License format: base64(json_payload):hmac_signature
    Payload: {activation_code, customer_id, expires_timestamp}
    
    Returns:
        Tuple of (success, result_data)
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
        
        activation_code = payload.get('activation_code')
        customer_id = payload.get('customer_id')
        expires_ts = payload.get('expires')
        
        if not all([activation_code, customer_id, expires_ts]):
            return False, {"error": "Malformed license data"}
        
        expires_dt = datetime.fromtimestamp(expires_ts)
        
        if datetime.now() >= expires_dt:
            return False, {
                "error": "License expired",
                "expired_on": expires_dt.strftime("%Y-%m-%d")
            }
        
        current_machine_id = get_machine_id()
        
        activated_license = {
            "activation_code": activation_code,
            "customer_id": customer_id,
            "machine_id": current_machine_id,
            "expires": expires_ts,
            "activated_on": int(datetime.now().timestamp())
        }
        
        activated_json = json.dumps(activated_license)
        activated_b64 = base64.b64encode(activated_json.encode()).decode()
        
        activated_sig = hmac.new(
            SECRET_KEY,
            activated_b64.encode(),
            hashlib.sha256
        ).hexdigest()
        
        activated_key = f"{activated_b64}:{activated_sig}"
        
        ACTIVATED_LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTIVATED_LICENSE_FILE.write_text(activated_key, encoding='utf-8')
        
        try:
            os.chmod(ACTIVATED_LICENSE_FILE, 0o600)
        except (OSError, AttributeError):
            pass
        
        days_remaining = (expires_dt - datetime.now()).days
        
        return True, {
            "status": "activated",
            "customer_id": customer_id,
            "activation_code": activation_code,
            "machine_id": current_machine_id,
            "expires": expires_dt.strftime("%Y-%m-%d %H:%M"),
            "days_remaining": days_remaining
        }
        
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        return False, {"error": f"License parsing error: {str(e)}"}
    except Exception as e:
        return False, {"error": f"License activation error: {str(e)}"}


def validate_activated_license() -> Tuple[bool, dict]:
    """
    Validate previously activated license
    
    Returns:
        Tuple of (is_valid, license_data)
    """
    try:
        if not ACTIVATED_LICENSE_FILE.exists():
            return False, {"error": "No activated license found - please activate first"}
        
        activated_key = ACTIVATED_LICENSE_FILE.read_text(encoding='utf-8').strip()
        
        if ':' not in activated_key:
            return False, {"error": "Invalid activated license format"}
        
        payload_b64, signature = activated_key.rsplit(':', 1)
        
        expected_sig = hmac.new(
            SECRET_KEY,
            payload_b64.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_sig):
            return False, {"error": "Activated license signature invalid - file may be tampered"}
        
        payload_json = base64.b64decode(payload_b64).decode('utf-8')
        payload = json.loads(payload_json)
        
        activation_code = payload.get('activation_code')
        customer_id = payload.get('customer_id')
        stored_machine_id = payload.get('machine_id')
        expires_ts = payload.get('expires')
        
        if not all([activation_code, customer_id, stored_machine_id, expires_ts]):
            return False, {"error": "Malformed activated license"}
        
        current_machine_id = get_machine_id()
        
        if stored_machine_id != current_machine_id:
            return False, {
                "error": "License machine mismatch - this license is bound to different hardware",
                "license_machine": stored_machine_id[:8] + "...",
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
            "activation_code": activation_code,
            "machine_id": current_machine_id,
            "expires": expires_dt.strftime("%Y-%m-%d %H:%M"),
            "days_remaining": days_remaining
        }
        
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        return False, {"error": f"Activated license parsing error: {str(e)}"}
    except Exception as e:
        return False, {"error": f"Activated license validation error: {str(e)}"}


def check_or_activate_license(license_key: str = None) -> Tuple[bool, dict]:
    """
    Check for existing activation or activate new license
    
    Args:
        license_key: New license key to activate (optional)
        
    Returns:
        Tuple of (is_valid, license_data)
    """
    is_valid, data = validate_activated_license()
    if is_valid:
        return is_valid, data
    
    if license_key:
        return activate_license(license_key)
    
    return False, {"error": "No valid license found and no new license key provided"}
