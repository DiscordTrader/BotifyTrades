"""
BrokerSyncService - Real-time trade synchronization with broker accounts
Runs periodic background task to sync database trades with actual Webull/Alpaca positions
"""

import asyncio
import logging
import sys
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from gui_app.database import Database
from gui_app.lot_matcher import get_matcher

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
        self._risk_manager = None  # Set via set_risk_manager()
        
        print(f"[SYNC] BrokerSyncService initialized (interval={sync_interval}s)")
    
    def set_risk_manager(self, risk_manager):
        """Set risk manager reference for pending order reconciliation."""
        self._risk_manager = risk_manager
        if risk_manager:
            print("[SYNC] ✓ Risk manager linked for order reconciliation")
    
    def _normalize_timestamp(self, timestamp_str: str) -> str:
        """Convert various timestamp formats to ISO format.
        
        Handles formats like:
        - '01/08/2026 14:11:41 EST' (Webull format)
        - '2026-01-08T14:11:41' (already ISO)
        - '2026-01-08 14:11:41' (ISO without T)
        """
        if not timestamp_str:
            return datetime.now().isoformat()
        
        # Webull format: MM/DD/YYYY HH:MM:SS EST/EDT (check first - has '/')
        if '/' in timestamp_str:
            try:
                # Remove timezone suffix
                clean_ts = timestamp_str.replace(' EST', '').replace(' EDT', '').strip()
                # Parse MM/DD/YYYY HH:MM:SS
                dt = datetime.strptime(clean_ts, '%m/%d/%Y %H:%M:%S')
                return dt.isoformat()
            except ValueError:
                pass
        
        # Already ISO format (has T separator or dashes for date)
        if timestamp_str.count('-') >= 2:
            result = timestamp_str.replace(' ', 'T').split('+')[0].split('Z')[0]
            return result
        
        # Fallback: return as-is or current time
        return timestamp_str or datetime.now().isoformat()
    
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
        
        # Add Tastytrade if available
        if hasattr(self.broker_manager, 'tastytrade_broker') and self.broker_manager.tastytrade_broker:
            tt_broker = self.broker_manager.tastytrade_broker
            # Determine if live or paper based on broker settings
            broker_label = 'TASTYTRADE_LIVE' if getattr(tt_broker, 'is_live', False) else 'TASTYTRADE_PAPER'
            brokers_to_sync.append((broker_label, tt_broker))
        
        # Add Schwab if available
        if hasattr(self.broker_manager, 'schwab_broker') and self.broker_manager.schwab_broker:
            schwab_broker = self.broker_manager.schwab_broker
            try:
                is_auth = await schwab_broker.is_authenticated()
                if is_auth:
                    brokers_to_sync.append(('SCHWAB', schwab_broker))
            except Exception:
                pass
        
        # Add IBKR if available (requires TWS/Gateway running)
        if hasattr(self.broker_manager, 'ibkr_broker') and self.broker_manager.ibkr_broker:
            ibkr_broker = self.broker_manager.ibkr_broker
            try:
                if getattr(ibkr_broker, 'connected', False):
                    broker_label = 'IBKR_LIVE' if not getattr(ibkr_broker, 'paper_trade', True) else 'IBKR_PAPER'
                    brokers_to_sync.append((broker_label, ibkr_broker))
            except Exception:
                pass
        
        # Add Robinhood if available (WARNING: LIVE ONLY - no paper trading)
        if hasattr(self.broker_manager, 'robinhood_broker') and self.broker_manager.robinhood_broker:
            rh_broker = self.broker_manager.robinhood_broker
            try:
                if getattr(rh_broker, 'connected', False):
                    brokers_to_sync.append(('ROBINHOOD', rh_broker))
            except Exception:
                pass
        
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
        
        # Step 3: Sync filled orders to database (runs every 5 sync cycles = ~2.5 min)
        if not hasattr(self, '_fill_sync_counter'):
            self._fill_sync_counter = {}
        self._fill_sync_counter[broker_name] = self._fill_sync_counter.get(broker_name, 0) + 1
        
        if self._fill_sync_counter[broker_name] >= 5:
            await self._sync_filled_orders(broker_name, broker_instance)
            self._fill_sync_counter[broker_name] = 0
        
        # Reconcile pending risk orders every sync cycle (not just every 5th)
        if hasattr(self, '_risk_manager') and self._risk_manager:
            await self.reconcile_risk_orders(self._risk_manager)
        
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
                        # Skip orders that are being canceled or already canceled
                        order_status = str(order.status.value if hasattr(order.status, 'value') else order.status).lower()
                        if order_status in ('pending_cancel', 'canceled', 'cancelled', 'expired', 'rejected'):
                            print(f"[SYNC] Skipping {order.symbol} order {order.id} - status: {order_status}")
                            continue
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
            
            elif broker_name == 'SCHWAB':
                # Get detailed positions from Schwab
                if hasattr(broker_instance, 'get_positions_detailed'):
                    positions = await broker_instance.get_positions_detailed() or []
                    
                    for pos in positions:
                        result['positions'].append({
                            'symbol': pos.get('symbol'),
                            'quantity': pos.get('quantity'),
                            'avg_price': pos.get('avg_cost'),
                            'current_price': pos.get('current_price'),
                            'unrealized_pnl': pos.get('unrealized_pl'),
                            'position_id': pos.get('position_id'),
                            'asset_type': pos.get('asset', 'stock'),
                            'strike': pos.get('strike'),
                            'expiry': pos.get('expiry'),
                            'call_put': pos.get('direction')
                        })
                
                # Get pending orders from Schwab
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
            
            elif broker_name.startswith('IBKR'):
                # IBKR - Interactive Brokers via ib_insync (requires TWS/Gateway)
                if hasattr(broker_instance, 'ib') and broker_instance.ib.isConnected():
                    try:
                        ib = broker_instance.ib
                        raw_positions = await asyncio.to_thread(ib.positions)
                        
                        for pos in raw_positions:
                            contract = pos.contract
                            symbol = contract.symbol
                            quantity = abs(int(pos.position))
                            avg_cost = float(pos.avgCost) if pos.avgCost else 0
                            
                            if contract.secType == 'OPT':
                                expiry_raw = contract.lastTradeDateOrContractMonth
                                if len(expiry_raw) == 8:
                                    expiry = f"{expiry_raw[:4]}-{expiry_raw[4:6]}-{expiry_raw[6:8]}"
                                else:
                                    expiry = expiry_raw
                                
                                result['positions'].append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'avg_price': avg_cost / 100 if avg_cost > 0 else 0,
                                    'current_price': 0,
                                    'unrealized_pnl': 0,
                                    'position_id': contract.conId,
                                    'asset_type': 'option',
                                    'strike': contract.strike,
                                    'expiry': expiry,
                                    'call_put': contract.right
                                })
                            else:
                                result['positions'].append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'avg_price': avg_cost,
                                    'current_price': 0,
                                    'unrealized_pnl': 0,
                                    'position_id': contract.conId,
                                    'asset_type': 'stock'
                                })
                        
                        raw_orders = await asyncio.to_thread(ib.openOrders)
                        for order in raw_orders:
                            result['pending_orders'].append({
                                'broker_order_id': str(order.orderId),
                                'symbol': order.contract.symbol if hasattr(order, 'contract') else '',
                                'quantity': order.totalQuantity if hasattr(order, 'totalQuantity') else 0,
                                'limit_price': order.lmtPrice if hasattr(order, 'lmtPrice') else None,
                                'order_type': order.action if hasattr(order, 'action') else '',
                                'status': 'PENDING'
                            })
                    except Exception as e:
                        print(f"[SYNC] IBKR fetch error: {e}")
            
            elif broker_name.startswith('TASTYTRADE'):
                # Tastytrade - uses async session with OAuth2
                if hasattr(broker_instance, 'session') and broker_instance.session:
                    try:
                        if hasattr(broker_instance, 'get_all_positions'):
                            positions = await asyncio.to_thread(broker_instance.get_all_positions) or []
                            for pos in positions:
                                result['positions'].append({
                                    'symbol': pos.get('symbol'),
                                    'quantity': pos.get('quantity'),
                                    'avg_price': pos.get('avg_price'),
                                    'current_price': pos.get('current_price', 0),
                                    'unrealized_pnl': pos.get('unrealized_pnl', 0),
                                    'position_id': pos.get('position_id'),
                                    'asset_type': pos.get('asset_type', 'stock'),
                                    'strike': pos.get('strike'),
                                    'expiry': pos.get('expiry'),
                                    'call_put': pos.get('call_put')
                                })
                        
                        if hasattr(broker_instance, 'get_pending_orders'):
                            orders = await asyncio.to_thread(broker_instance.get_pending_orders) or []
                            for order in orders:
                                result['pending_orders'].append({
                                    'broker_order_id': order.get('order_id'),
                                    'symbol': order.get('symbol'),
                                    'quantity': order.get('quantity'),
                                    'limit_price': order.get('limit_price'),
                                    'order_type': order.get('action'),
                                    'status': order.get('status', 'PENDING')
                                })
                    except Exception as e:
                        print(f"[SYNC] Tastytrade fetch error: {e}")
            
            elif broker_name == 'ROBINHOOD':
                # Robinhood - WARNING: LIVE ONLY (no paper trading)
                if hasattr(broker_instance, 'get_all_positions'):
                    try:
                        positions = await asyncio.to_thread(broker_instance.get_all_positions) or []
                        for pos in positions:
                            pos_type = pos.get('type', pos.get('asset_type', 'stock'))
                            current_price = pos.get('current_price', 0) or 0
                            unrealized_pnl = pos.get('unrealized_pnl', 0) or 0
                            result['positions'].append({
                                'symbol': pos.get('symbol'),
                                'quantity': pos.get('quantity'),
                                'avg_price': pos.get('avg_price') or pos.get('average_buy_price') or pos.get('average_price'),
                                'current_price': current_price,
                                'unrealized_pnl': unrealized_pnl,
                                'market_value': pos.get('market_value') or pos.get('equity', 0),
                                'position_id': None,
                                'asset_type': pos_type,
                                'strike': pos.get('strike_price'),
                                'expiry': pos.get('expiration_date'),
                                'call_put': 'C' if pos.get('option_type') == 'call' else 'P' if pos.get('option_type') == 'put' else None
                            })
                        
                        if hasattr(broker_instance, 'get_pending_orders'):
                            orders = await asyncio.to_thread(broker_instance.get_pending_orders) or []
                            for order in orders:
                                result['pending_orders'].append({
                                    'broker_order_id': order.get('id'),
                                    'symbol': order.get('symbol'),
                                    'quantity': order.get('quantity'),
                                    'limit_price': order.get('price'),
                                    'order_type': order.get('side'),
                                    'status': order.get('state', 'PENDING')
                                })
                    except Exception as e:
                        print(f"[SYNC] Robinhood fetch error: {e}")
            
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
            elif broker_lower == 'schwab' and 'schwab' in trade_broker:
                active_trades.append(t)
            elif broker_lower.startswith('ibkr') and 'ibkr' in trade_broker:
                active_trades.append(t)
            elif broker_lower.startswith('tastytrade') and 'tastytrade' in trade_broker:
                active_trades.append(t)
            elif broker_lower == 'robinhood' and 'robinhood' in trade_broker:
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
                
                # Update OPEN trade with current position data (UPDATE CURRENT PRICE, QUANTITY, AND P&L!)
                elif current_status == 'OPEN':
                    current_price = position.get('current_price')
                    broker_quantity = float(position.get('quantity', 0))
                    db_quantity = float(trade.get('quantity') or 0)
                    
                    # Get entry price for P&L calculation
                    entry_price = float(trade.get('executed_price') or trade.get('price') or 0)
                    asset_type = trade.get('asset_type', 'option')
                    
                    # Use broker quantity for P&L calculation (source of truth)
                    quantity = broker_quantity if broker_quantity > 0 else db_quantity
                    
                    # Calculate P&L
                    if entry_price > 0 and current_price:
                        multiplier = 100 if asset_type == 'option' else 1
                        pnl = (current_price - entry_price) * quantity * multiplier
                        pnl_percent = ((current_price - entry_price) / entry_price) * 100
                    else:
                        pnl = 0
                        pnl_percent = 0
                    
                    # Build update dict - always sync quantity from broker
                    update_fields = {'pnl': pnl, 'pnl_percent': pnl_percent}
                    if current_price:
                        update_fields['current_price'] = current_price
                    
                    # CRITICAL: Sync quantity from broker if different
                    if broker_quantity > 0 and abs(broker_quantity - db_quantity) > 0.001:
                        update_fields['quantity'] = broker_quantity
                        print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) quantity synced: DB={db_quantity} → Broker={broker_quantity}")
                    
                    # Update all fields
                    self.db.update_trade(trade_id, **update_fields)
            
            # CRITICAL: Trade not in pending or positions = order cancelled or position closed
            # Brokers remove closed positions entirely, so absence means it's gone
            else:
                if current_status == 'PENDING':
                    # GRACE PERIOD: Don't close PENDING trades too quickly (prevents race condition)
                    # Wait at least 60 seconds after trade creation before marking as cancelled
                    trade_created_at = trade.get('created_at') or trade.get('executed_at')
                    grace_period_seconds = 60
                    
                    if trade_created_at:
                        try:
                            # Parse creation time
                            if isinstance(trade_created_at, str):
                                # Handle various datetime formats
                                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f']:
                                    try:
                                        created_time = datetime.strptime(trade_created_at.split('.')[0], fmt.split('.')[0])
                                        break
                                    except ValueError:
                                        continue
                                else:
                                    created_time = datetime.now() - timedelta(seconds=grace_period_seconds + 1)
                            else:
                                created_time = trade_created_at
                            
                            seconds_since_created = (datetime.now() - created_time).total_seconds()
                            
                            if seconds_since_created < grace_period_seconds:
                                print(f"[SYNC] Trade #{trade_id} ({symbol}) PENDING - within grace period ({seconds_since_created:.0f}s < {grace_period_seconds}s), skipping")
                                continue
                        except Exception as parse_err:
                            print(f"[SYNC] ⚠️ Could not parse trade created_at: {parse_err}")
                    
                    # Pending order no longer exists after grace period = cancelled or rejected
                    print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) not in pending orders: PENDING → CLOSED (cancelled)")
                    self.db.update_trade(
                        trade_id,
                        status='CLOSED',
                        closed_at=datetime.now().isoformat(),
                        close_reason='order_cancelled_or_rejected'
                    )
                elif current_status == 'OPEN':
                    # Open position no longer exists = broker closed it (manual close, stop/target hit, or liquidation)
                    print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) not in positions: OPEN → CLOSED (broker closed)")
                    
                    # Use existing PNL data from last sync update (already calculated with live prices)
                    # This is more reliable than recalculating since position is now gone
                    exit_price = float(trade.get('current_price') or 0)
                    entry_price = float(trade.get('executed_price') or 0)
                    quantity = float(trade.get('quantity') or 0)
                    asset_type = trade.get('asset_type', 'option')
                    discord_channel_id = trade.get('channel_id')
                    
                    # Use existing PNL from last sync update (calculated while position was still open)
                    pnl = float(trade.get('pnl') or 0)
                    pnl_percent = float(trade.get('pnl_percent') or 0)
                    
                    # Only recalculate if we have valid prices and no existing PNL
                    if pnl == 0 and entry_price > 0 and exit_price > 0:
                        multiplier = 100 if asset_type == 'option' else 1
                        pnl = (exit_price - entry_price) * quantity * multiplier
                        pnl_percent = ((exit_price - entry_price) / entry_price) * 100
                    
                    # Update trade with final status and close_reason
                    self.db.update_trade(
                        trade_id,
                        status='CLOSED',
                        closed_at=datetime.now().isoformat(),
                        pnl=pnl,
                        pnl_percent=pnl_percent,
                        close_reason='broker_closed_position'
                    )
                    
                    # Create lot_closure for PNL/leaderboard tracking
                    # Note: exit_price can be 0 for expired worthless options - still valid closure
                    if discord_channel_id and quantity > 0:
                        try:
                            # Lookup db_channel_id using database module function
                            from gui_app.database import get_channel_by_discord_id
                            channel_row = get_channel_by_discord_id(str(discord_channel_id))
                            
                            if channel_row:
                                db_channel_id = channel_row['id']
                                
                                matcher = get_matcher()
                                lot_signal = {
                                    'action': 'STC',
                                    'symbol': symbol,
                                    'asset': asset_type,
                                    'qty': quantity,  # Preserve as float for partial positions
                                    'price': exit_price,  # Can be 0 for expired options
                                    'strike': trade.get('strike'),
                                    'expiry': trade.get('expiry'),
                                    'opt_type': trade.get('call_put'),
                                    'channel_id': discord_channel_id,
                                    'db_channel_id': db_channel_id,
                                    'received_at': datetime.now()
                                }
                                lot_result = matcher.process_signal(lot_signal)
                                if lot_result:
                                    print(f"[SYNC] ✓ Created {len(lot_result)} lot_closure(s) for PNL tracking (exit=${exit_price})")
                            else:
                                print(f"[SYNC] ⚠️ Channel {discord_channel_id} not found in database")
                        except Exception as le:
                            print(f"[SYNC] ⚠️ Lot matching warning: {le}")
                    elif not discord_channel_id:
                        print(f"[SYNC] ⚠️ No channel_id for trade #{trade_id} - PNL updated but leaderboard not updated")
    
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
        
        # Build broker_override lookup for Pass 3 fallback
        # Maps broker_name -> [(channel_discord_id, channel_db_id), ...]
        broker_to_channels = {}
        try:
            all_channels = self.db.get_channels()
            for ch in all_channels:
                ch_broker = (ch.get('broker_override') or '').lower().strip()
                if ch_broker:
                    # Normalize broker names for comparison
                    if 'webull' in ch_broker:
                        ch_broker = 'webull'
                    elif 'alpaca' in ch_broker:
                        ch_broker = 'alpaca_paper' if 'paper' in ch_broker else 'alpaca'
                    
                    if ch_broker not in broker_to_channels:
                        broker_to_channels[ch_broker] = []
                    broker_to_channels[ch_broker].append({
                        'discord_id': ch.get('discord_channel_id'),
                        'db_id': ch.get('id'),
                        'name': ch.get('channel_name', 'Unknown')
                    })
        except Exception as e:
            print(f"[SYNC] Warning: Could not load broker_override mappings: {e}")
        
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
            
            # Pass 3: Auto-assign based on broker_override if ONLY ONE channel uses this broker
            # This handles cases where Discord execution didn't save to database
            current_broker = broker_name.lower()
            if 'webull' in current_broker:
                current_broker = 'webull'
            elif 'alpaca' in current_broker:
                current_broker = 'alpaca_paper' if 'paper' in current_broker else 'alpaca'
            
            channels_for_broker = broker_to_channels.get(current_broker, [])
            if len(channels_for_broker) == 1:
                # Only ONE channel uses this broker - safe to auto-assign
                channel_info = channels_for_broker[0]
                print(f"[SYNC] Auto-assigning {position['symbol']} to '{channel_info['name']}' (only channel using {broker_name})")
                return channel_info['discord_id']
            elif len(channels_for_broker) > 1:
                print(f"[SYNC] Cannot auto-assign {position['symbol']} - {len(channels_for_broker)} channels use {broker_name}")
            
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
                # Normalize broker name to consistent format (e.g., 'Webull' not 'WEBULL')
                normalized_broker = broker_name
                if broker_name.upper() == 'WEBULL':
                    normalized_broker = 'Webull'
                elif broker_name.upper() == 'ALPACA_PAPER':
                    normalized_broker = 'ALPACA_PAPER'
                elif broker_name.upper() == 'ALPACA_LIVE':
                    normalized_broker = 'ALPACA_LIVE'
                
                trade_data = {
                    'symbol': symbol,
                    'direction': 'BTO',
                    'quantity': position['quantity'],
                    'intended_price': position['avg_price'],
                    'executed_price': position['avg_price'],
                    'current_price': current_price,
                    'pnl': pnl,
                    'pnl_percent': pnl_percent,
                    'broker': normalized_broker,
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

    async def _sync_filled_orders(self, broker_name: str, broker_instance):
        """Sync filled orders from broker to database"""
        from gui_app.database import insert_filled_order, get_broker_sync_state, update_broker_sync_state
        
        try:
            print(f"[SYNC] Syncing filled orders from {broker_name}...")
            filled_orders = []
            
            # Fetch filled orders based on broker type
            if broker_name == 'Webull':
                if hasattr(broker_instance, 'get_order_history'):
                    filled_orders = await broker_instance.get_order_history(count=50)
            elif 'ALPACA' in broker_name.upper():
                if hasattr(broker_instance, 'get_filled_orders'):
                    filled_orders = await broker_instance.get_filled_orders(limit=50)
                elif hasattr(broker_instance, 'get_orders'):
                    # Fallback to get_orders with status filter
                    try:
                        orders = broker_instance.get_orders(status='closed')
                        for order in orders:
                            if hasattr(order, 'status') and str(order.status) == 'OrderStatus.FILLED':
                                filled_time = order.filled_at.isoformat() if order.filled_at else None
                                if filled_time:
                                    # Parse OCC symbol for options
                                    parsed = parse_occ_symbol(order.symbol)
                                    filled_orders.append({
                                        'order_id': str(order.id),
                                        'symbol': parsed['symbol'] if parsed else order.symbol,
                                        'quantity': int(float(order.filled_qty or order.qty)),
                                        'filled_price': float(order.filled_avg_price or 0),
                                        'action': 'BUY' if str(order.side) == 'OrderSide.BUY' else 'SELL',
                                        'filled_time': filled_time,
                                        'asset_type': 'option' if parsed else 'stock',
                                        'strike': parsed.get('strike') if parsed else None,
                                        'expiry': parsed.get('expiry') if parsed else None,
                                        'direction': parsed.get('call_put') if parsed else None
                                    })
                    except Exception as e:
                        print(f"[SYNC] Error getting Alpaca orders: {e}")
            elif broker_name == 'SCHWAB':
                if hasattr(broker_instance, 'get_order_history'):
                    filled_orders = await broker_instance.get_order_history(count=50)
            
            if not filled_orders:
                print(f"[SYNC] No filled orders from {broker_name}")
                return
            
            # Insert filled orders into database (deduplication via UNIQUE constraint)
            new_count = 0
            for order in filled_orders:
                # Normalize side to standard format
                side = order.get('action', '')
                if side.upper() in ['BUY']:
                    side = 'BTO'
                elif side.upper() in ['SELL']:
                    side = 'STC'
                
                # Calculate total cost
                qty = order.get('quantity', 0)
                price = order.get('filled_price', 0)
                total_cost = qty * price * (100 if order.get('asset_type') == 'option' else 1)
                
                # Ensure filled_at has a valid value and convert to ISO format
                raw_time = order.get('filled_time') or ''
                filled_time = self._normalize_timestamp(raw_time) if raw_time else datetime.now().isoformat()
                
                result = insert_filled_order(
                    broker=broker_name,
                    broker_order_id=str(order.get('order_id', '')),
                    symbol=order.get('symbol', ''),
                    side=side,
                    quantity=qty,
                    filled_price=price,
                    filled_at=filled_time,
                    asset_type=order.get('asset_type', 'stock'),
                    total_cost=total_cost,
                    strike=order.get('strike'),
                    expiry=order.get('expiry'),
                    option_type=order.get('direction')
                )
                
                if result:
                    new_count += 1
                    
                    # Also record in execution_lots for Execution P&L tracking
                    if side == 'BTO':
                        await self._record_execution_lot(
                            broker=broker_name,
                            broker_order_id=str(order.get('order_id', '')),
                            symbol=order.get('symbol', ''),
                            asset_type=order.get('asset_type', 'stock'),
                            strike=order.get('strike'),
                            expiry=order.get('expiry'),
                            call_put=order.get('direction'),
                            quantity=qty,
                            fill_price=price,
                            filled_at=filled_time
                        )
                    elif side == 'STC':
                        # Record exit in execution_closures
                        await self._record_execution_closure(
                            broker=broker_name,
                            broker_order_id=str(order.get('order_id', '')),
                            symbol=order.get('symbol', ''),
                            asset_type=order.get('asset_type', 'stock'),
                            strike=order.get('strike'),
                            expiry=order.get('expiry'),
                            call_put=order.get('direction'),
                            quantity=qty,
                            fill_price=price,
                            filled_at=filled_time
                        )
            
            if new_count > 0:
                print(f"[SYNC] ✓ Synced {new_count} new filled orders from {broker_name}")
            
            # Update sync state
            update_broker_sync_state(
                broker=broker_name,
                last_sync_at=datetime.now().isoformat()
            )
            
        except Exception as e:
            print(f"[SYNC] Error syncing filled orders from {broker_name}: {e}")
            import traceback
            traceback.print_exc()
            update_broker_sync_state(broker=broker_name, error=str(e))
    
    async def reconcile_risk_orders(self, risk_manager):
        """
        Reconcile pending risk orders with broker order statuses.
        Confirms fills and marks tiers, or clears failed/cancelled orders.
        
        Industry Standard: Only mark tiers as hit after confirmed fills.
        """
        if not risk_manager or not hasattr(risk_manager, 'cache'):
            return
        
        try:
            pending_orders = risk_manager.cache.get_all_pending_orders()
            if not pending_orders:
                return
            
            pending_count = sum(len(orders) for orders in pending_orders.values())
            print(f"[SYNC] 🔍 Reconciling {pending_count} pending risk order(s)...")
            
            for position_key, orders in pending_orders.items():
                for order_id, order_data in orders.items():
                    if order_data.get('status') != 'pending':
                        continue
                    
                    tier = order_data.get('tier', 0)
                    qty_expected = order_data.get('qty_expected', 0)
                    broker = order_data.get('broker') or self._extract_broker(position_key)
                    
                    # Check order status from broker
                    order_status = await self._get_order_status(broker, order_id)
                    
                    if order_status:
                        status = order_status.get('status', '').upper()
                        filled_qty = order_status.get('filled_qty', 0)
                        
                        if status == 'FILLED':
                            # Confirmed fill - mark tier as hit
                            risk_manager.cache.confirm_order_fill(position_key, order_id, filled_qty)
                            print(f"[SYNC] ✅ Risk order {order_id} FILLED - Tier {tier} confirmed")
                        elif status in ('CANCELLED', 'REJECTED', 'EXPIRED'):
                            # Order failed - clear pending so tier can retry
                            risk_manager.cache.fail_pending_order(position_key, order_id)
                            print(f"[SYNC] ❌ Risk order {order_id} {status} - Tier {tier} will retry")
                        elif status == 'PARTIALLY_FILLED' and filled_qty > 0:
                            # Partial fill - update tracking via cache entry
                            entry = risk_manager.cache.get(position_key)
                            if entry:
                                entry.update_pending_order(order_id, 'partial', filled_qty)
                            print(f"[SYNC] ⚠️ Risk order {order_id} partial: {filled_qty}/{qty_expected}")
                        # PENDING/OPEN - leave as is, will check next cycle
                    else:
                        # Could not get order status - check age and timeout if stale
                        created_at = order_data.get('created_at')
                        if created_at:
                            try:
                                from datetime import datetime
                                created = datetime.fromisoformat(created_at)
                                age = (datetime.now() - created).total_seconds()
                                if age > 300:  # 5 min timeout for stale pending orders
                                    risk_manager.cache.fail_pending_order(position_key, order_id)
                                    print(f"[SYNC] ⏰ Risk order {order_id} timed out after {age:.0f}s")
                            except:
                                pass
            
            # Save cache after reconciliation
            risk_manager.cache.save()
            
        except Exception as e:
            print(f"[SYNC] Error reconciling risk orders: {e}")
            import traceback
            traceback.print_exc()
    
    def _extract_broker(self, position_key: str) -> str:
        """Extract broker name from position key (format: Broker_SYMBOL_...)"""
        if position_key.startswith('Webull_'):
            return 'Webull'
        elif position_key.startswith('ALPACA_'):
            return 'Alpaca'
        elif position_key.startswith('IBKR_'):
            return 'IBKR'
        return 'Unknown'
    
    async def _get_order_status(self, broker: str, order_id: str) -> Optional[Dict]:
        """Get order status from broker API"""
        try:
            if broker == 'Webull':
                wb = getattr(self.broker_manager, 'webull_broker', None)
                if wb and hasattr(wb, 'get_order_status'):
                    return await wb.get_order_status(order_id)
            elif 'Alpaca' in broker:
                alpaca = getattr(self.broker_manager, 'alpaca_paper_broker', None)
                if alpaca and hasattr(alpaca, 'get_order'):
                    order = alpaca.get_order(order_id)
                    if order:
                        status_str = str(order.status).replace('OrderStatus.', '').upper()
                        return {
                            'status': status_str,
                            'filled_qty': int(float(order.filled_qty or 0))
                        }
        except Exception as e:
            # Order may not exist or API error - return None
            pass
        return None
    
    async def _record_execution_lot(self, broker: str, broker_order_id: str, symbol: str,
                                     asset_type: str, strike: float, expiry: str, call_put: str,
                                     quantity: int, fill_price: float, filled_at: str,
                                     channel_id: str = None, signal_price: float = None,
                                     signal_detected_at: str = None, signal_parsed_at: str = None,
                                     order_submitted_at: str = None, analyst_entry_qty: int = None,
                                     sizing_mode: str = None, signal_lot_id: int = None):
        """Record an entry fill as an execution_lot for Execution P&L tracking.
        
        First attempts to hydrate from pending_order_metadata for full signal context,
        then falls back to provided parameters.
        """
        try:
            def _insert_lot():
                from gui_app.database import insert_execution_lot, get_pending_order_metadata, update_pending_order_status
                
                # Try to hydrate from pending order metadata first
                meta = get_pending_order_metadata(broker=broker, broker_order_id=broker_order_id)
                
                # Use metadata values if available, else fall back to params
                final_channel_id = channel_id or (meta['channel_id'] if meta else None) or 'UNKNOWN'
                final_signal_price = signal_price or (meta['signal_price'] if meta else None)
                final_analyst_qty = analyst_entry_qty or (meta['analyst_qty'] if meta else None)
                final_sizing_mode = sizing_mode or (meta['sizing_mode'] if meta else None)
                final_signal_lot_id = signal_lot_id or (meta['signal_lot_id'] if meta else None)
                final_signal_detected = signal_detected_at or (meta['signal_detected_at'] if meta else None)
                final_signal_parsed = signal_parsed_at or (meta['signal_parsed_at'] if meta else None)
                final_order_submitted = order_submitted_at or (meta['order_submitted_at'] if meta else None)
                sizing_details = meta['sizing_details'] if meta else None
                
                # Mark pending metadata as filled
                if meta:
                    update_pending_order_status(broker, broker_order_id, 'FILLED')
                
                # Calculate slippage if signal_price available
                slippage_pct = None
                if final_signal_price and final_signal_price > 0:
                    slippage_pct = ((fill_price - final_signal_price) / final_signal_price) * 100
                
                # Calculate latency metrics
                latency_parse_ms = None
                latency_broker_ms = None
                latency_total_ms = None
                
                if final_signal_detected and final_signal_parsed:
                    try:
                        from datetime import datetime
                        detected = datetime.fromisoformat(str(final_signal_detected).replace('Z', '+00:00'))
                        parsed = datetime.fromisoformat(str(final_signal_parsed).replace('Z', '+00:00'))
                        latency_parse_ms = int((parsed - detected).total_seconds() * 1000)
                    except:
                        pass
                
                if final_order_submitted and filled_at:
                    try:
                        from datetime import datetime
                        submitted = datetime.fromisoformat(str(final_order_submitted).replace('Z', '+00:00'))
                        filled = datetime.fromisoformat(filled_at.replace('Z', '+00:00'))
                        latency_broker_ms = int((filled - submitted).total_seconds() * 1000)
                    except:
                        pass
                
                if final_signal_detected and filled_at:
                    try:
                        from datetime import datetime
                        detected = datetime.fromisoformat(str(final_signal_detected).replace('Z', '+00:00'))
                        filled = datetime.fromisoformat(filled_at.replace('Z', '+00:00'))
                        latency_total_ms = int((filled - detected).total_seconds() * 1000)
                    except:
                        pass
                
                return insert_execution_lot(
                    signal_lot_id=final_signal_lot_id,
                    channel_id=final_channel_id,
                    broker=broker,
                    broker_order_id=broker_order_id,
                    symbol=symbol,
                    asset_type=asset_type,
                    strike=strike,
                    expiry=expiry,
                    call_put=call_put,
                    original_qty=quantity,
                    remaining_qty=quantity,
                    fill_price=fill_price,
                    signal_price=final_signal_price,
                    slippage_pct=slippage_pct,
                    signal_detected_at=final_signal_detected,
                    signal_parsed_at=final_signal_parsed,
                    order_submitted_at=final_order_submitted,
                    order_filled_at=filled_at,
                    latency_parse_ms=latency_parse_ms,
                    latency_broker_ms=latency_broker_ms,
                    latency_total_ms=latency_total_ms,
                    analyst_entry_qty=final_analyst_qty,
                    sizing_mode=final_sizing_mode,
                    sizing_details=sizing_details
                )
            
            result = await asyncio.to_thread(_insert_lot)
            if result:
                print(f"[EXEC] ✓ Recorded execution lot: {symbol} {quantity}x @${fill_price:.2f}")
            return result
            
        except Exception as e:
            print(f"[EXEC] Error recording execution lot: {e}")
            return None
    
    async def _record_execution_closure(self, broker: str, broker_order_id: str, symbol: str,
                                         asset_type: str, strike: float, expiry: str, call_put: str,
                                         quantity: int, fill_price: float, filled_at: str,
                                         exit_source: str = 'SIGNAL', signal_exit_price: float = None,
                                         order_submitted_at: str = None, channel_id: str = None):
        """Record an exit fill as an execution_closure with P&L calculation.
        
        Uses atomic transaction (BEGIN IMMEDIATE) to prevent race conditions
        when concurrent STC fills arrive for the same position.
        """
        try:
            def _insert_closure():
                from gui_app.database import record_execution_closure_atomic
                
                # Use atomic function for transaction safety
                closure_id, pnl = record_execution_closure_atomic(
                    broker=broker,
                    symbol=symbol,
                    asset_type=asset_type,
                    closed_qty=quantity,
                    fill_price=fill_price,
                    filled_at=filled_at,
                    exit_source=exit_source,
                    strike=strike,
                    expiry=expiry,
                    call_put=call_put,
                    broker_order_id=broker_order_id,
                    signal_exit_price=signal_exit_price,
                    order_submitted_at=order_submitted_at,
                    channel_id=channel_id
                )
                
                if closure_id and pnl is not None:
                    pnl_sign = '+' if pnl >= 0 else ''
                    print(f"[EXEC] ✓ Recorded closure: {symbol} {quantity}x @${fill_price:.2f} = {pnl_sign}${pnl:.2f}")
                elif closure_id is None:
                    print(f"[EXEC] ⚠️ No matching execution lot for {symbol} exit (or duplicate closure)")
                
                return closure_id
            
            result = await asyncio.to_thread(_insert_closure)
            return result
            
        except Exception as e:
            print(f"[EXEC] Error recording execution closure: {e}")
            import traceback
            traceback.print_exc()
            return None
