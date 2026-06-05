"""
Output Handler - Logging, debug mode, and smart print management
Provides controlled console output with file logging
"""

import builtins
from typing import Optional

_original_print = builtins.print
_DEBUG_MODE_ENABLED: Optional[bool] = None
_logger = None


def _get_logger():
    """Lazy load the logger to avoid circular imports."""
    global _logger
    if _logger is None:
        try:
            from logging_config import logger
            _logger = logger
        except ImportError:
            import logging
            _logger = logging.getLogger('botify')
    return _logger


def log_error_to_db(error_type: str, error_message: str, component: str = None,
                    severity: str = 'error', context: str = None) -> None:
    """
    Log error to database for AI assistant context awareness.
    
    Args:
        error_type: Category of error (e.g., 'connection', 'parsing')
        error_message: Detailed error message
        component: Which component raised the error
        severity: 'error', 'warning', 'critical'
        context: Additional context information
    """
    try:
        from gui_app.database import log_error as db_log_error
        db_log_error(
            error_type=error_type,
            error_message=error_message,
            component=component,
            severity=severity,
            context=context
        )
    except Exception:
        pass


def is_debug_mode() -> bool:
    """
    Check if debug mode is enabled in GUI settings.
    Result is cached for performance.
    """
    global _DEBUG_MODE_ENABLED
    if _DEBUG_MODE_ENABLED is None:
        try:
            from gui_app import database as settings_db
            value = settings_db.get_setting('debug_mode', 'false')
            _DEBUG_MODE_ENABLED = value.lower() == 'true'
        except Exception:
            _DEBUG_MODE_ENABLED = False
    return _DEBUG_MODE_ENABLED


def reset_debug_mode_cache() -> None:
    """Reset debug mode cache (call after settings change)."""
    global _DEBUG_MODE_ENABLED
    _DEBUG_MODE_ENABLED = None


def debug_print(message: str) -> None:
    """Print debug message only if DEBUG_MODE is enabled."""
    if is_debug_mode():
        _original_print(message)


def smart_print(*args, **kwargs) -> None:
    """
    Replacement for print() that:
    - Shows ONLY essential messages in console (errors, key status)
    - Logs ALL messages to rotating files for admin debugging
    - Verbose details ([CONFIG], [LICENSE]) only shown when debug mode ON
    """
    try:
        message = ' '.join(str(arg) for arg in args)
    except Exception:
        message = repr(args)
    logger = _get_logger()
    
    if any(tag in message for tag in ['[ERROR]', '[CRITICAL]']):
        logger.error(message)
        _original_print(message)
    elif '[WARNING]' in message or '⚠️' in message:
        logger.warning(message)
        _original_print(message)
    elif any(tag in message for tag in ['[DEBUG]', '[API]', '[ROUTE]', '[DEDUP]', 
                                         '[LOT_MATCHER]', '[PNL_TRACKER]', '[SWING]', 
                                         '[PRE-TRADE]', '[FUNDS]']):
        logger.debug(message)
        if is_debug_mode():
            _original_print(message)
    elif any(tag in message for tag in ['[CONFIG]', '[LICENSE]']):
        logger.info(message)
        if is_debug_mode():
            _original_print(message)
    elif any(tag in message for tag in ['[Init]', '[MAIN]', '[GUI]']):
        logger.info(message)
        _original_print(message)
    elif any(tag in message for tag in ['[ALPACA]', '[Discord]', '[Webull]', '[WORKER]', 
                                         '[SYNC]', '[DATABASE]', '[STARTUP]', '[POSITION SIZE]',
                                         '[SIGNAL PARSED]', '[QUEUE]', '[PAPER TRADE]',
                                         '[ORDER', '[MULTI-BROKER]', '[RISK]',
                                         '[T212]', '[T212-CLIENT]', '[TRADING212]',
                                         '[TASTYTRADE]', '[SCHWAB]', '[IBKR]', '[ROBINHOOD]']):
        logger.info(message)
        _original_print(message)
    else:
        logger.info(message)


def install_smart_print() -> None:
    """
    Install smart_print as the global print function.
    Also saves original print to builtins for modules that need it.
    """
    builtins._original_print = _original_print
    builtins.print = smart_print


def get_original_print():
    """Get the original print function."""
    return _original_print
