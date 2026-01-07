"""
Settings Integration Layer
===========================
Bridges existing settings loading functions to the unified SettingsService.
This provides backward compatibility while enabling centralized settings management.
"""
import logging
from typing import Any, Dict, Optional, Callable
from functools import wraps

logger = logging.getLogger(__name__)


def get_trading_settings_via_service() -> Dict[str, Any]:
    """
    Get trading settings through database directly.
    Includes position_sizing_enabled and global_default_quantity.
    """
    try:
        from gui_app import database as db
        settings = db.get_trading_settings()
        enabled = settings.get('max_position_size_enabled', True)
        return {
            'max_position_size': settings.get('max_position_size', 600),
            'max_position_size_enabled': enabled,
            'position_sizing_enabled': enabled,
            'global_default_quantity': settings.get('global_default_quantity'),
            'paper_trade': settings.get('paper_trade', False),
        }
    except Exception as e:
        logger.warning(f"[SETTINGS] Could not load via service, using direct DB: {e}")
        return _fallback_trading_settings()


def get_slippage_settings_via_service() -> Dict[str, Any]:
    """
    Get slippage settings directly from slippage_settings table.
    This ensures the GUI toggle is always respected.
    """
    try:
        from gui_app import database as db
        settings = db.get_slippage_settings()
        return {
            'enabled': settings.get('enabled', True),
            'threshold_percent': settings.get('threshold_percent', 10.0),
        }
    except Exception as e:
        logger.warning(f"[SETTINGS] Could not load slippage from database: {e}")
        return {'enabled': True, 'threshold_percent': 10.0}


def get_risk_settings_via_service() -> Dict[str, Any]:
    """
    Get risk management settings through SettingsService.
    Falls back to direct database access for reliability.
    """
    try:
        from gui_app import database as db
        settings = db.get_risk_management_settings()
        return {
            'enabled': settings.get('enabled', False),
            'profit_target_percent': settings.get('profit_target_percent', 20.0),
            'stop_loss_percent': settings.get('stop_loss_percent', 10.0),
            'trailing_stop_percent': settings.get('trailing_stop_percent', 5.0),
            'trailing_stop_enabled': settings.get('trailing_stop_percent', 0) > 0,
        }
    except Exception as e:
        logger.warning(f"[SETTINGS] Could not load risk from database: {e}")
        return _fallback_risk_settings()


def get_ai_settings_via_service() -> Dict[str, Any]:
    """
    Get AI analysis settings through SettingsService.
    """
    try:
        from .settings_service import get_settings_service
        service = get_settings_service()
        
        return {
            'enabled': service.get('ai.enabled', module='selfbot_webull'),
            'pre_trade_analysis': service.get('ai.pre_trade_analysis', module='selfbot_webull'),
            'post_trade_analysis': service.get('ai.post_trade_analysis', module='selfbot_webull'),
            'model': 'gpt-4',
            'sentiment_enabled': False,
        }
    except Exception as e:
        logger.warning(f"[SETTINGS] Could not load AI via service: {e}")
        return {'enabled': False, 'model': 'gpt-4', 'sentiment_enabled': False, 'pre_trade_analysis': False, 'post_trade_analysis': False}


def get_notification_settings_via_service() -> Dict[str, Any]:
    """
    Get notification settings through SettingsService.
    """
    try:
        from .settings_service import get_settings_service
        service = get_settings_service()
        
        return {
            'enabled': service.get('notifications.notifications_enabled', module='selfbot_webull'),
            'on_entry': service.get('notifications.notification_on_entry', module='selfbot_webull'),
            'on_exit': service.get('notifications.notification_on_exit', module='selfbot_webull'),
        }
    except Exception as e:
        logger.warning(f"[SETTINGS] Could not load notifications via service: {e}")
        return {'enabled': True, 'on_entry': True, 'on_exit': True}


def _fallback_trading_settings() -> Dict[str, Any]:
    """Fallback to direct database access."""
    try:
        from gui_app import database as db
        settings = db.get_trading_settings()
        enabled = settings.get('max_position_size_enabled', True)
        return {
            'max_position_size': settings.get('max_position_size', 600),
            'max_position_size_enabled': enabled,
            'position_sizing_enabled': enabled,
            'global_default_quantity': settings.get('global_default_quantity'),
            'paper_trade': settings.get('paper_trade', False),
        }
    except Exception:
        return {
            'max_position_size': 600,
            'max_position_size_enabled': True,
            'position_sizing_enabled': True,
            'global_default_quantity': None,
            'paper_trade': False,
        }


def _fallback_slippage_settings() -> Dict[str, Any]:
    """Fallback to direct database access."""
    try:
        from gui_app import database as db
        settings = db.get_slippage_settings()
        return {
            'enabled': settings.get('enabled', True),
            'threshold_percent': settings.get('threshold_percent', 10.0),
        }
    except Exception:
        return {'enabled': True, 'threshold_percent': 10.0}


def _fallback_risk_settings() -> Dict[str, Any]:
    """Fallback to direct database access."""
    try:
        from gui_app import database as db
        settings = db.get_risk_management_settings()
        return {
            'enabled': settings.get('enabled', False),
            'profit_target_percent': settings.get('profit_target_percent', 20.0),
            'stop_loss_percent': settings.get('stop_loss_percent', 10.0),
            'trailing_stop_percent': settings.get('trailing_stop_percent', 5.0),
            'trailing_stop_enabled': settings.get('trailing_stop_enabled', False),
        }
    except Exception:
        return {'enabled': False, 'profit_target_percent': 20.0, 'stop_loss_percent': 10.0, 'trailing_stop_percent': 5.0, 'trailing_stop_enabled': False}


def check_trading_limits(order_value: float, daily_trades: int = 0, daily_loss: float = 0) -> Dict[str, Any]:
    """
    Check if order meets trading limits.
    Returns dict with 'allowed' bool and 'reason' if blocked.
    """
    try:
        from .settings_service import get_settings_service
        service = get_settings_service()
        
        max_position = service.get('trading.max_position_size', module='order_validation')
        max_daily_trades = service.get('trading.max_daily_trades', module='order_validation')
        max_daily_loss = service.get('trading.max_daily_loss', module='order_validation')
        
        if order_value > max_position:
            return {
                'allowed': False,
                'reason': f"Order value ${order_value:.2f} exceeds max position size ${max_position:.2f}"
            }
        
        if max_daily_trades > 0 and daily_trades >= max_daily_trades:
            return {
                'allowed': False,
                'reason': f"Daily trade limit reached ({daily_trades}/{max_daily_trades})"
            }
        
        if max_daily_loss > 0 and daily_loss >= max_daily_loss:
            return {
                'allowed': False,
                'reason': f"Daily loss limit reached (${daily_loss:.2f}/${max_daily_loss:.2f})"
            }
        
        return {'allowed': True, 'reason': None}
        
    except Exception as e:
        logger.error(f"[SETTINGS] Error checking trading limits: {e}")
        return {'allowed': True, 'reason': None}


def log_settings_at_startup():
    """
    Log all settings at startup for debugging.
    Called once during initialization.
    """
    try:
        from .settings_service import get_settings_service
        service = get_settings_service()
        
        logger.info("[SETTINGS] ========== SETTINGS AUDIT ==========")
        
        trading = get_trading_settings_via_service()
        logger.info(f"[SETTINGS] Trading: max_position=${trading['max_position_size']}, sizing={trading['position_sizing_enabled']}, paper={trading['paper_trade']}")
        
        slippage = get_slippage_settings_via_service()
        logger.info(f"[SETTINGS] Slippage: enabled={slippage['enabled']}, threshold={slippage['threshold_percent']}%")
        
        risk = get_risk_settings_via_service()
        logger.info(f"[SETTINGS] Risk: enabled={risk['enabled']}, TP={risk['profit_target_percent']}%, SL={risk['stop_loss_percent']}%")
        
        ai = get_ai_settings_via_service()
        logger.info(f"[SETTINGS] AI: enabled={ai['enabled']}, pre={ai['pre_trade_analysis']}, post={ai['post_trade_analysis']}")
        
        logger.info("[SETTINGS] ========================================")
        
        return True
    except Exception as e:
        logger.error(f"[SETTINGS] Startup audit failed: {e}")
        return False
