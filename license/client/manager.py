"""
License Management System for Discord Trading Bot
Handles license key generation, validation, and expiration checking
"""

import json
import hmac
import hashlib
import base64
from datetime import datetime, timedelta
from typing import Optional, Tuple

try:
    from license.config import SECRET_KEY
except ImportError:
    SECRET_KEY = b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0744e429edb8c876dd2d8e227a16f4d3b09beac10c9c2984a"


class LicenseManager:
    """Manages license key generation and validation"""
    
    @classmethod
    def generate_license(cls, days: int, customer_id: str = "customer") -> str:
        """
        Generate a license key valid for specified number of days
        
        Args:
            days: Number of days the license is valid
            customer_id: Optional identifier for the customer
            
        Returns:
            License key string
        """
        expiration = datetime.now() + timedelta(days=days)
        
        license_data = {
            'customer_id': customer_id,
            'issued': datetime.now().isoformat(),
            'expires': expiration.isoformat(),
            'days': days
        }
        
        json_data = json.dumps(license_data, sort_keys=True)
        
        signature = hmac.new(
            SECRET_KEY,
            json_data.encode('utf-8'),
            hashlib.sha256
        ).digest()
        
        combined = json_data.encode('utf-8') + b'::' + signature
        license_key = base64.b64encode(combined).decode('utf-8')
        
        return license_key
    
    @classmethod
    def validate_license(cls, license_key: str) -> Tuple[bool, str, Optional[dict]]:
        """
        Validate a license key and check expiration
        
        Returns:
            (is_valid, message, license_data)
            - is_valid: True if license is valid and not expired
            - message: Human-readable status message
            - license_data: Dictionary with license info (or None if invalid)
        """
        try:
            combined = base64.b64decode(license_key.encode('utf-8'))
            
            if b'::' not in combined:
                return (False, "Invalid license format", None)
            
            json_data, signature = combined.rsplit(b'::', 1)
            
            expected_signature = hmac.new(
                SECRET_KEY,
                json_data,
                hashlib.sha256
            ).digest()
            
            if not hmac.compare_digest(signature, expected_signature):
                return (False, "License signature verification failed - tampered or invalid", None)
            
            license_data = json.loads(json_data.decode('utf-8'))
            
            expires = datetime.fromisoformat(license_data['expires'])
            now = datetime.now()
            
            if now > expires:
                days_expired = (now - expires).days
                return (False, f"License expired {days_expired} days ago (expired on {expires.strftime('%Y-%m-%d')})", license_data)
            
            days_remaining = (expires - now).days
            
            return (True, f"License valid - {days_remaining} days remaining (expires on {expires.strftime('%Y-%m-%d')})", license_data)
            
        except Exception as e:
            return (False, f"License validation error: {str(e)}", None)
    
    @classmethod
    def get_license_info(cls, license_key: str) -> Optional[dict]:
        """
        Get detailed license information without validation
        Useful for displaying license details
        """
        try:
            combined = base64.b64decode(license_key.encode('utf-8'))
            if b'::' not in combined:
                return None
            json_data, _ = combined.rsplit(b'::', 1)
            license_data = json.loads(json_data.decode('utf-8'))
            
            expires = datetime.fromisoformat(license_data['expires'])
            issued = datetime.fromisoformat(license_data['issued'])
            now = datetime.now()
            
            license_data['expires_formatted'] = expires.strftime('%Y-%m-%d %H:%M')
            license_data['issued_formatted'] = issued.strftime('%Y-%m-%d %H:%M')
            license_data['days_remaining'] = max(0, (expires - now).days)
            license_data['is_expired'] = now > expires
            
            return license_data
        except Exception:
            return None
