"""
Activation-Based License Manager
DEPRECATED: Use license.client.manager_activation instead
This file is a compatibility wrapper for the new consolidated license module
"""

try:
    from license.client.manager_activation import (
        activate_license,
        validate_activated_license,
        check_or_activate_license
    )
except ImportError:
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
        SECRET_KEY = os.getenv('LICENSE_SECRET_KEY', b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0744e429edb8c876dd2d8e227a16f4d3b09beac10c9c2984a")
        if isinstance(SECRET_KEY, str):
            SECRET_KEY = SECRET_KEY.encode()
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
        try:
            if ':' not in license_key:
                return False, {"error": "Invalid license format"}
            payload_b64, signature = license_key.rsplit(':', 1)
            expected_sig = hmac.new(SECRET_KEY, payload_b64.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected_sig):
                return False, {"error": "Invalid license signature"}
            payload_json = base64.b64decode(payload_b64).decode('utf-8')
            payload = json.loads(payload_json)
            expires_ts = payload.get('expires')
            expires_dt = datetime.fromtimestamp(expires_ts)
            if datetime.now() >= expires_dt:
                return False, {"error": "License expired"}
            current_machine_id = get_machine_id()
            activated_license = {
                "activation_code": payload.get('activation_code'),
                "customer_id": payload.get('customer_id'),
                "machine_id": current_machine_id,
                "expires": expires_ts,
                "activated_on": int(datetime.now().timestamp())
            }
            activated_json = json.dumps(activated_license)
            activated_b64 = base64.b64encode(activated_json.encode()).decode()
            activated_sig = hmac.new(SECRET_KEY, activated_b64.encode(), hashlib.sha256).hexdigest()
            activated_key = f"{activated_b64}:{activated_sig}"
            ACTIVATED_LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
            ACTIVATED_LICENSE_FILE.write_text(activated_key)
            days_remaining = (expires_dt - datetime.now()).days
            return True, {
                "status": "activated",
                "customer_id": payload.get('customer_id'),
                "machine_id": current_machine_id,
                "expires": expires_dt.strftime("%Y-%m-%d %H:%M"),
                "days_remaining": days_remaining
            }
        except Exception as e:
            return False, {"error": f"License activation error: {str(e)}"}

    def validate_activated_license() -> Tuple[bool, dict]:
        try:
            if not ACTIVATED_LICENSE_FILE.exists():
                return False, {"error": "No activated license found"}
            activated_key = ACTIVATED_LICENSE_FILE.read_text().strip()
            if ':' not in activated_key:
                return False, {"error": "Invalid activated license format"}
            payload_b64, signature = activated_key.rsplit(':', 1)
            expected_sig = hmac.new(SECRET_KEY, payload_b64.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected_sig):
                return False, {"error": "Activated license signature invalid"}
            payload_json = base64.b64decode(payload_b64).decode('utf-8')
            payload = json.loads(payload_json)
            stored_machine_id = payload.get('machine_id')
            current_machine_id = get_machine_id()
            if stored_machine_id != current_machine_id:
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
                "days_remaining": days_remaining
            }
        except Exception as e:
            return False, {"error": f"License validation error: {str(e)}"}

    def check_or_activate_license(license_key: str = None) -> Tuple[bool, dict]:
        is_valid, data = validate_activated_license()
        if is_valid:
            return is_valid, data
        if license_key:
            return activate_license(license_key)
        return False, {"error": "No valid license found"}
