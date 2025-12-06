"""
BotifyTrades Test Configuration and Fixtures
============================================
Central configuration for all tests with reusable fixtures.
"""
import os
import sys
import pytest
import sqlite3
import tempfile
import json
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'gui_app'))

@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent

@pytest.fixture
def temp_db():
    """Create a temporary SQLite database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    conn = sqlite3.connect(path)
    yield conn, path
    conn.close()
    os.unlink(path)

@pytest.fixture
def mock_database(temp_db):
    """Create a mock database with all required tables."""
    conn, path = temp_db
    cursor = conn.cursor()
    
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT UNIQUE NOT NULL,
            channel_name TEXT,
            guild_name TEXT,
            execute_trades INTEGER DEFAULT 0,
            track_only INTEGER DEFAULT 0,
            broker TEXT DEFAULT 'webull',
            position_size_pct REAL DEFAULT 0,
            profit_target_pct REAL DEFAULT 0,
            stop_loss_pct REAL DEFAULT 0,
            trailing_stop_pct REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            quantity REAL,
            price REAL,
            broker TEXT DEFAULT 'webull',
            status TEXT DEFAULT 'pending',
            source_channel_id TEXT,
            source_channel_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP,
            pnl REAL
        );
        
        CREATE TABLE IF NOT EXISTS server_licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL,
            customer_email TEXT,
            license_type TEXT DEFAULT 'subscription',
            status TEXT DEFAULT 'active',
            max_devices INTEGER DEFAULT 1,
            devices_used INTEGER DEFAULT 0,
            machine_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            last_validated_at TIMESTAMP,
            last_validated_ip TEXT,
            is_active INTEGER DEFAULT 1,
            activations_used INTEGER DEFAULT 0,
            max_activations INTEGER DEFAULT 1
        );
        
        CREATE TABLE IF NOT EXISTS license_validation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT NOT NULL,
            validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ip_address TEXT,
            machine_id TEXT,
            success INTEGER DEFAULT 1,
            error_message TEXT
        );
    ''')
    conn.commit()
    yield conn, path

@pytest.fixture
def sample_license_data():
    """Sample license data for testing."""
    return {
        'license_key': 'BT-TEST1234-ABCD5678',
        'customer_name': 'Test Customer',
        'customer_email': 'test@example.com',
        'license_type': 'subscription',
        'expires_at': (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S'),
        'max_devices': 1
    }

@pytest.fixture
def sample_channel_data():
    """Sample channel configuration for testing."""
    return {
        'channel_id': '123456789012345678',
        'channel_name': 'test-signals',
        'guild_name': 'Test Server',
        'execute_trades': True,
        'track_only': False,
        'broker': 'alpaca_paper',
        'position_size_pct': 5.0,
        'profit_target_pct': 10.0,
        'stop_loss_pct': 5.0,
        'trailing_stop_pct': 3.0
    }

@pytest.fixture
def sample_trade_data():
    """Sample trade data for testing."""
    return {
        'symbol': 'AAPL',
        'action': 'BUY',
        'quantity': 10,
        'price': 150.50,
        'broker': 'alpaca_paper',
        'status': 'filled',
        'source_channel_id': '123456789012345678',
        'source_channel_name': 'test-signals'
    }

@pytest.fixture
def sample_signal_messages():
    """Sample Discord messages that should be parsed as trading signals."""
    return [
        "BUY AAPL @ 150.50",
        "SELL TSLA @ 250.00",
        "BTO NVDA 12/15 500C @ 5.50",
        "STC NVDA 12/15 500C @ 7.50",
        "Long SPY 450 calls expiring Friday",
        "Buying 100 shares of MSFT at market",
    ]

@pytest.fixture
def sample_non_signal_messages():
    """Sample Discord messages that should NOT be parsed as signals."""
    return [
        "Good morning everyone!",
        "What do you think about the market today?",
        "I'm watching AAPL closely",
        "Nice trade!",
        "Thanks for the call",
    ]

@pytest.fixture
def mock_alpaca_client():
    """Mock Alpaca trading client."""
    client = MagicMock()
    client.get_account.return_value = MagicMock(
        id='test-account-id',
        account_number='PA12345678',
        buying_power=100000.0,
        portfolio_value=150000.0,
        status='ACTIVE'
    )
    client.get_all_positions.return_value = []
    client.get_orders.return_value = []
    return client

@pytest.fixture
def mock_webull_client():
    """Mock Webull trading client."""
    client = MagicMock()
    client.get_account.return_value = {
        'accountId': 'test-webull-id',
        'netLiquidation': 100000.0,
        'buyingPower': 50000.0
    }
    client.get_positions.return_value = []
    client.get_history_orders.return_value = []
    return client

@pytest.fixture
def env_with_admin_bypass(monkeypatch):
    """Set environment variables for admin bypass mode."""
    monkeypatch.setenv('ADMIN_PASSWORD', 'test_admin_pass')
    monkeypatch.setenv('LICENSE_SERVER_MODE', 'false')
    yield

@pytest.fixture
def env_with_license_server_mode(monkeypatch):
    """Set environment variables for license server mode."""
    monkeypatch.setenv('LICENSE_SERVER_MODE', 'true')
    monkeypatch.setenv('ADMIN_PASSWORD', '')
    yield

@pytest.fixture
def flask_test_client(mock_database):
    """Create a Flask test client with mock database."""
    conn, db_path = mock_database
    
    with patch.dict(os.environ, {'DATABASE_PATH': db_path}):
        try:
            from gui_app.app import app
            app.config['TESTING'] = True
            app.config['WTF_CSRF_ENABLED'] = False
            with app.test_client() as client:
                yield client
        except ImportError:
            pytest.skip("Flask app not available")

class MockDiscordMessage:
    """Mock Discord message for testing signal parsing."""
    def __init__(self, content, channel_id='123456789', author_id='987654321', 
                 channel_name='test-channel', guild_name='Test Guild'):
        self.content = content
        self.channel = MagicMock()
        self.channel.id = channel_id
        self.channel.name = channel_name
        self.guild = MagicMock()
        self.guild.name = guild_name
        self.author = MagicMock()
        self.author.id = author_id
        self.author.name = 'TestUser'
        self.created_at = datetime.now()

@pytest.fixture
def mock_discord_message():
    """Factory fixture for creating mock Discord messages."""
    def _create_message(content, **kwargs):
        return MockDiscordMessage(content, **kwargs)
    return _create_message

def pytest_configure(config):
    """Configure pytest with custom markers and settings."""
    config.addinivalue_line("markers", "quick: Fast unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests")
    config.addinivalue_line("markers", "license: License system tests")
    config.addinivalue_line("markers", "broker: Broker tests")
    config.addinivalue_line("markers", "signal: Signal processing tests")
    config.addinivalue_line("markers", "database: Database tests")
    config.addinivalue_line("markers", "gui: GUI/API tests")

def pytest_collection_modifyitems(config, items):
    """Automatically add markers based on test location."""
    for item in items:
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.quick)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
