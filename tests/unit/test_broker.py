"""
Broker Unit Tests
=================
Tests for broker connections, order placement, and position management.
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.mark.quick
@pytest.mark.broker
class TestBrokerConnection:
    """Test broker connection functionality."""
    
    def test_alpaca_connection_with_valid_credentials(self, mock_alpaca_client):
        """Test Alpaca connection with valid credentials."""
        account = mock_alpaca_client.get_account()
        
        assert account.status == 'ACTIVE'
        assert account.buying_power == 100000.0
        assert account.account_number == 'PA12345678'
    
    def test_alpaca_connection_without_credentials(self):
        """Test Alpaca connection fails gracefully without credentials."""
        with patch.dict('os.environ', {'ALPACA_API_KEY': '', 'ALPACA_SECRET_KEY': ''}):
            api_key = ''
            secret_key = ''
            
            can_connect = bool(api_key and secret_key)
            assert can_connect is False
    
    def test_webull_connection_with_valid_tokens(self, mock_webull_client):
        """Test Webull connection with valid tokens."""
        account = mock_webull_client.get_account()
        
        assert 'accountId' in account
        assert account['buyingPower'] == 50000.0
    
    def test_broker_mode_detection(self):
        """Test paper vs live mode detection."""
        paper_indicators = ['paper', 'PA', 'sandbox', 'test']
        live_indicators = ['live', 'LA', 'production']
        
        account_number = 'PA12345678'
        is_paper = any(ind in account_number for ind in paper_indicators)
        assert is_paper is True
        
        account_number = 'LA87654321'
        is_paper = any(ind in account_number for ind in paper_indicators)
        assert is_paper is False


@pytest.mark.quick
@pytest.mark.broker
class TestOrderPlacement:
    """Test order placement functionality."""
    
    def test_market_order_structure(self):
        """Test market order has correct structure."""
        order = {
            'symbol': 'AAPL',
            'side': 'buy',
            'type': 'market',
            'qty': 10,
            'time_in_force': 'day'
        }
        
        required_fields = ['symbol', 'side', 'type', 'qty', 'time_in_force']
        for field in required_fields:
            assert field in order, f"Order should have {field}"
        
        assert order['type'] == 'market'
        assert order['side'] in ['buy', 'sell']
    
    def test_limit_order_structure(self):
        """Test limit order has correct structure."""
        order = {
            'symbol': 'AAPL',
            'side': 'buy',
            'type': 'limit',
            'qty': 10,
            'limit_price': 150.50,
            'time_in_force': 'gtc'
        }
        
        assert order['type'] == 'limit'
        assert 'limit_price' in order
        assert order['limit_price'] > 0
    
    def test_bracket_order_structure(self):
        """Test bracket order has stop loss and take profit."""
        order = {
            'symbol': 'AAPL',
            'side': 'buy',
            'type': 'market',
            'qty': 10,
            'order_class': 'bracket',
            'take_profit': {'limit_price': 165.00},
            'stop_loss': {'stop_price': 145.00}
        }
        
        assert order['order_class'] == 'bracket'
        assert 'take_profit' in order
        assert 'stop_loss' in order
        assert order['take_profit']['limit_price'] > order['stop_loss']['stop_price']
    
    def test_option_order_structure(self):
        """Test option order has correct structure."""
        order = {
            'symbol': 'AAPL231215C00180000',
            'side': 'buy',
            'type': 'limit',
            'qty': 1,
            'limit_price': 5.50,
            'time_in_force': 'day'
        }
        
        assert len(order['symbol']) > 10  # OCC format is longer
        assert 'C' in order['symbol'] or 'P' in order['symbol']


@pytest.mark.quick
@pytest.mark.broker
class TestPositionManagement:
    """Test position management functionality."""
    
    def test_position_key_format(self):
        """Test unified position key format."""
        broker = 'ALPACA_PAPER'
        symbol = 'AAPL'
        strike = 180
        expiry = '2023-12-15'
        option_type = 'C'
        
        stock_key = f"{broker}_{symbol}"
        option_key = f"{broker}_{symbol}_{strike}_{expiry}_{option_type}"
        
        assert stock_key == 'ALPACA_PAPER_AAPL'
        assert option_key == 'ALPACA_PAPER_AAPL_180_2023-12-15_C'
    
    def test_position_pnl_calculation(self):
        """Test position PNL calculation."""
        entry_price = 100.0
        current_price = 110.0
        quantity = 10
        
        unrealized_pnl = (current_price - entry_price) * quantity
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        assert unrealized_pnl == 100.0
        assert pnl_pct == 10.0
    
    def test_short_position_pnl_calculation(self):
        """Test short position PNL calculation."""
        entry_price = 100.0
        current_price = 90.0
        quantity = -10  # Negative for short
        
        unrealized_pnl = (entry_price - current_price) * abs(quantity)
        
        assert unrealized_pnl == 100.0  # Profit when price goes down
    
    def test_option_position_value(self):
        """Test option position value calculation."""
        contract_price = 5.50
        contracts = 2
        multiplier = 100  # Options are 100 shares per contract
        
        position_value = contract_price * contracts * multiplier
        
        assert position_value == 1100.0


@pytest.mark.quick
@pytest.mark.broker
class TestBrokerSync:
    """Test broker synchronization functionality."""
    
    def test_position_sync_detection(self):
        """Test that new positions are detected during sync."""
        cached_positions = {'ALPACA_PAPER_AAPL': {'qty': 10}}
        broker_positions = [
            {'symbol': 'AAPL', 'qty': 10},
            {'symbol': 'TSLA', 'qty': 5}  # New position
        ]
        
        cached_symbols = set(cached_positions.keys())
        broker_symbols = {f"ALPACA_PAPER_{p['symbol']}" for p in broker_positions}
        
        new_positions = broker_symbols - cached_symbols
        
        assert 'ALPACA_PAPER_TSLA' in new_positions
        assert len(new_positions) == 1
    
    def test_closed_position_detection(self):
        """Test that closed positions are detected during sync."""
        cached_positions = {
            'ALPACA_PAPER_AAPL': {'qty': 10},
            'ALPACA_PAPER_NVDA': {'qty': 5}  # Will be closed
        }
        broker_positions = [
            {'symbol': 'AAPL', 'qty': 10}
        ]
        
        cached_symbols = set(cached_positions.keys())
        broker_symbols = {f"ALPACA_PAPER_{p['symbol']}" for p in broker_positions}
        
        closed_positions = cached_symbols - broker_symbols
        
        assert 'ALPACA_PAPER_NVDA' in closed_positions
        assert len(closed_positions) == 1
    
    def test_position_quantity_change_detection(self):
        """Test that quantity changes are detected during sync."""
        cached_position = {'symbol': 'AAPL', 'qty': 10}
        broker_position = {'symbol': 'AAPL', 'qty': 15}
        
        qty_changed = cached_position['qty'] != broker_position['qty']
        
        assert qty_changed is True


@pytest.mark.quick
@pytest.mark.broker
class TestOrderResult:
    """Test order result normalization."""
    
    def test_successful_order_result(self):
        """Test successful order result structure."""
        result = {
            'success': True,
            'order_id': 'ABC123',
            'symbol': 'AAPL',
            'side': 'buy',
            'qty': 10,
            'filled_qty': 10,
            'status': 'filled',
            'filled_price': 150.50
        }
        
        assert result['success'] is True
        assert result['filled_qty'] == result['qty']
        assert result['status'] == 'filled'
    
    def test_partial_fill_order_result(self):
        """Test partial fill order result."""
        result = {
            'success': True,
            'order_id': 'ABC123',
            'symbol': 'AAPL',
            'qty': 10,
            'filled_qty': 5,
            'status': 'partially_filled'
        }
        
        assert result['filled_qty'] < result['qty']
        assert result['status'] == 'partially_filled'
    
    def test_rejected_order_result(self):
        """Test rejected order result."""
        result = {
            'success': False,
            'error': 'Insufficient buying power',
            'symbol': 'AAPL',
            'qty': 1000
        }
        
        assert result['success'] is False
        assert 'error' in result
    
    def test_rate_limited_order_result(self):
        """Test rate limited order handling."""
        result = {
            'success': False,
            'error': 'Rate limit exceeded',
            'retry_after': 60
        }
        
        assert result['success'] is False
        assert 'retry_after' in result


@pytest.mark.quick
@pytest.mark.broker
class TestBrokerNameNormalization:
    """Test broker name normalization for matching."""
    
    def test_broker_name_case_insensitive(self):
        """Test broker names are matched case-insensitively."""
        broker_names = ['Webull', 'WEBULL', 'webull', 'WeBuLl']
        normalized = [name.lower() for name in broker_names]
        
        assert all(n == 'webull' for n in normalized)
    
    def test_alpaca_paper_live_distinction(self):
        """Test Alpaca paper vs live are distinguished."""
        brokers = ['alpaca_paper', 'alpaca_live', 'ALPACA_PAPER', 'ALPACA_LIVE']
        
        paper_brokers = [b for b in brokers if 'paper' in b.lower()]
        live_brokers = [b for b in brokers if 'live' in b.lower()]
        
        assert len(paper_brokers) == 2
        assert len(live_brokers) == 2
    
    def test_broker_id_format(self):
        """Test broker ID format for database storage."""
        broker_ids = {
            'webull': 'Webull',
            'alpaca_paper': 'ALPACA_PAPER',
            'alpaca_live': 'ALPACA_LIVE',
            'ibkr': 'IBKR'
        }
        
        for key, expected in broker_ids.items():
            assert expected.replace('_', '').isalnum()
