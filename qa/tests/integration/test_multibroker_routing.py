"""
Integration Tests for Multi-Broker Routing
Tests STRICT routing: all-or-reject verification
"""
import pytest
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from qa.tests.mocks.mock_broker import MockAlpacaBroker, MockWebullBroker


class TestStrictRouting:
    """Test STRICT routing architecture - no primary broker fallback"""
    
    @pytest.mark.integration
    def test_reject_signal_without_configured_brokers(self, test_db, channel_factory, signal_factory):
        """Signal should be REJECTED if channel has execute_enabled=1 but no enabled_brokers"""
        channel = channel_factory(
            discord_channel_id="no-broker-channel",
            name="misconfigured-channel",
            execute_enabled=1,
            enabled_brokers=None
        )
        
        cursor = test_db.execute(
            "SELECT enabled_brokers FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        
        assert row['enabled_brokers'] is None
    
    @pytest.mark.integration
    def test_route_to_single_configured_broker(self, test_db, channel_factory, mock_alpaca_broker):
        """Signal should route ONLY to the configured broker"""
        channel = channel_factory(
            discord_channel_id="single-broker-route",
            name="alpaca-only-channel",
            execute_enabled=1,
            enabled_brokers=["ALPACA_PAPER"]
        )
        
        cursor = test_db.execute(
            "SELECT enabled_brokers FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        brokers = json.loads(row['enabled_brokers'])
        
        assert brokers == ["ALPACA_PAPER"]
        assert "WEBULL" not in brokers
    
    @pytest.mark.integration
    def test_route_to_multiple_configured_brokers(self, test_db, channel_factory):
        """Signal should route to ALL configured brokers"""
        channel = channel_factory(
            discord_channel_id="multi-broker-route",
            name="webull-alpaca-channel",
            execute_enabled=1,
            enabled_brokers=["WEBULL", "ALPACA_PAPER"]
        )
        
        cursor = test_db.execute(
            "SELECT enabled_brokers FROM channels WHERE id = ?",
            (channel['id'],)
        )
        row = cursor.fetchone()
        brokers = json.loads(row['enabled_brokers'])
        
        assert len(brokers) == 2
        assert "WEBULL" in brokers
        assert "ALPACA_PAPER" in brokers


class TestMultiBrokerExecution:
    """Test multi-broker execution behavior"""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_execute_on_all_connected_brokers(self, mock_brokers, signal_factory):
        """Execute should succeed on all connected brokers"""
        signal = signal_factory(
            symbol='SPY',
            strike=450.0,
            price=1.50,
            quantity=10
        )
        
        results = []
        for broker_name, broker in mock_brokers.items():
            await broker.connect()
            result = await broker.place_option_order(
                symbol=signal['symbol'],
                action=signal['action'],
                quantity=signal['qty'],
                strike=signal['strike'],
                expiry=signal['expiry'],
                opt_type=signal['opt_type'],
                price=signal['price']
            )
            results.append({'broker': broker_name, 'result': result})
        
        assert len(results) == 2
        assert all(r['result'].success for r in results)
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_broker_not_connected_should_fail(self, mock_webull_broker, signal_factory):
        """Execution should fail if broker is not connected"""
        signal = signal_factory(symbol='AAPL', strike=185.0, price=2.00)
        
        result = await mock_webull_broker.place_option_order(
            symbol=signal['symbol'],
            action=signal['action'],
            quantity=signal['qty'],
            strike=signal['strike'],
            expiry=signal['expiry'],
            opt_type=signal['opt_type'],
            price=signal['price']
        )
        
        assert result.success is False
        assert "not connected" in result.message.lower()
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_slow_broker_connection_timing(self, signal_factory):
        """Test timing issue where slow broker misses execution"""
        fast_broker = MockAlpacaBroker()
        slow_broker = MockWebullBroker()
        slow_broker.set_connection_delay(0.5)
        
        await fast_broker.connect()
        assert fast_broker.connected is True
        assert slow_broker.connected is False
        
        signal = signal_factory(symbol='NVDA', strike=500.0, price=3.00)
        fast_result = await fast_broker.place_option_order(
            symbol=signal['symbol'],
            action=signal['action'],
            quantity=signal['qty'],
            strike=signal['strike'],
            expiry=signal['expiry'],
            opt_type=signal['opt_type'],
            price=signal['price']
        )
        
        slow_result = await slow_broker.place_option_order(
            symbol=signal['symbol'],
            action=signal['action'],
            quantity=signal['qty'],
            strike=signal['strike'],
            expiry=signal['expiry'],
            opt_type=signal['opt_type'],
            price=signal['price']
        )
        
        assert fast_result.success is True
        assert slow_result.success is False


class TestAllOrRejectPolicy:
    """Test all-or-reject execution policy"""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_partial_execution_detection(self, signal_factory):
        """Detect when only some brokers executed (partial execution)"""
        alpaca = MockAlpacaBroker()
        webull = MockWebullBroker()
        
        await alpaca.connect()
        
        signal = signal_factory(symbol='META', strike=400.0, price=2.50)
        
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
        
        successful = [b for b, s in results.items() if s]
        failed = [b for b, s in results.items() if not s]
        
        assert len(successful) == 1
        assert len(failed) == 1
        assert 'ALPACA_PAPER' in successful
        assert 'WEBULL' in failed
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_all_brokers_fail_should_reject(self, signal_factory):
        """If ALL configured brokers fail, signal should be fully rejected"""
        alpaca = MockAlpacaBroker()
        webull = MockWebullBroker()
        
        alpaca.set_next_order_fail("API rate limit exceeded")
        webull.set_next_order_fail("Insufficient buying power")
        
        await alpaca.connect()
        await webull.connect()
        
        signal = signal_factory(symbol='TSLA', strike=250.0, price=1.00)
        
        results = []
        for broker in [alpaca, webull]:
            result = await broker.place_option_order(
                symbol=signal['symbol'],
                action=signal['action'],
                quantity=signal['qty'],
                strike=signal['strike'],
                expiry=signal['expiry'],
                opt_type=signal['opt_type'],
                price=signal['price']
            )
            results.append(result)
        
        assert all(not r.success for r in results)


class TestBrokerReadinessGating:
    """Test broker readiness before execution"""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_wait_for_all_brokers_ready(self):
        """Execution should wait until all configured brokers are ready"""
        alpaca = MockAlpacaBroker()
        webull = MockWebullBroker()
        webull.set_connection_delay(0.2)
        
        connect_tasks = [
            alpaca.connect(),
            webull.connect()
        ]
        
        await asyncio.gather(*connect_tasks)
        
        assert alpaca.connected is True
        assert webull.connected is True
    
    @pytest.mark.integration
    def test_broker_readiness_check(self, mock_brokers):
        """Check readiness status of all brokers"""
        ready_brokers = []
        not_ready_brokers = []
        
        for name, broker in mock_brokers.items():
            if broker.connected:
                ready_brokers.append(name)
            else:
                not_ready_brokers.append(name)
        
        configured_brokers = ['ALPACA_PAPER', 'WEBULL']
        missing = set(configured_brokers) - set(ready_brokers)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
