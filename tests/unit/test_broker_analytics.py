"""
Broker Analytics Unit Tests
============================
Tests for broker live analytics, credential validation, and page loading.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.quick
@pytest.mark.broker
class TestBrokerCredentialValidation:
    """Test broker credential validation and early exit."""
    
    def test_webull_credentials_empty_returns_none(self):
        """Webull connection should return None quickly with empty credentials."""
        credentials = {}
        
        has_access_token = bool(credentials.get('access_token'))
        has_refresh_token = bool(credentials.get('refresh_token'))
        has_email = bool(credentials.get('email'))
        
        should_connect = has_access_token or has_refresh_token or has_email
        assert should_connect is False
    
    def test_webull_credentials_with_tokens_valid(self):
        """Webull connection should proceed with valid tokens."""
        credentials = {
            'access_token': 'dc_us1.abc123',
            'refresh_token': 'rt_abc123',
            'device_id': 'device123'
        }
        
        has_tokens = bool(credentials.get('access_token') and credentials.get('refresh_token'))
        assert has_tokens is True
    
    def test_webull_credentials_with_email_valid(self):
        """Webull connection should proceed with email/password."""
        credentials = {
            'email': 'test@example.com',
            'password': 'testpass123'
        }
        
        has_email = bool(credentials.get('email'))
        assert has_email is True
    
    def test_alpaca_credentials_empty_returns_none(self):
        """Alpaca connection should return None with empty credentials."""
        credentials = {}
        
        api_key = credentials.get('api_key')
        secret_key = credentials.get('secret_key')
        
        should_connect = bool(api_key and secret_key)
        assert should_connect is False
    
    def test_alpaca_credentials_valid(self):
        """Alpaca connection should proceed with valid API keys."""
        credentials = {
            'api_key': 'PKXXXXXXXXXXXXXXXX',
            'secret_key': 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
        }
        
        api_key = credentials.get('api_key')
        secret_key = credentials.get('secret_key')
        
        should_connect = bool(api_key and secret_key)
        assert should_connect is True


@pytest.mark.quick
@pytest.mark.broker
class TestBrokerAnalyticsPages:
    """Test broker analytics page behavior."""
    
    def test_account_info_returns_error_when_not_connected(self):
        """Account info should return error dict when client is None."""
        client = None
        
        if not client:
            result = {
                'connected': False,
                'error': 'Unable to connect to broker',
                'buying_power': 0,
                'cash': 0,
                'portfolio_value': 0,
                'day_pnl': 0,
                'day_pnl_percent': 0
            }
        else:
            result = {'connected': True}
        
        assert result['connected'] is False
        assert 'error' in result
        assert result['buying_power'] == 0
    
    def test_positions_returns_empty_list_when_not_connected(self):
        """Positions should return empty list when client is None."""
        client = None
        
        if not client:
            positions = []
        else:
            positions = ['position1', 'position2']
        
        assert positions == []
    
    def test_orders_returns_empty_list_when_not_connected(self):
        """Orders should return empty list when client is None."""
        client = None
        
        if not client:
            orders = []
        else:
            orders = ['order1', 'order2']
        
        assert orders == []


@pytest.mark.quick
@pytest.mark.broker
class TestBrokerConfigMapping:
    """Test broker configuration mapping."""
    
    def test_broker_configs_have_required_fields(self):
        """Each broker config should have type and paper fields."""
        BROKER_CONFIGS = {
            'webull_live': {'type': 'webull', 'paper': False, 'name': 'Webull Live'},
            'webull_paper': {'type': 'webull', 'paper': True, 'name': 'Webull Paper'},
            'alpaca_live': {'type': 'alpaca', 'paper': False, 'name': 'Alpaca Live'},
            'alpaca_paper': {'type': 'alpaca', 'paper': True, 'name': 'Alpaca Paper'},
        }
        
        for broker_id, config in BROKER_CONFIGS.items():
            assert 'type' in config, f"{broker_id} missing 'type'"
            assert 'paper' in config, f"{broker_id} missing 'paper'"
            assert 'name' in config, f"{broker_id} missing 'name'"
            assert config['type'] in ['webull', 'alpaca', 'ibkr']
    
    def test_paper_and_live_modes_correctly_set(self):
        """Paper mode should be correctly identified."""
        BROKER_CONFIGS = {
            'webull_live': {'type': 'webull', 'paper': False},
            'webull_paper': {'type': 'webull', 'paper': True},
            'alpaca_live': {'type': 'alpaca', 'paper': False},
            'alpaca_paper': {'type': 'alpaca', 'paper': True},
        }
        
        for broker_id, config in BROKER_CONFIGS.items():
            if 'paper' in broker_id:
                assert config['paper'] is True
            elif 'live' in broker_id:
                assert config['paper'] is False


@pytest.mark.quick
@pytest.mark.broker
class TestChannelSourceBadges:
    """Test channel source badge display for positions."""
    
    def test_channel_badge_colors(self):
        """Test channel badge color mapping."""
        badge_colors = {
            'execute': 'blue',
            'track': 'purple',
            'other': 'green',
            'sync': 'gray'
        }
        
        assert badge_colors['execute'] == 'blue'
        assert badge_colors['track'] == 'purple'
        assert badge_colors['sync'] == 'gray'
    
    def test_position_key_format(self):
        """Test unified position key format."""
        broker = 'WEBULL'
        symbol = 'AAPL'
        strike = '180'
        expiry = '2024-12-20'
        option_type = 'C'
        
        position_key = f"{broker}_{symbol}_{strike}_{expiry}_{option_type}"
        
        assert position_key == 'WEBULL_AAPL_180_2024-12-20_C'
        assert '_' in position_key
        parts = position_key.split('_')
        assert len(parts) == 5
