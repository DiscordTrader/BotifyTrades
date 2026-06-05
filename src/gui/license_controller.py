"""
License Controller - State machine for license validation flow
Integrates with splash screen for industry-standard license activation UX
"""
from enum import Enum, auto
from typing import Optional, Dict, Callable, Any, Tuple
from PySide6.QtCore import QObject, Signal, QThread
import os
import sys

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from license.client import LicenseClient
except ImportError:
    try:
        from src.license.client import LicenseClient
    except ImportError:
        LicenseClient = None


class LicenseState(Enum):
    """License validation states"""
    INIT = auto()           # Initial state, checking cache
    VALIDATING = auto()     # Validating with server
    ACTIVATED = auto()      # License valid, proceed to startup
    REQUIRE_KEY = auto()    # No license found, need input
    EXPIRED = auto()        # License expired, need renewal
    OFFLINE_GRACE = auto()  # Offline but within grace period
    FAILED = auto()         # Validation failed


class LicenseValidationWorker(QThread):
    """Background worker for license validation to avoid blocking UI"""
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, client, license_key: Optional[str] = None, action: str = 'validate'):
        super().__init__()
        self.client = client
        self.license_key = license_key
        self.action = action
    
    def run(self):
        try:
            if self.action == 'validate':
                result = self.client.validate_license(self.license_key)
            elif self.action == 'activate':
                result = self.client.activate_license(self.license_key)
            elif self.action == 'trial':
                result = self.client.request_trial()
            else:
                result = {'success': False, 'error': f'Unknown action: {self.action}'}
            
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class LicenseController(QObject):
    """
    State machine controller for license validation flow.
    Emits signals for UI updates and manages transitions between states.
    """
    
    # Signals for UI updates
    state_changed = Signal(object, str)  # (new_state, message) - using object for cross-platform enum compatibility
    validation_progress = Signal(str)           # Progress message
    license_activated = Signal(dict)            # License data on success
    license_failed = Signal(str)                # Error message on failure
    require_input = Signal(str)                 # Prompt message for license input
    
    def __init__(self):
        super().__init__()
        self._state = LicenseState.INIT
        self._license_data: Dict = {}
        self._worker: Optional[LicenseValidationWorker] = None
        
        # Initialize license client
        if LicenseClient:
            self._client = LicenseClient()
        else:
            self._client = None
            print("[LICENSE] Warning: LicenseClient not available")
    
    @property
    def state(self) -> LicenseState:
        return self._state
    
    @property
    def license_data(self) -> Dict:
        return self._license_data
    
    def _set_state(self, state: LicenseState, message: str = ""):
        """Update state and emit signal"""
        self._state = state
        self.state_changed.emit(state, message)
    
    def check_existing_license(self) -> bool:
        """
        Check for existing valid license.
        Priority: 1) Database, 2) Cache file, 3) Environment variable
        Returns True if license is valid, False if input needed.
        """
        # Priority 1: Check database for stored license
        db_license = self._load_license_from_database()
        if db_license and db_license.get('license_key'):
            license_key = db_license['license_key']
            print(f"[LICENSE] Found license in database: {license_key[:12]}...")
            self._set_state(LicenseState.VALIDATING, "Validating license...")
            if self._client:
                self._start_validation(license_key, 'validate')
                return True
            else:
                # No client - use cached data
                days = db_license.get('days_remaining', 0)
                if days > 0:
                    self._license_data = {
                        'is_valid': True,
                        'license_type': db_license.get('license_type', 'subscription'),
                        'days_remaining': days,
                        'license_key': license_key
                    }
                    self._set_state(LicenseState.ACTIVATED, "License activated")
                    self.license_activated.emit(self._license_data)
                    return True
        
        if not self._client:
            # No client available - check environment variable
            license_key = os.getenv('LICENSE_KEY', '').strip()
            if license_key:
                self._set_state(LicenseState.VALIDATING, "Validating license...")
                # Simple validation without server
                self._license_data = {
                    'is_valid': True,
                    'license_type': 'env_key',
                    'days_remaining': 365
                }
                self._set_state(LicenseState.ACTIVATED, "License activated")
                self.license_activated.emit(self._license_data)
                return True
            else:
                self._set_state(LicenseState.REQUIRE_KEY, "Please enter your license key")
                self.require_input.emit("No license found. Please activate.")
                return False
        
        self._set_state(LicenseState.VALIDATING, "Checking license...")
        
        # Priority 2: Check cache file
        cached = None
        try:
            if hasattr(self._client, '_load_cache'):
                cached = self._client._load_cache()
            elif hasattr(self._client, 'load_cache'):
                cached = self._client.load_cache()
        except Exception:
            pass
        
        if cached:
            license_key = cached.get('license_key') or os.getenv('LICENSE_KEY', '').strip()
            if license_key:
                # Validate cached license
                self._start_validation(license_key, 'validate')
                return True
        
        # Priority 3: Check environment variable
        license_key = os.getenv('LICENSE_KEY', '').strip()
        if license_key:
            self._start_validation(license_key, 'validate')
            return True
        
        # No license found
        self._set_state(LicenseState.REQUIRE_KEY, "Please enter your license key")
        self.require_input.emit("No license found. Please activate.")
        return False
    
    def _load_license_from_database(self) -> Optional[Dict]:
        """Load stored license from database"""
        try:
            from gui_app.database import get_local_license
            return get_local_license()
        except ImportError:
            return None
        except Exception as e:
            print(f"[LICENSE] Error loading from database: {e}")
            return None
    
    def _start_validation(self, license_key: str, action: str):
        """Start background validation"""
        self._set_state(LicenseState.VALIDATING, "Validating license...")
        
        self._worker = LicenseValidationWorker(self._client, license_key, action)
        self._worker.finished.connect(self._on_validation_complete)
        self._worker.error.connect(self._on_validation_error)
        self._worker.start()
    
    def _on_validation_complete(self, result: Dict):
        """Handle validation result"""
        if result.get('success') or result.get('is_valid'):
            self._license_data = result
            days = result.get('days_remaining', 0)
            
            if days <= 0:
                # License expired
                self._set_state(LicenseState.EXPIRED, f"License expired")
                self.require_input.emit("License expired. Please renew or enter a new key.")
            else:
                # License valid
                self._set_state(LicenseState.ACTIVATED, f"License valid ({days} days)")
                self.license_activated.emit(result)
        elif result.get('offline'):
            # Check offline grace period
            grace_valid, grace_msg = False, "Offline - reconnect to validate"
            try:
                if hasattr(self._client, '_check_grace_period'):
                    grace_valid, grace_msg = self._client._check_grace_period(result)
                elif hasattr(self._client, 'check_grace_period'):
                    grace_valid, grace_msg = self._client.check_grace_period(result)
            except Exception:
                pass
            if grace_valid:
                self._license_data = result
                self._set_state(LicenseState.OFFLINE_GRACE, grace_msg)
                self.license_activated.emit(result)
            else:
                self._set_state(LicenseState.REQUIRE_KEY, "Offline - please connect to validate")
                self.require_input.emit(grace_msg)
        else:
            # Invalid license
            error = result.get('error', 'License validation failed')
            self._set_state(LicenseState.REQUIRE_KEY, error)
            self.require_input.emit(error)
    
    def _on_validation_error(self, error: str):
        """Handle validation error"""
        self._set_state(LicenseState.FAILED, error)
        self.license_failed.emit(error)
    
    def activate_license(self, license_key: str):
        """Activate a license key"""
        if not license_key or not license_key.strip():
            self._set_state(LicenseState.REQUIRE_KEY, "Please enter a valid license key")
            return
        
        license_key = license_key.strip().upper()
        
        if not self._client:
            # Fallback: store in environment
            os.environ['LICENSE_KEY'] = license_key
            self._license_data = {
                'is_valid': True,
                'license_type': 'manual',
                'days_remaining': 365,
                'license_key': license_key
            }
            self._set_state(LicenseState.ACTIVATED, "License activated")
            self.license_activated.emit(self._license_data)
            return
        
        self._start_validation(license_key, 'activate')
    
    def request_trial(self):
        """Request a free trial license"""
        if not self._client:
            self._set_state(LicenseState.FAILED, "Trial not available offline")
            self.license_failed.emit("Trial requires internet connection")
            return
        
        self._set_state(LicenseState.VALIDATING, "Activating trial...")
        self._start_validation('', 'trial')
    
    def is_activated(self) -> bool:
        """Check if license is currently activated"""
        return self._state in (LicenseState.ACTIVATED, LicenseState.OFFLINE_GRACE)
    
    def get_status_message(self) -> str:
        """Get human-readable status message"""
        if self._state == LicenseState.ACTIVATED:
            days = self._license_data.get('days_remaining', 0)
            license_type = self._license_data.get('license_type', 'subscription')
            return f"{license_type.title()} - {days} days remaining"
        elif self._state == LicenseState.OFFLINE_GRACE:
            return "Offline mode - limited time remaining"
        elif self._state == LicenseState.EXPIRED:
            return "License expired - please renew"
        elif self._state == LicenseState.REQUIRE_KEY:
            return "License required"
        elif self._state == LicenseState.VALIDATING:
            return "Validating..."
        else:
            return "Unknown status"
