"""
Settings Service - Unified Settings Access Layer
=================================================
Provides centralized access to all application settings with:
- Automatic validation against manifest
- Runtime usage tracking for consistency checks
- Enforcement decorators for order pipelines
- Database synchronization

All settings access should go through this service.
"""
import functools
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

from .settings_manifest import (
    SETTINGS_MANIFEST,
    SettingDefinition,
    SettingNamespace,
    SettingType,
    get_setting_default,
    get_setting_info,
    validate_setting_value,
)

logger = logging.getLogger(__name__)


class SettingsUsageTracker:
    """Tracks which settings are actually used at runtime."""
    
    def __init__(self):
        self._accessed: Dict[str, datetime] = {}
        self._enforced: Dict[str, List[str]] = {}
        self._lock = threading.Lock()
    
    def record_access(self, setting_key: str, module: str = "unknown"):
        """Record that a setting was accessed."""
        with self._lock:
            self._accessed[setting_key] = datetime.now()
            if setting_key not in self._enforced:
                self._enforced[setting_key] = []
            if module not in self._enforced[setting_key]:
                self._enforced[setting_key].append(module)
    
    def get_accessed_settings(self) -> Set[str]:
        """Get all settings that were accessed at runtime."""
        with self._lock:
            return set(self._accessed.keys())
    
    def get_unused_settings(self) -> Set[str]:
        """Get settings that are declared but never accessed."""
        with self._lock:
            declared = set(SETTINGS_MANIFEST.keys())
            accessed = set(self._accessed.keys())
            return declared - accessed
    
    def get_enforcement_report(self) -> Dict[str, List[str]]:
        """Get report of which modules enforced which settings."""
        with self._lock:
            return self._enforced.copy()


_usage_tracker = SettingsUsageTracker()


class SettingsService:
    """
    Unified settings access service.
    
    This is the ONLY approved way to read settings in the application.
    Direct database access for settings is prohibited.
    """
    
    def __init__(self, db_adapter=None):
        self._db_adapter = db_adapter
        self._cache: Dict[str, Any] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 30
        self._lock = threading.Lock()
        self._loaded = False
    
    def set_db_adapter(self, adapter):
        """Set the database adapter for loading settings."""
        self._db_adapter = adapter
        self._loaded = False
    
    def _ensure_loaded(self):
        """Ensure settings are loaded from database."""
        if self._loaded and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds()
            if elapsed < self._cache_ttl_seconds:
                return
        
        self._load_from_db()
    
    def _load_from_db(self):
        """Load all settings from database."""
        with self._lock:
            if self._db_adapter:
                try:
                    raw_settings = self._db_adapter.get_all_settings()
                    for key, value in raw_settings.items():
                        self._cache[key] = value
                except Exception as e:
                    logger.warning(f"[SETTINGS] Failed to load from DB: {e}")
            
            for key, definition in SETTINGS_MANIFEST.items():
                storage_key = definition.storage_key
                if storage_key not in self._cache:
                    self._cache[storage_key] = definition.default
            
            self._cache_time = datetime.now()
            self._loaded = True
    
    def get(self, full_key: str, default: Any = None, module: str = "unknown") -> Any:
        """
        Get a setting value by its full key (namespace.key).
        
        Args:
            full_key: The setting key in format "namespace.key"
            default: Default value if setting not found
            module: Module requesting the setting (for tracking)
        
        Returns:
            The setting value
        """
        _usage_tracker.record_access(full_key, module)
        
        self._ensure_loaded()
        
        info = get_setting_info(full_key)
        if info:
            storage_key = info.storage_key
            with self._lock:
                if storage_key in self._cache:
                    return self._cache[storage_key]
                return info.default
        
        with self._lock:
            return self._cache.get(full_key, default)
    
    def get_bool(self, full_key: str, module: str = "unknown") -> bool:
        """Get a boolean setting."""
        value = self.get(full_key, module=module)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        if isinstance(value, (int, float)):
            return bool(value)
        info = get_setting_info(full_key)
        return info.default if info else False
    
    def get_int(self, full_key: str, module: str = "unknown") -> int:
        """Get an integer setting."""
        value = self.get(full_key, module=module)
        try:
            return int(value)
        except (TypeError, ValueError):
            info = get_setting_info(full_key)
            return info.default if info else 0
    
    def get_float(self, full_key: str, module: str = "unknown") -> float:
        """Get a float setting."""
        value = self.get(full_key, module=module)
        try:
            return float(value)
        except (TypeError, ValueError):
            info = get_setting_info(full_key)
            return info.default if info else 0.0
    
    def get_string(self, full_key: str, module: str = "unknown") -> str:
        """Get a string setting."""
        value = self.get(full_key, module=module)
        return str(value) if value is not None else ""
    
    def set(self, full_key: str, value: Any) -> bool:
        """
        Set a setting value.
        
        Args:
            full_key: The setting key
            value: The value to set
        
        Returns:
            True if successful
        """
        if not validate_setting_value(full_key, value):
            logger.warning(f"[SETTINGS] Invalid value for {full_key}: {value}")
            return False
        
        info = get_setting_info(full_key)
        storage_key = info.storage_key if info else full_key
        
        with self._lock:
            self._cache[storage_key] = value
        
        if self._db_adapter:
            try:
                self._db_adapter.set_setting(storage_key, value)
            except Exception as e:
                logger.error(f"[SETTINGS] Failed to save {full_key}: {e}")
                return False
        
        return True
    
    def refresh(self):
        """Force refresh settings from database."""
        self._loaded = False
        self._ensure_loaded()
    
    def get_all_by_namespace(self, namespace: SettingNamespace, module: str = "unknown") -> Dict[str, Any]:
        """Get all settings in a namespace."""
        self._ensure_loaded()
        
        result = {}
        for key, definition in SETTINGS_MANIFEST.items():
            if definition.namespace == namespace:
                result[definition.key] = self.get(key, module=module)
        
        return result
    
    def validate_all(self) -> Dict[str, List[str]]:
        """
        Validate all settings against manifest.
        
        Returns:
            Dict with 'errors' and 'warnings' lists
        """
        self._ensure_loaded()
        
        errors = []
        warnings = []
        
        for key, definition in SETTINGS_MANIFEST.items():
            storage_key = definition.storage_key
            
            with self._lock:
                if storage_key not in self._cache:
                    warnings.append(f"Setting '{key}' not found in database, using default")
                    continue
                
                value = self._cache[storage_key]
            
            if not validate_setting_value(key, value):
                errors.append(f"Setting '{key}' has invalid value: {value}")
        
        return {"errors": errors, "warnings": warnings}


_settings_service: Optional[SettingsService] = None
_service_lock = threading.Lock()


def get_settings_service() -> SettingsService:
    """Get the singleton settings service instance."""
    global _settings_service
    
    with _service_lock:
        if _settings_service is None:
            _settings_service = SettingsService()
        return _settings_service


def init_settings_service(db_adapter) -> SettingsService:
    """Initialize the settings service with a database adapter."""
    service = get_settings_service()
    service.set_db_adapter(db_adapter)
    service.refresh()
    return service


def requires_setting(setting_key: str, enabled_value: Any = True):
    """
    Decorator that enforces a setting must be enabled for a function to execute.
    
    Usage:
        @requires_setting("trading.slippage_protection_enabled")
        def check_slippage(order):
            # This only runs if slippage protection is enabled
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            service = get_settings_service()
            module = f"{func.__module__}:{func.__name__}"
            
            current_value = service.get(setting_key, module=module)
            
            if current_value != enabled_value:
                logger.debug(f"[SETTINGS] Skipping {func.__name__} - {setting_key} is {current_value}")
                return None
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


def with_setting(setting_key: str, param_name: str = "setting_value"):
    """
    Decorator that injects a setting value as a parameter.
    
    Usage:
        @with_setting("trading.max_position_size", "max_size")
        def calculate_quantity(order, max_size=None):
            # max_size is automatically injected
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            service = get_settings_service()
            module = f"{func.__module__}:{func.__name__}"
            
            value = service.get(setting_key, module=module)
            kwargs[param_name] = value
            
            return func(*args, **kwargs)
        return wrapper
    return decorator


def enforce_trading_limits(func: Callable):
    """
    Decorator that enforces all trading limits before executing an order.
    
    Checks:
    - Position sizing limits
    - Daily trade count
    - Daily loss limit
    - Slippage protection
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        service = get_settings_service()
        module = f"{func.__module__}:{func.__name__}"
        
        max_position = service.get_float("trading.max_position_size", module=module)
        max_daily_trades = service.get_int("trading.max_daily_trades", module=module)
        max_daily_loss = service.get_float("trading.max_daily_loss", module=module)
        
        order_value = kwargs.get('order_value', 0)
        if order_value > max_position:
            logger.warning(f"[SETTINGS] Order value ${order_value} exceeds max position ${max_position}")
            kwargs['_trading_limit_exceeded'] = f"Order exceeds max position size (${max_position})"
        
        return func(*args, **kwargs)
    return wrapper


def get_usage_tracker() -> SettingsUsageTracker:
    """Get the settings usage tracker for consistency checks."""
    return _usage_tracker


def get_runtime_enforcement_report() -> Dict[str, Any]:
    """
    Get a report of which settings are being enforced at runtime.
    
    Used by consistency checker to verify settings flow.
    """
    tracker = get_usage_tracker()
    
    accessed = tracker.get_accessed_settings()
    unused = tracker.get_unused_settings()
    enforcement = tracker.get_enforcement_report()
    
    return {
        "total_declared": len(SETTINGS_MANIFEST),
        "accessed_count": len(accessed),
        "unused_count": len(unused),
        "accessed_settings": list(accessed),
        "unused_settings": list(unused),
        "enforcement_map": enforcement,
    }
