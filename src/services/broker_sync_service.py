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
        self._first_sync_callback = None  # Called after first sync completes
        self._first_sync_done = False
        self._order_in_progress = asyncio.Event()
        self._order_in_progress.set()
        
        print(f"[SYNC] BrokerSyncService initialized (interval={sync_interval}s)")
    
    def pause_for_order(self):
        """Signal that an order is being executed — sync should yield"""
        self._order_in_progress.clear()
    
    def resume_after_order(self):
        """Signal that order execution is done — sync can proceed"""
        self._order_in_progress.set()
    
    def set_first_sync_callback(self, callback):
        """Set callback to run after first sync cycle completes (used for sync_ready event)"""
        self._first_sync_callback = callback
    
    def set_risk_manager(self, risk_manager):
        """Set risk manager reference for pending order reconciliation."""
        self._risk_manager = risk_manager
        if risk_manager:
            print("[SYNC] ✓ Risk manager linked for order reconciliation")

    def _find_risk_cache_entry(self, cache, broker_name, symbol, trade):
        """Check if risk cache has an active entry for this trade.

        Returns the current_price if found, None otherwise.
        """
        entry = self._get_risk_cache_entry(cache, broker_name, symbol, trade)
        if entry and getattr(entry, 'current_price', 0) > 0:
            return entry.current_price
        return None

    def _get_risk_cache_entry(self, cache, broker_name, symbol, trade):
        """Get the full risk cache entry for a trade.

        Returns the PositionCacheEntry if found, None otherwise.
        Handles both stock keys (broker_symbol_stock) and option keys
        (broker_symbol_strike_expiry_direction) by iterating cache entries.
        """
        asset_type = trade.get('asset_type', 'stock')
        simple_key = f"{broker_name}_{symbol}_{asset_type}"
        entry = cache.get(simple_key)
        if entry and getattr(entry, 'current_price', 0) > 0:
            return entry

        if asset_type == 'option':
            strike = trade.get('strike')
            expiry = trade.get('expiry')
            call_put = trade.get('call_put', '')
            if strike and expiry:
                option_key = f"{broker_name}_{symbol}_{strike}_{expiry}_{call_put}"
                entry = cache.get(option_key)
                if entry and getattr(entry, 'current_price', 0) > 0:
                    return entry

            try:
                symbol_upper = symbol.upper()
                broker_upper = broker_name.upper()
                _SYNC_ALIASES = {
                    'SPX': {'SPX', 'SPXW'}, 'SPXW': {'SPX', 'SPXW'},
                    'NDX': {'NDX', 'NDXP'}, 'NDXP': {'NDX', 'NDXP'},
                    'VIX': {'VIX', 'VIXW'}, 'VIXW': {'VIX', 'VIXW'},
                    'RUT': {'RUT', 'RUTW'}, 'RUTW': {'RUT', 'RUTW'},
                }
                symbols_to_match = _SYNC_ALIASES.get(symbol_upper, {symbol_upper})
                for cache_key in list(cache._cache.keys()):
                    cache_key_upper = cache_key.upper()
                    if broker_upper not in cache_key_upper:
                        continue
                    if any(s in cache_key_upper for s in symbols_to_match):
                        e = cache._cache.get(cache_key)
                        if e and getattr(e, 'current_price', 0) > 0:
                            return e
            except Exception:
                pass

        return None
    
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
        _consecutive_errors = 0
        _MAX_BACKOFF = 120
        
        while self.running:
            try:
                if not self._order_in_progress.is_set():
                    print("[SYNC] ⏸️ Order in progress — deferring sync cycle", flush=True)
                    try:
                        await asyncio.wait_for(self._order_in_progress.wait(), timeout=30)
                    except asyncio.TimeoutError:
                        print("[SYNC] ⚠️ Order pause timeout (30s) — resuming sync", flush=True)
                        self._order_in_progress.set()
                
                await self._perform_sync()
                _consecutive_errors = 0
                await asyncio.sleep(self.sync_interval)
                
            except asyncio.CancelledError:
                print("[SYNC] Sync loop cancelled", flush=True)
                break
            except Exception as e:
                _consecutive_errors += 1
                backoff = min(self.sync_interval * (2 ** _consecutive_errors), _MAX_BACKOFF)
                print(f"[SYNC] Error in sync loop (attempt {_consecutive_errors}, backoff {backoff:.0f}s): {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(backoff)
    
    async def _perform_sync(self):
        """Perform one sync cycle across all brokers"""
        print("[SYNC] 🔄 Starting sync cycle", flush=True)
        
        # Get all configured brokers
        brokers_to_sync = []
        
        # Add Webull if available
        if hasattr(self.broker_manager, 'webull_broker') and self.broker_manager.webull_broker:
            brokers_to_sync.append(('Webull', self.broker_manager.webull_broker))
        
        # Add Webull Paper if available
        if hasattr(self.broker_manager, 'webull_paper_broker') and self.broker_manager.webull_paper_broker:
            wb_paper = self.broker_manager.webull_paper_broker
            if getattr(wb_paper, '_logged_in', False) or getattr(wb_paper, 'connected', False):
                brokers_to_sync.append(('WEBULL_PAPER', wb_paper))
        
        # Add Alpaca if available
        if hasattr(self.broker_manager, 'alpaca_paper_broker') and self.broker_manager.alpaca_paper_broker:
            brokers_to_sync.append(('ALPACA_PAPER', self.broker_manager.alpaca_paper_broker))
        
        # Add Tastytrade if available
        if hasattr(self.broker_manager, 'tastytrade_broker') and self.broker_manager.tastytrade_broker:
            tt_broker = self.broker_manager.tastytrade_broker
            # Determine if live or paper based on broker settings
            broker_label = 'TASTYTRADE_LIVE' if getattr(tt_broker, 'is_live', False) else 'TASTYTRADE_PAPER'
            brokers_to_sync.append((broker_label, tt_broker))
        
        # Add Schwab if available (check both broker_manager and bot instance for hot-connect)
        schwab_broker = getattr(self.broker_manager, 'schwab_broker', None)
        if not schwab_broker:
            try:
                from gui_app.routes import _bot_instance
                if _bot_instance and getattr(_bot_instance, 'schwab_broker', None):
                    schwab_broker = _bot_instance.schwab_broker
                    self.broker_manager.schwab_broker = schwab_broker
                    print("[SYNC] 🔗 Schwab broker recovered from bot instance (hot-connect sync)", flush=True)
            except Exception:
                pass
        if schwab_broker:
            try:
                is_auth = schwab_broker.is_authenticated()
                if is_auth:
                    brokers_to_sync.append(('SCHWAB', schwab_broker))
                elif getattr(schwab_broker, 'connected', False):
                    brokers_to_sync.append(('SCHWAB', schwab_broker))
                    print("[SYNC] ⚠️ Schwab: is_authenticated()=False but connected=True — syncing anyway", flush=True)
            except Exception as schwab_err:
                print(f"[SYNC] ⚠️ Schwab auth check failed: {schwab_err}", flush=True)
        
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
        
        # ===== INDIA BROKERS (WARNING: ALL LIVE ONLY - no paper trading) =====
        
        # Add Zerodha if available
        if hasattr(self.broker_manager, 'zerodha_broker') and self.broker_manager.zerodha_broker:
            zerodha = self.broker_manager.zerodha_broker
            try:
                if getattr(zerodha, 'connected', False):
                    brokers_to_sync.append(('ZERODHA', zerodha))
            except Exception:
                pass
        
        # Add Upstox if available
        if hasattr(self.broker_manager, 'upstox_broker') and self.broker_manager.upstox_broker:
            upstox = self.broker_manager.upstox_broker
            try:
                if getattr(upstox, 'connected', False):
                    brokers_to_sync.append(('UPSTOX', upstox))
            except Exception:
                pass
        
        # Add DhanQ if available
        if hasattr(self.broker_manager, 'dhanq_broker') and self.broker_manager.dhanq_broker:
            dhanq = self.broker_manager.dhanq_broker
            try:
                if getattr(dhanq, 'connected', False):
                    brokers_to_sync.append(('DHANQ', dhanq))
            except Exception:
                pass
        
        # Add Trading 212 if available (UK/EU stocks only)
        if hasattr(self.broker_manager, 'trading212_broker') and self.broker_manager.trading212_broker:
            t212 = self.broker_manager.trading212_broker
            try:
                if getattr(t212, 'connected', False):
                    broker_label = 'TRADING212' if getattr(t212, 'is_live', True) else 'TRADING212_PAPER'
                    brokers_to_sync.append((broker_label, t212))
            except Exception:
                pass

        # Add Webull Official if available
        if hasattr(self.broker_manager, 'webull_official_broker') and self.broker_manager.webull_official_broker:
            wo = self.broker_manager.webull_official_broker
            try:
                if getattr(wo, 'connected', False):
                    broker_label = 'WEBULL_OFFICIAL_LIVE' if not getattr(wo, 'paper_trade', True) else 'WEBULL_OFFICIAL_PAPER'
                    brokers_to_sync.append((broker_label, wo))
            except Exception:
                pass

        if not brokers_to_sync:
            print("[SYNC] No brokers available for sync", flush=True)
            return
        
        print(f"[SYNC] Syncing {len(brokers_to_sync)} broker(s): {[b[0] for b in brokers_to_sync]}")
        
        if not self._order_in_progress.is_set():
            print(f"[SYNC] ⚡ Order incoming — skipping sync cycle", flush=True)
            return

        import time as _sync_timer
        _parallel_start = _sync_timer.monotonic()

        async def _sync_one(broker_name, broker_instance):
            try:
                await asyncio.wait_for(
                    self._sync_broker(broker_name, broker_instance),
                    timeout=25.0
                )
            except asyncio.TimeoutError:
                print(f"[SYNC] ⚠️ {broker_name} sync timed out after 25s — skipping", flush=True)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                error_str = str(e)
                is_transient = any(msg in error_str for msg in [
                    "cannot schedule new futures after shutdown",
                    "Event loop is closed",
                    "Session is closed",
                ])
                if is_transient:
                    print(f"[SYNC] ⏳ Transient error syncing {broker_name}: {e}")
                else:
                    print(f"[SYNC] Error syncing {broker_name}: {e}")

        await asyncio.gather(
            *[_sync_one(name, inst) for name, inst in brokers_to_sync],
            return_exceptions=True
        )

        _parallel_elapsed = (_sync_timer.monotonic() - _parallel_start) * 1000
        print(f"[SYNC] ✓ Sync cycle complete ({len(brokers_to_sync)} brokers, {_parallel_elapsed:.0f}ms)", flush=True)
        
        # Fire first sync callback (signals sync_ready event to worker)
        if not self._first_sync_done and self._first_sync_callback:
            try:
                self._first_sync_callback()
                self._first_sync_done = True
                print("[SYNC] ✓ First sync complete - worker ready to process orders")
            except Exception as e:
                print(f"[SYNC] Warning: First sync callback failed: {e}")
        
        if hasattr(self, '_risk_manager') and self._risk_manager:
            try:
                count = self._risk_manager.cache.populate_trade_id_mappings()
                if count > 0:
                    print(f"[SYNC] ✓ Mapped {count} trades to position cache for persistence")
            except Exception as e:
                print(f"[SYNC] Warning: Could not populate trade_id mappings: {e}")
    
    async def _sync_broker(self, broker_name: str, broker_instance):
        """Sync trades for a specific broker"""
        print(f"[SYNC] Syncing {broker_name}...")
        
        normalized_data = await self._fetch_and_normalize(broker_name, broker_instance)
        await asyncio.sleep(0)

        if not normalized_data:
            print(f"[SYNC] No data from {broker_name}")
            return

        if not hasattr(self, '_fill_sync_counter'):
            self._fill_sync_counter = {}
        self._fill_sync_counter[broker_name] = self._fill_sync_counter.get(broker_name, 0) + 1

        has_positions = bool(normalized_data.get('positions'))
        has_db_trades = False
        has_pending_trades = False
        try:
            from gui_app.database import get_open_trades_for_broker
            active = get_open_trades_for_broker(broker_name)
            has_db_trades = bool(active)
            if active:
                has_pending_trades = any(t.get('status') == 'PENDING' for t in active)
        except Exception:
            has_db_trades = True

        # Sync fills BEFORE reconcile so exit fill prices are available when close is detected
        fill_sync_interval = 1 if (has_pending_trades or has_positions) else 5
        if self._fill_sync_counter[broker_name] >= fill_sync_interval and (has_positions or has_db_trades):
            await self._sync_filled_orders(broker_name, broker_instance)
            self._fill_sync_counter[broker_name] = 0
            await asyncio.sleep(0)
        elif self._fill_sync_counter[broker_name] >= 5:
            self._fill_sync_counter[broker_name] = 0

        await self._reconcile_trades(broker_name, normalized_data, broker_instance=broker_instance)
        await asyncio.sleep(0)
        
        if hasattr(self, '_risk_manager') and self._risk_manager:
            await self.reconcile_bracket_orders(self._risk_manager)
            await asyncio.sleep(0)
            await self.reconcile_risk_orders(self._risk_manager)
            await asyncio.sleep(0)
        
        print(f"[SYNC] ✓ {broker_name} sync complete")
        
        if not hasattr(self, '_health_sync_counter'):
            self._health_sync_counter = {}
        is_first_health_update = broker_name not in self._health_sync_counter
        self._health_sync_counter[broker_name] = self._health_sync_counter.get(broker_name, 0) + 1
        if is_first_health_update or self._health_sync_counter[broker_name] >= 2:
            self._health_sync_counter[broker_name] = 0
            asyncio.ensure_future(self._update_health_async(broker_name, broker_instance))
    
    async def _update_health_async(self, broker_name, broker_instance):
        try:
            from src.services.broker_health_monitor import get_health_monitor
            health_monitor = get_health_monitor()

            if not hasattr(self, '_last_account_fetch_ts'):
                self._last_account_fetch_ts = {}
            import time as _time
            now = _time.time()
            last_fetch = self._last_account_fetch_ts.get(broker_name, 0)
            if now - last_fetch < 60:
                if not hasattr(self, '_cached_account_info'):
                    self._cached_account_info = {}
                cached = self._cached_account_info.get(broker_name)
                if cached:
                    health_monitor.update_broker_status(broker_name, True, account_info=cached)
                    return

            account_info = await asyncio.wait_for(
                self._fetch_account_info(broker_name, broker_instance),
                timeout=15
            )
            self._last_account_fetch_ts[broker_name] = now
            if not hasattr(self, '_cached_account_info'):
                self._cached_account_info = {}
            self._cached_account_info[broker_name] = account_info
            health_monitor.update_broker_status(broker_name, True, account_info=account_info)

            try:
                from src.services.daily_pnl_limit_service import get_daily_pnl_service
                pnl_service = get_daily_pnl_service()
                pnl_service.check_and_reset_if_new_day()
                pv = float(account_info.get('portfolio_value', 0) or 0)
                if pv > 0:
                    pnl_service.update_broker_pnl(broker_name, pv)
            except Exception as pnl_err:
                print(f"[SYNC] Daily P&L update error for {broker_name}: {pnl_err}")
        except asyncio.TimeoutError:
            print(f"[SYNC] ⚠️ {broker_name} account info fetch timed out after 15s")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[SYNC] Health monitor update failed: {e}")
    
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
            if broker_name in ('Webull', 'WEBULL_PAPER'):
                # Get positions using detailed method (supports options)
                if hasattr(broker_instance, 'get_positions_detailed'):
                    print(f"[SYNC] [DEBUG] Calling get_positions_detailed for {broker_name}, type={type(broker_instance).__name__}", flush=True)
                    _prev_wb_count = len(result['positions'])
                    positions = await broker_instance.get_positions_detailed() or []
                    print(f"[SYNC] [DEBUG] get_positions_detailed returned {len(positions)} positions for {broker_name}", flush=True)
                    
                    for pos in positions:
                        result['positions'].append({
                            'symbol': pos.get('symbol'),
                            'quantity': pos.get('quantity'),
                            'avg_price': pos.get('avg_cost'),
                            'current_price': pos.get('current_price'),
                            'unrealized_pnl': pos.get('unrealized_pl'),
                            'position_id': pos.get('option_id') or pos.get('ticker_id'),
                            'asset_type': pos.get('asset', 'stock'),
                            'strike': pos.get('strike'),
                            'expiry': pos.get('expiry'),
                            'call_put': pos.get('direction')
                        })
                    _new_wb_count = len(result['positions']) - _prev_wb_count
                    if _new_wb_count > 0:
                        try:
                            from src.services.webull_data_hub import get_webull_data_hub
                            get_webull_data_hub().request_risk_eval()
                        except Exception:
                            pass
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
                if hasattr(broker_instance, 'account_hash') and not broker_instance.account_hash:
                    print(f"[SYNC] ⚠️ SCHWAB missing account_hash — marking data as unreliable")
                    result['_fetch_error'] = True
                if hasattr(broker_instance, 'get_positions_detailed'):
                    positions = await broker_instance.get_positions_detailed() or []
                    
                    if not positions and not result.get('_fetch_error'):
                        had_error = getattr(broker_instance, '_last_fetch_had_error', False)
                        if had_error:
                            print(f"[SYNC] ⚠️ SCHWAB returned 0 positions after internal error — marking as fetch error")
                            result['_fetch_error'] = True
                    
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
                    
                    try:
                        if hasattr(broker_instance, '_data_hub') and broker_instance._data_hub:
                            broker_instance._data_hub.update_positions(positions, source="sync")
                        if positions and hasattr(broker_instance, 'subscribe_position_symbols'):
                            await broker_instance.subscribe_position_symbols(positions)
                    except Exception:
                        pass
                
                if hasattr(broker_instance, 'get_pending_orders'):
                    try:
                        orders = await asyncio.wait_for(
                            broker_instance.get_pending_orders(),
                            timeout=15.0
                        ) or []
                        for order in orders:
                            result['pending_orders'].append({
                                'broker_order_id': order.get('order_id'),
                                'symbol': order.get('symbol'),
                                'quantity': order.get('quantity'),
                                'limit_price': order.get('limit_price'),
                                'order_type': order.get('action'),
                                'status': order.get('status')
                            })
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        print(f"[SYNC] SCHWAB get_pending_orders timed out - skipping orders", flush=True)
            
            elif broker_name.startswith('IBKR'):
                # IBKR - Interactive Brokers via ib_insync (requires TWS/Gateway)
                if hasattr(broker_instance, 'ib') and broker_instance.ib.isConnected():
                    try:
                        ib = broker_instance.ib
                        # Use ib.portfolio() first — it includes marketPrice for P&L
                        raw_positions = await asyncio.to_thread(ib.portfolio)
                        if not raw_positions:
                            raw_positions = await asyncio.to_thread(ib.positions)

                        for pos in raw_positions:
                            contract = pos.contract
                            symbol = contract.symbol
                            quantity = abs(int(pos.position))
                            if quantity == 0:
                                continue
                            avg_cost_raw = getattr(pos, 'avgCost', None) or getattr(pos, 'averageCost', None) or 0
                            avg_cost = float(avg_cost_raw) if avg_cost_raw else 0

                            if contract.secType == 'OPT':
                                expiry_raw = contract.lastTradeDateOrContractMonth
                                if len(expiry_raw) == 8:
                                    expiry = f"{expiry_raw[:4]}-{expiry_raw[4:6]}-{expiry_raw[6:8]}"
                                else:
                                    expiry = expiry_raw

                                _mkt_price = float(getattr(pos, 'marketPrice', 0) or 0)
                                _IB_SENTINEL = 1.7976931348623157e+308
                                if _mkt_price <= 0 or _mkt_price >= _IB_SENTINEL:
                                    _mkt_price = 0
                                _unrealized = float(getattr(pos, 'unrealizedPNL', 0) or 0)
                                result['positions'].append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'avg_price': avg_cost / 100 if avg_cost > 0 else 0,
                                    'current_price': _mkt_price,
                                    'unrealized_pnl': _unrealized,
                                    'position_id': contract.conId,
                                    'asset_type': 'option',
                                    'strike': contract.strike,
                                    'expiry': expiry,
                                    'call_put': contract.right
                                })
                            else:
                                _mkt_price = float(getattr(pos, 'marketPrice', 0) or 0)
                                _IB_SENTINEL = 1.7976931348623157e+308
                                if _mkt_price <= 0 or _mkt_price >= _IB_SENTINEL:
                                    _mkt_price = 0
                                _unrealized = float(getattr(pos, 'unrealizedPNL', 0) or 0)
                                result['positions'].append({
                                    'symbol': symbol,
                                    'quantity': quantity,
                                    'avg_price': avg_cost,
                                    'current_price': _mkt_price,
                                    'unrealized_pnl': _unrealized,
                                    'position_id': contract.conId,
                                    'asset_type': 'stock'
                                })

                        raw_trades = await asyncio.to_thread(ib.openTrades)
                        for trade in raw_trades:
                            order = trade.order
                            contract = trade.contract
                            result['pending_orders'].append({
                                'broker_order_id': str(order.orderId),
                                'symbol': contract.symbol if contract else '',
                                'quantity': order.totalQuantity if hasattr(order, 'totalQuantity') else 0,
                                'limit_price': order.lmtPrice if hasattr(order, 'lmtPrice') else None,
                                'order_type': order.action if hasattr(order, 'action') else '',
                                'status': trade.orderStatus.status if trade.orderStatus else 'PENDING'
                            })
                    except Exception as e:
                        print(f"[SYNC] IBKR fetch error: {e}")
                        result['_fetch_error'] = True
                else:
                    print(f"[SYNC] ⚠️ IBKR not connected to TWS/Gateway — marking as fetch error to protect trades")
                    result['_fetch_error'] = True
            
            elif broker_name.startswith('TASTYTRADE'):
                if hasattr(broker_instance, 'session') and broker_instance.session:
                    try:
                        tt_hub = None
                        try:
                            from src.services.tastytrade_data_hub import get_tastytrade_data_hub
                            tt_hub = get_tastytrade_data_hub()
                            if tt_hub and not tt_hub._broker:
                                tt_hub.set_broker(broker_instance)
                        except Exception:
                            pass

                        if hasattr(broker_instance, 'get_all_positions'):
                            positions = await asyncio.to_thread(broker_instance.get_all_positions) or []
                            if tt_hub:
                                tt_hub.update_positions(positions, source='sync')
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
                            if tt_hub:
                                tt_hub.update_pending_orders(orders)
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
                                # Use new normalized field names from robinhood_broker.py
                                'strike': pos.get('strike') or pos.get('strike_price'),
                                'expiry': pos.get('expiry') or pos.get('expiration_date'),
                                'call_put': pos.get('call_put') or ('C' if pos.get('option_type') == 'call' else 'P' if pos.get('option_type') == 'put' else None)
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
            
            # ===== INDIA BROKERS =====
            
            elif broker_name == 'ZERODHA':
                if hasattr(broker_instance, 'get_positions'):
                    try:
                        positions = await broker_instance.get_positions() or []
                        for pos in positions:
                            product = pos.get('product', 'MIS')
                            quantity = pos.get('quantity', 0) or pos.get('overnight_quantity', 0) or pos.get('day_quantity', 0)
                            if quantity == 0:
                                continue
                            result['positions'].append({
                                'symbol': pos.get('tradingsymbol'),
                                'quantity': quantity,
                                'avg_price': pos.get('average_price') or pos.get('buy_price') or 0,
                                'current_price': pos.get('last_price') or 0,
                                'unrealized_pnl': pos.get('pnl') or pos.get('unrealised') or 0,
                                'position_id': None,
                                'asset_type': 'option' if any(x in pos.get('tradingsymbol', '') for x in ['CE', 'PE']) else 'stock',
                                'product': product,
                                'exchange': pos.get('exchange', 'NSE')
                            })
                        
                        if hasattr(broker_instance, 'get_orders'):
                            orders = await broker_instance.get_orders() or []
                            for order in orders:
                                status = (order.get('status') or '').upper()
                                if status in ('COMPLETE', 'CANCELLED', 'REJECTED'):
                                    continue
                                result['pending_orders'].append({
                                    'broker_order_id': order.get('order_id'),
                                    'symbol': order.get('tradingsymbol'),
                                    'quantity': order.get('quantity'),
                                    'limit_price': order.get('price'),
                                    'order_type': order.get('transaction_type'),
                                    'status': status
                                })
                    except Exception as e:
                        print(f"[SYNC] Zerodha fetch error: {e}")
                        import traceback
                        traceback.print_exc()
            
            elif broker_name == 'UPSTOX':
                if hasattr(broker_instance, 'get_positions'):
                    try:
                        positions = await broker_instance.get_positions() or []
                        for pos in positions:
                            quantity = pos.get('quantity', 0) or pos.get('net_quantity', 0)
                            if quantity == 0:
                                continue
                            symbol = pos.get('trading_symbol') or pos.get('tradingsymbol') or ''
                            result['positions'].append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'avg_price': pos.get('average_price') or pos.get('buy_price') or 0,
                                'current_price': pos.get('last_price') or pos.get('ltp') or 0,
                                'unrealized_pnl': pos.get('pnl') or pos.get('unrealised_pnl') or 0,
                                'position_id': pos.get('instrument_token'),
                                'asset_type': 'option' if any(x in symbol for x in ['CE', 'PE']) else 'stock',
                                'product': pos.get('product', 'I'),
                                'exchange': pos.get('exchange', 'NSE_FO')
                            })
                        
                        if hasattr(broker_instance, 'get_orders'):
                            orders = await broker_instance.get_orders() or []
                            for order in orders:
                                status = (order.get('status') or '').upper()
                                if status in ('COMPLETE', 'CANCELLED', 'REJECTED', 'FILLED'):
                                    continue
                                result['pending_orders'].append({
                                    'broker_order_id': order.get('order_id'),
                                    'symbol': order.get('trading_symbol') or order.get('tradingsymbol'),
                                    'quantity': order.get('quantity'),
                                    'limit_price': order.get('price'),
                                    'order_type': order.get('transaction_type'),
                                    'status': status
                                })
                    except Exception as e:
                        print(f"[SYNC] Upstox fetch error: {e}")
                        import traceback
                        traceback.print_exc()
            
            elif broker_name == 'DHANQ':
                if hasattr(broker_instance, 'get_positions'):
                    try:
                        positions = await broker_instance.get_positions() or []
                        for pos in positions:
                            quantity = pos.get('netQty', 0) or pos.get('quantity', 0)
                            if quantity == 0:
                                continue
                            symbol = pos.get('tradingSymbol') or pos.get('symbol') or ''
                            result['positions'].append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'avg_price': pos.get('averagePrice') or pos.get('buyAvg') or 0,
                                'current_price': pos.get('lastTradedPrice') or pos.get('ltp') or 0,
                                'unrealized_pnl': pos.get('unrealizedProfit') or pos.get('pnl') or 0,
                                'position_id': pos.get('securityId'),
                                'asset_type': 'option' if any(x in symbol for x in ['CE', 'PE']) else 'stock',
                                'product': pos.get('productType', 'INTRADAY'),
                                'exchange': pos.get('exchangeSegment', 'NSE_FNO')
                            })
                        
                        if hasattr(broker_instance, 'get_orders'):
                            orders = await broker_instance.get_orders() or []
                            for order in orders:
                                status = (order.get('orderStatus') or order.get('status') or '').upper()
                                if status in ('TRADED', 'CANCELLED', 'REJECTED'):
                                    continue
                                result['pending_orders'].append({
                                    'broker_order_id': order.get('orderId'),
                                    'symbol': order.get('tradingSymbol') or order.get('symbol'),
                                    'quantity': order.get('quantity'),
                                    'limit_price': order.get('price'),
                                    'order_type': order.get('transactionType'),
                                    'status': status
                                })
                    except Exception as e:
                        print(f"[SYNC] DhanQ fetch error: {e}")
                        import traceback
                        traceback.print_exc()
            
            elif broker_name in ('TRADING212', 'TRADING212_PAPER'):
                if hasattr(broker_instance, 'get_positions'):
                    try:
                        positions = await broker_instance.get_positions() or []
                        for pos in positions:
                            qty = float(pos.get('quantity', 0))
                            if qty == 0:
                                continue
                            result['positions'].append({
                                'symbol': pos.get('symbol'),
                                'quantity': qty,
                                'avg_price': float(pos.get('avg_cost', 0) or 0),
                                'current_price': float(pos.get('current_price', 0) or 0),
                                'unrealized_pnl': float(pos.get('unrealized_pnl', 0) or 0),
                                'position_id': None,
                                'asset_type': 'stock'
                            })

                        if hasattr(broker_instance, 'get_pending_orders'):
                            orders = await broker_instance.get_pending_orders() or []
                            for order in orders:
                                result['pending_orders'].append({
                                    'broker_order_id': order.get('order_id'),
                                    'symbol': order.get('symbol'),
                                    'quantity': order.get('quantity'),
                                    'limit_price': order.get('limit_price'),
                                    'order_type': 'BUY' if order.get('side', '').upper() == 'BUY' else 'SELL',
                                    'status': order.get('status')
                                })
                    except Exception as e:
                        print(f"[SYNC] Trading 212 fetch error: {e}")
                        import traceback
                        traceback.print_exc()

            elif broker_name.startswith('WEBULL_OFFICIAL'):
                if hasattr(broker_instance, 'get_positions'):
                    try:
                        positions = await broker_instance.get_positions() or []
                        for pos in positions:
                            asset = pos.get('asset', 'stock')
                            call_put = None
                            strike = None
                            expiry = None
                            if asset == 'option':
                                ot = (pos.get('option_type') or '').upper()
                                call_put = 'C' if 'CALL' in ot else ('P' if 'PUT' in ot else None)
                                strike = float(pos.get('strike_price') or 0) or None
                                expiry = pos.get('expiry_date')
                            qty = abs(float(pos.get('quantity', 0)))
                            if qty == 0:
                                continue
                            result['positions'].append({
                                'symbol': pos.get('symbol'),
                                'quantity': qty,
                                'avg_price': float(pos.get('avg_cost', 0) or 0),
                                'current_price': float(pos.get('current_price', 0) or 0),
                                'unrealized_pnl': float(pos.get('unrealized_pl', 0) or 0),
                                'position_id': pos.get('position_id'),
                                'asset_type': asset,
                                'strike': strike,
                                'expiry': expiry,
                                'call_put': call_put,
                                'broker': broker_name,
                            })
                    except Exception as e:
                        print(f"[SYNC] Webull Official fetch error: {e}")
                        import traceback
                        traceback.print_exc()

                if hasattr(broker_instance, 'get_pending_orders'):
                    try:
                        orders = await broker_instance.get_pending_orders() or []
                        for order in orders:
                            side = (order.get('action') or '').upper()
                            # DB stores client_order_id as order_id (what we generated before sending).
                            # order_id field from get_pending_orders() IS the client_order_id.
                            # broker_order_id is the server-side numeric ID — not what's in the DB.
                            # Prioritise client_order_id so pending_by_order_id keys match the DB.
                            result['pending_orders'].append({
                                'broker_order_id': order.get('order_id') or order.get('broker_order_id'),
                                'symbol': order.get('symbol'),
                                'quantity': order.get('quantity'),
                                'limit_price': order.get('limit_price'),
                                'order_type': 'BTO' if side in ('BUY', 'BUY_TO_OPEN') else 'STC',
                                'status': order.get('status', 'PENDING')
                            })
                    except Exception as e:
                        print(f"[SYNC] Webull Official pending orders error: {e}")

            print(f"[SYNC] {broker_name}: {len(result['positions'])} positions, {len(result['pending_orders'])} pending orders")
            if result['positions']:
                symbols = [p['symbol'] for p in result['positions']]
                print(f"[SYNC] {broker_name} positions: {symbols}")
            return result
            
        except Exception as e:
            print(f"[SYNC] Error fetching from {broker_name}: {e}")
            import traceback
            traceback.print_exc()
            
            try:
                from src.services.broker_health_monitor import get_health_monitor
                health_monitor = get_health_monitor()
                
                error_str = str(e).lower()
                error_code = 'API_ERROR'
                reason = str(e)
                
                if '401' in error_str or 'unauthorized' in error_str or 'invalid token' in error_str:
                    error_code = 'TOKEN_EXPIRED'
                    reason = f'{broker_name} access token expired - please re-authenticate'
                elif 'expired' in error_str or 'session' in error_str:
                    error_code = 'TOKEN_EXPIRED'
                    reason = f'{broker_name} session expired - please re-login'
                elif 'rate limit' in error_str or '429' in error_str:
                    error_code = 'RATE_LIMITED'
                    reason = f'{broker_name} rate limited - will retry'
                elif 'network' in error_str or 'connection' in error_str or 'timeout' in error_str:
                    error_code = 'NETWORK_ERROR'
                    reason = f'{broker_name} network error - check connection'
                elif 'auth' in error_str or 'credential' in error_str:
                    error_code = 'AUTH_FAILED'
                    reason = f'{broker_name} authentication failed - check credentials'
                
                health_monitor.update_broker_status(broker_name, False, reason=reason, error_code=error_code)
                print(f"[SYNC] ⚠️ {broker_name} marked DISCONNECTED: {error_code} - {reason}")
            except Exception:
                pass
            
            return {'positions': [], 'pending_orders': [], '_fetch_error': True}
    
    async def _fetch_account_info(self, broker_name: str, broker_instance) -> Dict[str, Any]:
        """Fetch account info for health monitor cache (buying power, balance, etc)."""
        try:
            account_info = {}
            
            if broker_name in ('Webull', 'WEBULL_PAPER'):
                if hasattr(broker_instance, 'get_account_info'):
                    raw = await broker_instance.get_account_info()
                    if raw:
                        print(f"[SYNC] {broker_name} account info keys: {list(raw.keys())[:10]}")
                        _raw_bp = float(raw.get('buying_power', 0) or 0)
                        _raw_sc = float(raw.get('settled_cash', 0) or 0)
                        if _raw_sc == 0 and _raw_bp > 0:
                            _raw_sc = _raw_bp
                        account_info = {
                            'portfolio_value': raw.get('portfolio_value', 0),
                            'buying_power': _raw_bp,
                            'cash': raw.get('cash', 0),
                            'options_buying_power': raw.get('options_buying_power', 0),
                            'settled_cash': _raw_sc,
                            'unsettled_cash': raw.get('unsettled_cash', 0),
                            'account_type': raw.get('account_type', 'Unknown'),
                            'account_id': raw.get('account_id')
                        }
                        print(f"[SYNC] Webull account info: buying_power=${account_info.get('buying_power')}, settled=${account_info.get('settled_cash')}, options_bp=${account_info.get('options_buying_power')}, portfolio=${account_info.get('portfolio_value')}")
                    else:
                        print(f"[SYNC] Webull get_account_info returned None/empty")
            
            elif broker_name.startswith('ALPACA'):
                if hasattr(broker_instance, 'get_account_info'):
                    raw = await broker_instance.get_account_info()
                    if raw:
                        account_info = {
                            'portfolio_value': float(raw.get('portfolio_value', 0) or 0),
                            'buying_power': float(raw.get('buying_power', 0) or 0),
                            'cash': float(raw.get('cash', 0) or 0),
                            'options_buying_power': float(raw.get('options_buying_power', 0) or raw.get('buying_power', 0) or 0),
                            'settled_cash': float(raw.get('settled_cash', 0) or 0),
                            'unsettled_cash': float(raw.get('unsettled_cash', 0) or 0),
                            'account_id': raw.get('account_id', None)
                        }
            
            elif broker_name == 'SCHWAB':
                if hasattr(broker_instance, 'get_account_info'):
                    raw = await broker_instance.get_account_info()
                    if raw:
                        account_info = {
                            'portfolio_value': float(raw.get('portfolio_value', 0) or 0),
                            'buying_power': float(raw.get('buying_power', 0) or 0),
                            'cash': float(raw.get('cash', 0) or 0),
                            'options_buying_power': float(raw.get('options_buying_power', 0) or raw.get('buying_power', 0) or 0),
                            'settled_cash': float(raw.get('settled_cash', 0) or 0),
                            'unsettled_cash': float(raw.get('unsettled_cash', 0) or 0),
                            'cashAvailableForTrading': float(raw.get('cashAvailableForTrading', 0) or 0),
                            'availableFunds': float(raw.get('availableFunds', 0) or 0),
                            'account_id': raw.get('account_id', ''),
                            'account_type': raw.get('account_type', '')
                        }
                        print(f"[SYNC] Schwab account info: buying_power=${account_info.get('buying_power')}, settled=${account_info.get('settled_cash')}, portfolio=${account_info.get('portfolio_value')}")
            
            elif broker_name == 'ROBINHOOD':
                if hasattr(broker_instance, 'get_account_info'):
                    raw = await broker_instance.get_account_info()
                    if raw:
                        account_info = {
                            'portfolio_value': float(raw.get('portfolio_value', 0) or 0),
                            'buying_power': float(raw.get('buying_power', 0) or 0),
                            'options_buying_power': float(raw.get('options_buying_power', 0) or raw.get('buying_power', 0) or 0),
                            'settled_cash': float(raw.get('settled_cash', 0) or 0),
                            'unsettled_cash': float(raw.get('unsettled_cash', 0) or 0),
                            'margin_buying_power': float(raw.get('margin_buying_power', 0) or 0)
                        }
            
            elif broker_name.startswith('IBKR'):
                if hasattr(broker_instance, 'get_account_info'):
                    raw = await broker_instance.get_account_info()
                    if raw:
                        account_info = {
                            'portfolio_value': float(raw.get('portfolio_value', 0) or 0),
                            'buying_power': float(raw.get('buying_power', 0) or 0),
                            'options_buying_power': float(raw.get('options_buying_power', 0) or 0),
                            'cash': float(raw.get('cash', 0) or 0)
                        }
            
            elif broker_name.startswith('TASTYTRADE'):
                if hasattr(broker_instance, 'get_account_balances'):
                    raw = await broker_instance.get_account_balances()
                    if raw:
                        account_info = {
                            'portfolio_value': float(raw.get('portfolio_value', 0) or 0),
                            'buying_power': float(raw.get('buying_power', 0) or raw.get('equity_buying_power', 0) or 0),
                            'option_buying_power': float(raw.get('options_buying_power', 0) or raw.get('derivative_buying_power', 0) or 0),
                            'cash_balance': float(raw.get('cash', 0) or raw.get('cash_balance', 0) or 0)
                        }
                        try:
                            from src.services.tastytrade_data_hub import get_tastytrade_data_hub
                            tt_hub = get_tastytrade_data_hub()
                            if tt_hub:
                                tt_hub.update_account_info(account_info)
                        except Exception:
                            pass
            
            elif broker_name == 'TRADING212':
                if hasattr(broker_instance, 'get_account_info'):
                    raw = await broker_instance.get_account_info()
                    if raw:
                        account_info = {
                            'portfolio_value': float(raw.get('portfolio_value', 0) or 0),
                            'buying_power': float(raw.get('buying_power', 0) or 0),
                            'cash': float(raw.get('cash', 0) or 0),
                            'invested': float(raw.get('invested', 0) or 0),
                            'ppl': float(raw.get('ppl', 0) or 0),
                        }
            
            elif broker_name == 'ZERODHA':
                if hasattr(broker_instance, 'margins'):
                    raw = broker_instance.margins()
                    if raw and 'equity' in raw:
                        eq = raw['equity']
                        account_info = {
                            'available_margin': float(eq.get('available', {}).get('live_balance', 0) or 0),
                            'net': float(eq.get('net', 0) or 0)
                        }
            
            elif broker_name == 'UPSTOX':
                if hasattr(broker_instance, 'get_fund_and_margin'):
                    raw = await broker_instance.get_fund_and_margin()
                    if raw and 'data' in raw:
                        account_info = {
                            'available_margin': float(raw['data'].get('available_margin', 0) or 0),
                            'used_margin': float(raw['data'].get('used_margin', 0) or 0)
                        }
            
            elif broker_name == 'DHAN':
                if hasattr(broker_instance, 'get_fund_limits'):
                    raw = await broker_instance.get_fund_limits()
                    if raw and 'data' in raw:
                        account_info = {
                            'availableBalance': float(raw['data'].get('availableBalance', 0) or 0),
                            'allocatedBalance': float(raw['data'].get('allocatedBalance', 0) or 0)
                        }

            elif broker_name.startswith('WEBULL_OFFICIAL'):
                if hasattr(broker_instance, 'get_account_info'):
                    raw = await broker_instance.get_account_info()
                    if raw:
                        account_info = {
                            'portfolio_value': float(raw.get('portfolio_value', 0) or 0),
                            'buying_power': float(raw.get('buying_power', 0) or 0),
                            'option_buying_power': float(raw.get('option_buying_power', 0) or raw.get('buying_power', 0) or 0),
                            'options_buying_power': float(raw.get('option_buying_power', 0) or raw.get('buying_power', 0) or 0),
                            'cash_balance': float(raw.get('cash_balance', 0) or 0),
                            'settled_cash': float(raw.get('settled_cash', 0) or 0),
                            'unsettled_cash': float(raw.get('unsettled_cash', 0) or 0),
                            'market_value': float(raw.get('market_value', 0) or 0),
                            'account_type': raw.get('account_type', ''),
                            'account_id': raw.get('account_id', ''),
                        }
                        print(f"[SYNC] {broker_name} account info: buying_power=${account_info['buying_power']:.2f}, option_bp=${account_info['option_buying_power']:.2f}, settled=${account_info['settled_cash']:.2f}, portfolio=${account_info['portfolio_value']:.2f}")

            return account_info
            
        except Exception as e:
            print(f"[SYNC] Error fetching account info for {broker_name}: {e}")
            return {}
    
    async def _reconcile_trades(self, broker_name: str, normalized_data: Dict[str, Any], broker_instance=None):
        """
        Reconcile normalized broker data with database trades

        Three-stage process:
        0. Pre-enrich option positions with missing metadata from DB trades
        1. Update existing database trades (PENDING→OPEN→CLOSED)
        2. Import broker-only positions as synthetic trades
        """
        
        self._pre_enrich_option_positions(broker_name, normalized_data)
        
        # Stage 1: Update existing database trades
        await self._update_existing_trades(broker_name, normalized_data)
        
        # Stage 2: Import manual trades (positions not tracked by bot)
        await self._import_manual_trades(broker_name, normalized_data)
    
    def _pre_enrich_option_positions(self, broker_name: str, normalized_data: Dict[str, Any]):
        """Pre-enrich option positions that have missing strike/expiry/call_put.
        
        Runs BEFORE Stage 1 so that _update_existing_trades builds correct
        position keys and doesn't falsely cancel tracked trades due to
        key mismatches (e.g. SPY_stock vs SPY_677.0_2026-03-10_P).
        """
        positions = normalized_data.get('positions', [])
        if not positions:
            return
        
        recovery_trades = None
        
        for position in positions:
            asset_type = position.get('asset_type', 'stock')
            if asset_type != 'option':
                continue
            
            strike = position.get('strike')
            expiry = position.get('expiry')
            call_put = position.get('call_put')
            
            if strike and float(strike) != 0 and expiry and call_put:
                continue
            
            symbol = (position.get('symbol') or '').upper()
            if not symbol:
                continue
            
            if recovery_trades is None:
                recovery_trades = self.db.get_trades(status='OPEN', limit=500) + self.db.get_trades(status='PENDING', limit=500)
            
            for t in recovery_trades:
                if (t.get('symbol', '').upper() == symbol and
                    self._is_broker_match(broker_name, t.get('broker', '')) and
                    t.get('direction', '').upper() == 'BTO'):
                    t_strike = t.get('strike')
                    t_expiry = t.get('expiry')
                    t_cp = t.get('call_put') or t.get('opt_type')
                    if t_strike and float(t_strike) > 0 and t_expiry and t_cp:
                        position['strike'] = t_strike
                        position['expiry'] = t_expiry
                        position['call_put'] = t_cp
                        print(f"[SYNC] 💡 Pre-enriched {symbol} option metadata from trade #{t.get('id')}: strike={t_strike}, expiry={t_expiry}, cp={t_cp}")
                        break

    def _is_broker_match(self, broker_name: str, trade_broker_raw: str) -> bool:
        """Check if a trade's broker matches the sync broker name.
        
        Uses exact matching to prevent cross-contamination between
        similar broker names (e.g., 'webull' vs 'webull_paper').
        """
        broker_lower = broker_name.lower()
        trade_broker = (trade_broker_raw or '').lower()
        
        if not trade_broker:
            return False
        
        if broker_lower == 'webull':
            return trade_broker == 'webull'
        elif broker_lower == 'webull_paper':
            return trade_broker == 'webull_paper'
        elif broker_lower == 'alpaca_paper':
            return trade_broker in ('alpaca_paper', 'alpaca')
        elif broker_lower == 'schwab':
            return 'schwab' in trade_broker
        elif broker_lower.startswith('ibkr'):
            return 'ibkr' in trade_broker
        elif broker_lower.startswith('tastytrade'):
            return 'tastytrade' in trade_broker
        elif broker_lower == 'robinhood':
            return trade_broker == 'robinhood'
        elif broker_lower == 'zerodha':
            return trade_broker == 'zerodha'
        elif broker_lower == 'upstox':
            return trade_broker == 'upstox'
        elif broker_lower == 'dhanq':
            return trade_broker == 'dhanq'
        elif broker_lower.startswith('webull_official'):
            # Match 'webull_official', 'webull_official_live', 'webull_official_paper'
            # DB may store any of these variants depending on how the order was routed
            return trade_broker.startswith('webull_official')
        else:
            return trade_broker == broker_lower

    async def _update_existing_trades(self, broker_name: str, normalized_data: Dict[str, Any]):
        """Update status of existing database trades based on broker state"""
        
        open_trades = self.db.get_trades(status='OPEN', limit=5000)
        closing_trades = self.db.get_trades(status='CLOSING', limit=500)
        pending_trades = self.db.get_trades(status='PENDING', limit=5000)
        db_trades = open_trades + closing_trades + pending_trades
        
        active_trades = []
        for t in db_trades:
            trade_broker = t.get('broker') or ''
            if self._is_broker_match(broker_name, trade_broker):
                active_trades.append(t)
        
        if not active_trades:
            print(f"[SYNC] No active {broker_name} trades to update")
            return
        
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
        
        if positions_by_key:
            print(f"[SYNC] {broker_name} position keys: {list(positions_by_key.keys())}")
        
        pending_by_order_id = {o['broker_order_id']: o for o in normalized_data.get('pending_orders', []) if o.get('broker_order_id')}
        pending_by_symbol = {o['symbol']: o for o in normalized_data.get('pending_orders', [])}
        
        has_pending_trades = any(t['status'] == 'PENDING' for t in active_trades)
        has_open_trades = any(t['status'] in ('OPEN', 'CLOSING') for t in active_trades)
        broker_returned_empty = not positions_by_key and not pending_by_order_id and not pending_by_symbol
        fetch_error = normalized_data.get('_fetch_error', False)
        
        if not hasattr(self, '_consecutive_empty_counts'):
            self._consecutive_empty_counts = {}
        
        if broker_returned_empty and (has_pending_trades or has_open_trades):
            if fetch_error:
                print(f"[SYNC] ⚠️ {broker_name} returned empty data with fetch error — skipping trade closures to avoid false state changes")
                active_trades = [t for t in active_trades if t['status'] not in ('PENDING', 'OPEN')]
                self._consecutive_empty_counts[broker_name] = 0
            else:
                self._consecutive_empty_counts[broker_name] = self._consecutive_empty_counts.get(broker_name, 0) + 1
                empty_count = self._consecutive_empty_counts[broker_name]
                if not hasattr(self, '_first_empty_times'):
                    self._first_empty_times = {}
                if broker_name not in self._first_empty_times:
                    import time as _empty_time
                    self._first_empty_times[broker_name] = _empty_time.time()
                import time as _empty_time2
                _empty_elapsed = _empty_time2.time() - self._first_empty_times.get(broker_name, _empty_time2.time())
                # IBKR reconnect storms can produce many consecutive empties — require more cycles + time
                if broker_name.startswith('IBKR'):
                    required_consecutive = 6
                    required_time_seconds = 120
                else:
                    required_consecutive = 3
                    required_time_seconds = 30
                if empty_count < required_consecutive or _empty_elapsed < required_time_seconds:
                    statuses_deferred = []
                    if has_pending_trades:
                        statuses_deferred.append('PENDING')
                    if has_open_trades:
                        statuses_deferred.append('OPEN')
                    print(f"[SYNC] ⚠️ {broker_name} returned empty with {'+'.join(statuses_deferred)} trades (empty_count={empty_count}/{required_consecutive}, elapsed={_empty_elapsed:.0f}s/{required_time_seconds}s) — deferring closures for re-verify")
                    active_trades = [t for t in active_trades if t['status'] not in statuses_deferred]
                else:
                    print(f"[SYNC] {broker_name} returned empty for {empty_count} consecutive cycles ({_empty_elapsed:.0f}s) — proceeding with trade reconciliation")
        else:
            if broker_name in self._consecutive_empty_counts:
                self._consecutive_empty_counts[broker_name] = 0
            if hasattr(self, '_first_empty_times') and broker_name in self._first_empty_times:
                del self._first_empty_times[broker_name]
        
        # Pre-pass: count how many OPEN trades share each position key
        # When multiple BTO trades exist for the same symbol (e.g. runner + new entry),
        # broker reports a combined position — we must NOT overwrite individual trade qty/price
        from collections import Counter
        _open_trades_per_key = Counter()
        for t in active_trades:
            if t['status'] == 'OPEN':
                k = self._build_position_key(
                    t['symbol'], t.get('asset_type', 'stock'),
                    t.get('strike'), t.get('expiry'), t.get('call_put'))
                _open_trades_per_key[k] += 1
        
        for trade in active_trades:
            symbol = trade['symbol']
            trade_id = trade['id']
            current_status = trade['status']
            db_order_id = trade.get('order_id')
            
            trade_key = self._build_position_key(
                symbol,
                trade.get('asset_type', 'stock'),
                trade.get('strike'),
                trade.get('expiry'),
                trade.get('call_put')
            )
            
            if current_status == 'PENDING':
                in_pending = db_order_id in pending_by_order_id if db_order_id else symbol in pending_by_symbol
                print(f"[SYNC] Trade #{trade_id} ({symbol}) key='{trade_key}' status={current_status} order_id={db_order_id} in_positions={trade_key in positions_by_key} in_pending={in_pending}")
            
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
                    fill_price = position['avg_price']
                    fill_qty = position['quantity']
                    print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) filled: PENDING → OPEN @ ${fill_price}")
                    self.db.update_trade(
                        trade_id,
                        status='OPEN',
                        executed_price=fill_price,
                        current_price=position.get('current_price'),
                        quantity=fill_qty,
                        executed_at=datetime.now().isoformat()
                    )

                    # Recalculate SL/PT prices using actual fill price instead of trigger price
                    # Only for small slippage — skip if fill diverges >50% (e.g. range entries)
                    try:
                        intended = float(trade.get('intended_price') or 0)
                        old_sl = float(trade.get('stop_loss_price') or 0)
                        old_pt = float(trade.get('profit_target_price') or 0)
                        _divergence = abs(fill_price - intended) / intended if intended > 0 else 0
                        if intended > 0 and fill_price > 0 and abs(fill_price - intended) > 0.0001 and _divergence <= 0.50:
                            _recalc_dec = 4 if fill_price < 1.0 else 2
                            recalc_updates = {}
                            if old_sl > 0:
                                _stored_sl_pct = float(trade.get('stop_loss_pct') or 0)
                                sl_pct = _stored_sl_pct / 100 if _stored_sl_pct > 0 else (intended - old_sl) / intended
                                new_sl = round(fill_price * (1 - sl_pct), _recalc_dec)
                                recalc_updates['stop_loss_price'] = new_sl
                                print(f"[SYNC] 🔧 Recalculated SL for #{trade_id}: ${old_sl} → ${new_sl} (fill ${fill_price} vs trigger ${intended})")
                            if old_pt > 0:
                                pt_pct = (old_pt - intended) / intended
                                new_pt = round(fill_price * (1 + pt_pct), _recalc_dec)
                                recalc_updates['profit_target_price'] = new_pt
                                print(f"[SYNC] 🔧 Recalculated PT for #{trade_id}: ${old_pt} → ${new_pt}")
                            if recalc_updates:
                                self.db.update_trade(trade_id, **recalc_updates)
                        elif _divergence > 0.50 and intended > 0:
                            print(f"[SYNC] ⏭ Skipping SL/PT rescale for #{trade_id}: fill ${fill_price} diverges {_divergence:.0%} from signal ${intended} (range entry?)")
                    except Exception as recalc_err:
                        print(f"[SYNC] Warning: SL/PT recalculation failed: {recalc_err}")

                    try:
                        from gui_app.discord_notifier import notify_order_filled
                        notify_order_filled(
                            symbol=symbol,
                            action=trade.get('action', 'BTO'),
                            broker=broker_name,
                            quantity=int(fill_qty),
                            price=float(fill_price),
                            strike=trade.get('strike'),
                            expiry=trade.get('expiry'),
                            opt_type=trade.get('call_put') or trade.get('opt_type')
                        )
                    except Exception as notify_err:
                        print(f"[SYNC] Warning: Could not send fill notification: {notify_err}")
                    
                    # For NDX→QQQ conversions: Update the lot's open_price with actual fill price
                    # This ensures P&L is calculated using QQQ fill price, not NDX signal price
                    # Use trade_id linkage for precise lot identification (prevents cross-lot contamination)
                    try:
                        from gui_app.database import get_connection
                        conn = get_connection()
                        cursor = conn.cursor()
                        trade_id = trade.get('id')
                        trade_symbol = trade.get('symbol', '')
                        trade_strike = trade.get('strike')
                        
                        lot_row = None
                        
                        # Priority 1: Use trade_id linkage (most precise)
                        if trade_id:
                            cursor.execute('''
                                SELECT id, executed_symbol, executed_strike, open_price
                                FROM signal_lots
                                WHERE trade_id = ?
                                AND status = 'OPEN'
                                LIMIT 1
                            ''', (trade_id,))
                            lot_row = cursor.fetchone()
                            if lot_row:
                                print(f"[SYNC] Found lot #{lot_row['id']} via trade_id={trade_id}")
                        
                        if not lot_row and trade_symbol and trade_strike:
                            _legacy_ch = trade.get('channel_id')
                            if _legacy_ch and _legacy_ch != 'UNKNOWN':
                                cursor.execute('''
                                    SELECT id, executed_symbol, executed_strike, open_price
                                    FROM signal_lots
                                    WHERE executed_symbol = ?
                                    AND executed_strike = ?
                                    AND status = 'OPEN'
                                    AND trade_id IS NULL
                                    AND channel_id = ?
                                    ORDER BY id DESC
                                    LIMIT 1
                                ''', (trade_symbol, float(trade_strike), str(_legacy_ch)))
                                lot_row = cursor.fetchone()
                                if lot_row:
                                    print(f"[SYNC] Found lot #{lot_row['id']} via symbol/strike+channel fallback (legacy)")
                            else:
                                print(f"[SYNC] ⚠️ Skipping legacy lot fallback for {trade_symbol}: no channel_id")
                        
                        if not lot_row and trade_id:
                            cursor.execute('''
                                SELECT id, executed_symbol, executed_strike, open_price
                                FROM signal_lots
                                WHERE trade_id = ?
                                LIMIT 1
                            ''', (trade_id,))
                            lot_row = cursor.fetchone()
                            if lot_row:
                                print(f"[SYNC] Found lot #{lot_row['id']} via trade_id={trade_id} (any status)")
                        
                        if lot_row:
                            old_price = lot_row['open_price']
                            cursor.execute('''
                                UPDATE signal_lots SET open_price = ? WHERE id = ?
                            ''', (fill_price, lot_row['id']))
                            conn.commit()
                            print(f"[SYNC] ✓ Updated lot #{lot_row['id']} open_price: ${old_price} → ${fill_price} (NDX→QQQ fill)")
                            try:
                                from gui_app.database import update_lot_entry_fill
                                update_lot_entry_fill(
                                    lot_id=lot_row['id'],
                                    fill_price=fill_price,
                                    broker=broker_name,
                                    order_id=db_order_id,
                                    filled_at=datetime.now().isoformat()
                                )
                            except Exception as fill_err:
                                print(f"[SYNC] ⚠️ Could not record entry fill for lot #{lot_row['id']}: {fill_err}")
                    except Exception as lot_err:
                        print(f"[SYNC] Warning: Could not update lot price: {lot_err}")
                
                # Update OPEN trade with current position data (UPDATE CURRENT PRICE, QUANTITY, AND P&L!)
                elif current_status == 'OPEN':
                    if hasattr(self, '_consecutive_empty_counts'):
                        _empty_key = f"{broker_name}_{trade_id}"
                        self._consecutive_empty_counts.pop(_empty_key, None)
                    current_price = position.get('current_price')
                    broker_quantity = float(position.get('quantity', 0))
                    db_quantity = float(trade.get('quantity') or 0)
                    
                    db_entry_price = float(trade.get('executed_price') or trade.get('price') or 0)
                    broker_avg_cost = float(position.get('avg_price', 0) or position.get('avg_cost', 0) or 0)
                    asset_type = trade.get('asset_type', 'option')
                    
                    # When multiple OPEN trades share the same position key (e.g. runner + new entry),
                    # broker reports combined qty/avg_price — skip qty/price sync to avoid corrupting individual trades
                    multi_trade_position = _open_trades_per_key.get(trade_key, 0) > 1
                    if multi_trade_position:
                        entry_price = db_entry_price
                    else:
                        entry_price = broker_avg_cost if broker_avg_cost > 0 else db_entry_price
                    
                    # Use trade's own quantity when multiple trades share the position (broker qty is combined)
                    if multi_trade_position:
                        quantity = abs(db_quantity)
                    else:
                        quantity = abs(broker_quantity) if broker_quantity != 0 else abs(db_quantity)
                    
                    # Calculate P&L using per-trade entry price and quantity
                    if entry_price > 0 and current_price and current_price > 0:
                        multiplier = 100 if asset_type == 'option' else 1
                        pnl = (current_price - entry_price) * quantity * multiplier
                        pnl_percent = ((current_price - entry_price) / entry_price) * 100
                    elif current_price and current_price > 0:
                        pnl = 0
                        pnl_percent = 0
                    else:
                        # current_price is 0 or None — DO NOT overwrite P&L
                        # Keep previous DB values intact (prevents $0 flicker)
                        pnl = None
                        pnl_percent = None

                    # Build update dict — only write fields that have real data
                    update_fields = {}
                    if pnl is not None:
                        update_fields['pnl'] = pnl
                        update_fields['pnl_percent'] = pnl_percent
                    if current_price and current_price > 0:
                        update_fields['current_price'] = current_price
                    
                    if multi_trade_position:
                        print(f"[SYNC] Trade #{trade_id} ({symbol}) multi-trade position — skipping qty/price sync (DB qty={db_quantity}, entry=${db_entry_price:.4f})")
                    else:
                        # Sync entry price from broker if it changed (user averaged up/down)
                        if broker_avg_cost > 0 and abs(broker_avg_cost - db_entry_price) > 0.0001:
                            update_fields['executed_price'] = broker_avg_cost
                            update_fields['intended_price'] = broker_avg_cost
                            print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) entry price synced: DB=${db_entry_price:.4f} → Broker=${broker_avg_cost:.4f}")
                        
                        # Sync quantity from broker — but never overwrite original_quantity
                        if broker_quantity > 0 and abs(broker_quantity - db_quantity) > 0.001:
                            if broker_quantity > db_quantity and trade.get('channel_id'):
                                print(f"[SYNC] ⚠️ Trade #{trade_id} ({symbol}) qty INCREASED: DB={db_quantity} → Broker={broker_quantity} "
                                      f"— possible manual add-on to signal trade (channel={trade.get('channel_id')}). "
                                      f"Risk settings from channel will apply to combined position.")
                            update_fields['quantity'] = broker_quantity
                            original_qty = trade.get('original_quantity')
                            if not original_qty and broker_quantity < db_quantity:
                                update_fields['original_quantity'] = int(db_quantity)
                                print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) qty synced: DB={db_quantity} → Broker={broker_quantity} (preserved original_quantity={int(db_quantity)})")
                            else:
                                print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) qty synced: DB={db_quantity} → Broker={broker_quantity} (original_quantity={original_qty or 'same'})")
                            
                            # Create lot_closures for PNL tracking when qty decreased (partial exit)
                            if broker_quantity < db_quantity:
                                sold_qty = int(db_quantity - broker_quantity)
                                discord_channel_id = trade.get('channel_id')
                                if discord_channel_id and sold_qty > 0:
                                    try:
                                        from gui_app.database import get_channel_by_discord_id
                                        channel_row = get_channel_by_discord_id(str(discord_channel_id))
                                        if channel_row:
                                            exit_price = float(current_price) if current_price and float(current_price) > 0 else 0
                                            matcher = get_matcher()
                                            lot_signal = {
                                                'action': 'STC',
                                                'symbol': symbol,
                                                'asset': asset_type,
                                                'qty': sold_qty,
                                                'price': exit_price,
                                                'strike': trade.get('strike'),
                                                'expiry': trade.get('expiry'),
                                                'opt_type': trade.get('call_put'),
                                                'channel_id': discord_channel_id,
                                                'db_channel_id': channel_row['id'],
                                                'received_at': datetime.now(),
                                                'exit_reason': 'BROKER_CLOSED',
                                                'broker': broker_name
                                            }
                                            lot_result = matcher.process_signal(lot_signal)
                                            if lot_result:
                                                print(f"[SYNC] ✓ Created {len(lot_result)} lot_closure(s) for partial exit PNL tracking ({sold_qty} shares @ ${exit_price:.2f})")
                                    except Exception as le:
                                        print(f"[SYNC] ⚠️ Partial exit lot_closure warning: {le}")
                    
                    # Update all fields
                    self.db.update_trade(trade_id, **update_fields)
            
            # CRITICAL: Trade not in pending or positions = order cancelled or position closed
            # Brokers remove closed positions entirely, so absence means it's gone
            else:
                if current_status == 'PENDING':
                    # PAPER_SIM orders are simulated and won't appear in broker pending list
                    order_id_val = trade.get('order_id', '') or ''
                    if order_id_val.startswith('PAPER_SIM'):
                        print(f"[SYNC] Trade #{trade_id} ({symbol}) is PAPER_SIM order - auto-filling")
                        self.db.update_trade(
                            trade_id,
                            status='OPEN',
                            executed_price=trade.get('price') or trade.get('executed_price'),
                            executed_at=datetime.now().isoformat()
                        )
                        try:
                            from gui_app.discord_notifier import notify_order_filled
                            notify_order_filled(
                                symbol=symbol,
                                action=trade.get('action', 'BTO'),
                                broker=broker_name,
                                quantity=int(trade.get('quantity', 1)),
                                price=float(trade.get('price') or trade.get('executed_price') or 0),
                                strike=trade.get('strike'),
                                expiry=trade.get('expiry'),
                                opt_type=trade.get('call_put') or trade.get('opt_type')
                            )
                        except Exception:
                            pass
                        continue
                    
                    trade_created_at = trade.get('created_at') or trade.get('executed_at')
                    grace_period_seconds = 30
                    
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
                    
                    try:
                        from gui_app.database import get_trade_by_id
                        fresh_trade = get_trade_by_id(trade_id)
                    except Exception:
                        fresh_trade = None
                    if fresh_trade and fresh_trade.get('status') == 'CLOSED':
                        print(f"[SYNC] Trade #{trade_id} ({symbol}) already CLOSED (likely user-cancelled), skipping")
                        continue
                    
                    order_id_str = trade.get('order_id', '') or ''
                    _broker_inst = None
                    _bn_upper = broker_name.upper()
                    schwab_desc = ''

                    if _bn_upper == 'SCHWAB':
                        _broker_inst = getattr(self.broker_manager, 'schwab_broker', None)
                        if _broker_inst and order_id_str and hasattr(_broker_inst, 'get_order_status'):
                            try:
                                status_result = await asyncio.wait_for(
                                    _broker_inst.get_order_status(order_id_str),
                                    timeout=10.0
                                )
                                if status_result:
                                    live_status = status_result.get('status', 'unknown')
                                    schwab_desc = status_result.get('status_description', '')
                                    print(f"[SYNC] 🔍 Schwab re-verify order #{order_id_str}: status={live_status}" + (f" desc={schwab_desc}" if schwab_desc else ""))
                                    if live_status in ('pending', 'working', 'partial', 'pending_activation'):
                                        print(f"[SYNC] ✓ Order #{order_id_str} still {live_status} on Schwab — skipping cancellation (stale pending list)")
                                        continue
                                    elif live_status in ('cancelled', 'rejected', 'expired', 'not_found'):
                                        print(f"[SYNC] ✓ Order #{order_id_str} confirmed {live_status} on Schwab — proceeding to close")
                                        if schwab_desc:
                                            cancel_reason = f"order_{live_status}: {schwab_desc}"
                                        else:
                                            cancel_reason = f"order_{live_status}"
                                    elif live_status == 'filled':
                                        fill_price = status_result.get('average_price', 0)
                                        fill_qty = status_result.get('filled_quantity', trade.get('quantity', 1))
                                        print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) FILLED on re-verify: {fill_qty}x @ ${fill_price}")
                                        self.db.update_trade(
                                            trade_id,
                                            status='OPEN',
                                            executed_price=fill_price,
                                            quantity=fill_qty,
                                            executed_at=datetime.now().isoformat()
                                        )
                                        try:
                                            intended = float(trade.get('intended_price') or 0)
                                            old_sl = float(trade.get('stop_loss_price') or 0)
                                            old_pt = float(trade.get('profit_target_price') or 0)
                                            _divergence = abs(fill_price - intended) / intended if intended > 0 else 0
                                            if intended > 0 and fill_price > 0 and abs(fill_price - intended) > 0.0001 and _divergence <= 0.50:
                                                _recalc_dec = 4 if fill_price < 1.0 else 2
                                                recalc_updates = {}
                                                if old_sl > 0:
                                                    _stored_sl_pct = float(trade.get('stop_loss_pct') or 0)
                                                    sl_pct = _stored_sl_pct / 100 if _stored_sl_pct > 0 else (intended - old_sl) / intended
                                                    new_sl = round(fill_price * (1 - sl_pct), _recalc_dec)
                                                    recalc_updates['stop_loss_price'] = new_sl
                                                    print(f"[SYNC] 🔧 Recalculated SL for #{trade_id}: ${old_sl} → ${new_sl} (fill ${fill_price} vs trigger ${intended})")
                                                if old_pt > 0:
                                                    pt_pct = (old_pt - intended) / intended
                                                    new_pt = round(fill_price * (1 + pt_pct), _recalc_dec)
                                                    recalc_updates['profit_target_price'] = new_pt
                                                    print(f"[SYNC] 🔧 Recalculated PT for #{trade_id}: ${old_pt} → ${new_pt}")
                                                if recalc_updates:
                                                    self.db.update_trade(trade_id, **recalc_updates)
                                            elif _divergence > 0.50 and intended > 0:
                                                print(f"[SYNC] ⏭ Skipping SL/PT rescale for #{trade_id}: fill ${fill_price} diverges {_divergence:.0%} from signal ${intended} (range entry?)")
                                        except Exception as recalc_err:
                                            print(f"[SYNC] Warning: SL/PT recalculation failed: {recalc_err}")
                                        try:
                                            from gui_app.discord_notifier import notify_order_filled
                                            notify_order_filled(
                                                symbol=symbol, action=trade.get('action', 'BTO'),
                                                broker=broker_name, quantity=int(fill_qty),
                                                price=float(fill_price), strike=trade.get('strike'),
                                                expiry=trade.get('expiry'),
                                                opt_type=trade.get('call_put') or trade.get('opt_type')
                                            )
                                        except Exception:
                                            pass
                                        continue
                                else:
                                    if not hasattr(self, '_schwab_reverify_fails'):
                                        self._schwab_reverify_fails = {}
                                    fails = self._schwab_reverify_fails.get(order_id_str, 0) + 1
                                    self._schwab_reverify_fails[order_id_str] = fails
                                    if fails < 3:
                                        print(f"[SYNC] ⚠️ Schwab re-verify returned None for order #{order_id_str} (attempt {fails}/3) — deferring")
                                        continue
                                    print(f"[SYNC] ✓ Schwab re-verify None x3 for order #{order_id_str} — order gone, proceeding to close")
                                    self._schwab_reverify_fails.pop(order_id_str, None)
                            except (asyncio.TimeoutError, asyncio.CancelledError):
                                print(f"[SYNC] ⚠️ Schwab re-verify timed out for order #{order_id_str} — deferring cancellation")
                                continue
                            except Exception as rv_err:
                                print(f"[SYNC] ⚠️ Schwab re-verify error: {rv_err} — deferring cancellation")
                                continue

                    if _bn_upper in ('WEBULL', 'WEBULL_PAPER'):
                        if _bn_upper == 'WEBULL_PAPER':
                            _broker_inst = getattr(self.broker_manager, 'webull_paper_broker', None) or getattr(self.broker_manager, 'webull_broker', None)
                        else:
                            _broker_inst = getattr(self.broker_manager, 'webull_broker', None) or getattr(self.broker_manager, 'webull_paper_broker', None)

                    if _bn_upper.startswith('WEBULL_OFFICIAL') and order_id_str:
                        _wo_broker = getattr(self.broker_manager, 'webull_official_broker', None)
                        if _wo_broker and hasattr(_wo_broker, 'get_order_status'):
                            try:
                                wo_status = await asyncio.wait_for(
                                    _wo_broker.get_order_status(order_id_str),
                                    timeout=10.0
                                )
                                if wo_status:
                                    wo_live = (wo_status.get('status') or 'unknown').upper()
                                    print(f"[SYNC] 🔍 WEBULL_OFFICIAL re-verify order #{order_id_str}: status={wo_live}")
                                    if wo_live in ('WORKING', 'PARTIAL', 'PENDING_NEW', 'SUBMITTING', 'SUBMITTED'):
                                        print(f"[SYNC] ✓ Order #{order_id_str} still {wo_live} on Webull Official — skipping cancellation")
                                        continue
                                    elif wo_live == 'FILLED':
                                        fill_price = float(wo_status.get('avg_fill_price') or wo_status.get('average_price') or 0)
                                        fill_qty = int(wo_status.get('filled_quantity') or trade.get('quantity', 1))
                                        print(f"[SYNC] ✓ WEBULL_OFFICIAL order #{order_id_str} FILLED: {fill_qty}x @ ${fill_price} — PENDING → OPEN")
                                        self.db.update_trade(trade_id, status='OPEN',
                                                             executed_price=fill_price if fill_price > 0 else None,
                                                             quantity=fill_qty if fill_qty > 0 else None,
                                                             executed_at=datetime.now().isoformat())
                                        continue
                                    # cancelled/rejected/not_found → fall through to close
                                else:
                                    if not hasattr(self, '_wo_reverify_fails'):
                                        self._wo_reverify_fails = {}
                                    fails = self._wo_reverify_fails.get(order_id_str, 0) + 1
                                    self._wo_reverify_fails[order_id_str] = fails
                                    if fails < 3:
                                        print(f"[SYNC] ⚠️ WEBULL_OFFICIAL re-verify returned None for #{order_id_str} ({fails}/3) — deferring")
                                        continue
                                    self._wo_reverify_fails.pop(order_id_str, None)
                            except (asyncio.TimeoutError, asyncio.CancelledError):
                                print(f"[SYNC] ⚠️ WEBULL_OFFICIAL re-verify timed out for #{order_id_str} — deferring")
                                continue
                            except Exception as wo_rv_err:
                                print(f"[SYNC] ⚠️ WEBULL_OFFICIAL re-verify error: {wo_rv_err} — deferring")
                                continue

                    cancel_reason = 'order_cancelled_or_rejected'
                    if _bn_upper == 'SCHWAB' and schwab_desc:
                        cancel_reason = f"order_cancelled_or_rejected: {schwab_desc}"

                    _wb_client = getattr(_broker_inst, 'wb', None) or getattr(_broker_inst, '_client', None)
                    if order_id_str and _broker_inst and _wb_client:
                        try:
                            _broker_inst._data_hub and _broker_inst._data_hub.invalidate_orders()
                            fresh_pending = await _broker_inst.get_pending_orders()
                            fresh_ids = {str(o.get('order_id', '')) for o in (fresh_pending or [])}
                            if order_id_str in fresh_ids:
                                print(f"[SYNC] ✓ Webull re-verify: order #{order_id_str} found in fresh pending — skipping cancellation")
                                continue
                            print(f"[SYNC] 🔍 Webull re-verify: order #{order_id_str} NOT in fresh pending ({len(fresh_ids)} orders)")
                        except Exception as rv_err:
                            print(f"[SYNC] ⚠️ Webull re-verify error: {rv_err} — deferring cancellation")
                            continue

                        _skip_cancel = False
                        try:
                            all_orders_raw = await asyncio.to_thread(
                                _wb_client.get_history_orders, count=20
                            )
                            for raw_order in (all_orders_raw or []):
                                if str(raw_order.get('orderId', '')) == order_id_str:
                                    raw_status = raw_order.get('status', '')
                                    raw_msg = raw_order.get('statusStr', '') or raw_order.get('msg', '') or ''
                                    cancel_reason_detail = raw_order.get('cancelReason', '') or raw_order.get('rejectReason', '') or ''
                                    print(f"[SYNC] 🔍 Order #{order_id_str} history: status={raw_status}, statusStr={raw_msg}, reason={cancel_reason_detail}")
                                    if raw_status.upper() in ('WORKING', 'PENDING', 'SUBMITTED'):
                                        print(f"[SYNC] ✓ Order #{order_id_str} still {raw_status} in history — skipping cancellation")
                                        _skip_cancel = True
                                    elif raw_status.upper() == 'FILLED':
                                        fill_price = float(raw_order.get('avgFilledPrice', 0) or raw_order.get('filledPrice', 0) or raw_order.get('lmtPrice', 0) or 0)
                                        fill_qty = int(raw_order.get('filledQuantity', 0) or raw_order.get('totalQuantity', 0) or trade.get('quantity', 1))
                                        print(f"[SYNC] ✓ Webull order #{order_id_str} FILLED: {fill_qty}x @ ${fill_price:.4f} — promoting PENDING → OPEN")
                                        self.db.update_trade(
                                            trade_id,
                                            status='OPEN',
                                            executed_price=fill_price if fill_price > 0 else None,
                                            quantity=fill_qty if fill_qty > 0 else None,
                                            executed_at=datetime.now().isoformat()
                                        )
                                        _skip_cancel = True
                                    elif cancel_reason_detail:
                                        cancel_reason = f"broker_rejected: {cancel_reason_detail}"
                                    elif raw_msg:
                                        cancel_reason = f"broker_rejected: {raw_msg}"
                                    break
                        except Exception as hist_err:
                            print(f"[SYNC] ⚠️ Could not query order history for rejection reason: {hist_err}")
                        if _skip_cancel:
                            continue

                    try:
                        _chaser = getattr(self.broker_manager, 'order_chaser', None) or getattr(self.broker_manager, '_order_chaser', None)
                        if not _chaser:
                            from src.services.unfilled_order_chaser import get_order_chaser as _get_oc
                            _chaser = _get_oc()
                        if _chaser and hasattr(_chaser, 'is_chasing_symbol'):
                            if _chaser.is_chasing_symbol(symbol, broker_name):
                                print(f"[SYNC] ⚠️ ORDER CHASER GUARD: Trade #{trade_id} ({symbol}) "
                                      f"— order chaser is actively replacing this entry order, skipping cancellation")
                                continue
                    except Exception as _chaser_err:
                        print(f"[SYNC] ⚠️ Order chaser check error: {_chaser_err}")

                    if hasattr(self, '_risk_manager') and self._risk_manager:
                        if hasattr(self._risk_manager, 'cache') and self._risk_manager.cache:
                            _risk_found = self._find_risk_cache_entry(
                                self._risk_manager.cache, broker_name, symbol, trade)
                            if _risk_found:
                                print(f"[SYNC] ⚠️ RISK GUARD: Trade #{trade_id} ({symbol}) "
                                      f"still in risk cache with price ${_risk_found:.2f} "
                                      f"— skipping cancellation despite broker returning empty positions")
                                continue

                    print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) not in pending orders: PENDING → CLOSED (cancelled) reason={cancel_reason}")
                    update_kwargs = dict(
                        status='CLOSED',
                        closed_at=datetime.now().isoformat(),
                        close_reason=cancel_reason
                    )
                    if schwab_desc:
                        update_kwargs['rejection_reason'] = schwab_desc
                    self.db.update_trade(trade_id, **update_kwargs)

                    trade_direction = (trade.get('direction') or '').upper()
                    if trade_direction == 'BTO':
                        try:
                            from src.services.daily_pnl_limit_service import get_daily_pnl_service
                            get_daily_pnl_service().decrement_bto_trade(broker_name, reason=f"order rejected #{trade_id} {symbol}")
                        except Exception as dec_err:
                            print(f"[SYNC] Warning: Could not decrement trade count: {dec_err}")
                    
                    # Send cancellation notification (not failure - order was cancelled, not rejected)
                    try:
                        from gui_app.discord_notifier import send_cancel_notification
                        opt_detail = ""
                        is_option = False
                        if trade.get('strike'):
                            is_option = True
                            opt_type_str = (trade.get('call_put') or trade.get('opt_type') or '').upper()
                            opt_detail = f" ${trade['strike']}{opt_type_str}"
                            if trade.get('expiry'):
                                opt_detail += f" {trade['expiry']}"
                        send_cancel_notification(
                            symbol=symbol,
                            quantity=int(trade.get('quantity', 1)),
                            price=float(trade.get('price') or trade.get('executed_price') or 0),
                            is_option=is_option,
                            order_id=trade.get('order_id', ''),
                            broker=broker_name
                        )
                        print(f"[SYNC] ✓ Sent cancel notification for trade #{trade_id} ({symbol}) on {broker_name}")
                    except Exception as notify_err:
                        print(f"[SYNC] Warning: Could not send cancel notification: {notify_err}")
                    
                    # Cancel associated lot to prevent orphaned P&L entries
                    try:
                        from gui_app.database import cancel_lot
                        if cancel_lot(trade_id=trade_id, reason='ORDER_CANCELLED'):
                            print(f"[SYNC] ✓ Cancelled lot linked to trade #{trade_id}")
                    except Exception as lot_err:
                        print(f"[SYNC] Warning: Could not cancel lot: {lot_err}")
                    
                    try:
                        if hasattr(self, '_risk_manager') and self._risk_manager:
                            pos_key = f"{broker_name}_{symbol}_{trade.get('asset_type', 'stock')}"
                            if hasattr(self._risk_manager, 'cache') and self._risk_manager.cache:
                                if pos_key in self._risk_manager.cache._cache:
                                    self._risk_manager.cache.remove(pos_key)
                                    print(f"[SYNC] ✓ Removed {pos_key} from position cache (order cancelled)")
                        
                        # Remove from position ledger if exists
                        try:
                            from src.services.position_ledger import get_position_ledger
                            ledger = get_position_ledger()
                            # Find and close position by trade info
                            message_id = trade.get('message_id')
                            if message_id and hasattr(ledger, 'close_by_message_id'):
                                ledger.close_by_message_id(message_id, exit_reason='ORDER_CANCELLED')
                        except Exception:
                            pass
                    except Exception as cache_err:
                        print(f"[SYNC] Warning: Could not clean up cache: {cache_err}")
                elif current_status in ('OPEN', 'CLOSING'):
                    order_id_val = trade.get('order_id', '') or ''
                    if order_id_val.startswith('PAPER_SIM'):
                        continue

                    _trade_age_guard = False
                    if current_status == 'OPEN':
                        try:
                            _exec_at = trade.get('executed_at') or trade.get('created_at') or ''
                            if _exec_at:
                                _exec_dt = datetime.fromisoformat(_exec_at.replace('Z', '+00:00'))
                                _age_minutes = (datetime.now() - _exec_dt.replace(tzinfo=None)).total_seconds() / 60
                                if _age_minutes < 2:
                                    print(f"[SYNC] ⚠️ RECENT TRADE GUARD: Trade #{trade_id} ({symbol}) opened {_age_minutes:.1f}min ago — skipping closure (protect <2min trades)")
                                    _trade_age_guard = True
                        except Exception as _age_err:
                            print(f"[SYNC] ⚠️ Trade age check error: {_age_err}")
                    if _trade_age_guard:
                        continue

                    if not hasattr(self, '_consecutive_empty_counts'):
                        self._consecutive_empty_counts = {}
                    _empty_key = f"{broker_name}_{trade_id}"
                    self._consecutive_empty_counts[_empty_key] = self._consecutive_empty_counts.get(_empty_key, 0) + 1
                    # CLOSING = risk engine already submitted STC; broker just needs to confirm gone
                    if current_status == 'CLOSING':
                        _REQUIRED_CONFIRMATIONS = 2
                    elif broker_name.startswith('IBKR'):
                        _REQUIRED_CONFIRMATIONS = 8
                    else:
                        _REQUIRED_CONFIRMATIONS = 4
                    if self._consecutive_empty_counts[_empty_key] < _REQUIRED_CONFIRMATIONS:
                        print(f"[SYNC] ⏳ Trade #{trade_id} ({symbol}) not in {broker_name} positions ({self._consecutive_empty_counts[_empty_key]}/{_REQUIRED_CONFIRMATIONS} confirmations) status={current_status}")
                        continue

                    # Extract bracket order IDs from risk cache BEFORE cleanup
                    _bracket_order_ids = {}
                    if hasattr(self, '_risk_manager') and self._risk_manager:
                        if hasattr(self._risk_manager, 'cache') and self._risk_manager.cache:
                            _cache_entry = self._get_risk_cache_entry(
                                self._risk_manager.cache, broker_name, symbol, trade)
                            if _cache_entry:
                                _bracket_order_ids = {
                                    'oco_id': getattr(_cache_entry, 'broker_oco_order_id', None),
                                    'sl_id': getattr(_cache_entry, 'broker_stop_order_id', None),
                                    'pt_id': getattr(_cache_entry, 'broker_pt_order_id', None),
                                }
                                pos_key = f"{broker_name}_{symbol}_{trade.get('asset_type', 'stock')}"
                                try:
                                    self._risk_manager.cache.remove(pos_key)
                                    print(f"[SYNC] 🧹 Cleared stale risk cache for {pos_key} (broker confirmed closed after {_REQUIRED_CONFIRMATIONS} cycles)")
                                except Exception:
                                    pass

                    if hasattr(self, '_consecutive_empty_counts'):
                        self._consecutive_empty_counts.pop(f"{broker_name}_{trade_id}", None)
                    print(f"[SYNC] ✓ Trade #{trade_id} ({symbol}) not in positions: OPEN → CLOSED (broker closed)")

                    entry_price = float(trade.get('executed_price') or 0)
                    quantity = float(trade.get('quantity') or 0)
                    asset_type = trade.get('asset_type', 'option')
                    discord_channel_id = trade.get('channel_id')

                    exit_price = float(trade.get('current_price') or 0)
                    exit_price_source = 'last_sync'
                    exit_order_id = None
                    exit_filled_at = None
                    pnl = float(trade.get('pnl') or 0)
                    pnl_percent = float(trade.get('pnl_percent') or 0)

                    try:
                        # Priority 1: Query broker for actual exit fill from bracket orders
                        if exit_price_source == 'last_sync' and _bracket_order_ids:
                            try:
                                _exit_fill = await self._query_broker_exit_fill(
                                    broker_name, broker_instance, symbol, _bracket_order_ids, trade)
                                if _exit_fill:
                                    exit_price = _exit_fill['price']
                                    exit_order_id = _exit_fill.get('order_id')
                                    exit_filled_at = _exit_fill.get('filled_at')
                                    exit_price_source = 'broker_fill'
                                    print(f"[SYNC] ✓ Trade #{trade_id} exit fill from broker: ${exit_price:.4f} order={exit_order_id} (actual bracket fill)")
                            except Exception as bf_err:
                                print(f"[SYNC] ⚠️ Broker exit fill query: {bf_err}")

                        # Priority 2: Query broker directly by BTO order_id for child order fills
                        if exit_price_source == 'last_sync' and broker_name.upper() == 'SCHWAB' and broker_instance:
                            try:
                                _bto_order_id = trade.get('order_id', '')
                                if _bto_order_id:
                                    _exit_fill = await self._query_broker_exit_fill(
                                        broker_name, broker_instance, symbol,
                                        {'oco_id': None, 'sl_id': None, 'pt_id': None},
                                        trade, bto_order_id=_bto_order_id)
                                    if _exit_fill:
                                        exit_price = _exit_fill['price']
                                        exit_order_id = _exit_fill.get('order_id')
                                        exit_filled_at = _exit_fill.get('filled_at')
                                        exit_price_source = 'broker_fill'
                                        print(f"[SYNC] ✓ Trade #{trade_id} exit fill from broker (by BTO order): ${exit_price:.4f}")
                            except Exception as bf_err2:
                                print(f"[SYNC] ⚠️ Broker exit fill query (BTO): {bf_err2}")

                        # Priority 3: Check execution_closures table
                        if exit_price_source == 'last_sync':
                            try:
                                from gui_app.database import get_connection as _get_conn
                                _conn = _get_conn()
                                _cur = _conn.cursor()
                                _fill_query = '''
                                    SELECT ec.fill_price, ec.filled_at FROM execution_closures ec
                                    JOIN execution_lots el ON ec.execution_lot_id = el.id
                                    WHERE UPPER(el.symbol) = UPPER(?) AND UPPER(el.broker) = UPPER(?)
                                '''
                                _fill_params = [symbol, broker_name]
                                if asset_type == 'option' and trade.get('strike'):
                                    _fill_query += ' AND el.strike = ?'
                                    _fill_params.append(trade['strike'])
                                if trade.get('expiry'):
                                    _fill_query += ' AND el.expiry = ?'
                                    _fill_params.append(trade['expiry'])
                                _fill_query += ' ORDER BY ec.filled_at DESC LIMIT 1'
                                _cur.execute(_fill_query, _fill_params)
                                _fill_row = _cur.fetchone()
                                if _fill_row and _fill_row['fill_price'] and float(_fill_row['fill_price']) > 0:
                                    exit_price = float(_fill_row['fill_price'])
                                    exit_price_source = 'execution_closure'
                                    print(f"[SYNC] ✓ Trade #{trade_id} exit price from execution_closures: ${exit_price:.4f}")
                            except Exception as fill_lookup_err:
                                print(f"[SYNC] ⚠️ Execution closure lookup: {fill_lookup_err}")

                        # Priority 4: Check filled_orders linked by trade_id
                        if exit_price_source == 'last_sync':
                            try:
                                from gui_app.database import get_connection as _get_conn4
                                _conn4 = _get_conn4()
                                _cur4 = _conn4.cursor()
                                _cur4.execute('''
                                    SELECT filled_price, filled_at FROM filled_orders
                                    WHERE trade_id = ? AND UPPER(broker) = UPPER(?)
                                      AND UPPER(side) IN ('SELL', 'STC', 'SELL_TO_CLOSE')
                                      AND filled_price > 0
                                    ORDER BY filled_at DESC LIMIT 1
                                ''', (trade_id, broker_name))
                                _fo_row = _cur4.fetchone()
                                if _fo_row and _fo_row['filled_price'] and float(_fo_row['filled_price']) > 0:
                                    exit_price = float(_fo_row['filled_price'])
                                    exit_price_source = 'filled_orders_tid'
                                    print(f"[SYNC] ✓ Trade #{trade_id} exit price from filled_orders by trade_id: ${exit_price:.4f}")
                            except Exception:
                                pass

                        # Priority 5: Check filled_orders by symbol+time
                        if exit_price_source == 'last_sync':
                            try:
                                _trade_opened_at = trade.get('executed_at') or trade.get('created_at') or ''
                                if _trade_opened_at:
                                    _fo_query = '''
                                        SELECT filled_price, filled_at FROM filled_orders
                                        WHERE UPPER(symbol) = UPPER(?) AND UPPER(broker) = UPPER(?)
                                          AND UPPER(side) IN ('SELL', 'STC', 'SELL_TO_CLOSE')
                                          AND filled_at >= ?
                                    '''
                                    _fo_params = [symbol, broker_name, _trade_opened_at]
                                    if asset_type == 'option' and trade.get('strike'):
                                        _fo_query += ' AND strike = ?'
                                        _fo_params.append(trade['strike'])
                                    _fo_query += ' ORDER BY filled_at DESC LIMIT 1'
                                    _cur.execute(_fo_query, _fo_params)
                                    _fo_row = _cur.fetchone()
                                    if _fo_row and _fo_row['filled_price'] and float(_fo_row['filled_price']) > 0:
                                        exit_price = float(_fo_row['filled_price'])
                                        exit_price_source = 'filled_orders'
                                        print(f"[SYNC] ✓ Trade #{trade_id} exit price from filled_orders: ${exit_price:.4f}")
                            except Exception as fo_err:
                                print(f"[SYNC] ⚠️ Filled orders lookup: {fo_err}")

                        original_quantity = int(trade.get('original_quantity') or quantity)
                        multiplier = 100 if asset_type == 'option' else 1

                        try:
                            from gui_app.database import get_connection as _pnl_conn
                            _pc = _pnl_conn()
                            _pcur = _pc.cursor()
                            _pcur.execute('''
                                SELECT id, quantity, executed_price FROM trades
                                WHERE origin_trade_id = ? AND direction = 'STC'
                                  AND status IN ('CLOSED', 'FILLED')
                                  AND executed_price IS NOT NULL AND executed_price > 0
                            ''', (trade_id,))
                            linked_stcs = _pcur.fetchall()

                            if linked_stcs:
                                total_pnl = 0
                                total_closed_qty = 0
                                for stc_row in linked_stcs:
                                    sq = int(stc_row['quantity'] or 0)
                                    sp = float(stc_row['executed_price'] or 0)
                                    total_pnl += (sp - entry_price) * sq * multiplier
                                    total_closed_qty += sq

                                unclosed_qty = original_quantity - total_closed_qty
                                if unclosed_qty > 0 and exit_price > 0:
                                    total_pnl += (exit_price - entry_price) * unclosed_qty * multiplier
                                    total_closed_qty += unclosed_qty

                                pnl = round(total_pnl, 2)
                                if total_closed_qty > 0 and entry_price > 0:
                                    weighted_exit = (sum(float(s['executed_price'] or 0) * int(s['quantity'] or 0) for s in linked_stcs) + (exit_price * unclosed_qty if unclosed_qty > 0 else 0)) / total_closed_qty
                                    pnl_percent = ((weighted_exit - entry_price) / entry_price) * 100
                                print(f"[SYNC] ✓ Trade #{trade_id} PNL from {len(linked_stcs)} linked STCs: ${pnl:+.2f} ({pnl_percent:+.2f}%) [{total_closed_qty}/{original_quantity} shares]")
                            elif exit_price_source != 'last_sync' or (pnl == 0 and entry_price > 0 and exit_price > 0):
                                pnl = (exit_price - entry_price) * original_quantity * multiplier
                                pnl_percent = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
                        except Exception as pnl_err:
                            print(f"[SYNC] ⚠️ Linked STC PNL calc error: {pnl_err}")
                            try:
                                original_quantity = int(trade.get('original_quantity') or quantity)
                                multiplier = 100 if asset_type == 'option' else 1
                                if exit_price_source != 'last_sync' or (pnl == 0 and entry_price > 0 and exit_price > 0):
                                    pnl = (exit_price - entry_price) * original_quantity * multiplier
                                    pnl_percent = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
                            except Exception:
                                pass

                    except Exception as close_calc_err:
                        print(f"[SYNC] ⚠️ Exit price/PNL calc failed for trade #{trade_id} ({symbol}): {close_calc_err}")
                        import traceback
                        traceback.print_exc()

                    try:
                        self.db.update_trade(
                            trade_id,
                            status='CLOSED',
                            closed_at=datetime.now().isoformat(),
                            current_price=exit_price,
                            pnl=pnl,
                            pnl_percent=pnl_percent,
                            close_reason='broker_closed_position'
                        )
                    except Exception as db_err:
                        print(f"[SYNC] ❌ CRITICAL: Failed to close trade #{trade_id} ({symbol}) in DB: {db_err}")
                        import traceback
                        traceback.print_exc()

                    try:
                        if hasattr(self, '_risk_manager') and self._risk_manager:
                            pos_key = f"{broker_name}_{symbol}_{trade.get('asset_type', 'stock')}"
                            if hasattr(self._risk_manager, 'cache') and self._risk_manager.cache:
                                if pos_key in self._risk_manager.cache._cache:
                                    self._risk_manager.cache.remove(pos_key)
                                    print(f"[SYNC] ✓ Cleaned position cache: {pos_key} (trade closed)")
                    except Exception as cache_err:
                        print(f"[SYNC] Warning: Could not clean cache on close: {cache_err}")

                    # Create lot_closure FIRST, then update with exit fill data
                    _new_closure_ids = []
                    if discord_channel_id and quantity > 0:
                        try:
                            from gui_app.database import get_channel_by_discord_id
                            channel_row = get_channel_by_discord_id(str(discord_channel_id))

                            if channel_row:
                                db_channel_id = channel_row['id']

                                matcher = get_matcher()
                                lot_signal = {
                                    'action': 'STC',
                                    'symbol': symbol,
                                    'asset': asset_type,
                                    'qty': quantity,
                                    'price': exit_price,
                                    'strike': trade.get('strike'),
                                    'expiry': trade.get('expiry'),
                                    'opt_type': trade.get('call_put'),
                                    'channel_id': discord_channel_id,
                                    'db_channel_id': db_channel_id,
                                    'received_at': datetime.now(),
                                    'exit_reason': 'BROKER_CLOSED',
                                    'broker': broker_name
                                }
                                lot_result = matcher.process_signal(lot_signal)
                                if lot_result:
                                    _new_closure_ids = [lr.get('closure_id') for lr in lot_result if lr.get('closure_id')]
                                    print(f"[SYNC] ✓ Created {len(lot_result)} lot_closure(s) for PNL tracking (exit=${exit_price})")
                            else:
                                print(f"[SYNC] ⚠️ Channel {discord_channel_id} not found in database")
                        except Exception as le:
                            print(f"[SYNC] ⚠️ Lot matching warning: {le}")

                    # NOW update lot_closures with exit fill data (after creation)
                    if exit_price > 0 and exit_price_source != 'last_sync':
                        try:
                            from gui_app.database import get_connection as _get_fill_conn, update_closure_exit_fill
                            _fill_conn = _get_fill_conn()
                            _fill_cur = _fill_conn.cursor()
                            _exit_src = exit_price_source
                            _exit_ts = exit_filled_at or datetime.now().isoformat()

                            if _new_closure_ids:
                                for _cid in _new_closure_ids:
                                    update_closure_exit_fill(
                                        _cid, exit_price, broker_name,
                                        order_id=exit_order_id, filled_at=_exit_ts,
                                        exit_source=_exit_src)
                                    print(f"[SYNC] ✓ Updated lot_closure #{_cid} exit fill: ${exit_price:.4f} via {broker_name} order={exit_order_id} (src={_exit_src})")
                            else:
                                _fill_query = '''
                                    SELECT lc.id, lc.closed_qty, lc.close_price
                                    FROM lot_closures lc
                                    JOIN signal_lots sl ON lc.lot_id = sl.id
                                    JOIN trades t ON sl.trade_id = t.id
                                    WHERE UPPER(sl.symbol) = UPPER(?) AND lc.exit_fill_price IS NULL
                                      AND UPPER(t.broker) = UPPER(?)
                                '''
                                _fill_params = [symbol, broker_name]
                                if discord_channel_id and str(discord_channel_id) != 'UNKNOWN':
                                    _fill_query += ' AND sl.channel_id = ?'
                                    _fill_params.append(str(discord_channel_id))
                                if asset_type == 'option' and trade.get('strike'):
                                    _fill_query += ' AND sl.strike = ?'
                                    _fill_params.append(str(trade['strike']))
                                if asset_type == 'option' and trade.get('expiry'):
                                    _fill_query += ' AND sl.expiry = ?'
                                    _fill_params.append(str(trade['expiry']))
                                _fill_query += ' ORDER BY ABS(lc.closed_qty - ?) ASC, lc.closed_at DESC LIMIT 1'
                                _fill_params.append(quantity)
                                _fill_cur.execute(_fill_query, _fill_params)
                                _best_closure = _fill_cur.fetchone()
                                if _best_closure:
                                    update_closure_exit_fill(
                                        _best_closure['id'], exit_price, broker_name,
                                        order_id=exit_order_id, filled_at=_exit_ts,
                                        exit_source=_exit_src)
                                    print(f"[SYNC] ✓ Updated lot_closure #{_best_closure['id']} exit fill: ${exit_price:.4f} via {broker_name} order={exit_order_id} (src={_exit_src})")
                        except Exception as fill_err:
                            print(f"[SYNC] ⚠️ Lot closure fill update warning: {fill_err}")
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

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize symbol for matching across brokers
        
        Handles broker-specific symbol variations:
        - SPXW -> SPX, NDXP -> NDX, RUTW -> RUT, DJXW -> DJX, VIXW -> VIX
        - XSP stays as XSP
        """
        if not symbol:
            return symbol
        from src.risk.risk_types import normalize_index_symbol
        return normalize_index_symbol(symbol.upper())

    def _build_position_key(self, symbol: str, asset_type: str, strike=None, expiry=None, call_put=None) -> str:
        """Build a normalized position key for matching between broker and database"""
        normalized_symbol = self._normalize_symbol(symbol)
        if asset_type == 'option' and strike and expiry and call_put:
            normalized_expiry = self._normalize_expiry(expiry)
            # Round strike to avoid float precision issues (0.5 increments for most options)
            normalized_strike = round(float(strike) * 2) / 2 if strike else 0
            return f"{normalized_symbol}_{normalized_strike}_{normalized_expiry}_{call_put}"
        else:
            return f"{normalized_symbol}_stock"
    
    async def _import_manual_trades(self, broker_name: str, normalized_data: Dict[str, Any]):
        """Import broker positions that aren't tracked in database as synthetic trades
        
        IMPORTANT: When importing, try to find the origin Discord trade and inherit its channel_id.
        This allows per-channel risk settings to work for positions that were opened via Discord signals.
        
        Also repairs orphaned trades (OPEN trades with no channel_id) by linking them to matching Discord signals.
        """
        
        broker_positions = normalized_data.get('positions', [])
        if not broker_positions:
            return
        
        # Get all tracked trades for this broker (handle case-insensitive broker names)
        # FIX: Include PENDING trades too - they may be awaiting fill confirmation
        all_db_trades_open = self.db.get_trades(status='OPEN', limit=1000)
        all_db_trades_pending = self.db.get_trades(status='PENDING', limit=1000)
        all_db_trades = all_db_trades_open + all_db_trades_pending
        
        orphaned_trades_by_key = {}
        for t in all_db_trades_open:
            if t.get('channel_id'):
                continue
            trade_broker = t.get('broker') or ''
            if self._is_broker_match(broker_name, trade_broker):
                key = self._build_position_key(
                    t['symbol'],
                    t.get('asset_type', 'stock'),
                    t.get('strike'),
                    t.get('expiry'),
                    t.get('call_put')
                )
                orphaned_trades_by_key[key] = t
        
        # Also get recently closed Discord trades to find origin channel_id for positions
        all_discord_trades = self.db.get_trades(limit=1000)  # Get all trades to find origins
        
        db_trades = []
        pending_trades_by_key = {}
        for t in all_db_trades:
            trade_broker = t.get('broker') or ''
            if self._is_broker_match(broker_name, trade_broker):
                db_trades.append(t)
                # Index PENDING trades by key for promotion lookup
                if t.get('status') == 'PENDING':
                    key = self._build_position_key(
                        t['symbol'],
                        t.get('asset_type', 'stock'),
                        t.get('strike'),
                        t.get('expiry'),
                        t.get('call_put')
                    )
                    pending_trades_by_key[key] = t
        
        # Build normalized keys for existing trades (both OPEN and PENDING)
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
        
        # Collect all trades with channel_id, sorted by recency (higher ID = more recent)
        # FIX: Include ANY trade with channel_id, not just those with source='discord'
        discord_trades_with_channel = [
            t for t in sorted(all_discord_trades, key=lambda x: x.get('id', 0), reverse=True)
            if t.get('channel_id')
        ]
        
        # Build broker_override lookup (needed for orphan recovery AND find_origin_channel)
        broker_to_channels = {}
        all_channels = []
        try:
            all_channels = self.db.get_channels()
            for ch in all_channels:
                ch_broker = (ch.get('broker_override') or '').lower().strip()
                if ch_broker:
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

        def _channel_has_broker_enabled(channel_id: str, target_broker: str) -> bool:
            """Check if a channel actually has this broker in its enabled_brokers list."""
            try:
                for ch in all_channels:
                    if str(ch.get('discord_channel_id')) == str(channel_id):
                        enabled_raw = ch.get('enabled_brokers') or '[]'
                        if isinstance(enabled_raw, str):
                            import json as _json_check
                            enabled_list = _json_check.loads(enabled_raw)
                        else:
                            enabled_list = enabled_raw
                        enabled_upper = [b.upper() for b in enabled_list]
                        return target_broker.upper() in enabled_upper
            except Exception:
                pass
            return False

        # RECOVERY: Try to repair orphaned trades by linking them to matching Discord signals or routing ledger
        # SAFETY: Only match against OPEN/PENDING trades — closed/historical trades should NOT
        # cause orphaned manual positions to inherit channel risk settings
        if orphaned_trades_by_key:
            print(f"[SYNC] 🔧 Found {len(orphaned_trades_by_key)} orphaned {broker_name} trades - attempting recovery...")
            for orphan_key, orphan_trade in orphaned_trades_by_key.items():
                recovered = False
                # Pass 1: Try to find a matching OPEN Discord trade with channel_id
                # SAFETY: Only inherit from trades with trusted sources (discord, signal)
                for discord_trade in discord_trades_with_channel:
                    if discord_trade.get('status', '').upper() not in ('OPEN', 'PENDING'):
                        continue
                    _dt_source = (discord_trade.get('source') or '').strip().lower()
                    if _dt_source in ('sync', 'risk_auto_import'):
                        continue
                    if discord_trade.get('id') == orphan_trade.get('id'):
                        continue
                    discord_key = self._build_position_key(
                        discord_trade['symbol'],
                        discord_trade.get('asset_type', 'stock'),
                        discord_trade.get('strike'),
                        discord_trade.get('expiry'),
                        discord_trade.get('call_put')
                    )
                    if discord_key == orphan_key and discord_trade.get('channel_id'):
                        if not self._is_broker_match(broker_name, discord_trade.get('broker', '')):
                            continue
                        ch_id = discord_trade.get('channel_id')
                        if not _channel_has_broker_enabled(ch_id, broker_name):
                            continue
                        orphan_id = orphan_trade.get('id')
                        print(f"[SYNC] ✓ Recovered orphan #{orphan_id} ({orphan_trade['symbol']}) → channel_id={ch_id} (from signal trade #{discord_trade.get('id')}, source='{_dt_source}')")
                        try:
                            self.db.update_trade(orphan_id, channel_id=ch_id, source='sync_discord', hide_in_ui=0)
                        except Exception as e:
                            print(f"[SYNC] ⚠️ Failed to update orphan #{orphan_id}: {e}")
                        recovered = True
                        break
                
                # Pass 2: Try signal routing position ledger
                if not recovered:
                    try:
                        from src.services.signal_routing_engine import get_position_ledger
                        ledger = get_position_ledger()
                        if ledger:
                            open_positions = ledger.get_open_positions()
                            sym = orphan_trade.get('symbol')
                            cp = orphan_trade.get('call_put')
                            st = orphan_trade.get('strike')
                            for lp in open_positions:
                                if (lp.symbol == sym and lp.option_type == cp and lp.remaining_qty > 0):
                                    lp_strike = float(lp.strike) if lp.strike else None
                                    pos_strike = float(st) if st else None
                                    if lp_strike == pos_strike and lp.routing_mapping_id:
                                        orphan_id = orphan_trade.get('id')
                                        print(f"[SYNC] ✓ Recovered orphan #{orphan_id} ({sym}) via routing ledger → mapping_id={lp.routing_mapping_id}, channel={lp.source_channel_id}")
                                        try:
                                            self.db.update_trade(
                                                orphan_id, 
                                                channel_id=lp.source_channel_id, 
                                                routing_mapping_id=lp.routing_mapping_id,
                                                source='sync_routing', 
                                                hide_in_ui=0
                                            )
                                        except Exception as e:
                                            print(f"[SYNC] ⚠️ Failed to update orphan #{orphan_id}: {e}")
                                        break
                    except Exception as e:
                        print(f"[SYNC] ⚠️ Routing ledger orphan recovery failed: {e}")
        
        def find_origin_channel(position: Dict) -> str:
            """Find the origin channel_id for a broker position using multi-pass matching.
            
            IMPORTANT: Only inherits channel_id if that channel actually has this broker
            in its enabled_brokers list. Prevents cross-broker channel attribution
            (e.g. WEBULL_PAPER positions inheriting phoenix channel which only uses WEBULL/SCHWAB).
            
            SAFETY: Only matches against OPEN trades from the same broker.
            Closed/historical trades are excluded to prevent manual positions from
            inheriting channel risk settings from unrelated past trades of the same symbol.
            """
            pos_key = self._build_position_key(
                position['symbol'],
                position.get('asset_type', 'stock'),
                position.get('strike'),
                position.get('expiry'),
                position.get('call_put')
            )
            
            # Pass 1: Match by order_id (most reliable) — ONLY OPEN/PENDING trades on same broker
            # SAFETY: Skip trades with untrusted sources to prevent channel contamination
            pos_order_id = position.get('position_id') or position.get('order_id')
            if pos_order_id:
                for t in discord_trades_with_channel:
                    if t.get('order_id') == pos_order_id:
                        if t.get('status', '').upper() not in ('OPEN', 'PENDING', 'PARTIAL'):
                            continue
                        if not self._is_broker_match(broker_name, t.get('broker', '')):
                            continue
                        _t_source = (t.get('source') or '').strip().lower()
                        if _t_source in ('sync', 'risk_auto_import'):
                            continue
                        ch_id = t.get('channel_id')
                        if ch_id and _channel_has_broker_enabled(ch_id, broker_name):
                            return ch_id
            
            # Pass 2: Match by position key — ONLY against OPEN trades on the same broker
            # This prevents manual positions from inheriting channel_id from closed/historical
            # trades that happened to have the same symbol (e.g. phoenix traded AHMA months ago,
            # user manually buys AHMA now — should NOT inherit phoenix risk settings)
            # SAFETY: Skip trades with untrusted sources to prevent channel contamination
            pos_qty = float(position.get('quantity', 0))
            matching_trades = []
            for t in discord_trades_with_channel:
                if t.get('status', '').upper() not in ('OPEN', 'PENDING'):
                    continue
                _t_source = (t.get('source') or '').strip().lower()
                if _t_source in ('sync', 'risk_auto_import'):
                    continue
                trade_key = self._build_position_key(
                    t['symbol'],
                    t.get('asset_type', 'stock'),
                    t.get('strike'),
                    t.get('expiry'),
                    t.get('call_put')
                )
                if trade_key == pos_key and self._is_broker_match(broker_name, t.get('broker', '')):
                    matching_trades.append(t)
            
            if matching_trades:
                for t in matching_trades:
                    trade_qty = float(t.get('quantity', 0))
                    ch_id = t.get('channel_id')
                    if trade_qty > 0 and abs(trade_qty - pos_qty) / trade_qty <= 0.2:
                        if ch_id and _channel_has_broker_enabled(ch_id, broker_name):
                            return ch_id
                
                for mt in matching_trades:
                    _mt_src = (mt.get('source') or '').strip().lower()
                    if _mt_src in ('discord', 'signal', 'sync_routing'):
                        mt_ch = mt.get('channel_id')
                        if mt_ch and _channel_has_broker_enabled(mt_ch, broker_name):
                            return mt_ch
            
            return None
        
        # Build set of position keys that already have pending SELL/STC orders
        # (exit order is in-flight; re-importing would create a new trade and trigger duplicate STC)
        pending_sell_pos_keys = set()
        for pending_order in normalized_data.get('pending_orders', []):
            order_type = (pending_order.get('order_type') or '').upper()
            if 'SELL' in order_type or order_type in ('STC', 'SELL_TO_CLOSE', 'STO'):
                p_sym = pending_order.get('symbol', '').upper()
                if p_sym:
                    pending_sell_pos_keys.add(p_sym)

        # Find positions not tracked by bot
        broker_positions = normalized_data.get('positions', [])
        
        for position in broker_positions:
            symbol = position['symbol']
            asset_type = position.get('asset_type', 'stock')
            strike = position.get('strike')
            expiry = position.get('expiry')
            call_put = position.get('call_put')
            
            if asset_type == 'option' and (not strike or float(strike) == 0 or not expiry or not call_put):
                try:
                    recovery_trades = self.db.get_trades(status='OPEN', limit=500) + self.db.get_trades(status='PENDING', limit=500)
                    recovery_candidates = []
                    for t in recovery_trades:
                        if (t.get('symbol', '').upper() == symbol.upper() and 
                            t.get('broker', '').upper() == broker_name.upper() and
                            t.get('direction', '').upper() == 'BTO'):
                            t_strike = t.get('strike')
                            t_expiry = t.get('expiry')
                            t_cp = t.get('call_put') or t.get('opt_type')
                            if t_strike and float(t_strike) > 0 and t_expiry and t_cp:
                                recovery_candidates.append(t)
                    open_candidates = [c for c in recovery_candidates if c.get('status') == 'OPEN']
                    if len(open_candidates) == 1:
                        recovery_candidates = open_candidates
                    if len(recovery_candidates) == 1:
                        t = recovery_candidates[0]
                        strike = t.get('strike')
                        expiry = t.get('expiry')
                        call_put = t.get('call_put') or t.get('opt_type')
                        position['strike'] = strike
                        position['expiry'] = expiry
                        position['call_put'] = call_put
                        print(f"[SYNC] 💡 Recovered option metadata for {symbol} from trade #{t.get('id')}: strike={strike}, expiry={expiry}, cp={call_put}")
                    elif len(recovery_candidates) > 1:
                        print(f"[SYNC] ⚠️ Option metadata recovery ambiguous: {len(recovery_candidates)} candidates for {symbol} on {broker_name} — skipping import")
                        continue
                except Exception as e:
                    print(f"[SYNC] ⚠️ Option metadata recovery failed: {e}")

            if asset_type == 'option' and (not strike or float(strike or 0) == 0 or not expiry or not call_put):
                print(f"[SYNC] ⚠️ Skipping import of {broker_name} option {symbol} — incomplete metadata (strike={strike}, expiry={expiry}, cp={call_put})")
                continue

            pos_key = self._build_position_key(symbol, asset_type, strike, expiry, call_put)
            
            if pos_key not in tracked_keys:
                # Check auto-import setting — skip external positions if disabled
                # FAIL-CLOSED: default is disabled, errors keep it disabled
                _auto_import_allowed = False
                try:
                    from gui_app.database import get_setting as _get_ai_setting
                    _ai_setting = _get_ai_setting('auto_import_external', 'false')
                    _auto_import_allowed = _ai_setting.lower() == 'true'
                except Exception as _ai_err:
                    print(f"[SYNC] ⚠️ Could not read auto_import_external setting: {_ai_err} — defaulting to disabled")
                
                if not _auto_import_allowed:
                    if not hasattr(self, '_sync_skip_logged'):
                        self._sync_skip_logged = set()
                    if pos_key not in self._sync_skip_logged:
                        self._sync_skip_logged.add(pos_key)
                        print(f"[SYNC] ⏭️ Skipping external position {symbol} ({asset_type}, key={pos_key}) — auto-import disabled")
                    continue
                
                # Skip if there's already a pending exit order for this symbol
                # (prevents re-import loop while limit STC orders are awaiting fill)
                if symbol.upper() in pending_sell_pos_keys:
                    print(f"[SYNC] ⏭️ Skipping import of {broker_name} {symbol} ({asset_type}) - pending exit order in flight")
                    continue
                
                # Skip positions with permanent failures (expired/invalid symbols)
                # (prevents re-import loop for positions that can never be closed via API)
                try:
                    full_pos_key = f"{broker_name}_{pos_key}"
                    full_pos_key_upper = full_pos_key.upper()
                    blocked = False
                    from src.risk.position_monitor import risk_manager_instance
                    if risk_manager_instance and hasattr(risk_manager_instance, '_permanent_failure_keys'):
                        pf_upper = {k.upper() for k in risk_manager_instance._permanent_failure_keys}
                        if full_pos_key_upper in pf_upper:
                            blocked = True
                    if not blocked:
                        from pathlib import Path
                        import json as _json
                        _pf_file = Path.cwd() / '.permanent_failures.json'
                        if _pf_file.exists():
                            with open(_pf_file, 'r') as _f:
                                _pf_keys = {k.upper() for k in _json.load(_f)}
                            if full_pos_key_upper in _pf_keys:
                                blocked = True
                    if blocked:
                        print(f"[SYNC] 🛑 Skipping blocklisted position: {full_pos_key}")
                        continue
                except Exception:
                    pass
                # Try to find origin channel_id using multi-pass matching
                origin_channel_id = find_origin_channel(position)
                
                routing_mapping_id = None
                if not origin_channel_id:
                    try:
                        from src.services.signal_routing_engine import get_position_ledger
                        ledger = get_position_ledger()
                        if ledger:
                            open_positions = ledger.get_open_positions()
                            for lp in open_positions:
                                if (lp.symbol == symbol and 
                                    lp.option_type == call_put and
                                    lp.remaining_qty > 0):
                                    lp_strike = float(lp.strike) if lp.strike else None
                                    pos_strike = float(strike) if strike else None
                                    if lp_strike == pos_strike and lp.routing_mapping_id:
                                        origin_channel_id = lp.source_channel_id
                                        routing_mapping_id = lp.routing_mapping_id
                                        print(f"[SYNC] ✓ Linked orphan to signal routing: {symbol} → mapping_id={routing_mapping_id}, channel={origin_channel_id}")
                                        break
                    except Exception as e:
                        print(f"[SYNC] ⚠️ Signal routing ledger lookup failed: {e}")
                
                if origin_channel_id:
                    print(f"[SYNC] 📥 Importing {broker_name} position: {symbol} ({asset_type}, qty={position['quantity']}, key={pos_key}) - inherited channel_id={origin_channel_id}")
                else:
                    print(f"[SYNC] 📥 Importing manual {broker_name} position: {symbol} ({asset_type}, qty={position['quantity']}, key={pos_key}) - no channel association")
                
                # Calculate initial P&L
                entry_price = float(position['avg_price'] or 0)
                current_price = float(position.get('current_price') or entry_price)
                quantity = abs(float(position['quantity'] or 1))
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
                elif 'IBKR' in broker_name.upper():
                    normalized_broker = 'IBKR'
                
                trade_data = {
                    'symbol': symbol,
                    'direction': 'BTO',
                    'quantity': abs(float(position['quantity'] or 0)),
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
                    'channel_id': origin_channel_id,
                    'order_id': position.get('position_id'),
                    'profit_target_percent': 0,
                    'stop_loss_percent': 0,
                    'trailing_stop_enabled': 0,
                    'source': 'sync_routing' if routing_mapping_id else ('sync' if not origin_channel_id else 'sync_discord'),
                    'hide_in_ui': 1 if not origin_channel_id else 0,
                    'routing_mapping_id': routing_mapping_id
                }
                
                # Add option-specific fields if it's an option
                if asset_type == 'option':
                    trade_data.update({
                        'strike': strike,
                        'expiry': expiry,
                        'call_put': call_put
                    })
                
                # DUPLICATE PREVENTION: Check by order_id (any status) then by symbol+broker (OPEN/PENDING)
                has_duplicate = False
                position_order_id = trade_data.get('order_id')
                trade_broker = trade_data['broker'].upper()

                # Check 1: order_id match across ALL statuses (deterministic, prevents re-import of closed trades)
                if position_order_id:
                    try:
                        from gui_app.database import get_connection as _dup_conn
                        _dc = _dup_conn()
                        _dcur = _dc.cursor()
                        _dcur.execute('SELECT id, status, broker FROM trades WHERE order_id = ? LIMIT 1', (position_order_id,))
                        _dup_row = _dcur.fetchone()
                        if _dup_row:
                            print(f"[SYNC] ⚠️ Skipping duplicate: {symbol} order_id={position_order_id} already exists (ID={_dup_row['id']}, status={_dup_row['status']})")
                            has_duplicate = True
                    except Exception:
                        pass

                # Check 2: Symbol + broker match (OPEN/PENDING only)
                # For IBKR, also treat 'IBKR', 'IBKR_LIVE', 'IBKR_PAPER' as the same broker
                # to prevent broker_sync from creating duplicate trades when the conditional-order
                # path already created an 'IBKR' record for the same position.
                def _ibkr_family(b: str) -> str:
                    return 'IBKR' if b.upper() in ('IBKR', 'IBKR_LIVE', 'IBKR_PAPER') else b.upper()

                if not has_duplicate:
                    existing_trades = self.db.get_trades(status='OPEN', limit=1000) + self.db.get_trades(status='PENDING', limit=500)
                    for existing in existing_trades:
                        existing_broker = (existing.get('broker') or '').upper()
                        brokers_match = (existing_broker == trade_broker or
                                         _ibkr_family(existing_broker) == _ibkr_family(trade_broker))
                        if existing['symbol'] == symbol and brokers_match:
                            if asset_type == 'stock':
                                print(f"[SYNC] ⚠️ Skipping duplicate: {symbol} already has OPEN/PENDING position (ID={existing['id']}, status={existing.get('status')}, broker={existing_broker} ≈ {trade_broker})")
                                has_duplicate = True
                                break
                            elif asset_type == 'option':
                                if (existing.get('strike') == strike and
                                    existing.get('call_put') == call_put):
                                    print(f"[SYNC] ⚠️ Skipping duplicate: {symbol} {strike}{call_put} already has OPEN/PENDING position (ID={existing['id']}, status={existing.get('status')})")
                                    has_duplicate = True
                                    break
                
                if not has_duplicate:
                    self.db.add_trade(trade_data)
                # Add to tracked keys so we don't import duplicates in same cycle
                tracked_keys.add(pos_key)
            else:
                # Position already tracked - check if it's a PENDING trade that needs promotion
                if pos_key in pending_trades_by_key:
                    pending_trade = pending_trades_by_key[pos_key]
                    trade_id = pending_trade.get('id')
                    fill_price = position['avg_price']
                    print(f"[SYNC] ✓ Promoting PENDING trade #{trade_id} ({symbol}) → OPEN via import_manual_trades")
                    self.db.update_trade(
                        trade_id,
                        status='OPEN',
                        executed_price=fill_price,
                        current_price=position.get('current_price'),
                        quantity=position['quantity'],
                        executed_at=datetime.now().isoformat()
                    )
                    try:
                        intended = float(pending_trade.get('intended_price') or 0)
                        old_sl = float(pending_trade.get('stop_loss_price') or 0)
                        old_pt = float(pending_trade.get('profit_target_price') or 0)
                        _divergence = abs(fill_price - intended) / intended if intended > 0 else 0
                        if intended > 0 and fill_price > 0 and abs(fill_price - intended) > 0.0001 and _divergence <= 0.50:
                            _recalc_dec = 4 if fill_price < 1.0 else 2
                            recalc_updates = {}
                            if old_sl > 0:
                                _stored_sl_pct = float(pending_trade.get('stop_loss_pct') or 0)
                                sl_pct = _stored_sl_pct / 100 if _stored_sl_pct > 0 else (intended - old_sl) / intended
                                new_sl = round(fill_price * (1 - sl_pct), _recalc_dec)
                                recalc_updates['stop_loss_price'] = new_sl
                                print(f"[SYNC] 🔧 Recalculated SL for #{trade_id}: ${old_sl} → ${new_sl} (fill ${fill_price} vs trigger ${intended})")
                            if old_pt > 0:
                                pt_pct = (old_pt - intended) / intended
                                new_pt = round(fill_price * (1 + pt_pct), _recalc_dec)
                                recalc_updates['profit_target_price'] = new_pt
                                print(f"[SYNC] 🔧 Recalculated PT for #{trade_id}: ${old_pt} → ${new_pt}")
                            if recalc_updates:
                                self.db.update_trade(trade_id, **recalc_updates)
                        elif _divergence > 0.50 and intended > 0:
                            print(f"[SYNC] ⏭ Skipping SL/PT rescale for #{trade_id}: fill ${fill_price} diverges {_divergence:.0%} from signal ${intended} (range entry?)")
                    except Exception as recalc_err:
                        print(f"[SYNC] Warning: SL/PT recalculation failed: {recalc_err}")
                    del pending_trades_by_key[pos_key]

    async def _sync_filled_orders(self, broker_name: str, broker_instance):
        """Sync filled orders from broker to database"""
        from gui_app.database import insert_filled_order, get_broker_sync_state, update_broker_sync_state
        
        try:
            print(f"[SYNC] Syncing filled orders from {broker_name}...")
            filled_orders = []
            
            # Fetch filled orders based on broker type
            if broker_name in ('Webull', 'WEBULL_PAPER'):
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
            elif broker_name in ('TRADING212', 'TRADING212_PAPER'):
                if hasattr(broker_instance, 'get_order_history'):
                    raw_orders = await broker_instance.get_order_history(count=50)
                    for order in raw_orders:
                        if order.get('status', '').upper() != 'FILLED':
                            continue
                        side = order.get('side', '').upper()
                        action = 'BUY' if side == 'BUY' else 'SELL'
                        filled_orders.append({
                            'order_id': order.get('order_id'),
                            'symbol': order.get('symbol'),
                            'quantity': int(float(order.get('filled_quantity', 0) or order.get('quantity', 0))),
                            'filled_price': float(order.get('fill_price', 0) or 0),
                            'action': action,
                            'filled_time': order.get('created_at', ''),
                            'asset_type': 'stock',
                        })
            elif broker_name.startswith('TASTYTRADE'):
                if hasattr(broker_instance, 'get_filled_orders'):
                    filled_orders = await asyncio.to_thread(broker_instance.get_filled_orders, 50)
            elif broker_name.startswith('IBKR'):
                if hasattr(broker_instance, 'ib') and broker_instance.ib.isConnected():
                    try:
                        ib = broker_instance.ib
                        # ib.trades() only has orders placed since last reqOpenOrders / session start.
                        # reqExecutionsAsync() fetches actual execution records from IB Gateway
                        # history and survives bot restarts — use both sources merged by order_id.
                        seen_order_ids = set()

                        def _ibkr_add_entry(order_id, action, contract, filled_qty, avg_price, filled_time):
                            if str(order_id) in seen_order_ids or filled_qty <= 0 or avg_price <= 0:
                                return
                            seen_order_ids.add(str(order_id))
                            side = 'BTO' if action == 'BUY' else 'STC'
                            asset_type = 'option' if contract.secType == 'OPT' else 'stock'
                            entry = {
                                'order_id': str(order_id),
                                'symbol': contract.symbol,
                                'quantity': filled_qty,
                                'filled_price': avg_price,
                                'action': side,
                                'filled_time': filled_time or datetime.now().isoformat(),
                                'asset_type': asset_type,
                            }
                            if asset_type == 'option':
                                expiry_raw = contract.lastTradeDateOrContractMonth or ''
                                if len(expiry_raw) == 8:
                                    entry['expiry'] = f"{expiry_raw[:4]}-{expiry_raw[4:6]}-{expiry_raw[6:8]}"
                                else:
                                    entry['expiry'] = expiry_raw
                                entry['strike'] = contract.strike
                                entry['direction'] = contract.right
                            filled_orders.append(entry)

                        # Primary: ib.trades() — in-memory, fast, covers current session
                        # Must call directly — asyncio.to_thread gives ib_insync a threadpool
                        # thread with no event loop, causing "no current event loop" crash that
                        # silently swallows the entire block including the orphan cleanup below.
                        for trade in ib.trades():
                            if not trade.orderStatus or trade.orderStatus.status != 'Filled':
                                continue
                            order = trade.order
                            contract = trade.contract
                            if not contract:
                                continue
                            filled_qty = int(trade.orderStatus.filled) if trade.orderStatus.filled else 0
                            avg_price = float(trade.orderStatus.avgFillPrice) if trade.orderStatus.avgFillPrice else 0
                            action = order.action if hasattr(order, 'action') else 'BUY'
                            ft = trade.fills[-1].time.isoformat() if trade.fills else None
                            _ibkr_add_entry(order.orderId, action, contract, filled_qty, avg_price, ft)

                        # Secondary: reqExecutionsAsync() — IB Gateway execution history,
                        # catches fills placed before this session started (e.g. after bot restart)
                        try:
                            execs = await ib.reqExecutionsAsync()
                            for exec_fill in execs:
                                ex = exec_fill.execution
                                contract = exec_fill.contract
                                if not contract or not ex:
                                    continue
                                action = ex.side.upper() if hasattr(ex, 'side') else 'BOT'
                                mapped_action = 'BUY' if action in ('BOT', 'BUY') else 'SELL'
                                filled_qty = int(ex.shares) if ex.shares else 0
                                avg_price = float(ex.price) if ex.price else 0
                                ft = ex.time if hasattr(ex, 'time') else None
                                _ibkr_add_entry(ex.orderId, mapped_action, contract, filled_qty, avg_price, str(ft) if ft else None)
                        except Exception as _exec_e:
                            print(f"[SYNC] IBKR reqExecutionsAsync warning: {_exec_e}")

                        # Reconcile orphaned PENDING orders: any order in the DB that is
                        # neither filled (seen_order_ids) nor still active in TWS (openTrades)
                        # must have been cancelled or expired at the exchange.
                        # Guard: skip if we reconnected recently — TWS replays open orders
                        # asynchronously after connectAsync(), so openTrades() may still be
                        # empty for a few seconds, causing live orders to be falsely cancelled.
                        try:
                            import time as _t
                            _reconnect_ts = getattr(broker_instance, '_last_reconnect_ts', 0.0)
                            if _t.time() - _reconnect_ts < 5.0:
                                print(f"[SYNC] IBKR skipping orphan cleanup — reconnected {_t.time() - _reconnect_ts:.1f}s ago, order replay in progress")
                            else:
                                active_ids = {str(t.order.orderId) for t in ib.openTrades()}
                                from gui_app.database import update_pending_order_status, get_connection as _gc
                                _conn = _gc()
                                _cur = _conn.cursor()
                                _cur.execute(
                                    "SELECT broker_order_id, symbol FROM pending_order_metadata "
                                    "WHERE broker LIKE 'IBKR%' AND status='PENDING'"
                                )
                                for _row in _cur.fetchall():
                                    _oid = str(_row['broker_order_id'])
                                    if _oid in seen_order_ids or _oid in active_ids:
                                        continue
                                    print(f"[SYNC] IBKR order {_oid} ({_row['symbol']}) gone from TWS — marking CANCELLED")
                                    update_pending_order_status('IBKR', _oid, 'CANCELLED')
                                    _cur.execute(
                                        "UPDATE execution_lots SET status='CANCELLED', remaining_qty=0 "
                                        "WHERE broker LIKE 'IBKR%' AND broker_order_id=? AND status='OPEN'",
                                        (_oid,)
                                    )
                                    _cur.execute(
                                        "UPDATE trades SET status='CANCELLED', "
                                        "close_reason='Order cancelled or expired at broker' "
                                        "WHERE broker LIKE 'IBKR%' AND order_id=? AND status='PENDING'",
                                        (_oid,)
                                    )
                                _conn.commit()
                        except Exception as _cleanup_err:
                            print(f"[SYNC] IBKR orphan cleanup error: {_cleanup_err}")

                    except Exception as e:
                        print(f"[SYNC] IBKR filled orders error: {e}")

            elif broker_name.startswith('WEBULL_OFFICIAL'):
                if hasattr(broker_instance, 'get_order_history'):
                    try:
                        raw_orders = await broker_instance.get_order_history() or []
                        for order in raw_orders:
                            status = (order.get('status') or '').upper()
                            if status != 'FILLED':
                                continue
                            side = (order.get('action') or '').upper()
                            if side in ('BUY', 'BUY_TO_OPEN'):
                                action = 'BTO'
                            elif side in ('SELL', 'SELL_TO_CLOSE'):
                                action = 'STC'
                            else:
                                action = side
                            inst_type = order.get('instrument_type', 'EQUITY')
                            asset_type = 'option' if inst_type == 'OPTION' else 'stock'
                            filled_orders.append({
                                'order_id': order.get('order_id') or order.get('broker_order_id'),
                                'symbol': order.get('symbol'),
                                'quantity': int(float(order.get('filled_quantity') or order.get('quantity', 0))),
                                'filled_price': float(order.get('filled_price', 0) or 0),
                                'action': action,
                                'filled_time': order.get('filled_time') or order.get('place_time', ''),
                                'asset_type': asset_type,
                            })
                    except Exception as e:
                        print(f"[SYNC] Webull Official filled orders error: {e}")

            elif broker_name == 'ROBINHOOD':
                if hasattr(broker_instance, 'get_orders'):
                    try:
                        raw_orders = await asyncio.to_thread(broker_instance.get_orders, 'closed')
                        for order in (raw_orders or []):
                            state = (order.get('state') or '').lower()
                            if state != 'filled':
                                continue
                            symbol = order.get('symbol') or order.get('chain_symbol', '')
                            if not symbol:
                                continue
                            is_option = bool(order.get('chain_symbol') and order.get('legs'))
                            side = (order.get('side') or 'buy').upper()
                            if is_option:
                                direction_raw = (order.get('direction') or '').upper()
                                action = 'BTO' if 'DEBIT' in direction_raw else 'STC'
                            else:
                                action = 'BTO' if side == 'BUY' else 'STC'
                            qty = float(order.get('cumulative_quantity', 0) or order.get('processed_quantity', 0) or order.get('quantity', 0))
                            price = float(order.get('average_price', 0) or order.get('price', 0) or 0)
                            filled_time = order.get('last_transaction_at') or order.get('updated_at', '')
                            entry = {
                                'order_id': order.get('id'),
                                'symbol': symbol,
                                'quantity': int(qty) if qty else 0,
                                'filled_price': price,
                                'action': action,
                                'filled_time': filled_time,
                                'asset_type': 'option' if is_option else 'stock',
                            }
                            if is_option and order.get('legs'):
                                leg = order['legs'][0]
                                entry['strike'] = float(leg.get('strike_price', 0) or 0) or None
                                entry['expiry'] = leg.get('expiration_date')
                                opt_type = (leg.get('option_type') or '').lower()
                                entry['direction'] = 'C' if opt_type == 'call' else ('P' if opt_type == 'put' else None)
                            filled_orders.append(entry)
                    except Exception as e:
                        print(f"[SYNC] Robinhood filled orders error: {e}")

            if not filled_orders:
                print(f"[SYNC] No filled orders from {broker_name}")
                return
            
            # Insert filled orders into database (deduplication via UNIQUE constraint)
            new_count = 0
            for order in filled_orders:
                # Normalize side to standard format
                # Handles: BUY/SELL (Alpaca), BUY_TO_OPEN/SELL_TO_CLOSE (Schwab)
                side = order.get('action', '')
                side_upper = side.upper()
                if side_upper in ('BUY', 'BUY_TO_OPEN', 'BTO'):
                    side = 'BTO'
                elif side_upper in ('SELL', 'SELL_TO_CLOSE', 'STC'):
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
                
                should_process = False
                if result:
                    new_count += 1
                    should_process = True
                else:
                    try:
                        from gui_app.database import get_connection as _gconn
                        _conn = _gconn()
                        _cur = _conn.cursor()
                        _cur.execute('''SELECT id, processed FROM filled_orders 
                            WHERE broker = ? AND broker_order_id = ?''',
                            (broker_name, str(order.get('order_id', ''))))
                        _existing = _cur.fetchone()
                        if _existing and not _existing['processed']:
                            should_process = True
                    except Exception:
                        pass
                
                if should_process:
                    try:
                        from gui_app.database import process_filled_order_event
                        fill_result = process_filled_order_event(
                            broker=broker_name,
                            broker_order_id=str(order.get('order_id', '')),
                            symbol=order.get('symbol', ''),
                            side=side,
                            quantity=qty,
                            fill_price=price,
                            filled_at=filled_time,
                            asset_type=order.get('asset_type', 'stock'),
                            strike=order.get('strike'),
                            expiry=order.get('expiry'),
                            call_put=order.get('direction')
                        )
                        if fill_result.get('trades_updated') or fill_result.get('lots_updated'):
                            print(f"[FILL_EVENT] ✓ Unified fill: {side} {order.get('symbol','')} trades={fill_result['trades_updated']} lots={fill_result['lots_updated']}")
                    except Exception as uf_err:
                        print(f"[FILL_EVENT] ⚠️ Unified fill warning: {uf_err}")
                    
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
                        exit_source = 'SIGNAL'
                        stc_channel_id = None
                        stc_asset_type = order.get('asset_type', 'stock')
                        try:
                            from gui_app.database import find_open_bto_trade, map_risk_trigger_to_exit_source, get_pending_order_metadata, update_pending_order_status, get_connection
                            
                            stc_meta = get_pending_order_metadata(broker=broker_name, broker_order_id=str(order.get('order_id', '')))
                            if stc_meta:
                                if stc_meta.get('exit_source'):
                                    exit_source = stc_meta['exit_source']
                                    print(f"[SYNC] ✓ Exit source from metadata: {exit_source} for {order.get('symbol', '')}")
                                if stc_meta.get('channel_id') and stc_meta['channel_id'] != 'UNKNOWN':
                                    stc_channel_id = stc_meta['channel_id']
                                if stc_meta.get('asset_type'):
                                    stc_asset_type = stc_meta['asset_type']
                                update_pending_order_status(broker_name, str(order.get('order_id', '')), 'FILLED')
                            
                            if exit_source == 'SIGNAL':
                                conn = get_connection()
                                cursor = conn.cursor()
                                cursor.execute("""
                                    SELECT risk_trigger, channel_id FROM trades
                                    WHERE symbol = ? AND UPPER(broker) = UPPER(?) AND direction = 'STC'
                                    AND risk_trigger IS NOT NULL AND risk_trigger != ''
                                    AND COALESCE(LOWER(TRIM(source)), '') IN ('discord', 'signal', 'sync_routing')
                                    ORDER BY id DESC LIMIT 1
                                """, (order.get('symbol', ''), broker_name))
                                stc_row = cursor.fetchone()
                                if stc_row and stc_row['risk_trigger']:
                                    exit_source = map_risk_trigger_to_exit_source(stc_row['risk_trigger'])
                                    stc_channel_id = stc_channel_id or stc_row['channel_id']
                            
                            if exit_source == 'SIGNAL' and hasattr(self, 'risk_manager') and self.risk_manager:
                                try:
                                    _rm = self.risk_manager
                                    _fill_sym = order.get('symbol', '')
                                    _fill_price = order.get('filled_price', 0) or 0
                                    for _pk in _rm.cache.get_all_keys():
                                        _ce = _rm.cache.get(_pk)
                                        if not _ce or _fill_sym.upper() not in _pk.upper():
                                            continue
                                        _bpt_price = _ce.broker_oco_pt_price or getattr(_ce, '_last_bracket_pt_price', None)
                                        _bsl_price = _ce.broker_oco_sl_price or getattr(_ce, '_last_bracket_sl_price', None)
                                        if _bpt_price and _fill_price > 0:
                                            _pt_dist = abs(_fill_price - _bpt_price) / _bpt_price if _bpt_price > 0 else 999
                                            if _pt_dist < 0.03:
                                                _bt = _ce.broker_pt_tier or getattr(_ce, '_last_bracket_fill_tier', 0) or 1
                                                exit_source = f'PROFIT_TARGET_T{_bt}'
                                                _rm.cache.mark_tier_hit(_pk, _bt)
                                                print(f"[SYNC] ✅ Bracket PT{_bt} fill matched for {_pk} (fill=${_fill_price:.2f} ≈ PT=${_bpt_price:.2f})")
                                                break
                                        if _bsl_price and _fill_price > 0:
                                            _sl_dist = abs(_fill_price - _bsl_price) / _bsl_price if _bsl_price > 0 else 999
                                            if _sl_dist < 0.05:
                                                exit_source = 'STOP_LOSS_BRACKET'
                                                print(f"[SYNC] ✅ Bracket SL fill matched for {_pk} (fill=${_fill_price:.2f} ≈ SL=${_bsl_price:.2f})")
                                                break
                                except Exception as _bm_err:
                                    print(f"[SYNC] ⚠️ Bracket fill attribution: {_bm_err}")

                            if not stc_channel_id:
                                bto_trade = find_open_bto_trade(
                                    symbol=order.get('symbol', ''),
                                    asset_type=stc_asset_type,
                                    broker=broker_name,
                                    strike=order.get('strike'),
                                    expiry=order.get('expiry'),
                                    call_put=order.get('direction')
                                )
                                if bto_trade:
                                    stc_channel_id = bto_trade.get('channel_id')
                        except Exception as lookup_err:
                            print(f"[SYNC] ⚠️ Exit source lookup: {lookup_err}")
                        
                        _stc_submitted_at = stc_meta.get('order_submitted_at') if stc_meta else None
                        await self._record_execution_closure(
                            broker=broker_name,
                            broker_order_id=str(order.get('order_id', '')),
                            symbol=order.get('symbol', ''),
                            asset_type=stc_asset_type,
                            strike=order.get('strike'),
                            expiry=order.get('expiry'),
                            call_put=order.get('direction'),
                            quantity=qty,
                            fill_price=price,
                            filled_at=filled_time,
                            exit_source=exit_source,
                            order_submitted_at=_stc_submitted_at,
                            channel_id=stc_channel_id
                        )
            
            if new_count > 0:
                print(f"[SYNC] ✓ Synced {new_count} new filled orders from {broker_name}")

            # Backfill: match unfilled lot_closures against filled_orders
            try:
                await self._backfill_exit_fills(broker_name, filled_orders)
            except Exception as bf_err:
                print(f"[SYNC] ⚠️ Exit fill backfill: {bf_err}")

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
    
    async def _backfill_exit_fills(self, broker_name, filled_orders):
        """Match STC filled_orders against lot_closures that have NULL exit_fill_price.

        Runs after every filled_orders sync to catch closures created by
        broker_closed_position that missed the exit fill because the lot_closure
        was created before the filled_orders sync ran.

        Also updates the parent trades table P&L to match the real broker fill.
        """
        from gui_app.database import get_connection, update_closure_exit_fill

        stc_fills = [f for f in filled_orders if f.get('action', '').upper() in ('SELL', 'STC', 'SELL_TO_CLOSE')]
        if not stc_fills:
            return

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT lc.id, lc.closed_qty, lc.close_price, sl.symbol, sl.asset_type,
                   sl.strike, sl.expiry, sl.entry_fill_price, sl.trade_id,
                   t.broker, t.executed_price as entry_price
            FROM lot_closures lc
            JOIN signal_lots sl ON lc.lot_id = sl.id
            LEFT JOIN trades t ON sl.trade_id = t.id
            WHERE lc.exit_fill_price IS NULL
              AND lc.exit_reason = 'BROKER_CLOSED'
              AND UPPER(COALESCE(t.broker, ?)) = UPPER(?)
              AND lc.closed_at >= datetime('now', '-7 days')
        ''', (broker_name, broker_name))
        unfilled = cursor.fetchall()

        if not unfilled:
            return

        matched = 0
        for closure in unfilled:
            sym = closure['symbol'].upper()
            qty = int(closure['closed_qty'] or 0)

            for fill in stc_fills:
                fill_sym = (fill.get('symbol') or '').upper()
                fill_qty = int(fill.get('quantity', 0))
                fill_price = float(fill.get('filled_price', 0))
                if fill_sym != sym or fill_price <= 0:
                    continue
                if fill_qty != qty and abs(fill_qty - qty) > max(1, qty * 0.1):
                    continue

                if closure['asset_type'] == 'option':
                    if str(closure.get('strike') or '') != str(fill.get('strike') or ''):
                        continue

                update_closure_exit_fill(
                    closure['id'], fill_price, broker_name,
                    order_id=str(fill.get('order_id', '')),
                    filled_at=fill.get('filled_time') or datetime.now().isoformat(),
                    exit_source='filled_orders_backfill')
                matched += 1
                print(f"[SYNC] ✓ Backfill: lot_closure #{closure['id']} {sym} exit fill ${fill_price:.4f} via {broker_name}")

                # Also update the trades table P&L to match broker fill
                trade_id = closure['trade_id']
                entry_price = float(closure['entry_price'] or closure['entry_fill_price'] or 0)
                if trade_id and entry_price > 0:
                    try:
                        multiplier = 100 if closure['asset_type'] == 'option' else 1
                        trade_pnl = round((fill_price - entry_price) * qty * multiplier, 2)
                        trade_pnl_pct = round(((fill_price - entry_price) / entry_price) * 100, 4) if entry_price > 0 else 0
                        cursor.execute('''
                            UPDATE trades SET current_price = ?, pnl = ?, pnl_percent = ?
                            WHERE id = ? AND status = 'CLOSED' AND close_reason = 'broker_closed_position'
                        ''', (fill_price, trade_pnl, trade_pnl_pct, trade_id))
                        if cursor.rowcount > 0:
                            conn.commit()
                            print(f"[SYNC] ✓ Backfill: trades #{trade_id} P&L corrected: ${trade_pnl:+.2f} ({trade_pnl_pct:+.2f}%) exit=${fill_price:.4f}")
                    except Exception as tp_err:
                        print(f"[SYNC] ⚠️ Backfill trades P&L: {tp_err}")
                break

        if matched:
            print(f"[SYNC] ✓ Backfilled {matched}/{len(unfilled)} lot_closure exit fills from {broker_name}")

    async def _query_broker_exit_fill(self, broker_name, broker_instance, symbol, bracket_ids, trade, bto_order_id=None):
        """Query the broker for actual exit fill price from bracket/OCO orders.

        Checks each bracket order ID (OCO parent, SL, PT) at the broker. If any
        is FILLED, returns the fill price and order details.

        For Schwab, also searches recent account orders for STC fills matching the
        symbol when no bracket IDs are available (fallback via bto_order_id).

        Returns dict with 'price', 'order_id', 'filled_at' or None.
        """
        bn = broker_name.upper()

        if bn == 'SCHWAB' and broker_instance and hasattr(broker_instance, 'get_order_status'):
            order_ids_to_check = []
            oco_id = bracket_ids.get('oco_id')
            sl_id = bracket_ids.get('sl_id')
            pt_id = bracket_ids.get('pt_id')

            if oco_id:
                order_ids_to_check.append(('OCO', str(oco_id)))
            if sl_id and str(sl_id) != str(oco_id or ''):
                order_ids_to_check.append(('SL', str(sl_id)))
            if pt_id and str(pt_id) != str(oco_id or ''):
                order_ids_to_check.append(('PT', str(pt_id)))

            for label, oid in order_ids_to_check:
                try:
                    status_result = await asyncio.wait_for(
                        broker_instance.get_order_status(oid),
                        timeout=8.0
                    )
                    if status_result and status_result.get('status') == 'filled':
                        avg_price = float(status_result.get('average_price', 0))
                        if avg_price > 0:
                            return {
                                'price': avg_price,
                                'order_id': oid,
                                'filled_at': datetime.now().isoformat(),
                                'source': f'bracket_{label.lower()}'
                            }
                except Exception as e:
                    print(f"[SYNC] ⚠️ Bracket {label} order #{oid} status check: {e}")

            # Fallback: search Schwab recent orders for STC fills
            if bto_order_id and hasattr(broker_instance, '_make_request') and hasattr(broker_instance, 'account_hash'):
                try:
                    from datetime import timedelta
                    now = datetime.now()
                    from_time = (now - timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
                    to_time = now.strftime('%Y-%m-%dT%H:%M:%S.000Z')

                    response = await broker_instance._make_request(
                        'GET',
                        f"{broker_instance.BASE_URL}/accounts/{broker_instance.account_hash}/orders",
                        params={
                            'fromEnteredTime': from_time,
                            'toEnteredTime': to_time,
                            'status': 'FILLED'
                        }
                    )
                    if response and response.status_code == 200:
                        orders = response.json()
                        symbol_upper = symbol.upper()
                        trade_strike = float(trade.get('strike') or 0)
                        for order in orders:
                            legs = order.get('orderLegCollection', [])
                            for leg in legs:
                                instr = leg.get('instrument', {})
                                # For options Schwab puts full OCC symbol in 'symbol'; use underlyingSymbol
                                instr_sym = (instr.get('underlyingSymbol') or instr.get('symbol') or '').upper()
                                if instr_sym != symbol_upper:
                                    continue
                                if leg.get('instruction', '').upper() not in ('SELL', 'SELL_TO_CLOSE'):
                                    continue
                                # For options additionally filter by strike to avoid grabbing wrong contract
                                if trade_strike > 0 and instr.get('assetType', '').upper() == 'OPTION':
                                    leg_strike = float(instr.get('strikePrice') or 0)
                                    if leg_strike > 0 and abs(leg_strike - trade_strike) > 0.01:
                                        continue
                                activities = order.get('orderActivityCollection', [])
                                total_filled = 0
                                total_cost = 0.0
                                for activity in activities:
                                    if activity.get('activityType') == 'EXECUTION':
                                        for exec_leg in activity.get('executionLegs', []):
                                            lq = int(exec_leg.get('quantity', 0))
                                            lp = float(exec_leg.get('price', 0))
                                            total_filled += lq
                                            total_cost += lq * lp
                                if total_filled > 0:
                                    avg = total_cost / total_filled
                                    filled_time = order.get('closeTime') or order.get('enteredTime') or ''
                                    return {
                                        'price': avg,
                                        'order_id': str(order.get('orderId', '')),
                                        'filled_at': filled_time or datetime.now().isoformat(),
                                        'source': 'schwab_recent_orders'
                                    }
                except Exception as e:
                    print(f"[SYNC] ⚠️ Schwab recent orders search: {e}")

        elif broker_instance and hasattr(broker_instance, 'get_order_status'):
            for label, oid in [('SL', bracket_ids.get('sl_id')), ('PT', bracket_ids.get('pt_id'))]:
                if not oid:
                    continue
                try:
                    status_result = await asyncio.wait_for(
                        broker_instance.get_order_status(str(oid)),
                        timeout=8.0
                    )
                    if status_result:
                        st = status_result.get('status', '').lower()
                        if st == 'filled':
                            avg_price = float(status_result.get('average_price', 0) or status_result.get('fill_price', 0) or 0)
                            if avg_price > 0:
                                return {
                                    'price': avg_price,
                                    'order_id': str(oid),
                                    'filled_at': datetime.now().isoformat(),
                                    'source': f'bracket_{label.lower()}'
                                }
                except Exception as e:
                    print(f"[SYNC] ⚠️ {broker_name} bracket {label} order #{oid}: {e}")

        return None

    async def reconcile_bracket_orders(self, risk_manager):
        """
        On restart, reconcile preserved bracket order IDs with actual broker state.
        Runs once per position — the _bracket_needs_reconciliation flag is cleared after.
        """
        if not risk_manager or not hasattr(risk_manager, 'cache'):
            return

        cache = risk_manager.cache
        reconcile_keys = []
        for key in cache.get_all_keys():
            entry = cache.get(key)
            if entry and getattr(entry, '_bracket_needs_reconciliation', False):
                reconcile_keys.append(key)

        if not reconcile_keys:
            return

        print(f"[SYNC] ♻️ Reconciling bracket orders for {len(reconcile_keys)} position(s)...")
        changed = False

        for pos_key in reconcile_keys:
            entry = cache.get(pos_key)
            if not entry:
                continue

            broker_name = self._extract_broker(pos_key)
            oco_id = entry.broker_oco_order_id
            sl_id = entry.broker_stop_order_id
            pt_id = entry.broker_pt_order_id

            result = await self._reconcile_bracket_for_entry(
                entry, pos_key, broker_name, oco_id, sl_id, pt_id
            )

            _fill_result = result if isinstance(result, tuple) else (result,)
            _result_type = _fill_result[0]

            if _result_type == 'restored':
                entry._bracket_needs_reconciliation = False
                print(f"[SYNC] ✓ BRACKET RESTORED {pos_key} — orders still active at {broker_name}")
                changed = True
            elif _result_type in ('filled', 'pt_filled', 'sl_filled'):
                entry._bracket_needs_reconciliation = False
                _tier = entry.broker_pt_tier or 1
                if _result_type == 'pt_filled':
                    risk_manager.cache.mark_tier_hit(pos_key, _tier)
                    if entry.entry_price > 0:
                        _pts_hit = {1: entry.tier1_hit, 2: entry.tier2_hit, 3: entry.tier3_hit, 4: entry.tier4_hit}
                        _dsl_profile = 'standard'
                        _ch = getattr(entry, 'channel_settings', None)
                        if _ch:
                            _dsl_profile = getattr(_ch, 'dynamic_sl_profile', 'standard') or 'standard'
                        try:
                            from src.risk.risk_engine import calculate_dynamic_sl
                            _new_dsl = calculate_dynamic_sl(entry.entry_price, _pts_hit, _dsl_profile)
                            if _new_dsl and (not entry.dynamic_sl_price or _new_dsl > entry.dynamic_sl_price):
                                entry.dynamic_sl_price = _new_dsl
                                print(f"[SYNC] 🔒 Dynamic SL escalated to ${_new_dsl:.2f} after bracket PT{_tier} fill on restart")
                        except Exception as _dsl_err:
                            print(f"[SYNC] ⚠️ Dynamic SL escalation failed: {_dsl_err}")
                    print(f"[SYNC] ✅ BRACKET PT{_tier} FILLED {pos_key} — tier marked, cascade on next eval")
                elif _result_type == 'sl_filled':
                    print(f"[SYNC] 🛑 BRACKET SL FILLED {pos_key} — position exiting via broker stop")
                else:
                    print(f"[SYNC] ✓ BRACKET FILLED {pos_key} — bracket triggered during downtime")
                self._clear_bracket_ids(entry)
                changed = True
            elif _result_type == 'cleared':
                entry._bracket_needs_reconciliation = False
                self._clear_bracket_ids(entry)
                entry.broker_orders_placed = False
                print(f"[SYNC] ✓ BRACKET CLEARED {pos_key} — will place fresh brackets on next eval")
                changed = True
            elif _result_type == 'deferred':
                print(f"[SYNC] ⏳ BRACKET DEFERRED {pos_key} — {broker_name} unreachable, retry next cycle")

        if changed:
            cache.save()

    async def _reconcile_bracket_for_entry(self, entry, pos_key, broker_name, oco_id, sl_id, pt_id):
        """Query broker for actual order status and return reconciliation outcome."""
        if 'Schwab' in broker_name or 'SCHWAB' in broker_name:
            return await self._reconcile_schwab_brackets(entry, pos_key, oco_id, sl_id, pt_id)
        elif 'IBKR' in broker_name:
            return await self._reconcile_ibkr_brackets(entry, pos_key, sl_id, pt_id)
        else:
            return await self._reconcile_generic_brackets(entry, pos_key, broker_name, sl_id, pt_id)

    async def _reconcile_schwab_brackets(self, entry, pos_key, oco_id, sl_id, pt_id):
        """Schwab uses a single OCO parent order — check its status."""
        check_id = oco_id or sl_id or pt_id
        if not check_id:
            return 'cleared'

        status_info = await self._get_order_status('SCHWAB', check_id)
        if not status_info:
            return 'deferred'

        status = (status_info.get('status') or '').lower()
        if status in ('pending', 'pending_activation', 'partial'):
            return 'restored'
        elif status == 'filled':
            fill_leg = status_info.get('fill_leg')
            if fill_leg == 'pt':
                return 'pt_filled'
            elif fill_leg == 'sl':
                return 'sl_filled'
            if entry.broker_oco_pt_price and entry.broker_oco_sl_price:
                fill_price = status_info.get('average_price', 0)
                if fill_price > 0:
                    pt_dist = abs(fill_price - entry.broker_oco_pt_price)
                    sl_dist = abs(fill_price - entry.broker_oco_sl_price)
                    return 'pt_filled' if pt_dist < sl_dist else 'sl_filled'
            return 'filled'
        elif status in ('cancelled', 'rejected', 'expired'):
            if sl_id and sl_id != oco_id:
                sl_info = await self._get_order_status('SCHWAB', sl_id)
                if sl_info:
                    sl_status = (sl_info.get('status') or '').lower()
                    if sl_status in ('pending', 'pending_activation', 'partial'):
                        entry.broker_oco_order_id = None
                        entry.broker_oco_sl_price = None
                        entry.broker_oco_pt_price = None
                        entry.broker_oco_qty = 0
                        entry.broker_pt_order_id = None
                        return 'restored'
            return 'cleared'
        return 'deferred'

    async def _reconcile_ibkr_brackets(self, entry, pos_key, sl_id, pt_id):
        """IBKR uses OCA group with individual SL and PT orders."""
        if not sl_id and not pt_id:
            return 'cleared'

        sl_alive = False
        pt_alive = False
        sl_filled = False
        pt_filled = False
        any_queried = False

        if sl_id:
            sl_info = await self._get_order_status('IBKR', sl_id)
            if sl_info:
                any_queried = True
                sl_status = (sl_info.get('status') or '').upper()
                if sl_status in ('PRESUBMITTED', 'SUBMITTED', 'PENDINGSUBMIT', 'PENDING'):
                    sl_alive = True
                elif sl_status == 'FILLED':
                    sl_filled = True

        if pt_id:
            pt_info = await self._get_order_status('IBKR', pt_id)
            if pt_info:
                any_queried = True
                pt_status = (pt_info.get('status') or '').upper()
                if pt_status in ('PRESUBMITTED', 'SUBMITTED', 'PENDINGSUBMIT', 'PENDING'):
                    pt_alive = True
                elif pt_status == 'FILLED':
                    pt_filled = True

        if not any_queried:
            return 'deferred'

        if sl_alive or pt_alive:
            if not sl_alive and sl_id:
                entry.broker_stop_order_id = None
            if not pt_alive and pt_id:
                entry.broker_pt_order_id = None
            return 'restored'
        elif pt_filled:
            return 'pt_filled'
        elif sl_filled:
            return 'sl_filled'
        return 'cleared'

    async def _reconcile_generic_brackets(self, entry, pos_key, broker_name, sl_id, pt_id):
        """For Alpaca, Tastytrade, Robinhood, Trading212, Webull."""
        if not sl_id and not pt_id:
            return 'cleared'

        sl_alive = False
        pt_alive = False
        sl_filled = False
        pt_filled = False
        any_queried = False

        alive_statuses = {'PENDING', 'WORKING', 'OPEN', 'ACCEPTED', 'NEW', 'PARTIAL',
                          'PENDING_ACTIVATION', 'QUEUED', 'AWAITING_CONDITION'}

        if sl_id:
            sl_info = await self._get_order_status(broker_name, sl_id)
            if sl_info:
                any_queried = True
                sl_status = (sl_info.get('status') or '').upper()
                if sl_status in alive_statuses:
                    sl_alive = True
                elif sl_status == 'FILLED':
                    sl_filled = True

        if pt_id:
            pt_info = await self._get_order_status(broker_name, pt_id)
            if pt_info:
                any_queried = True
                pt_status = (pt_info.get('status') or '').upper()
                if pt_status in alive_statuses:
                    pt_alive = True
                elif pt_status == 'FILLED':
                    pt_filled = True

        if not any_queried:
            return 'deferred'

        if sl_alive or pt_alive:
            if not sl_alive and sl_id:
                entry.broker_stop_order_id = None
            if not pt_alive and pt_id:
                entry.broker_pt_order_id = None
            return 'restored'
        elif pt_filled:
            return 'pt_filled'
        elif sl_filled:
            return 'sl_filled'
        return 'cleared'

    def _clear_bracket_ids(self, entry):
        """Reset all bracket order fields on a cache entry."""
        entry.broker_stop_order_id = None
        entry.broker_pt_order_id = None
        entry.broker_oco_order_id = None
        entry.broker_oco_sl_price = None
        entry.broker_oco_pt_price = None
        entry.broker_oco_qty = 0
        entry.broker_pt_tier = 0
        if hasattr(entry, '_bracket_placed_qty'):
            entry._bracket_placed_qty = 0
        if hasattr(entry, '_bracket_attempt_count'):
            entry._bracket_attempt_count = 0

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
                        filled_qty = order_status.get('filled_qty', 0) or order_status.get('filled_quantity', 0)
                        
                        if status == 'FILLED':
                            # Confirmed fill - mark tier as hit
                            risk_manager.cache.confirm_order_fill(position_key, order_id, filled_qty)
                            print(f"[SYNC] ✅ Risk order {order_id} FILLED - Tier {tier} confirmed")
                        elif status in ('CANCELLED', 'REJECTED', 'EXPIRED'):
                            risk_manager.cache.fail_pending_order(position_key, order_id)
                            print(f"[SYNC] ❌ Risk order {order_id} {status} - Tier {tier} will retry")
                            try:
                                from gui_app.database import get_connection as _sync_gc
                                _sc = _sync_gc()
                                _scur = _sc.cursor()
                                _scur.execute(
                                    "SELECT id, origin_trade_id FROM trades WHERE order_id = ? AND direction = 'STC' AND status = 'CLOSED'",
                                    (str(order_id),)
                                )
                                for _pr in _scur.fetchall():
                                    _scur.execute("DELETE FROM trades WHERE id = ?", (_pr['id'],))
                                    print(f"[SYNC] 🗑️ Deleted phantom STC trade #{_pr['id']} (order {order_id} was {status})")
                                    if _pr['origin_trade_id']:
                                        _scur.execute("SELECT status FROM trades WHERE id = ? AND direction = 'BTO'", (_pr['origin_trade_id'],))
                                        _orow = _scur.fetchone()
                                        if _orow and _orow['status'] == 'CLOSED':
                                            _scur.execute("UPDATE trades SET status = 'OPEN', closed_at = NULL WHERE id = ?", (_pr['origin_trade_id'],))
                                            print(f"[SYNC] ✅ Reopened origin BTO trade #{_pr['origin_trade_id']} (was closed by phantom STC)")
                                _sc.commit()
                            except Exception as _sdb_err:
                                print(f"[SYNC] ⚠️ Could not clean up phantom trades: {_sdb_err}")
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
        elif position_key.startswith('SCHWAB_'):
            return 'SCHWAB'
        elif position_key.startswith('ALPACA_'):
            return 'Alpaca'
        elif position_key.startswith('IBKR_'):
            return 'IBKR'
        elif position_key.startswith('SCHWAB_'):
            return 'Schwab'
        elif position_key.startswith('Tastytrade_') or position_key.startswith('TASTYTRADE_'):
            return 'Tastytrade'
        elif position_key.startswith('Robinhood_') or position_key.startswith('ROBINHOOD_'):
            return 'Robinhood'
        elif position_key.startswith('Trading212_') or position_key.startswith('TRADING212_'):
            return 'Trading212'
        return 'Unknown'
    
    async def _get_order_status(self, broker: str, order_id: str) -> Optional[Dict]:
        """Get order status from broker API"""
        try:
            broker_instance = None
            if broker in ('Webull', 'Webull_Paper', 'WEBULL', 'WEBULL_PAPER'):
                wb = getattr(self.broker_manager, 'webull_broker', None)
                wb_paper = getattr(self.broker_manager, 'webull_paper_broker', None)
                broker_instance = wb or wb_paper
            elif 'Alpaca' in broker or 'ALPACA' in broker:
                broker_instance = getattr(self.broker_manager, 'alpaca_paper_broker', None) or \
                                  getattr(self.broker_manager, 'alpaca_broker', None)
                if broker_instance and hasattr(broker_instance, 'get_order'):
                    order = broker_instance.get_order(order_id)
                    if order:
                        status_str = str(order.status).replace('OrderStatus.', '').upper()
                        return {
                            'status': status_str,
                            'filled_qty': int(float(order.filled_qty or 0))
                        }
                    return None
            elif 'Schwab' in broker or 'SCHWAB' in broker:
                broker_instance = getattr(self.broker_manager, 'schwab_broker', None)
            elif 'Robinhood' in broker or 'ROBINHOOD' in broker:
                broker_instance = getattr(self.broker_manager, 'robinhood_broker', None)
            elif 'Tastytrade' in broker or 'TASTYTRADE' in broker:
                broker_instance = getattr(self.broker_manager, 'tastytrade_broker', None)
            elif 'IBKR' in broker:
                broker_instance = getattr(self.broker_manager, 'ibkr_broker', None)
            elif 'TRADING212' in broker:
                broker_instance = getattr(self.broker_manager, 'trading212_broker', None)

            if broker_instance and hasattr(broker_instance, 'get_order_status'):
                return await broker_instance.get_order_status(order_id)
        except Exception as e:
            print(f"[SYNC] ⚠️ get_order_status({broker}, {order_id}) failed: {e}")
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
                from gui_app.database import insert_execution_lot, get_pending_order_metadata, update_pending_order_status, get_connection
                _insert_lot._resolved_lot_id = signal_lot_id
                
                # Try to hydrate from pending order metadata first
                meta = get_pending_order_metadata(broker=broker, broker_order_id=broker_order_id)
                
                # Use metadata values if available, else fall back to params
                candidate_channel = channel_id or (meta['channel_id'] if meta else None)
                
                # FALLBACK: If still no channel_id, look up from matching OPEN trades table
                # SAFETY: Only match OPEN/PENDING trades with trusted sources — never historical/closed trades
                if not candidate_channel or candidate_channel == 'UNKNOWN':
                    try:
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT channel_id, source FROM trades 
                            WHERE symbol = ? 
                            AND (UPPER(broker) = UPPER(?) OR broker IS NULL)
                            AND channel_id IS NOT NULL 
                            AND channel_id != 'UNKNOWN'
                            AND channel_id != ''
                            AND status IN ('OPEN', 'PENDING', 'PARTIAL')
                            AND COALESCE(LOWER(TRIM(source)), '') IN ('discord', 'signal', 'sync_routing')
                            ORDER BY id DESC
                            LIMIT 1
                        """, (symbol, broker))
                        row = cursor.fetchone()
                        if row and row['channel_id']:
                            candidate_channel = row['channel_id']
                            print(f"[SYNC] ✓ Recovered channel_id={candidate_channel} for {symbol} from OPEN trades (source='{row['source']}')")
                    except Exception as lookup_err:
                        print(f"[SYNC] ⚠️ Channel lookup fallback failed: {lookup_err}")
                
                final_channel_id = candidate_channel or 'UNKNOWN'
                final_signal_price = signal_price or (meta['signal_price'] if meta else None)
                final_analyst_qty = analyst_entry_qty or (meta['analyst_qty'] if meta else None)
                final_sizing_mode = sizing_mode or (meta['sizing_mode'] if meta else None)
                final_signal_lot_id = signal_lot_id or (meta['signal_lot_id'] if meta else None)
                _insert_lot._resolved_lot_id = final_signal_lot_id
                _insert_lot._resolved_channel_id = final_channel_id
                final_signal_detected = signal_detected_at or (meta['signal_detected_at'] if meta else None)
                final_signal_parsed = signal_parsed_at or (meta['signal_parsed_at'] if meta else None)
                final_order_submitted = order_submitted_at or (meta['order_submitted_at'] if meta else None)
                sizing_details = meta['sizing_details'] if meta else None
                
                final_asset_type = asset_type
                if meta and meta.get('asset_type'):
                    final_asset_type = meta['asset_type']
                    if final_asset_type != asset_type:
                        print(f"[SYNC] ✓ Corrected asset_type from '{asset_type}' to '{final_asset_type}' (from signal metadata)")
                if final_asset_type == 'option' and not strike and not expiry and not call_put:
                    final_asset_type = 'stock'
                    print(f"[SYNC] ✓ Corrected asset_type to 'stock' (no strike/expiry/call_put data)")
                
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
                
                if final_signal_detected and final_order_submitted:
                    try:
                        from datetime import datetime
                        detected = datetime.fromisoformat(str(final_signal_detected).replace('Z', '+00:00'))
                        submitted = datetime.fromisoformat(str(final_order_submitted).replace('Z', '+00:00'))
                        latency_total_ms = int((submitted - detected).total_seconds() * 1000)
                    except:
                        pass
                
                result = insert_execution_lot(
                    signal_lot_id=final_signal_lot_id,
                    channel_id=final_channel_id,
                    broker=broker,
                    broker_order_id=broker_order_id,
                    symbol=symbol,
                    asset_type=final_asset_type,
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
                if not result and broker_order_id:
                    # Execution lot already created at order time — update with actual fill data
                    try:
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute('''UPDATE execution_lots SET
                            fill_price = ?, order_filled_at = ?, slippage_pct = ?,
                            latency_broker_ms = COALESCE(?, latency_broker_ms),
                            latency_total_ms = COALESCE(?, latency_total_ms),
                            signal_lot_id = COALESCE(?, signal_lot_id),
                            signal_price = COALESCE(?, signal_price),
                            signal_detected_at = COALESCE(?, signal_detected_at),
                            signal_parsed_at = COALESCE(?, signal_parsed_at),
                            order_submitted_at = COALESCE(?, order_submitted_at)
                            WHERE broker = ? AND broker_order_id = ?''',
                            (fill_price, filled_at, slippage_pct,
                             latency_broker_ms, latency_total_ms,
                             final_signal_lot_id, final_signal_price,
                             final_signal_detected, final_signal_parsed, final_order_submitted,
                             broker, broker_order_id))
                        conn.commit()
                        if cursor.rowcount > 0:
                            result = True
                            print(f"[EXEC] ✓ Updated execution lot with fill data: {symbol} @${fill_price:.2f}")
                    except Exception as _upd_err:
                        print(f"[EXEC] ⚠️ Could not update execution lot: {_upd_err}")
                if result and meta:
                    update_pending_order_status(broker, broker_order_id, 'FILLED')
                return result
            
            _resolved_signal_lot_id = [signal_lot_id]
            _resolved_channel_id = [channel_id]
            _original_insert_lot = _insert_lot
            def _insert_lot_and_capture():
                result = _original_insert_lot()
                _resolved_signal_lot_id[0] = _insert_lot._resolved_lot_id
                _resolved_channel_id[0] = getattr(_insert_lot, '_resolved_channel_id', channel_id)
                return result
            
            result = await asyncio.to_thread(_insert_lot_and_capture)
            if result:
                print(f"[EXEC] ✓ Recorded execution lot: {symbol} {quantity}x @${fill_price:.2f}")
            
            resolved_lot = _resolved_signal_lot_id[0]
            if resolved_lot:
                try:
                    def _update_signal_lot_fill():
                        from gui_app.database import update_lot_entry_fill
                        update_lot_entry_fill(
                            lot_id=resolved_lot,
                            fill_price=fill_price,
                            broker=broker,
                            order_id=broker_order_id,
                            filled_at=filled_at
                        )
                    await asyncio.to_thread(_update_signal_lot_fill)
                except Exception as fill_err:
                    print(f"[EXEC] ⚠️ Could not update signal lot fill: {fill_err}")
            else:
                try:
                    _fb_channel = _resolved_channel_id[0] if _resolved_channel_id[0] and _resolved_channel_id[0] != 'UNKNOWN' else None
                    def _fallback_lot_fill():
                        if not _fb_channel:
                            print(f"[EXEC] ⚠️ Skipping fallback lot fill for {symbol}: no channel_id (would risk cross-channel match)")
                            return
                        from gui_app.database import get_connection
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT sl.id FROM signal_lots sl
                            JOIN trades t ON sl.trade_id = t.id
                            WHERE UPPER(sl.symbol) = UPPER(?) AND UPPER(t.broker) = UPPER(?)
                              AND sl.entry_fill_price IS NULL AND sl.status != 'CLOSED'
                              AND sl.channel_id = ?
                            ORDER BY sl.id DESC LIMIT 1
                        ''', (symbol, broker, _fb_channel))
                        row = cursor.fetchone()
                        if row:
                            from gui_app.database import update_lot_entry_fill
                            update_lot_entry_fill(row['id'], fill_price, broker, broker_order_id, filled_at)
                            print(f"[EXEC] ✓ Fallback entry fill: lot #{row['id']} {symbol} ch={_fb_channel} @${fill_price:.2f} via {broker}")
                    await asyncio.to_thread(_fallback_lot_fill)
                except Exception as fb_err:
                    print(f"[EXEC] ⚠️ Fallback entry fill failed: {fb_err}")
            
            try:
                def _mark_processed():
                    from gui_app.database import get_connection
                    conn = get_connection()
                    conn.cursor().execute('UPDATE filled_orders SET processed = 1 WHERE broker = ? AND broker_order_id = ?', (broker, broker_order_id))
                    conn.commit()
                await asyncio.to_thread(_mark_processed)
            except Exception:
                pass
            
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
            
            if result:
                try:
                    def _update_lot_closure_fill():
                        from gui_app.database import get_connection, update_closure_exit_fill
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT el.signal_lot_id FROM execution_lots el
                            JOIN execution_closures ec ON ec.execution_lot_id = el.id
                            WHERE ec.id = ?
                        ''', (result,))
                        row = cursor.fetchone()
                        target_lot_id = row['signal_lot_id'] if row and row['signal_lot_id'] else None
                        
                        if not target_lot_id:
                            _exit_fb_query = '''
                                SELECT sl.id FROM signal_lots sl
                                JOIN trades t ON sl.trade_id = t.id
                                WHERE UPPER(sl.symbol) = UPPER(?) AND UPPER(t.broker) = UPPER(?)
                                  AND sl.remaining_qty <= 0 AND sl.status = 'CLOSED'
                            '''
                            _exit_fb_params = [symbol, broker]
                            if channel_id and channel_id != 'UNKNOWN':
                                _exit_fb_query += ' AND sl.channel_id = ?'
                                _exit_fb_params.append(channel_id)
                            else:
                                print(f"[EXEC] ⚠️ Skipping fallback exit fill for {symbol}: no channel_id (would risk cross-channel match)")
                            _exit_fb_query += ' ORDER BY sl.id DESC LIMIT 1'
                            if channel_id and channel_id != 'UNKNOWN':
                                cursor.execute(_exit_fb_query, _exit_fb_params)
                                fb_row = cursor.fetchone()
                                if fb_row:
                                    target_lot_id = fb_row['id']
                                    print(f"[EXEC] ✓ Fallback exit fill: matched lot #{target_lot_id} for {symbol} ch={channel_id} via {broker}")
                        
                        if target_lot_id:
                            cursor.execute('''
                                SELECT id, closed_qty, close_price FROM lot_closures 
                                WHERE lot_id = ? AND (exit_fill_price IS NULL OR exit_fill_order_id IS NULL)
                                ORDER BY (exit_fill_price IS NULL) DESC, ABS(closed_qty - ?) ASC, ABS(close_price - ?) ASC, closed_at DESC 
                                LIMIT 1
                            ''', (target_lot_id, quantity, fill_price))
                            closure_row = cursor.fetchone()
                            if closure_row:
                                update_closure_exit_fill(
                                    closure_id=closure_row['id'],
                                    fill_price=fill_price,
                                    broker=broker,
                                    order_id=broker_order_id,
                                    filled_at=filled_at,
                                    exit_source=exit_source
                                )
                    await asyncio.to_thread(_update_lot_closure_fill)
                except Exception as fill_err:
                    print(f"[EXEC] ⚠️ Could not update lot closure fill: {fill_err}")
                
                try:
                    def _reconcile_trade_fill():
                        from gui_app.database import reconcile_trade_fill_price
                        reconcile_trade_fill_price(
                            broker=broker,
                            symbol=symbol,
                            asset_type=asset_type,
                            strike=strike,
                            expiry=expiry,
                            call_put=call_put,
                            quantity=quantity,
                            fill_price=fill_price,
                            broker_order_id=broker_order_id,
                            filled_at=filled_at
                        )
                    await asyncio.to_thread(_reconcile_trade_fill)
                except Exception as reconcile_err:
                    print(f"[EXEC] ⚠️ Could not reconcile trade fill price: {reconcile_err}")
            
            try:
                def _mark_stc_processed():
                    from gui_app.database import get_connection
                    conn = get_connection()
                    conn.cursor().execute('UPDATE filled_orders SET processed = 1 WHERE broker = ? AND broker_order_id = ?', (broker, broker_order_id))
                    conn.commit()
                await asyncio.to_thread(_mark_stc_processed)
            except Exception:
                pass
            
            return result
            
        except Exception as e:
            print(f"[EXEC] Error recording execution closure: {e}")
            import traceback
            traceback.print_exc()
            return None
