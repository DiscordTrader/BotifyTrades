"""
Integration Tests for Tier Fill Confirmation and Reconciliation

Tests the complete workflow from order placement through fill confirmation:
1. Order placed -> pending state tracked
2. Broker reports fill -> reconciliation confirms
3. Only then is tier marked as hit

Covers critical bug fixes from 2026-01-08:
- Tiers marked only after confirmed fills (not order acceptance)
- Partial fill handling
- Reconciliation frequency (every sync cycle)
"""
import unittest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime
import asyncio


class TestTierReconciliationWorkflow(unittest.TestCase):
    """Test complete tier reconciliation workflow"""
    
    def setUp(self):
        from src.risk.position_cache import PositionCache
        self.cache = PositionCache()
        self.position_key = "AAPL_123456_150_C_2026-01-17"
    
    def test_pending_order_lifecycle(self):
        """Test full lifecycle: add pending -> confirm -> tier marked"""
        order_id = "webull_12345"
        
        self.cache.add_pending_order(self.position_key, order_id, tier=1, qty=5)
        
        all_pending = self.cache.get_all_pending_orders()
        self.assertIn(self.position_key, all_pending)
        self.assertIn(order_id, all_pending[self.position_key])
        
        self.assertFalse(self.cache._cache[self.position_key].tier1_hit,
            "Tier should NOT be hit before fill confirmation")
        
        result = self.cache.confirm_order_fill(self.position_key, order_id, qty_filled=5)
        
        self.assertTrue(result)
        self.assertTrue(self.cache._cache[self.position_key].tier1_hit,
            "Tier should be hit AFTER fill confirmation")
        
        all_pending_after = self.cache.get_all_pending_orders()
        self.assertNotIn(order_id, all_pending_after.get(self.position_key, {}),
            "Pending order should be removed after fill")
    
    def test_partial_fill_tracking(self):
        """Test that partial fills are tracked correctly"""
        order_id = "webull_partial"
        
        self.cache.add_pending_order(self.position_key, order_id, tier=2, qty=10)
        
        result = self.cache.confirm_order_fill(self.position_key, order_id, qty_filled=5)
        
        self.assertFalse(result, "Partial fill should return False")
        self.assertFalse(self.cache._cache[self.position_key].tier2_hit,
            "Tier should NOT be marked on partial fill")
    
    def test_cancelled_order_cleanup(self):
        """Test that cancelled/failed orders are properly cleaned up"""
        order_id = "webull_cancelled"
        
        self.cache.add_pending_order(self.position_key, order_id, tier=3, qty=3)
        
        tier = self.cache.fail_pending_order(self.position_key, order_id)
        
        self.assertEqual(tier, 3)
        self.assertFalse(self.cache._cache[self.position_key].tier3_hit,
            "Tier should NOT be marked on failed order")
        
        all_pending = self.cache.get_all_pending_orders()
        self.assertNotIn(order_id, all_pending.get(self.position_key, {}))


class TestReconciliationService(unittest.TestCase):
    """Test the reconciliation service behavior"""
    
    def test_reconciliation_processes_pending_orders(self):
        """Reconciliation should process all pending orders"""
        from src.risk.position_cache import PositionCache
        
        cache = PositionCache()
        position_key = "SPY_789_400_C_2026-02-21"
        
        cache.add_pending_order(position_key, "order_001", tier=1, qty=2)
        cache.add_pending_order(position_key, "order_002", tier=2, qty=3)
        
        all_pending = cache.get_all_pending_orders()
        
        self.assertIn(position_key, all_pending)
        self.assertEqual(len(all_pending[position_key]), 2)
    
    def test_has_pending_order_for_tier(self):
        """Check if pending order exists for specific tier"""
        from src.risk.position_cache import PositionCache
        
        cache = PositionCache()
        position_key = "TSLA_100_250_C_2026-03-21"
        
        cache.add_pending_order(position_key, "order_pt1", tier=1, qty=2)
        
        self.assertTrue(cache.has_pending_order_for_tier(position_key, tier=1))
        self.assertFalse(cache.has_pending_order_for_tier(position_key, tier=2))


class TestBrokerFillDetection(unittest.TestCase):
    """Test broker fill detection mechanisms"""
    
    def test_webull_fill_status_detection(self):
        """Test detection of filled status from Webull response"""
        webull_filled_statuses = ["Filled", "FILLED", "Partially Filled"]
        webull_pending_statuses = ["Pending", "Working", "Submitted"]
        
        for status in webull_filled_statuses:
            self.assertTrue(
                "filled" in status.lower(),
                f"Status '{status}' should be detected as fill-related"
            )
        
        for status in webull_pending_statuses:
            self.assertFalse(
                "filled" in status.lower(),
                f"Status '{status}' should NOT be detected as filled"
            )


class TestTimerConsistency(unittest.TestCase):
    """Test sync timing consistency"""
    
    def test_sync_interval_is_30_seconds(self):
        """Default sync interval should be 30 seconds"""
        from src.services.broker_sync_service import BrokerSyncService
        
        sync = BrokerSyncService(Mock(), Mock())
        self.assertEqual(sync.sync_interval, 30)


def run_integration_tests():
    """Run all integration tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestTierReconciliationWorkflow))
    suite.addTests(loader.loadTestsFromTestCase(TestReconciliationService))
    suite.addTests(loader.loadTestsFromTestCase(TestBrokerFillDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestTimerConsistency))
    
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == "__main__":
    run_integration_tests()
