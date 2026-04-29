"""
Integration tests for Enhanced Risk Management v2.0 complete flow.
Tests UI → Database → Risk Engine → Broker execution pipeline.
"""
import pytest
import sys
import os
import sqlite3
import tempfile
from typing import Optional
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.risk.risk_engine import (
    evaluate_exit_actions,
    calculate_dynamic_sl,
    DYNAMIC_SL_PROFILES,
    TradeState,
    RiskAction,
    ActionType
)
from src.risk.risk_types import (
    ChannelRiskSettings,
    PositionSnapshot,
    PositionCacheEntry,
    ExitDecision
)


def create_test_database():
    """Create an in-memory SQLite database with channel settings schema."""
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE channels (
            channel_id TEXT PRIMARY KEY,
            channel_name TEXT,
            execute_enabled INTEGER DEFAULT 0,
            risk_management_enabled INTEGER DEFAULT 0,
            profit_target_1_pct REAL DEFAULT 0,
            profit_target_2_pct REAL DEFAULT 0,
            profit_target_3_pct REAL DEFAULT 0,
            profit_target_4_pct REAL DEFAULT 0,
            profit_target_qty_1 INTEGER,
            profit_target_qty_2 INTEGER,
            profit_target_qty_3 INTEGER,
            profit_target_qty_4 INTEGER,
            stop_loss_pct REAL DEFAULT 0,
            trailing_stop_pct REAL DEFAULT 0,
            trailing_activation_pct REAL DEFAULT 15,
            leave_runner_enabled INTEGER DEFAULT 0,
            leave_runner_pct REAL DEFAULT 25,
            exit_strategy_mode TEXT DEFAULT 'risk',
            enable_dynamic_sl INTEGER DEFAULT 0,
            enable_giveback_guard INTEGER DEFAULT 0,
            giveback_allowed_pct REAL DEFAULT 30,
            dynamic_sl_profile TEXT DEFAULT 'standard'
        )
    ''')
    conn.commit()
    return conn


def insert_channel_settings(conn, channel_id, **kwargs):
    """Insert channel settings into test database."""
    defaults = {
        'channel_name': 'Test Channel',
        'execute_enabled': 1,
        'risk_management_enabled': 1,
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
        'leave_runner_enabled': 0,
        'leave_runner_pct': 25.0,
        'exit_strategy_mode': 'risk',
        'enable_dynamic_sl': 0,
        'enable_giveback_guard': 0,
        'giveback_allowed_pct': 30.0,
        'dynamic_sl_profile': 'standard'
    }
    defaults.update(kwargs)
    
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO channels (
            channel_id, channel_name, execute_enabled, risk_management_enabled,
            profit_target_1_pct, profit_target_2_pct, profit_target_3_pct, profit_target_4_pct,
            profit_target_qty_1, profit_target_qty_2, profit_target_qty_3, profit_target_qty_4,
            stop_loss_pct, trailing_stop_pct, trailing_activation_pct,
            leave_runner_enabled, leave_runner_pct, exit_strategy_mode,
            enable_dynamic_sl, enable_giveback_guard, giveback_allowed_pct, dynamic_sl_profile
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        channel_id,
        defaults['channel_name'],
        defaults['execute_enabled'],
        defaults['risk_management_enabled'],
        defaults['profit_target_1_pct'],
        defaults['profit_target_2_pct'],
        defaults['profit_target_3_pct'],
        defaults['profit_target_4_pct'],
        defaults['profit_target_qty_1'],
        defaults['profit_target_qty_2'],
        defaults['profit_target_qty_3'],
        defaults['profit_target_qty_4'],
        defaults['stop_loss_pct'],
        defaults['trailing_stop_pct'],
        defaults['trailing_activation_pct'],
        defaults['leave_runner_enabled'],
        defaults['leave_runner_pct'],
        defaults['exit_strategy_mode'],
        defaults['enable_dynamic_sl'],
        defaults['enable_giveback_guard'],
        defaults['giveback_allowed_pct'],
        defaults['dynamic_sl_profile']
    ))
    conn.commit()


def read_channel_settings_from_db(conn, channel_id) -> Optional[ChannelRiskSettings]:
    """Read channel settings from database and return ChannelRiskSettings object."""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT channel_id, channel_name,
               profit_target_1_pct, profit_target_2_pct, profit_target_3_pct, profit_target_4_pct,
               profit_target_qty_1, profit_target_qty_2, profit_target_qty_3, profit_target_qty_4,
               stop_loss_pct, trailing_stop_pct, trailing_activation_pct,
               leave_runner_enabled, leave_runner_pct, exit_strategy_mode,
               enable_dynamic_sl, enable_giveback_guard, giveback_allowed_pct, dynamic_sl_profile
        FROM channels
        WHERE channel_id = ?
    ''', (channel_id,))
    row = cursor.fetchone()
    
    if not row:
        return None
    
    return ChannelRiskSettings(
        channel_id=row[0],
        channel_name=row[1],
        profit_target_1_pct=row[2] or 0.0,
        profit_target_2_pct=row[3] or 0.0,
        profit_target_3_pct=row[4] or 0.0,
        profit_target_4_pct=row[5] or 0.0,
        profit_target_qty_1=row[6],
        profit_target_qty_2=row[7],
        profit_target_qty_3=row[8],
        profit_target_qty_4=row[9],
        stop_loss_pct=row[10] or 0.0,
        trailing_stop_pct=row[11] or 0.0,
        trailing_activation_pct=row[12] or 15.0,
        leave_runner_enabled=bool(row[13]),
        leave_runner_pct=row[14] or 25.0,
        exit_strategy_mode=row[15] or 'risk',
        enable_dynamic_sl=bool(row[16]),
        enable_giveback_guard=bool(row[17]),
        giveback_allowed_pct=row[18] or 30.0,
        dynamic_sl_profile=row[19] or 'standard'
    )


class TestUIToDBFlow:
    """Tests for UI → Database settings persistence."""
    
    def test_dynamic_sl_settings_persist_to_db(self):
        """Dynamic SL settings should persist correctly to database."""
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_dynamic_sl=1,
            dynamic_sl_profile='conservative',
            channel_name='Day Traders'
        )
        
        settings = read_channel_settings_from_db(conn, '123456')
        
        assert settings.enable_dynamic_sl == True
        assert settings.dynamic_sl_profile == 'conservative'
        assert settings.channel_name == 'Day Traders'
        conn.close()
    
    def test_giveback_guard_settings_persist_to_db(self):
        """Giveback Guard settings should persist correctly to database."""
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_giveback_guard=1,
            giveback_allowed_pct=25.0,
            channel_name='Swing Traders'
        )
        
        settings = read_channel_settings_from_db(conn, '123456')
        
        assert settings.enable_giveback_guard == True
        assert settings.giveback_allowed_pct == 25.0
        conn.close()
    
    def test_all_enhanced_settings_persist_together(self):
        """All Enhanced Risk v2.0 settings should persist together."""
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_dynamic_sl=1,
            dynamic_sl_profile='aggressive',
            enable_giveback_guard=1,
            giveback_allowed_pct=20.0,
            profit_target_1_pct=15.0,
            profit_target_2_pct=30.0,
            profit_target_3_pct=50.0,
            profit_target_4_pct=80.0,
            stop_loss_pct=25.0,
            trailing_stop_pct=8.0,
            exit_strategy_mode='hybrid'
        )
        
        settings = read_channel_settings_from_db(conn, '123456')
        
        assert settings.enable_dynamic_sl == True
        assert settings.dynamic_sl_profile == 'aggressive'
        assert settings.enable_giveback_guard == True
        assert settings.giveback_allowed_pct == 20.0
        assert settings.profit_target_1_pct == 15.0
        assert settings.profit_target_2_pct == 30.0
        assert settings.profit_target_3_pct == 50.0
        assert settings.profit_target_4_pct == 80.0
        assert settings.stop_loss_pct == 25.0
        assert settings.trailing_stop_pct == 8.0
        assert settings.exit_strategy_mode == 'hybrid'
        conn.close()


class TestDBToRiskEngineFlow:
    """Tests for Database → Risk Engine settings flow."""
    
    def test_db_settings_trigger_dynamic_sl_escalation(self):
        """Settings from DB should correctly trigger Dynamic SL escalation in risk engine."""
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_dynamic_sl=1,
            dynamic_sl_profile='standard'
        )
        settings = read_channel_settings_from_db(conn, '123456')
        
        state = TradeState(
            entry_price=1.00,
            current_price=1.30,
            qty=10,
            remaining_qty=10,
            pt1_hit=True
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        move_stop_actions = [a for a in actions if a.action_type == ActionType.MOVE_STOP]
        assert len(move_stop_actions) == 1
        assert move_stop_actions[0].new_stop_price == 1.00  # Breakeven for standard profile
        conn.close()
    
    def test_db_settings_trigger_giveback_guard_activation(self):
        """Settings from DB should correctly trigger Giveback Guard activation."""
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_giveback_guard=1,
            giveback_allowed_pct=30.0,
            trailing_activation_pct=15.0
        )
        settings = read_channel_settings_from_db(conn, '123456')
        
        state = TradeState(
            entry_price=1.00,
            current_price=1.45,
            qty=10,
            remaining_qty=10,
            max_pnl_seen=45.0,
            pt2_hit=True
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        assert updated_state.giveback_guard_active == True
        activate_actions = [a for a in actions if a.action_type == ActionType.ACTIVATE_GIVEBACK]
        assert len(activate_actions) == 1
        conn.close()
    
    def test_db_profile_selection_applied_correctly(self):
        """Different Dynamic SL profiles from DB should be applied correctly."""
        conn = create_test_database()
        
        for profile, expected_pt2_sl in [('conservative', 1.03), ('standard', 1.05), ('aggressive', 1.00)]:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM channels')
            conn.commit()
            
            insert_channel_settings(conn, '123456',
                enable_dynamic_sl=1,
                dynamic_sl_profile=profile
            )
            settings = read_channel_settings_from_db(conn, '123456')
            
            state = TradeState(
                entry_price=1.00,
                current_price=1.50,
                qty=10,
                remaining_qty=10,
                pt1_hit=True,
                pt2_hit=True
            )
            
            actions, updated_state = evaluate_exit_actions(state, settings)
            
            assert updated_state.dynamic_sl_price == expected_pt2_sl, \
                f"Profile {profile}: expected SL ${expected_pt2_sl}, got ${updated_state.dynamic_sl_price}"
        
        conn.close()


class TestRiskEngineToBrokerFlow:
    """Tests for Risk Engine → Broker execution flow."""
    
    def test_sell_all_action_creates_valid_exit_decision(self):
        """SELL_ALL action should translate to valid ExitDecision for broker."""
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_dynamic_sl=1,
            dynamic_sl_profile='standard',
            stop_loss_pct=50.0
        )
        settings = read_channel_settings_from_db(conn, '123456')
        
        state = TradeState(
            entry_price=1.00,
            current_price=0.95,  # Below breakeven
            qty=10,
            remaining_qty=10,
            pt1_hit=True,
            dynamic_sl_price=1.00  # Breakeven set
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        sell_actions = [a for a in actions if a.action_type == ActionType.SELL_ALL]
        assert len(sell_actions) >= 1
        
        action = sell_actions[0]
        exit_decision = ExitDecision(
            should_exit=True,
            reason=f"DYNAMIC SL [{settings.channel_name}] {action.reason}",
            exit_qty=action.qty,
            is_partial=False,
            risk_trigger='dynamic_sl'
        )
        
        assert exit_decision.should_exit == True
        assert exit_decision.exit_qty == 10
        assert 'Dynamic SL' in action.reason
        conn.close()
    
    def test_giveback_guard_exit_creates_valid_decision(self):
        """Giveback Guard exit should create valid ExitDecision for broker."""
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_giveback_guard=1,
            giveback_allowed_pct=30.0,
            stop_loss_pct=50.0
        )
        settings = read_channel_settings_from_db(conn, '123456')
        
        state = TradeState(
            entry_price=1.00,
            current_price=1.30,
            qty=10,
            remaining_qty=10,
            max_pnl_seen=50.0,
            pt2_hit=True,
            giveback_guard_active=True
        )
        
        actions, _ = evaluate_exit_actions(state, settings)
        
        sell_actions = [a for a in actions if a.action_type == ActionType.SELL_ALL]
        assert len(sell_actions) >= 1
        assert 'Giveback' in sell_actions[0].reason
        
        exit_decision = ExitDecision(
            should_exit=True,
            reason=f"GIVEBACK GUARD [{settings.channel_name}] {sell_actions[0].reason}",
            exit_qty=sell_actions[0].qty,
            is_partial=False,
            risk_trigger='giveback_guard'
        )
        
        assert exit_decision.should_exit == True
        assert exit_decision.exit_qty == 10
        conn.close()


class TestCacheStateUpdates:
    """Tests for cache state updates during risk evaluation."""
    
    def test_cache_state_updates_on_dynamic_sl_escalation(self):
        """PositionCacheEntry should update correctly when Dynamic SL escalates."""
        cache = PositionCacheEntry(
            entry_price=1.00,
            highest_price=1.30,
            tier1_hit=True,
            dynamic_sl_price=None
        )
        
        settings = ChannelRiskSettings(
            channel_id='123456',
            channel_name='Test',
            enable_dynamic_sl=True,
            dynamic_sl_profile='standard'
        )
        
        state = TradeState(
            entry_price=cache.entry_price,
            current_price=1.30,
            qty=10,
            remaining_qty=10
        )
        state.copy_from_cache(cache)
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        cache.dynamic_sl_price = updated_state.dynamic_sl_price
        cache.last_evaluated_price = updated_state.last_evaluated_price
        
        assert cache.dynamic_sl_price == 1.00  # Breakeven
        assert cache.last_evaluated_price == 1.30
    
    def test_cache_state_updates_on_giveback_activation(self):
        """PositionCacheEntry should update when Giveback Guard activates."""
        cache = PositionCacheEntry(
            entry_price=1.00,
            highest_price=1.45,
            tier2_hit=True,
            max_pnl_seen=0.0,
            giveback_guard_active=False
        )
        
        settings = ChannelRiskSettings(
            channel_id='123456',
            channel_name='Test',
            enable_giveback_guard=True,
            giveback_allowed_pct=30.0
        )
        
        state = TradeState(
            entry_price=cache.entry_price,
            current_price=1.45,
            qty=10,
            remaining_qty=10
        )
        state.copy_from_cache(cache)
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        cache.max_pnl_seen = updated_state.max_pnl_seen
        cache.giveback_guard_active = updated_state.giveback_guard_active
        
        assert cache.max_pnl_seen == pytest.approx(45.0, rel=1e-6)
        assert cache.giveback_guard_active == True


class TestCompleteE2EFlow:
    """Complete end-to-end flow tests."""
    
    def test_complete_flow_dynamic_sl_pt1_to_exit(self):
        """Complete flow: Settings → DB → Risk Engine → Dynamic SL exit.
        
        Flow: First evaluation hits PT1 → Second evaluation sets Dynamic SL → Third evaluation triggers exit
        (Dynamic SL escalation happens on next cycle after PT hit by design)
        """
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_dynamic_sl=1,
            dynamic_sl_profile='standard',
            profit_target_1_pct=20.0,
            profit_target_qty_1=5,
            stop_loss_pct=30.0,
            trailing_stop_pct=0.0
        )
        
        settings = read_channel_settings_from_db(conn, '123456')
        assert settings.enable_dynamic_sl == True
        
        state1 = TradeState(
            entry_price=1.00,
            current_price=1.25,
            qty=10,
            remaining_qty=10,
            highest_price=1.00,
            max_pnl_seen=0.0
        )
        
        actions1, updated_state1 = evaluate_exit_actions(state1, settings)
        
        assert updated_state1.pt1_hit == True
        
        state2 = TradeState(
            entry_price=1.00,
            current_price=1.30,
            qty=10,
            remaining_qty=updated_state1.remaining_qty,
            pt1_hit=True,
            highest_price=1.25,
            max_pnl_seen=25.0,
            last_evaluated_price=1.25
        )
        
        actions2, updated_state2 = evaluate_exit_actions(state2, settings)
        
        assert updated_state2.dynamic_sl_price == 1.00
        
        state3 = TradeState(
            entry_price=1.00,
            current_price=0.95,
            qty=10,
            remaining_qty=updated_state2.remaining_qty,
            pt1_hit=True,
            dynamic_sl_price=1.00,
            highest_price=1.30,
            max_pnl_seen=30.0,
            last_evaluated_price=1.30
        )
        
        actions3, _ = evaluate_exit_actions(state3, settings)
        
        sell_actions = [a for a in actions3 if a.action_type == ActionType.SELL_ALL]
        assert len(sell_actions) >= 1
        assert 'Dynamic SL' in sell_actions[0].reason
        
        conn.close()
    
    def test_complete_flow_giveback_guard_to_exit(self):
        """Complete flow: Settings → DB → Risk Engine → Giveback Guard exit."""
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_giveback_guard=1,
            giveback_allowed_pct=30.0,
            profit_target_1_pct=20.0,
            profit_target_2_pct=40.0,
            stop_loss_pct=50.0
        )
        
        settings = read_channel_settings_from_db(conn, '123456')
        assert settings.enable_giveback_guard == True
        
        state = TradeState(
            entry_price=1.00,
            current_price=1.50,
            qty=10,
            remaining_qty=6,
            pt1_hit=True,
            pt2_hit=True,
            max_pnl_seen=50.0,
            giveback_guard_active=True,
            last_evaluated_price=1.50
        )
        
        state2 = TradeState(
            entry_price=1.00,
            current_price=1.30,
            qty=10,
            remaining_qty=6,
            pt1_hit=True,
            pt2_hit=True,
            max_pnl_seen=50.0,
            giveback_guard_active=True,
            last_evaluated_price=1.50
        )
        
        actions, _ = evaluate_exit_actions(state2, settings)
        
        sell_actions = [a for a in actions if a.action_type == ActionType.SELL_ALL]
        assert len(sell_actions) >= 1
        assert 'Giveback' in sell_actions[0].reason
        
        conn.close()


class TestDisabledFeatures:
    """Tests to ensure disabled features don't interfere."""
    
    def test_disabled_dynamic_sl_no_escalation(self):
        """Disabled Dynamic SL should not trigger escalation."""
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_dynamic_sl=0,
            dynamic_sl_profile='standard'
        )
        
        settings = read_channel_settings_from_db(conn, '123456')
        assert settings.enable_dynamic_sl == False
        
        state = TradeState(
            entry_price=1.00,
            current_price=1.30,
            qty=10,
            remaining_qty=10,
            pt1_hit=True,
            pt2_hit=True
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        move_actions = [a for a in actions if a.action_type == ActionType.MOVE_STOP]
        assert len(move_actions) == 0
        assert updated_state.dynamic_sl_price is None
        
        conn.close()
    
    def test_disabled_giveback_guard_no_activation(self):
        """Disabled Giveback Guard should not activate."""
        conn = create_test_database()
        
        insert_channel_settings(conn, '123456',
            enable_giveback_guard=0,
            giveback_allowed_pct=30.0
        )
        
        settings = read_channel_settings_from_db(conn, '123456')
        assert settings.enable_giveback_guard == False
        
        state = TradeState(
            entry_price=1.00,
            current_price=1.45,
            qty=10,
            remaining_qty=10,
            pt2_hit=True,
            max_pnl_seen=45.0
        )
        
        actions, updated_state = evaluate_exit_actions(state, settings)
        
        activate_actions = [a for a in actions if a.action_type == ActionType.ACTIVATE_GIVEBACK]
        assert len(activate_actions) == 0
        assert updated_state.giveback_guard_active == False
        
        conn.close()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
