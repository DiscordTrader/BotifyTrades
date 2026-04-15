"""
Tastytrade Broker Implementation
Options-focused trading platform with official API (SDK v11+, OAuth2 only)
"""

import sys
import os
import re
import asyncio
import inspect
from typing import Optional, Dict, Any, List
from datetime import datetime, date, timedelta
from decimal import Decimal


async def _await_if_needed(result):
    """Handle tastytrade SDK calls that may be sync or async depending on version."""
    if inspect.isawaitable(result):
        return await result
    return result

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory

try:
    from tastytrade import Session, Account
    from tastytrade.instruments import Equity, Option, get_option_chain, NestedOptionChain, InstrumentType
    from tastytrade.order import NewOrder, OrderAction, OrderTimeInForce, OrderType, OrderStatus as TT_OrderStatus
    TASTYTRADE_AVAILABLE = True
    NESTED_CHAIN_AVAILABLE = True
except ImportError as e:
    print(f"[TASTYTRADE] Warning: tastytrade package not available: {e}")
    TASTYTRADE_AVAILABLE = False
    NESTED_CHAIN_AVAILABLE = False

try:
    from tastytrade import DXLinkStreamer
    from tastytrade.dxfeed import Quote, Greeks
    DXLINK_AVAILABLE = True
except ImportError as e:
    print(f"[TASTYTRADE] Warning: DXLink streaming not available: {e}")
    DXLINK_AVAILABLE = False


def _parse_occ_symbol(occ_symbol: str) -> Optional[Dict]:
    """Parse OCC option symbol: AAPL  251219C00230000 or AAPL251219C00230000"""
    pattern = r'^([A-Z]{1,6})\s*(\d{6})([CP])(\d{8})$'
    m = re.match(pattern, occ_symbol.strip())
    if not m:
        return None
    underlying, date_str, cp, strike_str = m.groups()
    try:
        year = int('20' + date_str[:2])
        month = int(date_str[2:4])
        day = int(date_str[4:6])
        expiry = f"{year}-{month:02d}-{day:02d}"
        strike = int(strike_str) / 1000.0
        return {
            'underlying': underlying,
            'expiry': expiry,
            'call_put': cp,
            'strike': strike
        }
    except (ValueError, IndexError):
        return None


class TastytradeBroker(BrokerInterface):
    """Tastytrade broker implementation using official tastytrade SDK"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "TASTYTRADE"
        self.session = None
        self.account = None
        self.paper_trade = config.get('paper_trade', True)
    
    @property
    def is_live(self) -> bool:
        """Returns True if broker is in live trading mode (not paper/sandbox)"""
        return not self.paper_trade
    
    def _ensure_session_valid(self) -> bool:
        """Ensure session is valid, refresh if expired (15-minute token lifetime)"""
        if not self.session:
            print(f"[{self.name}] No session available")
            return False
        try:
            if hasattr(self.session, 'session_expiration') and hasattr(self.session, 'refresh'):
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                if now > self.session.session_expiration:
                    print(f"[{self.name}] Session token expired, refreshing...")
                    self.session.refresh()
                    print(f"[{self.name}] ✓ Session refreshed successfully")
            return True
        except Exception as e:
            print(f"[{self.name}] Session refresh failed: {e}")
            return False
    
    async def connect(self) -> bool:
        """Connect to Tastytrade using OAuth2 (SDK v11+ requires client_secret + refresh_token)"""
        try:
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._event_loop = None
            if not TASTYTRADE_AVAILABLE:
                print(f"[{self.name}] tastytrade package not installed")
                return False
            
            client_secret = self.config.get('client_secret')
            refresh_token = self.config.get('refresh_token')
            
            if not client_secret or not refresh_token:
                username = self.config.get('username')
                password = self.config.get('password')
                if username or password:
                    print(f"[{self.name}] Username/password login is no longer supported (SDK v11+)")
                    print(f"[{self.name}]    You must use OAuth2: client_secret + refresh_token")
                print(f"[{self.name}] Missing OAuth2 credentials (client_secret + refresh_token)")
                print(f"[{self.name}]    1. Go to my.tastytrade.com -> OAuth Applications")
                print(f"[{self.name}]    2. Create new app -> Save Client Secret")
                print(f"[{self.name}]    3. Manage -> Create Grant -> Save Refresh Token")
                print(f"[{self.name}]    4. Enter both in the Tastytrade broker settings")
                return False
            
            mode = "SANDBOX" if self.paper_trade else "LIVE"
            print(f"[{self.name}] Connecting to {mode} account via OAuth2...")
            
            self.session = await _await_if_needed(
                await asyncio.to_thread(
                    Session,
                    client_secret,
                    refresh_token,
                    is_test=self.paper_trade
                )
            )
            
            accounts = await _await_if_needed(
                await asyncio.to_thread(Account.get, self.session)
            )
            
            if not accounts:
                print(f"[{self.name}] No accounts found")
                return False
            
            if isinstance(accounts, list):
                self._all_accounts = accounts
                selected_acct_num = self.config.get('account_number')
                if selected_acct_num:
                    matched = [a for a in accounts if a.account_number == selected_acct_num]
                    if matched:
                        self.account = matched[0]
                        print(f"[{self.name}] Using selected account: {selected_acct_num}")
                    else:
                        self.account = accounts[0]
                        print(f"[{self.name}] Selected account {selected_acct_num} not found, using {self.account.account_number}")
                else:
                    self.account = accounts[0]
                
                if len(accounts) > 1:
                    print(f"[{self.name}] Available accounts ({len(accounts)}):")
                    for a in accounts:
                        marker = " <-- ACTIVE" if a.account_number == self.account.account_number else ""
                        acct_type = getattr(a, 'account_type_name', 'Unknown')
                        margin_cash = getattr(a, 'margin_or_cash', '')
                        print(f"[{self.name}]   {a.account_number} ({acct_type}, {margin_cash}){marker}")
            else:
                self.account = accounts
                self._all_accounts = [accounts]
            
            self.connected = True
            
            balances = await _await_if_needed(
                await asyncio.to_thread(self.account.get_balances, self.session)
            )
            
            nlv = float(getattr(balances, 'net_liquidating_value', 0) or 0)
            cash = float(getattr(balances, 'cash_balance', 0) or 0)
            
            print(f"[{self.name}] ✓ Connected successfully ({mode} trading)")
            print(f"[{self.name}]   Account #: {self.account.account_number}")
            print(f"[{self.name}]   Net Liq: ${nlv:,.2f}, Cash: ${cash:,.2f}")
            
            # Diagnostic: Test NestedOptionChain capability
            if NESTED_CHAIN_AVAILABLE:
                try:
                    print(f"[{self.name}] Testing NestedOptionChain with SPY...", flush=True)
                    result = NestedOptionChain.get(self.session, 'SPY')
                    print(f"[{self.name}] NestedOptionChain.get returned type: {type(result)}", flush=True)
                    
                    # Handle list vs single object
                    if isinstance(result, list):
                        print(f"[{self.name}] Got list with {len(result)} item(s)", flush=True)
                        if result:
                            chain = result[0]
                            print(f"[{self.name}] First item type: {type(chain)}", flush=True)
                            if hasattr(chain, 'expirations'):
                                print(f"[{self.name}] ✓ NestedOptionChain works! Found {len(chain.expirations)} expirations for SPY", flush=True)
                            else:
                                print(f"[{self.name}] Chain attrs: {[a for a in dir(chain) if not a.startswith('_')]}", flush=True)
                    elif hasattr(result, 'expirations'):
                        print(f"[{self.name}] ✓ NestedOptionChain works! Found {len(result.expirations)} expirations for SPY", flush=True)
                    else:
                        print(f"[{self.name}] ⚠ Unknown result structure", flush=True)
                except Exception as test_err:
                    print(f"[{self.name}] ⚠ NestedOptionChain test failed: {test_err}", flush=True)
                    import traceback
                    traceback.print_exc()
            else:
                print(f"[{self.name}] ⚠ NestedOptionChain not available (NESTED_CHAIN_AVAILABLE=False)", flush=True)
            
            return True
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            print(f"[{self.name}] Connection error: {error_msg}")
            
            if 'invalid_grant' in error_msg.lower() or 'jwt' in error_msg.lower() or 'unauthorized' in error_msg.lower():
                print(f"[{self.name}] Authentication failed. Check your OAuth2 credentials:")
                print(f"[{self.name}]    1. Go to my.tastytrade.com -> OAuth Applications")
                print(f"[{self.name}]    2. Verify Client Secret and Refresh Token are correct")
                print(f"[{self.name}]    3. For sandbox, use sandbox credentials")
            
            traceback.print_exc()
            return False
    
    async def disconnect(self):
        """Disconnect from Tastytrade"""
        self.connected = False
        self.session = None
        self.account = None
        print(f"[{self.name}] Disconnected")
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information from Tastytrade"""
        try:
            if not self.account or not self.session:
                if hasattr(self, '_last_account_info') and self._last_account_info:
                    return dict(self._last_account_info)
                return None
            
            balances = await _await_if_needed(
                await asyncio.to_thread(self.account.get_balances, self.session)
            )
            
            nlv = float(getattr(balances, 'net_liquidating_value', 0) or 0)
            cash = float(getattr(balances, 'cash_balance', 0) or 0)
            derivative_bp = float(getattr(balances, 'derivative_buying_power', 0) or 0)
            equity_bp = float(getattr(balances, 'equity_buying_power', 0) or 0)
            
            result = {
                'buying_power': equity_bp,
                'options_buying_power': derivative_bp,
                'cash': cash,
                'portfolio_value': nlv,
                'account_number': self.account.account_number,
                'account_type': getattr(self.account, 'account_type_name', ''),
                'margin_or_cash': getattr(self.account, 'margin_or_cash', ''),
            }
            
            if hasattr(self, '_all_accounts') and isinstance(self._all_accounts, list) and len(self._all_accounts) > 1:
                result['all_accounts'] = []
                for a in self._all_accounts:
                    result['all_accounts'].append({
                        'account_number': a.account_number,
                        'account_type': getattr(a, 'account_type_name', 'Unknown'),
                        'margin_or_cash': getattr(a, 'margin_or_cash', ''),
                        'nickname': getattr(a, 'nickname', ''),
                        'is_active': a.account_number == self.account.account_number,
                    })
            
            self._last_account_info = result
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            import traceback
            traceback.print_exc()
            if hasattr(self, '_last_account_info') and self._last_account_info:
                print(f"[{self.name}] Returning last known good account info after error")
                return dict(self._last_account_info)
            return None
    
    async def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        try:
            if not self.account or not self.session:
                return {}
            
            positions = await _await_if_needed(
                await asyncio.to_thread(self.account.get_positions, self.session)
            )
            result = {}
            for pos in positions:
                symbol = getattr(pos, 'symbol', None)
                qty = getattr(pos, 'quantity', 0)
                if symbol:
                    result[symbol] = int(float(qty))
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return {}
    
    def _convert_position_to_dict(self, pos) -> Dict[str, Any]:
        """Convert a Pydantic CurrentPosition object to a standard dict."""
        symbol = getattr(pos, 'symbol', '')
        underlying = getattr(pos, 'underlying_symbol', symbol)
        instrument_type = getattr(pos, 'instrument_type', None)
        quantity = float(getattr(pos, 'quantity', 0))
        quantity_direction = getattr(pos, 'quantity_direction', 'Long')
        avg_open = float(getattr(pos, 'average_open_price', 0) or 0)
        mark = getattr(pos, 'mark_price', None) or getattr(pos, 'mark', None) or getattr(pos, 'close_price', None)
        current_price = float(mark) if mark else 0.0
        multiplier = int(getattr(pos, 'multiplier', 1) or 1)

        is_option = False
        if instrument_type is not None:
            try:
                is_option = instrument_type.value == 'Equity Option' or instrument_type.value == 'Future Option'
            except (AttributeError, TypeError):
                is_option = str(instrument_type).upper() in ('EQUITY_OPTION', 'EQUITY OPTION', 'FUTURE_OPTION')
        
        asset_type = 'option' if is_option else 'stock'

        strike = None
        expiry = None
        call_put = None

        if is_option:
            parsed = _parse_occ_symbol(symbol)
            if parsed:
                strike = parsed['strike']
                expiry = parsed['expiry']
                call_put = parsed['call_put']
                underlying = parsed['underlying']
            else:
                exp_at = getattr(pos, 'expires_at', None)
                if exp_at:
                    try:
                        expiry = exp_at.strftime('%Y-%m-%d')
                    except (AttributeError, TypeError):
                        pass

        if quantity_direction == 'Short':
            quantity = -abs(quantity)

        if quantity < 0:
            unrealized_pnl = (avg_open - current_price) * abs(quantity) * multiplier
        else:
            unrealized_pnl = (current_price - avg_open) * abs(quantity) * multiplier
        market_value = current_price * abs(quantity) * multiplier

        return {
            'symbol': symbol,
            'underlying_symbol': underlying,
            'quantity': abs(quantity),
            'signed_quantity': quantity,
            'avg_price': avg_open,
            'current_price': current_price,
            'unrealized_pnl': round(unrealized_pnl, 2),
            'market_value': round(market_value, 2),
            'asset_type': asset_type,
            'strike': strike,
            'expiry': expiry,
            'call_put': call_put,
            'multiplier': multiplier,
            'position_id': symbol,
            'direction': call_put,
            'quantity_direction': quantity_direction,
        }

    def get_all_positions(self) -> list:
        """Get all positions as dicts for sync service (synchronous)"""
        try:
            if not self.account or not self.session:
                print(f"[{self.name}] Not connected")
                return []
            if not self._ensure_session_valid():
                return []
            raw_positions = self.account.get_positions(self.session)
            result = []
            for pos in raw_positions:
                try:
                    result.append(self._convert_position_to_dict(pos))
                except Exception as conv_err:
                    print(f"[{self.name}] Position conversion error for {getattr(pos, 'symbol', '?')}: {conv_err}")
            print(f"[{self.name}] get_all_positions returned {len(result)} positions")
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting all positions: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _convert_order_to_dict(self, order) -> Dict[str, Any]:
        """Convert a Pydantic PlacedOrder object to a standard dict."""
        order_id = str(getattr(order, 'id', ''))
        status_val = getattr(order, 'status', None)
        status_str = status_val.value if hasattr(status_val, 'value') else str(status_val or '')
        underlying = getattr(order, 'underlying_symbol', '')
        price = float(getattr(order, 'price', 0) or 0)
        order_type_val = getattr(order, 'order_type', None)
        order_type_str = order_type_val.value if hasattr(order_type_val, 'value') else str(order_type_val or '')

        legs_data = []
        total_qty = 0
        action_str = ''
        symbol = underlying
        asset_type = 'stock'

        legs = getattr(order, 'legs', []) or []
        for leg in legs:
            leg_symbol = getattr(leg, 'symbol', '')
            leg_action = getattr(leg, 'action', None)
            leg_action_str = leg_action.value if hasattr(leg_action, 'value') else str(leg_action or '')
            leg_qty = int(float(getattr(leg, 'quantity', 0) or 0))
            remaining = int(float(getattr(leg, 'remaining_quantity', 0) or 0))
            leg_inst = getattr(leg, 'instrument_type', None)
            leg_asset = 'option' if (leg_inst and hasattr(leg_inst, 'value') and leg_inst.value in ('Equity Option', 'Future Option')) else 'stock'

            fill_data = []
            for fill in (getattr(leg, 'fills', None) or []):
                fill_data.append({
                    'fill_id': getattr(fill, 'fill_id', ''),
                    'quantity': int(float(getattr(fill, 'quantity', 0))),
                    'fill_price': float(getattr(fill, 'fill_price', 0)),
                    'filled_at': getattr(fill, 'filled_at', None),
                })

            legs_data.append({
                'symbol': leg_symbol,
                'action': leg_action_str,
                'quantity': leg_qty,
                'remaining_quantity': remaining,
                'instrument_type': leg_asset,
                'fills': fill_data,
            })

            if not action_str:
                action_str = leg_action_str
            total_qty += leg_qty
            if leg_symbol:
                symbol = leg_symbol
            if leg_asset == 'option':
                asset_type = 'option'

        return {
            'order_id': order_id,
            'broker_order_id': order_id,
            'symbol': symbol,
            'underlying_symbol': underlying,
            'quantity': total_qty,
            'action': action_str,
            'status': status_str,
            'order_type': order_type_str,
            'limit_price': abs(price) if price else None,
            'asset_type': asset_type,
            'legs': legs_data,
            'received_at': getattr(order, 'received_at', None),
            'live_at': getattr(order, 'live_at', None),
            'terminal_at': getattr(order, 'terminal_at', None),
            'cancelled_at': getattr(order, 'cancelled_at', None),
            'reject_reason': getattr(order, 'reject_reason', None),
        }

    def get_orders(self, status: str = 'open') -> list:
        """Get orders by status for sync service (synchronous)"""
        try:
            if not self.account or not self.session:
                print(f"[{self.name}] Not connected")
                return []
            if not self._ensure_session_valid():
                return []
            
            raw_orders = self.account.get_live_orders(self.session)
            return [self._convert_order_to_dict(o) for o in raw_orders]
        except Exception as e:
            print(f"[{self.name}] Error getting orders: {e}")
            return []

    def get_pending_orders(self) -> list:
        """Get pending/live orders as dicts for sync service (synchronous)"""
        return self.get_orders(status='open')

    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific order by ID (synchronous)"""
        try:
            if not self.account or not self.session:
                return None
            if not self._ensure_session_valid():
                return None
            order = self.account.get_order(self.session, int(order_id))
            if order:
                d = self._convert_order_to_dict(order)
                filled_qty = 0
                for leg in (getattr(order, 'legs', []) or []):
                    for fill in (getattr(leg, 'fills', None) or []):
                        filled_qty += int(float(getattr(fill, 'quantity', 0)))
                d['filled_qty'] = filled_qty
                return d
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting order status for {order_id}: {e}")
            return None

    async def get_account_balances(self) -> Dict[str, Any]:
        """Get account balances in standard format for broker_sync_service"""
        try:
            if not self.account or not self.session:
                return {}
            if not self._ensure_session_valid():
                return {}
            
            balances = await _await_if_needed(
                await asyncio.to_thread(self.account.get_balances, self.session)
            )
            
            return {
                'net_liquidating_value': float(getattr(balances, 'net_liquidating_value', 0) or 0),
                'net-liquidating-value': float(getattr(balances, 'net_liquidating_value', 0) or 0),
                'cash_balance': float(getattr(balances, 'cash_balance', 0) or 0),
                'cash-balance': float(getattr(balances, 'cash_balance', 0) or 0),
                'equity_buying_power': float(getattr(balances, 'equity_buying_power', 0) or 0),
                'buying_power': float(getattr(balances, 'equity_buying_power', 0) or 0),
                'buying-power': float(getattr(balances, 'equity_buying_power', 0) or 0),
                'derivative_buying_power': float(getattr(balances, 'derivative_buying_power', 0) or 0),
                'derivative-buying-power': float(getattr(balances, 'derivative_buying_power', 0) or 0),
                'options_buying_power': float(getattr(balances, 'derivative_buying_power', 0) or 0),
                'portfolio_value': float(getattr(balances, 'net_liquidating_value', 0) or 0),
                'cash': float(getattr(balances, 'cash_balance', 0) or 0),
                'day_trading_buying_power': float(getattr(balances, 'day_trading_buying_power', 0) or 0),
                'maintenance_requirement': float(getattr(balances, 'maintenance_requirement', 0) or 0),
            }
        except Exception as e:
            print(f"[{self.name}] Error getting account balances: {e}")
            return {}

    def get_filled_orders(self, limit: int = 50) -> list:
        """Get filled orders from order history for fill reconciliation (synchronous)"""
        try:
            if not self.account or not self.session:
                return []
            if not self._ensure_session_valid():
                return []
            
            filled_orders = self.account.get_order_history(
                self.session,
                per_page=limit,
                statuses=[TT_OrderStatus.FILLED]
            )
            
            result = []
            for order in filled_orders:
                d = self._convert_order_to_dict(order)
                
                fill_price = 0.0
                fill_qty = 0
                latest_fill_time = None
                
                for leg in (getattr(order, 'legs', []) or []):
                    for fill in (getattr(leg, 'fills', None) or []):
                        fq = int(float(getattr(fill, 'quantity', 0)))
                        fp = float(getattr(fill, 'fill_price', 0))
                        ft = getattr(fill, 'filled_at', None)
                        fill_qty += fq
                        fill_price += fq * fp
                        if ft and (latest_fill_time is None or ft > latest_fill_time):
                            latest_fill_time = ft
                
                if fill_qty > 0:
                    fill_price = fill_price / fill_qty
                
                action_str = d.get('action', '')
                side = 'BTO'
                if 'Sell to Close' in action_str or action_str == 'STC':
                    side = 'STC'
                elif 'Sell to Open' in action_str or action_str == 'STO':
                    side = 'STO'
                elif 'Buy to Close' in action_str or action_str == 'BTC':
                    side = 'BTC'
                elif 'Buy to Open' in action_str or action_str == 'BTO':
                    side = 'BTO'
                elif 'Buy' in action_str:
                    side = 'BTO'
                elif 'Sell' in action_str:
                    side = 'STC'
                
                parsed = None
                symbol = d.get('symbol', '')
                asset_type = d.get('asset_type', 'stock')
                if asset_type == 'option':
                    parsed = _parse_occ_symbol(symbol)
                
                result.append({
                    'order_id': d['order_id'],
                    'symbol': parsed['underlying'] if parsed else d.get('underlying_symbol', symbol),
                    'quantity': fill_qty or d.get('quantity', 0),
                    'filled_price': round(fill_price, 4),
                    'action': side,
                    'filled_time': latest_fill_time.isoformat() if latest_fill_time else (d.get('terminal_at').isoformat() if d.get('terminal_at') else ''),
                    'asset_type': asset_type,
                    'strike': parsed['strike'] if parsed else None,
                    'expiry': parsed['expiry'] if parsed else None,
                    'direction': parsed['call_put'] if parsed else None,
                    'occ_symbol': symbol if asset_type == 'option' else None,
                })
            
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting filled orders: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        try:
            if not self.account or not self.session:
                return {'success': False, 'msg': 'Not connected to Tastytrade'}
            
            result = await _await_if_needed(
                await asyncio.to_thread(
                    self.account.delete_order, self.session, int(order_id)
                )
            )
            print(f"[{self.name}] ✓ Cancelled order {order_id}")
            return {'success': True, 'order_id': order_id}
        except Exception as e:
            print(f"[{self.name}] Cancel order {order_id} error: {e}")
            return {'success': False, 'msg': str(e)}

    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        **kwargs
    ) -> OrderResult:
        """Place a stock order"""
        try:
            if not self._ensure_session_valid():
                return OrderResult(
                    success=False,
                    message="Tastytrade session expired and refresh failed",
                    symbol=symbol,
                    action=action
                )
            if not self.account or not self.session:
                return OrderResult(
                    success=False,
                    message="Not connected to Tastytrade",
                    symbol=symbol,
                    action=action
                )
            
            equity = await _await_if_needed(
                await asyncio.to_thread(Equity.get, self.session, symbol)
            )
            
            if action.upper() == 'BTO':
                order_action = OrderAction.BUY_TO_OPEN
            elif action.upper() == 'STC':
                order_action = OrderAction.SELL_TO_CLOSE
            elif action.upper() == 'STO':
                order_action = OrderAction.SELL_TO_OPEN
            elif action.upper() == 'BTC':
                order_action = OrderAction.BUY_TO_CLOSE
            else:
                order_action = OrderAction.BUY_TO_OPEN if 'B' in action.upper() else OrderAction.SELL_TO_CLOSE
            
            leg = equity.build_leg(Decimal(str(quantity)), order_action)
            
            if price is not None and price > 0:
                price_decimal = Decimal(str(-price)) if 'B' in action.upper() else Decimal(str(price))
                order = NewOrder(
                    time_in_force=OrderTimeInForce.DAY,
                    order_type=OrderType.LIMIT,
                    legs=[leg],
                    price=price_decimal
                )
            else:
                order = NewOrder(
                    time_in_force=OrderTimeInForce.DAY,
                    order_type=OrderType.MARKET,
                    legs=[leg]
                )
            
            print(f"[{self.name}] Placing stock order: {action} {quantity} {symbol} @ ${price or 'MARKET'}")
            
            response = await _await_if_needed(
                await asyncio.to_thread(
                    self.account.place_order,
                    self.session,
                    order,
                    dry_run=False
                )
            )
            
            if response and hasattr(response, 'order') and response.order:
                return OrderResult(
                    success=True,
                    order_id=str(response.order.id),
                    message=f"Stock order placed: {action} {quantity} {symbol}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                return OrderResult(
                    success=True,
                    order_id="submitted",
                    message=f"Stock order submitted: {action} {quantity} {symbol}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            error_msg = str(e)
            print(f"[{self.name}] ❌ Stock order failed: {error_msg}")
            import traceback
            traceback.print_exc()
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
            if not self._ensure_session_valid():
                return OrderResult(
                    success=False,
                    message="Tastytrade session expired and refresh failed",
                    symbol=symbol,
                    action=action
                )
            if not self.account or not self.session:
                return OrderResult(
                    success=False,
                    message="Not connected to Tastytrade",
                    symbol=symbol,
                    action=action
                )
            
            if "/" in expiry:
                parts = expiry.split("/")
                if len(parts) == 2:
                    m, d = parts
                    y = datetime.now().year
                    expiry_date = datetime(y, int(m), int(d)).date()
                elif len(parts) == 3:
                    m, d, y = parts
                    if len(y) == 2:
                        y = f"20{y}"
                    expiry_date = datetime(int(y), int(m), int(d)).date()
                else:
                    expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            else:
                expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            
            print(f"[{self.name}] Looking up option chain for {symbol} expiry {expiry_date}")
            
            try:
                chain = await _await_if_needed(
                    await asyncio.to_thread(get_option_chain, self.session, symbol)
                )
                
                if expiry_date not in chain:
                    available_expiries = list(chain.keys())[:5]
                    return OrderResult(
                        success=False,
                        message=f"Expiry {expiry_date} not found. Available: {available_expiries}",
                        symbol=symbol,
                        action=action
                    )
                
                options = chain[expiry_date]
                opt_type = 'C' if option_type.upper().startswith('C') else 'P'
                
                target_option = None
                for opt in options:
                    if abs(float(opt.strike_price) - strike) < 0.01:
                        if (opt_type == 'C' and opt.option_type.value == 'C') or \
                           (opt_type == 'P' and opt.option_type.value == 'P'):
                            target_option = opt
                            break
                
                if not target_option:
                    return OrderResult(
                        success=False,
                        message=f"Could not find {symbol} ${strike}{opt_type} {expiry_date}",
                        symbol=symbol,
                        action=action
                    )
                
            except Exception as chain_err:
                print(f"[{self.name}] Option chain lookup failed: {chain_err}")
                return OrderResult(
                    success=False,
                    message=f"Could not find option contract: {chain_err}",
                    symbol=symbol,
                    action=action
                )
            
            if action.upper() == 'BTO':
                order_action = OrderAction.BUY_TO_OPEN
            elif action.upper() == 'STC':
                order_action = OrderAction.SELL_TO_CLOSE
            elif action.upper() == 'STO':
                order_action = OrderAction.SELL_TO_OPEN
            elif action.upper() == 'BTC':
                order_action = OrderAction.BUY_TO_CLOSE
            else:
                order_action = OrderAction.BUY_TO_OPEN if 'B' in action.upper() else OrderAction.SELL_TO_CLOSE
            
            leg = target_option.build_leg(Decimal(str(quantity)), order_action)
            
            if price is not None and price > 0:
                price_decimal = Decimal(str(-price)) if 'B' in action.upper() else Decimal(str(price))
                order = NewOrder(
                    time_in_force=OrderTimeInForce.DAY,
                    order_type=OrderType.LIMIT,
                    legs=[leg],
                    price=price_decimal
                )
            else:
                order = NewOrder(
                    time_in_force=OrderTimeInForce.DAY,
                    order_type=OrderType.MARKET,
                    legs=[leg]
                )
            
            print(f"[{self.name}] Placing option order: {action} {quantity} {target_option.symbol} @ ${price or 'MARKET'}")
            
            response = await _await_if_needed(
                await asyncio.to_thread(
                    self.account.place_order,
                    self.session,
                    order,
                    dry_run=False
                )
            )
            
            if response and hasattr(response, 'order') and response.order:
                return OrderResult(
                    success=True,
                    order_id=str(response.order.id),
                    message=f"Option order placed: {action} {quantity} {symbol} ${strike}{opt_type} {expiry}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                return OrderResult(
                    success=True,
                    order_id="submitted",
                    message=f"Option order submitted: {action} {quantity} {symbol} ${strike}{opt_type} {expiry}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            error_msg = str(e)
            print(f"[{self.name}] ❌ Option order failed: {error_msg}")
            import traceback
            traceback.print_exc()
            return OrderResult(
                success=False,
                message=f"Exception: {error_msg}",
                symbol=symbol,
                action=action
            )
    
    async def get_quote(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol using DXLink one-shot quote"""
        try:
            if not self.session:
                return None
            
            if not DXLINK_AVAILABLE:
                return None
            
            def _lookup_streamer_symbol():
                try:
                    equity = Equity.get(self.session, symbol)
                    if equity and hasattr(equity, 'streamer_symbol'):
                        return equity.streamer_symbol
                except Exception:
                    pass
                return symbol
            
            streamer_sym = await _await_if_needed(
                await asyncio.to_thread(_lookup_streamer_symbol)
            )
            
            async with DXLinkStreamer(self.session) as streamer:
                await streamer.subscribe(Quote, [streamer_sym])
                quote_event = await asyncio.wait_for(streamer.get_event(Quote), timeout=5.0)
                if quote_event:
                    bid = float(getattr(quote_event, 'bid_price', 0) or 0)
                    ask = float(getattr(quote_event, 'ask_price', 0) or 0)
                    if bid > 0 and ask > 0:
                        return round((bid + ask) / 2, 4)
                    elif bid > 0:
                        return bid
                    elif ask > 0:
                        return ask
            
            return None
        except asyncio.TimeoutError:
            print(f"[{self.name}] Quote timeout for {symbol}")
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
            return None
    
    async def get_option_data_dxlink(self, symbols: list, timeout: float = 10.0) -> Dict[str, Dict[str, float]]:
        """Fetch live quotes (bid/ask) AND Greeks (IV, delta, etc.) in a single DXLink session.
        
        DXLink streaming data is FREE for funded personal tastytrade accounts.
        
        Args:
            symbols: List of option streamer symbols
            timeout: Maximum time to wait for data (seconds)
            
        Returns:
            Dict mapping symbol to {'bid': val, 'ask': val, 'iv': val, 'delta': val, 'theta': val, 'gamma': val, 'vega': val}
        """
        option_data = {}
        
        if not DXLINK_AVAILABLE:
            print(f"[{self.name}] DXLink streaming not available")
            return option_data
        
        if not self.session:
            print(f"[{self.name}] Not connected - cannot fetch option data")
            return option_data
        
        if not symbols:
            return option_data
        
        try:
            print(f"[{self.name}] Fetching live quotes + Greeks for {len(symbols)} options via DXLink...")
            
            async with DXLinkStreamer(self.session) as streamer:
                await streamer.subscribe(Quote, symbols)
                await streamer.subscribe(Greeks, symbols)
                
                quotes_received = set()
                greeks_received = set()
                start_time = asyncio.get_event_loop().time()
                
                while len(quotes_received) < len(symbols) or len(greeks_received) < len(symbols):
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed >= timeout:
                        print(f"[{self.name}] DXLink timeout after {elapsed:.1f}s - quotes: {len(quotes_received)}, greeks: {len(greeks_received)}")
                        break
                    
                    try:
                        if len(quotes_received) < len(symbols):
                            try:
                                quote = await asyncio.wait_for(
                                    streamer.get_event(Quote),
                                    timeout=0.5
                                )
                                if quote and hasattr(quote, 'event_symbol'):
                                    sym = quote.event_symbol
                                    if sym not in quotes_received:
                                        if sym not in option_data:
                                            option_data[sym] = {'bid': 0, 'ask': 0, 'iv': 0, 'delta': 0, 'theta': 0, 'gamma': 0, 'vega': 0}
                                        option_data[sym]['bid'] = float(quote.bid_price) if quote.bid_price else 0.0
                                        option_data[sym]['ask'] = float(quote.ask_price) if quote.ask_price else 0.0
                                        quotes_received.add(sym)
                            except asyncio.TimeoutError:
                                pass
                        
                        if len(greeks_received) < len(symbols):
                            try:
                                greek = await asyncio.wait_for(
                                    streamer.get_event(Greeks),
                                    timeout=0.5
                                )
                                if greek and hasattr(greek, 'event_symbol'):
                                    sym = greek.event_symbol
                                    if sym not in greeks_received:
                                        if sym not in option_data:
                                            option_data[sym] = {'bid': 0, 'ask': 0, 'iv': 0, 'delta': 0, 'theta': 0, 'gamma': 0, 'vega': 0}
                                        option_data[sym]['iv'] = float(greek.volatility) if hasattr(greek, 'volatility') and greek.volatility else 0.0
                                        option_data[sym]['delta'] = float(greek.delta) if hasattr(greek, 'delta') and greek.delta else 0.0
                                        option_data[sym]['theta'] = float(greek.theta) if hasattr(greek, 'theta') and greek.theta else 0.0
                                        option_data[sym]['gamma'] = float(greek.gamma) if hasattr(greek, 'gamma') and greek.gamma else 0.0
                                        option_data[sym]['vega'] = float(greek.vega) if hasattr(greek, 'vega') and greek.vega else 0.0
                                        greeks_received.add(sym)
                            except asyncio.TimeoutError:
                                pass
                                
                    except Exception as e:
                        print(f"[{self.name}] DXLink event error: {e}")
                        continue
            
            print(f"[{self.name}] ✓ Received {len(quotes_received)} quotes, {len(greeks_received)} Greeks")
            return option_data
            
        except Exception as e:
            print(f"[{self.name}] DXLink streaming error: {e}")
            import traceback
            traceback.print_exc()
            return option_data
    
    def _get_option_data_sync(self, symbols: list, timeout: float = 10.0) -> Dict[str, Dict[str, float]]:
        """Synchronous wrapper for get_option_data_dxlink for use in Flask routes."""
        import concurrent.futures
        
        def run_async():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(self.get_option_data_dxlink(symbols, timeout))
            finally:
                new_loop.close()
        
        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_async)
                return future.result(timeout=timeout + 5)
        except Exception as e:
            print(f"[{self.name}] Sync option data fetch error: {e}")
            return {}
    
    def get_options_expiration_dates(self, symbol: str) -> list:
        """Get available expiration dates for a symbol using NestedOptionChain.
        
        Args:
            symbol: Stock symbol (e.g., 'SPY')
            
        Returns:
            List of expiration dates in YYYY-MM-DD format
        """
        try:
            if not TASTYTRADE_AVAILABLE:
                print(f"[{self.name}] ❌ tastytrade package not installed")
                return []
            
            if not self._ensure_session_valid():
                print(f"[{self.name}] Not connected or session invalid - cannot get expiration dates")
                return []
            
            print(f"[{self.name}] Fetching expiration dates for {symbol}", flush=True)
            
            if NESTED_CHAIN_AVAILABLE:
                result = NestedOptionChain.get(self.session, symbol)
                print(f"[{self.name}] NestedOptionChain.get returned: {type(result)}", flush=True)
                
                # Handle both list and single object returns (SDK version differences)
                if isinstance(result, list):
                    # Some SDK versions return a list of chains
                    if not result:
                        print(f"[{self.name}] No chains returned for {symbol}")
                        return []
                    # Use first chain in list
                    nested_chain = result[0]
                    print(f"[{self.name}] Using first chain from list: {type(nested_chain)}", flush=True)
                else:
                    nested_chain = result
                
                # Try to get expirations - handle different object structures
                expirations_data = None
                if hasattr(nested_chain, 'expirations'):
                    expirations_data = nested_chain.expirations
                elif isinstance(nested_chain, dict) and 'expirations' in nested_chain:
                    expirations_data = nested_chain['expirations']
                
                if not expirations_data:
                    print(f"[{self.name}] No expirations found in chain for {symbol}")
                    print(f"[{self.name}] Chain attributes: {dir(nested_chain) if hasattr(nested_chain, '__dict__') else nested_chain}", flush=True)
                    return []
                
                expirations = []
                for exp in expirations_data:
                    # Handle both object and dict formats
                    if hasattr(exp, 'expiration_date'):
                        exp_str = exp.expiration_date.strftime('%Y-%m-%d')
                    elif isinstance(exp, dict) and 'expiration_date' in exp:
                        exp_str = exp['expiration_date']
                    else:
                        print(f"[{self.name}] Unknown expiration format: {type(exp)}", flush=True)
                        continue
                    expirations.append(exp_str)
                
                expirations.sort()
                print(f"[{self.name}] ✓ Found {len(expirations)} expiration dates for {symbol}", flush=True)
                return expirations
            else:
                print(f"[{self.name}] NestedOptionChain not available")
                return []
                
        except Exception as e:
            print(f"[{self.name}] Error getting expiration dates for {symbol}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_option_chain(self, symbol: str, expiration_date: str) -> Dict[str, Any]:
        """Get option chain for a symbol and expiration date using NestedOptionChain.
        
        The tastytrade SDK's NestedOptionChain returns structured data:
        - chain.expirations[] - list of expiration objects
        - each expiration has: expiration_date, strikes[]
        - each strike has: strike_price, call (symbol), put (symbol)
        
        Args:
            symbol: Stock symbol (e.g., 'SPY')
            expiration_date: Expiration date in YYYY-MM-DD format
            
        Returns:
            Dictionary with 'calls', 'puts', 'stock_price', and 'data_source' keys
        """
        try:
            if not TASTYTRADE_AVAILABLE:
                print(f"[{self.name}] ❌ tastytrade package not installed")
                return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': 'Tastytrade (unavailable)'}
            
            if not self.session:
                print(f"[{self.name}] Not connected - cannot get option chain")
                return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': 'Tastytrade (not connected)'}
            
            print(f"[{self.name}] Fetching option chain for {symbol} exp {expiration_date}")
            
            exp_date = datetime.strptime(expiration_date, '%Y-%m-%d').date()
            
            if NESTED_CHAIN_AVAILABLE:
                try:
                    nested_result = NestedOptionChain.get(self.session, symbol)
                    if isinstance(nested_result, list):
                        nested_chain = nested_result[0] if nested_result else None
                    else:
                        nested_chain = nested_result
                    
                    if not nested_chain or not getattr(nested_chain, 'expirations', None):
                        print(f"[{self.name}] No option chain returned for {symbol}")
                        return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': 'Tastytrade (no data)'}
                    
                    target_expiration = None
                    for exp in nested_chain.expirations:
                        if exp.expiration_date == exp_date:
                            target_expiration = exp
                            break
                    
                    if not target_expiration:
                        available_expiries = sorted([e.expiration_date for e in nested_chain.expirations])[:10]
                        print(f"[{self.name}] Expiry {exp_date} not found. Available: {available_expiries}")
                        return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': f'Tastytrade (expiry {exp_date} not available)'}
                    
                    calls = []
                    puts = []
                    occ_symbols = []
                    
                    for strike_obj in target_expiration.strikes:
                        strike_price = float(strike_obj.strike_price)
                        
                        if strike_obj.call:
                            occ_symbols.append(strike_obj.call)
                            calls.append({
                                'strike': strike_price,
                                'symbol': strike_obj.call,
                                'type': 'call',
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
                            })
                        
                        if strike_obj.put:
                            occ_symbols.append(strike_obj.put)
                            puts.append({
                                'strike': strike_price,
                                'symbol': strike_obj.put,
                                'type': 'put',
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
                            })
                    
                    calls.sort(key=lambda x: x['strike'])
                    puts.sort(key=lambda x: x['strike'])
                    
                    print(f"[{self.name}] ✓ Found {len(calls)} calls, {len(puts)} puts for {symbol} exp {expiration_date}", flush=True)
                    
                    print(f"[{self.name}] DXLINK_AVAILABLE={DXLINK_AVAILABLE}, has_options={bool(calls or puts)}", flush=True)
                    if DXLINK_AVAILABLE and (calls or puts):
                        streamer_to_occ = {}
                        try:
                            option_objects = Option.get_options(self.session, occ_symbols)
                            for opt_obj in option_objects:
                                if hasattr(opt_obj, 'streamer_symbol') and opt_obj.streamer_symbol:
                                    streamer_to_occ[opt_obj.streamer_symbol] = opt_obj.symbol
                            print(f"[{self.name}] Got {len(streamer_to_occ)} streamer symbols from {len(occ_symbols)} OCC symbols", flush=True)
                        except Exception as e:
                            print(f"[{self.name}] Error fetching Option objects for streamer symbols: {e}", flush=True)
                        
                        if streamer_to_occ:
                            streamer_symbols = list(streamer_to_occ.keys())
                            print(f"[{self.name}] Fetching DXLink quotes + Greeks for {len(streamer_symbols)} options...", flush=True)
                            if streamer_symbols[:1]:
                                print(f"[{self.name}] Sample streamer symbol: {streamer_symbols[0]}", flush=True)
                            
                            option_data = self._get_option_data_sync(streamer_symbols, timeout=12.0)
                            print(f"[{self.name}] DXLink returned data for {len(option_data)} options", flush=True)
                            
                            if option_data:
                                quotes_applied = 0
                                greeks_applied = 0
                                for opt in calls + puts:
                                    for streamer_sym, occ_sym in streamer_to_occ.items():
                                        if occ_sym == opt['symbol'] and streamer_sym in option_data:
                                            data = option_data[streamer_sym]
                                            opt['bid'] = data.get('bid', 0)
                                            opt['ask'] = data.get('ask', 0)
                                            opt['iv'] = data.get('iv', 0)
                                            opt['delta'] = data.get('delta', 0)
                                            opt['theta'] = data.get('theta', 0)
                                            opt['gamma'] = data.get('gamma', 0)
                                            opt['vega'] = data.get('vega', 0)
                                            if opt['bid'] > 0 or opt['ask'] > 0:
                                                quotes_applied += 1
                                            if opt['bid'] > 0 and opt['ask'] > 0:
                                                opt['last'] = (opt['bid'] + opt['ask']) / 2
                                            if opt['iv'] > 0:
                                                greeks_applied += 1
                                            break
                                print(f"[{self.name}] ✓ Applied {quotes_applied} quotes, {greeks_applied} Greeks with non-zero values", flush=True)
                        else:
                            print(f"[{self.name}] No streamer symbols available, skipping DXLink data", flush=True)
                    
                    return {
                        'calls': calls,
                        'puts': puts,
                        'stock_price': None,
                        'data_source': 'Tastytrade (DXLink Live)' if DXLINK_AVAILABLE else 'Tastytrade',
                        'expiration': expiration_date,
                        'symbol': symbol
                    }
                except Exception as nested_err:
                    print(f"[{self.name}] NestedOptionChain failed: {nested_err}, falling back to get_option_chain")
            
            chain = get_option_chain(self.session, symbol)
            
            if not chain:
                print(f"[{self.name}] No option chain returned for {symbol}")
                return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': 'Tastytrade (no data)'}
            
            if exp_date not in chain:
                available_expiries = sorted(list(chain.keys()))[:10]
                print(f"[{self.name}] Expiry {exp_date} not found. Available: {available_expiries}")
                return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': f'Tastytrade (expiry {exp_date} not available)'}
            
            options = chain[exp_date]
            
            calls = []
            puts = []
            streamer_to_occ = {}
            
            for opt in options:
                strike = float(opt.strike_price)
                opt_type = opt.option_type.value
                opt_symbol = opt.symbol if hasattr(opt, 'symbol') else f"{symbol}{expiration_date.replace('-', '')}{opt_type}{int(strike*1000):08d}"
                
                if hasattr(opt, 'streamer_symbol') and opt.streamer_symbol:
                    streamer_to_occ[opt.streamer_symbol] = opt_symbol
                
                option_data = {
                    'strike': strike,
                    'symbol': opt_symbol,
                    'type': 'call' if opt_type == 'C' else 'put',
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
                
                if opt_type == 'C':
                    calls.append(option_data)
                else:
                    puts.append(option_data)
            
            calls.sort(key=lambda x: x['strike'])
            puts.sort(key=lambda x: x['strike'])
            
            print(f"[{self.name}] ✓ Found {len(calls)} calls, {len(puts)} puts for {symbol} exp {expiration_date}")
            print(f"[{self.name}] Got {len(streamer_to_occ)} streamer symbols from Option objects", flush=True)
            
            if DXLINK_AVAILABLE and streamer_to_occ:
                streamer_symbols = list(streamer_to_occ.keys())
                if streamer_symbols[:1]:
                    print(f"[{self.name}] Sample streamer symbol: {streamer_symbols[0]}", flush=True)
                quotes = self._get_option_data_sync(streamer_symbols, timeout=8.0)
                print(f"[{self.name}] DXLink returned {len(quotes)} quotes", flush=True)
                
                if quotes:
                    applied_count = 0
                    for opt_data in calls + puts:
                        for streamer_sym, occ_sym in streamer_to_occ.items():
                            if occ_sym == opt_data['symbol'] and streamer_sym in quotes:
                                q = quotes[streamer_sym]
                                opt_data['bid'] = q.get('bid', 0)
                                opt_data['ask'] = q.get('ask', 0)
                                if opt_data['bid'] > 0 or opt_data['ask'] > 0:
                                    applied_count += 1
                                if opt_data['bid'] > 0 and opt_data['ask'] > 0:
                                    opt_data['last'] = (opt_data['bid'] + opt_data['ask']) / 2
                                break
                    print(f"[{self.name}] ✓ Applied live quotes to {len(quotes)} options ({applied_count} with non-zero prices)", flush=True)
            elif DXLINK_AVAILABLE:
                print(f"[{self.name}] No streamer symbols found in Option objects, skipping DXLink quotes", flush=True)
            
            return {
                'calls': calls,
                'puts': puts,
                'stock_price': None,
                'data_source': 'Tastytrade (DXLink Live)' if DXLINK_AVAILABLE else 'Tastytrade',
                'expiration': expiration_date,
                'symbol': symbol
            }
            
        except Exception as e:
            print(f"[{self.name}] Error getting option chain for {symbol}: {e}")
            import traceback
            traceback.print_exc()
            return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': f'Tastytrade Error: {str(e)}'}
    
    async def get_quote_detailed(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get detailed quote with bid/ask/last for signal verification"""
        if not TASTYTRADE_AVAILABLE or not self.session:
            return None
        
        try:
            def fetch_quote():
                try:
                    equity = Equity.get(self.session, symbol)
                    if equity and hasattr(equity, 'streamer_symbol'):
                        return equity.streamer_symbol
                except Exception:
                    pass
                return None
            
            streamer_symbol = await _await_if_needed(
                await asyncio.to_thread(fetch_quote)
            )
            
            if streamer_symbol and DXLINK_AVAILABLE:
                quotes = self._get_option_data_sync([streamer_symbol], timeout=5.0)
                if quotes and streamer_symbol in quotes:
                    q = quotes[streamer_symbol]
                    return {
                        'symbol': symbol,
                        'bid': q.get('bid', 0),
                        'ask': q.get('ask', 0),
                        'last': (q.get('bid', 0) + q.get('ask', 0)) / 2 if q.get('bid', 0) > 0 else 0,
                        'close': 0,
                        'volume': 0,
                        'source': 'TASTYTRADE'
                    }
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting detailed quote for {symbol}: {e}")
            return None
    
    async def get_option_quote(self, symbol: str, strike: float, expiry: str, option_type: str) -> Optional[Dict[str, Any]]:
        """Get real-time option quote for signal verification"""
        if not TASTYTRADE_AVAILABLE or not self.session:
            return None
        
        try:
            exp_date = datetime.strptime(expiry, '%Y-%m-%d').date()
            opt_type = 'C' if option_type.upper() in ['C', 'CALL'] else 'P'
            
            def fetch_option():
                try:
                    if NESTED_CHAIN_AVAILABLE:
                        chain = NestedOptionChain.get(self.session, symbol)
                        if isinstance(chain, list) and chain:
                            chain = chain[0]
                        
                        for exp in chain.expirations:
                            if exp.expiration_date == exp_date:
                                for strike_obj in exp.strikes:
                                    if abs(float(strike_obj.strike_price) - strike) < 0.01:
                                        if opt_type == 'C' and strike_obj.call:
                                            return strike_obj.call
                                        elif opt_type == 'P' and strike_obj.put:
                                            return strike_obj.put
                except Exception as e:
                    print(f"[{self.name}] Option lookup error: {e}")
                return None
            
            occ_symbol = await _await_if_needed(
                await asyncio.to_thread(fetch_option)
            )
            
            if occ_symbol:
                def get_streamer():
                    try:
                        opts = Option.get_options(self.session, [occ_symbol])
                        if opts and hasattr(opts[0], 'streamer_symbol'):
                            return opts[0].streamer_symbol
                    except Exception:
                        pass
                    return None
                
                streamer_symbol = await _await_if_needed(
                    await asyncio.to_thread(get_streamer)
                )
                
                if streamer_symbol and DXLINK_AVAILABLE:
                    quotes = self._get_option_data_sync([streamer_symbol], timeout=5.0)
                    if quotes and streamer_symbol in quotes:
                        q = quotes[streamer_symbol]
                        return {
                            'symbol': symbol,
                            'strike': strike,
                            'expiry': expiry,
                            'type': option_type,
                            'bid': q.get('bid', 0),
                            'ask': q.get('ask', 0),
                            'last': (q.get('bid', 0) + q.get('ask', 0)) / 2 if q.get('bid', 0) > 0 else 0,
                            'volume': 0,
                            'open_interest': 0,
                            'iv': q.get('iv', 0),
                            'delta': q.get('delta', 0),
                            'source': 'TASTYTRADE'
                        }
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting option quote for {symbol} {strike}{option_type} {expiry}: {e}")
            return None


BrokerFactory.register_broker('TASTYTRADE', TastytradeBroker)
BrokerFactory.register_broker('TASTYTRADE_LIVE', TastytradeBroker)
BrokerFactory.register_broker('TASTYTRADE_PAPER', TastytradeBroker)
