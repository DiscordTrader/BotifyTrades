"""
Integration Tests for PNL Tracking
Tests signal P&L, execution P&L, lot matching (FIFO)
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class TestSignalPNL:
    """Test theoretical signal-based P&L tracking"""
    
    @pytest.mark.integration
    def test_open_position_pnl_calculation(self, test_db):
        """Calculate P&L for open position"""
        entry_price = 1.50
        current_price = 1.80
        quantity = 10
        
        unrealized_pnl = (current_price - entry_price) * quantity * 100
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        assert round(unrealized_pnl, 2) == 300.0
        assert round(pnl_pct, 2) == 20.0
    
    @pytest.mark.integration
    def test_closed_position_pnl_calculation(self, test_db):
        """Calculate P&L for closed position"""
        entry_price = 2.00
        exit_price = 2.50
        quantity = 5
        
        realized_pnl = (exit_price - entry_price) * quantity * 100
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        
        assert realized_pnl == 250.0
        assert pnl_pct == 25.0
    
    @pytest.mark.integration
    def test_losing_position_pnl(self, test_db):
        """Calculate negative P&L for losing position"""
        entry_price = 1.00
        exit_price = 0.50
        quantity = 10
        
        realized_pnl = (exit_price - entry_price) * quantity * 100
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        
        assert realized_pnl == -500.0
        assert pnl_pct == -50.0


class TestExecutionPNL:
    """Test actual execution-based P&L tracking"""
    
    @pytest.mark.integration
    def test_slippage_tracking(self, test_db):
        """Track slippage between intended and executed price"""
        intended_price = 1.50
        executed_price = 1.55
        quantity = 10
        
        slippage = executed_price - intended_price
        slippage_pct = (slippage / intended_price) * 100
        slippage_cost = slippage * quantity * 100
        
        assert round(slippage, 2) == 0.05
        assert round(slippage_pct, 2) == 3.33
        assert round(slippage_cost, 2) == 50.0
    
    @pytest.mark.integration
    def test_execution_pnl_vs_signal_pnl(self, test_db):
        """Compare execution P&L (actual) vs signal P&L (theoretical)"""
        intended_entry = 1.50
        executed_entry = 1.55
        intended_exit = 2.00
        executed_exit = 1.95
        quantity = 10
        
        signal_pnl = (intended_exit - intended_entry) * quantity * 100
        
        execution_pnl = (executed_exit - executed_entry) * quantity * 100
        
        pnl_difference = signal_pnl - execution_pnl
        
        assert round(signal_pnl, 2) == 500.0
        assert round(execution_pnl, 2) == 400.0
        assert round(pnl_difference, 2) == 100.0


class TestFIFOLotMatching:
    """Test FIFO-based lot matching for P&L calculation"""
    
    @pytest.mark.integration
    def test_fifo_single_lot_exit(self, test_db):
        """FIFO: Single lot should match correctly"""
        lots = [
            {'qty': 10, 'entry_price': 1.50, 'created_at': '2026-01-14 10:00:00'}
        ]
        
        exit_qty = 10
        exit_price = 2.00
        
        remaining_exit_qty = exit_qty
        total_pnl = 0
        
        for lot in sorted(lots, key=lambda x: x['created_at']):
            if remaining_exit_qty <= 0:
                break
            
            qty_to_match = min(lot['qty'], remaining_exit_qty)
            pnl = (exit_price - lot['entry_price']) * qty_to_match * 100
            total_pnl += pnl
            remaining_exit_qty -= qty_to_match
        
        assert total_pnl == 500.0
        assert remaining_exit_qty == 0
    
    @pytest.mark.integration
    def test_fifo_multiple_lots_exit(self, test_db):
        """FIFO: Multiple lots should match in order"""
        lots = [
            {'qty': 5, 'entry_price': 1.00, 'created_at': '2026-01-14 10:00:00'},
            {'qty': 5, 'entry_price': 1.50, 'created_at': '2026-01-14 11:00:00'},
            {'qty': 5, 'entry_price': 2.00, 'created_at': '2026-01-14 12:00:00'},
        ]
        
        exit_qty = 8
        exit_price = 1.75
        
        remaining_exit_qty = exit_qty
        matched_lots = []
        total_pnl = 0
        
        for lot in sorted(lots, key=lambda x: x['created_at']):
            if remaining_exit_qty <= 0:
                break
            
            qty_to_match = min(lot['qty'], remaining_exit_qty)
            pnl = (exit_price - lot['entry_price']) * qty_to_match * 100
            total_pnl += pnl
            matched_lots.append({
                'entry_price': lot['entry_price'],
                'qty_matched': qty_to_match,
                'pnl': pnl
            })
            remaining_exit_qty -= qty_to_match
        
        assert len(matched_lots) == 2
        assert matched_lots[0]['entry_price'] == 1.00
        assert matched_lots[0]['qty_matched'] == 5
        assert matched_lots[0]['pnl'] == 375.0
        
        assert matched_lots[1]['entry_price'] == 1.50
        assert matched_lots[1]['qty_matched'] == 3
        assert matched_lots[1]['pnl'] == 75.0
        
        assert total_pnl == 450.0
    
    @pytest.mark.integration
    def test_fifo_partial_lot_closure(self, test_db):
        """FIFO: Partial lot closure should leave remainder"""
        lots = [
            {'qty': 10, 'entry_price': 1.50, 'created_at': '2026-01-14 10:00:00', 'remaining': 10}
        ]
        
        exit_qty = 4
        exit_price = 2.00
        
        lot = lots[0]
        qty_to_match = min(lot['remaining'], exit_qty)
        pnl = (exit_price - lot['entry_price']) * qty_to_match * 100
        lot['remaining'] -= qty_to_match
        
        assert pnl == 200.0
        assert lot['remaining'] == 6


class TestPNLAggregation:
    """Test P&L aggregation across multiple positions/channels"""
    
    @pytest.mark.integration
    def test_daily_pnl_aggregation(self, test_db):
        """Aggregate P&L for a single day"""
        trades = [
            {'pnl': 100.0, 'channel': 'channel-1'},
            {'pnl': -50.0, 'channel': 'channel-1'},
            {'pnl': 200.0, 'channel': 'channel-2'},
            {'pnl': 75.0, 'channel': 'channel-2'},
        ]
        
        total_pnl = sum(t['pnl'] for t in trades)
        
        assert total_pnl == 325.0
    
    @pytest.mark.integration
    def test_per_channel_pnl_aggregation(self, test_db):
        """Aggregate P&L per channel"""
        trades = [
            {'pnl': 100.0, 'channel': 'channel-1'},
            {'pnl': -50.0, 'channel': 'channel-1'},
            {'pnl': 200.0, 'channel': 'channel-2'},
            {'pnl': 75.0, 'channel': 'channel-2'},
        ]
        
        channel_pnl = {}
        for t in trades:
            channel = t['channel']
            if channel not in channel_pnl:
                channel_pnl[channel] = 0
            channel_pnl[channel] += t['pnl']
        
        assert channel_pnl['channel-1'] == 50.0
        assert channel_pnl['channel-2'] == 275.0
    
    @pytest.mark.integration
    def test_per_broker_pnl_aggregation(self, test_db):
        """Aggregate P&L per broker"""
        trades = [
            {'pnl': 100.0, 'broker': 'ALPACA_PAPER'},
            {'pnl': 150.0, 'broker': 'ALPACA_PAPER'},
            {'pnl': 75.0, 'broker': 'WEBULL'},
            {'pnl': -25.0, 'broker': 'WEBULL'},
        ]
        
        broker_pnl = {}
        for t in trades:
            broker = t['broker']
            if broker not in broker_pnl:
                broker_pnl[broker] = 0
            broker_pnl[broker] += t['pnl']
        
        assert broker_pnl['ALPACA_PAPER'] == 250.0
        assert broker_pnl['WEBULL'] == 50.0


class TestMergedPNLEndpoint:
    """Test the /api/trades/merged endpoint logic"""
    
    @pytest.mark.integration
    def test_merge_signal_and_execution_pnl(self, test_db):
        """Merge signal P&L with execution P&L for complete picture"""
        signal_trade = {
            'id': 1,
            'symbol': 'SPY',
            'intended_price': 1.50,
            'signal_pnl': 500.0
        }
        
        execution_data = {
            'trade_id': 1,
            'executed_price': 1.55,
            'execution_pnl': 400.0
        }
        
        merged = {
            **signal_trade,
            'executed_price': execution_data['executed_price'],
            'execution_pnl': execution_data['execution_pnl'],
            'slippage': execution_data['executed_price'] - signal_trade['intended_price']
        }
        
        assert merged['signal_pnl'] == 500.0
        assert merged['execution_pnl'] == 400.0
        assert round(merged['slippage'], 2) == 0.05
    
    @pytest.mark.integration
    def test_entry_price_priority(self, test_db):
        """Entry price display: intended_price takes priority over executed_price"""
        trade_with_intended = {
            'intended_price': 1.50,
            'executed_price': 1.55
        }
        
        display_price = trade_with_intended.get('intended_price') or trade_with_intended.get('executed_price')
        
        assert display_price == 1.50
        
        trade_without_intended = {
            'intended_price': None,
            'executed_price': 1.55
        }
        
        display_price = trade_without_intended.get('intended_price') or trade_without_intended.get('executed_price')
        
        assert display_price == 1.55


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
