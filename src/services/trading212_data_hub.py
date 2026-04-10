import asyncio
import time
import threading
import sys
from typing import Optional, Dict, Any, List
from enum import Enum


class PollState(Enum):
    IDLE = 'idle'
    WATCHING = 'watching'
    ACTIVE = 'active'
    PENDING = 'pending'
    CONDITIONAL = 'conditional'


POLL_INTERVALS = {
    PollState.IDLE: 30,
    PollState.WATCHING: 15,
    PollState.ACTIVE: 6,
    PollState.PENDING: 5,
    PollState.CONDITIONAL: 4,
}

QUOTE_STALE_THRESHOLD = 60

_CONDITIONAL_QUOTE_INTERVAL = 3
_CONDITIONAL_QUOTE_MAX_AGE = 10


class Trading212DataHub:
    def __init__(self, broker=None):
        self._broker = broker
        self._positions = []
        self._positions_ts = 0
        self._orders = []
        self._orders_ts = 0
        self._account = {}
        self._account_ts = 0
        self._quotes: Dict[str, Dict[str, Any]] = {}
        self._quotes_lock = threading.Lock()
        self._poll_state = PollState.IDLE
        self._running = False
        self._task = None
        self._lock = threading.Lock()
        self._is_stale = False
        self._conditional_symbols: set = set()
        self._conditional_lock = threading.Lock()
        self._last_conditional_quote_ts: float = 0

    def set_broker(self, broker):
        self._broker = broker

    @property
    def poll_state(self) -> PollState:
        return self._poll_state

    @property
    def is_stale(self) -> bool:
        return self._is_stale

    def add_conditional_symbol(self, symbol: str):
        with self._conditional_lock:
            self._conditional_symbols.add(symbol.upper())
        self._update_state_for_conditionals()

    def remove_conditional_symbol(self, symbol: str):
        with self._conditional_lock:
            self._conditional_symbols.discard(symbol.upper())
        self._update_state_for_conditionals()

    def _update_state_for_conditionals(self):
        with self._conditional_lock:
            has_conditionals = len(self._conditional_symbols) > 0
        if has_conditionals and self._poll_state in (PollState.IDLE, PollState.WATCHING):
            self._poll_state = PollState.CONDITIONAL

    def update_poll_state(self, has_open_positions: bool, has_pending_orders: bool):
        with self._conditional_lock:
            has_conditionals = len(self._conditional_symbols) > 0
        if has_pending_orders:
            self._poll_state = PollState.PENDING
        elif has_conditionals:
            self._poll_state = PollState.CONDITIONAL
        elif has_open_positions:
            self._poll_state = PollState.ACTIVE
        else:
            self._poll_state = PollState.WATCHING

    def get_positions(self, max_age_seconds: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            age = time.time() - self._positions_ts
            if age > max_age_seconds:
                self._is_stale = True
            return list(self._positions)

    def get_orders(self, max_age_seconds: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            age = time.time() - self._orders_ts
            if age > max_age_seconds:
                self._is_stale = True
            return list(self._orders)

    def get_account(self, max_age_seconds: int = 30) -> Dict[str, Any]:
        with self._lock:
            return dict(self._account) if self._account else {}

    def get_quote_price(self, symbol: str) -> Optional[float]:
        with self._quotes_lock:
            entry = self._quotes.get(symbol.upper())
            if entry and (time.time() - entry['ts']) < QUOTE_STALE_THRESHOLD:
                return entry['price']
        return None

    def get_quote_timestamp(self, symbol: str) -> Optional[float]:
        with self._quotes_lock:
            entry = self._quotes.get(symbol.upper())
            if entry:
                return entry['ts']
        return None

    def _update_quotes_from_positions(self, positions: List[Dict[str, Any]]):
        now = time.time()
        with self._quotes_lock:
            for pos in positions:
                sym = (pos.get('symbol') or '').upper()
                price = pos.get('current_price')
                if sym and price and float(price) > 0:
                    self._quotes[sym] = {'price': float(price), 'ts': now}

    def _get_uncovered_conditional_symbols(self) -> List[str]:
        with self._conditional_lock:
            cond_syms = set(self._conditional_symbols)
        if not cond_syms:
            return []
        with self._quotes_lock:
            now = time.time()
            covered = set()
            for sym in cond_syms:
                entry = self._quotes.get(sym)
                if entry and (now - entry['ts']) < _CONDITIONAL_QUOTE_MAX_AGE:
                    covered.add(sym)
        return list(cond_syms - covered)

    def _try_cross_hub_quote(self, symbol: str) -> Optional[float]:
        sym_upper = symbol.upper()
        for mod_path, func_name in [
            ('src.services.webull_data_hub', 'get_webull_data_hub'),
            ('src.services.schwab_data_hub', 'get_schwab_data_hub'),
            ('src.services.ibkr_data_hub', 'get_ibkr_data_hub'),
            ('src.services.tastytrade_data_hub', 'get_tastytrade_data_hub'),
        ]:
            try:
                import importlib
                mod = importlib.import_module(mod_path)
                hub = getattr(mod, func_name)()
                if hub:
                    price = hub.get_quote_price(sym_upper)
                    if price and price > 0:
                        return float(price)
            except Exception:
                pass
        return None

    async def _try_broker_rest_quote(self, symbol: str) -> Optional[float]:
        try:
            from src.services.conditional_orders.router import conditional_order_router
            router = conditional_order_router
            if router and hasattr(router, 'us_service'):
                us_svc = router.us_service
                if us_svc and hasattr(us_svc, 'broker_instances'):
                    for bname, binst in us_svc.broker_instances.items():
                        bkey = bname.lower().replace('_paper', '').replace('_live', '')
                        if bkey == 'trading212':
                            continue
                        if binst and hasattr(binst, 'get_quote'):
                            try:
                                result = binst.get_quote(symbol)
                                if asyncio.iscoroutine(result):
                                    result = await result
                                if result and float(result) > 0:
                                    return float(result)
                            except Exception:
                                pass
        except Exception:
            pass
        return None

    async def _fetch_conditional_quotes(self):
        uncovered = self._get_uncovered_conditional_symbols()
        if not uncovered:
            return

        now = time.time()
        if now - self._last_conditional_quote_ts < _CONDITIONAL_QUOTE_INTERVAL:
            return
        self._last_conditional_quote_ts = now

        for sym in uncovered:
            cross_price = self._try_cross_hub_quote(sym)
            if cross_price:
                with self._quotes_lock:
                    self._quotes[sym] = {'price': cross_price, 'ts': time.time()}
                print(f"[T212-HUB] Cross-hub quote for {sym}: ${cross_price:.4f}")
                continue

            rest_price = await self._try_broker_rest_quote(sym)
            if rest_price:
                with self._quotes_lock:
                    self._quotes[sym] = {'price': rest_price, 'ts': time.time()}
                print(f"[T212-HUB] REST broker quote for conditional {sym}: ${rest_price:.4f}")
                continue

            print(f"[T212-HUB] No quote source for conditional symbol {sym} — cross-hub and REST both failed")

    async def poll_once(self):
        if not self._broker or not self._broker.connected:
            await self._fetch_conditional_quotes()
            return

        try:
            positions = await self._broker.get_positions()
            with self._lock:
                self._positions = positions if isinstance(positions, list) else []
                self._positions_ts = time.time()
                self._is_stale = False
            if self._positions:
                self._update_quotes_from_positions(self._positions)
        except Exception as e:
            print(f"[T212-HUB] Position poll error: {e}")

        try:
            orders = await self._broker.get_pending_orders()
            with self._lock:
                self._orders = orders if isinstance(orders, list) else []
                self._orders_ts = time.time()
        except Exception as e:
            print(f"[T212-HUB] Order poll error: {e}")

        try:
            account = await self._broker.get_account_info()
            with self._lock:
                self._account = account if isinstance(account, dict) else {}
                self._account_ts = time.time()
        except Exception as e:
            print(f"[T212-HUB] Account poll error: {e}")

        has_positions = len(self._positions) > 0
        has_orders = len(self._orders) > 0
        self.update_poll_state(has_positions, has_orders)

        await self._fetch_conditional_quotes()

    async def _poll_loop(self):
        print("[T212-HUB] Polling loop started")
        while self._running:
            try:
                await self.poll_once()
            except Exception as e:
                print(f"[T212-HUB] Poll cycle error: {e}")

            interval = POLL_INTERVALS.get(self._poll_state, 15)

            if self._broker and hasattr(self._broker, '_client'):
                client = self._broker._client
                if hasattr(client, 'is_soft_throttled') and client.is_soft_throttled:
                    interval = max(interval, 15)
                    self._is_stale = True
                    print(f"[T212-HUB] Soft throttle detected, backing off to {interval}s")

            await asyncio.sleep(interval)

        print("[T212-HUB] Polling loop stopped")

    def start(self, loop=None):
        if self._running:
            return
        self._running = True
        target_loop = loop or asyncio.get_event_loop()
        self._task = target_loop.create_task(self._poll_loop())
        print("[T212-HUB] Started")

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        print("[T212-HUB] Stopped")


_hub_instance: Optional[Trading212DataHub] = None
_hub_lock = threading.Lock()


def get_trading212_data_hub(broker=None) -> Trading212DataHub:
    global _hub_instance
    with _hub_lock:
        if _hub_instance is None:
            _hub_instance = Trading212DataHub(broker)
        elif broker and not _hub_instance._broker:
            _hub_instance.set_broker(broker)
        return _hub_instance
