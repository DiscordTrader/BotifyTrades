"""
Position Monitor
================
Main async monitoring loop coordinating all risk strategies.

Enhanced with:
- Service enable gate (only fetch broker data when risk enabled)
- Standby loop for processing invalidations without API calls
- Integration with centralized RateLimitManager
"""
import asyncio
import re
from typing import Optional, List, Dict, Any, Callable, Awaitable
from pathlib import Path

from .risk_types import (
    PositionSnapshot,
    RiskSettings,
    ChannelRiskSettings,
    ExitDecision,
    PositionCacheEntry
)
from .position_cache import PositionCache
from .tiered_targets import evaluate_tiered_targets, format_tier_reason, evaluate_channel_stop_loss
from .global_risk import evaluate_global_risk, evaluate_price_based_stops
from .trailing_stop import evaluate_trailing_stop, get_effective_trailing_settings
from .early_trailing import evaluate_early_trailing, EarlyTrailingState
from .risk_engine import (
    evaluate_exit_actions, 
    TradeState, 
    RiskAction, 
    ActionType,
    DYNAMIC_SL_PROFILES
)

import threading

try:
    from src.services.rate_limit_manager import get_rate_limit_manager
    RATE_LIMIT_AVAILABLE = True
except ImportError:
    RATE_LIMIT_AVAILABLE = False
    get_rate_limit_manager = None

try:
    from src.services.exit_order_arbiter import exit_order_arbiter
    ARBITER_AVAILABLE = True
except ImportError:
    ARBITER_AVAILABLE = False
    exit_order_arbiter = None

# Global RiskManager instance for external access (e.g., Flask routes)
# Uses a simple flag to signal invalidation needed - processed by monitoring loop
_risk_manager_lock = threading.Lock()
risk_manager_instance: Optional['RiskManager'] = None
_invalidation_requested = threading.Event()

def set_risk_manager_instance(instance: 'RiskManager') -> None:
    """Set the global RiskManager instance for external access."""
    global risk_manager_instance
    with _risk_manager_lock:
        risk_manager_instance = instance
    print("[RISK] ✓ Global RiskManager instance registered for settings cache invalidation")

def request_settings_invalidation() -> bool:
    """
    Thread-safe request for cache invalidation from Flask WSGI threads.
    Sets a flag that the RiskManager monitoring loop will process.
    
    This approach avoids cross-thread cache mutation - the invalidation
    is processed by the same thread that owns the cache.
    
    Returns:
        True if request was queued, False if RiskManager unavailable
    """
    with _risk_manager_lock:
        if risk_manager_instance is None:
            return False
    _invalidation_requested.set()
    print("[RISK] Settings invalidation requested - will be processed on next monitoring cycle")
    return True

def check_and_process_invalidation_request() -> int:
    """
    Called by RiskManager monitoring loop to check and process invalidation requests.
    This ensures cache mutation happens on the owning thread.
    
    Returns:
        Number of cache entries invalidated, or 0 if no request pending
    """
    if not _invalidation_requested.is_set():
        return 0
    
    # Get instance reference while holding lock
    with _risk_manager_lock:
        instance = risk_manager_instance
    
    if instance is None:
        return 0
    
    try:
        count = instance.invalidate_settings_cache()
        # Clear flag only after successful invalidation
        _invalidation_requested.clear()
        print(f"[RISK] ✓ Processed settings invalidation request - {count} entries refreshed")
        return count
    except Exception as e:
        # Don't clear flag - will retry on next cycle
        print(f"[RISK] Error during cache invalidation (will retry): {e}")
        return 0


class RiskDBAdapter:
    """
    Database adapter for risk management operations.
    Wraps gui_app.database to decouple risk module from database implementation.
    
    Usage:
        # Option 1: Pass database instance directly (preferred for SelfClient)
        adapter = RiskDBAdapter(db=self.db)
        
        # Option 2: Auto-import gui_app.database (standalone use)
        adapter = RiskDBAdapter()
    """
    
    def __init__(self, db=None):
        self._db = None
        self._available = False
        
        if db is not None:
            self._db = db
            self._available = True
        else:
            try:
                from gui_app import database as db_module
                self._db = db_module
                self._available = True
            except ImportError:
                print("[RISK] Warning: gui_app.database not available - running in headless mode")
    
    @property
    def available(self) -> bool:
        return self._available
    
    def get_connection(self):
        """Get database connection."""
        if self._db:
            return self._db.get_connection()
        return None
    
    def count_channels_with_risk(self) -> int:
        """Count channels with risk management explicitly enabled."""
        if not self._db:
            return 0
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM channels 
                WHERE risk_management_enabled = 1
            ''')
            return cursor.fetchone()[0]
        except Exception as e:
            print(f"[RISK] Warning: Could not count channels with risk: {e}")
            return 0
    
    def _get_signal_routing_risk_settings(
        self,
        routing_mapping_id: int
    ) -> Optional[ChannelRiskSettings]:
        """
        Fetch risk settings from signal_routing_mappings by routing_mapping_id.
        Returns ChannelRiskSettings if mapping has explicit risk config, else None.
        
        This is ONLY called when the trade has a routing_mapping_id set (i.e., is a routed trade).
        This ensures non-routed trades are never affected.
        """
        if not self._db or not routing_mapping_id:
            return None
        
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, name, source_channel_id, stop_loss_pct, 
                       pt1_pct, pt2_pct, pt3_pct, pt4_pct,
                       pt1_qty, pt2_qty, pt3_qty, pt4_qty,
                       trailing_stop_pct, trailing_activation_pct, 
                       trim_order_type, leave_runner_enabled, leave_runner_size_pct,
                       dynamic_sl_escalation_enabled, sl_escalation_profile,
                       max_profit_giveback_enabled, max_profit_giveback_pct,
                       exit_strategy_mode, price_monitor_enabled,
                       enable_early_trailing, early_trailing_activation_pct, early_trailing_step_pct
                FROM signal_routing_mappings
                WHERE id = ? AND enabled = 1
                LIMIT 1
            ''', (routing_mapping_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            sl = row[3] or 0
            pt1 = row[4] or 0
            pt2 = row[5] or 0
            pt3 = row[6] or 0
            pt4 = row[7] or 0
            pt1_qty = row[8]
            pt2_qty = row[9]
            pt3_qty = row[10]
            pt4_qty = row[11]
            trail = row[12] or 0
            trail_activation = row[13] or 15.0
            trim_order_type = row[14] or 'market'
            leave_runner_enabled = bool(row[15]) if row[15] else False
            leave_runner_pct = row[16] or 25.0
            dynamic_sl_enabled = bool(row[17]) if row[17] else False
            sl_profile = row[18] or 'standard'
            giveback_enabled = bool(row[19]) if row[19] else False
            giveback_pct = row[20] or 30.0
            exit_mode = row[21] or 'risk'
            enable_early_trailing = bool(row[23]) if len(row) > 23 and row[23] else False
            early_trailing_activation_pct = row[24] if len(row) > 24 and row[24] is not None else 5.0
            early_trailing_step_pct = row[25] if len(row) > 25 and row[25] is not None else 3.0
            
            has_any_risk_config = (sl > 0 or pt1 > 0 or pt2 > 0 or pt3 > 0 or pt4 > 0 or trail > 0 or enable_early_trailing)
            
            if not has_any_risk_config:
                return None
            
            return ChannelRiskSettings(
                channel_id=str(row[2]),
                channel_name=row[1] or 'Signal Routing',
                profit_target_1_pct=pt1,
                profit_target_2_pct=pt2,
                profit_target_3_pct=pt3,
                profit_target_4_pct=pt4,
                profit_target_qty_1=pt1_qty,
                profit_target_qty_2=pt2_qty,
                profit_target_qty_3=pt3_qty,
                profit_target_qty_4=pt4_qty,
                stop_loss_pct=sl,
                trailing_stop_pct=trail,
                trailing_activation_pct=trail_activation,
                leave_runner_enabled=leave_runner_enabled,
                leave_runner_pct=leave_runner_pct,
                trim_order_mode=trim_order_type,
                trim_limit_offset=0.01,
                exit_strategy_mode=exit_mode,
                enable_dynamic_sl=dynamic_sl_enabled,
                dynamic_sl_profile=sl_profile,
                enable_giveback_guard=giveback_enabled,
                giveback_allowed_pct=giveback_pct,
                enable_early_trailing=enable_early_trailing,
                early_trailing_activation_pct=early_trailing_activation_pct,
                early_trailing_step_pct=early_trailing_step_pct
            )
        except Exception as e:
            print(f"[RISK] Warning: Could not fetch signal routing risk settings: {e}")
            return None

    def get_channel_risk_settings(
        self, 
        symbol: str, 
        asset_type: str,
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        call_put: Optional[str] = None,
        broker_name: Optional[str] = None
    ) -> Optional[ChannelRiskSettings]:
        """Get per-channel risk settings for a position.
        
        Priority order (routed-trade-aware - preserves existing behavior):
        1. Signal routing mapping risk settings - ONLY if trade has routing_mapping_id set
           (explicitly routed trades get mapping-level risk settings)
        2. Channel-level risk settings - IF channel has risk_management_enabled=1 (unchanged)
        3. Return None if neither applies
        
        The routing_mapping_id is set on trades created via signal routing.
        Non-routed trades (routing_mapping_id = NULL) use channel settings only.
        This ensures existing per-channel risk configurations are never affected.
        """
        if not self._db:
            return None
        
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            
            if asset_type == 'option':
                # Normalize expiry to multiple formats for matching
                # Database may have: "12/17", "1/21", "2025-12-17", "12/17/25", etc.
                expiry_variants = [expiry] if expiry else []
                if expiry:
                    # If format is YYYY-MM-DD, also try MM/DD (with and without leading zeros)
                    if '-' in expiry and len(expiry) == 10:
                        parts = expiry.split('-')
                        month = parts[1]
                        day = parts[2]
                        expiry_variants.append(f"{month}/{day}")  # 01/21 (with zeros)
                        expiry_variants.append(f"{int(month)}/{int(day)}")  # 1/21 (without zeros)
                        expiry_variants.append(f"{month}/{day}/{parts[0][2:]}")  # 01/21/26
                        expiry_variants.append(f"{int(month)}/{int(day)}/{parts[0][2:]}")  # 1/21/26
                    # If format is MM/DD, also try variants
                    elif '/' in expiry and len(expiry) <= 5:
                        parts = expiry.split('/')
                        from datetime import datetime
                        year = datetime.now().year
                        month = parts[0]
                        day = parts[1]
                        expiry_variants.append(f"{year}-{month.zfill(2)}-{day.zfill(2)}")  # YYYY-MM-DD
                        expiry_variants.append(f"{int(month)}/{int(day)}")  # M/D (without leading zeros)
                        expiry_variants.append(f"{month.zfill(2)}/{day.zfill(2)}")  # MM/DD (with leading zeros)
                
                # Try each expiry variant - filter by broker to get correct channel settings
                # Include routing_mapping_id (index 23) for routed trade discrimination
                row = None
                for exp_try in expiry_variants:
                    if broker_name:
                        cursor.execute('''
                            SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                                   c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                                   c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct,
                                   c.profit_target_4_pct, c.profit_target_qty_1, c.profit_target_qty_2,
                                   c.profit_target_qty_3, c.profit_target_qty_4, c.trim_order_mode, c.trim_limit_offset,
                                   c.exit_strategy_mode, c.enable_dynamic_sl, c.enable_giveback_guard,
                                   c.giveback_allowed_pct, c.dynamic_sl_profile, t.routing_mapping_id,
                                   c.enable_early_trailing, c.early_trailing_activation_pct, c.early_trailing_step_pct,
                                   t.stop_loss_price, t.profit_target_price, t.executed_price
                            FROM trades t
                            LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id 
                                OR t.channel_id = CAST(c.id AS TEXT)
                                OR t.channel_id = c.telegram_chat_id)
                            WHERE t.symbol = ? AND t.asset_type = 'option' AND t.strike = ? AND t.expiry = ? AND t.call_put = ?
                            AND LOWER(t.broker) = LOWER(?)
                            AND t.status = 'OPEN' AND t.direction = 'BTO'
                            ORDER BY t.id DESC LIMIT 1
                        ''', (symbol, strike, exp_try, call_put, broker_name))
                    else:
                        cursor.execute('''
                            SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                                   c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                                   c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct,
                                   c.profit_target_4_pct, c.profit_target_qty_1, c.profit_target_qty_2,
                                   c.profit_target_qty_3, c.profit_target_qty_4, c.trim_order_mode, c.trim_limit_offset,
                                   c.exit_strategy_mode, c.enable_dynamic_sl, c.enable_giveback_guard,
                                   c.giveback_allowed_pct, c.dynamic_sl_profile, t.routing_mapping_id,
                                   c.enable_early_trailing, c.early_trailing_activation_pct, c.early_trailing_step_pct,
                                   t.stop_loss_price, t.profit_target_price, t.executed_price
                            FROM trades t
                            LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id 
                                OR t.channel_id = CAST(c.id AS TEXT)
                                OR t.channel_id = c.telegram_chat_id)
                            WHERE t.symbol = ? AND t.asset_type = 'option' AND t.strike = ? AND t.expiry = ? AND t.call_put = ?
                            AND t.status = 'OPEN' AND t.direction = 'BTO'
                            ORDER BY t.id DESC LIMIT 1
                        ''', (symbol, strike, exp_try, call_put))
                    row = cursor.fetchone()
                    if row:
                        break
                
                if not row:
                    return None
            else:
                # For stocks, also filter by broker to get correct channel settings
                # Include routing_mapping_id (index 23) for routed trade discrimination
                if broker_name:
                    cursor.execute('''
                        SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                               c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                               c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct,
                               c.profit_target_4_pct, c.profit_target_qty_1, c.profit_target_qty_2,
                               c.profit_target_qty_3, c.profit_target_qty_4, c.trim_order_mode, c.trim_limit_offset,
                               c.exit_strategy_mode, c.enable_dynamic_sl, c.enable_giveback_guard,
                               c.giveback_allowed_pct, c.dynamic_sl_profile, t.routing_mapping_id,
                               c.enable_early_trailing, c.early_trailing_activation_pct, c.early_trailing_step_pct,
                               t.stop_loss_price, t.profit_target_price, t.executed_price
                        FROM trades t
                        LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id
                            OR t.channel_id = CAST(c.id AS TEXT)
                            OR t.channel_id = c.telegram_chat_id)
                        WHERE t.symbol = ? AND t.asset_type = 'stock'
                        AND LOWER(t.broker) = LOWER(?)
                        AND t.status = 'OPEN' AND t.direction = 'BTO'
                        ORDER BY t.id DESC LIMIT 1
                    ''', (symbol, broker_name))
                else:
                    cursor.execute('''
                        SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                               c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                               c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct,
                               c.profit_target_4_pct, c.profit_target_qty_1, c.profit_target_qty_2,
                               c.profit_target_qty_3, c.profit_target_qty_4, c.trim_order_mode, c.trim_limit_offset,
                               c.exit_strategy_mode, c.enable_dynamic_sl, c.enable_giveback_guard,
                               c.giveback_allowed_pct, c.dynamic_sl_profile, t.routing_mapping_id,
                               c.enable_early_trailing, c.early_trailing_activation_pct, c.early_trailing_step_pct,
                               t.stop_loss_price, t.profit_target_price, t.executed_price
                        FROM trades t
                        LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id
                            OR t.channel_id = CAST(c.id AS TEXT)
                            OR t.channel_id = c.telegram_chat_id)
                        WHERE t.symbol = ? AND t.asset_type = 'stock'
                        AND t.status = 'OPEN' AND t.direction = 'BTO'
                        ORDER BY t.id DESC LIMIT 1
                    ''', (symbol,))
                row = cursor.fetchone()
                if not row:
                    return None
            
            if row[0] is not None:
                # Extract routing_mapping_id (index 23) - only set for routed trades
                routing_mapping_id = row[23] if len(row) > 23 else None
                
                # PRIORITY 1: Check if this is a routed trade with mapping-level risk settings
                # This ONLY applies to trades that have routing_mapping_id set
                if routing_mapping_id:
                    routing_settings = self._get_signal_routing_risk_settings(routing_mapping_id)
                    if routing_settings:
                        print(f"[RISK] Using signal routing risk settings for routed trade (mapping_id={routing_mapping_id})")
                        return routing_settings
                
                # PRIORITY 2: Channel-level risk settings (existing behavior - PRESERVED)
                # Check if risk management is explicitly enabled for this channel
                risk_enabled = row[8] if len(row) > 8 else 0
                
                # Only apply risk management if explicitly enabled
                if not risk_enabled:
                    return None
                
                # Extract trade-level SL/PT overrides (from conditional orders or parsed signals)
                # Indices 27-29: stop_loss_price, profit_target_price, executed_price
                trade_sl_price = row[27] if len(row) > 27 and row[27] else None
                trade_pt_price = row[28] if len(row) > 28 and row[28] else None
                trade_entry_price = row[29] if len(row) > 29 and row[29] else None
                
                pt1 = row[1] or 0
                pt2 = row[2] or 0
                pt3 = row[3] or 0
                pt4 = row[11] or 0  # New T4
                sl = row[4] or 0
                trail = row[5] or 0
                leave_runner_enabled = bool(row[9]) if len(row) > 9 and row[9] else False
                leave_runner_pct = row[10] if len(row) > 10 and row[10] else 25.0
                
                # Apply trade-level SL/PT overrides (convert absolute prices to percentages)
                # This enables signals with explicit SL/PT to override channel defaults
                if trade_sl_price and trade_entry_price and trade_entry_price > 0:
                    # Calculate SL percentage from absolute price
                    sl_pct_calc = ((trade_entry_price - trade_sl_price) / trade_entry_price) * 100
                    if sl_pct_calc > 0:
                        sl = round(sl_pct_calc, 1)
                        print(f"[RISK] Using trade-level SL: ${trade_sl_price:.2f} ({sl}% from entry ${trade_entry_price:.2f})")
                
                if trade_pt_price and trade_entry_price and trade_entry_price > 0:
                    # Calculate PT percentage from absolute price
                    pt_pct_calc = ((trade_pt_price - trade_entry_price) / trade_entry_price) * 100
                    if pt_pct_calc > 0:
                        pt1 = round(pt_pct_calc, 1)
                        print(f"[RISK] Using trade-level PT: ${trade_pt_price:.2f} ({pt1}% from entry ${trade_entry_price:.2f})")
                
                # Extract custom quantities (None means auto-calculate)
                qty1 = row[12] if len(row) > 12 else None
                qty2 = row[13] if len(row) > 13 else None
                qty3 = row[14] if len(row) > 14 else None
                qty4 = row[15] if len(row) > 15 else None
                
                # Extract trim order settings
                trim_mode = row[16] if len(row) > 16 and row[16] else 'market'
                trim_offset = row[17] if len(row) > 17 and row[17] is not None else 0.01
                
                # Extract exit strategy mode (signal, risk, hybrid)
                exit_mode = row[18] if len(row) > 18 and row[18] else 'signal'
                
                # Extract enhanced risk settings
                enable_dynamic_sl = bool(row[19]) if len(row) > 19 and row[19] else False
                enable_giveback_guard = bool(row[20]) if len(row) > 20 and row[20] else False
                giveback_allowed_pct = row[21] if len(row) > 21 and row[21] is not None else 30.0
                dynamic_sl_profile = row[22] if len(row) > 22 and row[22] else 'standard'
                
                # Extract Early Trailing settings (indices 24-26, after routing_mapping_id at 23)
                enable_early_trailing = bool(row[24]) if len(row) > 24 and row[24] else False
                early_trailing_activation_pct = row[25] if len(row) > 25 and row[25] is not None else 5.0
                early_trailing_step_pct = row[26] if len(row) > 26 and row[26] is not None else 3.0
                
                # Risk management is enabled - return settings
                return ChannelRiskSettings(
                    channel_id=str(row[0]),
                    channel_name=row[7] or 'Unknown',
                    profit_target_1_pct=pt1,
                    profit_target_2_pct=pt2,
                    profit_target_3_pct=pt3,
                    profit_target_4_pct=pt4,
                    profit_target_qty_1=qty1,
                    profit_target_qty_2=qty2,
                    profit_target_qty_3=qty3,
                    profit_target_qty_4=qty4,
                    stop_loss_pct=sl,
                    trailing_stop_pct=trail,
                    trailing_activation_pct=row[6] or 15.0,
                    leave_runner_enabled=leave_runner_enabled,
                    leave_runner_pct=leave_runner_pct,
                    trim_order_mode=trim_mode,
                    trim_limit_offset=trim_offset,
                    exit_strategy_mode=exit_mode,
                    enable_dynamic_sl=enable_dynamic_sl,
                    enable_giveback_guard=enable_giveback_guard,
                    giveback_allowed_pct=giveback_allowed_pct,
                    dynamic_sl_profile=dynamic_sl_profile,
                    enable_early_trailing=enable_early_trailing,
                    early_trailing_activation_pct=early_trailing_activation_pct,
                    early_trailing_step_pct=early_trailing_step_pct
                )
            
            return None
        except Exception as e:
            print(f"[RISK] Warning: Could not fetch channel settings: {e}")
            return None
    
    def get_open_trade_id_for_position(
        self,
        symbol: str,
        asset_type: str,
        broker: str,
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        call_put: Optional[str] = None
    ) -> Optional[int]:
        """Get the trade_id for an open position from the database."""
        if not self._db:
            return None
        
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            
            if asset_type == 'option' and strike:
                # Build query with all option identifiers for precise matching
                # Normalize expiry formats for matching (support ALL common formats)
                from datetime import datetime
                expiry_variants = []
                if expiry:
                    expiry_variants.append(expiry)  # Always include original
                    
                    if '-' in expiry:
                        # YYYY-MM-DD format (len 10)
                        parts = expiry.split('-')
                        if len(parts) == 3 and len(parts[0]) == 4:
                            yyyy, mm, dd = parts[0], parts[1].zfill(2), parts[2].zfill(2)
                            expiry_variants.append(f"{mm}/{dd}")  # MM/DD
                            expiry_variants.append(f"{int(mm)}/{int(dd)}")  # M/D (no padding)
                            expiry_variants.append(f"{mm}/{dd}/{yyyy[2:]}")  # MM/DD/YY
                            expiry_variants.append(f"{int(mm)}/{int(dd)}/{yyyy[2:]}")  # M/D/YY
                            expiry_variants.append(f"{mm}/{dd}/{yyyy}")  # MM/DD/YYYY
                            expiry_variants.append(f"{int(mm)}/{int(dd)}/{yyyy}")  # M/D/YYYY
                    elif '/' in expiry:
                        parts = expiry.split('/')
                        if len(parts) == 2:
                            # MM/DD or M/D format
                            mm, dd = parts[0].zfill(2), parts[1].zfill(2)
                            year = datetime.now().year
                            yy = str(year)[2:]  # Two-digit year
                            expiry_variants.append(f"{year}-{mm}-{dd}")  # YYYY-MM-DD
                            expiry_variants.append(f"{mm}/{dd}")  # MM/DD
                            expiry_variants.append(f"{int(parts[0])}/{int(parts[1])}")  # M/D
                            expiry_variants.append(f"{mm}/{dd}/{yy}")  # MM/DD/YY
                            expiry_variants.append(f"{int(parts[0])}/{int(parts[1])}/{yy}")  # M/D/YY
                            expiry_variants.append(f"{mm}/{dd}/{year}")  # MM/DD/YYYY
                            expiry_variants.append(f"{int(parts[0])}/{int(parts[1])}/{year}")  # M/D/YYYY
                        elif len(parts) == 3:
                            # MM/DD/YY or MM/DD/YYYY or M/D/YY variants
                            mm, dd = parts[0].zfill(2), parts[1].zfill(2)
                            yy_raw = parts[2]
                            if len(yy_raw) == 2:
                                year = 2000 + int(yy_raw)
                            elif len(yy_raw) == 4:
                                year = int(yy_raw)
                            else:
                                year = datetime.now().year
                            
                            expiry_variants.append(f"{year}-{mm}-{dd}")  # YYYY-MM-DD
                            expiry_variants.append(f"{mm}/{dd}")  # MM/DD
                            expiry_variants.append(f"{int(parts[0])}/{int(parts[1])}")  # M/D
                            expiry_variants.append(f"{mm}/{dd}/{str(year)[2:]}")  # MM/DD/YY
                            expiry_variants.append(f"{int(parts[0])}/{int(parts[1])}/{str(year)[2:]}")  # M/D/YY
                            expiry_variants.append(f"{mm}/{dd}/{year}")  # MM/DD/YYYY
                            expiry_variants.append(f"{int(parts[0])}/{int(parts[1])}/{year}")  # M/D/YYYY
                    
                    # Deduplicate while preserving order
                    seen = set()
                    expiry_variants = [x for x in expiry_variants if not (x in seen or seen.add(x))]
                
                # Normalize call_put
                cp_normalized = call_put.upper()[0] if call_put else None
                
                # Try each expiry variant
                for exp_try in expiry_variants:
                    if cp_normalized:
                        cursor.execute('''
                            SELECT id FROM trades
                            WHERE symbol = ? AND asset_type = 'option'
                            AND strike = ? AND expiry = ? AND call_put = ?
                            AND status = 'OPEN' AND direction = 'BTO'
                            AND LOWER(broker) = LOWER(?)
                            ORDER BY id DESC LIMIT 1
                        ''', (symbol, strike, exp_try, cp_normalized, broker))
                    else:
                        cursor.execute('''
                            SELECT id FROM trades
                            WHERE symbol = ? AND asset_type = 'option'
                            AND strike = ? AND expiry = ?
                            AND status = 'OPEN' AND direction = 'BTO'
                            AND LOWER(broker) = LOWER(?)
                            ORDER BY id DESC LIMIT 1
                        ''', (symbol, strike, exp_try, broker))
                    
                    row = cursor.fetchone()
                    if row:
                        return row[0]
                
                # Fallback: match by strike only if no expiry match found
                cursor.execute('''
                    SELECT id FROM trades
                    WHERE symbol = ? AND asset_type = 'option'
                    AND strike = ? AND status = 'OPEN' AND direction = 'BTO'
                    AND LOWER(broker) = LOWER(?)
                    ORDER BY id DESC LIMIT 1
                ''', (symbol, strike, broker))
                row = cursor.fetchone()
                return row[0] if row else None
            else:
                cursor.execute('''
                    SELECT id FROM trades
                    WHERE symbol = ? AND asset_type = 'stock'
                    AND status = 'OPEN' AND direction = 'BTO'
                    AND LOWER(broker) = LOWER(?)
                    ORDER BY id DESC LIMIT 1
                ''', (symbol, broker))
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as e:
            print(f"[RISK] Warning: Could not lookup trade_id: {e}")
            return None
    
    def load_position_price_targets(self) -> Dict[str, Dict[str, Optional[float]]]:
        """Load stop/target prices for all open positions.
        
        Returns dict keyed by db_key (no broker prefix) for matching with positions.
        """
        result = {}
        if not self._db:
            return result
        
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT symbol, asset_type, stop_loss_price, profit_target_price, strike, expiry, call_put
                FROM trades
                WHERE status = 'OPEN' AND direction = 'BTO'
                AND (stop_loss_price IS NOT NULL OR profit_target_price IS NOT NULL)
            ''')
            
            for row in cursor.fetchall():
                symbol = row[0]
                asset_type = row[1]
                sl_price = row[2]
                target_price = row[3]
                
                # Use db_key format (no broker prefix) for matching
                if asset_type == 'option':
                    db_key = f"{symbol}_{row[4]}_{row[5]}_{row[6]}"
                else:
                    db_key = f"{symbol}_stock"
                
                result[db_key] = {
                    'stop_loss_price': sl_price,
                    'profit_target_price': target_price
                }
            
            return result
        except Exception as e:
            print(f"[RISK] Warning: Could not load price targets: {e}")
            return result
    
    def find_open_bto_trade(
        self,
        symbol: str,
        asset_type: str,
        broker: str,
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        call_put: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Find the original BTO trade for PNL attribution."""
        if not self._db:
            return None
        
        try:
            # Pass type-safe values (the db method handles None internally)
            return self._db.find_open_bto_trade(
                symbol=symbol,
                asset_type=asset_type,
                broker=broker,
                strike=strike if strike is not None else 0.0,
                expiry=expiry if expiry is not None else "",
                call_put=call_put if call_put is not None else ""
            )
        except Exception as e:
            print(f"[RISK] Warning: Could not find open BTO trade: {e}")
            return None
    
    def get_channel_record_id(self, discord_channel_id: str) -> Optional[int]:
        """Get channel record ID from Discord channel ID."""
        if not self._db:
            return None
        
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM channels WHERE discord_channel_id = ?', 
                          (str(discord_channel_id),))
            row = cursor.fetchone()
            return row['id'] if row else None
        except Exception as e:
            print(f"[RISK] Warning: Could not get channel_record_id: {e}")
            return None


class RiskManager:
    """
    Main risk management coordinator.
    
    Monitors positions from multiple brokers and applies risk rules:
    1. Per-channel tiered profit targets (T1/T2/T3)
    2. Global profit target fallback
    3. Price-based stop loss / profit target overrides
    4. Trailing stop with activation threshold
    """
    
    DEFAULT_MONITORING_INTERVAL = 5  # seconds - optimized for fast profit/SL locks
    DEFAULT_TRAILING_ACTIVATION = 15.0  # percent
    
    def __init__(
        self,
        position_fetcher: Callable[[], Awaitable[List[Dict]]],
        order_queue: asyncio.Queue,
        settings_provider: Callable[[], Dict],
        db_adapter: Optional[RiskDBAdapter] = None,
        alpaca_broker=None,
        schwab_broker=None,
        ibkr_broker=None,
        tastytrade_broker=None,
        robinhood_broker=None,
        monitoring_interval: int = DEFAULT_MONITORING_INTERVAL,
        trailing_activation_pct: float = DEFAULT_TRAILING_ACTIVATION,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ):
        """
        Initialize RiskManager.
        
        Args:
            position_fetcher: Async callable returning Webull positions
            order_queue: Queue for exit orders
            settings_provider: Callable returning RiskSettings dict
            db_adapter: Database adapter (optional, for headless mode)
            alpaca_broker: Optional AlpacaBroker instance
            schwab_broker: Optional SchwabBroker instance
            ibkr_broker: Optional IBKRBroker instance
            tastytrade_broker: Optional TastytradeBroker instance
            robinhood_broker: Optional RobinhoodBroker instance (WARNING: LIVE ONLY)
            monitoring_interval: Seconds between position checks
            trailing_activation_pct: Default trailing stop activation threshold
            loop: Event loop (optional)
        """
        self.position_fetcher = position_fetcher
        self.order_queue = order_queue
        self.settings_provider = settings_provider
        self.db_adapter = db_adapter or RiskDBAdapter()
        self.alpaca_broker = alpaca_broker
        self.schwab_broker = schwab_broker
        self.ibkr_broker = ibkr_broker
        self.tastytrade_broker = tastytrade_broker
        self.robinhood_broker = robinhood_broker
        self.monitoring_interval = monitoring_interval
        self.trailing_activation_pct = trailing_activation_pct
        self.loop = loop or asyncio.get_event_loop()
        
        self.cache = PositionCache()
        self._running = False
    
    async def start_monitoring(self) -> None:
        """Start the position monitoring loop with enable gate and standby support."""
        cached_count = self.cache.load()
        if cached_count > 0:
            print(f"[RISK] Loaded {cached_count} cached positions")
        
        risk_restored = self.cache.restore_full_risk_state_from_db()
        if risk_restored > 0:
            print(f"[RISK] ✓ Restored full risk state (tier hits, dynamic SL, giveback) for {risk_restored} positions")
        
        self._load_db_price_targets()
        
        reconciled = self._reconcile_conditional_orders()
        if reconciled > 0:
            print(f"[RISK] ✓ Reconciled {reconciled} conditional order position(s) with SL/PT")
        
        print(f"[RISK] ✓ Position monitoring loop started - Will activate when risk settings enabled")
        self._running = True
        self._standby_mode = False
        self._last_status_log = 0
        
        while self._running:
            try:
                is_enabled = self._check_service_enabled()
                
                if is_enabled:
                    if self._standby_mode:
                        print("[RISK] ✓ Resuming active monitoring - risk settings enabled")
                        self._standby_mode = False
                    
                    await self._monitoring_cycle()
                    await asyncio.sleep(self._get_adaptive_interval())
                else:
                    if not self._standby_mode:
                        print("[RISK] ⏸️ Entering standby mode - no risk settings enabled (zero API calls)")
                        self._standby_mode = True
                    
                    await self._standby_cycle()
                    await asyncio.sleep(5)
                    
            except Exception as e:
                print(f"[RISK] Error in monitoring cycle: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(self.monitoring_interval)
    
    def _check_service_enabled(self) -> bool:
        """Check if risk monitoring should be active (any channel has risk enabled)."""
        try:
            from gui_app.database import get_setting
            risk_monitor_enabled = get_setting('risk_monitor_enabled', 'true').lower() == 'true'
            if not risk_monitor_enabled:
                return False
        except Exception:
            pass
        
        risk_settings = self._get_risk_settings()
        channel_count = self.db_adapter.count_channels_with_risk()
        
        return risk_settings.enabled or channel_count > 0
    
    def _get_adaptive_interval(self) -> float:
        """Get monitoring interval - configurable via GUI settings.
        
        Priority:
        1. GUI setting 'risk_check_interval_seconds' (if set)
        2. Default 5 seconds for fast profit/SL locks
        
        Configure in Settings → Risk Management → Check Interval
        Recommended: 3-5 seconds for active trading
        """
        try:
            from gui_app.database import get_setting
            custom_interval = get_setting('risk_check_interval_seconds', None)
            if custom_interval:
                interval = float(custom_interval)
                if 1 <= interval <= 60:
                    return interval
        except Exception:
            pass
        
        return self.monitoring_interval
    
    async def _standby_cycle(self) -> None:
        """Standby cycle - process invalidations WITHOUT making broker API calls."""
        check_and_process_invalidation_request()
        
        import time
        now = time.time()
        if now - self._last_status_log > 300:
            channel_count = self.db_adapter.count_channels_with_risk()
            print(f"[RISK] Standby: {channel_count} channels with risk settings (waiting for activation)")
            self._last_status_log = now
    
    def stop_monitoring(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
    
    def invalidate_settings_cache(self, channel_id: str = None) -> int:
        """Force refresh of cached channel settings on next monitoring cycle.
        
        Call this when channel risk settings are updated via GUI.
        
        Args:
            channel_id: If provided, only invalidate settings for this channel.
                       If None, invalidate all cached settings.
        
        Returns:
            Number of cache entries invalidated.
        """
        return self.cache.invalidate_channel_settings(channel_id)
    
    async def _monitoring_cycle(self) -> None:
        """Execute one monitoring cycle."""
        # Check for pending invalidation requests from Flask (thread-safe)
        check_and_process_invalidation_request()
        
        risk_settings = self._get_risk_settings()
        
        if not risk_settings.enabled:
            channel_count = self.db_adapter.count_channels_with_risk()
            if channel_count == 0:
                print("[RISK] Risk management disabled - stopping monitoring")
                self._running = False
                return
            else:
                print(f"[RISK] Per-channel risk ACTIVE for {channel_count} channel(s)")
        
        positions = await self._fetch_all_positions()
        
        if positions:
            webull_count = sum(1 for p in positions if p.broker == 'Webull')
            alpaca_count = sum(1 for p in positions if 'ALPACA' in p.broker)
            schwab_count = sum(1 for p in positions if 'SCHWAB' in p.broker.upper())
            ibkr_count = sum(1 for p in positions if 'IBKR' in p.broker.upper())
            tastytrade_count = sum(1 for p in positions if 'TASTYTRADE' in p.broker.upper())
            robinhood_count = sum(1 for p in positions if 'ROBINHOOD' in p.broker.upper())
            print(f"\n[RISK] Monitoring {len(positions)} open positions "
                  f"(Webull: {webull_count}, Alpaca: {alpaca_count}, Schwab: {schwab_count}, "
                  f"IBKR: {ibkr_count}, Tastytrade: {tastytrade_count}, Robinhood: {robinhood_count})...")
        
        broker_position_keys = set()
        
        for position in positions:
            try:
                await self._evaluate_position(position, risk_settings, broker_position_keys)
            except Exception as e:
                print(f"[RISK] ⚠️ Error processing position {position.symbol}: {e}")
        
        self.cache.save()
    
    async def _fetch_all_positions(self) -> List[PositionSnapshot]:
        """Fetch positions from all brokers with rate limit enforcement."""
        positions = []
        rate_manager = get_rate_limit_manager() if RATE_LIMIT_AVAILABLE else None
        
        if rate_manager:
            can_proceed, wait_time = rate_manager.can_make_request('webull')
            if not can_proceed:
                print(f"[RISK] Webull rate limit reached - skipping this cycle (wait {wait_time:.1f}s)")
            else:
                rate_manager.record_request('webull')
                webull_positions = await self.position_fetcher() or []
                for pos in webull_positions:
                    pos['broker'] = 'Webull'
                    positions.append(self._to_snapshot(pos))
        else:
            webull_positions = await self.position_fetcher() or []
            for pos in webull_positions:
                pos['broker'] = 'Webull'
                positions.append(self._to_snapshot(pos))
        
        if self.alpaca_broker and getattr(self.alpaca_broker, 'connected', False):
            try:
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('alpaca')
                    if not can_proceed:
                        print(f"[RISK] Alpaca rate limit - skipping (wait {wait_time:.1f}s)")
                    else:
                        rate_manager.record_request('alpaca')
                        alpaca_positions = await self._fetch_alpaca_positions()
                        positions.extend(alpaca_positions)
                else:
                    alpaca_positions = await self._fetch_alpaca_positions()
                    positions.extend(alpaca_positions)
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch Alpaca positions: {e}")
        
        if self.schwab_broker:
            try:
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('schwab')
                    if not can_proceed:
                        print(f"[RISK] Schwab rate limit - skipping (wait {wait_time:.1f}s)")
                    else:
                        # is_authenticated() is a regular function, not async
                        is_auth = self.schwab_broker.is_authenticated()
                        if is_auth:
                            rate_manager.record_request('schwab')
                            schwab_positions = await self._fetch_schwab_positions()
                            positions.extend(schwab_positions)
                else:
                    # is_authenticated() is a regular function, not async
                    is_auth = self.schwab_broker.is_authenticated()
                    if is_auth:
                        schwab_positions = await self._fetch_schwab_positions()
                        positions.extend(schwab_positions)
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch Schwab positions: {e}")
        
        if self.ibkr_broker and getattr(self.ibkr_broker, 'connected', False):
            try:
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('ibkr')
                    if not can_proceed:
                        print(f"[RISK] IBKR rate limit - skipping (wait {wait_time:.1f}s)")
                    else:
                        rate_manager.record_request('ibkr')
                        ibkr_positions = await self._fetch_ibkr_positions()
                        positions.extend(ibkr_positions)
                else:
                    ibkr_positions = await self._fetch_ibkr_positions()
                    positions.extend(ibkr_positions)
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch IBKR positions: {e}")
        
        if self.tastytrade_broker and getattr(self.tastytrade_broker, 'connected', False):
            try:
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('tastytrade')
                    if not can_proceed:
                        print(f"[RISK] Tastytrade rate limit - skipping (wait {wait_time:.1f}s)")
                    else:
                        rate_manager.record_request('tastytrade')
                        tastytrade_positions = await self._fetch_tastytrade_positions()
                        positions.extend(tastytrade_positions)
                else:
                    tastytrade_positions = await self._fetch_tastytrade_positions()
                    positions.extend(tastytrade_positions)
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch Tastytrade positions: {e}")
        
        if self.robinhood_broker and getattr(self.robinhood_broker, 'connected', False):
            try:
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('robinhood')
                    if not can_proceed:
                        print(f"[RISK] Robinhood rate limit - skipping (wait {wait_time:.1f}s)")
                    else:
                        rate_manager.record_request('robinhood')
                        robinhood_positions = await self._fetch_robinhood_positions()
                        positions.extend(robinhood_positions)
                else:
                    robinhood_positions = await self._fetch_robinhood_positions()
                    positions.extend(robinhood_positions)
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch Robinhood positions: {e}")
        
        return positions
    
    async def _fetch_alpaca_positions(self) -> List[PositionSnapshot]:
        """Fetch and parse Alpaca positions."""
        positions = []
        
        if not self.alpaca_broker or not hasattr(self.alpaca_broker, 'trading_client'):
            return positions
        
        alpaca_raw = await asyncio.to_thread(
            self.alpaca_broker.trading_client.get_all_positions
        )
        
        for ap in alpaca_raw:
            symbol = ap.symbol
            is_option = '  ' in symbol or len(symbol) > 10
            
            if is_option:
                snapshot = self._parse_alpaca_option(ap, symbol)
                if snapshot:
                    positions.append(snapshot)
            else:
                positions.append(PositionSnapshot(
                    symbol=symbol,
                    quantity=abs(float(ap.qty)),
                    avg_cost=float(ap.avg_entry_price),
                    current_price=float(ap.current_price),
                    asset='stock',
                    broker='ALPACA_PAPER'
                ))
        
        return positions
    
    def _parse_alpaca_option(self, ap, symbol: str) -> Optional[PositionSnapshot]:
        """Parse Alpaca option symbol (OCC format)."""
        try:
            if '  ' in symbol:
                parts = symbol.split()
                underlying = parts[0]
                option_code = parts[-1]
                
                exp_yy = option_code[:2]
                exp_mm = option_code[2:4]
                exp_dd = option_code[4:6]
                expiry = f"20{exp_yy}-{exp_mm}-{exp_dd}"
                
                call_put = option_code[6]
                strike = float(option_code[7:]) / 1000
            else:
                match = re.match(r'^([A-Z]+)(\d{6})([CP])(\d+)$', symbol)
                if not match:
                    return None
                
                underlying = match.group(1)
                date_part = match.group(2)
                call_put = match.group(3)
                strike = float(match.group(4)) / 1000
                
                expiry = f"20{date_part[:2]}-{date_part[2:4]}-{date_part[4:6]}"
            
            return PositionSnapshot(
                symbol=underlying,
                quantity=abs(float(ap.qty)),
                avg_cost=float(ap.avg_entry_price),
                current_price=float(ap.current_price),
                asset='option',
                broker='ALPACA_PAPER',
                strike=strike,
                expiry=expiry,
                direction=call_put,
                raw_symbol=symbol
            )
        except Exception as e:
            print(f"[RISK] Warning: Could not parse Alpaca option symbol {symbol}: {e}")
            return None
    
    async def _fetch_schwab_positions(self) -> List[PositionSnapshot]:
        """Fetch and parse Schwab positions."""
        positions = []
        
        if not self.schwab_broker:
            return positions
        
        try:
            schwab_raw = await self.schwab_broker.get_positions_detailed() or []
            
            for pos in schwab_raw:
                asset_type = pos.get('asset', 'stock')
                
                positions.append(PositionSnapshot(
                    symbol=pos.get('symbol', ''),
                    quantity=abs(float(pos.get('quantity', 0))),
                    avg_cost=float(pos.get('avg_cost', 0)),
                    current_price=float(pos.get('current_price', 0)),
                    asset=asset_type,
                    broker='SCHWAB',
                    strike=pos.get('strike'),
                    expiry=pos.get('expiry'),
                    direction=pos.get('direction'),
                    raw_symbol=pos.get('raw_symbol')
                ))
        except Exception as e:
            print(f"[RISK] Error fetching Schwab positions: {e}")
        
        return positions
    
    async def _fetch_ibkr_positions(self) -> List[PositionSnapshot]:
        """Fetch and parse IBKR positions (requires TWS/Gateway running)."""
        positions = []
        
        if not self.ibkr_broker or not hasattr(self.ibkr_broker, 'ib'):
            return positions
        
        try:
            ib = self.ibkr_broker.ib
            if not ib.isConnected():
                return positions
            
            broker_label = 'IBKR_LIVE' if not getattr(self.ibkr_broker, 'paper_trade', True) else 'IBKR_PAPER'
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
                    
                    positions.append(PositionSnapshot(
                        symbol=symbol,
                        quantity=quantity,
                        avg_cost=avg_cost / 100 if avg_cost > 0 else 0,
                        current_price=0,
                        asset='option',
                        broker=broker_label,
                        strike=contract.strike,
                        expiry=expiry,
                        direction=contract.right
                    ))
                else:
                    positions.append(PositionSnapshot(
                        symbol=symbol,
                        quantity=quantity,
                        avg_cost=avg_cost,
                        current_price=0,
                        asset='stock',
                        broker=broker_label
                    ))
        except Exception as e:
            print(f"[RISK] Error fetching IBKR positions: {e}")
        
        return positions
    
    async def _fetch_tastytrade_positions(self) -> List[PositionSnapshot]:
        """Fetch and parse Tastytrade positions."""
        positions = []
        
        if not self.tastytrade_broker:
            return positions
        
        try:
            broker_label = 'TASTYTRADE_LIVE' if getattr(self.tastytrade_broker, 'is_live', False) else 'TASTYTRADE_PAPER'
            
            if hasattr(self.tastytrade_broker, 'get_all_positions'):
                raw_positions = await asyncio.to_thread(self.tastytrade_broker.get_all_positions) or []
                
                for pos in raw_positions:
                    asset_type = pos.get('asset_type', 'stock')
                    
                    positions.append(PositionSnapshot(
                        symbol=pos.get('symbol', ''),
                        quantity=abs(float(pos.get('quantity', 0))),
                        avg_cost=float(pos.get('avg_price', 0)),
                        current_price=float(pos.get('current_price', 0)),
                        asset=asset_type,
                        broker=broker_label,
                        strike=pos.get('strike'),
                        expiry=pos.get('expiry'),
                        direction=pos.get('call_put')
                    ))
        except Exception as e:
            print(f"[RISK] Error fetching Tastytrade positions: {e}")
        
        return positions
    
    async def _fetch_robinhood_positions(self) -> List[PositionSnapshot]:
        """Fetch and parse Robinhood positions (WARNING: LIVE ONLY - no paper trading)."""
        positions = []
        
        if not self.robinhood_broker:
            return positions
        
        try:
            if hasattr(self.robinhood_broker, 'get_all_positions'):
                raw_positions = await asyncio.to_thread(self.robinhood_broker.get_all_positions) or []
                
                for pos in raw_positions:
                    pos_type = pos.get('type', 'stock')
                    
                    call_put = None
                    if pos.get('option_type') == 'call':
                        call_put = 'C'
                    elif pos.get('option_type') == 'put':
                        call_put = 'P'
                    
                    positions.append(PositionSnapshot(
                        symbol=pos.get('symbol', ''),
                        quantity=abs(float(pos.get('quantity', 0))),
                        avg_cost=float(pos.get('average_buy_price') or pos.get('average_price') or 0),
                        current_price=float(pos.get('current_price', 0) or 0),
                        asset=pos_type,
                        broker='ROBINHOOD',
                        strike=float(pos.get('strike_price')) if pos.get('strike_price') else None,
                        expiry=pos.get('expiration_date'),
                        direction=call_put
                    ))
        except Exception as e:
            print(f"[RISK] Error fetching Robinhood positions: {e}")
        
        return positions
    
    async def _evaluate_position(
        self, 
        position: PositionSnapshot, 
        risk_settings: RiskSettings,
        broker_position_keys: set
    ) -> None:
        """Evaluate a single position for risk triggers."""
        pos_key = position.position_key
        broker_position_keys.add(pos_key)
        
        
        cache = self.cache.get_or_create(
            position, 
            db_price_targets=getattr(self, '_db_price_targets', None)
        )
        
        if self.cache.is_closing(pos_key):
            return
        
        # Get trade_id for database persistence of trailing state
        # If not mapped yet (new position), look it up from DB and cache it
        trade_id = self.cache.get_trade_id(pos_key)
        if trade_id is None:
            call_put = self._normalize_call_put(position.direction) if position.asset == 'option' else None
            trade_id = self.db_adapter.get_open_trade_id_for_position(
                symbol=position.symbol,
                asset_type=position.asset,
                broker=position.broker,
                strike=position.strike,
                expiry=position.expiry,
                call_put=call_put
            )
            if trade_id:
                self.cache.set_trade_id(pos_key, trade_id)
        
        self.cache.update_highest_price(pos_key, position.current_price, trade_id=trade_id)
        
        pct_change = position.pct_change
        
        channel_settings = cache.channel_settings
        if channel_settings is None:
            call_put = self._normalize_call_put(position.direction)
            channel_settings = self.db_adapter.get_channel_risk_settings(
                position.symbol,
                position.asset,
                position.strike,
                position.expiry,
                call_put,
                position.broker
            )
            self.cache.apply_settings_with_versioning(pos_key, channel_settings)
            
            if channel_settings:
                print(f"[RISK] Using per-channel settings from '{channel_settings.channel_name}': "
                      f"Targets={channel_settings.profit_target_1_pct}%/"
                      f"{channel_settings.profit_target_2_pct}%/{channel_settings.profit_target_3_pct}%, "
                      f"StopLoss={channel_settings.stop_loss_pct}%, ExitMode={channel_settings.exit_strategy_mode}")
        
        # Skip position if global is disabled AND no channel settings - no risk management applies
        if not channel_settings and not risk_settings.enabled:
            return  # Skip this position entirely
        
        # Check exit_strategy_mode - if 'signal', skip automated risk evaluation
        # 'signal' mode = follow trader exit signals only, no automated exits
        # 'risk' mode = use automated risk management only
        # 'hybrid' mode = both trader signals AND automated exits
        if channel_settings and channel_settings.exit_strategy_mode == 'signal':
            return  # Signal mode: don't apply automated risk management, follow trader signals only
        
        self._log_position_status(position, cache, channel_settings, pct_change)
        
        decision = self._evaluate_exit_conditions(
            position, cache, channel_settings, risk_settings
        )
        
        if decision.should_exit:
            await self._execute_exit(position, cache, decision, channel_settings)
    
    def _evaluate_exit_conditions(
        self,
        position: PositionSnapshot,
        cache: PositionCacheEntry,
        channel_settings: Optional[ChannelRiskSettings],
        risk_settings: RiskSettings
    ) -> ExitDecision:
        """Evaluate all exit conditions in priority order including Enhanced Risk v2.0."""
        
        decision = evaluate_price_based_stops(position, cache)
        if decision.should_exit:
            return decision
        
        if channel_settings:
            decision = evaluate_channel_stop_loss(position, cache, channel_settings)
            if decision.should_exit:
                return decision
        
        if channel_settings and channel_settings.has_tiered_targets:
            decision = evaluate_tiered_targets(position, cache, channel_settings)
            if decision.should_exit:
                decision.reason = format_tier_reason(decision, channel_settings.channel_name)
                return decision
        
        if channel_settings and (channel_settings.enable_dynamic_sl or channel_settings.enable_giveback_guard):
            engine_decision = self._evaluate_enhanced_risk(position, cache, channel_settings)
            if engine_decision and engine_decision.should_exit:
                return engine_decision
        
        if channel_settings and channel_settings.enable_early_trailing:
            early_result, updated_cache = evaluate_early_trailing(
                position, cache, channel_settings, verbose=True
            )
            if early_result.should_update_stop:
                self.cache.persist_early_trailing_state(position.position_key)
            if early_result.should_exit:
                channel_name = channel_settings.channel_name
                return ExitDecision(
                    should_exit=True,
                    reason=f"EARLY TRAIL [{channel_name}] {early_result.reason}",
                    exit_qty=int(position.quantity),
                    is_partial=False,
                    risk_trigger='early_trailing'
                )
        
        trailing_pct, activation_pct, stop_pct = get_effective_trailing_settings(
            channel_settings, risk_settings, self.trailing_activation_pct
        )
        channel_name = channel_settings.channel_name if channel_settings else "Global"
        
        leave_runner_enabled = channel_settings.leave_runner_enabled if channel_settings else False
        leave_runner_pct = channel_settings.leave_runner_pct if channel_settings else 25.0
        
        decision, should_activate = evaluate_trailing_stop(
            position, cache, trailing_pct, activation_pct, stop_pct, channel_name,
            verbose=True,
            leave_runner_enabled=leave_runner_enabled,
            leave_runner_pct=leave_runner_pct
        )
        if should_activate:
            self.cache.activate_trailing_stop(position.position_key)
        if decision.should_exit:
            return decision
        
        if not channel_settings:
            decision = evaluate_global_risk(position, cache, risk_settings)
            if decision.should_exit:
                return decision
        
        return ExitDecision.no_exit()
    
    def _evaluate_enhanced_risk(
        self,
        position: PositionSnapshot,
        cache: PositionCacheEntry,
        channel_settings: ChannelRiskSettings
    ) -> Optional[ExitDecision]:
        """
        Evaluate Enhanced Risk v2.0 features: Dynamic SL and Giveback Guard.
        Updates cache state and returns exit decision if triggered.
        """
        state = TradeState(
            entry_price=cache.entry_price,
            current_price=position.current_price,
            qty=int(position.quantity),
            remaining_qty=int(position.quantity)
        )
        state.copy_from_cache(cache)
        
        actions, updated_state = evaluate_exit_actions(state, channel_settings, verbose=False)
        
        old_max_pnl = cache.max_pnl_seen
        old_dsl = cache.dynamic_sl_price
        old_giveback = cache.giveback_guard_active
        
        cache.max_pnl_seen = updated_state.max_pnl_seen
        cache.dynamic_sl_price = updated_state.dynamic_sl_price
        cache.giveback_guard_active = updated_state.giveback_guard_active
        cache.last_evaluated_price = updated_state.last_evaluated_price
        if updated_state.highest_price > cache.highest_price:
            cache.highest_price = updated_state.highest_price
        
        persist_updates = {}
        if updated_state.max_pnl_seen > old_max_pnl:
            persist_updates['max_pnl_seen'] = updated_state.max_pnl_seen
        if updated_state.dynamic_sl_price != old_dsl:
            persist_updates['dynamic_sl_price'] = updated_state.dynamic_sl_price
        if updated_state.giveback_guard_active and not old_giveback:
            persist_updates['giveback_guard_active'] = True
        if persist_updates:
            self.cache.update_enhanced_risk_state(position.position_key, **persist_updates)
        
        for action in actions:
            if action.action_type == ActionType.SELL_ALL:
                channel_name = channel_settings.channel_name
                if 'Dynamic SL' in action.reason:
                    return ExitDecision.stop_loss(action.reason, action.qty, channel_name)
                elif 'Giveback' in action.reason:
                    return ExitDecision(
                        should_exit=True,
                        reason=f"GIVEBACK GUARD [{channel_name}] {action.reason}",
                        exit_qty=action.qty,
                        is_partial=False,
                        risk_trigger='giveback_guard'
                    )
                else:
                    return ExitDecision.stop_loss(action.reason, action.qty, channel_name)
            
            elif action.action_type == ActionType.MOVE_STOP and action.new_stop_price:
                if cache.dynamic_sl_price is None or action.new_stop_price > cache.dynamic_sl_price:
                    cache.dynamic_sl_price = action.new_stop_price
                    print(f"[RISK] Dynamic SL escalated to ${action.new_stop_price:.2f} ({action.reason})")
            
            elif action.action_type == ActionType.ACTIVATE_GIVEBACK:
                cache.giveback_guard_active = True
                print(f"[RISK] Giveback Guard activated ({action.reason})")
            
            elif action.action_type == ActionType.ACTIVATE_EARLY_TRAIL:
                cache.early_trailing_active = True
                if action.new_stop_price is not None:
                    cache.early_stop_price = action.new_stop_price
                cache.early_steps_locked = 0
                stop_display = f"${cache.early_stop_price:.2f}" if cache.early_stop_price else "entry"
                print(f"[RISK] ✓ Early Trailing ACTIVATED - Breakeven locked at {stop_display}")
                self.cache.persist_early_trailing_state(position.position_key)
            
            elif action.action_type == ActionType.UPDATE_EARLY_STOP and action.new_stop_price is not None:
                old_stop = cache.early_stop_price
                cache.early_stop_price = action.new_stop_price
                if hasattr(action, 'steps_locked'):
                    cache.early_steps_locked = action.steps_locked
                else:
                    cache.early_steps_locked = (cache.early_steps_locked or 0) + 1
                old_display = f"${old_stop:.2f}" if old_stop else "entry"
                print(f"[RISK] 📈 Early Trail PROFIT LOCKED: {old_display} → ${action.new_stop_price:.2f} (step {cache.early_steps_locked})")
                self.cache.persist_early_trailing_state(position.position_key)
        
        return None
    
    async def _execute_exit(
        self,
        position: PositionSnapshot,
        cache: PositionCacheEntry,
        decision: ExitDecision,
        channel_settings: Optional[ChannelRiskSettings]
    ) -> None:
        """Queue an exit order with ExitOrderArbiter integration for hybrid mode."""
        from datetime import datetime
        pos_key = position.position_key
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Check if entering extended retry mode - send Discord notification once
        if self.cache.needs_extended_notification(pos_key):
            await self._send_extended_mode_notification(position, channel_settings)
        
        # Check retry cooldown (respects both fast and extended mode intervals)
        if not self.cache.can_retry_exit(pos_key):
            retry_state = self.cache.get_retry_state(pos_key)
            cooldown = retry_state.get('cooldown_remaining', 0)
            is_extended = self.cache.is_in_extended_mode(pos_key)
            
            if is_extended:
                print(f"[RISK] ⏳ EXTENDED RETRY MODE - Waiting for {pos_key}")
                print(f"[RISK]   Attempt #{retry_state.get('retry_count')} - next retry in {cooldown:.0f}s (5-min intervals)")
            else:
                print(f"[RISK] ⏳ EXIT DEFERRED - Retry cooldown active for {pos_key}")
                print(f"[RISK]   Retry {retry_state.get('retry_count')}/5 - wait {cooldown:.0f}s")
            return
        
        print(f"\n{'='*60}")
        print(f"[RISK] [{timestamp}] ✓ EXIT TRIGGERED")
        print(f"[RISK]   Position: {pos_key}")
        print(f"[RISK]   Reason: {decision.reason}")
        print(f"[RISK]   Qty: {decision.exit_qty} | Price: ${position.current_price:.2f}")
        print(f"[RISK]   Broker: {position.broker}")
        
        # Show retry state if retrying
        retry_state = self.cache.get_retry_state(pos_key)
        if retry_state.get('retry_count', 0) > 0:
            print(f"[RISK]   ↻ Retry attempt {retry_state['retry_count'] + 1}/{retry_state['max_retries']}")
            if retry_state.get('use_market'):
                print(f"[RISK]   📊 Using MARKET order (limit orders failed)")
        print(f"{'='*60}")
        
        is_stop_exit = 'STOP LOSS' in decision.reason or 'TRAILING STOP' in decision.reason
        
        exit_mode = channel_settings.exit_strategy_mode if channel_settings else 'risk'
        
        if ARBITER_AVAILABLE and exit_order_arbiter and exit_mode == 'hybrid':
            try:
                signal_instance_id = None
                if hasattr(cache, 'signal_instance_id'):
                    signal_instance_id = cache.signal_instance_id
                
                if 'TRAILING' in decision.reason:
                    exit_type = 'trailing_stop'
                    arbiter_source = 'trailing'
                elif 'TARGET' in decision.reason or 'PROFIT' in decision.reason:
                    exit_type = 'profit_target'
                    arbiter_source = 'channel'
                else:
                    exit_type = 'stop_loss'
                    arbiter_source = 'channel'
                
                arbiter_result = await exit_order_arbiter.request_exit(
                    signal_instance_id=signal_instance_id,
                    source=arbiter_source,
                    exit_type=exit_type,
                    exit_strategy_mode=exit_mode,
                    reason=f"Risk manager: {decision.reason}"
                )
                
                if not arbiter_result.get('approved'):
                    print(f"[RISK] Exit rejected by arbiter: {arbiter_result.get('reason')}")
                    return
                
                print(f"[RISK] Exit approved by arbiter (hybrid mode)")
            except Exception as e:
                print(f"[RISK] Arbiter check failed, proceeding with exit: {e}")
        
        if not decision.is_partial:
            self.cache.mark_closing(pos_key)
        
        # Note: tier_hit is added to signal and marked AFTER successful execution
        # This prevents re-trigger issues when orders fail
        
        try:
            stc_signal = self._build_stc_signal(position, decision)
            
            call_put = self._normalize_call_put(position.direction)
            origin_trade = self.db_adapter.find_open_bto_trade(
                symbol=position.symbol,
                asset_type=position.asset,
                broker=position.broker,
                strike=position.strike,
                expiry=position.expiry,
                call_put=call_put
            )
            
            if origin_trade:
                stc_signal['channel_id'] = origin_trade.get('channel_id')
                stc_signal['message_id'] = origin_trade.get('message_id')
                stc_signal['origin_trade_id'] = origin_trade.get('id')
                
                if origin_trade.get('channel_id'):
                    channel_record_id = self.db_adapter.get_channel_record_id(
                        origin_trade['channel_id']
                    )
                    if channel_record_id:
                        stc_signal['channel_record_id'] = channel_record_id
                
                print(f"[RISK] ✓ Linked to origin channel_id={origin_trade.get('channel_id')} "
                      f"(trade #{origin_trade.get('id')})")
            else:
                print(f"[RISK] ⚠️ No origin BTO trade found in database for {pos_key}")
            
            # Add market order flag if limit orders have failed multiple times
            if self.cache.should_use_market_order(pos_key):
                stc_signal['_use_market_order'] = True
                # Keep the current position price for options (Webull doesn't support market orders for options)
                # For stocks, we could set to None for true market order but keeping price is safer
                print(f"[RISK] 📊 Market order mode - using current price ${position.current_price:.2f}")
            
            await self.order_queue.put(stc_signal)
            print(f"[RISK] STC order queued for {pos_key} via {position.broker}: {stc_signal}")
            
        except Exception as e:
            self.cache.reset_closing(pos_key)
            print(f"[RISK] ✗ Failed to queue STC order for {pos_key}: {e}")
    
    def _build_stc_signal(self, position: PositionSnapshot, decision: ExitDecision) -> Dict:
        """Build STC signal dict for order queue."""
        stc_signal = {
            'asset': position.asset,
            'action': 'STC',
            'qty': decision.exit_qty,
            'symbol': position.symbol,
            'price': position.current_price,
            'broker': position.broker,
            'raw_symbol': position.raw_symbol,
            'exit_reason': decision.reason,
            'risk_trigger': decision.risk_trigger,
            '_risk_management_order': True,
            '_tier_to_mark': decision.tier_hit,
            '_position_key': position.position_key,
            '_is_partial': decision.is_partial
        }
        
        if position.asset == 'option':
            expiry_iso = position.expiry or ''
            expiry_year = None
            if expiry_iso and '-' in expiry_iso:
                parts = expiry_iso.split('-')
                if len(parts) == 3:
                    expiry_year = parts[0]
                    expiry_mmdd = f"{parts[1]}/{parts[2]}"
                else:
                    expiry_mmdd = expiry_iso
            else:
                expiry_mmdd = expiry_iso
            
            direction = (position.direction or '').upper()
            if direction == 'CALL':
                opt_type = 'C'
            elif direction == 'PUT':
                opt_type = 'P'
            else:
                opt_type = direction[0] if direction else 'C'
            
            stc_signal['strike'] = position.strike or 0
            stc_signal['opt_type'] = opt_type
            stc_signal['expiry'] = expiry_mmdd
            stc_signal['expiry_year'] = expiry_year
            stc_signal['option_id'] = position.option_id or 0
        
        return stc_signal
    
    async def _send_extended_mode_notification(
        self, 
        position: PositionSnapshot,
        channel_settings: Optional[ChannelRiskSettings]
    ) -> None:
        """Send Discord notification when entering extended retry mode."""
        retry_state = self.cache.get_retry_state(position.position_key)
        
        notification = {
            'action': 'NOTIFICATION',
            '_notification_type': 'extended_retry_mode',
            '_position_key': position.position_key,
            '_message': (
                f"⚠️ **EXTENDED RETRY MODE**\n\n"
                f"**Position:** {position.position_key}\n"
                f"**Broker:** {position.broker}\n"
                f"**Current P/L:** {position.pct_change:+.1f}%\n"
                f"**Retry Attempts:** {retry_state.get('retry_count', 5)}\n\n"
                f"Broker API repeatedly failed. Bot will keep retrying every 5 minutes.\n"
                f"You may want to close this position manually if urgent."
            ),
            'broker': position.broker,
            'symbol': position.symbol,
            'asset': position.asset
        }
        
        try:
            await self.order_queue.put(notification)
            print(f"[RISK] 📢 Discord notification sent for extended retry mode: {position.position_key}")
        except Exception as e:
            print(f"[RISK] ⚠️ Failed to send extended mode notification: {e}")
    
    def _get_risk_settings(self) -> RiskSettings:
        """Get current risk settings."""
        settings = self.settings_provider()
        return RiskSettings(
            enabled=settings.get('enabled', False),
            profit_target_percent=settings.get('profit_target_percent', 0),
            stop_loss_percent=settings.get('stop_loss_percent', 0),
            trailing_stop_percent=settings.get('trailing_stop_percent', 0)
        )
    
    def _load_db_price_targets(self) -> None:
        """Load per-position price targets from database.
        
        Note: DB returns db_key format (no broker). We store these targets
        and apply them when positions are first tracked via get_or_create().
        """
        self._db_price_targets = self.db_adapter.load_position_price_targets()
        if self._db_price_targets:
            print(f"[RISK] ✓ Loaded stop/target prices for {len(self._db_price_targets)} positions from database")
    
    def _reconcile_conditional_orders(self) -> int:
        """
        Reconcile executed conditional orders with open positions.
        Links positions to their source channels and seeds SL/PT into cache.
        
        This handles cases where:
        - Conditional orders triggered but bot restarted before seeding
        - BrokerSync created trade records without channel context
        - Positions are showing as "Pre-tracking" despite having conditional orders
        """
        try:
            from gui_app.database import get_connection
            import json
            
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT id, symbol, channel_id, broker_primary,
                       stop_loss_pct, stop_loss_fixed, stop_loss_type, stop_loss_value,
                       take_profit_targets, target_ranges, trigger_price,
                       trailing_stop_enabled, leave_runner
                FROM conditional_orders
                WHERE status IN ('EXECUTED', 'TRACKING')
                AND created_at >= datetime('now', '-7 days')
            ''')
            
            executed_orders = cursor.fetchall()
            if not executed_orders:
                return 0
            
            reconciled_count = 0
            for order in executed_orders:
                order_id = order['id']
                symbol = order['symbol'].upper()
                channel_id = order['channel_id']
                broker = order['broker_primary']
                trigger_price = order['trigger_price']
                
                sl_pct = order['stop_loss_pct'] or order['stop_loss_value']
                sl_fixed = order['stop_loss_fixed']
                sl_type = order['stop_loss_type'] or 'pct'
                
                profit_targets_raw = order['take_profit_targets'] or order['target_ranges']
                
                sl_price = None
                if sl_fixed and sl_type == 'fixed':
                    sl_price = float(sl_fixed)
                elif sl_pct and trigger_price:
                    sl_price = trigger_price * (1 - float(sl_pct) / 100)
                
                pt_price = None
                if profit_targets_raw:
                    try:
                        if isinstance(profit_targets_raw, str):
                            pts = json.loads(profit_targets_raw)
                        else:
                            pts = profit_targets_raw
                        
                        if isinstance(pts, list) and pts:
                            first_pt = pts[0]
                            if isinstance(first_pt, (int, float)):
                                pt_price = float(first_pt)
                            elif isinstance(first_pt, dict) and 'price' in first_pt:
                                pt_price = float(first_pt['price'])
                    except (json.JSONDecodeError, TypeError):
                        pass
                
                if not sl_price and not pt_price:
                    continue
                
                pos_key_stock = f"{broker}_{symbol}_stock"
                pos_key_simple = f"{broker}_{symbol}"
                
                cache_entry = self.cache.get(pos_key_stock) or self.cache.get(pos_key_simple)
                if cache_entry:
                    updated = False
                    
                    if sl_price and not cache_entry.stop_loss_price:
                        cache_entry.stop_loss_price = sl_price
                        updated = True
                    
                    if pt_price and not cache_entry.profit_target_price:
                        cache_entry.profit_target_price = pt_price
                        updated = True
                    
                    if updated:
                        reconciled_count += 1
                        sl_display = f"${sl_price:.2f}" if sl_price else "N/A"
                        pt_display = f"${pt_price:.2f}" if pt_price else "N/A"
                        print(f"[RISK] 🔗 Linked {symbol} to conditional order #{order_id} "
                              f"(SL: {sl_display}, PT: {pt_display})")
                else:
                    self.cache._cache[pos_key_stock] = PositionCacheEntry(
                        entry_price=trigger_price or 0,
                        highest_price=trigger_price or 0,
                        stop_loss_price=sl_price,
                        profit_target_price=pt_price,
                        broker=broker
                    )
                    reconciled_count += 1
                    print(f"[RISK] ✨ Created cache entry for {symbol} from conditional order #{order_id}")
            
            if reconciled_count > 0:
                self.cache.save()
            
            return reconciled_count
            
        except Exception as e:
            print(f"[RISK] Error reconciling conditional orders: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def _to_snapshot(self, pos: Dict) -> PositionSnapshot:
        """Convert raw position dict to PositionSnapshot."""
        return PositionSnapshot(
            symbol=pos.get('symbol', ''),
            quantity=float(pos.get('quantity', 0)),
            avg_cost=float(pos.get('avg_cost', 0)),
            current_price=float(pos.get('current_price', 0)),
            asset=pos.get('asset', 'stock'),
            broker=pos.get('broker', 'UNKNOWN'),
            strike=pos.get('strike'),
            expiry=pos.get('expiry'),
            direction=pos.get('direction'),
            raw_symbol=pos.get('raw_symbol'),
            option_id=pos.get('option_id')
        )
    
    def _normalize_call_put(self, direction: Optional[str]) -> Optional[str]:
        """Normalize CALL/PUT to C/P."""
        if not direction:
            return None
        d = direction.upper()
        if d == 'CALL':
            return 'C'
        if d == 'PUT':
            return 'P'
        return d[0] if d else None
    
    def _log_status(self, risk_settings: RiskSettings, channel_count: int) -> None:
        """Log risk management status."""
        print(f"[RISK] ========== RISK MANAGEMENT STATUS ==========")
        print(f"[RISK] Global Risk: {'✓ ENABLED' if risk_settings.enabled else '✗ DISABLED'}")
        if risk_settings.enabled:
            print(f"[RISK]   → Profit Target: {risk_settings.profit_target_percent}%")
            print(f"[RISK]   → Stop Loss: {risk_settings.stop_loss_percent}%")
            print(f"[RISK]   → Trailing Stop: {risk_settings.trailing_stop_percent}%")
        print(f"[RISK] Per-Channel Risk: {channel_count} channel(s) configured")
        print(f"[RISK] ===============================================")
        
        if risk_settings.enabled and channel_count > 0:
            print(f"[RISK] MODE: HYBRID - Per-channel first, Global fallback")
        elif risk_settings.enabled:
            print(f"[RISK] MODE: GLOBAL ONLY - All trades use global settings")
        elif channel_count > 0:
            print(f"[RISK] MODE: PER-CHANNEL ONLY - Only channel-linked trades get risk management")
            print(f"[RISK]   ⚠️  Trades without channel_id will NOT have risk management!")
    
    def _log_position_status(
        self, 
        position: PositionSnapshot, 
        cache: PositionCacheEntry,
        channel_settings: Optional[ChannelRiskSettings],
        pct_change: float
    ) -> None:
        """Log position monitoring status with Enhanced Risk v2.0 features."""
        pos_key = position.position_key
        current = position.current_price
        entry = cache.entry_price
        qty = position.quantity
        
        channel_name = channel_settings.channel_name if channel_settings else 'Global'
        sl_price = cache.stop_loss_price
        target_price = cache.profit_target_price
        
        trailing_pct = channel_settings.trailing_stop_pct if channel_settings else 0
        activation_pct = channel_settings.trailing_activation_pct if channel_settings else 15.0
        trailing_active = cache.trailing_activated
        high_price = cache.highest_price
        
        # Check if Early Trailing is enabled (mutually exclusive with legacy trailing)
        early_trailing_enabled = channel_settings.enable_early_trailing if channel_settings else False
        early_trailing_activation = channel_settings.early_trailing_activation_pct if channel_settings else 5.0
        early_trailing_step = channel_settings.early_trailing_step_pct if channel_settings else 3.0
        early_trailing_active = cache.early_trailing_active
        
        trailing_status = ""
        trailing_display = ""
        
        if early_trailing_enabled:
            # Early Trailing display
            trailing_display = f"EarlyTrail: {early_trailing_activation}%/{early_trailing_step}%"
            if early_trailing_active:
                stop_price = cache.early_stop_price if hasattr(cache, 'early_stop_price') and cache.early_stop_price else entry
                trailing_status = f" | [EARLY-TRAIL ✓] Stop: ${stop_price:.2f}"
            else:
                remaining = early_trailing_activation - pct_change
                if remaining > 0:
                    trailing_status = f" | [EARLY-TRAIL] Breakeven at +{early_trailing_activation}% (need +{remaining:.1f}%)"
                else:
                    trailing_status = f" | [EARLY-TRAIL] Ready for breakeven lock"
        elif trailing_pct > 0:
            # Legacy Trailing display
            trailing_display = f"Trail: {trailing_pct}%@{activation_pct}%"
            if trailing_active:
                stop_price = high_price * (1 - trailing_pct / 100)
                trailing_status = f" | [TRAIL ✓] High: ${high_price:.2f}, Stop: ${stop_price:.2f}"
            else:
                remaining = activation_pct - pct_change
                if remaining > 0:
                    trailing_status = f" | [TRAIL] Activate at +{activation_pct}% (need +{remaining:.1f}%)"
                else:
                    trailing_status = f" | [TRAIL] Ready to activate"
        else:
            trailing_display = "Trail: Off"
        
        enhanced_status = ""
        if channel_settings:
            if channel_settings.enable_dynamic_sl:
                if cache.dynamic_sl_price:
                    dsl_pct = ((cache.dynamic_sl_price - entry) / entry) * 100
                    enhanced_status += f" | [DYN-SL ✓] ${cache.dynamic_sl_price:.2f} (+{dsl_pct:.0f}%)"
                else:
                    enhanced_status += f" | [DYN-SL] {channel_settings.dynamic_sl_profile}"
            
            if channel_settings.enable_giveback_guard:
                if cache.giveback_guard_active:
                    max_pnl = cache.max_pnl_seen
                    threshold = max_pnl * (1 - channel_settings.giveback_allowed_pct / 100)
                    enhanced_status += f" | [GIVEBACK ✓] Max:{max_pnl:.0f}%, Exit@{threshold:.0f}%"
                else:
                    enhanced_status += f" | [GIVEBACK] {channel_settings.giveback_allowed_pct}% guard"
        
        if sl_price or target_price:
            print(f"[RISK] [{channel_name}] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | SL: ${sl_price or 'N/A'} | Target: ${target_price or 'N/A'} | Qty: {qty}{trailing_status}{enhanced_status}")
        elif channel_settings:
            print(f"[RISK] [{channel_name}] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | Targets: {channel_settings.profit_target_1_pct}/"
                  f"{channel_settings.profit_target_2_pct}/{channel_settings.profit_target_3_pct}% | "
                  f"SL: {channel_settings.stop_loss_pct}% | {trailing_display} | Qty: {qty}{trailing_status}{enhanced_status}")
        else:
            print(f"[RISK] [Global] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | Qty: {qty}{trailing_status}")
