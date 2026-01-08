"""
Database Integration Tests
==========================
Tests for database operations and schema validation.
"""

import unittest
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class TestDatabaseSchema(unittest.TestCase):
    """Test database schema integrity"""
    
    @classmethod
    def setUpClass(cls):
        """Set up database connection"""
        cls.db_path = 'botify_trades.db'
        if os.path.exists(cls.db_path):
            cls.conn = sqlite3.connect(cls.db_path)
            cls.conn.row_factory = sqlite3.Row
            cls.db_available = True
        else:
            cls.db_available = False
    
    @classmethod
    def tearDownClass(cls):
        """Close database connection"""
        if cls.db_available:
            cls.conn.close()
    
    def test_channels_table_exists(self):
        """Test channels table exists"""
        if not self.db_available:
            self.skipTest("Database not available")
        
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='channels'"
        )
        self.assertIsNotNone(cursor.fetchone())
    
    def test_channels_has_trade_summary_enabled(self):
        """Test channels table has trade_summary_enabled column"""
        if not self.db_available:
            self.skipTest("Database not available")
        
        cursor = self.conn.execute("PRAGMA table_info(channels)")
        columns = [row['name'] for row in cursor.fetchall()]
        self.assertIn('trade_summary_enabled', columns)
    
    def test_channels_has_leave_runner_enabled(self):
        """Test channels table has leave_runner_enabled column"""
        if not self.db_available:
            self.skipTest("Database not available")
        
        cursor = self.conn.execute("PRAGMA table_info(channels)")
        columns = [row['name'] for row in cursor.fetchall()]
        self.assertIn('leave_runner_enabled', columns)
    
    def test_channels_has_exit_strategy_mode(self):
        """Test channels table has exit_strategy_mode column"""
        if not self.db_available:
            self.skipTest("Database not available")
        
        cursor = self.conn.execute("PRAGMA table_info(channels)")
        columns = [row['name'] for row in cursor.fetchall()]
        self.assertIn('exit_strategy_mode', columns)
    
    def test_trades_table_exists(self):
        """Test trades table exists"""
        if not self.db_available:
            self.skipTest("Database not available")
        
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
        )
        self.assertIsNotNone(cursor.fetchone())
    
    def test_trading_settings_table_exists(self):
        """Test trading_settings table exists"""
        if not self.db_available:
            self.skipTest("Database not available")
        
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trading_settings'"
        )
        self.assertIsNotNone(cursor.fetchone())
    
    def test_trading_settings_has_trade_summary_enabled(self):
        """Test trading_settings table has trade_summary_enabled column"""
        if not self.db_available:
            self.skipTest("Database not available")
        
        cursor = self.conn.execute("PRAGMA table_info(trading_settings)")
        columns = [row['name'] for row in cursor.fetchall()]
        self.assertIn('trade_summary_enabled', columns)


class TestDatabaseOperations(unittest.TestCase):
    """Test database read/write operations"""
    
    @classmethod
    def setUpClass(cls):
        """Set up database module"""
        try:
            from gui_app import database as db
            db.init_db()
            cls.db = db
            cls.db_available = True
        except:
            cls.db_available = False
    
    def test_get_channels(self):
        """Test get_channels function"""
        if not self.db_available:
            self.skipTest("Database module not available")
        
        channels = self.db.get_channels()
        self.assertIsInstance(channels, list)
    
    def test_get_trading_settings(self):
        """Test get_trading_settings function"""
        if not self.db_available:
            self.skipTest("Database module not available")
        
        settings = self.db.get_trading_settings()
        self.assertIsInstance(settings, dict)
        self.assertIn('trade_summary_enabled', settings)
    
    def test_is_trade_summary_enabled(self):
        """Test is_trade_summary_enabled function"""
        if not self.db_available:
            self.skipTest("Database module not available")
        
        result = self.db.is_trade_summary_enabled()
        self.assertIsInstance(result, bool)


if __name__ == '__main__':
    unittest.main()
