"""
Database Unit Tests
===================
Tests for database schema, operations, and data integrity.
"""
import pytest
import sqlite3
from datetime import datetime, timedelta
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.quick
@pytest.mark.database
class TestDatabaseSchema:
    """Test database schema integrity."""
    
    def test_required_tables_exist(self, mock_database):
        """Test that all required tables are created."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        required_tables = [
            'settings',
            'channels', 
            'trades',
            'server_licenses',
            'license_validation_log'
        ]
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in cursor.fetchall()]
        
        for table in required_tables:
            assert table in existing_tables, f"Table '{table}' should exist"
    
    def test_channels_table_schema(self, mock_database):
        """Test channels table has required columns."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(channels)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        required_columns = {
            'channel_id': 'TEXT',
            'channel_name': 'TEXT',
            'execute_trades': 'INTEGER',
            'track_only': 'INTEGER',
            'broker': 'TEXT',
            'position_size_pct': 'REAL',
            'profit_target_pct': 'REAL',
            'stop_loss_pct': 'REAL',
        }
        
        for col, col_type in required_columns.items():
            assert col in columns, f"Column '{col}' should exist in channels"
    
    def test_trades_table_schema(self, mock_database):
        """Test trades table has required columns."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(trades)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        required_columns = {
            'symbol': 'TEXT',
            'action': 'TEXT',
            'quantity': 'REAL',
            'price': 'REAL',
            'broker': 'TEXT',
            'status': 'TEXT',
            'source_channel_id': 'TEXT',
        }
        
        for col, col_type in required_columns.items():
            assert col in columns, f"Column '{col}' should exist in trades"
    
    def test_server_licenses_table_schema(self, mock_database):
        """Test server_licenses table has required columns."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute("PRAGMA table_info(server_licenses)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        required_columns = {
            'license_key': 'TEXT',
            'customer_name': 'TEXT',
            'license_type': 'TEXT',
            'status': 'TEXT',
            'max_devices': 'INTEGER',
            'expires_at': 'TIMESTAMP',
        }
        
        for col, col_type in required_columns.items():
            assert col in columns, f"Column '{col}' should exist in server_licenses"


@pytest.mark.quick
@pytest.mark.database
class TestChannelOperations:
    """Test channel database operations."""
    
    def test_add_channel(self, mock_database, sample_channel_data):
        """Test adding a new channel to database."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO channels 
            (channel_id, channel_name, guild_name, execute_trades, track_only, broker, position_size_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            sample_channel_data['channel_id'],
            sample_channel_data['channel_name'],
            sample_channel_data['guild_name'],
            1 if sample_channel_data['execute_trades'] else 0,
            1 if sample_channel_data['track_only'] else 0,
            sample_channel_data['broker'],
            sample_channel_data['position_size_pct']
        ))
        conn.commit()
        
        cursor.execute('SELECT * FROM channels WHERE channel_id = ?', 
                      (sample_channel_data['channel_id'],))
        result = cursor.fetchone()
        
        assert result is not None, "Channel should be added"
    
    def test_update_channel_settings(self, mock_database, sample_channel_data):
        """Test updating channel settings."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO channels (channel_id, channel_name, position_size_pct)
            VALUES (?, ?, ?)
        ''', (sample_channel_data['channel_id'], sample_channel_data['channel_name'], 5.0))
        conn.commit()
        
        new_position_size = 10.0
        cursor.execute('''
            UPDATE channels SET position_size_pct = ? WHERE channel_id = ?
        ''', (new_position_size, sample_channel_data['channel_id']))
        conn.commit()
        
        cursor.execute('SELECT position_size_pct FROM channels WHERE channel_id = ?',
                      (sample_channel_data['channel_id'],))
        result = cursor.fetchone()
        
        assert result[0] == new_position_size, "Position size should be updated"
    
    def test_channel_id_unique_constraint(self, mock_database, sample_channel_data):
        """Test that channel_id has unique constraint."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO channels (channel_id, channel_name) VALUES (?, ?)
        ''', (sample_channel_data['channel_id'], 'First'))
        conn.commit()
        
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute('''
                INSERT INTO channels (channel_id, channel_name) VALUES (?, ?)
            ''', (sample_channel_data['channel_id'], 'Duplicate'))
            conn.commit()


@pytest.mark.quick
@pytest.mark.database
class TestTradeOperations:
    """Test trade database operations."""
    
    def test_record_trade(self, mock_database, sample_trade_data):
        """Test recording a new trade."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades 
            (symbol, action, quantity, price, broker, status, source_channel_id, source_channel_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            sample_trade_data['symbol'],
            sample_trade_data['action'],
            sample_trade_data['quantity'],
            sample_trade_data['price'],
            sample_trade_data['broker'],
            sample_trade_data['status'],
            sample_trade_data['source_channel_id'],
            sample_trade_data['source_channel_name']
        ))
        conn.commit()
        
        cursor.execute('SELECT * FROM trades WHERE symbol = ?', (sample_trade_data['symbol'],))
        result = cursor.fetchone()
        
        assert result is not None, "Trade should be recorded"
    
    def test_update_trade_status(self, mock_database, sample_trade_data):
        """Test updating trade status."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades (symbol, action, quantity, price, status)
            VALUES (?, ?, ?, ?, 'pending')
        ''', (sample_trade_data['symbol'], sample_trade_data['action'], 
              sample_trade_data['quantity'], sample_trade_data['price']))
        conn.commit()
        trade_id = cursor.lastrowid
        
        cursor.execute('UPDATE trades SET status = ? WHERE id = ?', ('filled', trade_id))
        conn.commit()
        
        cursor.execute('SELECT status FROM trades WHERE id = ?', (trade_id,))
        result = cursor.fetchone()
        
        assert result[0] == 'filled', "Status should be updated to filled"
    
    def test_close_trade_with_pnl(self, mock_database, sample_trade_data):
        """Test closing a trade and recording PNL."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        entry_price = 100.0
        cursor.execute('''
            INSERT INTO trades (symbol, action, quantity, price, status)
            VALUES (?, 'BUY', 10, ?, 'filled')
        ''', (sample_trade_data['symbol'], entry_price))
        conn.commit()
        trade_id = cursor.lastrowid
        
        exit_price = 110.0
        quantity = 10
        pnl = (exit_price - entry_price) * quantity
        
        cursor.execute('''
            UPDATE trades SET status = 'closed', pnl = ?, closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (pnl, trade_id))
        conn.commit()
        
        cursor.execute('SELECT status, pnl FROM trades WHERE id = ?', (trade_id,))
        result = cursor.fetchone()
        
        assert result[0] == 'closed', "Trade should be closed"
        assert result[1] == 100.0, "PNL should be $100"
    
    def test_trade_source_channel_tracking(self, mock_database, sample_trade_data):
        """Test that trade source channel is properly tracked."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO trades 
            (symbol, action, quantity, price, source_channel_id, source_channel_name)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            sample_trade_data['symbol'],
            sample_trade_data['action'],
            sample_trade_data['quantity'],
            sample_trade_data['price'],
            sample_trade_data['source_channel_id'],
            sample_trade_data['source_channel_name']
        ))
        conn.commit()
        trade_id = cursor.lastrowid
        
        cursor.execute('''
            SELECT source_channel_id, source_channel_name FROM trades WHERE id = ?
        ''', (trade_id,))
        result = cursor.fetchone()
        
        assert result[0] == sample_trade_data['source_channel_id']
        assert result[1] == sample_trade_data['source_channel_name']


@pytest.mark.quick
@pytest.mark.database
class TestSettingsOperations:
    """Test settings database operations."""
    
    def test_save_setting(self, mock_database):
        """Test saving a setting."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)
        ''', ('debug_mode', 'true'))
        conn.commit()
        
        cursor.execute('SELECT value FROM settings WHERE key = ?', ('debug_mode',))
        result = cursor.fetchone()
        
        assert result[0] == 'true', "Setting should be saved"
    
    def test_update_setting(self, mock_database):
        """Test updating an existing setting."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('INSERT INTO settings (key, value) VALUES (?, ?)', 
                      ('test_setting', 'old_value'))
        conn.commit()
        
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)
        ''', ('test_setting', 'new_value'))
        conn.commit()
        
        cursor.execute('SELECT value FROM settings WHERE key = ?', ('test_setting',))
        result = cursor.fetchone()
        
        assert result[0] == 'new_value', "Setting should be updated"
    
    def test_get_setting_with_default(self, mock_database):
        """Test getting a setting with default value."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('SELECT value FROM settings WHERE key = ?', ('nonexistent_key',))
        result = cursor.fetchone()
        
        value = result[0] if result else 'default_value'
        assert value == 'default_value', "Should return default for missing key"


@pytest.mark.quick
@pytest.mark.database
class TestDataIntegrity:
    """Test data integrity constraints and validations."""
    
    def test_license_key_unique(self, mock_database):
        """Test that license keys must be unique."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO server_licenses (license_key, customer_name)
            VALUES ('BT-UNIQUE00-00000000', 'Customer 1')
        ''')
        conn.commit()
        
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute('''
                INSERT INTO server_licenses (license_key, customer_name)
                VALUES ('BT-UNIQUE00-00000000', 'Customer 2')
            ''')
            conn.commit()
    
    def test_required_fields_not_null(self, mock_database):
        """Test that required fields cannot be NULL."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        with pytest.raises(sqlite3.IntegrityError):
            cursor.execute('''
                INSERT INTO server_licenses (license_key, customer_name)
                VALUES (NULL, 'Test Customer')
            ''')
            conn.commit()
    
    def test_cascade_behavior(self, mock_database):
        """Test that related records are handled correctly."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO channels (channel_id, channel_name) VALUES ('test-channel', 'Test')
        ''')
        cursor.execute('''
            INSERT INTO trades (symbol, action, source_channel_id) 
            VALUES ('AAPL', 'BUY', 'test-channel')
        ''')
        conn.commit()
        
        cursor.execute('SELECT COUNT(*) FROM trades WHERE source_channel_id = ?', ('test-channel',))
        count = cursor.fetchone()[0]
        
        assert count == 1, "Trade should reference channel"
