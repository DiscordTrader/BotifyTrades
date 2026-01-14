"""
BotifyTrades QA Framework - Shared Test Fixtures
Industry-grade testing infrastructure with mocks, factories, and utilities
"""
import pytest
import sys
import os
import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any, Optional, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from qa.tests.mocks.mock_broker import MockBroker, MockAlpacaBroker, MockWebullBroker
from qa.tests.mocks.mock_discord import MockDiscordClient, MockMessage, MockChannel
from qa.tests.mocks.mock_market_data import MockMarketData


@pytest.fixture(scope="session")
def test_db_path():
    """Create a temporary test database"""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def test_db(test_db_path):
    """Initialize test database with schema"""
    conn = sqlite3.connect(test_db_path)
    conn.row_factory = sqlite3.Row
    
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_channel_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            execute_enabled INTEGER DEFAULT 0,
            track_enabled INTEGER DEFAULT 0,
            broker_override TEXT,
            is_active INTEGER DEFAULT 1,
            paper_trade_enabled INTEGER DEFAULT 0,
            profit_target_pct REAL,
            stop_loss_pct REAL,
            trailing_stop_pct REAL,
            trailing_activation_pct REAL,
            profit_target_1_pct REAL,
            profit_target_2_pct REAL,
            profit_target_3_pct REAL,
            profit_target_4_pct REAL,
            enabled_brokers TEXT,
            position_size_pct REAL,
            default_quantity INTEGER,
            risk_management_enabled INTEGER DEFAULT 0,
            conditional_order_enabled INTEGER DEFAULT 1,
            leave_runner_enabled INTEGER DEFAULT 0,
            leave_runner_pct REAL DEFAULT 25.0,
            exit_strategy_mode TEXT DEFAULT 'hybrid',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            quantity REAL,
            price REAL,
            broker TEXT,
            status TEXT DEFAULT 'PENDING',
            order_id TEXT,
            channel_id TEXT,
            message_id TEXT,
            asset_type TEXT DEFAULT 'option',
            strike REAL,
            expiry TEXT,
            opt_type TEXT,
            executed_price REAL,
            intended_price REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS signal_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            quantity REAL,
            entry_price REAL,
            broker TEXT,
            channel_id TEXT,
            status TEXT DEFAULT 'OPEN',
            exit_price REAL,
            pnl REAL,
            pnl_pct REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS bot_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT NOT NULL UNIQUE,
            setting_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def mock_alpaca_broker():
    """Mock Alpaca paper broker"""
    return MockAlpacaBroker(name='ALPACA_PAPER', paper_trade=True)


@pytest.fixture
def mock_webull_broker():
    """Mock Webull live broker"""
    return MockWebullBroker(name='WEBULL', paper_trade=False)


@pytest.fixture
def mock_brokers(mock_alpaca_broker, mock_webull_broker):
    """Dictionary of all mock brokers"""
    return {
        'ALPACA_PAPER': mock_alpaca_broker,
        'WEBULL': mock_webull_broker,
    }


@pytest.fixture
def mock_discord_client():
    """Mock Discord client"""
    return MockDiscordClient()


@pytest.fixture
def mock_market_data():
    """Mock market data provider"""
    return MockMarketData()


@pytest.fixture
def channel_factory(test_db):
    """Factory for creating test channels"""
    def _create_channel(
        discord_channel_id: str = None,
        name: str = "test-channel",
        category: str = "test",
        execute_enabled: int = 1,
        enabled_brokers: List[str] = None,
        risk_management_enabled: int = 0,
        stop_loss_pct: float = None,
        trailing_stop_pct: float = None,
        trailing_activation_pct: float = None,
        profit_target_1_pct: float = None,
        exit_strategy_mode: str = 'hybrid',
        leave_runner_enabled: int = 0,
        conditional_order_enabled: int = 1
    ) -> Dict[str, Any]:
        if discord_channel_id is None:
            discord_channel_id = str(int(datetime.now().timestamp() * 1000000))
        
        brokers_json = json.dumps(enabled_brokers) if enabled_brokers else None
        
        cursor = test_db.execute("""
            INSERT INTO channels (
                discord_channel_id, name, category, execute_enabled,
                enabled_brokers, risk_management_enabled, stop_loss_pct,
                trailing_stop_pct, trailing_activation_pct, profit_target_1_pct,
                exit_strategy_mode, leave_runner_enabled, conditional_order_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            discord_channel_id, name, category, execute_enabled,
            brokers_json, risk_management_enabled, stop_loss_pct,
            trailing_stop_pct, trailing_activation_pct, profit_target_1_pct,
            exit_strategy_mode, leave_runner_enabled, conditional_order_enabled
        ))
        test_db.commit()
        
        return {
            'id': cursor.lastrowid,
            'discord_channel_id': discord_channel_id,
            'name': name,
            'enabled_brokers': enabled_brokers,
            'execute_enabled': execute_enabled,
            'risk_management_enabled': risk_management_enabled,
        }
    
    return _create_channel


@pytest.fixture
def signal_factory():
    """Factory for creating test signals"""
    def _create_signal(
        action: str = 'BTO',
        symbol: str = 'SPY',
        strike: float = 450.0,
        expiry: str = '01/17',
        opt_type: str = 'C',
        price: float = 1.50,
        quantity: int = 10,
        channel_id: str = '123456789',
        message_id: str = None,
        broker: str = None
    ) -> Dict[str, Any]:
        if message_id is None:
            message_id = str(int(datetime.now().timestamp() * 1000000))
        
        return {
            'action': action,
            'symbol': symbol,
            'strike': strike,
            'expiry': expiry,
            'opt_type': opt_type,
            'price': price,
            'qty': quantity,
            'channel_id': channel_id,
            'message_id': message_id,
            'broker': broker,
            'asset': 'option',
        }
    
    return _create_signal


class SignalTestVectors:
    """Golden test vectors for all signal formats"""
    
    BTO_STC_SIGNALS = [
        ("BTO 10 SPY 450c 01/17 @ 1.50", {
            'action': 'BTO', 'symbol': 'SPY', 'strike': 450.0,
            'opt_type': 'C', 'qty': 10, 'price': 1.50
        }),
        ("STC 5 AAPL 180p 02/21 @ 2.25", {
            'action': 'STC', 'symbol': 'AAPL', 'strike': 180.0,
            'opt_type': 'P', 'qty': 5, 'price': 2.25
        }),
    ]
    
    BULLWINKLE_SIGNALS = [
        ("TSLA 250c 01/19 lotto @ 0.50", {
            'action': 'BTO', 'symbol': 'TSLA', 'strike': 250.0,
            'opt_type': 'C', 'price': 0.50
        }),
    ]
    
    JACOB_SIGNALS = [
        ("ENTERED LONG NVDA 500c 01/24 @ 3.50", {
            'action': 'BTO', 'symbol': 'NVDA', 'strike': 500.0,
            'opt_type': 'C', 'price': 3.50
        }),
    ]
    
    BISHOP_SIGNALS = [
        ("I'M ENTERING\nOption: META 400c 02/14\nEntry: $2.00", {
            'action': 'BTO', 'symbol': 'META', 'strike': 400.0,
            'opt_type': 'C', 'price': 2.00
        }),
    ]
    
    CONDITIONAL_SIGNALS = [
        ("BTO 10 QQQ 400c 01/17 @ 1.00 over 399", {
            'action': 'BTO', 'symbol': 'QQQ', 'strike': 400.0,
            'trigger_type': 'over', 'trigger_price': 399.0
        }),
    ]
    
    EVAPANDA_SIGNALS = [
        ("🐼 AAPL 195c 01/24 @ 1.25 🎯", {
            'action': 'BTO', 'symbol': 'AAPL', 'strike': 195.0,
            'opt_type': 'C', 'price': 1.25
        }),
    ]


@pytest.fixture
def signal_test_vectors():
    """Provide access to golden test vectors"""
    return SignalTestVectors()


@pytest.fixture
def freeze_time():
    """Context manager for freezing time in tests"""
    class TimeFreezer:
        def __init__(self):
            self.frozen_time = None
            self._patch = None
        
        def freeze(self, dt: datetime):
            self.frozen_time = dt
            self._patch = patch('datetime.datetime')
            mock_dt = self._patch.start()
            mock_dt.now.return_value = dt
            mock_dt.utcnow.return_value = dt
            return self
        
        def unfreeze(self):
            if self._patch:
                self._patch.stop()
    
    freezer = TimeFreezer()
    yield freezer
    freezer.unfreeze()


pytest.register_assert_rewrite('qa.tests.mocks')
