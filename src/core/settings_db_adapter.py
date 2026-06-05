"""
Settings Database Adapter
=========================
Adapter for loading/saving settings from the database.
This connects SettingsService to gui_app.database without tight coupling.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SettingsDBAdapter:
    """
    Adapter for database access to settings.
    
    Provides a clean interface for SettingsService without 
    requiring direct imports from gui_app.database.
    """
    
    def __init__(self, db_module=None):
        self._db = db_module
        self._initialized = False
    
    def _ensure_db(self):
        """Lazy load database module if not provided."""
        if self._db is None:
            try:
                from gui_app import database as db
                self._db = db
            except ImportError:
                logger.warning("[SETTINGS-DB] Could not import gui_app.database")
                return False
        return True
    
    def get_all_settings(self) -> Dict[str, Any]:
        """Get all settings from database."""
        if not self._ensure_db():
            return {}
        
        try:
            settings = {}
            
            if hasattr(self._db, 'get_trading_settings'):
                trading = self._db.get_trading_settings()
                if trading:
                    settings.update({
                        'position_sizing_enabled': trading.get('position_sizing_enabled', True),
                        'max_position_size': trading.get('max_position_size', 1000.0),
                        'position_size_percent': trading.get('position_size_percent', 5.0),
                        'auto_clear_stale_trades': trading.get('auto_clear_stale_trades', False),
                        'stale_trade_hours': trading.get('stale_trade_hours', 24),
                        'max_daily_trades': trading.get('max_daily_trades', 50),
                        'max_daily_loss': trading.get('max_daily_loss', 500.0),
                        'paper_trade': trading.get('paper_trade', True),
                    })
            
            if hasattr(self._db, 'get_slippage_settings'):
                slippage = self._db.get_slippage_settings()
                if slippage:
                    settings.update({
                        'slippage_protection_enabled': slippage.get('enabled', False),
                        'slippage_percent': slippage.get('threshold_percent', 10.0),
                    })
                else:
                    settings.update({
                        'slippage_protection_enabled': False,
                        'slippage_percent': 10.0,
                    })
            
            if hasattr(self._db, 'get_risk_management_settings'):
                risk = self._db.get_risk_management_settings()
                if risk:
                    settings.update({
                        'risk_management_enabled': risk.get('enabled', False),
                        'global_stop_loss_percent': risk.get('stop_loss_percent', 10.0),
                        'global_take_profit_percent': risk.get('take_profit_percent', 20.0),
                        'trailing_stop_enabled': risk.get('trailing_stop_enabled', False),
                        'trailing_stop_percent': risk.get('trailing_stop_percent', 5.0),
                    })
            
            if hasattr(self._db, 'get_ai_settings'):
                ai = self._db.get_ai_settings()
                if ai:
                    settings.update({
                        'ai_analysis_enabled': ai.get('enabled', False),
                        'pre_trade_analysis': ai.get('pre_trade_analysis', True),
                        'post_trade_analysis': ai.get('post_trade_analysis', True),
                    })
            
            if hasattr(self._db, 'get_notification_settings'):
                notif = self._db.get_notification_settings()
                if notif:
                    settings.update({
                        'notifications_enabled': notif.get('enabled', True),
                        'notification_on_entry': notif.get('on_entry', True),
                        'notification_on_exit': notif.get('on_exit', True),
                    })
            
            if hasattr(self._db, 'get_setting'):
                for key in ['default_broker', 'signal_auto_execute', 'market_data_provider', 'news_enabled']:
                    val = self._db.get_setting(key)
                    if val is not None:
                        settings[key] = val
            
            return settings
            
        except Exception as e:
            logger.error(f"[SETTINGS-DB] Error loading settings: {e}")
            return {}
    
    def set_setting(self, key: str, value: Any) -> bool:
        """Set a single setting in the database."""
        if not self._ensure_db():
            return False
        
        try:
            if hasattr(self._db, 'update_setting'):
                self._db.update_setting(key, value)
                return True
            elif hasattr(self._db, 'set_setting'):
                self._db.set_setting(key, value)
                return True
            else:
                logger.warning(f"[SETTINGS-DB] No method to save setting: {key}")
                return False
        except Exception as e:
            logger.error(f"[SETTINGS-DB] Error saving {key}: {e}")
            return False
    
    def get_channel_settings(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get settings for a specific channel."""
        if not self._ensure_db():
            return None
        
        try:
            if hasattr(self._db, 'get_channel_by_id'):
                return self._db.get_channel_by_id(channel_id)
            return None
        except Exception as e:
            logger.error(f"[SETTINGS-DB] Error getting channel {channel_id}: {e}")
            return None
    
    def get_all_channel_risk_settings(self) -> Dict[str, Dict[str, Any]]:
        """Get risk settings for all channels."""
        if not self._ensure_db():
            return {}
        
        try:
            if hasattr(self._db, 'get_channel_risk_settings_map'):
                return self._db.get_channel_risk_settings_map()
            return {}
        except Exception as e:
            logger.error(f"[SETTINGS-DB] Error getting channel risk settings: {e}")
            return {}


_adapter_instance: Optional[SettingsDBAdapter] = None


def get_settings_db_adapter() -> SettingsDBAdapter:
    """Get the singleton database adapter instance."""
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = SettingsDBAdapter()
    return _adapter_instance


def init_settings_from_db():
    """
    Initialize the settings service with database adapter.
    
    Call this at application startup after database is ready.
    """
    from .settings_service import init_settings_service
    
    adapter = get_settings_db_adapter()
    service = init_settings_service(adapter)
    
    logger.info("[SETTINGS] ✓ Settings service initialized from database")
    return service
