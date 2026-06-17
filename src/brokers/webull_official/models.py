from dataclasses import dataclass
from typing import Optional


@dataclass
class WebullAccount:
    account_id: str
    account_type: str
    account_class: str
    account_label: str
    user_id: str = ""


@dataclass
class WebullBalance:
    total_cash_balance: float = 0.0
    total_market_value: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_net_liquidation: float = 0.0
    total_day_pnl: float = 0.0
    buying_power: float = 0.0
    settled_cash: float = 0.0
    unsettled_cash: float = 0.0
    day_trades_left: str = ""
    option_buying_power: float = 0.0
    day_buying_power: float = 0.0
    overnight_buying_power: float = 0.0

    @classmethod
    def from_api(cls, data: dict) -> "WebullBalance":
        # Webull API sometimes wraps the payload in one or more {"data": ...} envelopes
        while isinstance(data, dict) and "account_currency_assets" not in data and "data" in data:
            data = data["data"]
        currency_assets = data.get("account_currency_assets", [])
        usd = currency_assets[0] if currency_assets else {}
        return cls(
            total_cash_balance=float(data.get("total_cash_balance") or 0),
            total_market_value=float(data.get("total_market_value") or 0),
            total_unrealized_pnl=float(data.get("total_unrealized_profit_loss") or 0),
            total_net_liquidation=float(data.get("total_net_liquidation_value") or 0),
            total_day_pnl=float(data.get("total_day_profit_loss") or 0),
            buying_power=float(usd.get("buying_power") or 0),
            settled_cash=float(usd.get("settled_cash") or 0),
            unsettled_cash=float(usd.get("unsettled_cash") or 0),
            day_trades_left=data.get("day_trades_left", ""),
            option_buying_power=float(usd.get("option_buying_power") or 0),
            day_buying_power=float(usd.get("day_buying_power") or 0),
            overnight_buying_power=float(usd.get("overnight_buying_power") or 0),
        )


@dataclass
class WebullPosition:
    position_id: str
    symbol: str
    quantity: float
    cost_price: float
    last_price: float
    unrealized_pnl: float
    instrument_type: str
    currency: str = "USD"
    option_type: str = ""
    strike_price: float = 0.0
    expiry_date: str = ""
    option_strategy: str = ""
    multiplier: int = 100

    @classmethod
    def from_api(cls, data: dict) -> "WebullPosition":
        legs = data.get("legs", [])
        leg = legs[0] if legs else {}
        return cls(
            position_id=data.get("position_id", ""),
            symbol=data.get("symbol", ""),
            quantity=float(data.get("quantity") or 0),
            cost_price=float(data.get("cost_price") or 0),
            last_price=float(data.get("last_price") or 0),
            unrealized_pnl=float(data.get("unrealized_profit_loss") or 0),
            instrument_type=data.get("instrument_type", "EQUITY"),
            option_type=leg.get("option_type", ""),
            strike_price=float(leg.get("option_exercise_price") or 0),
            expiry_date=leg.get("option_expire_date", ""),
            option_strategy=data.get("option_strategy", ""),
            multiplier=int(leg.get("option_contract_multiplier") or 100),
        )


@dataclass
class WebullOrder:
    client_order_id: str
    order_id: str
    symbol: str
    side: str
    status: str
    order_type: str
    instrument_type: str
    quantity: float
    filled_quantity: float
    filled_price: float
    limit_price: float = 0.0
    stop_price: float = 0.0
    time_in_force: str = "DAY"
    place_time: str = ""
    filled_time: str = ""
    combo_type: str = "NORMAL"

    @classmethod
    def from_api(cls, data: dict, combo_type: str = "NORMAL") -> "WebullOrder":
        return cls(
            client_order_id=data.get("client_order_id", ""),
            order_id=data.get("order_id", ""),
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            status=data.get("status", ""),
            order_type=data.get("order_type", ""),
            instrument_type=data.get("instrument_type", "EQUITY"),
            quantity=float(data.get("total_quantity") or 0),
            filled_quantity=float(data.get("filled_quantity") or 0),
            filled_price=float(data.get("filled_price") or 0),
            limit_price=float(data.get("limit_price") or 0),
            stop_price=float(data.get("stop_price") or 0),
            time_in_force=data.get("time_in_force", "DAY"),
            place_time=data.get("place_time_at", ""),
            filled_time=data.get("filled_time_at", ""),
            combo_type=combo_type,
        )


@dataclass
class PlaceOrderResult:
    client_order_id: str
    order_id: str = ""
    combo_order_id: str = ""
    client_combo_order_id: str = ""
