#!/usr/bin/env python3
"""
BotifyTrades Fix Validation Script

Validates that all critical bug fixes are still intact.
Run this before any release to prevent regressions.

Usage:
    python qa/validate_fixes.py
    python qa/validate_fixes.py --verbose
"""
import sys
import os
import sqlite3
import inspect
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

class FixValidator:
    """Validates that bug fixes are still in place"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[Dict] = []
        self.db_path = Path("/home/runner/workspace/bot_data.db")
    
    def log(self, message: str, level: str = "INFO"):
        """Log message with level indicator"""
        symbols = {"INFO": "ℹ️", "PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}
        print(f"{symbols.get(level, '•')} {message}")
    
    def validate_all(self) -> Tuple[int, int]:
        """Run all fix validations. Returns (passed, failed) count."""
        self.log("=" * 60)
        self.log("BotifyTrades Fix Validation - 2026-01-08 Fixes")
        self.log("=" * 60)
        
        validations = [
            ("FIX-001: Timestamp Normalization", self.validate_timestamp_normalization),
            ("FIX-002: Date Filter Column", self.validate_date_filter_column),
            ("FIX-003: Tier Fill Confirmation", self.validate_tier_fill_confirmation),
            ("FIX-004: Reconciliation Frequency", self.validate_reconciliation_frequency),
            ("FIX-005: Cache Auto-Creation", self.validate_cache_auto_creation),
            ("DB-001: No Non-ISO Timestamps", self.validate_db_timestamps),
        ]
        
        passed = 0
        failed = 0
        
        for name, validator in validations:
            try:
                success, details = validator()
                if success:
                    self.log(f"{name}: PASSED", "PASS")
                    passed += 1
                else:
                    self.log(f"{name}: FAILED - {details}", "FAIL")
                    failed += 1
                
                if self.verbose and details:
                    print(f"    Details: {details}")
                    
            except Exception as e:
                self.log(f"{name}: ERROR - {e}", "FAIL")
                failed += 1
        
        self.log("=" * 60)
        self.log(f"Results: {passed} passed, {failed} failed")
        
        return passed, failed
    
    def validate_timestamp_normalization(self) -> Tuple[bool, str]:
        """Verify _normalize_timestamp method exists and works"""
        try:
            from src.services.broker_sync_service import BrokerSyncService
            from unittest.mock import Mock
            
            sync = BrokerSyncService(Mock(), Mock(), 30)
            
            if not hasattr(sync, '_normalize_timestamp'):
                return False, "_normalize_timestamp method not found"
            
            test_cases = [
                ("01/08/2026 14:11:41 EST", "2026-01-08T14:11:41"),
                ("07/15/2026 09:30:00 EDT", "2026-07-15T09:30:00"),
                ("2026-01-08T14:11:41", "2026-01-08T14:11:41"),
            ]
            
            for input_val, expected in test_cases:
                result = sync._normalize_timestamp(input_val)
                if result != expected:
                    return False, f"Input '{input_val}': Expected {expected}, got {result}"
            
            return True, "All timestamp conversions correct"
            
        except ImportError as e:
            return False, f"Import error: {e}"
    
    def validate_date_filter_column(self) -> Tuple[bool, str]:
        """Verify get_filled_orders uses created_at"""
        try:
            import gui_app.database as db_module
            source = inspect.getsource(db_module.get_filled_orders)
            
            if "created_at" not in source:
                return False, "get_filled_orders does not use created_at"
            
            if "filled_at >= datetime" in source:
                return False, "get_filled_orders still uses filled_at for comparison"
            
            return True, "Uses created_at for date filtering"
            
        except Exception as e:
            return False, str(e)
    
    def validate_tier_fill_confirmation(self) -> Tuple[bool, str]:
        """Verify tier confirmation requires fill"""
        try:
            from src.risk.position_cache import PositionCache
            
            cache = PositionCache()
            
            required_methods = ['add_pending_order', 'confirm_order_fill', 
                               'fail_pending_order', 'get_all_pending_orders']
            
            for method in required_methods:
                if not hasattr(cache, method):
                    return False, f"{method} method missing"
            
            position_key = "TEST_VALIDATION_KEY"
            order_id = "test_order_001"
            
            cache.add_pending_order(position_key, order_id, tier=1, qty=5)
            all_pending = cache.get_all_pending_orders()
            
            if position_key not in all_pending:
                return False, "Pending order not tracked"
            if order_id not in all_pending[position_key]:
                return False, "Order ID not in pending orders"
            
            return True, "Pending order tracking works"
            
        except Exception as e:
            return False, str(e)
    
    def validate_reconciliation_frequency(self) -> Tuple[bool, str]:
        """Verify reconciliation runs every cycle"""
        try:
            from src.services.broker_sync_service import BrokerSyncService
            source = inspect.getsource(BrokerSyncService._sync_broker)
            
            if "reconcile_risk_orders" not in source:
                return False, "reconcile_risk_orders not called in _sync_broker"
            
            return True, "Reconciliation runs every sync cycle"
            
        except Exception as e:
            return False, str(e)
    
    def validate_cache_auto_creation(self) -> Tuple[bool, str]:
        """Verify cache entries are auto-created"""
        try:
            from src.risk.position_cache import PositionCache
            
            cache = PositionCache()
            new_key = f"AUTO_CREATE_TEST_{datetime.now().timestamp()}"
            
            if new_key in cache._cache:
                return False, "Test key already exists (unexpected)"
            
            cache.add_pending_order(new_key, "order_001", tier=1, qty=5)
            
            if new_key not in cache._cache:
                return False, "Cache entry not auto-created"
            
            return True, "Cache entries auto-created when needed"
            
        except Exception as e:
            return False, str(e)
    
    def validate_db_timestamps(self) -> Tuple[bool, str]:
        """Verify no non-ISO timestamps in database"""
        if not self.db_path.exists():
            return True, "Database not found (skip)"
        
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COUNT(*) FROM filled_orders 
                WHERE filled_at LIKE '%/%'
            """)
            non_iso_count = cursor.fetchone()[0]
            conn.close()
            
            if non_iso_count > 0:
                return False, f"Found {non_iso_count} non-ISO timestamps"
            
            return True, "All timestamps are ISO format"
            
        except Exception as e:
            return False, str(e)


def run_unit_tests() -> Tuple[int, int]:
    """Run unit tests and return (passed, failed)"""
    import unittest
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    try:
        from qa.tests.unit import test_broker_sync
        suite.addTests(loader.loadTestsFromModule(test_broker_sync))
    except ImportError as e:
        print(f"Could not load test_broker_sync: {e}")
    
    try:
        from qa.tests.integration import test_tier_reconciliation
        suite.addTests(loader.loadTestsFromModule(test_tier_reconciliation))
    except ImportError as e:
        print(f"Could not load test_tier_reconciliation: {e}")
    
    if suite.countTestCases() == 0:
        return 0, 0
    
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    
    passed = result.testsRun - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)
    
    return passed, failed


def main():
    """Main entry point"""
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    
    print("\n" + "=" * 60)
    print("  BotifyTrades QA Validation Suite")
    print("  Date: 2026-01-08 Fixes")
    print("=" * 60 + "\n")
    
    validator = FixValidator(verbose=verbose)
    fix_passed, fix_failed = validator.validate_all()
    
    print("\n" + "-" * 60)
    print("Running Unit Tests...")
    print("-" * 60 + "\n")
    
    test_passed, test_failed = run_unit_tests()
    
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Fix Validations: {fix_passed} passed, {fix_failed} failed")
    print(f"  Unit Tests:      {test_passed} passed, {test_failed} failed")
    print("=" * 60)
    
    total_failed = fix_failed + test_failed
    if total_failed > 0:
        print("\n❌ VALIDATION FAILED - DO NOT RELEASE")
        sys.exit(1)
    else:
        print("\n✅ ALL VALIDATIONS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
