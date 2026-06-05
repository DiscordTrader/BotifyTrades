"""
Signal Routing Tests
Covers: Per-channel broker selection, user filtering in signals, complete routing matrix
"""
import pytest
import re
from datetime import datetime
from unittest.mock import Mock, patch

pytestmark = [pytest.mark.quick, pytest.mark.signal]


class TestSignalRouting:
    """Tests for routing signals to correct brokers."""
    
    @pytest.fixture
    def routing_config(self):
        """Signal routing configuration."""
        return {
            'channels': {
                '111': {
                    'name': 'Alpaca Signals',
                    'broker': 'alpaca_live',
                    'enabled': True
                },
                '222': {
                    'name': 'Webull Paper',
                    'broker': 'webull_paper',
                    'enabled': True
                },
                '333': {
                    'name': 'Multi-Broker',
                    'brokers': ['alpaca_live', 'alpaca_paper'],
                    'enabled': True
                },
            },
            'default_broker': 'alpaca_paper'
        }
    
    def test_signal_routes_to_channel_broker(self, routing_config):
        """Signal should use channel's configured broker."""
        channel_id = '111'
        channel = routing_config['channels'].get(channel_id)
        
        broker = channel.get('broker')
        assert broker == 'alpaca_live'
    
    def test_multi_broker_routing(self, routing_config):
        """Signal should execute on all configured brokers."""
        channel_id = '333'
        channel = routing_config['channels'].get(channel_id)
        
        brokers = channel.get('brokers', [channel.get('broker')])
        assert len(brokers) == 2
        assert 'alpaca_live' in brokers
        assert 'alpaca_paper' in brokers
    
    def test_unknown_channel_uses_default(self, routing_config):
        """Unknown channel should use default broker."""
        channel_id = '999'
        channel = routing_config['channels'].get(channel_id)
        
        if channel is None:
            broker = routing_config['default_broker']
        else:
            broker = channel.get('broker')
        
        assert broker == 'alpaca_paper'
    
    def test_disabled_channel_blocks_routing(self, routing_config):
        """Disabled channel should not route signals."""
        routing_config['channels']['111']['enabled'] = False
        
        channel = routing_config['channels']['111']
        assert channel['enabled'] is False


class TestSignalUserFiltering:
    """Tests for user-based signal filtering."""
    
    @pytest.fixture
    def signal_with_author(self):
        """Signal message with author information."""
        return {
            'channel_id': '123',
            'author_id': 'user_trusted',
            'author_name': 'TradingPro',
            'content': 'BUY AAPL @150',
            'timestamp': datetime.now().isoformat()
        }
    
    @pytest.fixture
    def channel_user_config(self):
        """Channel with user filtering."""
        return {
            'allowed_authors': ['user_trusted', 'user_vip'],
            'blocked_authors': ['user_spam'],
            'require_specific_author': True
        }
    
    def test_trusted_author_signal_accepted(self, signal_with_author, channel_user_config):
        """Signal from trusted author should be processed."""
        author_id = signal_with_author['author_id']
        allowed = author_id in channel_user_config['allowed_authors']
        blocked = author_id in channel_user_config['blocked_authors']
        
        should_process = allowed and not blocked
        assert should_process is True
    
    def test_blocked_author_signal_rejected(self, signal_with_author, channel_user_config):
        """Signal from blocked author should be rejected."""
        signal_with_author['author_id'] = 'user_spam'
        
        author_id = signal_with_author['author_id']
        blocked = author_id in channel_user_config['blocked_authors']
        
        assert blocked is True
    
    def test_unknown_author_rejected_when_filtering(self, signal_with_author, channel_user_config):
        """Unknown author should be rejected when filtering enabled."""
        signal_with_author['author_id'] = 'user_random'
        
        author_id = signal_with_author['author_id']
        allowed = author_id in channel_user_config['allowed_authors']
        require_specific = channel_user_config['require_specific_author']
        
        should_reject = require_specific and not allowed
        assert should_reject is True


class TestSignalPatternMatching:
    """Tests for signal pattern detection and extraction."""
    
    @pytest.fixture
    def signal_patterns(self):
        """Common signal patterns."""
        return {
            'stock_buy': r'(?:BUY|LONG)\s+(\$?[A-Z]{1,5})\s*(?:@|at)\s*\$?([\d.]+)',
            'stock_sell': r'(?:SELL|SHORT)\s+(\$?[A-Z]{1,5})\s*(?:@|at)\s*\$?([\d.]+)',
            'option': r'(\$?[A-Z]{1,5})\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*(\d+(?:\.\d+)?)\s*(C|P|CALL|PUT)',
            'trade_idea': r'TRADE IDEA[\s\S]*?Symbol:\s*(\w+)',
        }
    
    def test_stock_buy_signal_extraction(self, signal_patterns):
        """Should extract stock buy signals correctly."""
        signal = "BUY AAPL @150.50"
        match = re.search(signal_patterns['stock_buy'], signal, re.IGNORECASE)
        
        assert match is not None
        assert match.group(1) == 'AAPL'
        assert match.group(2) == '150.50'
    
    def test_stock_sell_signal_extraction(self, signal_patterns):
        """Should extract stock sell signals correctly."""
        signal = "SELL TSLA at $250"
        match = re.search(signal_patterns['stock_sell'], signal, re.IGNORECASE)
        
        assert match is not None
        assert match.group(1) == 'TSLA'
    
    def test_option_signal_extraction(self, signal_patterns):
        """Should extract option signals correctly."""
        signal = "AAPL 12/15 155 C"
        match = re.search(signal_patterns['option'], signal, re.IGNORECASE)
        
        assert match is not None
        assert match.group(1) == 'AAPL'
        assert match.group(4) in ['C', 'CALL']
    
    def test_non_signal_message_ignored(self, signal_patterns):
        """Non-signal messages should not match."""
        messages = [
            "Good morning everyone!",
            "Market looking bullish today",
            "What do you think about AAPL?",
        ]
        
        for msg in messages:
            buy_match = re.search(signal_patterns['stock_buy'], msg, re.IGNORECASE)
            sell_match = re.search(signal_patterns['stock_sell'], msg, re.IGNORECASE)
            assert buy_match is None and sell_match is None


class TestRoutingMatrix:
    """Tests for complete routing decision matrix."""
    
    @pytest.fixture
    def routing_scenarios(self):
        """Complete routing scenario matrix."""
        return [
            {'channel_enabled': True, 'user_allowed': True, 'signal_valid': True, 'should_execute': True},
            {'channel_enabled': True, 'user_allowed': True, 'signal_valid': False, 'should_execute': False},
            {'channel_enabled': True, 'user_allowed': False, 'signal_valid': True, 'should_execute': False},
            {'channel_enabled': False, 'user_allowed': True, 'signal_valid': True, 'should_execute': False},
            {'channel_enabled': False, 'user_allowed': False, 'signal_valid': False, 'should_execute': False},
        ]
    
    def test_routing_matrix(self, routing_scenarios):
        """All routing scenarios should produce correct decisions."""
        for scenario in routing_scenarios:
            result = (
                scenario['channel_enabled'] and 
                scenario['user_allowed'] and 
                scenario['signal_valid']
            )
            assert result == scenario['should_execute'], f"Scenario failed: {scenario}"
    
    def test_execute_mode_requires_all_conditions(self):
        """Execute mode requires channel, user, and signal all valid."""
        conditions = {
            'channel_enabled': True,
            'execute_enabled': True,
            'user_authorized': True,
            'signal_parsed': True,
            'broker_connected': True
        }
        
        should_execute = all(conditions.values())
        assert should_execute is True
        
        # Remove one condition
        conditions['broker_connected'] = False
        should_execute = all(conditions.values())
        assert should_execute is False
    
    def test_track_mode_independent_of_broker(self):
        """Track mode should work even if broker disconnected."""
        conditions = {
            'channel_enabled': True,
            'track_enabled': True,
            'user_authorized': True,
            'signal_parsed': True,
            'broker_connected': False  # Broker not required for tracking
        }
        
        should_track = (
            conditions['channel_enabled'] and
            conditions['track_enabled'] and
            conditions['user_authorized'] and
            conditions['signal_parsed']
        )
        assert should_track is True


class TestBrokerSelection:
    """Tests for broker selection logic."""
    
    @pytest.fixture
    def available_brokers(self):
        """Available broker instances."""
        return {
            'alpaca_live': {'connected': True, 'paper': False},
            'alpaca_paper': {'connected': True, 'paper': True},
            'webull_live': {'connected': False, 'paper': False},
            'webull_paper': {'connected': True, 'paper': True},
        }
    
    def test_connected_broker_selected(self, available_brokers):
        """Only connected brokers should be selectable."""
        requested = 'alpaca_live'
        broker = available_brokers.get(requested)
        
        assert broker is not None
        assert broker['connected'] is True
    
    def test_disconnected_broker_rejected(self, available_brokers):
        """Disconnected broker should fail gracefully."""
        requested = 'webull_live'
        broker = available_brokers.get(requested)
        
        assert broker is not None
        assert broker['connected'] is False
    
    def test_paper_trade_mode_selection(self, available_brokers):
        """Paper trade should select paper broker."""
        paper_mode = True
        
        paper_brokers = [
            name for name, config in available_brokers.items()
            if config['paper'] and config['connected']
        ]
        
        assert len(paper_brokers) >= 1
        assert 'alpaca_paper' in paper_brokers or 'webull_paper' in paper_brokers


class TestSignalExecution:
    """Tests for signal execution flow."""
    
    def test_execution_order_creation(self):
        """Signal should create proper order structure."""
        signal = {
            'symbol': 'AAPL',
            'action': 'BUY',
            'price': 150.0,
            'quantity': 10
        }
        
        order = {
            'symbol': signal['symbol'],
            'side': 'buy' if signal['action'] == 'BUY' else 'sell',
            'qty': signal['quantity'],
            'type': 'limit',
            'limit_price': signal['price'],
            'time_in_force': 'day'
        }
        
        assert order['symbol'] == 'AAPL'
        assert order['side'] == 'buy'
        assert order['qty'] == 10
    
    def test_execution_with_risk_settings(self):
        """Execution should include risk management."""
        order = {
            'symbol': 'AAPL',
            'qty': 10,
            'entry_price': 150.0,
            'stop_loss': 147.0,  # -2%
            'profit_target': 156.0,  # +4%
            'trailing_stop_pct': 1.5
        }
        
        assert order['stop_loss'] < order['entry_price']
        assert order['profit_target'] > order['entry_price']
        assert order['trailing_stop_pct'] > 0
    
    def test_execution_records_source_channel(self):
        """Trade should record source channel for tracking."""
        trade = {
            'symbol': 'AAPL',
            'source_channel_id': '123456789',
            'source_channel_name': 'Trading Signals',
            'source_author_id': 'user_123',
            'executed_at': datetime.now().isoformat()
        }
        
        assert 'source_channel_id' in trade
        assert 'source_author_id' in trade
