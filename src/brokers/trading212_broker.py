import asyncio
import time
from typing import Optional, Dict, Any, List

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker_interface import BrokerInterface, OrderResult


class Trading212Broker(BrokerInterface):
    TICKER_SUFFIXES = {
        'US': '_US_EQ',
        'UK': '_EQ',
        'DE': '_EQ',
    }

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "Trading212"
        self._api_key = config.get('api_key', '')
        self._api_secret = config.get('api_secret', '')
        self._environment = config.get('environment', 'demo')
        self.is_live = (self._environment == 'live')
        self._client = None
        self._instruments = {}
        self._instruments_ready = False
        self._ticker_cache = {}
        self._reverse_ticker_cache = {}
        self._positions_cache = []
        self._positions_cache_ts = 0
        self._account_cache = {}
        self._account_cache_ts = 0
        self._quote_cache = {}
        self._quote_cache_time = 0
        self._quote_cache_ttl = 3

    async def connect(self) -> bool:
        try:
            from src.services.trading212_client import Trading212Client
            self._client = Trading212Client(self._api_key, self._environment, api_secret=self._api_secret)

            result = await self._client.get_account_summary()
            if not result.get('success'):
                error_msg = result.get('error', 'Unknown')
                print(f"[T212] Connection failed: {error_msg}")
                await self._client.close()
                self.connected = False
                return False

            account_data = result.get('data', {})
            print(f"[T212] Connected to {self._environment.upper()} account")
            if isinstance(account_data, dict):
                free = account_data.get('free', 0)
                print(f"[T212] Available cash: ${free:,.2f}")

            await self._load_instruments()

            self.connected = True
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._event_loop = None
            return True

        except Exception as e:
            print(f"[T212] Connection error: {e}")
            self.connected = False
            return False

    def _schedule_post_order_refresh(self):
        import threading
        _loop = getattr(self, '_event_loop', None)

        def _do_refresh():
            try:
                self._positions_cache = []
                self._positions_cache_ts = 0

                try:
                    from src.services.trading212_data_hub import get_trading212_data_hub
                    hub = get_trading212_data_hub()
                    target_loop = _loop
                    if target_loop and not target_loop.is_closed():
                        asyncio.run_coroutine_threadsafe(hub.poll_once(), target_loop)
                except Exception:
                    pass

                try:
                    from gui_app.live_snapshot import request_force_refresh
                    request_force_refresh()
                except Exception:
                    pass
            except Exception:
                pass
        threading.Timer(5.5, _do_refresh).start()

    async def _load_instruments(self):
        try:
            result = await self._client.get_instruments()
            if result.get('success') and result.get('data'):
                instruments = result['data']
                if isinstance(instruments, list):
                    for inst in instruments:
                        ticker = inst.get('ticker', '')
                        short_name = inst.get('shortName', '') or inst.get('name', '')
                        isin = inst.get('isin', '')
                        self._instruments[ticker] = inst

                        base = ticker.split('_')[0] if '_' in ticker else ticker
                        if base and base not in self._ticker_cache:
                            self._ticker_cache[base] = ticker
                        self._reverse_ticker_cache[ticker] = base

                    self._instruments_ready = True
                    print(f"[T212] Loaded {len(self._instruments)} instruments")
                else:
                    print(f"[T212] Unexpected instruments format")
        except Exception as e:
            print(f"[T212] Failed to load instruments: {e}")

    def _translate_ticker(self, symbol: str) -> Optional[str]:
        if not self._instruments_ready:
            return None

        upper = symbol.upper().strip()

        if upper in self._instruments:
            return upper

        if upper in self._ticker_cache:
            return self._ticker_cache[upper]

        for suffix in ['_US_EQ', '_EQ', '_US']:
            candidate = f"{upper}{suffix}"
            if candidate in self._instruments:
                self._ticker_cache[upper] = candidate
                return candidate

        return None

    def _reverse_translate(self, t212_ticker: str) -> str:
        if t212_ticker in self._reverse_ticker_cache:
            return self._reverse_ticker_cache[t212_ticker]
        base = t212_ticker.split('_')[0] if '_' in t212_ticker else t212_ticker
        return base

    async def disconnect(self):
        if self._client:
            await self._client.close()
        self.connected = False
        print("[T212] Disconnected")

    async def get_account_info(self) -> Dict[str, Any]:
        if not self._client or not self.connected:
            return {'buying_power': 0, 'cash': 0, 'portfolio_value': 0}

        now = time.time()
        if self._account_cache and (now - self._account_cache_ts) < 10:
            return self._account_cache

        try:
            result = await self._client.get_account_summary()
            if result.get('success') and result.get('data'):
                data = result['data']
                info = {
                    'buying_power': float(data.get('free', 0)),
                    'cash': float(data.get('free', 0)),
                    'portfolio_value': float(data.get('total', 0)),
                    'invested': float(data.get('invested', 0)),
                    'ppl': float(data.get('ppiResult', 0)),
                    'result': float(data.get('result', 0)),
                }
                self._account_cache = info
                self._account_cache_ts = now
                return info
        except Exception as e:
            print(f"[T212] Error getting account info: {e}")

        return self._account_cache or {'buying_power': 0, 'cash': 0, 'portfolio_value': 0}

    async def get_positions(self) -> List[Dict[str, Any]]:
        if not self._client or not self.connected:
            return []

        now = time.time()
        if self._positions_cache and (now - self._positions_cache_ts) < 5:
            return self._positions_cache

        try:
            result = await self._client.get_portfolio()
            if result.get('success') and result.get('data'):
                raw_positions = result['data']
                if not isinstance(raw_positions, list):
                    return self._positions_cache or []

                positions = []
                for pos in raw_positions:
                    ticker = pos.get('ticker', '')
                    symbol = self._reverse_translate(ticker)
                    quantity = float(pos.get('quantity', 0))
                    avg_price = float(pos.get('averagePrice', 0))
                    current_price = float(pos.get('currentPrice', 0))
                    ppl = float(pos.get('ppl', 0))

                    positions.append({
                        'symbol': symbol,
                        'ticker': ticker,
                        'quantity': quantity,
                        'avg_cost': avg_price,
                        'current_price': current_price,
                        'unrealized_pnl': ppl,
                        'market_value': quantity * current_price,
                        'asset_type': 'stock',
                        'broker': 'TRADING212',
                    })

                self._positions_cache = positions
                self._positions_cache_ts = now
                return positions
        except Exception as e:
            print(f"[T212] Error fetching positions: {e}")

        return self._positions_cache or []

    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        **kwargs
    ) -> OrderResult:
        if not self._client or not self.connected:
            return OrderResult(success=False, message="Not connected to Trading 212")

        if not self._instruments_ready:
            return OrderResult(success=False, message="Instrument cache still loading. Try again in a few seconds.")

        ticker = self._translate_ticker(symbol)
        if not ticker:
            return OrderResult(
                success=False,
                symbol=symbol,
                action=action,
                message=f"Symbol '{symbol}' not found in Trading 212 instrument list"
            )

        action_upper = action.upper()
        if action_upper in ('STC', 'SELL'):
            qty = -abs(float(quantity))
        else:
            qty = abs(float(quantity))

        try:
            if price and price > 0:
                result = await self._client.place_limit_order(ticker, qty, price)
            else:
                result = await self._client.place_market_order(ticker, qty)

            if result.get('success') and result.get('data'):
                order_data = result['data']
                order_id = str(order_data.get('id', ''))
                fill_qty = order_data.get('filledQuantity', 0)
                status = order_data.get('status', 'UNKNOWN')

                self._schedule_post_order_refresh()

                return OrderResult(
                    success=True,
                    order_id=order_id,
                    symbol=symbol,
                    action=action,
                    quantity=abs(int(quantity)),
                    price=price,
                    message=f"T212 order {order_id} placed (status: {status})"
                )
            else:
                error = result.get('error', 'Unknown error')
                return OrderResult(
                    success=False,
                    symbol=symbol,
                    action=action,
                    message=f"T212 order failed: {error}"
                )

        except Exception as e:
            return OrderResult(
                success=False,
                symbol=symbol,
                action=action,
                message=f"T212 order exception: {e}"
            )

    async def place_option_order(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        **kwargs
    ) -> OrderResult:
        return OrderResult(
            success=False,
            symbol=symbol,
            action=action,
            message="Trading 212 does not support options trading. Order skipped."
        )

    async def get_quote(self, symbol: str) -> Optional[float]:
        now = time.time()
        if now - self._quote_cache_time < self._quote_cache_ttl and symbol.upper() in self._quote_cache:
            return self._quote_cache[symbol.upper()]

        positions = await self.get_positions()
        self._quote_cache_time = now
        self._quote_cache = {}
        for pos in positions:
            sym = pos.get('symbol', '').upper()
            price = pos.get('current_price')
            if sym and price:
                self._quote_cache[sym] = price

        price = self._quote_cache.get(symbol.upper())
        if price:
            return price

        price = self._cross_hub_quote(symbol)
        if price:
            self._quote_cache[symbol.upper()] = price
        return price

    def _cross_hub_quote(self, symbol: str) -> Optional[float]:
        sym_upper = symbol.upper()
        try:
            from src.services.trading212_data_hub import get_trading212_data_hub
            t212_hub = get_trading212_data_hub()
            if t212_hub:
                price = t212_hub.get_quote_price(sym_upper)
                if price and price > 0:
                    return float(price)
        except Exception:
            pass
        for mod_path, func_name in [
            ('src.services.schwab_data_hub', 'get_schwab_data_hub'),
            ('src.services.webull_data_hub', 'get_webull_data_hub'),
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

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if not self._client or not self.connected:
            return {'success': False, 'error': 'Not connected'}

        try:
            result = await self._client.cancel_order(int(order_id))
            if result.get('success'):
                return {'success': True, 'message': f'Order {order_id} cancelled'}
            return {'success': False, 'error': result.get('error', 'Cancel failed')}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def get_pending_orders(self) -> List[Dict[str, Any]]:
        if not self._client or not self.connected:
            return []

        try:
            result = await self._client.get_orders()
            if result.get('success') and result.get('data'):
                orders = result['data']
                if not isinstance(orders, list):
                    return []
                pending = []
                for order in orders:
                    status = order.get('status', '')
                    if status in ('NEW', 'CONFIRMED', 'UNCONFIRMED', 'PARTIALLY_FILLED', 'LOCAL'):
                        ticker = order.get('ticker', '')
                        pending.append({
                            'order_id': str(order.get('id', '')),
                            'symbol': self._reverse_translate(ticker),
                            'ticker': ticker,
                            'side': order.get('side', ''),
                            'quantity': abs(float(order.get('quantity', 0))),
                            'filled_quantity': float(order.get('filledQuantity', 0)),
                            'status': status,
                            'type': order.get('type', ''),
                            'limit_price': order.get('limitPrice'),
                            'stop_price': order.get('stopPrice'),
                            'created_at': order.get('createdAt', ''),
                            'broker': 'TRADING212',
                        })
                return pending
        except Exception as e:
            print(f"[T212] Error fetching pending orders: {e}")
        return []

    async def get_order_history(self, count: int = 20) -> List[Dict[str, Any]]:
        if not self._client or not self.connected:
            return []

        try:
            result = await self._client.get_order_history(limit=count)
            if result.get('success') and result.get('data'):
                data = result['data']
                items = data.get('items', []) if isinstance(data, dict) else data if isinstance(data, list) else []
                history = []
                for order in items:
                    ticker = order.get('ticker', '')
                    history.append({
                        'order_id': str(order.get('id', '')),
                        'symbol': self._reverse_translate(ticker),
                        'ticker': ticker,
                        'side': order.get('side', ''),
                        'quantity': abs(float(order.get('quantity', 0))),
                        'filled_quantity': float(order.get('filledQuantity', 0)),
                        'fill_price': order.get('fillPrice'),
                        'status': order.get('status', ''),
                        'type': order.get('type', ''),
                        'created_at': order.get('dateCreated', ''),
                        'broker': 'TRADING212',
                    })
                return history
        except Exception as e:
            print(f"[T212] Error fetching order history: {e}")
        return []

    @staticmethod
    def test_connection(api_key: str, environment: str = 'demo', api_secret: str = '') -> Dict[str, Any]:
        import asyncio

        async def _test():
            from src.services.trading212_client import Trading212Client
            client = Trading212Client(api_key, environment, api_secret=api_secret)
            try:
                result = await client.get_account_summary()
                if result.get('success') and result.get('data'):
                    data = result['data']
                    return {
                        'success': True,
                        'message': f"Connected to Trading 212 ({environment.upper()})",
                        'account_info': {
                            'cash': data.get('free', 0),
                            'total': data.get('total', 0),
                            'environment': environment,
                        }
                    }
                return {'success': False, 'message': result.get('error', 'Connection failed')}
            finally:
                await client.close()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, _test())
                    return future.result(timeout=15)
            else:
                return loop.run_until_complete(_test())
        except Exception as e:
            return {'success': False, 'message': str(e)}
