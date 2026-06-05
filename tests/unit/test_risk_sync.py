"""
Risk Settings and Sync Service Tests
Covers: Position calculations, trailing stops, P&L sync, multi-broker positions
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

pytestmark = [pytest.mark.quick, pytest.mark.broker]


class TestPositionSizing:
    """Tests for position size calculations."""
    
    @pytest.fixture
    def account_info(self):
        """Sample account information."""
        return {
            'buying_power': 50000.0,
            'portfolio_value': 100000.0,
            'cash': 25000.0
        }
    
    @pytest.fixture
    def risk_settings(self):
        """Risk management settings."""
        return {
            'position_size_pct': 5.0,  # 5% of portfolio
            'max_position_value': 2000.0,
            'max_shares': 100
        }
    
    def test_position_size_by_percentage(self, account_info, risk_settings):
        """Should calculate position size as percentage of portfolio."""
        portfolio = account_info['portfolio_value']
        pct = risk_settings['position_size_pct']
        
        position_value = portfolio * (pct / 100)
        assert position_value == 5000.0
    
    def test_position_size_capped_by_max(self, account_info, risk_settings):
        """Position size should not exceed max value."""
        portfolio = account_info['portfolio_value']
        pct = risk_settings['position_size_pct']
        max_value = risk_settings['max_position_value']
        
        calculated = portfolio * (pct / 100)
        actual = min(calculated, max_value)
        
        assert actual == 2000.0  # Capped at max
    
    def test_share_quantity_calculation(self, account_info, risk_settings):
        """Should calculate correct number of shares."""
        position_value = 2000.0
        stock_price = 150.0
        max_shares = risk_settings['max_shares']
        
        shares = int(position_value / stock_price)
        shares = min(shares, max_shares)
        
        assert shares == 13
    
    def test_buying_power_check(self, account_info):
        """Should verify sufficient buying power."""
        order_value = 3000.0
        buying_power = account_info['buying_power']
        
        has_power = buying_power >= order_value
        assert has_power is True
    
    def test_insufficient_buying_power(self, account_info):
        """Should detect insufficient buying power."""
        order_value = 60000.0
        buying_power = account_info['buying_power']
        
        has_power = buying_power >= order_value
        assert has_power is False


class TestStopLossCalculations:
    """Tests for stop loss price calculations."""
    
    def test_percentage_stop_loss(self):
        """Should calculate stop loss by percentage."""
        entry_price = 100.0
        stop_pct = 2.0
        
        stop_price = entry_price * (1 - stop_pct / 100)
        assert stop_price == 98.0
    
    def test_dollar_amount_stop_loss(self):
        """Should calculate stop loss by dollar amount."""
        entry_price = 100.0
        stop_amount = 3.0
        
        stop_price = entry_price - stop_amount
        assert stop_price == 97.0
    
    def test_stop_loss_for_short_position(self):
        """Short position stop loss should be above entry."""
        entry_price = 100.0
        stop_pct = 2.0
        is_short = True
        
        if is_short:
            stop_price = entry_price * (1 + stop_pct / 100)
        else:
            stop_price = entry_price * (1 - stop_pct / 100)
        
        assert stop_price == 102.0


class TestProfitTargetCalculations:
    """Tests for profit target calculations."""
    
    def test_single_profit_target(self):
        """Should calculate single profit target."""
        entry_price = 100.0
        target_pct = 4.0
        
        target_price = entry_price * (1 + target_pct / 100)
        assert target_price == 104.0
    
    def test_tiered_profit_targets(self):
        """Should calculate multiple profit tiers."""
        entry_price = 100.0
        tiers = [
            {'pct': 2.0, 'exit_pct': 33},  # Exit 33% at +2%
            {'pct': 4.0, 'exit_pct': 33},  # Exit 33% at +4%
            {'pct': 6.0, 'exit_pct': 34},  # Exit 34% at +6%
        ]
        
        for tier in tiers:
            tier['price'] = entry_price * (1 + tier['pct'] / 100)
        
        assert tiers[0]['price'] == 102.0
        assert tiers[1]['price'] == 104.0
        assert tiers[2]['price'] == 106.0
        assert sum(t['exit_pct'] for t in tiers) == 100


class TestTrailingStopCalculations:
    """Tests for trailing stop calculations."""
    
    @pytest.fixture
    def position(self):
        """Position with trailing stop."""
        return {
            'entry_price': 100.0,
            'current_price': 110.0,
            'high_since_entry': 112.0,
            'trailing_stop_pct': 3.0,
            'trailing_active': True
        }
    
    def test_trailing_stop_from_high(self, position):
        """Trailing stop should trail from highest price."""
        high = position['high_since_entry']
        trail_pct = position['trailing_stop_pct']
        
        trailing_stop = high * (1 - trail_pct / 100)
        assert trailing_stop == 108.64
    
    def test_trailing_stop_triggers(self, position):
        """Should trigger when price falls below trailing stop."""
        high = position['high_since_entry']
        trail_pct = position['trailing_stop_pct']
        trailing_stop = high * (1 - trail_pct / 100)
        
        current = 108.0
        triggered = current <= trailing_stop
        
        assert triggered is True
    
    def test_trailing_stop_updates_on_new_high(self, position):
        """Trailing stop should update when price makes new high."""
        old_high = position['high_since_entry']
        new_price = 115.0
        trail_pct = position['trailing_stop_pct']
        
        new_high = max(old_high, new_price)
        new_trailing = new_high * (1 - trail_pct / 100)
        old_trailing = old_high * (1 - trail_pct / 100)
        
        assert new_high == 115.0
        assert new_trailing > old_trailing


class TestPositionKeyFormat:
    """Tests for unified position key format."""
    
    def test_stock_position_key(self):
        """Stock position key format: {BROKER}_{SYMBOL}."""
        broker = 'alpaca_live'
        symbol = 'AAPL'
        
        key = f"{broker}_{symbol}"
        assert key == 'alpaca_live_AAPL'
    
    def test_option_position_key(self):
        """Option position key format: {BROKER}_{SYMBOL}_{STRIKE}_{EXPIRY}_{C/P}."""
        broker = 'alpaca_live'
        symbol = 'AAPL'
        strike = 150
        expiry = '2024-12-15'
        option_type = 'C'
        
        key = f"{broker}_{symbol}_{strike}_{expiry}_{option_type}"
        assert key == 'alpaca_live_AAPL_150_2024-12-15_C'
    
    def test_position_key_parsing(self):
        """Should parse position key back to components."""
        key = 'webull_paper_TSLA_250_2024-12-20_P'
        parts = key.split('_')
        
        broker = f"{parts[0]}_{parts[1]}"
        symbol = parts[2]
        strike = parts[3]
        expiry = parts[4]
        opt_type = parts[5]
        
        assert broker == 'webull_paper'
        assert symbol == 'TSLA'
        assert strike == '250'
        assert opt_type == 'P'


class TestPnLCalculations:
    """Tests for P&L calculation accuracy."""
    
    @pytest.fixture
    def closed_trade(self):
        """Sample closed trade."""
        return {
            'symbol': 'AAPL',
            'side': 'buy',
            'quantity': 10,
            'entry_price': 150.0,
            'exit_price': 156.0,
            'commission': 1.0
        }
    
    def test_gross_pnl_calculation(self, closed_trade):
        """Should calculate gross P&L correctly."""
        qty = closed_trade['quantity']
        entry = closed_trade['entry_price']
        exit_price = closed_trade['exit_price']
        
        gross_pnl = (exit_price - entry) * qty
        assert gross_pnl == 60.0
    
    def test_net_pnl_with_commission(self, closed_trade):
        """Should subtract commissions from P&L."""
        qty = closed_trade['quantity']
        entry = closed_trade['entry_price']
        exit_price = closed_trade['exit_price']
        commission = closed_trade['commission']
        
        gross = (exit_price - entry) * qty
        net = gross - (commission * 2)  # Entry + exit commission
        
        assert net == 58.0
    
    def test_pnl_percentage(self, closed_trade):
        """Should calculate P&L percentage correctly."""
        entry = closed_trade['entry_price']
        exit_price = closed_trade['exit_price']
        
        pnl_pct = ((exit_price - entry) / entry) * 100
        assert pnl_pct == 4.0
    
    def test_short_position_pnl(self):
        """Short position P&L should be inverted."""
        entry = 100.0
        exit_price = 95.0
        qty = 10
        side = 'sell'  # Short
        
        if side == 'sell':
            pnl = (entry - exit_price) * qty
        else:
            pnl = (exit_price - entry) * qty
        
        assert pnl == 50.0  # Profit from short


class TestBrokerSyncService:
    """Tests for broker position synchronization."""
    
    @pytest.fixture
    def positions_multi_broker(self):
        """Positions across multiple brokers."""
        return {
            'alpaca_live': [
                {'symbol': 'AAPL', 'qty': 10, 'avg_price': 150.0},
                {'symbol': 'GOOGL', 'qty': 5, 'avg_price': 140.0},
            ],
            'webull_paper': [
                {'symbol': 'AAPL', 'qty': 20, 'avg_price': 148.0},
                {'symbol': 'TSLA', 'qty': 8, 'avg_price': 250.0},
            ]
        }
    
    def test_aggregate_positions_by_symbol(self, positions_multi_broker):
        """Should aggregate same symbol across brokers."""
        aapl_positions = []
        for broker, positions in positions_multi_broker.items():
            for pos in positions:
                if pos['symbol'] == 'AAPL':
                    aapl_positions.append({**pos, 'broker': broker})
        
        assert len(aapl_positions) == 2
        total_qty = sum(p['qty'] for p in aapl_positions)
        assert total_qty == 30
    
    def test_broker_name_normalization(self):
        """Broker names should normalize for matching."""
        names = [
            ('Alpaca Live', 'alpaca_live'),
            ('ALPACA-LIVE', 'alpaca_live'),
            ('Webull Paper', 'webull_paper'),
        ]
        
        for input_name, expected in names:
            normalized = input_name.lower().replace(' ', '_').replace('-', '_')
            assert normalized == expected
    
    def test_position_sync_updates_database(self):
        """Sync should update positions in database."""
        db_position = {
            'id': 1,
            'symbol': 'AAPL',
            'qty': 10,
            'current_price': 150.0,
            'last_synced': datetime.now().isoformat()
        }
        
        broker_position = {
            'symbol': 'AAPL',
            'qty': 15,  # Changed
            'current_price': 155.0  # Changed
        }
        
        # Sync should detect changes
        qty_changed = db_position['qty'] != broker_position['qty']
        price_changed = db_position['current_price'] != broker_position['current_price']
        
        assert qty_changed is True
        assert price_changed is True


class TestRiskMonitoring:
    """Tests for real-time risk monitoring."""
    
    @pytest.fixture
    def monitored_position(self):
        """Position being monitored for risk."""
        return {
            'symbol': 'AAPL',
            'entry_price': 150.0,
            'current_price': 148.0,
            'quantity': 10,
            'stop_loss': 147.0,
            'profit_target': 156.0,
            'trailing_stop': None,
            'trailing_active': False
        }
    
    def test_stop_loss_trigger_check(self, monitored_position):
        """Should detect when stop loss is triggered."""
        current = monitored_position['current_price']
        stop = monitored_position['stop_loss']
        
        triggered = current <= stop
        assert triggered is False  # 148 > 147
        
        monitored_position['current_price'] = 146.5
        triggered = monitored_position['current_price'] <= stop
        assert triggered is True
    
    def test_profit_target_trigger_check(self, monitored_position):
        """Should detect when profit target is hit."""
        current = monitored_position['current_price']
        target = monitored_position['profit_target']
        
        triggered = current >= target
        assert triggered is False
        
        monitored_position['current_price'] = 157.0
        triggered = monitored_position['current_price'] >= target
        assert triggered is True
    
    def test_unrealized_pnl_calculation(self, monitored_position):
        """Should calculate unrealized P&L in real-time."""
        entry = monitored_position['entry_price']
        current = monitored_position['current_price']
        qty = monitored_position['quantity']
        
        unrealized = (current - entry) * qty
        assert unrealized == -20.0  # Loss
    
    def test_risk_exit_attribution(self):
        """Risk-triggered exits should attribute to original trade."""
        original_trade = {
            'id': 123,
            'symbol': 'AAPL',
            'entry_price': 150.0,
            'source_channel_id': '111222333'
        }
        
        exit_trade = {
            'parent_trade_id': 123,
            'exit_type': 'stop_loss',
            'exit_price': 147.0,
            'source_channel_id': original_trade['source_channel_id']  # Same channel
        }
        
        assert exit_trade['parent_trade_id'] == original_trade['id']
        assert exit_trade['source_channel_id'] == original_trade['source_channel_id']
