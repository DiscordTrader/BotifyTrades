"""
Position Cache Management
=========================
Handles persistence and state management for monitored positions.
"""
import json
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime

from .risk_types import PositionCacheEntry, PositionSnapshot


class PositionCache:
    """Manages position state cache with file persistence."""
    
    CLOSING_CYCLE_RESET = 3  # Reset closing flag after this many cycles
    
    def __init__(self, cache_file: Optional[Path] = None):
        self.cache_file = cache_file or Path.cwd() / '.position_cache.json'
        self._cache: Dict[str, PositionCacheEntry] = {}
    
    def load(self) -> int:
        """Load cache from file. Returns number of positions loaded."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                
                for key, entry_data in data.items():
                    self._cache[key] = PositionCacheEntry.from_dict(entry_data)
                
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
                profit_target_price=target_price
            )
            self._cache[pos_key] = entry
            
            if sl_price or target_price:
                print(f"[RISK] New position tracked: {pos_key} @ ${position.avg_cost:.2f} | "
                      f"SL: ${sl_price or 'N/A'} | Target: ${target_price or 'N/A'}")
            else:
                print(f"[RISK] New position tracked: {pos_key} @ ${position.avg_cost:.2f}")
        
        return self._cache[pos_key]
    
    def update_from_db(self, position_key: str, 
                       stop_loss_price: Optional[float],
                       profit_target_price: Optional[float]) -> None:
        """Update cache entry with database values."""
        if position_key in self._cache:
            self._cache[position_key].stop_loss_price = stop_loss_price
            self._cache[position_key].profit_target_price = profit_target_price
            if stop_loss_price or profit_target_price:
                print(f"[RISK] Loaded from DB: {position_key} SL=${stop_loss_price} Target=${profit_target_price}")
    
    def is_closing(self, position_key: str) -> bool:
        """Check if position is in closing state, with auto-reset after 3 cycles."""
        entry = self._cache.get(position_key)
        if not entry:
            return False
        
        if entry.closing:
            entry.closing_cycles += 1
            
            if entry.closing_cycles >= self.CLOSING_CYCLE_RESET:
                print(f"[RISK] ⚠️ {position_key}: Position still exists after {entry.closing_cycles} "
                      f"closing cycles - resetting closing flag")
                entry.reset_closing()
                return False
            
            return True
        return False
    
    def mark_closing(self, position_key: str, is_partial: bool = False) -> None:
        """Mark position as being closed."""
        if position_key in self._cache and not is_partial:
            self._cache[position_key].closing = True
            self._cache[position_key].closing_cycles = 0
            print(f"[RISK] Marked {position_key} as closing (prevent duplicate triggers)")
    
    def reset_closing(self, position_key: str) -> None:
        """Reset closing state (e.g., after order failure)."""
        if position_key in self._cache:
            self._cache[position_key].reset_closing()
    
    def mark_tier_hit(self, position_key: str, tier: int) -> None:
        """Mark a profit tier as hit (only call after confirmed fill)."""
        entry = self._cache.get(position_key)
        if entry:
            if tier == 1:
                entry.tier1_hit = True
            elif tier == 2:
                entry.tier2_hit = True
            elif tier == 3:
                entry.tier3_hit = True
            elif tier == 4:
                entry.tier4_hit = True
    
    def add_pending_order(self, position_key: str, order_id: str, tier: int, qty: int) -> bool:
        """Track a pending risk order awaiting fill confirmation."""
        entry = self._cache.get(position_key)
        if not entry:
            # Create minimal entry if position not in cache yet (edge case)
            print(f"[RISK] ⚠️ Creating cache entry for pending order: {position_key}")
            entry = PositionCacheEntry(entry_price=0, highest_price=0)
            self._cache[position_key] = entry
        entry.add_pending_order(order_id, tier, qty)
        print(f"[RISK] 📋 Pending order tracked: {position_key} tier={tier} order={order_id} qty={qty}")
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
    
    def activate_trailing_stop(self, position_key: str) -> None:
        """Activate trailing stop for a position."""
        if position_key in self._cache:
            self._cache[position_key].trailing_activated = True
    
    def update_highest_price(self, position_key: str, current_price: float, verbose: bool = True) -> None:
        """Update highest price for trailing stop calculation."""
        entry = self._cache.get(position_key)
        if entry:
            entry.update_highest_price(current_price, position_key=position_key, verbose=verbose)
    
    def set_channel_settings(self, position_key: str, settings) -> None:
        """Cache channel settings for a position."""
        if position_key in self._cache:
            self._cache[position_key].channel_settings = settings
    
    def remove(self, position_key: str) -> None:
        """Remove a position from cache."""
        self._cache.pop(position_key, None)
    
    def cleanup_stale(self, active_keys: set) -> int:
        """Remove cache entries not in active positions. Returns count removed."""
        stale = [k for k in self._cache.keys() if k not in active_keys]
        for key in stale:
            del self._cache[key]
        return len(stale)
    
    def __len__(self) -> int:
        return len(self._cache)
    
    def __contains__(self, key: str) -> bool:
        return key in self._cache
