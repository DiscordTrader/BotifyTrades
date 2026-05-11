"""
QA Gate 2: Webull Official Trading Operations Tests
Tests: account queries, order placement, position fetching, broker interface
"""
import asyncio
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def _run(coro):
    return asyncio.run(coro)


class TestAccountsAPI:
    def test_list_accounts_parses_response(self):
        from brokers.webull_official.accounts import AccountsAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.get.return_value = [
                {"account_id": "ACC001", "account_type": "MARGIN",
                 "account_class": "INDIVIDUAL_MARGIN", "account_label": "Individual Margin",
                 "user_id": "U001"},
                {"account_id": "ACC002", "account_type": "CASH",
                 "account_class": "ROTH_IRA", "account_label": "Roth IRA",
                 "user_id": "U001"},
            ]
            api = AccountsAPI(mock_client)
            accounts = await api.list_accounts()
            assert len(accounts) == 2
            assert accounts[0].account_id == "ACC001"
            assert accounts[0].account_type == "MARGIN"
            assert accounts[1].account_class == "ROTH_IRA"

        _run(_test())

    def test_get_balance_calls_correct_endpoint(self):
        from brokers.webull_official.accounts import AccountsAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.get.return_value = {
                "total_cash_balance": "10000", "total_market_value": "50000",
                "total_unrealized_profit_loss": "0", "total_net_liquidation_value": "60000",
                "total_day_profit_loss": "0",
                "account_currency_assets": [{"buying_power": "20000"}]
            }
            api = AccountsAPI(mock_client)
            balance = await api.get_balance("ACC001")
            mock_client.get.assert_called_with(
                "/openapi/assets/balance", params={"account_id": "ACC001"},
            )
            assert balance.total_net_liquidation == 60000.0

        _run(_test())

    def test_list_accounts_handles_wrapped_response(self):
        from brokers.webull_official.accounts import AccountsAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.get.return_value = {
                "accounts": [{"account_id": "A1", "account_type": "CASH",
                              "account_class": "INDIVIDUAL_CASH", "account_label": "Cash"}]
            }
            api = AccountsAPI(mock_client)
            accounts = await api.list_accounts()
            assert len(accounts) == 1
            assert accounts[0].account_id == "A1"

        _run(_test())


class TestOrdersAPI:
    def test_place_stock_market_order(self):
        from brokers.webull_official.orders import OrdersAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.post.return_value = {"client_order_id": "test123", "order_id": "WB456"}
            api = OrdersAPI(mock_client)
            result = await api.place_stock_order(
                account_id="ACC001", symbol="AAPL", side="BUY",
                quantity=10, order_type="MARKET",
            )
            assert result.client_order_id == "test123"
            assert result.order_id == "WB456"
            call_body = mock_client.post.call_args[0][1]
            assert call_body["account_id"] == "ACC001"
            order = call_body["new_orders"][0]
            assert order["symbol"] == "AAPL"
            assert order["side"] == "BUY"
            assert order["order_type"] == "MARKET"
            assert order["instrument_type"] == "EQUITY"
            assert order["combo_type"] == "NORMAL"
            assert order["entrust_type"] == "QTY"
            assert order["market"] == "US"

        _run(_test())

    def test_place_stock_limit_order_with_price(self):
        from brokers.webull_official.orders import OrdersAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.post.return_value = {"client_order_id": "lim1", "order_id": "WB789"}
            api = OrdersAPI(mock_client)
            await api.place_stock_order(
                account_id="ACC001", symbol="TSLA", side="SELL",
                quantity=5, order_type="LIMIT", limit_price=250.50,
            )
            call_body = mock_client.post.call_args[0][1]
            order = call_body["new_orders"][0]
            assert order["order_type"] == "LIMIT"
            assert order["limit_price"] == "250.5"

        _run(_test())

    def test_place_option_order_has_legs(self):
        from brokers.webull_official.orders import OrdersAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.post.return_value = {"client_order_id": "opt1", "order_id": "WB999"}
            api = OrdersAPI(mock_client)
            await api.place_option_order(
                account_id="ACC001", symbol="AAPL", side="BUY",
                quantity=2, option_type="CALL", strike_price=180.0,
                expiry_date="2026-06-20", position_intent="BUY_TO_OPEN",
                order_type="LIMIT", limit_price=5.50,
            )
            call_body = mock_client.post.call_args[0][1]
            order = call_body["new_orders"][0]
            assert order["instrument_type"] == "OPTION"
            assert order["option_strategy"] == "SINGLE"
            assert order["position_intent"] == "BUY_TO_OPEN"
            assert len(order["legs"]) == 1
            leg = order["legs"][0]
            assert leg["strike_price"] == "180.0"
            assert leg["option_expire_date"] == "2026-06-20"
            assert leg["option_type"] == "CALL"

        _run(_test())

    def test_place_bracket_order_has_three_legs(self):
        from brokers.webull_official.orders import OrdersAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.post.return_value = {"combo_order_id": "combo1", "client_order_id": ""}
            api = OrdersAPI(mock_client)
            await api.place_bracket_order(
                account_id="ACC001", symbol="AAPL", side="BUY",
                quantity=10, order_type="LIMIT", limit_price=150.0,
                take_profit_price=165.0, stop_loss_price=140.0,
            )
            call_body = mock_client.post.call_args[0][1]
            orders = call_body["new_orders"]
            assert len(orders) == 3
            combo_types = [o["combo_type"] for o in orders]
            assert "MASTER" in combo_types
            assert "STOP_PROFIT" in combo_types
            assert "STOP_LOSS" in combo_types
            master = [o for o in orders if o["combo_type"] == "MASTER"][0]
            assert master["side"] == "BUY"
            tp = [o for o in orders if o["combo_type"] == "STOP_PROFIT"][0]
            assert tp["side"] == "SELL"
            assert tp["limit_price"] == "165.0"
            sl = [o for o in orders if o["combo_type"] == "STOP_LOSS"][0]
            assert sl["side"] == "SELL"
            assert sl["stop_price"] == "140.0"

        _run(_test())

    def test_bracket_exit_side_flips_for_short(self):
        from brokers.webull_official.orders import OrdersAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.post.return_value = {"combo_order_id": "c2"}
            api = OrdersAPI(mock_client)
            await api.place_bracket_order(
                account_id="ACC001", symbol="SPY", side="SHORT",
                quantity=50, take_profit_price=400.0, stop_loss_price=460.0,
            )
            call_body = mock_client.post.call_args[0][1]
            orders = call_body["new_orders"]
            tp = [o for o in orders if o["combo_type"] == "STOP_PROFIT"][0]
            assert tp["side"] == "BUY"
            sl = [o for o in orders if o["combo_type"] == "STOP_LOSS"][0]
            assert sl["side"] == "BUY"

        _run(_test())

    def test_cancel_order_sends_client_order_id(self):
        from brokers.webull_official.orders import OrdersAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.post.return_value = {}
            api = OrdersAPI(mock_client)
            await api.cancel_order("ACC001", "my_order_123")
            call_body = mock_client.post.call_args[0][1]
            assert call_body["account_id"] == "ACC001"
            assert call_body["client_order_id"] == "my_order_123"

        _run(_test())

    def test_replace_order_only_sends_changed_fields(self):
        from brokers.webull_official.orders import OrdersAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.post.return_value = {}
            api = OrdersAPI(mock_client)
            await api.replace_order("ACC001", "ord1", limit_price=155.0)
            call_body = mock_client.post.call_args[0][1]
            modify = call_body["modify_orders"][0]
            assert modify["client_order_id"] == "ord1"
            assert modify["limit_price"] == "155.0"
            assert "quantity" not in modify
            assert "stop_price" not in modify

        _run(_test())

    def test_trailing_stop_order(self):
        from brokers.webull_official.orders import OrdersAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.post.return_value = {"client_order_id": "ts1", "order_id": "WB_TS"}
            api = OrdersAPI(mock_client)
            await api.place_trailing_stop(
                account_id="ACC001", symbol="AAPL", side="SELL",
                quantity=10, trailing_type="PERCENTAGE", trailing_stop_step=0.05,
            )
            call_body = mock_client.post.call_args[0][1]
            order = call_body["new_orders"][0]
            assert order["order_type"] == "TRAILING_STOP_LOSS"
            assert order["trailing_type"] == "PERCENTAGE"
            assert order["trailing_stop_step"] == "0.05"

        _run(_test())

    def test_client_order_id_max_32_chars(self):
        from brokers.webull_official.orders import OrdersAPI
        api = OrdersAPI(MagicMock())
        coid = api._gen_client_order_id()
        assert len(coid) <= 32
        assert len(coid) > 0

    def test_extended_hours_sets_all_session(self):
        from brokers.webull_official.orders import OrdersAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.post.return_value = {"client_order_id": "eh1", "order_id": "WB_EH"}
            api = OrdersAPI(mock_client)
            await api.place_stock_order(
                account_id="ACC001", symbol="AAPL", side="BUY",
                quantity=10, extended_hours=True,
            )
            order = mock_client.post.call_args[0][1]["new_orders"][0]
            assert order["support_trading_session"] == "ALL"

        _run(_test())

    def test_regular_hours_sets_core_session(self):
        from brokers.webull_official.orders import OrdersAPI

        async def _test():
            mock_client = AsyncMock()
            mock_client.post.return_value = {"client_order_id": "rh1", "order_id": "WB_RH"}
            api = OrdersAPI(mock_client)
            await api.place_stock_order(
                account_id="ACC001", symbol="AAPL", side="BUY",
                quantity=10, extended_hours=False,
            )
            order = mock_client.post.call_args[0][1]["new_orders"][0]
            assert order["support_trading_session"] == "CORE"

        _run(_test())


class TestBrokerInterface:
    def test_get_account_info_returns_expected_keys(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.models import WebullBalance

        async def _test():
            broker = WebullOfficialBroker(name="TEST")
            broker.connected = True
            broker.account_id = "ACC001"
            mock_accounts = AsyncMock()
            mock_accounts.get_balance.return_value = WebullBalance(
                total_cash_balance=10000, total_market_value=50000,
                total_unrealized_pnl=500, total_net_liquidation=60000,
                total_day_pnl=-100, buying_power=20000,
                settled_cash=8000, unsettled_cash=2000,
                day_trades_left="3", option_buying_power=15000,
            )
            broker._accounts = mock_accounts
            info = await broker.get_account_info()
            required_keys = [
                "account_id", "cash_balance", "buying_power",
                "portfolio_value", "market_value", "unrealized_pnl", "day_pnl",
            ]
            for key in required_keys:
                assert key in info, f"Missing key: {key}"
            assert info["buying_power"] == 20000
            assert info["portfolio_value"] == 60000

        _run(_test())

    def test_get_positions_returns_list_of_dicts(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.models import WebullPosition

        async def _test():
            broker = WebullOfficialBroker(name="TEST")
            broker.connected = True
            broker.account_id = "ACC001"
            mock_positions = AsyncMock()
            mock_positions.get_positions.return_value = [
                WebullPosition(
                    position_id="P1", symbol="AAPL", quantity=100,
                    cost_price=150, last_price=155, unrealized_pnl=500,
                    instrument_type="EQUITY",
                )
            ]
            broker._positions = mock_positions
            positions = await broker.get_positions()
            assert len(positions) == 1
            pos = positions[0]
            assert pos["symbol"] == "AAPL"
            assert pos["quantity"] == 100
            assert pos["avg_cost"] == 150
            assert pos["current_price"] == 155
            assert pos["unrealized_pl"] == 500
            assert pos["asset"] == "stock"

        _run(_test())

    def test_option_position_marked_as_option(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.models import WebullPosition

        async def _test():
            broker = WebullOfficialBroker(name="TEST")
            broker.connected = True
            broker.account_id = "ACC001"
            mock_positions = AsyncMock()
            mock_positions.get_positions.return_value = [
                WebullPosition(
                    position_id="P2", symbol="AAPL", quantity=5,
                    cost_price=3.5, last_price=5.2, unrealized_pnl=850,
                    instrument_type="OPTION", option_type="CALL",
                    strike_price=180, expiry_date="2026-06-20",
                )
            ]
            broker._positions = mock_positions
            positions = await broker.get_positions()
            pos = positions[0]
            assert pos["asset"] == "option"
            assert pos["option_type"] == "CALL"
            assert pos["strike_price"] == 180

        _run(_test())

    def test_place_stock_order_action_mapping(self):
        from brokers.webull_official.broker import WebullOfficialBroker

        async def _test():
            broker = WebullOfficialBroker(name="TEST")
            broker.connected = True
            broker.account_id = "ACC001"
            mock_orders = AsyncMock()
            mock_orders.place_stock_order.return_value = MagicMock(
                client_order_id="c1", order_id="o1"
            )
            broker._orders = mock_orders
            mappings = {
                "BTO": "BUY", "STC": "SELL", "BUY": "BUY",
                "SELL": "SELL", "SHORT": "SHORT", "COVER": "BUY",
            }
            for action, expected_side in mappings.items():
                await broker.place_stock_order("AAPL", 10, action)
                call_kwargs = mock_orders.place_stock_order.call_args[1]
                assert call_kwargs["side"] == expected_side, \
                    f"Action {action} should map to side {expected_side}"

        _run(_test())

    def test_place_stock_order_type_mapping(self):
        from brokers.webull_official.broker import WebullOfficialBroker

        async def _test():
            broker = WebullOfficialBroker(name="TEST")
            broker.connected = True
            broker.account_id = "ACC001"
            mock_orders = AsyncMock()
            mock_orders.place_stock_order.return_value = MagicMock(
                client_order_id="c1", order_id="o1"
            )
            broker._orders = mock_orders
            mappings = {
                "MARKET": "MARKET", "LIMIT": "LIMIT",
                "STOP": "STOP_LOSS", "STOP_LIMIT": "STOP_LOSS_LIMIT",
            }
            for bot_type, api_type in mappings.items():
                await broker.place_stock_order("AAPL", 10, "BUY", order_type=bot_type, limit_price=150)
                call_kwargs = mock_orders.place_stock_order.call_args[1]
                assert call_kwargs["order_type"] == api_type

        _run(_test())

    def test_place_option_order_intent_mapping(self):
        from brokers.webull_official.broker import WebullOfficialBroker

        async def _test():
            broker = WebullOfficialBroker(name="TEST")
            broker.connected = True
            broker.account_id = "ACC001"
            mock_orders = AsyncMock()
            mock_orders.place_option_order.return_value = MagicMock(
                client_order_id="c1", order_id="o1"
            )
            broker._orders = mock_orders
            mappings = {
                "BTO": "BUY_TO_OPEN", "STC": "SELL_TO_CLOSE",
                "STO": "SELL_TO_OPEN", "BTC": "BUY_TO_CLOSE",
            }
            for action, expected_intent in mappings.items():
                await broker.place_option_order(
                    "AAPL", 1, action, limit_price=5.0,
                    option_type="CALL", strike_price=180, expiry_date="2026-06-20"
                )
                call_kwargs = mock_orders.place_option_order.call_args[1]
                assert call_kwargs["position_intent"] == expected_intent

        _run(_test())

    def test_disconnected_broker_returns_failure(self):
        from brokers.webull_official.broker import WebullOfficialBroker

        async def _test():
            broker = WebullOfficialBroker(name="TEST")
            broker.connected = False
            result = await broker.place_stock_order("AAPL", 10, "BUY")
            assert result.success is False
            assert "Not connected" in result.message
            positions = await broker.get_positions()
            assert positions == []
            info = await broker.get_account_info()
            assert info == {}

        _run(_test())

    def test_order_error_returns_failure_with_message(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.exceptions import WebullOrderError

        async def _test():
            broker = WebullOfficialBroker(name="TEST")
            broker.connected = True
            broker.account_id = "ACC001"
            mock_orders = AsyncMock()
            mock_orders.place_stock_order.side_effect = WebullOrderError(
                417, "INVALID_PARAMETER", "Quantity must be positive"
            )
            broker._orders = mock_orders
            result = await broker.place_stock_order("AAPL", -1, "BUY")
            assert result.success is False
            assert "Quantity" in result.message or "INVALID" in result.message

        _run(_test())

    def test_get_pending_orders_returns_expected_format(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.models import WebullOrder

        async def _test():
            broker = WebullOfficialBroker(name="TEST")
            broker.connected = True
            broker.account_id = "ACC001"
            mock_orders = AsyncMock()
            mock_orders.get_open_orders.return_value = [
                WebullOrder(
                    client_order_id="c1", order_id="wb1", symbol="AAPL",
                    side="BUY", status="SUBMITTED", order_type="LIMIT",
                    instrument_type="EQUITY", quantity=10, filled_quantity=0,
                    filled_price=0, limit_price=150.0,
                )
            ]
            broker._orders = mock_orders
            orders = await broker.get_pending_orders()
            assert len(orders) == 1
            o = orders[0]
            assert o["order_id"] == "c1"
            assert o["broker_order_id"] == "wb1"
            assert o["symbol"] == "AAPL"
            assert o["status"] == "SUBMITTED"

        _run(_test())


class TestClientResponseHandling:
    def test_401_raises_auth_error(self):
        from brokers.webull_official.client import WebullClient
        from brokers.webull_official.config import WebullConfig
        from brokers.webull_official.exceptions import WebullAuthError

        config = WebullConfig(app_key="k", app_secret="s")
        client = WebullClient(config)
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "error_code": "UNAUTHORIZED", "message": "Insufficient permission"
        }
        with pytest.raises(WebullAuthError) as exc_info:
            client._handle_response(mock_response, "/test")
        assert exc_info.value.status_code == 401

    def test_417_on_order_raises_order_error(self):
        from brokers.webull_official.client import WebullClient
        from brokers.webull_official.config import WebullConfig
        from brokers.webull_official.exceptions import WebullOrderError

        config = WebullConfig(app_key="k", app_secret="s")
        client = WebullClient(config)
        mock_response = MagicMock()
        mock_response.status_code = 417
        mock_response.json.return_value = {
            "error_code": "INVALID_PARAMETER", "message": "Bad qty"
        }
        with pytest.raises(WebullOrderError):
            client._handle_response(mock_response, "/openapi/trade/order/place")

    def test_200_returns_json(self):
        from brokers.webull_official.client import WebullClient
        from brokers.webull_official.config import WebullConfig

        config = WebullConfig(app_key="k", app_secret="s")
        client = WebullClient(config)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"ok": true}'
        mock_response.json.return_value = {"ok": True}
        result = client._handle_response(mock_response, "/test")
        assert result == {"ok": True}

    def test_200_empty_body_returns_empty_dict(self):
        from brokers.webull_official.client import WebullClient
        from brokers.webull_official.config import WebullConfig

        config = WebullConfig(app_key="k", app_secret="s")
        client = WebullClient(config)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b''
        result = client._handle_response(mock_response, "/test")
        assert result == {}

    def test_end_to_end_stock_order_lifecycle(self):
        from brokers.webull_official.broker import WebullOfficialBroker
        from brokers.webull_official.models import WebullOrder

        async def _test():
            broker = WebullOfficialBroker(name="TEST")
            broker.connected = True
            broker.account_id = "ACC001"
            mock_orders = AsyncMock()
            mock_orders.place_stock_order.return_value = MagicMock(
                client_order_id="lifecycle_1", order_id="WB_LT1",
            )
            broker._orders = mock_orders
            result = await broker.place_stock_order("AAPL", 10, "BUY", "LIMIT", limit_price=150)
            assert result.success is True
            mock_orders.get_open_orders.return_value = [
                WebullOrder(
                    client_order_id="lifecycle_1", order_id="WB_LT1",
                    symbol="AAPL", side="BUY", status="SUBMITTED",
                    order_type="LIMIT", instrument_type="EQUITY",
                    quantity=10, filled_quantity=0, filled_price=0,
                    limit_price=150.0,
                )
            ]
            pending = await broker.get_pending_orders()
            assert len(pending) == 1
            assert pending[0]["status"] == "SUBMITTED"
            mock_orders.cancel_order.return_value = {}
            cancelled = await broker.cancel_order_by_id("lifecycle_1")
            assert cancelled is True
            mock_orders.cancel_order.assert_called_with("ACC001", "lifecycle_1")

        _run(_test())
