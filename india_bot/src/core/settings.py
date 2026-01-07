"""
Settings module - Trading, slippage, risk management, and AI settings
Provides centralized access to all bot configuration with database priority
"""

from typing import Dict, Any, Optional
import os

_db = None
_cfg = None


def _get_database():
    """Lazy load database module to avoid circular imports."""
    global _db
    if _db is None:
        try:
            from gui_app import database as db
            _db = db
        except ImportError:
            _db = False  # Mark as unavailable
    return _db if _db else None


def _get_config():
    """Lazy load config parser."""
    global _cfg
    if _cfg is None:
        from .config_loader import get_config
        _cfg = get_config()
    return _cfg


def get_trading_settings() -> Dict[str, Any]:
    """
    Get trading settings from database (if available), fallback to config.ini.
    
    Returns:
        Dictionary with trading settings including max_position_size
    """
    db = _get_database()
    cfg = _get_config()
    
    if db:
        try:
            settings = db.get_trading_settings()
            return {
                'max_position_size': settings['max_position_size']
            }
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load trading settings from database: {e}")
    
    return {
        'max_position_size': cfg.getfloat('signals', 'max_position_size', fallback=200.0)
    }


def get_slippage_settings() -> Dict[str, Any]:
    """
    Get slippage protection settings from database (if available), fallback to config.ini.
    
    Returns:
        Dictionary with slippage settings including enabled, threshold_percent
    """
    db = _get_database()
    cfg = _get_config()
    
    if db:
        try:
            settings = db.get_slippage_settings()
            return {
                'enabled': settings['enabled'],
                'threshold_percent': settings['threshold_percent']
            }
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load slippage settings from database: {e}")
    
    return {
        'enabled': cfg.getboolean('price_slippage', 'enable_slippage_protection', fallback=True),
        'threshold_percent': cfg.getfloat('price_slippage', 'high_slippage_threshold_percent', fallback=10.0)
    }


def get_risk_management_settings() -> Dict[str, Any]:
    """
    Get risk management settings from database (if available), fallback to config.ini.
    
    Returns:
        Dictionary with risk settings including enabled, profit_target, stop_loss, trailing_stop
    """
    db = _get_database()
    cfg = _get_config()
    
    if db:
        try:
            settings = db.get_risk_management_settings()
            return {
                'enabled': settings['enabled'],
                'profit_target_percent': settings['profit_target_percent'],
                'stop_loss_percent': settings['stop_loss_percent'],
                'trailing_stop_percent': settings['trailing_stop_percent']
            }
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load risk management settings from database: {e}")
    
    return {
        'enabled': cfg.getboolean('risk_management', 'enable_risk_management', fallback=False),
        'profit_target_percent': cfg.getfloat('risk_management', 'profit_target_percent', fallback=0.0),
        'stop_loss_percent': cfg.getfloat('risk_management', 'stop_loss_percent', fallback=0.0),
        'trailing_stop_percent': cfg.getfloat('risk_management', 'trailing_stop_percent', fallback=0.0)
    }


def get_ai_analysis_settings() -> Dict[str, Any]:
    """
    Get AI analysis settings from database (if available), fallback to config.ini.
    
    Returns:
        Dictionary with AI settings including enabled, model, sentiment_enabled
    """
    db = _get_database()
    cfg = _get_config()
    
    if db:
        try:
            settings = db.get_ai_settings()
            return {
                'enabled': settings['enabled'],
                'model': settings['model'],
                'sentiment_enabled': settings['sentiment_enabled']
            }
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load AI settings from database: {e}")
    
    return {
        'enabled': cfg.getboolean('ai_analysis', 'enable_ai_analysis', fallback=False),
        'model': cfg.get('ai_analysis', 'ai_model', fallback='gpt-4o-mini').strip(),
        'sentiment_enabled': cfg.getboolean('ai_analysis', 'enable_sentiment_analysis', fallback=False)
    }


def get_swing_analysis_settings() -> Dict[str, Any]:
    """Get swing trading analysis settings."""
    cfg = _get_config()
    
    return {
        'enabled': cfg.getboolean('swing_analysis', 'enable_swing_analysis', fallback=True),
        'min_confidence_score': cfg.getint('swing_analysis', 'min_confidence_score', fallback=60),
        'analysis_timeframe': cfg.get('swing_analysis', 'analysis_timeframe', fallback='1d').strip(),
        'auto_reject_low_confidence': cfg.getboolean('swing_analysis', 'auto_reject_low_confidence', fallback=False)
    }


def get_news_settings() -> Dict[str, Any]:
    """Get news service settings."""
    cfg = _get_config()
    
    return {
        'enabled': cfg.getboolean('news', 'enable_news', fallback=True),
        'provider': cfg.get('news', 'provider', fallback='finnhub').strip().lower(),
        'cache_ttl_minutes': cfg.getint('news', 'cache_ttl_minutes', fallback=5),
        'max_items': cfg.getint('news', 'max_items', fallback=5)
    }


def get_alpha_vantage_settings() -> Dict[str, Any]:
    """Get Alpha Vantage scanner settings."""
    cfg = _get_config()
    
    return {
        'enabled': cfg.getboolean('alpha_vantage', 'enable_scanner', fallback=False),
        'min_premium': cfg.getfloat('alpha_vantage', 'min_premium', fallback=100000),
        'min_volume': cfg.getint('alpha_vantage', 'min_volume', fallback=100),
        'min_dte': cfg.getint('alpha_vantage', 'min_dte', fallback=7),
        'max_dte': cfg.getint('alpha_vantage', 'max_dte', fallback=45),
        'max_results': cfg.getint('alpha_vantage', 'max_results', fallback=10),
        'default_symbols': cfg.get('alpha_vantage', 'default_symbols', fallback='SPY,QQQ,IWM').strip(),
        'sentiment_filter': cfg.get('alpha_vantage', 'sentiment_filter', fallback='').strip()
    }


def get_ai_command_settings() -> Dict[str, Any]:
    """Get AI command settings for Discord."""
    cfg = _get_config()
    
    ai_channel_str = cfg.get('ai_commands', 'ai_channel_id', fallback='').strip()
    
    return {
        'enabled': cfg.getboolean('ai_commands', 'enable_ai_commands', fallback=False),
        'channel_id': int(ai_channel_str) if ai_channel_str else None,
        'include_news': cfg.getboolean('ai_commands', 'include_news_in_analyze', fallback=True),
        'include_fundamentals': cfg.getboolean('ai_commands', 'include_fundamentals_in_analyze', fallback=True)
    }


def get_signal_conversion_settings() -> Dict[str, Any]:
    """Get signal conversion channel settings."""
    cfg = _get_config()
    
    conversion_channel_str = cfg.get('signal_conversion', 'conversion_channel_id', fallback='').strip()
    
    return {
        'enabled': cfg.getboolean('signal_conversion', 'enable_conversion', fallback=True),
        'channel_id': int(conversion_channel_str) if conversion_channel_str else None
    }


def get_discord_settings() -> Dict[str, Any]:
    """Get Discord-related settings."""
    cfg = _get_config()
    
    return {
        'discovery_mode': cfg.getboolean('discord', 'discovery_mode', fallback=False),
        'allow_self_messages': cfg.getboolean('discord', 'allow_self_messages', fallback=False)
    }


def get_monitoring_interval() -> int:
    """Get the risk management monitoring interval in seconds."""
    cfg = _get_config()
    return cfg.getint('risk_management', 'monitoring_interval', fallback=30)


def get_trailing_activation_percent() -> float:
    """Get the trailing stop activation percentage."""
    cfg = _get_config()
    return cfg.getfloat('risk_management', 'trailing_stop_activation_percent', fallback=0.0)


def get_debug_mode() -> bool:
    """Get debug mode status from database."""
    db = _get_database()
    if db:
        try:
            value = db.get_setting('debug_mode', 'false')
            return value.lower() == 'true'
        except Exception:
            pass
    return False


def reload_settings() -> None:
    """Force reload all cached settings."""
    global _db, _cfg
    _db = None
    _cfg = None
