#!/usr/bin/env python3
"""
System Diagnostics Module
=========================
Provides comprehensive system health checks accessible from the GUI.
"""
import os
import sys
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class DiagnosticResult:
    """Result of a diagnostic check."""
    
    def __init__(self, name: str, status: str, message: str, details: dict = None):
        self.name = name
        self.status = status  # 'pass', 'warn', 'fail'
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self):
        return {
            'name': self.name,
            'status': self.status,
            'message': self.message,
            'details': self.details,
            'timestamp': self.timestamp
        }


class SystemDiagnostics:
    """Run comprehensive system diagnostics."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or 'bot_data.db'
        self.results: List[DiagnosticResult] = []
    
    def run_all(self) -> List[Dict]:
        """Run all diagnostic checks."""
        self.results = []
        
        # Core system checks
        self._check_python_environment()
        self._check_database_connection()
        self._check_database_schema()
        self._check_required_tables()
        
        # License checks
        self._check_license_status()
        self._check_license_cache()
        self._check_license_server_admin()
        
        # Broker checks
        self._check_broker_credentials()
        self._check_broker_connections()
        
        # Channel checks
        self._check_channel_configuration()
        
        # Environment checks
        self._check_environment_variables()
        self._check_api_keys()
        
        # Route checks
        self._check_route_conflicts()
        
        return [r.to_dict() for r in self.results]
    
    def _add_result(self, name: str, status: str, message: str, details: dict = None):
        """Add a diagnostic result."""
        self.results.append(DiagnosticResult(name, status, message, details))
    
    def _check_python_environment(self):
        """Check Python version and critical imports."""
        try:
            version = sys.version_info
            if version.major == 3 and version.minor >= 8:
                self._add_result(
                    'Python Environment',
                    'pass',
                    f'Python {version.major}.{version.minor}.{version.micro}',
                    {'version': f'{version.major}.{version.minor}.{version.micro}'}
                )
            else:
                self._add_result(
                    'Python Environment',
                    'warn',
                    f'Python {version.major}.{version.minor} (3.8+ recommended)'
                )
        except Exception as e:
            self._add_result('Python Environment', 'fail', str(e))
    
    def _check_database_connection(self):
        """Check database connectivity."""
        try:
            if not Path(self.db_path).exists():
                self._add_result(
                    'Database Connection',
                    'warn',
                    'Database file not found (will be created on first run)',
                    {'path': self.db_path}
                )
                return
            
            conn = sqlite3.connect(self.db_path)
            conn.execute('SELECT 1')
            conn.close()
            
            self._add_result(
                'Database Connection',
                'pass',
                'Database connected successfully',
                {'path': self.db_path}
            )
        except Exception as e:
            self._add_result('Database Connection', 'fail', str(e))
    
    def _check_database_schema(self):
        """Check database schema integrity."""
        try:
            if not Path(self.db_path).exists():
                return
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            conn.close()
            
            self._add_result(
                'Database Schema',
                'pass',
                f'{len(tables)} tables found',
                {'tables': tables}
            )
        except Exception as e:
            self._add_result('Database Schema', 'fail', str(e))
    
    def _check_required_tables(self):
        """Check for required database tables."""
        required_tables = ['server_licenses']
        optional_tables = ['settings', 'channels', 'trades', 'signals']
        
        try:
            if not Path(self.db_path).exists():
                return
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing = {row[0] for row in cursor.fetchall()}
            conn.close()
            
            missing_required = [t for t in required_tables if t not in existing]
            missing_optional = [t for t in optional_tables if t not in existing]
            
            if missing_required:
                self._add_result(
                    'Required Tables',
                    'fail',
                    f'Missing required tables: {", ".join(missing_required)}'
                )
            elif missing_optional:
                self._add_result(
                    'Required Tables',
                    'warn',
                    f'Missing optional tables: {", ".join(missing_optional)}'
                )
            else:
                self._add_result(
                    'Required Tables',
                    'pass',
                    'All required tables present'
                )
        except Exception as e:
            self._add_result('Required Tables', 'fail', str(e))
    
    def _check_license_status(self):
        """Check license system status."""
        try:
            server_mode = os.environ.get('LICENSE_SERVER_MODE', '').lower() == 'true'
            admin_password = os.environ.get('ADMIN_PASSWORD', '')
            
            if server_mode:
                self._add_result(
                    'License Status',
                    'pass',
                    'Server mode enabled (admin bypass active)'
                )
            elif admin_password:
                self._add_result(
                    'License Status',
                    'pass',
                    'Admin password configured'
                )
            else:
                self._add_result(
                    'License Status',
                    'warn',
                    'No admin bypass configured'
                )
        except Exception as e:
            self._add_result('License Status', 'fail', str(e))
    
    def _check_license_cache(self):
        """Check license cache status."""
        cache_file = Path.home() / '.discord_trading_bot' / 'license_cache.json'
        
        try:
            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    cache = json.load(f)
                
                has_token = bool(cache.get('signed_token'))
                self._add_result(
                    'License Cache',
                    'pass' if has_token else 'warn',
                    'Cache present' + (' (signed)' if has_token else ' (unsigned)'),
                    {'has_signed_token': has_token}
                )
            else:
                self._add_result(
                    'License Cache',
                    'warn',
                    'No cache file (server connection required for offline mode)'
                )
        except Exception as e:
            self._add_result('License Cache', 'warn', f'Cannot read cache: {e}')
    
    def _check_license_server_admin(self):
        """Check license server admin panel status and database tables."""
        try:
            license_db_path = 'bot_data.db'
            if not Path(license_db_path).exists():
                self._add_result(
                    'License Server Admin',
                    'warn',
                    'License database not found'
                )
                return
            
            conn = sqlite3.connect(license_db_path)
            cursor = conn.cursor()
            
            # Check for license server tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='server_licenses'")
            has_licenses_table = cursor.fetchone() is not None
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='server_machines'")
            has_machines_table = cursor.fetchone() is not None
            
            if not has_licenses_table:
                self._add_result(
                    'License Server Admin',
                    'warn',
                    'License server tables not initialized (server_licenses missing)',
                    {'admin_url': '/admin/licenses'}
                )
                conn.close()
                return
            
            # Get license statistics
            cursor.execute("SELECT COUNT(*) FROM server_licenses")
            total_licenses = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM server_licenses WHERE status='active'")
            active_licenses = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM server_licenses WHERE devices_used >= max_devices AND max_devices > 0")
            maxed_devices = cursor.fetchone()[0]
            
            conn.close()
            
            details = {
                'total_licenses': total_licenses,
                'active_licenses': active_licenses,
                'devices_maxed': maxed_devices,
                'has_machines_table': has_machines_table,
                'admin_url': '/admin/licenses',
                'reset_devices_endpoint': 'POST /api/admin/licenses/<key>/reset-devices'
            }
            
            if maxed_devices > 0:
                self._add_result(
                    'License Server Admin',
                    'warn',
                    f'{active_licenses} active licenses, {maxed_devices} at device limit (use Reset Devices button)',
                    details
                )
            else:
                self._add_result(
                    'License Server Admin',
                    'pass',
                    f'{active_licenses} active licenses, {total_licenses} total',
                    details
                )
                
        except Exception as e:
            self._add_result('License Server Admin', 'fail', f'Error checking license server: {e}')
    
    def _check_broker_credentials(self):
        """Check broker credential status."""
        alpaca_key = os.environ.get('ALPACA_API_KEY', '')
        alpaca_secret = os.environ.get('ALPACA_SECRET_KEY', '')
        
        if alpaca_key and alpaca_secret:
            self._add_result(
                'Broker Credentials',
                'pass',
                'Alpaca API keys configured',
                {'brokers': ['alpaca']}
            )
        else:
            self._add_result(
                'Broker Credentials',
                'warn',
                'No broker API keys found in environment'
            )
    
    def _check_broker_connections(self):
        """Check broker connection status (placeholder)."""
        self._add_result(
            'Broker Connections',
            'warn',
            'Broker connectivity check requires runtime (use /api/brokers/all_accounts)'
        )
    
    def _check_channel_configuration(self):
        """Check channel configuration."""
        try:
            if not Path(self.db_path).exists():
                return
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if channels table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='channels'")
            if not cursor.fetchone():
                self._add_result(
                    'Channel Configuration',
                    'warn',
                    'Channels table not found'
                )
                conn.close()
                return
            
            cursor.execute("SELECT COUNT(*) FROM channels")
            count = cursor.fetchone()[0]
            
            conn.close()
            
            if count > 0:
                self._add_result(
                    'Channel Configuration',
                    'pass',
                    f'{count} channel(s) configured'
                )
            else:
                self._add_result(
                    'Channel Configuration',
                    'warn',
                    'No channels configured'
                )
        except Exception as e:
            self._add_result('Channel Configuration', 'warn', str(e))
    
    def _check_environment_variables(self):
        """Check critical environment variables."""
        required = {
            'ADMIN_PASSWORD': bool(os.environ.get('ADMIN_PASSWORD')),
        }
        optional = {
            'ALPHA_VANTAGE_API_KEY': bool(os.environ.get('ALPHA_VANTAGE_API_KEY')),
            'FINNHUB_API_KEY': bool(os.environ.get('FINNHUB_API_KEY')),
            'OPENAI_API_KEY': bool(os.environ.get('OPENAI_API_KEY')),
        }
        
        missing_required = [k for k, v in required.items() if not v]
        missing_optional = [k for k, v in optional.items() if not v]
        
        if missing_required:
            self._add_result(
                'Environment Variables',
                'warn',
                f'Missing: {", ".join(missing_required)}'
            )
        else:
            self._add_result(
                'Environment Variables',
                'pass',
                'Required variables configured',
                {'optional_missing': missing_optional}
            )
    
    def _check_api_keys(self):
        """Check API key configuration."""
        apis = {
            'Alpha Vantage': bool(os.environ.get('ALPHA_VANTAGE_API_KEY')),
            'Finnhub': bool(os.environ.get('FINNHUB_API_KEY')),
            'OpenAI': bool(os.environ.get('OPENAI_API_KEY')),
        }
        
        configured = [k for k, v in apis.items() if v]
        
        if configured:
            self._add_result(
                'API Keys',
                'pass',
                f'Configured: {", ".join(configured)}'
            )
        else:
            self._add_result(
                'API Keys',
                'warn',
                'No API keys configured'
            )
    
    def _check_route_conflicts(self):
        """Check for route conflicts in routes.py."""
        routes_file = Path('gui_app/routes.py')
        
        if not routes_file.exists():
            self._add_result(
                'Route Conflicts',
                'warn',
                'routes.py not found'
            )
            return
        
        try:
            import re
            from collections import defaultdict
            
            content = routes_file.read_text(encoding='utf-8')
            route_pattern = r"@(?:app|bp)\.route\(['\"]([^'\"]+)['\"](?:,\s*methods=\[([^\]]+)\])?\)"
            matches = re.findall(route_pattern, content)
            
            seen = defaultdict(int)
            for path, methods in matches:
                method_list = ['GET'] if not methods else [m.strip().strip("'\"") for m in methods.split(',')]
                for method in method_list:
                    key = f"{method.upper()} {path}"
                    seen[key] += 1
            
            duplicates = [k for k, v in seen.items() if v > 1]
            
            if duplicates:
                self._add_result(
                    'Route Conflicts',
                    'fail',
                    f'{len(duplicates)} duplicate route(s) found',
                    {'duplicates': duplicates}
                )
            else:
                self._add_result(
                    'Route Conflicts',
                    'pass',
                    f'No duplicate routes ({len(seen)} unique routes)'
                )
        except Exception as e:
            self._add_result('Route Conflicts', 'warn', str(e))
    
    def get_summary(self) -> Dict:
        """Get summary of diagnostic results."""
        passed = sum(1 for r in self.results if r.status == 'pass')
        warned = sum(1 for r in self.results if r.status == 'warn')
        failed = sum(1 for r in self.results if r.status == 'fail')
        
        overall = 'healthy' if failed == 0 and warned == 0 else 'degraded' if failed == 0 else 'critical'
        
        return {
            'overall_status': overall,
            'passed': passed,
            'warnings': warned,
            'failures': failed,
            'total': len(self.results),
            'timestamp': datetime.now().isoformat()
        }


def run_diagnostics(db_path: str = None) -> Dict:
    """Run all diagnostics and return results."""
    diag = SystemDiagnostics(db_path)
    results = diag.run_all()
    summary = diag.get_summary()
    
    return {
        'summary': summary,
        'results': results
    }


if __name__ == '__main__':
    results = run_diagnostics()
    
    print("=" * 50)
    print("SYSTEM DIAGNOSTICS REPORT")
    print("=" * 50)
    
    summary = results['summary']
    print(f"\nOverall Status: {summary['overall_status'].upper()}")
    print(f"Passed: {summary['passed']} | Warnings: {summary['warnings']} | Failures: {summary['failures']}")
    print()
    
    for result in results['results']:
        status_icon = {'pass': '✓', 'warn': '⚠', 'fail': '✗'}[result['status']]
        print(f"  {status_icon} {result['name']}: {result['message']}")
    
    print()
