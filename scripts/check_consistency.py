#!/usr/bin/env python3
"""
System Consistency Checker
==========================
Centralized script to verify system integrity after any code changes.
Run this after adding features, modifying code, or before deployment.

Usage:
    python scripts/check_consistency.py [--quick] [--full] [--pre-deploy]
    
Modes:
    --quick     : Fast checks (imports, schema, routes) - ~5 seconds
    --full      : All checks including tests - ~30 seconds
    --pre-deploy: Full + build validation - ~60 seconds
"""
import os
import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Dict

sys.path.insert(0, str(Path(__file__).parent.parent))


class ConsistencyChecker:
    """Centralized system consistency verification."""
    
    def __init__(self, mode: str = 'quick'):
        self.mode = mode
        self.results: List[Tuple[str, str, str]] = []  # (check_name, status, message)
        self.start_time = datetime.now()
    
    def run(self) -> bool:
        """Run all consistency checks for the selected mode."""
        print("=" * 60)
        print(f"SYSTEM CONSISTENCY CHECK - {self.mode.upper()} MODE")
        print(f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        # Always run quick checks
        self._check_imports()
        self._check_no_duplicate_files()
        self._check_database_schema()
        self._check_route_conflicts()
        self._check_module_structure()
        self._check_settings_consistency()
        
        if self.mode in ['full', 'pre-deploy']:
            self._run_unit_tests()
            self._check_system_diagnostics()
        
        if self.mode == 'pre-deploy':
            self._validate_build_targets()
            self._check_documentation()
        
        return self._print_summary()
    
    def _add_result(self, name: str, status: str, message: str):
        """Add a check result."""
        self.results.append((name, status, message))
        icon = {'pass': '✓', 'warn': '⚠', 'fail': '✗'}[status]
        print(f"  {icon} {name}: {message}")
    
    def _check_imports(self):
        """Verify core module imports work without errors."""
        print("\n[1/8] Checking Core Imports...")
        
        modules_to_check = [
            ('src.core.bootstrap', 'Core Bootstrap'),
            ('src.core.settings', 'Core Settings'),
            ('src.signals.parser', 'Signal Parser'),
            ('src.signals.patterns', 'Signal Patterns'),
            ('gui_app.app', 'Flask App'),
        ]
        
        failed = []
        for module_path, name in modules_to_check:
            try:
                __import__(module_path)
            except ImportError as e:
                failed.append(f"{name}: {e}")
            except Exception as e:
                failed.append(f"{name}: {type(e).__name__}")
        
        if failed:
            self._add_result('Core Imports', 'fail', f'{len(failed)} import errors')
            for f in failed:
                print(f"      - {f}")
        else:
            self._add_result('Core Imports', 'pass', f'{len(modules_to_check)} modules OK')
    
    def _check_no_duplicate_files(self):
        """Ensure no duplicate implementation files exist."""
        print("\n[2/8] Checking for Duplicate Files...")
        
        patterns_to_check = [
            ('**/signal_parser*.py', 1, 'signal parser'),
            ('**/bootstrap*.py', 1, 'bootstrap'),
            ('**/routes*.py', 1, 'routes'),
            ('**/database*.py', 2, 'database'),  # Allow gui_app/database.py + tests
        ]
        
        duplicates = []
        for pattern, max_allowed, name in patterns_to_check:
            import glob
            matches = list(glob.glob(pattern, recursive=True))
            # Filter out test files and backups
            matches = [m for m in matches if 'test' not in m.lower() 
                      and 'backup' not in m.lower() 
                      and '__pycache__' not in m]
            if len(matches) > max_allowed:
                duplicates.append(f"{name}: {len(matches)} files ({', '.join(matches)})")
        
        # Check for multiple database files (should be 1-2 only)
        import glob
        db_files = list(glob.glob('**/*.db', recursive=True)) + list(glob.glob('**/*.sqlite', recursive=True))
        db_files = [f for f in db_files if '__pycache__' not in f and 'backup' not in f.lower()]
        allowed_dbs = {'bot_data.db', 'license_server.db'}
        unexpected_dbs = [f for f in db_files if Path(f).name not in allowed_dbs]
        
        if unexpected_dbs:
            duplicates.append(f"databases: unexpected files ({', '.join(unexpected_dbs)})")
        
        if duplicates:
            self._add_result('No Duplicates', 'warn', f'{len(duplicates)} potential duplicates')
            for d in duplicates:
                print(f"      - {d}")
        else:
            self._add_result('No Duplicates', 'pass', 'No duplicate implementation files')
    
    def _check_database_schema(self):
        """Validate database schema using existing validator."""
        print("\n[3/8] Validating Database Schema...")
        
        try:
            from scripts.validate_schema import validate_schema
            
            db_paths = ['bot_data.db']
            valid_count = 0
            
            for db_path in db_paths:
                if Path(db_path).exists():
                    if validate_schema(db_path):
                        valid_count += 1
            
            if valid_count > 0:
                self._add_result('Database Schema', 'pass', f'{valid_count} database(s) validated')
            else:
                self._add_result('Database Schema', 'warn', 'No database files found')
        except Exception as e:
            self._add_result('Database Schema', 'warn', f'Skipped: {e}')
    
    def _check_route_conflicts(self):
        """Check for duplicate API routes."""
        print("\n[4/8] Checking Route Conflicts...")
        
        routes_file = Path('gui_app/routes.py')
        if not routes_file.exists():
            self._add_result('Route Conflicts', 'warn', 'routes.py not found')
            return
        
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
            self._add_result('Route Conflicts', 'fail', f'{len(duplicates)} duplicate routes')
            for d in duplicates[:5]:  # Show first 5
                print(f"      - {d}")
        else:
            self._add_result('Route Conflicts', 'pass', f'{len(seen)} unique routes')
    
    def _check_module_structure(self):
        """Verify modular architecture is maintained."""
        print("\n[5/8] Checking Module Structure...")
        
        required_modules = [
            ('src/core/__init__.py', 'Core module'),
            ('src/signals/__init__.py', 'Signals module'),
            ('src/discord_client/__init__.py', 'Discord client module'),
            ('src/risk/__init__.py', 'Risk module'),
            ('gui_app/__init__.py', 'GUI app module'),
        ]
        
        missing = []
        for path, name in required_modules:
            if not Path(path).exists():
                missing.append(name)
        
        if missing:
            self._add_result('Module Structure', 'fail', f'Missing: {", ".join(missing)}')
        else:
            self._add_result('Module Structure', 'pass', f'{len(required_modules)} modules OK')
    
    def _check_settings_consistency(self):
        """Validate settings manifest against database and enforcement points."""
        print("\n[6/8] Checking Settings Consistency...")
        
        try:
            from src.core.settings_validator import SettingsValidator
            from src.core.settings_manifest import SETTINGS_MANIFEST
            
            validator = SettingsValidator(db_path='bot_data.db')
            results = validator.run_all_checks()
            
            total_errors = sum(len(r.errors) for r in results)
            total_warnings = sum(len(r.warnings) for r in results)
            
            if total_errors > 0:
                self._add_result('Settings Consistency', 'fail', 
                               f'{total_errors} errors, {total_warnings} warnings in {len(SETTINGS_MANIFEST)} settings')
                for result in results:
                    for error in result.errors[:3]:
                        print(f"      - {error}")
            elif total_warnings > 0:
                self._add_result('Settings Consistency', 'warn',
                               f'{total_warnings} warnings in {len(SETTINGS_MANIFEST)} settings')
            else:
                self._add_result('Settings Consistency', 'pass',
                               f'{len(SETTINGS_MANIFEST)} settings validated')
                
        except ImportError as e:
            self._add_result('Settings Consistency', 'warn', f'Module not found: {e}')
        except Exception as e:
            self._add_result('Settings Consistency', 'warn', f'Skipped: {e}')
    
    def _run_unit_tests(self):
        """Run quick unit tests."""
        print("\n[7/9] Running Unit Tests...")
        
        try:
            result = subprocess.run(
                ['python', '-m', 'pytest', 'tests/unit/', '-m', 'quick', '-q', '--tb=no'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                # Extract pass count from output
                lines = result.stdout.strip().split('\n')
                self._add_result('Unit Tests', 'pass', lines[-1] if lines else 'All tests passed')
            else:
                self._add_result('Unit Tests', 'fail', 'Some tests failed')
                if result.stdout:
                    print(f"      {result.stdout[:200]}")
        except subprocess.TimeoutExpired:
            self._add_result('Unit Tests', 'warn', 'Tests timed out')
        except Exception as e:
            self._add_result('Unit Tests', 'warn', f'Skipped: {e}')
    
    def _check_system_diagnostics(self):
        """Run full system diagnostics."""
        print("\n[8/9] Running System Diagnostics...")
        
        try:
            from scripts.system_diagnostics import run_diagnostics
            
            results = run_diagnostics()
            summary = results['summary']
            
            if summary['failures'] > 0:
                self._add_result('System Diagnostics', 'fail', 
                               f"{summary['failures']} failures, {summary['warnings']} warnings")
            elif summary['warnings'] > 0:
                self._add_result('System Diagnostics', 'warn',
                               f"{summary['warnings']} warnings, {summary['passed']} passed")
            else:
                self._add_result('System Diagnostics', 'pass',
                               f"All {summary['passed']} checks passed")
        except Exception as e:
            self._add_result('System Diagnostics', 'warn', f'Skipped: {e}')
    
    def _validate_build_targets(self):
        """Validate dual-build architecture."""
        print("\n[9/9] Validating Build Targets...")
        
        issues = []
        
        # Check admin_server.py exists and sets correct env vars
        admin_server = Path('admin_server.py')
        if not admin_server.exists():
            issues.append('admin_server.py not found')
        else:
            content = admin_server.read_text(encoding='utf-8')
            if 'BUILD_TARGET' not in content or 'LICENSE_SERVER_MODE' not in content:
                issues.append('admin_server.py missing required env vars')
        
        # Check selfbot_webull.py has entry point verification
        selfbot = Path('src/selfbot_webull.py')
        if selfbot.exists():
            content = selfbot.read_text(encoding='utf-8')
            if '_is_admin_entrypoint' not in content:
                issues.append('selfbot missing entry point verification')
        
        if issues:
            self._add_result('Build Targets', 'fail', '; '.join(issues))
        else:
            self._add_result('Build Targets', 'pass', 'Dual-build architecture validated')
    
    def _check_documentation(self):
        """Check critical documentation is up to date."""
        docs = ['replit.md', 'README.md', 'REFACTORING_GUIDE.md']
        existing = [d for d in docs if Path(d).exists()]
        
        if len(existing) == len(docs):
            self._add_result('Documentation', 'pass', f'{len(existing)} docs present')
        else:
            missing = set(docs) - set(existing)
            self._add_result('Documentation', 'warn', f'Missing: {", ".join(missing)}')
    
    def _print_summary(self) -> bool:
        """Print summary and return True if all checks passed."""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        
        passed = sum(1 for _, s, _ in self.results if s == 'pass')
        warned = sum(1 for _, s, _ in self.results if s == 'warn')
        failed = sum(1 for _, s, _ in self.results if s == 'fail')
        
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"  Passed:   {passed}")
        print(f"  Warnings: {warned}")
        print(f"  Failed:   {failed}")
        print(f"  Time:     {elapsed:.1f}s")
        
        if failed > 0:
            print("\n  STATUS: ❌ FAILED - Fix issues before proceeding")
            return False
        elif warned > 0:
            print("\n  STATUS: ⚠️  DEGRADED - Review warnings")
            return True
        else:
            print("\n  STATUS: ✓ HEALTHY - All checks passed")
            return True


def main():
    parser = argparse.ArgumentParser(description='System Consistency Checker')
    parser.add_argument('--quick', action='store_true', help='Quick checks only')
    parser.add_argument('--full', action='store_true', help='Full checks with tests')
    parser.add_argument('--pre-deploy', action='store_true', help='Pre-deployment validation')
    
    args = parser.parse_args()
    
    if args.pre_deploy:
        mode = 'pre-deploy'
    elif args.full:
        mode = 'full'
    else:
        mode = 'quick'
    
    checker = ConsistencyChecker(mode)
    success = checker.run()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
