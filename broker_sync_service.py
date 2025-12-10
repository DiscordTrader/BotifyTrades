"""
BrokerSyncService - Real-time trade synchronization with broker accounts
Runs periodic background task to sync database trades with actual Webull/Alpaca positions
"""

import asyncio
import logging
import sys
import re
from datetime import datetime
from typing import List, Dict, Optional, Any
from gui_app.database import Database

# Use print() for logging - it's redirected to the logging system in selfbot_webull.py
# logger = logging.getLogger(__name__)  # Not configured, logs go nowhere

def parse_occ_symbol(occ_symbol: str) -> Optional[Dict]:
    """
    Parse OCC option symbol format: AAPL251219C00230000
    Returns dict with: symbol, expiry (YYYY-MM-DD), strike, call_put (C/P)
    Returns None if not an option symbol
    """
    occ_pattern = r'^([A-Z]{1,5})\s*(\d{6})([CP])(\d{8})$'
    match = re.match(occ_pattern, occ_symbol.strip())
    
    if not match:
        return None
    
    underlying, date_str, call_put, strike_str = match.groups()
    
    try:
        year = int('20' + date_str[:2])
        month = int(date_str[2:4])
        day = int(date_str[4:6])
        expiry = f"{year}-{month:02d}-{day:02d}"
        
        strike = int(strike_str) / 1000.0
        
        return {
            'symbol': underlying,
            'expiry': expiry,
            'call_put': call_put,
            'strike': strike,
            'asset_type': 'option'
        }
    except (ValueError, IndexError):
        return None


class BrokerSyncService:
    """Synchronizes database trades with live broker positions/orders"""
    
    def __init__(self, broker_manager, db: Database, sync_interval: int = 30):
        """
        Initialize sync service
        
        Args:
            broker_manager: BrokerManager instance with connected brokers
            db: Database instance for trade updates
            sync_interval: Sync frequency in seconds (default: 30s)
        """
        self.broker_manager = broker_manager
        self.db = db
        self.sync_interval = sync_interval
        self.running = False
        self._task = None
        
        print(f"[SYNC] BrokerSyncService initialized (interval={sync_interval}s)")
    
    async def start(self):
        """Start the background sync task"""
        try:
            if self.running:
                print("[SYNC] Service already running", flush=True)
                return
            
            self.running = True
            # Use ensure_future instead of create_task for better scheduling
            self._task = asyncio.ensure_future(self._sync_loop())
            
            # Force the event loop to schedule the task immediately
            await asyncio.sleep(0.1)
            
            # Verify task is running
            if self._task.done():
                exception = self._task.exception()
                if exception:
                    print(f"[SYNC] ❌ Task failed immediately: {exception}", flush=True)
                    import traceback
                    traceback.print_exception(type(exception), exception, exception.__traceback__)
                else:
                    print(f"[SYNC] ❌ Task completed immediately (should be running!)", flush=True)
            else:
                print(f"[SYNC] ✓ Trade synchronization service started ({self.sync_interval}s interval)", flush=True)
        except Exception as e:
            print(f"[SYNC] FATAL ERROR in start(): {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def stop(self):
        """Stop the background sync task"""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[SYNC] ✓ Sync service stopped", flush=True)
    
    async def _sync_loop(self):
        """Main sync loop - runs every sync_interval seconds"""
        print("[SYNC] 🔄 Sync loop started", flush=True)
        
        while self.running:
            try:
                # Perform sync FIRST, then sleep (so first sync happens immediately)
                await self._perform_sync()
                await asyncio.sleep(self.sync_interval)
                
            except asyncio.CancelledError:
                print("[SYNC] Sync loop cancelled", flush=True)
                break
            except Exception as e:
                print(f"[SYNC] Error in sync loop: {e}")
                import traceback
                traceback.print_exc()
                # Continue running despite errors
    
    async def _perform_sync(self):
        """Perform one sync cycle across all brokers"""
        print("[SYNC] 🔄 Starting sync cycle", flush=True)
        
        # Get all configured brokers
        brokers_to_sync = []
        
        # Add Webull if available
        if hasattr(self.broker_manager, 'webull_broker') and self.broker_manager.webull_broker:
            brokers_to_sync.append(('Webull', self.broker_manager.webull_broker))
        
        # Add Alpaca if available
        if hasattr(self.broker_manager, 'alpaca_paper_broker') and self.broker_manager.alpaca_paper_broker:
            brokers_to_sync.append(('ALPACA_PAPER', self.broker_manager.alpaca_paper_broker))
        
        if not brokers_to_sync:
            print("[SYNC] No brokers available for sync", flush=True)
            return
        
        print(f"[SYNC] Syncing {len(brokers_to_sync)} broker(s): {[b[0] for b in brokers_to_sync]}")
        
        # Sync each broker
        for broker_name, broker_instance in brokers_to_sync:
            try:
                await self._sync_broker(broker_name, broker_instance)
            except Exception as e:
                print(f"[SYNC] Error syncing {broker_name}: {e}")
                import traceback
                traceback.print_exc()
        
        print("[SYNC] ✓ Sync cycle complete", flush=True)
    
    async def _sync_broker(self, broker_name: str, broker_instance):
        """Sync trades for a specific broker"""
        print(f"[SYNC] Syncing {broker_name}...")
        
        # Step 1: Fetch broker positions and orders
        normalized_data = await self._fetch_and_normalize(broker_name, broker_instance)
        
        if not normalized_data:
            print(f"[SYNC] No data from {broker_name}")
            return
        
        # Step 2: Reconcile with database trades
        await self._reconcile_trades(broker_name, normalized_data)
        
        print(f"[SYNC] ✓ {broker_name} sync complete")
    
    async def _fetch_and_normalize(self, broker_name: str, broker_instance) -> Dict[str, Any]:
        """
        Fetch positions and orders from broker, normalize to common schema
        
        Returns:
            {
                'positions': [{'symbol': 'AAPL', 'quantity': 10, 'avg_price': 150.0, ...}],
                'pending_orders': [{'symbol': 'TSLA', 'quantity': 5, 'limit_price': 200.0, ...}]
            }
        """
        try:
            result = {
                'positions': [],
                'pending_orders': []
            }
            
            # Fetch based on broker type
            if broker_name == 'Webull':
                # Get live positions using detailed method (supports options)
                if hasattr(broker_instance, 'get_positions_detailed'):
                    positions = await broker_instance.get_positions_detailed() or []
                    
                    for pos in positions:
                        result['positions'].append({
                            'symbol': pos.get('symbol'),
                            'quantity': pos.get('quantity'),
                            'avg_price': pos.get('avg_cost'),  # Corrected from entry_price
                            'current_price': pos.get('current_price'),
                            'unrealized_pnl': pos.get('unrealized_pl'),  # Corrected from pnl
                            'position_id': pos.get('option_id') or pos.get('ticker_id'),
                            'asset_type': pos.get('asset', 'stock'),  # Corrected from asset_type
                            'strike': pos.get('strike'),
                            'expiry': pos.get('expiry'),
                            'call_put': pos.get('direction')  # Corrected from call_put
                        })
                else:
                    print("[SYNC] Webull broker missing get_positions_detailed() method", flush=True)
                
                # Get pending orders from Webull
                if hasattr(broker_instance, 'get_pending_orders'):
                    orders = await broker_instance.get_pending_orders() or []
                    for order in orders:
                        result['pending_orders'].append({
                            'broker_order_id': order.get('order_id'),
                            'symbol': order.get('symbol'),
                            'quantity': order.get('quantity'),
                            'limit_price': order.get('limit_price'),
                            'order_type': order.get('action'),  # BUY/SELL
                            'status': order.get('status')
                        })
                else:
                    print("[SYNC] Webull broker missing get_pending_orders() method", flush=True)
            
            elif broker_name == 'ALPACA_PAPER':
                # Get pending orders (Alpaca)
                if hasattr(broker_instance, 'get_orders'):
                    orders = broker_instance.get_orders(status='open') or []
                    for order in orders:
                        result['pending_orders'].append({
                            'broker_order_id': str(order.id),
                            'symbol': order.symbol,
                            'quantity': float(order.qty),
                            'limit_price': float(order.limit_price) if order.limit_price else None,
                            'order_type': order.side,  # buy/sell
                            'status': order.status
                        })
                
                # Get live positions (Alpaca)
                if hasattr(broker_instance, 'get_all_positions'):
                    positions = broker_instance.get_all_positions() or []
                    for pos in positions:
                        raw_symbol = pos.symbol
                        
                        # Parse OCC option symbols like TSLA251219C00450000
                        parsed = parse_occ_symbol(raw_symbol)
                        
                        if parsed:
                            # It's an option - use parsed data with underlying symbol
                            result['positions'].append({
                                'symbol': parsed['symbol'],  # Underlying (e.g., TSLA)
                                'occ_symbol': raw_symbol,  # Full OCC symbol for reference
                                'quantity': float(pos.qty),
                                'avg_price': float(pos.avg_entry_price),
                                'current_price': float(pos.current_price),
                                'unrealized_pnl': float(pos.unrealized_pl),
                                'position_id': None,
                                'asset_type': 'option',
                                'strike': parsed['strike'],
                                'expiry': parsed['expiry'],
                                'call_put': parsed['call_put']
                            })
                        else:
                            # It's a stock
                            result['positions'].append({
                                'symbol': raw_symbol,
                                'quantity': float(pos.qty),
                                'avg_price': float(pos.avg_entry_price),
                                'current_price': float(pos.current_price),
                                'unrealized_pnl': float(pos.unrealized_pl),
                                'position_id': None,
                                'asset_type': 'stock'
                            })
            
            print(f"[SYNC] {broker_name}: {len(result['positions'])} positions, {len(result['pending_orders'])} pending orders")
            if result['positions']:
                symbols = [p['symbol'] for p in result['positions']]
                print(f"[SYNC] {broker_name} positions: {symbols}")
            return result
            
        except Exception as e:
            print(f"[SYNC] Error fetching from {broker_name}: {e}")
            import traceback
            traceback.print_exc()
            return {'positions': [], 'pending_orders': []}
    
    async def _reconcile_trades(self, broker_name: str, normalized_data: Dict[str, Any]):
        """
        Reconcile normalized broker data with database trades
        
        Two-stage process:
        1. Update existing database trades (PENDING→OPEN→CLOSED)
        2. Import broker-only positions as synthetic trades
        """
        
        # Stage 1: Update existing database trades
        await self._update_existing_trades(broker_name, normalized_data)
        
        # Stage 2: Import manual trades (positions not tracked by bot)
        await self._import_manual_trades(broker_name, normalized_data)
    
    async def _update_existing_trades(self, broker_name: str, normalized_data: Dict[str, Any]):
        """Update status of existing database trades based on broker state"""
        
        # Get all non-closed trades for this broker (handle multiple name formats)
        db_trades = self.db.get_trades(limit=1000)
        
        # Filter for this broker (case-insensitive match)
        broker_lower = broker_name.lower()
        active_trades = []
        for t in db_trades:
            if t['status'] in ('CLOSED', 'FAILED'):
                continue
            trade_broker = (t.get('broker') or '').lower()
            if broker_lower == 'webull' and 'webull' in trade_broker:
                active_trades.append(t)
            elif broker_lower == 'alpaca_paper' and 'alpaca' in trade_broker:
                active_trades.append(t)
            elif trade_broker == broker_lower:
                active_trades.append(t)
        
        if not active_trades:
            print(f"[SYNC] No active {broker_name} trades to update")
            return
        
        # Build position lookup by normalized key (NOT raw symbol)
        positions_by_key = {}
        for p in normalized_data.get('positions', []):
            key = self._build_position_key(
                p['symbol'],
                p.get('asset_type', 'stock'),
                p.get('strike'),
                p.get('expiry'),
                p.get('call_put')
            )
            positions_by_key[key] = p
        
        pending_by_order_id = {o['broker_order_id']: o for o in normalized_data.get('pending_orders', []) if o.get('broker_order_id')}
        pending_by_symbol = {o['symbol']: o for o in normalized_data.get('pending_orders', [])}
        
        for trade in active_trades:
            symbol = trade['symbol']
            trade_id = trade['id']
            current_status = trade['status']
            db_order_id = trade.get('order_id')
            
            # Build normalized key for this trade
            trade_key = self._build_position_key(
                symbol,
                trade.get('asset_type', 'stock'),
                trade.get('strike'),
                trade.get('expiry'),
                trade.get('call_put')
            )
            
            # Check if trade is in broker's pending orders (match by order_id first, then symbol)
            found_in_pending = False
            
            if db_order_id and db_order_id in pending_by_order_id:
                found_in_pending = True
                if current_status == 'PENDING':
                    print(f"[SYNC] Trade #{trade_id} ({symbol}) still PENDING (order_id: {db_order_id})")
            elif not db_order_id and symbol in pending_by_symbol:
                pending_order = pending_by_symbol[symbol]
                found_in_pending = True
                if current_status == 'PENDING':
                    print(f"[SYNC] Trade #{trade_id} ({symbol}) still PENDING")
                    if pending_order.get('broker_order_id'):
                        print(f"[SYNC] Updating trade #{trade_id} with order_id: {pending_order['broker_order_id']}")
                        self.db.update_trade(trade_id, order_id=pending_order['broker_order_id'])
            
            if found_in_pending:
                pass
            
            # Check if trade has filled (match by normalized key)
            elif trade_key in positions_by_key:
                position = positions_by_key[trade_key]
                
                # Transition PENDING → OPEN
                if current_status == 'PENDING':
                    print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) filled: PENDING → OPEN")
                    self.db.update_trade(
                        trade_id,
                        status='OPEN',
                        executed_price=position['avg_price'],
                        current_price=position.get('current_price'),
                        quantity=position['quantity'],
                        executed_at=datetime.now().isoformat()
                    )
                
                # Update OPEN trade with current position data (UPDATE CURRENT PRICE AND P&L!)
                elif current_status == 'OPEN':
                    current_price = position.get('current_price')
                    if current_price:
                        # Get entry price and quantity from database trade for P&L calculation
                        entry_price = float(trade.get('executed_price') or trade.get('price') or 0)
                        quantity = float(trade.get('quantity') or position['quantity'] or 1)
                        asset_type = trade.get('asset_type', 'option')
                        
                        # Calculate P&L
                        if entry_price > 0:
                            multiplier = 100 if asset_type == 'option' else 1
                            pnl = (current_price - entry_price) * quantity * multiplier
                            pnl_percent = ((current_price - entry_price) / entry_price) * 100
                        else:
                            pnl = 0
                            pnl_percent = 0
                        
                        # Update all price-related fields
                        self.db.update_trade(trade_id, current_price=current_price, pnl=pnl, pnl_percent=pnl_percent)
                    print(f"[SYNC] Trade #{trade_id} ({symbol}) still OPEN (qty={position['quantity']}, price=${current_price})")
            
            # CRITICAL: Trade not in pending or positions = order cancelled or position closed
            # Brokers remove closed positions entirely, so absence means it's gone
            else:
                if current_status == 'PENDING':
                    # Pending order no longer exists = cancelled or rejected
                    print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) not in pending orders: PENDING → CLOSED (cancelled)")
                    self.db.update_trade(
                        trade_id,
                        status='CLOSED',
                        closed_at=datetime.now().isoformat(),
                        close_reason='ORDER_CANCELLED'
                    )
                elif current_status == 'OPEN':
                    # Open position no longer exists = broker closed it (manual close, stop/target hit, or liquidation)
                    print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) not in positions: OPEN → CLOSED (broker closed)")
                    self.db.update_trade(
                        trade_id,
                        status='CLOSED',
                        closed_at=datetime.now().isoformat(),
                        close_reason='BROKER_CLOSED'
                    )
    
    def _normalize_expiry(self, expiry: str) -> str:
        """Normalize expiry date to YYYY-MM-DD format for consistent matching"""
        if not expiry:
            return ''
        
        expiry = str(expiry).strip()
        
        # Already in YYYY-MM-DD format
        if len(expiry) == 10 and expiry[4] == '-' and expiry[7] == '-':
            return expiry
        
        # Handle MM/DD format (assumes current year or next year)
        if '/' in expiry and len(expiry) <= 5:
            parts = expiry.split('/')
            if len(parts) == 2:
                try:
                    month = int(parts[0])
                    day = int(parts[1])
                    from datetime import datetime
                    current_year = datetime.now().year
                    current_month = datetime.now().month
                    # If expiry month is less than current month, assume next year
                    year = current_year if month >= current_month else current_year + 1
                    return f"{year}-{month:02d}-{day:02d}"
                except (ValueError, IndexError):
                    pass
        
        # Handle MM/DD/YY or MM/DD/YYYY format
        if '/' in expiry:
            parts = expiry.split('/')
            if len(parts) == 3:
                try:
                    month = int(parts[0])
                    day = int(parts[1])
                    year = int(parts[2])
                    if year < 100:
                        year += 2000
                    return f"{year}-{month:02d}-{day:02d}"
                except (ValueError, IndexError):
                    pass
        
        return expiry

    def _build_position_key(self, symbol: str, asset_type: str, strike=None, expiry=None, call_put=None) -> str:
        """Build a normalized position key for matching between broker and database"""
        if asset_type == 'option' and strike and expiry and call_put:
            normalized_expiry = self._normalize_expiry(expiry)
            # Round strike to avoid float precision issues (0.5 increments for most options)
            normalized_strike = round(float(strike) * 2) / 2 if strike else 0
            return f"{symbol}_{normalized_strike}_{normalized_expiry}_{call_put}"
        else:
            return f"{symbol}_stock"
    
    async def _import_manual_trades(self, broker_name: str, normalized_data: Dict[str, Any]):
        """Import broker positions that aren't tracked in database as synthetic trades
        
        IMPORTANT: When importing, try to find the origin Discord trade and inherit its channel_id.
        This allows per-channel risk settings to work for positions that were opened via Discord signals.
        """
        
        # Get all tracked trades for this broker (handle case-insensitive broker names)
        all_db_trades = self.db.get_trades(status='OPEN', limit=1000)
        
        # Also get recently closed Discord trades to find origin channel_id for positions
        all_discord_trades = self.db.get_trades(limit=1000)  # Get all trades to find origins
        
        # Filter for this broker (case-insensitive)
        broker_lower = broker_name.lower()
        db_trades = []
        for t in all_db_trades:
            trade_broker = (t.get('broker') or '').lower()
            if broker_lower == 'webull' and 'webull' in trade_broker:
                db_trades.append(t)
            elif broker_lower == 'alpaca_paper' and 'alpaca' in trade_broker:
                db_trades.append(t)
            elif trade_broker == broker_lower:
                db_trades.append(t)
        
        # Build normalized keys for existing trades
        tracked_keys = set()
        for t in db_trades:
            key = self._build_position_key(
                t['symbol'],
                t.get('asset_type', 'stock'),
                t.get('strike'),
                t.get('expiry'),
                t.get('call_put')
            )
            tracked_keys.add(key)
        
        # Build a lookup for finding origin channel_id from Discord-triggered trades
        # Priority: Match by order_id first, then by position_key with closest timestamp
        # This allows imported positions to maintain their Discord channel association
        
        # Collect all Discord trades with channel_id, sorted by recency (higher ID = more recent)
        discord_trades_with_channel = [
            t for t in sorted(all_discord_trades, key=lambda x: x.get('id', 0), reverse=True)
            if t.get('channel_id') and (t.get('source') == 'discord' or t.get('message_id'))
        ]
        
        def find_origin_channel(position: Dict) -> str:
            """Find the origin channel_id for a broker position using multi-pass matching"""
            pos_key = self._build_position_key(
                position['symbol'],
                position.get('asset_type', 'stock'),
                position.get('strike'),
                position.get('expiry'),
                position.get('call_put')
            )
            
            # Pass 1: Match by order_id (most reliable)
            pos_order_id = position.get('position_id') or position.get('order_id')
            if pos_order_id:
                for t in discord_trades_with_channel:
                    if t.get('order_id') == pos_order_id:
                        return t.get('channel_id')
            
            # Pass 2: Match by position key (symbol + option details) with quantity consideration
            pos_qty = float(position.get('quantity', 0))
            matching_trades = []
            for t in discord_trades_with_channel:
                trade_key = self._build_position_key(
                    t['symbol'],
                    t.get('asset_type', 'stock'),
                    t.get('strike'),
                    t.get('expiry'),
                    t.get('call_put')
                )
                if trade_key == pos_key:
                    matching_trades.append(t)
            
            if matching_trades:
                # Prefer trades with matching or similar quantity (within 20%)
                for t in matching_trades:
                    trade_qty = float(t.get('quantity', 0))
                    if trade_qty > 0 and abs(trade_qty - pos_qty) / trade_qty <= 0.2:
                        return t.get('channel_id')
                
                # Fallback: most recent trade with matching key
                return matching_trades[0].get('channel_id')
            
            return None  # No match found
        
        # Find positions not tracked by bot
        broker_positions = normalized_data.get('positions', [])
        
        for position in broker_positions:
            symbol = position['symbol']
            asset_type = position.get('asset_type', 'stock')
            strike = position.get('strike')
            expiry = position.get('expiry')
            call_put = position.get('call_put')
            
            # Build position key for this broker position
            pos_key = self._build_position_key(symbol, asset_type, strike, expiry, call_put)
            
            if pos_key not in tracked_keys:
                # Try to find origin channel_id using multi-pass matching
                origin_channel_id = find_origin_channel(position)
                
                if origin_channel_id:
                    print(f"[SYNC] 📥 Importing {broker_name} position: {symbol} ({asset_type}, qty={position['quantity']}, key={pos_key}) - inherited channel_id={origin_channel_id}")
                else:
                    print(f"[SYNC] 📥 Importing manual {broker_name} position: {symbol} ({asset_type}, qty={position['quantity']}, key={pos_key}) - no channel association")
                
                # Calculate initial P&L
                entry_price = float(position['avg_price'] or 0)
                current_price = float(position.get('current_price') or entry_price)
                quantity = float(position['quantity'] or 1)
                multiplier = 100 if asset_type == 'option' else 1
                
                if entry_price > 0:
                    pnl = (current_price - entry_price) * quantity * multiplier
                    pnl_percent = ((current_price - entry_price) / entry_price) * 100
                else:
                    pnl = 0
                    pnl_percent = 0
                
                # Create synthetic trade entry - inherit channel_id if found from Discord origin
                trade_data = {
                    'symbol': symbol,
                    'direction': 'BTO',
                    'quantity': position['quantity'],
                    'intended_price': position['avg_price'],
                    'executed_price': position['avg_price'],
                    'current_price': current_price,
                    'pnl': pnl,
                    'pnl_percent': pnl_percent,
                    'broker': broker_name,
                    'status': 'OPEN',
                    'asset_type': asset_type,
                    'executed_at': datetime.now().isoformat(),
                    'message_id': None,
                    'channel_id': origin_channel_id,  # Inherit from Discord origin if available
                    'order_id': position.get('position_id'),
                    'profit_target_percent': 0,
                    'stop_loss_percent': 0,
                    'trailing_stop_enabled': 0,
                    'source': 'sync' if not origin_channel_id else 'sync_discord'  # Mark source type
                }
                
                # Add option-specific fields if it's an option
                if asset_type == 'option':
                    trade_data.update({
                        'strike': strike,
                        'expiry': expiry,
                        'call_put': call_put
                    })
                
                self.db.add_trade(trade_data)
                # Add to tracked keys so we don't import duplicates in same cycle
                tracked_keys.add(pos_key)
            else:
                # Position already tracked - skip import
                pass
