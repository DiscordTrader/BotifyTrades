"""
Position Cache Management
=========================
Handles persistence and state management for monitored positions.
"""
import json
import threading
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

from .risk_types import PositionCacheEntry, PositionSnapshot


def get_position_cache() -> 'PositionCache':
    """Get the global PositionCache instance from the active RiskManager.
    This is the singleton accessor used by partial exit and other modules.
    Returns a fallback PositionCache if RiskManager not yet initialized."""
    import sys
    for mod_name in ('src.risk.position_monitor', 'risk.position_monitor'):
        mod = sys.modules.get(mod_name)
        rm = getattr(mod, 'risk_manager_instance', None) if mod else None
        if rm and hasattr(rm, 'cache'):
            return rm.cache
    try:
        from .position_monitor import risk_manager_instance
        if risk_manager_instance and hasattr(risk_manager_instance, 'cache'):
            return risk_manager_instance.cache
    except Exception:
        pass
    return PositionCache()


class PositionCache:
    """Manages position state cache with file persistence."""
    
    CLOSING_TIMEOUT_SECONDS = 180
    
    FLIP_FLOP_HISTORY_SIZE = 3
    ENTRY_PRICE_CHANGE_TOLERANCE = 0.05
    ENTRY_PRICE_ABS_FLOOR = 0.05
    ENTRY_PRICE_LOW_PRICE_THRESHOLD = 10.0

    @classmethod
    def _entry_change_is_material(cls, old_price: float, new_price: float) -> bool:
        """A price change is material if EITHER the percent change exceeds the
        relative tolerance OR (for low-priced instruments where small absolute
        moves are large in percent-of-spread terms) the absolute change exceeds
        the cents floor. This prevents the 5% relative gate from silently
        suppressing real broker corrections like $3.87 -> $3.77 on a sub-$10
        stock (2.6% relative, $0.10 absolute)."""
        if old_price is None or new_price is None or old_price <= 0:
            return True
        abs_diff = abs(new_price - old_price)
        if abs_diff < 0.001:
            return False
        pct_diff = abs_diff / old_price
        if pct_diff >= cls.ENTRY_PRICE_CHANGE_TOLERANCE:
            return True
        if (old_price < cls.ENTRY_PRICE_LOW_PRICE_THRESHOLD or
                new_price < cls.ENTRY_PRICE_LOW_PRICE_THRESHOLD) and \
                abs_diff >= cls.ENTRY_PRICE_ABS_FLOOR:
            return True
        return False

    def __init__(self, cache_file: Optional[Path] = None):
        self.cache_file = cache_file or Path.cwd() / '.position_cache.json'
        self._cache: Dict[str, PositionCacheEntry] = {}
        self._trade_id_map: Dict[str, int] = {}  # position_key -> trade_id for database persistence
        self._cache_lock = threading.RLock()
        self._persist_lock = threading.Lock()  # Concurrency safety for DB writes
        self._last_entry_prices: Dict[str, list] = {}
        self._locked_entry_prices: Dict[str, float] = {}
    
    def restore_trailing_state_from_db(self) -> int:
        """Restore trailing stop state from database for all open trades. 
        Also populates trade_id mappings for ALL open trades to enable persistence.
        Returns count of trailing states restored."""
        try:
            from gui_app.database import get_open_trades_with_trailing_state
            trades = get_open_trades_with_trailing_state()
            restored = 0
            mapped = 0
            
            for trade in trades:
                broker = trade['broker'] or 'UNKNOWN'
                asset_type = trade['asset_type'] or 'stock'
                
                if asset_type == 'option' and trade['strike']:
                    pos_key = f"{broker}_{trade['symbol']}_{trade['strike']}_{trade['expiry']}_{trade['call_put']}"
                else:
                    pos_key = f"{broker}_{trade['symbol']}_stock"
                
                # Store trade_id mapping for ALL open trades (needed for persistence)
                self._trade_id_map[pos_key] = trade['id']
                mapped += 1
                
                # Restore trailing state only if it was activated
                if trade['trailing_activated']:
                    # If cache entry exists, restore trailing state
                    if pos_key in self._cache:
                        self._cache[pos_key].trailing_activated = True
                        if trade['highest_price']:
                            self._cache[pos_key].highest_price = trade['highest_price']
                        highest_val = trade['highest_price'] or 0.0
                        print(f"[RISK] ✓ Restored trailing state: {pos_key} | activated=True, highest=${highest_val:.2f}")
                        restored += 1
            
            if mapped > 0:
                print(f"[RISK] Mapped {mapped} open trades to position cache for trailing persistence")
            if restored > 0:
                print(f"[RISK] Restored trailing state for {restored} positions from database")
            return restored
        except Exception as e:
            print(f"[RISK] Warning: Could not restore trailing state from DB: {e}")
            return 0
    
    def _normalize_broker_name(self, broker: str) -> str:
        """Normalize broker name to match cache format used by sync service."""
        broker_map = {
            'WEBULL': 'Webull',
            'ALPACA_PAPER': 'ALPACA_PAPER',
            'ALPACA_LIVE': 'ALPACA_LIVE',
            'ROBINHOOD': 'Robinhood',
            'SCHWAB': 'SCHWAB',
            'IBKR': 'IBKR',
            'TASTYTRADE': 'TASTYTRADE_LIVE',
            'TASTYTRADE_LIVE': 'TASTYTRADE_LIVE',
            'TASTYTRADE_PAPER': 'TASTYTRADE_PAPER',
            'QUESTRADE': 'Questrade',
            'UPSTOX': 'Upstox',
            'ZERODHA': 'Zerodha',
            'DHANQ': 'DhanQ',
            'TRADING212': 'TRADING212',
            'TRADING212_PAPER': 'TRADING212_PAPER',
        }
        return broker_map.get(broker.upper(), broker)
    
    def _normalize_expiry(self, expiry: str) -> str:
        """Normalize expiry format to match cache format (e.g., 2/20 -> 02/20)."""
        if not expiry:
            return expiry
        parts = expiry.replace('-', '/').split('/')
        if len(parts) >= 2:
            month = parts[0].zfill(2)
            day = parts[1].zfill(2)
            return f"{month}/{day}"
        return expiry
    
    def restore_full_risk_state_from_db(self) -> int:
        """
        Restore complete risk state from database for all open trades.
        This includes tier hits, dynamic SL, giveback guard, max P&L seen, and trailing state.
        Returns count of positions with restored risk state.
        """
        try:
            from gui_app.database import get_open_trades_with_risk_state
            trades = get_open_trades_with_risk_state()
            restored = 0
            mapped = 0
            
            for trade in trades:
                raw_broker = trade['broker'] or 'UNKNOWN'
                broker = self._normalize_broker_name(raw_broker)
                asset_type = trade['asset_type'] or 'stock'
                
                if asset_type == 'option' and trade['strike']:
                    expiry = self._normalize_expiry(trade['expiry'] or '')
                    pos_key = f"{broker}_{trade['symbol']}_{trade['strike']}_{expiry}_{trade['call_put']}"
                else:
                    pos_key = f"{broker}_{trade['symbol']}_stock"
                
                self._trade_id_map[pos_key] = trade['id']
                mapped += 1
                
                if pos_key in self._cache:
                    entry = self._cache[pos_key]
                    has_state = False
                    
                    if trade.get('quantity') and trade['quantity'] > 0:
                        entry.original_qty = int(trade['quantity'])
                    
                    if trade.get('pt1_hit'):
                        entry.tier1_hit = True
                        has_state = True
                    if trade.get('pt2_hit'):
                        entry.tier2_hit = True
                        has_state = True
                    if trade.get('pt3_hit'):
                        entry.tier3_hit = True
                        has_state = True
                    if trade.get('pt4_hit'):
                        entry.tier4_hit = True
                        has_state = True
                    if trade.get('dynamic_sl_price'):
                        entry.dynamic_sl_price = trade['dynamic_sl_price']
                        has_state = True
                    if trade.get('giveback_guard_active'):
                        entry.giveback_guard_active = True
                        has_state = True
                    if trade.get('max_pnl_seen'):
                        entry.max_pnl_seen = trade['max_pnl_seen']
                        has_state = True
                    if trade.get('trailing_stop_price'):
                        entry.trailing_stop_price = trade['trailing_stop_price']
                        has_state = True
                    if trade.get('trailing_activated'):
                        entry.trailing_activated = True
                        has_state = True
                        if trade.get('highest_price'):
                            entry.highest_price = trade['highest_price']
                    if trade.get('risk_settings_hash'):
                        entry.risk_settings_hash = trade['risk_settings_hash']
                    
                    if trade.get('early_trailing_active'):
                        entry.early_trailing_active = True
                        has_state = True
                    if trade.get('early_stop_price') is not None:
                        entry.early_stop_price = trade['early_stop_price']
                        has_state = True
                    if trade.get('early_steps_locked') is not None and trade.get('early_steps_locked') >= 0:
                        entry.early_steps_locked = trade['early_steps_locked']
                        has_state = True
                    if trade.get('highest_price') is not None and trade['highest_price'] > 0:
                        entry.highest_price = trade['highest_price']
                    
                    if has_state:
                        tier_hits = f"PT1={trade.get('pt1_hit')} PT2={trade.get('pt2_hit')} PT3={trade.get('pt3_hit')} PT4={trade.get('pt4_hit')}"
                        early_info = f" | Early={'ON' if trade.get('early_trailing_active') else 'OFF'} steps={trade.get('early_steps_locked', 0)}" if trade.get('early_trailing_active') else ""
                        print(f"[RISK] ✓ Restored full risk state: {pos_key} | {tier_hits}{early_info}")
                        restored += 1
            
            if mapped > 0:
                print(f"[RISK] Mapped {mapped} open trades to position cache for risk persistence")
            if restored > 0:
                print(f"[RISK] ✓ Restored full risk state for {restored} positions from database")
            return restored
        except Exception as e:
            print(f"[RISK] Warning: Could not restore risk state from DB: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def get_all_trade_id_keys(self) -> set:
        """Return set of position keys that have trade_id mappings (actively risk-managed)."""
        return set(self._trade_id_map.keys())

    def get_trade_id(self, position_key: str) -> Optional[int]:
        """Get trade_id for a position key, used for database persistence."""
        return self._trade_id_map.get(position_key)
    
    def set_trade_id(self, position_key: str, trade_id: int) -> None:
        """Store trade_id mapping for a position key."""
        self._trade_id_map[position_key] = trade_id
    
    def rename_key(self, old_key: str, new_key: str, trade_id: int = None) -> None:
        """Atomically migrate cache entry and trade_id mapping from old_key to new_key."""
        with self._cache_lock:
            if old_key in self._cache:
                self._cache[new_key] = self._cache.pop(old_key)
            if old_key in self._trade_id_map:
                tid = self._trade_id_map.pop(old_key)
                self._trade_id_map[new_key] = tid
            if trade_id is not None:
                self._trade_id_map[new_key] = trade_id
    
    def load(self) -> int:
        """Load cache from file. Returns number of positions loaded."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                
                closing_reset = 0
                bracket_reset = 0
                for key, entry_data in data.items():
                    entry = PositionCacheEntry.from_dict(entry_data)
                    if entry.closing:
                        entry.closing = False
                        entry.closing_cycles = 0
                        closing_reset += 1
                    if entry.broker_orders_placed and not entry.broker_stop_order_id and not entry.broker_pt_order_id:
                        entry.broker_orders_placed = False
                        entry._bracket_attempt_count = 0
                        bracket_reset += 1
                    self._cache[key] = entry
                
                if closing_reset > 0:
                    print(f"[RISK] ♻️ Cleared {closing_reset} stale closing flag(s) from previous session")
                if bracket_reset > 0:
                    print(f"[RISK] ♻️ Reset {bracket_reset} bracket flag(s) with no actual broker orders — will re-attempt")
                
                return len(self._cache)
        except Exception as e:
            print(f"[RISK] Warning: Could not load position cache: {e}")
        return 0
    
    def save(self) -> bool:
        """Save cache to file. Returns True on success."""
        try:
            data = {key: entry.to_dict() for key, entry in self._cache.items()}
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"[RISK] Warning: Could not save position cache: {e}")
            return False
    
    def get(self, position_key: str) -> Optional[PositionCacheEntry]:
        """Get cached entry for a position."""
        return self._cache.get(position_key)
    
    def get_position(self, symbol: str, broker: str = None, channel_id: str = None):
        """Find an open position by symbol using database as source of truth.
        Returns a lightweight object with qty, asset_type, broker, and option fields.
        
        Args:
            symbol: Stock/option ticker symbol
            broker: Optional broker filter for multi-broker setups
            channel_id: Optional channel filter
        """
        symbol_upper = symbol.upper()
        try:
            from gui_app.database import get_open_trades_with_trailing_state
            open_trades = get_open_trades_with_trailing_state()
            matches = []
            for trade in open_trades:
                if trade.get('symbol', '').upper() != symbol_upper:
                    continue
                if broker and trade.get('broker', '').upper() != broker.upper():
                    continue
                if channel_id and trade.get('channel_id') and str(trade['channel_id']) != str(channel_id):
                    continue
                matches.append(trade)
            
            if not matches:
                return None
            
            trade = matches[0]
            
            class PositionInfo:
                pass
            pos = PositionInfo()
            pos.qty = trade.get('quantity', 0)
            pos.asset_type = trade.get('asset_type', 'stock')
            pos.broker = trade.get('broker', '')
            pos.strike = trade.get('strike')
            pos.opt_type = trade.get('call_put')
            pos.expiry = trade.get('expiry')
            pos.entry_price = trade.get('entry_price', 0)
            pos.channel_id = trade.get('channel_id')
            pos.trade_id = trade.get('id')
            
            if pos.asset_type == 'option' and pos.strike:
                pos.position_key = f"{pos.broker}_{symbol_upper}_{pos.strike}_{pos.expiry}_{pos.opt_type}"
            else:
                pos.position_key = f"{pos.broker}_{symbol_upper}_stock"
            
            return pos
        except Exception as e:
            print(f"[RISK] Warning: Could not look up position from DB: {e}")
            return None
    
    def get_or_create(self, position: PositionSnapshot, 
                      stop_loss_price: Optional[float] = None,
                      profit_target_price: Optional[float] = None,
                      db_price_targets: Optional[Dict[str, Dict[str, Any]]] = None) -> PositionCacheEntry:
        """Get existing cache entry or create new one.
        
        Args:
            position: Position snapshot
            stop_loss_price: Override stop loss price
            profit_target_price: Override profit target price
            db_price_targets: Dict of db_key -> {stop_loss_price, profit_target_price}
        """
        pos_key = position.position_key
        
        if pos_key not in self._cache:
            sl_price = stop_loss_price
            target_price = profit_target_price
            
            if db_price_targets and position.db_key in db_price_targets:
                db_targets = db_price_targets[position.db_key]
                sl_price = sl_price or db_targets.get('stop_loss_price')
                target_price = target_price or db_targets.get('profit_target_price')
            
            entry = PositionCacheEntry(
                entry_price=position.avg_cost,
                highest_price=position.current_price,
                broker=position.broker,
                raw_symbol=position.raw_symbol,
                stop_loss_price=sl_price,
                profit_target_price=target_price,
                original_qty=int(position.quantity)
            )
            self._cache[pos_key] = entry
            
            trade_id = self._trade_id_map.get(pos_key)
            if trade_id:
                try:
                    from gui_app.database import load_risk_state
                    saved_state = load_risk_state(trade_id)
                    if saved_state:
                        has_state = False
                        if saved_state.get('pt1_hit'):
                            entry.tier1_hit = True
                            has_state = True
                        if saved_state.get('pt2_hit'):
                            entry.tier2_hit = True
                            has_state = True
                        if saved_state.get('pt3_hit'):
                            entry.tier3_hit = True
                            has_state = True
                        if saved_state.get('pt4_hit'):
                            entry.tier4_hit = True
                            has_state = True
                        if saved_state.get('dynamic_sl_price'):
                            entry.dynamic_sl_price = saved_state['dynamic_sl_price']
                            has_state = True
                        if saved_state.get('giveback_guard_active'):
                            entry.giveback_guard_active = True
                            has_state = True
                        if saved_state.get('max_pnl_seen'):
                            entry.max_pnl_seen = saved_state['max_pnl_seen']
                            has_state = True
                        if saved_state.get('trailing_activated'):
                            entry.trailing_activated = True
                            has_state = True
                        if saved_state.get('quantity') and saved_state['quantity'] > 0:
                            entry.original_qty = int(saved_state['quantity'])
                        if saved_state.get('highest_price'):
                            entry.highest_price = max(entry.highest_price, saved_state['highest_price'])
                        if saved_state.get('risk_settings_hash'):
                            entry.risk_settings_hash = saved_state['risk_settings_hash']
                        if has_state:
                            tier_str = f"PT1={entry.tier1_hit} PT2={entry.tier2_hit} PT3={entry.tier3_hit} PT4={entry.tier4_hit}"
                            print(f"[RISK] ✓ Restored risk state on cache creation: {pos_key} | {tier_str}")
                except Exception as e:
                    print(f"[RISK] Warning: Could not load risk state for {pos_key}: {e}")
            
            if sl_price or target_price:
                print(f"[RISK] New position tracked: {pos_key} @ ${position.avg_cost:.2f} | "
                      f"SL: ${sl_price or 'N/A'} | Target: ${target_price or 'N/A'}")
            else:
                print(f"[RISK] New position tracked: {pos_key} @ ${position.avg_cost:.2f}")
        else:
            cached_entry = self._cache[pos_key]
            broker_entry_price = position.avg_cost
            if broker_entry_price > 0 and abs(cached_entry.entry_price - broker_entry_price) > 0.001:
                old_price = cached_entry.entry_price
                is_trade_rollover = False
                pct_diff = abs(broker_entry_price - old_price) / old_price if old_price > 0 else 1.0
                is_material = self._entry_change_is_material(old_price, broker_entry_price)
                if is_material:
                    current_trade_id = self._trade_id_map.get(pos_key)
                    if current_trade_id:
                        try:
                            from gui_app.database import get_db
                            db = get_db()
                            cursor = db.execute("SELECT status FROM trades WHERE id = ?", (current_trade_id,))
                            row = cursor.fetchone()
                            if row and row[0] in ('CLOSED', 'CANCELLED', 'CANCELED', 'EXPIRED', 'REJECTED'):
                                is_trade_rollover = True
                                print(f"[RISK] 🔄 Trade rollover detected: {pos_key} trade #{current_trade_id} is {row[0]}, "
                                      f"price ${old_price:.2f} → ${broker_entry_price:.2f} — resetting all risk state")
                                del self._trade_id_map[pos_key]
                        except Exception as e:
                            print(f"[RISK] ⚠️ Could not check trade status for rollover: {e}")
                if is_trade_rollover or cached_entry.closing or cached_entry.giveback_guard_active or cached_entry.early_trailing_active:
                    print(f"[RISK] ♻️  New position detected at same key {pos_key}: ${old_price:.2f} → ${broker_entry_price:.2f}")
                    print(f"[RISK]   Resetting stale risk state (giveback={cached_entry.giveback_guard_active}, "
                          f"max_pnl={cached_entry.max_pnl_seen:.1f}%, early_trail={cached_entry.early_trailing_active}, "
                          f"closing={cached_entry.closing})")
                    cached_entry.entry_price = broker_entry_price
                    cached_entry.highest_price = broker_entry_price
                    cached_entry.trailing_activated = False
                    cached_entry.trailing_stop_price = None
                    cached_entry.closing = False
                    cached_entry.closing_cycles = 0
                    cached_entry.tier1_hit = False
                    cached_entry.tier2_hit = False
                    cached_entry.tier3_hit = False
                    cached_entry.tier4_hit = False
                    cached_entry.max_pnl_seen = 0.0
                    cached_entry.dynamic_sl_price = None
                    cached_entry.giveback_guard_active = False
                    cached_entry.last_evaluated_price = None
                    cached_entry.early_trailing_active = False
                    cached_entry.early_stop_price = None
                    cached_entry.early_steps_locked = 0
                    cached_entry.exit_retry_count = 0
                    cached_entry.exit_retry_cooldown_until = None
                    cached_entry.last_exit_failure_reason = None
                    cached_entry.use_market_order = False
                    cached_entry.pending_orders = {}
                    cached_entry.manual_sl_price = None
                    cached_entry.manual_sl_pct = None
                    cached_entry.manual_pt_targets = None
                    cached_entry.source_order_id = None
                    cached_entry.source_trade_id = None
                    cached_entry.seed_time = None
                    if pos_key in self._locked_entry_prices:
                        del self._locked_entry_prices[pos_key]
                    if pos_key in self._last_entry_prices:
                        del self._last_entry_prices[pos_key]
                    self._guard_against_corrupt_risk_levels(pos_key, cached_entry, old_price, broker_entry_price)
                else:
                    if pos_key in self._locked_entry_prices:
                        locked = self._locked_entry_prices[pos_key]
                        if abs(cached_entry.entry_price - locked) < 0.001:
                            pass
                        else:
                            cached_entry.entry_price = locked
                    else:
                        if not is_material:
                            pass
                        else:
                            history = self._last_entry_prices.get(pos_key, [])
                            is_flip_flop = any(abs(broker_entry_price - h) < 0.001 for h in history)
                            history.append(old_price)
                            if len(history) > self.FLIP_FLOP_HISTORY_SIZE:
                                history = history[-self.FLIP_FLOP_HISTORY_SIZE:]
                            self._last_entry_prices[pos_key] = history
                            if is_flip_flop:
                                first_price = history[0]
                                self._locked_entry_prices[pos_key] = first_price
                                cached_entry.entry_price = first_price
                                print(f"[RISK] 🔒 Flip-flop detected for {pos_key}: locking entry price to ${first_price:.2f} "
                                      f"(suppressed ${old_price:.2f} → ${broker_entry_price:.2f})")
                            else:
                                cached_entry.entry_price = broker_entry_price
                                print(f"[RISK] ✓ Updated {pos_key} entry price: ${old_price:.2f} → ${broker_entry_price:.2f} (broker sync)")
                                self._guard_against_corrupt_risk_levels(pos_key, cached_entry, old_price, broker_entry_price)
        
        return self._cache[pos_key]
    
    def _guard_against_corrupt_risk_levels(self, pos_key: str, cached_entry,
                                           old_entry_price: float,
                                           new_entry_price: float) -> None:
        """After an entry-price correction, detect and clear stop-loss /
        profit-target values that are now mathematically impossible for a long
        position (SL must be below entry, PT must be above entry).

        This is a safety net: if a stale linked-conditional or DB-loaded SL was
        based on a different (wrong) entry price, the corrected entry will
        expose it as guaranteed-to-trigger nonsense. Clearing forces a clean
        re-derivation on the next risk evaluation cycle.

        Conservative scope:
        - Only clears when SL/PT are clearly invalid (>= or <= new entry).
        - Skipped when trailing has activated or meaningful profit was seen,
          because in those states an SL above the original entry is legitimate
          (locked-in profit / break-even stop).
        - Manual overrides (manual_sl_price / manual_pt_targets) are NOT
          touched — user-set values win.
        """
        try:
            if getattr(cached_entry, 'trailing_activated', False):
                return
            if getattr(cached_entry, 'max_pnl_seen', 0.0) >= 0.5:
                return
            if getattr(cached_entry, 'manual_sl_price', None) is not None:
                return

            sl = getattr(cached_entry, 'stop_loss_price', None)
            pt = getattr(cached_entry, 'profit_target_price', None)

            if sl is not None and sl > 0 and sl >= new_entry_price:
                print(f"[RISK] ⚠️ CORRUPT SL DETECTED for {pos_key}: stored SL=${sl:.4f} "
                      f">= corrected entry=${new_entry_price:.4f} (was based on stale entry "
                      f"${old_entry_price:.4f}). Clearing — will re-derive next cycle.")
                cached_entry.stop_loss_price = None
                cached_entry.source_order_id = None

            if pt is not None and pt > 0 and pt <= new_entry_price:
                print(f"[RISK] ⚠️ CORRUPT PT DETECTED for {pos_key}: stored PT=${pt:.4f} "
                      f"<= corrected entry=${new_entry_price:.4f} (was based on stale entry "
                      f"${old_entry_price:.4f}). Clearing — will re-derive next cycle.")
                cached_entry.profit_target_price = None
        except Exception as guard_err:
            print(f"[RISK] ⚠️ Corruption guard error for {pos_key}: {guard_err}")

    def update_from_db(self, position_key: str, 
                       stop_loss_price: Optional[float],
                       profit_target_price: Optional[float]) -> None:
        """Update cache entry with database values."""
        if position_key in self._cache:
            self._cache[position_key].stop_loss_price = stop_loss_price
            self._cache[position_key].profit_target_price = profit_target_price
            if stop_loss_price or profit_target_price:
                print(f"[RISK] Loaded from DB: {position_key} SL=${stop_loss_price} Target=${profit_target_price}")
    
    def update_position_sl_override(self, symbol: str, channel_id: str,
                                    sl_price: Optional[float] = None,
                                    sl_pct: Optional[float] = None,
                                    pt_targets: Optional[list] = None) -> list:
        """Update manual SL/PT overrides for filled positions matching symbol/channel.
        
        Called when signal provider posts follow-up like "moving SL to 1.88".
        Returns list of position keys that were updated.
        
        Args:
            symbol: Stock symbol to match (e.g., "BOXL")
            channel_id: Channel ID where the follow-up was posted
            sl_price: Fixed price SL override (e.g., 1.88)
            sl_pct: Percentage SL override (e.g., 11.0 for 11%)
            pt_targets: Profit target prices list override
        """
        updated_keys = []
        symbol_upper = symbol.upper() if symbol else None
        
        for pos_key, entry in self._cache.items():
            if entry.closing:
                continue
                
            pos_symbol = pos_key.split('_')[1] if '_' in pos_key else None
            if pos_symbol and symbol_upper and pos_symbol.upper() == symbol_upper:
                update_parts = []
                
                if sl_price is not None:
                    entry.manual_sl_price = sl_price
                    entry.manual_sl_pct = None
                    update_parts.append(f"SL=${sl_price:.2f}")
                    
                if sl_pct is not None:
                    entry.manual_sl_pct = sl_pct
                    entry.manual_sl_price = None
                    update_parts.append(f"SL={sl_pct:.1f}%")
                    
                if pt_targets is not None:
                    entry.manual_pt_targets = pt_targets
                    update_parts.append(f"PT={pt_targets}")
                
                if update_parts:
                    updated_keys.append(pos_key)
                    print(f"[FOLLOW-UP] ✓ Updated {pos_key}: {', '.join(update_parts)} (signal provider override)")
                    
                    trade_id = self._trade_id_map.get(pos_key)
                    if trade_id:
                        try:
                            from gui_app.database import update_trade_sl_override
                            update_trade_sl_override(trade_id, sl_price, sl_pct)
                        except Exception as e:
                            print(f"[FOLLOW-UP] Warning: Could not persist SL override to DB: {e}")
        
        return updated_keys
    
    def get_positions_by_symbol(self, symbol: str) -> list:
        """Get all active (non-closing) positions for a given symbol."""
        results = []
        symbol_upper = symbol.upper() if symbol else None
        
        for pos_key, entry in self._cache.items():
            if entry.closing:
                continue
            pos_symbol = pos_key.split('_')[1] if '_' in pos_key else None
            if pos_symbol and symbol_upper and pos_symbol.upper() == symbol_upper:
                results.append({
                    'position_key': pos_key,
                    'entry_price': entry.entry_price,
                    'broker': entry.broker,
                    'trade_id': self._trade_id_map.get(pos_key)
                })
        return results
    
    def is_closing(self, position_key: str) -> bool:
        """Check if position is in closing state, with auto-reset after wall-clock timeout."""
        import time as _time
        entry = self._cache.get(position_key)
        if not entry:
            return False
        
        if entry.closing:
            closing_since = getattr(entry, 'closing_since', 0) or 0
            if closing_since > 0:
                elapsed = _time.monotonic() - closing_since
                if elapsed >= self.CLOSING_TIMEOUT_SECONDS:
                    _has_active_chaser = False
                    try:
                        from src.risk.position_monitor import risk_manager_instance
                        if risk_manager_instance:
                            _chaser = getattr(risk_manager_instance, '_order_chaser', None)
                            if _chaser and hasattr(_chaser, '_tracked_orders'):
                                for _oid, _to in list(_chaser._tracked_orders.items()):
                                    if getattr(_to, 'position_key', None) == position_key:
                                        _has_active_chaser = True
                                        break
                    except Exception:
                        pass
                    if _has_active_chaser:
                        print(f"[RISK] ⏳ {position_key}: Closing timeout ({elapsed:.0f}s) but chaser still active — keeping closing flag")
                        return True
                    print(f"[RISK] ⚠️ {position_key}: Position still exists after {elapsed:.0f}s "
                          f"closing — resetting closing flag")
                    entry.reset_closing()
                    try:
                        from src.risk.position_monitor import risk_manager_instance
                        if risk_manager_instance:
                            risk_manager_instance.release_exit_marker(position_key)
                    except Exception:
                        pass
                    return False
            else:
                entry.closing_cycles += 1
                if entry.closing_cycles >= 60:
                    entry.reset_closing()
                    return False
            
            return True
        return False
    
    def mark_closing(self, position_key: str, is_partial: bool = False) -> None:
        """Mark position as being closed."""
        import time as _time
        if position_key in self._cache and not is_partial:
            self._cache[position_key].closing = True
            self._cache[position_key].closing_cycles = 0
            self._cache[position_key].closing_since = _time.monotonic()
            print(f"[RISK] Marked {position_key} as closing (prevent duplicate triggers)")
    
    def reset_closing(self, position_key: str) -> None:
        """Reset closing state (e.g., after order failure)."""
        if position_key in self._cache:
            self._cache[position_key].reset_closing()
    
    def record_exit_failure(self, position_key: str, reason: str, is_stop_loss: bool = False) -> bool:
        """Record a failed exit attempt. Returns True if more retries allowed.
        
        Args:
            position_key: Position identifier
            reason: Failure reason message
            is_stop_loss: If True, use emergency fast retry (5s, 10s, 15s max)
        """
        entry = self._cache.get(position_key)
        if entry:
            entry.record_exit_failure(reason, is_stop_loss=is_stop_loss)
            entry.reset_closing()  # Allow retry after cooldown
            return entry.can_retry_exit()
        return False
    
    def can_retry_exit(self, position_key: str) -> bool:
        """Check if position can retry exit (within limits and cooldown expired)."""
        entry = self._cache.get(position_key)
        if not entry:
            return True  # New position, can try
        return entry.can_retry_exit()
    
    def is_permanent_failure(self, position_key: str) -> bool:
        """Check if position has a permanent/unrecoverable failure (expired symbol, etc.)."""
        entry = self._cache.get(position_key)
        if not entry:
            return False
        return getattr(entry, 'permanent_failure', False)
    
    def get_permanent_failure_reason(self, position_key: str) -> Optional[str]:
        """Get the reason for permanent failure, if any."""
        entry = self._cache.get(position_key)
        if not entry:
            return None
        return getattr(entry, 'permanent_failure_reason', None)
    
    def get_retry_state(self, position_key: str) -> dict:
        """Get retry state for debugging/logging."""
        entry = self._cache.get(position_key)
        if not entry:
            return {'retry_count': 0, 'cooldown_remaining': 0, 'use_market': False, 'extended_mode': False, 'emergency_mode': False, 'permanent_failure': False}
        return {
            'retry_count': entry.exit_retry_count,
            'max_retries': entry.MAX_FAST_RETRIES,
            'cooldown_remaining': entry.retry_cooldown_remaining(),
            'use_market': entry.use_market_order,
            'extended_mode': entry.in_extended_retry_mode(),
            'emergency_mode': getattr(entry, 'is_emergency_exit', False),
            'last_failure': entry.last_exit_failure_reason,
            'permanent_failure': getattr(entry, 'permanent_failure', False),
            'permanent_failure_reason': getattr(entry, 'permanent_failure_reason', None)
        }
    
    def reset_exit_retry_state(self, position_key: str) -> None:
        """Reset retry state after successful exit."""
        entry = self._cache.get(position_key)
        if entry:
            entry.reset_exit_retry_state()
    
    def clear_retry_state(self, position_key: str) -> None:
        """Clear retry state and closing flag to allow immediate retry after conflicting order cancel."""
        entry = self._cache.get(position_key)
        if entry:
            entry.reset_exit_retry_state()
            entry.closing = False
            entry.use_market_order = True  # Use market order on retry after cancel
            print(f"[CACHE] ✓ Cleared retry state for {position_key} - ready for immediate retry")
    
    def should_use_market_order(self, position_key: str) -> bool:
        """Check if should use market order (after limit failures)."""
        entry = self._cache.get(position_key)
        return entry.use_market_order if entry else False
    
    def is_in_extended_mode(self, position_key: str) -> bool:
        """Check if position is in extended retry mode (persistent 5-min retries)."""
        entry = self._cache.get(position_key)
        return entry.in_extended_retry_mode() if entry else False
    
    def needs_extended_notification(self, position_key: str) -> bool:
        """Check if Discord notification needed for entering extended mode."""
        entry = self._cache.get(position_key)
        return entry.needs_extended_notification() if entry else False
    
    def mark_tier_hit(self, position_key: str, tier: int) -> None:
        """Mark a profit tier as hit (only call after confirmed fill) and persist to database."""
        entry = self._cache.get(position_key)
        if entry:
            tier_field = None
            if tier == 1:
                entry.tier1_hit = True
                tier_field = 'pt1_hit'
            elif tier == 2:
                entry.tier2_hit = True
                tier_field = 'pt2_hit'
            elif tier == 3:
                entry.tier3_hit = True
                tier_field = 'pt3_hit'
            elif tier == 4:
                entry.tier4_hit = True
                tier_field = 'pt4_hit'
            
            if tier_field:
                trade_id = self.get_trade_id(position_key)
                if trade_id:
                    with self._persist_lock:  # Thread-safe DB write
                        try:
                            from gui_app.database import save_risk_state
                            save_risk_state(trade_id, **{tier_field: True})
                            print(f"[RISK] ✓ Persisted tier {tier} hit for trade #{trade_id}")
                        except Exception as e:
                            print(f"[RISK] Warning: Could not persist tier hit: {e}")
    
    def add_pending_order(self, position_key: str, order_id: str, tier: int, qty: int, trade_id: int = None) -> bool:
        """Track a pending risk order awaiting fill confirmation."""
        entry = self._cache.get(position_key)
        if not entry:
            print(f"[RISK] ⚠️ Creating cache entry for pending order: {position_key}")
            entry = PositionCacheEntry(entry_price=0, highest_price=0)
            self._cache[position_key] = entry
        if trade_id is None:
            trade_id = self._trade_id_map.get(position_key)
        entry.add_pending_order(order_id, tier, qty, trade_id=trade_id)
        print(f"[RISK] 📋 Pending order tracked: {position_key} tier={tier} order={order_id} qty={qty} trade_id={trade_id}")
        return True
    
    def has_pending_order_for_tier(self, position_key: str, tier: int) -> bool:
        """Check if there's already a pending order for this tier."""
        entry = self._cache.get(position_key)
        if entry:
            return entry.has_pending_order_for_tier(tier)
        return False
    
    def confirm_order_fill(self, position_key: str, order_id: str, qty_filled: int) -> bool:
        """Confirm order fill and mark tier as hit. Returns True if tier marked."""
        entry = self._cache.get(position_key)
        if not entry:
            return False
        
        order_data = entry.pending_orders.get(order_id)
        if not order_data:
            return False
        
        stored_trade_id = order_data.get('trade_id')
        current_trade_id = self._trade_id_map.get(position_key)
        if stored_trade_id and current_trade_id and stored_trade_id != current_trade_id:
            print(f"[RISK] ⚠️ Rejected stale fill for {position_key}: order {order_id} belongs to "
                  f"trade #{stored_trade_id}, current trade is #{current_trade_id}")
            entry.remove_pending_order(order_id)
            return False
        
        tier = order_data.get('tier', 0)
        qty_expected = order_data.get('qty_expected', 0)
        
        if qty_filled >= qty_expected:
            entry.update_pending_order(order_id, 'filled', qty_filled)
            entry.remove_pending_order(order_id)
            if tier > 0:
                self.mark_tier_hit(position_key, tier)
                print(f"[RISK] ✅ Order {order_id} FILLED - Tier {tier} marked as hit")
            return True
        elif qty_filled > 0:
            entry.update_pending_order(order_id, 'partial', qty_filled)
            print(f"[RISK] ⚠️ Order {order_id} PARTIAL fill: {qty_filled}/{qty_expected}")
            return False
        return False
    
    def fail_pending_order(self, position_key: str, order_id: str) -> int:
        """Mark pending order as failed. Returns tier number if found."""
        entry = self._cache.get(position_key)
        if not entry:
            return 0
        
        tier = entry.update_pending_order(order_id, 'failed', 0)
        if tier:
            entry.remove_pending_order(order_id)
            print(f"[RISK] ❌ Order {order_id} FAILED - Tier {tier} NOT marked (will retry)")
        return tier or 0
    
    def get_all_pending_orders(self) -> dict:
        """Get all pending orders across all positions for reconciliation."""
        all_pending = {}
        for pos_key, entry in self._cache.items():
            if entry.pending_orders:
                all_pending[pos_key] = entry.pending_orders.copy()
        return all_pending
    
    def set_all_tiers_hit(self, position_key: str) -> None:
        """Mark all tiers as hit (for small positions closing at T1)."""
        entry = self._cache.get(position_key)
        if entry:
            entry.tier1_hit = True
            entry.tier2_hit = True
            entry.tier3_hit = True
            entry.tier4_hit = True
    
    def activate_trailing_stop(self, position_key: str, trade_id: int = None) -> None:
        """Activate trailing stop for a position and persist to database."""
        if position_key in self._cache:
            entry = self._cache[position_key]
            entry.trailing_activated = True
            
            # Persist to database for survival across restarts
            if trade_id:
                try:
                    from gui_app.database import save_trailing_state
                    save_trailing_state(trade_id, True, entry.highest_price)
                except Exception as e:
                    print(f"[RISK] Warning: Could not persist trailing state: {e}")
    
    def update_highest_price(self, position_key: str, current_price: float, verbose: bool = True, trade_id: int = None) -> None:
        """Update highest price for trailing stop calculation and persist if trailing is active."""
        entry = self._cache.get(position_key)
        if entry:
            old_highest = entry.highest_price
            entry.update_highest_price(current_price, position_key=position_key, verbose=verbose)
            
            # Persist to database if trailing is activated and highest price changed
            if entry.trailing_activated and trade_id and entry.highest_price > old_highest:
                try:
                    from gui_app.database import save_trailing_state
                    save_trailing_state(trade_id, True, entry.highest_price)
                except Exception as e:
                    print(f"[RISK] Warning: Could not persist highest price: {e}")
    
    def update_enhanced_risk_state(self, position_key: str, **kwargs) -> None:
        """
        Update enhanced risk state and persist to database.
        
        Supported kwargs:
            dynamic_sl_price: float - current dynamic stop loss price
            giveback_guard_active: bool - whether giveback guard is active
            max_pnl_seen: float - maximum P&L percentage seen
            trailing_stop_price: float - current trailing stop price
        """
        entry = self._cache.get(position_key)
        if not entry:
            return
        
        for key, value in kwargs.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        
        trade_id = self.get_trade_id(position_key)
        if trade_id:
            with self._persist_lock:
                try:
                    from gui_app.database import save_risk_state
                    db_kwargs = {}
                    for k, v in kwargs.items():
                        if k.startswith('tier') and k.endswith('_hit'):
                            db_kwargs[k.replace('tier', 'pt')] = v
                        else:
                            db_kwargs[k] = v
                    save_risk_state(trade_id, **db_kwargs)
                except Exception as e:
                    print(f"[RISK] Warning: Could not persist enhanced risk state: {e}")
    
    def get_all_risk_states(self) -> dict:
        """Export all monitored position risk states for the UI dashboard.
        Returns a dict keyed by trade_id (or pos_key fallback) with risk state details."""
        result = {}
        with self._cache_lock:
            cache_snapshot = dict(self._cache)
        for pos_key, entry in cache_snapshot.items():
            trade_id = self._trade_id_map.get(pos_key)
            state_key = str(trade_id) if trade_id else pos_key
            
            cs = entry.channel_settings
            
            sl_price = entry.stop_loss_price
            pt_price = entry.profit_target_price
            ep = entry.entry_price
            if ep and ep > 0 and cs:
                if sl_price is None and hasattr(cs, 'stop_loss_pct') and cs.stop_loss_pct and cs.stop_loss_pct > 0:
                    sl_price = ep * (1 - cs.stop_loss_pct / 100.0)
                if pt_price is None and hasattr(cs, 'profit_target_1_pct') and cs.profit_target_1_pct and cs.profit_target_1_pct > 0:
                    _next_pct = cs.profit_target_1_pct
                    if entry.tier1_hit and hasattr(cs, 'profit_target_2_pct') and cs.profit_target_2_pct and cs.profit_target_2_pct > 0:
                        _next_pct = cs.profit_target_2_pct
                    if entry.tier2_hit and hasattr(cs, 'profit_target_3_pct') and cs.profit_target_3_pct and cs.profit_target_3_pct > 0:
                        _next_pct = cs.profit_target_3_pct
                    if entry.tier3_hit and hasattr(cs, 'profit_target_4_pct') and cs.profit_target_4_pct and cs.profit_target_4_pct > 0:
                        _next_pct = cs.profit_target_4_pct
                    pt_price = ep * (1 + _next_pct / 100.0)
            
            _effective_sl = entry.dynamic_sl_price or entry.early_stop_price or sl_price
            has_stop_loss = _effective_sl is not None
            has_profit_target = pt_price is not None
            
            early_trail_enabled = bool(cs and cs.enable_early_trailing) if cs else False
            giveback_enabled = bool(cs and cs.enable_giveback_guard) if cs else False
            trailing_enabled = bool(cs and cs.trailing_stop_pct and cs.trailing_stop_pct > 0) if cs else False
            dynamic_sl_enabled = bool(cs and cs.enable_dynamic_sl) if cs else False
            
            current_pnl_pct = 0.0
            if ep and ep > 0 and entry.last_evaluated_price:
                current_pnl_pct = ((entry.last_evaluated_price - ep) / ep) * 100
            
            tiers_hit = []
            if entry.tier1_hit:
                tiers_hit.append(1)
            if entry.tier2_hit:
                tiers_hit.append(2)
            if entry.tier3_hit:
                tiers_hit.append(3)
            if entry.tier4_hit:
                tiers_hit.append(4)
            
            result[state_key] = {
                'position_key': pos_key,
                'monitoring': True,
                'entry_price': ep,
                'highest_price': entry.highest_price,
                'current_price': entry.last_evaluated_price,
                'current_pnl_pct': round(current_pnl_pct, 2),
                'max_pnl_seen': round(entry.max_pnl_seen, 2),
                'stop_loss_active': has_stop_loss,
                'stop_loss_price': _effective_sl if _effective_sl else sl_price,
                'stop_loss_pct': cs.stop_loss_pct if cs and hasattr(cs, 'stop_loss_pct') else None,
                'profit_target_active': has_profit_target,
                'profit_target_price': pt_price,
                'profit_target_pcts': [
                    cs.profit_target_1_pct if cs and hasattr(cs, 'profit_target_1_pct') else None,
                    cs.profit_target_2_pct if cs and hasattr(cs, 'profit_target_2_pct') else None,
                    cs.profit_target_3_pct if cs and hasattr(cs, 'profit_target_3_pct') else None,
                ],
                'trailing_enabled': trailing_enabled,
                'trailing_activated': entry.trailing_activated,
                'trailing_stop_price': entry.trailing_stop_price,
                'early_trail_enabled': early_trail_enabled,
                'early_trailing_active': entry.early_trailing_active,
                'early_stop_price': entry.early_stop_price,
                'early_steps_locked': entry.early_steps_locked or 0,
                'early_activation_pct': cs.early_trailing_activation_pct if cs and hasattr(cs, 'early_trailing_activation_pct') else None,
                'early_step_pct': cs.early_trailing_step_pct if cs and hasattr(cs, 'early_trailing_step_pct') else None,
                'giveback_enabled': giveback_enabled,
                'giveback_guard_active': entry.giveback_guard_active,
                'giveback_allowed_pct': cs.giveback_allowed_pct if cs else None,
                'dynamic_sl_enabled': dynamic_sl_enabled,
                'dynamic_sl_price': entry.dynamic_sl_price,
                'tiers_hit': tiers_hit,
                'closing': entry.closing,
                'channel_name': cs.channel_name if cs and hasattr(cs, 'channel_name') else None,
                'exit_mode': cs.exit_strategy_mode if cs and hasattr(cs, 'exit_strategy_mode') else None,
            }
        return result

    def persist_early_trailing_state(self, position_key: str) -> None:
        """
        Persist early trailing stop state to database for restart resilience.
        Called when breakeven is locked or profit step is advanced.
        """
        entry = self._cache.get(position_key)
        if not entry:
            return
        
        trade_id = self.get_trade_id(position_key)
        if trade_id:
            with self._persist_lock:
                try:
                    from gui_app.database import save_risk_state
                    save_risk_state(
                        trade_id,
                        early_trailing_active=entry.early_trailing_active,
                        early_stop_price=entry.early_stop_price,
                        early_steps_locked=entry.early_steps_locked,
                        highest_price=entry.highest_price
                    )
                except Exception as e:
                    print(f"[RISK] Warning: Could not persist early trailing state: {e}")
    
    def apply_settings_with_versioning(self, position_key: str, settings) -> bool:
        """
        Apply channel settings to a position with versioning support.
        Implements prospective-only policy: if settings changed, previously hit
        tiers remain hit; only new thresholds apply going forward.
        
        Returns True if settings were applied (new or compatible), False if rejected.
        """
        entry = self._cache.get(position_key)
        if not entry:
            return False
        
        if settings is None:
            return False
        
        new_hash = settings.compute_settings_hash()
        
        if entry.risk_settings_hash is None:
            entry.risk_settings_hash = new_hash
            entry.channel_settings = settings
            trade_id = self.get_trade_id(position_key)
            if trade_id:
                with self._persist_lock:
                    try:
                        from gui_app.database import save_risk_state
                        save_risk_state(trade_id, risk_settings_hash=new_hash)
                    except Exception as e:
                        print(f"[RISK] Warning: Could not persist settings hash: {e}")
            return True
        
        if entry.risk_settings_hash != new_hash:
            tier_status = f"PT1={entry.tier1_hit} PT2={entry.tier2_hit} PT3={entry.tier3_hit} PT4={entry.tier4_hit}"
            print(f"[RISK] Settings changed for {position_key}: old={entry.risk_settings_hash[:8]}... new={new_hash[:8]}... "
                  f"| Applying prospective-only (existing tiers: {tier_status})")
            entry.risk_settings_hash = new_hash
            trade_id = self.get_trade_id(position_key)
            if trade_id:
                with self._persist_lock:
                    try:
                        from gui_app.database import save_risk_state
                        save_risk_state(trade_id, risk_settings_hash=new_hash)
                    except Exception as e:
                        print(f"[RISK] Warning: Could not persist settings hash: {e}")
        
        entry.channel_settings = settings
        return True
    
    def populate_trade_id_mappings(self) -> int:
        """
        Populate trade_id mappings for all open trades from database.
        Call this after broker sync to ensure all positions can persist state.
        Returns count of mappings added.
        """
        try:
            from gui_app.database import get_open_trades_with_risk_state
            trades = get_open_trades_with_risk_state()
            added = 0
            
            for trade in trades:
                raw_broker = trade['broker'] or 'UNKNOWN'
                broker = self._normalize_broker_name(raw_broker)
                asset_type = trade['asset_type'] or 'stock'
                
                if asset_type == 'option' and trade['strike']:
                    expiry = self._normalize_expiry(trade['expiry'] or '')
                    pos_key = f"{broker}_{trade['symbol']}_{trade['strike']}_{expiry}_{trade['call_put']}"
                else:
                    pos_key = f"{broker}_{trade['symbol']}_stock"
                
                if pos_key not in self._trade_id_map:
                    self._trade_id_map[pos_key] = trade['id']
                    added += 1
            
            if added > 0:
                print(f"[RISK] ✓ Added {added} new trade_id mappings after broker sync")
            return added
        except Exception as e:
            print(f"[RISK] Warning: Could not populate trade_id mappings: {e}")
            return 0
    
    def set_channel_settings(self, position_key: str, settings) -> None:
        """Cache channel settings for a position."""
        if position_key in self._cache:
            self._cache[position_key].channel_settings = settings
    
    def invalidate_channel_settings(self, channel_id: str = None) -> int:
        """Invalidate cached channel settings to force refresh on next cycle.
        
        Args:
            channel_id: If provided, only invalidate settings for positions from this channel.
                       If None, invalidate all cached channel settings.
        
        Returns:
            Number of cache entries invalidated.
        """
        count = 0
        with self._cache_lock:
            for pos_key, entry in list(self._cache.items()):
                if entry.channel_settings is not None:
                    if channel_id is None:
                        entry.channel_settings = None
                        count += 1
                    elif entry.channel_settings.channel_id and str(entry.channel_settings.channel_id) == str(channel_id):
                        entry.channel_settings = None
                        count += 1
        
        if count > 0:
            print(f"[RISK] Invalidated channel settings cache for {count} positions")
        return count
    
    def remove(self, position_key: str) -> None:
        """Remove a position from cache and clean up stale trade_id mapping."""
        with self._cache_lock:
            self._cache.pop(position_key, None)
        old_trade_id = self._trade_id_map.pop(position_key, None)
        if old_trade_id:
            print(f"[RISK] ✓ Cleaned trade_id mapping: {position_key} (trade #{old_trade_id})")
        try:
            from src.risk.position_monitor import risk_manager_instance
            if risk_manager_instance:
                risk_manager_instance.release_exit_marker(position_key)
        except Exception:
            pass
    
    def has_any_pending_orders(self) -> bool:
        """Check if any cache entry has pending risk orders."""
        for entry in self._cache.values():
            if entry.pending_orders:
                return True
        return False

    def get_all_keys(self) -> list:
        """Get all position keys in the cache."""
        return list(self._cache.keys())

    def cleanup_stale(self, active_keys: set) -> int:
        """Remove cache entries not in active positions. Returns count removed."""
        stale_entries_with_brackets = []
        with self._cache_lock:
            stale = [k for k in self._cache.keys() if k not in active_keys]
            for key in stale:
                entry = self._cache[key]
                if hasattr(entry, 'broker_stop_order_id') or hasattr(entry, 'broker_pt_order_id'):
                    if getattr(entry, 'broker_stop_order_id', None) or getattr(entry, 'broker_pt_order_id', None):
                        stale_entries_with_brackets.append((key, entry))
                del self._cache[key]
                old_trade_id = self._trade_id_map.pop(key, None)
                if old_trade_id:
                    print(f"[RISK] ✓ Cleaned stale trade_id mapping: {key} (trade #{old_trade_id})")
                self._last_entry_prices.pop(key, None)
                self._locked_entry_prices.pop(key, None)
        for key in stale:
            try:
                from src.risk.position_monitor import risk_manager_instance
                if risk_manager_instance:
                    risk_manager_instance.release_exit_marker(key)
            except Exception:
                pass
        if stale_entries_with_brackets:
            try:
                from src.risk.position_monitor import risk_manager_instance
                if risk_manager_instance:
                    import asyncio
                    for key, entry in stale_entries_with_brackets:
                        _sl_id = getattr(entry, 'broker_stop_order_id', None)
                        _pt_id = getattr(entry, 'broker_pt_order_id', None)
                        print(f"[RISK] 🧹 Stale cache cleanup: cancelling orphaned bracket orders for {key} (SL={_sl_id}, PT={_pt_id})")
                        try:
                            parts = key.split('_', 1)
                            broker_name = parts[0].upper() if parts else ''
                            broker_inst = risk_manager_instance._get_broker_instance_for_bracket(broker_name)
                            asset_type = getattr(entry, 'asset_type', 'stock')
                            if broker_inst:
                                if _sl_id:
                                    asyncio.ensure_future(risk_manager_instance._cancel_single_order(broker_name, _sl_id, broker_inst, asset_type=asset_type))
                                if _pt_id:
                                    asyncio.ensure_future(risk_manager_instance._cancel_single_order(broker_name, _pt_id, broker_inst, asset_type=asset_type))
                        except Exception as ce:
                            print(f"[RISK] ⚠️ Could not schedule orphaned bracket cancel for {key}: {ce}")
                        entry.broker_stop_order_id = None
                        entry.broker_pt_order_id = None
            except Exception as e:
                print(f"[RISK] ⚠️ Stale bracket cleanup error: {e}")
        return len(stale)
    
    def __len__(self) -> int:
        return len(self._cache)
    
    def __contains__(self, key: str) -> bool:
        return key in self._cache
