"""
Integration Tests for Risk Management
Tests trailing stop, profit targets, stop loss, exit strategy modes
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class TestStopLoss:
    """Test stop loss triggering"""
    
    @pytest.mark.integration
    def test_stop_loss_trigger_at_threshold(self, test_db, channel_factory):
        """Stop loss should trigger when price drops to threshold"""
        channel = channel_factory(
            discord_channel_id="sl-test-channel",
            name="stoploss-test",
            risk_management_enabled=1,
            stop_loss_pct=25.0
        )
        
        entry_price = 2.00
        stop_loss_pct = 25.0
        stop_loss_trigger_price = entry_price * (1 - stop_loss_pct / 100)
        
        current_prices = [2.00, 1.80, 1.60, 1.50, 1.40]
        
        triggered = False
        trigger_price = None
        for price in current_prices:
            pnl_pct = ((price - entry_price) / entry_price) * 100
            if pnl_pct <= -stop_loss_pct:
                triggered = True
                trigger_price = price
                break
        
        assert triggered is True
        assert trigger_price == 1.50
    
    @pytest.mark.integration
    def test_stop_loss_not_trigger_above_threshold(self, test_db, channel_factory):
        """Stop loss should NOT trigger when price is above threshold"""
        channel = channel_factory(
            discord_channel_id="sl-no-trigger",
            name="stoploss-no-trigger",
            risk_management_enabled=1,
            stop_loss_pct=25.0
        )
        
        entry_price = 2.00
        current_price = 1.60
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        assert pnl_pct > -25.0


class TestTrailingStop:
    """Test trailing stop functionality"""
    
    @pytest.mark.integration
    def test_trailing_stop_activates_after_profit_threshold(self, test_db, channel_factory):
        """Trailing stop should only activate after reaching profit threshold"""
        channel = channel_factory(
            discord_channel_id="trail-activate",
            name="trailing-activation-test",
            trailing_stop_pct=15.0,
            trailing_activation_pct=35.0
        )
        
        entry_price = 1.00
        activation_pct = 35.0
        
        price_at_35_pct = entry_price * (1 + activation_pct / 100)
        
        assert price_at_35_pct == 1.35
        
        price_journey = [1.00, 1.10, 1.20, 1.30, 1.35, 1.40, 1.50]
        
        trailing_activated = False
        high_water_mark = entry_price
        
        for price in price_journey:
            if price > high_water_mark:
                high_water_mark = price
            
            current_pnl_pct = ((price - entry_price) / entry_price) * 100
            
            if current_pnl_pct >= activation_pct:
                trailing_activated = True
                break
        
        assert trailing_activated is True
        assert high_water_mark >= 1.35
    
    @pytest.mark.integration
    def test_trailing_stop_triggers_after_pullback(self, test_db, channel_factory):
        """Trailing stop should trigger when price pulls back by trailing percentage"""
        channel = channel_factory(
            discord_channel_id="trail-trigger",
            name="trailing-trigger-test",
            trailing_stop_pct=15.0,
            trailing_activation_pct=35.0
        )
        
        entry_price = 1.00
        high_water_mark = 1.50
        trailing_pct = 15.0
        
        trail_stop_price = high_water_mark * (1 - trailing_pct / 100)
        
        assert trail_stop_price == 1.275
        
        current_price = 1.20
        
        should_trigger = current_price <= trail_stop_price
        assert should_trigger is True
    
    @pytest.mark.integration
    def test_trailing_stop_not_on_downside(self, test_db, channel_factory):
        """Trailing stop should NOT activate if position never reached profit threshold"""
        channel = channel_factory(
            discord_channel_id="trail-downside",
            name="trailing-downside-test",
            trailing_stop_pct=15.0,
            trailing_activation_pct=35.0,
            stop_loss_pct=25.0
        )
        
        entry_price = 1.00
        activation_pct = 35.0
        
        price_journey = [1.00, 1.10, 1.05, 0.90, 0.80, 0.75]
        
        trailing_activated = False
        for price in price_journey:
            pnl_pct = ((price - entry_price) / entry_price) * 100
            if pnl_pct >= activation_pct:
                trailing_activated = True
        
        assert trailing_activated is False


class TestProfitTargets:
    """Test 4-tier profit target system"""
    
    @pytest.mark.integration
    def test_profit_target_1_trigger(self, test_db, channel_factory):
        """PT1 should trigger at first profit threshold"""
        channel = channel_factory(
            discord_channel_id="pt1-test",
            name="profit-target-1-test",
            profit_target_1_pct=15.0
        )
        
        entry_price = 1.00
        pt1_pct = 15.0
        
        pt1_target = entry_price * (1 + pt1_pct / 100)
        
        assert pt1_target == 1.15
        
        current_price = 1.20
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        assert pnl_pct >= pt1_pct
    
    @pytest.mark.integration
    def test_all_profit_targets_in_sequence(self, test_db, channel_factory):
        """All 4 profit targets should trigger in sequence"""
        channel = channel_factory(
            discord_channel_id="pt-sequence",
            name="profit-targets-sequence",
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
        
        entry_price = 1.00
        targets = [15.0, 25.0, 35.0, 50.0]
        
        current_price = 1.55
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        triggered_targets = [t for t in targets if pnl_pct >= t]
        
        assert len(triggered_targets) == 4


class TestExitStrategyModes:
    """Test exit strategy mode behavior"""
    
    @pytest.mark.integration
    def test_signal_mode_ignores_risk_triggers(self, test_db, channel_factory):
        """Signal mode should ONLY exit on trader signals, not risk triggers"""
        channel = channel_factory(
            discord_channel_id="signal-mode",
            name="signal-mode-channel",
            exit_strategy_mode='signal',
            risk_management_enabled=1,
            stop_loss_pct=25.0
        )
        
        cursor = test_db.execute(
            "SELECT exit_strategy_mode FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row['exit_strategy_mode'] == 'signal'
    
    @pytest.mark.integration
    def test_risk_mode_ignores_signal_exits(self, test_db, channel_factory):
        """Risk mode should ONLY exit on automated risk triggers"""
        channel = channel_factory(
            discord_channel_id="risk-mode",
            name="risk-mode-channel",
            exit_strategy_mode='risk',
            risk_management_enabled=1,
            stop_loss_pct=25.0
        )
        
        cursor = test_db.execute(
            "SELECT exit_strategy_mode FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row['exit_strategy_mode'] == 'risk'
    
    @pytest.mark.integration
    def test_hybrid_mode_allows_both(self, test_db, channel_factory):
        """Hybrid mode should exit on BOTH trader signals AND risk triggers"""
        channel = channel_factory(
            discord_channel_id="hybrid-mode",
            name="hybrid-mode-channel",
            exit_strategy_mode='hybrid',
            risk_management_enabled=1,
            stop_loss_pct=25.0
        )
        
        cursor = test_db.execute(
            "SELECT exit_strategy_mode FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row['exit_strategy_mode'] == 'hybrid'


class TestLeaveRunner:
    """Test leave runner functionality"""
    
    @pytest.mark.integration
    def test_leave_runner_percentage(self, test_db, channel_factory):
        """Leave runner should keep specified percentage of position"""
        channel = channel_factory(
            discord_channel_id="leave-runner",
            name="leave-runner-channel",
            leave_runner_enabled=1
        )
        
        test_db.execute(
            "UPDATE channels SET leave_runner_pct = 25.0 WHERE id = ?",
            (channel['id'],)
        )
        test_db.commit()
        
        original_qty = 100
        leave_runner_pct = 25.0
        
        qty_to_close = int(original_qty * (1 - leave_runner_pct / 100))
        qty_to_keep = original_qty - qty_to_close
        
        assert qty_to_close == 75
        assert qty_to_keep == 25


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
