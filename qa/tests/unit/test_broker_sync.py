"""
Unit Tests for Broker Sync Service
Tests timestamp normalization, filled orders sync, and reconciliation

Covers fixes from 2026-01-08:
- Webull timestamp format conversion (MM/DD/YYYY HH:MM:SS EST -> ISO)
- Date filtering using created_at instead of filled_at
- Reconciliation running every sync cycle
"""
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
import asyncio


class TestTimestampNormalization(unittest.TestCase):
    """Test timestamp format conversion for various broker formats"""
    
    def setUp(self):
        from src.services.broker_sync_service import BrokerSyncService
        self.sync_service = BrokerSyncService(
            broker_manager=Mock(),
            db=Mock(),
            sync_interval=30
        )
    
    def test_webull_est_format(self):
        """Webull format: MM/DD/YYYY HH:MM:SS EST"""
        result = self.sync_service._normalize_timestamp("01/08/2026 14:11:41 EST")
        self.assertEqual(result, "2026-01-08T14:11:41")
    
    def test_webull_edt_format(self):
        """Webull format with EDT timezone"""
        result = self.sync_service._normalize_timestamp("07/15/2026 09:30:00 EDT")
        self.assertEqual(result, "2026-07-15T09:30:00")
    
    def test_already_iso_with_t(self):
        """Already ISO format with T separator"""
        result = self.sync_service._normalize_timestamp("2026-01-08T14:11:41")
        self.assertEqual(result, "2026-01-08T14:11:41")
    
    def test_iso_with_space(self):
        """ISO format with space instead of T"""
        result = self.sync_service._normalize_timestamp("2026-01-08 14:11:41")
        self.assertEqual(result, "2026-01-08T14:11:41")
    
    def test_iso_with_timezone(self):
        """ISO format with timezone suffix"""
        result = self.sync_service._normalize_timestamp("2026-01-08T14:11:41+00:00")
        self.assertEqual(result, "2026-01-08T14:11:41")
    
    def test_iso_with_z(self):
        """ISO format with Z suffix"""
        result = self.sync_service._normalize_timestamp("2026-01-08T14:11:41Z")
        self.assertEqual(result, "2026-01-08T14:11:41")
    
    def test_empty_string_returns_current_time(self):
        """Empty string should return current ISO time"""
        result = self.sync_service._normalize_timestamp("")
        self.assertIsNotNone(result)
        self.assertIn("T", result)
    
    def test_none_returns_current_time(self):
        """None should return current ISO time"""
        result = self.sync_service._normalize_timestamp(None)
        self.assertIsNotNone(result)
    
    def test_webull_single_digit_month(self):
        """Webull format with single-digit month padded"""
        result = self.sync_service._normalize_timestamp("01/05/2026 08:30:00 EST")
        self.assertEqual(result, "2026-01-05T08:30:00")


class TestFilledOrdersDateFilter(unittest.TestCase):
    """Test that filled orders use created_at for date filtering"""
    
    def test_get_filled_orders_uses_created_at(self):
        """Verify query uses created_at, not filled_at"""
        import gui_app.database as db_module
        import inspect
        
        source = inspect.getsource(db_module.get_filled_orders)
        self.assertIn("created_at", source, 
            "get_filled_orders must use created_at for date filtering")
        self.assertNotIn("filled_at >= datetime", source,
            "get_filled_orders must NOT use filled_at for date comparison")


class TestReconciliationTiming(unittest.TestCase):
    """Test that reconciliation runs every sync cycle"""
    
    def test_reconciliation_called_in_sync_broker(self):
        """Reconcile should be called in _sync_broker (runs for each broker each cycle)"""
        from src.services.broker_sync_service import BrokerSyncService
        import inspect
        
        source = inspect.getsource(BrokerSyncService._sync_broker)
        
        self.assertIn("reconcile_risk_orders", source,
            "reconcile_risk_orders must be called in _sync_broker")


class TestPositionCacheAPI(unittest.TestCase):
    """Test PositionCache API for pending order tracking"""
    
    def test_add_pending_order_creates_entry(self):
        """Adding pending order should create cache entry if missing"""
        from src.risk.position_cache import PositionCache
        
        cache = PositionCache()
        position_key = "TEST_123456_100_C_2026-01-15"
        order_id = "order_001"
        
        cache.add_pending_order(position_key, order_id, tier=1, qty=5)
        
        self.assertIn(position_key, cache._cache,
            "Cache entry must be auto-created when adding pending order")
    
    def test_get_all_pending_orders(self):
        """Test get_all_pending_orders returns pending orders"""
        from src.risk.position_cache import PositionCache
        
        cache = PositionCache()
        position_key = "TEST_123456_100_C_2026-01-15"
        order_id = "order_001"
        
        cache.add_pending_order(position_key, order_id, tier=1, qty=5)
        
        all_pending = cache.get_all_pending_orders()
        self.assertIn(position_key, all_pending)
        self.assertIn(order_id, all_pending[position_key])
    
    def test_confirm_order_fill_marks_tier(self):
        """Confirm fill should mark tier as hit"""
        from src.risk.position_cache import PositionCache
        
        cache = PositionCache()
        position_key = "TEST_123456_100_C_2026-01-15"
        order_id = "order_001"
        
        cache.add_pending_order(position_key, order_id, tier=1, qty=5)
        
        result = cache.confirm_order_fill(position_key, order_id, qty_filled=5)
        
        self.assertTrue(result, "confirm_order_fill should return True on success")
        self.assertTrue(cache._cache[position_key].tier1_hit, "Tier 1 should be marked as hit")
    
    def test_fail_pending_order_does_not_mark_tier(self):
        """Failed order should not mark tier"""
        from src.risk.position_cache import PositionCache
        
        cache = PositionCache()
        position_key = "TEST_123456_100_C_2026-01-15"
        order_id = "order_001"
        
        cache.add_pending_order(position_key, order_id, tier=2, qty=5)
        
        tier = cache.fail_pending_order(position_key, order_id)
        
        self.assertEqual(tier, 2, "fail_pending_order should return tier number")
        self.assertFalse(cache._cache[position_key].tier2_hit, "Tier 2 should NOT be marked")


class TestDatabaseSchemaIntegrity(unittest.TestCase):
    """Test database schema meets requirements"""
    
    def test_filled_orders_has_required_columns(self):
        """filled_orders table must have required columns"""
        import sqlite3
        from pathlib import Path
        
        db_path = Path("/home/runner/workspace/bot_data.db")
        if not db_path.exists():
            self.skipTest("Database not found")
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(filled_orders)")
        columns = {row[1] for row in cursor.fetchall()}
        
        required = {'id', 'broker', 'broker_order_id', 'symbol', 'side', 
                   'quantity', 'filled_price', 'filled_at', 'created_at'}
        
        missing = required - columns
        self.assertEqual(missing, set(), f"Missing columns: {missing}")
        
        conn.close()
    
    def test_filled_orders_timestamps_are_iso(self):
        """All filled_at timestamps should be ISO format"""
        import sqlite3
        from pathlib import Path
        
        db_path = Path("/home/runner/workspace/bot_data.db")
        if not db_path.exists():
            self.skipTest("Database not found")
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) FROM filled_orders 
            WHERE filled_at LIKE '%/%'
        """)
        non_iso_count = cursor.fetchone()[0]
        
        self.assertEqual(non_iso_count, 0, 
            f"Found {non_iso_count} non-ISO timestamps in filled_orders.filled_at")
        
        conn.close()


class TestBrokerSyncIntegration(unittest.TestCase):
    """Integration tests for broker sync workflow"""
    
    def test_sync_converts_timestamps(self):
        """Full sync workflow should convert Webull timestamps"""
        from src.services.broker_sync_service import BrokerSyncService
        
        sync = BrokerSyncService(Mock(), Mock(), 30)
        
        webull_dates = [
            "01/08/2026 14:11:41 EST",
            "12/31/2025 09:30:00 EST",
            "07/04/2026 13:00:00 EDT",
        ]
        
        for webull_date in webull_dates:
            result = sync._normalize_timestamp(webull_date)
            self.assertNotIn("/", result, 
                f"Webull date {webull_date} not converted: {result}")
            self.assertIn("T", result,
                f"Result missing ISO T separator: {result}")


def run_all_tests():
    """Run all QA tests and return results"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestTimestampNormalization))
    suite.addTests(loader.loadTestsFromTestCase(TestFilledOrdersDateFilter))
    suite.addTests(loader.loadTestsFromTestCase(TestReconciliationTiming))
    suite.addTests(loader.loadTestsFromTestCase(TestPositionCacheAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseSchemaIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestBrokerSyncIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == "__main__":
    run_all_tests()
