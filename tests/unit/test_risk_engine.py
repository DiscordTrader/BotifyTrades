"""
Unit tests for the risk engine module.
Tests Dynamic SL Escalation, Giveback Guard, priority ordering, and idempotency.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.risk.risk_engine import (
    evaluate_exit_actions,
    calculate_dynamic_sl,
    DYNAMIC_SL_PROFILES,
    TradeState,
    RiskAction,
    ActionType
)
from src.risk.risk_types import ChannelRiskSettings


def make_channel_settings(**kwargs) -> ChannelRiskSettings:
    """Helper to create ChannelRiskSettings with defaults."""
    defaults = {
        'channel_id': '123456',
        'channel_name': 'Test Channel',
        'profit_target_1_pct': 20.0,
        'profit_target_2_pct': 40.0,
        'profit_target_3_pct': 60.0,
        'profit_target_4_pct': 100.0,
        'profit_target_qty_1': 25,
        'profit_target_qty_2': 25,
        'profit_target_qty_3': 25,
        'profit_target_qty_4': 25,
        'stop_loss_pct': 30.0,
        'trailing_stop_pct': 10.0,
        'trailing_activation_pct': 15.0,
        'leave_runner_enabled': False,
        'leave_runner_pct': 25.0,
        'trim_order_mode': 'market',
        'trim_limit_offset': 0.01,
        'exit_strategy_mode': 'risk',
        'enable_dynamic_sl': False,
        'enable_giveback_guard': False,
        'giveback_allowed_pct': 30.0,
        'dynamic_sl_profile': 'standard'
    }
    defaults.update(kwargs)
    return ChannelRiskSettings(**defaults)


def make_trade_state(**kwargs) -> TradeState:
    """Helper to create TradeState with defaults."""
    defaults = {
        'entry_price': 1.00,
        'current_price': 1.20,
        'qty': 10,
        'remaining_qty': 10,
        'highest_price': 1.20,
        'max_pnl_seen': 20.0,
        'pt1_hit': False,
        'pt2_hit': False,
        'pt3_hit': False,
        'pt4_hit': False,
        'trailing_active': False,
        'giveback_guard_active': False,
        'dynamic_sl_price': None,
        'trailing_stop_price': None,
        'current_stop_price': None,
        'last_evaluated_price': None
    }
    defaults.update(kwargs)
    return TradeState(**defaults)


class TestDynamicSLProfiles:
    """Tests for Dynamic SL Escalation feature."""
    
    def test_standard_profile_levels(self):
        """Verify standard profile SL levels: BE, +5%, +10%, +17%."""
        profile = DYNAMIC_SL_PROFILES['standard']
        assert profile['pt1_sl_pct'] == 0    # Breakeven
        assert profile['pt2_sl_pct'] == 5    # +5%
        assert profile['pt3_sl_pct'] == 10   # +10%
        assert profile['pt4_sl_pct'] == 17   # +17%

    def test_conservative_profile_levels(self):
        """Verify conservative profile SL levels: BE, +3%, +8%, +15%."""
        profile = DYNAMIC_SL_PROFILES['conservative']
        assert profile['pt1_sl_pct'] == 0    # Breakeven
        assert profile['pt2_sl_pct'] == 3    # +3%
        assert profile['pt3_sl_pct'] == 8    # +8%
        assert profile['pt4_sl_pct'] == 15   # +15%

    def test_aggressive_profile_levels(self):
        """Verify aggressive profile SL levels: -2%, BE, +8%, +15%."""
        profile = DYNAMIC_SL_PROFILES['aggressive']
        assert profile['pt1_sl_pct'] == -2   # -2% (still risk)
        assert profile['pt2_sl_pct'] == 0    # Breakeven
        assert profile['pt3_sl_pct'] == 8    # +8%
        assert profile['pt4_sl_pct'] == 15   # +15%
    
    def test_calculate_dynamic_sl_no_pts_hit(self):
        """No dynamic SL when no profit targets hit."""
        pts_hit = {1: False, 2: False, 3: False, 4: False}
        sl_price = calculate_dynamic_sl(1.00, pts_hit, 'standard')
        assert sl_price is None
    
    def test_calculate_dynamic_sl_pt1_hit_standard(self):
        """Standard profile: PT1 hit → SL at breakeven ($1.00)."""
        pts_hit = {1: True, 2: False, 3: False, 4: False}
        sl_price = calculate_dynamic_sl(1.00, pts_hit, 'standard')
        assert sl_price == 1.00  # 0% = breakeven
    
    def test_calculate_dynamic_sl_pt2_hit_standard(self):
        """Standard profile: PT2 hit → SL at +5% ($1.05)."""
        pts_hit = {1: True, 2: True, 3: False, 4: False}
        sl_price = calculate_dynamic_sl(1.00, pts_hit, 'standard')
        assert sl_price == 1.05  # 5% above entry
    
    def test_calculate_dynamic_sl_pt3_hit_standard(self):
        """Standard profile: PT3 hit → SL at +10% ($1.10)."""
        pts_hit = {1: True, 2: True, 3: True, 4: False}
        sl_price = calculate_dynamic_sl(1.00, pts_hit, 'standard')
        assert sl_price == 1.10  # 10% above entry

    def test_calculate_dynamic_sl_pt4_hit_standard(self):
        """Standard profile: PT4 hit → SL at +17% ($1.17)."""
        pts_hit = {1: True, 2: True, 3: True, 4: True}
        sl_price = calculate_dynamic_sl(1.00, pts_hit, 'standard')
        assert sl_price == 1.17  # 17% above entry
    
    def test_calculate_dynamic_sl_pt1_hit_aggressive(self):
        """Aggressive profile: PT1 hit → SL at -2% ($0.98)."""
        pts_hit = {1: True, 2: False, 3: False, 4: False}
        sl_price = calculate_dynamic_sl(1.00, pts_hit, 'aggressive')
        assert sl_price == 0.98  # -2%, still risk
    
    def test_dynamic_sl_escalation_triggers_move_stop(self):
        """Dynamic SL escalation should trigger MOVE_STOP action when PT1 hit."""
        settings = make_channel_settings(enable_dynamic_sl=True, dynamic_sl_profile='standard')
        state = make_trade_state(
            entry_price=1.00,
            current_price=1.30,  # Well above breakeven
            pt1_hit=True
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        move_stop_actions = [a for a in actions if a.action_type == ActionType.MOVE_STOP]
        assert len(move_stop_actions) == 1
        assert move_stop_actions[0].new_stop_price == 1.00  # Breakeven
        assert updated_state.dynamic_sl_price == 1.00
    
    def test_dynamic_sl_no_downgrade(self):
        """Dynamic SL should never move lower (downgrade)."""
        settings = make_channel_settings(enable_dynamic_sl=True, dynamic_sl_profile='standard')
        state = make_trade_state(
            entry_price=1.00,
            current_price=1.50,
            pt1_hit=True,
            pt2_hit=True,
            dynamic_sl_price=1.05  # Already at +5%
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        move_stop_actions = [a for a in actions if a.action_type == ActionType.MOVE_STOP]
        assert len(move_stop_actions) == 0  # No downgrade
        assert updated_state.dynamic_sl_price == 1.05  # Unchanged


class TestGivebackGuard:
    """Tests for Max Profit Giveback Guard feature."""
    
    def test_giveback_guard_not_active_without_pt2(self):
        """Giveback guard should not activate without PT2 hit and below threshold."""
        settings = make_channel_settings(
            enable_giveback_guard=True,
            giveback_allowed_pct=30.0,
            trailing_activation_pct=50.0  # High threshold
        )
        state = make_trade_state(
            pt1_hit=True,
            max_pnl_seen=25.0,
            current_price=1.20
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        assert not updated_state.giveback_guard_active
        sell_actions = [a for a in actions if a.action_type == ActionType.SELL_ALL]
        assert len(sell_actions) == 0
    
    def test_giveback_guard_activates_on_pt2(self):
        """Giveback guard should activate when PT2 hit."""
        settings = make_channel_settings(
            enable_giveback_guard=True,
            giveback_allowed_pct=30.0,
            profit_target_1_pct=20.0,
            profit_target_2_pct=40.0
        )
        state = make_trade_state(
            pt1_hit=True,
            pt2_hit=True,
            max_pnl_seen=45.0,
            current_price=1.45
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        assert updated_state.giveback_guard_active
        activate_actions = [a for a in actions if a.action_type == ActionType.ACTIVATE_GIVEBACK]
        assert len(activate_actions) == 1
    
    def test_giveback_guard_activates_on_trailing_threshold(self):
        """Giveback guard should activate when max_pnl_seen >= trailing_activation_pct."""
        settings = make_channel_settings(
            enable_giveback_guard=True,
            giveback_allowed_pct=30.0,
            trailing_activation_pct=15.0
        )
        state = make_trade_state(
            pt1_hit=False,  # No PT2
            max_pnl_seen=20.0,  # >= 15%
            current_price=1.20
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        assert updated_state.giveback_guard_active
    
    def test_giveback_guard_triggers_exit(self):
        """Giveback guard should trigger SELL_ALL when profit drops too much from peak."""
        settings = make_channel_settings(
            enable_giveback_guard=True,
            giveback_allowed_pct=30.0
        )
        state = make_trade_state(
            pt2_hit=True,
            max_pnl_seen=50.0,  # Peak profit at 50%
            current_price=1.30,  # Now at 30%, dropped 40% from peak (>30% allowed)
            giveback_guard_active=True
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        sell_actions = [a for a in actions if a.action_type == ActionType.SELL_ALL]
        assert len(sell_actions) >= 1
        assert 'Giveback' in sell_actions[0].reason
    
    def test_giveback_guard_no_exit_within_threshold(self):
        """Giveback guard should not exit if profit drop is within allowed threshold."""
        settings = make_channel_settings(
            enable_giveback_guard=True,
            giveback_allowed_pct=30.0
        )
        state = make_trade_state(
            pt2_hit=True,
            max_pnl_seen=50.0,  # Peak profit at 50%
            current_price=1.40,  # Now at 40%, dropped only 20% from peak (within 30%)
            giveback_guard_active=True
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        sell_actions = [a for a in actions if a.action_type == ActionType.SELL_ALL and 'Giveback' in a.reason]
        assert len(sell_actions) == 0


class TestPriorityOrdering:
    """Tests for exit condition priority ordering."""
    
    def test_hard_sl_preempts_all(self):
        """Hard stop loss should preempt all other exit conditions."""
        settings = make_channel_settings(
            stop_loss_pct=30.0,
            enable_dynamic_sl=True,
            enable_giveback_guard=True,
            trailing_stop_pct=10.0
        )
        state = make_trade_state(
            entry_price=1.00,
            current_price=0.65,  # -35%, below hard SL of 30%
            pt1_hit=True,  # Would trigger dynamic SL
            giveback_guard_active=True,  # Would trigger giveback
            trailing_active=True  # Would trigger trailing
        )
        
        actions, _ = evaluate_exit_actions(state, settings)
        
        assert len(actions) >= 1
        assert actions[0].action_type == ActionType.SELL_ALL
        assert 'Hard SL' in actions[0].reason
    
    def test_dynamic_sl_preempts_giveback(self):
        """Dynamic SL trigger should preempt giveback guard."""
        settings = make_channel_settings(
            stop_loss_pct=50.0,  # High, won't trigger
            enable_dynamic_sl=True,
            dynamic_sl_profile='standard',
            enable_giveback_guard=True,
            giveback_allowed_pct=30.0
        )
        state = make_trade_state(
            entry_price=1.00,
            current_price=0.98,  # Below breakeven
            pt1_hit=True,
            dynamic_sl_price=1.00,  # Already set to breakeven
            max_pnl_seen=25.0,
            giveback_guard_active=True
        )
        
        actions, _ = evaluate_exit_actions(state, settings)
        
        sell_actions = [a for a in actions if a.action_type == ActionType.SELL_ALL]
        assert len(sell_actions) >= 1
        assert 'Dynamic SL' in sell_actions[0].reason
    
    def test_giveback_preempts_trailing(self):
        """Giveback guard should preempt trailing stop when both would trigger."""
        settings = make_channel_settings(
            stop_loss_pct=50.0,  # High, won't trigger
            enable_dynamic_sl=False,
            enable_giveback_guard=True,
            giveback_allowed_pct=30.0,
            trailing_stop_pct=10.0
        )
        state = make_trade_state(
            entry_price=1.00,
            current_price=1.30,  # 30% profit
            highest_price=1.60,  # Was at 60%
            max_pnl_seen=60.0,
            pt2_hit=True,
            giveback_guard_active=True,
            trailing_active=True,
            trailing_stop_price=1.44  # Would trigger at $1.44
        )
        
        actions, _ = evaluate_exit_actions(state, settings)
        
        sell_actions = [a for a in actions if a.action_type == ActionType.SELL_ALL]
        assert len(sell_actions) >= 1
        assert 'Giveback' in sell_actions[0].reason


class TestIdempotency:
    """Tests for idempotency via last_evaluated_price tracking."""
    
    def test_no_duplicate_actions_same_price(self):
        """Evaluating same price twice should not produce duplicate actions."""
        settings = make_channel_settings(enable_dynamic_sl=True)
        state = make_trade_state(
            current_price=1.30,
            pt1_hit=True,
            last_evaluated_price=None
        )
        
        actions1, state1 = evaluate_exit_actions(state, settings)
        actions2, state2 = evaluate_exit_actions(state1, settings)
        
        assert state1.last_evaluated_price == 1.30
        assert state2.last_evaluated_price == 1.30
        
        move_actions1 = [a for a in actions1 if a.action_type == ActionType.MOVE_STOP]
        assert len(move_actions1) == 1
        assert len(actions2) == 0  # No actions on second call
    
    def test_new_actions_on_price_change(self):
        """New price should produce new evaluation."""
        settings = make_channel_settings(enable_dynamic_sl=True)
        state = make_trade_state(
            current_price=1.30,
            pt1_hit=True,
            last_evaluated_price=1.25  # Different price
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        assert updated_state.last_evaluated_price == 1.30
        # Should have evaluated and produced move_stop action
        move_actions = [a for a in actions if a.action_type == ActionType.MOVE_STOP]
        assert len(move_actions) == 1


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_zero_remaining_qty_returns_empty(self):
        """No actions when position is already closed (remaining_qty=0)."""
        settings = make_channel_settings()
        state = make_trade_state(remaining_qty=0)
        
        actions, _ = evaluate_exit_actions(state, settings)
        
        assert len(actions) == 0
    
    def test_highest_price_updates_on_new_high(self):
        """highest_price should update when current_price exceeds it."""
        settings = make_channel_settings()
        state = make_trade_state(
            current_price=1.50,
            highest_price=1.40,
            max_pnl_seen=40.0
        )
        
        _, updated_state = evaluate_exit_actions(state, settings)
        
        assert updated_state.highest_price == 1.50
        assert updated_state.max_pnl_seen == 50.0  # 50% profit
    
    def test_disabled_features_have_no_effect(self):
        """Disabled features should not trigger any actions."""
        settings = make_channel_settings(
            enable_dynamic_sl=False,
            enable_giveback_guard=False,
            trailing_stop_pct=0.0,
            stop_loss_pct=0.0,
            profit_target_1_pct=0.0,
            profit_target_2_pct=0.0,
            profit_target_3_pct=0.0,
            profit_target_4_pct=0.0
        )
        state = make_trade_state(
            pt1_hit=True,
            pt2_hit=True,
            max_pnl_seen=50.0,
            current_price=1.30
        )
        
        actions, _ = evaluate_exit_actions(state, settings)
        
        sell_actions = [a for a in actions if a.action_type == ActionType.SELL_ALL]
        assert len(sell_actions) == 0
    
    def test_dynamic_sl_disabled_no_move_stop(self):
        """No MOVE_STOP when dynamic SL is disabled."""
        settings = make_channel_settings(enable_dynamic_sl=False)
        state = make_trade_state(pt1_hit=True, pt2_hit=True, pt3_hit=True, current_price=1.80)
        
        actions, _ = evaluate_exit_actions(state, settings)
        
        move_actions = [a for a in actions if a.action_type == ActionType.MOVE_STOP]
        assert len(move_actions) == 0


class TestProfitTargetTiers:
    """Tests for profit target tier triggering."""
    
    def test_pt1_triggers_partial_sell(self):
        """PT1 hit should trigger partial sell action."""
        settings = make_channel_settings(
            profit_target_1_pct=20.0,
            profit_target_2_pct=40.0,
            profit_target_3_pct=60.0,
            profit_target_4_pct=100.0
        )
        state = make_trade_state(
            entry_price=1.00,
            current_price=1.25,  # 25% profit, above PT1 (20%)
            qty=10,
            remaining_qty=10
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        assert updated_state.pt1_hit
        partial_sells = [a for a in actions if a.action_type == ActionType.SELL_PARTIAL]
        assert len(partial_sells) >= 1
        assert partial_sells[0].tier == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
