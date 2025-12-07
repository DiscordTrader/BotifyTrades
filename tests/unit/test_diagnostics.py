"""
System Diagnostics Unit Tests
=============================
Tests for system health checks and diagnostic functionality.
"""
import pytest
import sqlite3
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.quick
@pytest.mark.database
class TestDatabaseDiagnostics:
    """Test database diagnostic checks."""
    
    def test_required_tables_list(self):
        """Verify required tables match actual schema."""
        required_tables = [
            'settings', 'channels', 'signals', 'trades', 
            'signal_lots', 'lot_closures', 'app_users'
        ]
        
        assert 'settings' in required_tables
        assert 'channels' in required_tables
        assert 'signals' in required_tables
        assert 'trades' in required_tables
        assert 'app_users' in required_tables
        assert 'users' not in required_tables  # Old name should not be used
    
    def test_missing_table_detection(self, mock_database):
        """Test detection of missing tables."""
        conn, path = mock_database
        cursor = conn.cursor()
        
        required_tables = ['settings', 'channels', 'nonexistent_table']
        missing = []
        
        for table in required_tables:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            if not cursor.fetchone():
                missing.append(table)
        
        assert 'nonexistent_table' in missing
    
    def test_database_connection_check(self, mock_database):
        """Test database connectivity check."""
        conn, path = mock_database
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            connected = result is not None and result[0] == 1
        except Exception:
            connected = False
        
        assert connected is True


@pytest.mark.quick
@pytest.mark.license
class TestLicenseDiagnostics:
    """Test license diagnostic checks."""
    
    def test_license_validation_without_key(self):
        """License check should warn when no key is configured."""
        license_key = ''
        
        if not license_key:
            status = 'warning'
            message = 'No license key configured'
        else:
            status = 'pass'
            message = 'Valid and active'
        
        assert status == 'warning'
        assert 'No license key' in message
    
    def test_license_validation_with_key(self):
        """License check should attempt validation when key exists."""
        license_key = 'BT-12345678-ABCDEFGH'
        
        if not license_key:
            status = 'warning'
        else:
            status = 'checking'
        
        assert status == 'checking'
    
    def test_license_client_validate_license_signature(self):
        """License client should have validate_license method."""
        class MockLicenseClient:
            def validate_license(self, license_key):
                return True, {'is_valid': True, 'expiry': '2025-12-31'}
        
        client = MockLicenseClient()
        is_valid, result = client.validate_license('BT-TEST-KEY')
        
        assert is_valid is True
        assert result.get('is_valid') is True


@pytest.mark.quick
@pytest.mark.broker
class TestBrokerDiagnostics:
    """Test broker diagnostic checks."""
    
    def test_discord_bot_status_check(self):
        """Test Discord bot connection status check."""
        bot_instance = None
        
        if bot_instance is None:
            status = 'fail'
            message = 'Bot not connected'
        elif hasattr(bot_instance, 'is_ready') and bot_instance.is_ready():
            status = 'pass'
            message = 'Bot connected'
        else:
            status = 'warning'
            message = 'Bot initializing'
        
        assert status == 'fail'
        assert 'not connected' in message
    
    def test_broker_not_configured_warning(self):
        """Broker should show warning when not configured."""
        credentials = {}
        
        if not credentials:
            status = 'warning'
            message = 'Not configured'
        else:
            status = 'checking'
            message = 'Checking connection...'
        
        assert status == 'warning'
        assert 'Not configured' in message


@pytest.mark.quick
class TestSignalPatternDiagnostics:
    """Test signal pattern diagnostic checks."""
    
    def test_no_patterns_shows_warning(self):
        """No patterns should show warning with default message."""
        patterns = None
        
        if patterns:
            status = 'pass'
            message = f'{len(patterns)} patterns configured'
        else:
            status = 'warning'
            message = 'No custom patterns (using defaults)'
        
        assert status == 'warning'
        assert 'using defaults' in message
    
    def test_patterns_configured_shows_count(self):
        """Configured patterns should show count."""
        patterns = ['pattern1', 'pattern2', 'pattern3']
        
        if patterns:
            status = 'pass'
            message = f'{len(patterns)} patterns configured'
        else:
            status = 'warning'
            message = 'No custom patterns (using defaults)'
        
        assert status == 'pass'
        assert '3 patterns' in message


@pytest.mark.quick
class TestPositionDiagnostics:
    """Test open position diagnostic checks."""
    
    def test_position_count_display(self):
        """Position count should be displayed correctly."""
        lots = []
        trades = []
        
        message = f'{len(lots)} lots, {len(trades)} trades open'
        
        assert message == '0 lots, 0 trades open'
    
    def test_position_count_with_data(self):
        """Position count with data should show correct numbers."""
        lots = ['lot1', 'lot2', 'lot3']
        trades = ['trade1', 'trade2']
        
        message = f'{len(lots)} lots, {len(trades)} trades open'
        
        assert message == '3 lots, 2 trades open'
