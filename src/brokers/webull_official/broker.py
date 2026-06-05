import asyncio
import logging
import sys
import os
from typing import Optional

from .client import WebullClient
from .config import WebullConfig
from .accounts import AccountsAPI
from .orders import OrdersAPI
from .positions import PositionsAPI
from .streaming import WebullMarketStream, TradeEventPoller
from .models import WebullBalance, WebullPosition, WebullOrder

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from broker_interface import OrderResult

log = logging.getLogger("webull_official")


class WebullOfficialBroker:
    def __init__(self, loop=None, name="WEBULL_OFFICIAL", paper_trade=False, credentials: dict = None):
        self.name = name
        self.loop = loop
        self.paper_trade = paper_trade
        self.connected = False
        self.account_id = ""
        self.account_number = ""
        self.account_type = ""

        self._credentials = credentials or {}
        self._config: Optional[WebullConfig] = None
        self._client: Optional[WebullClient] = None
        self._accounts: Optional[AccountsAPI] = None
        self._orders: Optional[OrdersAPI] = None
        self._positions: Optional[PositionsAPI] = None
        self._stream: Optional[WebullMarketStream] = None
        self._event_poller: Optional[TradeEventPoller] = None

        self._cached_balance: Optional[WebullBalance] = None
        self._cached_positions: list[WebullPosition] = []
        self._accounts_list: list = []

    async def connect(self, app_key: str = None, app_secret: str = None,
                      account_id: str = "", environment: str = "production",
                      account_type: str = ""):
        app_key = app_key or self._credentials.get("app_key", "")
        app_secret = app_secret or self._credentials.get("app_secret", "")
        account_id = account_id or self._credentials.get("account_id", "")
        account_type = account_type or self._credentials.get("account_type", "")

        if not app_key or not app_secret:
            print(f"[{self.name}] ❌ Missing app_key or app_secret")
            return False

        try:
            self._config = WebullConfig(
                app_key=app_key,
                app_secret=app_secret,
                account_id=account_id,
                environment="test" if self.paper_trade else environment,
            )
            self._client = WebullClient(self._config)
            await self._client.start()

            self._accounts = AccountsAPI(self._client)
            self._orders = OrdersAPI(self._client)
            self._positions = PositionsAPI(self._client)

            accounts = await self._accounts.list_accounts()
            if not accounts:
                print(f"[{self.name}] ❌ No accounts found")
                return False

            self._accounts_list = accounts
            for a in accounts:
                print(f"[{self.name}]   Found account: {a.account_id} "
                      f"(type={a.account_type}, class={a.account_class})")

            if account_id:
                matched = [a for a in accounts if a.account_id == account_id]
                if matched:
                    self.account_id = matched[0].account_id
                    self.account_number = matched[0].account_id
                    self.account_type = matched[0].account_type
                else:
                    print(f"[{self.name}] ⚠️ Account {account_id} not found, using first")
                    self.account_id = accounts[0].account_id
                    self.account_number = accounts[0].account_id
                    self.account_type = accounts[0].account_type
            else:
                preferred = account_type.upper() if account_type else ""
                if preferred and preferred != "AUTO":
                    type_map = {
                        "MARGIN": "MARGIN", "CASH": "CASH",
                        "TRADITIONAL IRA": "IRA", "ROTH IRA": "IRA",
                        "ROLLOVER IRA": "IRA",
                    }
                    api_type = type_map.get(preferred, preferred)
                    matched_type = [a for a in accounts if a.account_type == api_type]
                    if preferred in ("TRADITIONAL IRA", "ROTH IRA", "ROLLOVER IRA"):
                        label_key = preferred.lower()
                        matched_type = [a for a in matched_type
                                        if label_key in (a.account_label or "").lower()]
                    target = matched_type[0] if matched_type else accounts[0]
                else:
                    margin_accounts = [a for a in accounts if a.account_type == "MARGIN"]
                    target = margin_accounts[0] if margin_accounts else accounts[0]
                self.account_id = target.account_id
                self.account_number = target.account_id
                self.account_type = target.account_type

            balance = await self._accounts.get_balance(self.account_id)
            self.connected = True
            print(f"[{self.name}] ✅ Connected — Account: {self.account_id}, "
                  f"Balance: ${balance.total_net_liquidation:,.2f}")
            return True

        except Exception as e:
            print(f"[{self.name}] ❌ Connection failed: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        if self._event_poller:
            await self._event_poller.stop()
        if self._stream:
            await self._stream.disconnect()
        if self._client:
            await self._client.close()
        self.connected = False
        print(f"[{self.name}] Disconnected")

    async def get_account_info(self) -> dict:
        if not self.connected:
            return {}
        try:
            balance = await self._accounts.get_balance(self.account_id)
            self._cached_balance = balance
            return {
                "account_id": self.account_id,
                "account_number": self.account_number,
                "account_type": self.account_type,
                "cash_balance": balance.total_cash_balance,
                "buying_power": balance.buying_power,
                "portfolio_value": balance.total_net_liquidation,
                "market_value": balance.total_market_value,
                "unrealized_pnl": balance.total_unrealized_pnl,
                "day_pnl": balance.total_day_pnl,
                "settled_cash": balance.settled_cash,
                "unsettled_cash": balance.unsettled_cash,
                "day_trades_left": balance.day_trades_left,
                "option_buying_power": balance.option_buying_power,
            }
        except Exception as e:
            log.error(f"[{self.name}] get_account_info error: {e}")
            return {}

    async def get_positions(self) -> list:
        if not self.connected:
            return []
        try:
            positions = await self._positions.get_positions(self.account_id)
            self._cached_positions = positions
            return [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_cost": p.cost_price,
                    "current_price": p.last_price,
                    "unrealized_pl": p.unrealized_pnl,
                    "asset": "option" if p.instrument_type == "OPTION" else "stock",
                    "position_id": p.position_id,
                    "option_type": p.option_type,
                    "strike_price": p.strike_price,
                    "expiry_date": p.expiry_date,
                }
                for p in positions
            ]
        except Exception as e:
            log.error(f"[{self.name}] get_positions error: {e}")
            return []

    async def get_positions_detailed(self) -> list:
        return await self.get_positions()

    async def place_stock_order(self, symbol, quantity, action, order_type="MARKET",
                                limit_price=None, stop_price=None, duration="DAY",
                                extended_hours=False) -> OrderResult:
        if not self.connected:
            return OrderResult(success=False, message="Not connected")

        side_map = {
            "BUY": "BUY", "SELL": "SELL", "BTO": "BUY", "STC": "SELL",
            "SHORT": "SHORT", "COVER": "BUY",
        }
        side = side_map.get(action.upper(), action.upper())

        type_map = {
            "MARKET": "MARKET", "LIMIT": "LIMIT",
            "STOP": "STOP_LOSS", "STOP_LIMIT": "STOP_LOSS_LIMIT",
        }
        otype = type_map.get(order_type.upper(), order_type.upper())

        tif_map = {"DAY": "DAY", "GTC": "GTC", "IOC": "IOC"}
        tif = tif_map.get(duration.upper(), "DAY")

        try:
            result = await self._orders.place_stock_order(
                account_id=self.account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=otype,
                limit_price=limit_price,
                stop_price=stop_price,
                time_in_force=tif,
                extended_hours=extended_hours,
            )
            return OrderResult(
                success=True,
                order_id=result.order_id or result.client_order_id,
                message=f"Order placed: {side} {quantity} {symbol}",
                price=limit_price,
                quantity=quantity,
                symbol=symbol,
                action=action,
            )
        except Exception as e:
            return OrderResult(
                success=False,
                message=str(e),
                symbol=symbol,
                action=action,
                quantity=quantity,
            )

    async def place_option_order(self, symbol, quantity, action, order_type="LIMIT",
                                 limit_price=None, option_type=None,
                                 strike_price=None, expiry_date=None,
                                 **kwargs) -> OrderResult:
        if not self.connected:
            return OrderResult(success=False, message="Not connected")

        intent_map = {
            "BTO": "BUY_TO_OPEN", "STC": "SELL_TO_CLOSE",
            "STO": "SELL_TO_OPEN", "BTC": "BUY_TO_CLOSE",
        }
        position_intent = intent_map.get(action.upper(), "BUY_TO_OPEN")

        side = "BUY" if action.upper() in ("BTO", "BTC") else "SELL"
        otype = "CALL" if option_type and option_type.upper().startswith("C") else "PUT"

        try:
            result = await self._orders.place_option_order(
                account_id=self.account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                option_type=otype,
                strike_price=strike_price,
                expiry_date=expiry_date,
                position_intent=position_intent,
                order_type=order_type.upper(),
                limit_price=limit_price,
            )
            return OrderResult(
                success=True,
                order_id=result.order_id or result.client_order_id,
                message=f"Option order placed: {action} {quantity}x {symbol}",
                price=limit_price,
                quantity=quantity,
                symbol=symbol,
                action=action,
            )
        except Exception as e:
            return OrderResult(
                success=False,
                message=str(e),
                symbol=symbol,
                action=action,
                quantity=quantity,
            )

    async def get_quote(self, symbol) -> dict:
        return {"symbol": symbol, "last": 0.0, "bid": 0.0, "ask": 0.0}

    async def place_bracket_order(self, symbol, quantity, side, order_type="MARKET",
                                  limit_price=None, take_profit=None, stop_loss=None,
                                  extended_hours=False) -> OrderResult:
        if not self.connected:
            return OrderResult(success=False, message="Not connected")

        try:
            result = await self._orders.place_bracket_order(
                account_id=self.account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                take_profit_price=take_profit,
                stop_loss_price=stop_loss,
                extended_hours=extended_hours,
            )
            return OrderResult(
                success=True,
                order_id=result.combo_order_id or result.client_combo_order_id,
                message=f"Bracket order placed: {side} {quantity} {symbol} "
                        f"TP={take_profit} SL={stop_loss}",
                quantity=quantity,
                symbol=symbol,
                action=side,
            )
        except Exception as e:
            return OrderResult(success=False, message=str(e), symbol=symbol)

    async def cancel_order(self, client_order_id: str) -> dict:
        try:
            result = await self._orders.cancel_order(self.account_id, client_order_id)
            return {"success": True, "data": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def cancel_order_by_id(self, client_order_id: str) -> bool:
        try:
            await self._orders.cancel_order(self.account_id, client_order_id)
            return True
        except Exception as e:
            print(f"[{self.name}] Cancel failed: {e}")
            return False

    async def get_pending_orders(self) -> list:
        if not self.connected:
            return []
        try:
            orders = await self._orders.get_open_orders(self.account_id)
            return [
                {
                    "order_id": o.client_order_id,
                    "broker_order_id": o.order_id,
                    "symbol": o.symbol,
                    "quantity": o.quantity,
                    "filled_quantity": o.filled_quantity,
                    "limit_price": o.limit_price,
                    "stop_price": o.stop_price,
                    "action": o.side,
                    "status": o.status,
                    "order_type": o.order_type,
                    "combo_type": o.combo_type,
                }
                for o in orders
            ]
        except Exception as e:
            log.error(f"[{self.name}] get_pending_orders error: {e}")
            return []

    async def get_order_history(self, start_date: str = None, end_date: str = None) -> list:
        if not self.connected:
            return []
        try:
            orders = await self._orders.get_order_history(
                self.account_id, start_date=start_date, end_date=end_date
            )
            return [
                {
                    "order_id": o.client_order_id,
                    "broker_order_id": o.order_id,
                    "symbol": o.symbol,
                    "quantity": o.quantity,
                    "filled_quantity": o.filled_quantity,
                    "filled_price": o.filled_price,
                    "action": o.side,
                    "status": o.status,
                    "order_type": o.order_type,
                    "place_time": o.place_time,
                    "filled_time": o.filled_time,
                }
                for o in orders
            ]
        except Exception as e:
            log.error(f"[{self.name}] get_order_history error: {e}")
            return []

    async def start_streaming(self, symbols: list[str] = None):
        if not self._stream:
            self._stream = WebullMarketStream(self._config, self._client)

        connected = await self._stream.connect()
        if connected and symbols:
            await self._stream.subscribe(symbols)

        if not self._event_poller:
            self._event_poller = TradeEventPoller(self._client, self.account_id)
            await self._event_poller.start()

    def get_accounts_list(self) -> list[dict]:
        return [
            {
                "account_id": a.account_id,
                "account_type": a.account_type,
                "account_class": a.account_class,
                "account_label": a.account_label,
            }
            for a in self._accounts_list
        ]

    def is_authenticated(self) -> bool:
        return self.connected
