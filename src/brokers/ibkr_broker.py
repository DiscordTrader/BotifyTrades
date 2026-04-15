"""
Interactive Brokers (IBKR) Implementation
Professional-grade multi-asset trading
"""

import sys
import os
import asyncio
from typing import Optional, Dict, Any

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    print("[IBKR] ⚠️ nest_asyncio not available — IBKR may fail if event loop is already running")

from ib_insync import IB, Stock, Option, MarketOrder, LimitOrder, util
from datetime import datetime

# Add parent directory to path for absolute imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory


class IBKRBroker(BrokerInterface):
    """Interactive Brokers implementation using ib_insync"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "IBKR"
        self.ib = IB()
        self.paper_trade = config.get('paper_trade', True)
        self.host = config.get('host', '127.0.0.1')
        # Paper trading: 7497, Live trading: 7496
        self.port = config.get('port', 7497 if self.paper_trade else 7496)
        self.client_id = config.get('client_id', 1)
        self._quote_fail_cache = {}
        self._event_loop_broken = False
        self._event_loop_broken_ts = 0
    
    @staticmethod
    def _normalize_expiry_yyyymmdd(expiry: str) -> str:
        """Convert any expiry format to YYYYMMDD for IB contract construction.
        
        Supported: MM/DD, MM/DD/YY, MM/DD/YYYY, YYYY-MM-DD, YYYYMMDD
        """
        from datetime import datetime
        if '/' in expiry:
            parts = expiry.split('/')
            if len(parts) == 2:
                m, d = parts
                y = datetime.now().year
                return f"{y}{int(m):02d}{int(d):02d}"
            elif len(parts) == 3:
                p0, p1, p2 = parts
                if len(p0) == 4:
                    y, m, d = p0, p1, p2
                else:
                    m, d, y = p0, p1, p2
                    if len(y) == 2:
                        y = f"20{y}"
                return f"{int(y)}{int(m):02d}{int(d):02d}"
            raise ValueError(f"Invalid expiry format: {expiry}")
        elif '-' in expiry:
            parts = expiry.split('-')
            if len(parts) == 3:
                y, m, d = parts
                return f"{y}{m.zfill(2)}{d.zfill(2)}"
            raise ValueError(f"Invalid expiry format: {expiry}")
        return expiry

    async def connect(self) -> bool:
        """Connect to Interactive Brokers TWS/Gateway"""
        try:
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._event_loop = asyncio.get_event_loop()
            await self.ib.connectAsync(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                timeout=20
            )
            
            if self.ib.isConnected():
                self.connected = True
                mode = "PAPER" if self.paper_trade else "LIVE"
                print(f"[{self.name}] ✓ Connected successfully ({mode} trading)")
                
                try:
                    account_values = self.ib.accountValues()
                    for av in account_values:
                        if av.tag == 'BuyingPower' and av.currency in ('', 'USD', 'BASE'):
                            print(f"[{self.name}]   Buying power: ${float(av.value):,.2f}")
                            break
                except Exception as e_summary:
                    print(f"[{self.name}] ⚠️ Connected but could not read account values: {e_summary}")
                
                return True
            
            print(f"[{self.name}] ❌ Failed to connect to TWS/Gateway")
            return False
            
        except Exception as e:
            print(f"[{self.name}] ❌ Connection error: {e}")
            print(f"[{self.name}] Make sure TWS or IB Gateway is running on {self.host}:{self.port}")
            return False
    
    async def disconnect(self):
        """Disconnect from Interactive Brokers"""
        if self.ib.isConnected():
            self.ib.disconnect()
        self.connected = False
        print(f"[{self.name}] Disconnected")
    
    def _get_extended_hours_enabled(self) -> bool:
        """Check if extended hours trading is enabled for IBKR.
        
        IBKR outsideRth parameter allows orders to execute during
        pre-market (4:00 AM - 9:30 AM ET) and after-hours (4:00 PM - 8:00 PM ET).
        
        Returns:
            True if extended hours is enabled
        """
        try:
            from gui_app.database import get_broker_extended_hours
            enabled = get_broker_extended_hours('ibkr')
            if enabled:
                print(f"[{self.name}] Extended hours ENABLED - outsideRth=True")
            return enabled
        except ImportError:
            return False
        except Exception as e:
            print(f"[{self.name}] Error checking extended hours setting: {e}")
            return False
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information using async-safe approach"""
        try:
            if not self.ib.isConnected():
                print(f"[{self.name}] ⚠️ get_account_info called but not connected")
                if hasattr(self, '_last_account_info') and self._last_account_info:
                    return dict(self._last_account_info)
                return None

            result = {'buying_power': 0, 'options_buying_power': 0, 'cash': 0, 'portfolio_value': 0}
            need_async_fallback = False
            try:
                account_values = self.ib.accountValues()
                if account_values:
                    for av in account_values:
                        if av.currency in ('', 'USD', 'BASE', 'CAD'):
                            if av.tag == 'BuyingPower':
                                result['buying_power'] = float(av.value)
                            elif av.tag == 'AvailableFunds':
                                result['options_buying_power'] = float(av.value)
                            elif av.tag == 'TotalCashValue':
                                result['cash'] = float(av.value)
                            elif av.tag == 'NetLiquidation':
                                result['portfolio_value'] = float(av.value)
                    if result['buying_power'] <= 0 and result['portfolio_value'] <= 0:
                        need_async_fallback = True
                else:
                    need_async_fallback = True
            except Exception:
                need_async_fallback = True

            if need_async_fallback:
                try:
                    summary = await self.ib.accountSummaryAsync()
                    for item in summary:
                        if item.tag == 'BuyingPower':
                            result['buying_power'] = float(item.value)
                        elif item.tag == 'AvailableFunds':
                            result['options_buying_power'] = float(item.value)
                        elif item.tag == 'TotalCashValue':
                            result['cash'] = float(item.value)
                        elif item.tag == 'NetLiquidation':
                            result['portfolio_value'] = float(item.value)
                except Exception as e2:
                    print(f"[{self.name}] ⚠️ accountSummaryAsync fallback failed: {e2}")

            if result['options_buying_power'] <= 0:
                result['options_buying_power'] = result['buying_power']
            
            self._last_account_info = result
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            if hasattr(self, '_last_account_info') and self._last_account_info:
                print(f"[{self.name}] Returning last known good account info after error")
                return dict(self._last_account_info)
            return None
    
    async def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        try:
            positions = self.ib.positions()
            result = {}
            for pos in positions:
                if hasattr(pos.contract, 'symbol'):
                    symbol = pos.contract.symbol
                    quantity = int(pos.position)
                    result[symbol] = quantity
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return {}
    
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        try:
            trade = None
            for t in self.ib.openTrades():
                if str(t.order.orderId) == str(order_id):
                    trade = t
                    break
            if not trade:
                return {'success': False, 'msg': f'Order {order_id} not found in open trades'}
            
            self.ib.cancelOrder(trade.order)
            print(f"[{self.name}] ✓ Cancelled order {order_id}")
            return {'success': True, 'order_id': order_id}
        except Exception as e:
            print(f"[{self.name}] Cancel order {order_id} error: {e}")
            return {'success': False, 'msg': str(e)}

    async def get_pending_orders(self) -> list:
        """Get all pending/open orders from TWS/Gateway."""
        try:
            if not self.ib.isConnected():
                return []
            trades = self.ib.openTrades()
            pending = []
            for trade in trades:
                order = trade.order
                contract = trade.contract
                status = trade.orderStatus.status if trade.orderStatus else 'Unknown'
                if status in ('PreSubmitted', 'Submitted', 'PendingSubmit', 'PendingCancel'):
                    pending.append({
                        'order_id': str(order.orderId),
                        'broker_order_id': str(order.orderId),
                        'symbol': contract.symbol if contract else '',
                        'quantity': int(order.totalQuantity) if hasattr(order, 'totalQuantity') else 0,
                        'limit_price': float(order.lmtPrice) if hasattr(order, 'lmtPrice') and order.lmtPrice else None,
                        'action': order.action if hasattr(order, 'action') else '',
                        'order_type': order.orderType if hasattr(order, 'orderType') else '',
                        'status': status,
                        'asset_type': 'option' if contract and contract.secType == 'OPT' else 'stock'
                    })
            return pending
        except Exception as e:
            print(f"[{self.name}] Error getting pending orders: {e}")
            return []

    async def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get the status of a specific order by order ID."""
        try:
            if not self.ib.isConnected():
                return None
            for trade in self.ib.openTrades():
                if str(trade.order.orderId) == str(order_id):
                    status = trade.orderStatus.status if trade.orderStatus else 'Unknown'
                    filled_qty = int(trade.orderStatus.filled) if trade.orderStatus else 0
                    remaining = int(trade.orderStatus.remaining) if trade.orderStatus else 0
                    avg_price = float(trade.orderStatus.avgFillPrice) if trade.orderStatus and trade.orderStatus.avgFillPrice else 0
                    ib_to_internal = {
                        'Filled': 'FILLED', 'Cancelled': 'CANCELLED', 'Inactive': 'CANCELLED',
                        'Submitted': 'WORKING', 'PreSubmitted': 'PENDING',
                        'PendingSubmit': 'PENDING', 'PendingCancel': 'PENDING_CANCEL',
                        'ApiCancelled': 'CANCELLED'
                    }
                    return {
                        'order_id': str(order_id),
                        'status': ib_to_internal.get(status, status),
                        'filled_qty': filled_qty,
                        'filled_quantity': filled_qty,
                        'remaining_quantity': remaining,
                        'avg_fill_price': avg_price,
                        'raw_status': status
                    }
            for trade in self.ib.trades():
                if str(trade.order.orderId) == str(order_id):
                    status = trade.orderStatus.status if trade.orderStatus else 'Unknown'
                    filled_qty = int(trade.orderStatus.filled) if trade.orderStatus else 0
                    avg_price = float(trade.orderStatus.avgFillPrice) if trade.orderStatus and trade.orderStatus.avgFillPrice else 0
                    ib_to_internal = {
                        'Filled': 'FILLED', 'Cancelled': 'CANCELLED', 'Inactive': 'CANCELLED',
                        'Submitted': 'WORKING', 'PreSubmitted': 'PENDING',
                        'PendingSubmit': 'PENDING', 'PendingCancel': 'PENDING_CANCEL',
                        'ApiCancelled': 'CANCELLED'
                    }
                    return {
                        'order_id': str(order_id),
                        'status': ib_to_internal.get(status, status),
                        'filled_qty': filled_qty,
                        'filled_quantity': filled_qty,
                        'remaining_quantity': 0,
                        'avg_fill_price': avg_price,
                        'raw_status': status
                    }
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting order status for {order_id}: {e}")
            return None

    async def get_positions_detailed(self) -> list:
        """Get detailed positions for sync service compatibility."""
        try:
            if not self.ib.isConnected():
                return []
            raw_positions = self.ib.positions()
            positions = []
            for pos in raw_positions:
                contract = pos.contract
                quantity = abs(int(pos.position))
                if quantity == 0:
                    continue
                avg_cost = float(pos.avgCost) if pos.avgCost else 0
                entry = {
                    'symbol': contract.symbol,
                    'quantity': quantity,
                    'position_id': str(contract.conId),
                    'asset_type': 'option' if contract.secType == 'OPT' else 'stock'
                }
                if contract.secType == 'OPT':
                    entry['avg_price'] = avg_cost / 100 if avg_cost > 0 else 0
                    expiry_raw = contract.lastTradeDateOrContractMonth
                    entry['expiry'] = f"{expiry_raw[:4]}-{expiry_raw[4:6]}-{expiry_raw[6:8]}" if len(expiry_raw) == 8 else expiry_raw
                    entry['strike'] = contract.strike
                    entry['call_put'] = contract.right
                else:
                    entry['avg_price'] = avg_cost
                positions.append(entry)
            return positions
        except Exception as e:
            print(f"[{self.name}] Error getting detailed positions: {e}")
            return []

    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None
    ) -> OrderResult:
        """Place a stock order"""
        try:
            # Create contract
            contract = Stock(symbol, 'SMART', 'USD')
            
            await self.ib.qualifyContractsAsync(contract)
            
            side = 'BUY' if action == 'BTO' else 'SELL'
            
            if price is None:
                order = MarketOrder(side, quantity)
            else:
                order = LimitOrder(side, quantity, price)
            
            order.outsideRth = self._get_extended_hours_enabled()
            
            trade = self.ib.placeOrder(contract, order)
            
            # Wait for order to be acknowledged
            await asyncio.sleep(1)
            
            if trade and trade.orderStatus.status != 'Cancelled':
                return OrderResult(
                    success=True,
                    order_id=str(trade.order.orderId),
                    message=f"Stock order placed: {action} {quantity} {symbol}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                status = trade.orderStatus.status if trade else 'Unknown'
                return OrderResult(
                    success=False,
                    message=f"Order failed with status: {status}",
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            error_msg = str(e)
            
            # Handle insufficient funds
            if 'insufficient' in error_msg.lower():
                try:
                    account_info = await self.get_account_info()
                    buying_power = account_info['buying_power']
                    
                    # Get current price
                    current_price = await self.get_quote(symbol)
                    
                    if current_price and buying_power > 0:
                        # Calculate max quantity
                        max_qty = int(buying_power / current_price)
                        
                        if max_qty > 0:
                            print(f"[{self.name}] Auto-adjusting: {quantity} → {max_qty} shares")
                            return await self.place_stock_order(symbol, action, max_qty, price)
                except Exception as adjust_error:
                    print(f"[{self.name}] Auto-adjust failed: {adjust_error}")
            
            return OrderResult(
                success=False,
                message=f"Exception: {error_msg}",
                symbol=symbol,
                action=action
            )
    
    async def place_option_order(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str,
        action: str,
        quantity: int,
        price: Optional[float] = None
    ) -> OrderResult:
        """Place an options order"""
        try:
            from datetime import datetime
            expiry_formatted = self._normalize_expiry_yyyymmdd(expiry)
            
            # Create option contract
            right = 'C' if option_type.lower() in ['c', 'call'] else 'P'
            contract = Option(symbol, expiry_formatted, strike, right, 'SMART')
            
            await self.ib.qualifyContractsAsync(contract)
            
            # Create order
            side = 'BUY' if action == 'BTO' else 'SELL'
            
            if price is None:
                # Market order
                order = MarketOrder(side, quantity)
            else:
                # Limit order
                order = LimitOrder(side, quantity, price)
            
            # Enable extended hours trading if configured
            order.outsideRth = self._get_extended_hours_enabled()
            
            # Place order
            trade = self.ib.placeOrder(contract, order)
            
            # Wait for acknowledgment
            await asyncio.sleep(1)
            
            if trade and trade.orderStatus.status != 'Cancelled':
                return OrderResult(
                    success=True,
                    order_id=str(trade.order.orderId),
                    message=f"Option order placed: {action} {quantity} {symbol} ${strike}{option_type} {expiry}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                status = trade.orderStatus.status if trade else 'Unknown'
                return OrderResult(
                    success=False,
                    message=f"Order failed with status: {status}",
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            return OrderResult(
                success=False,
                message=f"Exception: {str(e)}",
                symbol=symbol,
                action=action
            )
    
    def _is_on_ib_loop(self) -> bool:
        """Check if we're currently running on the IB event loop."""
        if not self._event_loop:
            return False
        try:
            return asyncio.get_running_loop() is self._event_loop
        except RuntimeError:
            return False

    async def _ib_get_quote_impl(self, symbol: str) -> Optional[float]:
        """Internal: fetch quote via IB API — must run on IB's event loop."""
        contract = Stock(symbol, 'SMART', 'USD')
        await self.ib.qualifyContractsAsync(contract)
        
        ticker = self.ib.reqMktData(contract, '', False, False)
        await asyncio.sleep(2)
        
        if ticker.last and ticker.last > 0:
            price = float(ticker.last)
        elif ticker.bid and ticker.bid > 0 and ticker.ask and ticker.ask > 0:
            price = round((float(ticker.bid) + float(ticker.ask)) / 2, 4)
        elif ticker.bid and ticker.bid > 0:
            price = float(ticker.bid)
        elif ticker.ask and ticker.ask > 0:
            price = float(ticker.ask)
        else:
            price = None
        
        self.ib.cancelMktData(contract)
        return price

    _quote_fail_cache: Dict[str, float] = {}
    _QUOTE_FAIL_BACKOFF = 60.0
    _QUOTE_FAIL_BACKOFF_EVENT_LOOP = 600.0
    _event_loop_broken: bool = False
    _event_loop_broken_ts: float = 0

    def _check_event_loop_reset(self, now: float):
        if self._event_loop_broken and now - self._event_loop_broken_ts >= self._QUOTE_FAIL_BACKOFF_EVENT_LOOP:
            print(f"[{self.name}] ✓ Event loop circuit breaker reset after {self._QUOTE_FAIL_BACKOFF_EVENT_LOOP:.0f}s — retrying REST quotes")
            self._event_loop_broken = False
            self._event_loop_broken_ts = 0
            self._quote_fail_cache.clear()

    async def get_quote(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol — checks hub cache first"""
        now = __import__('time').time()
        self._check_event_loop_reset(now)
        fail_ts = self._quote_fail_cache.get(symbol, 0)
        backoff = self._QUOTE_FAIL_BACKOFF_EVENT_LOOP if self._event_loop_broken else self._QUOTE_FAIL_BACKOFF
        if fail_ts and now - fail_ts < backoff:
            return None

        try:
            try:
                from src.services.ibkr_data_hub import get_ibkr_data_hub
                hub = get_ibkr_data_hub()
                if hub.is_streaming():
                    cached = hub.get_quote_price(symbol)
                    if cached and cached > 0:
                        self._quote_fail_cache.pop(symbol, None)
                        return cached
                    if not self._event_loop_broken:
                        hub.subscribe_symbol(symbol)
            except (ImportError, Exception):
                pass

            if self._event_loop_broken:
                self._quote_fail_cache[symbol] = now
                return None

            if self._is_on_ib_loop():
                result = await self._ib_get_quote_impl(symbol)
                if result and result > 0:
                    self._quote_fail_cache.pop(symbol, None)
                    self._event_loop_broken = False
                    return result
            elif self._event_loop and self._event_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self._ib_get_quote_impl(symbol), self._event_loop
                )
                try:
                    result = await asyncio.wait_for(
                        asyncio.wrap_future(future), timeout=10
                    )
                    if result and result > 0:
                        self._quote_fail_cache.pop(symbol, None)
                        self._event_loop_broken = False
                        return result
                except asyncio.TimeoutError:
                    future.cancel()

            self._quote_fail_cache[symbol] = now
            return None
        except Exception as e:
            if 'event loop' in str(e).lower():
                if not self._event_loop_broken:
                    print(f"[{self.name}] ⚠️ Event loop conflict detected — IBKR REST quotes disabled for 10min (hub-only mode)")
                    self._event_loop_broken = True
                    self._event_loop_broken_ts = now
                self._quote_fail_cache[symbol] = now
            else:
                print(f"[{self.name}] Error getting quote for {symbol}: {e}")
                self._quote_fail_cache[symbol] = now
            return None
    
    async def _ib_get_quote_detailed_impl(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Internal: fetch detailed quote via IB API — must run on IB's event loop."""
        contract = Stock(symbol, 'SMART', 'USD')
        await self.ib.qualifyContractsAsync(contract)
        
        ticker = self.ib.reqMktData(contract, '', False, False)
        await asyncio.sleep(2)
        
        result = {
            'symbol': symbol,
            'bid': float(ticker.bid) if ticker.bid and ticker.bid > 0 else 0,
            'ask': float(ticker.ask) if ticker.ask and ticker.ask > 0 else 0,
            'last': float(ticker.last) if ticker.last and ticker.last > 0 else 0,
            'close': float(ticker.close) if ticker.close and ticker.close > 0 else 0,
            'volume': int(ticker.volume) if ticker.volume else 0,
            'source': 'IBKR'
        }
        
        self.ib.cancelMktData(contract)
        return result

    async def get_quote_detailed(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get detailed quote with bid/ask/last — checks hub cache first"""
        now = __import__('time').time()
        self._check_event_loop_reset(now)
        fail_key = f"detailed_{symbol}"
        fail_ts = self._quote_fail_cache.get(fail_key, 0)
        backoff = self._QUOTE_FAIL_BACKOFF_EVENT_LOOP if self._event_loop_broken else self._QUOTE_FAIL_BACKOFF
        if fail_ts and now - fail_ts < backoff:
            return None
        try:
            if not self.ib.isConnected():
                return None
            
            try:
                from src.services.ibkr_data_hub import get_ibkr_data_hub
                hub = get_ibkr_data_hub()
                if hub.is_streaming():
                    cached = hub.get_quote_detailed(symbol, max_age=10)
                    if cached and (cached.get('last', 0) > 0 or cached.get('bid', 0) > 0):
                        return cached
                    if not self._event_loop_broken:
                        hub.subscribe_symbol(symbol)
            except (ImportError, Exception):
                pass

            if self._event_loop_broken:
                self._quote_fail_cache[fail_key] = now
                return None

            if self._is_on_ib_loop():
                return await self._ib_get_quote_detailed_impl(symbol)
            elif self._event_loop and self._event_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self._ib_get_quote_detailed_impl(symbol), self._event_loop
                )
                try:
                    return await asyncio.wait_for(
                        asyncio.wrap_future(future), timeout=10
                    )
                except asyncio.TimeoutError:
                    future.cancel()
                    self._quote_fail_cache[fail_key] = now
                    return None
            else:
                self._quote_fail_cache[fail_key] = now
                return None
        except Exception as e:
            if 'event loop' in str(e).lower():
                if not self._event_loop_broken:
                    print(f"[{self.name}] ⚠️ Event loop conflict detected — IBKR REST quotes disabled for 10min (hub-only mode)")
                    self._event_loop_broken = True
                    self._event_loop_broken_ts = now
            else:
                print(f"[{self.name}] Error getting detailed quote for {symbol}: {e}")
            self._quote_fail_cache[fail_key] = now
            return None
    
    async def _ib_get_option_quote_impl(self, symbol: str, strike: float, expiry: str, option_type: str) -> Optional[Dict[str, Any]]:
        """Internal: fetch option quote via IB API — must run on IB's event loop."""
        exp_ib = expiry.replace('-', '')
        right = 'C' if option_type.upper() in ['C', 'CALL'] else 'P'
        
        contract = Option(symbol, exp_ib, strike, right, 'SMART')
        qualified = await self.ib.qualifyContractsAsync(contract)
        
        if not qualified:
            return None
        
        ticker = self.ib.reqMktData(contract, '', False, False)
        await asyncio.sleep(2)
        
        result = {
            'symbol': symbol,
            'strike': strike,
            'expiry': expiry,
            'type': option_type,
            'bid': float(ticker.bid) if ticker.bid and ticker.bid > 0 else 0,
            'ask': float(ticker.ask) if ticker.ask and ticker.ask > 0 else 0,
            'last': float(ticker.last) if ticker.last and ticker.last > 0 else 0,
            'volume': int(ticker.volume) if ticker.volume else 0,
            'open_interest': 0,
            'source': 'IBKR'
        }
        
        self.ib.cancelMktData(contract)
        return result

    async def get_option_quote(self, symbol: str, strike: float, expiry: str, option_type: str) -> Optional[Dict[str, Any]]:
        """Get real-time option quote for signal verification"""
        self._check_event_loop_reset(__import__('time').time())
        if self._event_loop_broken:
            return None
        try:
            if not self.ib.isConnected():
                return None
            
            if self._is_on_ib_loop():
                return await self._ib_get_option_quote_impl(symbol, strike, expiry, option_type)
            elif self._event_loop and self._event_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self._ib_get_option_quote_impl(symbol, strike, expiry, option_type), self._event_loop
                )
                try:
                    return await asyncio.wait_for(
                        asyncio.wrap_future(future), timeout=10
                    )
                except asyncio.TimeoutError:
                    future.cancel()
                    return None
            else:
                return None
        except Exception as e:
            if 'event loop' in str(e).lower():
                if not self._event_loop_broken:
                    print(f"[{self.name}] ⚠️ Event loop conflict detected — IBKR REST quotes disabled for 10min")
                    self._event_loop_broken = True
                    self._event_loop_broken_ts = __import__('time').time()
            else:
                print(f"[{self.name}] Error getting option quote for {symbol} {strike}{option_type} {expiry}: {e}")
            return None
    
    async def get_options_expiration_dates(self, symbol: str) -> list:
        """Get all available option expiration dates for a symbol"""
        try:
            if not self.ib.isConnected():
                print(f"[{self.name}] Not connected - cannot get expirations")
                return []
            
            stock = Stock(symbol, 'SMART', 'USD')
            await self.ib.qualifyContractsAsync(stock)
            
            chains = await self.ib.reqSecDefOptParamsAsync(
                stock.symbol, 
                '', 
                stock.secType, 
                stock.conId
            )
            
            if not chains:
                return []
            
            # Extract unique expirations
            expirations = set()
            for chain in chains:
                for exp in chain.expirations:
                    try:
                        exp_date = datetime.strptime(exp, '%Y%m%d')
                        expirations.add(exp_date.strftime('%Y-%m-%d'))
                    except:
                        continue
            
            sorted_exp = sorted(list(expirations))
            print(f"[{self.name}] Found {len(sorted_exp)} expirations for {symbol}")
            return sorted_exp
            
        except Exception as e:
            print(f"[{self.name}] Error getting expirations for {symbol}: {e}")
            return []
    
    async def get_option_chain(self, symbol: str, expiration_date: str) -> Dict[str, Any]:
        """Get option chain for a symbol and expiration date"""
        try:
            if not self.ib.isConnected():
                print(f"[{self.name}] Not connected - cannot get option chain")
                return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': 'IBKR'}
            
            # Get stock price first
            stock_price = await self.get_quote(symbol)
            
            # Convert expiry format from YYYY-MM-DD to YYYYMMDD
            exp_ib = expiration_date.replace('-', '')
            
            stock = Stock(symbol, 'SMART', 'USD')
            await self.ib.qualifyContractsAsync(stock)
            
            chains = await self.ib.reqSecDefOptParamsAsync(
                stock.symbol, 
                '', 
                stock.secType, 
                stock.conId
            )
            
            if not chains:
                return {'calls': [], 'puts': [], 'stock_price': stock_price, 'data_source': 'IBKR'}
            
            # Find strikes for this expiration
            strikes = set()
            for chain in chains:
                if exp_ib in chain.expirations:
                    strikes.update(chain.strikes)
            
            if not strikes:
                return {'calls': [], 'puts': [], 'stock_price': stock_price, 'data_source': 'IBKR'}
            
            calls = []
            puts = []
            
            # Build option contracts for each strike
            sorted_strikes = sorted(strikes)
            
            # Filter to ATM +/- 20 strikes for performance
            if stock_price:
                atm_strikes = [s for s in sorted_strikes if abs(s - stock_price) / stock_price < 0.3]
            else:
                atm_strikes = sorted_strikes[:40]
            
            for strike in atm_strikes:
                for right in ['C', 'P']:
                    try:
                        contract = Option(symbol, exp_ib, strike, right, 'SMART')
                        qualified = await self.ib.qualifyContractsAsync(contract)
                        
                        if qualified:
                            option_data = {
                                'strike': strike,
                                'symbol': f"{symbol}{exp_ib}{right}{int(strike*1000):08d}",
                                'type': 'call' if right == 'C' else 'put',
                                'expiry': expiration_date,
                                'bid': 0,
                                'ask': 0,
                                'last': 0,
                                'volume': 0,
                                'open_interest': 0,
                                'iv': 0,
                                'delta': 0,
                                'gamma': 0,
                                'theta': 0,
                                'vega': 0
                            }
                            
                            if right == 'C':
                                calls.append(option_data)
                            else:
                                puts.append(option_data)
                    except Exception as e:
                        continue
            
            return {
                'calls': calls,
                'puts': puts,
                'stock_price': stock_price,
                'data_source': 'IBKR',
                'expiration': expiration_date,
                'symbol': symbol
            }
            
        except Exception as e:
            print(f"[{self.name}] Error getting option chain for {symbol}: {e}")
            return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': 'IBKR'}


# Register this broker with the factory
BrokerFactory.register_broker('IBKR', IBKRBroker)
