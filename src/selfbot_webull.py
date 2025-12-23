# -*- coding: utf-8 -*-
# selfbot_webull.py
# ------------------------------------------------------------
# Discord self-bot that reads trade signals and places orders
# on Webull (stocks + options). Use at your own risk.
# ------------------------------------------------------------

# BUILD VERSION MARKER - This MUST print if the code is current
import sys
import builtins
_early_print = builtins.print  # Save original print before any override

# Import version dynamically to show actual release version
try:
    from upgrade.version import APP_VERSION
    _build_version = f"v{APP_VERSION}"
except ImportError:
    _build_version = "DEV"

_early_print("=" * 60, flush=True)
_early_print(f"BUILD VERSION: {_build_version}", flush=True)
_early_print("=" * 60, flush=True)
sys.stdout.flush()

import re
import json
import asyncio
import configparser
import os
import time
import hashlib
import sys
import ssl

# Fix SSL certificate verification for cloud environments AND EXE distribution
# This is critical for aiohttp (used by discord.py-self) which doesn't use env vars
SSL_CONTEXT = None
try:
    import certifi
    cert_path = certifi.where()
    os.environ['SSL_CERT_FILE'] = cert_path
    os.environ['REQUESTS_CA_BUNDLE'] = cert_path
    
    # Create SSL context for aiohttp (discord.py-self uses aiohttp internally)
    SSL_CONTEXT = ssl.create_default_context(cafile=cert_path)
    
    # Patch aiohttp's default SSL context creation
    try:
        import aiohttp
        _original_connector_init = aiohttp.TCPConnector.__init__
        
        def _patched_connector_init(self, *args, **kwargs):
            if 'ssl' not in kwargs or kwargs['ssl'] is None:
                kwargs['ssl'] = SSL_CONTEXT
            _original_connector_init(self, *args, **kwargs)
        
        aiohttp.TCPConnector.__init__ = _patched_connector_init
        print("[SSL] ✓ Patched aiohttp with certifi certificates")
    except Exception as e:
        print(f"[SSL] Warning: Could not patch aiohttp: {e}")
except ImportError:
    print("[SSL] Warning: certifi not available, using system certificates")

# Add current directory and parent directory to Python path for local imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)  # workspace root
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import Alpaca broker for paper trading
try:
    from brokers.alpaca_broker import AlpacaBroker
    ALPACA_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import AlpacaBroker: {e}")
    ALPACA_AVAILABLE = False

# Import Tastytrade broker
try:
    from brokers.tastytrade_broker import TastytradeBroker
    TASTYTRADE_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import TastytradeBroker: {e}")
    TASTYTRADE_AVAILABLE = False

# Import Robinhood broker (WARNING: No paper trading - all trades are LIVE)
try:
    from brokers.robinhood_broker import RobinhoodBroker
    ROBINHOOD_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import RobinhoodBroker: {e}")
    ROBINHOOD_AVAILABLE = False

# Import IBKR broker (requires TWS or IB Gateway running)
try:
    from brokers.ibkr_broker import IBKRBroker
    IBKR_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import IBKRBroker: {e}")
    IBKR_AVAILABLE = False

# Import BrokerSyncService for real-time trade synchronization
from broker_sync_service import BrokerSyncService

# Import webull_auth early to apply monkey-patch for Webull API v2 (rzone fix)
try:
    from webull_auth import webull_auth as _webull_auth_patch
except ImportError:
    pass

# Import Risk Management module (single source of truth - no legacy fallback)
try:
    from risk import RiskManager, RiskDBAdapter
    RISK_MODULE_AVAILABLE = True
except ImportError:
    RISK_MODULE_AVAILABLE = False
    print("[RISK] Warning: Risk module not available - risk monitoring will be disabled")

# Import Settings Integration (unified settings via SettingsService)
try:
    from core.settings_integration import (
        get_trading_settings_via_service,
        get_slippage_settings_via_service,
        get_risk_settings_via_service,
        get_ai_settings_via_service,
        check_trading_limits,
        log_settings_at_startup
    )
    SETTINGS_SERVICE_AVAILABLE = True
except ImportError:
    SETTINGS_SERVICE_AVAILABLE = False
    print("[SETTINGS] Warning: Settings service not available - using direct DB access")

from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from enum import Enum
from pathlib import Path
import discord
import platform

# Import logging configuration FIRST (before any print statements)
from logging_config import (
    log_signal, log_execution, log_balance, log_channel, log_position,
    log_debug, log_error, log_warning, log_startup, logger
)

# ==================== DATABASE ERROR LOGGING ====================
def log_error_to_db(error_type: str, error_message: str, component: str = None,
                    severity: str = 'error', context: str = None):
    """Log error to database for AI assistant context awareness."""
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
        pass  # Don't fail if database logging fails

# Redirect print() to logging system for clean console + file logs
import builtins
_original_print = builtins.print
# CRITICAL: Save original print on builtins so other modules (license_client.py) can access it
builtins._original_print = _original_print

# Debug mode flag - loaded from database settings
_DEBUG_MODE_ENABLED = None

def is_debug_mode():
    """Check if debug mode is enabled in GUI settings (cached)."""
    global _DEBUG_MODE_ENABLED
    if _DEBUG_MODE_ENABLED is None:
        try:
            from gui_app import database as settings_db
            value = settings_db.get_setting('debug_mode', 'false')
            _DEBUG_MODE_ENABLED = value.lower() == 'true'
        except:
            _DEBUG_MODE_ENABLED = False
    return _DEBUG_MODE_ENABLED

def reset_debug_mode_cache():
    """Reset debug mode cache (call after settings change)."""
    global _DEBUG_MODE_ENABLED
    _DEBUG_MODE_ENABLED = None

def smart_print(*args, **kwargs):
    """
    Replacement for print() that:
    - Shows ONLY essential messages in console (errors, key status)
    - Logs ALL messages to rotating files for admin debugging
    - Verbose details ([CONFIG], [LICENSE]) only shown when debug mode ON
    - Captures to log monitor for AI chat assistant
    """
    message = ' '.join(str(arg) for arg in args)
    
    # Capture to log monitor for AI assistant
    try:
        from src.log_monitor import capture_log
        level = "info"
        if any(tag in message for tag in ['[ERROR]', '[CRITICAL]']):
            level = "error"
        elif '[WARNING]' in message or '⚠️' in message:
            level = "warning"
        capture_log(message, level)
    except:
        pass
    
    # Always log everything to file
    if any(tag in message for tag in ['[ERROR]', '[CRITICAL]']):
        logger.error(message)
        _original_print(message)  # Errors always shown
    elif '[WARNING]' in message or '⚠️' in message:
        logger.warning(message)
        _original_print(message)  # Warnings always shown
    elif any(tag in message for tag in ['[DEBUG]', '[API]', '[ROUTE]', '[DEDUP]', 
                                         '[LOT_MATCHER]', '[PNL_TRACKER]', '[SWING]', 
                                         '[PRE-TRADE]', '[FUNDS]']):
        # Technical debug - only to file
        logger.debug(message)
        if is_debug_mode():
            _original_print(message)
    elif any(tag in message for tag in ['[CONFIG]', '[LICENSE]']):
        # Verbose config/license details - only when debug mode ON
        logger.info(message)
        if is_debug_mode():
            _original_print(message)
    elif any(tag in message for tag in ['[Init]', '[MAIN]', '[GUI]']):
        # Essential startup status - always show (brief)
        logger.info(message)
        _original_print(message)
    elif any(tag in message for tag in ['[ALPACA]', '[Discord]', '[Webull]', '[WORKER]', 
                                         '[SYNC]', '[DATABASE]', '[STARTUP]', '[POSITION SIZE]',
                                         '[SIGNAL PARSED]', '[QUEUE]', '[PAPER TRADE]',
                                         '[ORDER', '[MULTI-BROKER]', '[RISK]', '[TASTYTRADE]',
                                         '[ROBINHOOD]', '[IBKR]', '[OPTIONS API]']):
        # Trading/broker messages - show in console
        logger.info(message)
        _original_print(message)
    else:
        # Other messages - only to log file
        logger.info(message)

# Replace built-in print
builtins.print = smart_print

log_startup("Script starting - clean logging enabled")

# Fix asyncio event loop for Windows
if platform.system() == 'Windows':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print("[STARTUP] Windows event loop policy set")

# AI Analysis imports (conditional - only if enabled)
try:
    from ai_analyzer import TradeAnalyzer, SentimentAnalyzer
    from trade_tracker import TradeTracker
    AI_IMPORTS_AVAILABLE = True
except ImportError:
    AI_IMPORTS_AVAILABLE = False
    TradeTracker = None
    print("[STARTUP] AI analyzer not available (openai package not installed)")

# Alpha Vantage option flow scanner
try:
    from alpha_vantage_scanner import AlphaVantageScanner
    ALPHA_VANTAGE_AVAILABLE = True
except ImportError:
    ALPHA_VANTAGE_AVAILABLE = False
    AlphaVantageScanner = None
    print("[STARTUP] Alpha Vantage scanner not available")

# Swing Trading Analyzer
try:
    from swing_analyzer import SwingTradeAnalyzer
    from fundamental_analyzer import FundamentalAnalyzer
    SWING_ANALYZER_AVAILABLE = True
except ImportError:
    SWING_ANALYZER_AVAILABLE = False
    SwingTradeAnalyzer = None
    print("[STARTUP] Swing trading analyzer not available")

# News Service (Finnhub API)
try:
    from news_service import NewsService
    NEWS_SERVICE_AVAILABLE = True
except ImportError:
    NEWS_SERVICE_AVAILABLE = False
    NewsService = None
    print("[STARTUP] News service not available")

# Database module for GUI control panel
try:
    # Handle PyInstaller bundled environment
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller EXE - use _MEIPASS for bundled modules
        bundle_dir = sys._MEIPASS
        gui_app_path = os.path.join(bundle_dir, 'gui_app')
        if gui_app_path not in sys.path:
            sys.path.insert(0, gui_app_path)
        if bundle_dir not in sys.path:
            sys.path.insert(0, bundle_dir)
        print(f"[STARTUP] PyInstaller mode - bundle dir: {bundle_dir}")
    else:
        # Running from source
        from pathlib import Path
        gui_app_parent = str(Path(__file__).parent.parent)
        if gui_app_parent not in sys.path:
            sys.path.insert(0, gui_app_parent)
    
    # Try importing from gui_app package first
    try:
        from gui_app import database as db
        DATABASE_MODULE_AVAILABLE = True
        print("[STARTUP] Loaded database module from gui_app package")
    except ImportError:
        # Fall back to direct import
        import database as db
        DATABASE_MODULE_AVAILABLE = True
        print("[STARTUP] Loaded database module directly")
except Exception as e:
    DATABASE_MODULE_AVAILABLE = False
    print(f"[STARTUP] Database module not available: {e}")

# Broker Manager for multi-broker support
try:
    from broker_manager import BrokerManager
    BROKER_MANAGER_AVAILABLE = True
except ImportError:
    BROKER_MANAGER_AVAILABLE = False
    print("[STARTUP] Broker manager not available")

# Load environment variables from .env file (if present)
try:
    from dotenv import load_dotenv
    load_dotenv()  # Load .env file from project root
except ImportError:
    pass  # Using system environment variables only

# ----------------------------- OPTIONAL HTTP DEBUG LOGGER -----------------------------
# Disabled to reduce console clutter - only show position updates and signals
# Uncomment the code below to enable HTTP debugging if troubleshooting API issues
# try:
#     import requests
#     _orig_request = requests.Session.request
#     def _debug_request(self, method, url, **kwargs):
#         resp = _orig_request(self, method, url, **kwargs)
#         try:
#             preview = resp.text[:400]
#         except Exception:
#             preview = "<non-text body>"
#         print(f"\n[HTTP {resp.status_code}] {method.upper()} {url}\n{preview}\n---\n")
#         return resp
#     requests.Session.request = _debug_request
#     print("[HTTP] Debug logging ENABLED")
# except Exception as _e:
#     print("[HTTP] Debug logger not enabled:", _e)

# ------------------------------------- CONFIG ----------------------------------------
from pathlib import Path
import sys
import os

# Global debug mode flag - can be toggled via GUI
DEBUG_MODE = False

def debug_print(message):
    """Print debug message only if DEBUG_MODE is enabled"""
    if DEBUG_MODE:
        print(message)

cfg = configparser.ConfigParser()

if getattr(sys, 'frozen', False):
    exe_dir = Path(sys.executable).parent
else:
    exe_dir = Path(__file__).parent.parent

config_paths = [
    exe_dir / 'config.ini',
    exe_dir / 'config.ini.example',
    Path.cwd() / 'config.ini',
    Path.cwd() / 'src' / 'config.ini',
    Path(__file__).parent.parent / 'config.ini',
    Path(__file__).parent / 'config.ini',
]

config_found = False
for config_path in config_paths:
    if config_path.exists():
        cfg.read(str(config_path))
        config_found = True
        break

# If no config.ini found, create empty sections with defaults
# This allows the app to start and be configured via GUI
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

# Function to load credentials from database (GUI configuration)
def load_credentials_from_database():
    """Load broker credentials from encrypted database storage (set via GUI)."""
    credentials = {}
    try:
        from gui_app.broker_credentials_service import get_all_credentials_for_startup
        credentials = get_all_credentials_for_startup()
    except ImportError:
        pass
    except Exception:
        pass
    return credentials

# Load credentials from database first (takes priority over config.ini)
db_credentials = load_credentials_from_database()

# Load debug mode from database
try:
    from gui_app import database as db_module
    debug_setting = db_module.get_setting('debug_mode', 'false')
    DEBUG_MODE = debug_setting == 'true'
    if DEBUG_MODE:
        print("[CONFIG] ✓ Debug mode ENABLED (from database settings)")
except Exception:
    DEBUG_MODE = False  # Default to off

# ============================================================================
# MANDATORY LICENSE VALIDATION - Cannot be bypassed
# ============================================================================

# Try to load wizard credentials first (for EXE distribution)
wizard_credentials = {}
SetupWizard = None
try:
    try:
        from src.setup_wizard import SetupWizard
    except ImportError:
        from setup_wizard import SetupWizard
    
    wizard = SetupWizard()
    if wizard.config_file.exists():
        wizard_credentials = wizard._load_credentials()
except ImportError:
    pass
except Exception:
    pass

# Import license validation functions
def _get_license_validator():
    """Get the license validation function - tries multiple import paths."""
    try:
        from src.license_manager_secure import validate_license
        return validate_license
    except ImportError:
        pass
    try:
        from license_manager_secure import validate_license
        return validate_license
    except ImportError:
        pass
    try:
        from license.client.manager import LicenseManager
        return LicenseManager.validate_license
    except ImportError:
        pass
    return None

def _get_activated_license_validator():
    """Get the activated license validator - tries multiple import paths."""
    try:
        from src.license_manager_activation import validate_activated_license
        return validate_activated_license
    except ImportError:
        pass
    try:
        from license_manager_activation import validate_activated_license
        return validate_activated_license
    except ImportError:
        pass
    return None

def _save_license_to_cache(license_key: str, machine_id: str, result: dict) -> bool:
    """Save license key to cache file for persistence across reboots."""
    import sys
    
    try:
        from pathlib import Path
        import json
        from datetime import datetime, timedelta
        
        cache_dir = Path.home() / '.discord_trading_bot'
        cache_dir.mkdir(exist_ok=True)
        cache_file = cache_dir / 'license_cache.json'
        
        # Calculate offline grace period (48 hours from now)
        offline_grace_expires = (datetime.now() + timedelta(hours=48)).isoformat()
        
        cache_data = {
            'license_key': license_key,
            'machine_id': machine_id,
            'result': result,  # Full server response
            'last_validated': datetime.now().isoformat(),
            'offline_grace_expires': offline_grace_expires,  # Add explicit grace period
            'expires_at': result.get('expires'),
            'days_remaining': result.get('days_remaining'),
            'signed_token': result.get('signed_token')
        }
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)
        
        return cache_file.exists()
    except Exception as e:
        print(f"[LICENSE] ⚠️  Could not save to cache: {e}", flush=True)
        return False

# Check for license - MANDATORY
LICENSE_VALID = False
LICENSE_DATA = {}

# Build Target Detection - prevent env bypass in distributed EXE builds
# PyInstaller sets sys.frozen when running from bundled EXE
IS_FROZEN_BUILD = getattr(sys, 'frozen', False)

# SECURITY: BUILD_TARGET verification
# Only trust BUILD_TARGET=admin if we can verify the entry point
_env_build_target = os.getenv('BUILD_TARGET', 'user').lower()
BUILD_TARGET = 'user'  # Default to user, verify before allowing admin

# Check if we're actually running from admin_server.py
_is_admin_entrypoint = False
try:
    import __main__
    main_file = getattr(__main__, '__file__', '')
    if main_file and (main_file.endswith('admin_server.py') or '/admin_server.py' in main_file or '\\admin_server.py' in main_file):
        _is_admin_entrypoint = True
except Exception:
    pass

# Only allow BUILD_TARGET=admin if running from admin entrypoint
if _env_build_target == 'admin' and _is_admin_entrypoint and not IS_FROZEN_BUILD:
    BUILD_TARGET = 'admin'
# Silent fallback to user mode - no warning needed for normal user builds

# Admin Bypass Modes - skip license check for admin/development use
# SECURITY: Admin bypass is ONLY allowed when:
# 1. Running from source (not frozen EXE) AND
# 2. BUILD_TARGET=admin is explicitly set
LICENSE_SERVER_MODE = os.getenv('LICENSE_SERVER_MODE', 'false').lower() == 'true'
ADMIN_MODE = os.getenv('ADMIN_MODE', 'false').lower() == 'true'
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '').strip()

# Block admin bypass in distributed EXE builds (user builds)
if IS_FROZEN_BUILD:
    # Frozen builds (PyInstaller EXE) ALWAYS require license - ignore env overrides
    if LICENSE_SERVER_MODE or ADMIN_MODE:
        print(f"[LICENSE] ⚠️  Admin mode env vars ignored in distributed build")
        LICENSE_SERVER_MODE = False
        ADMIN_MODE = False
    BUILD_TARGET = 'user'  # Force user mode in EXE

# If admin mode, license server mode, or admin password is set = admin bypass
# SECURITY: Only works when ALL of these conditions are met:
# 1. Running from source (not frozen EXE)
# 2. BUILD_TARGET is explicitly set to 'admin'
# 3. Admin mode env var is set
if BUILD_TARGET == 'admin' and (LICENSE_SERVER_MODE or ADMIN_MODE or ADMIN_PASSWORD) and not IS_FROZEN_BUILD:
    bypass_reason = 'License Server' if LICENSE_SERVER_MODE else 'Admin Mode' if ADMIN_MODE else 'Admin Password Set'
    print(f"[LICENSE] ✅ {bypass_reason} - license check bypassed (unlimited access)")
    LICENSE_VALID = True
    LICENSE_DATA = {'license_type': 'admin_unlimited', 'days_remaining': 36500, 'customer_id': 'Admin/Owner'}
# Admin env vars silently ignored in user builds - no warning needed

# Step 1: Check for already-activated license file
validate_activated = _get_activated_license_validator()
if validate_activated:
    try:
        is_activated_valid, activated_data = validate_activated()
        if is_activated_valid:
            print(f"[LICENSE] ✅ Found existing activated license - {activated_data['days_remaining']} days remaining")
            print(f"[LICENSE]   Customer: {activated_data['customer_id']}")
            print(f"[LICENSE]   Expires: {activated_data['expires']}")
            LICENSE_VALID = True
            LICENSE_DATA = activated_data
    except Exception as e:
        print(f"[LICENSE] Could not check activated license: {e}")

# Step 2: Check LICENSE_KEY from environment, wizard credentials, or cache
if not LICENSE_VALID:
    # Get current machine ID
    try:
        try:
            from src.machine_fingerprint import get_machine_id as get_current_machine_id
        except ImportError:
            from machine_fingerprint import get_machine_id as get_current_machine_id
        current_machine_id = get_current_machine_id()
    except Exception:
        current_machine_id = "ERROR"
    
    # Priority: BTF-format licenses first, then fallback to legacy
    env_license = os.getenv('LICENSE_KEY', '').strip()
    wizard_license = wizard_credentials.get('LICENSE_KEY', '').strip() if wizard_credentials else ''
    
    # Check license cache file for previously saved license key
    cache_license = ''
    try:
        cache_file = Path.home() / '.discord_trading_bot' / 'license_cache.json'
        if cache_file.exists():
            import json
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
                cache_license = cache_data.get('license_key', '').strip()
    except Exception:
        pass
    
    # Smart priority: ENV > CACHE > WIZARD
    if env_license.startswith('BTF-') or env_license.startswith('BT-'):
        license_key = env_license
    elif cache_license.startswith('BTF-') or cache_license.startswith('BT-'):
        license_key = cache_license
    elif wizard_license.startswith('BTF-') or wizard_license.startswith('BT-'):
        license_key = wizard_license
    elif env_license:
        license_key = env_license
    elif cache_license:
        license_key = cache_license
    elif wizard_license:
        license_key = wizard_license
    else:
        license_key = ''
    
    if license_key:
        # Try to load LicenseClient
        try:
            try:
                from src.license_client import LicenseClient
            except ImportError:
                from license_client import LicenseClient
            
            client = LicenseClient()
            
            # Try server validation FIRST for fresh data
            is_valid, license_data = client.validate_license(license_key)
            
            # Check if we got fresh data from server (not cached/offline fallback)
            is_fresh_from_server = is_valid and not license_data.get('offline_mode') and not license_data.get('cached_mode')
            
            if is_fresh_from_server:
                # Use fresh server data
                is_cached_valid = True
                cached_data = license_data
            else:
                # Server unreachable - fall back to cached validation
                is_cached_valid, cached_data = client.validate_cached(license_key)
            
            if is_cached_valid:
                # Recalculate days_remaining from expires timestamp
                days_rem = cached_data.get('days_remaining', 999)
                expires_str = cached_data.get('expires', '')
                if expires_str:
                    try:
                        from datetime import datetime
                        if 'T' in expires_str:
                            expires_dt = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
                        else:
                            expires_dt = datetime.strptime(expires_str, '%Y-%m-%d %H:%M:%S')
                        hours_remaining = (expires_dt - datetime.now()).total_seconds() / 3600
                        days_rem = max(0, int(hours_remaining / 24)) if hours_remaining > 0 else -1
                    except Exception:
                        pass
                
                print(f"[LICENSE] ✅ Valid - {days_rem} days remaining")
                
                # Block expired licenses
                if days_rem < 0:
                    print(f"[LICENSE] ❌ License EXPIRED! Please renew.")
                    try:
                        new_key = input("[LICENSE] New License Key: ").strip()
                        if new_key and (new_key.startswith('BT-') or new_key.startswith('BTF-') or new_key.startswith('TRIAL-')):
                            print(f"[LICENSE] Activating new license: {new_key[:8]}...")
                            client.clear_cache()
                            new_result = client.activate_license(new_key)
                            if new_result.get('success') or new_result.get('is_valid'):
                                print(f"[LICENSE] ✅ New license activated successfully!")
                                _save_license_to_cache(new_key, client.machine_id, new_result)
                                LICENSE_VALID = True
                                LICENSE_DATA = new_result
                                LICENSE_DATA['license_key'] = new_key
                            else:
                                print(f"[LICENSE] ❌ Activation failed: {new_result.get('error')}")
                        elif new_key:
                            print(f"[LICENSE] ❌ Invalid license format. Must start with BT-, BTF-, or TRIAL-")
                    except (EOFError, KeyboardInterrupt):
                        print(f"\n[LICENSE] No new license provided.")
                    # Do NOT set LICENSE_VALID = True for expired licenses without new key
                elif days_rem <= 7:
                    print(f"[LICENSE] ⚠️  WARNING: License expires in {days_rem} days!")
                    LICENSE_VALID = True
                    LICENSE_DATA = cached_data
                    LICENSE_DATA['license_key'] = license_key
                else:
                    LICENSE_VALID = True
                    LICENSE_DATA = cached_data
                    LICENSE_DATA['license_key'] = license_key
            else:
                # Try server validation
                is_valid, license_data = client.validate_license(license_key)
                
                if is_valid:
                    # Recalculate days_remaining from expires timestamp
                    days_rem = license_data.get('days_remaining', 999)
                    expires_str = license_data.get('expires', '')
                    if expires_str:
                        try:
                            from datetime import datetime
                            if 'T' in expires_str:
                                expires_dt = datetime.fromisoformat(expires_str.replace('Z', '+00:00'))
                            else:
                                expires_dt = datetime.strptime(expires_str, '%Y-%m-%d %H:%M:%S')
                            hours_remaining = (expires_dt - datetime.now()).total_seconds() / 3600
                            days_rem = max(0, int(hours_remaining / 24)) if hours_remaining > 0 else -1
                        except Exception:
                            pass
                    
                    print(f"[LICENSE] ✅ Valid - {days_rem} days remaining")
                    
                    # Block expired licenses
                    if days_rem < 0:
                        print(f"[LICENSE] ❌ License EXPIRED! Please renew.")
                        try:
                            new_key = input("[LICENSE] New License Key: ").strip()
                            if new_key and (new_key.startswith('BT-') or new_key.startswith('BTF-') or new_key.startswith('TRIAL-')):
                                print(f"[LICENSE] Activating new license: {new_key[:8]}...")
                                client.clear_cache()
                                new_result = client.activate_license(new_key)
                                if new_result.get('success') or new_result.get('is_valid'):
                                    print(f"[LICENSE] ✅ New license activated successfully!")
                                    _save_license_to_cache(new_key, client.machine_id, new_result)
                                    LICENSE_VALID = True
                                    LICENSE_DATA = new_result
                                    LICENSE_DATA['license_key'] = new_key
                                else:
                                    print(f"[LICENSE] ❌ Activation failed: {new_result.get('error')}")
                            elif new_key:
                                print(f"[LICENSE] ❌ Invalid license format. Must start with BT-, BTF-, or TRIAL-")
                        except (EOFError, KeyboardInterrupt):
                            print(f"\n[LICENSE] No new license provided.")
                        # Do NOT set LICENSE_VALID = True for expired licenses without new key
                    elif days_rem <= 7:
                        print(f"[LICENSE] ⚠️  WARNING: License expires in {days_rem} days!")
                        LICENSE_VALID = True
                        LICENSE_DATA = license_data
                        LICENSE_DATA['license_key'] = license_key
                    else:
                        LICENSE_VALID = True
                        LICENSE_DATA = license_data
                        LICENSE_DATA['license_key'] = license_key
                else:
                    error_msg = license_data.get('error', 'License validation failed')
                    print(f"[LICENSE] ❌ {error_msg}")
                    # Check if this is an expiry/invalid error - offer to enter new key
                    if 'expired' in error_msg.lower() or 'invalid' in error_msg.lower() or 'not found' in error_msg.lower():
                        try:
                            new_key = input("[LICENSE] New License Key: ").strip()
                            if new_key and (new_key.startswith('BT-') or new_key.startswith('BTF-') or new_key.startswith('TRIAL-')):
                                print(f"[LICENSE] Activating new license: {new_key[:8]}...")
                                client.clear_cache()
                                new_result = client.activate_license(new_key)
                                if new_result.get('success') or new_result.get('is_valid'):
                                    print(f"[LICENSE] ✅ New license activated successfully!")
                                    _save_license_to_cache(new_key, client.machine_id, new_result)
                                    LICENSE_VALID = True
                                    LICENSE_DATA = new_result
                                    LICENSE_DATA['license_key'] = new_key
                                else:
                                    print(f"[LICENSE] ❌ Activation failed: {new_result.get('error')}")
                            elif new_key:
                                print(f"[LICENSE] ❌ Invalid license format. Must start with BT-, BTF-, or TRIAL-")
                        except (EOFError, KeyboardInterrupt):
                            print(f"\n[LICENSE] No new license provided.")
                    else:
                        print("[LICENSE] Your license has expired or is invalid.")
        except Exception as e:
            print(f"[LICENSE] Server validation failed: {e}")
            # Fall back to local validation ONLY for non-server keys
            # BT- and BTF- prefixed keys are SERVER-ONLY and require internet connection
            if license_key.startswith('BT-') or license_key.startswith('BTF-'):
                print(f"[LICENSE] ❌ Server connection required for this license type")
                print(f"[LICENSE] Please check your internet connection and try again")
            else:
                validate_license = _get_license_validator()
                if validate_license:
                    try:
                        is_valid, license_data = validate_license(license_key)
                        if is_valid:
                            print(f"[LICENSE] ✅ License valid (local) - {license_data['days_remaining']} days remaining")
                            LICENSE_VALID = True
                            LICENSE_DATA = license_data
                            LICENSE_DATA['license_key'] = license_key
                    except Exception as local_err:
                        print(f"[LICENSE] ❌ Local validation error: {local_err}")
    else:
        print("[LICENSE] ❌ No LICENSE_KEY found")

# Step 3: If no valid license, try setup wizard (for EXE) or block startup (for Replit)
if not LICENSE_VALID:
    import sys
    print("[LICENSE] ❌ No valid license found")
    
    # Check if setup wizard is available (EXE mode)
    SETUP_WIZARD_AVAILABLE = False
    if SetupWizard is None:
        try:
            try:
                from src.setup_wizard import SetupWizard
                print("[LICENSE] ✓ Imported SetupWizard from src.setup_wizard")
            except ImportError as e1:
                print(f"[LICENSE] src.setup_wizard failed: {e1}")
                try:
                    from setup_wizard import SetupWizard
                    print("[LICENSE] ✓ Imported SetupWizard from setup_wizard")
                except ImportError as e2:
                    print(f"[LICENSE] setup_wizard failed: {e2}")
                    raise ImportError(f"Both import paths failed")
            SETUP_WIZARD_AVAILABLE = True
        except ImportError as final_err:
            print(f"[LICENSE] ⚠️  SetupWizard not available: {final_err}")
    else:
        print("[LICENSE] ✓ SetupWizard already loaded")
        SETUP_WIZARD_AVAILABLE = True
    
    print(f"[LICENSE] SETUP_WIZARD_AVAILABLE = {SETUP_WIZARD_AVAILABLE}")
    
    if SETUP_WIZARD_AVAILABLE:
        # EXE mode - prompt user for license via setup wizard
        print()
        print("=" * 60)
        print("  LICENSE REQUIRED")
        print("=" * 60)
        print()
        print("  Your license is missing, expired, or invalid.")
        print("  Please enter a valid license to continue.")
        print()
        print("=" * 60)
        print()
        
        # Run setup wizard license step only
        try:
            try:
                from src.setup_wizard import LICENSE_MODE
            except ImportError:
                from setup_wizard import LICENSE_MODE
            
            if LICENSE_MODE == 'offline':
                try:
                    from src.license_manager_secure import validate_license as validate_license_secure, get_current_machine_id
                except ImportError:
                    from license_manager_secure import validate_license as validate_license_secure, get_current_machine_id
            
            print("Choose your license option:")
            print()
            print("  [TRIAL]        - Start a FREE 7-day trial (no purchase required)")
            print("  [SUBSCRIPTION] - Enter your purchased license key")
            print()
            
            license_choice = input("Type 'trial' for free trial or 'sub' to enter license key: ").strip().lower()
            print()
            
            if license_choice in ('trial', 't', '1'):
                # REQUEST TRIAL FROM LICENSE SERVER
                print("🎉 REQUESTING FREE 7-DAY TRIAL FROM SERVER...")
                print()
                
                try:
                    try:
                        from src.license_client import LicenseClient
                    except ImportError:
                        try:
                            from license_client import LicenseClient
                        except ImportError:
                            print("[ERROR] license_client.py not found!")
                            print("[INFO] Make sure license_client.py is in the src/ folder")
                            raise SystemExit("Setup cancelled - license client missing")
                    
                    client = LicenseClient()
                    print(f"[LICENSE] Machine ID: {client.machine_id}")
                    print(f"[LICENSE] Server URL: {client.server_url}")
                    print(f"[LICENSE] Contacting license server...")
                    
                    result = client.request_trial()
                    print(f"[LICENSE] Server response: {result}")
                    
                    if result.get('success'):
                        trial_license_key = result['license_key']
                        print()
                        print("✅ FREE TRIAL ACTIVATED SUCCESSFULLY!")
                        print(f"   ✓ License: {trial_license_key}")
                        print(f"   ✓ Trial Period: 7 days")
                        print(f"   ✓ Expires: {result.get('expires_at', 'N/A')}")
                        print()
                        
                        # Save license key to cache file for persistence
                        trial_result = {
                            'is_valid': True,
                            'success': True,
                            'expires': result.get('expires_at'),
                            'days_remaining': result.get('days_remaining', 7),
                            'license_type': 'trial',
                            'signed_token': result.get('signed_token')
                        }
                        _save_license_to_cache(trial_license_key, client.machine_id, trial_result)
                        
                        # Also save to wizard credentials file (backup)
                        try:
                            wizard = SetupWizard()
                            if wizard.config_file.exists():
                                existing_creds = wizard._load_credentials()
                            else:
                                existing_creds = {}
                            existing_creds['LICENSE_KEY'] = trial_license_key
                            wizard._save_credentials(existing_creds)
                            print("[LICENSE] ✓ License saved to wizard credentials")
                        except Exception as save_err:
                            print(f"[LICENSE] ⚠️  Could not save to wizard: {save_err}")
                        
                        LICENSE_VALID = True
                        LICENSE_DATA = {
                            'license_type': 'trial',
                            'days_remaining': result.get('days_remaining', 7),
                            'expires': result.get('expires_at'),
                            'customer_id': 'trial_user'
                        }
                    else:
                        error_msg = result.get('error', 'Trial request failed')
                        print(f"❌ {error_msg}")
                        if 'already' in error_msg.lower():
                            print("\n[INFO] This machine has already used a trial.")
                            print("[INFO] Please purchase a license to continue.")
                        raise SystemExit("Setup cancelled - could not activate trial")
                        
                except SystemExit:
                    raise
                except Exception as e:
                    import traceback
                    print(f"❌ Trial activation error: {e}")
                    print(f"[DEBUG] Full error: {traceback.format_exc()}")
                    raise SystemExit("Setup cancelled - could not connect to license server")
            
            elif license_choice in ('sub', 'subscription', 's', '2'):
                # SUBSCRIPTION LICENSE - ACTIVATE VIA LICENSE SERVER
                try:
                    try:
                        from src.license_client import LicenseClient
                    except ImportError:
                        from license_client import LicenseClient
                    
                    client = LicenseClient()
                    
                    print()
                    print("╔" + "=" * 58 + "╗")
                    print("║" + " " * 58 + "║")
                    print("║" + "  🔑 LICENSE ACTIVATION".center(58) + "║")
                    print("║" + " " * 58 + "║")
                    print("║" + f"  Machine ID: {client.machine_id}".center(58) + "║")
                    print("║" + " " * 58 + "║")
                    print("╚" + "=" * 58 + "╝")
                    print()
                    
                    license_valid = False
                    while not license_valid:
                        new_license_key = input("Enter your license key: ").strip()
                        print(f"[LICENSE] DEBUG: Received key: {new_license_key[:10]}...", flush=True)
                        import sys
                        sys.stdout.flush()
                        
                        if not new_license_key:
                            print("❌ License key cannot be empty")
                            retry = input("Try again? (yes/no): ").strip().lower()
                            if retry not in ('yes', 'y'):
                                raise SystemExit("Setup cancelled - license key required")
                            continue
                        
                        _early_print("[LICENSE] Activating with license server...", flush=True)
                        sys.stdout.flush()
                        result = client.activate_license(new_license_key)
                        _early_print(f"[LICENSE] Server response: success={result.get('success')}, is_valid={result.get('is_valid')}", flush=True)
                        sys.stdout.flush()
                        
                        if result.get('success') or result.get('is_valid'):
                            _early_print("", flush=True)
                            _early_print("╔════════════════════════════════════════════════════════════╗", flush=True)
                            _early_print("║       ✅ LICENSE ACTIVATED SUCCESSFULLY!                   ║", flush=True)
                            _early_print("╠════════════════════════════════════════════════════════════╣", flush=True)
                            _early_print(f"║  License Type: {str(result.get('license_type', 'subscription')).ljust(43)}║", flush=True)
                            _early_print(f"║  Expires: {str(result.get('expires', 'N/A')).ljust(48)}║", flush=True)
                            _early_print(f"║  Days Remaining: {str(result.get('days_remaining', 'N/A')).ljust(41)}║", flush=True)
                            _early_print("╚════════════════════════════════════════════════════════════╝", flush=True)
                            _early_print("", flush=True)
                            sys.stdout.flush()
                            
                            # Save license key to cache file for persistence
                            print("[LICENSE] About to save to cache...", flush=True)
                            cache_saved = _save_license_to_cache(new_license_key, client.machine_id, result)
                            print(f"[LICENSE] Cache save result: {cache_saved}", flush=True)
                            
                            # Also save to wizard credentials file (backup)
                            try:
                                wizard = SetupWizard()
                                if wizard.config_file.exists():
                                    existing_creds = wizard._load_credentials()
                                else:
                                    existing_creds = {}
                                existing_creds['LICENSE_KEY'] = new_license_key
                                wizard._save_credentials(existing_creds)
                                print(f"[LICENSE] ✓ License saved to wizard credentials")
                            except Exception as wiz_err:
                                print(f"[LICENSE] ⚠️  Could not save to wizard: {wiz_err}")
                            
                            LICENSE_VALID = True
                            LICENSE_DATA = {
                                'license_type': result.get('license_type', 'subscription'),
                                'days_remaining': result.get('days_remaining', 999),
                                'expires': result.get('expires'),
                                'customer_id': result.get('customer_id', 'subscriber')
                            }
                            license_valid = True
                        else:
                            _early_print("", flush=True)
                            _early_print("╔════════════════════════════════════════════════════════════╗", flush=True)
                            _early_print("║       ❌ LICENSE ACTIVATION FAILED                         ║", flush=True)
                            _early_print("╠════════════════════════════════════════════════════════════╣", flush=True)
                            _early_print(f"║  Error: {str(result.get('error', 'Unknown error')).ljust(50)}║", flush=True)
                            _early_print(f"║  Machine ID: {client.machine_id.ljust(45)}║", flush=True)
                            _early_print("╚════════════════════════════════════════════════════════════╝", flush=True)
                            _early_print("", flush=True)
                            sys.stdout.flush()
                            retry = input("Try again? (yes/no): ").strip().lower()
                            if retry not in ('yes', 'y'):
                                raise SystemExit("Setup cancelled - valid license required")
                                
                except Exception as e:
                    print(f"❌ License activation error: {e}")
                    raise SystemExit("Setup cancelled - could not connect to license server")
            else:
                print(f"❌ Invalid choice: '{license_choice}'")
                print("   Please type 'trial' for free trial or 'sub' for subscription license.")
                raise SystemExit("Setup cancelled - invalid license option")
                
        except SystemExit:
            raise
        except Exception as e:
            print(f"❌ License setup error: {e}")
            raise SystemExit("Setup cancelled - license setup failed")
    else:
        # Replit mode or no setup wizard - show error
        print()
        print("=" * 60)
        print("  LICENSE REQUIRED - Bot cannot start without a license")
        print("=" * 60)
        print()
        print("  To use this bot, you need a valid license key.")
        print()
        print("  HOW TO ADD YOUR LICENSE:")
        print("  -------------------------")
        print("  Replit: Go to 'Secrets' tab and add LICENSE_KEY")
        print("  Windows: Set LICENSE_KEY environment variable or use Setup Wizard")
        print()
        print("  GET A LICENSE:")
        print("  ---------------")
        print("  Contact the bot provider for a trial or subscription.")
        print()
        print("=" * 60)
        
        # On Windows EXE, pause so user can read the error before window closes
        if getattr(sys, 'frozen', False) and sys.platform == 'win32':
            print()
            input("Press Enter to exit...")
        
        raise SystemExit("ERROR: Valid license required to run this bot.")

# Set API keys as environment variables if present in wizard credentials
for api_key in ['OPENAI_API_KEY', 'ALPHA_VANTAGE_API_KEY', 'FINNHUB_API_KEY']:
    if wizard_credentials.get(api_key):
        os.environ[api_key] = wizard_credentials[api_key]
        print(f"[CONFIG] ✓ {api_key} loaded from wizard")

# Discord - Load from setup wizard, environment variables, or config
print("[CONFIG] Loading Discord settings...")

try:
    # Priority: 1) Database (GUI), 2) Setup wizard, 3) Environment variables, 4) config.ini
    USER_TOKEN = db_credentials.get('DISCORD_USER_TOKEN', '').strip()
    
    if not USER_TOKEN:
        USER_TOKEN = wizard_credentials.get('DISCORD_USER_TOKEN') or os.getenv('DISCORD_USER_TOKEN', '').strip()
    
    if not USER_TOKEN:
        USER_TOKEN = cfg['discord'].get('discord_user_token', '').strip()
    
    if not USER_TOKEN:
        # Check if running with GUI - wait for credentials to be set via GUI
        if DATABASE_MODULE_AVAILABLE:
            print("\n[CONFIG] ⚠️  No Discord token found.")
            print("[CONFIG] Please configure your Discord token in the Settings page of the web GUI.")
            print("[CONFIG] The bot will start but won't connect to Discord until configured.")
            print("[CONFIG] Access the GUI at: http://localhost:<GUI_PORT>/settings (default port: 5000, or set GUI_PORT env var)")
            USER_TOKEN = None  # Allow startup without token - will be set via GUI
        else:
            # No GUI - try setup wizard as last resort
            try:
                if SetupWizard is None:
                    try:
                        from src.setup_wizard import SetupWizard
                    except ImportError:
                        from setup_wizard import SetupWizard
                print("\n[SETUP] No credentials found. Running first-time setup wizard...")
                print()
                wizard = SetupWizard()
                wizard_credentials = wizard.run()
                USER_TOKEN = wizard_credentials['DISCORD_USER_TOKEN']
                
                # Set API keys as environment variables if present in wizard credentials
                for api_key in ['OPENAI_API_KEY', 'ALPHA_VANTAGE_API_KEY', 'FINNHUB_API_KEY']:
                    if api_key in wizard_credentials and wizard_credentials[api_key]:
                        os.environ[api_key] = wizard_credentials[api_key]
                        print(f"[CONFIG] ✓ {api_key} loaded from wizard")
            except Exception as e:
                raise SystemExit(f"ERROR: Could not obtain Discord token. Please set DISCORD_USER_TOKEN environment variable or run setup wizard. Error: {e}")
    
    # Set API keys from database credentials if available
    for api_key in ['OPENAI_API_KEY', 'ALPHA_VANTAGE_API_KEY', 'FINNHUB_API_KEY']:
        if db_credentials.get(api_key):
            os.environ[api_key] = db_credentials[api_key]
            print(f"[CONFIG] ✓ {api_key} loaded from database")
    
    if USER_TOKEN:
        # Clean and validate token
        USER_TOKEN = USER_TOKEN.strip()
        print(f"[CONFIG] ✓ Discord token loaded (length: {len(USER_TOKEN)} chars)")
        if len(USER_TOKEN) > 35:
            print(f"[CONFIG]   Token starts with: {USER_TOKEN[:20]}...")
            print(f"[CONFIG]   Token ends with: ...{USER_TOKEN[-15:]}")
    else:
        print("[CONFIG] Discord token not configured - will be set via GUI")
    
    # Load channel IDs from database first, then fall back to config.ini
    CHANNEL_IDS = []
    if DATABASE_MODULE_AVAILABLE:
        try:
            channels = db.get_channels()
            if channels:
                for ch in channels:
                    ch_id = ch.get('discord_channel_id')
                    if ch_id:
                        try:
                            # Only add numeric Discord channel IDs (skip GUI_EXEC, etc.)
                            CHANNEL_IDS.append(int(ch_id))
                        except (ValueError, TypeError):
                            # Skip non-numeric channel IDs like 'GUI_EXEC'
                            pass
                print(f"[CONFIG] ✓ Loaded {len(CHANNEL_IDS)} channels from database")
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load channels from database: {e}")
    
    if not CHANNEL_IDS:
        channel_ids_str = cfg['discord'].get('channel_ids', '').strip()
        CHANNEL_IDS = [int(x.strip()) for x in channel_ids_str.split(',') if x.strip()]
    
    # Load Discord settings from database (GUI) first, fallback to config.ini
    DISCORD_SETTINGS_SOURCE = 'config.ini'
    ALLOWED_AUTHOR_IDS = []
    ALLOWED_GUILD_IDS = []
    DISCOVERY_MODE = False
    ALLOW_SELF_MESSAGES = False
    DB_OPTION_PATTERN = None
    DB_STOCK_PATTERN = None
    
    if DATABASE_MODULE_AVAILABLE:
        try:
            discord_settings = db.get_discord_settings()
            ALLOW_SELF_MESSAGES = discord_settings.get('allow_self_messages', False)
            DISCOVERY_MODE = discord_settings.get('discovery_mode', False)
            DB_OPTION_PATTERN = discord_settings.get('option_pattern', '').strip()
            DB_STOCK_PATTERN = discord_settings.get('stock_pattern', '').strip()
            
            # Parse allowed author IDs from database
            author_ids_str = discord_settings.get('allowed_author_ids', '').strip()
            if author_ids_str:
                ALLOWED_AUTHOR_IDS = [int(x.strip()) for x in author_ids_str.split(',') if x.strip()]
            
            # Parse allowed guild IDs from database
            guild_ids_str = discord_settings.get('allowed_guild_ids', '').strip()
            if guild_ids_str:
                ALLOWED_GUILD_IDS = [int(x.strip()) for x in guild_ids_str.split(',') if x.strip()]
            
            DISCORD_SETTINGS_SOURCE = 'DATABASE'
            print(f"[CONFIG] ✓ Loaded Discord settings from DATABASE (GUI Settings)")
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load Discord settings from database: {e}")
    
    # Fallback to config.ini if database settings not available
    if DISCORD_SETTINGS_SOURCE == 'config.ini':
        # Load allowed author IDs
        author_ids_str = cfg['discord'].get('allowed_author_ids', '').strip()
        if author_ids_str:
            ALLOWED_AUTHOR_IDS = [int(x.strip()) for x in author_ids_str.split(',') if x.strip()]
        
        # Load allowed guild IDs
        guild_ids_str = cfg['discord'].get('allowed_guild_ids', '').strip()
        if guild_ids_str:
            ALLOWED_GUILD_IDS = [int(x.strip()) for x in guild_ids_str.split(',') if x.strip()]
        
        DISCOVERY_MODE = cfg['discord'].getboolean('discovery_mode', fallback=False)
        ALLOW_SELF_MESSAGES = cfg['discord'].getboolean('allow_self_messages', fallback=False)
    
    print(f"[CONFIG] Discord channels: {CHANNEL_IDS if CHANNEL_IDS else '(None - add via GUI)'}")
    print(f"[CONFIG] Allowed authors: {ALLOWED_AUTHOR_IDS if ALLOWED_AUTHOR_IDS else 'ALL'}")
    print(f"[CONFIG] Allowed guilds: {ALLOWED_GUILD_IDS if ALLOWED_GUILD_IDS else 'ALL'}")
    print(f"[CONFIG] Discovery mode: {DISCOVERY_MODE}")
    print(f"[CONFIG] Allow self messages: {ALLOW_SELF_MESSAGES}")
    print(f"[CONFIG]   - Source: {DISCORD_SETTINGS_SOURCE}")
except KeyError as e:
    raise SystemExit(f"Missing [discord] key in config.ini: {e}")

# Signals - LOWERCASE C/P FIX + MARKET ORDER SUPPORT
print("[CONFIG] Loading signal patterns...")

# Updated patterns to support market orders: "@ m" or "@m" means market order
# Group 7 captures either a price (e.g., "0.28") or "m"/"M" for market
# Pattern now supports both "3 c" and "3c" formats (optional space between strike and option type)
FLEXIBLE_OPT_PATTERN = r'^(BTO|STC)\s+(?:(\d+)\s+)?\$?([A-Za-z]+)\s+\$?([\d.]+)\s*([CPcp])\s*(\d{1,2}/\d{1,2})\s*@?\s*([\d.]+|[mM])'
DEFAULT_STK_PATTERN = r'(?:[\U0001F300-\U0001F9FF✅🟢🔴⚠️❌]+)?\s*\*{0,2}(BTO|STC)\*{0,2}\s+(?:(\d+)\s+)?\$?([A-Za-z]+)\s*@?\s*\$?([\d.]+|[mM])\*{0,2}'

# Alternate pattern for formats like: 🟢**BTO $RKT | 21.2 C JAN/16 .56**
# Handles: emoji, markdown **, $SYMBOL, | separator, month names (JAN/FEB/etc)
MONTH_NAMES = {'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04', 'MAY': '05', 'JUN': '06',
               'JUL': '07', 'AUG': '08', 'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'}
ALT_OPT_PATTERN = r'[🟢🔴]?\*{0,2}(BTO|STC)\s+\$([A-Za-z]+)\s*\|\s*([\d.]+)\s*([CPcp])\s+([A-Za-z]{3}|\d{1,2})/(\d{1,2})\s+\.?([\d.]+)'

# Steel-style patterns for formats like:
# BTO: :green_alert: COIN | $290 C 5.14
#      TSLA | 470 C 5.15 next week (no prefix)
# STC: :SirenRed: AAPL | 1.82 OUT HALF SL ENTRY ✅
#      :SirenRed: PLTR | 1.33 OUT 1/3 ✅
#      TSLA 5.03 OUT (simple format)

# BTO pattern - with or without :green_alert: prefix
# Groups: (symbol, strike, opt_type, price, expiry_text)
# Note: [$] is used instead of \$ because $ is a regex metacharacter
STEEL_BTO_PATTERN = r'(?::green_alert:|:greencheckmark:)?\s*([A-Za-z]+)\s*[|]\s*[$]?([0-9.]+)\s*([CPcp])\s+([0-9.]+)\s*(NEXT\s*WEEK|THIS\s*WEEK|TOMORROW|[0-9]{1,2}/[0-9]{1,2})?'

# STC pattern with :SirenRed: prefix - handles OUT HALF, OUT 1/3, OUT ALL, or just OUT
# Groups: (symbol, price, exit_type)
# Note: OUT alone (with any trailing text) means exit all
STEEL_STC_PATTERN = r':SirenRed:\s*([A-Za-z]+)\s*[|]\s*([0-9.]+)\s*(OUT\s*HALF|OUT\s*ALL\s*BUT\s*[0-9]+|OUT\s*ALL|OUT\s*[0-9]+/[0-9]+|SL\s*ENTRY|OUT(?=\s|$))?'

# Extended STEEL_STC with optional STC prefix before symbol
# Handles: :SirenRed: STC $RKT | .70 OUT ALL ✅
# Groups: (symbol, price, exit_type)
STEEL_STC_WITH_PREFIX_PATTERN = r':SirenRed:\s*STC\s*\$?([A-Za-z]+)\s*[|]\s*([0-9.]+)\s*(OUT\s*HALF|OUT\s*ALL\s*BUT\s*[0-9]+|OUT\s*ALL|OUT\s*[0-9]+/[0-9]+|SL\s*ENTRY|OUT(?=\s|$))?'

# STC with qty and @ price format (no pipe separator)
# Handles: :SirenRed: STC 4 RKT @ .75 SL .70 ON LAST ✅
# Groups: (qty, symbol, price)
STC_QTY_AT_PATTERN = r':?SirenRed:?\s*STC\s+(\d+)\s+\$?([A-Za-z]+)\s*@\s*\.?([0-9.]+)'

# Extended entry with strike, price, then month name + day (unusual order)
# Handles: :green_alert: TSLA | $492.5 10.10 JAN 2ND
# Groups: (symbol, strike, price, month_name, day)
STEEL_BTO_EXTENDED_PATTERN = r'(?::green_alert:|:greencheckmark:)?\s*([A-Za-z]+)\s*[|]\s*[$]?([0-9.]+)\s+([0-9.]+)\s+([A-Za-z]{3})\s+([0-9]+)(?:ST|ND|RD|TH)?'

# Simple STC pattern: SYMBOL PRICE OUT (no prefix)
# Groups: (symbol, price)
SIMPLE_STC_PATTERN = r'^([A-Za-z]+)\s+([0-9.]+)\s+OUT'

# SirenRed with PRICE only (no symbol) - for closing most recent position
# :SirenRed: 4.67 OUT ✅ or :SirenRed: $4.20 OUT 3/4 ✅
# Groups: (price, exit_type)
SIRENRED_PRICE_STC_PATTERN = r':SirenRed:\s*[$]?([0-9.]+)\s+(OUT\s*HALF|OUT\s*ALL\s*BUT\s*[0-9]+|OUT\s*ALL|OUT\s*[0-9]+/[0-9]+|OUT(?=\s|$))'

# Price-only STC pattern: 5.38 out all but 1, 4.20 out all, etc (no prefix, no symbol)
# Groups: (price, exit_type)
PRICE_ONLY_STC_PATTERN = r'^[$]?([0-9.]+)\s+(out\s*half|out\s*all\s*but\s*[0-9]+|out\s*all|out\s*[0-9]+/[0-9]+|out(?=\s|$))'

# JC-style pattern: BTO $QQQ $627c 12/10 .77
# Supports strike+optType combined: $627c, $619p
# Groups: (direction, symbol, strike, opt_type, month, day, price)
JC_OPT_PATTERN = r'(BTO|STC)\s+[$]?([A-Za-z]+)\s+[$]?([0-9.]+)([CPcp])\s+([0-9]{1,2})/([0-9]{1,2})\s+[.]?([0-9.]+)'

# SPX/NDX shorthand patterns (0DTE style)
# Format 1: Just strike+type - "6900c" → BTO 1 SPX 6900C <today> @ m
# Format 2: With action - "BTO 25 6900c" or "STC 25 15000p"
# Format 3: Action + strike only - "STC 6900c" → STC 1 SPX 6900C <today> @ m
# Strike >= 10000 = NDX, Strike < 10000 = SPX
# Groups: (action, qty, strike, opt_type)
SPX_NDX_SHORTHAND_PATTERN = r'^(?:(BTO|STC)\s+)?(?:(\d+)\s+)?(\d{4,5})([CPcp])$'

# Waxui-style patterns (LOTTO alerts)
# Entry format: SPX here 12/05 6880C Avg. 4.00 or "SPX here 12/13 6100C Avg .35"
# Groups: (symbol, month, day, strike, opt_type, price)
# Price pattern: supports "4.00", ".35", "0.35" formats
WAXUI_ENTRY_PATTERN = r'([A-Za-z]+)\s+here\s+(\d{1,2})/(\d{1,2})\s+(\d+(?:\.\d+)?)\s*([CPcp])\s+[Aa]vg\.?\s*(\.?\d+\.?\d*)'

# Trim format: "Trim SPX here" or "Trim SPX here at $5.50" - partial exit
# Groups: (symbol)
WAXUI_TRIM_PATTERN = r'[Tt]rim\s+([A-Za-z]+)\s+here'

# Close format: "Closed SPX here" or "Close SPX here" - full exit
# Groups: (symbol)
WAXUI_CLOSE_PATTERN = r'[Cc]lose[d]?\s+([A-Za-z]+)\s+here'

def calculate_next_week_expiry():
    """Calculate next Friday's date for 'NEXT WEEK' expiry"""
    from datetime import datetime, timedelta
    today = datetime.now()
    # Find days until next Friday (weekday 4)
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        days_until_friday = 7  # If today is Friday, get NEXT Friday
    # For "NEXT WEEK", add 7 more days to get the Friday after this one
    next_friday = today + timedelta(days=days_until_friday + 7)
    return next_friday.strftime("%m/%d")

def calculate_this_week_expiry():
    """Calculate this Friday's date for 'THIS WEEK' expiry"""
    from datetime import datetime, timedelta
    today = datetime.now()
    days_until_friday = (4 - today.weekday()) % 7
    if days_until_friday == 0:
        # Today is Friday, use today
        this_friday = today
    else:
        this_friday = today + timedelta(days=days_until_friday)
    return this_friday.strftime("%m/%d")

def calculate_tomorrow_expiry():
    """Calculate tomorrow's date for 'TOMORROW' expiry"""
    from datetime import datetime, timedelta
    tomorrow = datetime.now() + timedelta(days=1)
    return tomorrow.strftime("%m/%d")

# Use database patterns if available, otherwise fallback to config.ini or defaults
if DB_OPTION_PATTERN:
    OPT_REGEX = re.compile(DB_OPTION_PATTERN, re.IGNORECASE | re.MULTILINE)
    print(f"[CONFIG] ✓ Option pattern loaded from DATABASE")
else:
    OPT_REGEX = re.compile(cfg.get('signals', 'pattern', fallback=FLEXIBLE_OPT_PATTERN), re.IGNORECASE | re.MULTILINE)

if DB_STOCK_PATTERN:
    STK_REGEX = re.compile(DB_STOCK_PATTERN, re.IGNORECASE | re.MULTILINE)
    print(f"[CONFIG] ✓ Stock pattern loaded from DATABASE")
else:
    STK_REGEX = re.compile(cfg.get('signals', 'stock_pattern', fallback=DEFAULT_STK_PATTERN), re.IGNORECASE | re.MULTILINE)

print(f"[CONFIG] ✓ Option pattern: {OPT_REGEX.pattern}")
print(f"[CONFIG] ✓ Stock pattern: {STK_REGEX.pattern}")
print(f"[CONFIG] ✓ IGNORECASE flag: {bool(OPT_REGEX.flags & re.IGNORECASE)}")
print(f"[CONFIG] ✓ Market order support: @ m or @m")

# Auto-quantity calculation when quantity not specified
def get_trading_settings():
    """Get trading settings via SettingsService (falls back to database/config.ini)"""
    if SETTINGS_SERVICE_AVAILABLE:
        try:
            settings = get_trading_settings_via_service()
            print(f"[CONFIG] ✓ Trading settings loaded via SettingsService")
            return settings
        except Exception as e:
            print(f"[CONFIG] Warning: SettingsService failed, falling back: {e}")
    
    if DATABASE_MODULE_AVAILABLE:
        try:
            settings = db.get_trading_settings()
            return {
                'max_position_size': settings['max_position_size']
            }
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load trading settings from database: {e}")
    
    # Fallback to config.ini
    return {
        'max_position_size': cfg.getfloat('signals', 'max_position_size', fallback=200.0)
    }

_trading_settings = get_trading_settings()
MAX_POSITION_SIZE = _trading_settings['max_position_size']
if MAX_POSITION_SIZE <= 0:
    raise SystemExit("ERROR: max_position_size must be positive")
print(f"[CONFIG] ✓ Max position size (auto-qty): ${MAX_POSITION_SIZE}")
print(f"[CONFIG]   - Source: {'DATABASE' if DATABASE_MODULE_AVAILABLE else 'config.ini'}")

# Price Slippage Protection - Intelligent order management
print("[CONFIG] Loading price slippage protection settings...")

# Helper function to get slippage settings (SettingsService > database > config.ini)
def get_slippage_settings():
    """Get slippage settings via SettingsService (falls back to database/config.ini)"""
    if SETTINGS_SERVICE_AVAILABLE:
        try:
            settings = get_slippage_settings_via_service()
            return settings
        except Exception as e:
            print(f"[CONFIG] Warning: SettingsService slippage failed: {e}")
    
    if DATABASE_MODULE_AVAILABLE:
        try:
            settings = db.get_slippage_settings()
            return {
                'enabled': settings['enabled'],
                'threshold_percent': settings['threshold_percent']
            }
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load slippage settings from database: {e}")
    
    # Fallback to config.ini
    return {
        'enabled': cfg.getboolean('price_slippage', 'enable_slippage_protection', fallback=True),
        'threshold_percent': cfg.getfloat('price_slippage', 'high_slippage_threshold_percent', fallback=10.0)
    }

# Load initial slippage settings
_slippage_settings = get_slippage_settings()
ENABLE_SLIPPAGE_PROTECTION = _slippage_settings['enabled']
MAX_IMMEDIATE_SLIPPAGE_PCT = cfg.getfloat('price_slippage', 'max_immediate_slippage_percent', fallback=5.0)
HIGH_SLIPPAGE_THRESHOLD_PCT = _slippage_settings['threshold_percent']
SLIPPAGE_WAIT_MINUTES = cfg.getint('price_slippage', 'wait_time_minutes', fallback=5)
SLIPPAGE_RETRY_INTERVAL = cfg.getint('price_slippage', 'retry_interval_seconds', fallback=30)
ALLOW_ORDER_WHEN_NO_QUOTE = cfg.getboolean('price_slippage', 'allow_when_no_quote', fallback=True)

if ENABLE_SLIPPAGE_PROTECTION:
    print(f"[CONFIG] ✓ Price slippage protection ENABLED")
    print(f"[CONFIG]   - Immediate fill threshold: ±{MAX_IMMEDIATE_SLIPPAGE_PCT}%")
    print(f"[CONFIG]   - High slippage threshold: ±{HIGH_SLIPPAGE_THRESHOLD_PCT}%")
    print(f"[CONFIG]   - Wait time: {SLIPPAGE_WAIT_MINUTES} minutes")
    print(f"[CONFIG]   - Retry interval: {SLIPPAGE_RETRY_INTERVAL} seconds")
    print(f"[CONFIG]   - Allow order when no quote: {ALLOW_ORDER_WHEN_NO_QUOTE}")
    print(f"[CONFIG]   - Source: {'DATABASE' if DATABASE_MODULE_AVAILABLE else 'config.ini'}")
else:
    print(f"[CONFIG] Price slippage protection DISABLED")

# Risk Management - Profit targets, stop loss, trailing stops
print("[CONFIG] Loading risk management settings...")

def get_risk_management_settings():
    """Get risk settings via SettingsService (falls back to database/config.ini)"""
    if SETTINGS_SERVICE_AVAILABLE:
        try:
            settings = get_risk_settings_via_service()
            return settings
        except Exception as e:
            print(f"[CONFIG] Warning: SettingsService risk failed: {e}")
    
    if DATABASE_MODULE_AVAILABLE:
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
    
    # Fallback to config.ini
    return {
        'enabled': cfg.getboolean('risk_management', 'enable_risk_management', fallback=False),
        'profit_target_percent': cfg.getfloat('risk_management', 'profit_target_percent', fallback=0.0),
        'stop_loss_percent': cfg.getfloat('risk_management', 'stop_loss_percent', fallback=0.0),
        'trailing_stop_percent': cfg.getfloat('risk_management', 'trailing_stop_percent', fallback=0.0)
    }

_risk_settings = get_risk_management_settings()
ENABLE_RISK_MGMT = _risk_settings['enabled']
PROFIT_TARGET_PCT = _risk_settings['profit_target_percent']
STOP_LOSS_PCT = _risk_settings['stop_loss_percent']
TRAILING_STOP_PCT = _risk_settings['trailing_stop_percent']
MONITORING_INTERVAL = cfg.getint('risk_management', 'monitoring_interval', fallback=30)
TRAILING_ACTIVATION_PCT = cfg.getfloat('risk_management', 'trailing_stop_activation_percent', fallback=0.0)

if ENABLE_RISK_MGMT:
    print(f"[CONFIG] ✓ Risk management ENABLED")
    print(f"[CONFIG]   - Monitoring interval: {MONITORING_INTERVAL}s")
    print(f"[CONFIG]   - Profit target: {PROFIT_TARGET_PCT}%")
    print(f"[CONFIG]   - Stop loss: {STOP_LOSS_PCT}%")
    print(f"[CONFIG]   - Trailing stop: {TRAILING_STOP_PCT}% (activates after {TRAILING_ACTIVATION_PCT}% gain)")
    print(f"[CONFIG]   - Source: {'DATABASE' if DATABASE_MODULE_AVAILABLE else 'config.ini'}")
else:
    print(f"[CONFIG] Risk management DISABLED")

# AI Analysis - Post-trade analysis and sentiment tracking
print("[CONFIG] Loading AI analysis settings...")

def get_ai_analysis_settings():
    """Get AI settings via SettingsService (falls back to database/config.ini)"""
    if SETTINGS_SERVICE_AVAILABLE:
        try:
            settings = get_ai_settings_via_service()
            return settings
        except Exception as e:
            print(f"[CONFIG] Warning: SettingsService AI failed: {e}")
    
    if DATABASE_MODULE_AVAILABLE:
        try:
            settings = db.get_ai_settings()
            return {
                'enabled': settings['enabled'],
                'model': settings['model'],
                'sentiment_enabled': settings['sentiment_enabled']
            }
        except Exception as e:
            print(f"[CONFIG] Warning: Could not load AI settings from database: {e}")
    
    # Fallback to config.ini
    return {
        'enabled': cfg.getboolean('ai_analysis', 'enable_ai_analysis', fallback=False),
        'model': cfg.get('ai_analysis', 'ai_model', fallback='gpt-4o-mini').strip(),
        'sentiment_enabled': cfg.getboolean('ai_analysis', 'enable_sentiment_analysis', fallback=False)
    }

_ai_settings = get_ai_analysis_settings()
ENABLE_AI_ANALYSIS = _ai_settings['enabled']
AI_MODEL = _ai_settings['model']
ENABLE_SENTIMENT = _ai_settings['sentiment_enabled']
SENTIMENT_INTERVAL = cfg.getint('ai_analysis', 'sentiment_interval', fallback=600)

# AI Commands - Interactive Discord commands
ENABLE_AI_COMMANDS = cfg.getboolean('ai_commands', 'enable_ai_commands', fallback=False)
AI_CHANNEL_ID_STR = cfg.get('ai_commands', 'ai_channel_id', fallback='').strip()
AI_CHANNEL_ID = int(AI_CHANNEL_ID_STR) if AI_CHANNEL_ID_STR else None

# Signal conversion channel
ENABLE_SIGNAL_CONVERSION = cfg.getboolean('signal_conversion', 'enable_conversion', fallback=True)
CONVERSION_CHANNEL_ID_STR = cfg.get('signal_conversion', 'conversion_channel_id', fallback='').strip()
CONVERSION_CHANNEL_ID = int(CONVERSION_CHANNEL_ID_STR) if CONVERSION_CHANNEL_ID_STR else None
INCLUDE_NEWS_IN_ANALYZE = cfg.getboolean('ai_commands', 'include_news_in_analyze', fallback=True)
INCLUDE_FUNDAMENTALS_IN_ANALYZE = cfg.getboolean('ai_commands', 'include_fundamentals_in_analyze', fallback=True)

if ENABLE_AI_ANALYSIS:
    print(f"[CONFIG] ✓ AI trade analysis ENABLED")
    print(f"[CONFIG]   - Model: {AI_MODEL}")
    print(f"[CONFIG]   - Source: {'DATABASE' if DATABASE_MODULE_AVAILABLE else 'config.ini'}")
    if ENABLE_SENTIMENT:
        print(f"[CONFIG] ✓ Sentiment analysis ENABLED (interval: {SENTIMENT_INTERVAL}s)")
    else:
        print(f"[CONFIG] Sentiment analysis DISABLED")
else:
    print(f"[CONFIG] AI analysis DISABLED")

if ENABLE_AI_COMMANDS and AI_CHANNEL_ID:
    print(f"[CONFIG] ✓ AI commands ENABLED (channel: {AI_CHANNEL_ID})")
    print(f"[CONFIG]   Commands: !analyze [SYMBOL], !ask [QUESTION], !scanflow [SYMBOLS]")
elif ENABLE_AI_COMMANDS and not AI_CHANNEL_ID:
    print(f"[CONFIG] ⚠️  AI commands enabled but no channel configured")
else:
    print(f"[CONFIG] AI commands DISABLED")

if ENABLE_SIGNAL_CONVERSION and CONVERSION_CHANNEL_ID:
    print(f"[CONFIG] ✓ Signal Conversion ENABLED (channel: {CONVERSION_CHANNEL_ID})")
    print(f"[CONFIG]   AI auto-monitors and converts natural language to BTO/STC signals")

# Alpha Vantage - Option flow scanner
print("[CONFIG] Loading Alpha Vantage settings...")
ENABLE_AV_SCANNER = cfg.getboolean('alpha_vantage', 'enable_scanner', fallback=False)
AV_MIN_PREMIUM = cfg.getfloat('alpha_vantage', 'min_premium', fallback=100000)
AV_MIN_VOLUME = cfg.getint('alpha_vantage', 'min_volume', fallback=100)
AV_MIN_DTE = cfg.getint('alpha_vantage', 'min_dte', fallback=7)
AV_MAX_DTE = cfg.getint('alpha_vantage', 'max_dte', fallback=45)
AV_MAX_RESULTS = cfg.getint('alpha_vantage', 'max_results', fallback=10)
AV_DEFAULT_SYMBOLS = cfg.get('alpha_vantage', 'default_symbols', fallback='SPY,QQQ,IWM').strip()
AV_SENTIMENT_FILTER = cfg.get('alpha_vantage', 'sentiment_filter', fallback='').strip()

if ENABLE_AV_SCANNER:
    print(f"[CONFIG] ✓ Alpha Vantage scanner ENABLED")
    print(f"[CONFIG]   - Min premium: ${AV_MIN_PREMIUM:,.0f}")
    print(f"[CONFIG]   - Min volume: {AV_MIN_VOLUME}")
    print(f"[CONFIG]   - DTE range: {AV_MIN_DTE}-{AV_MAX_DTE} days")
    print(f"[CONFIG]   - Default symbols: {AV_DEFAULT_SYMBOLS}")
else:
    print(f"[CONFIG] Alpha Vantage scanner DISABLED")

# Swing Trading Analyzer - Pre-trade technical analysis
print("[CONFIG] Loading Swing Trading Analyzer settings...")
ENABLE_SWING_ANALYSIS = cfg.getboolean('swing_analysis', 'enable_swing_analysis', fallback=True)
SWING_MIN_CONFIDENCE = cfg.getint('swing_analysis', 'min_confidence_score', fallback=60)
SWING_ANALYSIS_TIMEFRAME = cfg.get('swing_analysis', 'analysis_timeframe', fallback='1d').strip()
SWING_AUTO_REJECT = cfg.getboolean('swing_analysis', 'auto_reject_low_confidence', fallback=False)

if ENABLE_SWING_ANALYSIS:
    print(f"[CONFIG] ✓ Swing trading analysis ENABLED")
    print(f"[CONFIG]   - Min confidence score: {SWING_MIN_CONFIDENCE}%")
    print(f"[CONFIG]   - Analysis timeframe: {SWING_ANALYSIS_TIMEFRAME}")
    print(f"[CONFIG]   - Auto-reject low confidence: {SWING_AUTO_REJECT}")
else:
    print(f"[CONFIG] Swing trading analysis DISABLED")

# News Service - Real-time market news with biotech detection
print("[CONFIG] Loading News Service settings...")
ENABLE_NEWS = cfg.getboolean('news', 'enable_news', fallback=True)
NEWS_PROVIDER = cfg.get('news', 'provider', fallback='finnhub').strip().lower()
NEWS_CACHE_TTL = cfg.getint('news', 'cache_ttl_minutes', fallback=5)
NEWS_MAX_ITEMS = cfg.getint('news', 'max_items', fallback=5)

if ENABLE_NEWS:
    print(f"[CONFIG] ✓ News service ENABLED")
    print(f"[CONFIG]   - Provider: {NEWS_PROVIDER}")
    print(f"[CONFIG]   - Cache TTL: {NEWS_CACHE_TTL} minutes")
    print(f"[CONFIG]   - Max news items: {NEWS_MAX_ITEMS}")
    
    # Validate Finnhub API key format
    if NEWS_PROVIDER == 'finnhub':
        finnhub_key = os.getenv('FINNHUB_API_KEY', '').strip()
        if finnhub_key and ('http' in finnhub_key.lower() or '/' in finnhub_key):
            print(f"[CONFIG] ⚠️  WARNING: FINNHUB_API_KEY appears to be a URL, not an API key!")
            print(f"[CONFIG]      Current value starts with: {finnhub_key[:30]}...")
            print(f"[CONFIG]      Please set the actual API key string (alphanumeric)")
            print(f"[CONFIG]      Get your free API key at: https://finnhub.io/register")
            print(f"[CONFIG]      News service will be DISABLED until valid key is provided")
            ENABLE_NEWS = False
        elif not finnhub_key:
            print(f"[CONFIG] ⚠️  FINNHUB_API_KEY not set - news service will be disabled")
            ENABLE_NEWS = False
else:
    print(f"[CONFIG] News service DISABLED")

# Webull - Load from database (GUI), setup wizard, environment variables, or config
print("[CONFIG] Loading Webull settings...")
try:
    # Priority: 1) DATABASE (GUI Settings), 2) Setup wizard, 3) Environment variables, 4) config.ini
    db_webull_creds = {}
    try:
        from gui_app.broker_credentials_service import get_webull_credentials
        db_webull_creds = get_webull_credentials() or {}
        if db_webull_creds.get('access_token') or db_webull_creds.get('email'):
            print("[CONFIG] ✓ Loaded Webull credentials from DATABASE (GUI Settings)")
    except Exception as db_err:
        print(f"[CONFIG] Database credentials not available: {db_err}")
    
    # Load with priority: Database > Wizard > Environment > Config
    WB_USER = db_webull_creds.get('email', '') or wizard_credentials.get('WEBULL_USERNAME') or os.getenv('WEBULL_USERNAME', '').strip()
    if not WB_USER:
        WB_USER = cfg['webull'].get('username', '').strip()
    
    WB_PASS = db_webull_creds.get('password', '') or wizard_credentials.get('WEBULL_PASSWORD') or os.getenv('WEBULL_PASSWORD', '').strip()
    if not WB_PASS:
        WB_PASS = cfg['webull'].get('password', '').strip()
    
    WB_PIN = db_webull_creds.get('trade_pin', '') or wizard_credentials.get('WEBULL_TRADE_PIN') or os.getenv('WEBULL_TRADE_PIN', '').strip()
    if not WB_PIN:
        WB_PIN = cfg['webull'].get('trade_pin', '').strip()
    
    WB_ACCESS_TOKEN = db_webull_creds.get('access_token', '') or wizard_credentials.get('WEBULL_ACCESS_TOKEN') or os.getenv('WEBULL_ACCESS_TOKEN', '').strip()
    if not WB_ACCESS_TOKEN:
        WB_ACCESS_TOKEN = cfg['webull'].get('access_token', '').strip()
    
    WB_REFRESH_TOKEN = db_webull_creds.get('refresh_token', '') or wizard_credentials.get('WEBULL_REFRESH_TOKEN') or os.getenv('WEBULL_REFRESH_TOKEN', '').strip()
    if not WB_REFRESH_TOKEN:
        WB_REFRESH_TOKEN = cfg['webull'].get('refresh_token', '').strip()
    
    WB_DID = db_webull_creds.get('device_id', '') or wizard_credentials.get('WEBULL_DID') or os.getenv('WEBULL_DID', '').strip()
    if not WB_DID:
        WB_DID = cfg['webull'].get('did', '').strip()
    
    # Get paper mode from database if available
    PAPER_TRADE = db_webull_creds.get('paper_mode', cfg['webull'].getboolean('paper_trade', fallback=True))
    
    # GUI-first approach: Don't exit if credentials missing - allow GUI configuration
    WEBULL_CREDENTIALS_MISSING = False
    
    if WB_ACCESS_TOKEN and WB_REFRESH_TOKEN:
        print("[CONFIG] ✓ Using saved access/refresh tokens (skipping login)")
    elif not WB_USER or not WB_PASS:
        print("[CONFIG] ⚠️  Webull credentials not configured - configure via GUI at http://localhost:<port>/settings")
        WEBULL_CREDENTIALS_MISSING = True
    
    if not WB_PIN and not WEBULL_CREDENTIALS_MISSING:
        print("[CONFIG] ⚠️  Webull trade PIN not configured - configure via GUI at http://localhost:<port>/settings")
        WEBULL_CREDENTIALS_MISSING = True
    
    WB_DEVICE = cfg['webull'].get('device_name', 'MyTradingBot').strip()
    WB_ENFORCE = cfg['webull'].get('enforce', 'GTC').strip().upper()
    
    print(f"[CONFIG] Webull user: {WB_USER if WB_USER else '(using saved tokens)'}")
    print(f"[CONFIG] Webull DID: {WB_DID if WB_DID else '(not set)'}")
    print(f"[CONFIG] Webull enforce: {WB_ENFORCE}")
    print(f"[CONFIG] Paper trading: {PAPER_TRADE}")
    
    if PAPER_TRADE:
        print("[CONFIG] ⚠️  PAPER TRADING MODE ENABLED - No real trades will be executed")
    else:
        print("[CONFIG] ⚠️  LIVE TRADING MODE - Real trades will be executed!")
        
except KeyError as e:
    raise SystemExit(f"Missing [webull] key in config.ini: {e}")

if WB_ENFORCE not in ('GTC', 'DAY'):
    WB_ENFORCE = 'GTC'

def _latin1(s: str) -> str:
    return (s or "").encode('latin-1', 'ignore').decode('latin-1')

print("[CONFIG] ✓ All settings loaded successfully\n")

# ------------------------------ HELPERS ---------------------------------------
def fix_symbol(symbol: str, direction: str) -> str:
    if direction == 'in':
        return symbol.replace("SPXW", "SPX").replace("NDXP", "NDX")
    elif direction == 'out':
        return symbol.replace("SPX", "SPXW").replace("NDX", "NDXP")
    return symbol

# Slippage decision enum
class SlippageDecision(Enum):
    IMMEDIATE = "immediate"  # Fill immediately - low slippage
    WAIT = "wait"            # Wait for better price - high slippage
    ABORT = "abort"          # Cancel order - price never improved or illiquid

# --------------------------------- WEBULL BROKER -------------------------------------
class WebullBroker:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.name = "WEBULL"  # Add name attribute for multi-broker detection
        self._client = None
        self._logged_in = False
        self._use_paper_account = False  # Flag for paper trading

    def _patch_headers(self, wb):
        if hasattr(wb, "_session") and hasattr(wb, "_headers"):
            safe_device = _latin1(WB_DEVICE or "AndroidDevice")
            safe_ua = _latin1('Mozilla/5.0 (Linux; Android 13; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36')
            wb._headers.update({
                'did': _latin1(WB_DID) if WB_DID else '',
                'device-type': 'Android',
                'device-name': safe_device,
                'os': 'Android',
                'os-version': '13',
                'app': 'global',
                'app-version': '9.53.3',
                'accept-language': 'en-US',
                'user-agent': safe_ua,
            })
            wb._session.headers.update(wb._headers)

    def _set_did(self, wb):
        if WB_DID:
            if hasattr(wb, "_set_did"):
                wb._set_did(WB_DID)
            else:
                wb._did = WB_DID

    def _apply_tokens(self, wb, access_token, refresh_token, did_from_web=None, region_data=None):
        for attr, val in (("_access_token", access_token),
                          ("access_token", access_token),
                          ("_refresh_token", refresh_token),
                          ("refresh_token", refresh_token),
                          ("_did", did_from_web or WB_DID)):
            try:
                setattr(wb, attr, val)
            except Exception:
                pass
        if hasattr(wb, "_headers"):
            wb._headers['Authorization'] = f'Bearer {access_token}'
        if hasattr(wb, "_session"):
            wb._session.headers['Authorization'] = f'Bearer {access_token}'
        if did_from_web:
            try:
                if hasattr(wb, "_set_did"):
                    wb._set_did(did_from_web)
                else:
                    wb._did = did_from_web
            except Exception:
                pass
        if region_data:
            rzone = region_data.get('rzone', '')
            region_id = region_data.get('region_id', '')
            zone_id = region_data.get('zone_id', '')
            if rzone and hasattr(wb, '_session') and isinstance(wb._session, dict):
                wb._session['rzone'] = rzone
            if region_id:
                try:
                    wb._region_id = region_id
                except Exception:
                    pass
            if zone_id:
                try:
                    wb._zone_id = zone_id
                except Exception:
                    pass

    async def login(self):
        def _blocking_login():
            # Check if credentials are available
            if WEBULL_CREDENTIALS_MISSING:
                print("[Webull] ⚠️  Credentials not configured - skipping login")
                print("[Webull] Configure credentials via GUI at http://localhost:<port>/settings")
                return None
            
            # Use paper trading account if flag is set
            if self._use_paper_account:
                from webull import paper_webull
                wb = paper_webull()
                print("[Webull] Using PAPER TRADING account")
            else:
                from webull import webull
                wb = webull()
            
            try:
                self._set_did(wb)
            except Exception as e:
                print(f"[Webull] DID set warning: {e}")
            try:
                self._patch_headers(wb)
            except Exception as e:
                print(f"[Webull] header patch warning: {e}")

            if WB_ACCESS_TOKEN and WB_REFRESH_TOKEN:
                print("[Webull] Using saved access/refresh tokens")
                self._apply_tokens(wb, WB_ACCESS_TOKEN, WB_REFRESH_TOKEN, did_from_web=WB_DID or None)
                print("[Webull] ✓ Tokens applied successfully")
            else:
                try:
                    print(f"[Webull] Attempting login with username: {WB_USER}")
                    data = wb.login(WB_USER, WB_PASS, _latin1(WB_DEVICE))
                    if not (data and data.get('accessToken')):
                        raise RuntimeError(f"login returned no accessToken: {data}")
                    print("[Webull] ✓ Login successful")
                except Exception as e_login:
                    print(f"[Webull] primary login failed: {e_login}")
                    log_error_to_db('broker_connection', f"Webull login failed: {str(e_login)}", 
                                   'WebullBroker', 'error', 'Login with username/password failed')
                    print("[Webull] Using manual token bootstrap from your logged-in browser session.")
                    print("\n>>> In Chrome/Edge: open https://app.webull.com, log in, press F12 → Console and paste:")
                    print("""console.log(JSON.stringify({
  accessToken: sessionStorage.accessToken || localStorage.accessToken || localStorage.ACCESS_TOKEN || '',
  refreshToken: sessionStorage.refreshToken || localStorage.refreshToken || localStorage.REFRESH_TOKEN || '',
  did: sessionStorage.did || localStorage.did || sessionStorage.deviceId || localStorage.deviceId || ''
}));""")
                    print("\n>>> After getting the JSON, save these values to config.ini or Replit Secrets:")
                    print("    access_token = <accessToken value>")
                    print("    refresh_token = <refreshToken value>")
                    print("    did = <did value>")
                    blob = input("\nPaste the printed JSON here: ").strip()
                    try:
                        tokens = json.loads(blob)
                    except Exception:
                        raise RuntimeError("Invalid JSON pasted. Please paste exactly what the console printed.")
                    acc = (tokens.get("accessToken") or "").strip()
                    ref = (tokens.get("refreshToken") or "").strip()
                    did_web = (tokens.get("did") or "").strip()
                    if not acc:
                        raise RuntimeError("Missing accessToken in pasted JSON.")
                    if not ref:
                        print("[Webull] No refreshToken provided — continuing with accessToken only.")
                    self._apply_tokens(wb, acc, ref, did_from_web=did_web or None)

            try:
                wb.get_account_id()
            except Exception as e_acc:
                print(f"[Webull] get_account_id warning: {e_acc}")
            try:
                wb.get_trade_token(WB_PIN)
            except Exception as e_pin:
                log_error_to_db('broker_connection', f"Trade PIN verification failed: {str(e_pin)}", 
                               'WebullBroker', 'critical', 'Check your 6-digit trading PIN in Settings')
                raise RuntimeError(f"get_trade_token failed (check your 6-digit trading PIN): {e_pin}")
            return wb

        self._client = await self.loop.run_in_executor(None, _blocking_login)
        if self._client is not None:
            self._logged_in = True
        else:
            self._logged_in = False
            print("[Webull] ⚠️  Broker not connected - trading functions disabled")

    async def refresh_tokens(self):
        """Refresh Webull access and refresh tokens"""
        def _blocking_refresh():
            try:
                if not self._client:
                    print("[Webull] Cannot refresh tokens - client not initialized")
                    return False
                
                print("[Webull] Refreshing access token...")
                
                if hasattr(self._client, 'refresh_login'):
                    new_token = self._client.refresh_login()
                    
                    if new_token and isinstance(new_token, dict):
                        new_access = new_token.get('accessToken')
                        new_refresh = new_token.get('refreshToken')
                        
                        if new_access:
                            self._apply_tokens(self._client, new_access, new_refresh or WB_REFRESH_TOKEN, did_from_web=WB_DID)
                            print(f"[Webull] ✓ Token refreshed successfully")
                            print(f"[Webull]   New access token: {new_access[:20]}...{new_access[-10:]}")
                            
                            if os.getenv('REPL_ID'):
                                print("[Webull] NOTE: Please update your Replit Secrets with the new token:")
                                print(f"[Webull]   WEBULL_ACCESS_TOKEN={new_access}")
                                if new_refresh:
                                    print(f"[Webull]   WEBULL_REFRESH_TOKEN={new_refresh}")
                            
                            return True
                        else:
                            print("[Webull] ⚠️  Refresh returned no new accessToken")
                            return False
                    else:
                        print(f"[Webull] ⚠️  Unexpected refresh response: {type(new_token)}")
                        return False
                else:
                    print("[Webull] ⚠️  Client doesn't support refresh_login method")
                    return False
                    
            except Exception as e:
                print(f"[Webull] ⚠️  Token refresh failed: {e}")
                import traceback
                traceback.print_exc()
                return False
        
        return await self.loop.run_in_executor(None, _blocking_refresh)

    async def get_account_info(self) -> dict:
        """Get account information for position sizing"""
        def _blocking_get_account():
            if not self._client:
                return {'buying_power': 0, 'options_buying_power': 0, 'cash': 0, 'portfolio_value': 0}
            try:
                account = self._client.get_account()
                if not account:
                    return {'buying_power': 0, 'options_buying_power': 0, 'cash': 0, 'portfolio_value': 0}
                
                # Parse accountMembers list into a dict (Webull returns {'key': 'name', 'value': 'val'} items)
                account_data = {}
                account_members = account.get('accountMembers', [])
                if account_members and isinstance(account_members, list):
                    for item in account_members:
                        if isinstance(item, dict) and 'key' in item and 'value' in item:
                            account_data[item['key']] = item['value']
                
                # Merge direct fields (accountMembers parsed values take priority)
                for k, v in account.items():
                    if k != 'accountMembers' and k not in account_data:
                        account_data[k] = v
                
                # Extract buying power
                buying_power = 0.0
                for field in ['buyingPower', 'dayBuyingPower', 'cashAvailableForTrade', 'settledFunds']:
                    if field in account_data:
                        try:
                            buying_power = float(account_data[field])
                            if buying_power > 0:
                                break
                        except (ValueError, TypeError):
                            pass
                
                # Extract options buying power (critical for options trading)
                options_bp = 0.0
                if 'optionBuyingPower' in account_data:
                    try:
                        options_bp = float(account_data['optionBuyingPower'])
                    except (ValueError, TypeError):
                        pass
                if options_bp <= 0:
                    options_bp = buying_power  # Fall back to regular buying power
                
                # Extract portfolio value (market value)
                portfolio_value = 0.0
                for field in ['netLiquidation', 'totalMarketValue', 'accountValue']:
                    if field in account_data:
                        try:
                            portfolio_value = float(account_data[field])
                            if portfolio_value > 0:
                                break
                        except (ValueError, TypeError):
                            pass
                
                # Extract account type (Margin/Cash/IRA)
                account_type = 'Unknown'
                for field in ['brokerAccountTypeStr', 'accountType', 'brokerAccountType']:
                    if field in account_data:
                        raw_type = str(account_data[field]).upper()
                        if 'MARGIN' in raw_type:
                            account_type = 'Margin'
                        elif 'CASH' in raw_type:
                            account_type = 'Cash'
                        elif 'IRA' in raw_type or 'ROTH' in raw_type or 'TRADITIONAL' in raw_type:
                            account_type = 'IRA'
                        else:
                            account_type = account_data[field]
                        break
                
                # Get account ID for display
                account_id = account_data.get('secAccountId', account_data.get('accountId', 'N/A'))
                
                result = {
                    'buying_power': buying_power,
                    'options_buying_power': options_bp,
                    'cash': buying_power,
                    'portfolio_value': portfolio_value,
                    'account_type': account_type,
                    'account_id': str(account_id)
                }
                return result
            except Exception as e:
                print(f"[Webull] Error getting account info: {e}")
                return {'buying_power': 0, 'options_buying_power': 0, 'cash': 0, 'portfolio_value': 0}
        
        return await self.loop.run_in_executor(None, _blocking_get_account)

    async def _ensure_login(self):
        if not self._logged_in:
            await self.login()

    def _wb_get_option_id_strict(self, wb, base_symbol: str, strike: float, opt_type: str, expiry_mmdd: str, expiry_year: Optional[str] = None) -> Tuple[int, int]:
        def iso_from_mmdd(mmdd: str, year: Optional[str] = None) -> str:
            m, d = mmdd.split('/')
            if year is None:
                yyyy = datetime.now().strftime('%Y')
            else:
                yyyy = year
            return f"{yyyy}-{int(m):02d}-{int(d):02d}"

        def iter_rows(obj):
            if isinstance(obj, dict):
                yield obj
                for v in obj.values():
                    yield from iter_rows(v)
            elif isinstance(obj, list):
                for it in obj:
                    yield from iter_rows(it)

        def extract_candidate(row, direction: str):
            if not isinstance(row, dict):
                return None

            strike_raw = row.get('strikePrice') or row.get('strike')
            try:
                strike_val = float(strike_raw) if strike_raw is not None else None
            except Exception:
                strike_val = None

            exp = row.get('expireDate') or row.get('expiry') or row.get('date')

            side = (row.get('callPut') or row.get('optionType') or row.get('direction') or '').lower()
            nested = row.get(direction)
            nested_oid = None
            nested_exp = None
            if isinstance(nested, dict):
                nested_oid = nested.get('tickerId') or nested.get('id') or nested.get('optionId')
                nested_exp = nested.get('expireDate') or nested.get('expiry') or nested.get('date')

            oid = row.get('tickerId') or row.get('optionId') or row.get('id')

            if not side and isinstance(nested, dict):
                side = direction
            side = {'c': 'call', 'p': 'put'}.get(side[:1], side)

            if nested_oid:
                oid = nested_oid
            if nested_exp:
                exp = nested_exp

            if (strike_val is None) or (oid is None):
                return None

            return {
                'strike': strike_val,
                'side': side,
                'expiry': exp,
                'option_id': oid
            }

        symbol = fix_symbol(base_symbol, "in")
        direction = 'call' if opt_type.upper() == 'C' else 'put'
        iso_exp = iso_from_mmdd(expiry_mmdd, year=expiry_year)
        target_strike = float(strike)

        # Check if this is an index option (SPX, NDX, VIX, etc.)
        index_symbols = ['SPX', 'SPXW', 'NDX', 'NDXP', 'VIX', 'VIXW', 'XSP', 'DJX', 'RUT']
        is_index_option = symbol.upper() in index_symbols
        
        if is_index_option:
            print(f"[WEBULL] 🔍 Index option detected: {symbol}")
        
        tId = wb.get_ticker(symbol)
        print(f"[WEBULL] get_ticker('{symbol}') returned: {tId}")
        if not tId:
            raise RuntimeError(f"Symbol not found: {symbol}")

        data = wb.get_options(stock=symbol, direction=direction, expireDate=iso_exp)
        print(f"[WEBULL] get_options('{symbol}', '{direction}', '{iso_exp}') returned: {type(data)} - {len(data) if isinstance(data, (list, dict)) else 'N/A'} items")
        candidates = []
        for row in iter_rows(data):
            cand = extract_candidate(row, direction)
            if not cand:
                continue
            if cand['side'] != direction:
                continue
            if cand['expiry'] and str(cand['expiry']).startswith(iso_exp):
                candidates.append(cand)

        if not candidates:
            data = wb.get_options(stock=symbol, direction=direction)
            for row in iter_rows(data):
                cand = extract_candidate(row, direction)
                if not cand:
                    continue
                if cand['side'] != direction:
                    continue
                if cand['expiry'] and str(cand['expiry']).startswith(iso_exp):
                    candidates.append(cand)

        print(f"[WEBULL] Found {len(candidates)} candidate options for {symbol} {target_strike}{direction} {iso_exp}")
        
        for cand in candidates:
            if abs(cand['strike'] - target_strike) < 1e-6:
                print(f"[WEBULL] ✓ Exact match found: option_id={cand['option_id']}, strike={cand['strike']}")
                return int(cand['option_id']), int(tId)

        best = None
        best_diff = 1e9
        for cand in candidates:
            diff = abs(cand['strike'] - target_strike)
            if diff < best_diff:
                best, best_diff = cand, diff
        if best and best_diff <= 0.01:
            print(f"[WEBULL] ✓ Close match found: option_id={best['option_id']}, strike={best['strike']} (diff={best_diff})")
            return int(best['option_id']), int(tId)

        print(f"[WEBULL] ❌ No matching option found. Candidates: {candidates[:5]}...")
        raise RuntimeError(f"OptionId not found for {symbol} {strike}{opt_type} {iso_exp}")

    def _get_current_option_quote(self, wb, symbol: str, strike: float, opt_type: str, expiry_mmdd: str, expiry_year: Optional[str] = None) -> Optional[float]:
        """
        Fetch current option quote (mark price preferred, fallback to last/bid/ask)
        Returns None if no quote available (illiquid option)
        """
        try:
            option_id, tId = self._wb_get_option_id_strict(wb, symbol, strike, opt_type, expiry_mmdd, expiry_year)
            if option_id == 0:
                print(f"[SLIPPAGE] ⚠️  Could not find option ID for {symbol} ${strike}{opt_type} {expiry_mmdd}")
                return None
            
            # Get option quote data
            quote = wb.get_option_quote(stock=symbol, optionId=str(option_id))
            if not quote:
                print(f"[SLIPPAGE] ⚠️  No quote data available for option {option_id}")
                return None
            
            # Debug: Print full quote response to see what fields are available
            print(f"[SLIPPAGE] DEBUG: Quote response keys: {list(quote.keys())}")
            
            # Price data is nested in 'data' field - find matching option by option_id
            ask = 0.0
            bid = 0.0
            last = 0.0
            
            if 'data' in quote and isinstance(quote.get('data'), list):
                # Search for matching option in data array
                for opt in quote.get('data', []):
                    # Match by option_id or tickerId
                    if opt.get('tickerId') == option_id or str(opt.get('tickerId')) == str(option_id):
                        # Extract prices from nested data
                        askList = opt.get('askList', [])
                        bidList = opt.get('bidList', [])
                        
                        if askList and len(askList) > 0:
                            ask = float(askList[0].get('price', 0))
                        if bidList and len(bidList) > 0:
                            bid = float(bidList[0].get('price', 0))
                        
                        last = float(opt.get('latestPrice', 0) or opt.get('close', 0) or opt.get('lastPrice', 0) or 0)
                        
                        print(f"[SLIPPAGE] DEBUG: Extracted from data field - ask: ${ask}, bid: ${bid}, last: ${last}")
                        break
            else:
                # Fallback: Try top-level fields (older API format)
                ask = float(quote.get('askPrice', 0) or quote.get('askList', [{}])[0].get('price', 0) or 0)
                bid = float(quote.get('bidPrice', 0) or quote.get('bidList', [{}])[0].get('price', 0) or 0)
                last = float(quote.get('lastPrice', 0) or quote.get('latestPrice', 0) or quote.get('close', 0) or 0)
            
            if ask > 0 and bid > 0:
                mark_price = (ask + bid) / 2
                print(f"[SLIPPAGE] Current mark price: ${mark_price:.2f} (bid: ${bid:.2f}, ask: ${ask:.2f})")
                return mark_price
            
            # Fallback to last trade price
            if last > 0:
                print(f"[SLIPPAGE] Current last price: ${last:.2f} (no bid/ask)")
                return last
            
            # No valid price data
            print(f"[SLIPPAGE] ⚠️  No valid price data (bid: ${bid}, ask: ${ask}, last: ${last})")
            return None
            
        except Exception as e:
            print(f"[SLIPPAGE] Error fetching option quote: {e}")
            return None
    
    def _get_current_stock_quote(self, wb, symbol: str) -> Optional[float]:
        """
        Fetch current stock quote (mark price preferred, fallback to last)
        Returns None if no quote available
        """
        try:
            quote = wb.get_quote(stock=symbol)
            if not quote:
                print(f"[SLIPPAGE] ⚠️  No quote data available for stock {symbol}")
                return None
            
            # Try mark price (mid of bid/ask) first
            ask = float(quote.get('askPrice', 0))
            bid = float(quote.get('bidPrice', 0))
            if ask > 0 and bid > 0:
                mark_price = (ask + bid) / 2
                print(f"[SLIPPAGE] Current mark price: ${mark_price:.2f} (bid: ${bid:.2f}, ask: ${ask:.2f})")
                return mark_price
            
            # Fallback to last trade price
            last = float(quote.get('last', 0))
            if last > 0:
                print(f"[SLIPPAGE] Current last price: ${last:.2f}")
                return last
            
            print(f"[SLIPPAGE] ⚠️  No valid price data for {symbol}")
            return None
            
        except Exception as e:
            print(f"[SLIPPAGE] Error fetching stock quote: {e}")
            return None
    
    def _evaluate_slippage(self, signal_price: float, current_price: Optional[float], threshold_override: Optional[float] = None) -> Tuple[SlippageDecision, float]:
        """
        Evaluate price slippage and return decision
        Args:
            signal_price: Price from signal
            current_price: Current market price
            threshold_override: Optional threshold to use instead of global HIGH_SLIPPAGE_THRESHOLD_PCT
        Returns: (SlippageDecision, slippage_percentage)
        """
        if current_price is None or current_price <= 0:
            # No quote data - check if we should proceed anyway
            if ALLOW_ORDER_WHEN_NO_QUOTE:
                print(f"[SLIPPAGE] ⚠️  No valid current price - proceeding anyway (allow_when_no_quote=true)")
                return (SlippageDecision.IMMEDIATE, 0.0)
            else:
                print(f"[SLIPPAGE] ❌ No valid current price - marking as ABORT (illiquid)")
                return (SlippageDecision.ABORT, 0.0)
        
        # Calculate slippage percentage
        slippage_pct = abs(current_price - signal_price) / signal_price * 100
        
        # Use override threshold if provided, otherwise use global
        high_threshold = threshold_override if threshold_override is not None else HIGH_SLIPPAGE_THRESHOLD_PCT
        
        print(f"[SLIPPAGE] Signal price: ${signal_price:.2f}, Current price: ${current_price:.2f}")
        print(f"[SLIPPAGE] Slippage: {slippage_pct:.2f}%")
        
        if slippage_pct <= MAX_IMMEDIATE_SLIPPAGE_PCT:
            print(f"[SLIPPAGE] ✅ IMMEDIATE fill - slippage {slippage_pct:.2f}% <= {MAX_IMMEDIATE_SLIPPAGE_PCT}%")
            return (SlippageDecision.IMMEDIATE, slippage_pct)
        elif slippage_pct <= high_threshold:
            print(f"[SLIPPAGE] ⏸️  WAIT - slippage {slippage_pct:.2f}% between {MAX_IMMEDIATE_SLIPPAGE_PCT}% and {high_threshold}%")
            return (SlippageDecision.WAIT, slippage_pct)
        else:
            print(f"[SLIPPAGE] ❌ ABORT - slippage {slippage_pct:.2f}% > {high_threshold}%")
            return (SlippageDecision.ABORT, slippage_pct)
    
    async def _wait_for_better_price(self, signal: dict, get_current_price_func) -> Tuple[SlippageDecision, Optional[float]]:
        """
        Wait and retry for better price within configured time limit
        Returns: (final_decision, final_current_price)
        """
        signal_price = signal.get('price')
        
        # For market orders (price is None), skip slippage wait - execute immediately
        if signal_price is None:
            print(f"[SLIPPAGE] Market order detected - skipping price wait")
            return (SlippageDecision.IMMEDIATE, None)
        
        wait_until = datetime.now() + timedelta(minutes=SLIPPAGE_WAIT_MINUTES)
        retry_count = 0
        
        print(f"[SLIPPAGE] ⏳ Waiting up to {SLIPPAGE_WAIT_MINUTES} minutes for better price...")
        print(f"[SLIPPAGE] Will retry every {SLIPPAGE_RETRY_INTERVAL} seconds")
        
        while datetime.now() < wait_until:
            retry_count += 1
            await asyncio.sleep(SLIPPAGE_RETRY_INTERVAL)
            
            # Check current price again
            def check_price():
                return get_current_price_func()
            
            current_price = await asyncio.to_thread(check_price)
            decision, slippage_pct = self._evaluate_slippage(signal_price, current_price)
            
            print(f"[SLIPPAGE] Retry #{retry_count}: Decision = {decision.value}, Slippage = {slippage_pct:.2f}%")
            
            if decision == SlippageDecision.IMMEDIATE:
                print(f"[SLIPPAGE] ✅ Price improved! Proceeding with order")
                return (decision, current_price)
            elif decision == SlippageDecision.ABORT:
                print(f"[SLIPPAGE] ❌ Price worsened or became illiquid. Canceling order")
                return (decision, current_price)
        
        # Timeout reached
        print(f"[SLIPPAGE] ⏰ Wait timeout reached ({SLIPPAGE_WAIT_MINUTES} minutes)")
        print(f"[SLIPPAGE] ❌ Canceling order - price never improved")
        return (SlippageDecision.ABORT, None)
    
    async def place_option_order(self, action: str, qty: int, symbol: str,
                                 strike: float, opt_type: str, expiry_mmdd: str,
                                 limit_price: float, expiry_year: Optional[str] = None) -> Dict[str, Any]:
        await self._ensure_login()
        
        # Log if using paper trading account (actual Webull paper API will be called)
        if self._use_paper_account:
            print(f"[PAPER TRADE] Placing {action} {qty} {symbol} {strike}{opt_type} {expiry_mmdd} @{limit_price} on Webull PAPER account")
        
        # Price slippage protection for BTO orders (reload settings from database in real-time)
        _current_slippage_settings = get_slippage_settings()  # Reload from database
        if _current_slippage_settings['enabled'] and action.upper() in ('BTO', 'BTC'):
            print(f"[SLIPPAGE] Checking price slippage for {action} {symbol} ${strike}{opt_type} {expiry_mmdd}")
            print(f"[SLIPPAGE] Current threshold: {_current_slippage_settings['threshold_percent']}% (from {'DATABASE' if DATABASE_MODULE_AVAILABLE else 'config.ini'})")
            
            # Get current option quote
            def get_quote():
                return self._get_current_option_quote(self._client, symbol, strike, opt_type, expiry_mmdd, expiry_year)
            
            current_price = await asyncio.to_thread(get_quote)
            # Use dynamic threshold from database
            decision, slippage_pct = self._evaluate_slippage(limit_price, current_price, threshold_override=_current_slippage_settings['threshold_percent'])
            
            if decision == SlippageDecision.ABORT:
                print(f"[SLIPPAGE] ❌ Order ABORTED - excessive slippage or illiquid")
                return {
                    'success': False,
                    'msg': f'Order canceled: price slippage {slippage_pct:.2f}% exceeds threshold or option is illiquid',
                    'error': 'EXCESSIVE_SLIPPAGE'
                }
            
            elif decision == SlippageDecision.WAIT:
                # Enter wait-and-retry loop
                signal = {
                    'action': action,
                    'symbol': symbol,
                    'strike': strike,
                    'opt_type': opt_type,
                    'expiry': expiry_mmdd,
                    'price': limit_price
                }
                
                final_decision, final_price = await self._wait_for_better_price(signal, get_quote)
                
                if final_decision == SlippageDecision.ABORT:
                    print(f"[SLIPPAGE] ❌ Order CANCELED - price never improved after waiting")
                    return {
                        'success': False,
                        'msg': f'Order canceled: price did not improve within {SLIPPAGE_WAIT_MINUTES} minutes',
                        'error': 'SLIPPAGE_TIMEOUT'
                    }
                
                # Price improved - update limit price to current price for better fill
                if final_price and final_price > 0:
                    print(f"[SLIPPAGE] ✓ Using improved price: ${limit_price:.2f} → ${final_price:.2f}")
                    limit_price = final_price
            
            else:  # IMMEDIATE
                print(f"[SLIPPAGE] ✅ Proceeding with order - acceptable slippage {slippage_pct:.2f}%")


        def _blocking_place():
            import inspect
            import sys
            wb = self._client
            if not wb:
                raise RuntimeError("Webull client not initialized")
            print(f"[WEBULL] 🔍 Looking up option_id for {symbol} ${strike}{opt_type} {expiry_mmdd}")
            sys.stdout.flush()
            option_id, tId = self._wb_get_option_id_strict(wb, symbol, strike, opt_type, expiry_mmdd, expiry_year)
            print(f"[WEBULL] ✓ Got option_id={option_id}, ticker_id={tId} for {symbol}")
            sys.stdout.flush()
            side = 'BUY' if action.upper() in ('BTO', 'BTC') else 'SELL'
            
            adjusted_qty = qty
            
            if side == 'BUY':
                try:
                    account_info = wb.get_account()
                    account_members = account_info.get('accountMembers', [])
                    
                    # Convert list of {'key': 'name', 'value': 'value'} into a proper dict
                    account_data = {}
                    if account_members:
                        for item in account_members:
                            if isinstance(item, dict) and 'key' in item and 'value' in item:
                                account_data[item['key']] = item['value']
                    
                    # DEBUG: Show what fields are available
                    print(f"[DEBUG] Account fields available: {list(account_data.keys())}")
                    
                    # Try multiple possible field names for buying power
                    buying_power = 0.0
                    for field in ['buyingPower', 'cashAvailableForTrade', 'cashBalance', 'dayBuyingPower', 'accountMembers.0.buyingPower']:
                        if field in account_data:
                            try:
                                buying_power = float(account_data[field])
                                if buying_power > 0:
                                    print(f"[DEBUG] Found buying power in field '{field}': ${buying_power:.2f}")
                                    break
                            except (ValueError, TypeError):
                                continue
                    
                    order_cost = qty * limit_price * 100
                    
                    net_liq = float(account_data.get('netLiquidation', 0))
                    print(f"[FUNDS] Buying power: ${buying_power:.2f}, Order cost: ${order_cost:.2f} (Net liquidation: ${net_liq:.2f})")
                    
                    if buying_power <= 0:
                        return {
                            'success': False,
                            'msg': f'No buying power available: ${buying_power:.2f} (Account value: ${net_liq:.2f})',
                            'error': 'INSUFFICIENT_FUNDS'
                        }
                    
                    if order_cost > buying_power:
                        max_affordable_qty = int(buying_power / (limit_price * 100))
                        if max_affordable_qty > 0:
                            print(f"[FUNDS] ⚠️ Insufficient funds for {qty} contracts")
                            print(f"[FUNDS] ✓ Adjusting quantity: {qty} → {max_affordable_qty} contracts")
                            print(f"[FUNDS] Adjusted cost: ${max_affordable_qty * limit_price * 100:.2f}")
                            adjusted_qty = max_affordable_qty
                        else:
                            return {
                                'success': False,
                                'msg': f'Insufficient buying power: have ${buying_power:.2f}, need ${order_cost:.2f}',
                                'error': 'INSUFFICIENT_FUNDS'
                            }
                except Exception as e:
                    print(f"[FUNDS] Warning: Could not check buying power: {e}")
            
            elif side == 'SELL':
                try:
                    positions = wb.get_positions()
                    if positions:
                        for pos in positions:
                            pos_symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                            pos_strike = float(pos.get('strikePrice', 0))
                            pos_direction = pos.get('direction', '').upper()
                            pos_qty = float(pos.get('position', 0))
                            
                            pos_expiry = pos.get('expireDate', '')
                            if pos_expiry:
                                from datetime import datetime
                                try:
                                    exp_date = datetime.strptime(pos_expiry, '%Y-%m-%d')
                                    pos_expiry_mmdd = exp_date.strftime('%m/%d')
                                except:
                                    pos_expiry_mmdd = ''
                            else:
                                pos_expiry_mmdd = ''
                            
                            pos_type = 'C' if pos_direction == 'CALL' else 'P' if pos_direction == 'PUT' else ''
                            
                            if (pos_symbol == symbol and 
                                abs(pos_strike - strike) < 0.01 and 
                                pos_type == opt_type.upper() and 
                                pos_expiry_mmdd == expiry_mmdd and
                                pos_qty > 0):
                                
                                actual_qty = int(pos_qty)
                                if actual_qty < qty:
                                    print(f"[POSITION] ⚠️ Signal wants to sell {qty} contracts")
                                    print(f"[POSITION] ✓ Adjusting to actual position: {qty} → {actual_qty} contracts")
                                    adjusted_qty = actual_qty
                                elif actual_qty > qty:
                                    print(f"[POSITION] Selling {qty} of {actual_qty} contracts held")
                                else:
                                    print(f"[POSITION] Selling all {actual_qty} contracts")
                                break
                        else:
                            print(f"[POSITION] ⚠️ Warning: No matching position found for {symbol} {strike}{opt_type} {expiry_mmdd}")
                            print(f"[POSITION] Proceeding with signal quantity: {qty}")
                except Exception as e:
                    print(f"[POSITION] Warning: Could not check positions: {e}")

            if not hasattr(wb, "place_order_option"):
                raise RuntimeError("Your installed `webull` package has no place_order_option(). Please upgrade that package.")

            # Use ONLY the direct HTTP API call (SDK fails with 500, direct API works)
            # This is the SINGLE order submission path - no fallbacks to prevent duplicates
            import requests
            import uuid
            
            headers = wb.build_req_headers(include_trade_token=True, include_time=True)
            api_payload = {
                'orderType': 'LMT',
                'serialId': str(uuid.uuid4()),
                'timeInForce': WB_ENFORCE,
                'orders': [{'quantity': int(adjusted_qty), 'action': side, 'tickerId': int(option_id), 'tickerType': 'OPTION'}],
                'lmtPrice': float(limit_price)
            }
            print(f"[WEBULL] Placing option order via direct API: {api_payload}")
            
            try:
                api_url = wb._urls.place_option_orders(wb._account_id)
                print(f"[WEBULL] API URL: {api_url}")
                api_response = requests.post(api_url, json=api_payload, headers=headers, timeout=wb.timeout)
                print(f"[WEBULL] Response Status: {api_response.status_code}")
                
                if api_response.status_code == 200:
                    response_json = api_response.json()
                    print(f"[WEBULL] ✓ Order placed successfully: orderId={response_json.get('orderId')}")
                    return response_json
                else:
                    # Return detailed error
                    error_msg = f"Webull API Error {api_response.status_code}: {api_response.reason}"
                    try:
                        error_details = api_response.json()
                        error_msg += f" - Details: {error_details}"
                    except:
                        error_msg += f" - Text: {api_response.text}"
                    
                    print(f"[WEBULL] ❌ Order failed: {error_msg}")
                    log_error_to_db('order_execution', f"Option order failed: {error_msg}", 
                                   'WebullBroker', 'error', f'Symbol: {symbol}, Action: {side}, Qty: {adjusted_qty}')
                    return {
                        'success': False,
                        'msg': error_msg,
                        'error': 'WEBULL_API_ERROR',
                        'status_code': api_response.status_code
                    }
                    
            except Exception as api_error:
                print(f"[WEBULL] ❌ API call failed: {api_error}")
                log_error_to_db('order_execution', f"Webull API call failed: {str(api_error)}", 
                               'WebullBroker', 'error', f'Symbol: {symbol}')
                raise Exception(f"Webull API Error: {str(api_error)}") from api_error

        return await self.loop.run_in_executor(None, _blocking_place)

    async def place_option_order_simple(self, symbol: str, strike: float, expiry: str, 
                                       option_type: str, quantity: int, side: str, 
                                       price: float, option_id: str) -> Dict[str, Any]:
        """
        Simplified option order placement - wrapper for GUI API compatibility
        Thread-safe version that works from Flask routes.
        
        Args:
            symbol: Stock symbol
            strike: Strike price
            expiry: Expiration date in YYYY-MM-DD format
            option_type: 'CALL' or 'PUT'
            quantity: Number of contracts
            side: 'BUY' or 'SELL'
            price: Limit price per contract
            option_id: Webull option contract ID (not used by old broker, kept for compatibility)
        
        Returns:
            Dict with success status and message
        """
        # Convert new API parameters to old format
        from datetime import datetime
        import asyncio
        
        # Convert YYYY-MM-DD to MM/DD format
        try:
            exp_date = datetime.strptime(expiry, '%Y-%m-%d')
            expiry_mmdd = exp_date.strftime('%m/%d')
            expiry_year = exp_date.strftime('%Y')
        except ValueError:
            return {
                'success': False,
                'msg': f'Invalid expiry date format: {expiry}. Expected YYYY-MM-DD',
                'error': 'INVALID_DATE'
            }
        
        # Convert parameters
        action = 'BTO' if side == 'BUY' else 'STC'
        opt_type = 'C' if option_type.upper() == 'CALL' else 'P'
        
        # Ensure we're logged in
        await self._ensure_login()
        
        # Check paper trade mode
        if PAPER_TRADE:
            print(f"[PAPER TRADE] Would place {action} {quantity} {symbol} {strike}{opt_type} {expiry_mmdd} @{price}")
            return {
                'success': True,
                'msg': 'Paper trade - no actual order placed',
                'paper_trade': True,
                'order_id': 'PAPER'
            }
        
        # Define blocking order placement function
        def _blocking_place():
            wb = self._client
            if not wb:
                raise RuntimeError("Webull client not initialized")
            
            print(f"[DEBUG] Starting order placement for {action} {quantity} {symbol} ${strike}{opt_type} {expiry_mmdd}/{expiry_year} @{price}")
            
            # Get option ID
            try:
                option_id, tId = self._wb_get_option_id_strict(wb, symbol, strike, opt_type, expiry_mmdd, expiry_year)
                print(f"[DEBUG] ✓ Option ID resolved: {option_id}, tId: {tId}")
            except Exception as e:
                print(f"[DEBUG] ✗ Failed to get option ID: {e}")
                raise
            
            side_action = 'BUY' if action.upper() in ('BTO', 'BTC') else 'SELL'
            print(f"[DEBUG] Side action: {side_action}")
            
            adjusted_qty = quantity
            
            # Check buying power for BUY orders
            if side_action == 'BUY':
                try:
                    account_info = wb.get_account()
                    account_members = account_info.get('accountMembers', [])
                    account_data = {}
                    if account_members:
                        for item in account_members:
                            if isinstance(item, dict) and 'key' in item and 'value' in item:
                                account_data[item['key']] = item['value']
                    
                    # Try to find buying power
                    buying_power = 0.0
                    for field in ['buyingPower', 'cashAvailableForTrade', 'cashBalance', 'dayBuyingPower']:
                        if field in account_data:
                            try:
                                buying_power = float(account_data[field])
                                if buying_power > 0:
                                    print(f"[DEBUG] Found buying power in field '{field}': ${buying_power:.2f}")
                                    break
                            except (ValueError, TypeError):
                                continue
                    
                    order_cost = quantity * price * 100
                    print(f"[DEBUG] Order cost: ${order_cost:.2f}, Available: ${buying_power:.2f}")
                    
                    if buying_power <= 0:
                        return {
                            'success': False,
                            'msg': f'No buying power available: ${buying_power:.2f}',
                            'error': 'INSUFFICIENT_FUNDS'
                        }
                    
                    if order_cost > buying_power:
                        max_affordable_qty = int(buying_power / (price * 100))
                        if max_affordable_qty > 0:
                            print(f"[DEBUG] ⚠️ Insufficient funds for {quantity} contracts")
                            print(f"[DEBUG] ✓ Adjusting quantity: {quantity} → {max_affordable_qty} contracts")
                            adjusted_qty = max_affordable_qty
                        else:
                            return {
                                'success': False,
                                'msg': f'Insufficient buying power: have ${buying_power:.2f}, need ${order_cost:.2f}',
                                'error': 'INSUFFICIENT_FUNDS'
                            }
                except Exception as e:
                    print(f"[DEBUG] Warning: Could not check buying power: {e}")
            
            # Use the webull library's place_order_option method
            if not hasattr(wb, "place_order_option"):
                raise RuntimeError("Your installed `webull` package has no place_order_option(). Please upgrade that package.")
            
            payload = {
                'optionId': int(option_id),
                'lmtPrice': float(price),
                'action': side_action,
                'orderType': 'LMT',
                'enforce': WB_ENFORCE,
                'quant': int(adjusted_qty),
            }
            
            print(f"[DEBUG] Payload: {payload}")
            print(f"[ORDER] Placing {action} {adjusted_qty} {symbol} ${strike}{opt_type} {expiry_mmdd}/{expiry_year} @{price}")
            
            # Call the Webull API
            try:
                result = wb.place_order_option(**payload)
                print(f"[DEBUG] ✓ Webull API response: {result}")
                return result
            except Exception as api_error:
                print(f"[DEBUG] ✗ Webull API error: {api_error}")
                print(f"[DEBUG] Error type: {type(api_error)}")
                # Re-raise so the outer try/catch can handle it
                raise
        
        # Use asyncio.to_thread for thread-safe execution (works with any event loop)
        try:
            result = await asyncio.to_thread(_blocking_place)
            return result
        except Exception as e:
            print(f"[ORDER ERROR] {e}")
            return {
                'success': False,
                'msg': f'Order placement failed: {str(e)}',
                'error': 'ORDER_FAILED'
            }

    async def place_stock_order(self, action: str, qty: int, symbol: str, limit_price: float) -> Dict[str, Any]:
        await self._ensure_login()
        
        # Log if using paper trading account (actual Webull paper API will be called)
        if self._use_paper_account:
            print(f"[PAPER TRADE] Placing {action} {qty} {symbol} @{limit_price} on Webull PAPER account")
        
        # Price slippage protection for BTO orders (reload settings from database in real-time)
        _current_slippage_settings = get_slippage_settings()  # Reload from database
        if _current_slippage_settings['enabled'] and action.upper() in ('BTO',):
            print(f"[SLIPPAGE] Checking price slippage for {action} {symbol}")
            print(f"[SLIPPAGE] Current threshold: {_current_slippage_settings['threshold_percent']}% (from {'DATABASE' if DATABASE_MODULE_AVAILABLE else 'config.ini'})")
            
            # Get current stock quote
            def get_quote():
                return self._get_current_stock_quote(self._client, symbol)
            
            current_price = await asyncio.to_thread(get_quote)
            # Use dynamic threshold from database
            decision, slippage_pct = self._evaluate_slippage(limit_price, current_price, threshold_override=_current_slippage_settings['threshold_percent'])
            
            if decision == SlippageDecision.ABORT:
                print(f"[SLIPPAGE] ❌ Order ABORTED - excessive slippage or no quote available")
                return {
                    'success': False,
                    'msg': f'Order canceled: price slippage {slippage_pct:.2f}% exceeds threshold or stock has no quote',
                    'error': 'EXCESSIVE_SLIPPAGE'
                }
            
            elif decision == SlippageDecision.WAIT:
                # Enter wait-and-retry loop
                signal = {
                    'action': action,
                    'symbol': symbol,
                    'price': limit_price
                }
                
                final_decision, final_price = await self._wait_for_better_price(signal, get_quote)
                
                if final_decision == SlippageDecision.ABORT:
                    print(f"[SLIPPAGE] ❌ Order CANCELED - price never improved after waiting")
                    return {
                        'success': False,
                        'msg': f'Order canceled: price did not improve within {SLIPPAGE_WAIT_MINUTES} minutes',
                        'error': 'SLIPPAGE_TIMEOUT'
                    }
                
                # Price improved - update limit price to current price for better fill
                if final_price and final_price > 0:
                    print(f"[SLIPPAGE] ✓ Using improved price: ${limit_price:.2f} → ${final_price:.2f}")
                    limit_price = final_price
            
            else:  # IMMEDIATE
                print(f"[SLIPPAGE] ✅ Proceeding with order - acceptable slippage {slippage_pct:.2f}%")

        def _blocking_place():
            import inspect
            wb = self._client
            if not wb:
                raise RuntimeError("Webull client not initialized")
            base_sym = fix_symbol(symbol, "in")
            tId = wb.get_ticker(base_sym)
            if not tId:
                raise RuntimeError(f"Symbol not found: {base_sym}")

            side = 'BUY' if action.upper() in ('BTO', 'BTC') else 'SELL'
            
            adjusted_qty = qty
            
            if side == 'BUY':
                try:
                    account_info = wb.get_account()
                    account_members = account_info.get('accountMembers', [])
                    
                    # Convert list of {'key': 'name', 'value': 'value'} into a proper dict
                    account_data = {}
                    if account_members:
                        for item in account_members:
                            if isinstance(item, dict) and 'key' in item and 'value' in item:
                                account_data[item['key']] = item['value']
                    
                    # Try multiple possible field names for buying power
                    buying_power = 0.0
                    for field in ['buyingPower', 'cashAvailableForTrade', 'cashBalance', 'dayBuyingPower']:
                        if field in account_data:
                            try:
                                buying_power = float(account_data[field])
                                if buying_power > 0:
                                    break
                            except (ValueError, TypeError):
                                continue
                    
                    order_cost = qty * limit_price
                    
                    net_liq = float(account_data.get('netLiquidation', 0))
                    print(f"[FUNDS] Buying power: ${buying_power:.2f}, Order cost: ${order_cost:.2f} (Net liquidation: ${net_liq:.2f})")
                    
                    if buying_power <= 0:
                        return {
                            'success': False,
                            'msg': f'No buying power available: ${buying_power:.2f} (Account value: ${net_liq:.2f})',
                            'error': 'INSUFFICIENT_FUNDS'
                        }
                    
                    if order_cost > buying_power:
                        max_affordable_qty = int(buying_power / limit_price)
                        if max_affordable_qty > 0:
                            print(f"[FUNDS] ⚠️ Insufficient funds for {qty} shares")
                            print(f"[FUNDS] ✓ Adjusting quantity: {qty} → {max_affordable_qty} shares")
                            print(f"[FUNDS] Adjusted cost: ${max_affordable_qty * limit_price:.2f}")
                            adjusted_qty = max_affordable_qty
                        else:
                            return {
                                'success': False,
                                'msg': f'Insufficient buying power: have ${buying_power:.2f}, need ${order_cost:.2f}',
                                'error': 'INSUFFICIENT_FUNDS'
                            }
                except Exception as e:
                    print(f"[FUNDS] Warning: Could not check buying power: {e}")
            
            elif side == 'SELL':
                try:
                    positions = wb.get_positions()
                    if positions:
                        for pos in positions:
                            pos_symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                            pos_qty = float(pos.get('position', 0))
                            
                            is_stock = pos.get('assetType', '').lower() not in ('option', 'opt') and 'strikePrice' not in pos
                            
                            if is_stock and pos_symbol == base_sym and pos_qty > 0:
                                actual_qty = int(pos_qty)
                                if actual_qty < qty:
                                    print(f"[POSITION] ⚠️ Signal wants to sell {qty} shares")
                                    print(f"[POSITION] ✓ Adjusting to actual position: {qty} → {actual_qty} shares")
                                    adjusted_qty = actual_qty
                                elif actual_qty > qty:
                                    print(f"[POSITION] Selling {qty} of {actual_qty} shares held")
                                else:
                                    print(f"[POSITION] Selling all {actual_qty} shares")
                                break
                        else:
                            print(f"[POSITION] ⚠️ Warning: No matching stock position found for {base_sym}")
                            print(f"[POSITION] Proceeding with signal quantity: {qty}")
                except Exception as e:
                    print(f"[POSITION] Warning: Could not check positions: {e}")

            base_payload = {
                'stock': base_sym,
                'tId': int(tId),
                'price': float(limit_price),
                'lmtPrice': float(limit_price),
                'action': side,
                'orderType': 'LMT',
                'enforce': WB_ENFORCE,
                'quant': int(adjusted_qty),
                'outsideRegularTradingHour': True,
                'stpPrice': None,
                'trial_value': None,
                'trial_type': None,
            }

            func = None
            if hasattr(wb, 'place_order'):
                func = wb.place_order
            elif hasattr(wb, 'place_stock_order'):
                func = wb.place_stock_order
            else:
                raise RuntimeError("This webull client lacks place_order/place_stock_order.")

            try:
                sig = inspect.signature(func)
                allowed = set(sig.parameters.keys())
            except Exception:
                allowed = {'stock','tId','price','action','orderType','enforce','quant',
                           'outsideRegularTradingHour','stpPrice','trial_value','trial_type','lmtPrice'}
            payload = {k: v for k, v in base_payload.items() if k in allowed}

            if 'price' not in allowed and 'lmtPrice' in allowed:
                payload.pop('price', None)
            if 'lmtPrice' not in allowed and 'price' in payload:
                payload.pop('lmtPrice', None)

            print(f"[DEBUG] place_stock payload: {payload}")
            resp = func(**payload)
            print(f"[DEBUG] Webull place_stock response: {resp}")
            return resp

        return await self.loop.run_in_executor(None, _blocking_place)

    async def get_positions(self) -> list:
        """Get current open positions from Webull (stocks and options)"""
        def _blocking_get():
            wb = self._client
            if not wb:
                return []
            
            positions = []
            
            # Get all positions (stocks and options together)
            try:
                all_positions = wb.get_positions()
                if all_positions:
                    for pos in all_positions:
                        # Convert position to float for comparison (API may return string)
                        try:
                            position_qty = float(pos.get('position', 0))
                        except (ValueError, TypeError):
                            position_qty = 0
                        
                        if position_qty <= 0:  # Skip closed positions
                            continue
                        
                        # Determine asset type
                        symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                        asset_type = pos.get('assetType', 'unknown')
                        
                        # Check if this is an option by looking for option-specific fields
                        is_option = (
                            'optionId' in pos or 
                            'strikePrice' in pos or 
                            'expireDate' in pos or
                            asset_type in ('option', 'OPTION', 'OPT')
                        )
                        
                        if is_option:
                            # Option position - use tickerId to fetch details if missing
                            ticker_id = pos.get('tickerId', 0)
                            symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                            
                            # Try to get option details from API using tickerId
                            option_details = None
                            if ticker_id:
                                try:
                                    # Use tickerId as optionId to get full option details
                                    option_details = wb.get_option_quote(stock=symbol, optionId=str(ticker_id))
                                except Exception as e:
                                    print(f"[RISK] Warning: Could not fetch option details for {symbol}: {e}")
                            
                            # Extract option metadata from API response or fallback to empty
                            strike = 0.0
                            expiry = ''
                            direction = ''
                            option_id = ticker_id
                            
                            if option_details and isinstance(option_details, dict) and 'data' in option_details:
                                # Search for the matching option in the data array by tickerId
                                matched_option = None
                                for opt in option_details.get('data', []):
                                    if opt.get('tickerId') == ticker_id:
                                        matched_option = opt
                                        break
                                
                                if matched_option:
                                    # Extract metadata from matched option
                                    strike = float(matched_option.get('strikePrice', 0))
                                    
                                    # Convert expiry date: "2025-12-19" -> "12/19" or "12/19/25"
                                    raw_expiry = matched_option.get('expireDate', '')
                                    if raw_expiry:
                                        from datetime import datetime
                                        try:
                                            exp_date = datetime.strptime(raw_expiry, '%Y-%m-%d')
                                            current_year = datetime.now().year
                                            if exp_date.year == current_year:
                                                expiry = exp_date.strftime('%m/%d')  # Same year: "12/19"
                                            else:
                                                expiry = exp_date.strftime('%m/%d/%y')  # Future year: "12/19/25"
                                        except:
                                            expiry = raw_expiry
                                    
                                    # Convert direction: "call" -> "C", "put" -> "P"
                                    raw_direction = matched_option.get('direction', '').lower()
                                    if raw_direction == 'call':
                                        direction = 'C'
                                    elif raw_direction == 'put':
                                        direction = 'P'
                                    
                                    option_id = ticker_id
                                else:
                                    print(f"[RISK] Warning: Could not match option metadata for {symbol} (tickerId={ticker_id})")
                            
                            positions.append({
                                'asset': 'option',
                                'symbol': symbol,
                                'quantity': float(pos.get('position', 0)),
                                'avg_cost': float(pos.get('costPrice', 0)),
                                'current_price': float(pos.get('latestPrice', 0) or pos.get('lastPrice', 0)),
                                'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                                'option_id': option_id,
                                'strike': strike,
                                'expiry': expiry,
                                'direction': direction,
                                'ticker_id': ticker_id  # Keep for future lookups
                            })
                        else:
                            # Stock position
                            quantity = float(pos.get('position', 1))
                            market_value = float(pos.get('marketValue', 0))
                            current_price = market_value / quantity if quantity > 0 else 0
                            
                            positions.append({
                                'asset': 'stock',
                                'symbol': pos.get('ticker', {}).get('symbol', ''),
                                'quantity': quantity,
                                'avg_cost': float(pos.get('costPrice', 0)),
                                'current_price': current_price,
                                'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                                'ticker_id': pos.get('ticker', {}).get('tickerId', 0)
                            })
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch positions: {e}")
                import traceback
                traceback.print_exc()
            
            return positions
        
        return await self.loop.run_in_executor(None, _blocking_get)

    async def get_positions_detailed(self) -> list:
        """Alias for get_positions() - returns detailed position information"""
        return await self.get_positions()

    async def get_pending_orders(self) -> list:
        """Get all pending/open orders from Webull
        
        Returns:
            List of order dicts with keys: order_id, symbol, quantity, limit_price, action, status
        """
        def _blocking_get_orders():
            wb = self._client
            if not wb:
                return []
            
            try:
                orders_raw = wb.get_current_orders()
                orders = []
                
                if not orders_raw:
                    return []
                
                for order in orders_raw:
                    ticker = order.get('ticker', {})
                    symbol = ticker.get('symbol', '') if ticker else ''
                    
                    orders.append({
                        'order_id': str(order.get('orderId', '')),
                        'symbol': symbol,
                        'quantity': int(order.get('totalQuantity', 0)),
                        'limit_price': float(order.get('lmtPrice', 0)) if order.get('lmtPrice') else None,
                        'action': order.get('action', ''),
                        'status': order.get('status', ''),
                        'order_type': order.get('orderType', ''),
                        'filled_quantity': int(order.get('filledQuantity', 0))
                    })
                
                return orders
            except Exception as e:
                print(f"[Webull] Error getting pending orders: {e}")
                import traceback
                traceback.print_exc()
                return []
        
        return await self.loop.run_in_executor(None, _blocking_get_orders)

    async def get_latest_quote(self, symbol: str, asset_type: str = 'stock', option_id: Optional[int] = None):
        """Get latest price quote for a symbol"""
        def _blocking_quote():
            wb = self._client
            if not wb:
                return None
            
            try:
                if asset_type == 'option' and option_id is not None:
                    # For options, we need the option ID
                    quote = wb.get_option_quote(optionId=option_id)
                    if quote:
                        return float(quote.get('latestPrice', 0))
                else:
                    # For stocks
                    quote = wb.get_quote(stock=symbol)
                    if quote:
                        return float(quote.get('close', 0) or quote.get('lastPrice', 0))
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch quote for {symbol}: {e}")
            
            return None
        
        return await self.loop.run_in_executor(None, _blocking_quote)

    async def get_options_expiration_dates(self, symbol: str) -> list:
        """Get all available option expiration dates for a symbol"""
        def _blocking_get_expirations():
            wb = self._client
            if not wb:
                return []
            
            try:
                result = wb.get_options_expiration_dates(stock=symbol)
                
                # Handle both list (new API) and dict (old API) formats
                exp_list = []
                if isinstance(result, list):
                    exp_list = result
                elif isinstance(result, dict) and 'expireDateList' in result:
                    exp_list = result['expireDateList']
                
                if exp_list:
                    expirations = []
                    for exp in exp_list:
                        if isinstance(exp, dict):
                            exp_date = exp.get('date', '')
                            exp_label = exp.get('label', exp_date)
                        else:
                            exp_date = str(exp)
                            exp_label = exp_date
                        
                        if exp_date:
                            expirations.append({
                                'date': exp_date,
                                'label': exp_label,
                                'count': exp.get('count', 0) if isinstance(exp, dict) else 0
                            })
                    return expirations
                return []
            except Exception as e:
                print(f"[Webull] Error getting expiration dates for {symbol}: {e}")
                return []
        
        return await self.loop.run_in_executor(None, _blocking_get_expirations)

    async def get_option_chain(self, symbol: str, expiration_date: str) -> dict:
        """Get option chain for a symbol and expiration date"""
        def _blocking_chain():
            wb = self._client
            if not wb:
                return {'calls': [], 'puts': [], 'stock_price': None}
            
            try:
                def extract_option(row, direction):
                    """Extract option data from row - handles nested Webull structure.
                    Webull returns: [{"strikePrice": "600", "call": {...}, "put": {...}}, ...]
                    The actual bid/ask/tickerId are nested under 'call' or 'put' key.
                    """
                    if not row or not isinstance(row, dict):
                        return None
                    
                    # Get strike price from the row itself
                    strike_val = row.get('strikePrice') or row.get('strike')
                    if strike_val is None:
                        return None
                    
                    def extract_price_from_list(price_list):
                        """Extract best price from Webull bid/ask list format"""
                        if not price_list:
                            return 0.0
                        if isinstance(price_list, list) and len(price_list) > 0:
                            first = price_list[0]
                            if isinstance(first, dict):
                                return float(first.get('price', 0) or first.get('value', 0) or 0)
                            elif isinstance(first, (int, float)):
                                return float(first)
                        return 0.0
                    
                    # Check for nested data under 'call' or 'put' key
                    nested = row.get(direction)
                    if isinstance(nested, dict):
                        # Data is nested under direction key (this is the expected Webull structure)
                        oid = nested.get('tickerId') or nested.get('optionId') or nested.get('id')
                        
                        # Bid/ask might be in bidList/askList arrays or direct values
                        bid_list = nested.get('bidList')
                        ask_list = nested.get('askList')
                        if bid_list:
                            bid = extract_price_from_list(bid_list)
                        else:
                            bid = nested.get('bidPrice') or nested.get('bid') or 0
                        if ask_list:
                            ask = extract_price_from_list(ask_list)
                        else:
                            ask = nested.get('askPrice') or nested.get('ask') or 0
                        
                        last = nested.get('close') or nested.get('lastPrice') or nested.get('price') or 0
                        volume = nested.get('volume') or 0
                        oi = nested.get('openInterest') or 0
                        iv = nested.get('impVol') or nested.get('impliedVolatility') or 0
                        delta = nested.get('delta') or 0
                    else:
                        # Fallback: Data is directly in the row (alternative format)
                        oid = row.get('tickerId') or row.get('optionId') or row.get('id')
                        bid = row.get('bidPrice') or row.get('bid') or 0
                        ask = row.get('askPrice') or row.get('ask') or 0
                        last = row.get('lastPrice') or row.get('close') or row.get('price') or 0
                        volume = row.get('volume') or 0
                        oi = row.get('openInterest') or 0
                        iv = row.get('impVol') or row.get('impliedVolatility') or 0
                        delta = row.get('delta') or 0
                    
                    if oid is None:
                        return None
                    
                    try:
                        return {
                            'strike': float(strike_val),
                            'bid': float(bid) if bid else 0.0,
                            'ask': float(ask) if ask else 0.0,
                            'last': float(last) if last else 0.0,
                            'volume': int(volume) if volume else 0,
                            'open_interest': int(oi) if oi else 0,
                            'option_id': str(oid),
                            'iv': float(iv) if iv else 0.0,
                            'delta': float(delta) if delta else 0.0,
                            'needs_live_quote': (float(bid) if bid else 0.0) == 0 and (float(ask) if ask else 0.0) == 0
                        }
                    except (ValueError, TypeError):
                        return None
                
                def fetch_live_quote(option_id, symbol, strike=None):
                    """Fetch real-time quote for an option when chain data is missing bid/ask"""
                    try:
                        quote = wb.get_option_quote(stock=symbol, optionId=str(option_id))
                        if not quote:
                            return None
                        
                        # Price data may be in 'data' field or directly
                        if 'data' in quote and isinstance(quote['data'], list):
                            for opt in quote['data']:
                                if str(opt.get('tickerId')) == str(option_id):
                                    ask_list = opt.get('askList', [])
                                    bid_list = opt.get('bidList', [])
                                    ask = float(ask_list[0].get('price', 0)) if ask_list else 0
                                    bid = float(bid_list[0].get('price', 0)) if bid_list else 0
                                    last = float(opt.get('latestPrice', 0) or opt.get('close', 0) or 0)
                                    return {'bid': bid, 'ask': ask, 'last': last}
                        
                        # Try direct fields
                        ask_list = quote.get('askList', [])
                        bid_list = quote.get('bidList', [])
                        ask = float(ask_list[0].get('price', 0)) if ask_list else float(quote.get('askPrice', 0) or 0)
                        bid = float(bid_list[0].get('price', 0)) if bid_list else float(quote.get('bidPrice', 0) or 0)
                        last = float(quote.get('latestPrice', 0) or quote.get('close', 0) or quote.get('lastPrice', 0) or 0)
                        return {'bid': bid, 'ask': ask, 'last': last}
                    except Exception:
                        return None
                
                # Get call options
                calls = []
                seen_strikes = set()
                needs_live_quotes = False
                try:
                    call_data = wb.get_options(stock=symbol, direction='call', expireDate=expiration_date)
                    data_list = call_data if isinstance(call_data, list) else call_data.get('data', []) if isinstance(call_data, dict) else []
                    first_row_checked = False
                    for row in data_list:
                        if not first_row_checked and isinstance(row, dict):
                            if 'call' in row:
                                call_nested = row.get('call', {})
                                if isinstance(call_nested, dict):
                                    bid_list = call_nested.get('bidList', [])
                                    ask_list = call_nested.get('askList', [])
                                    if not bid_list and not ask_list:
                                        needs_live_quotes = True
                            first_row_checked = True
                        opt = extract_option(row, 'call')
                        if opt and opt['strike'] not in seen_strikes:
                            seen_strikes.add(opt['strike'])
                            calls.append(opt)
                except Exception as e:
                    print(f"[Webull] Error: Could not fetch calls for {symbol}: {e}")
                
                # Get put options
                puts = []
                seen_strikes = set()
                try:
                    put_data = wb.get_options(stock=symbol, direction='put', expireDate=expiration_date)
                    data_list = put_data if isinstance(put_data, list) else put_data.get('data', []) if isinstance(put_data, dict) else []
                    for row in data_list:
                        opt = extract_option(row, 'put')
                        if opt and opt['strike'] not in seen_strikes:
                            seen_strikes.add(opt['strike'])
                            puts.append(opt)
                except Exception as e:
                    print(f"[Webull] Error: Could not fetch puts for {symbol}: {e}")
                
                # If chain data is missing bid/ask, fetch live quotes for ATM options
                if needs_live_quotes and (calls or puts):
                    
                    # Get stock price to determine ATM range
                    stock_price = None
                    try:
                        quote = wb.get_quote(stock=symbol)
                        if quote:
                            stock_price = float(quote.get('close', 0) or quote.get('lastPrice', 0))
                    except:
                        pass
                    
                    if stock_price:
                        # Fetch live quotes for strikes closest to ATM first (limit to 30 options)
                        atm_range = stock_price * 0.10  # 10% range for speed
                        max_live_quotes = 30  # Balance between coverage and speed
                        
                        # Sort options by distance from ATM (closest first)
                        atm_calls = [opt for opt in calls if opt.get('needs_live_quote') and abs(opt['strike'] - stock_price) <= atm_range]
                        atm_puts = [opt for opt in puts if opt.get('needs_live_quote') and abs(opt['strike'] - stock_price) <= atm_range]
                        
                        atm_calls.sort(key=lambda x: abs(x['strike'] - stock_price))
                        atm_puts.sort(key=lambda x: abs(x['strike'] - stock_price))
                        
                        # Alternate between calls and puts, starting with closest to ATM
                        all_atm_opts = []
                        for i in range(max(len(atm_calls), len(atm_puts))):
                            if i < len(atm_calls):
                                all_atm_opts.append(atm_calls[i])
                            if i < len(atm_puts):
                                all_atm_opts.append(atm_puts[i])
                        
                        # Limit to max_live_quotes
                        all_atm_opts = all_atm_opts[:max_live_quotes]
                        
                        # Parallel fetch using ThreadPoolExecutor for speed
                        import concurrent.futures
                        
                        def fetch_quote_for_opt(opt):
                            live_data = fetch_live_quote(opt['option_id'], symbol, opt['strike'])
                            return (opt, live_data)
                        
                        live_quote_count = 0
                        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                            futures = [executor.submit(fetch_quote_for_opt, opt) for opt in all_atm_opts]
                            for future in concurrent.futures.as_completed(futures):
                                try:
                                    opt, live_data = future.result(timeout=5)
                                    if live_data:
                                        opt['bid'] = live_data['bid']
                                        opt['ask'] = live_data['ask']
                                        if live_data['last'] > 0:
                                            opt['last'] = live_data['last']
                                        opt['needs_live_quote'] = False
                                        live_quote_count += 1
                                except:
                                    pass
                        
                
                # Get stock price
                stock_price = None
                try:
                    quote = wb.get_quote(stock=symbol)
                    if quote:
                        stock_price = float(quote.get('close', 0) or quote.get('lastPrice', 0))
                except Exception as e:
                    print(f"[Webull] Warning: Could not fetch stock price for {symbol}: {e}")
                
                return {
                    'calls': calls,
                    'puts': puts,
                    'stock_price': stock_price,
                    'expiration': expiration_date,
                    'symbol': symbol
                }
                
            except Exception as e:
                print(f"[Webull] Error getting option chain for {symbol} {expiration_date}: {e}")
                import traceback
                traceback.print_exc()
                return {'calls': [], 'puts': [], 'stock_price': None}
        
        return await self.loop.run_in_executor(None, _blocking_chain)


# ------------------------------ SIGNAL PARSER -------------------------------------
# Compile alternate pattern regex
ALT_OPT_REGEX = re.compile(ALT_OPT_PATTERN, re.IGNORECASE)
STEEL_BTO_REGEX = re.compile(STEEL_BTO_PATTERN, re.IGNORECASE)
STEEL_STC_REGEX = re.compile(STEEL_STC_PATTERN, re.IGNORECASE)
STEEL_STC_WITH_PREFIX_REGEX = re.compile(STEEL_STC_WITH_PREFIX_PATTERN, re.IGNORECASE)
STC_QTY_AT_REGEX = re.compile(STC_QTY_AT_PATTERN, re.IGNORECASE)
STEEL_BTO_EXTENDED_REGEX = re.compile(STEEL_BTO_EXTENDED_PATTERN, re.IGNORECASE)
SIMPLE_STC_REGEX = re.compile(SIMPLE_STC_PATTERN, re.IGNORECASE)
SIRENRED_PRICE_STC_REGEX = re.compile(SIRENRED_PRICE_STC_PATTERN, re.IGNORECASE)
PRICE_ONLY_STC_REGEX = re.compile(PRICE_ONLY_STC_PATTERN, re.IGNORECASE)
JC_OPT_REGEX = re.compile(JC_OPT_PATTERN, re.IGNORECASE)
SPX_NDX_SHORTHAND_REGEX = re.compile(SPX_NDX_SHORTHAND_PATTERN, re.IGNORECASE)
WAXUI_ENTRY_REGEX = re.compile(WAXUI_ENTRY_PATTERN, re.IGNORECASE)
WAXUI_TRIM_REGEX = re.compile(WAXUI_TRIM_PATTERN, re.IGNORECASE)
WAXUI_CLOSE_REGEX = re.compile(WAXUI_CLOSE_PATTERN, re.IGNORECASE)

def parse_option_signal(text: str) -> Optional[dict]:
    learned_result = try_parse_with_learned_formats(text)
    if learned_result and learned_result.get('asset') == 'option':
        print(f"[SIGNAL] Parsed using learned format: {learned_result.get('action')} {learned_result.get('symbol')} {learned_result.get('strike')}{learned_result.get('opt_type')}")
        return learned_result
    
    m = OPT_REGEX.search(text.strip())
    use_alt_format = False
    use_steel_format = False
    use_steel_stc = False
    use_jc_format = False
    
    if not m:
        # Try JC format first: BTO $QQQ $627c 12/10 .77
        m = JC_OPT_REGEX.search(text.strip())
        if m:
            use_jc_format = True
            print(f"[Discord] ✓ Matched JC format (strike+type combined)")
        else:
            # Try alternate format: 🟢**BTO $RKT | 21.2 C JAN/16 .56**
            m = ALT_OPT_REGEX.search(text.strip())
            if m:
                use_alt_format = True
                print(f"[Discord] ✓ Matched alternate format (pipe-separated)")
            else:
                # Try steel BTO format: :green_alert: AAPL | $282.5 C 1.72 NEXT WEEK
                m = STEEL_BTO_REGEX.search(text.strip())
                if m:
                    use_steel_format = True
                    print(f"[Discord] ✓ Matched steel BTO format")
                else:
                    # Try extended BTO format: :green_alert: TSLA | $492.5 10.10 JAN 2ND
                    m = STEEL_BTO_EXTENDED_REGEX.search(text.strip())
                    if m:
                        symbol, strike, price_str, month_name, day = m.groups()
                        month = MONTH_NAMES.get(month_name.upper(), '01')
                        expiry = f"{month}/{day}"
                        price = float(price_str)
                        print(f"[Discord] ✓ Matched steel BTO extended format: {symbol} {strike}C {expiry} @ ${price}")
                        _current_trading_settings = get_trading_settings()
                        max_position_size = _current_trading_settings['max_position_size']
                        actual_cost_per_contract = price * 100
                        qty = max(1, int(max_position_size / actual_cost_per_contract)) if actual_cost_per_contract > 0 else 1
                        print(f"[AUTO-QTY] Extended BTO: ${price} x 100 = ${actual_cost_per_contract}/contract, buying {qty} (max ${max_position_size})")
                        return {
                            "asset": "option",
                            "action": "BTO",
                            "qty": qty,
                            "symbol": symbol.upper(),
                            "strike": float(strike),
                            "opt_type": "C",  # Assume call for this format
                            "expiry": expiry,
                            "price": price,
                            "is_market_order": False,
                            "_steel_extended": True
                        }
                    else:
                        # Try steel STC with STC prefix: :SirenRed: STC $RKT | .70 OUT ALL
                        m = STEEL_STC_WITH_PREFIX_REGEX.search(text.strip())
                        if m:
                            use_steel_stc = True
                            print(f"[Discord] ✓ Matched steel STC with prefix format")
                        else:
                            # Try STC with qty and @ price: :SirenRed: STC 4 RKT @ .75
                            m = STC_QTY_AT_REGEX.search(text.strip())
                            if m:
                                qty, symbol, price_str = m.groups()
                                price = float(price_str)
                                print(f"[Discord] ✓ Matched STC qty @ price format: STC {qty} {symbol} @ ${price}")
                                return {
                                    "asset": "option",
                                    "action": "STC",
                                    "qty": int(qty),
                                    "symbol": symbol.upper(),
                                    "strike": None,
                                    "opt_type": None,
                                    "expiry": None,
                                    "price": price,
                                    "is_market_order": False,
                                    "_exit_type": "ALL",
                                    "_stc_qty_at": True
                                }
                            else:
                                # Try steel STC format: :SirenRed: AAPL | 1.82 OUT HALF
                                m = STEEL_STC_REGEX.search(text.strip())
                                if m:
                                    use_steel_stc = True
                                    print(f"[Discord] ✓ Matched steel STC format")
                                else:
                                    # Try simple STC format: TSLA 5.03 OUT
                                    m = SIMPLE_STC_REGEX.search(text.strip())
                                    if m:
                                        use_steel_stc = True
                                        print(f"[Discord] ✓ Matched simple STC format (SYMBOL PRICE OUT)")
                                    else:
                                        # Try :SirenRed: with price only (no symbol): :SirenRed: 4.67 OUT
                                        m = SIRENRED_PRICE_STC_REGEX.search(text.strip())
                                        if m:
                                            use_steel_stc = True
                                            print(f"[Discord] ✓ Matched SirenRed price-only STC format")
                                        else:
                                            # Try price-only STC: 5.38 out all but 1
                                            m = PRICE_ONLY_STC_REGEX.search(text.strip())
                                            if m:
                                                use_steel_stc = True
                                                print(f"[Discord] ✓ Matched price-only STC format")
                                            else:
                                                # Try Waxui entry: SPX here 12/05 6880C Avg. 4.00
                                                m = WAXUI_ENTRY_REGEX.search(text.strip())
                                                if m:
                                                    symbol, month, day, strike, opt_type, price_str = m.groups()
                                                    expiry = f"{month}/{day}"
                                                    price = float(price_str)
                                                    print(f"[Discord] ✓ Matched Waxui entry format: {symbol} {expiry} {strike}{opt_type} Avg ${price_str}")
                                                    _current_trading_settings = get_trading_settings()
                                                    max_position_size = _current_trading_settings['max_position_size']
                                                    actual_cost_per_contract = price * 100
                                                    if actual_cost_per_contract <= 0:
                                                        qty = 1
                                                    else:
                                                        qty = max(1, int(max_position_size / actual_cost_per_contract))
                                                    print(f"[AUTO-QTY] Waxui: ${price} premium x 100 = ${actual_cost_per_contract}/contract, buying {qty} contracts (max ${max_position_size})")
                                                    return {
                                                        "asset": "option",
                                                        "action": "BTO",
                                                        "qty": qty,
                                                        "symbol": symbol.upper(),
                                                        "strike": float(strike),
                                                        "opt_type": opt_type.upper(),
                                                        "expiry": expiry,
                                                        "price": price,
                                                        "is_market_order": False,
                                                        "_waxui_format": True
                                                    }
                                                else:
                                                    # Try Waxui close: Closed SPX here
                                                    m = WAXUI_CLOSE_REGEX.search(text.strip())
                                                    if m:
                                                        symbol = m.group(1)
                                                        print(f"[Discord] ✓ Matched Waxui CLOSE format: {symbol}")
                                                        return {
                                                            "asset": "option",
                                                            "action": "STC",
                                                            "qty": 1,
                                                            "symbol": symbol.upper(),
                                                            "strike": None,
                                                            "opt_type": None,
                                                            "expiry": None,
                                                            "price": None,
                                                            "is_market_order": True,
                                                            "_waxui_close": True,
                                                            "_exit_type": "ALL"
                                                        }
                                                    else:
                                                        # Try Waxui trim: Trim SPX here
                                                        m = WAXUI_TRIM_REGEX.search(text.strip())
                                                        if m:
                                                            symbol = m.group(1)
                                                            print(f"[Discord] ✓ Matched Waxui TRIM format: {symbol}")
                                                            return {
                                                                "asset": "option",
                                                                "action": "STC",
                                                                "qty": 1,
                                                                "symbol": symbol.upper(),
                                                                "strike": None,
                                                                "opt_type": None,
                                                                "expiry": None,
                                                                "price": None,
                                                                "is_market_order": True,
                                                                "_waxui_trim": True,
                                                                "_exit_type": "HALF"
                                                            }
                                                        else:
                                                            # Try SPX/NDX shorthand: 6900c, BTO 25 6900c, STC 15000p
                                                            m = SPX_NDX_SHORTHAND_REGEX.search(text.strip())
                                                            if m:
                                                                action, qty_str, strike_str, opt_type = m.groups()
                                                                strike = float(strike_str)
                                                                symbol = "NDX" if strike >= 10000 else "SPX"
                                                                action = (action or "BTO").upper()
                                                                qty = int(qty_str) if qty_str else 1
                                                                from datetime import datetime
                                                                today = datetime.now()
                                                                expiry = today.strftime("%m/%d")
                                                                print(f"[Discord] ✓ Matched SPX/NDX shorthand: {action} {qty} {symbol} {strike}{opt_type.upper()} {expiry} @ MARKET")
                                                                return {
                                                                    "asset": "option",
                                                                    "action": action,
                                                                    "qty": qty,
                                                                    "symbol": symbol,
                                                                    "strike": strike,
                                                                    "opt_type": opt_type.upper(),
                                                                    "expiry": expiry,
                                                                    "price": None,
                                                                    "is_market_order": True,
                                                                    "_spx_ndx_shorthand": True
                                                                }
                                                            else:
                                                                # Silently return None - let the caller try other formats (stock, TRADE IDEA)
                                                                return None
    
    if use_steel_stc:
        # Handle various STC formats with different group structures
        groups = m.groups()
        symbol = None
        price_str = None
        exit_type = "ALL"
        
        # Determine format based on matched regex and groups
        text_stripped = text.strip()
        
        # Check if it's a price-only format (no symbol)
        if SIRENRED_PRICE_STC_REGEX.search(text_stripped) or PRICE_ONLY_STC_REGEX.search(text_stripped):
            if len(groups) == 2:
                # Price-only formats: (price, exit_type)
                price_str, exit_type = groups
                symbol = None  # Will need to find from most recent open position
                print(f"[Discord] Price-only STC: @ ${price_str}, exit type: {exit_type}")
        elif len(groups) == 3:
            # Steel STC format groups: (symbol, price, exit_type)
            symbol, price_str, exit_type = groups
        elif len(groups) == 2:
            # Simple STC format groups: (symbol, price)
            symbol, price_str = groups
            exit_type = "ALL"
        
        direction = 'STC'
        
        # For STC, we need to find the matching open position
        if symbol:
            print(f"[Discord] Steel STC: {symbol} @ ${price_str}, exit type: {exit_type}")
        else:
            print(f"[Discord] Price-only STC: @ ${price_str}, exit type: {exit_type} (will match to recent position)")
        
        # We don't have strike/expiry from STC signal - need to match to open position
        # Return a special signal that will trigger position lookup
        return {
            "asset": "option",
            "action": "STC",
            "qty": 1,  # Will be overridden by position lookup
            "symbol": symbol.upper() if symbol else None,  # None means find most recent position
            "strike": None,  # Will need position lookup
            "opt_type": None,  # Will need position lookup
            "expiry": None,  # Will need position lookup
            "price": float(price_str),
            "is_market_order": False,
            "_steel_stc": True,  # Flag for position lookup
            "_price_only": symbol is None,  # Flag for price-only format
            "_exit_type": exit_type.strip().upper() if exit_type else "ALL"
        }
    
    if use_jc_format:
        # JC format groups: (direction, symbol, strike, opt_type, month, day, price)
        direction, symbol, strike, opt_type, month, day, price_str = m.groups()
        qty_str = None  # JC format doesn't include quantity
        expiry = f"{month}/{day}"
        print(f"[Discord] JC format parsed: {direction} {symbol} {strike}{opt_type} {expiry} @ {price_str}")
    elif use_steel_format:
        # Steel BTO format groups: (symbol, strike, opt_type, price, expiry_text)
        symbol, strike, opt_type, price_str, expiry_text = m.groups()
        direction = 'BTO'
        qty_str = None  # Steel format doesn't include quantity
        
        # Calculate expiry from text
        if expiry_text:
            expiry_upper = expiry_text.strip().upper()
            if 'NEXT' in expiry_upper and 'WEEK' in expiry_upper:
                expiry = calculate_next_week_expiry()
                print(f"[Discord] Calculated NEXT WEEK expiry: {expiry}")
            elif 'THIS' in expiry_upper and 'WEEK' in expiry_upper:
                expiry = calculate_this_week_expiry()
                print(f"[Discord] Calculated THIS WEEK expiry: {expiry}")
            elif 'TOMORROW' in expiry_upper:
                expiry = calculate_tomorrow_expiry()
                print(f"[Discord] Calculated TOMORROW expiry: {expiry}")
            elif '/' in expiry_text:
                expiry = expiry_text.strip()
            else:
                # Default to this Friday
                expiry = calculate_this_week_expiry()
                print(f"[Discord] No expiry specified, defaulting to this Friday: {expiry}")
        else:
            # Default to this Friday if no expiry text
            expiry = calculate_this_week_expiry()
            print(f"[Discord] No expiry specified, defaulting to this Friday: {expiry}")
    elif use_alt_format:
        # Alt format groups: (action, symbol, strike, opt_type, month, day, price)
        direction, symbol, strike, opt_type, month_str, day, price_str = m.groups()
        qty_str = None  # Alternate format doesn't include quantity
        
        # Convert month name to number if needed
        month_upper = month_str.upper()
        if month_upper in MONTH_NAMES:
            month = MONTH_NAMES[month_upper]
        else:
            month = month_str.zfill(2)  # Pad single digit months
        
        expiry = f"{month}/{day}"
        print(f"[Discord] Converted expiry: {month_str}/{day} → {expiry}")
    else:
        direction, qty_str, symbol, strike, opt_type, expiry, price_str = m.groups()
    
    # Check for market order: "@ m" or "@m" means execute at market price
    is_market_order = price_str.lower() == 'm'
    if is_market_order:
        price = None  # Market order - price will be determined at execution
        print(f"[SIGNAL] Market order detected for {symbol} {strike}{opt_type} {expiry}")
    else:
        price = float(price_str)
    
    # Calculate quantity if not specified
    # CRITICAL: Options cost 100x the quoted premium (1 contract = 100 shares)
    if qty_str is None:
        if is_market_order:
            # For market orders without qty, default to 1 contract
            qty = 1
            print(f"[AUTO-QTY] Market order: defaulting to 1 contract")
        else:
            # Fetch latest max position size from database
            _current_trading_settings = get_trading_settings()
            max_position_size = _current_trading_settings['max_position_size']
            
            actual_cost_per_contract = price * 100
            if actual_cost_per_contract <= 0:
                print(f"[AUTO-QTY] ✗ Invalid option price: ${price}, skipping auto-calculation")
                return None
            qty = max(1, int(max_position_size / actual_cost_per_contract))
            print(f"[AUTO-QTY] Option: ${price} premium x 100 = ${actual_cost_per_contract}/contract, buying {qty} contracts (max ${max_position_size})")
    else:
        qty = int(qty_str)
    
    return {
        "asset": "option",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "strike": float(strike),
        "opt_type": opt_type.upper(),
        "expiry": expiry,
        "price": price,  # None for market orders
        "is_market_order": is_market_order
    }

def try_parse_with_learned_formats(text: str) -> Optional[dict]:
    """
    Try to parse signal using learned formats from database.
    Returns parsed signal dict if successful, None otherwise.
    Uses "teach once, use forever" approach - no AI cost per message.
    """
    try:
        import sys
        from pathlib import Path
        gui_app_path = str(Path(__file__).parent.parent / 'gui_app')
        if gui_app_path not in sys.path:
            sys.path.insert(0, gui_app_path)
        
        from gui_app.format_trainer import get_format_trainer
        trainer = get_format_trainer()
        
        result = trainer.try_parse_with_learned_formats(text)
        
        if result and result.get('action'):
            action = result.get('action', '').upper()
            symbol = result.get('symbol', '').upper()
            
            if not symbol:
                return None
            
            is_option = result.get('is_option', False)
            entry_price = result.get('entry_price')
            quantity = result.get('quantity')
            
            if is_option:
                strike = result.get('strike')
                expiry = result.get('expiration', '')
                opt_type = result.get('option_type', 'C').upper()
                
                if expiry:
                    if '/' in expiry:
                        parts = expiry.split('/')
                        if len(parts) == 2:
                            expiry = f"{parts[0].zfill(2)}/{parts[1].zfill(2)}"
                        elif len(parts) == 3:
                            expiry = f"{parts[0].zfill(2)}/{parts[1].zfill(2)}"
                
                if quantity is None:
                    quantity = 1
                
                return {
                    "asset": "option",
                    "action": action,
                    "qty": int(quantity) if quantity else 1,
                    "symbol": symbol,
                    "strike": float(strike) if strike else 0,
                    "opt_type": opt_type,
                    "expiry": expiry or '',
                    "price": float(entry_price) if entry_price else None,
                    "is_market_order": entry_price is None,
                    "parsed_by": "learned_format",
                    "profit_targets": result.get('profit_targets'),
                    "stop_loss": result.get('stop_loss')
                }
            else:
                if quantity is None:
                    quantity = 1
                
                return {
                    "asset": "stock",
                    "action": action,
                    "qty": int(quantity) if quantity else 1,
                    "symbol": symbol,
                    "price": float(entry_price) if entry_price else None,
                    "is_market_order": entry_price is None,
                    "parsed_by": "learned_format",
                    "profit_targets": result.get('profit_targets'),
                    "stop_loss": result.get('stop_loss')
                }
        
        return None
        
    except ImportError:
        return None
    except Exception as e:
        print(f"[LEARNED_FORMAT] Error parsing with learned formats: {e}")
        return None


def parse_stock_signal(text: str) -> Optional[dict]:
    learned_result = try_parse_with_learned_formats(text)
    if learned_result and learned_result.get('asset') == 'stock':
        print(f"[SIGNAL] Parsed using learned format: {learned_result.get('action')} {learned_result.get('symbol')}")
        return learned_result
    
    m = STK_REGEX.search(text.strip())
    if not m:
        return None
    direction, qty_str, symbol, price_str = m.groups()
    
    # Check for market order: "@ m" or "@m" means execute at market price
    is_market_order = price_str.lower() == 'm'
    if is_market_order:
        price = None  # Market order - price will be determined at execution
        print(f"[SIGNAL] Market order detected for {symbol}")
    else:
        price = float(price_str)
    
    # Calculate quantity if not specified
    if qty_str is None:
        if is_market_order:
            # For market orders without qty, default to 1 share
            qty = 1
            print(f"[AUTO-QTY] Market order: defaulting to 1 share")
        else:
            # Fetch latest max position size from database
            _current_trading_settings = get_trading_settings()
            max_position_size = _current_trading_settings['max_position_size']
            
            if price <= 0:
                print(f"[AUTO-QTY] ✗ Invalid stock price: ${price}, skipping auto-calculation")
                return None
            qty = max(1, int(max_position_size / price))
            print(f"[AUTO-QTY] Stock: ${price}/share, buying {qty} shares (max ${max_position_size})")
    else:
        qty = int(qty_str)
    
    return {
        "asset": "stock",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "price": price,  # None for market orders
        "is_market_order": is_market_order
    }

# ------------------------------ DISCORD SELF-BOT -------------------------------------
class SelfClient(discord.Client):
    def __init__(self, **kwargs):
        # Ensure intents are set for compatibility with newer discord.py-self versions
        # Older versions (like on Replit) don't have Intents, newer versions require it
        if 'intents' not in kwargs and hasattr(discord, 'Intents'):
            intents = discord.Intents.default()
            intents.guilds = True
            intents.messages = True
            intents.message_content = True
            kwargs['intents'] = intents
        
        super().__init__(**kwargs)
        # Initialize async objects to None - will be created in setup() when event loop is ready
        self.order_queue = None
        self.broker: Optional[WebullBroker] = None
        self.broker_ready = None
        self.processing_ready = None
        self._send_lock = None
        
        # Message deduplication (prevent duplicate event processing from Discord self-bot)
        self._processed_messages: set = set()
        self._max_processed_cache = 1000  # Keep last 1000 message IDs
        
        # Command execution lock (prevent race conditions)
        self._executing_commands: set = set()  # Track currently executing command message IDs
        
        # Sent message tracking (prevent duplicate sends from discord.py-self bug)
        self._recent_sends: dict = {}  # {content_hash: timestamp}
        self._send_dedupe_window = 300.0  # 5 minutes (discord.py-self can resend messages after long delays)
        
        # Initialize AI analyzers if enabled
        self.trade_analyzer = None
        self.sentiment_analyzer = None
        self.trade_tracker = None
        if ENABLE_AI_ANALYSIS and AI_IMPORTS_AVAILABLE:
            try:
                self.trade_analyzer = TradeAnalyzer(model=AI_MODEL)
                if ENABLE_SENTIMENT:
                    self.sentiment_analyzer = SentimentAnalyzer(model=AI_MODEL)
                print(f"[AI] ✓ AI analyzers initialized (model: {AI_MODEL})")
            except Exception as e:
                print(f"[AI] ⚠️  Failed to initialize AI analyzers: {e}")
                self.trade_analyzer = None
                self.sentiment_analyzer = None
        
        # Initialize Alpha Vantage scanner if enabled
        self.av_scanner = None
        if ENABLE_AV_SCANNER and ALPHA_VANTAGE_AVAILABLE:
            try:
                self.av_scanner = AlphaVantageScanner()
                print(f"[ALPHA VANTAGE] ✓ Scanner initialized")
            except Exception as e:
                print(f"[ALPHA VANTAGE] ⚠️  Failed to initialize scanner: {e}")
                self.av_scanner = None
        
        # Initialize Swing Trading Analyzer if enabled
        self.swing_analyzer = None
        if ENABLE_SWING_ANALYSIS and SWING_ANALYZER_AVAILABLE:
            try:
                self.swing_analyzer = SwingTradeAnalyzer()
                print(f"[SWING] ✓ Swing trading analyzer initialized")
            except Exception as e:
                print(f"[SWING] ⚠️  Failed to initialize swing analyzer: {e}")
                self.swing_analyzer = None
        
        # Initialize News Service if enabled
        self.news_service = None
        if ENABLE_NEWS and NEWS_SERVICE_AVAILABLE:
            try:
                self.news_service = NewsService(cache_ttl_minutes=NEWS_CACHE_TTL)
                print(f"[NEWS] ✓ News service initialized (provider: {NEWS_PROVIDER})")
            except Exception as e:
                print(f"[NEWS] ⚠️  Failed to initialize news service: {e}")
                self.news_service = None
        
        # Initialize Fundamental Analyzer
        self.fundamental_analyzer = None
        if SWING_ANALYZER_AVAILABLE:  # Uses yfinance like swing analyzer
            try:
                self.fundamental_analyzer = FundamentalAnalyzer()
                print(f"[FUNDAMENTAL] ✓ Fundamental analyzer initialized")
            except Exception as e:
                print(f"[FUNDAMENTAL] ⚠️  Failed to initialize fundamental analyzer: {e}")
                self.fundamental_analyzer = None
        
        # Initialize database connection for GUI integration
        self.db = None
        try:
            import sys
            from pathlib import Path
            parent_dir = Path(__file__).parent.parent
            if str(parent_dir) not in sys.path:
                sys.path.insert(0, str(parent_dir))
            
            from gui_app.database import Database
            self.db = Database()
            print("[DATABASE] ✓ Database initialized")
        except Exception as e:
            print(f"[DATABASE] ⚠️  Failed to initialize: {e} - GUI features disabled")
            self.db = None
        
        # Risk Manager (pluggable module) - initialized in setup() when async context ready
        self.risk_manager = None
    
    def _get_channel_category(self, channel_id: int) -> Optional[str]:
        """Get channel category from database (EXECUTE or TRACK) - legacy method"""
        channel_info = self._get_channel_info(channel_id)
        return channel_info['category'] if channel_info else None
    
    def _get_channel_info(self, channel_id: int) -> Optional[dict]:
        """Get full channel information from database including dual-mode flags"""
        if not self.db:
            return None
        
        try:
            channels = self.db.get_channels()
            for channel in channels:
                if channel['discord_channel_id'] == str(channel_id) and channel['is_active']:
                    return channel
            return None
        except Exception as e:
            print(f"[DATABASE] Error checking channel info: {e}")
            return None
    
    def _save_signal_to_db(self, signal: dict, channel_id: int, message_id: int, author_name: str = None):
        """Save signal to database for tracking and process PNL"""
        if not self.db:
            return
        
        try:
            # Save signal to database first (with author attribution and option details)
            signal_id = self.db.add_signal(
                discord_channel_id=str(channel_id),
                message_id=str(message_id),
                signal_type=signal['action'],
                symbol=signal['symbol'],
                quantity=signal['qty'],
                price=signal.get('price'),
                asset_type=signal['asset'],
                author_name=author_name,
                strike=signal.get('strike'),
                expiry=signal.get('expiry'),
                call_put=signal.get('opt_type')
            )
            
            # Get database channel_id
            import sys
            from pathlib import Path
            parent_dir = Path(__file__).parent.parent
            if str(parent_dir) not in sys.path:
                sys.path.insert(0, str(parent_dir))
            
            from gui_app.database import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM channels WHERE discord_channel_id = ?', (str(channel_id),))
            channel_row = cursor.fetchone()
            db_channel_id = channel_row['id'] if channel_row else None
            
            # Add database IDs and author info to signal for lot processing
            signal['signal_id'] = signal_id
            signal['channel_id'] = channel_id  # Discord channel ID for lot matcher
            signal['db_channel_id'] = db_channel_id  # Database channel ID
            signal['author_name'] = author_name  # User attribution for PNL tracker
            
            # Process PNL tracking with lot matcher
            self._process_lot_tracking(signal, channel_id, message_id)
            
        except Exception as e:
            print(f"[DATABASE] Error saving signal: {e}")
    
    def _process_lot_tracking(self, signal: dict, channel_id: int, message_id: int):
        """Process BTO/STC signals for PNL tracking using FIFO lot matching"""
        if not self.db:
            return
        
        try:
            # Import lot matcher
            import sys
            from pathlib import Path
            parent_dir = Path(__file__).parent.parent
            if str(parent_dir) not in sys.path:
                sys.path.insert(0, str(parent_dir))
            
            from gui_app.lot_matcher import get_matcher
            from datetime import datetime
            
            # Add signal metadata
            signal['channel_id'] = channel_id
            signal['received_at'] = datetime.now()
            
            # Get signal ID from database (last inserted)
            conn = self.db.get_connection() if hasattr(self.db, 'get_connection') else None
            if conn:
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM signals WHERE message_id = ?', (str(message_id),))
                result = cursor.fetchone()
                if result:
                    signal['signal_id'] = result['id']
            
            # Process with lot matcher
            matcher = get_matcher()
            result = matcher.process_signal(signal)
            
            price_str = f"${signal['price']}" if signal.get('price') is not None else "MARKET"
            if signal['action'] == 'BTO':
                print(f"[PNL_TRACKER] ✓ Created lot for {signal['symbol']} BTO {signal['qty']} @ {price_str}")
            elif signal['action'] == 'STC' and result:
                print(f"[PNL_TRACKER] ✓ Closed {len(result)} lot(s) for {signal['symbol']} STC {signal['qty']} @ {price_str}")
            
        except Exception as e:
            print(f"[PNL_TRACKER] Error processing lot: {e}")
            import traceback
            traceback.print_exc()
    
    def _save_trade_to_db(self, signal: dict, channel_id: int, execution_result: dict):
        """Save executed trade to database"""
        if not self.db:
            return
        
        try:
            # Determine broker from execution result or signal
            broker = execution_result.get('broker', 'webull')
            # Normalize broker name to uppercase for consistency
            if broker:
                broker = broker.upper()
            
            # Build trade data dict matching add_trade() expected format
            trade_data = {
                'symbol': signal['symbol'],
                'asset_type': signal.get('asset', 'stock'),
                'direction': signal['action'],
                'quantity': signal['qty'],
                'intended_price': signal.get('price'),
                'executed_price': signal.get('price'),
                'broker': broker,
                'channel_id': str(channel_id),
                'message_id': signal.get('message_id'),
                'order_id': execution_result.get('orderId') or execution_result.get('order_id'),
                'strike': signal.get('strike'),
                'expiry': signal.get('expiry'),
                'call_put': signal.get('opt_type') or signal.get('call_put'),
                'status': 'PENDING' if signal['action'] == 'BTO' else 'CLOSED',
                'source': 'discord'
            }
            
            self.db.add_trade(trade_data)
            print(f"[DATABASE] ✓ Trade saved: {signal['symbol']} {signal['action']} qty={signal['qty']} order_id={trade_data.get('order_id')}")
        except Exception as e:
            print(f"[DATABASE] Error saving trade: {e}")
            import traceback
            traceback.print_exc()

    async def setup(self):
        # Create async objects NOW when event loop is properly set up (fixes Windows "different loop" error)
        self.order_queue = asyncio.Queue()
        self.broker_ready = asyncio.Event()
        self.processing_ready = asyncio.Event()
        self._send_lock = asyncio.Lock()
        print("[ASYNC] ✓ Queue and events created in event loop")
        
        self.broker = WebullBroker(loop=self.loop)
        try:
            await self.broker.login()
            if self.broker._logged_in:
                print("[Webull] ✓ Login successful (LIVE account)", flush=True)
                self.broker_ready.set()
            else:
                print("[Webull] ⚠️  Broker not configured - configure via GUI (see startup logs for port)", flush=True)
        except Exception as e:
            print("[Webull] ✗ Login failed:", e, flush=True)
        
        # Initialize Alpaca paper trading broker for tracking channels
        try:
            _original_print("[ALPACA] Starting paper broker initialization...", flush=True)
            _original_print(f"[ALPACA] ALPACA_AVAILABLE: {ALPACA_AVAILABLE}", flush=True)
            
            if not ALPACA_AVAILABLE:
                _original_print("[ALPACA] ⚠️ AlpacaBroker not available - paper trading disabled", flush=True)
                self.paper_broker = None
            else:
                _original_print("[ALPACA] Initializing paper trading broker...", flush=True)
                
                # Load Alpaca keys from DATABASE ONLY (Settings GUI is the source of truth)
                alpaca_api_key = None
                alpaca_secret_key = None
                
                try:
                    from gui_app import database as db
                    alpaca_settings = db.get_alpaca_settings()
                    alpaca_api_key = alpaca_settings.get('alpaca_api_key')
                    alpaca_secret_key = alpaca_settings.get('alpaca_secret_key')
                    _original_print(f"[ALPACA] ✓ Loaded from DATABASE - API Key: {bool(alpaca_api_key)}, Secret: {bool(alpaca_secret_key)}", flush=True)
                except Exception as db_err:
                    _original_print(f"[ALPACA] ⚠️ Database load failed: {db_err}", flush=True)
                    # Only fall back to env vars if database loading fails
                    alpaca_api_key = os.getenv('ALPACA_API_KEY')
                    alpaca_secret_key = os.getenv('ALPACA_SECRET_KEY')
                    _original_print(f"[ALPACA] ⚠️ Fallback to ENV - API Key: {bool(alpaca_api_key)}, Secret: {bool(alpaca_secret_key)}", flush=True)
                
                _original_print(f"[ALPACA] API Key found: {bool(alpaca_api_key)}", flush=True)
                _original_print(f"[ALPACA] Secret Key found: {bool(alpaca_secret_key)}", flush=True)
                
                if not alpaca_api_key or not alpaca_secret_key:
                    _original_print("[ALPACA] ⚠️ Missing API credentials - paper trading disabled", flush=True)
                    self.paper_broker = None
                else:
                    # Create Alpaca broker instance in PAPER mode
                    _original_print("[ALPACA] Creating AlpacaBroker instance...", flush=True)
                    alpaca_config = {
                        'api_key': alpaca_api_key,
                        'api_secret': alpaca_secret_key,
                        'paper_trade': True  # CRITICAL: Enable paper trading mode
                    }
                    self.paper_broker = AlpacaBroker(alpaca_config)
                    _original_print("[ALPACA] AlpacaBroker instance created", flush=True)
                    
                    # Connect to Alpaca paper account
                    _original_print("[ALPACA] Attempting to connect to Alpaca...", flush=True)
                    connected = await self.paper_broker.connect()
                    _original_print(f"[ALPACA] Connection result: {connected}", flush=True)
                    
                    if connected:
                        _original_print("[ALPACA] ✓ Paper trading broker connected (PAPER account)", flush=True)
                    else:
                        _original_print("[ALPACA] ⚠️ Paper broker connection failed", flush=True)
                        self.paper_broker = None
                    
        except Exception as e:
            _original_print(f"[ALPACA] ⚠️ Paper broker initialization failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.paper_broker = None

        # Initialize Tastytrade broker
        self.tastytrade_broker = None
        try:
            if TASTYTRADE_AVAILABLE:
                _original_print("[TASTYTRADE] Starting broker initialization...", flush=True)
                from gui_app.broker_credentials_service import get_tastytrade_credentials
                tt_creds = get_tastytrade_credentials()
                
                has_oauth = tt_creds.get('client_secret') and tt_creds.get('refresh_token')
                has_legacy = tt_creds.get('username') and tt_creds.get('password')
                
                if has_oauth or has_legacy:
                    auth_type = "OAuth2" if has_oauth else "username/password"
                    paper_mode = tt_creds.get('paper_mode', True)
                    mode_str = "PAPER" if paper_mode else "LIVE"
                    _original_print(f"[TASTYTRADE] Creating TastytradeBroker instance ({auth_type}, {mode_str})...", flush=True)
                    
                    self.tastytrade_broker = TastytradeBroker({
                        'username': tt_creds.get('username'),
                        'password': tt_creds.get('password'),
                        'client_secret': tt_creds.get('client_secret'),
                        'refresh_token': tt_creds.get('refresh_token'),
                        'paper_trade': paper_mode
                    })
                    
                    connected = await self.tastytrade_broker.connect()
                    if connected:
                        _original_print(f"[TASTYTRADE] ✓ Connected successfully ({mode_str})", flush=True)
                        _original_print(f"[TASTYTRADE]   Account #: {self.tastytrade_broker.account.account_number}", flush=True)
                        # Update GUI broker status with account info
                        try:
                            from gui_app.broker_credentials_service import set_broker_status
                            
                            account_info = await self.tastytrade_broker.get_account_info()
                            nlv = account_info.get('portfolio_value', 0)
                            
                            # Warn if balance is zero (common OAuth scope issue)
                            if nlv == 0:
                                _original_print(f"[TASTYTRADE] ⚠️  Balance shows $0 - API returned zero values", flush=True)
                                _original_print(f"[TASTYTRADE]     This may indicate:", flush=True)
                                _original_print(f"[TASTYTRADE]     1. Account has no funds", flush=True)
                                _original_print(f"[TASTYTRADE]     2. OAuth scope may need 'Account Balance' permission", flush=True)
                                _original_print(f"[TASTYTRADE]     3. Check account balance at my.tastytrade.com", flush=True)
                            else:
                                _original_print(f"[TASTYTRADE]   Net Liq: ${nlv:,.2f}", flush=True)
                                _original_print(f"[TASTYTRADE]   Buying Power: ${account_info.get('equity_buying_power', 0):,.2f}", flush=True)
                            
                            broker_id = 'tastytrade_paper' if paper_mode else 'tastytrade_live'
                            set_broker_status(broker_id, True, 'connected', account_info=account_info)
                            _original_print(f"[TASTYTRADE] ✓ Broker status updated in GUI", flush=True)
                        except Exception as status_err:
                            _original_print(f"[TASTYTRADE] ⚠️ Failed to update broker status: {status_err}", flush=True)
                            import traceback
                            traceback.print_exc()
                    else:
                        _original_print("[TASTYTRADE] ⚠️ Connection failed", flush=True)
                        self.tastytrade_broker = None
                else:
                    _original_print("[TASTYTRADE] No credentials configured - broker disabled", flush=True)
                    _original_print("[TASTYTRADE]   Need OAuth2 (client_secret + refresh_token) or legacy (username + password)", flush=True)
            else:
                _original_print("[TASTYTRADE] TastytradeBroker not available", flush=True)
        except Exception as e:
            _original_print(f"[TASTYTRADE] ⚠️ Initialization failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.tastytrade_broker = None

        # Initialize Robinhood broker (WARNING: No paper trading - all trades are LIVE)
        self.robinhood_broker = None
        try:
            if ROBINHOOD_AVAILABLE:
                _original_print("[ROBINHOOD] Starting broker initialization...", flush=True)
                _original_print("[ROBINHOOD] ⚠️  WARNING: Robinhood has NO paper trading mode", flush=True)
                _original_print("[ROBINHOOD] ⚠️  ALL trades will be executed with REAL money", flush=True)
                
                from gui_app import database as db
                rh_settings = db.get_robinhood_settings()
                rh_username = rh_settings.get('robinhood_username', '')
                rh_password = rh_settings.get('robinhood_password', '')
                rh_totp_secret = rh_settings.get('robinhood_totp_secret', '')
                
                if rh_username and rh_password:
                    _original_print(f"[ROBINHOOD] ✓ Loaded credentials from DATABASE", flush=True)
                    _original_print(f"[ROBINHOOD] Creating RobinhoodBroker instance...", flush=True)
                    
                    self.robinhood_broker = RobinhoodBroker({
                        'username': rh_username,
                        'password': rh_password,
                        'totp_secret': rh_totp_secret
                    })
                    
                    connected = await self.robinhood_broker.connect()
                    if connected:
                        _original_print(f"[ROBINHOOD] ✓ Connected successfully (LIVE)", flush=True)
                        try:
                            from gui_app.broker_credentials_service import set_broker_status
                            account_info = await self.robinhood_broker.get_account_info()
                            set_broker_status('robinhood', True, 'connected', account_info=account_info)
                            _original_print(f"[ROBINHOOD] ✓ Broker status updated in GUI", flush=True)
                        except Exception as status_err:
                            _original_print(f"[ROBINHOOD] ⚠️ Failed to update broker status: {status_err}", flush=True)
                    else:
                        _original_print("[ROBINHOOD] ⚠️ Connection failed", flush=True)
                        self.robinhood_broker = None
                else:
                    _original_print("[ROBINHOOD] No credentials configured - broker disabled", flush=True)
            else:
                _original_print("[ROBINHOOD] RobinhoodBroker not available", flush=True)
        except Exception as e:
            _original_print(f"[ROBINHOOD] ⚠️ Initialization failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.robinhood_broker = None

        # Initialize IBKR broker (requires TWS or IB Gateway running)
        self.ibkr_broker = None
        try:
            if IBKR_AVAILABLE:
                _original_print("[IBKR] Starting broker initialization...", flush=True)
                _original_print("[IBKR] Note: Requires TWS or IB Gateway running", flush=True)
                
                from gui_app.broker_credentials_service import get_ibkr_credentials, set_broker_status
                ibkr_creds = get_ibkr_credentials()
                ibkr_host = ibkr_creds.get('host', '127.0.0.1')
                ibkr_port_live = ibkr_creds.get('port_live', 7496)
                ibkr_port_paper = ibkr_creds.get('port_paper', 7497)
                ibkr_client_id = ibkr_creds.get('client_id', 1)
                ibkr_paper_mode = ibkr_creds.get('paper_mode', True)
                
                # Select port based on paper/live mode
                ibkr_port = ibkr_port_paper if ibkr_paper_mode else ibkr_port_live
                
                _original_print(f"[IBKR] ✓ Loaded credentials from DATABASE", flush=True)
                _original_print(f"[IBKR]   Host: {ibkr_host}:{ibkr_port} (Client ID: {ibkr_client_id})", flush=True)
                _original_print(f"[IBKR]   Mode: {'PAPER' if ibkr_paper_mode else 'LIVE'}", flush=True)
                _original_print(f"[IBKR] Creating IBKRBroker instance...", flush=True)
                
                self.ibkr_broker = IBKRBroker({
                    'host': ibkr_host,
                    'port': ibkr_port,
                    'client_id': ibkr_client_id,
                    'paper_trade': ibkr_paper_mode
                })
                
                connected = await self.ibkr_broker.connect()
                if connected:
                    mode = "PAPER" if ibkr_paper_mode else "LIVE"
                    _original_print(f"[IBKR] ✓ Connected successfully ({mode})", flush=True)
                    try:
                        account_info = await self.ibkr_broker.get_account_info()
                        broker_id = 'ibkr_paper' if ibkr_paper_mode else 'ibkr_live'
                        set_broker_status(broker_id, True, 'connected', account_info=account_info)
                        _original_print(f"[IBKR] ✓ Broker status updated in GUI", flush=True)
                        nlv = account_info.get('portfolio_value', 0)
                        if nlv > 0:
                            _original_print(f"[IBKR]   Net Liq: ${nlv:,.2f}", flush=True)
                            _original_print(f"[IBKR]   Buying Power: ${account_info.get('buying_power', 0):,.2f}", flush=True)
                    except Exception as status_err:
                        _original_print(f"[IBKR] ⚠️ Failed to update broker status: {status_err}", flush=True)
                else:
                    _original_print("[IBKR] ⚠️ Connection failed - TWS/Gateway may not be running", flush=True)
                    _original_print("[IBKR]   Make sure TWS or IB Gateway is running and API is enabled", flush=True)
                    self.ibkr_broker = None
            else:
                _original_print("[IBKR] IBKRBroker not available (ib_insync not installed)", flush=True)
        except Exception as e:
            _original_print(f"[IBKR] ⚠️ Initialization failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.ibkr_broker = None

        # CRITICAL: Set broker_ready if ANY broker is available (not just Webull)
        # This fixes user builds where only Alpaca/Tastytrade are configured
        if not self.broker_ready.is_set():
            any_broker_available = (
                (self.broker and getattr(self.broker, 'is_logged_in', False)) or
                self.paper_broker or
                self.tastytrade_broker or
                self.robinhood_broker or
                self.ibkr_broker
            )
            if any_broker_available:
                self.broker_ready.set()
            else:
                _original_print("[WARNING] ⚠️ No brokers available - order worker will wait until a broker connects", flush=True)

        # Initialize and start BrokerSyncService for real-time trade synchronization
        # Check if broker sync is enabled in settings
        broker_sync_enabled = True
        try:
            from gui_app.database import Database
            db_instance = Database()
            broker_sync_setting = db_instance.get_setting('broker_sync_enabled', 'true')
            broker_sync_enabled = broker_sync_setting.lower() == 'true'
        except Exception:
            pass
        
        if broker_sync_enabled:
            try:
                _original_print("[SYNC] Initializing trade synchronization service...", flush=True)
                
                # Create simple broker manager for sync service
                class BrokerManager:
                    def __init__(self, webull_broker, alpaca_paper_broker, tastytrade_broker=None, robinhood_broker=None, ibkr_broker=None):
                        self.webull_broker = webull_broker
                        self.alpaca_paper_broker = alpaca_paper_broker
                        self.tastytrade_broker = tastytrade_broker
                        self.robinhood_broker = robinhood_broker
                        self.ibkr_broker = ibkr_broker
                
                broker_manager = BrokerManager(self.broker, self.paper_broker, self.tastytrade_broker, self.robinhood_broker, self.ibkr_broker)
                
                self.sync_service = BrokerSyncService(broker_manager, db_instance, sync_interval=30)
                await self.sync_service.start()
                await asyncio.sleep(0)  # Yield to event loop so sync task can start
                _original_print("[SYNC] ✓ Trade synchronization service started (30s interval)", flush=True)
            except Exception as e:
                _original_print(f"[SYNC] ⚠️ Sync service initialization failed: {e}", flush=True)
                import traceback
                traceback.print_exc()
                self.sync_service = None
        else:
            _original_print("[SYNC] ⏸️ Broker Sync Service DISABLED (Settings → Background Services)", flush=True)
            self.sync_service = None

        worker_task = asyncio.create_task(self.worker())
        await asyncio.sleep(0)  # Yield to event loop so worker can start
        self.processing_ready.set()
        print("[Init] ✓ Worker task started; processing signals.")
        
        # Initialize trade tracker if AI analysis is enabled
        if self.trade_analyzer and TradeTracker:
            try:
                self.trade_tracker = TradeTracker(
                    trade_analyzer=self.trade_analyzer,
                    broker=self.broker
                )
                self.loop.create_task(self.trade_analysis_scheduler())
                print("[AI] ✓ Post-trade analysis scheduler started (30min, 1hr, 1day intervals)")
            except Exception as e:
                print(f"[AI] ⚠️  Failed to initialize trade tracker: {e}")
        
        # Start position monitoring for risk management (monitors BOTH Webull AND Alpaca positions)
        # Uses RiskManager module from src/risk/position_monitor.py (single source of truth)
        # Check if risk monitor is enabled in settings
        risk_monitor_enabled = True
        try:
            risk_monitor_setting = db_instance.get_setting('risk_monitor_enabled', 'true')
            risk_monitor_enabled = risk_monitor_setting.lower() == 'true'
        except Exception:
            pass
        
        if RISK_MODULE_AVAILABLE and risk_monitor_enabled:
            try:
                # Create adapter with database access
                risk_adapter = RiskDBAdapter(db=self.db)
                
                # Create RiskManager with all required parameters
                self.risk_manager = RiskManager(
                    position_fetcher=self.broker.get_positions,
                    order_queue=self.order_queue,
                    settings_provider=get_risk_management_settings,
                    db_adapter=risk_adapter,
                    alpaca_broker=self.paper_broker,
                    loop=self.loop
                )
                
                # Start monitoring as async task
                self.loop.create_task(self.risk_manager.start_monitoring())
                print("[RISK] ✓ RiskManager module initialized")
            except Exception as e:
                print(f"[RISK] ⚠️ Failed to start RiskManager: {e}")
                import traceback
                traceback.print_exc()
        elif not risk_monitor_enabled:
            print("[RISK] ⏸️ Risk Monitor Service DISABLED (Settings → Background Services)")
        else:
            print("[RISK] ⚠️ RiskManager module not available - risk monitoring disabled")
        
        # Start sentiment analysis task if enabled
        if self.sentiment_analyzer:
            self.loop.create_task(self.sentiment_task())
            print(f"[AI] ✓ Sentiment analysis task started (interval: {SENTIMENT_INTERVAL}s)")
        
        # Start automatic token refresh task
        self.loop.create_task(self.token_refresh_scheduler())
        print("[Webull] ✓ Automatic token refresh scheduler started (every 12 hours)")
    
    async def token_refresh_scheduler(self):
        """Automatically refresh Webull tokens every 12 hours"""
        await asyncio.sleep(3600)  # Wait 1 hour before first refresh
        
        while True:
            try:
                print("[Webull] Running automatic token refresh...")
                success = await self.broker.refresh_tokens()
                
                if success:
                    print("[Webull] ✓ Automatic token refresh completed successfully")
                else:
                    print("[Webull] ⚠️  Automatic token refresh failed - will retry in 12 hours")
                
            except Exception as e:
                print(f"[Webull] ⚠️  Token refresh scheduler error: {e}")
                import traceback
                traceback.print_exc()
            
            # Wait 12 hours before next refresh
            await asyncio.sleep(43200)
    
    async def trade_analysis_scheduler(self):
        """Periodically check for trades needing follow-up analysis"""
        await asyncio.sleep(60)  # Wait 1 minute before first check
        while True:
            try:
                if self.trade_tracker:
                    await self.trade_tracker.check_and_analyze()
            except Exception as e:
                print(f"[AI] Trade analysis scheduler error: {e}")
            await asyncio.sleep(300)  # Check every 5 minutes
    
    async def sentiment_task(self):
        """Periodic market sentiment analysis"""
        await asyncio.sleep(SENTIMENT_INTERVAL)  # Wait before first analysis
        while True:
            try:
                if self.sentiment_analyzer:
                    await asyncio.to_thread(
                        self.sentiment_analyzer.analyze_sentiment
                    )
            except Exception as e:
                print(f"[AI] Sentiment analysis error: {e}")
            
            await asyncio.sleep(SENTIMENT_INTERVAL)
    
    async def _safe_send(self, channel, content: str):
        """
        Send message with deduplication to prevent discord.py-self bug that sends duplicates.
        Returns the sent message or None if deduplicated.
        Uses async lock to prevent race conditions.
        
        Tracks send location (file:line) rather than content to catch duplicates
        even when content differs slightly (e.g., real-time market data changes).
        """
        async with self._send_lock:  # Prevent race conditions
            # Track the CALL LOCATION instead of content hash
            # This catches duplicates even if content differs slightly
            import traceback
            stack = traceback.extract_stack()
            # Get caller's location (2 frames back: _safe_send -> caller)
            if len(stack) >= 2:
                caller_frame = stack[-2]
                call_location = f"{caller_frame.filename}:{caller_frame.lineno}"
            else:
                call_location = "unknown"
            
            current_time = time.time()
            
            # Clean up old entries (older than dedupe window)
            expired_locs = [loc for loc, t in self._recent_sends.items() if current_time - t > self._send_dedupe_window]
            for loc in expired_locs:
                del self._recent_sends[loc]
            
            # Check if we recently sent from this EXACT code location
            if call_location in self._recent_sends:
                last_send_time = self._recent_sends[call_location]
                if current_time - last_send_time < 1.0:  # 1 second is enough for same-location sends
                    print(f"[SEND DEDUP] Skipping duplicate send from {call_location} (sent {current_time - last_send_time:.2f}s ago)")
                    return None
            
            # Record this send location and actually send it
            self._recent_sends[call_location] = current_time
            return await channel.send(content)
    
    def normalize_timeframe(self, timeframe: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Normalize and validate timeframe parameter
        Returns: (normalized_timeframe, error_message) - error_message is None if valid
        """
        timeframe = timeframe.lower().strip()
        
        # Supported Webull intervals
        supported = {
            '1min': 'm1', '1m': 'm1',
            '5min': 'm5', '5m': 'm5',
            '15min': 'm15', '15m': 'm15',
            '30min': 'm30', '30m': 'm30',
            '1hr': 'm60', '1h': 'm60', '60min': 'm60',
            '4hr': 'm240', '4h': 'm240',
            '1day': 'd1', '1d': 'd1', 'day': 'd1', 'daily': 'd1'
        }
        
        if timeframe in supported:
            return (supported[timeframe], None)
        
        # Suggest closest match for unsupported timeframes
        if timeframe in ['10min', '10m']:
            return (None, "10min not supported. Try **5min** or **15min** instead.")
        
        return (None, f"Unsupported timeframe: {timeframe}\nSupported: 1min, 5min, 15min, 30min, 1hr, 4hr, 1day")
    
    async def handle_analyze_command(self, message: discord.Message, symbol: str, timeframe: str = '1day'):
        """Handle !analyze [SYMBOL] [TIMEFRAME] command - provides AI stock analysis with market data"""
        # Prevent duplicate execution of the same command
        if message.id in self._executing_commands:
            print(f"[CMD LOCK] Command already executing for MsgID: {message.id}")
            return
        
        self._executing_commands.add(message.id)
        print(f"[CMD LOCK] Locked command execution for MsgID: {message.id}")
        
        try:
            if not self.trade_analyzer:
                await message.channel.send("❌ AI analysis not available (trade analyzer not initialized)")
                return
            
            symbol = symbol.upper().strip()
            
            # Validate and normalize timeframe
            normalized_tf, error = self.normalize_timeframe(timeframe)
            if error:
                await message.channel.send(f"❌ {error}")
                return
            
            print(f"[AI CMD] Analyzing {symbol} ({timeframe}) for {message.author.name} (MsgID: {message.id})")
            
            # Send "thinking" message (with send deduplication)
            thinking_msg = await self._safe_send(message.channel, f"🤖 Analyzing **{symbol}** ({timeframe})...")
            
            # Fetch market data, news, and fundamentals in parallel
            market_data = None
            data_status = "No market data available"
            news = []
            is_biotech = False
            fundamentals = {}
            
            async def fetch_market_data():
                nonlocal market_data, data_status
                try:
                    def fetch_bars():
                        return self.broker._client.get_bars(
                            stock=symbol,
                            interval=normalized_tf,
                            count=50,
                            extendTrading=0
                        )
                    
                    bars_raw = await asyncio.to_thread(fetch_bars)
                    
                    # Handle pandas DataFrame or list response
                    if bars_raw is not None:
                        # Check if it's a DataFrame and convert to list of dicts
                        if hasattr(bars_raw, 'empty'):
                            # It's a pandas DataFrame
                            if not bars_raw.empty:
                                bars_list = bars_raw.to_dict('records')
                                market_data = self._format_market_data(bars_list, timeframe)
                                data_status = f"Based on {len(bars_list)} {timeframe} candles"
                                print(f"[AI CMD] Fetched {len(bars_list)} candles for {symbol} (DataFrame)")
                        elif isinstance(bars_raw, list) and len(bars_raw) > 0:
                            # It's already a list
                            market_data = self._format_market_data(bars_raw, timeframe)
                            data_status = f"Based on {len(bars_raw)} {timeframe} candles"
                            print(f"[AI CMD] Fetched {len(bars_raw)} candles for {symbol} (list)")
                except Exception as e:
                    print(f"[AI CMD] Market data fetch failed: {e}")
            
            async def fetch_news_data():
                nonlocal news, is_biotech
                if self.news_service and INCLUDE_NEWS_IN_ANALYZE:
                    try:
                        news, is_biotech = await self.news_service.get_news(symbol, max_items=NEWS_MAX_ITEMS)
                        print(f"[AI CMD] Fetched {len(news)} news items for {symbol} (biotech: {is_biotech})")
                    except Exception as e:
                        print(f"[AI CMD] News fetch failed: {e}")
            
            async def fetch_fundamentals():
                nonlocal fundamentals
                if self.fundamental_analyzer and INCLUDE_FUNDAMENTALS_IN_ANALYZE:
                    try:
                        def get_fundamentals():
                            return self.fundamental_analyzer.get_fundamentals(symbol)
                        
                        fundamentals = await asyncio.to_thread(get_fundamentals)
                        print(f"[AI CMD] Fetched fundamentals for {symbol}")
                    except Exception as e:
                        print(f"[AI CMD] Fundamentals fetch failed: {e}")
            
            # Fetch all data in parallel
            await asyncio.gather(fetch_market_data(), fetch_news_data(), fetch_fundamentals())
            
            # Build analysis prompt with market data, news, and fundamentals
            news_context = ""
            if news and self.news_service:
                news_context = "\n\n" + self.news_service.format_news_for_ai(news, is_biotech)
            
            fundamental_context = ""
            if fundamentals and self.fundamental_analyzer:
                fundamental_context = "\n\n" + self.fundamental_analyzer.format_fundamentals_for_ai(fundamentals)
            
            if market_data:
                prompt = f"""Provide both technical and fundamental analysis for {symbol}.

**Market Data ({timeframe} candles):**
{market_data}{news_context}{fundamental_context}

**Analysis Requirements:**
1. **Technical Analysis ({timeframe} timeframe)**: Current trend, key levels, momentum
2. **Fundamental Analysis**: Valuation (P/E, growth), financial health, analyst targets
3. **Short-term Trade**: Buy/Sell/Hold for {timeframe} trading with entry/exit levels
4. **Long-term Investment**: Is this a good long-term hold? Growth potential over 6-12 months
5. **Risk Assessment**: Key risks for both short-term traders and long-term investors
{('6. **News Impact**: How might recent news affect short and long-term outlook?' if news else '')}

Provide actionable insights for BOTH day traders ({timeframe}) AND long-term investors. Keep under 500 words."""
            else:
                # Fallback to prompt-only mode (no market data)
                prompt = f"""Provide both technical and fundamental analysis for {symbol}:{news_context}{fundamental_context}

1. **Technical Setup**: Likely direction, typical support/resistance, what to check on {timeframe}
2. **Fundamental Analysis**: Valuation, growth prospects, financial health
3. **Short-term Trade**: Buy/Sell/Hold for {timeframe} with reasoning
4. **Long-term Investment**: Is this a good long-term hold? 6-12 month outlook
5. **Risk Assessment**: Key risks for both traders and investors
{('6. **News Impact**: How might recent news affect short and long-term outlook?' if news else '')}

Provide actionable insights for BOTH day traders AND long-term investors. Keep under 500 words."""
            
            # Get AI analysis
            def get_analysis():
                response = self.trade_analyzer.client.chat.completions.create(
                    model=self.trade_analyzer.model,
                    messages=[
                        {
                            "role": "system",
                            "content": f"You are an expert stock analyst providing both technical ({timeframe} timeframe) and fundamental analysis. Give clear, actionable insights for day traders AND long-term investors. Focus on valuation, growth potential, and risk assessment. Format with bullet points."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.7,
                    max_tokens=700
                )
                return response.choices[0].message.content
            
            analysis = await asyncio.to_thread(get_analysis)
            
            # Delete thinking message
            try:
                await thinking_msg.delete()
            except:
                pass
            
            # Format news for Discord
            news_section = ""
            if news and self.news_service:
                news_section = "\n\n" + self.news_service.format_news_for_discord(news, is_biotech, max_chars=600)
            
            # Format fundamentals for Discord
            fundamental_section = ""
            if fundamentals and self.fundamental_analyzer:
                fundamental_section = "\n\n" + self.fundamental_analyzer.format_fundamentals_for_discord(fundamentals, max_chars=700)
            
            # Helper function to chunk messages safely
            def chunk_message(text: str, max_len: int = 1900) -> list:
                """Split a message into chunks that fit Discord's 2000 char limit"""
                if len(text) <= max_len:
                    return [text]
                chunks = []
                while text:
                    if len(text) <= max_len:
                        chunks.append(text)
                        break
                    # Find a good split point (newline, space, etc.)
                    split_idx = text.rfind('\n', 0, max_len)
                    if split_idx == -1:
                        split_idx = text.rfind(' ', 0, max_len)
                    if split_idx == -1:
                        split_idx = max_len
                    chunks.append(text[:split_idx])
                    text = text[split_idx:].lstrip()
                return chunks
            
            # Combine everything into ONE cohesive message
            full_message = f"📊 **Analysis: {symbol}**\n**Timeframe:** {timeframe.upper()}\n**Data:** {data_status}"
            
            # Add fundamentals section first (more concise)
            if fundamental_section and fundamental_section.strip():
                full_message += fundamental_section
            
            # Add news section
            if news_section and news_section.strip():
                full_message += news_section
            
            # Add AI analysis with separator for clarity
            full_message += f"\n\n**🤖 AI Analysis:**\n{analysis}"
            full_message += f"\n\n_AI Model: {self.trade_analyzer.model}_"
            
            # Only chunk if necessary (message too long)
            chunks = chunk_message(full_message)
            if len(chunks) == 1:
                # Fits in one message - perfect!
                await self._safe_send(message.channel, chunks[0])
            else:
                # Need to split - send with clear labels
                await self._safe_send(message.channel, f"📊 **Analysis: {symbol}** (Part 1/{len(chunks)})\n{chunks[0]}")
                for i, chunk in enumerate(chunks[1:], start=2):
                    if chunk.strip():
                        await self._safe_send(message.channel, f"📊 **Analysis: {symbol}** (Part {i}/{len(chunks)})\n{chunk}")
            
        except Exception as e:
            print(f"[AI CMD] Analysis error: {e}")
            await message.channel.send(f"❌ Error analyzing {symbol}: {str(e)}")
        finally:
            # Release the command lock
            self._executing_commands.discard(message.id)
            print(f"[CMD LOCK] Released lock for MsgID: {message.id}")
    
    def _format_market_data(self, bars: list, timeframe: str) -> str:
        """Format OHLCV bars into compact summary for AI prompt"""
        try:
            if not bars or len(bars) == 0:
                return "No data available"
            
            # Get last 10 candles for detailed view
            recent = bars[-10:]
            
            # Format as compact table
            lines = ["```"]
            lines.append(f"Recent {timeframe} Candles (Last 10):")
            lines.append("Time          | Open    | High    | Low     | Close   | Volume")
            lines.append("-" * 70)
            
            for bar in recent:
                timestamp = datetime.fromtimestamp(int(bar.get('timestamp', 0))/1000).strftime('%m/%d %H:%M')
                o = float(bar.get('open', 0))
                h = float(bar.get('high', 0))
                l = float(bar.get('low', 0))
                c = float(bar.get('close', 0))
                v = int(bar.get('volume', 0))
                
                lines.append(f"{timestamp} | ${o:7.2f} | ${h:7.2f} | ${l:7.2f} | ${c:7.2f} | {v:>8,}")
            
            # Add summary stats
            closes = [float(b.get('close', 0)) for b in bars if 'close' in b]
            if closes:
                current_price = closes[-1]
                price_change = ((closes[-1] - closes[0]) / closes[0] * 100) if len(closes) > 1 else 0
                high_50 = max(float(b.get('high', 0)) for b in bars)
                low_50 = min(float(b.get('low', 0)) for b in bars)
                
                lines.append("")
                lines.append(f"Summary ({len(bars)} candles):")
                lines.append(f"  Current: ${current_price:.2f}")
                lines.append(f"  Change: {price_change:+.2f}%")
                lines.append(f"  Range: ${low_50:.2f} - ${high_50:.2f}")
            
            lines.append("```")
            return "\n".join(lines)
            
        except Exception as e:
            print(f"[AI CMD] Error formatting market data: {e}")
            return "Error formatting market data"
    
    def clean_signal_text(self, text: str) -> str:
        """
        Normalize signal text by removing invisible unicode characters
        and standardizing punctuation for reliable regex parsing.
        
        Handles: zero-width joiners, RTL/LTR marks, unicode dashes/colons,
        fullwidth characters, and other problematic invisible formatting.
        """
        import unicodedata
        
        if not text:
            return text
        
        # First, normalize using NFKC to fold compatibility characters
        # This handles fullwidth chars, some special forms, etc.
        text = unicodedata.normalize('NFKC', text)
        
        # Remove invisible formatting characters (Unicode category Cf)
        # This includes: zero-width joiners, RTL/LTR marks, soft hyphens, etc.
        cleaned_chars = []
        for char in text:
            category = unicodedata.category(char)
            # Keep normal characters, but remove format characters (Cf)
            # Preserve emojis which are in category So (Symbol, other)
            if category != 'Cf':
                cleaned_chars.append(char)
        text = ''.join(cleaned_chars)
        
        # Standardize common unicode punctuation variants to ASCII
        punctuation_map = {
            '\u2010': '-',  # Hyphen
            '\u2011': '-',  # Non-breaking hyphen
            '\u2012': '-',  # Figure dash
            '\u2013': '-',  # En dash
            '\u2014': '-',  # Em dash
            '\u2015': '-',  # Horizontal bar
            '\uFE58': '-',  # Small em dash
            '\uFE63': '-',  # Small hyphen-minus
            '\uFF0D': '-',  # Fullwidth hyphen-minus
            '\uFF1A': ':',  # Fullwidth colon
            '\uFE55': ':',  # Small colon
            '\uFF04': '$',  # Fullwidth dollar sign
            '\uFE69': '$',  # Small dollar sign
            '\u00A0': ' ',  # Non-breaking space
            '\u2000': ' ',  # En quad
            '\u2001': ' ',  # Em quad
            '\u2002': ' ',  # En space
            '\u2003': ' ',  # Em space
            '\u2004': ' ',  # Three-per-em space
            '\u2005': ' ',  # Four-per-em space
            '\u2006': ' ',  # Six-per-em space
            '\u2007': ' ',  # Figure space
            '\u2008': ' ',  # Punctuation space
            '\u2009': ' ',  # Thin space
            '\u200A': ' ',  # Hair space
            '\u202F': ' ',  # Narrow no-break space
            '\u205F': ' ',  # Medium mathematical space
            '\u3000': ' ',  # Ideographic space
        }
        
        for unicode_char, ascii_char in punctuation_map.items():
            text = text.replace(unicode_char, ascii_char)
        
        # Collapse multiple spaces into single space
        import re as re_local
        text = re_local.sub(r' +', ' ', text)
        
        return text

    def parse_structured_alert(self, text: str) -> dict:
        """Parse structured stock trading alerts like:
        ENTERED LONG: $CGTL, ENTRY: $1.15, S.L: $1.06, 1st Target: $1.25-1.28
        FOXX over 3.40-3.45, SL 3.04, target 3.70-3.75
        
        NEW FORMAT - TRADE IDEA with emojis:
        TRADE IDEA
        📌 Ticker: AMZE
        💰 Entry: 0.48
        📈 Levels: 0.50 - 0.515 - 0.53 - 0.55 - 0.585+
        ⛔ SL: 0.435
        """
        import re
        
        # Clean text of invisible unicode characters before parsing
        text = self.clean_signal_text(text)
        
        alert_data = {
            'symbol': None,
            'entry_price': None,
            'stop_loss': None,
            'target_price': None,
            'target_levels': [],
            'raw_text': text
        }
        
        # Check for TRADE IDEA format first (with emojis)
        is_trade_idea = 'TRADE IDEA' in text.upper() or '📌' in text or 'Ticker:' in text
        
        if is_trade_idea:
            # TRADE IDEA format parsing - handles multi-line format where emoji is on separate line:
            # 📌
            # Ticker: AMZE
            # 💰
            # Entry: 0.48
            
            # Extract ticker - handles "📌\nTicker: AMZE" or "📌 Ticker: AMZE" or just "Ticker: AMZE"
            ticker_match = re.search(r'Ticker:\s*\$?([A-Z]{1,5})\b', text, re.IGNORECASE)
            if ticker_match:
                alert_data['symbol'] = ticker_match.group(1).upper()
            
            # Extract entry - handles "💰\nEntry: 0.48" or "Entry: 0.48"
            entry_match = re.search(r'Entry:\s*\$?([\d.]+)', text, re.IGNORECASE)
            if entry_match:
                try:
                    alert_data['entry_price'] = float(entry_match.group(1))
                except:
                    pass
            
            # Extract stop loss - handles "⛔\nSL: 0.435" or "SL: 0.435" or "SL 0.435" (colon optional)
            sl_match = re.search(r'SL[:\s]+\$?([\d.]+)', text, re.IGNORECASE)
            if sl_match:
                try:
                    alert_data['stop_loss'] = float(sl_match.group(1))
                except:
                    pass
            
            # Extract target levels - handles "📈\nLevels: 0.50 - 0.515 - 0.53"
            levels_match = re.search(r'Levels?:\s*([\d.\s\-\+]+)', text, re.IGNORECASE)
            if levels_match:
                levels_str = levels_match.group(1)
                # Parse all price levels (separated by - or spaces)
                level_prices = re.findall(r'([\d.]+)\+?', levels_str)
                try:
                    alert_data['target_levels'] = [float(p) for p in level_prices if p]
                    # Use first level as primary target
                    if alert_data['target_levels']:
                        alert_data['target_price'] = alert_data['target_levels'][0]
                except:
                    pass
            
            print(f"[TRADE IDEA] Parsed: {alert_data['symbol']} Entry=${alert_data['entry_price']}, SL=${alert_data['stop_loss']}, Targets={alert_data['target_levels']}")
        
        else:
            # Original format parsing
            # Extract symbol - look for $SYMBOL or SYMBOL or "ENTERED LONG: $SYMBOL"
            symbol_match = re.search(r'\$([A-Z]{1,5})\b|\b([A-Z]{1,5})\s+(?:over|@|entry|ENTRY)', text, re.IGNORECASE)
            if symbol_match:
                alert_data['symbol'] = symbol_match.group(1) or symbol_match.group(2)
            
            # Extract entry price - look for "ENTRY:" or "ENTERED" or "over"
            entry_match = re.search(r'(?:ENTRY|entry):\s*\$?([\d.]+)|over\s+\$?([\d.]+)[\d.-]*', text, re.IGNORECASE)
            if entry_match:
                price_str = entry_match.group(1) or entry_match.group(2)
                try:
                    alert_data['entry_price'] = float(price_str)
                except:
                    pass
            
            # Extract stop loss - look for "S.L:" or "SL" or "STOP" (colon optional)
            sl_match = re.search(r'(?:S\.L|SL|stop\s*loss)[:\s]+\$?([\d.]+)', text, re.IGNORECASE)
            if sl_match:
                try:
                    alert_data['stop_loss'] = float(sl_match.group(1))
                except:
                    pass
            
            # Extract target - look for "target" or "1st Target"
            target_match = re.search(r'(?:target|1st\s+target):\s*\$?([\d.]+)', text, re.IGNORECASE)
            if target_match:
                try:
                    alert_data['target_price'] = float(target_match.group(1))
                except:
                    pass
        
        # Return None if we couldn't extract key data
        if not all([alert_data['symbol'], alert_data['entry_price']]):
            return None
        
        return alert_data

    async def handle_auto_signal_conversion(self, message: discord.Message, text: str, target_channel_id: str = None):
        """Automatically convert stock alerts to BTO/STC signals - NO AI COST (Pure Regex Detection)"""
        
        print(f"[ALERT PARSER] Analyzing text from {message.author.name}: {text[:100]}")
        
        # Parse structured alerts using PURE REGEX (NO AI COST)
        # Detects: ENTRY: $X, S.L: $Y, TARGET: $Z patterns
        structured = self.parse_structured_alert(text)
        if structured:
            print(f"[ALERT PARSER] ✅ Detected structured alert: {structured['symbol']} Entry=${structured['entry_price']}, SL=${structured['stop_loss']}, Target=${structured['target_price']}")
            
            # Add signal DIRECTLY to execution queue instead of forwarding to Discord
            # This avoids the bot ignoring its own message
            try:
                if DATABASE_MODULE_AVAILABLE:
                    from gui_app import database as db
                    
                    # Use passed target_channel_id (from channel mapping) or fall back to settings
                    if not target_channel_id:
                        conversion_settings = db.get_signal_conversion_settings()
                        target_channel_id = conversion_settings.get('target_execution_channel_id', '')
                    
                    # FALLBACK: If no target channel configured, use the originating channel
                    if not target_channel_id:
                        target_channel_id = str(message.channel.id)
                        print(f"[ALERT PARSER] Using originating channel {target_channel_id} as execution target")
                    
                    if target_channel_id:
                        # Get target channel info
                        target_channel_info = next((ch for ch in db.get_channels() if str(ch['discord_channel_id']) == target_channel_id), None)
                        
                        if target_channel_info:
                            # Generate unique signal ID for tracking
                            import uuid
                            signal_id = str(uuid.uuid4())
                            
                            # Create signal dict for direct queue execution
                            # Include tracking metadata so worker can send notifications and log to database
                            signal = {
                                'action': 'BTO',
                                'qty': 1,
                                'symbol': structured['symbol'],
                                'price': structured['entry_price'],
                                'asset': 'stock',
                                'channel_id': target_channel_id,
                                'channel_name': target_channel_info['name'],
                                'message_id': str(message.id),
                                'author': message.author.name,
                                '_paper_trade_mode': bool(target_channel_info.get('paper_trade_enabled', 0)),
                                # Add tracking metadata for notification and database logging
                                'forward_channel_id': target_channel_id,
                                'channel_record_id': target_channel_info['id'],
                                'signal_id': signal_id,
                                # Add bracket order prices from alert
                                'stop_loss_price': structured.get('stop_loss'),
                                'profit_target_price': structured.get('target_price'),
                                # Flag to calculate qty from position sizing (TRADE IDEA has no explicit qty)
                                '_calculate_qty': True
                            }
                            
                            # Add position sizing from channel settings
                            position_size_pct = target_channel_info.get('position_size_pct')
                            if position_size_pct:
                                signal['_position_size_pct'] = float(position_size_pct)
                                print(f"[ALERT PARSER] ✓ Position sizing: {position_size_pct}% of portfolio")
                            
                            # Add multi-broker configuration from channel settings
                            enabled_brokers_json = target_channel_info.get('enabled_brokers')
                            if enabled_brokers_json:
                                try:
                                    import json
                                    signal['_enabled_brokers'] = json.loads(enabled_brokers_json)
                                    print(f"[ALERT PARSER] Multi-broker enabled: {signal['_enabled_brokers']}")
                                except Exception as e:
                                    print(f"[ALERT PARSER] Failed to parse enabled_brokers: {e}")
                                    pass
                            
                            # Add directly to queue for execution
                            await self.order_queue.put(signal)
                            print(f"[ALERT PARSER] ✅ Added signal to execution queue: BTO 1 {structured['symbol']} @${structured['entry_price']}")
                            print(f"[ALERT PARSER]    → Channel: {target_channel_info['name']} | Paper: {bool(target_channel_info.get('paper_trade_enabled', 0))} | Signal ID: {signal_id}")
                            # Note: Worker will send notification to execution channel after order completes
                        else:
                            print(f"[ALERT PARSER] ⚠️ Channel {target_channel_id} not configured in database - please add it in Channels page")
                else:
                    print(f"[ALERT PARSER] ⚠️ Database not available - cannot add signal to queue")
            except Exception as e:
                print(f"[ALERT PARSER] ❌ Error adding signal to queue: {e}")
                import traceback
                traceback.print_exc()
            return
        
        # If not a structured alert, log for manual review
        print(f"[ALERT PARSER] Text does not match structured alert format - skipping")

    async def handle_convert_command(self, message: discord.Message, text: str):
        """Handle !convert [TEXT] command - manual signal conversion"""
        await self.handle_auto_signal_conversion(message, text)

    async def handle_ask_command(self, message: discord.Message, question: str):
        """Handle !ask [QUESTION] command - free-form trading questions"""
        if not self.trade_analyzer:
            await message.channel.send("❌ AI not available (trade analyzer not initialized)")
        
        print(f"[AI CMD] Question from {message.author.name}: {question[:100]}")
        
        try:
            # Send "thinking" message
            thinking_msg = await message.channel.send("🤔 Thinking...")
            
            # Get AI response
            def get_answer():
                response = self.trade_analyzer.client.chat.completions.create(
                    model=self.trade_analyzer.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an expert trading assistant. Answer questions clearly and concisely. Provide actionable advice when relevant. Keep responses under 400 words."
                        },
                        {
                            "role": "user",
                            "content": question
                        }
                    ],
                    temperature=0.7,
                    max_tokens=600
                )
                return response.choices[0].message.content
            
            answer = await asyncio.to_thread(get_answer)
            
            # Delete thinking message
            try:
                await thinking_msg.delete()
            except:
                pass
            
            # Send answer
            response_msg = f"💡 **AI Response**\n\n{answer}\n\n_AI Model: {self.trade_analyzer.model}_"
            await message.channel.send(response_msg)
            
        except Exception as e:
            print(f"[AI CMD] Question error: {e}")
            await message.channel.send(f"❌ Error: {str(e)}")
    
    async def handle_scanflow_command(self, message: discord.Message, symbols_str: Optional[str] = None):
        """Handle !scanflow [SYMBOLS] command - scan for unusual options activity"""
        if not self.av_scanner:
            await message.channel.send("❌ Option flow scanner not available (Alpha Vantage not initialized)")
            return
        
        # Parse symbols
        if symbols_str:
            symbols = [s.strip().upper() for s in symbols_str.split(',')]
        else:
            symbols = [s.strip().upper() for s in AV_DEFAULT_SYMBOLS.split(',')]
        
        print(f"[ALPHA VANTAGE] Scanning {len(symbols)} symbols for unusual activity: {symbols}")
        
        try:
            # Send "scanning" message
            scanning_msg = await message.channel.send(f"🔍 Scanning {len(symbols)} symbols for unusual option flow...\n_This may take 15-30 seconds..._")
            
            # Scan for unusual activity
            def scan():
                return self.av_scanner.scan_unusual_activity(
                    symbols=symbols,
                    min_premium=AV_MIN_PREMIUM,
                    min_volume=AV_MIN_VOLUME,
                    min_dte=AV_MIN_DTE,
                    max_dte=AV_MAX_DTE,
                    sentiment=AV_SENTIMENT_FILTER if AV_SENTIMENT_FILTER else None,
                    max_results=AV_MAX_RESULTS
                )
            
            unusual_options = await asyncio.to_thread(scan)
            
            # Delete scanning message
            try:
                await scanning_msg.delete()
            except:
                pass
            
            if not unusual_options:
                await message.channel.send(f"📊 No unusual options found matching criteria:\n"
                                         f"- Min premium: ${AV_MIN_PREMIUM:,.0f}\n"
                                         f"- Min volume: {AV_MIN_VOLUME}\n"
                                         f"- DTE range: {AV_MIN_DTE}-{AV_MAX_DTE} days")
                return
            
            # Build response with AI analysis
            response = f"🔥 **Unusual Options Activity** (Top {len(unusual_options)})\n\n"
            
            for i, option in enumerate(unusual_options[:5], 1):  # Show top 5
                response += f"**{i}. {self.av_scanner.format_option_display(option)}**\n\n"
                
                # Add AI analysis if available
                if self.trade_analyzer:
                    try:
                        # Generate quick AI assessment
                        def get_ai_assessment():
                            prompt = f"""Provide a brief 2-3 sentence trading assessment for this unusual options activity:

{option['symbol']} ${option['strike']}{option['type'][0].upper()} {option['expiration']} (DTE: {option['dte']})
- Volume: {option['volume']:,} | OI: {option['open_interest']:,} | Vol/OI: {option['volume_to_oi_ratio']:.2f}x
- Premium: ${option['premium']:,.0f} | IV: {option['implied_volatility']*100:.1f}%
- Unusual Score: {option['unusual_score']:.1f}

Focus on: Why is this unusual? Bullish or bearish signal? Risk/reward assessment."""
                            
                            ai_response = self.trade_analyzer.client.chat.completions.create(
                                model=self.trade_analyzer.model,
                                messages=[
                                    {"role": "system", "content": "You are a concise options trading analyst. Keep responses under 80 words."},
                                    {"role": "user", "content": prompt}
                                ],
                                temperature=0.7,
                                max_tokens=150
                            )
                            return ai_response.choices[0].message.content
                        
                        assessment = await asyncio.to_thread(get_ai_assessment)
                        response += f"**🤖 AI Assessment:** {assessment}\n\n"
                        response += "─" * 50 + "\n\n"
                        
                    except Exception as e:
                        print(f"[ALPHA VANTAGE] AI assessment error: {e}")
            
            # Add footer
            response += f"\n_Scanned: {', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}_\n"
            response += f"_Filters: Premium>${AV_MIN_PREMIUM/1000:.0f}K, Vol>{AV_MIN_VOLUME}, DTE:{AV_MIN_DTE}-{AV_MAX_DTE}_\n"
            response += f"_Model: {self.trade_analyzer.model if self.trade_analyzer else 'No AI'}_"
            
            # Send response (split if too long)
            if len(response) > 2000:
                # Discord message limit is 2000 chars
                chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
                for chunk in chunks:
                    await message.channel.send(chunk)
            else:
                await message.channel.send(response)
            
        except Exception as e:
            print(f"[ALPHA VANTAGE] Scan error: {e}")
            import traceback
            traceback.print_exc()
            await message.channel.send(f"❌ Scan failed: {str(e)}")
    

    async def on_ready(self):
        if self.user:
            print(f"\n[Discord] ✓ Logged in as {self.user} (id={self.user.id})")
        else:
            print(f"\n[Discord] ✓ Logged in (user info not available)")

        print(f"[Discord] ✓ Monitoring {len(CHANNEL_IDS)} channels:")
        for cid in CHANNEL_IDS:
            channel = self.get_channel(cid)
            if channel:
                if hasattr(channel, 'guild') and channel.guild:
                    channel_name = getattr(channel, 'name', str(channel))
                    print(f"[Discord]   - #{channel_name} in {channel.guild.name}")
                elif hasattr(channel, 'name'):
                    print(f"[Discord]   - {getattr(channel, 'name', str(channel))}")
                else:
                    print(f"[Discord]   - Channel: {channel}")
            else:
                print(f"[Discord]   - Channel ID {cid} (not accessible)")
        print("[Discord] Ready to process signals")

        await self.setup()
        
        # Register with GUI after setup completes (for threading architecture)
        try:
            from gui_app import routes
            routes.set_bot_instance(self)
            print("[Discord] ✓ Bot instance registered with web GUI")
        except Exception as e:
            print(f"[Discord] Warning: Could not register bot instance: {e}")
        
        # Run startup validation for critical settings consistency
        try:
            from gui_app.settings_validator import run_system_validation
            from gui_app import database as db
            
            print("\n[STARTUP] Running settings consistency validation...")
            report = run_system_validation(db)
            
            if report.is_valid:
                print(f"[STARTUP] ✓ Settings validation PASSED ({report.channels_checked} channels, {report.brokers_checked} brokers)")
                if report.warning_count > 0:
                    print(f"[STARTUP] ⚠️  {report.warning_count} warnings found - review /api/system/consistency-check")
            else:
                print(f"[STARTUP] ❌ Settings validation FAILED - {report.critical_count} critical issues:")
                for issue in report.issues:
                    if issue.severity == 'critical':
                        channel_info = f" [Channel: {issue.channel_name}]" if issue.channel_name else ""
                        print(f"[STARTUP]   - {issue.field}: {issue.message}{channel_info}")
                print("[STARTUP] ⚠️  TRADING MAY BE AFFECTED - Fix issues via GUI or /api/system/consistency-check")
        except Exception as e:
            print(f"[STARTUP] Warning: Could not run settings validation: {e}")
        
        # Start Trade Monitor if enabled (monitors broker for new trades)
        try:
            from gui_app.trade_monitor import get_trade_monitor
            from gui_app import database as db
            
            monitor_settings = db.get_trade_monitor_settings()
            if monitor_settings.get('enabled'):
                trade_monitor = get_trade_monitor()
                if self.broker:
                    trade_monitor.set_broker(self.broker)
                    asyncio.create_task(trade_monitor.start())
                    print("[STARTUP] ✓ Trade Monitor started - syncing broker trades to Discord")
                else:
                    print("[STARTUP] ⚠️  Trade Monitor enabled but no broker connected")
            else:
                print("[STARTUP] Trade Monitor disabled (enable in Settings)")
        except Exception as e:
            print(f"[STARTUP] Warning: Could not start Trade Monitor: {e}")
        
        # Signal ready event for thread synchronization (if available)
        try:
            global _discord_ready_event
            if _discord_ready_event:
                _discord_ready_event.set()
                print("[Discord] ✓ Bot ready event signaled")
        except Exception:
            pass  # Event not needed in non-threaded mode
    
    async def on_error(self, event_name: str, *args, **kwargs):
        """Log Discord gateway errors that would otherwise be silent"""
        import traceback
        error_info = traceback.format_exc()
        print(f"\n[Discord ERROR] Event '{event_name}' raised an exception:")
        print(error_info)
        print(f"[Discord ERROR] Args: {args}")
        print(f"[Discord ERROR] Kwargs: {kwargs}")
    
    async def on_disconnect(self):
        """Log when Discord websocket connection is lost"""
        print(f"\n[Discord DISCONNECT] ⚠️  Websocket connection lost!")
        print(f"[Discord DISCONNECT] Latency before disconnect: {self.latency * 1000:.2f}ms")
        print(f"[Discord DISCONNECT] Will attempt automatic reconnection...")
    
    async def on_resumed(self):
        """Log when Discord websocket reconnects after disconnect"""
        print(f"\n[Discord RESUMED] ✓ Websocket connection restored!")
        print(f"[Discord RESUMED] Current latency: {self.latency * 1000:.2f}ms")

    async def on_message(self, message: discord.Message):
        # Check database for channel info (dual-mode support)
        channel_info = self._get_channel_info(message.channel.id)
        channel_category = channel_info['category'] if channel_info else None
        execute_enabled = channel_info.get('execute_enabled', 0) if channel_info else False
        track_enabled = channel_info.get('track_enabled', 0) if channel_info else False
        
        # Check if this channel is a source in channel mappings (multi-channel conversion)
        is_mapped_source_channel = False
        if DATABASE_MODULE_AVAILABLE:
            try:
                from gui_app import database as db
                mapped_dest = db.get_destination_for_source(str(message.channel.id))
                if mapped_dest:
                    is_mapped_source_channel = True
                    print(f"[Discord] ✓ Channel is mapped source -> {mapped_dest}")
            except Exception as e:
                pass
        
        # If not in database, not in legacy CHANNEL_IDS list, AND not a mapped source, ignore
        if not channel_info and message.channel.id not in CHANNEL_IDS and not is_mapped_source_channel:
            return
        
        # Deduplicate messages (Discord self-bot sometimes delivers duplicate events)
        if message.id in self._processed_messages:
            print(f"[Discord] Skipping duplicate message ID: {message.id}")
            return
        self._processed_messages.add(message.id)
        print(f"[Discord] Processing message ID: {message.id}")
        
        # Limit cache size to prevent memory growth
        if len(self._processed_messages) > self._max_processed_cache:
            # Remove oldest half of cached message IDs
            to_remove = list(self._processed_messages)[:self._max_processed_cache // 2]
            for msg_id in to_remove:
                self._processed_messages.discard(msg_id)
        
        # Add message to sentiment analyzer if enabled
        if self.sentiment_analyzer and not message.author.bot:
            self.sentiment_analyzer.add_message(message.content)
        
        # Handle webhook messages - skip ALL webhook messages to prevent Trade Monitor loops
        # Discord webhook messages have webhook_id attribute
        # Trade Monitor posts to webhooks, so we must not re-execute those signals
        if hasattr(message, 'webhook_id') and message.webhook_id:
            print(f"[SKIP] Webhook message from {message.author.name} - preventing re-execution loop")
            return
        
        # Skip bot's own response messages SECOND (before any logging)
        # This prevents the bot from processing its own 🤖/📊/❌ messages
        if self.user and message.author.id == self.user.id:
            content_preview = message.content.strip()[:50]
            if content_preview.startswith(('🤖', '📊', '💡', '❌', '⚠️', '📰', 'pong')):
                print(f"[Discord] ⏭️ Skipping own bot response: {content_preview}...")
                return
            elif not ALLOW_SELF_MESSAGES:
                print(f"[Discord] ⏭️ YOUR message ignored! Enable 'Allow Self Messages' in Settings to test")
                print(f"[Discord]    Content: {content_preview}...")
                return

        # Now log only messages from monitored channels
        print(f"\n[Discord] 📨 Channel:{message.channel.id} Author:{message.author.name}")
        print(f"[Discord] Content: {message.content[:150]}")
        
        if ALLOWED_AUTHOR_IDS and message.author.id not in ALLOWED_AUTHOR_IDS:
            print(f"[SKIP] Author {message.author.id} not in allowed list")
            return
        
        if ALLOWED_GUILD_IDS and hasattr(message, 'guild') and message.guild:
            if message.guild.id not in ALLOWED_GUILD_IDS:
                print(f"[SKIP] Guild {message.guild.id} not in allowed list")
                return
        
        # Check channel-specific allowed users (if configured)
        if channel_info and DATABASE_MODULE_AVAILABLE:
            try:
                from gui_app import database as db
                channel_internal_id = channel_info.get('id')
                if channel_internal_id:
                    is_allowed = db.is_user_allowed(channel_internal_id, str(message.author.id))
                    if not is_allowed:
                        print(f"[SKIP] Author {message.author.name} (ID:{message.author.id}) not in channel's allowed user list")
                        return
            except Exception as e:
                print(f"[WARN] Failed to check allowed users: {e}")
                # Continue processing if check fails (fail-open for safety)

        # Store message for format discovery (after all eligibility checks pass)
        if channel_info and DATABASE_MODULE_AVAILABLE:
            try:
                from gui_app import database as db
                db.save_channel_message(
                    channel_id=str(message.channel.id),
                    message_content=message.content,
                    channel_name=channel_name,
                    author_id=str(message.author.id),
                    author_name=message.author.name,
                    message_id=str(message.id)
                )
            except Exception as e:
                pass  # Don't fail message processing if storage fails

        if message.content.strip().lower() == "ping":
            try:
                await message.channel.send("pong")
            except Exception:
                pass
            return
        
        # AUTO SIGNAL CONVERSION - monitor designated channel and auto-convert natural language
        # Check both config.ini and database for conversion channel ID
        active_conversion_channel_id = CONVERSION_CHANNEL_ID
        target_execution_channel_id = None
        
        if DATABASE_MODULE_AVAILABLE:
            from gui_app import database as db
            
            # First check channel mappings (multi-channel support)
            mapped_dest = db.get_destination_for_source(str(message.channel.id))
            if mapped_dest:
                print(f"[CHANNEL MAP] ✓ Source {message.channel.id} mapped to destination {mapped_dest}")
                active_conversion_channel_id = message.channel.id  # Use current channel as source
                target_execution_channel_id = mapped_dest
            else:
                # Fall back to single conversion channel settings
                conversion_settings = db.get_signal_conversion_settings()
                db_conversion_channel_id = conversion_settings.get('conversion_channel_id', '').strip()
                if db_conversion_channel_id:
                    active_conversion_channel_id = int(db_conversion_channel_id)
                target_execution_channel_id = conversion_settings.get('target_execution_channel_id', '').strip()
        
        # Debug: Always log to see what's happening
        is_mapped_source = DATABASE_MODULE_AVAILABLE and db.get_destination_for_source(str(message.channel.id)) is not None
        print(f"[CONVERT DEBUG] ENABLE={ENABLE_SIGNAL_CONVERSION}, active_id={active_conversion_channel_id}, msg_channel={message.channel.id}, mapped={is_mapped_source}")
        
        # Check if this is a mapped source channel OR the single conversion channel
        should_convert = (is_mapped_source or 
                         (ENABLE_SIGNAL_CONVERSION and active_conversion_channel_id and message.channel.id == active_conversion_channel_id))
        
        if should_convert:
            # Don't process commands, only natural language text
            if not message.content.strip().startswith('!'):
                print(f"[AUTO CONVERT] Monitoring signal conversion channel: '{message.content[:50]}'")
                await self.handle_auto_signal_conversion(message, message.content.strip(), target_channel_id=target_execution_channel_id)
                return
        
        # Handle AI commands (only in designated AI channel)
        if ENABLE_AI_COMMANDS and AI_CHANNEL_ID and message.channel.id == AI_CHANNEL_ID:
            content = message.content.strip()
            
            # !analyze [SYMBOL] [TIMEFRAME]
            if content.lower().startswith('!analyze '):
                print(f"[CMD DEBUG] Matched !analyze command")
                args = content[9:].strip().split()  # Extract args after "!analyze "
                if len(args) >= 1:
                    symbol = args[0]
                    timeframe = args[1] if len(args) >= 2 else '1day'  # Default to 1day
                    print(f"[CMD DEBUG] Calling handle_analyze_command for {symbol}")
                    await self.handle_analyze_command(message, symbol, timeframe)
                else:
                    await message.channel.send("❌ Usage: `!analyze [SYMBOL] [TIMEFRAME]`\nExample: `!analyze AAPL 15min`\nSupported timeframes: 1min, 5min, 15min, 30min, 1hr, 4hr, 1day (default: 1day)")
                return
            
            # !ask [QUESTION]
            elif content.lower().startswith('!ask '):
                question = content[5:].strip()  # Extract question after "!ask "
                if question:
                    await self.handle_ask_command(message, question)
                else:
                    await message.channel.send("❌ Usage: `!ask [QUESTION]`\nExample: `!ask What are the best indicators for day trading?`")
                return
            
            # !scanflow [SYMBOLS]
            elif content.lower().startswith('!scanflow'):
                symbols_str = content[9:].strip() if len(content) > 9 else None  # Extract symbols after "!scanflow "
                await self.handle_scanflow_command(message, symbols_str)
                return
            
            # !analyze_trade [SYMBOL]
            elif content.lower().startswith('!analyze_trade '):
                symbol = content[15:].strip()  # Extract symbol after "!analyze_trade "
                if symbol:
                    await self.handle_analyze_trade_command(message, symbol)
                else:
                    await message.channel.send("❌ Usage: `!analyze_trade [SYMBOL]`\nExample: `!analyze_trade NVDA`")
                return
            
            # !convert [NATURAL LANGUAGE]
            elif content.lower().startswith('!convert '):
                text = content[9:].strip()  # Extract text after "!convert "
                if text:
                    await self.handle_convert_command(message, text)
                else:
                    await message.channel.send("❌ Usage: `!convert [TEXT]`\nExample: `!convert Added back 20% META`")
                return
        
        # Pre-process special formats (Bullwinkle scalps, etc.)
        from src.signals.parser import normalize_bullwinkle_format
        normalized_content = normalize_bullwinkle_format(message.content)
        
        # Parse trading signals
        opt = parse_option_signal(normalized_content)
        if opt:
            # Handle price-only STC signals - find most recent open position from this channel
            if opt.get('_price_only') and opt.get('symbol') is None:
                print(f"[STC] Price-only signal detected - looking up most recent open position for channel {message.channel.id}")
                try:
                    from gui_app.database import get_connection
                    conn = get_connection()
                    cursor = conn.cursor()
                    # Find most recent open BTO trade from this channel
                    cursor.execute('''
                        SELECT symbol, strike, call_put, expiry 
                        FROM trades 
                        WHERE channel_id = ? 
                        AND direction = 'BTO' 
                        AND status IN ('OPEN', 'PENDING', 'open', 'pending')
                        ORDER BY created_at DESC 
                        LIMIT 1
                    ''', (str(message.channel.id),))
                    open_position = cursor.fetchone()
                    if open_position:
                        opt['symbol'] = open_position['symbol']
                        opt['strike'] = open_position['strike']
                        opt['opt_type'] = open_position['call_put']
                        opt['expiry'] = open_position['expiry']
                        print(f"[STC] ✓ Found open position: {opt['symbol']} ${opt['strike']}{opt['opt_type']} {opt['expiry']}")
                    else:
                        print(f"[STC] ❌ No open positions found for channel {message.channel.id} - cannot process price-only STC")
                        return
                except Exception as e:
                    print(f"[STC] ❌ Error looking up position: {e}")
                    return
            
            print(f"[SIGNAL PARSED] ✓ Option Signal: {opt['action']} {opt['qty']} {opt['symbol']} {opt['strike']}{opt['opt_type']} {opt['expiry']} @ ${opt['price']}")
            print(f"[CHANNEL CONFIG] execute_enabled={execute_enabled}, track_enabled={track_enabled}, paper_trade_enabled={channel_info.get('paper_trade_enabled', 0) if channel_info else 0}")
            
            # Save signal to database (for both EXECUTE and TRACK channels) with author attribution
            author_name = f"{message.author.name}#{message.author.discriminator}" if message.author.discriminator != '0' else message.author.name
            self._save_signal_to_db(opt, message.channel.id, message.id, author_name)
            print(f"[DATABASE] ✓ Signal saved to database with option details")
            
            # Dual-mode routing: check flags instead of category
            if execute_enabled:
                print(f"[ROUTE] EXECUTE enabled - adding to order queue", flush=True)
                print(f"[DEBUG] Queue size BEFORE put: {self.order_queue.qsize()}", flush=True)
                
                # Add EXECUTION position size percentage for dynamic qty calculation
                exec_position_size_pct = channel_info.get('position_size_pct') if channel_info else None
                print(f"[DEBUG] Channel position_size_pct from DB: {exec_position_size_pct} (type: {type(exec_position_size_pct).__name__})")
                if exec_position_size_pct:
                    opt['_position_size_pct'] = float(exec_position_size_pct)
                    print(f"[POSITION SIZE] ✓ Execution configured for {exec_position_size_pct}% of portfolio")
                else:
                    print(f"[POSITION SIZE] ⚠️ No position_size_pct configured - using signal quantity as-is")
                
                # Add enabled brokers if configured
                enabled_brokers_json = channel_info.get('enabled_brokers') if channel_info else None
                if enabled_brokers_json:
                    try:
                        import json
                        opt['_enabled_brokers'] = json.loads(enabled_brokers_json)
                        print(f"[MULTI-BROKER] Enabled brokers: {opt['_enabled_brokers']}")
                    except:
                        pass
                
                # Add channel_record_id and channel_id for database saving after execution
                if channel_info:
                    opt['channel_record_id'] = channel_info.get('id')
                    opt['channel_id'] = str(message.channel.id)
                    opt['message_id'] = str(message.id)
                    opt['author'] = author_name
                    print(f"[DATABASE] ✓ Added channel_record_id={opt['channel_record_id']} for trade tracking")
                
                await self.order_queue.put(opt)
                print(f"[DEBUG] Queue size AFTER put: {self.order_queue.qsize()}", flush=True)
                print(f"[QUEUE] ✅ Signal successfully queued for LIVE execution", flush=True)
            
            if track_enabled and not execute_enabled:
                # Check if paper trading is enabled for this tracking channel
                paper_trade_enabled = channel_info.get('paper_trade_enabled', 0) if channel_info else 0
                if paper_trade_enabled:
                    print(f"[ROUTE] TRACK channel with PAPER TRADING enabled - executing in PAPER mode")
                    
                    # Add TRACKING position size percentage for paper trading
                    track_position_size_pct = channel_info.get('tracking_position_size_pct') if channel_info else None
                    print(f"[DEBUG] Channel tracking_position_size_pct from DB: {track_position_size_pct} (type: {type(track_position_size_pct).__name__})", flush=True)
                    if track_position_size_pct:
                        opt['_position_size_pct'] = float(track_position_size_pct)
                        print(f"[POSITION SIZE] ✓ Tracking configured for {track_position_size_pct}% of portfolio", flush=True)
                    else:
                        print(f"[POSITION SIZE] ⚠️ No tracking_position_size_pct configured - using signal quantity as-is", flush=True)
                    
                    # Add paper trading flag and channel config to signal
                    opt['_paper_trade_mode'] = True
                    opt['_channel_paper_config'] = {
                        'profit_target_1_pct': channel_info.get('profit_target_1_pct'),
                        'profit_target_2_pct': channel_info.get('profit_target_2_pct'),
                        'profit_target_3_pct': channel_info.get('profit_target_3_pct'),
                        'stop_loss_pct': channel_info.get('stop_loss_pct'),
                        'trailing_stop_pct': channel_info.get('trailing_stop_pct'),
                        'trailing_activation_pct': channel_info.get('trailing_activation_pct')
                    }
                    
                    # Add channel_record_id and channel_id for database saving after execution
                    if channel_info:
                        opt['channel_record_id'] = channel_info.get('id')
                        opt['channel_id'] = str(message.channel.id)
                        opt['message_id'] = str(message.id)
                        opt['author'] = author_name
                        print(f"[DATABASE] ✓ Added channel_record_id={opt['channel_record_id']} for paper trade tracking")
                    
                    await self.order_queue.put(opt)
                    print(f"[QUEUE] ✓ Signal queued for PAPER execution")
                else:
                    print(f"[ROUTE] TRACK-only channel (paper trading disabled) - signal saved for performance analysis")
            elif track_enabled and execute_enabled:
                print(f"[ROUTE] DUAL mode - executing trade AND tracking performance")
            
            # Legacy fallback - channel in config.ini CHANNEL_IDS list
            if not execute_enabled and not track_enabled and message.channel.id in CHANNEL_IDS:
                print(f"[ROUTE] Legacy channel - adding to order queue")
                await self.order_queue.put(opt)
            
            return
        
        stk = parse_stock_signal(normalized_content)
        if stk:
            # Check if this is an STC that should close an option position (Bullwinkle format)
            if stk['action'] == 'STC' and normalized_content != message.content:
                # This was normalized from Bullwinkle format - look for matching option position
                try:
                    from gui_app.database import get_connection
                    conn = get_connection()
                    cursor = conn.cursor()
                    # Find most recent open option position for this symbol from this channel
                    cursor.execute('''
                        SELECT id, symbol, strike, call_put, expiry, quantity
                        FROM trades 
                        WHERE symbol = ? 
                        AND direction = 'BTO' 
                        AND status = 'OPEN'
                        AND strike IS NOT NULL
                        ORDER BY id DESC 
                        LIMIT 1
                    ''', (stk['symbol'],))
                    open_position = cursor.fetchone()
                    if open_position:
                        # Convert stock STC to option STC
                        opt = {
                            'asset': 'option',
                            'action': 'STC',
                            'qty': open_position['quantity'] or 1,
                            'symbol': stk['symbol'],
                            'strike': open_position['strike'],
                            'opt_type': open_position['call_put'],
                            'expiry': open_position['expiry'],
                            'price': stk['price'],
                            'is_market_order': stk.get('is_market_order', False)
                        }
                        print(f"[BULLWINKLE STC] ✓ Converted to option close: STC {opt['qty']} {opt['symbol']} {opt['strike']}{opt['opt_type']} {opt['expiry']} @ ${opt['price']}")
                        
                        # Now process as option signal
                        author_name = f"{message.author.name}#{message.author.discriminator}" if message.author.discriminator != '0' else message.author.name
                        self._save_signal_to_db(opt, message.channel.id, message.id, author_name)
                        print(f"[DATABASE] ✓ Signal saved to database with option details")
                        
                        if execute_enabled:
                            print(f"[ROUTE] EXECUTE enabled - adding to order queue")
                            enabled_brokers_json = channel_info.get('enabled_brokers') if channel_info else None
                            if enabled_brokers_json:
                                try:
                                    import json
                                    opt['_enabled_brokers'] = json.loads(enabled_brokers_json)
                                    print(f"[MULTI-BROKER] Enabled brokers: {opt['_enabled_brokers']}")
                                except:
                                    pass
                            if channel_info:
                                opt['channel_record_id'] = channel_info.get('id')
                                opt['channel_id'] = str(message.channel.id)
                                opt['message_id'] = str(message.id)
                                opt['author'] = author_name
                            await self.order_queue.put(opt)
                            print(f"[QUEUE] ✓ Signal queued for execution")
                        return
                    else:
                        print(f"[BULLWINKLE STC] ⚠️ No open option position found for {stk['symbol']} - processing as stock")
                except Exception as e:
                    print(f"[BULLWINKLE STC] ❌ Error looking up position: {e}")
            
            print(f"[SIGNAL PARSED] ✓ Stock Signal: {stk['action']} {stk['qty']} {stk['symbol']} @ ${stk['price']}")
            print(f"[CHANNEL CONFIG] execute_enabled={execute_enabled}, track_enabled={track_enabled}, paper_trade_enabled={channel_info.get('paper_trade_enabled', 0) if channel_info else 0}")
            
            # Save signal to database (for both EXECUTE and TRACK channels) with author attribution
            author_name = f"{message.author.name}#{message.author.discriminator}" if message.author.discriminator != '0' else message.author.name
            self._save_signal_to_db(stk, message.channel.id, message.id, author_name)
            print(f"[DATABASE] ✓ Signal saved to database")
            
            # Dual-mode routing: check flags instead of category
            if execute_enabled:
                print(f"[ROUTE] EXECUTE enabled - adding to order queue")
                
                # Add EXECUTION position size percentage for dynamic qty calculation
                exec_position_size_pct = channel_info.get('position_size_pct') if channel_info else None
                if exec_position_size_pct:
                    stk['_position_size_pct'] = float(exec_position_size_pct)
                    print(f"[POSITION SIZE] Execution configured for {exec_position_size_pct}% of portfolio")
                
                # Check for multi-broker configuration
                enabled_brokers_json = channel_info.get('enabled_brokers') if channel_info else None
                if enabled_brokers_json:
                    try:
                        import json
                        stk['_enabled_brokers'] = json.loads(enabled_brokers_json)
                        print(f"[MULTI-BROKER] Enabled brokers: {stk['_enabled_brokers']}")
                    except:
                        pass
                
                # Add channel_record_id and channel_id for database saving after execution
                if channel_info:
                    stk['channel_record_id'] = channel_info.get('id')
                    stk['channel_id'] = str(message.channel.id)
                    stk['message_id'] = str(message.id)
                    stk['author'] = author_name
                    print(f"[DATABASE] ✓ Added channel_record_id={stk['channel_record_id']} for trade tracking")
                
                await self.order_queue.put(stk)
                print(f"[QUEUE] ✓ Signal queued for LIVE execution on Webull")
            
            if track_enabled and not execute_enabled:
                # Check if paper trading is enabled for this tracking channel
                paper_trade_enabled = channel_info.get('paper_trade_enabled', 0) if channel_info else 0
                if paper_trade_enabled:
                    print(f"[ROUTE] TRACK channel with PAPER TRADING enabled - executing in PAPER mode")
                    
                    # Add TRACKING position size percentage for paper trading
                    track_position_size_pct = channel_info.get('tracking_position_size_pct') if channel_info else None
                    if track_position_size_pct:
                        stk['_position_size_pct'] = float(track_position_size_pct)
                        print(f"[POSITION SIZE] Tracking configured for {track_position_size_pct}% of portfolio")
                    
                    # Add paper trading flag and channel config to signal
                    stk['_paper_trade_mode'] = True
                    stk['_channel_paper_config'] = {
                        'profit_target_1_pct': channel_info.get('profit_target_1_pct'),
                        'profit_target_2_pct': channel_info.get('profit_target_2_pct'),
                        'profit_target_3_pct': channel_info.get('profit_target_3_pct'),
                        'stop_loss_pct': channel_info.get('stop_loss_pct'),
                        'trailing_stop_pct': channel_info.get('trailing_stop_pct'),
                        'trailing_activation_pct': channel_info.get('trailing_activation_pct')
                    }
                    
                    # Add channel_record_id and channel_id for database saving after execution
                    if channel_info:
                        stk['channel_record_id'] = channel_info.get('id')
                        stk['channel_id'] = str(message.channel.id)
                        stk['message_id'] = str(message.id)
                        stk['author'] = author_name
                        print(f"[DATABASE] ✓ Added channel_record_id={stk['channel_record_id']} for paper trade tracking")
                    
                    await self.order_queue.put(stk)
                    print(f"[QUEUE] ✓ Signal queued for PAPER execution")
                else:
                    print(f"[ROUTE] TRACK-only channel (paper trading disabled) - signal saved for performance analysis")
            elif track_enabled and execute_enabled:
                print(f"[ROUTE] DUAL mode - executing trade AND tracking performance")
            
            # Legacy fallback - channel in config.ini CHANNEL_IDS list
            if not execute_enabled and not track_enabled and message.channel.id in CHANNEL_IDS:
                print(f"[ROUTE] Legacy channel - adding to order queue")
                await self.order_queue.put(stk)
                print(f"[QUEUE] ✓ Signal queued (legacy mode)")
            
            return
        
        # FALLBACK: Try TRADE IDEA format for execute/track channels when BTO/STC and stock patterns fail
        if execute_enabled or track_enabled:
            structured = self.parse_structured_alert(message.content)
            if structured:
                print(f"[TRADE IDEA] ✅ Parsed: {structured['symbol']} Entry=${structured['entry_price']}, SL=${structured['stop_loss']}, Target=${structured['target_price']}")
                await self.handle_auto_signal_conversion(message, message.content.strip())
                return
            else:
                # ALL pattern matching failed - print debug info
                text_preview = message.content.strip()[:80]
                print(f"[Discord] ❌ No pattern matched: '{text_preview}'")
                print(f"[Discord]    Supported: BTO/STC options, BTO/STC stock, TRADE IDEA (Ticker/Entry/SL/Levels)")
    
    async def execute_on_single_broker(self, signal: dict, broker_name: str, broker_instance) -> dict:
        """Execute order on a single broker instance"""
        try:
            # Check if we need to recalculate quantity based on position_size_pct
            position_size_pct = signal.get('_position_size_pct')
            original_qty = signal['qty']
            
            if position_size_pct and signal['action'] == 'BTO':
                # Get broker's portfolio value/buying power
                try:
                    # Handle both WebullBroker wrapper and legacy webull object
                    account_info = None
                    options_buying_power = None
                    
                    _original_print(f"[{broker_name}] [DEBUG] Checking position sizing - has get_account_info: {hasattr(broker_instance, 'get_account_info')}")
                    
                    if hasattr(broker_instance, 'get_account_info'):
                        account_info = await broker_instance.get_account_info()
                        _original_print(f"[{broker_name}] [DEBUG] get_account_info returned: {account_info}")
                        # For Alpaca, also get options-specific buying power
                        if account_info:
                            options_buying_power = account_info.get('options_buying_power') or account_info.get('buying_power')
                    elif hasattr(broker_instance, 'wb') and broker_instance.wb:
                        # Legacy webull object
                        import asyncio
                        raw_account = await asyncio.to_thread(broker_instance.wb.get_account)
                        if raw_account:
                            account_info = {'buying_power': float(raw_account.get('dayBuyingPower', 0) or raw_account.get('cashBalance', 0) or 0)}
                            options_buying_power = float(raw_account.get('optionBuyingPower', 0) or raw_account.get('dayBuyingPower', 0) or 0)
                    elif hasattr(broker_instance, 'get_account'):
                        # Direct webull object
                        import asyncio
                        raw_account = await asyncio.to_thread(broker_instance.get_account)
                        if raw_account:
                            account_info = {'buying_power': float(raw_account.get('dayBuyingPower', 0) or raw_account.get('cashBalance', 0) or 0)}
                            options_buying_power = float(raw_account.get('optionBuyingPower', 0) or raw_account.get('dayBuyingPower', 0) or 0)
                    
                    if account_info:
                        buying_power = account_info.get('buying_power') or account_info.get('net_liquidation') or 0
                        if buying_power > 0:
                            # Calculate position size in dollars based on percentage
                            position_dollars = (buying_power * position_size_pct) / 100
                            
                            if signal['asset'] == 'option':
                                # Options cost 100x the premium
                                price = signal.get('price') or 1.0
                                actual_cost = price * 100
                                if actual_cost > 0:
                                    # Calculate qty based on position size percentage (allow 0 if budget too small)
                                    pct_qty = max(0, int(position_dollars / actual_cost))
                                    
                                    # Calculate max affordable qty based on actual buying power
                                    effective_bp = options_buying_power if options_buying_power else buying_power
                                    affordable_qty = max(0, int(effective_bp / actual_cost))
                                    
                                    # FIXED LOGIC: If position size budget can't afford 1 contract but 
                                    # buying power CAN afford it, execute at least 1 contract
                                    if pct_qty == 0 and affordable_qty >= 1:
                                        # Budget too small for even 1 contract, but we CAN afford it
                                        new_qty = min(original_qty, affordable_qty)
                                        _original_print(f"[{broker_name}] [POSITION SIZE] ⚠️ {position_size_pct}% budget (${position_dollars:.0f}) < 1 contract (${actual_cost:.0f}), using buying power instead")
                                    else:
                                        # Take the minimum of: original signal, percentage limit, and affordable
                                        new_qty = min(original_qty, pct_qty, affordable_qty)
                                    
                                    # If we truly can't afford any contracts, skip this trade
                                    if new_qty == 0:
                                        _original_print(f"[{broker_name}] [POSITION SIZE] ❌ SKIPPING - Cannot afford 1 contract (cost: ${actual_cost:.0f}, budget: ${position_dollars:.0f}, buying power: ${effective_bp:.0f})")
                                        return {'success': False, 'error': f'Insufficient funds for 1 contract (need ${actual_cost:.0f}, have ${effective_bp:.0f})'}
                                    
                                    if new_qty < original_qty:
                                        signal['qty'] = new_qty
                                        # Determine the limiting factor
                                        if affordable_qty < pct_qty and affordable_qty < original_qty:
                                            reason = f"insufficient buying power (${effective_bp:.0f} available, ${original_qty * actual_cost:.0f} needed)"
                                            _original_print(f"[{broker_name}] [POSITION SIZE] ⚠️ Reduced qty: {original_qty} -> {new_qty} contracts - {reason}")
                                        else:
                                            reason = f"{position_size_pct}% position limit (${position_dollars:.0f} budget)"
                                            _original_print(f"[{broker_name}] [POSITION SIZE] Reduced qty: {original_qty} -> {new_qty} contracts - {reason}")
                                    else:
                                        cost_info = f"${original_qty * actual_cost:.0f}"
                                        _original_print(f"[{broker_name}] [POSITION SIZE] ✓ Using full signal qty: {original_qty} contracts (cost: {cost_info}, buying power: ${effective_bp:.0f})")
                            else:
                                # Stocks
                                price = signal.get('price') or 1.0
                                if price > 0:
                                    # Calculate qty based on position size percentage (allow 0 if budget too small)
                                    pct_qty = max(0, int(position_dollars / price))
                                    
                                    # Calculate max affordable qty based on actual buying power
                                    affordable_qty = max(0, int(buying_power / price))
                                    
                                    # Check if signal requests qty calculation (TRADE IDEA format has no explicit qty)
                                    calculate_qty = signal.get('_calculate_qty', False)
                                    
                                    if calculate_qty:
                                        # TRADE IDEA: Calculate qty from position sizing, don't cap at signal default
                                        new_qty = min(pct_qty, affordable_qty)
                                        if new_qty == 0:
                                            _original_print(f"[{broker_name}] [POSITION SIZE] ❌ SKIPPING - Cannot afford 1 share (price: ${price:.2f}, budget: ${position_dollars:.0f}, buying power: ${buying_power:.0f})")
                                            return {'success': False, 'error': f'Insufficient funds for 1 share (need ${price:.2f}, have ${buying_power:.0f})'}
                                        signal['qty'] = new_qty
                                        _original_print(f"[{broker_name}] [POSITION SIZE] ✓ Calculated qty: {new_qty} shares ({position_size_pct}% = ${position_dollars:.0f} budget, ${price:.2f}/share)")
                                    else:
                                        # FIXED LOGIC: If position size budget can't afford 1 share but 
                                        # buying power CAN afford it, execute at least 1 share
                                        if pct_qty == 0 and affordable_qty >= 1:
                                            # Budget too small for even 1 share, but we CAN afford it
                                            new_qty = min(original_qty, affordable_qty)
                                            _original_print(f"[{broker_name}] [POSITION SIZE] ⚠️ {position_size_pct}% budget (${position_dollars:.0f}) < 1 share (${price:.2f}), using buying power instead")
                                        else:
                                            # Take the minimum of: original signal, percentage limit, and affordable
                                            new_qty = min(original_qty, pct_qty, affordable_qty)
                                        
                                        # If we truly can't afford any shares, skip this trade
                                        if new_qty == 0:
                                            _original_print(f"[{broker_name}] [POSITION SIZE] ❌ SKIPPING - Cannot afford 1 share (price: ${price:.2f}, budget: ${position_dollars:.0f}, buying power: ${buying_power:.0f})")
                                            return {'success': False, 'error': f'Insufficient funds for 1 share (need ${price:.2f}, have ${buying_power:.0f})'}
                                        
                                        if new_qty < original_qty:
                                            signal['qty'] = new_qty
                                            # Determine the limiting factor
                                            if affordable_qty < pct_qty and affordable_qty < original_qty:
                                                reason = f"insufficient buying power (${buying_power:.0f} available, ${original_qty * price:.0f} needed)"
                                                _original_print(f"[{broker_name}] [POSITION SIZE] ⚠️ Reduced qty: {original_qty} -> {new_qty} shares - {reason}")
                                            else:
                                                reason = f"{position_size_pct}% position limit (${position_dollars:.0f} budget)"
                                                _original_print(f"[{broker_name}] [POSITION SIZE] Reduced qty: {original_qty} -> {new_qty} shares - {reason}")
                                        else:
                                            cost_info = f"${original_qty * price:.0f}"
                                            _original_print(f"[{broker_name}] [POSITION SIZE] ✓ Using full signal qty: {original_qty} shares (cost: {cost_info}, buying power: ${buying_power:.0f})")
                except Exception as e:
                    _original_print(f"[{broker_name}] [POSITION SIZE] Could not get account info for qty adjustment: {e}")
            
            _original_print(f"[{broker_name}] Executing {signal['action']} {signal['qty']} {signal['symbol']}")
            
            # Check if we should use bracket orders (stocks with stop loss or profit target)
            use_bracket = (
                signal['asset'] == 'stock' and 
                signal['action'] == 'BTO' and
                (signal.get('stop_loss_price') or signal.get('profit_target_price')) and
                hasattr(broker_instance, 'place_bracket_order')
            )
            
            if use_bracket:
                # Use bracket order (entry + stop + target all at once)
                _original_print(f"[{broker_name}] Using BRACKET order (entry + risk management)...")
                if signal.get('stop_loss_price'):
                    _original_print(f"[{broker_name}]   Stop Loss: ${signal['stop_loss_price']}")
                if signal.get('profit_target_price'):
                    _original_print(f"[{broker_name}]   Profit Target: ${signal['profit_target_price']}")
                
                result = await broker_instance.place_bracket_order(
                    symbol=signal['symbol'],
                    action=signal['action'],
                    quantity=signal['qty'],
                    stop_loss_price=signal.get('stop_loss_price'),
                    profit_target_price=signal.get('profit_target_price'),
                    entry_price=signal.get('price')  # None for market order
                )
                
                # Convert Alpaca OrderResult to dict format for consistency
                if hasattr(result, 'success'):
                    resp = {
                        'success': result.success,
                        'msg': result.message,
                        'broker': broker_name,
                        'orderId': result.order_id if result.success else None,
                        'executed_qty': signal['qty']
                    }
                else:
                    # Result is a dict, create a new dict with broker name
                    resp = dict(result) if isinstance(result, dict) else result
                    if isinstance(resp, dict):
                        resp['broker'] = broker_name
                        resp['executed_qty'] = signal['qty']
                    else:
                        resp = {'broker': broker_name, 'result': resp, 'executed_qty': signal['qty']}
            elif signal['asset'] == 'option':
                # Handle different broker parameter names
                # AlpacaBroker uses: symbol, strike, expiry, option_type, action, quantity, price
                # WebullBroker uses: action, qty, symbol, strike, opt_type, expiry_mmdd, limit_price
                if broker_name == 'ALPACA_PAPER' or 'ALPACA' in broker_name.upper():
                    result = await broker_instance.place_option_order(
                        symbol=signal['symbol'],
                        strike=signal['strike'],
                        expiry=signal['expiry'],
                        option_type=signal['opt_type'],
                        action=signal['action'],
                        quantity=signal['qty'],
                        price=signal.get('price')  # None for market orders
                    )
                else:
                    # Webull and other brokers
                    _original_print(f"[{broker_name}] Placing option order: {signal['action']} {signal['qty']} {signal['symbol']} ${signal['strike']}{signal['opt_type']} {signal['expiry']} @ ${signal.get('price')}")
                    result = await broker_instance.place_option_order(
                        action=signal['action'],
                        qty=signal['qty'],
                        symbol=signal['symbol'],
                        strike=signal['strike'],
                        opt_type=signal['opt_type'],
                        expiry_mmdd=signal['expiry'],
                        limit_price=signal.get('price')  # None for market orders
                    )
                    # Log the result for debugging
                    if hasattr(result, 'success'):
                        if result.success:
                            _original_print(f"[{broker_name}] ✅ Option order SUCCESS: {result.message}, Order ID: {result.order_id}")
                        else:
                            _original_print(f"[{broker_name}] ❌ Option order FAILED: {result.message}")
                    elif isinstance(result, dict):
                        if result.get('success') or result.get('orderId'):
                            _original_print(f"[{broker_name}] ✅ Option order SUCCESS: {result.get('msg', result.get('orderId'))}")
                        else:
                            _original_print(f"[{broker_name}] ❌ Option order FAILED: {result.get('msg', result.get('error', 'Unknown error'))}")
                    else:
                        _original_print(f"[{broker_name}] Option order result: {result}")
                # Convert OrderResult to dict format for consistency
                if hasattr(result, 'success'):
                    resp = {
                        'success': result.success,
                        'msg': result.message,
                        'broker': broker_name,
                        'orderId': result.order_id if result.success else None,
                        'executed_qty': signal['qty']
                    }
                elif isinstance(result, dict):
                    resp = dict(result)
                    resp['broker'] = broker_name
                    resp['executed_qty'] = signal['qty']
                else:
                    resp = {'broker': broker_name, 'result': result, 'executed_qty': signal['qty']}
            else:
                # Handle legacy WebullBroker (uses qty, not quantity)
                result = await broker_instance.place_stock_order(
                    action=signal['action'],
                    qty=signal['qty'],
                    symbol=signal['symbol'],
                    limit_price=signal.get('price')  # None for market orders
                )
                # Convert OrderResult to dict format for consistency
                if hasattr(result, 'success'):
                    resp = {
                        'success': result.success,
                        'msg': result.message,
                        'broker': broker_name,
                        'orderId': result.order_id if result.success else None,
                        'executed_qty': signal['qty']
                    }
                elif isinstance(result, dict):
                    resp = dict(result)
                    resp['broker'] = broker_name
                    resp['executed_qty'] = signal['qty']
                else:
                    resp = {'broker': broker_name, 'result': result, 'executed_qty': signal['qty']}
            
            return resp
        
        except Exception as e:
            _original_print(f"[{broker_name}] ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'msg': f'{broker_name} execution failed: {str(e)}',
                'broker': broker_name,
                'error': str(e)
            }
    
    async def handle_analyze_trade_command(self, message: discord.Message, symbol: str):
        """Handle !analyze_trade SYMBOL command - comprehensive swing trading analysis"""
        if not self.swing_analyzer:
            await message.channel.send("❌ Swing trading analysis not available")
            return
        
        symbol = symbol.upper().strip()
        print(f"[SWING CMD] Analyzing {symbol} for swing trade setup")
        
        try:
            thinking_msg = await message.channel.send(f"📊 Analyzing **{symbol}** for swing trade setup...")
            
            # Perform swing analysis
            def analyze():
                return self.swing_analyzer.analyze_symbol(symbol, SWING_ANALYSIS_TIMEFRAME)
            
            analysis = await asyncio.to_thread(analyze)
            
            # Delete thinking message
            try:
                await thinking_msg.delete()
            except:
                pass
            
            # Format and send results
            if "error" in analysis:
                await message.channel.send(f"❌ {analysis['error']}")
            else:
                report = self.swing_analyzer.format_analysis_report(analysis)
                
                # Split if too long
                if len(report) > 1900:
                    chunks = [report[i:i+1900] for i in range(0, len(report), 1900)]
                    for chunk in chunks:
                        await message.channel.send(chunk)
                else:
                    await message.channel.send(report)
        
        except Exception as e:
            print(f"[SWING CMD] Error: {e}")
            import traceback
            traceback.print_exc()
            await message.channel.send(f"❌ Analysis failed: {str(e)}")
    
    async def worker(self):
        """Process orders from queue with pre-trade analysis"""
        _original_print("[WORKER] 💤 Waiting for broker_ready event...", flush=True)
        await self.broker_ready.wait()
        _original_print("[WORKER] 🚀 Order processor started - broker is ready!", flush=True)
        
        while True:
            try:
                _original_print(f"[WORKER] ⏳ Waiting for signal from queue... (size={self.order_queue.qsize()})", flush=True)
                signal = await self.order_queue.get()
                _original_print(f"[WORKER] ✅ Got signal from queue: {signal.get('action')} {signal.get('symbol')}", flush=True)
                
                # Pre-trade analysis for BTO orders
                if signal['action'] == 'BTO' and ENABLE_SWING_ANALYSIS and self.swing_analyzer:
                    symbol = signal['symbol']
                    _original_print(f"\n[PRE-TRADE] Analyzing {symbol} before execution...")
                    
                    try:
                        def analyze():
                            return self.swing_analyzer.analyze_symbol(symbol, SWING_ANALYSIS_TIMEFRAME)
                        
                        analysis = await asyncio.to_thread(analyze)
                        
                        if "error" not in analysis:
                            confidence = analysis['confidence_score']
                            recommendation = analysis['recommendation']
                            
                            _original_print(f"[PRE-TRADE] {symbol} Confidence: {confidence}% - {recommendation}")
                            
                            # Check if trade meets minimum confidence
                            if confidence < SWING_MIN_CONFIDENCE:
                                if SWING_AUTO_REJECT:
                                    _original_print(f"[PRE-TRADE] ❌ REJECTED - Confidence {confidence}% below minimum {SWING_MIN_CONFIDENCE}%")
                                    _original_print(f"[PRE-TRADE] Recommendation: {recommendation}")
                                    continue
                                else:
                                    _original_print(f"[PRE-TRADE] ⚠️  WARNING - Low confidence {confidence}% (min: {SWING_MIN_CONFIDENCE}%), but proceeding (auto_reject=false)")
                            else:
                                _original_print(f"[PRE-TRADE] ✅ APPROVED - High confidence setup")
                        else:
                            _original_print(f"[PRE-TRADE] ⚠️  Analysis failed: {analysis['error']}, proceeding without analysis")
                    
                    except Exception as e:
                        _original_print(f"[PRE-TRADE] ⚠️  Analysis error: {e}, proceeding without analysis")
                
                _original_print(f"[DEBUG] Pre-trade analysis complete, continuing to order execution...", flush=True)
                
                # Initialize order_success to prevent scope errors
                order_success = False
                resp = None
                
                # Check for multi-broker execution
                enabled_brokers = signal.get('_enabled_brokers', None)
                if enabled_brokers and isinstance(enabled_brokers, list) and len(enabled_brokers) > 0:
                    # MULTI-BROKER EXECUTION - Execute on all selected brokers
                    _original_print(f"[MULTI-BROKER] Executing on {len(enabled_brokers)} brokers: {enabled_brokers}")
                    
                    responses = []
                    for broker_name in enabled_brokers:
                        broker_instance = None
                        broker_name_lower = broker_name.lower().strip()
                        
                        # Map broker names to instances - handle various naming conventions
                        # Alpaca Paper: 'alpaca_paper', 'ALPACA_PAPER', 'alpaca', 'ALPACA'
                        if broker_name_lower in ('alpaca_paper', 'alpaca') and self.paper_broker and hasattr(self.paper_broker, 'name') and self.paper_broker.name == 'ALPACA':
                            broker_instance = self.paper_broker
                            _original_print(f"[MULTI-BROKER] Using Alpaca PAPER broker")
                        # Webull Live: 'webull_live', 'WEBULL_LIVE', 'webull', 'WEBULL'
                        elif broker_name_lower in ('webull_live', 'webull') and self.broker and hasattr(self.broker, 'name') and self.broker.name == 'WEBULL':
                            broker_instance = self.broker
                            _original_print(f"[MULTI-BROKER] Using Webull LIVE broker")
                        # Webull Paper: 'webull_paper', 'WEBULL_PAPER'
                        elif broker_name_lower == 'webull_paper' and self.paper_broker and hasattr(self.paper_broker, 'name') and self.paper_broker.name == 'WEBULL':
                            broker_instance = self.paper_broker
                            _original_print(f"[MULTI-BROKER] Using Webull PAPER broker")
                        # IBKR routing - single instance supporting either paper or live mode
                        # Note: IBKR only connects to one TWS/Gateway at a time, mode is determined at startup
                        elif broker_name_lower in ('ibkr_paper', 'ibkr', 'ibkr_live') and self.ibkr_broker and self.ibkr_broker.connected:
                            ibkr_is_paper = getattr(self.ibkr_broker, 'paper_trade', True)
                            # Match the requested mode with the actual mode
                            if broker_name_lower == 'ibkr_paper' and ibkr_is_paper:
                                broker_instance = self.ibkr_broker
                                _original_print(f"[MULTI-BROKER] Using IBKR PAPER broker")
                            elif broker_name_lower == 'ibkr_live' and not ibkr_is_paper:
                                broker_instance = self.ibkr_broker
                                _original_print(f"[MULTI-BROKER] Using IBKR LIVE broker")
                            elif broker_name_lower == 'ibkr':
                                # Generic 'ibkr' route uses whatever mode is configured
                                broker_instance = self.ibkr_broker
                                mode = "PAPER" if ibkr_is_paper else "LIVE"
                                _original_print(f"[MULTI-BROKER] Using IBKR broker ({mode} mode)")
                            else:
                                # Requested mode doesn't match configured mode - append failure response
                                configured_mode = "PAPER" if ibkr_is_paper else "LIVE"
                                _original_print(f"[MULTI-BROKER] ⚠️ IBKR mode mismatch: requested '{broker_name}' but configured as {configured_mode}")
                                responses.append({
                                    'success': False,
                                    'msg': f'IBKR mode mismatch: requested {broker_name} but configured as {configured_mode}',
                                    'broker': broker_name
                                })
                                continue
                        # Tastytrade Paper: 'tastytrade_paper', 'TASTYTRADE_PAPER'
                        elif broker_name_lower == 'tastytrade_paper' and self.tastytrade_broker and self.tastytrade_broker.connected and not self.tastytrade_broker.is_live:
                            broker_instance = self.tastytrade_broker
                            _original_print(f"[MULTI-BROKER] Using Tastytrade PAPER broker")
                        # Tastytrade Live: 'tastytrade_live', 'TASTYTRADE_LIVE', 'tastytrade', 'TASTYTRADE'
                        elif broker_name_lower in ('tastytrade_live', 'tastytrade') and self.tastytrade_broker and self.tastytrade_broker.connected and self.tastytrade_broker.is_live:
                            broker_instance = self.tastytrade_broker
                            _original_print(f"[MULTI-BROKER] Using Tastytrade LIVE broker")
                        else:
                            _original_print(f"[MULTI-BROKER] ⚠️  Broker '{broker_name}' not available or not connected")
                            _original_print(f"[DEBUG] Requested: '{broker_name_lower}', paper_broker: {getattr(self.paper_broker, 'name', None) if self.paper_broker else None}, broker: {getattr(self.broker, 'name', None) if self.broker else None}")
                            responses.append({
                                'success': False,
                                'msg': f'{broker_name} not available',
                                'broker': broker_name
                            })
                            continue
                        
                        # Execute on this broker - create a copy of signal to avoid cross-broker qty contamination
                        # Each broker needs to independently calculate qty based on its own portfolio
                        import copy
                        broker_signal = copy.deepcopy(signal)
                        resp = await self.execute_on_single_broker(broker_signal, broker_name.upper(), broker_instance)
                        responses.append(resp)
                    
                    # Handle multi-broker responses
                    successes = [r for r in responses if r.get('success') or 'orderId' in r]
                    failures = [r for r in responses if not (r.get('success') or 'orderId' in r)]
                    
                    _original_print(f"[MULTI-BROKER] Results: {len(successes)} succeeded, {len(failures)} failed")
                    
                    # For now, treat as success if at least one broker succeeded
                    if successes:
                        _original_print(f"[MULTI-BROKER] ✅ At least one broker executed successfully")
                        # Use first successful response for database/notification
                        resp = successes[0]
                        
                        # Add multi-broker info to response
                        resp['_multi_broker_results'] = responses
                    else:
                        _original_print(f"[MULTI-BROKER] ❌ All brokers failed")
                        resp = {
                            'success': False,
                            'msg': 'All brokers failed',
                            '_multi_broker_results': responses
                        }
                    
                    # Skip to post-execution handling
                    order_success = resp and ('orderId' in resp or resp.get('success') == True)
                    
                else:
                    # SINGLE BROKER EXECUTION (original behavior)
                    
                    # Check if this is a risk management order with specific broker routing
                    risk_broker = signal.get('broker')  # Set by monitor_positions for risk management exits
                    is_risk_order = signal.get('_risk_management_order', False)
                    
                    if is_risk_order and risk_broker:
                        _original_print(f"[RISK] Processing risk management exit order via {risk_broker}")
                        
                        # Route to the correct broker
                        if 'alpaca' in risk_broker.lower():
                            # Use Alpaca paper broker
                            if self.paper_broker and self.paper_broker.connected:
                                try:
                                    if signal['asset'] == 'option':
                                        # Use raw_symbol for Alpaca option orders
                                        raw_symbol = signal.get('raw_symbol') or signal['symbol']
                                        _original_print(f"[RISK] Closing Alpaca option position: {raw_symbol}")
                                        result = await self.paper_broker.place_option_order(
                                            symbol=signal['symbol'],
                                            strike=signal.get('strike'),
                                            expiry=signal.get('expiry'),
                                            option_type=signal.get('opt_type', 'C'),
                                            action='STC',
                                            quantity=signal['qty'],
                                            price=signal.get('price')
                                        )
                                    else:
                                        _original_print(f"[RISK] Closing Alpaca stock position: {signal['symbol']}")
                                        result = await self.paper_broker.place_stock_order(
                                            symbol=signal['symbol'],
                                            action='STC',
                                            quantity=signal['qty'],
                                            price=signal.get('price')
                                        )
                                    
                                    if result and (result.success or result.order_id):
                                        _original_print(f"[RISK] ✅ Alpaca exit order placed: {result}")
                                        resp = {'success': True, 'orderId': result.order_id, 'broker': 'ALPACA_PAPER'}
                                        order_success = True
                                        
                                        # Save risk-triggered STC trade to database for PNL tracking
                                        if DATABASE_MODULE_AVAILABLE and signal.get('channel_id'):
                                            try:
                                                from gui_app import database as db
                                                from gui_app.lot_matcher import get_matcher
                                                from datetime import datetime
                                                
                                                # Save signal to database
                                                db.add_signal(
                                                    discord_channel_id=str(signal['channel_id']),
                                                    message_id=str(signal.get('message_id', f"RISK_{datetime.now().timestamp()}")),
                                                    signal_type='STC',
                                                    symbol=signal['symbol'],
                                                    quantity=signal['qty'],
                                                    price=signal.get('price'),
                                                    asset_type=signal['asset'],
                                                    author_name='Risk Management',
                                                    strike=signal.get('strike'),
                                                    expiry=signal.get('expiry'),
                                                    call_put=signal.get('opt_type')
                                                )
                                                _original_print(f"[RISK] ✓ Signal saved to database for channel {signal['channel_id']}")
                                                
                                                # Add trade record with risk_trigger
                                                trade_data = {
                                                    'channel_id': str(signal['channel_id']),
                                                    'message_id': str(signal.get('message_id', f"RISK_{datetime.now().timestamp()}")),
                                                    'direction': 'STC',
                                                    'asset_type': signal['asset'],
                                                    'symbol': signal['symbol'],
                                                    'strike': signal.get('strike'),
                                                    'expiry': signal.get('expiry'),
                                                    'call_put': signal.get('opt_type'),
                                                    'quantity': signal['qty'],
                                                    'intended_price': signal.get('price'),
                                                    'executed_price': signal.get('price'),
                                                    'executed': True,
                                                    'status': 'CLOSED',
                                                    'broker': 'ALPACA_PAPER',
                                                    'risk_trigger': signal.get('risk_trigger', 'risk_management'),
                                                    'origin_trade_id': signal.get('origin_trade_id')
                                                }
                                                stc_trade_id = db.add_trade(trade_data)
                                                _original_print(f"[RISK] ✓ Trade #{stc_trade_id} saved with risk_trigger={signal.get('risk_trigger')}")
                                                
                                                # Close the original BTO trade
                                                if signal.get('origin_trade_id'):
                                                    db.update_trade(signal['origin_trade_id'], status='CLOSED', closed_at=datetime.now().isoformat())
                                                    _original_print(f"[RISK] ✓ Closed origin trade #{signal['origin_trade_id']}")
                                                
                                                # Process lot matching for PNL calculation
                                                try:
                                                    matcher = get_matcher()
                                                    lot_signal = {
                                                        'action': 'STC',
                                                        'symbol': signal['symbol'],
                                                        'asset': signal['asset'],
                                                        'qty': signal['qty'],
                                                        'price': signal.get('price'),
                                                        'strike': signal.get('strike'),
                                                        'expiry': signal.get('expiry'),
                                                        'opt_type': signal.get('opt_type'),
                                                        'channel_id': signal['channel_id'],
                                                        'received_at': datetime.now()
                                                    }
                                                    lot_result = matcher.process_signal(lot_signal)
                                                    if lot_result:
                                                        _original_print(f"[RISK] ✓ Closed {len(lot_result)} lot(s) for PNL tracking")
                                                except Exception as le:
                                                    _original_print(f"[RISK] ⚠️ Lot matching warning: {le}")
                                                
                                            except Exception as db_error:
                                                _original_print(f"[RISK] ⚠️ Database save warning: {db_error}")
                                        elif DATABASE_MODULE_AVAILABLE:
                                            _original_print(f"[RISK] ⚠️ No channel_id for trade - skipping database save")
                                        
                                    else:
                                        _original_print(f"[RISK] ❌ Alpaca exit order failed: {result}")
                                        resp = {'success': False, 'msg': str(result.message if result else 'Unknown error')}
                                        order_success = False
                                except Exception as e:
                                    _original_print(f"[RISK] ❌ Alpaca exit order error: {e}")
                                    import traceback
                                    traceback.print_exc()
                                    resp = {'success': False, 'msg': str(e)}
                                    order_success = False
                            else:
                                _original_print(f"[RISK] ❌ Alpaca broker not available")
                                resp = {'success': False, 'msg': 'Alpaca broker not connected'}
                                order_success = False
                            
                            continue  # Skip the rest of the single broker execution
                        
                        elif 'webull' in risk_broker.lower():
                            # Use Webull broker - fall through to normal execution
                            _original_print(f"[RISK] Routing to Webull broker")
                            # Continue with normal Webull execution below
                        
                        elif 'tastytrade' in risk_broker.lower():
                            # Use Tastytrade broker for risk exit
                            if self.tastytrade_broker and self.tastytrade_broker.connected:
                                try:
                                    if signal['asset'] == 'option':
                                        _original_print(f"[RISK] Closing Tastytrade option position: {signal['symbol']}")
                                        result = await self.tastytrade_broker.place_option_order(
                                            symbol=signal['symbol'],
                                            strike=signal.get('strike'),
                                            expiry=signal.get('expiry'),
                                            option_type=signal.get('opt_type', 'C'),
                                            action='STC',
                                            quantity=signal['qty'],
                                            price=signal.get('price')
                                        )
                                    else:
                                        _original_print(f"[RISK] Closing Tastytrade stock position: {signal['symbol']}")
                                        result = await self.tastytrade_broker.place_stock_order(
                                            symbol=signal['symbol'],
                                            action='STC',
                                            quantity=signal['qty'],
                                            price=signal.get('price')
                                        )
                                    
                                    broker_label = 'TASTYTRADE_LIVE' if self.tastytrade_broker.is_live else 'TASTYTRADE_PAPER'
                                    if result and (result.success or result.order_id):
                                        _original_print(f"[RISK] ✅ Tastytrade exit order placed: {result}")
                                        resp = {'success': True, 'orderId': result.order_id, 'broker': broker_label}
                                        order_success = True
                                    else:
                                        _original_print(f"[RISK] ❌ Tastytrade exit order failed: {result}")
                                        resp = {'success': False, 'msg': str(result.message if result else 'Unknown error')}
                                        order_success = False
                                except Exception as e:
                                    _original_print(f"[RISK] ❌ Tastytrade exit order error: {e}")
                                    import traceback
                                    traceback.print_exc()
                                    resp = {'success': False, 'msg': str(e)}
                                    order_success = False
                            else:
                                _original_print(f"[RISK] ❌ Tastytrade broker not available")
                                resp = {'success': False, 'msg': 'Tastytrade broker not connected'}
                                order_success = False
                            
                            continue  # Skip the rest of the single broker execution
                    
                    # Check if this is a paper trading signal from tracking channel
                    is_paper_trade = signal.get('_paper_trade_mode', False)
                    paper_config = signal.get('_channel_paper_config', {})
                    _original_print(f"[DEBUG] Paper trade mode: {is_paper_trade}, Signal: {signal.get('action')} {signal.get('symbol')}", flush=True)
                    
                    # Get the appropriate broker (paper or live)
                    if is_paper_trade:
                        # PAPER TRADING - Route to paper trading account
                        _original_print(f"[PAPER TRADE] Executing {signal['action']} order in paper trading account")
                        price_display = f"${signal['price']}" if signal.get('price') is not None else "MARKET"
                        if signal['asset'] == 'option':
                            _original_print(f"[PAPER TRADE] {signal['action']} {signal['qty']} {signal['symbol']} ${signal['strike']}{signal['opt_type']} {signal['expiry']} @{price_display}")
                        else:
                            _original_print(f"[PAPER TRADE] {signal['action']} {signal['qty']} {signal['symbol']} @{price_display}")
                        
                        # Show risk management settings being used
                        profit_target = paper_config.get('profit_target_pct') or PROFIT_TARGET_PCT
                        stop_loss = paper_config.get('stop_loss_pct') or STOP_LOSS_PCT
                        trailing_stop = paper_config.get('trailing_stop_pct') or TRAILING_STOP_PCT
                        if profit_target or stop_loss or trailing_stop:
                            _original_print(f"[PAPER TRADE] Risk settings - Profit Target: {profit_target}%, Stop Loss: {stop_loss}%, Trailing Stop: {trailing_stop}%")
                        
                        # Determine which paper broker to use based on channel settings
                        # Check if Tastytrade paper is configured for this channel
                        enabled_brokers = signal.get('_enabled_brokers', [])
                        use_tastytrade_paper = (
                            any(b.lower() == 'tastytrade_paper' for b in enabled_brokers) and
                            self.tastytrade_broker and 
                            self.tastytrade_broker.connected and 
                            not self.tastytrade_broker.is_live
                        )
                        
                        # Execute paper trade
                        try:
                            if use_tastytrade_paper:
                                # Use Tastytrade paper broker
                                _original_print(f"[PAPER TRADE] ✓ Using Tastytrade paper broker")
                                active_paper_broker = self.tastytrade_broker
                                paper_broker_label = 'TASTYTRADE_PAPER'
                            elif self.paper_broker:
                                # Use Alpaca paper broker (default)
                                _original_print(f"[PAPER TRADE] ✓ Using Alpaca paper broker")
                                active_paper_broker = self.paper_broker
                                paper_broker_label = 'ALPACA_PAPER'
                            else:
                                active_paper_broker = None
                                paper_broker_label = 'SIMULATION'
                            
                            if not active_paper_broker:
                                _original_print("[PAPER TRADE] ❌ Paper trading broker not available - falling back to simulation")
                                # Fallback to simulation only
                                resp = {
                                    'success': True,
                                    'msg': 'Paper broker unavailable - simulated only',
                                    'paper_trade': True,
                                    'broker': 'SIMULATION',
                                    'signal': signal
                                }
                            else:
                                _original_print(f"[PAPER TRADE] ✓ Paper broker instance available - Using: {active_paper_broker.__class__.__name__}")
                                _original_print(f"[PAPER TRADE] Paper broker connected: {active_paper_broker.connected}")
                                
                                # ======== POSITION SIZE CALCULATION FOR PAPER TRADES ========
                                position_size_pct = signal.get('_position_size_pct')
                                if position_size_pct and signal['action'] == 'BTO':
                                    try:
                                        _original_print(f"[PAPER TRADE] Calculating position size ({position_size_pct}% of portfolio)...")
                                        account_info = await active_paper_broker.get_account_info()
                                        if account_info:
                                            buying_power = account_info.get('buying_power') or 0
                                            options_buying_power = account_info.get('options_buying_power') or buying_power
                                            
                                            if buying_power > 0:
                                                position_dollars = (buying_power * position_size_pct) / 100
                                                original_qty = signal['qty']
                                                
                                                if signal['asset'] == 'option':
                                                    price = signal.get('price') or 1.0
                                                    actual_cost = price * 100
                                                    if actual_cost > 0:
                                                        pct_qty = max(0, int(position_dollars / actual_cost))
                                                        affordable_qty = max(0, int(options_buying_power / actual_cost))
                                                        
                                                        # FIXED LOGIC: If position size budget can't afford 1 contract but 
                                                        # buying power CAN afford it, execute at least 1 contract
                                                        if pct_qty == 0 and affordable_qty >= 1:
                                                            new_qty = min(original_qty, affordable_qty)
                                                            _original_print(f"[PAPER TRADE] [POSITION SIZE] ⚠️ {position_size_pct}% budget (${position_dollars:.0f}) < 1 contract (${actual_cost:.0f}), using buying power instead")
                                                        else:
                                                            new_qty = min(original_qty, pct_qty, affordable_qty)
                                                        
                                                        if new_qty == 0:
                                                            _original_print(f"[PAPER TRADE] [POSITION SIZE] ❌ SKIPPING - Cannot afford 1 contract (cost: ${actual_cost:.0f}, budget: ${position_dollars:.0f}, buying power: ${options_buying_power:.0f})")
                                                            resp = {'success': False, 'msg': f'Insufficient funds for 1 contract', 'paper_trade': True}
                                                            raise Exception("Skip order - insufficient funds")
                                                        
                                                        if new_qty < original_qty:
                                                            signal['qty'] = new_qty
                                                            if affordable_qty < pct_qty:
                                                                _original_print(f"[PAPER TRADE] [POSITION SIZE] ⚠️ Reduced qty: {original_qty} -> {new_qty} contracts (buying power: ${options_buying_power:.0f})")
                                                            else:
                                                                _original_print(f"[PAPER TRADE] [POSITION SIZE] Reduced qty: {original_qty} -> {new_qty} contracts ({position_size_pct}% = ${position_dollars:.0f} budget)")
                                                        else:
                                                            _original_print(f"[PAPER TRADE] [POSITION SIZE] ✓ Using signal qty: {original_qty} contracts (cost: ${original_qty * actual_cost:.0f}, buying power: ${options_buying_power:.0f})")
                                                else:
                                                    # Stock
                                                    price = signal.get('price') or 1.0
                                                    if price > 0:
                                                        pct_qty = max(0, int(position_dollars / price))
                                                        affordable_qty = max(0, int(buying_power / price))
                                                        
                                                        # Check if signal requests qty calculation (TRADE IDEA format has no explicit qty)
                                                        calculate_qty = signal.get('_calculate_qty', False)
                                                        
                                                        if calculate_qty:
                                                            # TRADE IDEA: Calculate qty from position sizing, don't cap at signal default
                                                            new_qty = min(pct_qty, affordable_qty)
                                                            if new_qty == 0:
                                                                _original_print(f"[PAPER TRADE] [POSITION SIZE] ❌ SKIPPING - Cannot afford 1 share (price: ${price:.2f}, budget: ${position_dollars:.0f})")
                                                                resp = {'success': False, 'msg': f'Insufficient funds for 1 share', 'paper_trade': True}
                                                                raise Exception("Skip order - insufficient funds")
                                                            signal['qty'] = new_qty
                                                            _original_print(f"[PAPER TRADE] [POSITION SIZE] ✓ Calculated qty: {new_qty} shares ({position_size_pct}% = ${position_dollars:.0f} budget, ${price:.2f}/share)")
                                                        else:
                                                            # FIXED LOGIC: If position size budget can't afford 1 share but 
                                                            # buying power CAN afford it, execute at least 1 share
                                                            if pct_qty == 0 and affordable_qty >= 1:
                                                                new_qty = min(original_qty, affordable_qty)
                                                                _original_print(f"[PAPER TRADE] [POSITION SIZE] ⚠️ {position_size_pct}% budget (${position_dollars:.0f}) < 1 share (${price:.2f}), using buying power instead")
                                                            else:
                                                                new_qty = min(original_qty, pct_qty, affordable_qty)
                                                            
                                                            if new_qty == 0:
                                                                _original_print(f"[PAPER TRADE] [POSITION SIZE] ❌ SKIPPING - Cannot afford 1 share (price: ${price:.2f}, budget: ${position_dollars:.0f})")
                                                                resp = {'success': False, 'msg': f'Insufficient funds for 1 share', 'paper_trade': True}
                                                                raise Exception("Skip order - insufficient funds")
                                                            
                                                            if new_qty < original_qty:
                                                                signal['qty'] = new_qty
                                                                _original_print(f"[PAPER TRADE] [POSITION SIZE] Reduced qty: {original_qty} -> {new_qty} shares ({position_size_pct}% = ${position_dollars:.0f} budget)")
                                                            else:
                                                                _original_print(f"[PAPER TRADE] [POSITION SIZE] ✓ Using signal qty: {original_qty} shares")
                                    except Exception as e:
                                        if "Skip order" in str(e):
                                            raise  # Re-raise to skip order
                                        _original_print(f"[PAPER TRADE] [POSITION SIZE] ⚠️ Could not calculate position size: {e}")
                                
                                # Check if we should use bracket orders (stocks with stop loss or profit target)
                                use_bracket = (
                                    signal['asset'] == 'stock' and 
                                    signal['action'] == 'BTO' and
                                    (signal.get('stop_loss_price') or signal.get('profit_target_price')) and
                                    hasattr(active_paper_broker, 'place_bracket_order')
                                )
                                
                                if use_bracket:
                                    # Use bracket order (entry + stop + target all at once)
                                    _original_print(f"[PAPER TRADE] Using BRACKET order (entry + risk management)...")
                                    if signal.get('stop_loss_price'):
                                        _original_print(f"[PAPER TRADE]   Stop Loss: ${signal['stop_loss_price']}")
                                    if signal.get('profit_target_price'):
                                        _original_print(f"[PAPER TRADE]   Profit Target: ${signal['profit_target_price']}")
                                    
                                    result = await active_paper_broker.place_bracket_order(
                                        symbol=signal['symbol'],
                                        action=signal['action'],
                                        quantity=signal['qty'],
                                        stop_loss_price=signal.get('stop_loss_price'),
                                        profit_target_price=signal.get('profit_target_price'),
                                        entry_price=signal.get('price')  # None for market order
                                    )
                                else:
                                    # Regular order execution
                                    _original_print(f"[PAPER TRADE] Calling {paper_broker_label}.place_{signal['asset']}_order()...")
                                    if signal['asset'] == 'option':
                                        result = await active_paper_broker.place_option_order(
                                            symbol=signal['symbol'],
                                            strike=signal['strike'],
                                            expiry=signal['expiry'],
                                            option_type=signal['opt_type'],
                                            action=signal['action'],
                                            quantity=signal['qty'],
                                            price=signal['price']
                                        )
                                    else:
                                        result = await active_paper_broker.place_stock_order(
                                            symbol=signal['symbol'],
                                            action=signal['action'],
                                            quantity=signal['qty'],
                                            price=signal['price']
                                        )
                                
                                # Convert OrderResult to dict format
                                if hasattr(result, 'success'):
                                    # AlpacaBroker/TastytradeBroker returns OrderResult object
                                    resp = {
                                        'success': result.success,
                                        'msg': result.message,
                                        'paper_trade': True,
                                        'broker': paper_broker_label,
                                        'orderId': result.order_id if result.success else None
                                    }
                                    if result.success:
                                        _original_print(f"[PAPER TRADE] ✅ Order executed in {paper_broker_label} account")
                                        _original_print(f"[PAPER TRADE] Order ID: {result.order_id}")
                                else:
                                    # Fallback for dict response
                                    resp = result
                                    resp['paper_trade'] = True
                                    resp['broker'] = paper_broker_label
                        except Exception as e:
                            _original_print(f"[PAPER TRADE] ❌ Error executing paper trade: {e}")
                            import traceback
                            traceback.print_exc()
                            # Create error response but don't crash worker
                            resp = {
                                'success': False,
                                'msg': f'Paper trade failed: {str(e)}',
                                'paper_trade': True,
                                'error': str(e)
                            }
                    else:
                        # LIVE TRADING
                        _original_print(f"[LIVE TRADE] 🔥 Executing LIVE order: {signal['action']} {signal.get('qty')} {signal['symbol']}", flush=True)
                        
                        # Check if we should use bracket orders (stocks with stop loss or profit target)
                        use_bracket = (
                            signal['asset'] == 'stock' and 
                            signal['action'] == 'BTO' and
                            (signal.get('stop_loss_price') or signal.get('profit_target_price')) and
                            hasattr(self.broker, 'place_bracket_order')
                        )
                        
                        # Retry configuration for transient errors
                        max_retries = 3
                        retry_delay = 2  # seconds
                        
                        if use_bracket:
                            # Use bracket order (entry + stop + target all at once)
                            _original_print(f"[LIVE TRADE] Using BRACKET order (entry + risk management)...")
                            if signal.get('stop_loss_price'):
                                _original_print(f"[LIVE TRADE]   Stop Loss: ${signal['stop_loss_price']}")
                            if signal.get('profit_target_price'):
                                _original_print(f"[LIVE TRADE]   Profit Target: ${signal['profit_target_price']}")
                            
                            result = await self.broker.place_bracket_order(
                                symbol=signal['symbol'],
                                action=signal['action'],
                                quantity=signal['qty'],
                                stop_loss_price=signal.get('stop_loss_price'),
                                profit_target_price=signal.get('profit_target_price'),
                                entry_price=signal.get('price')  # None for market order
                            )
                            
                            # Convert Alpaca OrderResult to dict format for consistency
                            if hasattr(result, 'success'):
                                resp = {
                                    'success': result.success,
                                    'msg': result.message,
                                    'orderId': result.order_id if result.success else None
                                }
                            else:
                                resp = result
                        elif signal['asset'] == 'option':
                            price_str = f"${signal['price']}" if signal.get('price') is not None else "MARKET"
                            _original_print(f"[LIVE TRADE] Option order: ${signal['strike']}{signal['opt_type']} {signal['expiry']} @{price_str}", flush=True)
                            _original_print(f"[LIVE TRADE] Calling broker.place_option_order()...", flush=True)
                            
                            # Retry loop for transient errors
                            for attempt in range(max_retries):
                                resp = await self.broker.place_option_order(
                                    action=signal['action'],
                                    qty=signal['qty'],
                                    symbol=signal['symbol'],
                                    strike=signal['strike'],
                                    opt_type=signal['opt_type'],
                                    expiry_mmdd=signal['expiry'],
                                    limit_price=signal.get('price')  # None for market orders
                                )
                                _original_print(f"[LIVE TRADE] Broker response received: {resp}", flush=True)
                                
                                # Check if it's a transient error that should be retried
                                if resp and not resp.get('success') and resp.get('msg'):
                                    error_msg = str(resp.get('msg', '')).lower()
                                    is_transient = 'system is busy' in error_msg or 'try again' in error_msg or 'timeout' in error_msg
                                    
                                    if is_transient and attempt < max_retries - 1:
                                        _original_print(f"[LIVE TRADE] ⏳ Transient error, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})...", flush=True)
                                        await asyncio.sleep(retry_delay)
                                        retry_delay *= 2  # Exponential backoff
                                        continue
                                
                                # Success or non-transient error, break out
                                break
                        else:
                            _original_print(f"[LIVE TRADE] Calling broker.place_stock_order()...", flush=True)
                            resp = await self.broker.place_stock_order(
                                symbol=signal['symbol'],
                                action=signal['action'],
                                quantity=signal['qty'],
                                price=signal.get('price')  # None for market orders
                            )
                            _original_print(f"[LIVE TRADE] Broker response received: {resp}", flush=True)
                        
                        # Determine success for single-broker execution
                        # Handle both dict responses and OrderResult dataclass objects
                        if resp is None:
                            order_success = False
                        elif hasattr(resp, 'success'):
                            # OrderResult dataclass - check .success attribute
                            order_success = resp.success == True
                        elif isinstance(resp, dict):
                            # Dict response - check orderId or success key
                            order_success = 'orderId' in resp or resp.get('success') == True
                        else:
                            order_success = False
                        _original_print(f"[DEBUG] After broker call, order_success: {order_success}, resp type: {type(resp).__name__}", flush=True)
                
                # Handle failed orders
                if not order_success:
                    # Extract error message from either dict or OrderResult
                    if hasattr(resp, 'message'):
                        error_msg = resp.message or 'Unknown error'
                        error_type = 'ORDER_FAILED'
                    elif isinstance(resp, dict):
                        error_msg = resp.get('msg') or resp.get('message') or 'Unknown error'
                        error_type = resp.get('error', 'ORDER_FAILED')
                    else:
                        error_msg = 'Unknown error'
                        error_type = 'ORDER_FAILED'
                    _original_print(f"[ORDER FAILED] ❌ {signal['action']} {signal['symbol']} - {error_msg}", flush=True)
                    
                    # Update signal execution status in database
                    if DATABASE_MODULE_AVAILABLE and signal.get('message_id'):
                        try:
                            from gui_app import database as db
                            db.update_signal_execution_status(
                                str(signal['message_id']), 
                                'FAILED', 
                                error_msg[:200]  # Limit reason length
                            )
                        except Exception as e:
                            _original_print(f"[DATABASE] ⚠️ Could not update signal status: {e}")
                    
                    # Log to database for AI assistant awareness
                    log_error_to_db('order_execution', f"Order failed: {error_msg}", 
                                   'OrderProcessor', 'error', 
                                   f"{signal['action']} {signal.get('qty', 1)} {signal['symbol']}")
                    
                    # Send Discord notification for failed order
                    webhook_url = globals().get('DISCORD_WEBHOOK_URL')
                    if webhook_url:
                        try:
                            webhook_data = {
                                "content": f"❌ **ORDER REJECTED**\n"
                                          f"**Action:** {signal['action']} {signal.get('qty')} {signal['symbol']}\n"
                                          f"**Reason:** {error_msg}\n"
                                          f"**Error Type:** {error_type}"
                            }
                            requests.post(webhook_url, json=webhook_data)
                        except:
                            pass
                
                # Post-execution: Send Discord notification and save to database
                if order_success:
                    # Update signal execution status to EXECUTED
                    if DATABASE_MODULE_AVAILABLE and signal.get('message_id'):
                        try:
                            from gui_app import database as db
                            # Build success reason with broker info - handle both dict and OrderResult
                            success_brokers = []
                            if isinstance(resp, dict):
                                multi_results = resp.get('_multi_broker_results', [])
                                if multi_results:
                                    success_brokers = [r.get('broker', 'Unknown') for r in multi_results if r.get('success') or 'orderId' in r]
                                else:
                                    success_brokers = [resp.get('broker', 'Webull')]
                            else:
                                # OrderResult object - single broker execution
                                multi_results = []
                                success_brokers = [getattr(resp, 'broker', None) or 'Broker']
                            
                            success_reason = f"Executed on {', '.join(success_brokers)}"
                            db.update_signal_execution_status(
                                str(signal['message_id']), 
                                'EXECUTED', 
                                success_reason
                            )
                        except Exception as e:
                            _original_print(f"[DATABASE] ⚠️ Could not update signal status: {e}")
                    
                    # 1. Send notification to Discord channel (check settings first)
                    try:
                        from gui_app import database as db
                        notif_settings = db.get_signal_conversion_settings()
                        notifications_enabled = notif_settings.get('notifications_enabled', True)
                        custom_notif_channel = notif_settings.get('notification_channel_id', '')
                    except:
                        notifications_enabled = True
                        custom_notif_channel = ''
                    
                    if notifications_enabled:
                        # Use custom notification channel if set, otherwise use forward_channel_id
                        notif_channel_id = custom_notif_channel if custom_notif_channel else signal.get('forward_channel_id')
                        
                        if notif_channel_id:
                            try:
                                exec_channel = self.get_channel(int(notif_channel_id))
                                if exec_channel:
                                    # Get executed quantity and order ID - handle both dict and OrderResult
                                    if isinstance(resp, dict):
                                        multi_results = resp.get('_multi_broker_results', [])
                                        if multi_results:
                                            # Find first successful broker result
                                            first_success = next((r for r in multi_results if r.get('success') or 'orderId' in r), None)
                                            if first_success:
                                                display_qty = first_success.get('executed_qty', signal['qty'])
                                                order_id = first_success.get('orderId', 'N/A')
                                                broker_name = first_success.get('broker', 'Unknown')
                                            else:
                                                display_qty = signal['qty']
                                                order_id = 'N/A'
                                                broker_name = 'Unknown'
                                        else:
                                            display_qty = resp.get('executed_qty', signal['qty'])
                                            order_id = resp.get('orderId', 'N/A')
                                            broker_name = resp.get('broker', 'Webull')
                                    else:
                                        # OrderResult object
                                        display_qty = getattr(resp, 'quantity', None) or signal['qty']
                                        order_id = getattr(resp, 'order_id', 'N/A') or 'N/A'
                                        broker_name = getattr(resp, 'broker', None) or 'Broker'
                                    
                                    # Build execution message with actual executed quantity
                                    exec_price = f"${signal['price']}" if signal.get('price') is not None else "MARKET"
                                    if signal['asset'] == 'option':
                                        exec_msg = f"✅ **{signal['action']} {display_qty} {signal['symbol']} ${signal['strike']}{signal['opt_type']} {signal['expiry']} @{exec_price}**"
                                    else:
                                        exec_msg = f"✅ **{signal['action']} {display_qty} {signal['symbol']} @{exec_price}**"
                                    
                                    # Add broker info
                                    exec_msg += f"\n📊 **{broker_name}**"
                                    
                                    # Add order ID
                                    exec_msg += f"\n🔖 Order ID: `{order_id}`"
                                    
                                    await exec_channel.send(exec_msg)
                                    _original_print(f"[NOTIFICATION] ✓ Sent to channel {notif_channel_id}")
                            except Exception as e:
                                _original_print(f"[NOTIFICATION] ⚠️ Failed to send to channel: {e}")
                    
                    # 2. Save execution to database (if channel_record_id is set)
                    channel_record_id = signal.get('channel_record_id')
                    if channel_record_id and DATABASE_MODULE_AVAILABLE:
                        try:
                            from gui_app import database as db
                            # Save signal to database
                            db.add_signal(
                                discord_channel_id=str(signal['channel_id']),
                                message_id=str(signal.get('message_id', '')),
                                signal_type=signal['action'],
                                symbol=signal['symbol'],
                                quantity=signal['qty'],
                                price=signal.get('price'),
                                asset_type=signal['asset'],
                                author_name=signal.get('author', 'Auto-Converted'),
                                strike=signal.get('strike'),
                                expiry=signal.get('expiry'),
                                call_put=signal.get('opt_type')
                            )
                            
                            # Save trade with stop/target prices for position monitoring
                            if signal['action'] == 'BTO':
                                # Check if this was multi-broker execution
                                multi_broker_results = resp.get('_multi_broker_results')
                                if multi_broker_results:
                                    # Save ONE trade entry PER successful broker
                                    _original_print(f"[DATABASE] Multi-broker execution - saving {len([r for r in multi_broker_results if r.get('success') or 'orderId' in r])} trade entries")
                                    for broker_resp in multi_broker_results:
                                        if broker_resp.get('success') or 'orderId' in broker_resp:
                                            # Use executed_qty from broker response (position-sized), fallback to signal qty
                                            executed_qty = broker_resp.get('executed_qty', signal['qty'])
                                            trade_data = {
                                                'channel_id': str(signal['channel_id']),
                                                'message_id': str(signal.get('message_id', '')),
                                                'direction': signal['action'],
                                                'asset_type': signal['asset'],
                                                'symbol': signal['symbol'],
                                                'strike': signal.get('strike'),
                                                'expiry': signal.get('expiry'),
                                                'call_put': signal.get('opt_type'),
                                                'quantity': executed_qty,
                                                'intended_price': signal.get('price'),
                                                'executed_price': signal.get('price'),
                                                'executed': True,
                                                'broker': (broker_resp.get('broker') or 'WEBULL').upper(),
                                                'order_id': broker_resp.get('orderId'),
                                                'stop_loss_price': signal.get('stop_loss_price'),
                                                'profit_target_price': signal.get('profit_target_price')
                                            }
                                            db.add_trade(trade_data)
                                            _original_print(f"[DATABASE] ✓ Trade saved for {trade_data['broker']} qty={executed_qty} with SL=${trade_data.get('stop_loss_price')} Target=${trade_data.get('profit_target_price')}")
                                else:
                                    # Single broker execution - use executed_qty from response
                                    executed_qty = resp.get('executed_qty', signal['qty'])
                                    trade_data = {
                                        'channel_id': str(signal['channel_id']),
                                        'message_id': str(signal.get('message_id', '')),
                                        'direction': signal['action'],
                                        'asset_type': signal['asset'],
                                        'symbol': signal['symbol'],
                                        'strike': signal.get('strike'),
                                        'expiry': signal.get('expiry'),
                                        'call_put': signal.get('opt_type'),
                                        'quantity': executed_qty,
                                        'intended_price': signal.get('price'),
                                        'executed_price': signal.get('price'),
                                        'executed': True,
                                        'broker': (resp.get('broker') or 'WEBULL').upper(),
                                        'order_id': resp.get('orderId'),
                                        'stop_loss_price': signal.get('stop_loss_price'),
                                        'profit_target_price': signal.get('profit_target_price')
                                    }
                                    db.add_trade(trade_data)
                                    _original_print(f"[DATABASE] ✓ Trade saved qty={executed_qty} broker={trade_data['broker']} with SL=${trade_data.get('stop_loss_price')} Target=${trade_data.get('profit_target_price')}")
                            
                            elif signal['action'] == 'STC':
                                # Handle STC trades - especially for risk management exits
                                from datetime import datetime
                                trade_data = {
                                    'channel_id': str(signal['channel_id']),
                                    'message_id': str(signal.get('message_id', '')),
                                    'direction': 'STC',
                                    'asset_type': signal['asset'],
                                    'symbol': signal['symbol'],
                                    'strike': signal.get('strike'),
                                    'expiry': signal.get('expiry'),
                                    'call_put': signal.get('opt_type'),
                                    'quantity': signal['qty'],
                                    'intended_price': signal.get('price'),
                                    'executed_price': signal.get('price'),
                                    'executed': True,
                                    'status': 'CLOSED',
                                    'broker': (resp.get('broker') or 'WEBULL').upper(),
                                    'order_id': resp.get('orderId'),
                                    'risk_trigger': signal.get('risk_trigger'),
                                    'origin_trade_id': signal.get('origin_trade_id')
                                }
                                stc_trade_id = db.add_trade(trade_data)
                                _original_print(f"[DATABASE] ✓ STC Trade #{stc_trade_id} saved broker={trade_data['broker']}")
                                
                                # If this is a risk management exit, close the original BTO trade
                                if signal.get('origin_trade_id'):
                                    db.update_trade(signal['origin_trade_id'], status='CLOSED', closed_at=datetime.now().isoformat())
                                    _original_print(f"[DATABASE] ✓ Closed origin trade #{signal['origin_trade_id']}")
                                
                                # Process lot matching for PNL calculation
                                if signal.get('_risk_management_order'):
                                    try:
                                        from gui_app.lot_matcher import get_matcher
                                        matcher = get_matcher()
                                        lot_signal = {
                                            'action': 'STC',
                                            'symbol': signal['symbol'],
                                            'asset': signal['asset'],
                                            'qty': signal['qty'],
                                            'price': signal.get('price'),
                                            'strike': signal.get('strike'),
                                            'expiry': signal.get('expiry'),
                                            'opt_type': signal.get('opt_type'),
                                            'channel_id': signal['channel_id'],
                                            'received_at': datetime.now()
                                        }
                                        lot_result = matcher.process_signal(lot_signal)
                                        if lot_result:
                                            _original_print(f"[DATABASE] ✓ Closed {len(lot_result)} lot(s) for PNL tracking")
                                    except Exception as le:
                                        _original_print(f"[DATABASE] ⚠️ Lot matching warning: {le}")
                            
                            _original_print(f"[DATABASE] ✓ Logged execution to database")
                        except Exception as e:
                            _original_print(f"[DATABASE] ⚠️ Failed to save: {e}")
                    
                    # 3. Bracket orders already handled during order execution
                    # (No separate bracket order placement needed - it's part of the entry order)
                
                # Post-trade AI analysis if enabled
                if order_success and self.trade_tracker and signal['action'] in ['BTO', 'BTC']:
                    try:
                        await self.trade_tracker.add_trade(signal)
                    except Exception as e:
                        _original_print(f"[TRADE TRACKER] Error tracking trade: {e}")
            
            except Exception as e:
                _original_print(f"[WORKER] Error processing order: {e}")
                log_error_to_db('order_execution', f"Worker error: {str(e)}", 
                               'OrderProcessor', 'error', f"Signal: {signal.get('symbol', 'unknown')}")
                import traceback
                traceback.print_exc()

# ------------------------------ MAIN ---------------------------------------
# Global events for lifecycle management
_discord_ready_event = None
_discord_shutdown_event = None
_discord_error_queue = None

def run_discord_bot_thread():
    """
    Runs Discord bot in its own dedicated thread with isolated asyncio event loop.
    Uses client.start() with asyncio.run() for proper loop isolation.
    """
    global _discord_ready_event, _discord_shutdown_event, _discord_error_queue
    
    async def discord_main():
        """Async entrypoint for Discord bot with proper lifecycle"""
        try:
            _original_print("[Discord Thread] Starting Discord bot...")
            
            # Create Discord client instance (on_ready will handle GUI registration)
            client = SelfClient()
            
            # Start Discord connection (non-blocking async)
            _original_print("[Discord Thread] Connecting to Discord...")
            await client.start(USER_TOKEN)
            
        except Exception as e:
            _original_print(f"[Discord Thread ERROR] Bot crashed: {e}")
            log_error_to_db('discord_connection', f"Discord bot crashed: {str(e)}", 
                           'DiscordClient', 'critical', 'Check Discord token and network connection')
            import traceback
            traceback.print_exc()
            # Propagate error to main thread
            _discord_error_queue.put(e)
            raise
    
    try:
        # Run Discord bot with dedicated event loop via asyncio.run()
        asyncio.run(discord_main())
    except KeyboardInterrupt:
        _original_print("\n[Discord Thread] Bot stopped by user (Ctrl+C)")
    except Exception as e:
        _original_print(f"[Discord Thread] Exception escaped asyncio.run(): {e}")
        _discord_error_queue.put(e)
    finally:
        _original_print("[Discord Thread] Shutting down...")
        _discord_shutdown_event.set()

if __name__ == '__main__':
    import threading
    import queue
    import multiprocessing
    import argparse
    
    # Required for multiprocessing to work in PyInstaller frozen EXE
    multiprocessing.freeze_support()
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='BotifyTrades - Discord Trading Bot',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                    # Start with default port 5000
  %(prog)s --port 8080        # Start on port 8080 (useful for macOS where 5000 is used by AirPlay)
  %(prog)s --wizard           # Launch the setup wizard
  
Environment Variables:
  GUI_PORT                    # Alternative way to set the web GUI port (default: 5000)
        """
    )
    parser.add_argument('--port', '-p', type=int, default=None, 
                        help='Port for web control panel (default: 5000, or GUI_PORT env var)')
    parser.add_argument('--wizard', action='store_true', 
                        help='Launch the setup wizard')
    
    args = parser.parse_args()
    
    # Set GUI_PORT environment variable if --port was provided
    if args.port:
        os.environ['GUI_PORT'] = str(args.port)
        _original_print(f"[CONFIG] Using port {args.port} for web GUI")
    
    # Check if launched with --wizard flag (for subprocess wizard launch)
    if args.wizard or '--wizard' in sys.argv:
        try:
            _original_print("[WIZARD] Launching Setup Wizard...")
            from ui.wizard.launcher import launch_wizard
            result = launch_wizard(skip_first_run_check=True)
            _original_print(f"[WIZARD] Wizard finished with result: {result}")
            sys.exit(0)
        except Exception as e:
            _original_print(f"[WIZARD] Error launching wizard: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    # Initialize global lifecycle events
    _discord_ready_event = threading.Event()
    _discord_shutdown_event = threading.Event()
    _discord_error_queue = queue.Queue()
    
    # Run startup diagnostics
    try:
        from src.diagnostics import run_all_checks
        _original_print("\n[STARTUP] Running system diagnostics...")
        diag_summary = run_all_checks(print_summary=True)
        if diag_summary.failed > 0:
            _original_print(f"[STARTUP] ⚠️  {diag_summary.failed} check(s) failed - review above for details")
        else:
            _original_print(f"[STARTUP] ✓ All {diag_summary.passed} checks passed")
    except Exception as e:
        _original_print(f"[STARTUP] ⚠️  Diagnostics skipped: {e}")
    
    # Run settings audit via SettingsService
    try:
        if SETTINGS_SERVICE_AVAILABLE:
            log_settings_at_startup()
            _original_print("[STARTUP] ✓ Settings audit complete")
    except ImportError:
        _original_print("[STARTUP] Diagnostics module not available, skipping health checks")
    except Exception as e:
        _original_print(f"[STARTUP] Warning: Could not run diagnostics: {e}")
    
    # Start Flask GUI server in main thread
    try:
        import sys
        from pathlib import Path
        # Add parent directory to path so gui_app can be imported
        parent_dir = Path(__file__).parent.parent
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))
        
        from gui_app import start_gui_server, get_gui_port
        gui_port = get_gui_port()
        gui_thread, gui_port = start_gui_server()  # Port configurable via GUI_PORT env var (default: 5000)
        _original_print(f"[GUI] ✓ Web control panel started on port {gui_port}")
    except Exception as e:
        _original_print(f"[GUI] ⚠️  Failed to start web GUI: {e}")
        _original_print("[GUI] Bot will continue without web interface")
    
    # Start Discord bot in dedicated NON-daemon thread (explicit lifecycle)
    discord_thread = threading.Thread(target=run_discord_bot_thread, name="DiscordBot", daemon=False)
    discord_thread.start()
    _original_print("[MAIN] ✓ Discord bot started in dedicated thread")
    
    # Wait for Discord to be ready (with timeout)
    _original_print("[MAIN] Waiting for Discord bot to connect...")
    if _discord_ready_event.wait(timeout=30):
        _original_print("[MAIN] ✓ Discord bot is ready and connected")
    else:
        _original_print("[MAIN] ⚠️  Discord bot did not connect within 30 seconds")
    
    # Main thread monitoring loop - check for Discord errors and keep GUI alive
    discord_failed = False
    try:
        while True:
            # Check for errors from Discord thread
            try:
                error = _discord_error_queue.get(timeout=1)
                error_msg = str(error)
                
                # Check if this is a configuration error (token missing/invalid)
                if 'token' in error_msg.lower() or 'NoneType' in error_msg:
                    if not discord_failed:
                        discord_failed = True
                        _original_print(f"[MAIN] Discord connection failed: {error}")
                        _original_print("[MAIN] ═══════════════════════════════════════════════════════════")
                        _original_print("[MAIN] Discord token not configured or invalid.")
                        _original_print("[MAIN] Please configure your Discord token in the web GUI:")
                        _original_print(f"[MAIN]   → Open http://localhost:{gui_port}/settings")
                        _original_print("[MAIN]   → Enter your Discord token")
                        _original_print("[MAIN]   → Save and restart the application")
                        _original_print("[MAIN] ═══════════════════════════════════════════════════════════")
                        _original_print("[MAIN] GUI is still running. Press Ctrl+C to exit.")
                    # Keep running - GUI is still available for configuration
                else:
                    _original_print(f"[MAIN] FATAL: Discord thread reported error: {error}")
                    _original_print("[MAIN] Shutting down due to Discord thread failure...")
                    break
            except queue.Empty:
                pass  # No errors, continue monitoring
            
            # Check if shutdown requested by user (Ctrl+C or explicit shutdown)
            if _discord_shutdown_event.is_set() and not discord_failed:
                _original_print("[MAIN] Discord thread shutdown detected")
                break
            
            # If Discord failed but GUI is running, keep the main loop alive
            if discord_failed:
                # Keep main thread alive for GUI
                import time
                time.sleep(1)
                continue
                
    except KeyboardInterrupt:
        _original_print("\n[MAIN] Shutdown signal received (Ctrl+C)")
    
    # Clean shutdown - wait for Discord thread to finish
    _original_print("[MAIN] Waiting for Discord thread to terminate...")
    discord_thread.join(timeout=5)
    if discord_thread.is_alive():
        _original_print("[MAIN] ⚠️  Discord thread did not terminate cleanly")
    else:
        _original_print("[MAIN] ✓ Discord thread terminated cleanly")
    
    _original_print("[MAIN] Shutdown complete. Exiting...")
    import sys
    sys.exit(0)
