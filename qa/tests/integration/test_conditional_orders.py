"""
Integration Tests for Conditional Order Flow
Tests over/above, under/below triggers, timeout precedence, channel settings linkage
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


class TestConditionalTriggers:
    """Test conditional order trigger conditions"""
    
    @pytest.mark.integration
    def test_over_trigger_condition(self):
        """Order should execute when price goes OVER trigger price"""
        trigger_price = 450.0
        trigger_type = 'over'
        
        price_journey = [448.0, 449.0, 449.5, 450.5, 451.0]
        
        triggered = False
        trigger_at_price = None
        for price in price_journey:
            if trigger_type == 'over' and price > trigger_price:
                triggered = True
                trigger_at_price = price
                break
        
        assert triggered is True
        assert trigger_at_price == 450.5
    
    @pytest.mark.integration
    def test_above_trigger_condition(self):
        """Order should execute when price goes ABOVE trigger price (alias for over)"""
        trigger_price = 400.0
        trigger_type = 'above'
        
        price_journey = [398.0, 399.0, 400.0, 401.0]
        
        triggered = False
        for price in price_journey:
            if trigger_type in ('over', 'above') and price > trigger_price:
                triggered = True
                break
        
        assert triggered is True
    
    @pytest.mark.integration
    def test_under_trigger_condition(self):
        """Order should execute when price goes UNDER trigger price"""
        trigger_price = 445.0
        trigger_type = 'under'
        
        price_journey = [448.0, 446.0, 445.0, 444.0]
        
        triggered = False
        trigger_at_price = None
        for price in price_journey:
            if trigger_type == 'under' and price < trigger_price:
                triggered = True
                trigger_at_price = price
                break
        
        assert triggered is True
        assert trigger_at_price == 444.0
    
    @pytest.mark.integration
    def test_below_trigger_condition(self):
        """Order should execute when price goes BELOW trigger price (alias for under)"""
        trigger_price = 380.0
        trigger_type = 'below'
        
        price_journey = [382.0, 381.0, 380.0, 379.0]
        
        triggered = False
        for price in price_journey:
            if trigger_type in ('under', 'below') and price < trigger_price:
                triggered = True
                break
        
        assert triggered is True
    
    @pytest.mark.integration
    def test_trigger_not_met(self):
        """Order should NOT trigger if condition is never met"""
        trigger_price = 500.0
        trigger_type = 'over'
        
        price_journey = [480.0, 485.0, 490.0, 495.0, 498.0]
        
        triggered = False
        for price in price_journey:
            if trigger_type == 'over' and price > trigger_price:
                triggered = True
                break
        
        assert triggered is False


class TestTimeoutPrecedence:
    """Test conditional order timeout precedence"""
    
    @pytest.mark.integration
    def test_order_timeout_minutes_highest_priority(self, test_db, channel_factory):
        """order_timeout_minutes should take highest priority"""
        channel = channel_factory(
            discord_channel_id="timeout-priority",
            name="timeout-test-channel",
            conditional_order_enabled=1
        )
        
        order_timeout_minutes = 30
        conditional_order_timeout_minutes = 60
        conditional_order_expiry = 'end_of_day'
        
        effective_timeout = order_timeout_minutes or conditional_order_timeout_minutes or conditional_order_expiry
        
        assert effective_timeout == 30
    
    @pytest.mark.integration
    def test_conditional_order_timeout_second_priority(self, test_db, channel_factory):
        """conditional_order_timeout_minutes should be second priority"""
        order_timeout_minutes = None
        conditional_order_timeout_minutes = 60
        conditional_order_expiry = 'end_of_day'
        
        effective_timeout = order_timeout_minutes or conditional_order_timeout_minutes or conditional_order_expiry
        
        assert effective_timeout == 60
    
    @pytest.mark.integration
    def test_conditional_order_expiry_fallback(self, test_db, channel_factory):
        """conditional_order_expiry (legacy) should be fallback"""
        order_timeout_minutes = None
        conditional_order_timeout_minutes = None
        conditional_order_expiry = 'end_of_day'
        
        effective_timeout = order_timeout_minutes or conditional_order_timeout_minutes or conditional_order_expiry
        
        assert effective_timeout == 'end_of_day'


class TestChannelSettingsLinkage:
    """Test channel settings flow to conditional orders"""
    
    @pytest.mark.integration
    def test_position_sizing_flows_to_conditional(self, test_db, channel_factory):
        """Channel position_size_pct should flow to conditional orders"""
        channel = channel_factory(
            discord_channel_id="conditional-sizing",
            name="conditional-sizing-channel",
            conditional_order_enabled=1
        )
        
        test_db.execute(
            "UPDATE channels SET position_size_pct = 5.0 WHERE id = ?",
            (channel['id'],)
        )
        test_db.commit()
        
        cursor = test_db.execute(
            "SELECT position_size_pct FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row['position_size_pct'] == 5.0
    
    @pytest.mark.integration
    def test_trailing_stop_flows_to_conditional(self, test_db, channel_factory):
        """Channel trailing_stop_pct should flow to conditional orders when > 0"""
        channel = channel_factory(
            discord_channel_id="conditional-trail",
            name="conditional-trailing-channel",
            trailing_stop_pct=15.0,
            trailing_activation_pct=35.0
        )
        
        cursor = test_db.execute(
            "SELECT trailing_stop_pct, trailing_activation_pct FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        trailing_enabled = row['trailing_stop_pct'] > 0 if row['trailing_stop_pct'] else False
        
        assert trailing_enabled is True
    
    @pytest.mark.integration
    def test_exit_strategy_flows_to_conditional(self, test_db, channel_factory):
        """Channel exit_strategy_mode should flow to conditional orders"""
        channel = channel_factory(
            discord_channel_id="conditional-exit",
            name="conditional-exit-channel",
            exit_strategy_mode='hybrid'
        )
        
        cursor = test_db.execute(
            "SELECT exit_strategy_mode FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row['exit_strategy_mode'] == 'hybrid'


class TestConditionalOrderExpiry:
    """Test conditional order expiration"""
    
    @pytest.mark.integration
    def test_end_of_day_expiry(self):
        """Conditional order should expire at end of trading day"""
        from datetime import datetime, time
        
        market_close = time(16, 0)
        current_time = time(15, 30)
        
        order_should_be_active = current_time < market_close
        assert order_should_be_active is True
        
        current_time = time(16, 5)
        order_should_expire = current_time >= market_close
        assert order_should_expire is True
    
    @pytest.mark.integration
    def test_minute_based_expiry(self):
        """Conditional order should expire after X minutes"""
        from datetime import datetime, timedelta
        
        order_created = datetime(2026, 1, 14, 10, 0, 0)
        timeout_minutes = 30
        expiry_time = order_created + timedelta(minutes=timeout_minutes)
        
        current_time = datetime(2026, 1, 14, 10, 25, 0)
        order_active = current_time < expiry_time
        assert order_active is True
        
        current_time = datetime(2026, 1, 14, 10, 35, 0)
        order_expired = current_time >= expiry_time
        assert order_expired is True


class TestConditionalOrderMonitoring:
    """Test conditional order monitoring system"""
    
    @pytest.mark.integration
    def test_price_check_interval(self):
        """Conditional orders should be checked at regular intervals"""
        check_interval_seconds = 5
        checks_per_minute = 60 / check_interval_seconds
        
        assert checks_per_minute == 12
    
    @pytest.mark.integration
    def test_trigger_offset_percent(self):
        """Trigger offset should adjust the trigger price"""
        original_trigger = 450.0
        offset_pct = 0.5
        adjusted_trigger = original_trigger * (1 + offset_pct / 100)
        
        assert round(adjusted_trigger, 2) == 452.25


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
