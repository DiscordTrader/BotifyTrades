"""
Secure License Manager - Machine-Bound HMAC Validation
DEPRECATED: Use license.client.manager_secure instead
This file is a compatibility wrapper for the new consolidated license module
"""

try:
    from src.machine_fingerprint import get_machine_id as get_current_machine_id
except ImportError:
    try:
        from machine_fingerprint import get_machine_id as get_current_machine_id
    except ImportError:
        def get_current_machine_id():
            return "UNKNOWN_MACHINE"

try:
    from license.client.manager_secure import (
        validate_license,
        validate_legacy_license,
        validate_machine_bound_license,
        get_current_machine_id as _get_current_machine_id
    )
    if not get_current_machine_id:
        get_current_machine_id = _get_current_machine_id
except ImportError:
    import hmac
    import hashlib
    import json
    import base64
    import os
    from datetime import datetime
    from typing import Tuple

    try:
        from license.config import SECRET_KEY
    except ImportError:
        SECRET_KEY = os.getenv('LICENSE_SECRET_KEY', b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0744e429edb8c876dd2d8e227a16f4d3b09beac10c9c2984a")
        if isinstance(SECRET_KEY, str):
            SECRET_KEY = SECRET_KEY.encode()

    try:
        from src.machine_fingerprint import get_machine_id
    except ImportError:
        try:
            from machine_fingerprint import get_machine_id
        except ImportError:
            def get_machine_id():
                return "UNKNOWN_MACHINE"

    def validate_legacy_license(license_key: str) -> Tuple[bool, dict]:
        try:
            combined = base64.b64decode(license_key.encode('utf-8'))
            if b'::' not in combined:
                return False, {"error": "Invalid legacy license format"}
            json_data, signature = combined.rsplit(b'::', 1)
            expected_signature = hmac.new(SECRET_KEY, json_data, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected_signature):
                return False, {"error": "Invalid license signature"}
            payload = json.loads(json_data.decode('utf-8'))
            expires_str = payload.get('expires')
            expires_dt = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
            if datetime.now() >= expires_dt:
                return False, {"error": "License expired"}
            days_remaining = (expires_dt - datetime.now()).days
            return True, {
                "customer_id": payload.get('customer_id'),
                "expires": expires_dt.strftime("%Y-%m-%d %H:%M"),
                "days_remaining": days_remaining,
                "license_type": "legacy"
            }
        except Exception as e:
            return False, {"error": f"License validation error: {str(e)}"}

    def validate_machine_bound_license(license_key: str) -> Tuple[bool, dict]:
        try:
            if ':' not in license_key:
                return False, {"error": "Invalid license format"}
            payload_b64, signature = license_key.rsplit(':', 1)
            expected_sig = hmac.new(SECRET_KEY, payload_b64.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected_sig):
                return False, {"error": "Invalid license signature"}
            payload_json = base64.b64decode(payload_b64).decode('utf-8')
            payload = json.loads(payload_json)
            license_machine_id = payload.get('machine_id')
            current_machine_id = get_machine_id()
            if license_machine_id != current_machine_id:
                return False, {"error": "License machine mismatch"}
            expires_ts = payload.get('expires')
            expires_dt = datetime.fromtimestamp(expires_ts)
            if datetime.now() >= expires_dt:
                return False, {"error": "License expired"}
            days_remaining = (expires_dt - datetime.now()).days
            return True, {
                "customer_id": payload.get('customer_id'),
                "machine_id": current_machine_id,
                "expires": expires_dt.strftime("%Y-%m-%d %H:%M"),
                "days_remaining": days_remaining,
                "license_type": "machine-bound"
            }
        except Exception as e:
            return False, {"error": f"License validation error: {str(e)}"}

    def validate_license(license_key: str) -> Tuple[bool, dict]:
        if not license_key or not isinstance(license_key, str):
            return False, {"error": "Invalid license key format"}
        if ':' in license_key and '::' not in license_key:
            return validate_machine_bound_license(license_key)
        return validate_legacy_license(license_key)
