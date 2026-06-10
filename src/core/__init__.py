"""
Core module - Foundation layer for BotifyTrades
Contains bootstrap, configuration, logging, and thread management
"""

from .bootstrap import (
    SSL_CONTEXT,
    setup_ssl,
    setup_paths,
    setup_event_loop,
    setup_env,
    get_exe_directory,
    is_pyinstaller_bundle,
    get_bundle_directory,
    initialize,
    is_initialized,
)

from .output_handler import (
    smart_print,
    debug_print,
    log_error_to_db,
    is_debug_mode,
    reset_debug_mode_cache,
    install_smart_print,
    get_original_print,
)

from .config_loader import (
    load_config_file,
    load_credentials_from_database,
    get_config,
    get_config_value,
    get_config_bool,
    get_config_float,
    get_config_int,
    reload_config,
)

from .settings import (
    get_trading_settings,
    get_slippage_settings,
    get_risk_management_settings,
    get_ai_analysis_settings,
    get_swing_analysis_settings,
    get_news_settings,
    get_alpha_vantage_settings,
    get_ai_command_settings,
    get_signal_conversion_settings,
    get_discord_settings,
    get_monitoring_interval,
    get_trailing_activation_percent,
    get_debug_mode,
    reload_settings,
)

from .thread_manager import (
    get_executor,
    start_discord_thread,
    start_flask_thread,
    set_discord_loop,
    get_discord_loop,
    schedule_in_discord_loop,
    is_discord_thread_alive,
    is_flask_thread_alive,
    wait_for_discord_thread,
    wait_for_flask_thread,
    shutdown_executor,
    create_isolated_event_loop,
    ThreadSafeCounter,
    ThreadSafeFlag,
)

from .expiry import (
    normalize_expiry_iso,
    expiry_to_yyyymmdd,
    expiry_to_date,
    expiry_to_mmdd,
    expiry_to_occ,
    expiry_year,
    is_expired,
    is_same_day,
)

from .imports import (
    load_optional_imports,
    is_available,
    get_module,
    AI_IMPORTS_AVAILABLE,
    ALPHA_VANTAGE_AVAILABLE,
    SWING_ANALYZER_AVAILABLE,
    NEWS_SERVICE_AVAILABLE,
    DATABASE_MODULE_AVAILABLE,
    BROKER_MANAGER_AVAILABLE,
    ALPACA_AVAILABLE,
)

__all__ = [
    # Bootstrap
    'SSL_CONTEXT',
    'setup_ssl',
    'setup_paths',
    'setup_event_loop',
    'setup_env',
    'get_exe_directory',
    'is_pyinstaller_bundle',
    'get_bundle_directory',
    'initialize',
    'is_initialized',
    # Output Handler
    'smart_print',
    'debug_print',
    'log_error_to_db',
    'is_debug_mode',
    'reset_debug_mode_cache',
    'install_smart_print',
    'get_original_print',
    # Config Loader
    'load_config_file',
    'load_credentials_from_database',
    'get_config',
    'get_config_value',
    'get_config_bool',
    'get_config_float',
    'get_config_int',
    'reload_config',
    # Settings
    'get_trading_settings',
    'get_slippage_settings',
    'get_risk_management_settings',
    'get_ai_analysis_settings',
    'get_swing_analysis_settings',
    'get_news_settings',
    'get_alpha_vantage_settings',
    'get_ai_command_settings',
    'get_signal_conversion_settings',
    'get_discord_settings',
    'get_monitoring_interval',
    'get_trailing_activation_percent',
    'get_debug_mode',
    'reload_settings',
    # Thread Manager
    'get_executor',
    'start_discord_thread',
    'start_flask_thread',
    'set_discord_loop',
    'get_discord_loop',
    'schedule_in_discord_loop',
    'is_discord_thread_alive',
    'is_flask_thread_alive',
    'wait_for_discord_thread',
    'wait_for_flask_thread',
    'shutdown_executor',
    'create_isolated_event_loop',
    'ThreadSafeCounter',
    'ThreadSafeFlag',
    # Expiry
    'normalize_expiry_iso',
    'expiry_to_yyyymmdd',
    'expiry_to_date',
    'expiry_to_mmdd',
    'expiry_to_occ',
    'expiry_year',
    'is_expired',
    'is_same_day',
    # Imports
    'load_optional_imports',
    'is_available',
    'get_module',
    'AI_IMPORTS_AVAILABLE',
    'ALPHA_VANTAGE_AVAILABLE',
    'SWING_ANALYZER_AVAILABLE',
    'NEWS_SERVICE_AVAILABLE',
    'DATABASE_MODULE_AVAILABLE',
    'BROKER_MANAGER_AVAILABLE',
    'ALPACA_AVAILABLE',
]
