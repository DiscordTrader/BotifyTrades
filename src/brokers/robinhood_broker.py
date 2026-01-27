"""
Robinhood Broker Implementation
Uses unofficial robin-stocks library
WARNING: No paper trading - all trades are LIVE
"""

import sys
import os
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory

try:
    import robin_stocks.robinhood as rh
    import pyotp
    ROBIN_STOCKS_AVAILABLE = True
except ImportError:
    ROBIN_STOCKS_AVAILABLE = False
    rh = None
    pyotp = None


class RobinhoodBroker(BrokerInterface):
    """
    Robinhood broker implementation using robin-stocks library
    
    WARNING: Robinhood does NOT have paper trading.
    All trades executed through this broker are LIVE with real money.
    
    Authentication requires:
    - Username (email)
    - Password
    - 2FA TOTP secret (from authenticator app setup)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "ROBINHOOD"
        self.paper_trade = False  # Robinhood has NO paper trading
        self._logged_in = False
        
        if not ROBIN_STOCKS_AVAILABLE:
            print(f"[{self.name}] WARNING: robin-stocks library not installed")
            print(f"[{self.name}] Install with: pip install robin-stocks pyotp")
    
    async def connect(self) -> bool:
        """
        Connect to Robinhood using credentials and 2FA
        
        Required config keys:
        - username: Robinhood email
        - password: Robinhood password
        - totp_secret: 2FA authenticator secret (from Robinhood app setup)
        """
        if not ROBIN_STOCKS_AVAILABLE:
            print(f"[{self.name}] ❌ robin-stocks library not installed")
            return False
        
        try:
            username = self.config.get('username')
            password = self.config.get('password')
            totp_secret = self.config.get('totp_secret')
            
            if not username or not password:
                print(f"[{self.name}] ❌ Missing username or password")
                return False
            
            print(f"[{self.name}] ⚠️  WARNING: Robinhood has NO paper trading mode")
            print(f"[{self.name}] ⚠️  ALL trades will be executed with REAL money")
            print(f"[{self.name}] Connecting to account: {username[:3]}***@***")
            
            def do_login():
                mfa_code = None
                if totp_secret:
                    try:
                        mfa_code = pyotp.TOTP(totp_secret).now()
                        print(f"[{self.name}] Generated 2FA code: {mfa_code}")
                    except Exception as e:
                        print(f"[{self.name}] ⚠️  2FA generation failed: {e}")
                
                login_result = rh.login(
                    username=username,
                    password=password,
                    mfa_code=mfa_code,
                    store_session=True,
                    expiresIn=86400
                )
                return login_result
            
            login_result = await asyncio.to_thread(do_login)
            
            if login_result and 'access_token' in login_result:
                self.connected = True
                self._logged_in = True
                
                account_info = await self.get_account_info()
                buying_power = account_info.get('buying_power', 0)
                
                print(f"[{self.name}] ✓ Connected successfully (LIVE trading)")
                print(f"[{self.name}]   Buying power: ${buying_power:,.2f}")
                return True
            else:
                print(f"[{self.name}] ❌ Login failed")
                if login_result:
                    detail = login_result.get('detail', 'Unknown error')
                    print(f"[{self.name}]   Error: {detail}")
                return False
                
        except Exception as e:
            import traceback
            print(f"[{self.name}] ❌ Connection error: {e}")
            traceback.print_exc()
            return False
    
    async def disconnect(self):
        """Disconnect from Robinhood"""
        try:
            if ROBIN_STOCKS_AVAILABLE and self._logged_in:
                await asyncio.to_thread(rh.logout)
        except Exception as e:
            print(f"[{self.name}] Logout error (non-critical): {e}")
        
        self.connected = False
        self._logged_in = False
        print(f"[{self.name}] Disconnected")
    
    def _get_extended_hours_enabled(self) -> bool:
        """Check if extended hours trading is enabled for Robinhood.
        
        Robinhood extendedHours parameter allows STOCK orders to execute during:
        - Pre-market: 9:00 AM - 9:30 AM ET
        - After-hours: 4:00 PM - 6:00 PM ET
        
        Note: Extended hours ONLY works for STOCKS, NOT options.
        Options can only be traded during regular market hours.
        
        Returns:
            True if extended hours is enabled
        """
        try:
            from gui_app.database import get_broker_extended_hours
            enabled = get_broker_extended_hours('robinhood')
            if enabled:
                print(f"[{self.name}] Extended hours ENABLED (stocks only)")
            return enabled
        except ImportError:
            return False
        except Exception as e:
            print(f"[{self.name}] Error checking extended hours setting: {e}")
            return False
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return {'buying_power': 0, 'cash': 0, 'portfolio_value': 0}
        
        try:
            def get_profile():
                return rh.profiles.load_account_profile()
            
            def get_portfolio():
                return rh.profiles.load_portfolio_profile()
            
            account = await asyncio.to_thread(get_profile)
            portfolio = await asyncio.to_thread(get_portfolio)
            
            buying_power = 0.0
            cash = 0.0
            portfolio_value = 0.0
            
            if account:
                buying_power = float(account.get('buying_power', 0) or 0)
                cash = float(account.get('cash', 0) or 0)
            
            if portfolio:
                portfolio_value = float(portfolio.get('equity', 0) or 0)
            
            return {
                'buying_power': buying_power,
                'options_buying_power': buying_power,
                'cash': cash,
                'portfolio_value': portfolio_value
            }
            
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            return {'buying_power': 0, 'options_buying_power': 0, 'cash': 0, 'portfolio_value': 0}
    
    async def get_positions(self) -> Dict[str, Any]:
        """Get current stock positions"""
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return {}
        
        try:
            def get_holdings():
                return rh.account.build_holdings()
            
            holdings = await asyncio.to_thread(get_holdings)
            
            result = {}
            if holdings:
                for symbol, data in holdings.items():
                    qty = float(data.get('quantity', 0))
                    result[symbol] = int(qty) if qty == int(qty) else qty
            
            return result
            
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return {}
    
    def get_all_positions(self) -> list:
        """Get all positions as raw objects for sync service (synchronous)"""
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return []
        
        try:
            holdings = rh.account.build_holdings()
            positions = []
            
            if holdings:
                for symbol, data in holdings.items():
                    qty = float(data.get('quantity', 0))
                    current_price = float(data.get('price', 0) or 0)
                    avg_price = float(data.get('average_buy_price', 0))
                    equity = float(data.get('equity', 0))
                    unrealized_pnl = (current_price - avg_price) * qty if current_price and avg_price else 0
                    
                    positions.append({
                        'symbol': symbol,
                        'quantity': qty,
                        'average_buy_price': avg_price,
                        'avg_price': avg_price,
                        'current_price': current_price,
                        'market_value': equity,
                        'equity': equity,
                        'unrealized_pnl': unrealized_pnl,
                        'percent_change': float(data.get('percent_change', 0)),
                        'type': 'stock',
                        'asset_type': 'stock'
                    })
            
            option_positions = rh.options.get_open_option_positions()
            if option_positions:
                for pos in option_positions:
                    raw_avg_price = pos.get('average_price')
                    raw_avg_float = float(raw_avg_price or 0)
                    qty = float(pos.get('quantity', 0))
                    
                    # Robinhood returns average_price in different formats:
                    # - Some positions return price per contract in dollars (e.g., 1.25 = $1.25)
                    # - Others return price in cents or total (e.g., 100.0 might mean $1.00)
                    # If price seems too high (>$50 per contract), assume it's in cents
                    if raw_avg_float > 50:
                        avg_price = raw_avg_float / 100.0  # Convert from cents to dollars
                        print(f"[ROBINHOOD] Option position: {pos.get('chain_symbol')} - converted avg_price from {raw_avg_float} cents to ${avg_price:.4f}")
                    else:
                        avg_price = raw_avg_float
                        print(f"[ROBINHOOD] Option position: {pos.get('chain_symbol')} - avg_price=${avg_price:.4f}")
                    
                    # Get option instrument details (strike, expiry, type)
                    option_url = pos.get('option', '')
                    option_id = pos.get('option_id') or option_url
                    strike_price = None
                    expiration_date = None
                    option_type = None
                    
                    # Extract option ID from URL if needed
                    if isinstance(option_id, str) and '/' in option_id:
                        option_id = option_id.rstrip('/').split('/')[-1]
                    
                    # Fetch option instrument details for strike/expiry/type
                    if option_id:
                        try:
                            option_info = rh.options.get_option_instrument_data_by_id(option_id)
                            if option_info:
                                strike_price = option_info.get('strike_price')
                                expiration_date = option_info.get('expiration_date')
                                option_type = option_info.get('type')  # 'call' or 'put'
                        except Exception as e:
                            print(f"[ROBINHOOD] Could not fetch option instrument details: {e}")
                    
                    # Fetch current mark price for P&L calculation
                    current_price = avg_price  # Fallback to avg_price
                    try:
                        if option_id:
                            market_data = rh.options.get_option_market_data_by_id(option_id)
                            if market_data and len(market_data) > 0:
                                data = market_data[0] if isinstance(market_data, list) else market_data
                                current_price = float(data.get('adjusted_mark_price') or data.get('mark_price') or data.get('last_trade_price') or avg_price)
                    except Exception as e:
                        print(f"[ROBINHOOD] Could not fetch mark price for option: {e}")
                    
                    # Calculate P&L with 100x multiplier for options
                    unrealized_pnl = (current_price - avg_price) * qty * 100 if current_price and avg_price else 0
                    
                    # Map option_type to call_put (C/P format)
                    call_put = 'C' if option_type == 'call' else 'P' if option_type == 'put' else None
                    
                    # Normalize strike to float
                    strike_float = float(strike_price) if strike_price else None
                    
                    positions.append({
                        'symbol': pos.get('chain_symbol', ''),
                        'quantity': qty,
                        'average_price': avg_price,
                        'avg_price': avg_price,
                        'current_price': current_price,
                        'unrealized_pnl': unrealized_pnl,
                        'market_value': current_price * qty * 100,
                        'type': 'option',
                        'asset_type': 'option',
                        'option_type': option_type or '',
                        'strike_price': strike_price or '',
                        'expiration_date': expiration_date or '',
                        # Sync service expects these field names:
                        'strike': strike_float,
                        'expiry': expiration_date or '',
                        'call_put': call_put
                    })
            
            return positions
            
        except Exception as e:
            print(f"[{self.name}] Error getting all positions: {e}")
            return []
    
    def get_orders(self, status: str = 'open') -> list:
        """Get orders by status for sync service (synchronous)"""
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return []
        
        try:
            if status == 'open':
                stock_orders = rh.orders.get_all_open_stock_orders() or []
                option_orders = []
                try:
                    option_orders = rh.orders.get_all_open_option_orders() or []
                except Exception:
                    pass
                return list(stock_orders) + list(option_orders)
            else:
                stock_orders = rh.orders.get_all_stock_orders() or []
                option_orders = []
                try:
                    option_orders = rh.orders.get_all_option_orders() or []
                except Exception:
                    pass
                return list(stock_orders) + list(option_orders)
                
        except Exception as e:
            print(f"[{self.name}] Error getting orders: {e}")
            return []
    
    def get_pending_orders(self) -> list:
        """Get pending/open orders for BrokerSyncService (synchronous)
        
        Returns list of orders with BrokerSyncService expected fields:
        - broker_order_id, symbol, quantity, limit_price, order_type, status
        """
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return []
        
        try:
            orders = []
            
            stock_orders = rh.orders.get_all_open_stock_orders() or []
            for order in stock_orders:
                instrument_url = order.get('instrument', '')
                symbol = order.get('symbol', '')
                if not symbol and instrument_url:
                    try:
                        instrument = rh.stocks.get_instrument_by_url(instrument_url)
                        symbol = instrument.get('symbol', '') if instrument else ''
                    except:
                        pass
                
                side = order.get('side', 'buy').upper()
                order_type = 'BTO' if side == 'BUY' else 'STC'
                state = order.get('state', 'pending').upper()
                status = 'PENDING' if state in ('QUEUED', 'CONFIRMED', 'PENDING') else state
                
                orders.append({
                    'broker_order_id': order.get('id'),
                    'symbol': symbol,
                    'quantity': float(order.get('quantity', 0)),
                    'limit_price': float(order.get('price', 0) or order.get('average_price', 0) or 0),
                    'order_type': order_type,
                    'status': status,
                    'asset_type': 'stock'
                })
            
            try:
                option_orders = rh.orders.get_all_open_option_orders() or []
                for order in option_orders:
                    symbol = order.get('chain_symbol', '')
                    direction = order.get('direction', 'debit').upper()
                    order_type = 'BTO' if 'DEBIT' in direction else 'STC'
                    state = order.get('state', 'pending').upper()
                    status = 'PENDING' if state in ('QUEUED', 'CONFIRMED', 'PENDING') else state
                    
                    orders.append({
                        'broker_order_id': order.get('id'),
                        'symbol': symbol,
                        'quantity': float(order.get('quantity', 0)),
                        'limit_price': float(order.get('price', 0) or order.get('premium', 0) or 0),
                        'order_type': order_type,
                        'status': status,
                        'asset_type': 'option'
                    })
            except Exception:
                pass
            
            return orders
            
        except Exception as e:
            print(f"[{self.name}] Error getting pending orders: {e}")
            return []
    
    def get_options_expiration_dates(self, symbol: str) -> list:
        """Get available option expiration dates for a symbol.
        
        Uses robin-stocks library to fetch tradable options and extract unique expiration dates.
        
        Args:
            symbol: Underlying stock symbol
            
        Returns:
            List of expiration dates in YYYY-MM-DD format, sorted chronologically
        """
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            print(f"[{self.name}] Not connected, cannot fetch expirations")
            return []
        
        try:
            options = rh.options.find_tradable_options(symbol)
            
            if not options:
                print(f"[{self.name}] No tradable options found for {symbol}")
                return []
            
            expirations = set()
            for opt in options:
                exp = opt.get('expiration_date')
                if exp:
                    expirations.add(exp)
            
            sorted_expirations = sorted(list(expirations))
            print(f"[{self.name}] Found {len(sorted_expirations)} expiration dates for {symbol}")
            return sorted_expirations
            
        except Exception as e:
            print(f"[{self.name}] Error fetching expiration dates for {symbol}: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_option_chain(self, symbol: str, expiry: str) -> Dict[str, Any]:
        """Get option chain for a symbol and expiry date.
        
        Uses robin-stocks library to fetch options data.
        Optimized to only fetch ITM + limited OTM strikes for performance.
        
        Args:
            symbol: Underlying stock symbol
            expiry: Expiration date in YYYY-MM-DD format
            
        Returns:
            Dict with 'calls', 'puts', 'stock_price', 'data_source' keys
        """
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': 'Error: Robinhood not connected'}
        
        # Configurable: how many OTM strikes to load per side
        OTM_LIMIT = 15
        
        try:
            # Get stock price first (needed for ITM/OTM filtering)
            stock_price = None
            try:
                prices = rh.stocks.get_latest_price(symbol)
                if prices and prices[0]:
                    stock_price = float(prices[0])
            except:
                pass
            
            # Normalize expiry format to YYYY-MM-DD
            if "/" in expiry:
                parts = expiry.split("/")
                if len(parts) == 2:
                    m, d = parts
                    from datetime import datetime
                    y = datetime.now().year
                    expiry = f"{y:04d}-{int(m):02d}-{int(d):02d}"
                elif len(parts) == 3:
                    m, d, y = parts
                    if len(y) == 2:
                        y = f"20{y}"
                    expiry = f"{y}-{int(m):02d}-{int(d):02d}"
            
            calls = []
            puts = []
            
            # Get call options - just get the strikes first (fast)
            call_options = rh.options.find_tradable_options(
                symbol,
                expirationDate=expiry,
                optionType='call'
            )
            
            # Get put options
            put_options = rh.options.find_tradable_options(
                symbol,
                expirationDate=expiry,
                optionType='put'
            )
            
            # Filter strikes to ITM + limited OTM for performance
            if stock_price and stock_price > 0:
                # CALLS: ITM = strike < stock_price, OTM = strike >= stock_price
                if call_options:
                    # Sort by strike
                    call_options = sorted(call_options, key=lambda x: float(x.get('strike_price', 0)))
                    itm_calls = [opt for opt in call_options if float(opt.get('strike_price', 0)) < stock_price]
                    otm_calls = [opt for opt in call_options if float(opt.get('strike_price', 0)) >= stock_price]
                    # Take all ITM + first OTM_LIMIT OTM strikes
                    call_options = itm_calls + otm_calls[:OTM_LIMIT]
                
                # PUTS: ITM = strike > stock_price, OTM = strike <= stock_price
                if put_options:
                    # Sort by strike descending to get closest OTM first
                    put_options = sorted(put_options, key=lambda x: float(x.get('strike_price', 0)))
                    itm_puts = [opt for opt in put_options if float(opt.get('strike_price', 0)) > stock_price]
                    otm_puts = [opt for opt in put_options if float(opt.get('strike_price', 0)) <= stock_price]
                    # Take last OTM_LIMIT OTM strikes (closest to ATM) + all ITM
                    call_options_count = len(call_options) if call_options else 0
                    put_options = otm_puts[-OTM_LIMIT:] + itm_puts
                
                total_options = (len(call_options) if call_options else 0) + (len(put_options) if put_options else 0)
                print(f"[{self.name}] Filtered to {total_options} strikes (ITM + {OTM_LIMIT} OTM per side) near ${stock_price:.2f}")
            
            # Fetch market data for filtered call options
            if call_options:
                for opt in call_options:
                    strike = float(opt.get('strike_price', 0))
                    opt_id = opt.get('id', '')
                    
                    data = {}
                    if opt_id:
                        try:
                            result = rh.options.get_option_market_data_by_id(opt_id)
                            if result and isinstance(result, list) and len(result) > 0:
                                data = result[0] or {}
                            elif result and isinstance(result, dict):
                                data = result
                        except:
                            pass
                    
                    calls.append({
                        'strike': strike,
                        'bid': float(data.get('bid_price', 0) or 0),
                        'ask': float(data.get('ask_price', 0) or 0),
                        'last': float(data.get('adjusted_mark_price', 0) or data.get('mark_price', 0) or data.get('last_trade_price', 0) or 0),
                        'volume': int(data.get('volume', 0) or 0),
                        'open_interest': int(data.get('open_interest', 0) or 0),
                        'iv': float(data.get('implied_volatility', 0) or 0),
                        'delta': float(data.get('delta', 0) or 0),
                        'gamma': float(data.get('gamma', 0) or 0),
                        'theta': float(data.get('theta', 0) or 0),
                        'vega': float(data.get('vega', 0) or 0),
                    })
            
            # Fetch market data for filtered put options
            if put_options:
                for opt in put_options:
                    strike = float(opt.get('strike_price', 0))
                    opt_id = opt.get('id', '')
                    
                    data = {}
                    if opt_id:
                        try:
                            result = rh.options.get_option_market_data_by_id(opt_id)
                            if result and isinstance(result, list) and len(result) > 0:
                                data = result[0] or {}
                            elif result and isinstance(result, dict):
                                data = result
                        except:
                            pass
                    
                    puts.append({
                        'strike': strike,
                        'bid': float(data.get('bid_price', 0) or 0),
                        'ask': float(data.get('ask_price', 0) or 0),
                        'last': float(data.get('adjusted_mark_price', 0) or data.get('mark_price', 0) or data.get('last_trade_price', 0) or 0),
                        'volume': int(data.get('volume', 0) or 0),
                        'open_interest': int(data.get('open_interest', 0) or 0),
                        'iv': float(data.get('implied_volatility', 0) or 0),
                        'delta': float(data.get('delta', 0) or 0),
                        'gamma': float(data.get('gamma', 0) or 0),
                        'theta': float(data.get('theta', 0) or 0),
                        'vega': float(data.get('vega', 0) or 0),
                    })
            
            # Sort by strike
            calls.sort(key=lambda x: x['strike'])
            puts.sort(key=lambda x: x['strike'])
            
            print(f"[{self.name}] ✓ Fetched option chain: {len(calls)} calls, {len(puts)} puts for {symbol} {expiry}")
            
            return {
                'calls': calls,
                'puts': puts,
                'stock_price': stock_price,
                'data_source': 'Robinhood'
            }
            
        except Exception as e:
            print(f"[{self.name}] Error getting option chain: {e}")
            import traceback
            traceback.print_exc()
            return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': f'Error: {str(e)}'}
    
    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        stop_price: Optional[float] = None
    ) -> OrderResult:
        """
        Place a stock order
        
        Args:
            symbol: Stock ticker (e.g., "AAPL")
            action: BTO (buy) or STC (sell)
            quantity: Number of shares
            price: Limit price (None for market order)
            stop_price: Stop price (for stop loss orders)
        """
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return OrderResult(
                success=False,
                message="Robinhood not connected",
                symbol=symbol,
                action=action
            )
        
        try:
            is_buy = action.upper() in ['BTO', 'BUY']
            extended_hours_enabled = self._get_extended_hours_enabled()
            
            def execute_order():
                if stop_price is not None:
                    # Stop orders do NOT support extended hours on Robinhood
                    if extended_hours_enabled:
                        print(f"[{self.name}] ⚠️ Extended hours disabled for STOP orders (not supported by Robinhood)")
                    if is_buy:
                        return rh.orders.order_buy_stop_loss(
                            symbol=symbol,
                            quantity=quantity,
                            stopPrice=stop_price,
                            timeInForce='gtc'
                        )
                    else:
                        return rh.orders.order_sell_stop_loss(
                            symbol=symbol,
                            quantity=quantity,
                            stopPrice=stop_price,
                            timeInForce='gtc'
                        )
                elif price is not None:
                    # Limit orders support extended hours
                    if is_buy:
                        return rh.orders.order_buy_limit(
                            symbol=symbol,
                            quantity=quantity,
                            limitPrice=price,
                            timeInForce='gtc',
                            extendedHours=extended_hours_enabled
                        )
                    else:
                        return rh.orders.order_sell_limit(
                            symbol=symbol,
                            quantity=quantity,
                            limitPrice=price,
                            timeInForce='gtc',
                            extendedHours=extended_hours_enabled
                        )
                else:
                    # Market orders support extended hours
                    if is_buy:
                        return rh.orders.order_buy_market(
                            symbol=symbol,
                            quantity=quantity,
                            timeInForce='gtc',
                            extendedHours=extended_hours_enabled
                        )
                    else:
                        return rh.orders.order_sell_market(
                            symbol=symbol,
                            quantity=quantity,
                            timeInForce='gtc',
                            extendedHours=extended_hours_enabled
                        )
            
            order = await asyncio.to_thread(execute_order)
            
            if order and order.get('id'):
                order_type = "STOP" if stop_price else ("LIMIT" if price else "MARKET")
                return OrderResult(
                    success=True,
                    order_id=order.get('id'),
                    message=f"{order_type} order placed: {action} {quantity} {symbol}",
                    price=price or stop_price or float(order.get('average_price', 0) or 0),
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                error_detail = order.get('detail', 'Unknown error') if order else 'No response'
                return OrderResult(
                    success=False,
                    message=f"Order failed: {error_detail}",
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
        """
        Place an options order
        
        NOTE: Robinhood only supports LIMIT orders for options.
        If price is None, we'll attempt to get current bid/ask.
        
        Args:
            symbol: Underlying ticker (e.g., "AAPL")
            strike: Strike price
            expiry: Expiration date (YYYY-MM-DD or MM/DD/YY)
            option_type: "call" or "put" (or "C"/"P")
            action: BTO or STC
            quantity: Number of contracts
            price: Limit price (REQUIRED for Robinhood options)
        """
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return OrderResult(
                success=False,
                message="Robinhood not connected",
                symbol=symbol,
                action=action
            )
        
        try:
            expiry_date = self._normalize_expiry(expiry)
            opt_type = 'call' if option_type.upper().startswith('C') else 'put'
            is_buy = action.upper() in ['BTO', 'BUY']
            
            if is_buy:
                position_effect = 'open'
                credit_or_debit = 'debit'
            else:
                position_effect = 'close'
                credit_or_debit = 'credit'
            
            if price is None or price <= 0:
                print(f"[{self.name}] ⚠️  Options require limit price - attempting to get market price")
                market_price = await self._get_option_price(symbol, strike, expiry_date, opt_type, is_buy)
                if market_price:
                    price = market_price
                    print(f"[{self.name}] Using market price: ${price:.2f}")
                else:
                    return OrderResult(
                        success=False,
                        message="Robinhood options require a limit price. Could not determine market price.",
                        symbol=symbol,
                        action=action
                    )
            
            index_symbols = {'SPX', 'SPXW', 'NDX', 'NDXP', 'VIX', 'VIXW', 'RUT', 'DJX', 'XSP'}
            is_index_option = symbol.upper() in index_symbols
            
            if is_index_option:
                original_price = price
                price = round(price * 20) / 20
                if price != original_price:
                    print(f"[{self.name}] Index option tick: ${original_price:.2f} → ${price:.2f} ($0.05 min tick)")
            else:
                original_price = price
                price = round(price * 100) / 100
                if price != original_price:
                    print(f"[{self.name}] Standard tick: ${original_price:.4f} → ${price:.2f} ($0.01 min tick)")
            
            def execute_option_order():
                if is_buy:
                    return rh.orders.order_buy_option_limit(
                        positionEffect=position_effect,
                        creditOrDebit=credit_or_debit,
                        price=price,
                        symbol=symbol,
                        quantity=quantity,
                        expirationDate=expiry_date,
                        strike=strike,
                        optionType=opt_type,
                        timeInForce='gtc'
                    )
                else:
                    return rh.orders.order_sell_option_limit(
                        positionEffect=position_effect,
                        creditOrDebit=credit_or_debit,
                        price=price,
                        symbol=symbol,
                        quantity=quantity,
                        expirationDate=expiry_date,
                        strike=strike,
                        optionType=opt_type,
                        timeInForce='gtc'
                    )
            
            print(f"[{self.name}] Submitting option order: {action} {quantity} {symbol} ${strike}{opt_type[0].upper()} {expiry_date} @ ${price:.2f}")
            order = await asyncio.to_thread(execute_option_order)
            
            if order and order.get('id'):
                return OrderResult(
                    success=True,
                    order_id=order.get('id'),
                    message=f"Option LIMIT order placed: {action} {quantity} {symbol} ${strike}{opt_type[0].upper()} {expiry_date}",
                    price=price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                error_detail = order.get('detail', 'Unknown error') if order else 'No response'
                return OrderResult(
                    success=False,
                    message=f"Option order failed: {error_detail}",
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            import traceback
            print(f"[{self.name}] ❌ Option order exception: {e}")
            traceback.print_exc()
            return OrderResult(
                success=False,
                message=f"Exception: {str(e)}",
                symbol=symbol,
                action=action
            )
    
    async def get_quote(self, symbol: str) -> Optional[float]:
        """Get current price for a stock symbol"""
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return None
        
        try:
            def get_price():
                prices = rh.stocks.get_latest_price(symbol)
                if prices and len(prices) > 0:
                    return float(prices[0]) if prices[0] else None
                return None
            
            return await asyncio.to_thread(get_price)
            
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
            return None
    
    async def _get_option_price(
        self,
        symbol: str,
        strike: float,
        expiry: str,
        option_type: str,
        is_buy: bool
    ) -> Optional[float]:
        """Get option market price for limit order"""
        try:
            def get_option_data():
                options = rh.options.find_options_by_expiration_and_strike(
                    inputSymbols=symbol,
                    expirationDate=expiry,
                    strikePrice=str(strike),
                    optionType=option_type
                )
                return options
            
            options = await asyncio.to_thread(get_option_data)
            
            if options and len(options) > 0:
                option = options[0]
                if is_buy:
                    price = option.get('ask_price') or option.get('adjusted_mark_price')
                else:
                    price = option.get('bid_price') or option.get('adjusted_mark_price')
                
                if price:
                    return float(price)
            
            return None
            
        except Exception as e:
            print(f"[{self.name}] Error getting option price: {e}")
            return None
    
    def _normalize_expiry(self, expiry: str) -> str:
        """Convert various expiry formats to YYYY-MM-DD"""
        if '-' in expiry and len(expiry) == 10:
            return expiry
        
        try:
            if "/" in expiry:
                parts = expiry.split("/")
                if len(parts) == 2:
                    m, d = parts
                    y = datetime.now().year
                    return f"{y:04d}-{int(m):02d}-{int(d):02d}"
                elif len(parts) == 3:
                    m, d, y = parts
                    if len(y) == 2:
                        y = f"20{y}"
                    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
        except Exception as e:
            print(f"[{self.name}] Warning: Could not parse expiry '{expiry}': {e}")
        
        return expiry
    
    async def cancel_order(self, order_id: str, order_type: str = 'stock') -> bool:
        """Cancel an open order"""
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return False
        
        try:
            def do_cancel():
                if order_type == 'option':
                    return rh.orders.cancel_option_order(order_id)
                else:
                    return rh.orders.cancel_stock_order(order_id)
            
            result = await asyncio.to_thread(do_cancel)
            return result is not None
            
        except Exception as e:
            print(f"[{self.name}] Error cancelling order {order_id}: {e}")
            return False
    
    async def get_quote_detailed(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get detailed quote with bid/ask/last for signal verification"""
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return None
        
        try:
            def get_quote_data():
                quotes = rh.stocks.get_quotes(symbol)
                if quotes and len(quotes) > 0:
                    return quotes[0]
                return None
            
            quote = await asyncio.to_thread(get_quote_data)
            
            if quote:
                return {
                    'symbol': symbol,
                    'bid': float(quote.get('bid_price') or 0),
                    'ask': float(quote.get('ask_price') or 0),
                    'last': float(quote.get('last_trade_price') or 0),
                    'close': float(quote.get('previous_close') or 0),
                    'volume': int(float(quote.get('volume') or 0)),
                    'source': 'ROBINHOOD'
                }
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting detailed quote for {symbol}: {e}")
            return None
    
    async def get_option_quote(self, symbol: str, strike: float, expiry: str, option_type: str) -> Optional[Dict[str, Any]]:
        """Get real-time option quote for signal verification"""
        if not ROBIN_STOCKS_AVAILABLE or not self._logged_in:
            return None
        
        try:
            expiry_normalized = self._normalize_expiry(expiry)
            opt_type = 'call' if option_type.upper() in ['C', 'CALL'] else 'put'
            
            def get_option_data():
                options = rh.options.find_options_by_expiration_and_strike(
                    inputSymbols=symbol,
                    expirationDate=expiry_normalized,
                    strikePrice=str(strike),
                    optionType=opt_type
                )
                return options
            
            options = await asyncio.to_thread(get_option_data)
            
            if options and len(options) > 0:
                option = options[0]
                return {
                    'symbol': symbol,
                    'strike': strike,
                    'expiry': expiry,
                    'type': option_type,
                    'bid': float(option.get('bid_price') or 0),
                    'ask': float(option.get('ask_price') or 0),
                    'last': float(option.get('adjusted_mark_price') or 0),
                    'volume': int(float(option.get('volume') or 0)),
                    'open_interest': int(float(option.get('open_interest') or 0)),
                    'iv': float(option.get('implied_volatility') or 0),
                    'delta': float(option.get('delta') or 0),
                    'source': 'ROBINHOOD'
                }
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting option quote for {symbol} {strike}{option_type} {expiry}: {e}")
            return None


BrokerFactory.register_broker('ROBINHOOD', RobinhoodBroker)
