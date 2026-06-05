"""
Config Loader - Configuration file and database credential loading
Handles both config.ini files and encrypted database storage
"""

import os
import sys
import configparser
from pathlib import Path
from typing import Dict, Any, Optional

_config: Optional[configparser.ConfigParser] = None
_db_credentials: Optional[Dict[str, Any]] = None


def get_config_paths() -> list:
    """Get list of paths to search for config.ini file."""
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
    else:
        exe_dir = Path(__file__).parent.parent.parent
    
    return [
        exe_dir / 'config.ini',
        exe_dir / 'config.ini.example',
        Path.cwd() / 'config.ini',
        Path.cwd() / 'src' / 'config.ini',
        Path(__file__).parent.parent.parent / 'config.ini',
        Path(__file__).parent.parent / 'config.ini',
    ]


def load_config_file() -> configparser.ConfigParser:
    """
    Load configuration from config.ini file.
    Creates default sections if no config file found.
    
    Returns:
        ConfigParser object with configuration values
    """
    global _config
    
    if _config is not None:
        return _config
    
    cfg = configparser.ConfigParser()
    config_paths = get_config_paths()
    
    config_found = False
    for config_path in config_paths:
        print(f"[CONFIG] Checking: {config_path}")
        if config_path.exists():
            cfg.read(str(config_path))
            print(f"[CONFIG] Loaded from: {config_path}")
            config_found = True
            break
    
    if not config_found:
        print("[CONFIG] No config.ini found - using GUI configuration and sensible defaults")
        cfg['discord'] = {
            'channel_ids': '',
            'allowed_author_ids': '',
            'allowed_guild_ids': '',
            'discovery_mode': 'false',
            'allow_self_messages': 'false'
        }
        cfg['signals'] = {
            'max_position_size': '200.0'
        }
        cfg['price_slippage'] = {
            'enable_slippage_protection': 'true',
            'high_slippage_threshold_percent': '10.0'
        }
        cfg['webull'] = {
            'paper_trade': 'true'
        }
    
    _config = cfg
    return cfg


def load_credentials_from_database() -> Dict[str, Any]:
    """
    Load broker credentials from encrypted database storage (set via GUI).
    
    Returns:
        Dictionary of credentials from all configured brokers
    """
    global _db_credentials
    
    if _db_credentials is not None:
        return _db_credentials
    
    credentials = {}
    try:
        from gui_app.broker_credentials_service import get_all_credentials_for_startup
        credentials = get_all_credentials_for_startup()
        if any(credentials.values()):
            print("[CONFIG] Loaded credentials from database (GUI configuration)")
    except ImportError:
        print("[CONFIG] Broker credentials service not available")
    except Exception as e:
        print(f"[CONFIG] Could not load credentials from database: {e}")
    
    _db_credentials = credentials
    return credentials


def get_config() -> configparser.ConfigParser:
    """Get the loaded configuration (loads if not already loaded)."""
    if _config is None:
        load_config_file()
    return _config


def get_config_value(section: str, key: str, default: str = '') -> str:
    """
    Get a configuration value with fallback to default.
    
    Args:
        section: Config section name
        key: Config key name
        default: Default value if not found
        
    Returns:
        Configuration value or default
    """
    cfg = get_config()
    try:
        return cfg.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default


def get_config_bool(section: str, key: str, default: bool = False) -> bool:
    """Get a boolean configuration value."""
    value = get_config_value(section, key, str(default).lower())
    return value.lower() in ('true', 'yes', '1', 'on')


def get_config_float(section: str, key: str, default: float = 0.0) -> float:
    """Get a float configuration value."""
    value = get_config_value(section, key, str(default))
    try:
        return float(value)
    except ValueError:
        return default


def get_config_int(section: str, key: str, default: int = 0) -> int:
    """Get an integer configuration value."""
    value = get_config_value(section, key, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def reload_config() -> configparser.ConfigParser:
    """Force reload configuration from file."""
    global _config, _db_credentials
    _config = None
    _db_credentials = None
    return load_config_file()
