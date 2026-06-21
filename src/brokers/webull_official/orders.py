import uuid
from .client import WebullClient
from .models import WebullOrder, PlaceOrderResult


class OrdersAPI:
    def __init__(self, client: WebullClient):
        self._client = client

    def _gen_client_order_id(self) -> str:
        return uuid.uuid4().hex[:32]

    async def place_stock_order(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        limit_price: float = None,
        stop_price: float = None,
        time_in_force: str = "DAY",
        extended_hours: bool = False,
        client_order_id: str = None,
        total_cash_amount: float = None,
    ) -> PlaceOrderResult:
        # Fractional shares: use entrust_type=AMOUNT with total_cash_amount instead of quantity
        _entrust = "AMOUNT" if total_cash_amount is not None else "QTY"
        order = {
            "client_order_id": client_order_id or self._gen_client_order_id(),
            "combo_type": "NORMAL",
            "instrument_type": "EQUITY",
            "entrust_type": _entrust,
            "symbol": symbol,
            "market": "US",
            "side": side,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "support_trading_session": "ALL" if extended_hours else "CORE",
        }
        if total_cash_amount is not None:
            order["total_cash_amount"] = str(total_cash_amount)
        else:
            order["quantity"] = str(quantity)
        if limit_price is not None:
            order["limit_price"] = str(limit_price)
        if stop_price is not None:
            order["stop_price"] = str(stop_price)

        body = {"account_id": account_id, "new_orders": [order]}
        data = await self._client.post("/openapi/trade/order/place", body)

        return PlaceOrderResult(
            client_order_id=data.get("client_order_id", order["client_order_id"]),
            order_id=data.get("order_id", ""),
            combo_order_id=data.get("combo_order_id", ""),
        )

    async def place_option_order(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: int,
        option_type: str,
        strike_price: float,
        expiry_date: str,
        position_intent: str = None,
        order_type: str = "LIMIT",
        limit_price: float = None,
        stop_price: float = None,
        time_in_force: str = "DAY",
        client_order_id: str = None,
    ) -> PlaceOrderResult:
        quantity = int(quantity)
        coid = client_order_id or self._gen_client_order_id()
        _close_intents = {"SELL_TO_CLOSE", "BUY_TO_CLOSE"}
        position_effect = "CLOSE" if position_intent in _close_intents else "OPEN"
        order = {
            "client_order_id": coid,
            "combo_type": "NORMAL",
            "instrument_type": "OPTION",
            "option_strategy": "SINGLE",
            "entrust_type": "QTY",
            "symbol": symbol,
            "market": "US",
            "side": side,
            "order_type": order_type,
            "time_in_force": time_in_force,
            "quantity": str(quantity),
            "position_intent": position_intent or ("SELL_TO_CLOSE" if side == "SELL" else "BUY_TO_OPEN"),
            "legs": [{
                "side": side,
                "quantity": str(quantity),
                "symbol": symbol,
                "market": "US",
                "instrument_type": "OPTION",
                "strike_price": str(strike_price),
                "option_expire_date": expiry_date,
                "option_type": option_type,
                "position_effect": position_effect,
            }],
        }
        if limit_price is not None:
            order["limit_price"] = str(limit_price)
        if stop_price is not None:
            order["stop_price"] = str(stop_price)

        body = {"account_id": account_id, "new_orders": [order]}
        data = await self._client.post("/openapi/trade/order/place", body)

        return PlaceOrderResult(
            client_order_id=data.get("client_order_id", coid),
            order_id=data.get("order_id", ""),
        )

    async def place_bracket_order(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        limit_price: float = None,
        take_profit_price: float = None,
        stop_loss_price: float = None,
        extended_hours: bool = False,
        client_order_id: str = None,
    ) -> PlaceOrderResult:
        combo_id = client_order_id or self._gen_client_order_id()
        exit_side = "SELL" if side == "BUY" else "BUY"

        master = {
            "client_order_id": self._gen_client_order_id(),
            "combo_type": "MASTER",
            "instrument_type": "EQUITY",
            "entrust_type": "QTY",
            "symbol": symbol,
            "market": "US",
            "side": side,
            "order_type": order_type,
            "time_in_force": "GTC" if extended_hours else "DAY",
            "quantity": str(quantity),
            "support_trading_session": "CORE",
        }
        if limit_price is not None:
            master["limit_price"] = str(limit_price)

        orders = [master]

        if take_profit_price is not None:
            orders.append({
                "client_order_id": self._gen_client_order_id(),
                "combo_type": "STOP_PROFIT",
                "instrument_type": "EQUITY",
                "entrust_type": "QTY",
                "symbol": symbol,
                "market": "US",
                "side": exit_side,
                "order_type": "LIMIT",
                "time_in_force": "GTC",
                "quantity": str(quantity),
                "limit_price": str(take_profit_price),
                "support_trading_session": "CORE",
            })

        if stop_loss_price is not None:
            orders.append({
                "client_order_id": self._gen_client_order_id(),
                "combo_type": "STOP_LOSS",
                "instrument_type": "EQUITY",
                "entrust_type": "QTY",
                "symbol": symbol,
                "market": "US",
                "side": exit_side,
                "order_type": "STOP_LOSS",
                "time_in_force": "GTC",
                "quantity": str(quantity),
                "stop_price": str(stop_loss_price),
                "support_trading_session": "CORE",
            })

        body = {
            "account_id": account_id,
            "client_combo_order_id": combo_id,
            "new_orders": orders,
        }
        data = await self._client.post("/openapi/trade/order/place", body)

        return PlaceOrderResult(
            client_order_id=data.get("client_order_id", ""),
            combo_order_id=data.get("combo_order_id", ""),
            client_combo_order_id=combo_id,
        )

    async def place_oco_order(
        self,
        account_id: str,
        symbol: str,
        quantity: int,
        pt_price: float,
        sl_price: float,
        sl_order_type: str = "STOP_LOSS",
        sl_limit_price: float = None,
        time_in_force: str = "GTC",
        extended_hours: bool = False,
        # Option fields (None = stock order)
        option_type: str = None,
        strike_price: float = None,
        expiry_date: str = None,
    ) -> PlaceOrderResult:
        """Place OCO (One Cancels Other) exit bracket — SL + PT linked.

        When one leg fills, the broker auto-cancels the other.
        Supports both stocks (EQUITY) and options (OPTION).

        For stocks: GTC TIF, survives bot crash.
        For options: DAY TIF only (Webull restriction), must re-place daily.
        """
        combo_id = self._gen_client_order_id()
        pt_coid = self._gen_client_order_id()
        sl_coid = self._gen_client_order_id()
        is_option = option_type is not None and strike_price is not None
        inst_type = "OPTION" if is_option else "EQUITY"
        _tif = "DAY" if is_option else time_in_force
        _session = "ALL" if extended_hours and not is_option else "CORE"

        # PT leg — LIMIT sell at profit target
        pt_leg = {
            "client_order_id": pt_coid,
            "combo_type": "OCO",
            "instrument_type": inst_type,
            "entrust_type": "QTY",
            "symbol": symbol,
            "market": "US",
            "side": "SELL",
            "order_type": "LIMIT",
            "limit_price": str(pt_price),
            "quantity": str(int(quantity)),
            "time_in_force": _tif,
        }
        if not is_option:
            pt_leg["support_trading_session"] = _session

        # SL leg — STOP_LOSS or STOP_LOSS_LIMIT sell at stop price
        sl_leg = {
            "client_order_id": sl_coid,
            "combo_type": "OCO",
            "instrument_type": inst_type,
            "entrust_type": "QTY",
            "symbol": symbol,
            "market": "US",
            "side": "SELL",
            "order_type": sl_order_type,
            "stop_price": str(sl_price),
            "quantity": str(int(quantity)),
            "time_in_force": _tif,
        }
        if sl_limit_price is not None:
            sl_leg["limit_price"] = str(sl_limit_price)
        if not is_option:
            sl_leg["support_trading_session"] = _session

        # Option-specific: add legs[] array + option_strategy + position_intent
        if is_option:
            opt_leg_detail = {
                "side": "SELL",
                "quantity": str(int(quantity)),
                "symbol": symbol,
                "market": "US",
                "instrument_type": "OPTION",
                "strike_price": str(strike_price),
                "option_expire_date": expiry_date or "",
                "option_type": option_type.upper(),
                "position_effect": "CLOSE",
            }
            pt_leg["option_strategy"] = "SINGLE"
            pt_leg["position_intent"] = "SELL_TO_CLOSE"
            pt_leg["legs"] = [opt_leg_detail.copy()]

            sl_leg["option_strategy"] = "SINGLE"
            sl_leg["position_intent"] = "SELL_TO_CLOSE"
            sl_leg["legs"] = [opt_leg_detail.copy()]

        body = {
            "account_id": account_id,
            "client_combo_order_id": combo_id,
            "new_orders": [pt_leg, sl_leg],
        }
        data = await self._client.post("/openapi/trade/order/place", body)

        return PlaceOrderResult(
            client_order_id=data.get("client_order_id", ""),
            combo_order_id=data.get("combo_order_id", ""),
            client_combo_order_id=combo_id,
            pt_client_order_id=pt_coid,
            sl_client_order_id=sl_coid,
        )

    async def place_trailing_stop(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: float,
        trailing_type: str,
        trailing_stop_step: float,
        client_order_id: str = None,
    ) -> PlaceOrderResult:
        coid = client_order_id or self._gen_client_order_id()
        order = {
            "client_order_id": coid,
            "combo_type": "NORMAL",
            "instrument_type": "EQUITY",
            "entrust_type": "QTY",
            "symbol": symbol,
            "market": "US",
            "side": side,
            "order_type": "TRAILING_STOP_LOSS",
            "time_in_force": "DAY",
            "quantity": str(quantity),
            "trailing_type": trailing_type,
            "trailing_stop_step": str(trailing_stop_step),
        }
        body = {"account_id": account_id, "new_orders": [order]}
        data = await self._client.post("/openapi/trade/order/place", body)
        return PlaceOrderResult(
            client_order_id=data.get("client_order_id", coid),
            order_id=data.get("order_id", ""),
        )

    async def cancel_order(self, account_id: str, client_order_id: str) -> dict:
        body = {
            "account_id": account_id,
            "client_order_id": client_order_id,
        }
        return await self._client.post("/openapi/trade/order/cancel", body)

    async def cancel_order_by_broker_id(self, account_id: str, order_id: str) -> dict:
        """WO-5: Cancel using Webull's numeric order_id instead of client_order_id."""
        body = {
            "account_id": account_id,
            "order_id": order_id,
        }
        return await self._client.post("/openapi/trade/order/cancel", body)

    async def replace_order(
        self,
        account_id: str,
        client_order_id: str,
        limit_price: float = None,
        stop_price: float = None,
        quantity: float = None,
        time_in_force: str = None,
        order_type: str = None,
        trailing_stop_step: float = None,
        leg_id: str = None,
        leg_quantity: int = None,
    ) -> dict:
        modify = {"client_order_id": client_order_id}
        if limit_price is not None:
            modify["limit_price"] = str(limit_price)
        if stop_price is not None:
            modify["stop_price"] = str(stop_price)
        if quantity is not None:
            modify["quantity"] = str(quantity)
        if time_in_force is not None:
            modify["time_in_force"] = time_in_force
        if order_type is not None:
            modify["order_type"] = order_type
        if trailing_stop_step is not None:
            modify["trailing_stop_step"] = str(trailing_stop_step)
        # Option orders require legs array with id for Replace API
        if leg_id is not None:
            modify["legs"] = [{"id": leg_id, "quantity": str(leg_quantity or quantity or 1)}]

        body = {"account_id": account_id, "modify_orders": [modify]}
        return await self._client.post("/openapi/trade/order/replace", body)

    async def get_open_orders(self, account_id: str, page_size: int = 100) -> list[WebullOrder]:
        data = await self._client.get(
            "/openapi/trade/order/open",
            params={"account_id": account_id, "page_size": str(page_size)},
        )
        results = []
        items = data if isinstance(data, list) else data.get("orders", [])
        for group in items:
            combo_type = group.get("combo_type", "NORMAL")
            for order in group.get("orders", [group]):
                results.append(WebullOrder.from_api(order, combo_type))
        return results

    async def get_order_detail(self, account_id: str, client_order_id: str) -> WebullOrder:
        data = await self._client.get(
            "/openapi/trade/order/detail",
            params={"account_id": account_id, "client_order_id": client_order_id},
        )
        orders = data.get("orders", [data])
        return WebullOrder.from_api(orders[0] if orders else data)

    async def get_order_history(
        self,
        account_id: str,
        start_date: str = None,
        end_date: str = None,
        page_size: int = 100,
    ) -> list[WebullOrder]:
        params = {"account_id": account_id, "page_size": str(page_size)}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        data = await self._client.get("/openapi/trade/order/history", params)
        results = []
        items = data if isinstance(data, list) else data.get("orders", [])
        for group in items:
            combo_type = group.get("combo_type", "NORMAL")
            for order in group.get("orders", [group]):
                results.append(WebullOrder.from_api(order, combo_type))
        return results

    async def preview_order(self, order_body: dict) -> dict:
        """Preview an order before placement — returns estimated cost, fees, buying power impact.

        Uses the same body as place_stock_order/place_option_order but sends to /preview endpoint.
        BUY-side only (STC exits skip preview for latency). Fail-open: network errors return None.
        """
        try:
            return await self._client.post("/openapi/trade/order/preview", order_body)
        except Exception as e:
            log.warning(f"[WEBULL-OFF] Order preview failed (non-blocking): {e}")
            return None

    async def batch_place_orders(self, account_id: str, orders: list[dict]) -> list:
        """Place multiple orders in a single API call.

        Each order dict should be a complete order body (same as place_stock_order).
        Returns list of PlaceOrderResult for each order.
        """
        body = {
            "account_id": account_id,
            "new_orders": orders,
        }
        data = await self._client.post("/openapi/trade/order/batch-place", body)
        results = []
        items = data if isinstance(data, list) else data.get("results", [data])
        for item in items:
            results.append(PlaceOrderResult(
                client_order_id=item.get("client_order_id", ""),
                order_id=item.get("order_id", ""),
            ))
        return results
