"""
Diagnostic Checks
=================
Individual health check implementations.
"""

from typing import Dict, Any, Optional, List
from .diagnostic_types import CheckResult, CheckStatus, DiagnosticCategory


def check_database_connection() -> CheckResult:
    """Verify database is accessible and schema is valid."""
    try:
        from gui_app import database as db
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        required_tables = ['app_users', 'trades', 'channels', 'risk_management_settings']
        missing = [t for t in required_tables if t not in tables]
        
        if missing:
            return CheckResult(
                name="Database Schema",
                category=DiagnosticCategory.DATABASE,
                status=CheckStatus.WARN,
                message=f"Missing tables: {missing}",
                details={'tables': tables, 'missing': missing},
                remediation="Run database migration or restart the application"
            )
        
        return CheckResult(
            name="Database Connection",
            category=DiagnosticCategory.DATABASE,
            status=CheckStatus.PASS,
            message=f"Connected with {len(tables)} tables",
            details={'tables': tables}
        )
    except ImportError:
        return CheckResult(
            name="Database Connection",
            category=DiagnosticCategory.DATABASE,
            status=CheckStatus.FAIL,
            message="Database module not available",
            remediation="Ensure gui_app.database module is installed"
        )
    except Exception as e:
        return CheckResult(
            name="Database Connection",
            category=DiagnosticCategory.DATABASE,
            status=CheckStatus.FAIL,
            message=f"Connection failed: {str(e)}",
            remediation="Check database file permissions and path"
        )


def check_database_functions() -> CheckResult:
    """Verify all required database functions are accessible."""
    required_functions = [
        'get_connection', 'get_risk_management_settings', 'find_open_bto_trade',
        'get_ai_settings', 'get_channels'
    ]
    
    try:
        from gui_app import database as db
        
        missing = []
        for func_name in required_functions:
            if not hasattr(db, func_name):
                missing.append(func_name)
        
        if missing:
            return CheckResult(
                name="Database Functions",
                category=DiagnosticCategory.DATABASE,
                status=CheckStatus.FAIL,
                message=f"Missing functions: {missing}",
                details={'missing': missing, 'required': required_functions},
                remediation="Database module is outdated or corrupted"
            )
        
        return CheckResult(
            name="Database Functions",
            category=DiagnosticCategory.DATABASE,
            status=CheckStatus.PASS,
            message=f"All {len(required_functions)} functions available",
            details={'functions': required_functions}
        )
    except ImportError as e:
        return CheckResult(
            name="Database Functions",
            category=DiagnosticCategory.DATABASE,
            status=CheckStatus.FAIL,
            message=f"Import failed: {str(e)}",
            remediation="Ensure gui_app package is properly installed"
        )


def check_risk_management_sync() -> CheckResult:
    """Verify risk management settings are synced between DB and runtime."""
    try:
        from gui_app import database as db
        
        db_settings = db.get_risk_management_settings()
        
        details = {
            'db_enabled': db_settings['enabled'],
            'db_profit_target': db_settings['profit_target_percent'],
            'db_stop_loss': db_settings['stop_loss_percent'],
            'db_trailing_stop': db_settings['trailing_stop_percent']
        }
        
        runtime_synced = True
        mismatches = []
        
        try:
            import sys
            bot_module = None
            
            if '__main__' in sys.modules:
                main_mod = sys.modules['__main__']
                if hasattr(main_mod, 'ENABLE_RISK_MGMT'):
                    bot_module = main_mod
            
            if bot_module is None:
                try:
                    import src.selfbot_webull as bot_module
                except ImportError:
                    pass
            
            if bot_module and hasattr(bot_module, 'ENABLE_RISK_MGMT'):
                runtime_enabled = getattr(bot_module, 'ENABLE_RISK_MGMT', None)
                runtime_profit = getattr(bot_module, 'PROFIT_TARGET_PCT', None)
                runtime_stop = getattr(bot_module, 'STOP_LOSS_PCT', None)
                runtime_trailing = getattr(bot_module, 'TRAILING_STOP_PCT', None)
                
                details['runtime_enabled'] = runtime_enabled
                details['runtime_profit_target'] = runtime_profit
                details['runtime_stop_loss'] = runtime_stop
                details['runtime_trailing_stop'] = runtime_trailing
                details['runtime_loaded'] = True
                
                if runtime_enabled != db_settings['enabled']:
                    mismatches.append(f"enabled: DB={db_settings['enabled']} vs runtime={runtime_enabled}")
                    runtime_synced = False
                if runtime_profit != db_settings['profit_target_percent']:
                    mismatches.append(f"profit_target: DB={db_settings['profit_target_percent']} vs runtime={runtime_profit}")
                    runtime_synced = False
                if runtime_stop != db_settings['stop_loss_percent']:
                    mismatches.append(f"stop_loss: DB={db_settings['stop_loss_percent']} vs runtime={runtime_stop}")
                    runtime_synced = False
                if runtime_trailing != db_settings['trailing_stop_percent']:
                    mismatches.append(f"trailing_stop: DB={db_settings['trailing_stop_percent']} vs runtime={runtime_trailing}")
                    runtime_synced = False
            else:
                details['runtime_loaded'] = False
        except Exception:
            details['runtime_loaded'] = False
        
        if not runtime_synced:
            return CheckResult(
                name="Risk Management Sync",
                category=DiagnosticCategory.RISK_MANAGEMENT,
                status=CheckStatus.WARN,
                message=f"DB/Runtime mismatch: {'; '.join(mismatches)}",
                details=details,
                remediation="Restart bot to reload settings from database"
            )
        
        if db_settings['enabled']:
            if db_settings['stop_loss_percent'] <= 0 and db_settings['profit_target_percent'] <= 0:
                return CheckResult(
                    name="Risk Management Sync",
                    category=DiagnosticCategory.RISK_MANAGEMENT,
                    status=CheckStatus.WARN,
                    message="Risk enabled but no targets/stops configured",
                    details=details,
                    remediation="Configure profit targets or stop loss in Settings"
                )
        
        return CheckResult(
            name="Risk Management Sync",
            category=DiagnosticCategory.RISK_MANAGEMENT,
            status=CheckStatus.PASS,
            message=f"Enabled={db_settings['enabled']}, SL={db_settings['stop_loss_percent']}% (synced)",
            details=details
        )
    except Exception as e:
        return CheckResult(
            name="Risk Management Sync",
            category=DiagnosticCategory.RISK_MANAGEMENT,
            status=CheckStatus.FAIL,
            message=f"Failed to read settings: {str(e)}",
            remediation="Check database connection"
        )


def check_channel_risk_settings() -> CheckResult:
    """Verify per-channel risk settings configuration."""
    try:
        from gui_app import database as db
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM channels 
            WHERE (profit_target_1_pct > 0 OR stop_loss_pct > 0 OR trailing_stop_pct > 0)
        ''')
        configured_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM channels')
        total_count = cursor.fetchone()[0]
        
        return CheckResult(
            name="Per-Channel Risk Settings",
            category=DiagnosticCategory.RISK_MANAGEMENT,
            status=CheckStatus.PASS,
            message=f"{configured_count}/{total_count} channels have risk settings",
            details={'configured': configured_count, 'total': total_count}
        )
    except Exception as e:
        return CheckResult(
            name="Per-Channel Risk Settings",
            category=DiagnosticCategory.RISK_MANAGEMENT,
            status=CheckStatus.WARN,
            message=f"Could not check: {str(e)}",
            details={}
        )


def check_license_status() -> CheckResult:
    """Verify license validation and cache status."""
    try:
        from src.license_client import validate_license, get_cached_validation
        
        cached = get_cached_validation()
        
        if cached and cached.get('is_valid'):
            days = cached.get('days_remaining', 0)
            
            if days <= 3:
                status = CheckStatus.WARN
                message = f"License expires in {days} days!"
            else:
                status = CheckStatus.PASS
                message = f"Valid ({days} days remaining)"
            
            return CheckResult(
                name="License Status",
                category=DiagnosticCategory.LICENSE,
                status=status,
                message=message,
                details={
                    'valid': True,
                    'days_remaining': days,
                    'expires': cached.get('expires'),
                    'license_type': cached.get('license_type')
                }
            )
        
        result = validate_license()
        
        if result and result.get('is_valid'):
            return CheckResult(
                name="License Status",
                category=DiagnosticCategory.LICENSE,
                status=CheckStatus.PASS,
                message=f"Validated ({result.get('days_remaining', 0)} days)",
                details=result
            )
        
        return CheckResult(
            name="License Status",
            category=DiagnosticCategory.LICENSE,
            status=CheckStatus.FAIL,
            message="License invalid or expired",
            details=result or {},
            remediation="Contact support or enter a valid license key"
        )
    except ImportError:
        return CheckResult(
            name="License Status",
            category=DiagnosticCategory.LICENSE,
            status=CheckStatus.SKIP,
            message="License module not available",
            details={}
        )
    except Exception as e:
        return CheckResult(
            name="License Status",
            category=DiagnosticCategory.LICENSE,
            status=CheckStatus.WARN,
            message=f"Could not validate: {str(e)}",
            details={'error': str(e)}
        )


def check_webull_broker() -> CheckResult:
    """Verify Webull broker connectivity."""
    try:
        from gui_app import database as db
        from gui_app.broker_credentials_service import get_webull_credentials
        
        creds = get_webull_credentials()
        
        if not creds:
            return CheckResult(
                name="Webull Broker",
                category=DiagnosticCategory.BROKER_WEBULL,
                status=CheckStatus.SKIP,
                message="No credentials configured",
                remediation="Add Webull credentials in Settings"
            )
        
        has_email = bool(creds.get('email'))
        has_tokens = bool(creds.get('access_token'))
        
        if has_tokens:
            return CheckResult(
                name="Webull Broker",
                category=DiagnosticCategory.BROKER_WEBULL,
                status=CheckStatus.PASS,
                message=f"Credentials ready (token-based auth)",
                details={'email': creds.get('email', 'N/A')[:20] + '...', 'has_tokens': True}
            )
        elif has_email:
            return CheckResult(
                name="Webull Broker",
                category=DiagnosticCategory.BROKER_WEBULL,
                status=CheckStatus.PASS,
                message=f"Credentials configured (email-based)",
                details={'email': creds.get('email', '')[:20] + '...', 'has_tokens': False}
            )
        
        return CheckResult(
            name="Webull Broker",
            category=DiagnosticCategory.BROKER_WEBULL,
            status=CheckStatus.WARN,
            message="Incomplete credentials",
            remediation="Add Webull email/password or access tokens"
        )
    except Exception as e:
        return CheckResult(
            name="Webull Broker",
            category=DiagnosticCategory.BROKER_WEBULL,
            status=CheckStatus.FAIL,
            message=f"Error: {str(e)}",
            details={'error': str(e)}
        )


def check_alpaca_broker() -> CheckResult:
    """Verify Alpaca broker connectivity."""
    try:
        from gui_app.broker_credentials_service import load_config
        
        creds = load_config('alpaca_credentials') or {}
        
        if not creds.get('api_key'):
            return CheckResult(
                name="Alpaca Broker",
                category=DiagnosticCategory.BROKER_ALPACA,
                status=CheckStatus.SKIP,
                message="No credentials configured",
                remediation="Add Alpaca API credentials in Settings"
            )
        
        return CheckResult(
            name="Alpaca Broker",
            category=DiagnosticCategory.BROKER_ALPACA,
            status=CheckStatus.PASS,
            message="Credentials configured",
            details={'api_key_prefix': creds['api_key'][:8] + '...'}
        )
    except Exception as e:
        return CheckResult(
            name="Alpaca Broker",
            category=DiagnosticCategory.BROKER_ALPACA,
            status=CheckStatus.WARN,
            message=f"Could not verify: {str(e)}",
            details={'error': str(e)}
        )


def check_discord_token() -> CheckResult:
    """Verify Discord token is configured."""
    try:
        from gui_app.broker_credentials_service import get_discord_credentials
        
        discord_creds = get_discord_credentials()
        token = discord_creds.get('token', '').strip()
        
        if not token:
            return CheckResult(
                name="Discord Token",
                category=DiagnosticCategory.DISCORD,
                status=CheckStatus.FAIL,
                message="No token configured",
                remediation="Add Discord token in Settings"
            )
        
        if len(token) < 50:
            return CheckResult(
                name="Discord Token",
                category=DiagnosticCategory.DISCORD,
                status=CheckStatus.WARN,
                message="Token appears too short",
                remediation="Verify Discord token is correct"
            )
        
        return CheckResult(
            name="Discord Token",
            category=DiagnosticCategory.DISCORD,
            status=CheckStatus.PASS,
            message=f"Token configured ({len(token)} chars)",
            details={'length': len(token), 'prefix': token[:10] + '...'}
        )
    except Exception as e:
        return CheckResult(
            name="Discord Token",
            category=DiagnosticCategory.DISCORD,
            status=CheckStatus.FAIL,
            message=f"Error: {str(e)}",
            details={'error': str(e)}
        )


def check_monitored_channels() -> CheckResult:
    """Verify Discord channels are configured for monitoring."""
    try:
        from gui_app import database as db
        
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM channels WHERE is_active = 1")
        enabled_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM channels")
        total_count = cursor.fetchone()[0]
        
        if enabled_count == 0:
            return CheckResult(
                name="Monitored Channels",
                category=DiagnosticCategory.DISCORD,
                status=CheckStatus.WARN,
                message="No channels enabled for monitoring",
                details={'enabled': 0, 'total': total_count},
                remediation="Enable at least one channel in the Channels settings"
            )
        
        return CheckResult(
            name="Monitored Channels",
            category=DiagnosticCategory.DISCORD,
            status=CheckStatus.PASS,
            message=f"{enabled_count}/{total_count} channels enabled",
            details={'enabled': enabled_count, 'total': total_count}
        )
    except Exception as e:
        return CheckResult(
            name="Monitored Channels",
            category=DiagnosticCategory.DISCORD,
            status=CheckStatus.WARN,
            message=f"Could not check: {str(e)}",
            details={'error': str(e)}
        )


def check_options_chain_availability() -> CheckResult:
    """Verify options chain data source is available."""
    try:
        import webull
        wb = webull.webull()
        
        result = wb.get_options_expiration_dates(stock='SPY')
        
        if isinstance(result, list) and len(result) > 0:
            return CheckResult(
                name="Options Chain Source",
                category=DiagnosticCategory.OPTIONS_CHAIN,
                status=CheckStatus.PASS,
                message=f"Webull API working ({len(result)} expirations for SPY)",
                details={'source': 'webull', 'expiration_count': len(result)}
            )
        elif isinstance(result, dict) and 'expireDateList' in result:
            exp_list = result['expireDateList']
            return CheckResult(
                name="Options Chain Source",
                category=DiagnosticCategory.OPTIONS_CHAIN,
                status=CheckStatus.PASS,
                message=f"Webull API working ({len(exp_list)} expirations)",
                details={'source': 'webull', 'expiration_count': len(exp_list)}
            )
        
        return CheckResult(
            name="Options Chain Source",
            category=DiagnosticCategory.OPTIONS_CHAIN,
            status=CheckStatus.WARN,
            message="Unexpected response format",
            details={'response_type': str(type(result))}
        )
    except Exception as e:
        return CheckResult(
            name="Options Chain Source",
            category=DiagnosticCategory.OPTIONS_CHAIN,
            status=CheckStatus.FAIL,
            message=f"Webull API error: {str(e)}",
            details={'error': str(e)},
            remediation="Check internet connection or Webull service status"
        )


def check_ibkr_broker() -> CheckResult:
    """Verify Interactive Brokers connectivity."""
    try:
        from gui_app.broker_credentials_service import get_ibkr_credentials
        
        creds = get_ibkr_credentials() or {}
        host = creds.get('host', '')
        
        if not host:
            return CheckResult(
                name="IBKR Broker",
                category=DiagnosticCategory.BROKER_IBKR,
                status=CheckStatus.SKIP,
                message="No credentials configured",
                remediation="Add IBKR credentials in Settings if using Interactive Brokers"
            )
        
        paper = creds.get('paper_mode', True)
        port = creds.get('port_paper', 7497) if paper else creds.get('port_live', 7496)
        client_id = creds.get('client_id', 1)
        mode = "paper" if paper else "live"
        
        return CheckResult(
            name="IBKR Broker",
            category=DiagnosticCategory.BROKER_IBKR,
            status=CheckStatus.PASS,
            message=f"Configured ({mode} mode, {host}:{port}, clientId={client_id})",
            details={'host': host, 'port': port, 'client_id': client_id, 'paper_mode': paper}
        )
    except Exception as e:
        return CheckResult(
            name="IBKR Broker",
            category=DiagnosticCategory.BROKER_IBKR,
            status=CheckStatus.WARN,
            message=f"Could not verify: {str(e)}",
            details={'error': str(e)}
        )


def check_version_update() -> CheckResult:
    """Check GitHub for available updates using the existing VersionChecker."""
    try:
        from upgrade.version import get_current_version
        from upgrade.version_checker import get_version_checker
        from datetime import datetime, timedelta
        
        current_version = get_current_version()
        checker = get_version_checker()
        
        status_before = checker.get_status()
        last_check_before = status_before.get('last_check')
        
        update_info = checker.check_for_updates(force=True)
        
        status_after = checker.get_status()
        last_check_after = status_after.get('last_check')
        
        check_timestamp_updated = last_check_after and last_check_after != last_check_before
        
        if update_info:
            return CheckResult(
                name="Version Update",
                category=DiagnosticCategory.SYSTEM,
                status=CheckStatus.WARN,
                message=f"Update available: v{update_info.version} (current: v{current_version})",
                details={
                    'current_version': current_version,
                    'latest_version': update_info.version,
                    'release_url': update_info.download_url,
                    'is_critical': update_info.is_critical,
                    'release_date': update_info.release_date
                },
                remediation=f"Download latest version from {update_info.download_url}" if update_info.download_url else "Check GitHub releases for the latest version"
            )
        
        if not check_timestamp_updated:
            return CheckResult(
                name="Version Update",
                category=DiagnosticCategory.SYSTEM,
                status=CheckStatus.WARN,
                message=f"Could not check for updates (v{current_version})",
                details={
                    'current_version': current_version,
                    'error': 'GitHub API check failed - no response received'
                },
                remediation="Check internet connection or try again later"
            )
        
        return CheckResult(
            name="Version Update",
            category=DiagnosticCategory.SYSTEM,
            status=CheckStatus.PASS,
            message=f"Up to date (v{current_version})",
            details={
                'current_version': current_version,
                'last_check': last_check_after
            }
        )
    except ImportError as e:
        return CheckResult(
            name="Version Update",
            category=DiagnosticCategory.SYSTEM,
            status=CheckStatus.SKIP,
            message=f"Version module not available: {str(e)}",
            remediation="Ensure upgrade module is properly installed"
        )
    except Exception as e:
        return CheckResult(
            name="Version Update",
            category=DiagnosticCategory.SYSTEM,
            status=CheckStatus.WARN,
            message=f"Could not check: {str(e)}",
            details={'error': str(e)},
            remediation="Check internet connection or try again later"
        )


def get_all_checks() -> List:
    """Return list of all check functions."""
    return [
        check_database_connection,
        check_database_functions,
        check_risk_management_sync,
        check_channel_risk_settings,
        check_license_status,
        check_webull_broker,
        check_alpaca_broker,
        check_ibkr_broker,
        check_discord_token,
        check_monitored_channels,
        check_options_chain_availability,
        check_version_update
    ]
