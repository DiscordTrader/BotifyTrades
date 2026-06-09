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

import time

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

    MAX_ORDER_SIZE = 70000

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
        self._reconnect_in_progress = False
        self._last_reconnect_ts = 0.0
        self._RECONNECT_COOLDOWN = 5.0
        self._MAX_RECONNECT_DELAY = 120.0
        self._consecutive_reconnect_failures = 0
    
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
                self._consecutive_reconnect_failures = 0
                mode = "PAPER" if self.paper_trade else "LIVE"
                print(f"[{self.name}] ✓ Connected successfully ({mode} trading)")

                self.ib.disconnectedEvent += self._on_disconnected

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
        try:
            self.ib.disconnectedEvent -= self._on_disconnected
        except Exception:
            pass
        if self.ib.isConnected():
            self.ib.disconnect()
        self.connected = False
        print(f"[{self.name}] Disconnected")

    def _on_disconnected(self):
        self.connected = False
        print(f"[{self.name}] ⚠️ TWS/Gateway disconnected — scheduling auto-reconnect")
        if self._event_loop and not self._event_loop.is_closed():
            self._event_loop.call_soon_threadsafe(
                lambda: self._event_loop.create_task(self._auto_reconnect())
            )

    async def _auto_reconnect(self):
        if self._reconnect_in_progress:
            return
        self._reconnect_in_progress = True
        try:
            delay = min(
                self._RECONNECT_COOLDOWN * (2 ** self._consecutive_reconnect_failures),
                self._MAX_RECONNECT_DELAY
            )
            elapsed = time.time() - self._last_reconnect_ts
            if elapsed < delay:
                wait = delay - elapsed
                print(f"[{self.name}] Waiting {wait:.0f}s before reconnect attempt...")
                await asyncio.sleep(wait)

            for attempt in range(1, 4):
                self._last_reconnect_ts = time.time()
                print(f"[{self.name}] 🔄 Reconnect attempt {attempt}/3...")
                try:
                    if self.ib.isConnected():
                        try:
                            self.ib.disconnectedEvent -= self._on_disconnected
                        except Exception:
                            pass
                        self.ib.disconnect()
                        await asyncio.sleep(2)

                    self.ib = IB()
                    await self.ib.connectAsync(
                        host=self.host, port=self.port,
                        clientId=self.client_id, timeout=20
                    )
                    if self.ib.isConnected():
                        self.connected = True
                        self._consecutive_reconnect_failures = 0
                        self.ib.disconnectedEvent += self._on_disconnected
                        print(f"[{self.name}] ✅ Reconnected successfully (attempt {attempt})")
                        try:
                            from src.services.ibkr_data_hub import get_ibkr_data_hub
                            hub = get_ibkr_data_hub()
                            hub.attach_broker(self, self._event_loop)
                        except Exception:
                            pass
                        return
                except Exception as e:
                    print(f"[{self.name}] ❌ Reconnect attempt {attempt} failed: {e}")
                if attempt < 3:
                    await asyncio.sleep(5 * attempt)

            self._consecutive_reconnect_failures += 1
            print(f"[{self.name}] ❌ All reconnect attempts failed — will retry in {min(self._RECONNECT_COOLDOWN * (2 ** self._consecutive_reconnect_failures), self._MAX_RECONNECT_DELAY):.0f}s")
        finally:
            self._reconnect_in_progress = False

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
            positions = await asyncio.to_thread(self.ib.positions)
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
            open_trades = await asyncio.to_thread(self.ib.openTrades)
            for t in open_trades:
                if str(t.order.orderId) == str(order_id):
                    trade = t
                    break
            if not trade:
                return {'success': False, 'msg': f'Order {order_id} not found in open trades'}

            await asyncio.to_thread(self.ib.cancelOrder, trade.order)
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
            trades = await asyncio.to_thread(self.ib.openTrades)
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
                        'stop_price': float(order.auxPrice) if hasattr(order, 'auxPrice') and order.auxPrice else None,
                        'action': order.action if hasattr(order, 'action') else '',
                        'order_type': order.orderType if hasattr(order, 'orderType') else '',
                        'status': status,
                        'asset_type': 'option' if contract and contract.secType == 'OPT' else 'stock',
                        'oca_group': getattr(order, 'ocaGroup', '') or '',
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
            ib_to_internal = {
                'Filled': 'FILLED', 'Cancelled': 'CANCELLED', 'Inactive': 'CANCELLED',
                'Submitted': 'WORKING', 'PreSubmitted': 'PENDING',
                'PendingSubmit': 'PENDING', 'PendingCancel': 'PENDING_CANCEL',
                'ApiCancelled': 'CANCELLED'
            }
            for trade in await asyncio.to_thread(self.ib.openTrades):
                if str(trade.order.orderId) == str(order_id):
                    status = trade.orderStatus.status if trade.orderStatus else 'Unknown'
                    filled_qty = int(trade.orderStatus.filled) if trade.orderStatus else 0
                    remaining = int(trade.orderStatus.remaining) if trade.orderStatus else 0
                    avg_price = float(trade.orderStatus.avgFillPrice) if trade.orderStatus and trade.orderStatus.avgFillPrice else 0
                    return {
                        'order_id': str(order_id),
                        'status': ib_to_internal.get(status, status),
                        'filled_qty': filled_qty,
                        'filled_quantity': filled_qty,
                        'remaining_quantity': remaining,
                        'avg_fill_price': avg_price,
                        'raw_status': status
                    }
            for trade in await asyncio.to_thread(self.ib.trades):
                if str(trade.order.orderId) == str(order_id):
                    status = trade.orderStatus.status if trade.orderStatus else 'Unknown'
                    filled_qty = int(trade.orderStatus.filled) if trade.orderStatus else 0
                    avg_price = float(trade.orderStatus.avgFillPrice) if trade.orderStatus and trade.orderStatus.avgFillPrice else 0
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
        """Get detailed positions matching Schwab/live_snapshot field contract."""
        try:
            if not self.ib.isConnected():
                return []

            portfolio_prices = {}
            try:
                for item in await asyncio.to_thread(self.ib.portfolio):
                    if item.contract and item.marketPrice and item.marketPrice > 0:
                        portfolio_prices[item.contract.conId] = float(item.marketPrice)
            except Exception:
                pass

            raw_positions = await asyncio.to_thread(self.ib.positions)
            positions = []
            for pos in raw_positions:
                contract = pos.contract
                quantity = abs(int(pos.position))
                if quantity == 0:
                    continue
                avg_cost_raw = float(pos.avgCost) if pos.avgCost else 0
                is_option = contract.secType == 'OPT'

                current_price = 0.0
                try:
                    tickers = await asyncio.to_thread(self.ib.tickers)
                    for t in tickers:
                        if t.contract and t.contract.conId == contract.conId:
                            if t.last and t.last > 0:
                                current_price = float(t.last)
                            elif t.bid and t.ask and t.bid > 0 and t.ask > 0:
                                current_price = (float(t.bid) + float(t.ask)) / 2
                            break
                except Exception:
                    pass

                if current_price <= 0:
                    current_price = portfolio_prices.get(contract.conId, 0.0)
                if current_price <= 0:
                    try:
                        from src.services.ibkr_data_hub import get_ibkr_data_hub
                        hub = get_ibkr_data_hub()
                        hub_price = hub.get_quote_price(contract.symbol)
                        if hub_price and hub_price > 0:
                            current_price = hub_price
                    except Exception:
                        pass

                if is_option:
                    avg_cost = avg_cost_raw / 100 if avg_cost_raw > 0 else 0
                else:
                    avg_cost = avg_cost_raw

                unrealized_pl = (current_price - avg_cost) * quantity if avg_cost > 0 and current_price > 0 else 0.0
                if is_option:
                    unrealized_pl *= 100

                entry = {
                    'symbol': contract.symbol,
                    'quantity': quantity,
                    'avg_cost': avg_cost,
                    'current_price': current_price,
                    'unrealized_pl': unrealized_pl,
                    'asset': 'option' if is_option else 'stock',
                    'position_id': str(contract.conId),
                }
                if is_option:
                    expiry_raw = contract.lastTradeDateOrContractMonth
                    entry['expiry'] = f"{expiry_raw[:4]}-{expiry_raw[4:6]}-{expiry_raw[6:8]}" if len(expiry_raw) == 8 else expiry_raw
                    entry['strike'] = contract.strike
                    entry['direction'] = contract.right
                    entry['raw_symbol'] = f"{contract.symbol}_{expiry_raw}_{contract.strike}_{contract.right}"
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
        price: Optional[float] = None,
        _auto_adjust_depth: int = 0
    ) -> OrderResult:
        """Place a stock order"""
        if not self.ib.isConnected():
            return OrderResult(success=False, message="IBKR not connected to TWS/Gateway", symbol=symbol, action=action)
        try:
            # Create contract
            contract = Stock(symbol, 'SMART', 'USD')
            
            await self.ib.qualifyContractsAsync(contract)

            side = 'BUY' if action == 'BTO' else 'SELL'

            if quantity > self.MAX_ORDER_SIZE:
                print(f"[{self.name}] ⚠️ Order size {quantity} exceeds IBKR max {self.MAX_ORDER_SIZE} — capping")
                quantity = self.MAX_ORDER_SIZE

            if price is None:
                order = MarketOrder(side, quantity)
            else:
                # SEC Rule 612: penny increments for NMS stocks >= $1.00
                if price >= 1.0:
                    price = round(price, 2)
                else:
                    price = round(price, 4)
                order = LimitOrder(side, quantity, price)

            order.outsideRth = self._get_extended_hours_enabled()

            trade = await asyncio.to_thread(self.ib.placeOrder, contract, order)

            filled_price = await self._wait_for_fill(trade, symbol, timeout=10)

            status = trade.orderStatus.status if trade and trade.orderStatus else 'Unknown'
            if status in ('Cancelled', 'Inactive'):
                await asyncio.sleep(2)
                status = trade.orderStatus.status if trade and trade.orderStatus else status
            if status in ('Cancelled', 'Inactive'):
                reject_reason = self._extract_rejection_reason(trade)
                return OrderResult(
                    success=False,
                    message=reject_reason,
                    symbol=symbol,
                    action=action
                )
            avg_price = float(trade.orderStatus.avgFillPrice) if trade.orderStatus and trade.orderStatus.avgFillPrice else price
            return OrderResult(
                success=True,
                order_id=str(trade.order.orderId),
                message=f"Stock order placed: {action} {quantity} {symbol} (status={status})",
                price=avg_price,
                quantity=quantity,
                symbol=symbol,
                action=action
            )

        except Exception as e:
            error_msg = str(e)

            if 'insufficient' in error_msg.lower() and _auto_adjust_depth < 1:
                try:
                    account_info = await self.get_account_info()
                    buying_power = account_info['buying_power']
                    current_price = await self.get_quote(symbol)
                    if current_price and buying_power > 0:
                        max_qty = int(buying_power / current_price)
                        if 0 < max_qty < quantity:
                            print(f"[{self.name}] Auto-adjusting: {quantity} → {max_qty} shares")
                            return await self.place_stock_order(symbol, action, max_qty, price, _auto_adjust_depth=1)
                except Exception as adjust_error:
                    print(f"[{self.name}] Auto-adjust failed: {adjust_error}")
            
            return OrderResult(
                success=False,
                message=f"IBKR error: {error_msg}",
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
        if not self.ib.isConnected():
            return OrderResult(success=False, message="IBKR not connected to TWS/Gateway", symbol=symbol, action=action)
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
                price = round(price, 2)
                order = LimitOrder(side, quantity, price)
            
            # Enable extended hours trading if configured
            order.outsideRth = self._get_extended_hours_enabled()
            
            trade = await asyncio.to_thread(self.ib.placeOrder, contract, order)

            filled_price = await self._wait_for_fill(trade, symbol, timeout=10)

            status = trade.orderStatus.status if trade and trade.orderStatus else 'Unknown'
            if status in ('Cancelled', 'Inactive'):
                await asyncio.sleep(2)
                status = trade.orderStatus.status if trade and trade.orderStatus else status
            if status in ('Cancelled', 'Inactive'):
                reject_reason = self._extract_rejection_reason(trade)
                return OrderResult(
                    success=False,
                    message=reject_reason,
                    symbol=symbol,
                    action=action
                )
            avg_price = float(trade.orderStatus.avgFillPrice) if trade.orderStatus and trade.orderStatus.avgFillPrice else price
            return OrderResult(
                success=True,
                order_id=str(trade.order.orderId),
                message=f"Option order placed: {action} {quantity} {symbol} ${strike}{option_type} {expiry} (status={status})",
                price=avg_price,
                quantity=quantity,
                symbol=symbol,
                action=action
            )

        except Exception as e:
            return OrderResult(
                success=False,
                message=f"IBKR error: {str(e)}",
                symbol=symbol,
                action=action
            )
    
    def _extract_rejection_reason(self, trade) -> str:
        """Extract human-readable rejection reason from IBKR trade log entries."""
        _IBKR_REASON_MAP = {
            'closing-only': 'Stock is in CLOSING-ONLY mode at IBKR — new positions blocked by broker risk management',
            'No Trading Permission': 'No trading permission for this product at IBKR — check Account Settings → Trading Permissions',
            'Customer Ineligible': 'Customer ineligible for this product at IBKR',
            'insufficient': 'Insufficient funds or buying power at IBKR',
            'margin': 'Margin requirement not met at IBKR',
            'cannot be traded': 'This security cannot be traded through IBKR',
            'outside of trading hours': 'Order placed outside IBKR trading hours',
            'price cap': 'Order price exceeds IBKR price cap for this security',
        }
        try:
            if trade and hasattr(trade, 'log') and trade.log:
                for entry in reversed(trade.log):
                    msg = getattr(entry, 'message', '') or ''
                    error_code = getattr(entry, 'errorCode', 0) or 0
                    if not msg or error_code == 0:
                        continue
                    raw = msg.replace('<br>', ' ').replace('<br/>', ' ').strip()
                    for keyword, friendly in _IBKR_REASON_MAP.items():
                        if keyword.lower() in raw.lower():
                            return f"{friendly} | IBKR error {error_code}: {raw[:200]}"
                    if error_code and error_code != 10349:
                        return f"IBKR rejected (error {error_code}): {raw[:200]}"
            status = trade.orderStatus.status if trade and trade.orderStatus else 'Unknown'
            return f"Order rejected by IBKR with status: {status}"
        except Exception:
            return "Order rejected by IBKR (unable to extract reason)"

    async def _wait_for_fill(self, trade, symbol: str, timeout: float = 10) -> Optional[float]:
        """Wait for order acknowledgment using event-driven approach with timeout fallback."""
        if not trade:
            return None
        try:
            done = asyncio.Event()
            final_status = [None]

            def on_status(t):
                s = t.orderStatus.status if t.orderStatus else ''
                if s in ('Filled', 'Cancelled', 'Inactive'):
                    final_status[0] = s
                    done.set()
                elif s in ('Submitted', 'PreSubmitted'):
                    final_status[0] = s
                    done.set()

            trade.statusEvent += on_status

            try:
                await asyncio.wait_for(done.wait(), timeout=timeout)

                # IB Gateway/TWS may auto-adjust order params (e.g., TIF→DAY, error 10349)
                # causing a transient Cancelled→Submitted within ~1s.
                # Wait briefly for potential resubmission before treating as final.
                if final_status[0] in ('Cancelled', 'Inactive'):
                    done.clear()
                    final_status[0] = None
                    try:
                        await asyncio.wait_for(done.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        pass
            except asyncio.TimeoutError:
                print(f"[{self.name}] ⚠️ Order for {symbol} — no status update within {timeout}s, continuing")
            finally:
                trade.statusEvent -= on_status

            if trade.orderStatus and trade.orderStatus.avgFillPrice:
                return float(trade.orderStatus.avgFillPrice)
        except Exception as e:
            print(f"[{self.name}] ⚠️ Fill wait error for {symbol}: {e}")
            await asyncio.sleep(1)
        return None

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
                    if not cached:
                        cached = hub.get_quote_price(symbol, allow_stale=True)
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
