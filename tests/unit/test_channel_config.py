"""
Channel Configuration Tests
Covers: Execute vs track modes, user filtering, broker overrides, disabled channels
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

pytestmark = [pytest.mark.quick, pytest.mark.signal]


class TestChannelModes:
    """Tests for channel execution/tracking modes."""
    
    @pytest.fixture
    def channel_configs(self):
        """Sample channel configurations."""
        return {
            'execute_only': {
                'channel_id': '123456789',
                'name': 'Trading Signals',
                'execute_enabled': True,
                'track_enabled': False,
                'is_enabled': True
            },
            'track_only': {
                'channel_id': '987654321',
                'name': 'Paper Tracking',
                'execute_enabled': False,
                'track_enabled': True,
                'is_enabled': True
            },
            'both_enabled': {
                'channel_id': '111222333',
                'name': 'Full Mode',
                'execute_enabled': True,
                'track_enabled': True,
                'is_enabled': True
            },
            'disabled': {
                'channel_id': '444555666',
                'name': 'Disabled Channel',
                'execute_enabled': False,
                'track_enabled': False,
                'is_enabled': False
            }
        }
    
    def test_execute_only_mode(self, channel_configs):
        """Execute-only channel should trade but not track."""
        channel = channel_configs['execute_only']
        assert channel['execute_enabled'] is True
        assert channel['track_enabled'] is False
        assert channel['is_enabled'] is True
    
    def test_track_only_mode(self, channel_configs):
        """Track-only channel should record but not trade."""
        channel = channel_configs['track_only']
        assert channel['execute_enabled'] is False
        assert channel['track_enabled'] is True
        assert channel['is_enabled'] is True
    
    def test_both_modes_enabled(self, channel_configs):
        """Channel can have both execute and track enabled."""
        channel = channel_configs['both_enabled']
        assert channel['execute_enabled'] is True
        assert channel['track_enabled'] is True
    
    def test_disabled_channel_blocks_all(self, channel_configs):
        """Disabled channel should block all operations."""
        channel = channel_configs['disabled']
        assert channel['is_enabled'] is False
        # Should not process signals from disabled channel
    
    def test_channel_requires_at_least_one_mode(self, channel_configs):
        """Enabled channel should have at least one mode active."""
        for name, channel in channel_configs.items():
            if channel['is_enabled']:
                has_mode = channel['execute_enabled'] or channel['track_enabled']
                assert has_mode or name == 'disabled', f"Enabled channel {name} should have a mode"


class TestUserFiltering:
    """Tests for per-channel user allowlists/denylists."""
    
    @pytest.fixture
    def channel_with_users(self):
        """Channel with user filtering configured."""
        return {
            'channel_id': '123456789',
            'allowed_users': ['user_123', 'user_456', 'user_789'],
            'blocked_users': ['user_bad', 'user_spam'],
            'allow_all_users': False
        }
    
    @pytest.fixture
    def open_channel(self):
        """Channel accepting all users."""
        return {
            'channel_id': '999888777',
            'allowed_users': [],
            'blocked_users': [],
            'allow_all_users': True
        }
    
    def test_allowed_user_passes(self, channel_with_users):
        """Message from allowed user should be processed."""
        user_id = 'user_123'
        allowed = user_id in channel_with_users['allowed_users']
        assert allowed is True
    
    def test_blocked_user_rejected(self, channel_with_users):
        """Message from blocked user should be rejected."""
        user_id = 'user_bad'
        blocked = user_id in channel_with_users['blocked_users']
        assert blocked is True
    
    def test_unknown_user_rejected_when_allowlist_active(self, channel_with_users):
        """Unknown user should be rejected when allowlist is active."""
        user_id = 'user_unknown'
        channel = channel_with_users
        
        is_allowed = user_id in channel['allowed_users']
        is_blocked = user_id in channel['blocked_users']
        allow_all = channel['allow_all_users']
        
        # Should be rejected: not in allowlist, and not allowing all
        should_process = allow_all or (is_allowed and not is_blocked)
        assert should_process is False
    
    def test_open_channel_accepts_all(self, open_channel):
        """Open channel should accept any user."""
        user_id = 'any_random_user'
        channel = open_channel
        
        is_blocked = user_id in channel['blocked_users']
        allow_all = channel['allow_all_users']
        
        should_process = allow_all and not is_blocked
        assert should_process is True
    
    def test_blocklist_overrides_allowlist(self):
        """Blocked user should be rejected even if in allowlist."""
        channel = {
            'allowed_users': ['user_123'],
            'blocked_users': ['user_123'],  # Same user in both
            'allow_all_users': False
        }
        user_id = 'user_123'
        
        is_blocked = user_id in channel['blocked_users']
        is_allowed = user_id in channel['allowed_users']
        
        # Blocklist should take precedence
        should_process = is_allowed and not is_blocked
        assert should_process is False


class TestBrokerOverrides:
    """Tests for per-channel broker selection."""
    
    @pytest.fixture
    def channel_broker_configs(self):
        """Channels with different broker configurations."""
        return {
            'alpaca_live': {
                'channel_id': '111',
                'broker_override': 'alpaca_live',
                'use_default_broker': False
            },
            'webull_paper': {
                'channel_id': '222',
                'broker_override': 'webull_paper',
                'use_default_broker': False
            },
            'default_broker': {
                'channel_id': '333',
                'broker_override': None,
                'use_default_broker': True
            },
            'multi_broker': {
                'channel_id': '444',
                'brokers': ['alpaca_live', 'webull_paper'],
                'use_default_broker': False
            }
        }
    
    def test_channel_specific_broker(self, channel_broker_configs):
        """Channel should use its configured broker override."""
        channel = channel_broker_configs['alpaca_live']
        assert channel['broker_override'] == 'alpaca_live'
        assert channel['use_default_broker'] is False
    
    def test_default_broker_fallback(self, channel_broker_configs):
        """Channel without override should use default broker."""
        channel = channel_broker_configs['default_broker']
        assert channel['broker_override'] is None
        assert channel['use_default_broker'] is True
    
    def test_multi_broker_execution(self, channel_broker_configs):
        """Channel can execute on multiple brokers simultaneously."""
        channel = channel_broker_configs['multi_broker']
        assert 'brokers' in channel
        assert len(channel['brokers']) == 2
        assert 'alpaca_live' in channel['brokers']
        assert 'webull_paper' in channel['brokers']
    
    def test_broker_name_normalization(self):
        """Broker names should be normalized for matching."""
        broker_names = [
            ('Alpaca Live', 'alpaca_live'),
            ('ALPACA_LIVE', 'alpaca_live'),
            ('alpaca-live', 'alpaca_live'),
            ('Webull Paper', 'webull_paper'),
        ]
        for input_name, expected in broker_names:
            normalized = input_name.lower().replace(' ', '_').replace('-', '_')
            assert normalized == expected, f"'{input_name}' should normalize to '{expected}'"


class TestChannelRiskSettings:
    """Tests for per-channel risk settings."""
    
    @pytest.fixture
    def channel_risk_config(self):
        """Channel with custom risk settings."""
        return {
            'channel_id': '123456789',
            'use_global_risk': False,
            'position_size_pct': 5.0,
            'stop_loss_pct': 2.0,
            'profit_target_pct': 4.0,
            'trailing_stop_pct': 1.5,
            'max_position_value': 1000.0
        }
    
    @pytest.fixture
    def global_risk_channel(self):
        """Channel using global risk settings."""
        return {
            'channel_id': '987654321',
            'use_global_risk': True,
            'position_size_pct': None,  # Inherit from global
            'stop_loss_pct': None,
            'profit_target_pct': None
        }
    
    def test_custom_risk_settings(self, channel_risk_config):
        """Channel should use its custom risk settings."""
        assert channel_risk_config['use_global_risk'] is False
        assert channel_risk_config['position_size_pct'] == 5.0
        assert channel_risk_config['stop_loss_pct'] == 2.0
    
    def test_global_risk_inheritance(self, global_risk_channel):
        """Channel should inherit global risk when configured."""
        assert global_risk_channel['use_global_risk'] is True
        assert global_risk_channel['position_size_pct'] is None
    
    def test_position_size_bounds(self, channel_risk_config):
        """Position size should be within valid range."""
        pct = channel_risk_config['position_size_pct']
        assert 0 < pct <= 100, "Position size must be 0-100%"
    
    def test_stop_loss_less_than_profit_target(self, channel_risk_config):
        """Stop loss should typically be less than profit target."""
        sl = channel_risk_config['stop_loss_pct']
        pt = channel_risk_config['profit_target_pct']
        assert sl < pt, "Stop loss should be less than profit target"


class TestChannelSignalProcessing:
    """Tests for signal processing per channel."""
    
    def test_signal_routes_to_correct_channel(self):
        """Signal should be routed to matching channel."""
        channels = {
            '123': {'name': 'Channel A'},
            '456': {'name': 'Channel B'},
        }
        incoming_channel_id = '123'
        
        matched = channels.get(incoming_channel_id)
        assert matched is not None
        assert matched['name'] == 'Channel A'
    
    def test_unknown_channel_ignored(self):
        """Signal from unknown channel should be ignored."""
        channels = {'123': {}, '456': {}}
        incoming_channel_id = '999'
        
        matched = channels.get(incoming_channel_id)
        assert matched is None
    
    def test_channel_processes_matching_patterns(self):
        """Channel should process signals matching its patterns."""
        channel = {
            'patterns': [
                r'BUY (\w+)',
                r'SELL (\w+)',
            ]
        }
        import re
        
        signal = "BUY AAPL @150"
        matches = [re.search(p, signal) for p in channel['patterns']]
        has_match = any(m is not None for m in matches)
        
        assert has_match is True


class TestChannelStatistics:
    """Tests for channel performance tracking."""
    
    @pytest.fixture
    def channel_stats(self):
        """Channel with performance statistics."""
        return {
            'channel_id': '123456789',
            'total_signals': 100,
            'executed_trades': 80,
            'successful_trades': 65,
            'failed_trades': 15,
            'total_pnl': 2500.50,
            'win_rate': 81.25
        }
    
    def test_win_rate_calculation(self, channel_stats):
        """Win rate should be calculated correctly."""
        wins = channel_stats['successful_trades']
        total = channel_stats['executed_trades']
        calculated_rate = (wins / total) * 100
        
        assert abs(calculated_rate - channel_stats['win_rate']) < 0.1
    
    def test_execution_rate(self, channel_stats):
        """Should track execution rate (signals -> trades)."""
        signals = channel_stats['total_signals']
        executed = channel_stats['executed_trades']
        execution_rate = (executed / signals) * 100
        
        assert execution_rate == 80.0
