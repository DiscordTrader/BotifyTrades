"""
Upgrade Readiness Checker
=========================
Performs pre-upgrade checks to ensure the system is ready for an update.
"""

import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple

from .backup_manager import get_backup_manager


class ReadinessCheck:
    """Result of a single readiness check."""
    
    def __init__(self, name: str, passed: bool, message: str, critical: bool = True):
        self.name = name
        self.passed = passed
        self.message = message
        self.critical = critical
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'passed': self.passed,
            'message': self.message,
            'critical': self.critical
        }


class ReadinessChecker:
    """Performs pre-upgrade readiness checks."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.environ.get('DATABASE_PATH', 'bot_data.db')
    
    def run_all_checks(self) -> Tuple[bool, List[ReadinessCheck]]:
        """
        Run all readiness checks.
        
        Returns:
            Tuple of (all_critical_passed, list of check results)
        """
        checks = [
            self.check_disk_space(),
            self.check_backup_writable(),
            self.check_database_accessible(),
            self.check_no_active_trades(),
            self.check_database_integrity(),
        ]
        
        all_critical_passed = all(c.passed for c in checks if c.critical)
        
        return all_critical_passed, checks
    
    def check_disk_space(self, min_mb: int = 100) -> ReadinessCheck:
        """Check if there's enough disk space for upgrade."""
        try:
            import shutil
            backup_dir = Path('upgrade/backups')
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            _, _, free = shutil.disk_usage(backup_dir)
            free_mb = free / (1024 * 1024)
            
            if free_mb >= min_mb:
                return ReadinessCheck(
                    "Disk Space",
                    True,
                    f"{free_mb:.0f} MB available",
                    critical=True
                )
            else:
                return ReadinessCheck(
                    "Disk Space",
                    False,
                    f"Only {free_mb:.0f} MB available (need {min_mb} MB)",
                    critical=True
                )
        except Exception as e:
            return ReadinessCheck(
                "Disk Space",
                False,
                f"Could not check disk space: {e}",
                critical=True
            )
    
    def check_backup_writable(self) -> ReadinessCheck:
        """Check if backup directory is writable."""
        try:
            backup_dir = Path('upgrade/backups')
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            test_file = backup_dir / '.write_test'
            test_file.write_text('test', encoding='utf-8')
            test_file.unlink()
            
            return ReadinessCheck(
                "Backup Location",
                True,
                "Backup directory is writable",
                critical=True
            )
        except Exception as e:
            return ReadinessCheck(
                "Backup Location",
                False,
                f"Cannot write to backup directory: {e}",
                critical=True
            )
    
    def check_database_accessible(self) -> ReadinessCheck:
        """Check if database is accessible."""
        try:
            if not Path(self.db_path).exists():
                return ReadinessCheck(
                    "Database",
                    True,
                    "No existing database (new installation)",
                    critical=True
                )
            
            conn = sqlite3.connect(self.db_path, timeout=5)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            conn.close()
            
            return ReadinessCheck(
                "Database",
                True,
                "Database is accessible",
                critical=True
            )
        except Exception as e:
            return ReadinessCheck(
                "Database",
                False,
                f"Database error: {e}",
                critical=True
            )
    
    def check_no_active_trades(self) -> ReadinessCheck:
        """Check if there are no active trades in progress."""
        try:
            if not Path(self.db_path).exists():
                return ReadinessCheck(
                    "Active Trades",
                    True,
                    "No database yet",
                    critical=False
                )
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
            if not cursor.fetchone():
                conn.close()
                return ReadinessCheck(
                    "Active Trades",
                    True,
                    "No trades table",
                    critical=False
                )
            
            cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'open' OR status = 'pending'")
            count = cursor.fetchone()[0]
            conn.close()
            
            if count == 0:
                return ReadinessCheck(
                    "Active Trades",
                    True,
                    "No active trades",
                    critical=False
                )
            else:
                return ReadinessCheck(
                    "Active Trades",
                    False,
                    f"{count} active trade(s) - consider closing before upgrade",
                    critical=False
                )
        except Exception as e:
            return ReadinessCheck(
                "Active Trades",
                True,
                f"Could not check trades: {e}",
                critical=False
            )
    
    def check_database_integrity(self) -> ReadinessCheck:
        """Run SQLite integrity check on database."""
        try:
            if not Path(self.db_path).exists():
                return ReadinessCheck(
                    "Database Integrity",
                    True,
                    "No database yet",
                    critical=True
                )
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()[0]
            conn.close()
            
            if result == 'ok':
                return ReadinessCheck(
                    "Database Integrity",
                    True,
                    "Database integrity OK",
                    critical=True
                )
            else:
                return ReadinessCheck(
                    "Database Integrity",
                    False,
                    f"Database integrity issue: {result}",
                    critical=True
                )
        except Exception as e:
            return ReadinessCheck(
                "Database Integrity",
                False,
                f"Integrity check failed: {e}",
                critical=True
            )
    
    def get_summary(self) -> Dict:
        """Get a summary of all readiness checks."""
        all_passed, checks = self.run_all_checks()
        
        passed_count = sum(1 for c in checks if c.passed)
        failed_count = len(checks) - passed_count
        critical_failed = sum(1 for c in checks if not c.passed and c.critical)
        
        return {
            'ready': all_passed,
            'total_checks': len(checks),
            'passed': passed_count,
            'failed': failed_count,
            'critical_failed': critical_failed,
            'checks': [c.to_dict() for c in checks]
        }


def check_upgrade_readiness() -> Tuple[bool, List[Dict]]:
    """
    Convenience function to check upgrade readiness.
    
    Returns:
        Tuple of (is_ready, list of check results as dicts)
    """
    checker = ReadinessChecker()
    ready, checks = checker.run_all_checks()
    return ready, [c.to_dict() for c in checks]
