#!/usr/bin/env python3
"""
License Management System for Discord Trading Bot
DEPRECATED: Use license.client.LicenseManager instead
This file is a compatibility wrapper for the new consolidated license module
"""

try:
    from license.client.manager import LicenseManager
except ImportError:
    import json
    import hmac
    import hashlib
    import base64
    import os
    from datetime import datetime, timedelta
    from typing import Optional, Tuple
    
    try:
        from license.config import SECRET_KEY
    except ImportError:
        # Must match the key in license/client/manager.py for cross-compatibility
        SECRET_KEY = b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0744e429edb8c876dd2d8e227a16f4d3b09beac10c9c2984a"

    class LicenseManager:
        """Manages license key generation and validation - DEPRECATED wrapper"""
        
        @classmethod
        def generate_license(cls, days: int, customer_id: str = "customer") -> str:
            expiration = datetime.now() + timedelta(days=days)
            license_data = {
                'customer_id': customer_id,
                'issued': datetime.now().isoformat(),
                'expires': expiration.isoformat(),
                'days': days
            }
            json_data = json.dumps(license_data, sort_keys=True)
            signature = hmac.new(SECRET_KEY, json_data.encode('utf-8'), hashlib.sha256).digest()
            combined = json_data.encode('utf-8') + b'::' + signature
            return base64.b64encode(combined).decode('utf-8')
        
        @classmethod
        def validate_license(cls, license_key: str) -> Tuple[bool, str, Optional[dict]]:
            try:
                combined = base64.b64decode(license_key.encode('utf-8'))
                if b'::' not in combined:
                    return (False, "Invalid license format", None)
                json_data, signature = combined.rsplit(b'::', 1)
                expected_signature = hmac.new(SECRET_KEY, json_data, hashlib.sha256).digest()
                if not hmac.compare_digest(signature, expected_signature):
                    return (False, "License signature verification failed", None)
                license_data = json.loads(json_data.decode('utf-8'))
                expires = datetime.fromisoformat(license_data['expires'])
                now = datetime.now()
                if now > expires:
                    days_expired = (now - expires).days
                    return (False, f"License expired {days_expired} days ago", license_data)
                days_remaining = (expires - now).days
                return (True, f"License valid - {days_remaining} days remaining", license_data)
            except Exception as e:
                return (False, f"License validation error: {str(e)}", None)
        
        @classmethod
        def get_license_info(cls, license_key: str) -> Optional[dict]:
            try:
                combined = base64.b64decode(license_key.encode('utf-8'))
                if b'::' not in combined:
                    return None
                json_data, _ = combined.rsplit(b'::', 1)
                license_data = json.loads(json_data.decode('utf-8'))
                expires = datetime.fromisoformat(license_data['expires'])
                issued = datetime.fromisoformat(license_data['issued'])
                now = datetime.now()
                license_data['days_remaining'] = max(0, (expires - now).days)
                license_data['is_expired'] = now > expires
                license_data['issued_formatted'] = issued.strftime('%Y-%m-%d %H:%M')
                license_data['expires_formatted'] = expires.strftime('%Y-%m-%d %H:%M')
                return license_data
            except:
                return None
