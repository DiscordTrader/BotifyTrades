"""
License Heartbeat - Background license re-validation during operation
"""

from datetime import datetime
from typing import Dict, Optional

from .client import LicenseClient


class LicenseHeartbeat:
    """
    Background license heartbeat - periodically re-validates license during operation.
    This prevents users from simply bypassing initial license check.
    """
    
    def __init__(self, license_key: str, interval_minutes: int = 30, revoke_callback=None):
        self.license_key = license_key
        self.interval_minutes = interval_minutes
        self.client = LicenseClient()
        self._stop_event = None
        self._thread = None
        self._last_check = None
        self._consecutive_failures = 0
        self._max_failures = 3
        self._revoke_callback = revoke_callback
    
    def start(self):
        """Start the heartbeat background thread."""
        import threading
        
        if self._thread and self._thread.is_alive():
            return
        
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()
        print(f"[LICENSE] Heartbeat started (every {self.interval_minutes} min)")
    
    def stop(self):
        """Stop the heartbeat thread."""
        if self._stop_event:
            self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
    
    def _heartbeat_loop(self):
        """Background loop for license re-validation."""
        import time
        
        interval_seconds = self.interval_minutes * 60
        
        while not self._stop_event.is_set():
            self._stop_event.wait(interval_seconds)
            
            if self._stop_event.is_set():
                break
            
            try:
                is_valid, result = self.client.validate_license(self.license_key)
                self._last_check = datetime.now()
                
                if is_valid:
                    self._consecutive_failures = 0
                    print(f"[LICENSE] Heartbeat OK - license valid")
                else:
                    self._consecutive_failures += 1
                    print(f"[LICENSE] Heartbeat FAIL ({self._consecutive_failures}/{self._max_failures})")
                    
                    if self._consecutive_failures >= self._max_failures:
                        print("[LICENSE] Too many heartbeat failures - license may be revoked")
                        self._on_license_revoked()
            except Exception as e:
                print(f"[LICENSE] Heartbeat error: {e}")
    
    def _on_license_revoked(self):
        """Called when license is detected as revoked during operation."""
        print("[LICENSE] ========================================")
        print("[LICENSE] LICENSE REVOKED OR EXPIRED")
        print("[LICENSE] Trading functionality will be disabled.")
        print("[LICENSE] Please renew your license to continue.")
        print("[LICENSE] ========================================")
        
        try:
            from gui_app import database as db
            db.update_setting('license_revoked', 'true')
            db.update_setting('trading_enabled', 'false')
        except Exception as e:
            print(f"[LICENSE] Could not update settings: {e}")
        
        if self._revoke_callback:
            try:
                self._revoke_callback()
            except Exception as e:
                print(f"[LICENSE] Revoke callback error: {e}")
    
    def get_status(self) -> Dict:
        """Get heartbeat status."""
        return {
            'running': self._thread and self._thread.is_alive(),
            'last_check': self._last_check.isoformat() if self._last_check else None,
            'failures': self._consecutive_failures,
            'max_failures': self._max_failures
        }


# Global heartbeat instance
_heartbeat_instance: Optional[LicenseHeartbeat] = None


def start_license_heartbeat(license_key: str, interval_minutes: int = 30, revoke_callback=None) -> LicenseHeartbeat:
    """Start the global license heartbeat."""
    global _heartbeat_instance
    
    if _heartbeat_instance:
        _heartbeat_instance.stop()
    
    _heartbeat_instance = LicenseHeartbeat(license_key, interval_minutes, revoke_callback)
    _heartbeat_instance.start()
    return _heartbeat_instance


def stop_license_heartbeat():
    """Stop the global license heartbeat."""
    global _heartbeat_instance
    
    if _heartbeat_instance:
        _heartbeat_instance.stop()
        _heartbeat_instance = None
