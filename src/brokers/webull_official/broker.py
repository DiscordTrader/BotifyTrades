import asyncio
import logging
import sys
import os
from pathlib import Path
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


def _token_file_path() -> Path:
    """Token stored next to bot_data.db so it survives restarts."""
    base = Path(__file__).parent.parent.parent.parent
    return base / "webull_official_token.json"


def _build_occ_symbol(symbol: str, expiry_date: str, call_put: str, strike) -> str:
    """Build compact OCC symbol: QQQ250620C00745000"""
    try:
        exp = expiry_date.replace('-', '')[2:]  # "2025-06-20" → "250620"
        strike_int = int(round(float(strike) * 1000))
        return f"{symbol.upper()}{exp}{call_put.upper()}{strike_int:08d}"
    except Exception:
        return ""


class WebullOfficialBroker:
    _active_instance: Optional["WebullOfficialBroker"] = None

    def __init__(self, loop=None, name="WEBULL_OFFICIAL", paper_trade=False, credentials: dict = None):
        WebullOfficialBroker._active_instance = self
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
        self._positions_cache: list = []
        self._positions_cache_ts: float = 0.0
        self._account_info_cache: dict = {}
        self._account_info_cache_ts: float = 0.0

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
            self._client = WebullClient(self._config, token_file=_token_file_path())
            await self._client.start()

            # Acquire x-access-token (requires Webull app approval on first use)
            await self._client.init_token()

            self._accounts = AccountsAPI(self._client)
            self._orders = OrdersAPI(self._client)
            self._positions = PositionsAPI(self._client)

            accounts = await self._accounts.list_accounts()
            if not accounts:
                print(f"[{self.name}] ❌ No accounts found — verify app_key/app_secret are from developer.webull.com")
                raise RuntimeError("No accounts found. Verify your App Key and App Secret at developer.webull.com")

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
            import time as _t
            _raw_bp = {"buying_power": float(balance.buying_power or 0), "option_buying_power": float(balance.option_buying_power or 0), "settled_cash": float(balance.settled_cash or 0)}
            effective_bp = self._effective_buying_power(_raw_bp)
            acct_seed = {
                "account_id": self.account_id,
                "account_number": self.account_number,
                "account_type": self.account_type,
                "cash_balance": balance.total_cash_balance,
                "buying_power": effective_bp,
                "portfolio_value": balance.total_net_liquidation,
                "market_value": balance.total_market_value,
                "unrealized_pnl": balance.total_unrealized_pnl,
                "day_pnl": balance.total_day_pnl,
                "settled_cash": balance.settled_cash,
                "unsettled_cash": balance.unsettled_cash,
                "day_trades_left": balance.day_trades_left,
                "option_buying_power": balance.option_buying_power,
                "options_buying_power": balance.option_buying_power,
            }
            self._account_info_cache = acct_seed
            self._account_info_cache_ts = _t.monotonic()
            if effective_bp > 0:
                self._last_known_good_balance = acct_seed
            print(f"[{self.name}] ✅ Connected — Account: {self.account_id}, "
                  f"Balance: ${balance.total_net_liquidation:,.2f} BP: ${effective_bp:,.2f} (settled=${balance.settled_cash:,.2f})")
            return True

        except Exception as e:
            print(f"[{self.name}] ❌ Connection failed: {e}")
            self.connected = False
            raise

    async def disconnect(self):
        if self._event_poller:
            await self._event_poller.stop()
        if self._stream:
            await self._stream.disconnect()
        if self._client:
            await self._client.close()
        self.connected = False
        if WebullOfficialBroker._active_instance is self:
            WebullOfficialBroker._active_instance = None
        print(f"[{self.name}] Disconnected")

    @staticmethod
    def _effective_buying_power(balance_dict: dict) -> float:
        """Effective buying power: cash accounts report buying_power=0; use option_buying_power or settled_cash."""
        bp = float(balance_dict.get('buying_power') or 0)
        if bp > 0:
            return bp
        obp = float(balance_dict.get('option_buying_power') or 0)
        if obp > 0:
            return obp
        return float(balance_dict.get('settled_cash') or 0)

    async def get_account_info(self, max_age_seconds: float = 30.0) -> dict:
        import time as _time
        if not self.connected:
            return self._account_info_cache or {}
        now = _time.monotonic()
        if self._account_info_cache_ts > 0 and (now - self._account_info_cache_ts) < max_age_seconds:
            return self._account_info_cache
        try:
            balance = await self._accounts.get_balance(self.account_id)
            self._cached_balance = balance
            _raw_bp = {"buying_power": float(balance.buying_power or 0), "option_buying_power": float(balance.option_buying_power or 0), "settled_cash": float(balance.settled_cash or 0)}
            effective_bp = self._effective_buying_power(_raw_bp)
            result = {
                "account_id": self.account_id,
                "account_number": self.account_number,
                "account_type": self.account_type,
                "cash_balance": balance.total_cash_balance,
                "buying_power": effective_bp,
                "portfolio_value": balance.total_net_liquidation,
                "market_value": balance.total_market_value,
                "unrealized_pnl": balance.total_unrealized_pnl,
                "day_pnl": balance.total_day_pnl,
                "settled_cash": balance.settled_cash,
                "unsettled_cash": balance.unsettled_cash,
                "day_trades_left": balance.day_trades_left,
                "option_buying_power": balance.option_buying_power,
                "options_buying_power": balance.option_buying_power,
            }
            self._account_info_cache = result
            self._account_info_cache_ts = now
            if effective_bp > 0:
                self._last_known_good_balance = result
            return result
        except Exception as e:
            log.error(f"[{self.name}] get_account_info error: {e}")
            return self._account_info_cache or {}

    def _get_account_info_for_sizing(self) -> dict:
        """Return best available balance for position sizing — prefers live, falls back to last known good."""
        cache = self._account_info_cache or {}
        if self._effective_buying_power(cache) > 0:
            return cache
        fallback = getattr(self, '_last_known_good_balance', None)
        if fallback and self._effective_buying_power(fallback) > 0:
            bp = self._effective_buying_power(fallback)
            log.warning(f"[{self.name}] Live balance returned $0 — using last known good balance (BP=${bp:.2f})")
            return fallback
        return cache

    async def get_positions(self, max_age_seconds: float = 30.0) -> list:
        import time as _time
        if not self.connected:
            return self._positions_cache if self._positions_cache else []
        now = _time.monotonic()
        if self._positions_cache_ts > 0 and (now - self._positions_cache_ts) < max_age_seconds:
            return self._positions_cache
        try:
            positions = await self._positions.get_positions(self.account_id)
            self._cached_positions = positions
            result = [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_cost": p.cost_price,
                    "current_price": p.last_price,
                    "unrealized_pl": p.unrealized_pnl,
                    "asset": "option" if p.instrument_type == "OPTION" else "stock",
                    "broker": self.name,
                    "position_id": p.position_id,
                    "option_id": p.position_id,
                    "option_type": p.option_type,
                    "strike_price": p.strike_price,
                    "expiry_date": p.expiry_date,
                }
                for p in positions
            ]
            self._positions_cache = result
            self._positions_cache_ts = now
            return result
        except Exception as e:
            log.error(f"[{self.name}] get_positions error: {e}")
            return self._positions_cache  # return stale cache on error

    async def get_positions_detailed(self) -> list:
        return await self.get_positions()

    @staticmethod
    def _needs_extended_hours() -> bool:
        """Return True when current time is outside regular US market hours (9:30–16:00 ET).
        Webull Official rejects DAY/CORE orders after hours with 417 — must use ALL session."""
        try:
            from datetime import datetime
            import pytz
            et = pytz.timezone('US/Eastern')
            now = datetime.now(et)
            if now.weekday() >= 5:
                return True
            open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
            close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
            return not (open_t <= now <= close_t)
        except Exception:
            return False

    async def place_stock_order(self, symbol, quantity, action, price=None,
                                order_type=None, stop_price=None, duration="DAY",
                                extended_hours=False, **kwargs) -> OrderResult:
        if not self.connected:
            return OrderResult(success=False, message="Not connected")

        side_map = {
            "BUY": "BUY", "SELL": "SELL", "BTO": "BUY", "STC": "SELL",
            "SHORT": "SHORT", "COVER": "BUY",
        }
        side = side_map.get(action.upper(), action.upper())

        # Derive order_type from price when not explicitly provided
        if order_type is None:
            otype = "LIMIT" if price is not None else "MARKET"
        else:
            type_map = {
                "MARKET": "MARKET", "LIMIT": "LIMIT",
                "STOP": "STOP_LOSS", "STOP_LIMIT": "STOP_LOSS_LIMIT",
            }
            otype = type_map.get(order_type.upper(), order_type.upper())

        tif_map = {"DAY": "DAY", "GTC": "GTC", "IOC": "IOC"}
        tif = tif_map.get(duration.upper(), "DAY")

        if side == "BUY":
            try:
                await self.get_account_info(max_age_seconds=60)
                acct = self._get_account_info_for_sizing()
                bp = self._effective_buying_power(acct)
                if bp <= 0:
                    print(f"[{self.name}] ❌ FUNDS: No buying power available (${bp:.2f})", flush=True)
                    return OrderResult(success=False, message=f"Insufficient buying power: ${bp:.2f} available", symbol=symbol, action=action, quantity=quantity)
                if price is not None:
                    order_cost = quantity * price
                    if order_cost > bp:
                        print(f"[{self.name}] ❌ FUNDS: Stock order cost ${order_cost:.2f} > buying power ${bp:.2f}", flush=True)
                        return OrderResult(success=False, message=f"Insufficient buying power: ${bp:.2f} available, ${order_cost:.2f} needed", symbol=symbol, action=action, quantity=quantity)
                print(f"[{self.name}] ✓ FUNDS: Stock buying power OK — ${bp:.2f} available", flush=True)
            except Exception as _fe:
                print(f"[{self.name}] ⚠️ FUNDS: Could not verify buying power: {_fe}", flush=True)

        # Webull requires price precision: 2dp for stocks >= $1, 4dp for < $1
        if price is not None:
            price = round(price, 2) if price >= 1.0 else round(price, 4)
        if stop_price is not None:
            stop_price = round(stop_price, 2) if stop_price >= 1.0 else round(stop_price, 4)

        # Auto-enable extended hours when outside regular session (same behaviour as legacy Webull)
        if not extended_hours and self._needs_extended_hours():
            extended_hours = True
            # Webull rejects DAY TIF outside core hours — upgrade to GTC
            if tif == "DAY":
                tif = "GTC"
            print(f"[{self.name}] ⏰ After-hours detected — GTC TIF, CORE session (queues for regular open)", flush=True)
            # Extended hours requires LIMIT — convert MARKET orders
            if otype == "MARKET":
                if price is None:
                    _q = None
                    try:
                        from src.services.webull_data_hub import get_webull_data_hub
                        _q = get_webull_data_hub().get_quote(symbol)
                    except Exception:
                        pass
                    if _q and (_q.ask or _q.bid or _q.last):
                        price = _q.ask if side == "BUY" else _q.bid or _q.last
                        price = round(price, 2) if price >= 1.0 else round(price, 4)
                otype = "LIMIT"
                print(f"[{self.name}] ⏰ Extended hours MARKET→LIMIT: ${price}", flush=True)

        try:
            result = await self._orders.place_stock_order(
                account_id=self.account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=otype,
                limit_price=price,
                stop_price=stop_price,
                time_in_force=tif,
                extended_hours=extended_hours,
            )
            return OrderResult(
                success=True,
                order_id=result.client_order_id or result.order_id,
                message=f"Order placed: {side} {quantity} {symbol}",
                price=price,
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

    async def get_option_quote(self, symbol: str, strike: float, expiry: str, option_type: str) -> Optional[dict]:
        """Fetch live option bid/ask from Webull Official REST API."""
        if not self._client:
            return None
        try:
            otype = "CALL" if str(option_type).upper().startswith("C") else "PUT"
            data = await asyncio.wait_for(
                self._client.get("/openapi/quote/option/query", params={
                    "symbol": symbol,
                    "strike_price": str(strike),
                    "option_expire_date": expiry,
                    "option_type": otype,
                }),
                timeout=3.0,
            )
            if isinstance(data, dict):
                bid = float(data.get("bidPrice") or data.get("bid_price") or data.get("bid") or 0)
                ask = float(data.get("askPrice") or data.get("ask_price") or data.get("ask") or 0)
                last = float(data.get("close") or data.get("lastPrice") or data.get("last") or 0)
                if bid > 0 or ask > 0 or last > 0:
                    return {"bid": bid, "ask": ask, "last": last}
        except Exception as e:
            print(f"[{self.name}] ⚠️ get_option_quote failed for {symbol} ${strike} {expiry} {option_type}: {e}", flush=True)
        return None

    async def place_option_order(self, symbol, quantity, action, order_type="LIMIT",
                                 limit_price=None, option_type=None,
                                 strike_price=None, expiry_date=None,
                                 strike=None, expiry=None, price=None,
                                 **kwargs) -> OrderResult:
        if not self.connected:
            return OrderResult(success=False, message="Not connected")

        # Resolve parameter aliases — caller uses strike/expiry/price; API layer uses strike_price/expiry_date/limit_price
        effective_strike = strike_price if strike_price is not None else strike
        effective_expiry = expiry_date if expiry_date is not None else expiry
        effective_limit = limit_price if limit_price is not None else price

        # Normalize expiry to YYYY-MM-DD — positions from legacy Webull hub may carry MM/DD or MM/DD/YY
        if effective_expiry:
            _exp = str(effective_expiry).strip()
            if '/' in _exp and '-' not in _exp:
                from datetime import date as _date
                _parts = _exp.split('/')
                if len(_parts) == 2:
                    _m, _d = int(_parts[0]), int(_parts[1])
                    _yr = _date.today().year
                    # Roll to next year if the date has already passed
                    if (_m, _d) < (_date.today().month, _date.today().day):
                        _yr += 1
                    effective_expiry = f"{_yr}-{_m:02d}-{_d:02d}"
                elif len(_parts) == 3:
                    _m, _d, _y = int(_parts[0]), int(_parts[1]), int(_parts[2])
                    effective_expiry = f"{2000 + _y if _y < 100 else _y}-{_m:02d}-{_d:02d}"

        # Webull Official API does not support MARKET orders for options.
        # Simulate market order by fetching live bid/ask: BTO uses ask, STC uses bid.
        if order_type.upper() == "MARKET":
            order_type = "LIMIT"
        if effective_limit is None:
            side = "BUY" if action.upper() in ("BTO", "BTC") else "SELL"
            otype_str = "C" if option_type and str(option_type).upper().startswith("C") else "P"
            q = await self.get_option_quote(symbol, effective_strike, effective_expiry, otype_str)
            if q:
                if side == "BUY":
                    raw = q.get("ask") or q.get("last") or 0.0
                    effective_limit = round(raw * 1.01, 2) if raw > 0 else None
                    print(f"[{self.name}] ⚡ Market BTO sim: ask=${q.get('ask', 0):.4f} → limit=${effective_limit}", flush=True)
                else:
                    raw = q.get("bid") or q.get("last") or 0.0
                    effective_limit = round(raw, 2) if raw > 0 else None
                    print(f"[{self.name}] ⚡ Market STC sim: bid=${q.get('bid', 0):.4f} → limit=${effective_limit}", flush=True)
            # Fallback: caller passes _signal_price_fallback (UPH bid for exits, signal price for entries)
            if effective_limit is None:
                _fb = kwargs.get('_signal_price_fallback')
                if _fb and float(_fb) > 0:
                    if side == "BUY":
                        effective_limit = round(float(_fb) * 1.01, 2)
                    else:
                        effective_limit = round(float(_fb), 2)
                    print(f"[{self.name}] ⚡ Market sim fallback: using signal price ${_fb:.4f} → limit=${effective_limit}", flush=True)
            if effective_limit is None:
                print(f"[{self.name}] ❌ Option order rejected: no price and live quote failed for {symbol} ${effective_strike} {effective_expiry}", flush=True)
                return OrderResult(
                    success=False,
                    message="Options require a limit price. Market order simulation failed — could not fetch live bid/ask.",
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                )

        intent_map = {
            "BTO": "BUY_TO_OPEN", "STC": "SELL_TO_CLOSE",
            "STO": "SELL_TO_OPEN", "BTC": "BUY_TO_CLOSE",
        }
        position_intent = intent_map.get(action.upper(), "BUY_TO_OPEN")

        side = "BUY" if action.upper() in ("BTO", "BTC") else "SELL"
        otype = "CALL" if option_type and option_type.upper().startswith("C") else "PUT"

        if side == "BUY":
            try:
                acct = await self.get_account_info(max_age_seconds=60)
                settled = float(acct.get('settled_cash', 0) or 0)
                bp = float(acct.get('buying_power', 0) or 0)
                # Options require settled cash in cash accounts; fall back to buying_power if not set
                effective_funds = settled if settled > 0 else bp
                if effective_funds <= 0:
                    print(f"[{self.name}] ❌ FUNDS: No settled cash available — settled=${settled:.2f}, BP=${bp:.2f}", flush=True)
                    return OrderResult(success=False, message=f"Insufficient settled cash: ${settled:.2f} available", symbol=symbol, action=action, quantity=quantity)
                if effective_limit is not None:
                    order_cost = quantity * effective_limit * 100
                    if order_cost > effective_funds:
                        print(f"[{self.name}] ❌ FUNDS: Option order cost ${order_cost:.2f} > settled cash ${effective_funds:.2f} (settled=${settled:.2f}, BP=${bp:.2f})", flush=True)
                        return OrderResult(success=False, message=f"Insufficient settled cash: ${effective_funds:.2f} available, ${order_cost:.2f} needed", symbol=symbol, action=action, quantity=quantity)
                print(f"[{self.name}] ✓ FUNDS: Options settled cash OK — ${settled:.2f} settled, ${bp:.2f} BP", flush=True)
            except Exception as _fe:
                print(f"[{self.name}] ⚠️ FUNDS: Could not verify settled cash: {_fe}", flush=True)

        # Sell-side STC/STO: DAY only (Webull Official restriction). Buy-side (BTO/BTC): allow GTC for PT brackets.
        tif = "DAY" if side == "SELL" else kwargs.get('time_in_force', 'GTC')

        try:
            result = await self._orders.place_option_order(
                account_id=self.account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                option_type=otype,
                strike_price=effective_strike,
                expiry_date=effective_expiry,
                position_intent=position_intent,
                order_type=order_type.upper(),
                limit_price=effective_limit,
                time_in_force=tif,
            )
            return OrderResult(
                success=True,
                order_id=result.client_order_id or result.order_id,
                message=f"Option order placed: {action} {quantity}x {symbol}",
                price=effective_limit,
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
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            q = get_webull_data_hub().get_quote(symbol)
            if q:
                return {"symbol": symbol, "last": q.last or 0.0, "bid": q.bid or 0.0, "ask": q.ask or 0.0}
        except Exception:
            pass
        return {"symbol": symbol, "last": 0.0, "bid": 0.0, "ask": 0.0}

    async def place_bracket_order(self, symbol, quantity, side, order_type="MARKET",
                                  limit_price=None, take_profit=None, stop_loss=None,
                                  extended_hours=False) -> OrderResult:
        if not self.connected:
            return OrderResult(success=False, message="Not connected")

        if not extended_hours and self._needs_extended_hours():
            extended_hours = True
            print(f"[{self.name}] ⏰ After-hours detected — enabling extended hours for bracket order", flush=True)

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

    async def get_order_status(self, client_order_id: str) -> Optional[dict]:
        if not self.connected:
            return None
        try:
            order = await self._orders.get_order_detail(self.account_id, client_order_id)
            if not order:
                return None
            status_map = {
                'FILLED': 'FILLED',
                'PARTIAL_FILLED': 'PARTIAL',
                'WORKING': 'WORKING',
                'SUBMITTING': 'WORKING',
                'SUBMITTED': 'WORKING',
                'PENDING_NEW': 'WORKING',
                'CANCELLED': 'CANCELLED',
                'CANCELING': 'CANCELLED',
                'REJECTED': 'CANCELLED',
                'EXPIRED': 'CANCELLED',
            }
            return {
                'order_id': order.client_order_id,
                'status': status_map.get(order.status, order.status),
                'filled_qty': int(order.filled_quantity),
                'filled_quantity': int(order.filled_quantity),
                'remaining_quantity': max(0, int(order.quantity - order.filled_quantity)),
                'avg_fill_price': float(order.filled_price),
                'raw_status': order.status,
            }
        except Exception as e:
            if "ORDER_NOT_FOUND" in str(e) or "order was not found" in str(e).lower():
                log.debug(f"[{self.name}] get_order_status: order {client_order_id} not found")
            else:
                log.error(f"[{self.name}] get_order_status error: {e}")
            return None

    async def place_stop_order(self, symbol: str, quantity: int, stop_price: float, side: str = 'sell') -> 'OrderResult':
        action = 'STC' if side.lower() in ('sell', 'stc') else 'BTO'
        return await self.place_stock_order(
            symbol=symbol,
            quantity=quantity,
            action=action,
            order_type='STOP',
            stop_price=stop_price,
            duration='GTC',
        )

    async def modify_order(self, client_order_id: str, stop_price: float = None, limit_price: float = None) -> dict:
        try:
            await self._orders.replace_order(
                self.account_id,
                client_order_id,
                stop_price=stop_price,
                limit_price=limit_price,
            )
            return {'success': True, 'order_id': client_order_id}
        except Exception as e:
            log.error(f"[{self.name}] modify_order error: {e}")
            return {'success': False, 'error': str(e)}

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
            if "TOO_MANY_REQUESTS" in str(e) or "429" in str(e):
                log.warning(f"[{self.name}] get_pending_orders rate limited")
            else:
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

    def _on_mqtt_quote(self, tick_data):
        try:
            symbol = tick_data.get('symbol') or tick_data.get('ticker')
            if not symbol:
                return
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub:
                quote = {}
                if tick_data.get('bidPrice') is not None:
                    quote['bid'] = float(tick_data['bidPrice'])
                if tick_data.get('askPrice') is not None:
                    quote['ask'] = float(tick_data['askPrice'])
                if tick_data.get('close') is not None:
                    quote['last'] = float(tick_data['close'])
                elif tick_data.get('dealPrice') is not None:
                    quote['last'] = float(tick_data['dealPrice'])
                # When only snapshot close is present (no bid/ask), use last as bid fallback so SL exits have a meaningful price
                if not quote.get('bid') and quote.get('last'):
                    quote['bid'] = quote['last']
                if tick_data.get('volume') is not None:
                    quote['volume'] = int(tick_data['volume'])
                if tick_data.get('high') is not None:
                    quote['high'] = float(tick_data['high'])
                if tick_data.get('low') is not None:
                    quote['low'] = float(tick_data['low'])
                if tick_data.get('open') is not None:
                    quote['open'] = float(tick_data['open'])
                if tick_data.get('change') is not None:
                    quote['change'] = float(tick_data['change'])
                if tick_data.get('changeRatio') is not None:
                    quote['changeRatio'] = float(tick_data['changeRatio'])
                if quote:
                    hub.update_quote(symbol, quote, source='webull_official')
        except Exception as e:
            print(f"[WEBULL_OFF] ⚠️ MQTT quote handler error: {e}")

    def subscribe_symbol(self, symbol: str, is_option: bool = None):
        """Subscribe a symbol to MQTT streaming. Schedules an async task on the running loop."""
        if not self._stream:
            return
        if is_option is None:
            is_option = len(symbol) > 10 and any(c.isdigit() for c in symbol)
        category = "US_OPTION" if is_option else "US_STOCK"
        loop = getattr(self._stream, '_main_loop', None)
        if not loop or not loop.is_running():
            log.warning(f"[{self.name}] subscribe_symbol({symbol}) skipped — stream not ready (loop={loop})")
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._stream.subscribe([symbol], category=category), loop
            )
        except Exception as e:
            log.warning(f"[{self.name}] subscribe_symbol({symbol}) failed: {e}")

    async def start_streaming(self, symbols: list[str] = None):
        if not self._stream:
            self._stream = WebullMarketStream(self._config, self._client)
            self._stream.on_quote_callback = self._on_mqtt_quote

        connected = await self._stream.connect()
        if connected:
            if symbols:
                await self._stream.subscribe(symbols)
            # Auto-subscribe current positions so MQTT prices flow immediately
            try:
                pos_list = await self.get_positions(max_age_seconds=0)
                stock_syms, opt_syms = [], []
                for p in pos_list:
                    sym = p.get('symbol', '')
                    if not sym:
                        continue
                    if p.get('asset') == 'option':
                        occ = _build_occ_symbol(
                            sym,
                            p.get('expiry_date', ''),
                            'C' if 'CALL' in (p.get('option_type') or '').upper() else 'P',
                            p.get('strike_price', 0),
                        )
                        if occ:
                            opt_syms.append(occ)
                        stock_syms.append(sym)
                    else:
                        stock_syms.append(sym)
                if stock_syms:
                    await self._stream.subscribe(list(set(stock_syms)), category="US_STOCK")
                if opt_syms:
                    await self._stream.subscribe(list(set(opt_syms)), category="US_OPTION")
                if stock_syms or opt_syms:
                    print(f"[{self.name}] ✓ MQTT subscribed {len(stock_syms)} stocks, {len(opt_syms)} options", flush=True)
            except Exception as _se:
                log.warning(f"[{self.name}] Auto-subscribe positions failed: {_se}")

        if not self._event_poller:
            self._event_poller = TradeEventPoller(self._client, self.account_id)
            await self._event_poller.start()
            print(f"[{self.name}] ✓ TradeEventPoller started")

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
