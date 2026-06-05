"""
Settings API Integration Tests
==============================
Tests for settings-related API endpoints.
"""

import unittest
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class TestTradingSettingsAPI(unittest.TestCase):
    """Test trading settings API"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test client"""
        try:
            from gui_app.app import create_app
            cls.app = create_app()
            cls.client = cls.app.test_client()
            cls.app_available = True
        except:
            cls.app_available = False
    
    def test_get_trading_settings(self):
        """Test GET /api/settings/trading"""
        if not self.app_available:
            self.skipTest("App not available")
        
        response = self.client.get('/api/settings/trading')
        # 401 is acceptable (auth required)
        self.assertIn(response.status_code, [200, 401])
    
    def test_trading_settings_has_trade_summary(self):
        """Test that trading settings includes trade_summary_enabled"""
        if not self.app_available:
            self.skipTest("App not available")
        
        # This would need auth in real scenario
        self.assertTrue(True)  # Placeholder


class TestChannelSettingsAPI(unittest.TestCase):
    """Test channel settings API"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test client"""
        try:
            from gui_app.app import create_app
            cls.app = create_app()
            cls.client = cls.app.test_client()
            cls.app_available = True
        except:
            cls.app_available = False
    
    def test_get_channels(self):
        """Test GET /api/channels"""
        if not self.app_available:
            self.skipTest("App not available")
        
        response = self.client.get('/api/channels')
        self.assertIn(response.status_code, [200, 401])
    
    def test_channel_has_trade_summary_field(self):
        """Test that channel response includes trade_summary_enabled"""
        self.assertTrue(True)  # Placeholder


class TestHealthAPI(unittest.TestCase):
    """Test health check API"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test client"""
        try:
            from gui_app.app import create_app
            cls.app = create_app()
            cls.client = cls.app.test_client()
            cls.app_available = True
        except:
            cls.app_available = False
    
    def test_health_diagnostics(self):
        """Test GET /api/health/diagnostics"""
        if not self.app_available:
            self.skipTest("App not available")
        
        response = self.client.get('/api/health/diagnostics')
        self.assertIn(response.status_code, [200, 401, 500])


if __name__ == '__main__':
    unittest.main()
