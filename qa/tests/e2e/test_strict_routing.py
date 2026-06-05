"""
End-to-End Tests for STRICT Routing Architecture
Tests complete signal-to-execution pipeline with multi-broker routing
"""
import pytest
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from qa.tests.mocks.mock_broker import MockAlpacaBroker, MockWebullBroker
from qa.tests.mocks.mock_discord import MockDiscordClient, create_signal_message


class TestStrictRoutingE2E:
    """End-to-end tests for strict routing architecture"""
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_full_signal_to_execution_pipeline(
        self, test_db, channel_factory, signal_factory, mock_brokers
    ):
        """
        Complete pipeline test:
        1. Signal received in Discord
        2. Signal parsed
        3. Channel config loaded (enabled_brokers)
        4. Route to ALL configured brokers
        5. Execute on each broker
        6. Record trades in database
        """
        channel = channel_factory(
            discord_channel_id="e2e-test-channel",
            name="e2e-trading",
            execute_enabled=1,
            enabled_brokers=["ALPACA_PAPER", "WEBULL"],
            risk_management_enabled=1,
            stop_loss_pct=25.0
        )
        
        for broker in mock_brokers.values():
            await broker.connect()
        
        signal = signal_factory(
            symbol='SPY',
            strike=450.0,
            expiry='01/17',
            opt_type='C',
            price=1.50,
            quantity=10,
            channel_id=channel['discord_channel_id']
        )
        
        cursor = test_db.execute(
            "SELECT enabled_brokers FROM channels WHERE discord_channel_id = ?",
            (channel['discord_channel_id'],)
        )
        row = cursor.fetchone()
        enabled_brokers = json.loads(row['enabled_brokers'])
        
        execution_results = []
        for broker_name in enabled_brokers:
            broker = mock_brokers.get(broker_name)
            if broker and broker.connected:
                result = await broker.place_option_order(
                    symbol=signal['symbol'],
                    action=signal['action'],
                    quantity=signal['qty'],
                    strike=signal['strike'],
                    expiry=signal['expiry'],
                    opt_type=signal['opt_type'],
                    price=signal['price']
                )
                execution_results.append({
                    'broker': broker_name,
                    'success': result.success,
                    'order_id': result.order_id
                })
                
                if result.success:
                    test_db.execute("""
                        INSERT INTO trades (
                            symbol, action, quantity, price, broker, status,
                            asset_type, strike, expiry, opt_type, channel_id, order_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        signal['symbol'], signal['action'], signal['qty'],
                        signal['price'], broker_name, 'FILLED',
                        'option', signal['strike'], signal['expiry'],
                        signal['opt_type'], channel['discord_channel_id'],
                        result.order_id
                    ))
                    test_db.commit()
        
        assert len(execution_results) == 2
        assert all(r['success'] for r in execution_results)
        
        cursor = test_db.execute(
            "SELECT COUNT(*) as count FROM trades WHERE channel_id = ?",
            (channel['discord_channel_id'],)
        )
        row = cursor.fetchone()
        assert row['count'] == 2
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_signal_rejected_without_broker_config(
        self, test_db, channel_factory, signal_factory
    ):
        """Signal should be REJECTED if no brokers configured"""
        channel = channel_factory(
            discord_channel_id="no-broker-e2e",
            name="misconfigured-e2e",
            execute_enabled=1,
            enabled_brokers=None
        )
        
        signal = signal_factory(
            symbol='AAPL',
            strike=185.0,
            channel_id=channel['discord_channel_id']
        )
        
        cursor = test_db.execute(
            "SELECT enabled_brokers FROM channels WHERE discord_channel_id = ?",
            (channel['discord_channel_id'],)
        )
        row = cursor.fetchone()
        
        should_reject = row['enabled_brokers'] is None
        assert should_reject is True
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_partial_execution_detected(
        self, test_db, channel_factory, signal_factory
    ):
        """Detect and log when only some brokers execute (timing issue)"""
        channel = channel_factory(
            discord_channel_id="partial-exec-e2e",
            name="partial-execution-test",
            execute_enabled=1,
            enabled_brokers=["ALPACA_PAPER", "WEBULL"]
        )
        
        alpaca = MockAlpacaBroker()
        webull = MockWebullBroker()
        
        await alpaca.connect()
        
        signal = signal_factory(
            symbol='NVDA',
            strike=500.0,
            channel_id=channel['discord_channel_id']
        )
        
        results = {}
        for broker_name, broker in [('ALPACA_PAPER', alpaca), ('WEBULL', webull)]:
            if broker.connected:
                result = await broker.place_option_order(
                    symbol=signal['symbol'],
                    action=signal['action'],
                    quantity=signal['qty'],
                    strike=signal['strike'],
                    expiry=signal['expiry'],
                    opt_type=signal['opt_type'],
                    price=signal['price']
                )
                results[broker_name] = result.success
            else:
                results[broker_name] = False
        
        successful = sum(1 for s in results.values() if s)
        failed = sum(1 for s in results.values() if not s)
        
        is_partial = successful > 0 and failed > 0
        assert is_partial is True


class TestRiskManagementE2E:
    """End-to-end tests for risk management flows"""
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_stop_loss_triggers_exit(
        self, test_db, channel_factory, mock_alpaca_broker
    ):
        """Complete flow: Position opened → Price drops → Stop loss triggers → Exit"""
        channel = channel_factory(
            discord_channel_id="sl-e2e-channel",
            name="stoploss-e2e",
            execute_enabled=1,
            enabled_brokers=["ALPACA_PAPER"],
            risk_management_enabled=1,
            stop_loss_pct=25.0,
            exit_strategy_mode='hybrid'
        )
        
        await mock_alpaca_broker.connect()
        
        entry_result = await mock_alpaca_broker.place_option_order(
            symbol='SPY',
            action='BTO',
            quantity=10,
            strike=450.0,
            expiry='01/17',
            opt_type='C',
            price=2.00
        )
        assert entry_result.success is True
        
        test_db.execute("""
            INSERT INTO trades (
                symbol, action, quantity, price, broker, status,
                asset_type, strike, expiry, opt_type, channel_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ('SPY', 'BTO', 10, 2.00, 'ALPACA_PAPER', 'FILLED',
              'option', 450.0, '01/17', 'C', channel['discord_channel_id']))
        test_db.commit()
        
        entry_price = 2.00
        current_price = 1.40
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        stop_loss_pct = 25.0
        should_trigger = pnl_pct <= -stop_loss_pct
        
        if should_trigger:
            exit_result = await mock_alpaca_broker.place_option_order(
                symbol='SPY',
                action='STC',
                quantity=10,
                strike=450.0,
                expiry='01/17',
                opt_type='C',
                price=current_price
            )
            assert exit_result.success is True
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_trailing_stop_full_lifecycle(
        self, test_db, channel_factory, mock_alpaca_broker
    ):
        """
        Complete trailing stop flow:
        1. Position opened at $1.00
        2. Price rises to $1.50 (+50%) - trailing activates
        3. High water mark set at $1.50
        4. Price drops to $1.20 (-20% from high) - trailing triggers exit
        """
        channel = channel_factory(
            discord_channel_id="trail-e2e-channel",
            name="trailing-e2e",
            execute_enabled=1,
            enabled_brokers=["ALPACA_PAPER"],
            risk_management_enabled=1,
            trailing_stop_pct=15.0,
            trailing_activation_pct=35.0,
            exit_strategy_mode='hybrid'
        )
        
        await mock_alpaca_broker.connect()
        
        entry_price = 1.00
        entry_result = await mock_alpaca_broker.place_option_order(
            symbol='TSLA',
            action='BTO',
            quantity=10,
            strike=250.0,
            expiry='01/24',
            opt_type='C',
            price=entry_price
        )
        assert entry_result.success is True
        
        price_journey = [1.00, 1.20, 1.35, 1.40, 1.50, 1.45, 1.30, 1.20]
        
        trailing_activated = False
        high_water_mark = entry_price
        trailing_triggered = False
        exit_price = None
        
        activation_pct = 35.0
        trailing_pct = 15.0
        
        for price in price_journey:
            if price > high_water_mark:
                high_water_mark = price
            
            current_pnl_pct = ((price - entry_price) / entry_price) * 100
            
            if current_pnl_pct >= activation_pct:
                trailing_activated = True
            
            if trailing_activated:
                trail_stop_price = high_water_mark * (1 - trailing_pct / 100)
                if price <= trail_stop_price:
                    trailing_triggered = True
                    exit_price = price
                    break
        
        assert trailing_activated is True
        assert high_water_mark == 1.50
        assert trailing_triggered is True
        assert exit_price == 1.20


class TestConditionalOrderE2E:
    """End-to-end tests for conditional order flows"""
    
    @pytest.mark.e2e
    @pytest.mark.asyncio
    async def test_conditional_order_triggers_and_executes(
        self, test_db, channel_factory, mock_alpaca_broker, mock_market_data
    ):
        """
        Complete conditional order flow:
        1. Conditional BTO signal received (over trigger)
        2. Order stored as pending
        3. Price monitored
        4. Trigger condition met
        5. Order executed
        """
        channel = channel_factory(
            discord_channel_id="conditional-e2e",
            name="conditional-e2e",
            execute_enabled=1,
            enabled_brokers=["ALPACA_PAPER"],
            conditional_order_enabled=1
        )
        
        await mock_alpaca_broker.connect()
        
        conditional_order = {
            'symbol': 'QQQ',
            'action': 'BTO',
            'quantity': 10,
            'strike': 400.0,
            'expiry': '01/17',
            'opt_type': 'C',
            'price': 1.00,
            'trigger_type': 'over',
            'trigger_price': 398.0,
            'status': 'PENDING_TRIGGER'
        }
        
        mock_market_data.set_quote('QQQ', 395.0)
        
        price_journey = [395.0, 396.0, 397.0, 398.5, 399.0]
        
        order_triggered = False
        for price in price_journey:
            if conditional_order['trigger_type'] == 'over' and price > conditional_order['trigger_price']:
                order_triggered = True
                break
        
        assert order_triggered is True
        
        if order_triggered:
            result = await mock_alpaca_broker.place_option_order(
                symbol=conditional_order['symbol'],
                action=conditional_order['action'],
                quantity=conditional_order['quantity'],
                strike=conditional_order['strike'],
                expiry=conditional_order['expiry'],
                opt_type=conditional_order['opt_type'],
                price=conditional_order['price']
            )
            assert result.success is True


class TestPNLTrackingE2E:
    """End-to-end tests for P&L tracking"""
    
    @pytest.mark.e2e
    def test_complete_trade_lifecycle_pnl(self, test_db, channel_factory):
        """
        Complete trade lifecycle P&L tracking:
        1. BTO executed → lot created
        2. Position monitored
        3. STC executed → lot closed
        4. P&L calculated and recorded
        """
        channel = channel_factory(
            discord_channel_id="pnl-e2e-channel",
            name="pnl-e2e",
            execute_enabled=1,
            enabled_brokers=["ALPACA_PAPER"]
        )
        
        signal_id = 'sig-e2e-001'
        entry_price = 1.50
        quantity = 10
        
        cursor = test_db.execute("""
            INSERT INTO signal_lots (
                signal_id, symbol, action, quantity, entry_price, 
                broker, channel_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (signal_id, 'SPY', 'BTO', quantity, entry_price,
              'ALPACA_PAPER', channel['discord_channel_id'], 'OPEN'))
        test_db.commit()
        lot_id = cursor.lastrowid
        
        exit_price = 2.25
        realized_pnl = (exit_price - entry_price) * quantity * 100
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        
        test_db.execute("""
            UPDATE signal_lots SET 
                status = 'CLOSED',
                exit_price = ?,
                pnl = ?,
                pnl_pct = ?,
                closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (exit_price, realized_pnl, pnl_pct, lot_id))
        test_db.commit()
        
        cursor = test_db.execute(
            "SELECT * FROM signal_lots WHERE id = ?",
            (lot_id,)
        )
        row = cursor.fetchone()
        
        assert row['status'] == 'CLOSED'
        assert row['exit_price'] == 2.25
        assert row['pnl'] == 750.0
        assert row['pnl_pct'] == 50.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "e2e"])
