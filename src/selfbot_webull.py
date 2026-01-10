# -*- coding: utf-8 -*-
# selfbot_webull.py
# ------------------------------------------------------------
# Discord self-bot that reads trade signals and places orders
# on Webull (stocks + options). Use at your own risk.
# ------------------------------------------------------------

# BUILD VERSION MARKER - This MUST print if the code is current
import sys
import os
import builtins
_early_print = builtins.print  # Save original print before any override

# Handle PyInstaller GUI mode where stdout/stderr may be None
# Use UTF-8 encoding to support Unicode characters (checkmarks, etc.)
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8', errors='replace')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8', errors='replace')

# Import version dynamically to show actual release version
try:
    from upgrade.version import APP_VERSION
    _build_version = f"v{APP_VERSION}"
except ImportError:
    _build_version = "DEV"

_early_print("=" * 60)
_early_print(f"BUILD VERSION: {_build_version}")
_early_print("=" * 60)
if sys.stdout and hasattr(sys.stdout, 'flush'):
    sys.stdout.flush()

import re
import json
import asyncio
import configparser
import time
import hashlib
import ssl

# BUILD TYPE: Controls feature visibility
# ADMIN = Full features (Channel Mappings, Debug tools, etc.) - for developer use
# USER = Limited features - for end-user distribution
# This line is automatically updated by scripts/release.sh
BUILD_TYPE = 'USER'  # Set by release.sh

def is_admin_build():
    """Check if this is an admin build with full features"""
    return BUILD_TYPE == 'ADMIN'

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
    from src.brokers.alpaca_broker import AlpacaBroker
    ALPACA_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import AlpacaBroker: {e}")
    ALPACA_AVAILABLE = False

# Import Tastytrade broker
try:
    from src.brokers.tastytrade_broker import TastytradeBroker
    TASTYTRADE_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import TastytradeBroker: {e}")
    TASTYTRADE_AVAILABLE = False

# Import Robinhood broker (WARNING: No paper trading - all trades are LIVE)
try:
    from src.brokers.robinhood_broker import RobinhoodBroker
    ROBINHOOD_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import RobinhoodBroker: {e}")
    ROBINHOOD_AVAILABLE = False

# Import IBKR broker (requires TWS or IB Gateway running)
try:
    from src.brokers.ibkr_broker import IBKRBroker
    IBKR_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import IBKRBroker: {e}")
    IBKR_AVAILABLE = False

# Import DhanQ broker (India - DhanHQ v2 API)
try:
    from src.brokers.dhanq_broker import DhanQBroker
    DHANQ_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import DhanQBroker: {e}")
    DHANQ_AVAILABLE = False

# Import Upstox broker (India - OAuth2 API)
try:
    from src.brokers.upstox_broker import UpstoxBroker
    UPSTOX_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import UpstoxBroker: {e}")
    UPSTOX_AVAILABLE = False

# Import Zerodha broker (India - Kite Connect API)
try:
    from src.brokers.zerodha_broker import ZerodhaBroker
    ZERODHA_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Could not import ZerodhaBroker: {e}")
    ZERODHA_AVAILABLE = False

# Import BrokerSyncService for real-time trade synchronization
from src.services.broker_sync_service import BrokerSyncService

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
                                         '[ROBINHOOD]', '[IBKR]', '[OPTIONS API]', '[TELEGRAM]',
                                         '[DHANQ]', '[ZERODHA]', '[UPSTOX]']):
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
# IMPORTANT: In GUI/frozen mode, skip console prompts - let splash screen handle license
IS_GUI_MODE = getattr(sys, 'frozen', False)  # PyInstaller frozen EXE = GUI mode
DEFER_TO_SPLASH_SCREEN = IS_GUI_MODE  # GUI mode defers license handling to splash screen

if not LICENSE_VALID and not DEFER_TO_SPLASH_SCREEN:
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
                    print(f"[LICENSE] Contacting license server...")
                    
                    result = client.request_trial()
                    
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
elif not LICENSE_VALID and DEFER_TO_SPLASH_SCREEN:
    # GUI mode - defer license check to splash screen instead of console prompts
    print("[LICENSE] ⚠️  License validation deferred to GUI splash screen")
    print("[LICENSE]    The splash screen will handle license activation")

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

# Bear-style patterns (@Stxbearish Discord format)
# Entry format: **Contract:** $SPX 12/19 6845C\n**Entry:** @2.45
# or: Contract: **SPX 11/18 5900c** (no entry price = track only)
# Groups: (symbol, month, day, strike, opt_type)
BEAR_CONTRACT_PATTERN = r'\*{0,2}Contract:?\*{0,2}\s*\*{0,2}\$?([A-Za-z]+)\s+(\d{1,2})/(\d{1,2})\s+(\d+(?:\.\d+)?)\s*([CPcp])\*{0,2}'

# Bear entry price pattern - captures price after Entry:
# Groups: (price)
BEAR_ENTRY_PATTERN = r'\*{0,2}Entry:?\*{0,2}\s*[@]?\s*(\d+\.?\d*)'

# Bear trim pattern: **I'm trimming here for XX%** or **I'm trimming here**
# Groups: (percentage if present)
BEAR_TRIM_PATTERN = r"[Ii]'?m\s+trimming\s+here(?:\s+for\s+(\d+)%)?"

# Bear lotto pattern: SPX 11/18. 5900c @0.55 or SPX 11/18 5900c @0.55
# Groups: (symbol, month, day, strike, opt_type, price)
BEAR_LOTTO_PATTERN = r'([A-Za-z]+)\s+(\d{1,2})/(\d{1,2})\.?\s+(\d+(?:\.\d+)?)\s*([CPcp])\s*@\s*(\d+\.?\d*)'

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

def calculate_dte_expiry(dte_days: int) -> str:
    """Calculate expiry date from DTE (Days To Expiration) notation.
    
    Args:
        dte_days: Number of days until expiration (0 = today, 1 = tomorrow, etc.)
    
    Returns:
        Expiry date in MM/DD format
    """
    from datetime import datetime, timedelta
    expiry_date = datetime.now() + timedelta(days=dte_days)
    return expiry_date.strftime("%m/%d")

# DTE pattern: BTO $QQQ 621c 0DTE @0.74 or STC $SPY 600p 1DTE @1.25
# Supports 0DTE, 1DTE, 2DTE, etc.
# Groups: (action, symbol, strike, opt_type, dte_days, price)
DTE_OPT_PATTERN = r'(BTO|STC)\s+[$]?([A-Za-z]+)\s+[$]?([0-9.]+)\s*([CPcp])\s+(\d+)\s*DTE\s*[@]?\s*[.]?([0-9.]+)'

# Bishop-style patterns (multi-line entry format)
# Entry format: "I'm Entering" followed by "**Option:** SPX 6900 P 12/30" and "**Entry:** 1.00"
# Note: Discord embeds use markdown bold (**) around labels
# Option line groups: (symbol, strike, opt_type, month, day)
BISHOP_OPTION_PATTERN = r'\*{0,2}Option:\*{0,2}\s*([A-Za-z]+)\s+(\d+(?:\.\d+)?)\s*([CPcp])\s+(\d{1,2})/(\d{1,2})'
# Entry price groups: (price)
BISHOP_ENTRY_PATTERN = r'\*{0,2}Entry:\*{0,2}\s*(\d+\.?\d*)'
# Trim/STC format: "Trimming SPX 6900 P 12/30 @$1.30"
# Groups: (symbol, strike, opt_type, month, day, price)
BISHOP_TRIM_PATTERN = r'[Tt]rimming\s+(?:\?\w\s+)?([A-Za-z]+)\s+(\d+(?:\.\d+)?)\s*([CPcp])\s+(\d{1,2})/(\d{1,2})\s*@\s*\$?(\d+\.?\d*)'

# Bishop stopped out pattern: "Got stopped out at $1.65" or "stopped out at $1.65 for -35%"
# Groups: (price)
BISHOP_STOPPED_PATTERN = r'[Ss]topped\s+out\s+(?:at\s+)?\$?(\d+\.?\d*)'

# EvaPanda-style patterns (embed-based with Open/Close titles)
# Embed Title: "Open" = BTO entry, "Close" = STC exit, "Update:" = skip
# Format: BTO FSLR 01/16/26 300C @ 3.25 (Swing) or STC FSLR 01/16/26 300C @ 4.10
# Note: Expiry format is MM/DD/YY (full year)
# Groups: (action, symbol, month, day, year, strike, opt_type, price)
EVAPANDA_PATTERN = r'(BTO|STC)\s+([A-Za-z]+)\s+(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d+(?:\.\d+)?)\s*([CPcp])\s*@\s*(\d+\.?\d*)'

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
MAX_POSITION_SIZE_ENABLED = _trading_settings.get('max_position_size_enabled', True)
GLOBAL_DEFAULT_QUANTITY = _trading_settings.get('global_default_quantity')

if MAX_POSITION_SIZE <= 0:
    raise SystemExit("ERROR: max_position_size must be positive")

if MAX_POSITION_SIZE_ENABLED:
    print(f"[CONFIG] ✓ Max position size (auto-qty): ${MAX_POSITION_SIZE}")
else:
    print(f"[CONFIG] ✓ Max position size calculation: DISABLED")
    if GLOBAL_DEFAULT_QUANTITY:
        print(f"[CONFIG] ✓ Global default quantity: {GLOBAL_DEFAULT_QUANTITY} contracts/shares")
    else:
        print(f"[CONFIG] ⚠️  Global default quantity not set - will fallback to 1")
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
            # Apply monkey-patch to fix the startTime date bug in webull library
            self._patch_order_history_urls(self._client)
        else:
            self._logged_in = False
            print("[Webull] ⚠️  Broker not connected - trading functions disabled")
    
    def _patch_order_history_urls(self, wb):
        """Monkey-patch the webull library to fix the startTime date bug.
        
        The webull library has a hardcoded bug in endpoints.py where startTime=1970-0-1
        which is a malformed date string. The Webull API actually expects timestamps 
        in MILLISECONDS (Unix epoch * 1000), not date strings.
        
        This patch overrides the URL builder at runtime to use proper timestamp format.
        """
        try:
            if not hasattr(wb, '_urls'):
                print("[Webull] ⚠️  Cannot patch URLs - _urls not found", flush=True)
                return
            
            urls_obj = wb._urls
            
            # Get the base URL from the urls object
            base_ustradebroker = getattr(urls_obj, 'base_ustradebroker_url', 'https://ustrade.webullbroker.com/api')
            base_paper = getattr(urls_obj, 'base_paper_url', 'https://act.webullbroker.com/webull-paper-center/api')
            
            # Webull API expects timestamps - try different date formats
            # The API uses Spring framework which may accept ISO-8601 or specific formats
            from datetime import datetime, timedelta
            
            # Calculate dates: start from 30 days ago to avoid very old data
            end_date = datetime.now()
            start_date = end_date - timedelta(days=90)  # Last 90 days of orders
            
            # Format: YYYY-MM-DD (standard ISO format that Spring accepts)
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            
            def patched_orders(account_id, page_size=20):
                """Patched orders URL - remove startTime entirely if causing issues"""
                # Try without startTime parameter - let API use default
                return f'{base_ustradebroker}/trade/v2/option/list?secAccountId={account_id}&dateType=ORDER&pageSize={page_size}&status='
            
            def patched_paper_orders(paper_account_id, page_size=20):
                """Patched paper orders URL - remove startTime entirely"""
                return f'{base_paper}/paper/1/acc/{paper_account_id}/order?&dateType=ORDER&pageSize={page_size}&status='
            
            # Apply the patches
            urls_obj.orders = patched_orders
            urls_obj.paper_orders = patched_paper_orders
            
            print("[Webull] ✓ Patched order history URLs (using timestamp format)", flush=True)
            
        except Exception as e:
            print(f"[Webull] ⚠️  URL patch failed: {e}", flush=True)
            import traceback
            traceback.print_exc()

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
    
    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Public method to get stock quote for conditional order monitoring.
        Returns dict with 'close' key for compatibility with conditional order service.
        """
        try:
            wb = self._client
            if not wb:
                return None
            
            quote = wb.get_quote(stock=symbol)
            if not quote:
                return None
            
            ask = float(quote.get('askPrice', 0) or 0)
            bid = float(quote.get('bidPrice', 0) or 0)
            last = float(quote.get('last', 0) or quote.get('close', 0) or 0)
            
            if ask > 0 and bid > 0:
                mark_price = (ask + bid) / 2
            elif last > 0:
                mark_price = last
            else:
                mark_price = 0
            
            return {
                'close': mark_price,
                'bid': bid,
                'ask': ask,
                'last': last,
                'symbol': symbol
            }
        except Exception as e:
            print(f"[WEBULL] Error in get_quote for {symbol}: {e}")
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

    async def place_stock_order(self, action: str = None, qty: int = None, symbol: str = None, limit_price: float = None, **kwargs) -> Dict[str, Any]:
        # Support both naming conventions: qty/quantity and limit_price/price
        if qty is None:
            qty = kwargs.get('quantity', 1)
        if limit_price is None:
            limit_price = kwargs.get('price')
        if symbol is None:
            symbol = kwargs.get('symbol')
        if action is None:
            action = kwargs.get('action', 'BTO')
        
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

    async def get_order_history(self, count: int = 50) -> list:
        """Get filled/completed order history from Webull
        
        Args:
            count: Number of recent orders to fetch (default 50)
            
        Returns:
            List of filled order dicts with keys: order_id, symbol, quantity, 
            filled_price, action, filled_time, asset_type, strike, expiry, direction
        """
        def _blocking_get_history():
            wb = self._client
            if not wb:
                return []
            
            try:
                orders_raw = None
                
                # METHOD 1: Try get_history_orders() with patched URL (fixes startTime bug)
                # This is the primary method now that we've monkey-patched the URL
                if hasattr(wb, 'get_history_orders'):
                    try:
                        history = wb.get_history_orders(status='Filled', count=count)
                        
                        if isinstance(history, list) and len(history) > 0:
                            orders_raw = history
                        elif isinstance(history, dict):
                            orders_raw = history.get('data', []) or history.get('items', [])
                    except Exception as hist_err:
                        pass  # Silent fallback to other methods
                
                # METHOD 2: Try get_activities() as fallback
                if not orders_raw and hasattr(wb, 'get_activities'):
                    try:
                        activities = wb.get_activities(index=1, size=100)
                        if isinstance(activities, dict):
                            all_items = activities.get('items', []) or activities.get('data', [])
                            if all_items:
                                orders_raw = [
                                    item for item in all_items
                                    if isinstance(item, dict) and (
                                        item.get('type') in ('BUY', 'SELL', 'TRADE', 'OPTION_BUY', 'OPTION_SELL') or
                                        item.get('action') in ('BUY', 'SELL')
                                    )
                                ]
                    except Exception:
                        pass  # Silent fallback
                
                # METHOD 3: Direct API call with correct URL as last resort
                if not orders_raw:
                    try:
                        import requests
                        headers = wb.build_req_headers(include_trade_token=True, include_time=True)
                        account_id = getattr(wb, '_account_id', '')
                        
                        url = f"https://ustrade.webullbroker.com/api/trade/v2/option/list?secAccountId={account_id}&dateType=ORDER&pageSize={count}&status=Filled"
                        
                        response = requests.get(url, headers=headers, timeout=15)
                        if response.status_code == 200:
                            result = response.json()
                            if isinstance(result, list):
                                orders_raw = result
                            elif isinstance(result, dict):
                                orders_raw = result.get('data', []) or result.get('items', [])
                    except Exception:
                        orders_raw = []
                
                orders = []
                
                if not orders_raw:
                    return []
                
                if not isinstance(orders_raw, list):
                    return []
                
                for combo_order in orders_raw:
                    if not isinstance(combo_order, dict):
                        continue
                    
                    nested_orders = combo_order.get('orders', [])
                    if nested_orders and isinstance(nested_orders, list):
                        for order in nested_orders:
                            if not isinstance(order, dict):
                                continue
                            status = order.get('status', order.get('statusStr', ''))
                            if 'Filled' not in str(status):
                                continue
                            
                            ticker = order.get('ticker', {})
                            symbol = ticker.get('symbol', '') if isinstance(ticker, dict) else ''
                            
                            option_data = order.get('optionExercisePrice')
                            is_option = option_data is not None or order.get('assetType') == 'OPTION'
                            
                            order_dict = {
                                'order_id': str(order.get('orderId', '')),
                                'symbol': symbol,
                                'quantity': int(order.get('filledQuantity', 0) or order.get('totalQuantity', 0)),
                                'filled_price': float(order.get('avgFilledPrice', 0) or order.get('filledPrice', 0) or 0),
                                'action': order.get('action', ''),
                                'filled_time': order.get('filledTime', '') or order.get('updateTime', ''),
                                'asset_type': 'option' if is_option else 'stock',
                                'order_type': order.get('orderType', 'LMT'),
                            }
                            
                            if is_option:
                                order_dict['strike'] = float(order.get('optionExercisePrice', 0) or 0)
                                order_dict['expiry'] = order.get('optionExpireDate', '')
                                direction = order.get('optionType', '')
                                order_dict['direction'] = 'C' if direction.upper() == 'CALL' else ('P' if direction.upper() == 'PUT' else '')
                            
                            if order_dict['order_id'] and order_dict['symbol']:
                                orders.append(order_dict)
                    else:
                        # Flat order structure (stocks or single-leg orders)
                        order = combo_order
                        status = order.get('status', order.get('statusStr', ''))
                        if 'Filled' not in str(status):
                            continue
                            
                        ticker = order.get('ticker', {})
                        symbol = ticker.get('symbol', '') if isinstance(ticker, dict) else ''
                        
                        option_data = order.get('optionExercisePrice')
                        is_option = option_data is not None or order.get('assetType') == 'OPTION'
                        
                        order_dict = {
                            'order_id': str(order.get('orderId', '')),
                            'symbol': symbol,
                            'quantity': int(order.get('filledQuantity', 0) or order.get('totalQuantity', 0)),
                            'filled_price': float(order.get('avgFilledPrice', 0) or order.get('filledPrice', 0) or 0),
                            'action': order.get('action', ''),
                            'filled_time': order.get('filledTime', '') or order.get('updateTime', ''),
                            'asset_type': 'option' if is_option else 'stock',
                            'order_type': order.get('orderType', 'LMT'),
                        }
                        
                        if is_option:
                            order_dict['strike'] = float(order.get('optionExercisePrice', 0) or 0)
                            order_dict['expiry'] = order.get('optionExpireDate', '')
                            direction = order.get('optionType', '')
                            order_dict['direction'] = 'C' if direction.upper() == 'CALL' else ('P' if direction.upper() == 'PUT' else '')
                        
                        if order_dict['order_id'] and order_dict['symbol']:
                            orders.append(order_dict)
                
                return orders
            except Exception as e:
                print(f"[Webull] Error getting order history: {e}")
                import traceback
                traceback.print_exc()
                return []
        
        return await self.loop.run_in_executor(None, _blocking_get_history)

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
DTE_OPT_REGEX = re.compile(DTE_OPT_PATTERN, re.IGNORECASE)
SPX_NDX_SHORTHAND_REGEX = re.compile(SPX_NDX_SHORTHAND_PATTERN, re.IGNORECASE)
WAXUI_ENTRY_REGEX = re.compile(WAXUI_ENTRY_PATTERN, re.IGNORECASE)
WAXUI_TRIM_REGEX = re.compile(WAXUI_TRIM_PATTERN, re.IGNORECASE)
WAXUI_CLOSE_REGEX = re.compile(WAXUI_CLOSE_PATTERN, re.IGNORECASE)
BEAR_CONTRACT_REGEX = re.compile(BEAR_CONTRACT_PATTERN, re.IGNORECASE | re.MULTILINE)
BEAR_ENTRY_REGEX = re.compile(BEAR_ENTRY_PATTERN, re.IGNORECASE)
BEAR_TRIM_REGEX = re.compile(BEAR_TRIM_PATTERN, re.IGNORECASE)
BEAR_LOTTO_REGEX = re.compile(BEAR_LOTTO_PATTERN, re.IGNORECASE)
BISHOP_OPTION_REGEX = re.compile(BISHOP_OPTION_PATTERN, re.IGNORECASE | re.MULTILINE)
BISHOP_ENTRY_REGEX = re.compile(BISHOP_ENTRY_PATTERN, re.IGNORECASE)
BISHOP_TRIM_REGEX = re.compile(BISHOP_TRIM_PATTERN, re.IGNORECASE)
BISHOP_STOPPED_REGEX = re.compile(BISHOP_STOPPED_PATTERN, re.IGNORECASE)
EVAPANDA_REGEX = re.compile(EVAPANDA_PATTERN, re.IGNORECASE)

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
        # Try DTE format first: BTO $QQQ 621c 0DTE @0.74
        dte_match = DTE_OPT_REGEX.search(text.strip())
        if dte_match:
            action, symbol, strike, opt_type, dte_days, price_str = dte_match.groups()
            expiry = calculate_dte_expiry(int(dte_days))
            price = float(price_str)
            print(f"[Discord] ✓ Matched DTE format: {action} {symbol} {strike}{opt_type} {dte_days}DTE @ ${price} -> expiry {expiry}")
            _current_trading_settings = get_trading_settings()
            max_position_size = _current_trading_settings['max_position_size']
            actual_cost_per_contract = price * 100
            qty = max(1, int(max_position_size / actual_cost_per_contract)) if actual_cost_per_contract > 0 else 1
            print(f"[AUTO-QTY] DTE format: ${price} x 100 = ${actual_cost_per_contract}/contract, buying {qty} (max ${max_position_size})")
            return {
                "asset": "option",
                "action": action.upper(),
                "qty": qty,
                "qty_specified": False,
                "symbol": symbol.upper(),
                "strike": float(strike),
                "opt_type": opt_type.upper(),
                "expiry": expiry,
                "price": price,
                "is_market_order": False,
                "_dte_format": True,
                "_dte_days": int(dte_days)
            }
        
        # Try JC format: BTO $QQQ $627c 12/10 .77
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
                                                                # Try Bear-style Contract/Entry format
                                                                bear_contract_m = BEAR_CONTRACT_REGEX.search(text.strip())
                                                                if bear_contract_m:
                                                                    symbol, month, day, strike, opt_type = bear_contract_m.groups()
                                                                    expiry = f"{month}/{day}"
                                                                    # Check for Entry price
                                                                    bear_entry_m = BEAR_ENTRY_REGEX.search(text.strip())
                                                                    if bear_entry_m:
                                                                        price_str = bear_entry_m.group(1)
                                                                        price = float(price_str) if price_str else None
                                                                        print(f"[Discord] ✓ Matched Bear Contract/Entry format: {symbol} {strike}{opt_type} {expiry} @ ${price_str}")
                                                                        _current_trading_settings = get_trading_settings()
                                                                        max_position_size = _current_trading_settings['max_position_size']
                                                                        actual_cost_per_contract = price * 100 if price else 100
                                                                        qty = max(1, int(max_position_size / actual_cost_per_contract)) if actual_cost_per_contract > 0 else 1
                                                                        print(f"[AUTO-QTY] Bear: ${price} x 100 = ${actual_cost_per_contract}/contract, buying {qty} (max ${max_position_size})")
                                                                        return {
                                                                            "asset": "option",
                                                                            "action": "BTO",
                                                                            "qty": qty,
                                                                            "symbol": symbol.upper(),
                                                                            "strike": float(strike),
                                                                            "opt_type": opt_type.upper(),
                                                                            "expiry": expiry,
                                                                            "price": price,
                                                                            "is_market_order": price is None,
                                                                            "_bear_format": True
                                                                        }
                                                                    else:
                                                                        # Contract without Entry - check if it's a trim
                                                                        bear_trim_m = BEAR_TRIM_REGEX.search(text.strip())
                                                                        if bear_trim_m:
                                                                            print(f"[Discord] ✓ Matched Bear TRIM format: {symbol} {strike}{opt_type} {expiry}")
                                                                            return {
                                                                                "asset": "option",
                                                                                "action": "STC",
                                                                                "qty": 1,
                                                                                "symbol": symbol.upper(),
                                                                                "strike": float(strike),
                                                                                "opt_type": opt_type.upper(),
                                                                                "expiry": expiry,
                                                                                "price": None,
                                                                                "is_market_order": True,
                                                                                "_bear_trim": True,
                                                                                "_exit_type": "HALF"
                                                                            }
                                                                        else:
                                                                            # Just tracking/update - no execution
                                                                            print(f"[Discord] Bear Contract (tracking only, no Entry): {symbol} {strike}{opt_type} {expiry}")
                                                                            return None
                                                                else:
                                                                    # Try Bear lotto format: SPX 11/18. 5900c @0.55
                                                                    bear_lotto_m = BEAR_LOTTO_REGEX.search(text.strip())
                                                                    if bear_lotto_m:
                                                                        symbol, month, day, strike, opt_type, price_str = bear_lotto_m.groups()
                                                                        expiry = f"{month}/{day}"
                                                                        price = float(price_str)
                                                                        print(f"[Discord] ✓ Matched Bear LOTTO format: {symbol} {strike}{opt_type} {expiry} @ ${price_str}")
                                                                        _current_trading_settings = get_trading_settings()
                                                                        max_position_size = _current_trading_settings['max_position_size']
                                                                        actual_cost_per_contract = price * 100
                                                                        qty = max(1, int(max_position_size / actual_cost_per_contract)) if actual_cost_per_contract > 0 else 1
                                                                        print(f"[AUTO-QTY] Bear Lotto: ${price} x 100 = ${actual_cost_per_contract}/contract, buying {qty} (max ${max_position_size})")
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
                                                                            "_bear_lotto": True
                                                                        }
                                                                    else:
                                                                        # Try standalone Bear trim: "I'm trimming here"
                                                                        bear_trim_standalone_m = BEAR_TRIM_REGEX.search(text.strip())
                                                                        if bear_trim_standalone_m:
                                                                            print(f"[Discord] ✓ Matched standalone Bear TRIM format (no contract context)")
                                                                            return {
                                                                                "asset": "option",
                                                                                "action": "STC",
                                                                                "qty": 1,
                                                                                "symbol": None,
                                                                                "strike": None,
                                                                                "opt_type": None,
                                                                                "expiry": None,
                                                                                "price": None,
                                                                                "is_market_order": True,
                                                                                "_bear_trim": True,
                                                                                "_exit_type": "HALF"
                                                                            }
                                                                        else:
                                                                            # Try Bishop trim format: Trimming SPX 6900 P 12/30 @$1.30
                                                                            bishop_trim_m = BISHOP_TRIM_REGEX.search(text.strip())
                                                                            if bishop_trim_m:
                                                                                symbol, strike, opt_type, month, day, price_str = bishop_trim_m.groups()
                                                                                expiry = f"{month}/{day}"
                                                                                price = float(price_str)
                                                                                print(f"[Discord] ✓ Matched Bishop TRIM format: STC {symbol} {strike}{opt_type} {expiry} @ ${price_str}")
                                                                                return {
                                                                                    "asset": "option",
                                                                                    "action": "STC",
                                                                                    "qty": 1,
                                                                                    "qty_specified": False,
                                                                                    "symbol": symbol.upper(),
                                                                                    "strike": float(strike),
                                                                                    "opt_type": opt_type.upper(),
                                                                                    "expiry": expiry,
                                                                                    "price": price,
                                                                                    "is_market_order": False,
                                                                                    "_bishop_trim": True,
                                                                                    "_exit_type": "PARTIAL"
                                                                                }
                                                                            else:
                                                                                # Try Bishop entry format: "I'm Entering" + "Option: SPX 6900 P 12/30" + "Entry: 1.00"
                                                                                if "i'm entering" in text.lower() or "im entering" in text.lower():
                                                                                    bishop_option_m = BISHOP_OPTION_REGEX.search(text.strip())
                                                                                    if bishop_option_m:
                                                                                        symbol, strike, opt_type, month, day = bishop_option_m.groups()
                                                                                        expiry = f"{month}/{day}"
                                                                                        # Check for Entry price
                                                                                        bishop_entry_m = BISHOP_ENTRY_REGEX.search(text.strip())
                                                                                        if bishop_entry_m:
                                                                                            price_str = bishop_entry_m.group(1)
                                                                                            price = float(price_str) if price_str else None
                                                                                            print(f"[Discord] ✓ Matched Bishop Entry format: BTO {symbol} {strike}{opt_type} {expiry} @ ${price_str}")
                                                                                            _current_trading_settings = get_trading_settings()
                                                                                            max_position_size = _current_trading_settings['max_position_size']
                                                                                            actual_cost_per_contract = price * 100 if price else 100
                                                                                            qty = max(1, int(max_position_size / actual_cost_per_contract)) if actual_cost_per_contract > 0 else 1
                                                                                            print(f"[AUTO-QTY] Bishop: ${price} x 100 = ${actual_cost_per_contract}/contract, buying {qty} (max ${max_position_size})")
                                                                                            return {
                                                                                                "asset": "option",
                                                                                                "action": "BTO",
                                                                                                "qty": qty,
                                                                                                "qty_specified": False,
                                                                                                "symbol": symbol.upper(),
                                                                                                "strike": float(strike),
                                                                                                "opt_type": opt_type.upper(),
                                                                                                "expiry": expiry,
                                                                                                "price": price,
                                                                                                "is_market_order": price is None,
                                                                                                "_bishop_format": True
                                                                                            }
                                                                                
                                                                                # Try Bishop "stopped out" format: "Got stopped out at $1.65"
                                                                                # This requires position matching since it doesn't include contract details
                                                                                bishop_stopped_m = BISHOP_STOPPED_REGEX.search(text.strip())
                                                                                if bishop_stopped_m:
                                                                                    price_str = bishop_stopped_m.group(1)
                                                                                    price = float(price_str) if price_str else None
                                                                                    print(f"[Discord] ✓ Matched Bishop STOPPED format: exit @ ${price_str}")
                                                                                    # Mark this signal for position matching (will be resolved during execution)
                                                                                    return {
                                                                                        "asset": "option",
                                                                                        "action": "STC",
                                                                                        "qty": 0,  # Will be filled from position
                                                                                        "qty_specified": False,
                                                                                        "symbol": None,  # Will be matched from most recent position
                                                                                        "strike": None,
                                                                                        "opt_type": None,
                                                                                        "expiry": None,
                                                                                        "price": price,
                                                                                        "is_market_order": price is None,
                                                                                        "_bishop_stopped": True,
                                                                                        "_exit_type": "ALL",
                                                                                        "_needs_position_match": True  # Flag for position matching
                                                                                    }
                                                                                
                                                                                # Try EvaPanda format: BTO FSLR 01/16/26 300C @ 3.25
                                                                                # Uses embed title "Open" or "Close" to indicate entry/exit
                                                                                evapanda_m = EVAPANDA_REGEX.search(text.strip())
                                                                                if evapanda_m:
                                                                                    action, symbol, month, day, year, strike, opt_type, price_str = evapanda_m.groups()
                                                                                    expiry = f"{month}/{day}"  # Convert to MM/DD format
                                                                                    price = float(price_str) if price_str else None
                                                                                    print(f"[Discord] ✓ Matched EvaPanda format: {action} {symbol} {strike}{opt_type} {expiry} @ ${price_str}")
                                                                                    _current_trading_settings = get_trading_settings()
                                                                                    max_position_size = _current_trading_settings['max_position_size']
                                                                                    actual_cost_per_contract = price * 100 if price else 100
                                                                                    qty = max(1, int(max_position_size / actual_cost_per_contract)) if actual_cost_per_contract > 0 else 1
                                                                                    print(f"[AUTO-QTY] EvaPanda: ${price} x 100 = ${actual_cost_per_contract}/contract, qty={qty} (max ${max_position_size})")
                                                                                    return {
                                                                                        "asset": "option",
                                                                                        "action": action.upper(),
                                                                                        "qty": qty,
                                                                                        "qty_specified": False,
                                                                                        "symbol": symbol.upper(),
                                                                                        "strike": float(strike),
                                                                                        "opt_type": opt_type.upper(),
                                                                                        "expiry": expiry,
                                                                                        "price": price,
                                                                                        "is_market_order": price is None,
                                                                                        "_evapanda_format": True
                                                                                    }
                                                                                
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
    qty_from_signal = False  # Track whether qty came from signal text
    
    if qty_str is None:
        if direction.upper() == 'STC':
            # For STC without qty, we'll set a flag to calculate from open position later
            # This prevents the bug of calculating STC qty from exit price
            qty = None  # Will be calculated from open lots in lot_matcher
            print(f"[AUTO-QTY] STC without qty - will close based on open position size")
        elif is_market_order:
            # For market orders without qty, default to 1 contract
            qty = 1
            print(f"[AUTO-QTY] Market order: defaulting to 1 contract")
        else:
            # BTO without qty - set flag for tiered default system
            # Will check: channel default → global default → max_position_size calculation
            qty = None  # Will be set by tiered default system in handler
            print(f"[AUTO-QTY] BTO without qty - will apply tiered default (channel → global → max_position_size)")
    else:
        qty = int(qty_str)
        qty_from_signal = True
    
    return {
        "asset": "option",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "strike": float(strike),
        "opt_type": opt_type.upper(),
        "expiry": expiry,
        "price": price,  # None for market orders
        "is_market_order": is_market_order,
        "_qty_from_signal": qty_from_signal  # Flag for tiered default system
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
    groups = m.groups()
    direction, qty_str, symbol, price_str = groups[:4]
    pct_str = groups[4] if len(groups) > 4 else None
    
    # Check for market order: "@ m" or "@m" means execute at market price
    is_market_order = price_str.lower() == 'm'
    if is_market_order:
        price = None  # Market order - price will be determined at execution
        print(f"[SIGNAL] Market order detected for {symbol}")
    else:
        price = float(price_str)
    
    # Calculate quantity if not specified
    qty_from_signal = False  # Track whether qty came from signal text
    
    if qty_str is None:
        if is_market_order:
            # For market orders without qty, default to 1 share
            qty = 1
            print(f"[AUTO-QTY] Market order: defaulting to 1 share")
        elif direction.upper() == 'STC':
            # For STC without qty, close entire position
            qty = None
            print(f"[AUTO-QTY] STC without qty - will close based on open position size")
        else:
            # BTO without qty - set flag for tiered default system
            qty = None
            print(f"[AUTO-QTY] Stock BTO without qty - will apply tiered default (channel → global → max_position_size)")
    else:
        qty = int(qty_str)
        qty_from_signal = True
    
    result = {
        "asset": "stock",
        "action": direction.upper(),
        "qty": qty,
        "symbol": symbol.upper(),
        "price": price,  # None for market orders
        "is_market_order": is_market_order,
        "_qty_from_signal": qty_from_signal  # Flag for tiered default system
    }
    
    # Add position size percentage if parsed from signal (e.g., "BTO $SIDU @ 4.00 (12.5%)")
    if pct_str:
        result['_position_size_pct'] = float(pct_str)
        print(f"[POSITION SIZE] ✓ Parsed {pct_str}% from signal - will size based on account percentage")
    
    return result


# ------------------------------ TRADE IDEA PARSER ---------------------------------
TRADE_IDEA_PATTERN = re.compile(
    r'TRADE\s+IDEA\s*\n'
    r'.*?Ticker:\s*(\$?[A-Za-z]+)\s*\n'
    r'.*?Entry:\s*([\d.]+)(?:\s*\(([^)]+)\))?\s*\n'
    r'.*?Levels?:\s*(.+?)\s*\n'
    r'.*?SL:\s*([\d.]+)',
    re.IGNORECASE | re.DOTALL
)

def parse_trade_idea_signal(text: str) -> Optional[dict]:
    """Parse TRADE IDEA format signals into structured data.
    
    Format:
    TRADE IDEA
    Ticker: ENSC
    Entry: 2.02 (break)
    Levels: 2.10 - 2.16 - 2.22 - 2.30
    SL: 1.78
    """
    m = TRADE_IDEA_PATTERN.search(text)
    if not m:
        return None
    
    ticker = m.group(1).replace('$', '').upper()
    entry_price = float(m.group(2))
    entry_qualifier = m.group(3) or ''  # e.g., "break"
    levels_str = m.group(4)
    stop_loss = float(m.group(5))
    
    levels = []
    for level in re.findall(r'[\d.]+', levels_str):
        try:
            levels.append(float(level))
        except ValueError:
            pass
    
    return {
        "type": "trade_idea",
        "ticker": ticker,
        "entry": entry_price,
        "entry_qualifier": entry_qualifier.strip(),
        "levels": levels,
        "stop_loss": stop_loss,
        "raw_text": text.strip()
    }


def format_trade_idea_for_webhook(parsed: dict) -> str:
    """Format parsed trade idea for Discord webhook posting."""
    ticker = parsed.get('ticker', 'UNKNOWN')
    entry = parsed.get('entry', 0)
    qualifier = parsed.get('entry_qualifier', '')
    levels = parsed.get('levels', [])
    stop_loss = parsed.get('stop_loss', 0)
    
    entry_str = f"{entry}"
    if qualifier:
        entry_str += f" ({qualifier})"
    
    levels_str = ' - '.join([str(l) for l in levels]) if levels else 'N/A'
    if levels and any('+' in str(l) for l in levels):
        levels_str = levels_str.rstrip('+') + '+'
    
    msg = f"📈 **TRADE IDEA**\n"
    msg += f"**Ticker:** {ticker}\n"
    msg += f"**Entry:** ${entry_str}\n"
    msg += f"**Targets:** {levels_str}\n"
    msg += f"**Stop Loss:** ${stop_loss}\n"
    
    return msg


def format_trade_idea_as_bto_stc(parsed: dict) -> str:
    """Format parsed trade idea as BTO/STC signal format.
    
    Converts TRADE IDEA format to a simpler BTO format for webhook forwarding.
    Works with both stock and option signals.
    
    For stocks:
        TRADE IDEA: $AAPL ENTRY $175 LEVELS 180-185-190 SL $170
    To:
        BTO AAPL @ $175
        Targets: $180, $185, $190
        SL: $170
    """
    ticker = parsed.get('ticker', 'UNKNOWN')
    entry = parsed.get('entry', 0)
    stop_loss = parsed.get('stop_loss', 0)
    levels = parsed.get('levels', [])
    qualifier = parsed.get('entry_qualifier', '')
    
    # Check if this looks like an option (has option_type, expiry, or strike fields)
    is_option = parsed.get('is_option', False)
    strike = parsed.get('strike')
    expiry = parsed.get('expiry', '')
    option_type = parsed.get('option_type', '')
    premium = parsed.get('premium', '')
    
    if is_option and (strike or option_type):
        # Format as BTO option signal
        opt_type = option_type if option_type else 'C'
        strike_val = strike if strike else entry
        
        # If no expiry provided, use a reasonable default (next Friday)
        if not expiry:
            from datetime import datetime, timedelta
            today = datetime.now()
            days_until_friday = (4 - today.weekday()) % 7
            if days_until_friday == 0:
                days_until_friday = 7
            next_friday = today + timedelta(days=days_until_friday)
            expiry = next_friday.strftime('%m/%d')
        
        msg = f"BTO {ticker} {expiry} {strike_val}{opt_type}"
        if premium:
            msg += f" @ {premium}"
        
        if levels:
            targets_str = ', '.join([f"${l}" for l in levels[:3]])
            msg += f"\nTargets: {targets_str}"
        
        if stop_loss:
            msg += f"\nSL: ${stop_loss}"
        
        return msg
    else:
        # For stock signals, format as simple BTO entry
        entry_str = f"@ ${entry}"
        if qualifier:
            entry_str += f" ({qualifier})"
        
        msg = f"BTO {ticker} {entry_str}\n"
        
        if levels:
            targets_str = ', '.join([f"${l}" for l in levels[:3]])
            msg += f"Targets: {targets_str}\n"
        
        if stop_loss:
            msg += f"SL: ${stop_loss}"
        
        return msg.strip()


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
        self._message_dedupe_lock = None  # Will be created in setup() when event loop is ready
        
        # Command execution lock (prevent race conditions)
        self._executing_commands: set = set()  # Track currently executing command message IDs
        
        # Sent message tracking (prevent duplicate sends from discord.py-self bug)
        self._recent_sends: dict = {}  # {content_hash: timestamp}
        self._send_dedupe_window = 300.0  # 5 minutes (discord.py-self can resend messages after long delays)
        
        # Guard to prevent on_ready from running multiple times (Discord reconnects trigger on_ready)
        self._on_ready_completed = False
        
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
    
    def _resolve_position_match(self, signal: dict, channel_id: int) -> bool:
        """Resolve signals that need position matching (e.g., Bishop 'stopped out' signals).
        
        For exit signals that don't include contract details, this function finds
        the most recent open position from the channel and fills in the missing info.
        
        Returns:
            True if position was found and signal was resolved
            False if no matching position found
        """
        if not signal.get('_needs_position_match'):
            return True  # No matching needed
        
        try:
            # Import database function
            import sys
            from pathlib import Path
            parent_dir = Path(__file__).parent.parent
            if str(parent_dir) not in sys.path:
                sys.path.insert(0, str(parent_dir))
            
            from gui_app.database import get_most_recent_open_lot
            
            # Find most recent open lot from this channel
            lot = get_most_recent_open_lot(channel_id, asset_type='option')
            
            if lot:
                # Fill in contract details from the lot
                signal['symbol'] = lot['symbol']
                signal['strike'] = lot['strike']
                signal['expiry'] = lot['expiry']
                signal['opt_type'] = lot['call_put']
                signal['qty'] = lot['remaining_qty']
                signal['_matched_lot_id'] = lot['id']
                
                print(f"[POSITION_MATCH] ✓ Matched 'stopped out' to: {lot['symbol']} {lot['strike']}{lot['call_put']} {lot['expiry']} (qty={lot['remaining_qty']})")
                return True
            else:
                print(f"[POSITION_MATCH] ⚠️ No open position found for channel {channel_id} - skipping 'stopped out' signal")
                return False
                
        except Exception as e:
            print(f"[POSITION_MATCH] Error matching position: {e}")
            return False
    
    def _process_lot_tracking(self, signal: dict, channel_id: int, message_id: int):
        """Process BTO/STC signals for PNL tracking using FIFO lot matching"""
        if not self.db:
            return
        
        try:
            # Handle position matching for signals that need it (e.g., Bishop 'stopped out')
            if signal.get('_needs_position_match'):
                if not self._resolve_position_match(signal, channel_id):
                    print(f"[PNL_TRACKER] Skipping signal - no matching position found")
                    return
            
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
                
                # Calculate PNL and store for Trade Summary posting
                total_pnl = 0
                total_qty = 0
                entry_prices = []
                for closed_lot in result:
                    qty_closed = closed_lot.get('qty_closed', 0)
                    entry_price = closed_lot.get('entry_price', 0)
                    exit_price = signal.get('price', 0)
                    lot_pnl = (exit_price - entry_price) * qty_closed * 100  # Options = 100 multiplier
                    total_pnl += lot_pnl
                    total_qty += qty_closed
                    entry_prices.append(entry_price)
                
                avg_entry = sum(entry_prices) / len(entry_prices) if entry_prices else 0
                exit_price = signal.get('price', 0)
                pnl_pct = ((exit_price - avg_entry) / avg_entry * 100) if avg_entry > 0 else 0
                
                # Store PNL result for Trade Summary posting (accessed by on_message)
                signal['_pnl_result'] = {
                    'total_pnl': total_pnl,
                    'total_qty': total_qty,
                    'avg_entry': avg_entry,
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct,
                    'lots_closed': len(result)
                }
                print(f"[PNL_TRACKER] 💰 PNL: ${total_pnl:+.2f} ({pnl_pct:+.1f}%) - {total_qty} contracts @ ${avg_entry:.2f} → ${exit_price:.2f}")
            
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
        self._message_dedupe_lock = asyncio.Lock()  # Protect message deduplication from race conditions
        print("[ASYNC] ✓ Queue and events created in event loop")
        
        self.broker = WebullBroker(loop=self.loop)
        try:
            await self.broker.login()
            if self.broker._logged_in:
                print("[Webull] ✓ Login successful (LIVE account)", flush=True)
                self.broker_ready.set()
                # Update broker status in GUI
                try:
                    from gui_app.broker_credentials_service import set_broker_status
                    set_broker_status('webull_live', True, 'connected', account_info={'mode': 'live'})
                    if PAPER_TRADE:
                        set_broker_status('webull_paper', True, 'connected', account_info={'mode': 'paper'})
                except Exception:
                    pass
            else:
                print("[Webull] ⚠️  Broker not configured - configure via GUI (see startup logs for port)", flush=True)
                # Update broker status to disconnected
                try:
                    from gui_app.broker_credentials_service import set_broker_status
                    set_broker_status('webull_live', False, 'disconnected', error='Credentials not configured')
                    set_broker_status('webull_paper', False, 'disconnected', error='Credentials not configured')
                except Exception:
                    pass
        except Exception as e:
            print("[Webull] ✗ Login failed:", e, flush=True)
            # Update broker status to disconnected on error
            try:
                from gui_app.broker_credentials_service import set_broker_status
                set_broker_status('webull_live', False, 'disconnected', error=str(e))
                set_broker_status('webull_paper', False, 'disconnected', error=str(e))
            except Exception:
                pass
        
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
                    # Update broker status to disconnected
                    try:
                        from gui_app.broker_credentials_service import set_broker_status
                        set_broker_status('alpaca_paper', False, 'disconnected', error='Missing API credentials')
                    except Exception:
                        pass
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
                        # Update broker status in GUI
                        try:
                            from gui_app.broker_credentials_service import set_broker_status
                            set_broker_status('alpaca_paper', True, 'connected', account_info={'mode': 'paper'})
                        except Exception:
                            pass
                    else:
                        _original_print("[ALPACA] ⚠️ Paper broker connection failed", flush=True)
                        self.paper_broker = None
                        # Update broker status to disconnected
                        try:
                            from gui_app.broker_credentials_service import set_broker_status
                            set_broker_status('alpaca_paper', False, 'disconnected', error='Connection failed')
                        except Exception:
                            pass
                    
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

        # Initialize DhanQ broker (India - DhanHQ v2 API - Always LIVE)
        self.dhanq_broker = None
        try:
            if DHANQ_AVAILABLE:
                _original_print("[DHANQ] Starting broker initialization...", flush=True)
                _original_print("[DHANQ] ⚠️ WARNING: DhanQ has NO paper trading mode - ALL trades are LIVE", flush=True)
                
                from gui_app.database import get_broker_credentials
                dhanq_creds = get_broker_credentials('dhanq')
                
                if dhanq_creds and dhanq_creds.get('credentials'):
                    creds = dhanq_creds.get('credentials', {})
                    dhanq_client_id = creds.get('client_id', '')
                    dhanq_access_token = creds.get('access_token', '')
                    
                    if dhanq_client_id and dhanq_access_token:
                        _original_print(f"[DHANQ] ✓ Loaded credentials from DATABASE", flush=True)
                        _original_print(f"[DHANQ]   Client ID: {dhanq_client_id[:8]}...", flush=True)
                        _original_print(f"[DHANQ] Creating DhanQBroker instance...", flush=True)
                        
                        self.dhanq_broker = DhanQBroker({
                            'client_id': dhanq_client_id,
                            'access_token': dhanq_access_token
                        })
                        
                        connected = await self.dhanq_broker.connect()
                        if connected:
                            _original_print(f"[DHANQ] ✓ Connected successfully (LIVE trading)", flush=True)
                            try:
                                from gui_app.database import update_broker_connection_status
                                account_info = await self.dhanq_broker.get_account_info()
                                update_broker_connection_status('dhanq', True, f"Connected - Client: {dhanq_client_id}")
                                available = account_info.get('available_balance', 0)
                                if available:
                                    _original_print(f"[DHANQ]   Available: ₹{available:,.2f}", flush=True)
                                _original_print(f"[DHANQ] ✓ Broker status updated in GUI", flush=True)
                            except Exception as status_err:
                                _original_print(f"[DHANQ] ⚠️ Failed to update broker status: {status_err}", flush=True)
                        else:
                            _original_print("[DHANQ] ⚠️ Connection failed - token may be expired", flush=True)
                            _original_print("[DHANQ]   Go to Settings → Brokers → DhanQ to update access token", flush=True)
                            from gui_app.database import update_broker_connection_status
                            update_broker_connection_status('dhanq', False, 'Connection failed - token may be expired')
                            self.dhanq_broker = None
                    else:
                        _original_print("[DHANQ] ⚠️ Incomplete credentials - missing client_id or access_token", flush=True)
                else:
                    _original_print("[DHANQ] No credentials configured - broker disabled", flush=True)
            else:
                _original_print("[DHANQ] DhanQBroker not available (dhanhq not installed)", flush=True)
        except Exception as e:
            _original_print(f"[DHANQ] ⚠️ Initialization failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.dhanq_broker = None

        # Initialize Upstox broker (India - OAuth2 API - Always LIVE)
        self.upstox_broker = None
        try:
            if UPSTOX_AVAILABLE:
                _original_print("[UPSTOX] Starting broker initialization...", flush=True)
                _original_print("[UPSTOX] ⚠️ WARNING: Upstox has NO paper trading mode - ALL trades are LIVE", flush=True)
                
                from gui_app.database import get_broker_credentials
                upstox_creds = get_broker_credentials('upstox')
                
                if upstox_creds and upstox_creds.get('credentials'):
                    creds = upstox_creds.get('credentials', {})
                    upstox_access_token = creds.get('access_token', '')
                    upstox_refresh_token = creds.get('refresh_token', '')
                    upstox_api_key = creds.get('api_key', '')
                    upstox_api_secret = creds.get('api_secret', '')
                    token_issued_at = creds.get('token_issued_at', '')
                    
                    if upstox_access_token:
                        _original_print(f"[UPSTOX] ✓ Loaded credentials from DATABASE", flush=True)
                        _original_print(f"[UPSTOX] Creating UpstoxBroker instance...", flush=True)
                        
                        self.upstox_broker = UpstoxBroker({
                            'access_token': upstox_access_token,
                            'refresh_token': upstox_refresh_token,
                            'api_key': upstox_api_key,
                            'api_secret': upstox_api_secret,
                            'token_issued_at': token_issued_at
                        })
                        
                        connected = await self.upstox_broker.connect()
                        if connected:
                            _original_print(f"[UPSTOX] ✓ Connected successfully (LIVE trading)", flush=True)
                            try:
                                from gui_app.database import update_broker_connection_status
                                account_info = await self.upstox_broker.get_account_info()
                                update_broker_connection_status('upstox', True, f"Connected - User: {self.upstox_broker.user_id}")
                                _original_print(f"[UPSTOX] ✓ Broker status updated in GUI", flush=True)
                                
                                if upstox_refresh_token:
                                    try:
                                        await self.upstox_broker.start_token_refresh_scheduler()
                                    except Exception as sched_err:
                                        _original_print(f"[UPSTOX] ⚠️ Auto-refresh scheduler failed: {sched_err}", flush=True)
                            except Exception as status_err:
                                _original_print(f"[UPSTOX] ⚠️ Failed to update broker status: {status_err}", flush=True)
                        else:
                            _original_print("[UPSTOX] ⚠️ Connection failed - token may be expired", flush=True)
                            if upstox_refresh_token:
                                _original_print("[UPSTOX]   Attempting token refresh...", flush=True)
                                refresh_success = await self.upstox_broker.refresh_access_token()
                                if refresh_success:
                                    _original_print("[UPSTOX] ✓ Token refreshed, retrying connection...", flush=True)
                                    self.upstox_broker.config['token_issued_at'] = datetime.now().isoformat()
                                    retry_connected = await self.upstox_broker.connect()
                                    if retry_connected:
                                        _original_print(f"[UPSTOX] ✓ Reconnected after token refresh (LIVE trading)", flush=True)
                                        from gui_app.database import update_broker_connection_status
                                        update_broker_connection_status('upstox', True, f"Connected - User: {self.upstox_broker.user_id}")
                                        await self.upstox_broker.start_token_refresh_scheduler()
                                    else:
                                        _original_print("[UPSTOX] ⚠️ Reconnection failed after refresh", flush=True)
                                        from gui_app.database import update_broker_connection_status
                                        update_broker_connection_status('upstox', False, 'Reconnection failed after token refresh')
                                        self.upstox_broker = None
                                else:
                                    _original_print("[UPSTOX] ⚠️ Token refresh failed - manual re-auth required", flush=True)
                                    from gui_app.database import update_broker_connection_status
                                    update_broker_connection_status('upstox', False, 'Token refresh failed - manual re-auth required')
                                    self.upstox_broker = None
                            else:
                                _original_print("[UPSTOX]   Go to Settings → Brokers → Upstox to update access token", flush=True)
                                from gui_app.database import update_broker_connection_status
                                update_broker_connection_status('upstox', False, 'Connection failed - token may be expired')
                                self.upstox_broker = None
                    else:
                        _original_print("[UPSTOX] ⚠️ Incomplete credentials - missing access_token", flush=True)
                else:
                    _original_print("[UPSTOX] No credentials configured - broker disabled", flush=True)
            else:
                _original_print("[UPSTOX] UpstoxBroker not available (upstox-python-sdk not installed)", flush=True)
        except Exception as e:
            _original_print(f"[UPSTOX] ⚠️ Initialization failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.upstox_broker = None

        # Initialize Zerodha broker (India - Kite Connect API - Always LIVE)
        self.zerodha_broker = None
        try:
            if ZERODHA_AVAILABLE:
                _original_print("[ZERODHA] Starting broker initialization...", flush=True)
                _original_print("[ZERODHA] ⚠️ WARNING: Zerodha has NO paper trading mode - ALL trades are LIVE", flush=True)
                
                from gui_app.database import get_broker_credentials
                zerodha_creds = get_broker_credentials('zerodha')
                
                if zerodha_creds and zerodha_creds.get('credentials'):
                    creds = zerodha_creds.get('credentials', {})
                    zerodha_api_key = creds.get('api_key', '')
                    zerodha_api_secret = creds.get('api_secret', '')
                    zerodha_access_token = creds.get('access_token', '')
                    zerodha_request_token = creds.get('request_token', '')
                    
                    has_access_token = bool(zerodha_access_token)
                    has_request_token_flow = bool(zerodha_request_token and zerodha_api_secret)
                    
                    if zerodha_api_key and (has_access_token or has_request_token_flow):
                        _original_print(f"[ZERODHA] ✓ Loaded credentials from DATABASE", flush=True)
                        if has_access_token:
                            _original_print(f"[ZERODHA]   Using access_token flow", flush=True)
                        else:
                            _original_print(f"[ZERODHA]   Using request_token+api_secret flow", flush=True)
                        _original_print(f"[ZERODHA] Creating ZerodhaBroker instance...", flush=True)
                        
                        self.zerodha_broker = ZerodhaBroker({
                            'api_key': zerodha_api_key,
                            'api_secret': zerodha_api_secret,
                            'access_token': zerodha_access_token,
                            'request_token': zerodha_request_token
                        })
                        
                        connected = await self.zerodha_broker.connect()
                        if connected:
                            _original_print(f"[ZERODHA] ✓ Connected successfully (LIVE trading)", flush=True)
                            try:
                                from gui_app.database import update_broker_connection_status, save_broker_credentials
                                update_broker_connection_status('zerodha', True, f"Connected - API Key: {zerodha_api_key[:8]}...")
                                _original_print(f"[ZERODHA] ✓ Broker status updated in GUI", flush=True)
                                
                                if self.zerodha_broker.kite and hasattr(self.zerodha_broker.kite, 'access_token'):
                                    new_access_token = self.zerodha_broker.kite.access_token
                                    if new_access_token and new_access_token != zerodha_access_token:
                                        updated_creds = {
                                            'api_key': zerodha_api_key,
                                            'api_secret': zerodha_api_secret,
                                            'access_token': new_access_token
                                        }
                                        save_broker_credentials('zerodha', updated_creds)
                                        _original_print(f"[ZERODHA] ✓ New access token persisted (request_token cleared - it's one-time use)", flush=True)
                            except Exception as status_err:
                                _original_print(f"[ZERODHA] ⚠️ Failed to update broker status: {status_err}", flush=True)
                        else:
                            _original_print("[ZERODHA] ⚠️ Connection failed - token may be expired", flush=True)
                            _original_print("[ZERODHA]   Go to Settings → Brokers → Zerodha to update access token", flush=True)
                            from gui_app.database import update_broker_connection_status
                            update_broker_connection_status('zerodha', False, 'Connection failed - token may be expired')
                            self.zerodha_broker = None
                    else:
                        _original_print("[ZERODHA] ⚠️ Incomplete credentials - need api_key + (access_token OR request_token+api_secret)", flush=True)
                        from gui_app.database import update_broker_connection_status
                        update_broker_connection_status('zerodha', False, 'Incomplete credentials - need api_key + (access_token OR request_token+api_secret)')
                else:
                    _original_print("[ZERODHA] No credentials configured - broker disabled", flush=True)
            else:
                _original_print("[ZERODHA] ZerodhaBroker not available (kiteconnect not installed)", flush=True)
                from gui_app.database import update_broker_connection_status
                update_broker_connection_status('zerodha', False, 'kiteconnect library not installed')
        except Exception as e:
            _original_print(f"[ZERODHA] ⚠️ Initialization failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.zerodha_broker = None

        # Initialize Charles Schwab broker (OAuth2 API)
        self.schwab_broker = None
        try:
            _original_print("[SCHWAB] Starting broker initialization...", flush=True)
            
            from gui_app.broker_credentials_service import get_schwab_credentials
            from src.brokers.schwab_broker import SchwabBroker
            
            schwab_creds = get_schwab_credentials()
            
            if schwab_creds and schwab_creds.get('client_id') and schwab_creds.get('client_secret'):
                _original_print(f"[SCHWAB] ✓ Loaded credentials from DATABASE", flush=True)
                
                self.schwab_broker = SchwabBroker({
                    'client_id': schwab_creds.get('client_id'),
                    'client_secret': schwab_creds.get('client_secret'),
                    'redirect_uri': schwab_creds.get('redirect_uri', 'https://127.0.0.1'),
                    'dry_run': schwab_creds.get('dry_run', True)
                })
                
                connected = await self.schwab_broker.connect()
                if connected:
                    mode = "PAPER" if schwab_creds.get('dry_run', True) else "LIVE"
                    _original_print(f"[SCHWAB] ✓ Connected successfully ({mode})", flush=True)
                    try:
                        from gui_app.database import update_broker_connection_status
                        account_info = await self.schwab_broker.get_account_info()
                        update_broker_connection_status('schwab', True, f"Connected - Account: {self.schwab_broker.account_number}")
                        buying_power = account_info.get('buying_power', 0)
                        if buying_power > 0:
                            _original_print(f"[SCHWAB]   Buying Power: ${buying_power:,.2f}", flush=True)
                        _original_print(f"[SCHWAB] ✓ Broker status updated in GUI", flush=True)
                    except Exception as status_err:
                        _original_print(f"[SCHWAB] ⚠️ Failed to update broker status: {status_err}", flush=True)
                else:
                    _original_print("[SCHWAB] ⚠️ Not authenticated - click 'Connect with Schwab' in Settings", flush=True)
                    self.schwab_broker = None
            else:
                _original_print("[SCHWAB] No credentials configured - broker disabled", flush=True)
        except Exception as e:
            _original_print(f"[SCHWAB] ⚠️ Initialization failed: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self.schwab_broker = None

        # CRITICAL: Set broker_ready if ANY broker is available (not just Webull)
        # This fixes user builds where only Alpaca/Tastytrade are configured
        if not self.broker_ready.is_set():
            any_broker_available = (
                (self.broker and getattr(self.broker, 'is_logged_in', False)) or
                self.paper_broker or
                self.tastytrade_broker or
                self.robinhood_broker or
                self.ibkr_broker or
                self.dhanq_broker or
                self.upstox_broker or
                self.zerodha_broker or
                self.schwab_broker
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
                    def __init__(self, webull_broker, alpaca_paper_broker, tastytrade_broker=None, robinhood_broker=None, ibkr_broker=None, dhanq_broker=None, upstox_broker=None, zerodha_broker=None, schwab_broker=None):
                        self.webull_broker = webull_broker
                        self.alpaca_paper_broker = alpaca_paper_broker
                        self.tastytrade_broker = tastytrade_broker
                        self.robinhood_broker = robinhood_broker
                        self.ibkr_broker = ibkr_broker
                        self.dhanq_broker = dhanq_broker
                        self.upstox_broker = upstox_broker
                        self.zerodha_broker = zerodha_broker
                        self.schwab_broker = schwab_broker
                
                broker_manager = BrokerManager(self.broker, self.paper_broker, self.tastytrade_broker, self.robinhood_broker, self.ibkr_broker, self.dhanq_broker, self.upstox_broker, self.zerodha_broker, self.schwab_broker)
                
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
        
        telegram_bridge_task = asyncio.create_task(self.telegram_signal_bridge())
        await asyncio.sleep(0)
        
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
                    schwab_broker=self.schwab_broker,
                    loop=self.loop
                )
                
                # Start monitoring as async task
                self.loop.create_task(self.risk_manager.start_monitoring())
                print("[RISK] ✓ RiskManager module initialized")
                
                # Link risk manager to sync service for pending order reconciliation
                if hasattr(self, 'sync_service') and self.sync_service:
                    self.sync_service.set_risk_manager(self.risk_manager)
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
        
        # Initialize Signal Verification Service with real-time broker data
        try:
            from src.services.signal_verification import set_broker_clients
            webull_client = getattr(self.broker, 'wb', None) if self.broker else None
            tastytrade_session = getattr(self.tastytrade_broker, 'session', None) if self.tastytrade_broker else None
            alpaca_broker = self.paper_broker if self.paper_broker and hasattr(self.paper_broker, 'connected') and self.paper_broker.connected else None
            schwab_broker = None
            if self.schwab_broker and hasattr(self.schwab_broker, 'is_authenticated'):
                try:
                    is_auth = await self.schwab_broker.is_authenticated()
                    if is_auth:
                        schwab_broker = self.schwab_broker
                except Exception:
                    pass
            set_broker_clients(
                webull_client=webull_client, 
                tastytrade_session=tastytrade_session,
                alpaca_broker=alpaca_broker,
                schwab_broker=schwab_broker
            )
        except Exception as e:
            print(f"[VERIFY] ⚠️ Could not initialize real-time verification: {e}")
    
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
    
    async def handle_extract_history(self, message: discord.Message, channel_id: int, limit: int = 200):
        """Extract and analyze message history from a channel for pattern discovery."""
        try:
            await message.channel.send(f"📊 Extracting last {limit} messages from channel {channel_id}...")
            
            target_channel = self.get_channel(channel_id)
            if not target_channel:
                try:
                    target_channel = await self.fetch_channel(channel_id)
                except Exception as e:
                    await message.channel.send(f"❌ Cannot access channel {channel_id}: {e}")
                    return
            
            messages = []
            entries = []
            exits = []
            partial_exits = []
            
            async for msg in target_channel.history(limit=limit):
                embed_text = ""
                if msg.embeds:
                    for embed in msg.embeds:
                        parts = []
                        if embed.title:
                            parts.append(f"[TITLE:{embed.title}]")
                        if embed.description:
                            parts.append(f"[DESC:{embed.description}]")
                        for field in embed.fields:
                            parts.append(f"[{field.name}:{field.value}]")
                        embed_text = " ".join(parts)
                
                full_content = f"{msg.content} {embed_text}".strip()
                
                # Classify message type
                content_lower = full_content.lower()
                if any(x in content_lower for x in ["i'm entering", "im entering", "option:", "entry:"]):
                    entries.append(full_content)
                elif any(x in content_lower for x in ["trimming", "trim", "partial", "half", "50%", "25%", "75%"]):
                    partial_exits.append(full_content)
                elif any(x in content_lower for x in ["out", "exit", "close", "sold", "stc"]):
                    exits.append(full_content)
                
                messages.append(full_content)
                print(f"[HISTORY] {msg.created_at.strftime('%m-%d %H:%M')}: {full_content[:200]}")
            
            # Build analysis report
            report = f"📊 **Channel Analysis: {target_channel.name}**\n"
            report += f"Analyzed: {len(messages)} messages\n\n"
            
            report += f"**ENTRIES FOUND ({len(entries)}):**\n"
            for e in entries[:5]:
                report += f"• `{e[:100]}`\n"
            
            report += f"\n**PARTIAL EXITS ({len(partial_exits)}):**\n"
            for p in partial_exits[:5]:
                report += f"• `{p[:100]}`\n"
            
            report += f"\n**FULL EXITS ({len(exits)}):**\n"
            for x in exits[:5]:
                report += f"• `{x[:100]}`\n"
            
            # Log full details to console
            print("\n" + "="*80)
            print("FULL ENTRY PATTERNS:")
            for e in entries:
                print(f"  {e}")
            print("\nFULL PARTIAL EXIT PATTERNS:")
            for p in partial_exits:
                print(f"  {p}")
            print("\nFULL EXIT PATTERNS:")
            for x in exits:
                print(f"  {x}")
            print("="*80 + "\n")
            
            await message.channel.send(report[:1900])
            
        except Exception as e:
            await message.channel.send(f"❌ Error extracting history: {e}")
            import traceback
            traceback.print_exc()
    
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
        Normalize signal text by removing invisible unicode characters,
        markdown formatting, and standardizing punctuation for reliable regex parsing.
        
        Handles: markdown (**bold**, _italic_, __underline__), zero-width joiners, 
        RTL/LTR marks, unicode dashes/colons, fullwidth characters, and other 
        problematic invisible formatting.
        """
        import unicodedata
        import re as re_local
        
        if not text:
            return text
        
        # Strip markdown formatting: **bold**, *italic*, __underline__, _italic_, ~~strikethrough~~
        text = re_local.sub(r'\*\*(.+?)\*\*', r'\1', text)  # **bold**
        text = re_local.sub(r'\*(.+?)\*', r'\1', text)      # *italic*
        text = re_local.sub(r'__(.+?)__', r'\1', text)      # __underline__
        text = re_local.sub(r'_(.+?)_', r'\1', text)        # _italic_
        text = re_local.sub(r'~~(.+?)~~', r'\1', text)      # ~~strikethrough~~
        text = re_local.sub(r'`(.+?)`', r'\1', text)        # `code`
        
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
        # Guard against duplicate on_ready calls (Discord reconnects can trigger this multiple times)
        if self._on_ready_completed:
            print("[Discord] Reconnected - skipping duplicate on_ready initialization")
            return
        
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
            print(f"[STARTUP] Trade Monitor settings: {monitor_settings}", flush=True)
            if monitor_settings.get('enabled'):
                trade_monitor = get_trade_monitor()
                print(f"[STARTUP] Trade Monitor instance: {trade_monitor}, broker: {self.broker is not None}", flush=True)
                if self.broker:
                    trade_monitor.set_broker(self.broker)
                    print(f"[STARTUP] Broker set, calling trade_monitor.start()...", flush=True)
                    try:
                        await trade_monitor.start()
                        print("[STARTUP] ✓ Trade Monitor start() completed", flush=True)
                    except Exception as start_err:
                        print(f"[STARTUP] ❌ Trade Monitor start() failed: {start_err}", flush=True)
                        import traceback
                        traceback.print_exc()
                    print("[STARTUP] ✓ Trade Monitor started - syncing broker trades to Discord", flush=True)
                else:
                    print("[STARTUP] ⚠️  Trade Monitor enabled but no broker connected", flush=True)
            else:
                print("[STARTUP] Trade Monitor disabled (enable in Settings)", flush=True)
        except Exception as e:
            import traceback
            print(f"[STARTUP] Warning: Could not start Trade Monitor: {e}", flush=True)
            traceback.print_exc()
        
        # Start Conditional Order Service if enabled (using market-isolated router)
        try:
            from src.services.conditional_orders.router import conditional_order_router
            
            if conditional_order_router.is_enabled():
                # Register broker instances - router auto-routes to correct market service
                # US Brokers
                if self.broker:
                    conditional_order_router.set_broker_instance('Webull', self.broker)
                    print("[STARTUP] ✓ Webull registered for US conditional order monitoring", flush=True)
                if hasattr(self, 'paper_broker') and self.paper_broker:
                    conditional_order_router.set_broker_instance('Alpaca', self.paper_broker)
                    print("[STARTUP] ✓ Alpaca registered for US conditional order monitoring", flush=True)
                # India Brokers
                if hasattr(self, 'upstox_broker') and self.upstox_broker:
                    conditional_order_router.set_broker_instance('upstox', self.upstox_broker)
                    print("[STARTUP] ✓ Upstox registered for INDIA conditional order monitoring", flush=True)
                if hasattr(self, 'dhanq_broker') and self.dhanq_broker:
                    conditional_order_router.set_broker_instance('dhanq', self.dhanq_broker)
                    print("[STARTUP] ✓ DhanQ registered for INDIA conditional order monitoring", flush=True)
                if hasattr(self, 'zerodha_broker') and self.zerodha_broker:
                    conditional_order_router.set_broker_instance('zerodha', self.zerodha_broker)
                    print("[STARTUP] ✓ Zerodha registered for INDIA conditional order monitoring", flush=True)
                # Canada Brokers  
                if hasattr(self, 'questrade_broker') and self.questrade_broker:
                    conditional_order_router.set_broker_instance('questrade', self.questrade_broker)
                    print("[STARTUP] ✓ Questrade registered for CANADA conditional order monitoring", flush=True)
                
                # Use the global sync signal queue (same as Telegram) for thread-safe handoff
                global _telegram_signal_queue
                
                # Set up async execution callback
                async def execute_conditional_order(order, triggered_price):
                    """Execute a triggered conditional order using sync signal queue."""
                    import sys
                    global _telegram_signal_queue
                    try:
                        sys.stderr.write(f"[CONDITIONAL EXEC] Starting execution for order: {order.get('id')}\n")
                        sys.stderr.flush()
                        symbol = order['symbol']
                        broker_name = order.get('broker_primary', 'Webull')
                        market = order.get('market', 'US')
                        currency = '₹' if market == 'INDIA' else '$'
                        option_info = f" {order.get('strike')}{order.get('opt_type')}" if order.get('strike') else ""
                        sys.stderr.write(f"[CONDITIONAL EXEC] Executing order #{order['id']}: {symbol}{option_info} @ {currency}{triggered_price:.2f}\n")
                        sys.stderr.flush()
                        
                        # Build a BTO signal from the conditional order
                        signal = {
                            'asset': order.get('asset_type', 'stock'),
                            'action': 'BTO',
                            'symbol': symbol,
                            'price': triggered_price,
                            'is_market_order': True,
                            '_conditional_order_id': order['id'],
                            '_broker_override': broker_name,
                            'channel_id': order.get('channel_id'),  # Critical for RiskManager tracking
                        }
                        
                        # Handle Indian options orders
                        if market == 'INDIA':
                            signal['market'] = 'INDIA'
                            signal['asset'] = 'option'
                            signal['asset_type'] = 'option'
                            if order.get('strike'):
                                signal['strike'] = order['strike']
                            if order.get('opt_type'):
                                signal['opt_type'] = order['opt_type']
                                signal['call_put'] = order['opt_type']
                            if order.get('expiry'):
                                signal['expiry'] = order['expiry']
                            if order.get('lot_size'):
                                signal['lot_size'] = order['lot_size']
                            if order.get('lots'):
                                signal['lots'] = order['lots']
                            signal['exchange_segment'] = 'NSE_FNO'
                        
                        # Add position sizing
                        size_mode = order.get('size_mode')
                        if size_mode == 'percent_account':
                            signal['_position_size_pct'] = order.get('qty_value')
                            signal['_calculate_qty'] = True
                            signal['qty'] = 1  # Default qty, will be replaced by position sizing calculation
                        elif size_mode == 'fixed_qty':
                            signal['qty'] = int(order.get('qty_value', 1))
                        else:
                            # Use calculated_qty from order if available
                            calculated = order.get('calculated_qty')
                            if calculated:
                                signal['qty'] = int(calculated)
                            elif market == 'INDIA' and order.get('lots'):
                                signal['qty'] = int(order['lots'])
                            else:
                                signal['qty'] = 1
                        
                        # Add stop loss and profit targets
                        import json
                        from gui_app.database import get_channel_by_discord_id
                        
                        has_signal_sl = bool(order.get('stop_loss_value'))
                        has_signal_targets = bool(order.get('take_profit_targets'))
                        
                        channel_id = order.get('channel_id')
                        channel_settings = None
                        if channel_id and (not has_signal_sl or not has_signal_targets):
                            channel_settings = get_channel_by_discord_id(str(channel_id))
                        
                        # Stop Loss: Signal value first, then channel settings
                        # Hybrid SL: Both fixed price AND percentage (whichever triggers first)
                        sl_type = order.get('stop_loss_type')
                        has_hybrid_sl = sl_type == 'hybrid' or (order.get('stop_loss_fixed') and order.get('stop_loss_pct'))
                        
                        if has_hybrid_sl:
                            # Hybrid SL: set both price and percentage - risk manager uses whichever triggers first
                            sl_fixed = order.get('stop_loss_fixed') or order.get('stop_loss_value')
                            sl_pct = order.get('stop_loss_pct')
                            if sl_fixed:
                                signal['stop_loss_price'] = sl_fixed
                            if sl_pct:
                                signal['stop_loss_pct'] = sl_pct
                            signal['_hybrid_sl'] = True
                            print(f"[CONDITIONAL] Using HYBRID SL: ${sl_fixed} or {sl_pct}%", flush=True)
                        elif has_signal_sl:
                            if sl_type == 'percent':
                                sl_pct = order['stop_loss_value']
                                signal['stop_loss_pct'] = sl_pct
                                # Calculate actual stop loss price from percentage
                                sl_price = triggered_price * (1 - sl_pct / 100)
                                signal['stop_loss_price'] = round(sl_price, 2)
                                print(f"[CONDITIONAL] Using signal SL: {sl_pct}% = ${signal['stop_loss_price']:.2f} (entry: ${triggered_price:.2f})", flush=True)
                            else:
                                signal['stop_loss_price'] = order['stop_loss_value']
                                print(f"[CONDITIONAL] Using signal SL: ${order['stop_loss_value']}", flush=True)
                        elif channel_settings and channel_settings.get('stop_loss_pct'):
                            ch_sl_pct = channel_settings['stop_loss_pct']
                            signal['stop_loss_pct'] = ch_sl_pct
                            # Calculate actual stop loss price from channel percentage
                            ch_sl_price = triggered_price * (1 - ch_sl_pct / 100)
                            signal['stop_loss_price'] = round(ch_sl_price, 2)
                            print(f"[CONDITIONAL] Using channel SL: {ch_sl_pct}% = ${signal['stop_loss_price']:.2f}", flush=True)
                        
                        # Profit Targets: Signal values first, then channel settings
                        if has_signal_targets:
                            raw_targets = order['take_profit_targets']
                            targets = None
                            if isinstance(raw_targets, str):
                                # Try JSON first, then comma-separated
                                try:
                                    targets = json.loads(raw_targets)
                                except json.JSONDecodeError:
                                    # Parse comma-separated string: "172.0,190.0,220.0"
                                    targets = [float(t.strip()) for t in raw_targets.split(',') if t.strip()]
                            elif isinstance(raw_targets, list):
                                targets = raw_targets
                            elif raw_targets is not None:
                                targets = [float(raw_targets)]
                            
                            # Ensure targets is a list
                            if targets is not None:
                                if not isinstance(targets, list):
                                    targets = [targets]  # Convert single value to list
                                if len(targets) > 0:
                                    signal['profit_target_price'] = targets[0]
                                    signal['profit_targets'] = targets
                                    sys.stderr.write(f"[CONDITIONAL EXEC] Using signal targets: {targets}\n")
                                    sys.stderr.flush()
                        elif channel_settings:
                            channel_targets_pct = []
                            for i in range(1, 5):
                                pct = channel_settings.get(f'profit_target_{i}_pct')
                                if pct:
                                    channel_targets_pct.append(pct)
                            if channel_targets_pct:
                                # Convert percentage targets to actual prices
                                channel_targets_price = [round(triggered_price * (1 + pct / 100), 2) for pct in channel_targets_pct]
                                signal['profit_target_pct'] = channel_targets_pct[0]
                                signal['profit_targets_pct'] = channel_targets_pct
                                signal['profit_target_price'] = channel_targets_price[0]
                                signal['profit_targets'] = channel_targets_price
                                print(f"[CONDITIONAL] Using channel targets: {channel_targets_pct}% = ${channel_targets_price}", flush=True)
                        
                        # Trailing Stop: Always from channel settings
                        if channel_settings:
                            if channel_settings.get('trailing_stop_pct'):
                                signal['trailing_stop_pct'] = channel_settings['trailing_stop_pct']
                                print(f"[CONDITIONAL] Trailing stop: {channel_settings['trailing_stop_pct']}%", flush=True)
                            if channel_settings.get('trailing_activation_pct'):
                                signal['trailing_activation_pct'] = channel_settings['trailing_activation_pct']
                            if channel_settings.get('leave_runner_enabled'):
                                signal['leave_runner'] = True
                                signal['leave_runner_pct'] = channel_settings.get('leave_runner_pct', 25)
                        
                        # Use sync signal queue (thread-safe, same as Telegram)
                        sys.stderr.write(f"[CONDITIONAL EXEC] Checking sync queue: {_telegram_signal_queue is not None}\n")
                        sys.stderr.flush()
                        if _telegram_signal_queue is not None:
                            _telegram_signal_queue.put_nowait(signal)
                            sys.stderr.write(f"[CONDITIONAL EXEC] ✓ Signal queued via sync queue: {symbol}{option_info} @ {currency}{triggered_price:.2f}\n")
                            sys.stderr.flush()
                            return True
                        else:
                            sys.stderr.write(f"[CONDITIONAL EXEC] ❌ Sync signal queue not available!\n")
                            sys.stderr.flush()
                            return False
                        
                    except Exception as e:
                        sys.stderr.write(f"[CONDITIONAL EXEC] ❌ Execution error: {e}\n")
                        sys.stderr.flush()
                        import traceback
                        traceback.print_exc()
                        return False
                
                import asyncio as aio_module
                main_loop = aio_module.get_event_loop()
                conditional_order_router.set_execution_callback(execute_conditional_order, main_loop)
                print(f"[STARTUP] Starting market-isolated conditional order services...", flush=True)
                conditional_order_router.start()
                status = conditional_order_router.get_market_status()
                print(f"[STARTUP] ✓ Conditional Order Router started", flush=True)
                for market, mstatus in status.items():
                    print(f"[STARTUP]   {market}: running={mstatus['running']}, brokers={mstatus['registered_brokers']}", flush=True)
            else:
                print("[STARTUP] Conditional Order Service disabled (enable in Settings)")
        except ImportError as e:
            print(f"[STARTUP] ⚠️ Conditional Order Service not available: {e}")
        except Exception as e:
            print(f"[STARTUP] Warning: Could not start Conditional Order Service: {e}")
        
        # Signal ready event for thread synchronization (if available)
        try:
            global _discord_ready_event
            if _discord_ready_event:
                _discord_ready_event.set()
                print("[Discord] ✓ Bot ready event signaled")
        except Exception:
            pass  # Event not needed in non-threaded mode
        
        # Mark on_ready as completed to prevent duplicate initialization on reconnects
        self._on_ready_completed = True
    
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
        # FIRST: Deduplicate messages BEFORE any processing (Discord self-bot sometimes delivers duplicate events)
        # Ensure lock exists (create if needed)
        if not self._message_dedupe_lock:
            self._message_dedupe_lock = asyncio.Lock()
        
        # Check-and-add atomically using lock to prevent race condition
        async with self._message_dedupe_lock:
            if message.id in self._processed_messages:
                return  # Silent skip for duplicates
            self._processed_messages.add(message.id)
        
        # Limit cache size to prevent memory growth (do this after dedupe check)
        if len(self._processed_messages) > self._max_processed_cache:
            to_remove = list(self._processed_messages)[:self._max_processed_cache // 2]
            for msg_id in to_remove:
                self._processed_messages.discard(msg_id)
        
        # Check database for channel info (dual-mode support)
        channel_info = self._get_channel_info(message.channel.id)
        channel_category = channel_info['category'] if channel_info else None
        execute_enabled = channel_info.get('execute_enabled', 0) if channel_info else False
        track_enabled = channel_info.get('track_enabled', 0) if channel_info else False
        
        # Check if this channel is a source in channel mappings (multi-channel conversion)
        # Use the new mapping config to get full routing configuration
        is_mapped_source_channel = False
        mapping_config = None  # Will hold forward_enabled, execute_on_source, format_as_bto_stc
        if DATABASE_MODULE_AVAILABLE:
            try:
                from gui_app import database as db
                mapping_config = db.get_mapping_config_for_source(str(message.channel.id))
                if mapping_config:
                    is_mapped_source_channel = True
                    print(f"[Discord] ✓ Channel mapped: forward={mapping_config['forward_enabled']}, execute={mapping_config['execute_on_source']}, format_bto_stc={mapping_config['format_as_bto_stc']}")
            except Exception as e:
                pass
        
        # If not in database, not in legacy CHANNEL_IDS list, AND not a mapped source, ignore
        if not channel_info and message.channel.id not in CHANNEL_IDS and not is_mapped_source_channel:
            return
        
        print(f"[Discord] Processing message ID: {message.id}")
        print(f"[DEBUG] Author: {message.author.name} (ID: {message.author.id}), Channel: {message.channel.id}")
        
        # Add message to sentiment analyzer if enabled
        if self.sentiment_analyzer and not message.author.bot:
            self.sentiment_analyzer.add_message(message.content)
        
        # Handle webhook messages - conditionally allow based on ALLOW_SELF_MESSAGES setting
        # When ALLOW_SELF_MESSAGES is True, webhook messages from monitored channels are processed
        # This enables testing via webhooks and automation while still preventing Trade Monitor loops
        print(f"[DEBUG] Checking webhook: has_attr={hasattr(message, 'webhook_id')}, webhook_id={getattr(message, 'webhook_id', None)}")
        is_webhook_message = hasattr(message, 'webhook_id') and message.webhook_id
        if is_webhook_message:
            if ALLOW_SELF_MESSAGES:
                print(f"[DEBUG] ✓ Webhook message ALLOWED - ALLOW_SELF_MESSAGES is True")
            else:
                print(f"[SKIP] Webhook message from {message.author.name} - ALLOW_SELF_MESSAGES is False")
                return
        
        # Skip bot's own response messages SECOND (before any logging)
        # This prevents the bot from processing its own 🤖/📊/❌ messages
        print(f"[DEBUG] Checking self-message: self.user={self.user.id if self.user else None}, author={message.author.id}")
        is_self_message = self.user and message.author.id == self.user.id
        if is_self_message:
            content_preview = message.content.strip()[:50]
            print(f"[DEBUG] Self-message detected: '{content_preview}' | ALLOW_SELF_MESSAGES={ALLOW_SELF_MESSAGES}")
            if content_preview.startswith(('🤖', '📊', '💡', '❌', '⚠️', '📰', 'pong')):
                print(f"[Discord] ⏭️ Skipping own bot response: {content_preview}...")
                return
            elif not ALLOW_SELF_MESSAGES:
                print(f"[Discord] ⏭️ YOUR message ignored! Enable 'Allow Self Messages' in Settings to test")
                print(f"[Discord]    Content: {content_preview}...")
                return
            else:
                print(f"[DEBUG] ✓ Self-message ALLOWED - continuing to process")

        # Now log only messages from monitored channels
        channel_name = getattr(message.channel, 'name', str(message.channel.id))
        print(f"\n[Discord] 📨 Channel:{message.channel.id} ({channel_name}) Author:{message.author.name}")
        print(f"[Discord] Content: {message.content[:150]}")
        
        # EMBED EXTRACTION: Extract text from Discord embeds (for signals like Bishop format)
        # Many trading signals are posted in embeds rather than plain message content
        embed_content_parts = []
        if hasattr(message, 'embeds') and message.embeds:
            for embed in message.embeds:
                if embed.title:
                    embed_content_parts.append(embed.title)
                if embed.description:
                    embed_content_parts.append(embed.description)
                for field in embed.fields:
                    if field.name and field.value:
                        embed_content_parts.append(f"{field.name}: {field.value}")
            if embed_content_parts:
                print(f"[Discord] Embed content: {' | '.join(embed_content_parts)[:200]}")
        
        # Create combined content for signal parsing (message.content + embed text)
        # This allows parsers to match patterns in embed title/description/fields
        combined_content = message.content
        if embed_content_parts:
            combined_content = message.content + "\n" + "\n".join(embed_content_parts)
        if ALLOWED_AUTHOR_IDS and message.author.id not in ALLOWED_AUTHOR_IDS:
            print(f"[SKIP] Author {message.author.id} not in allowed list")
            return
        
        if ALLOWED_GUILD_IDS and hasattr(message, 'guild') and message.guild:
            if message.guild.id not in ALLOWED_GUILD_IDS:
                print(f"[SKIP] Guild {message.guild.id} not in allowed list")
                return
        
        # Check channel-specific allowed users (if configured)
        # Skip this check for self-messages and webhook messages when ALLOW_SELF_MESSAGES is enabled
        if channel_info and DATABASE_MODULE_AVAILABLE:
            try:
                from gui_app import database as db
                channel_internal_id = channel_info.get('id')
                if channel_internal_id:
                    # Self-messages and webhook messages bypass the per-channel user filter when ALLOW_SELF_MESSAGES is True
                    if is_self_message and ALLOW_SELF_MESSAGES:
                        print(f"[DEBUG] Self-message bypasses per-channel user filter")
                    elif is_webhook_message and ALLOW_SELF_MESSAGES:
                        print(f"[DEBUG] Webhook message bypasses per-channel user filter")
                    else:
                        is_allowed = db.is_user_allowed(channel_internal_id, str(message.author.id))
                        if not is_allowed:
                            print(f"[SKIP] Author {message.author.name} (ID:{message.author.id}) not in channel's allowed user list")
                            return
            except Exception as e:
                print(f"[WARN] Failed to check allowed users: {e}")

        # Store message for format discovery (after all eligibility checks pass)
        # For mapped source channels, store full combined_content (includes embeds)
        if channel_info and DATABASE_MODULE_AVAILABLE:
            try:
                from gui_app import database as db
                # Use combined_content for storage to capture embed data
                storage_content = combined_content if embed_content_parts else message.content
                db.save_channel_message(
                    channel_id=str(message.channel.id),
                    message_content=storage_content,
                    channel_name=channel_name,
                    author_id=str(message.author.id),
                    author_name=message.author.name,
                    message_id=str(message.id)
                )
                # Enhanced logging for analysis channels (Bishop, etc.)
                if str(message.channel.id) in ['1239624229583061052']:
                    print(f"[BISHOP-LOG] Full content: {storage_content[:500]}")
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
        
        # Use the mapping_config we already fetched at the start
        print(f"[DEBUG] is_mapped_source_channel={is_mapped_source_channel}, DATABASE_MODULE_AVAILABLE={DATABASE_MODULE_AVAILABLE}")
        destination_type = None
        dest_channel_id = None
        if is_mapped_source_channel and mapping_config:
            destination_type = mapping_config.get('destination_type', 'webhook')
            webhook_url = mapping_config.get('webhook_url', '')
            dest_channel_id = mapping_config.get('destination_channel_id', '')
            print(f"[DEBUG] destination_type={destination_type}, webhook_url={webhook_url}, dest_channel_id={dest_channel_id}")
            
            if destination_type == 'webhook' and webhook_url:
                print(f"[CHANNEL MAP] ✓ Source {message.channel.id} mapped to webhook")
                active_conversion_channel_id = message.channel.id
                target_execution_channel_id = webhook_url
            elif destination_type == 'channel' and dest_channel_id:
                print(f"[CHANNEL MAP] ✓ Source {message.channel.id} mapped to channel {dest_channel_id}")
                active_conversion_channel_id = message.channel.id
                target_execution_channel_id = dest_channel_id
            else:
                print(f"[DEBUG] No valid destination configured")
        
        print(f"[DEBUG] target_execution_channel_id={target_execution_channel_id}")
        
        if not is_mapped_source_channel and DATABASE_MODULE_AVAILABLE:
            from gui_app import database as db
            # Fall back to single conversion channel settings
            conversion_settings = db.get_signal_conversion_settings()
            db_conversion_channel_id = conversion_settings.get('conversion_channel_id', '').strip()
            if db_conversion_channel_id:
                active_conversion_channel_id = int(db_conversion_channel_id)
            target_execution_channel_id = conversion_settings.get('target_execution_channel_id', '').strip()
        
        # Check if this is a mapped source channel OR the single conversion channel
        should_convert = (is_mapped_source_channel or 
                         (ENABLE_SIGNAL_CONVERSION and active_conversion_channel_id and message.channel.id == active_conversion_channel_id))
        
        print(f"[DEBUG] should_convert={should_convert}, starts_with_bang={message.content.strip().startswith('!')}")
        
        if should_convert:
            # Don't process commands, only natural language text
            if not message.content.strip().startswith('!'):
                # Check if this is a BTO/STC signal - if so, skip webhook forwarding and let it go to trade execution
                content_upper = combined_content.strip().upper()
                # Check for standard BTO/STC signals
                is_bto_stc_signal = content_upper.startswith('BTO ') or content_upper.startswith('STC ') or ' BTO ' in content_upper or ' STC ' in content_upper
                # Also check for Bishop format: "I'm Entering" + "Option:" or "Trimming"
                is_bishop_signal = ("I'M ENTERING" in content_upper and "OPTION:" in content_upper) or "TRIMMING " in content_upper
                # Combine all signal checks
                is_bto_stc_signal = is_bto_stc_signal or is_bishop_signal
                
                # DUAL-ACTION ROUTING: Check if we should execute on broker AND/OR forward to webhook
                should_execute = False
                should_forward = True  # Default behavior
                format_as_bto_stc = True  # Default behavior
                
                if mapping_config:
                    should_execute = mapping_config.get('execute_on_source', False)
                    should_forward = mapping_config.get('forward_enabled', True)
                    format_as_bto_stc = mapping_config.get('format_as_bto_stc', True)
                    print(f"[DUAL-ACTION] Config: execute={should_execute}, forward={should_forward}, bto_stc={format_as_bto_stc}")
                
                # Check for Bullwinkle format (needs emoji stripping)
                from src.signals.parser import (
                    is_bullwinkle_signal, parse_bullwinkle_signal, 
                    strip_bullwinkle_emojis, format_bullwinkle_for_webhook,
                    is_bracket_order_signal, parse_bracket_order_signal,
                    is_jacob_signal, parse_jacob_signal, format_jacob_for_webhook,
                    is_zscalps_signal, parse_zscalps_signal
                )
                is_bullwinkle = is_bullwinkle_signal(combined_content)
                is_bracket_order = is_bracket_order_signal(combined_content)
                is_jacob = is_jacob_signal(combined_content)
                is_zscalps = is_zscalps_signal(combined_content)
                
                if is_bto_stc_signal or is_bullwinkle or is_jacob or is_zscalps:
                    print(f"[DEBUG] BTO/STC or Bullwinkle signal detected - will process for trade execution")
                    
                    is_webhook_dest = destination_type == 'webhook' and target_execution_channel_id and target_execution_channel_id.startswith('https://')
                    is_channel_dest = destination_type == 'channel' and dest_channel_id
                    print(f"[DEBUG] should_forward={should_forward}, is_webhook_dest={is_webhook_dest}, is_channel_dest={is_channel_dest}")
                    
                    # DUAL-ACTION for BTO/STC: Forward FIRST (if enabled), then execute (if enabled)
                    if should_forward and (is_webhook_dest or is_channel_dest):
                        import sys
                        print(f"[DEBUG] Entering forward block (type={destination_type})...", flush=True)
                        # Prepare message for forwarding - convert to BTO/STC format when enabled
                        print(f"[DEBUG] is_bullwinkle={is_bullwinkle}, is_zscalps={is_zscalps}, format_as_bto_stc={format_as_bto_stc}", flush=True)
                        if is_zscalps:
                            print(f"[DEBUG] Taking ZSCALPS path", flush=True)
                            zscalps_parsed = parse_zscalps_signal(combined_content)
                            if zscalps_parsed:
                                # Format as BTO/STC
                                action = zscalps_parsed.get('action', 'BTO')
                                symbol = zscalps_parsed.get('symbol', '')
                                price = zscalps_parsed.get('price')
                                if action == 'BTO':
                                    strike = zscalps_parsed.get('strike', '')
                                    opt_type = zscalps_parsed.get('opt_type', 'C')
                                    expiry = zscalps_parsed.get('expiry', '')
                                    price_str = f"@ {price}" if price else "@ m"
                                    forward_msg = f"BTO {symbol} {strike}{opt_type} {expiry} {price_str}"
                                else:
                                    price_str = f"@ {price}" if price else ""
                                    forward_msg = f"STC {symbol} {price_str}"
                                print(f"[CHANNEL MAP] ✓ Formatted Z-scalps: {forward_msg}")
                            else:
                                forward_msg = combined_content.strip()
                                print(f"[CHANNEL MAP] ⚠️ Z-scalps parse failed, forwarding raw")
                        elif is_bullwinkle:
                            print(f"[DEBUG] Taking BULLWINKLE path", flush=True)
                            bullwinkle_parsed = parse_bullwinkle_signal(combined_content)
                            if bullwinkle_parsed:
                                forward_msg = format_bullwinkle_for_webhook(bullwinkle_parsed)
                                print(f"[CHANNEL MAP] ✓ Formatted Bullwinkle: {forward_msg}")
                            else:
                                forward_msg = strip_bullwinkle_emojis(combined_content.strip())
                                print(f"[CHANNEL MAP] ✓ Stripped emojis (parse failed): {forward_msg}")
                        elif is_jacob:
                            print(f"[DEBUG] Taking JACOB path", flush=True)
                            jacob_parsed = parse_jacob_signal(combined_content)
                            if jacob_parsed:
                                forward_msg = format_jacob_for_webhook(jacob_parsed)
                                print(f"[CHANNEL MAP] ✓ Formatted Jacob: {forward_msg}")
                            else:
                                forward_msg = message.content.strip()
                                print(f"[CHANNEL MAP] ⚠️ Jacob parse failed, forwarding raw")
                        elif format_as_bto_stc:
                            print(f"[DEBUG] Taking FORMAT_AS_BTO_STC path", flush=True)
                            # Convert any signal format to BTO/STC format for forwarding
                            parsed_opt = parse_option_signal(combined_content)
                            print(f"[DEBUG] parse_option_signal returned: {type(parsed_opt)}, truthy={bool(parsed_opt)}", flush=True)
                            if parsed_opt:
                                try:
                                    action = parsed_opt.get('action', 'BTO')
                                    qty = parsed_opt.get('qty')
                                    qty_from_signal = parsed_opt.get('_qty_from_signal', False)
                                    symbol = parsed_opt.get('symbol', '')
                                    strike = parsed_opt.get('strike', '')
                                    opt_type = parsed_opt.get('opt_type', 'C')
                                    expiry = parsed_opt.get('expiry', '')
                                    price = parsed_opt.get('price')
                                    price_str = f"@ {price}" if price else "@ m"
                                    # Only include qty in forward if source signal had it AND it's valid
                                    if qty_from_signal and qty is not None:
                                        forward_msg = f"{action} {qty} {symbol} {strike}{opt_type} {expiry} {price_str}"
                                    else:
                                        forward_msg = f"{action} {symbol} {strike}{opt_type} {expiry} {price_str}"
                                    print(f"[CHANNEL MAP] ✓ Converted to BTO/STC format: {forward_msg}", flush=True)
                                except Exception as conv_err:
                                    print(f"[CHANNEL MAP] ❌ Conversion error: {conv_err}", flush=True)
                                    import traceback
                                    traceback.print_exc()
                                    forward_msg = message.content.strip()
                            else:
                                # Couldn't parse, forward as-is
                                forward_msg = message.content.strip()
                                print(f"[CHANNEL MAP] ⚠️ Could not parse signal, forwarding raw: {forward_msg[:50]}...")
                        else:
                            forward_msg = message.content.strip()
                        
                        try:
                            if is_webhook_dest:
                                # Forward to webhook URL
                                import aiohttp
                                webhook_url = target_execution_channel_id
                                print(f"[DEBUG] Posting to webhook: {webhook_url[:50]}...")
                                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                                    async with session.post(webhook_url, json={"content": forward_msg}) as resp:
                                        if resp.status in [200, 204]:
                                            print(f"[CHANNEL MAP] ✓ Forwarded BTO/STC signal to webhook")
                                        else:
                                            print(f"[CHANNEL MAP] ⚠️ Webhook returned status {resp.status}")
                            elif is_channel_dest:
                                # Forward to Discord channel ID
                                print(f"[DEBUG] Forwarding to channel: {dest_channel_id}")
                                try:
                                    dest_channel = self.get_channel(int(dest_channel_id))
                                    if dest_channel is None:
                                        dest_channel = await self.fetch_channel(int(dest_channel_id))
                                    
                                    if dest_channel:
                                        await dest_channel.send(forward_msg)
                                        print(f"[CHANNEL MAP] ✓ Forwarded BTO/STC signal to channel {dest_channel_id}")
                                    else:
                                        print(f"[CHANNEL MAP] ❌ Could not find destination channel {dest_channel_id}")
                                except Exception as ch_err:
                                    print(f"[CHANNEL MAP] ❌ Channel forward failed: {ch_err}")
                        except Exception as e:
                            import traceback
                            print(f"[CHANNEL MAP] ❌ Forward failed: {e}")
                            traceback.print_exc()
                    
                    # TRACK SIGNAL FOR PNL - even if not executing trades
                    # This allows Trade Summary/PNL tracking for forwarded signals
                    print(f"[PNL TRACK] Starting signal tracking...", flush=True)
                    try:
                        from gui_app.database import (
                            create_signal_instance, close_signal_instance, 
                            get_open_position_for_symbol, partial_exit_signal_instance
                        )
                        
                        channel_id = str(message.channel.id)
                        author_name = f"{message.author.name}#{message.author.discriminator}" if message.author.discriminator != '0' else message.author.name
                        
                        # Parse the signal to get details - use unified parse_option_signal for ALL formats
                        parsed_signal = None
                        print(f"[PNL TRACK] Parsing signal for tracking, is_bullwinkle={is_bullwinkle}, is_jacob={is_jacob}")
                        if is_bullwinkle:
                            parsed_signal = parse_bullwinkle_signal(combined_content)
                            print(f"[PNL TRACK] Bullwinkle parsed: {parsed_signal}")
                        elif is_jacob:
                            jacob_parsed = parse_jacob_signal(combined_content)
                            if jacob_parsed:
                                parsed_signal = {
                                    'symbol': jacob_parsed.get('symbol', ''),
                                    'strike': 0,
                                    'opt_type': None,
                                    'expiry': '',
                                    'price': jacob_parsed.get('entry_price', 0),
                                    'qty': jacob_parsed.get('qty', 1),
                                    'is_exit': False,
                                    'asset_type': 'stock',
                                    'stop_loss': jacob_parsed.get('stop_loss'),
                                    'profit_targets': jacob_parsed.get('profit_targets', [])
                                }
                                print(f"[PNL TRACK] Jacob parsed: {parsed_signal}")
                        else:
                            # Use the unified parser which handles ALL formats (BTO/STC, Bishop, EvaPanda, DTE, etc.)
                            parsed_opt = parse_option_signal(combined_content)
                            print(f"[PNL TRACK] parse_option_signal returned: {parsed_opt}")
                            if parsed_opt:
                                action = parsed_opt.get('action', 'BTO').upper()
                                is_exit = action == 'STC'
                                parsed_signal = {
                                    'symbol': parsed_opt.get('symbol', ''),
                                    'strike': parsed_opt.get('strike'),
                                    'opt_type': parsed_opt.get('opt_type', 'C'),
                                    'expiry': parsed_opt.get('expiry', ''),
                                    'price': parsed_opt.get('price', 0),
                                    'qty': parsed_opt.get('qty', 1),
                                    'is_exit': is_exit
                                }
                                print(f"[PNL TRACK] {'STC' if is_exit else 'BTO'} parsed: {parsed_signal}")
                        
                        if parsed_signal:
                            symbol = parsed_signal['symbol']
                            is_exit = parsed_signal.get('is_exit', False)
                            
                            if is_exit:
                                # STC - Process partial or full exit and calculate PNL
                                exit_price = parsed_signal.get('price', 0)
                                exit_qty = parsed_signal.get('qty')
                                
                                # Find open position for this symbol in this channel
                                open_pos = get_open_position_for_symbol(channel_id, symbol)
                                if open_pos:
                                    entry_price = open_pos.get('entry_price', 0)
                                    remaining_qty = open_pos.get('qty', 1)
                                    original_qty = open_pos.get('original_qty', remaining_qty)
                                    
                                    # Determine exit quantity
                                    actual_exit_qty = exit_qty if exit_qty else remaining_qty
                                    actual_exit_qty = min(actual_exit_qty, remaining_qty)  # Can't exit more than we have
                                    
                                    # Calculate PNL for this exit
                                    pnl = (exit_price - entry_price) * actual_exit_qty * 100
                                    pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                                    
                                    # Process partial/full exit
                                    exit_result = partial_exit_signal_instance(
                                        channel_id=channel_id,
                                        ticker=symbol,
                                        exit_qty=actual_exit_qty,
                                        close_reason='exit_signal'
                                    )
                                    
                                    if exit_result:
                                        new_remaining = exit_result.get('remaining_qty', 0)
                                        fully_closed = exit_result.get('fully_closed', True)
                                        
                                        if fully_closed:
                                            print(f"[PNL TRACK] ✓ FULL EXIT: {symbol} @ ${exit_price:.2f}, {actual_exit_qty} contracts, PNL: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
                                        else:
                                            print(f"[PNL TRACK] ✓ PARTIAL EXIT: {symbol} @ ${exit_price:.2f}, {actual_exit_qty}/{original_qty} contracts, Remaining: {new_remaining}, PNL: ${pnl:+.2f} ({pnl_pct:+.1f}%)")
                                        
                                        # Post Trade Summary to webhook (if enabled)
                                        try:
                                            trade_summary_enabled_for_channel = db.is_trade_summary_enabled(str(channel_id))
                                        except Exception as e:
                                            print(f"[PNL TRACK] Error checking trade_summary_enabled: {e}")
                                            trade_summary_enabled_for_channel = True
                                        
                                        if webhook_url and trade_summary_enabled_for_channel:
                                            exit_type = "FULL EXIT" if fully_closed else f"PARTIAL EXIT ({actual_exit_qty}/{original_qty})"
                                            summary_msg = (
                                                f"**Trade Summary - {exit_type}**\n"
                                                f"Closed: {symbol} @ ${exit_price:.2f} (Entry: ${entry_price:.2f})\n"
                                                f"Qty: {actual_exit_qty} | Gain: {pnl_pct:+.1f}%\n"
                                                f"Profit: ${pnl:+.2f}"
                                            )
                                            if not fully_closed:
                                                summary_msg += f"\n*Remaining: {new_remaining} contracts*"
                                            
                                            try:
                                                import aiohttp
                                                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                                                    async with session.post(webhook_url, json={"content": summary_msg}) as resp:
                                                        if resp.status in [200, 204]:
                                                            print(f"[PNL TRACK] ✓ Posted Trade Summary to webhook")
                                            except Exception as e:
                                                print(f"[PNL TRACK] ⚠️ Failed to post summary: {e}")
                                        elif webhook_url and not trade_summary_enabled_for_channel:
                                            print(f"[PNL TRACK] ⏭️ Trade Summary disabled for channel {channel_id}")
                                    else:
                                        print(f"[PNL TRACK] ⚠️ Failed to process exit for {symbol}")
                                else:
                                    print(f"[PNL TRACK] ⚠️ No open position found for {symbol} in channel {channel_id}")
                            else:
                                # BTO - Create new position with quantity
                                entry_price = parsed_signal.get('price', 0)
                                qty = parsed_signal.get('qty', 1) or 1
                                
                                # Create signal instance for tracking with quantity
                                instance_id = create_signal_instance(
                                    channel_id=channel_id,
                                    ticker=symbol,
                                    entry_price=entry_price,
                                    direction='BTO',
                                    quantity=qty,
                                    author_name=author_name,
                                    message_id=str(message.id)
                                )
                                if instance_id:
                                    print(f"[PNL TRACK] ✓ Opened {symbol} @ ${entry_price:.2f} x{qty} (instance #{instance_id})")
                                else:
                                    print(f"[PNL TRACK] ⚠️ Duplicate or failed to create instance for {symbol}")
                        else:
                            print(f"[PNL TRACK] ⚠️ Could not parse signal for tracking")
                    except Exception as e:
                        import traceback
                        print(f"[PNL TRACK] ❌ Error tracking signal: {e}")
                        traceback.print_exc()
                    
                    # If execute is NOT enabled, we're done (already forwarded and tracked)
                    if not should_execute:
                        return
                    # If execute IS enabled, fall through to trade execution below
                    pass
                else:
                    # Non-signal message (Trade Summary, informational, etc.)
                    print(f"[DEBUG] Non-signal message detected (not BTO/STC or Bullwinkle)")
                    print(f"[DEBUG] should_forward={should_forward}, target_execution_channel_id={target_execution_channel_id}")
                    print(f"[DEBUG] Message preview: {message.content[:100]}...")
                    
                    # Check for CONDITIONAL ORDER signals (e.g., "AAPL over 150 SL 5%")
                    try:
                        from src.signals.parser import is_conditional_order_signal, parse_conditional_order_signal
                        from src.services.conditional_orders.router import conditional_order_router
                        
                        if is_conditional_order_signal(message.content) and conditional_order_router.is_enabled():
                            cond_channel_id = str(message.channel.id)
                            print(f"[COND ORDER] ✓ Detected conditional order signal in channel {cond_channel_id}")
                            parsed_cond = parse_conditional_order_signal(message.content)
                            if parsed_cond:
                                # Add channel context
                                parsed_cond['message_id'] = str(message.id)
                                parsed_cond['author_id'] = str(message.author.id)
                                parsed_cond['author_name'] = str(message.author)
                                
                                # Determine broker (use channel setting first, then default)
                                # PRIORITY: enabled_brokers > broker_override (enabled_brokers is from Execution page, more specific)
                                cond_broker = None
                                if channel_info:
                                    # Check enabled_brokers FIRST (JSON array from Execution page - more specific)
                                    if channel_info.get('enabled_brokers'):
                                        try:
                                            import json
                                            enabled = channel_info.get('enabled_brokers')
                                            if isinstance(enabled, str):
                                                enabled = json.loads(enabled)
                                            if enabled and len(enabled) > 0:
                                                # Map uppercase names to proper broker names
                                                broker_map = {
                                                    'WEBULL': 'Webull', 
                                                    'ALPACA': 'Alpaca',
                                                    'ALPACA_PAPER': 'Alpaca',
                                                    'TASTYTRADE': 'Tastytrade',
                                                    'TASTYTRADE_PAPER': 'Tastytrade',
                                                    'IBKR': 'IBKR',
                                                    'IBKR_PAPER': 'IBKR',
                                                    'SCHWAB': 'Schwab',
                                                    'UPSTOX': 'upstox',
                                                    'ZERODHA': 'zerodha',
                                                    'DHANQ': 'dhanq',
                                                    'QUESTRADE': 'questrade'
                                                }
                                                first_broker = enabled[0].upper()
                                                cond_broker = broker_map.get(first_broker, enabled[0])
                                                print(f"[COND ORDER] Using channel enabled_brokers[0]: {enabled[0]} -> {cond_broker}")
                                        except Exception as e:
                                            print(f"[COND ORDER] Error parsing enabled_brokers: {e}")
                                    # Fall back to broker_override if enabled_brokers not set
                                    elif channel_info.get('broker_override'):
                                        cond_broker = channel_info.get('broker_override')
                                        print(f"[COND ORDER] Using channel broker_override: {cond_broker}")
                                
                                # Reject if no broker is configured - do NOT fallback to a default
                                if not cond_broker:
                                    print(f"[COND ORDER] ❌ REJECTED: No broker configured for channel {cond_channel_id}")
                                    print(f"[COND ORDER] Please configure 'enabled_brokers' in the Execution page for this channel")
                                    # Reactions disabled for conditional orders
                                    return
                                
                                # Submit to conditional order router (market-isolated)
                                order_id = conditional_order_router.create_order(cond_channel_id, parsed_cond, cond_broker)
                                if order_id:
                                    trigger_type = parsed_cond.get('trigger_type', 'over')
                                    print(f"[COND ORDER] ✓ Created conditional order #{order_id}: {parsed_cond['symbol']} {trigger_type} ${parsed_cond['trigger_price']}")
                                    
                                    # Save to signals table for Execution tab display
                                    try:
                                        author_name = f"{message.author.name}#{message.author.discriminator}" if message.author.discriminator != '0' else message.author.name
                                        cond_signal = {
                                            'action': 'BTO',
                                            'symbol': parsed_cond['symbol'],
                                            'qty': parsed_cond.get('calculated_qty', 1),
                                            'price': parsed_cond.get('trigger_price', 0),
                                            'asset': parsed_cond.get('asset_type', 'stock'),
                                            '_conditional_order_id': order_id
                                        }
                                        self._save_signal_to_db(cond_signal, message.channel.id, message.id, author_name)
                                        print(f"[COND ORDER] ✓ Signal saved to database for Execution tab")
                                    except Exception as save_err:
                                        print(f"[COND ORDER] ⚠️ Failed to save signal to DB: {save_err}")
                                else:
                                    print(f"[COND ORDER] ⚠️ Failed to create conditional order")
                            else:
                                print(f"[COND ORDER] ⚠️ Could not parse conditional order signal")
                            return  # Don't forward conditional order signals
                    except Exception as e:
                        import traceback
                        print(f"[COND ORDER] ⚠️ Error checking conditional order: {e}")
                        traceback.print_exc()
                    
                    # Check for PARTIAL EXIT signals (e.g., "selling 80% MLTX", "leaving 10%")
                    try:
                        from src.signals.parser import is_partial_exit_signal, parse_partial_exit_signal
                        
                        if is_partial_exit_signal(message.content):
                            parsed_partial = parse_partial_exit_signal(message.content)
                            if parsed_partial:
                                symbol = parsed_partial.get('symbol')
                                exit_pct = parsed_partial.get('exit_percent', 0)
                                action_type = parsed_partial.get('action', 'PARTIAL_EXIT')
                                
                                # If no symbol specified, try to find from context
                                if not symbol:
                                    try:
                                        from src.services.signal_conversation_state import get_conversation_state_manager
                                        manager = get_conversation_state_manager()
                                        symbol = manager.get_recent_symbol_for_author(
                                            int(message.channel.id),
                                            int(message.author.id)
                                        )
                                        if symbol:
                                            parsed_partial['symbol'] = symbol
                                            print(f"[PARTIAL EXIT] Inferred symbol from context: {symbol}")
                                    except Exception as e:
                                        print(f"[PARTIAL EXIT] Could not get context symbol: {e}")
                                
                                if symbol:
                                    print(f"[PARTIAL EXIT] Processing {exit_pct}% exit of {symbol}")
                                    
                                    # Execute partial exit via position cache (supports both stocks and options)
                                    try:
                                        from src.risk.position_cache import get_position_cache
                                        cache = get_position_cache()
                                        
                                        # Try to find position - supports both stock and option positions
                                        position = cache.get_position(symbol)
                                        
                                        if position and position.qty > 0:
                                            exit_qty = int(position.qty * (exit_pct / 100.0))
                                            if exit_qty > 0:
                                                # Build STC signal preserving asset type from position
                                                asset_type = getattr(position, 'asset_type', 'stock')
                                                stc_signal = {
                                                    'asset': asset_type,
                                                    'action': 'STC',
                                                    'symbol': symbol,
                                                    'qty': exit_qty,
                                                    'is_market_order': True,
                                                    '_partial_exit': True,
                                                    '_exit_percent': exit_pct,
                                                    '_exit_reason': action_type,
                                                }
                                                
                                                # Add option details if this is an option position
                                                if hasattr(position, 'strike') and position.strike:
                                                    stc_signal['strike'] = position.strike
                                                if hasattr(position, 'opt_type') and position.opt_type:
                                                    stc_signal['opt_type'] = position.opt_type
                                                if hasattr(position, 'expiry') and position.expiry:
                                                    stc_signal['expiry'] = position.expiry
                                                
                                                # Queue the partial exit
                                                global _telegram_signal_queue
                                                if _telegram_signal_queue is not None:
                                                    _telegram_signal_queue.put_nowait(stc_signal)
                                                    print(f"[PARTIAL EXIT] ✓ Queued STC for {exit_qty} {asset_type} of {symbol} ({exit_pct}%)")
                                                else:
                                                    print(f"[PARTIAL EXIT] ❌ Signal queue not available")
                                            else:
                                                print(f"[PARTIAL EXIT] ⚠️ Calculated exit qty is 0 (position: {position.qty})")
                                        else:
                                            print(f"[PARTIAL EXIT] ⚠️ No open position found for {symbol}")
                                    except Exception as e:
                                        print(f"[PARTIAL EXIT] ❌ Error executing partial exit: {e}")
                                else:
                                    print(f"[PARTIAL EXIT] ⚠️ Could not determine symbol for partial exit")
                                return
                    except Exception as e:
                        import traceback
                        print(f"[PARTIAL EXIT] ⚠️ Error checking partial exit: {e}")
                        traceback.print_exc()
                    
                    # Check for CANCELLATION signals (e.g., "@Daytrades cancelling JTAI")
                    try:
                        from src.signals.parser import is_cancel_order_signal, parse_cancel_order_signal
                        from src.services.conditional_orders.router import conditional_order_router
                        
                        if is_cancel_order_signal(message.content):
                            parsed_cancel = parse_cancel_order_signal(message.content)
                            if parsed_cancel:
                                symbol = parsed_cancel.get('symbol')
                                channel_id = str(message.channel.id)
                                
                                print(f"[CANCEL ORDER] Processing cancellation for {symbol}")
                                
                                # Cancel via conditional order router
                                try:
                                    cancelled = conditional_order_router.cancel_order_by_symbol(channel_id, symbol)
                                    if cancelled:
                                        print(f"[CANCEL ORDER] ✓ Cancelled conditional order for {symbol}")
                                    else:
                                        print(f"[CANCEL ORDER] ⚠️ No active conditional order found for {symbol}")
                                    
                                    # Also remove from conversation state
                                    try:
                                        from src.services.signal_conversation_state import cancel_signal_context
                                        cancel_signal_context(
                                            channel_id=int(message.channel.id),
                                            author_id=int(message.author.id),
                                            symbol=symbol
                                        )
                                    except Exception:
                                        pass
                                except Exception as e:
                                    print(f"[CANCEL ORDER] ❌ Error cancelling order: {e}")
                                return
                    except Exception as e:
                        import traceback
                        print(f"[CANCEL ORDER] ⚠️ Error checking cancellation: {e}")
                        traceback.print_exc()
                    
                    # Check for FOLLOW-UP updates (e.g., "SL now at 14.60", "PT raised to 17.50")
                    try:
                        from src.services.signal_conversation_state import process_follow_up_message
                        
                        update_result = process_follow_up_message(
                            message_id=int(message.id),
                            channel_id=int(message.channel.id),
                            author_id=int(message.author.id),
                            text=message.content
                        )
                        
                        if update_result:
                            order_id = update_result.get('order_id')
                            symbol = update_result.get('symbol')
                            sl_update = update_result.get('stop_loss_value')
                            pt_update = update_result.get('profit_target_update')
                            
                            if order_id:
                                # Update the conditional order in database
                                try:
                                    from gui_app.database import update_conditional_order_sl_pt
                                    update_conditional_order_sl_pt(
                                        order_id=order_id,
                                        stop_loss_value=sl_update,
                                        take_profit_target=pt_update
                                    )
                                    update_info = []
                                    if sl_update:
                                        update_info.append(f"SL=${sl_update}")
                                    if pt_update:
                                        update_info.append(f"PT=${pt_update}")
                                    print(f"[FOLLOW-UP] ✓ Updated order #{order_id}: {', '.join(update_info)}")
                                except Exception as e:
                                    print(f"[FOLLOW-UP] ⚠️ Could not update order #{order_id}: {e}")
                            else:
                                print(f"[FOLLOW-UP] ✓ Context updated for {symbol} (no active order)")
                    except Exception as e:
                        pass  # Silently ignore follow-up parsing errors
                    
                    # Check if target is a webhook URL (for channel mappings)
                    if target_execution_channel_id and target_execution_channel_id.startswith('https://'):
                        print(f"[DEBUG] Inside webhook URL block, parsing message...")
                        
                        # DUAL-ACTION: Execute on broker FIRST if enabled
                        if should_execute:
                            print(f"[DUAL-ACTION] Executing on broker first...")
                            # Parse the signal and execute trade
                            trade_idea = None
                            try:
                                trade_idea = parse_trade_idea_signal(message.content)
                            except Exception as e:
                                print(f"[DUAL-ACTION] parse_trade_idea_signal exception: {e}")
                            
                            if trade_idea:
                                # Execute the trade on connected broker
                                await self.handle_auto_signal_conversion(message, message.content.strip(), target_channel_id=None)
                                print(f"[DUAL-ACTION] ✓ Broker execution initiated for {trade_idea['ticker']}")
                        
                        # THEN Forward to webhook if enabled
                        if should_forward:
                            # Parse TRADE IDEA format and forward to webhook
                            try:
                                trade_idea = parse_trade_idea_signal(message.content)
                                print(f"[DEBUG] trade_idea result: {trade_idea}")
                            except Exception as e:
                                print(f"[DEBUG] parse_trade_idea_signal exception: {e}")
                                trade_idea = None
                            
                            if trade_idea:
                                # Format based on format_as_bto_stc flag
                                if format_as_bto_stc:
                                    webhook_msg = format_trade_idea_as_bto_stc(trade_idea)
                                    print(f"[CHANNEL MAP] ✓ Formatted as BTO: {trade_idea['ticker']}")
                                else:
                                    webhook_msg = format_trade_idea_for_webhook(trade_idea)
                                    print(f"[CHANNEL MAP] ✓ Parsed TRADE IDEA: {trade_idea['ticker']} @ ${trade_idea['entry']}")
                            else:
                                # Trade Summary, informational messages, etc. - forward as-is
                                webhook_msg = message.content.strip()
                                print(f"[CHANNEL MAP] ✓ Forwarding raw message to webhook (Trade Summary/Info)")
                                print(f"[CHANNEL MAP]   Content: {webhook_msg[:100]}...")
                            
                            try:
                                import aiohttp
                                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                                    async with session.post(target_execution_channel_id, json={"content": webhook_msg}) as resp:
                                        if resp.status in [200, 204]:
                                            print(f"[CHANNEL MAP] ✓ Posted to webhook successfully")
                                        else:
                                            print(f"[CHANNEL MAP] ⚠️ Webhook returned status {resp.status}")
                            except Exception as e:
                                print(f"[CHANNEL MAP] ❌ Webhook post failed: {e}")
                        return
                    
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
            
            # !extracthistory [CHANNEL_ID] [LIMIT] - Extract messages for pattern analysis
            elif content.lower().startswith('!extracthistory'):
                args = content[15:].strip().split()
                channel_id = int(args[0]) if args else 1239624229583061052  # Default to Bishop
                limit = int(args[1]) if len(args) > 1 else 200
                await self.handle_extract_history(message, channel_id, limit)
                return
        
        # Allow !extracthistory from ANY channel (for admin use)
        if message.content.strip().lower().startswith('!extracthistory') and self.user and message.author.id == self.user.id:
            content = message.content.strip()
            args = content[15:].strip().split()
            channel_id = int(args[0]) if args else 1239624229583061052  # Default to Bishop
            limit = int(args[1]) if len(args) > 1 else 200
            await self.handle_extract_history(message, channel_id, limit)
            return
        
        # Pre-process special formats (Bullwinkle scalps, etc.)
        from src.signals.parser import (
            normalize_bullwinkle_format, is_india_signal, parse_india_option_signal, 
            parse_india_stock_signal, parse_trade_idea, is_trade_idea_signal,
            is_bullwinkle_signal, parse_bullwinkle_signal
        )
        from gui_app.database import (
            check_signal_instance, create_signal_instance, update_signal_instance, close_signal_instance,
            get_open_position_for_symbol
        )
        
        # Initialize variables for signal tracking
        india_stock_signal = None
        bullwinkle_opt = None
        
        # Check for Bullwinkle format first (with deduplication)
        if is_bullwinkle_signal(combined_content):
            bullwinkle_signal = parse_bullwinkle_signal(combined_content)
            if bullwinkle_signal:
                symbol = bullwinkle_signal['symbol']
                author_name = f"{message.author.name}#{message.author.discriminator}" if message.author.discriminator != '0' else message.author.name
                
                if bullwinkle_signal.get('is_exit'):
                    # Exit signal - look up open position to get strike/expiry
                    print(f"[BULLWINKLE] ✓ Exit signal detected for {symbol}")
                    
                    # Find matching open position
                    open_position = get_open_position_for_symbol(symbol, str(message.channel.id))
                    if open_position:
                        # Create STC signal with position details
                        bullwinkle_opt = {
                            'asset': 'option',
                            'action': 'STC',
                            'symbol': symbol,
                            'strike': open_position.get('strike'),
                            'opt_type': open_position.get('call_put') or open_position.get('opt_type'),
                            'expiry': open_position.get('expiry'),
                            'price': bullwinkle_signal.get('price'),
                            'qty': bullwinkle_signal.get('qty') or open_position.get('quantity') or 1,
                            '_bullwinkle': True,
                        }
                        print(f"[BULLWINKLE] ✓ Found open position: {symbol} {bullwinkle_opt['strike']}{bullwinkle_opt['opt_type']} {bullwinkle_opt['expiry']}")
                        
                        # Close the signal instance by channel+ticker (don't require exact price match)
                        close_signal_instance(channel_id=str(message.channel.id), ticker=symbol, close_reason='exit_signal')
                        print(f"[DEDUPE] ✓ Closed signal instance for {symbol}")
                    else:
                        print(f"[BULLWINKLE] ⚠️ No open position found for {symbol} - cannot determine strike/expiry")
                        # Still try to process as market order STC
                        bullwinkle_opt = bullwinkle_signal
                else:
                    # Entry signal - check for deduplication
                    entry_price = bullwinkle_signal.get('price')
                    strike = bullwinkle_signal.get('strike')
                    
                    existing_instance = check_signal_instance(
                        str(message.channel.id), symbol, entry_price, 'BTO'
                    )
                    
                    if existing_instance:
                        # Duplicate - skip execution
                        print(f"[DEDUPE] ⚠️ Duplicate Bullwinkle signal detected for {symbol} @ {entry_price} (instance #{existing_instance['id']})")
                        return
                    
                    # New signal - create instance and proceed
                    instance_id = create_signal_instance(
                        channel_id=str(message.channel.id),
                        ticker=symbol,
                        entry_price=entry_price,
                        direction='BTO',
                        author_id=str(message.author.id),
                        author_name=author_name,
                        message_id=str(message.id),
                        stop_loss=None,
                        profit_targets=[],
                        ttl_hours=24
                    )
                    
                    if instance_id:
                        print(f"[DEDUPE] ✓ New Bullwinkle signal instance: {symbol} {strike} @ {entry_price} (ID: {instance_id})")
                        bullwinkle_opt = bullwinkle_signal
                    else:
                        print(f"[DEDUPE] ⚠️ Failed to create instance for {symbol} - may be duplicate")
                        return
        
        normalized_content = normalize_bullwinkle_format(combined_content)
        
        # Check for TRADE IDEA format first (with deduplication)
        if is_trade_idea_signal(combined_content):
            trade_idea = parse_trade_idea(combined_content)
            if trade_idea:
                ticker = trade_idea['ticker']
                entry_price = trade_idea['entry_price']
                stop_loss = trade_idea.get('stop_loss')
                profit_targets = trade_idea.get('profit_targets', [])
                author_name = f"{message.author.name}#{message.author.discriminator}" if message.author.discriminator != '0' else message.author.name
                
                # Check for duplicate/update
                existing_instance = check_signal_instance(
                    str(message.channel.id), ticker, entry_price, 'BTO'
                )
                
                signal_type = trade_idea.get('signal_type', 'entry')
                hit_levels = trade_idea.get('hit_levels', [])
                pending_levels = trade_idea.get('pending_levels', [])
                is_update = trade_idea.get('is_update', False)
                
                if existing_instance:
                    # This is an update to an existing signal - log but don't execute new BTO
                    update_reason = []
                    if hit_levels:
                        update_reason.append(f"HIT levels: {hit_levels}")
                    if is_update:
                        update_reason.append("SL/PT updated")
                    reason_str = f" ({', '.join(update_reason)})" if update_reason else ""
                    
                    print(f"[DEDUPE] ⚠️ Update detected for {ticker} @ {entry_price} (instance #{existing_instance['id']}, update #{existing_instance['update_count'] + 1}){reason_str}")
                    update_signal_instance(
                        existing_instance['id'],
                        message_id=str(message.id),
                        stop_loss=stop_loss,
                        profit_targets=profit_targets
                    )
                    
                    # Check if this is an exit signal
                    if trade_idea.get('is_exit'):
                        close_signal_instance(instance_id=existing_instance['id'], close_reason='exit_signal')
                        print(f"[DEDUPE] ✓ Closed signal instance for {ticker} - exit detected ('all out')")
                    
                    return  # Skip execution, this is just an update
                
                # Check if signal itself indicates update (strikethrough levels) but no existing instance
                if signal_type == 'update' and not existing_instance:
                    print(f"[TRADE IDEA] ⚠️ Update signal for {ticker} but no open position tracked - skipping")
                    return
                
                # New signal - create instance and proceed
                instance_id = create_signal_instance(
                    channel_id=str(message.channel.id),
                    ticker=ticker,
                    entry_price=entry_price,
                    direction='BTO',
                    author_id=str(message.author.id),
                    author_name=author_name,
                    message_id=str(message.id),
                    stop_loss=stop_loss,
                    profit_targets=profit_targets,
                    ttl_hours=24
                )
                
                if instance_id:
                    print(f"[DEDUPE] ✓ New signal instance created: {ticker} @ {entry_price} (ID: {instance_id})")
                    # Convert to stock signal format for processing
                    india_stock_signal = trade_idea
                else:
                    # Failed to create (duplicate or error), skip
                    return
        
        # Parse trading signals - check Bullwinkle first, then India, then US format
        opt = bullwinkle_opt  # Use Bullwinkle signal if already parsed
        
        if opt is None and is_india_signal(normalized_content):
            print(f"[SIGNAL] Detected India format signal, using India parser")
            opt = parse_india_option_signal(normalized_content)
            if not opt:
                india_stock_signal = parse_india_stock_signal(normalized_content)
        
        # Route Indian CONDITIONAL orders (with ABOVE/BELOW) to conditional order router
        if opt and opt.get('_conditional_order') and opt.get('market') == 'INDIA':
            print(f"[INDIA CONDITIONAL] ✓ Detected conditional order: {opt['symbol']} {opt['strike']}{opt['opt_type']} {opt.get('trigger_type')} ₹{opt.get('trigger_price')}")
            
            try:
                from src.services.conditional_orders.router import conditional_order_router
                
                if conditional_order_router.is_enabled():
                    # Get broker from channel config - prioritize enabled_brokers over broker_override
                    broker = None
                    if channel_info:
                        # Check enabled_brokers first (Execution page config)
                        if channel_info.get('enabled_brokers'):
                            try:
                                import json
                                enabled = channel_info.get('enabled_brokers')
                                if isinstance(enabled, str):
                                    enabled = json.loads(enabled)
                                if enabled and len(enabled) > 0:
                                    # Map to proper broker names for India market
                                    broker_map = {
                                        'UPSTOX': 'upstox',
                                        'ZERODHA': 'zerodha', 
                                        'DHANQ': 'dhanq',
                                    }
                                    first_broker = enabled[0].upper()
                                    broker = broker_map.get(first_broker, enabled[0].lower())
                                    print(f"[INDIA CONDITIONAL] Using channel enabled_brokers[0]: {enabled[0]} -> {broker}")
                            except Exception as e:
                                print(f"[INDIA CONDITIONAL] Error parsing enabled_brokers: {e}")
                        # Fall back to broker_override if enabled_brokers not set
                        if not broker and channel_info.get('broker_override'):
                            broker = channel_info.get('broker_override').lower()
                            print(f"[INDIA CONDITIONAL] Using channel broker_override: {broker}")
                    
                    # Reject if no broker is configured for India channels
                    if not broker:
                        print(f"[INDIA CONDITIONAL] ❌ REJECTED: No India broker configured for channel {message.channel.id}")
                        print(f"[INDIA CONDITIONAL] Please configure 'enabled_brokers' (Upstox/Zerodha/DhanQ) in the Execution page for this channel")
                        # Reactions disabled for conditional orders
                        return
                    
                    # For India markets, treat channel default_quantity as number of LOTS
                    # If signal has explicit 'lots', use it; otherwise derive from qty or channel default
                    signal_qty = opt.get('qty')
                    signal_lots = opt.get('lots')
                    
                    # If lots not explicitly in signal but qty is set (from channel default), treat qty as lots
                    if signal_lots is None and signal_qty is not None:
                        signal_lots = int(signal_qty)
                        print(f"[INDIA CONDITIONAL] Using qty={signal_qty} as lots for India market")
                    elif signal_lots is None:
                        # Check channel default_quantity - treat as lots for India
                        channel_default_qty = channel_info.get('default_quantity') if channel_info else None
                        if channel_default_qty:
                            signal_lots = int(channel_default_qty)
                            print(f"[INDIA CONDITIONAL] Using channel default_quantity={channel_default_qty} as lots")
                        else:
                            signal_lots = 1
                    
                    conditional_signal = {
                        'symbol': opt['symbol'],
                        'strike': opt['strike'],
                        'opt_type': opt['opt_type'],
                        'trigger_price': opt.get('trigger_price'),
                        'trigger_type': opt.get('trigger_type', 'over'),
                        'stop_loss': opt.get('stop_loss'),
                        'profit_targets': opt.get('profit_targets', []),
                        'qty': signal_qty,
                        'lots': signal_lots,
                        'lot_size': opt.get('lot_size'),
                        'expiry': opt.get('expiry'),
                        'market': 'INDIA',
                        'asset_type': 'option',
                        'message_id': str(message.id),
                        'author_id': str(message.author.id),
                        'author_name': str(message.author),
                    }
                    
                    order_id = conditional_order_router.create_order(
                        channel_id=str(message.channel.id),
                        parsed_signal=conditional_signal,
                        broker=broker
                    )
                    
                    if order_id:
                        print(f"[INDIA CONDITIONAL] ✓ Created conditional order #{order_id} - monitoring started")
                        # Reactions disabled for conditional orders
                    else:
                        print(f"[INDIA CONDITIONAL] ⚠️ Failed to create conditional order")
                else:
                    print(f"[INDIA CONDITIONAL] ⚠️ Conditional order service disabled - signal ignored")
            except ImportError as e:
                print(f"[INDIA CONDITIONAL] ⚠️ Conditional order service not available: {e}")
            except Exception as e:
                print(f"[INDIA CONDITIONAL] ❌ Error creating conditional order: {e}")
            
            return
        
        # Fall back to US format parser if not India signal or India parser failed
        if opt is None and india_stock_signal is None:
            opt = parse_option_signal(normalized_content)
        
        # Check for bracket order signal (stock with targets and stop loss)
        bracket_signal = None
        from src.signals.parser import is_bracket_order_signal, parse_bracket_order_signal, is_jacob_signal, parse_jacob_signal, is_conditional_order_signal, parse_conditional_order_signal
        
        # Check for conditional order signal FIRST (before regular BTO/STC parsing)
        # This routes price-triggered orders to the conditional order service
        if is_conditional_order_signal(normalized_content):
            conditional_signal = parse_conditional_order_signal(normalized_content)
            if conditional_signal:
                print(f"[CONDITIONAL] ✓ Detected conditional order: {conditional_signal['symbol']} {conditional_signal['trigger_type']} ${conditional_signal['trigger_price']}")
                
                # Route to conditional order router if enabled (market-isolated)
                try:
                    from src.services.conditional_orders.router import conditional_order_router
                    
                    if conditional_order_router.is_enabled():
                        # Get broker from channel config - use channel's configured broker
                        broker = None
                        if channel_info:
                            # Check enabled_brokers FIRST (more specific - from Execution page)
                            if channel_info.get('enabled_brokers'):
                                try:
                                    import json
                                    enabled = channel_info.get('enabled_brokers')
                                    if isinstance(enabled, str):
                                        enabled = json.loads(enabled)
                                    if enabled and len(enabled) > 0:
                                        # Map uppercase names to proper broker names (including paper accounts)
                                        broker_map = {
                                            'WEBULL': 'Webull', 
                                            'ALPACA': 'Alpaca',
                                            'ALPACA_PAPER': 'Alpaca',
                                            'TASTYTRADE': 'Tastytrade',
                                            'TASTYTRADE_PAPER': 'Tastytrade',
                                            'IBKR': 'IBKR',
                                            'IBKR_PAPER': 'IBKR',
                                            'SCHWAB': 'Schwab',
                                            'UPSTOX': 'upstox',
                                            'ZERODHA': 'zerodha',
                                            'DHANQ': 'dhanq',
                                            'QUESTRADE': 'questrade'
                                        }
                                        first_broker = enabled[0].upper()
                                        broker = broker_map.get(first_broker, enabled[0])
                                        print(f"[CONDITIONAL] Using channel enabled_brokers[0]: {enabled[0]} -> {broker}")
                                except Exception as e:
                                    print(f"[CONDITIONAL] Error parsing enabled_brokers: {e}")
                            # Fall back to broker_override if enabled_brokers not set
                            elif channel_info.get('broker_override'):
                                broker = channel_info.get('broker_override')
                                print(f"[CONDITIONAL] Using channel broker_override: {broker}")
                        
                        # Reject if no broker is configured - do NOT fallback to a default
                        if not broker:
                            print(f"[CONDITIONAL] ❌ REJECTED: No broker configured for channel {message.channel.id}")
                            print(f"[CONDITIONAL] Please configure 'enabled_brokers' in the Execution page for this channel")
                            # Reactions disabled for conditional orders
                            return
                        print(f"[CONDITIONAL] Using broker: {broker}")
                        
                        order_id = conditional_order_router.create_order(
                            channel_id=str(message.channel.id),
                            parsed_signal=conditional_signal,
                            broker=broker
                        )
                        
                        if order_id:
                            print(f"[CONDITIONAL] ✓ Created conditional order #{order_id} - monitoring started")
                            # Reactions disabled for conditional orders
                        else:
                            print(f"[CONDITIONAL] ⚠️ Failed to create conditional order")
                    else:
                        print(f"[CONDITIONAL] ⚠️ Conditional order service disabled - signal ignored")
                except ImportError as e:
                    print(f"[CONDITIONAL] ⚠️ Conditional order service not available: {e}")
                except Exception as e:
                    print(f"[CONDITIONAL] ❌ Error creating conditional order: {e}")
                
                return  # Don't process as regular signal
        
        if opt is None and india_stock_signal is None and is_bracket_order_signal(normalized_content):
            bracket_signal = parse_bracket_order_signal(normalized_content)
            if bracket_signal:
                # Convert to stock signal format with bracket order fields
                india_stock_signal = bracket_signal
                # Add bracket order fields for execution
                if bracket_signal.get('stop_loss'):
                    india_stock_signal['stop_loss_price'] = bracket_signal['stop_loss']
                if bracket_signal.get('profit_targets') and len(bracket_signal['profit_targets']) > 0:
                    # Use first target as profit target
                    india_stock_signal['profit_target_price'] = bracket_signal['profit_targets'][0]
                print(f"[BRACKET ORDER] ✓ Detected stock bracket order: {bracket_signal['ticker']} @ {bracket_signal['entry_price']}, SL={bracket_signal.get('stop_loss')}, Targets={bracket_signal.get('profit_targets')}")
        
        # Check for Jacob format signal (ENTERED LONG/SHORT with bracket order data)
        if opt is None and india_stock_signal is None and is_jacob_signal(normalized_content):
            jacob_signal = parse_jacob_signal(normalized_content)
            if jacob_signal:
                # Convert to stock signal format with bracket order fields
                india_stock_signal = jacob_signal
                # Add bracket order fields for execution
                if jacob_signal.get('stop_loss'):
                    india_stock_signal['stop_loss_price'] = jacob_signal['stop_loss']
                if jacob_signal.get('profit_targets') and len(jacob_signal['profit_targets']) > 0:
                    # Use first target as profit target
                    india_stock_signal['profit_target_price'] = jacob_signal['profit_targets'][0]
                print(f"[JACOB] ✓ Detected stock bracket order: {jacob_signal['ticker']} @ {jacob_signal['entry_price']}, SL={jacob_signal.get('stop_loss')}, Targets={jacob_signal.get('profit_targets')}")
        
        if opt:
            # Apply tiered quantity defaults for BTO signals without qty from signal text
            if opt.get('action') == 'BTO' and opt.get('qty') is None and not opt.get('_qty_from_signal', False):
                # Tiered default: channel → global → max_position_size calculation (if enabled) → 1
                channel_default_qty = channel_info.get('default_quantity') if channel_info else None
                
                if channel_default_qty:
                    opt['qty'] = int(channel_default_qty)
                    print(f"[DEFAULT QTY] ✓ Using channel default: {opt['qty']} contracts")
                else:
                    # Check global default and max_position_size settings
                    _current_trading_settings = get_trading_settings()
                    global_default_qty = _current_trading_settings.get('global_default_quantity')
                    max_position_size_enabled = _current_trading_settings.get('max_position_size_enabled', True)
                    
                    if global_default_qty:
                        opt['qty'] = int(global_default_qty)
                        print(f"[DEFAULT QTY] ✓ Using global default: {opt['qty']} contracts")
                    elif max_position_size_enabled:
                        # Use max_position_size calculation only if enabled
                        max_position_size = _current_trading_settings['max_position_size']
                        price = opt.get('price')
                        if price and price > 0:
                            actual_cost_per_contract = price * 100
                            opt['qty'] = max(1, int(max_position_size / actual_cost_per_contract))
                            print(f"[DEFAULT QTY] ✓ Using max_position_size calculation: {opt['qty']} contracts (${max_position_size} / ${actual_cost_per_contract})")
                        else:
                            opt['qty'] = 1
                            print(f"[DEFAULT QTY] ✓ Fallback to 1 contract (no price available)")
                    else:
                        # Max position size disabled and no global default - fallback to 1
                        opt['qty'] = 1
                        print(f"[DEFAULT QTY] ⚠️ Max position size disabled, no global default set - using 1 contract")
            
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
            
            # Post Trade Summary for STC signals with PNL data (if enabled)
            if opt['action'] == 'STC' and opt.get('_pnl_result'):
                # Check if trade summary is enabled (global + per-channel)
                try:
                    trade_summary_enabled = db.is_trade_summary_enabled(str(message.channel.id))
                except Exception as e:
                    print(f"[PNL_TRACKER] Error checking trade_summary_enabled: {e}")
                    trade_summary_enabled = True  # Default to enabled on error
                
                if trade_summary_enabled:
                    pnl = opt['_pnl_result']
                    pnl_emoji = "🟢" if pnl['total_pnl'] >= 0 else "🔴"
                    summary_msg = (
                        f"**Trade Summary - {opt['symbol']}**\n"
                        f"{pnl_emoji} P/L: **${pnl['total_pnl']:+,.2f}** ({pnl['pnl_pct']:+.1f}%)\n"
                        f"📊 {pnl['total_qty']} contracts @ ${pnl['avg_entry']:.2f} → ${pnl['exit_price']:.2f}"
                    )
                    try:
                        await message.channel.send(summary_msg)
                        print(f"[PNL_TRACKER] ✓ Posted Trade Summary to channel {message.channel.id}")
                    except Exception as e:
                        print(f"[PNL_TRACKER] ❌ Failed to post Trade Summary: {e}")
                else:
                    print(f"[PNL_TRACKER] ⏭️ Trade Summary disabled for channel {message.channel.id}")
            
            # Execute if execute_enabled flag is True (category is for UI organization only)
            if execute_enabled:
                print(f"[ROUTE] EXECUTE enabled - adding to order queue", flush=True)
                print(f"[DEBUG] Queue size BEFORE put: {self.order_queue.qsize()}", flush=True)
            
            if execute_enabled:
                
                # Add EXECUTION position size percentage for dynamic qty calculation
                # Priority: Signal percentage (from Jacob/etc with _calculate_qty) > Channel percentage
                exec_position_size_pct = channel_info.get('position_size_pct') if channel_info else None
                print(f"[DEBUG] Channel position_size_pct from DB: {exec_position_size_pct} (type: {type(exec_position_size_pct).__name__})")
                
                # Check if signal already has percentage from parsing (e.g., Jacob "12.5% OF ACCOUNT")
                signal_has_pct = opt.get('_position_size_pct') is not None and opt.get('_calculate_qty', False)
                
                if signal_has_pct:
                    # Signal's percentage takes precedence - don't overwrite
                    print(f"[POSITION SIZE] ✓ Using signal's {opt['_position_size_pct']}% (overrides channel's {exec_position_size_pct}%)")
                elif exec_position_size_pct:
                    opt['_position_size_pct'] = float(exec_position_size_pct)
                    opt['_pct_from_channel'] = True  # Mark as channel-sourced for cap mode
                    print(f"[POSITION SIZE] ✓ Execution configured for {exec_position_size_pct}% of portfolio (channel setting)")
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
                    opt['_channel_name'] = channel_info.get('name', message.channel.name)
                    opt['_broker_override'] = channel_info.get('broker_override')
                    print(f"[DATABASE] ✓ Added channel_record_id={opt['channel_record_id']} for trade tracking")
                
                await self.order_queue.put(opt)
                print(f"[DEBUG] Queue size AFTER put: {self.order_queue.qsize()}", flush=True)
                print(f"[QUEUE] ✅ Signal successfully queued for LIVE execution", flush=True)
            
            # Paper trading - only queue separately if execute_enabled is False
            # If execute_enabled is True, multi-broker execution already handles paper brokers via enabled_brokers
            if track_enabled and not execute_enabled:
                paper_trade_enabled = channel_info.get('paper_trade_enabled', 0) if channel_info else 0
                if paper_trade_enabled:
                    print(f"[ROUTE] PAPER TRADING enabled - executing in PAPER mode")
                    
                    # Add TRACKING position size percentage for paper trading
                    # Priority: Signal percentage (from Jacob/etc with _calculate_qty) > Channel percentage
                    track_position_size_pct = channel_info.get('tracking_position_size_pct') if channel_info else None
                    print(f"[DEBUG] Channel tracking_position_size_pct from DB: {track_position_size_pct} (type: {type(track_position_size_pct).__name__})", flush=True)
                    
                    # Check if signal already has percentage from parsing
                    signal_has_pct = opt.get('_position_size_pct') is not None and opt.get('_calculate_qty', False)
                    
                    if signal_has_pct:
                        print(f"[POSITION SIZE] ✓ Using signal's {opt['_position_size_pct']}% (overrides channel's {track_position_size_pct}%)", flush=True)
                    elif track_position_size_pct:
                        opt['_position_size_pct'] = float(track_position_size_pct)
                        opt['_pct_from_channel'] = True
                        print(f"[POSITION SIZE] ✓ Tracking configured for {track_position_size_pct}% of portfolio (channel setting)", flush=True)
                    else:
                        print(f"[POSITION SIZE] ⚠️ No tracking_position_size_pct configured - using signal quantity as-is", flush=True)
                    
                    # Add paper trading flag and channel config to signal
                    opt['_paper_trade_mode'] = True
                    opt['_channel_paper_config'] = {
                        'profit_target_1_pct': channel_info.get('profit_target_1_pct'),
                        'profit_target_2_pct': channel_info.get('profit_target_2_pct'),
                        'profit_target_3_pct': channel_info.get('profit_target_3_pct'),
                        'profit_target_4_pct': channel_info.get('profit_target_4_pct'),
                        'profit_target_qty_1': channel_info.get('profit_target_qty_1'),
                        'profit_target_qty_2': channel_info.get('profit_target_qty_2'),
                        'profit_target_qty_3': channel_info.get('profit_target_qty_3'),
                        'profit_target_qty_4': channel_info.get('profit_target_qty_4'),
                        'stop_loss_pct': channel_info.get('stop_loss_pct'),
                        'trailing_stop_pct': channel_info.get('trailing_stop_pct'),
                        'trailing_activation_pct': channel_info.get('trailing_activation_pct'),
                        'leave_runner_enabled': channel_info.get('leave_runner_enabled'),
                        'leave_runner_pct': channel_info.get('leave_runner_pct'),
                        'trim_order_mode': channel_info.get('trim_order_mode', 'market'),
                        'trim_limit_offset': channel_info.get('trim_limit_offset', 0.01)
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
            
            # Legacy fallback - channel in config.ini CHANNEL_IDS list
            if not execute_enabled and not track_enabled and message.channel.id in CHANNEL_IDS:
                print(f"[ROUTE] Legacy channel - adding to order queue")
                await self.order_queue.put(opt)
            
            return
        
        # Use India stock signal if parsed, otherwise try US stock parser
        stk = india_stock_signal if india_stock_signal else parse_stock_signal(normalized_content)
        if stk:
            # Apply tiered quantity defaults for BTO signals without qty from signal text
            if stk.get('action') == 'BTO' and stk.get('qty') is None and not stk.get('_qty_from_signal', False):
                # Tiered default: channel → global → max_position_size calculation (if enabled) → 1
                channel_default_qty = channel_info.get('default_quantity') if channel_info else None
                
                if channel_default_qty:
                    stk['qty'] = int(channel_default_qty)
                    print(f"[DEFAULT QTY] ✓ Using channel default: {stk['qty']} shares")
                else:
                    # Check global default and max_position_size settings
                    _current_trading_settings = get_trading_settings()
                    global_default_qty = _current_trading_settings.get('global_default_quantity')
                    max_position_size_enabled = _current_trading_settings.get('max_position_size_enabled', True)
                    
                    if global_default_qty:
                        stk['qty'] = int(global_default_qty)
                        print(f"[DEFAULT QTY] ✓ Using global default: {stk['qty']} shares")
                    elif max_position_size_enabled:
                        # Use max_position_size calculation only if enabled
                        max_position_size = _current_trading_settings['max_position_size']
                        price = stk.get('price')
                        if price and price > 0:
                            stk['qty'] = max(1, int(max_position_size / price))
                            print(f"[DEFAULT QTY] ✓ Using max_position_size calculation: {stk['qty']} shares (${max_position_size} / ${price})")
                        else:
                            stk['qty'] = 1
                            print(f"[DEFAULT QTY] ✓ Fallback to 1 share (no price available)")
                    else:
                        # Max position size disabled and no global default - fallback to 1
                        stk['qty'] = 1
                        print(f"[DEFAULT QTY] ⚠️ Max position size disabled, no global default set - using 1 share")
            
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
                        
                        # Safety check: require BOTH execute_enabled AND category='EXECUTE'
                        is_exec_channel = channel_category == 'EXECUTE' if channel_category else False
                        if execute_enabled and is_exec_channel:
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
            
            # Execute if execute_enabled flag is True (category is for UI organization only)
            if execute_enabled:
                print(f"[ROUTE] EXECUTE enabled - adding to order queue")
                
                # Log bracket order info if present
                if stk.get('stop_loss_price') or stk.get('profit_target_price'):
                    print(f"[BRACKET ORDER] ✓ Including SL=${stk.get('stop_loss_price')} Target=${stk.get('profit_target_price')}")
                
                # Add EXECUTION position size percentage for dynamic qty calculation
                # Priority: Signal percentage (from Jacob/etc with _calculate_qty) > Channel percentage
                exec_position_size_pct = channel_info.get('position_size_pct') if channel_info else None
                
                # Check if signal already has percentage from parsing (e.g., Jacob "12.5% OF ACCOUNT")
                signal_has_pct = stk.get('_position_size_pct') is not None and stk.get('_calculate_qty', False)
                
                if signal_has_pct:
                    # Signal's percentage takes precedence - don't overwrite
                    print(f"[POSITION SIZE] ✓ Using signal's {stk['_position_size_pct']}% (overrides channel's {exec_position_size_pct}%)")
                elif exec_position_size_pct:
                    stk['_position_size_pct'] = float(exec_position_size_pct)
                    stk['_pct_from_channel'] = True  # Mark as channel-sourced for cap mode
                    print(f"[POSITION SIZE] Execution configured for {exec_position_size_pct}% of portfolio (channel setting)")
                
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
                    stk['_channel_name'] = channel_info.get('name', message.channel.name)
                    stk['_broker_override'] = channel_info.get('broker_override')
                    print(f"[DATABASE] ✓ Added channel_record_id={stk['channel_record_id']} for trade tracking")
                
                await self.order_queue.put(stk)
                print(f"[QUEUE] ✓ Signal queued for LIVE execution")
            
            # Paper trading - only queue separately if execute_enabled is False
            # If execute_enabled is True, multi-broker execution already handles paper brokers via enabled_brokers
            if track_enabled and not execute_enabled:
                paper_trade_enabled = channel_info.get('paper_trade_enabled', 0) if channel_info else 0
                if paper_trade_enabled:
                    print(f"[ROUTE] PAPER TRADING enabled - executing in PAPER mode")
                    
                    # Add TRACKING position size percentage for paper trading
                    # Priority: Signal percentage (from Jacob/etc with _calculate_qty) > Channel percentage
                    track_position_size_pct = channel_info.get('tracking_position_size_pct') if channel_info else None
                    
                    # Check if signal already has percentage from parsing
                    signal_has_pct = stk.get('_position_size_pct') is not None and stk.get('_calculate_qty', False)
                    
                    if signal_has_pct:
                        print(f"[POSITION SIZE] ✓ Using signal's {stk['_position_size_pct']}% (overrides channel's {track_position_size_pct}%)")
                    elif track_position_size_pct:
                        stk['_position_size_pct'] = float(track_position_size_pct)
                        stk['_pct_from_channel'] = True
                        print(f"[POSITION SIZE] Tracking configured for {track_position_size_pct}% of portfolio (channel setting)")
                    
                    # Add paper trading flag and channel config to signal
                    stk['_paper_trade_mode'] = True
                    stk['_channel_paper_config'] = {
                        'profit_target_1_pct': channel_info.get('profit_target_1_pct'),
                        'profit_target_2_pct': channel_info.get('profit_target_2_pct'),
                        'profit_target_3_pct': channel_info.get('profit_target_3_pct'),
                        'profit_target_4_pct': channel_info.get('profit_target_4_pct'),
                        'profit_target_qty_1': channel_info.get('profit_target_qty_1'),
                        'profit_target_qty_2': channel_info.get('profit_target_qty_2'),
                        'profit_target_qty_3': channel_info.get('profit_target_qty_3'),
                        'profit_target_qty_4': channel_info.get('profit_target_qty_4'),
                        'stop_loss_pct': channel_info.get('stop_loss_pct'),
                        'trailing_stop_pct': channel_info.get('trailing_stop_pct'),
                        'trailing_activation_pct': channel_info.get('trailing_activation_pct'),
                        'leave_runner_enabled': channel_info.get('leave_runner_enabled'),
                        'leave_runner_pct': channel_info.get('leave_runner_pct'),
                        'trim_order_mode': channel_info.get('trim_order_mode', 'market'),
                        'trim_limit_offset': channel_info.get('trim_limit_offset', 0.01)
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
        
        # CHANNEL MAPPING FORWARDING: Forward messages (including TRADE IDEA) to webhook destinations
        # This runs FIRST for mapped channels, regardless of execute/track status
        if is_mapped_source_channel:
            trade_idea = parse_trade_idea_signal(message.content)
            if trade_idea:
                webhook_msg = format_trade_idea_for_webhook(trade_idea)
                print(f"[CHANNEL MAP] ✓ Parsed TRADE IDEA: {trade_idea['ticker']} @ ${trade_idea['entry']}")
            else:
                webhook_msg = message.content.strip()
                print(f"[CHANNEL MAP] Forwarding raw message to webhook(s)")
            
            try:
                from gui_app import database as db
                import aiohttp
                
                all_webhooks = db.get_all_active_webhook_mappings()
                if all_webhooks:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                        posted_count = 0
                        for wh in all_webhooks:
                            webhook_url = wh.get('webhook_url')
                            if webhook_url:
                                try:
                                    async with session.post(webhook_url, json={"content": webhook_msg}) as resp:
                                        if resp.status in [200, 204]:
                                            posted_count += 1
                                except Exception as e:
                                    print(f"[CHANNEL MAP] ⚠️ Webhook post failed: {e}")
                        
                        if posted_count > 0:
                            print(f"[CHANNEL MAP] ✓ Posted to {posted_count} webhook(s)")
                        else:
                            print(f"[CHANNEL MAP] ⚠️ No webhooks succeeded")
                else:
                    print(f"[CHANNEL MAP] ⚠️ No active webhook mappings found")
            except Exception as e:
                print(f"[CHANNEL MAP] ❌ Error forwarding to webhooks: {e}")
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
                                    
                                    # Check if we should calculate qty from position sizing
                                    # ALWAYS calculate if:
                                    # 1. _calculate_qty is True (explicit calculation request)
                                    # 2. Signal text has percentage (pct_from_signal)
                                    # 3. Channel has position_size_pct configured (_pct_from_channel) - USE AS CALCULATION, NOT JUST CAP
                                    calculate_qty = signal.get('_calculate_qty', False)
                                    pct_from_signal = '_position_size_pct' in signal and not signal.get('_pct_from_channel', False)
                                    pct_from_channel = signal.get('_pct_from_channel', False)  # Channel wants calculated sizing
                                    
                                    if calculate_qty or pct_from_signal or pct_from_channel:
                                        # Calculate qty from position sizing percentage
                                        new_qty = min(pct_qty, affordable_qty)
                                        if new_qty == 0:
                                            _original_print(f"[{broker_name}] [POSITION SIZE] ❌ SKIPPING - Cannot afford 1 contract (cost: ${actual_cost:.0f}, budget: ${position_dollars:.0f}, buying power: ${effective_bp:.0f})")
                                            return {'success': False, 'error': f'Insufficient funds for 1 contract (need ${actual_cost:.0f}, have ${effective_bp:.0f})'}
                                        signal['qty'] = new_qty
                                        _original_print(f"[{broker_name}] [POSITION SIZE] ✓ Calculated qty: {new_qty} contracts ({position_size_pct}% = ${position_dollars:.0f} budget, ${actual_cost:.0f}/contract)")
                                    else:
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
                                    
                                    # Check if we should calculate qty from position sizing
                                    # ALWAYS calculate if:
                                    # 1. _calculate_qty is True (explicit calculation request)
                                    # 2. Signal text has percentage (pct_from_signal)
                                    # 3. Channel has position_size_pct configured (_pct_from_channel) - USE AS CALCULATION, NOT JUST CAP
                                    calculate_qty = signal.get('_calculate_qty', False)
                                    pct_from_signal = '_position_size_pct' in signal and not signal.get('_pct_from_channel', False)
                                    pct_from_channel = signal.get('_pct_from_channel', False)  # Channel wants calculated sizing
                                    
                                    if calculate_qty or pct_from_signal or pct_from_channel:
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
                    # Webull and other US brokers
                    _original_print(f"[{broker_name}] Placing option order: {signal['action']} {signal['qty']} {signal['symbol']} ${signal['strike']}{signal['opt_type']} {signal['expiry']} @ ${signal.get('price')}")
                    # Only pass lots parameter to Indian brokers (Upstox, Zerodha, DhanQ)
                    india_brokers = ['UPSTOX', 'ZERODHA', 'DHANQ']
                    if broker_name.upper() in india_brokers and signal.get('lots'):
                        result = await broker_instance.place_option_order(
                            action=signal['action'],
                            qty=signal['qty'],
                            symbol=signal['symbol'],
                            strike=signal['strike'],
                            opt_type=signal['opt_type'],
                            expiry_mmdd=signal['expiry'],
                            limit_price=signal.get('price'),
                            lots=signal.get('lots')
                        )
                    else:
                        # US brokers (Webull, etc.) - no lots parameter
                        result = await broker_instance.place_option_order(
                            action=signal['action'],
                            qty=signal['qty'],
                            symbol=signal['symbol'],
                            strike=signal['strike'],
                            opt_type=signal['opt_type'],
                            expiry_mmdd=signal['expiry'],
                            limit_price=signal.get('price')
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
                # Handle different broker parameter names for stocks
                # AlpacaBroker uses: symbol, action, quantity, price
                # WebullBroker uses: action, qty, symbol, limit_price
                if broker_name == 'ALPACA_PAPER' or 'ALPACA' in broker_name.upper():
                    result = await broker_instance.place_stock_order(
                        symbol=signal['symbol'],
                        action=signal['action'],
                        quantity=signal['qty'],
                        price=signal.get('price')  # None for market orders
                    )
                else:
                    # Webull and other legacy brokers (uses qty, not quantity)
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
            
            # Save pending order metadata for execution tracking (only for BTO orders)
            if resp.get('success') or resp.get('orderId'):
                order_id = resp.get('orderId') or resp.get('order_id')
                if order_id and signal.get('action', '').upper() in ('BTO', 'BUY'):
                    try:
                        from gui_app.database import save_pending_order_metadata
                        from datetime import datetime
                        save_pending_order_metadata(
                            broker=broker_name,
                            broker_order_id=str(order_id),
                            channel_id=str(signal.get('channel_id', 'UNKNOWN')),
                            message_id=str(signal.get('message_id', '')),
                            symbol=signal.get('symbol', ''),
                            asset_type=signal.get('asset', 'option'),
                            action=signal.get('action', 'BTO'),
                            quantity=signal.get('qty', 1),
                            signal_price=signal.get('price'),
                            analyst_qty=signal.get('original_qty') or signal.get('qty'),
                            sizing_mode=signal.get('sizing_mode'),
                            sizing_details=signal.get('sizing_details'),
                            signal_detected_at=signal.get('detected_at'),
                            signal_parsed_at=signal.get('parsed_at'),
                            signal_lot_id=signal.get('lot_id')
                        )
                    except Exception as meta_err:
                        _original_print(f"[EXEC] Warning: Could not save order metadata: {meta_err}")
            
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
    
    async def telegram_signal_bridge(self):
        """
        Bridge task that polls signals from the thread-safe Telegram queue
        and pushes them to the async order queue for processing.
        This enables cross-thread signal passing from Telegram to the worker.
        """
        global _telegram_signal_queue
        
        if _telegram_signal_queue is None:
            return
        
        _original_print("[TELEGRAM BRIDGE] ✓ Started - bridging Telegram signals to order queue", flush=True)
        
        while True:
            try:
                try:
                    import queue as std_queue
                    signal = _telegram_signal_queue.get(timeout=1.0)
                    
                    _original_print(f"[TELEGRAM BRIDGE] Received signal: {signal.get('action')} {signal.get('symbol')}", flush=True)
                    
                    if signal.get('_conditional_order') and signal.get('market') == 'INDIA':
                        await self._route_telegram_conditional_order(signal)
                    else:
                        await self.order_queue.put(signal)
                        _original_print(f"[TELEGRAM BRIDGE] ✓ Signal forwarded to order queue", flush=True)
                    
                except std_queue.Empty:
                    pass
                
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                _original_print("[TELEGRAM BRIDGE] Shutdown requested", flush=True)
                break
            except Exception as e:
                _original_print(f"[TELEGRAM BRIDGE] Error: {e}", flush=True)
                await asyncio.sleep(1.0)
    
    async def _route_telegram_conditional_order(self, signal):
        """Route Telegram conditional order to market-isolated conditional order router."""
        try:
            from src.services.conditional_orders.router import conditional_order_router
            
            symbol = signal.get('symbol')
            strike = signal.get('strike')
            opt_type = signal.get('opt_type', 'C')
            trigger_price = signal.get('trigger_price') or signal.get('price')
            trigger_type = signal.get('trigger_type', 'over')
            expiry = signal.get('expiry')
            stop_loss = signal.get('stop_loss')
            profit_targets = signal.get('profit_targets')
            
            _original_print(f"[TELEGRAM CONDITIONAL] ✓ Detected conditional order: {symbol} {strike}{opt_type} {trigger_type} ₹{trigger_price}", flush=True)
            
            if not conditional_order_router.is_enabled():
                _original_print("[TELEGRAM CONDITIONAL] ⚠️ Conditional order service DISABLED - executing immediately", flush=True)
                await self.order_queue.put(signal)
                return
            
            current_price = None
            try:
                if hasattr(self, 'upstox_broker') and self.upstox_broker:
                    result = await self.upstox_broker._lookup_instrument_key(
                        symbol, float(strike) if strike else 0, opt_type, expiry
                    )
                    instrument_key = result[0] if isinstance(result, tuple) else result
                    if instrument_key:
                        current_price = await self.upstox_broker.get_ltp(instrument_key)
                    if current_price:
                        _original_print(f"[TELEGRAM CONDITIONAL] Current LTP: ₹{current_price:.2f}", flush=True)
                        
                        already_triggered = False
                        if trigger_type == 'over' and current_price >= float(trigger_price):
                            already_triggered = True
                            _original_print(f"[TELEGRAM CONDITIONAL] ⚠️ WARNING: Price ₹{current_price:.2f} already ABOVE trigger ₹{trigger_price}", flush=True)
                        elif trigger_type == 'under' and current_price <= float(trigger_price):
                            already_triggered = True
                            _original_print(f"[TELEGRAM CONDITIONAL] ⚠️ WARNING: Price ₹{current_price:.2f} already BELOW trigger ₹{trigger_price}", flush=True)
                        
                        if already_triggered:
                            _original_print(f"[TELEGRAM CONDITIONAL] Creating order anyway - it will trigger immediately", flush=True)
            except Exception as e:
                _original_print(f"[TELEGRAM CONDITIONAL] Could not check current price: {e}", flush=True)
            
            channel_id = str(signal.get('channel_id', ''))
            broker_primary = signal.get('_broker_list', ['UPSTOX'])[0] if signal.get('_broker_list') else 'UPSTOX'
            
            # For India markets, treat channel default_quantity as number of LOTS
            signal_qty = signal.get('qty')
            signal_lots = signal.get('lots')
            
            # If lots not explicitly in signal but qty is set (from channel default), treat qty as lots
            if signal_lots is None and signal_qty is not None:
                signal_lots = int(signal_qty)
                _original_print(f"[TELEGRAM CONDITIONAL] Using qty={signal_qty} as lots for India market", flush=True)
            elif signal_lots is None:
                # Check channel default_quantity - treat as lots for India
                try:
                    from gui_app.database import get_telegram_channel
                    telegram_channel_info = get_telegram_channel(channel_id) if channel_id else None
                    channel_default_qty = telegram_channel_info.get('default_quantity') if telegram_channel_info else None
                    if channel_default_qty:
                        signal_lots = int(channel_default_qty)
                        _original_print(f"[TELEGRAM CONDITIONAL] Using channel default_quantity={channel_default_qty} as lots", flush=True)
                    else:
                        signal_lots = 1
                except Exception as e:
                    _original_print(f"[TELEGRAM CONDITIONAL] Could not get channel default_quantity: {e}", flush=True)
                    signal_lots = 1
            
            conditional_signal = {
                'symbol': symbol,
                'strike': float(strike) if strike else None,
                'opt_type': opt_type[0].upper() if opt_type else 'C',
                'trigger_price': float(trigger_price) if trigger_price else 0,
                'trigger_type': trigger_type,
                'expiry': expiry,
                'stop_loss': stop_loss,
                'stop_loss_value': float(stop_loss) if stop_loss else None,
                'stop_loss_type': 'fixed' if stop_loss else None,
                'profit_targets': profit_targets or [],
                'qty': signal_qty,
                'lots': signal_lots,
                'lot_size': signal.get('lot_size'),
                'market': 'INDIA',
                'asset_type': 'option',
                'original_message': signal.get('raw_message', ''),
                'message_id': signal.get('message_id'),
            }
            
            order_id = conditional_order_router.create_order(
                channel_id=channel_id,
                parsed_signal=conditional_signal,
                broker=broker_primary
            )
            
            if order_id:
                _original_print(f"[TELEGRAM CONDITIONAL] ✓ Created conditional order #{order_id}", flush=True)
                _original_print(f"[TELEGRAM CONDITIONAL]   Symbol: {symbol} {strike}{opt_type} exp={expiry}", flush=True)
                _original_print(f"[TELEGRAM CONDITIONAL]   Trigger: {trigger_type.upper()} ₹{trigger_price}", flush=True)
                if stop_loss:
                    _original_print(f"[TELEGRAM CONDITIONAL]   SL: ₹{stop_loss}", flush=True)
                if profit_targets:
                    _original_print(f"[TELEGRAM CONDITIONAL]   Targets: {profit_targets}", flush=True)
                _original_print(f"[TELEGRAM CONDITIONAL] ✓ Order #{order_id} routed to INDIA service", flush=True)
            else:
                _original_print(f"[TELEGRAM CONDITIONAL] ❌ Failed to create conditional order", flush=True)
                await self.order_queue.put(signal)
                
        except Exception as e:
            _original_print(f"[TELEGRAM CONDITIONAL] ❌ Error routing conditional order: {e}", flush=True)
            import traceback
            traceback.print_exc()
            _original_print(f"[TELEGRAM CONDITIONAL] Falling back to immediate execution", flush=True)
            await self.order_queue.put(signal)
    
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
                        # DhanQ (India - Always LIVE): 'dhanq', 'DHANQ'
                        elif broker_name_lower == 'dhanq' and self.dhanq_broker and self.dhanq_broker.connected:
                            broker_instance = self.dhanq_broker
                            _original_print(f"[MULTI-BROKER] Using DhanQ LIVE broker (India)")
                        # Upstox (India - Always LIVE): 'upstox', 'UPSTOX'
                        elif broker_name_lower == 'upstox' and self.upstox_broker and self.upstox_broker.connected:
                            broker_instance = self.upstox_broker
                            _original_print(f"[MULTI-BROKER] Using Upstox LIVE broker (India)")
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
                    # Check success flag OR if orderId has a truthy value (not just key existence)
                    successes = [r for r in responses if r.get('success') or r.get('orderId')]
                    failures = [r for r in responses if not (r.get('success') or r.get('orderId'))]
                    
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
                                                        'received_at': datetime.now(),
                                                        'exit_reason': signal.get('exit_reason') or signal.get('risk_trigger', 'RISK_EXIT')
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
                    
                    # CHECK: Skip live execution if no broker is selected for this channel
                    # Risk management orders are exempt (they need to close positions on whatever broker holds them)
                    is_risk_order = signal.get('_risk_management_order', False)
                    has_broker_config = bool(signal.get('_enabled_brokers')) or bool(signal.get('_broker_override'))
                    
                    if not is_paper_trade and not is_risk_order and not has_broker_config:
                        channel_name = signal.get('_channel_name', 'Unknown')
                        _original_print(f"[EXECUTION] ⚠️ SKIPPING - No broker selected for channel '{channel_name}'")
                        _original_print(f"[EXECUTION] Configure a broker in the Execution page to enable trading for this channel")
                        # Save to database as skipped for tracking
                        try:
                            from gui_app.database import save_signal
                            signal_copy = signal.copy()
                            signal_copy['_skipped'] = True
                            signal_copy['_skip_reason'] = 'No broker configured'
                            save_signal(signal_copy)
                        except Exception as e:
                            _original_print(f"[EXECUTION] Failed to log skipped signal: {e}")
                        continue
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
                        
                        # Select broker based on channel override OR risk management broker routing
                        # Risk management orders have 'broker' set directly (e.g., 'Webull' for risk exits)
                        is_risk_order = signal.get('_risk_management_order', False)
                        if is_risk_order and signal.get('broker'):
                            broker_override = signal.get('broker', '').lower()
                            _original_print(f"[LIVE TRADE] Risk order using broker: {broker_override}")
                        else:
                            broker_override = signal.get('_broker_override', '').lower() if signal.get('_broker_override') else ''
                        live_broker = None
                        broker_name_used = None
                        
                        if broker_override:
                            if broker_override == 'upstox' and hasattr(self, 'upstox_broker') and self.upstox_broker and self.upstox_broker.connected:
                                live_broker = self.upstox_broker
                                broker_name_used = 'Upstox'
                                _original_print(f"[LIVE TRADE] Using channel broker override: Upstox (India)")
                            elif broker_override == 'dhanq' and hasattr(self, 'dhanq_broker') and self.dhanq_broker and self.dhanq_broker.connected:
                                live_broker = self.dhanq_broker
                                broker_name_used = 'DhanQ'
                                _original_print(f"[LIVE TRADE] Using channel broker override: DhanQ (India)")
                            elif broker_override == 'zerodha' and hasattr(self, 'zerodha_broker') and self.zerodha_broker and getattr(self.zerodha_broker, 'connected', False):
                                live_broker = self.zerodha_broker
                                broker_name_used = 'Zerodha'
                                _original_print(f"[LIVE TRADE] Using channel broker override: Zerodha (India)")
                            elif broker_override in ('tastytrade', 'tasty') and hasattr(self, 'tastytrade_broker') and self.tastytrade_broker and self.tastytrade_broker.connected:
                                live_broker = self.tastytrade_broker
                                broker_name_used = 'Tastytrade'
                                _original_print(f"[LIVE TRADE] Using channel broker override: Tastytrade")
                            elif broker_override in ('robinhood', 'rh') and hasattr(self, 'robinhood_broker') and self.robinhood_broker and self.robinhood_broker.connected:
                                live_broker = self.robinhood_broker
                                broker_name_used = 'Robinhood'
                                _original_print(f"[LIVE TRADE] Using channel broker override: Robinhood")
                            elif broker_override == 'ibkr' and hasattr(self, 'ibkr_broker') and self.ibkr_broker and self.ibkr_broker.connected:
                                live_broker = self.ibkr_broker
                                broker_name_used = 'IBKR'
                                _original_print(f"[LIVE TRADE] Using channel broker override: Interactive Brokers")
                            elif broker_override in ('alpaca', 'alpaca_paper') and hasattr(self, 'paper_broker') and self.paper_broker and self.paper_broker.connected:
                                live_broker = self.paper_broker
                                broker_name_used = 'Alpaca'
                                _original_print(f"[LIVE TRADE] Using channel broker override: Alpaca")
                            elif broker_override == 'webull' and hasattr(self, 'broker') and self.broker and getattr(self.broker, 'connected', True):
                                live_broker = self.broker
                                broker_name_used = 'Webull'
                                _original_print(f"[LIVE TRADE] Using channel broker override: Webull")
                            else:
                                _original_print(f"[LIVE TRADE] ❌ REJECTED: Broker override '{broker_override}' not available or not connected")
                                _original_print(f"[LIVE TRADE] Please check broker configuration in Settings")
                                continue
                        else:
                            _original_print(f"[LIVE TRADE] ❌ REJECTED: No broker configured for this channel")
                            _original_print(f"[LIVE TRADE] Please configure 'enabled_brokers' in the Execution page")
                            continue
                        
                        # Position sizing calculation for conditional orders with _calculate_qty flag
                        position_size_pct = signal.get('_position_size_pct')
                        if position_size_pct and signal.get('_calculate_qty') and signal['action'] == 'BTO':
                            try:
                                _original_print(f"[LIVE TRADE] Calculating position size ({position_size_pct}% of portfolio)...")
                                
                                if hasattr(live_broker, 'get_account_info'):
                                    import inspect
                                    account_info_result = live_broker.get_account_info()
                                    # Handle both sync and async get_account_info methods
                                    if inspect.iscoroutine(account_info_result):
                                        account_info = await account_info_result
                                    else:
                                        account_info = account_info_result
                                    
                                    if account_info:
                                        if signal['asset'] == 'option':
                                            buying_power = account_info.get('options_buying_power') or account_info.get('buying_power', 0)
                                        else:
                                            buying_power = account_info.get('buying_power', 0)
                                        
                                        if buying_power > 0:
                                            budget = buying_power * (position_size_pct / 100)
                                            price = signal.get('price') or 1.0
                                            
                                            if signal['asset'] == 'option':
                                                actual_cost = price * 100
                                            else:
                                                actual_cost = price
                                            
                                            if actual_cost > 0:
                                                calculated_qty = max(1, int(budget / actual_cost))
                                                original_qty = signal.get('qty', 1)
                                                signal['qty'] = calculated_qty
                                                _original_print(f"[LIVE TRADE] Position size: ${budget:.2f} budget, ${actual_cost:.2f}/unit → {calculated_qty} qty (was {original_qty})")
                            except Exception as e:
                                _original_print(f"[LIVE TRADE] ⚠️ Position sizing error: {e}, using qty={signal.get('qty', 1)}")
                                import traceback
                                traceback.print_exc()
                        
                        # Check if we should use bracket orders (stocks with stop loss or profit target)
                        use_bracket = (
                            signal['asset'] == 'stock' and 
                            signal['action'] == 'BTO' and
                            (signal.get('stop_loss_price') or signal.get('profit_target_price')) and
                            hasattr(live_broker, 'place_bracket_order')
                        )
                        
                        # Retry configuration for transient errors
                        max_retries = 3
                        retry_delay = 2  # seconds
                        
                        if use_bracket:
                            # Use bracket order (entry + stop + target all at once)
                            _original_print(f"[LIVE TRADE] Using BRACKET order (entry + risk management) via {broker_name_used}...")
                            if signal.get('stop_loss_price'):
                                _original_print(f"[LIVE TRADE]   Stop Loss: ${signal['stop_loss_price']}")
                            if signal.get('profit_target_price'):
                                _original_print(f"[LIVE TRADE]   Profit Target: ${signal['profit_target_price']}")
                            
                            result = await live_broker.place_bracket_order(
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
                            _original_print(f"[LIVE TRADE] Calling {broker_name_used}.place_option_order()...", flush=True)
                            
                            # Build order kwargs
                            order_kwargs = {
                                'action': signal['action'],
                                'symbol': signal['symbol'],
                                'strike': signal['strike'],
                                'opt_type': signal['opt_type'],
                                'expiry_mmdd': signal['expiry'],
                                'limit_price': signal.get('price')  # None for market orders
                            }
                            
                            # For India brokers, determine lots to use
                            if broker_name_used in ('Upstox', 'DhanQ', 'Zerodha'):
                                # Priority:
                                # 1) Signal's explicit lots (BUY 1, BUY 2 → lots=1, lots=2)
                                # 2) Calculate from channel's position_size_pct (if no explicit qty)
                                # 3) Default to 1 lot
                                
                                signal_has_explicit_qty = signal.get('_qty_from_signal', False)
                                signal_lots = signal.get('lots')
                                
                                if signal_has_explicit_qty and signal_lots:
                                    # Signal explicitly said "BUY 1" or "BUY 2" - respect that
                                    order_kwargs['lots'] = signal_lots
                                    _original_print(f"[LIVE TRADE] India broker - using {signal_lots} lot(s) from signal (explicit)")
                                else:
                                    # No explicit qty in signal - check for channel position_size_pct
                                    calculated_lots = None
                                    position_size_pct = signal.get('_position_size_pct')
                                    
                                    if position_size_pct and signal.get('price'):
                                        try:
                                            account_info = await live_broker.get_account_info()
                                            buying_power = account_info.get('buying_power', 0) or account_info.get('available_margin', 0)
                                            
                                            if buying_power > 0:
                                                position_value = buying_power * (float(position_size_pct) / 100)
                                                option_price = float(signal['price'])
                                                estimated_lots = max(1, int(position_value / (option_price * 50)))
                                                calculated_lots = estimated_lots
                                                _original_print(f"[POSITION SIZE] ✓ Channel {position_size_pct}% of ₹{buying_power:.0f} = ₹{position_value:.0f} → ~{calculated_lots} lot(s)")
                                        except Exception as e:
                                            _original_print(f"[POSITION SIZE] ⚠️ Could not fetch buying power: {e}, using signal qty")
                                    
                                    if calculated_lots:
                                        order_kwargs['lots'] = calculated_lots
                                        _original_print(f"[LIVE TRADE] India broker - using {calculated_lots} lot(s) from channel position size")
                                    elif signal_lots:
                                        order_kwargs['lots'] = signal_lots
                                        _original_print(f"[LIVE TRADE] India broker - using {signal_lots} lot(s) from signal")
                                    else:
                                        order_kwargs['lots'] = 1
                                        _original_print(f"[LIVE TRADE] India broker - defaulting to 1 lot")
                            else:
                                order_kwargs['qty'] = signal['qty']
                            
                            # Retry loop for transient errors
                            for attempt in range(max_retries):
                                resp = await live_broker.place_option_order(**order_kwargs)
                                _original_print(f"[LIVE TRADE] Broker response received: {resp}", flush=True)
                                
                                # Check if it's a transient error that should be retried
                                # Handle both dict and OrderResult dataclass responses
                                resp_success = resp.success if hasattr(resp, 'success') else resp.get('success') if isinstance(resp, dict) else False
                                resp_msg = resp.message if hasattr(resp, 'message') else resp.get('msg', '') if isinstance(resp, dict) else ''
                                
                                if resp and not resp_success and resp_msg:
                                    error_msg = str(resp_msg).lower()
                                    is_transient = 'system is busy' in error_msg or 'try again' in error_msg or 'timeout' in error_msg
                                    
                                    if is_transient and attempt < max_retries - 1:
                                        _original_print(f"[LIVE TRADE] ⏳ Transient error, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})...", flush=True)
                                        await asyncio.sleep(retry_delay)
                                        retry_delay *= 2  # Exponential backoff
                                        continue
                                
                                # Success or non-transient error, break out
                                break
                        else:
                            _original_print(f"[LIVE TRADE] Calling {broker_name_used}.place_stock_order()...", flush=True)
                            resp = await live_broker.place_stock_order(
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
                    
                    # Update conditional order status to ERROR if this was a conditional order
                    cond_order_id = signal.get('_conditional_order_id')
                    if cond_order_id:
                        try:
                            from gui_app.database import update_conditional_order_status
                            update_conditional_order_status(
                                cond_order_id, 
                                'ERROR', 
                                event='BROKER_REJECTED',
                                error_message=error_msg[:200]
                            )
                            _original_print(f"[CONDITIONAL] ❌ Order #{cond_order_id} marked as ERROR: {error_msg[:100]}")
                        except Exception as e:
                            _original_print(f"[CONDITIONAL] ⚠️ Could not update order status: {e}")
                    
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
                    # Update conditional order status to EXECUTED if this was a conditional order
                    cond_order_id = signal.get('_conditional_order_id')
                    if cond_order_id:
                        try:
                            from gui_app.database import update_conditional_order_status
                            update_conditional_order_status(cond_order_id, 'EXECUTED', event='BROKER_CONFIRMED')
                            _original_print(f"[CONDITIONAL] ✓ Order #{cond_order_id} marked as EXECUTED")
                        except Exception as e:
                            _original_print(f"[CONDITIONAL] ⚠️ Could not update order status: {e}")
                    
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
                    
                    # Track pending risk order - tier will be marked after fill confirmation
                    if signal.get('_risk_management_order') and signal.get('_tier_to_mark'):
                        try:
                            tier_to_mark = signal['_tier_to_mark']
                            position_key = signal.get('_position_key')
                            is_partial = signal.get('_is_partial', True)
                            qty = signal.get('qty', 1)
                            
                            # Extract order_id from response
                            order_id = None
                            if isinstance(resp, dict):
                                order_id = resp.get('orderId')
                            elif hasattr(resp, 'order_id'):
                                order_id = resp.order_id
                            
                            if position_key and hasattr(self, 'risk_manager') and self.risk_manager:
                                if order_id:
                                    # Track as pending - tier marked after fill confirmation
                                    self.risk_manager.cache.add_pending_order(
                                        position_key, str(order_id), tier_to_mark, qty
                                    )
                                    _original_print(f"[RISK] 📋 Tier {tier_to_mark} order PENDING fill confirmation: {order_id}")
                                    # Store order info for reconciliation
                                    signal['_pending_order_id'] = str(order_id)
                                else:
                                    # No order_id means immediate fill (some brokers)
                                    self.risk_manager.cache.mark_tier_hit(position_key, tier_to_mark)
                                    if tier_to_mark == 1 and not is_partial:
                                        self.risk_manager.cache.set_all_tiers_hit(position_key)
                                    _original_print(f"[RISK] ✓ Tier {tier_to_mark} marked as hit (immediate fill)")
                        except Exception as e:
                            _original_print(f"[RISK] ⚠️ Could not track pending order: {e}")
                    
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
                                            'received_at': datetime.now(),
                                            'exit_reason': signal.get('exit_reason') or signal.get('risk_trigger', 'RISK_EXIT')
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
            error_msg = str(e)
            if 'expected token to be a str' in error_msg or 'NoneType' in error_msg:
                _original_print("[Discord Thread] Discord token not configured - this is expected if you haven't set it up yet")
                _original_print("[Discord Thread] Configure your Discord token in Settings > Discord to enable signal reading")
            else:
                _original_print(f"[Discord Thread ERROR] Bot crashed: {e}")
                log_error_to_db('discord_connection', f"Discord bot crashed: {str(e)}", 
                               'DiscordClient', 'critical', 'Check Discord token and network connection')
                import traceback
                traceback.print_exc()
            _discord_error_queue.put(e)
            raise
    
    try:
        # Run Discord bot with dedicated event loop via asyncio.run()
        asyncio.run(discord_main())
    except KeyboardInterrupt:
        _original_print("\n[Discord Thread] Bot stopped by user (Ctrl+C)")
    except Exception as e:
        error_msg = str(e)
        if 'expected token to be a str' in error_msg or 'NoneType' in error_msg:
            _original_print("[Discord Thread] Discord not configured - set your token in Settings to enable")
        else:
            _original_print(f"[Discord Thread] Exception escaped asyncio.run(): {e}")
        _discord_error_queue.put(e)
    finally:
        _original_print("[Discord Thread] Shutting down...")
        _discord_shutdown_event.set()


_telegram_ready_event = None
_telegram_shutdown_event = None
_telegram_signal_queue = None
_telegram_listener = None

def get_telegram_listener():
    """Get the Telegram listener instance (for API access to reload configs)."""
    return _telegram_listener

def run_telegram_bot_thread():
    """
    Runs Telegram listener in its own dedicated thread with isolated asyncio event loop.
    Uses Telethon to connect as a user account to read trading signals.
    Signals are passed via a thread-safe queue.Queue to avoid cross-loop issues.
    """
    global _telegram_ready_event, _telegram_shutdown_event, _telegram_signal_queue, _telegram_listener
    
    async def telegram_main():
        """Async entrypoint for Telegram listener with proper lifecycle"""
        try:
            _original_print("[Telegram Thread] Starting Telegram listener...")
            
            from gui_app.database import get_telegram_settings, get_telegram_channels
            settings = get_telegram_settings()
            
            if not settings.get('enabled'):
                _original_print("[Telegram Thread] Telegram integration is disabled in settings")
                _telegram_ready_event.set()
                return
            
            api_id = settings.get('api_id')
            api_hash = settings.get('api_hash')
            phone_number = settings.get('phone_number')
            session_string = settings.get('session_string')
            
            if not api_id or not api_hash:
                _original_print("[Telegram Thread] Telegram API credentials not configured")
                _telegram_ready_event.set()
                return
            
            from src.telegram_client import TelegramListener
            from src.signals.parser import (
                parse_india_option_signal, parse_india_stock_signal,
                parse_option_signal, parse_stock_signal
            )
            
            global _telegram_listener
            listener = TelegramListener(
                api_id=api_id,
                api_hash=api_hash,
                phone_number=phone_number,
                session_string=session_string,
            )
            _telegram_listener = listener
            
            if _telegram_signal_queue is not None:
                listener.set_sync_signal_queue(_telegram_signal_queue)
                _original_print("[Telegram Thread] Using thread-safe signal queue")
            
            if parse_option_signal:
                listener.register_parser('option_signal', parse_option_signal)
            if parse_stock_signal:
                listener.register_parser('stock_signal', parse_stock_signal)
            listener.register_parser('india_option_signal', parse_india_option_signal)
            listener.register_parser('india_stock_signal', parse_india_stock_signal)
            
            _original_print(f"[Telegram Thread] Loading channels from database...")
            listener.load_channels_from_db()
            
            _original_print(f"[Telegram Thread] Attempting connection with api_id={api_id}, has_session={bool(session_string)}")
            connected = await listener.connect()
            _original_print(f"[Telegram Thread] Connection result: {connected}")
            if not connected:
                _original_print("[Telegram Thread] Could not connect to Telegram - check logs above for details")
                _telegram_ready_event.set()
                return
            
            _original_print("[Telegram Thread] ✓ Telegram listener connected")
            _telegram_ready_event.set()
            
            await listener.start_listening()
            
        except ImportError as e:
            _original_print(f"[Telegram Thread] Telethon not available: {e}")
            _telegram_ready_event.set()
        except Exception as e:
            _original_print(f"[Telegram Thread ERROR] Listener crashed: {e}")
            import traceback
            traceback.print_exc()
            _telegram_ready_event.set()
    
    try:
        asyncio.run(telegram_main())
    except KeyboardInterrupt:
        _original_print("\n[Telegram Thread] Stopped by user (Ctrl+C)")
    except Exception as e:
        _original_print(f"[Telegram Thread] Exception escaped asyncio.run(): {e}")
    finally:
        _original_print("[Telegram Thread] Shutting down...")
        _telegram_shutdown_event.set()


def run_bot_startup(progress_callback=None):
    """
    Run the full bot startup sequence.
    progress_callback: Optional function to report progress (step, message)
    """
    import time
    global _discord_ready_event, _discord_shutdown_event, _discord_error_queue
    global _telegram_ready_event, _telegram_shutdown_event, _telegram_signal_queue
    
    startup_start = time.time()
    step_times = {}
    
    def report_progress(step, message):
        step_times[step] = time.time()
        elapsed = time.time() - startup_start
        if progress_callback:
            progress_callback(step, message)
        if is_debug_mode():
            _original_print(f"[STARTUP] [{elapsed:.2f}s] Step {step}: {message}")
        else:
            _original_print(f"[STARTUP] {message}")
    
    report_progress(1, "Loading configuration...")
    
    # Initialize global lifecycle events
    _discord_ready_event = threading.Event()
    _discord_shutdown_event = threading.Event()
    _discord_error_queue = queue.Queue()
    _telegram_ready_event = threading.Event()
    _telegram_shutdown_event = threading.Event()
    _telegram_signal_queue = queue.Queue()
    
    report_progress(2, "Running diagnostics...")
    
    # Run startup diagnostics
    try:
        from src.diagnostics import run_all_checks
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
    
    report_progress(3, "Starting web control panel...")
    
    # Start Flask GUI server
    gui_port = 5000
    try:
        import sys
        from pathlib import Path
        parent_dir = Path(__file__).parent.parent
        if str(parent_dir) not in sys.path:
            sys.path.insert(0, str(parent_dir))
        
        from gui_app import start_gui_server, get_gui_port
        gui_port = get_gui_port()
        gui_thread, gui_port = start_gui_server()
        _original_print(f"[GUI] ✓ Web control panel started on port {gui_port}")
    except Exception as e:
        _original_print(f"[GUI] ⚠️  Failed to start web GUI: {e}")
        _original_print("[GUI] Bot will continue without web interface")
    
    report_progress(4, "Connecting to Discord...")
    
    # Start Discord bot in dedicated thread
    discord_thread = threading.Thread(target=run_discord_bot_thread, name="DiscordBot", daemon=False)
    discord_thread.start()
    _original_print("[MAIN] ✓ Discord bot started in dedicated thread")
    
    report_progress(5, "Starting Telegram listener...")
    
    # Start Telegram listener in dedicated thread (if enabled)
    telegram_thread = None
    try:
        from gui_app.database import get_telegram_settings
        telegram_settings = get_telegram_settings()
        if telegram_settings.get('enabled') and telegram_settings.get('api_id') and telegram_settings.get('api_hash'):
            telegram_thread = threading.Thread(target=run_telegram_bot_thread, name="TelegramBot", daemon=False)
            telegram_thread.start()
            _original_print("[MAIN] ✓ Telegram listener started in dedicated thread")
        else:
            _original_print("[MAIN] Telegram integration not enabled or not configured")
    except Exception as e:
        _original_print(f"[MAIN] Telegram startup skipped: {e}")
    
    report_progress(6, "Waiting for Discord connection...")
    
    # Wait for Discord to be ready (with timeout)
    if _discord_ready_event.wait(timeout=30):
        _original_print("[MAIN] ✓ Discord bot is ready and connected")
        report_progress(8, "Discord connected!")
    else:
        _original_print("[MAIN] ⚠️  Discord bot did not connect within 30 seconds")
        report_progress(8, "Discord connection timeout")
    
    report_progress(9, "Waiting for Telegram...")
    
    # Wait for Telegram if it was started
    if telegram_thread:
        if _telegram_ready_event.wait(timeout=15):
            _original_print("[MAIN] ✓ Telegram listener ready")
        else:
            _original_print("[MAIN] ⚠️  Telegram listener did not connect within 15 seconds")
    
    total_time = time.time() - startup_start
    report_progress(10, f"Ready! (startup took {total_time:.1f}s)")
    
    # Register with lifecycle manager for proper stop/restart
    try:
        from src.services.lifecycle_manager import get_lifecycle_manager
        lifecycle = get_lifecycle_manager()
        lifecycle.register_threads(
            discord_thread=discord_thread,
            telegram_thread=telegram_thread,
            discord_shutdown=_discord_shutdown_event,
            telegram_shutdown=_telegram_shutdown_event,
            gui_port=gui_port
        )
        _original_print("[LIFECYCLE] ✓ Bot registered with lifecycle manager")
    except Exception as e:
        _original_print(f"[LIFECYCLE] Warning: Could not register with lifecycle manager: {e}")
    
    # Debug: Print startup timing breakdown
    if is_debug_mode() and len(step_times) > 1:
        _original_print("\n[STARTUP] ===== TIMING BREAKDOWN =====")
        sorted_steps = sorted(step_times.items())
        for i, (step, ts) in enumerate(sorted_steps):
            if i > 0:
                prev_step, prev_ts = sorted_steps[i-1]
                duration = ts - prev_ts
                _original_print(f"[STARTUP]   Step {prev_step}→{step}: {duration:.2f}s")
        _original_print(f"[STARTUP]   TOTAL: {total_time:.1f}s")
        _original_print("[STARTUP] ================================\n")
    
    return discord_thread, telegram_thread, gui_port


def run_main_loop(discord_thread, telegram_thread, gui_port):
    """Main monitoring loop - runs until shutdown"""
    discord_failed = False
    try:
        while True:
            try:
                error = _discord_error_queue.get(timeout=1)
                error_msg = str(error)
                
                if 'token' in error_msg.lower() or 'NoneType' in error_msg:
                    if not discord_failed:
                        discord_failed = True
                        _original_print(f"[MAIN] Discord connection failed: {error}")
                        _original_print("[MAIN] Discord token not configured - configure in web GUI")
                else:
                    _original_print(f"[MAIN] FATAL: Discord thread reported error: {error}")
                    _original_print("[MAIN] Shutting down due to Discord thread failure...")
                    break
            except queue.Empty:
                pass
            
            if _discord_shutdown_event.is_set() and not discord_failed:
                _original_print("[MAIN] Discord thread shutdown detected")
                break
            
            if discord_failed:
                import time
                time.sleep(1)
                continue
                
    except KeyboardInterrupt:
        _original_print("\n[MAIN] Shutdown signal received (Ctrl+C)")
    
    # Clean shutdown
    _original_print("[MAIN] Waiting for Discord thread to terminate...")
    discord_thread.join(timeout=5)
    if discord_thread.is_alive():
        _original_print("[MAIN] ⚠️  Discord thread did not terminate cleanly")
    else:
        _original_print("[MAIN] ✓ Discord thread terminated cleanly")
    
    _original_print("[MAIN] Shutdown complete. Exiting...")


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
  %(prog)s --no-gui           # Run without splash screen (console mode)
  
Environment Variables:
  GUI_PORT                    # Alternative way to set the web GUI port (default: 5000)
        """
    )
    parser.add_argument('--port', '-p', type=int, default=None, 
                        help='Port for web control panel (default: 5000, or GUI_PORT env var)')
    parser.add_argument('--wizard', action='store_true', 
                        help='Launch the setup wizard')
    parser.add_argument('--no-gui', action='store_true',
                        help='Run without splash screen (console mode)')
    
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
    
    # Check if running in GUI mode (with splash screen and system tray)
    use_gui_mode = not args.no_gui and getattr(sys, 'frozen', False)
    
    if use_gui_mode:
        # GUI mode: Show splash screen with progress, then minimize to system tray
        try:
            # Check for single instance FIRST (before any heavy imports)
            from src.gui.single_instance import check_single_instance, show_already_running_dialog
            if not check_single_instance("BotifyTrades"):
                _original_print("[STARTUP] Another instance of BotifyTrades is already running!")
                show_already_running_dialog()
                sys.exit(0)
            
            from PySide6.QtWidgets import QApplication, QSystemTrayIcon
            from PySide6.QtCore import QTimer, Signal, QObject
            from src.gui.splash_screen import SplashScreen, StartupProgress
            from src.gui.system_tray import setup_system_tray, get_tray_manager
            
            class StartupWorker(QObject):
                """Thread-safe progress signaler for Qt main thread updates"""
                progress_signal = Signal(int, str)
                complete_signal = Signal()
                error_signal = Signal(str)
            
            app = QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)
            app.setApplicationName("BotifyTrades")
            
            progress = StartupProgress()
            
            # Only bypass license panel if license is already validated
            # Don't bypass just because LICENSE_KEY exists - it might be expired
            license_bypass = LICENSE_VALID
            splash = SplashScreen(progress, skip_license=license_bypass)
            splash.show()
            app.processEvents()
            # License check is now triggered automatically in showEvent
            
            worker = StartupWorker()
            worker.progress_signal.connect(lambda step, msg: progress.update(step, msg))
            worker.complete_signal.connect(progress.complete)
            worker.error_signal.connect(lambda e: progress.fail(e))
            
            startup_state = {
                'discord_thread': None,
                'telegram_thread': None,
                'gui_port': 5000,
                'error': None,
                'license_ready': license_bypass,
                'startup_thread': None
            }
            
            def do_startup():
                try:
                    def update_progress(step, message):
                        worker.progress_signal.emit(step, message)
                    
                    d_thread, t_thread, port = run_bot_startup(update_progress)
                    startup_state['discord_thread'] = d_thread
                    startup_state['telegram_thread'] = t_thread
                    startup_state['gui_port'] = port
                    worker.complete_signal.emit()
                except Exception as e:
                    startup_state['error'] = str(e)
                    worker.error_signal.emit(str(e))
            
            def on_license_ready():
                startup_state['license_ready'] = True
                _original_print("[LICENSE] License validated, starting bot...")
                
                try:
                    from src.license import start_network_monitor, show_license_expired_popup
                    license_key = None
                    if LICENSE_DATA and LICENSE_DATA.get('license_key'):
                        license_key = LICENSE_DATA.get('license_key')
                    elif os.getenv('LICENSE_KEY'):
                        license_key = os.getenv('LICENSE_KEY')
                    else:
                        try:
                            from src.license_client import LicenseClient
                            temp_client = LicenseClient()
                            cache = temp_client._load_cache()
                            if cache and cache.get('license_key'):
                                license_key = cache.get('license_key')
                        except Exception:
                            pass
                    
                    if license_key:
                        _original_print("[LICENSE] Starting network connectivity monitor...")
                        start_network_monitor(
                            license_key=license_key,
                            check_interval=10,
                            show_message_callback=show_license_expired_popup
                        )
                    else:
                        _original_print("[LICENSE] Warning: No license key found for network monitor")
                except Exception as nm_err:
                    _original_print(f"[LICENSE] Network monitor init error: {nm_err}")
                
                startup_thread = threading.Thread(target=do_startup, daemon=True)
                startup_state['startup_thread'] = startup_thread
                startup_thread.start()
            
            splash.startup_ready.connect(on_license_ready)
            
            if license_bypass:
                startup_thread = threading.Thread(target=do_startup, daemon=True)
                startup_state['startup_thread'] = startup_thread
                startup_thread.start()
            
            def check_startup():
                thread = startup_state.get('startup_thread')
                if thread is None:
                    QTimer.singleShot(100, check_startup)
                    return
                if thread.is_alive():
                    QTimer.singleShot(100, check_startup)
                else:
                    splash.close()
                    if startup_state['error'] is None:
                        tray = setup_system_tray()
                        tray.web_panel_port = startup_state['gui_port']
                        tray.set_status("running", "Bot is active and monitoring signals")
                        tray.show_notification(
                            "BotifyTrades",
                            "Bot started successfully! Running in background.",
                            QSystemTrayIcon.MessageIcon.Information,
                            5000
                        )
                        
                        import webbrowser
                        url = f"http://localhost:{startup_state['gui_port']}"
                        _original_print(f"[GUI] Opening control panel in browser: {url}")
                        webbrowser.open(url)
                        
                        def shutdown_handler():
                            _original_print("[MAIN] Shutdown requested from tray")
                            _discord_shutdown_event.set()
                            _telegram_shutdown_event.set()
                            app.quit()
                        
                        tray.shutdown_requested.connect(shutdown_handler)
                    else:
                        _original_print(f"[MAIN] Startup failed: {startup_state['error']}")
                        app.quit()
            
            QTimer.singleShot(100, check_startup)
            
            exit_code = app.exec()
            
            if startup_state['discord_thread'] and startup_state['discord_thread'].is_alive():
                _original_print("[MAIN] Waiting for Discord thread...")
                startup_state['discord_thread'].join(timeout=5)
            
            if startup_state['telegram_thread'] and startup_state['telegram_thread'].is_alive():
                _original_print("[MAIN] Waiting for Telegram thread...")
                startup_state['telegram_thread'].join(timeout=5)
            
            sys.exit(exit_code)
            
        except ImportError as e:
            _original_print(f"[MAIN] PySide6 not available, falling back to console mode: {e}")
            use_gui_mode = False
    
    if not use_gui_mode:
        # Console mode: Run without splash screen
        try:
            from src.license import start_network_monitor, show_license_expired_popup
            license_key = None
            if LICENSE_DATA and LICENSE_DATA.get('license_key'):
                license_key = LICENSE_DATA.get('license_key')
            elif os.getenv('LICENSE_KEY'):
                license_key = os.getenv('LICENSE_KEY')
            else:
                try:
                    from src.license_client import LicenseClient
                    temp_client = LicenseClient()
                    cache = temp_client._load_cache()
                    if cache and cache.get('license_key'):
                        license_key = cache.get('license_key')
                except Exception:
                    pass
            
            if license_key:
                print("[LICENSE] Starting network connectivity monitor...")
                start_network_monitor(
                    license_key=license_key,
                    check_interval=10,
                    show_message_callback=show_license_expired_popup
                )
            else:
                print("[LICENSE] Warning: No license key found for network monitor")
        except Exception as nm_err:
            print(f"[LICENSE] Network monitor init error: {nm_err}")
        
        discord_thread, telegram_thread, gui_port = run_bot_startup()
        run_main_loop(discord_thread, telegram_thread, gui_port)
        sys.exit(0)
