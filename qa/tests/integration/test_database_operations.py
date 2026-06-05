"""
Integration Tests for Database Operations
Tests channel CRUD, broker assignment, risk settings persistence
"""
import pytest
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class TestChannelCRUD:
    """Test channel database operations"""
    
    @pytest.mark.integration
    def test_create_channel(self, test_db, channel_factory):
        """Test creating a new channel"""
        channel = channel_factory(
            discord_channel_id="111222333444",
            name="test-trading-signals",
            execute_enabled=1
        )
        
        assert channel['id'] is not None
        assert channel['discord_channel_id'] == "111222333444"
        assert channel['name'] == "test-trading-signals"
    
    @pytest.mark.integration
    def test_read_channel(self, test_db, channel_factory):
        """Test reading a channel from database"""
        channel = channel_factory(
            discord_channel_id="222333444555",
            name="read-test-channel"
        )
        
        cursor = test_db.execute(
            "SELECT * FROM channels WHERE discord_channel_id = ?",
            (channel['discord_channel_id'],)
        )
        row = cursor.fetchone()
        
        assert row is not None
        assert row['name'] == "read-test-channel"
    
    @pytest.mark.integration
    def test_update_channel(self, test_db, channel_factory):
        """Test updating channel settings"""
        channel = channel_factory(
            discord_channel_id="333444555666",
            name="update-test-channel",
            execute_enabled=0
        )
        
        test_db.execute(
            "UPDATE channels SET execute_enabled = 1 WHERE id = ?",
            (channel['id'],)
        )
        test_db.commit()
        
        cursor = test_db.execute(
            "SELECT execute_enabled FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row['execute_enabled'] == 1
    
    @pytest.mark.integration
    def test_delete_channel(self, test_db, channel_factory):
        """Test deleting a channel"""
        channel = channel_factory(
            discord_channel_id="444555666777",
            name="delete-test-channel"
        )
        
        test_db.execute("DELETE FROM channels WHERE id = ?", (channel['id'],))
        test_db.commit()
        
        cursor = test_db.execute(
            "SELECT * FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row is None


class TestBrokerAssignment:
    """Test broker assignment to channels"""
    
    @pytest.mark.integration
    def test_assign_single_broker(self, test_db, channel_factory):
        """Test assigning a single broker to channel"""
        channel = channel_factory(
            discord_channel_id="555666777888",
            name="single-broker-channel",
            enabled_brokers=["ALPACA_PAPER"]
        )
        
        cursor = test_db.execute(
            "SELECT enabled_brokers FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        brokers = json.loads(row['enabled_brokers'])
        
        assert brokers == ["ALPACA_PAPER"]
    
    @pytest.mark.integration
    def test_assign_multiple_brokers(self, test_db, channel_factory):
        """Test assigning multiple brokers to channel"""
        channel = channel_factory(
            discord_channel_id="666777888999",
            name="multi-broker-channel",
            enabled_brokers=["WEBULL", "ALPACA_PAPER", "IBKR"]
        )
        
        cursor = test_db.execute(
            "SELECT enabled_brokers FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        brokers = json.loads(row['enabled_brokers'])
        
        assert len(brokers) == 3
        assert "WEBULL" in brokers
        assert "ALPACA_PAPER" in brokers
        assert "IBKR" in brokers
    
    @pytest.mark.integration
    def test_update_broker_assignment(self, test_db, channel_factory):
        """Test updating broker assignment"""
        channel = channel_factory(
            discord_channel_id="777888999000",
            name="broker-update-channel",
            enabled_brokers=["ALPACA_PAPER"]
        )
        
        new_brokers = json.dumps(["WEBULL", "ROBINHOOD"])
        test_db.execute(
            "UPDATE channels SET enabled_brokers = ? WHERE id = ?",
            (new_brokers, channel['id'])
        )
        test_db.commit()
        
        cursor = test_db.execute(
            "SELECT enabled_brokers FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        brokers = json.loads(row['enabled_brokers'])
        
        assert "WEBULL" in brokers
        assert "ROBINHOOD" in brokers
        assert "ALPACA_PAPER" not in brokers


class TestRiskSettingsPersistence:
    """Test risk management settings persistence"""
    
    @pytest.mark.integration
    def test_stop_loss_setting(self, test_db, channel_factory):
        """Test stop loss percentage persistence"""
        channel = channel_factory(
            discord_channel_id="888999000111",
            name="stoploss-channel",
            risk_management_enabled=1,
            stop_loss_pct=25.0
        )
        
        cursor = test_db.execute(
            "SELECT stop_loss_pct, risk_management_enabled FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row['risk_management_enabled'] == 1
        assert row['stop_loss_pct'] == 25.0
    
    @pytest.mark.integration
    def test_trailing_stop_settings(self, test_db, channel_factory):
        """Test trailing stop and activation percentage persistence"""
        channel = channel_factory(
            discord_channel_id="999000111222",
            name="trailing-channel",
            trailing_stop_pct=15.0,
            trailing_activation_pct=35.0
        )
        
        cursor = test_db.execute(
            "SELECT trailing_stop_pct, trailing_activation_pct FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row['trailing_stop_pct'] == 15.0
        assert row['trailing_activation_pct'] == 35.0
    
    @pytest.mark.integration
    def test_profit_targets(self, test_db, channel_factory):
        """Test 4-tier profit target persistence"""
        channel = channel_factory(
            discord_channel_id="000111222333",
            name="profit-target-channel",
            profit_target_1_pct=15.0
        )
        
        test_db.execute("""
            UPDATE channels SET 
                profit_target_2_pct = 25.0,
                profit_target_3_pct = 35.0,
                profit_target_4_pct = 50.0
            WHERE id = ?
        """, (channel['id'],))
        test_db.commit()
        
        cursor = test_db.execute(
            "SELECT profit_target_1_pct, profit_target_2_pct, profit_target_3_pct, profit_target_4_pct FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row['profit_target_1_pct'] == 15.0
        assert row['profit_target_2_pct'] == 25.0
        assert row['profit_target_3_pct'] == 35.0
        assert row['profit_target_4_pct'] == 50.0
    
    @pytest.mark.integration
    def test_exit_strategy_mode(self, test_db, channel_factory):
        """Test exit strategy mode persistence"""
        for mode in ['signal', 'risk', 'hybrid']:
            channel = channel_factory(
                discord_channel_id=f"exit-mode-{mode}",
                name=f"exit-{mode}-channel",
                exit_strategy_mode=mode
            )
            
            cursor = test_db.execute(
                "SELECT exit_strategy_mode FROM channels WHERE id = ?",
                (channel['id'],)
            )
            row = cursor.fetchone()
            
            assert row['exit_strategy_mode'] == mode


class TestTradeRecords:
    """Test trade record persistence"""
    
    @pytest.mark.integration
    def test_create_trade_record(self, test_db):
        """Test creating a trade record"""
        cursor = test_db.execute("""
            INSERT INTO trades (
                symbol, action, quantity, price, broker, status,
                asset_type, strike, expiry, opt_type, channel_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('SPY', 'BTO', 10, 1.50, 'ALPACA_PAPER', 'FILLED', 
              'option', 450.0, '01/17', 'C', '123456789'))
        test_db.commit()
        
        trade_id = cursor.lastrowid
        
        cursor = test_db.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        
        assert row['symbol'] == 'SPY'
        assert row['action'] == 'BTO'
        assert row['broker'] == 'ALPACA_PAPER'
        assert row['status'] == 'FILLED'
    
    @pytest.mark.integration
    def test_update_trade_status(self, test_db):
        """Test updating trade status"""
        cursor = test_db.execute("""
            INSERT INTO trades (symbol, action, quantity, price, broker, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ('AAPL', 'BTO', 5, 2.00, 'WEBULL', 'PENDING'))
        test_db.commit()
        trade_id = cursor.lastrowid
        
        test_db.execute(
            "UPDATE trades SET status = ?, executed_price = ? WHERE id = ?",
            ('FILLED', 2.05, trade_id)
        )
        test_db.commit()
        
        cursor = test_db.execute("SELECT status, executed_price FROM trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        
        assert row['status'] == 'FILLED'
        assert row['executed_price'] == 2.05


class TestSignalLots:
    """Test signal lot tracking"""
    
    @pytest.mark.integration
    def test_create_signal_lot(self, test_db):
        """Test creating a signal lot for PNL tracking"""
        cursor = test_db.execute("""
            INSERT INTO signal_lots (
                signal_id, symbol, action, quantity, entry_price, broker, channel_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ('sig-123', 'SPY', 'BTO', 10, 1.50, 'ALPACA_PAPER', '123456789', 'OPEN'))
        test_db.commit()
        
        lot_id = cursor.lastrowid
        
        cursor = test_db.execute("SELECT * FROM signal_lots WHERE id = ?", (lot_id,))
        row = cursor.fetchone()
        
        assert row['signal_id'] == 'sig-123'
        assert row['status'] == 'OPEN'
    
    @pytest.mark.integration
    def test_close_signal_lot_with_pnl(self, test_db):
        """Test closing a lot and calculating PNL"""
        cursor = test_db.execute("""
            INSERT INTO signal_lots (
                signal_id, symbol, action, quantity, entry_price, broker, channel_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ('sig-456', 'AAPL', 'BTO', 5, 2.00, 'WEBULL', '987654321', 'OPEN'))
        test_db.commit()
        lot_id = cursor.lastrowid
        
        exit_price = 2.50
        pnl = (exit_price - 2.00) * 5 * 100
        pnl_pct = ((exit_price - 2.00) / 2.00) * 100
        
        test_db.execute("""
            UPDATE signal_lots SET 
                status = 'CLOSED',
                exit_price = ?,
                pnl = ?,
                pnl_pct = ?,
                closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (exit_price, pnl, pnl_pct, lot_id))
        test_db.commit()
        
        cursor = test_db.execute("SELECT * FROM signal_lots WHERE id = ?", (lot_id,))
        row = cursor.fetchone()
        
        assert row['status'] == 'CLOSED'
        assert row['exit_price'] == 2.50
        assert row['pnl'] == 250.0
        assert row['pnl_pct'] == 25.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
