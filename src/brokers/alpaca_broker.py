"""
Alpaca Broker Implementation
Commission-free trading with official API
"""

import sys
import os
import asyncio
from typing import Optional, Dict, Any
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopOrderRequest,
    GetOrdersRequest,
    GetOptionContractsRequest,
    StopLossRequest,
    TakeProfitRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    QueryOrderStatus,
    OrderClass,
    AssetClass,
    AssetStatus,
    ExerciseStyle,
    OrderType,
    PositionIntent,
)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, OptionLatestQuoteRequest

# Add parent directory to path for absolute imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from broker_interface import BrokerInterface, OrderResult, BrokerFactory


class AlpacaBroker(BrokerInterface):
    """Alpaca broker implementation using official alpaca-py SDK"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.name = "ALPACA"
        self.trading_client = None
        self.data_client = None
        self.option_data_client = None
        self.paper_trade = config.get('paper_trade', True)
    
    async def connect(self) -> bool:
        """Connect to Alpaca"""
        try:
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                self._event_loop = None
            api_key = self.config.get('api_key')
            api_secret = self.config.get('api_secret')
            
            if not api_key or not api_secret:
                print(f"[{self.name}] ❌ Missing API credentials")
                return False
            
            # Show which mode and which key (first 10 chars)
            mode = "PAPER" if self.paper_trade else "LIVE"
            key_preview = api_key[:10] + "..." if len(api_key) > 10 else api_key
            print(f"[{self.name}] Connecting to {mode} account with key: {key_preview}")
            
            # Initialize trading client
            self.trading_client = TradingClient(
                api_key=api_key,
                secret_key=api_secret,
                paper=self.paper_trade
            )
            
            # Initialize data client
            self.data_client = StockHistoricalDataClient(
                api_key=api_key,
                secret_key=api_secret
            )
            
            # Initialize option data client for option quotes
            self.option_data_client = OptionHistoricalDataClient(
                api_key=api_key,
                secret_key=api_secret
            )
            
            # Verify connection
            account = await asyncio.to_thread(self.trading_client.get_account)
            
            if account:
                self.connected = True
                account_id = str(getattr(account, 'id', 'N/A'))
                account_number = str(getattr(account, 'account_number', 'N/A'))
                self.account_id = account_id
                self.account_number = account_number
                print(f"[{self.name}] ✓ Connected successfully ({mode} trading)")
                print(f"[{self.name}]   Account ID: {account_id}")
                print(f"[{self.name}]   Account #: {account_number}")
                print(f"[{self.name}]   Buying power: ${float(account.buying_power):,.2f}")
                return True
            
            print(f"[{self.name}] ❌ Failed to verify connection")
            return False
            
        except Exception as e:
            import traceback
            error_msg = str(e)
            print(f"[{self.name}] ❌ Connection error: {error_msg}")
            
            # Check for authorization errors
            if 'unauthorized' in error_msg.lower() or '401' in error_msg:
                print(f"[{self.name}] ⚠️  AUTHORIZATION FAILED - Check that:")
                print(f"[{self.name}]    1. API Key and Secret are CORRECT")
                print(f"[{self.name}]    2. Keys are for PAPER trading (not LIVE)")
                print(f"[{self.name}]    3. Keys have not been revoked")
                print(f"[{self.name}]    4. Get new keys from: https://app.alpaca.markets/paper/dashboard/overview")
            
            # Print full traceback for debugging
            traceback.print_exc()
            return False
    
    async def disconnect(self):
        """Disconnect from Alpaca"""
        self.connected = False
        self.trading_client = None
        self.data_client = None
        print(f"[{self.name}] Disconnected")
    
    def _get_extended_hours_enabled(self) -> bool:
        """Check if extended hours trading is enabled for Alpaca.
        
        Alpaca extended_hours parameter allows orders to execute during:
        - Pre-market: 4:00 AM - 9:30 AM ET
        - After-hours: 4:00 PM - 8:00 PM ET
        
        Note: Extended hours only works with LIMIT orders (not MARKET)
        
        Returns:
            True if extended hours is enabled
        """
        try:
            from gui_app.database import get_broker_extended_hours
            enabled = get_broker_extended_hours('alpaca')
            if enabled:
                print(f"[{self.name}] Extended hours ENABLED")
            return enabled
        except ImportError:
            return False
        except Exception as e:
            print(f"[{self.name}] Error checking extended hours setting: {e}")
            return False
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information including settled cash for good faith violation prevention"""
        try:
            account = await asyncio.to_thread(self.trading_client.get_account)
            # Get options buying power if available (may be different from stock buying power)
            options_bp = getattr(account, 'options_buying_power', None)
            if options_bp is None:
                options_bp = account.buying_power  # Fall back to regular buying power
            
            cash_withdrawable = float(getattr(account, 'cash_withdrawable', 0) or 0)
            non_marginable_bp = float(getattr(account, 'non_marginable_buying_power', 0) or 0)
            
            is_paper = str(getattr(account, 'account_number', '')).startswith('PA') or 'paper' in str(getattr(account, 'status', '')).lower()
            
            if is_paper:
                settled_cash = float(getattr(account, 'cash', 0) or 0)
                if settled_cash <= 0:
                    settled_cash = float(getattr(account, 'buying_power', 0) or 0)
            else:
                settled_cash = min(cash_withdrawable, non_marginable_bp) if non_marginable_bp > 0 else cash_withdrawable
            
            # Unsettled cash = total cash - settled (withdrawable) cash
            total_cash = float(account.cash)
            unsettled_cash = max(0, total_cash - cash_withdrawable)
            
            result = {
                'buying_power': float(account.buying_power),
                'options_buying_power': float(options_bp),
                'cash': total_cash,
                'cash_balance': total_cash,
                'portfolio_value': float(account.portfolio_value),
                'settled_cash': settled_cash,
                'unsettled_cash': unsettled_cash,
                'cash_withdrawable': cash_withdrawable,
                'non_marginable_buying_power': non_marginable_bp
            }
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
            positions = await asyncio.to_thread(self.trading_client.get_all_positions)
            result = {}
            for pos in positions:
                result[pos.symbol] = int(float(pos.qty))
            return result
        except Exception as e:
            print(f"[{self.name}] Error getting positions: {e}")
            return {}
    
    def get_all_positions(self) -> list:
        """Get all positions as raw objects for sync service (synchronous)"""
        try:
            if not self.trading_client:
                print(f"[{self.name}] Trading client not connected")
                return []
            positions = self.trading_client.get_all_positions()
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
            if not self.trading_client:
                print(f"[{self.name}] Trading client not connected")
                return []
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            
            if status == 'open':
                request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            else:
                request = GetOrdersRequest(status=QueryOrderStatus.ALL)
            
            orders = self.trading_client.get_orders(filter=request)
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
        stop_price: Optional[float] = None,
        channel_id: Optional[str] = None
    ) -> OrderResult:
        """Place a stock order
        
        Args:
            symbol: Stock ticker
            action: BTO (buy) or STC (sell)
            quantity: Number of shares
            price: Limit price (for limit orders)
            stop_price: Stop price (for stop loss orders)
        """
        try:
            side = OrderSide.BUY if action == 'BTO' else OrderSide.SELL
            
            if price is not None and price > 0:
                price = round(price, 4) if price < 1.0 else round(price, 2)
            if stop_price is not None:
                stop_price = round(stop_price, 4) if stop_price < 1.0 else round(stop_price, 2)
            
            is_market = (price is None or price <= 0)
            
            extended_hours = self._get_extended_hours_enabled() if not is_market and stop_price is None else False
            
            if stop_price is not None:
                order_data = StopOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=side,
                    time_in_force=TimeInForce.GTC,
                    stop_price=stop_price
                )
            elif is_market:
                order_data = MarketOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=side,
                    time_in_force=TimeInForce.DAY
                )
            else:
                # Limit order - supports extended hours trading
                order_data = LimitOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=side,
                    time_in_force=TimeInForce.GTC,  # Good till cancelled for profit targets
                    limit_price=price,
                    extended_hours=extended_hours
                )
            
            # Submit order
            order = await asyncio.to_thread(
                self.trading_client.submit_order,
                order_data=order_data
            )
            
            if order:
                return OrderResult(
                    success=True,
                    order_id=str(order.id),
                    message=f"Stock order placed: {action} {quantity} {symbol}",
                    price=price if price else float(order.filled_avg_price or 0),
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                return OrderResult(
                    success=False,
                    message="Order submission failed - no response",
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            error_msg = str(e)
            
            # Handle insufficient funds - auto-adjust quantity (only once to prevent infinite loop)
            if 'insufficient' in error_msg.lower() or 'buying power' in error_msg.lower():
                # Check if this is already an auto-adjusted retry (prevent infinite recursion)
                if hasattr(self, '_auto_adjust_in_progress') and self._auto_adjust_in_progress.get(symbol):
                    print(f"[{self.name}] ❌ Auto-adjust already attempted for {symbol} - stopping to prevent loop")
                    del self._auto_adjust_in_progress[symbol]
                else:
                    try:
                        # Mark that we're auto-adjusting this symbol
                        if not hasattr(self, '_auto_adjust_in_progress'):
                            self._auto_adjust_in_progress = {}
                        self._auto_adjust_in_progress[symbol] = True
                        
                        # Calculate available quantity based on action
                        if action.upper() in ('STC', 'SELL'):
                            # For sell orders, the limiting factor is the position size
                            positions = await self.get_positions()
                            available_qty = positions.get(symbol, 0)
                            print(f"[{self.name}] Auto-adjusting SELL: {quantity} -> {available_qty} (position size)")
                        else:
                            # For buy orders, the limiting factor is buying power
                            account_info = await self.get_account_info()
                            buying_power = account_info['buying_power']
                            current_price = await self.get_quote(symbol)
                            if current_price and buying_power > 0:
                                available_qty = int(buying_power / current_price)
                                print(f"[{self.name}] Auto-adjusting BUY: {quantity} -> {available_qty} (buying power: ${buying_power:.2f})")
                            else:
                                available_qty = 0
                        
                        if available_qty > 0 and available_qty != quantity:
                            result = await self.place_stock_order(symbol, action, available_qty, price)
                            # Clear the flag after successful adjustment
                            if symbol in self._auto_adjust_in_progress:
                                del self._auto_adjust_in_progress[symbol]
                            return result
                        else:
                            print(f"[{self.name}] ❌ Cannot auto-adjust: available_qty={available_qty} (same or zero)")
                        
                        # Clear flag on completion
                        if symbol in self._auto_adjust_in_progress:
                            del self._auto_adjust_in_progress[symbol]
                    except Exception as adjust_error:
                        print(f"[{self.name}] Auto-adjust failed: {adjust_error}")
                        if hasattr(self, '_auto_adjust_in_progress') and symbol in self._auto_adjust_in_progress:
                            del self._auto_adjust_in_progress[symbol]
            
            return OrderResult(
                success=False,
                message=f"Exception: {error_msg}",
                symbol=symbol,
                action=action
            )
    
    async def place_bracket_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        stop_loss_price: Optional[float] = None,
        profit_target_price: Optional[float] = None,
        entry_price: Optional[float] = None
    ) -> OrderResult:
        """Place a bracket order (entry + stop loss + profit target)
        
        Args:
            symbol: Stock ticker
            action: BTO (buy) or STC (sell)
            quantity: Number of shares
            stop_loss_price: Stop loss price
            profit_target_price: Profit target price
            entry_price: Entry limit price (None for market order)
        """
        try:
            side = OrderSide.BUY if action == 'BTO' else OrderSide.SELL
            
            if entry_price is not None:
                entry_price = round(entry_price, 4) if entry_price < 1.0 else round(entry_price, 2)
            if stop_loss_price is not None:
                stop_loss_price = round(stop_loss_price, 4) if stop_loss_price < 1.0 else round(stop_loss_price, 2)
            if profit_target_price is not None:
                profit_target_price = round(profit_target_price, 4) if profit_target_price < 1.0 else round(profit_target_price, 2)
            
            # Alpaca BRACKET orders require BOTH stop_loss AND take_profit
            # If only one is provided, fall back to simple order
            has_both_legs = stop_loss_price is not None and profit_target_price is not None
            has_any_leg = stop_loss_price is not None or profit_target_price is not None
            
            if has_both_legs:
                # Full bracket order with both legs
                order_class = OrderClass.BRACKET
                stop_loss = StopLossRequest(stop_price=stop_loss_price)
                take_profit = TakeProfitRequest(limit_price=profit_target_price)
                print(f"[{self.name}] Using full BRACKET order (stop + target)")
            elif has_any_leg:
                # Alpaca doesn't support partial bracket - fall back to simple order
                # We'll place entry order and let risk management handle stops
                order_class = OrderClass.SIMPLE
                stop_loss = None
                take_profit = None
                if stop_loss_price:
                    print(f"[{self.name}] ⚠️  BRACKET requires both SL+Target - placing SIMPLE order (SL will be managed separately)")
                else:
                    print(f"[{self.name}] ⚠️  BRACKET requires both SL+Target - placing SIMPLE order (Target will be managed separately)")
            else:
                # No legs - simple order
                order_class = OrderClass.SIMPLE
                stop_loss = None
                take_profit = None
            
            # Check extended hours setting
            # NOTE: Extended hours only applies to SIMPLE LIMIT orders, NOT bracket orders
            # Bracket orders (with stop_loss/take_profit legs) cannot use extended hours
            # because the exit legs don't support extended hours execution
            extended_hours_enabled = self._get_extended_hours_enabled()
            use_extended_hours = extended_hours_enabled and entry_price is not None and order_class == OrderClass.SIMPLE
            
            if extended_hours_enabled and order_class != OrderClass.SIMPLE:
                print(f"[{self.name}] ⚠️ Extended hours disabled for BRACKET orders (exit legs don't support it)")
            
            if entry_price is None:
                # Market order (extended hours not supported for market orders)
                if extended_hours_enabled:
                    print(f"[{self.name}] ⚠️ Extended hours disabled for MARKET orders (not supported by Alpaca)")
                order_data = MarketOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    order_class=order_class,
                    stop_loss=stop_loss,
                    take_profit=take_profit
                )
            else:
                # Limit order - supports extended hours trading (only for SIMPLE orders)
                order_data = LimitOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=entry_price,
                    order_class=order_class,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    extended_hours=use_extended_hours
                )
            
            # Submit order
            order = await asyncio.to_thread(
                self.trading_client.submit_order,
                order_data=order_data
            )
            
            if order:
                # Get the order IDs for all legs
                order_ids = [str(order.id)]
                if hasattr(order, 'legs') and order.legs:
                    for leg in order.legs:
                        order_ids.append(str(leg.id))
                
                message_parts = [f"Bracket order placed: {action} {quantity} {symbol}"]
                if stop_loss_price:
                    message_parts.append(f"Stop Loss @ ${stop_loss_price}")
                if profit_target_price:
                    message_parts.append(f"Target @ ${profit_target_price}")
                
                return OrderResult(
                    success=True,
                    order_id=str(order.id),
                    message=" | ".join(message_parts),
                    price=entry_price if entry_price else float(order.filled_avg_price or 0),
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                return OrderResult(
                    success=False,
                    message="Bracket order submission failed - no response",
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            error_msg = str(e)
            print(f"[{self.name}] ❌ Bracket order exception: {error_msg}")
            
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
        price: Optional[float] = None,
        **kwargs
    ) -> OrderResult:
        """Place an options order using Alpaca's option contracts endpoint"""
        try:
            from datetime import datetime
            
            # SIDE: Buy/Sell mapping
            side = OrderSide.BUY if action in ('BTO', 'BTC') else OrderSide.SELL
            
            # INTENT: Mapping BTO/STC to Alpaca PositionIntent
            intent = kwargs.get('position_intent')
            if not intent:
                intent = PositionIntent.BUY_TO_OPEN if action == 'BTO' else \
                         PositionIntent.SELL_TO_CLOSE if action == 'STC' else \
                         PositionIntent.SELL_TO_OPEN if action == 'STO' else \
                         PositionIntent.BUY_TO_CLOSE if action == 'BTC' else \
                         PositionIntent.BUY_TO_OPEN # Fallback

            # Normalize expiry to YYYY-MM-DD
            expiry_date = expiry
            if "/" in expiry:
                parts = expiry.split("/")
                if len(parts) == 2:
                    # MM/DD format
                    m, d = parts
                    y = datetime.now().year
                    expiry_date = f"{y:04d}-{int(m):02d}-{int(d):02d}"
                elif len(parts) == 3:
                    # MM/DD/YY or MM/DD/YYYY
                    m, d, y = parts
                    if len(y) == 2:
                        y = f"20{y}"
                    expiry_date = f"{y}-{int(m):02d}-{int(d):02d}"
                else:
                    raise ValueError(f"Invalid expiry format: {expiry}")
            else:
                expiry_date = expiry  # assume already YYYY-MM-DD

            # Resolve the option contract using Alpaca's endpoint
            req = GetOptionContractsRequest(
                underlying_symbols=[symbol],
                status=AssetStatus.ACTIVE,
                expiration_date=expiry_date,
                type="call" if option_type.upper().startswith("C") else "put",
                strike_price_gte=str(strike),  # Convert to string for Alpaca API
                strike_price_lte=str(strike),  # Convert to string for Alpaca API
                style=ExerciseStyle.AMERICAN,
                limit=10,
            )
            
            print(f"[{self.name}] Searching for option contract: {symbol} {strike}{option_type} {expiry_date}", flush=True)
            contracts = await asyncio.to_thread(self.trading_client.get_option_contracts, req)
            
            if not contracts.option_contracts:
                return OrderResult(
                    success=False,
                    message=f"No matching Alpaca option contract for {symbol} {strike}{option_type} {expiry_date}",
                    symbol=symbol,
                    action=action,
                )

            contract = contracts.option_contracts[0]
            print(f"[{self.name}] Found contract: {contract.symbol}", flush=True)
            
            side = OrderSide.BUY if action.upper() == "BTO" else OrderSide.SELL
            
            # CRITICAL FIX: For STC orders, verify actual position quantity to prevent "uncovered option" errors
            # The original BTO may have been auto-reduced by Alpaca, so we must check the real held quantity
            if action.upper() == "STC":
                try:
                    positions = await self.get_positions()
                    held_qty = positions.get(contract.symbol, 0)
                    if held_qty > 0 and held_qty < quantity:
                        print(f"[{self.name}] ⚠️ Adjusting STC quantity for {contract.symbol}: {quantity} -> {held_qty} (actual position)", flush=True)
                        quantity = held_qty
                    elif held_qty <= 0:
                        return OrderResult(
                            success=False,
                            message=f"No open position found for {contract.symbol} (cannot STC)",
                            symbol=symbol,
                            action=action
                        )
                except Exception as pos_err:
                    print(f"[{self.name}] ⚠️ Error checking position for {contract.symbol}: {pos_err}", flush=True)

            # Check for existing pending orders that might be locking shares/contracts
            # If this is a risk management exit, cancel conflicting orders first
            if action.upper() in ('STC', 'BTC'):
                try:
                    open_orders = await asyncio.to_thread(self.get_orders, status='open')
                    target_symbol = contract.symbol if 'option' in str(type(contract)).lower() else symbol
                    for o in open_orders:
                        if o.symbol == target_symbol and o.side == side:
                            print(f"[{self.name}] ⚠️ Found existing pending {o.side} order for {o.symbol} (ID: {o.id}). Shares may be locked.", flush=True)
                            # Cancel the stale order to free up the shares for new exit order
                            print(f"[{self.name}] 🔄 Cancelling stale pending order {o.id} to allow new exit order...", flush=True)
                            try:
                                await asyncio.to_thread(
                                    self.trading_client.cancel_order_by_id,
                                    str(o.id)
                                )
                                print(f"[{self.name}] ✓ Cancelled stale order {o.id}", flush=True)
                                # Brief wait for cancel to process
                                await asyncio.sleep(0.5)
                            except Exception as cancel_err:
                                print(f"[{self.name}] ⚠️ Could not cancel stale order {o.id}: {cancel_err}", flush=True)
                except Exception as order_err:
                    print(f"[{self.name}] ⚠️ Error checking open orders: {order_err}", flush=True)
                try:
                    positions = await asyncio.to_thread(self.trading_client.get_all_positions)
                    held_qty = 0
                    for pos in positions:
                        if pos.symbol == contract.symbol:
                            held_qty = int(abs(float(pos.qty)))
                            break
                    
                    print(f"[{self.name}] STC quantity check: requested={quantity}, held={held_qty}", flush=True)
                    
                    if held_qty == 0:
                        return OrderResult(
                            success=False,
                            message=f"⚠️  No position found for {contract.symbol}. Position may have already been closed.",
                            symbol=symbol,
                            action=action
                        )
                    
                    if quantity > held_qty:
                        print(f"[{self.name}] ⚠️  Reducing STC quantity: {quantity} → {held_qty} (actual position size)", flush=True)
                        quantity = held_qty
                        
                except Exception as e:
                    print(f"[{self.name}] Warning: Could not verify position quantity: {e}", flush=True)
            
            # CRITICAL: For options, specify position_intent to avoid "uncovered option" errors
            # BTO = Buy To Open (new long position)
            # STC = Sell To Close (close existing long position)
            # BTC = Buy To Close (close existing short position)
            # STO = Sell To Open (new short position)
            if action.upper() == "BTO":
                position_intent = PositionIntent.BUY_TO_OPEN
            elif action.upper() == "STC":
                position_intent = PositionIntent.SELL_TO_CLOSE
            elif action.upper() == "BTC":
                position_intent = PositionIntent.BUY_TO_CLOSE
            elif action.upper() == "STO":
                position_intent = PositionIntent.SELL_TO_OPEN
            else:
                # Default based on side
                position_intent = PositionIntent.BUY_TO_OPEN if side == OrderSide.BUY else PositionIntent.SELL_TO_CLOSE

            # Check extended hours setting (only applies to LIMIT orders)
            extended_hours = self._get_extended_hours_enabled() if price is not None and price > 0 else False
            
            if price is None or price <= 0:
                # Market order (extended hours not supported for market orders)
                order_req = MarketOrderRequest(
                    symbol=contract.symbol,
                    qty=quantity,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    type=OrderType.MARKET,
                    position_intent=position_intent,
                )
            else:
                # Limit order - supports extended hours trading
                order_req = LimitOrderRequest(
                    symbol=contract.symbol,
                    qty=quantity,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                    limit_price=price,
                    type=OrderType.LIMIT,
                    position_intent=position_intent,
                    extended_hours=extended_hours,
                )

            print(f"[{self.name}] Submitting option order: {action} {quantity} {contract.symbol} @ ${price or 'MARKET'} [position_intent={position_intent}]", flush=True)
            print(f"[{self.name}] Order request: symbol={order_req.symbol}, side={order_req.side}, qty={order_req.qty}, intent={order_req.position_intent}", flush=True)
            order = await asyncio.to_thread(self.trading_client.submit_order, order_data=order_req)
            
            print(f"[{self.name}] Option order response: {order}", flush=True)
            
            if order:
                filled_price = float(order.filled_avg_price or price or 0)
                total_cost = filled_price * quantity * 100
                order_type = "LIMIT" if price else "MARKET"
                action_label = "Bought" if action.upper() == "BTO" else "Sold"
                opt_label = "Call" if option_type.upper().startswith("C") else "Put"
                
                success_msg = f"✅ {action_label} {quantity}x {symbol} ${strike} {opt_label} exp {expiry} @ ${filled_price:.2f} ({order_type}) - Total: ${total_cost:.2f}"
                
                return OrderResult(
                    success=True,
                    order_id=str(order.id),
                    message=success_msg,
                    price=filled_price,
                    quantity=quantity,
                    symbol=symbol,
                    action=action
                )
            else:
                return OrderResult(
                    success=False,
                    message="Order submission failed - no response",
                    symbol=symbol,
                    action=action
                )
                
        except Exception as e:
            error_msg = str(e)
            print(f"[{self.name}] ❌ Option order failed: {error_msg}", flush=True)
            
            # Check for specific error types and provide better messages
            if 'uncovered' in error_msg.lower():
                # For STC orders, retry with MARKET order if limit order fails
                # Sometimes Alpaca Paper trading has issues with limit order pricing
                # NOTE: Market order retry only works during regular trading hours
                if action.upper() == "STC" and price is not None:
                    # Check if we're in extended hours - if so, market orders won't work
                    if extended_hours:
                        print(f"[{self.name}] ⚠️ Cannot retry with MARKET order during extended hours (not supported)", flush=True)
                    else:
                        try:
                            print(f"[{self.name}] ⚠️ Limit STC failed, retrying with MARKET order...", flush=True)
                            market_req = MarketOrderRequest(
                                symbol=contract.symbol,
                                qty=quantity,
                                side=OrderSide.SELL,
                                time_in_force=TimeInForce.DAY,
                                type=OrderType.MARKET,
                                position_intent=PositionIntent.SELL_TO_CLOSE,
                            )
                            order = await asyncio.to_thread(self.trading_client.submit_order, order_data=market_req)
                            if order:
                                filled_price = float(order.filled_avg_price or 0)
                                print(f"[{self.name}] ✅ MARKET STC order succeeded!", flush=True)
                                return OrderResult(
                                    success=True,
                                    order_id=str(order.id),
                                    message=f"✅ Sold {quantity}x {symbol} ${strike} (MARKET)",
                                    price=filled_price,
                                    quantity=quantity,
                                    symbol=symbol,
                                    action=action
                                )
                        except Exception as retry_e:
                            print(f"[{self.name}] ❌ MARKET STC retry also failed: {retry_e}", flush=True)
                
                return OrderResult(
                    success=False,
                    message=f"⚠️  Alpaca uncovered option error. Make sure you have the position to close: {symbol} ${strike}{option_type}",
                    symbol=symbol,
                    action=action
                )
            elif 'expired' in error_msg.lower():
                return OrderResult(
                    success=False,
                    message=f"⚠️  Option contract expired: {symbol} ${strike}{option_type}",
                    symbol=symbol,
                    action=action
                )
            elif 'insufficient' in error_msg.lower():
                return OrderResult(
                    success=False,
                    message=f"⚠️  Insufficient quantity or already has pending order: {symbol} ${strike}{option_type}",
                    symbol=symbol,
                    action=action
                )
            elif 'not eligible' in error_msg.lower() or 'not enabled' in error_msg.lower():
                return OrderResult(
                    success=False,
                    message=f"⚠️  Alpaca options not enabled for this account: {symbol} ${strike}{option_type}",
                    symbol=symbol,
                    action=action
                )
            elif 'invalid underlying' in error_msg.lower() or 'invalid symbol' in error_msg.lower():
                return OrderResult(
                    success=False,
                    message=f"❌ Symbol '{symbol}' not supported on Alpaca. Index options (SPX/NDX/VIX) require SPXW/NDXP/VIXW symbols. Try using SPY for S&P 500 exposure.",
                    symbol=symbol,
                    action=action
                )
            elif 'no option contract' in error_msg.lower() or 'contract not found' in error_msg.lower():
                return OrderResult(
                    success=False,
                    message=f"❌ No option contract found for {symbol} ${strike}{option_type} exp {expiry}. Check strike price and expiration date.",
                    symbol=symbol,
                    action=action
                )
            elif 'buying power' in error_msg.lower() or 'insufficient funds' in error_msg.lower():
                return OrderResult(
                    success=False,
                    message=f"❌ Insufficient buying power for {quantity}x {symbol} ${strike}{option_type} @ ${price}. Reduce quantity or add funds.",
                    symbol=symbol,
                    action=action
                )
            
            return OrderResult(
                success=False,
                message=f"❌ Order failed: {error_msg}",
                symbol=symbol,
                action=action
            )
    
    async def place_option_order_simple(self, symbol: str, strike: float, expiry: str, 
                                       option_type: str, quantity: int, side: str, 
                                       price: float, option_id: str = None) -> OrderResult:
        """
        Simplified option order placement - wrapper for GUI API compatibility
        
        Args:
            symbol: Stock symbol
            strike: Strike price
            expiry: Expiration date (YYYY-MM-DD format)
            option_type: 'CALL' or 'PUT'
            quantity: Number of contracts
            side: 'BUY' or 'SELL'
            price: Limit price per contract
            option_id: Option contract ID (not used by Alpaca - we look up the contract)
        
        Returns:
            OrderResult with success status and message
        """
        # Index options are NOT supported on Alpaca - reject early with clear message
        # Alpaca only supports equity options, not cash-settled index options (CBOE)
        INDEX_SYMBOLS = {'SPX', 'SPXW', 'NDX', 'NDXP', 'RUT', 'RUTW', 'VIX', 'VIXW', 'XSP', 'DJX'}
        
        if symbol.upper() in INDEX_SYMBOLS:
            print(f"[{self.name}] ❌ Index options not supported: {symbol} - Use Tastytrade or IBKR for index options")
            return OrderResult(
                success=False,
                message=f"❌ Index options ({symbol}) are NOT supported on Alpaca. Alpaca only supports equity options. Use Tastytrade or IBKR for SPX/NDX/VIX trading, or use QQQ/SPY for similar exposure.",
                symbol=symbol,
                action='BTO' if side.upper() == 'BUY' else 'STC'
            )
        
        # Convert GUI-style side to action format
        # BUY -> BTO (Buy To Open), SELL -> STC (Sell To Close)
        if side.upper() == 'BUY':
            action = 'BTO'
        elif side.upper() == 'SELL':
            action = 'STC'
        else:
            action = side.upper()
        
        # Convert option_type to single letter format
        opt_type = 'C' if option_type.upper().startswith('C') else 'P'
        
        print(f"[{self.name}] place_option_order_simple: {side} {quantity} {symbol} ${strike}{opt_type} {expiry} @ ${price}")
        
        # Call the main option order method
        return await self.place_option_order(
            symbol=symbol,
            strike=strike,
            expiry=expiry,
            option_type=opt_type,
            action=action,
            quantity=quantity,
            price=price
        )
    
    async def get_quote(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol"""
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
            quotes = await asyncio.to_thread(
                self.data_client.get_stock_latest_quote,
                request
            )
            
            if symbol in quotes:
                quote = quotes[symbol]
                bid = float(quote.bid_price or 0)
                ask = float(quote.ask_price or 0)
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                elif ask > 0:
                    return ask
                elif bid > 0:
                    return bid
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting quote for {symbol}: {e}")
            return None
    
    async def get_option_quote(self, symbol: str, strike: float, opt_type: str, expiry: str) -> Optional[dict]:
        """Get current quote for an option contract
        
        Returns dict with 'bid', 'ask', 'mid' prices or None if not available
        """
        try:
            from alpaca.data.requests import OptionLatestQuoteRequest
            
            # Build the option symbol (e.g., QQQ260121C00619000)
            from datetime import datetime
            
            # Parse expiry (e.g., "1/21" or "01/21")
            if '/' in expiry:
                parts = expiry.split('/')
                month = int(parts[0])
                day = int(parts[1])
                year = datetime.now().year
                if month < datetime.now().month:
                    year += 1
            else:
                return None
            
            # Format: SYMBOL + YYMMDD + C/P + strike*1000 (8 digits)
            opt_char = opt_type.upper()[0] if opt_type else 'C'
            strike_formatted = int(float(strike) * 1000)
            option_symbol = f"{symbol}{year % 100:02d}{month:02d}{day:02d}{opt_char}{strike_formatted:08d}"
            
            request = OptionLatestQuoteRequest(symbol_or_symbols=[option_symbol])
            quotes = await asyncio.to_thread(
                self.option_data_client.get_option_latest_quote,
                request
            )
            
            if option_symbol in quotes:
                quote = quotes[option_symbol]
                bid = float(quote.bid_price) if quote.bid_price else 0
                ask = float(quote.ask_price) if quote.ask_price else 0
                mid = (bid + ask) / 2 if bid and ask else (ask or bid)
                return {'bid': bid, 'ask': ask, 'mid': mid, 'symbol': option_symbol}
            return None
        except Exception as e:
            print(f"[{self.name}] Error getting option quote: {e}")
            return None
    
    async def close_position(self, symbol: str, quantity: Optional[int] = None, limit_price: Optional[float] = None) -> OrderResult:
        """Close a position (works for both LONG and SHORT positions)
        
        Args:
            symbol: Stock ticker to close
            quantity: Number of shares to close (None = close all)
            limit_price: Optional limit price for the close order (None = market order)
        """
        try:
            if not self.trading_client:
                return OrderResult(
                    success=False,
                    message="Not connected to Alpaca",
                    symbol=symbol,
                    action='STC'
                )
            
            # Get current position
            try:
                position = await asyncio.to_thread(
                    self.trading_client.get_open_position,
                    symbol
                )
            except Exception as e:
                return OrderResult(
                    success=False,
                    message=f"No open position found for {symbol}",
                    symbol=symbol,
                    action='STC'
                )
            
            if not position:
                return OrderResult(
                    success=False,
                    message=f"No position found for {symbol}",
                    symbol=symbol,
                    action='STC'
                )
            
            # Determine position type and quantity
            position_qty = float(position.qty)
            is_short = position_qty < 0
            abs_qty = abs(int(position_qty))
            qty_to_close = quantity if quantity else abs_qty
            
            if qty_to_close > abs_qty:
                return OrderResult(
                    success=False,
                    message=f"Cannot close {qty_to_close} shares, only {abs_qty} available",
                    symbol=symbol,
                    action='BTC' if is_short else 'STC'
                )
            
            # Determine order type based on limit_price
            order_type_str = f"LIMIT @ ${limit_price}" if limit_price else "MARKET"
            action = 'BTC' if is_short else 'STC'
            
            # Use Alpaca's close_position API only for full market orders
            if qty_to_close == abs_qty and limit_price is None:
                # Close entire position using Alpaca's API (handles both long/short)
                result = await asyncio.to_thread(
                    self.trading_client.close_position,
                    symbol
                )
                
                if result:
                    action_word = "Covered" if is_short else "Sold"
                    return OrderResult(
                        success=True,
                        order_id=str(result.id) if hasattr(result, 'id') else None,
                        message=f"{action_word} {qty_to_close} {symbol} @ MARKET ({'SHORT' if is_short else 'LONG'} position closed)",
                        quantity=qty_to_close,
                        symbol=symbol,
                        action=action
                    )
            else:
                # Partial close OR limit order - place appropriate order
                # For long positions: SELL (STC)
                # For short positions: BUY (BTC - buy to cover)
                side = OrderSide.BUY if is_short else OrderSide.SELL
                
                # Check if this is an options position
                # Method 1: Check asset_class attribute
                is_option = hasattr(position, 'asset_class') and str(getattr(position, 'asset_class', '')).lower() == 'us_option'
                
                # Method 2: Check symbol format - OCC options format: SYMBOL + YYMMDD + C/P + strike
                # e.g., CLSK251205P00014000, AAPL240119C00150000
                import re
                if not is_option:
                    # Options symbols are 15+ chars with embedded date and C/P indicator
                    option_pattern = r'^[A-Z]{1,6}\d{6}[CP]\d{8}$'
                    is_option = bool(re.match(option_pattern, symbol))
                
                # Use DAY for options (GTC not supported by Alpaca for options), GTC for stocks
                tif = TimeInForce.DAY if is_option else TimeInForce.GTC
                print(f"[{self.name}] Position type: {'OPTION' if is_option else 'STOCK'}, using TIF: {tif}")
                
                if limit_price:
                    # Limit order
                    order_data = LimitOrderRequest(
                        symbol=symbol,
                        qty=qty_to_close,
                        side=side,
                        time_in_force=tif,  # DAY for options, GTC for stocks
                        limit_price=limit_price
                    )
                    print(f"[{self.name}] Closing position with LIMIT order: {action} {qty_to_close} {symbol} @ ${limit_price} (TIF: {tif})")
                else:
                    # Market order - always use DAY
                    order_data = MarketOrderRequest(
                        symbol=symbol,
                        qty=qty_to_close,
                        side=side,
                        time_in_force=TimeInForce.DAY
                    )
                    print(f"[{self.name}] Closing position with MARKET order: {action} {qty_to_close} {symbol}")
                
                order = await asyncio.to_thread(
                    self.trading_client.submit_order,
                    order_data=order_data
                )
                
                if order:
                    action_word = "Cover" if is_short else "Sell"
                    return OrderResult(
                        success=True,
                        order_id=str(order.id),
                        message=f"{action_word} {qty_to_close} {symbol} @ {order_type_str} - Order submitted",
                        price=limit_price if limit_price else float(order.filled_avg_price or 0),
                        quantity=qty_to_close,
                        symbol=symbol,
                        action=action
                    )
            
            return OrderResult(
                success=False,
                message=f"Failed to close position for {symbol}",
                symbol=symbol,
                action='BTC' if is_short else 'STC'
            )
            
        except Exception as e:
            error_msg = str(e)
            print(f"[{self.name}] ❌ Close position failed for {symbol}: {error_msg}")
            return OrderResult(
                success=False,
                message=f"Exception: {error_msg}",
                symbol=symbol,
                action='STC'
            )
    
    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open order
        
        Args:
            order_id: The Alpaca order ID to cancel
        """
        try:
            if not self.trading_client:
                return {'success': False, 'error': 'Not connected to Alpaca'}
            
            # Cancel the order
            await asyncio.to_thread(
                self.trading_client.cancel_order_by_id,
                order_id
            )
            
            print(f"[{self.name}] ✓ Order {order_id} cancelled successfully")
            return {'success': True, 'message': f'Order {order_id} cancelled'}
            
        except Exception as e:
            error_msg = str(e)
            print(f"[{self.name}] ❌ Cancel order failed for {order_id}: {error_msg}")
            
            # Handle specific Alpaca error codes
            if '42210000' in error_msg or 'pending cancel' in error_msg.lower():
                return {
                    'success': True,  # Treat as success - order is already being cancelled
                    'message': 'Order is already being cancelled. Please wait a moment and refresh.'
                }
            elif 'order is not cancelable' in error_msg.lower() or 'filled' in error_msg.lower():
                return {
                    'success': False,
                    'error': 'Order has already been filled and cannot be cancelled.'
                }
            
            return {'success': False, 'error': error_msg}
    
    async def get_open_orders(self) -> list:
        """Get all open orders"""
        try:
            if not self.trading_client:
                return []
            
            request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = await asyncio.to_thread(
                self.trading_client.get_orders,
                request
            )
            
            result = []
            for order in orders:
                result.append({
                    'order_id': str(order.id),
                    'symbol': order.symbol,
                    'quantity': int(float(order.qty)),
                    'side': str(order.side.value),
                    'type': str(order.type.value),
                    'status': str(order.status.value),
                    'limit_price': float(order.limit_price) if order.limit_price else None,
                    'stop_price': float(order.stop_price) if order.stop_price else None,
                    'created_at': str(order.created_at)
                })
            
            return result
            
        except Exception as e:
            print(f"[{self.name}] Error getting open orders: {e}")
            return []
    
    async def get_options_expiration_dates(self, symbol: str) -> list:
        """Get all available option expiration dates for a symbol"""
        try:
            from src.data_providers.alpaca_data_provider import AlpacaDataProvider
            
            api_key = self.config.get('api_key')
            api_secret = self.config.get('api_secret')
            
            if not api_key or not api_secret:
                print(f"[{self.name}] No credentials for option chain data")
                return []
            
            provider = AlpacaDataProvider(api_key, api_secret)
            return await provider.get_options_expiration_dates(symbol)
            
        except Exception as e:
            print(f"[{self.name}] Error getting expirations for {symbol}: {e}")
            return []
    
    async def get_option_chain(self, symbol: str, expiration_date: str) -> Dict[str, Any]:
        """Get option chain for a symbol and expiration date"""
        try:
            from src.data_providers.alpaca_data_provider import AlpacaDataProvider
            
            api_key = self.config.get('api_key')
            api_secret = self.config.get('api_secret')
            
            if not api_key or not api_secret:
                print(f"[{self.name}] No credentials for option chain data")
                return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': 'ALPACA'}
            
            provider = AlpacaDataProvider(api_key, api_secret)
            chain = await provider.get_option_chain(symbol, expiration_date)
            chain['data_source'] = 'ALPACA'
            return chain
            
        except Exception as e:
            print(f"[{self.name}] Error getting option chain for {symbol}: {e}")
            return {'calls': [], 'puts': [], 'stock_price': None, 'data_source': 'ALPACA'}


# Register this broker with the factory
BrokerFactory.register_broker('ALPACA', AlpacaBroker)
