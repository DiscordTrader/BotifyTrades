"""
Tastytrade Broker Implementation
Options-focused trading platform with official API
"""

import sys
import os
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory

try:
    from tastytrade import Session, Account
    from tastytrade.instruments import Equity, Option, get_option_chain, NestedOptionChain
    from tastytrade.order import NewOrder, OrderAction, OrderTimeInForce, OrderType
    TASTYTRADE_AVAILABLE = True
    NESTED_CHAIN_AVAILABLE = True
except ImportError as e:
    print(f"[TASTYTRADE] Warning: tastytrade package not available: {e}")
    TASTYTRADE_AVAILABLE = False
    NESTED_CHAIN_AVAILABLE = False

try:
    from tastytrade import DXLinkStreamer
    from tastytrade.dxfeed import Quote
    DXLINK_AVAILABLE = True
except ImportError as e:
    print(f"[TASTYTRADE] Warning: DXLink streaming not available: {e}")
    DXLINK_AVAILABLE = False


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
    
    async def connect(self) -> bool:
        """Connect to Tastytrade using OAuth2 (preferred) or legacy username/password"""
        try:
            if not TASTYTRADE_AVAILABLE:
                print(f"[{self.name}] ❌ tastytrade package not installed")
                return False
            
            client_secret = self.config.get('client_secret')
            refresh_token = self.config.get('refresh_token')
            username = self.config.get('username')
            password = self.config.get('password')
            
            mode = "SANDBOX" if self.paper_trade else "LIVE"
            print(f"[{self.name}] Connecting to {mode} account...")
            
            if client_secret and refresh_token:
                print(f"[{self.name}] Using OAuth2 authentication...")
                print(f"[{self.name}]    Environment: {'Sandbox' if self.paper_trade else 'Production'}")
                try:
                    self.session = await asyncio.to_thread(
                        Session,
                        client_secret,
                        refresh_token,
                        is_test=self.paper_trade
                    )
                except TypeError:
                    self.session = Session(
                        client_secret,
                        refresh_token,
                        is_test=self.paper_trade
                    )
            elif username and password:
                print(f"[{self.name}] Using legacy username/password authentication...")
                print(f"[{self.name}] ⚠️  NOTE: Session-token login is being deprecated Dec 2025")
                print(f"[{self.name}]    Consider switching to OAuth2 for better reliability")
                try:
                    self.session = await asyncio.to_thread(
                        Session,
                        username,
                        password,
                        is_test=self.paper_trade
                    )
                except Exception as legacy_err:
                    error_str = str(legacy_err).lower()
                    if 'invalid_grant' in error_str or 'jwt' in error_str:
                        print(f"[{self.name}] ❌ Legacy login failed - OAuth2 required!")
                        print(f"[{self.name}] ")
                        print(f"[{self.name}] 📋 TO FIX THIS:")
                        print(f"[{self.name}]    1. Go to my.tastytrade.com")
                        print(f"[{self.name}]    2. Navigate to OAuth Applications")
                        print(f"[{self.name}]    3. Create new app → Save Client Secret")
                        print(f"[{self.name}]    4. Manage → Create Grant → Save Refresh Token")
                        print(f"[{self.name}]    5. Enter Client Secret + Refresh Token in bot settings")
                        print(f"[{self.name}] ")
                        return False
                    raise
            else:
                print(f"[{self.name}] ❌ Missing credentials")
                print(f"[{self.name}]    Option 1 (Recommended): client_secret + refresh_token")
                print(f"[{self.name}]    Option 2 (Deprecated): username + password")
                return False
            
            accounts = await asyncio.to_thread(Account.get, self.session)
            
            if not accounts:
                print(f"[{self.name}] ❌ No accounts found")
                return False
            
            self.account = accounts[0]
            self.connected = True
            
            balances = await asyncio.to_thread(self.account.get_balances, self.session)
            
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
            print(f"[{self.name}] ❌ Connection error: {error_msg}")
            
            if 'invalid_grant' in error_msg.lower() or 'jwt' in error_msg.lower():
                print(f"[{self.name}] ")
                print(f"[{self.name}] ⚠️  TASTYTRADE NOW REQUIRES OAUTH2 AUTHENTICATION")
                print(f"[{self.name}] ")
                print(f"[{self.name}] 📋 How to set up OAuth2:")
                print(f"[{self.name}]    1. Go to my.tastytrade.com")
                print(f"[{self.name}]    2. Navigate to OAuth Applications")
                print(f"[{self.name}]    3. Create new application")
                print(f"[{self.name}]    4. Save your Client Secret")
                print(f"[{self.name}]    5. Go to Manage → Create Grant")
                print(f"[{self.name}]    6. Save your Refresh Token")
                print(f"[{self.name}]    7. Enter both in the Tastytrade broker settings")
                print(f"[{self.name}] ")
            elif 'invalid' in error_msg.lower() or '401' in error_msg or 'unauthorized' in error_msg.lower():
                print(f"[{self.name}] ⚠️  AUTHENTICATION FAILED - Check that:")
                print(f"[{self.name}]    1. Credentials are correct")
                print(f"[{self.name}]    2. Account has API access enabled")
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
                return {'buying_power': 0, 'options_buying_power': 0, 'cash': 0, 'portfolio_value': 0}
            
            balances = await asyncio.to_thread(self.account.get_balances, self.session)
            
            nlv = float(getattr(balances, 'net_liquidating_value', 0) or 0)
            cash = float(getattr(balances, 'cash_balance', 0) or 0)
            derivative_bp = float(getattr(balances, 'derivative_buying_power', 0) or 0)
            equity_bp = float(getattr(balances, 'equity_buying_power', 0) or 0)
            
            return {
                'buying_power': equity_bp,
                'options_buying_power': derivative_bp,
                'cash': cash,
                'portfolio_value': nlv,
                'account_number': self.account.account_number
            }
        except Exception as e:
            print(f"[{self.name}] Error getting account info: {e}")
            import traceback
            traceback.print_exc()
            return {'buying_power': 0, 'options_buying_power': 0, 'cash': 0, 'portfolio_value': 0}
    
    async def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        try:
            if not self.account or not self.session:
                return {}
            
            positions = await asyncio.to_thread(self.account.get_positions, self.session)
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
    
    def get_all_positions(self) -> list:
        """Get all positions as raw objects for sync service (synchronous)"""
        try:
            if not self.account or not self.session:
                print(f"[{self.name}] Not connected")
                return []
            positions = self.account.get_positions(self.session)
            print(f"[{self.name}] get_all_positions returned {len(positions)} positions")
            return positions
        except Exception as e:
            print(f"[{self.name}] Error getting all positions: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def get_orders(self, status: str = 'open') -> list:
        """Get orders by status for sync service (synchronous)"""
        try:
            if not self.account or not self.session:
                print(f"[{self.name}] Not connected")
                return []
            
            orders = self.account.get_live_orders(self.session)
            return orders
        except Exception as e:
            print(f"[{self.name}] Error getting orders: {e}")
            return []
    
    async def place_stock_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        price: Optional[float] = None,
        stop_price: Optional[float] = None
    ) -> OrderResult:
        """Place a stock order"""
        try:
            if not self.account or not self.session:
                return OrderResult(
                    success=False,
                    message="Not connected to Tastytrade",
                    symbol=symbol,
                    action=action
                )
            
            equity = await asyncio.to_thread(Equity.get, self.session, symbol)
            
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
            
            response = await asyncio.to_thread(
                self.account.place_order,
                self.session,
                order,
                dry_run=False
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
                chain = await asyncio.to_thread(get_option_chain, self.session, symbol)
                
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
            
            response = await asyncio.to_thread(
                self.account.place_order,
                self.session,
                order,
                dry_run=False
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
        """Get current price for a symbol"""
        try:
            if not self.session:
                return None
            
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
            return None
    
    async def get_option_quotes_dxlink(self, symbols: list, timeout: float = 5.0) -> Dict[str, Dict[str, float]]:
        """Fetch live bid/ask quotes for option symbols using DXLink streaming.
        
        DXLink streaming data is FREE for funded personal tastytrade accounts.
        
        Args:
            symbols: List of option symbols (OCC format)
            timeout: Maximum time to wait for quotes (seconds)
            
        Returns:
            Dict mapping symbol to {'bid': price, 'ask': price}
        """
        quotes = {}
        
        if not DXLINK_AVAILABLE:
            print(f"[{self.name}] DXLink streaming not available")
            return quotes
        
        if not self.session:
            print(f"[{self.name}] Not connected - cannot fetch quotes")
            return quotes
        
        if not symbols:
            return quotes
        
        try:
            print(f"[{self.name}] Fetching live quotes for {len(symbols)} options via DXLink...")
            
            async with DXLinkStreamer(self.session) as streamer:
                await streamer.subscribe(Quote, symbols)
                
                received = 0
                start_time = asyncio.get_event_loop().time()
                
                while received < len(symbols):
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed >= timeout:
                        print(f"[{self.name}] Quote timeout after {elapsed:.1f}s, got {received}/{len(symbols)} quotes")
                        break
                    
                    try:
                        quote = await asyncio.wait_for(
                            streamer.get_event(Quote),
                            timeout=min(1.0, timeout - elapsed)
                        )
                        
                        if quote and hasattr(quote, 'event_symbol'):
                            sym = quote.event_symbol
                            if sym not in quotes:
                                bid = float(quote.bid_price) if quote.bid_price else 0.0
                                ask = float(quote.ask_price) if quote.ask_price else 0.0
                                quotes[sym] = {'bid': bid, 'ask': ask}
                                received += 1
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        print(f"[{self.name}] Quote event error: {e}")
                        continue
            
            print(f"[{self.name}] ✓ Received {len(quotes)} live quotes")
            return quotes
            
        except Exception as e:
            print(f"[{self.name}] DXLink streaming error: {e}")
            import traceback
            traceback.print_exc()
            return quotes
    
    def _get_option_quotes_sync(self, symbols: list, timeout: float = 5.0) -> Dict[str, Dict[str, float]]:
        """Synchronous wrapper for get_option_quotes_dxlink for use in Flask routes."""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            
            if loop is not None:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.get_option_quotes_dxlink(symbols, timeout)
                    )
                    return future.result(timeout=timeout + 2)
            else:
                return asyncio.run(self.get_option_quotes_dxlink(symbols, timeout))
        except Exception as e:
            print(f"[{self.name}] Sync quote fetch error: {e}")
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
            
            if not self.session:
                print(f"[{self.name}] Not connected - cannot get expiration dates")
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
                    nested_chain = NestedOptionChain.get(self.session, symbol)
                    
                    if not nested_chain or not nested_chain.expirations:
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
                            print(f"[{self.name}] Fetching DXLink quotes for {len(streamer_symbols)} streamer symbols...", flush=True)
                            if streamer_symbols[:1]:
                                print(f"[{self.name}] Sample streamer symbol: {streamer_symbols[0]}", flush=True)
                            quotes = self._get_option_quotes_sync(streamer_symbols, timeout=8.0)
                            print(f"[{self.name}] DXLink returned {len(quotes)} quotes", flush=True)
                            
                            if quotes:
                                applied_count = 0
                                for opt in calls + puts:
                                    for streamer_sym, occ_sym in streamer_to_occ.items():
                                        if occ_sym == opt['symbol'] and streamer_sym in quotes:
                                            q = quotes[streamer_sym]
                                            opt['bid'] = q.get('bid', 0)
                                            opt['ask'] = q.get('ask', 0)
                                            if opt['bid'] > 0 or opt['ask'] > 0:
                                                applied_count += 1
                                            if opt['bid'] > 0 and opt['ask'] > 0:
                                                opt['last'] = (opt['bid'] + opt['ask']) / 2
                                            break
                                print(f"[{self.name}] ✓ Applied live quotes to {len(quotes)} options ({applied_count} with non-zero prices)", flush=True)
                        else:
                            print(f"[{self.name}] No streamer symbols available, skipping DXLink quotes", flush=True)
                    
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
                quotes = self._get_option_quotes_sync(streamer_symbols, timeout=8.0)
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


BrokerFactory.register_broker('TASTYTRADE', TastytradeBroker)
BrokerFactory.register_broker('TASTYTRADE_LIVE', TastytradeBroker)
BrokerFactory.register_broker('TASTYTRADE_PAPER', TastytradeBroker)
