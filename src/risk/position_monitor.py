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
    PositionCacheEntry,
    normalize_index_symbol
)
from .position_cache import PositionCache
from .tiered_targets import evaluate_tiered_targets, format_tier_reason, evaluate_channel_stop_loss, get_trim_order_price
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


def notify_order_placed(broker_name: str, order_id: str = '', symbol: str = ''):
    with _risk_manager_lock:
        instance = risk_manager_instance
    if instance is not None:
        instance.notify_order_placed(broker_name, order_id=order_id, symbol=symbol)
    else:
        try:
            broker_upper = broker_name.upper()
            if 'WEBULL' in broker_upper:
                from src.services.webull_data_hub import get_webull_data_hub
                get_webull_data_hub().request_risk_eval()
            elif 'SCHWAB' in broker_upper:
                from src.services.schwab_data_hub import get_schwab_data_hub
                get_schwab_data_hub().request_risk_eval()
            elif 'IBKR' in broker_upper:
                from src.services.ibkr_data_hub import get_ibkr_data_hub
                get_ibkr_data_hub().request_risk_eval()
        except Exception:
            pass


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
                       enable_early_trailing, early_trailing_activation_pct, early_trailing_step_pct,
                       sl_order_type, escalation_only_mode
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
            sl_order_type = row[26] if len(row) > 26 and row[26] else 'limit'
            escalation_only = bool(row[27]) if len(row) > 27 and row[27] else False
            
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
                sl_order_mode=sl_order_type,
                trim_limit_offset=0.01,
                exit_strategy_mode=exit_mode,
                enable_dynamic_sl=dynamic_sl_enabled,
                dynamic_sl_profile=sl_profile,
                enable_giveback_guard=giveback_enabled,
                giveback_allowed_pct=giveback_pct,
                enable_early_trailing=enable_early_trailing,
                early_trailing_activation_pct=early_trailing_activation_pct,
                early_trailing_step_pct=early_trailing_step_pct,
                escalation_only_mode=escalation_only
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
        broker_name: Optional[str] = None,
        trade_id: Optional[int] = None
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
        
        SYMBOL_ALIASES = {
            'SPX': ['SPXW', 'SPX'],
            'SPXW': ['SPX', 'SPXW'],
            'NDX': ['NDXP', 'NDX'],
            'NDXP': ['NDX', 'NDXP'],
            'VIX': ['VIXW', 'VIX'],
            'VIXW': ['VIX', 'VIXW'],
            'RUT': ['RUTW', 'RUT'],
            'RUTW': ['RUT', 'RUTW'],
            'DJX': ['DJXW', 'DJX'],
            'DJXW': ['DJX', 'DJXW'],
        }
        symbols_to_check = [symbol] + [s for s in SYMBOL_ALIASES.get(symbol, []) if s != symbol]
        
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            
            sym_placeholders = ','.join(['?' for _ in symbols_to_check])
            
            if asset_type == 'option':
                expiry_variants = [expiry] if expiry else []
                if expiry:
                    if '-' in expiry and len(expiry) == 10:
                        parts = expiry.split('-')
                        month = parts[1]
                        day = parts[2]
                        expiry_variants.append(f"{month}/{day}")  # 01/21
                        expiry_variants.append(f"{int(month)}/{int(day)}")  # 1/21
                        expiry_variants.append(f"{int(month)}/{day}")  # 1/21 (mixed: stripped month, padded day)
                        expiry_variants.append(f"{month}/{int(day)}")  # 01/1 (mixed: padded month, stripped day)
                        expiry_variants.append(f"{month}/{day}/{parts[0][2:]}")  # 01/21/26
                        expiry_variants.append(f"{int(month)}/{int(day)}/{parts[0][2:]}")  # 1/21/26
                    elif '/' in expiry and len(expiry) <= 5:
                        parts = expiry.split('/')
                        from datetime import datetime
                        year = datetime.now().year
                        month = parts[0]
                        day = parts[1]
                        expiry_variants.append(f"{year}-{month.zfill(2)}-{day.zfill(2)}")  # YYYY-MM-DD
                        expiry_variants.append(f"{int(month)}/{int(day)}")  # M/D
                        expiry_variants.append(f"{month.zfill(2)}/{day.zfill(2)}")  # MM/DD
                        expiry_variants.append(f"{int(month)}/{day.zfill(2)}")  # M/DD (mixed)
                        expiry_variants.append(f"{month.zfill(2)}/{int(day)}")  # MM/D (mixed)
                
                # Try each expiry variant - filter by broker to get correct channel settings
                # Include routing_mapping_id (index 23) for routed trade discrimination
                row = None
                for exp_try in expiry_variants:
                    if broker_name:
                        cursor.execute(f'''
                            SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                                   c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                                   c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct,
                                   c.profit_target_4_pct, c.profit_target_qty_1, c.profit_target_qty_2,
                                   c.profit_target_qty_3, c.profit_target_qty_4, c.trim_order_mode, c.trim_limit_offset,
                                   c.exit_strategy_mode, c.enable_dynamic_sl, c.enable_giveback_guard,
                                   c.giveback_allowed_pct, c.dynamic_sl_profile, t.routing_mapping_id,
                                   c.enable_early_trailing, c.early_trailing_activation_pct, c.early_trailing_step_pct,
                                   t.stop_loss_price, t.profit_target_price, t.executed_price, c.sl_order_mode, c.sl_limit_offset,
                                   c.trim_limit_offset_mode, c.trim_limit_offset_pct, c.use_global_risk_settings,
                                   c.ema_risk_enabled, c.ema_period, c.ema_timeframe_minutes, c.ema_buffer_pct,
                                   c.ema_exit_enabled, c.ema_escalation_enabled, c.ema_extended_hours,
                                   c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode
                            FROM trades t
                            LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id 
                                OR t.channel_id = CAST(c.id AS TEXT)
                                OR t.channel_id = c.telegram_chat_id)
                            WHERE t.symbol IN ({sym_placeholders}) AND t.asset_type = 'option' AND t.strike = ? AND t.expiry = ? AND t.call_put = ?
                            AND LOWER(t.broker) = LOWER(?)
                            AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                            ORDER BY t.id DESC LIMIT 1
                        ''', (*symbols_to_check, strike, exp_try, call_put, broker_name))
                    else:
                        cursor.execute(f'''
                            SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                                   c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                                   c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct,
                                   c.profit_target_4_pct, c.profit_target_qty_1, c.profit_target_qty_2,
                                   c.profit_target_qty_3, c.profit_target_qty_4, c.trim_order_mode, c.trim_limit_offset,
                                   c.exit_strategy_mode, c.enable_dynamic_sl, c.enable_giveback_guard,
                                   c.giveback_allowed_pct, c.dynamic_sl_profile, t.routing_mapping_id,
                                   c.enable_early_trailing, c.early_trailing_activation_pct, c.early_trailing_step_pct,
                                   t.stop_loss_price, t.profit_target_price, t.executed_price, c.sl_order_mode, c.sl_limit_offset,
                                   c.trim_limit_offset_mode, c.trim_limit_offset_pct, c.use_global_risk_settings,
                                   c.ema_risk_enabled, c.ema_period, c.ema_timeframe_minutes, c.ema_buffer_pct,
                                   c.ema_exit_enabled, c.ema_escalation_enabled, c.ema_extended_hours,
                                   c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode
                            FROM trades t
                            LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id 
                                OR t.channel_id = CAST(c.id AS TEXT)
                                OR t.channel_id = c.telegram_chat_id)
                            WHERE t.symbol IN ({sym_placeholders}) AND t.asset_type = 'option' AND t.strike = ? AND t.expiry = ? AND t.call_put = ?
                            AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                            ORDER BY t.id DESC LIMIT 1
                        ''', (*symbols_to_check, strike, exp_try, call_put))
                    row = cursor.fetchone()
                    if row:
                        break
                
                if not row and trade_id:
                    sym_placeholders = ','.join(['?' for _ in symbols_to_check])
                    cursor.execute(f'''
                        SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                               c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                               c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct,
                               c.profit_target_4_pct, c.profit_target_qty_1, c.profit_target_qty_2,
                               c.profit_target_qty_3, c.profit_target_qty_4, c.trim_order_mode, c.trim_limit_offset,
                               c.exit_strategy_mode, c.enable_dynamic_sl, c.enable_giveback_guard,
                               c.giveback_allowed_pct, c.dynamic_sl_profile, t.routing_mapping_id,
                               c.enable_early_trailing, c.early_trailing_activation_pct, c.early_trailing_step_pct,
                               t.stop_loss_price, t.profit_target_price, t.executed_price, c.sl_order_mode, c.sl_limit_offset,
                               c.trim_limit_offset_mode, c.trim_limit_offset_pct, c.use_global_risk_settings,
                               c.ema_risk_enabled, c.ema_period, c.ema_timeframe_minutes, c.ema_buffer_pct,
                               c.ema_exit_enabled, c.ema_escalation_enabled, c.ema_extended_hours,
                               c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode
                        FROM trades t
                        LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id 
                            OR t.channel_id = CAST(c.id AS TEXT)
                            OR t.channel_id = c.telegram_chat_id)
                        WHERE t.id = ?
                        AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                        ORDER BY t.id DESC LIMIT 1
                    ''', (trade_id,))
                    row = cursor.fetchone()
                    if row:
                        print(f"[RISK] ✓ Channel settings resolved via trade_id #{trade_id} (direct lookup fallback)")

                if not row:
                    return None
            else:
                # For stocks, also filter by broker to get correct channel settings
                # Include routing_mapping_id (index 23) for routed trade discrimination
                if broker_name:
                    cursor.execute(f'''
                        SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                               c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                               c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct,
                               c.profit_target_4_pct, c.profit_target_qty_1, c.profit_target_qty_2,
                               c.profit_target_qty_3, c.profit_target_qty_4, c.trim_order_mode, c.trim_limit_offset,
                               c.exit_strategy_mode, c.enable_dynamic_sl, c.enable_giveback_guard,
                               c.giveback_allowed_pct, c.dynamic_sl_profile, t.routing_mapping_id,
                               c.enable_early_trailing, c.early_trailing_activation_pct, c.early_trailing_step_pct,
                               t.stop_loss_price, t.profit_target_price, t.executed_price, c.sl_order_mode, c.sl_limit_offset,
                               c.trim_limit_offset_mode, c.trim_limit_offset_pct, c.use_global_risk_settings,
                               c.ema_risk_enabled, c.ema_period, c.ema_timeframe_minutes, c.ema_buffer_pct,
                               c.ema_exit_enabled, c.ema_escalation_enabled, c.ema_extended_hours,
                               c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode
                        FROM trades t
                        LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id
                            OR t.channel_id = CAST(c.id AS TEXT)
                            OR t.channel_id = c.telegram_chat_id)
                        WHERE t.symbol IN ({sym_placeholders}) AND t.asset_type = 'stock'
                        AND LOWER(t.broker) = LOWER(?)
                        AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                        ORDER BY t.id DESC LIMIT 1
                    ''', (*symbols_to_check, broker_name))
                else:
                    cursor.execute(f'''
                        SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                               c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                               c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct,
                               c.profit_target_4_pct, c.profit_target_qty_1, c.profit_target_qty_2,
                               c.profit_target_qty_3, c.profit_target_qty_4, c.trim_order_mode, c.trim_limit_offset,
                               c.exit_strategy_mode, c.enable_dynamic_sl, c.enable_giveback_guard,
                               c.giveback_allowed_pct, c.dynamic_sl_profile, t.routing_mapping_id,
                               c.enable_early_trailing, c.early_trailing_activation_pct, c.early_trailing_step_pct,
                               t.stop_loss_price, t.profit_target_price, t.executed_price, c.sl_order_mode, c.sl_limit_offset,
                               c.trim_limit_offset_mode, c.trim_limit_offset_pct, c.use_global_risk_settings,
                               c.ema_risk_enabled, c.ema_period, c.ema_timeframe_minutes, c.ema_buffer_pct,
                               c.ema_exit_enabled, c.ema_escalation_enabled, c.ema_extended_hours,
                               c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode
                        FROM trades t
                        LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id
                            OR t.channel_id = CAST(c.id AS TEXT)
                            OR t.channel_id = c.telegram_chat_id)
                        WHERE t.symbol IN ({sym_placeholders}) AND t.asset_type = 'stock'
                        AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                        ORDER BY t.id DESC LIMIT 1
                    ''', (*symbols_to_check,))
                row = cursor.fetchone()
                
                if not row and trade_id:
                    cursor.execute(f'''
                        SELECT t.channel_id, c.profit_target_1_pct, c.profit_target_2_pct, c.profit_target_3_pct,
                               c.stop_loss_pct, c.trailing_stop_pct, c.trailing_activation_pct, c.name,
                               c.risk_management_enabled, c.leave_runner_enabled, c.leave_runner_pct,
                               c.profit_target_4_pct, c.profit_target_qty_1, c.profit_target_qty_2,
                               c.profit_target_qty_3, c.profit_target_qty_4, c.trim_order_mode, c.trim_limit_offset,
                               c.exit_strategy_mode, c.enable_dynamic_sl, c.enable_giveback_guard,
                               c.giveback_allowed_pct, c.dynamic_sl_profile, t.routing_mapping_id,
                               c.enable_early_trailing, c.early_trailing_activation_pct, c.early_trailing_step_pct,
                               t.stop_loss_price, t.profit_target_price, t.executed_price, c.sl_order_mode, c.sl_limit_offset,
                               c.trim_limit_offset_mode, c.trim_limit_offset_pct, c.use_global_risk_settings,
                               c.ema_risk_enabled, c.ema_period, c.ema_timeframe_minutes, c.ema_buffer_pct,
                               c.ema_exit_enabled, c.ema_escalation_enabled, c.ema_extended_hours,
                               c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode
                        FROM trades t
                        LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id
                            OR t.channel_id = CAST(c.id AS TEXT)
                            OR t.channel_id = c.telegram_chat_id)
                        WHERE t.id = ?
                        AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                        ORDER BY t.id DESC LIMIT 1
                    ''', (trade_id,))
                    row = cursor.fetchone()
                    if row:
                        print(f"[RISK] ✓ Channel settings resolved via trade_id #{trade_id} (stock direct lookup fallback)")
                
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
                
                # PRIORITY 2: Channel-level risk settings
                # If risk management is explicitly enabled at channel level, use channel settings
                # This takes priority over use_global_risk_settings flag
                risk_enabled = row[8] if len(row) > 8 else 0
                use_global = row[34] if (len(row) > 34 and row[34] is not None) else 1  # Default: use global (backwards compat, handles NULL from LEFT JOIN)
                
                if risk_enabled:
                    pass
                elif use_global:
                    trade_sl_price = row[27] if len(row) > 27 and row[27] else None
                    trade_pt_price = row[28] if len(row) > 28 and row[28] else None
                    trade_entry_price = row[29] if len(row) > 29 and row[29] else None
                    if not trade_entry_price or trade_entry_price <= 0:
                        try:
                            if trade_id:
                                cursor.execute('SELECT intended_price FROM trades WHERE id = ?', (trade_id,))
                            else:
                                cursor.execute('SELECT intended_price FROM trades WHERE id = (SELECT MAX(id) FROM trades WHERE symbol IN ({}) AND asset_type = ? AND status IN (?, ?, ?) AND direction = ?{})'.format(
                                    ','.join(['?' for _ in symbols_to_check]),
                                    ' AND LOWER(broker) = LOWER(?)' if broker_name else ''),
                                    (*symbols_to_check, asset_type, 'OPEN', 'PENDING', 'PARTIAL', 'BTO', *([broker_name] if broker_name else [])))
                            ip_row = cursor.fetchone()
                            if ip_row and ip_row[0] and ip_row[0] > 0:
                                trade_entry_price = ip_row[0]
                        except Exception:
                            pass
                    if trade_sl_price or trade_pt_price:
                        sl_override = 0
                        pt_override = 0
                        if trade_sl_price and trade_entry_price and trade_entry_price > 0:
                            sl_pct = ((trade_entry_price - trade_sl_price) / trade_entry_price) * 100
                            if sl_pct > 0:
                                sl_override = round(sl_pct, 1)
                                print(f"[RISK] ✓ Bracket SL override: ${trade_sl_price:.2f} ({sl_override}% from entry ${trade_entry_price:.2f})")
                        if trade_pt_price and trade_entry_price and trade_entry_price > 0:
                            pt_pct = ((trade_pt_price - trade_entry_price) / trade_entry_price) * 100
                            if pt_pct > 0:
                                pt_override = round(pt_pct, 1)
                                print(f"[RISK] ✓ Bracket PT override: ${trade_pt_price:.2f} ({pt_override}% from entry ${trade_entry_price:.2f})")
                        if sl_override > 0 or pt_override > 0:
                            channel_name = row[7] or 'Unknown'
                            channel_exit_mode = row[18] if len(row) > 18 and row[18] else 'hybrid'
                            print(f"[RISK] ✓ Using signal bracket SL/PT for '{channel_name}' (global risk disabled, but signal has explicit levels, exit_mode={channel_exit_mode})")
                            return ChannelRiskSettings(
                                channel_id=str(row[0]),
                                channel_name=channel_name,
                                profit_target_1_pct=pt_override if pt_override > 0 else 0,
                                stop_loss_pct=sl_override if sl_override > 0 else 0,
                                trailing_stop_pct=row[5] or 0,
                                trailing_activation_pct=row[6] or 15.0,
                                exit_strategy_mode=channel_exit_mode,
                            )
                    return None
                else:
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
                
                # Extract exit strategy mode BEFORE applying overrides
                # Default to 'hybrid' (matches DB schema default) - NOT 'signal' which skips all automated risk
                exit_mode = row[18] if len(row) > 18 and row[18] else 'hybrid'
                
                # Apply trade-level SL/PT overrides ONLY when exit mode allows it
                # exit_mode='risk' → channel settings are authoritative, signal values ignored
                # exit_mode='hybrid' or 'signal' → signal-embedded SL/PT can override channel defaults
                if exit_mode != 'risk':
                    if trade_sl_price and trade_entry_price and trade_entry_price > 0:
                        sl_pct_calc = ((trade_entry_price - trade_sl_price) / trade_entry_price) * 100
                        if sl_pct_calc > 0:
                            sl = round(sl_pct_calc, 1)
                            print(f"[RISK] Using trade-level SL: ${trade_sl_price:.2f} ({sl}% from entry ${trade_entry_price:.2f})")
                    
                    if trade_pt_price and trade_entry_price and trade_entry_price > 0:
                        pt_pct_calc = ((trade_pt_price - trade_entry_price) / trade_entry_price) * 100
                        if pt_pct_calc > 0:
                            pt_pct_rounded = round(pt_pct_calc, 1)
                            if pt2 > 0 and pt_pct_rounded > pt2:
                                print(f"[RISK] Signal PT ${trade_pt_price:.2f} ({pt_pct_rounded}%) would break tier ordering (T2={pt2}%) — keeping channel tiered targets")
                            else:
                                pt1 = pt_pct_rounded
                                print(f"[RISK] Using trade-level PT: ${trade_pt_price:.2f} ({pt1}% from entry ${trade_entry_price:.2f})")
                else:
                    if trade_sl_price or trade_pt_price:
                        print(f"[RISK] Exit mode is 'risk' - using channel settings (ignoring signal SL/PT override)")
                
                # Extract custom quantities (None means auto-calculate)
                qty1 = row[12] if len(row) > 12 else None
                qty2 = row[13] if len(row) > 13 else None
                qty3 = row[14] if len(row) > 14 else None
                qty4 = row[15] if len(row) > 15 else None
                
                # Extract trim order settings
                trim_mode = row[16] if len(row) > 16 and row[16] else 'market'
                trim_offset = row[17] if len(row) > 17 and row[17] is not None else 0.01
                trim_offset_mode = row[32] if len(row) > 32 and row[32] else 'dollar'
                trim_offset_pct = row[33] if len(row) > 33 and row[33] is not None else 2.0
                
                # exit_mode already extracted above (before SL/PT override logic)
                
                # Extract enhanced risk settings
                enable_dynamic_sl = bool(row[19]) if len(row) > 19 and row[19] else False
                enable_giveback_guard = bool(row[20]) if len(row) > 20 and row[20] else False
                giveback_allowed_pct = row[21] if len(row) > 21 and row[21] is not None else 30.0
                dynamic_sl_profile = row[22] if len(row) > 22 and row[22] else 'standard'
                
                # Extract Early Trailing settings (indices 24-26, after routing_mapping_id at 23)
                enable_early_trailing = bool(row[24]) if len(row) > 24 and row[24] else False
                early_trailing_activation_pct = row[25] if len(row) > 25 and row[25] is not None else 5.0
                early_trailing_step_pct = row[26] if len(row) > 26 and row[26] is not None else 3.0
                
                # Extract SL order mode (index 30, after executed_price at 29)
                sl_order_mode = row[30] if len(row) > 30 and row[30] else 'limit'
                
                # Extract SL limit offset (index 31, after sl_order_mode)
                sl_limit_offset = row[31] if len(row) > 31 and row[31] is not None else 0.03

                # Extract EMA Risk settings (indices 35-43, after use_global_risk_settings at 34)
                ema_risk_enabled = bool(row[35]) if len(row) > 35 and row[35] else False
                ema_period = row[36] if len(row) > 36 and row[36] is not None else 5
                ema_timeframe_minutes = row[37] if len(row) > 37 and row[37] is not None else 5
                ema_buffer_pct = row[38] if len(row) > 38 and row[38] is not None else 0.1
                ema_exit_enabled = bool(row[39]) if len(row) > 39 and row[39] is not None else True
                ema_escalation_enabled = bool(row[40]) if len(row) > 40 and row[40] is not None else True
                ema_extended_hours = bool(row[41]) if len(row) > 41 and row[41] else False
                ema_use_underlying = bool(row[42]) if len(row) > 42 and row[42] is not None else True
                ema_no_trend_candles = row[43] if len(row) > 43 and row[43] is not None else 3
                escalation_only_mode = bool(row[44]) if len(row) > 44 and row[44] else False

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
                    trim_limit_offset_mode=trim_offset_mode,
                    trim_limit_offset_pct=trim_offset_pct,
                    sl_order_mode=sl_order_mode,
                    sl_limit_offset=sl_limit_offset,
                    exit_strategy_mode=exit_mode,
                    enable_dynamic_sl=enable_dynamic_sl,
                    enable_giveback_guard=enable_giveback_guard,
                    giveback_allowed_pct=giveback_allowed_pct,
                    dynamic_sl_profile=dynamic_sl_profile,
                    enable_early_trailing=enable_early_trailing,
                    early_trailing_activation_pct=early_trailing_activation_pct,
                    early_trailing_step_pct=early_trailing_step_pct,
                    ema_risk_enabled=ema_risk_enabled,
                    ema_period=ema_period,
                    ema_timeframe_minutes=ema_timeframe_minutes,
                    ema_buffer_pct=ema_buffer_pct,
                    ema_exit_enabled=ema_exit_enabled,
                    ema_escalation_enabled=ema_escalation_enabled,
                    ema_extended_hours=ema_extended_hours,
                    ema_use_underlying=ema_use_underlying,
                    ema_no_trend_candles=ema_no_trend_candles,
                    escalation_only_mode=escalation_only_mode
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
        
        broker = (broker or '').strip()
        symbol = (symbol or '').strip().upper()
        
        SYMBOL_ALIASES = {
            'SPX': ['SPXW', 'SPX'],
            'SPXW': ['SPX', 'SPXW'],
            'NDX': ['NDXP', 'NDX'],
            'NDXP': ['NDX', 'NDXP'],
            'VIX': ['VIXW', 'VIX'],
            'VIXW': ['VIX', 'VIXW'],
            'RUT': ['RUTW', 'RUT'],
            'RUTW': ['RUT', 'RUTW'],
            'DJX': ['DJXW', 'DJX'],
            'DJXW': ['DJX', 'DJXW'],
        }
        symbols_to_check = [symbol] + [s for s in SYMBOL_ALIASES.get(symbol, []) if s != symbol]
        
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
                
                cp_normalized = call_put.upper()[0] if call_put else None
                
                for sym_try in symbols_to_check:
                    for exp_try in expiry_variants:
                        if cp_normalized:
                            cursor.execute('''
                                SELECT id FROM trades
                                WHERE symbol = ? AND asset_type = 'option'
                                AND strike = ? AND expiry = ? AND call_put = ?
                                AND status IN ('OPEN', 'PENDING') AND direction = 'BTO'
                                AND LOWER(broker) = LOWER(?)
                                ORDER BY id DESC LIMIT 1
                            ''', (sym_try, strike, exp_try, cp_normalized, broker))
                        else:
                            cursor.execute('''
                                SELECT id FROM trades
                                WHERE symbol = ? AND asset_type = 'option'
                                AND strike = ? AND expiry = ?
                                AND status IN ('OPEN', 'PENDING') AND direction = 'BTO'
                                AND LOWER(broker) = LOWER(?)
                                ORDER BY id DESC LIMIT 1
                            ''', (sym_try, strike, exp_try, broker))
                        
                        row = cursor.fetchone()
                        if row:
                            return row[0]
                
                for sym_try in symbols_to_check:
                    cursor.execute('''
                        SELECT id FROM trades
                        WHERE symbol = ? AND asset_type = 'option'
                        AND strike = ? AND status IN ('OPEN', 'PENDING') AND direction = 'BTO'
                        AND LOWER(broker) = LOWER(?)
                        ORDER BY id DESC LIMIT 1
                    ''', (sym_try, strike, broker))
                    row = cursor.fetchone()
                    if row:
                        return row[0]
                return None
            elif asset_type == 'option' and (not strike or strike == 0.0):
                from datetime import datetime
                expiry_variants = []
                if expiry:
                    expiry_variants.append(expiry)
                    if '/' in expiry:
                        parts = expiry.split('/')
                        if len(parts) == 2:
                            mm, dd = parts[0].zfill(2), parts[1].zfill(2)
                            year = datetime.now().year
                            expiry_variants.append(f"{year}-{mm}-{dd}")
                            expiry_variants.append(f"{mm}/{dd}")
                            expiry_variants.append(f"{int(parts[0])}/{int(parts[1])}")
                        elif len(parts) == 3:
                            mm, dd = parts[0].zfill(2), parts[1].zfill(2)
                            yy_raw = parts[2]
                            year = (2000 + int(yy_raw)) if len(yy_raw) == 2 else int(yy_raw)
                            expiry_variants.append(f"{year}-{mm}-{dd}")
                            expiry_variants.append(f"{mm}/{dd}")
                            expiry_variants.append(f"{int(parts[0])}/{int(parts[1])}")
                    elif '-' in expiry:
                        parts = expiry.split('-')
                        if len(parts) == 3 and len(parts[0]) == 4:
                            yyyy, mm, dd = parts[0], parts[1].zfill(2), parts[2].zfill(2)
                            expiry_variants.append(f"{mm}/{dd}")
                            expiry_variants.append(f"{int(mm)}/{int(dd)}")
                    seen = set()
                    expiry_variants = [x for x in expiry_variants if not (x in seen or seen.add(x))]

                cp_normalized = call_put.upper()[0] if call_put else None

                for sym_try in symbols_to_check:
                    for exp_try in (expiry_variants or ['']):
                        if exp_try and cp_normalized:
                            cursor.execute('''
                                SELECT id FROM trades
                                WHERE symbol = ? AND asset_type = 'option'
                                AND status IN ('OPEN', 'PENDING') AND direction = 'BTO'
                                AND LOWER(broker) = LOWER(?) AND expiry = ? AND call_put = ?
                                ORDER BY id DESC
                            ''', (sym_try, broker, exp_try, cp_normalized))
                        elif exp_try:
                            cursor.execute('''
                                SELECT id FROM trades
                                WHERE symbol = ? AND asset_type = 'option'
                                AND status IN ('OPEN', 'PENDING') AND direction = 'BTO'
                                AND LOWER(broker) = LOWER(?) AND expiry = ?
                                ORDER BY id DESC
                            ''', (sym_try, broker, exp_try))
                        else:
                            cursor.execute('''
                                SELECT id FROM trades
                                WHERE symbol = ? AND asset_type = 'option'
                                AND status IN ('OPEN', 'PENDING') AND direction = 'BTO'
                                AND LOWER(broker) = LOWER(?)
                                ORDER BY id DESC
                            ''', (sym_try, broker))
                        rows = cursor.fetchall()
                        if len(rows) == 1:
                            print(f"[RISK] ✓ Fuzzy trade lookup (strike=0.0): matched trade #{rows[0][0]} for {sym_try} on {broker}")
                            return rows[0][0]
                        elif len(rows) > 1:
                            row_ids = [r[0] for r in rows]
                            cursor.execute(f'''
                                SELECT id, status FROM trades WHERE id IN ({",".join("?" * len(row_ids))})
                            ''', row_ids)
                            status_rows = cursor.fetchall()
                            open_rows = [r for r in status_rows if r[1] == 'OPEN']
                            if len(open_rows) == 1:
                                print(f"[RISK] ✓ Fuzzy trade lookup (strike=0.0): {len(rows)} candidates, preferring OPEN trade #{open_rows[0][0]} for {sym_try} on {broker}")
                                return open_rows[0][0]
                            print(f"[RISK] ⚠️ Fuzzy trade lookup (strike=0.0): {len(rows)} ambiguous matches for {sym_try} on {broker} — skipping")
                return None
            else:
                for sym_try in symbols_to_check:
                    cursor.execute('''
                        SELECT id FROM trades
                        WHERE symbol = ? AND asset_type = 'stock'
                        AND status IN ('OPEN', 'PENDING') AND direction = 'BTO'
                        AND LOWER(broker) = LOWER(?)
                        ORDER BY id DESC LIMIT 1
                    ''', (sym_try, broker))
                    row = cursor.fetchone()
                    if row:
                        return row[0]
                return None
        except Exception as e:
            print(f"[RISK] Warning: Could not lookup trade_id: {e}")
            return None
    
    def auto_import_manual_position(
        self,
        position: 'PositionSnapshot'
    ) -> Optional[int]:
        """Instantly import a broker position not tracked in DB as a synthetic trade.
        
        Called by the risk engine when it detects a live broker position with no 
        matching DB trade. Creates a trade entry immediately so risk state can persist.
        Returns the new trade_id or None if import failed.
        
        This is the FASTEST detection path (~1 second) vs broker_sync (30 seconds).
        """
        if not self._db:
            return None
        
        try:
            from datetime import datetime
            
            entry_price = float(position.avg_cost) if position.avg_cost else 0
            current_price = float(position.current_price) if position.current_price else entry_price
            quantity = float(position.quantity) if position.quantity else 1
            
            multiplier = 100 if position.asset == 'option' else 1
            pnl = (current_price - entry_price) * quantity * multiplier if entry_price > 0 else 0
            pnl_percent = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            
            call_put = None
            if position.asset == 'option' and position.direction:
                d = position.direction.upper().strip()
                if d in ('CALL', 'C'):
                    call_put = 'C'
                elif d in ('PUT', 'P'):
                    call_put = 'P'
                else:
                    call_put = d
            
            trade_data = {
                'symbol': position.symbol,
                'direction': 'BTO',
                'quantity': quantity,
                'intended_price': entry_price,
                'executed_price': entry_price,
                'current_price': current_price,
                'pnl': round(pnl, 2),
                'pnl_percent': round(pnl_percent, 4),
                'broker': position.broker,
                'status': 'OPEN',
                'asset_type': position.asset or 'stock',
                'executed': True,
                'channel_id': None,
                'message_id': None,
                'order_id': None,
                'source': 'risk_auto_import',
                'stop_loss_price': None,
                'profit_target_price': None,
            }
            
            if position.asset == 'option':
                trade_data.update({
                    'strike': position.strike,
                    'expiry': position.expiry,
                    'call_put': call_put
                })
            
            try:
                from gui_app.database import get_trades
                existing = get_trades(status='OPEN', limit=2000) + get_trades(status='PENDING', limit=1000)
                SYMBOL_ALIASES = {
                    'SPX': ['SPXW', 'SPX'], 'SPXW': ['SPX', 'SPXW'],
                    'NDX': ['NDXP', 'NDX'], 'NDXP': ['NDX', 'NDXP'],
                    'VIX': ['VIXW', 'VIX'], 'VIXW': ['VIX', 'VIXW'],
                    'RUT': ['RUTW', 'RUT'], 'RUTW': ['RUT', 'RUTW'],
                    'DJX': ['DJXW', 'DJX'], 'DJXW': ['DJX', 'DJXW'],
                }
                symbols_to_match = set([position.symbol] + SYMBOL_ALIASES.get(position.symbol, []))

                fuzzy_candidates = []
                for ex in existing:
                    ex_broker = (ex.get('broker') or '').upper()
                    ex_symbol = (ex.get('symbol') or '').upper()
                    if ex_symbol in symbols_to_match and ex_broker == position.broker.upper():
                        if position.asset == 'stock':
                            return ex.get('id')
                        elif position.asset == 'option':
                            ex_strike = float(ex.get('strike') or 0)
                            pos_strike = float(position.strike or 0)
                            ex_expiry = str(ex.get('expiry') or '').replace('/', '').replace('-', '')[-4:]
                            pos_expiry = str(position.expiry or '').replace('/', '').replace('-', '')[-4:]
                            if (abs(ex_strike - pos_strike) < 0.01 and
                                ex.get('call_put') == call_put and
                                (not pos_expiry or not ex_expiry or ex_expiry == pos_expiry)):
                                return ex.get('id')
                            if pos_strike == 0.0 and (not pos_expiry or not ex_expiry or ex_expiry == pos_expiry):
                                if call_put and ex.get('call_put') == call_put:
                                    fuzzy_candidates.append(ex)
                                elif not call_put:
                                    fuzzy_candidates.append(ex)

                if fuzzy_candidates and float(position.strike or 0) == 0.0:
                    if len(fuzzy_candidates) > 1:
                        open_only = [ex for ex in fuzzy_candidates if ex.get('status') == 'OPEN']
                        if len(open_only) >= 1:
                            fuzzy_candidates = open_only

                    if len(fuzzy_candidates) == 1:
                        matched = fuzzy_candidates[0]
                        print(f"[RISK] ✓ Fuzzy-matched position (strike=0.0) to trade #{matched.get('id')} "
                              f"({matched.get('symbol')} {matched.get('strike')}{matched.get('call_put')} {matched.get('expiry')})")
                        return matched.get('id')
                    elif len(fuzzy_candidates) > 1:
                        qty_matches = [ex for ex in fuzzy_candidates if int(ex.get('quantity', 0)) == int(quantity)]
                        if len(qty_matches) == 1:
                            matched = qty_matches[0]
                            print(f"[RISK] ✓ Fuzzy-matched position (strike=0.0, qty={int(quantity)}) to trade #{matched.get('id')} "
                                  f"({matched.get('symbol')} {matched.get('strike')}{matched.get('call_put')} {matched.get('expiry')})")
                            return matched.get('id')
                        else:
                            print(f"[RISK] ⚠️ Fuzzy-match ambiguous: {len(fuzzy_candidates)} candidates for {position.symbol} (strike=0.0) — skipping auto-import")
                            return None
            except Exception:
                pass
            
            if float(position.strike or 0) == 0.0 and position.asset == 'option':
                print(f"[RISK] ⚠️ Refusing to auto-import option with strike=0.0 ({position.symbol}) — waiting for enriched data")
                return None

            if hasattr(self._db, 'add_trade'):
                trade_id = self._db.add_trade(trade_data)
            else:
                from gui_app.database import add_trade
                trade_id = add_trade(trade_data)
            
            return trade_id
            
        except Exception as e:
            print(f"[RISK] ⚠️ Auto-import failed for {position.symbol}: {e}")
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
    
    DEFAULT_MONITORING_INTERVAL = 1  # seconds - real-time monitoring for live positions
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
        trading212_broker=None,
        webull_broker=None,
        monitoring_interval: int = DEFAULT_MONITORING_INTERVAL,
        trailing_activation_pct: float = DEFAULT_TRAILING_ACTIVATION,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        sync_ready_event: Optional[asyncio.Event] = None
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
            webull_broker: Optional WebullBroker instance for REST price refresh
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
        self.trading212_broker = trading212_broker
        self.monitoring_interval = monitoring_interval
        self.trailing_activation_pct = trailing_activation_pct
        self.loop = loop or asyncio.get_event_loop()

        self._webull_broker = webull_broker
        self.webull_broker = webull_broker
        if not self._webull_broker:
            try:
                if hasattr(position_fetcher, '__self__'):
                    _pf_self = position_fetcher.__self__
                    if hasattr(_pf_self, 'wb') or hasattr(_pf_self, '_client'):
                        self._webull_broker = _pf_self
                        self.webull_broker = _pf_self
            except Exception:
                pass
        if self._webull_broker:
            print(f"[RISK] ✓ Webull broker reference acquired ({type(self._webull_broker).__name__})")
        
        self._stuck_price_tracker = {}
        self._STUCK_PRICE_THRESHOLD_REGULAR = 3
        self._STUCK_PRICE_THRESHOLD_EXTENDED = 15
        self._STUCK_PRICE_THRESHOLD = 3
        self._rest_repaired_prices = {}
        self._rest_repair_cycle_keys = {}
        self._price_unverified = {}
        self._STALENESS_EXIT_BLOCK_THRESHOLD = 10
        
        self._sync_ready_event = sync_ready_event
        self.cache = PositionCache()
        self._running = False
        self._permanent_failure_keys = self._load_permanent_failures()
        
        import threading as _threading
        self._exit_executed_lock = _threading.Lock()
        self._exit_executed_keys = set()

        self._dirty_symbols = {}
        self._dirty_lock = _threading.Lock()
        self._price_wake_event = asyncio.Event()
        self._monitored_symbols = set()
        self._monitored_symbols_lock = _threading.Lock()
        self._hub_subscribed = False
        self._incremental_cycle_lock = asyncio.Lock()
        self._last_positions_snapshot = []
        self._tick_eval_count = 0
        self._tick_eval_total_latency_ms = 0.0

        self._fill_watch_orders = {}
        self._fill_watch_lock = _threading.Lock()
        self._FILL_WATCH_TIMEOUT = 30
        self._FILL_WATCH_BROKER_INTERVALS = {
            'WEBULL': 2.0,
            'SCHWAB': 0.5,
            'IBKR': 0.5,
            'ALPACA': 0.5,
            'TASTYTRADE': 0.5,
            'ROBINHOOD': 8.0,
            'TRADING212': 5.0,
        }
        self._FILL_WATCH_DEFAULT_INTERVAL = 1.0

    def notify_order_placed(self, broker_name: str, order_id: str = '', symbol: str = ''):
        import time as _nop_time
        watch_key = f"{broker_name}_{order_id or symbol or _nop_time.time()}"
        broker_upper = broker_name.upper()
        baseline = self._get_broker_symbol_baseline(broker_upper, symbol.upper() if symbol else '')
        with self._fill_watch_lock:
            self._fill_watch_orders[watch_key] = {
                'broker': broker_upper,
                'order_id': order_id,
                'symbol': symbol.upper() if symbol else '',
                'placed_at': _nop_time.time(),
                'baseline_total_qty': baseline['total_qty'],
                'baseline_position_count': baseline['position_count'],
                'symbol_existed': baseline['symbol_existed'],
            }
        self._force_rest_refresh = True
        try:
            if 'WEBULL' in broker_upper:
                from src.services.webull_data_hub import get_webull_data_hub
                get_webull_data_hub().request_risk_eval()
            elif 'SCHWAB' in broker_upper:
                from src.services.schwab_data_hub import get_schwab_data_hub
                get_schwab_data_hub().request_risk_eval()
            elif 'IBKR' in broker_upper:
                from src.services.ibkr_data_hub import get_ibkr_data_hub
                get_ibkr_data_hub().request_risk_eval()
        except Exception:
            pass
        _fw_interval = self._FILL_WATCH_DEFAULT_INTERVAL
        for bk, bv in self._FILL_WATCH_BROKER_INTERVALS.items():
            if bk in broker_upper:
                _fw_interval = bv
                break
        existed_tag = " (scale-in)" if baseline['symbol_existed'] else " (new position)"
        print(f"[RISK] ⚡ FILL WATCH: Order placed on {broker_name} for {symbol}{existed_tag} — rapid polling {_fw_interval}s for {self._FILL_WATCH_TIMEOUT}s")

    def _has_active_fill_watches(self) -> bool:
        with self._fill_watch_lock:
            return len(self._fill_watch_orders) > 0

    def _get_broker_symbol_baseline(self, broker_upper: str, symbol_upper: str) -> dict:
        try:
            snapshot = list(self._last_positions_snapshot or [])
        except Exception:
            snapshot = []
        total_qty = 0.0
        position_count = 0
        symbol_existed = False
        for p in snapshot:
            p_broker = (getattr(p, 'broker', '') or '').upper()
            if broker_upper not in p_broker:
                continue
            position_count += 1
            if symbol_upper and symbol_upper in (getattr(p, 'symbol', '') or '').upper():
                symbol_existed = True
                total_qty += float(getattr(p, 'quantity', 0) or 0)
        return {
            'total_qty': total_qty,
            'position_count': position_count,
            'symbol_existed': symbol_existed,
        }

    def _expire_fill_watches(self):
        import time as _efw_time
        now = _efw_time.time()
        with self._fill_watch_lock:
            expired = [k for k, v in self._fill_watch_orders.items()
                       if (now - v['placed_at']) > self._FILL_WATCH_TIMEOUT]
            for k in expired:
                w = self._fill_watch_orders.pop(k)
                elapsed = now - w['placed_at']
                print(f"[RISK] ⏱ Fill watch expired for {w['broker']} order {w.get('order_id', '?')} after {elapsed:.1f}s — order chaser will handle")

    def _check_fill_watch_detected(self, positions):
        import time as _cfw_time
        now = _cfw_time.time()

        broker_data = {}
        for p in (positions or []):
            b = (getattr(p, 'broker', '') or '').upper()
            if b not in broker_data:
                broker_data[b] = {'count': 0, 'symbols': {}}
            broker_data[b]['count'] += 1
            sym = (getattr(p, 'symbol', '') or '').upper()
            qty = float(getattr(p, 'quantity', 0) or 0)
            broker_data[b]['symbols'][sym] = broker_data[b]['symbols'].get(sym, 0) + qty

        with self._fill_watch_lock:
            resolved = []
            for key, watch in self._fill_watch_orders.items():
                broker_upper = watch['broker']
                bd = broker_data.get(broker_upper, {'count': 0, 'symbols': {}})
                sym = watch.get('symbol', '')
                elapsed_ms = (now - watch['placed_at']) * 1000

                if sym and sym in bd['symbols']:
                    if not watch.get('symbol_existed'):
                        print(f"[RISK] ⚡ FILL DETECTED: {sym} on {broker_upper} (new position) — {elapsed_ms:.0f}ms after order placement")
                        resolved.append(key)
                        continue
                    else:
                        current_qty = bd['symbols'].get(sym, 0)
                        baseline_qty = watch.get('baseline_total_qty', 0)
                        if current_qty > baseline_qty:
                            print(f"[RISK] ⚡ FILL DETECTED: {sym} on {broker_upper} (scale-in qty {baseline_qty:.0f}→{current_qty:.0f}) — {elapsed_ms:.0f}ms after order placement")
                            resolved.append(key)
                            continue

                baseline_count = watch.get('baseline_position_count', -1)
                if baseline_count >= 0 and bd['count'] > baseline_count:
                    print(f"[RISK] ⚡ FILL DETECTED: New position on {broker_upper} (count {baseline_count}→{bd['count']}) — {elapsed_ms:.0f}ms after order placement")
                    resolved.append(key)

            for k in resolved:
                self._fill_watch_orders.pop(k, None)

    def release_exit_marker(self, pos_key: str):
        """Clear the exit-executed marker for a position key.
        
        Must be called when:
        - A risk STC order succeeds (position sold)
        - A position closes (cleanup)
        - An exit lease expires and the closing flag resets for retry
        This prevents stale markers from blocking future exits on
        re-opened positions with the same key.
        """
        with self._exit_executed_lock:
            if pos_key in self._exit_executed_keys:
                self._exit_executed_keys.discard(pos_key)
                print(f"[RISK] ✓ Released exit marker for {pos_key}")
        try:
            from src.risk.exit_lease_manager import get_exit_lease_manager
            get_exit_lease_manager().force_release(pos_key)
        except Exception:
            pass
    
    _PERMANENT_FAILURES_FILE = Path.cwd() / '.permanent_failures.json'
    
    def _load_permanent_failures(self) -> set:
        try:
            import json
            if self._PERMANENT_FAILURES_FILE.exists():
                with open(self._PERMANENT_FAILURES_FILE, 'r') as f:
                    data = json.load(f)
                keys = set(data) if isinstance(data, list) else set()
                if keys:
                    print(f"[RISK] ✓ Loaded {len(keys)} permanent failure blocklist entries from disk")
                return keys
        except Exception as e:
            print(f"[RISK] ⚠️ Failed to load permanent failures file: {e}")
        return set()
    
    def _save_permanent_failures(self) -> None:
        try:
            import json
            with open(self._PERMANENT_FAILURES_FILE, 'w') as f:
                json.dump(list(self._permanent_failure_keys), f, indent=2)
        except Exception as e:
            print(f"[RISK] ⚠️ Failed to save permanent failures file: {e}")
    
    def _subscribe_to_price_streams(self):
        if self._hub_subscribed:
            return
        _any_subscribed = False

        def _on_quote_update(data):
            if not data or not isinstance(data, dict):
                return
            symbol = data.get('symbol', '')
            if not symbol:
                q = data.get('quote')
                if q:
                    symbol = getattr(q, 'symbol', '') if hasattr(q, 'symbol') else (q.get('symbol', '') if isinstance(q, dict) else '')
            if not symbol:
                return
            symbol = symbol.upper()
            with self._monitored_symbols_lock:
                if symbol not in self._monitored_symbols:
                    return
            import time as _t
            tick_ts = _t.monotonic()
            with self._dirty_lock:
                if symbol not in self._dirty_symbols or tick_ts < self._dirty_symbols[symbol]:
                    self._dirty_symbols[symbol] = tick_ts
            try:
                self.loop.call_soon_threadsafe(self._price_wake_event.set)
            except RuntimeError:
                pass

        self._quote_handler = _on_quote_update

        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            hub.on('quote_updated', _on_quote_update)
            _any_subscribed = True
            print("[RISK] ✓ Subscribed to Webull streaming prices (event-driven risk)")
        except ImportError:
            pass
        except Exception as e:
            print(f"[RISK] ⚠️ Webull hub subscription error: {e}")

        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            schwab_hub = get_schwab_data_hub()
            schwab_hub.on('quote_updated', _on_quote_update)
            _any_subscribed = True
            print("[RISK] ✓ Subscribed to Schwab streaming prices (event-driven risk)")
        except ImportError:
            pass
        except Exception as e:
            print(f"[RISK] ⚠️ Schwab hub subscription error: {e}")

        try:
            from src.services.ibkr_data_hub import get_ibkr_data_hub
            ibkr_hub = get_ibkr_data_hub()
            ibkr_hub.on('quote_updated', _on_quote_update)
            _any_subscribed = True
            print("[RISK] ✓ Subscribed to IBKR streaming prices (event-driven risk)")
        except ImportError:
            pass
        except Exception as e:
            print(f"[RISK] ⚠️ IBKR hub subscription error: {e}")

        try:
            from src.services.tastytrade_data_hub import get_tastytrade_data_hub
            tt_hub = get_tastytrade_data_hub()
            tt_hub.on('quote_updated', _on_quote_update)
            _any_subscribed = True
            print("[RISK] ✓ Subscribed to Tastytrade streaming prices (event-driven risk)")
        except ImportError:
            pass
        except Exception as e:
            print(f"[RISK] ⚠️ Tastytrade hub subscription error: {e}")

        self._hub_subscribed = _any_subscribed

    def _update_monitored_symbols(self, positions):
        symbols = set()
        non_streaming_symbols = set()
        for p in positions:
            sym = p.symbol.upper()
            symbols.add(sym)
            if hasattr(p, 'raw_symbol') and p.raw_symbol:
                symbols.add(p.raw_symbol.upper())
            broker_upper = (p.broker or '').upper()
            has_streaming = 'WEBULL' in broker_upper or broker_upper == 'SCHWAB' or 'IBKR' in broker_upper
            if not has_streaming and 'TASTYTRADE' in broker_upper:
                try:
                    from src.services.tastytrade_data_hub import get_tastytrade_data_hub
                    has_streaming = get_tastytrade_data_hub().is_streaming()
                except Exception:
                    pass
            if not has_streaming:
                if p.asset != 'option':
                    non_streaming_symbols.add(sym)
        with self._monitored_symbols_lock:
            self._monitored_symbols = symbols
        if non_streaming_symbols:
            self._request_cross_broker_subscriptions(non_streaming_symbols)

    def _request_cross_broker_subscriptions(self, symbols):
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            hub = get_schwab_data_hub()
            if hub.is_streaming():
                already = hub.get_subscribed_symbols()
                needed = symbols - already
                if needed:
                    hub.request_subscribe_equities(needed)
        except Exception:
            pass

    async def _run_incremental_eval(self):
        if not getattr(self, '_first_sync_completed', False):
            return
        if self._incremental_cycle_lock.locked():
            return
        async with self._incremental_cycle_lock:
            import time as _t
            eval_start = _t.monotonic()

            with self._dirty_lock:
                dirty = dict(self._dirty_symbols)
                self._dirty_symbols.clear()

            if not dirty:
                return

            dirty_symbol_names = set(dirty.keys())
            earliest_tick = min(dirty.values())

            positions = self._last_positions_snapshot
            if not positions:
                return

            self._update_prices_from_hub(positions)

            risk_settings = self._get_risk_settings()
            if not risk_settings.enabled:
                channel_count = self.db_adapter.count_channels_with_risk()
                if channel_count == 0:
                    return

            evaluated = 0
            broker_position_keys = set()
            for position in positions:
                sym_match = (position.symbol.upper() in dirty_symbol_names)
                if not sym_match and hasattr(position, 'raw_symbol') and position.raw_symbol:
                    sym_match = position.raw_symbol.upper() in dirty_symbol_names
                if not sym_match:
                    continue
                try:
                    pos_key = position.position_key
                    pos_key_upper = pos_key.upper()
                    if pos_key in self._permanent_failure_keys or pos_key_upper in {k.upper() for k in self._permanent_failure_keys}:
                        call_put = self._normalize_call_put(position.direction) if position.asset == 'option' else None
                        reopened_trade_id = self.db_adapter.get_open_trade_id_for_position(
                            symbol=position.symbol, asset_type=position.asset, broker=position.broker,
                            strike=position.strike, expiry=position.expiry, call_put=call_put
                        )
                        if reopened_trade_id:
                            self._permanent_failure_keys.discard(pos_key)
                            for k in list(self._permanent_failure_keys):
                                if k.upper() == pos_key_upper:
                                    self._permanent_failure_keys.discard(k)
                            self._save_permanent_failures()
                            print(f"[RISK] ✓ Cleared permanent failure for {pos_key} — new trade #{reopened_trade_id} found")
                        else:
                            continue
                    await self._evaluate_position(position, risk_settings, broker_position_keys)
                    evaluated += 1
                except Exception as e:
                    print(f"[RISK] ⚠️ Incremental eval error {position.symbol}: {e}")

            eval_elapsed_ms = (_t.monotonic() - eval_start) * 1000
            tick_to_eval_ms = (_t.monotonic() - earliest_tick) * 1000

            self._tick_eval_count += 1
            self._tick_eval_total_latency_ms += tick_to_eval_ms

            if self._tick_eval_count <= 3 or self._tick_eval_count % 500 == 0:
                avg_latency = self._tick_eval_total_latency_ms / self._tick_eval_count
                print(f"[RISK] ⚡ Tick eval #{self._tick_eval_count}: {evaluated} positions in {eval_elapsed_ms:.1f}ms | "
                      f"tick→eval: {tick_to_eval_ms:.1f}ms | avg: {avg_latency:.1f}ms")

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
        self._first_sync_completed = False
        
        if not hasattr(self, '_heartbeat_counter'):
            self._heartbeat_counter = 0
        
        self._subscribe_to_price_streams()
        
        while self._running:
            try:
                is_enabled = self._check_service_enabled()
                
                if is_enabled:
                    if self._standby_mode:
                        print("[RISK] ✓ Resuming active monitoring - risk settings enabled")
                        self._standby_mode = False
                    
                    import time as _cycle_t
                    _cycle_start = _cycle_t.monotonic()
                    await self._monitoring_cycle()
                    _cycle_elapsed_ms = (_cycle_t.monotonic() - _cycle_start) * 1000
                    if not hasattr(self, '_cycle_timing_log_counter'):
                        self._cycle_timing_log_counter = 0
                    self._cycle_timing_log_counter += 1
                    if self._cycle_timing_log_counter <= 5 or self._cycle_timing_log_counter % 60 == 0 or _cycle_elapsed_ms > 2000:
                        print(f"[RISK] ⏱ Cycle #{self._cycle_timing_log_counter}: {_cycle_elapsed_ms:.0f}ms")
                    interval = self._get_adaptive_interval()
                    _sleep_start = _cycle_t.monotonic()
                    _order_event_woke = False
                    while True:
                        _remaining = interval - (_cycle_t.monotonic() - _sleep_start)
                        if _remaining <= 0:
                            break
                        try:
                            from src.services.webull_data_hub import get_webull_data_hub
                            if get_webull_data_hub().check_risk_eval_requested():
                                print("[RISK] ⚡ Early wake: order event from Webull stream")
                                self._force_rest_refresh = True
                                _order_event_woke = True
                                break
                        except Exception:
                            pass
                        try:
                            from src.services.schwab_data_hub import get_schwab_data_hub
                            if get_schwab_data_hub().check_risk_eval_requested():
                                print("[RISK] ⚡ Early wake: order event from Schwab stream")
                                self._force_rest_refresh = True
                                _order_event_woke = True
                                break
                        except Exception:
                            pass
                        try:
                            from src.services.ibkr_data_hub import get_ibkr_data_hub
                            _ibkr_h = get_ibkr_data_hub()
                            if _ibkr_h.is_streaming() and _ibkr_h.check_risk_eval_requested():
                                print("[RISK] ⚡ Early wake: order event from IBKR stream")
                                self._force_rest_refresh = True
                                _order_event_woke = True
                                break
                        except Exception:
                            pass
                        try:
                            await asyncio.wait_for(
                                self._price_wake_event.wait(),
                                timeout=min(0.05, _remaining)
                            )
                            self._price_wake_event.clear()
                            await asyncio.sleep(0.02)
                            await self._run_incremental_eval()
                        except asyncio.TimeoutError:
                            pass
                else:
                    if not self._standby_mode:
                        print("[RISK] ⏸️ Entering standby mode - no risk settings enabled (zero API calls)")
                        self._standby_mode = True
                    
                    await self._standby_cycle()
                    await asyncio.sleep(5)
                
                self._heartbeat_counter += 1
                if self._heartbeat_counter >= 60:
                    self._heartbeat_counter = 0
                    cache_count = len(self.cache.get_all_risk_states()) if self.cache else 0
                    print(f"[RISK] ♥ Heartbeat: loop alive, {cache_count} risk states cached, standby={self._standby_mode}")
                    
            except asyncio.CancelledError:
                print("[RISK] ⚠️ Monitoring task cancelled - exiting loop")
                raise
            except Exception as e:
                print(f"[RISK] Error in monitoring cycle: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(self.monitoring_interval)
    
    _service_enabled_cache = None
    _service_enabled_cache_ts = 0

    def _check_service_enabled(self) -> bool:
        """Check if risk monitoring should be active (cached 10s to reduce DB overhead)."""
        import time as _t
        now = _t.monotonic()
        if self._service_enabled_cache is not None and (now - self._service_enabled_cache_ts) < 10:
            return self._service_enabled_cache

        try:
            from gui_app.database import get_setting
            risk_monitor_enabled = get_setting('risk_monitor_enabled', 'true').lower() == 'true'
            if not risk_monitor_enabled:
                self._service_enabled_cache = False
                self._service_enabled_cache_ts = now
                return False
        except Exception:
            pass
        
        risk_settings = self._get_risk_settings()
        channel_count = self.db_adapter.count_channels_with_risk()
        
        result = risk_settings.enabled or channel_count > 0
        self._service_enabled_cache = result
        self._service_enabled_cache_ts = now
        return result
    
    def _get_adaptive_interval(self) -> float:
        """Get monitoring interval - configurable via GUI settings.
        
        Priority:
        1. Fill watch active → 0.5s rapid polling for immediate fill detection
        2. Global risk setting 'risk_check_interval_seconds' (if set)
        3. Default 1 second for real-time live position monitoring
        
        Configure in Settings → Risk Management → Check Interval
        Supports sub-second intervals (0.2s minimum) for faster risk evaluation.
        """
        if self._has_active_fill_watches():
            with self._fill_watch_lock:
                min_interval = self._FILL_WATCH_DEFAULT_INTERVAL
                for w in self._fill_watch_orders.values():
                    broker = w.get('broker', '')
                    for bk, bv in self._FILL_WATCH_BROKER_INTERVALS.items():
                        if bk in broker:
                            min_interval = min(min_interval, bv)
                            break
            return min_interval

        try:
            from gui_app.database import get_global_risk_settings
            settings = get_global_risk_settings()
            custom_interval = settings.get('risk_check_interval_seconds')
            if custom_interval is not None:
                interval = float(custom_interval)
                if 0.2 <= interval <= 60:
                    return interval
        except Exception:
            pass
        
        return self.monitoring_interval
    
    async def _standby_cycle(self) -> None:
        """Standby cycle - process invalidations WITHOUT making broker API calls."""
        check_and_process_invalidation_request()
        self._expire_fill_watches()
        
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
    
    _PERIODIC_REST_FALLBACK_INTERVAL = 3
    _POSITION_REST_REFRESH_INTERVAL = 5

    async def _monitoring_cycle(self) -> None:
        """Execute one monitoring cycle."""
        if not self._first_sync_completed:
            _sync_event = self._sync_ready_event
            
            if _sync_event and not _sync_event.is_set():
                print("[RISK] ⏳ Waiting for first broker sync before evaluating positions...")
                try:
                    await asyncio.wait_for(_sync_event.wait(), timeout=30.0)
                    print("[RISK] ✓ First broker sync completed — risk evaluation starting")
                except asyncio.TimeoutError:
                    print("[RISK] ⚠️ First sync timed out after 30s — proceeding with caution")
            self._first_sync_completed = True
            self._permanent_failure_keys = self._load_permanent_failures()
        
        check_and_process_invalidation_request()
        
        risk_settings = self._get_risk_settings()
        
        if not risk_settings.enabled:
            channel_count = self.db_adapter.count_channels_with_risk()
            if channel_count == 0:
                return
            else:
                print(f"[RISK] Per-channel risk ACTIVE for {channel_count} channel(s)")
        
        import time as _mc_time
        _now = _mc_time.time()
        _last_refresh = getattr(self, '_last_periodic_webull_rest_ts', 0)

        _streaming_live = False
        try:
            from src.services.webull_data_hub import get_webull_data_hub as _check_hub
            _streaming_live = _check_hub().is_streaming()
        except Exception:
            pass

        _fill_watch_active = self._has_active_fill_watches()
        if _fill_watch_active:
            self._expire_fill_watches()
            _fw_brokers = set()
            with self._fill_watch_lock:
                for w in self._fill_watch_orders.values():
                    _fw_brokers.add(w['broker'])
            if any('WEBULL' in b for b in _fw_brokers):
                self._force_webull_rest_refresh = True
            if len(_fw_brokers - {'WEBULL'}) > 0:
                self._force_rest_refresh = True

        _pos_refresh_interval = self._POSITION_REST_REFRESH_INTERVAL if _streaming_live else self._PERIODIC_REST_FALLBACK_INTERVAL

        if (_now - _last_refresh) > _pos_refresh_interval:
            self._force_webull_rest_refresh = True
            self._last_periodic_webull_rest_ts = _now

        if _streaming_live:
            if not getattr(self, '_streaming_mode_logged', False):
                print(f"[RISK] ✓ Streaming live — quotes via MQTT, position refresh every {self._POSITION_REST_REFRESH_INTERVAL}s")
                self._streaming_mode_logged = True
            self._rest_fallback_logged = False
        else:
            if not getattr(self, '_rest_fallback_logged', False):
                print(f"[RISK] ⚠️ Streaming dead — REST fallback active (every {self._PERIODIC_REST_FALLBACK_INTERVAL}s)")
                self._rest_fallback_logged = True
            self._streaming_mode_logged = False
        
        try:
            positions = await self._fetch_all_positions()
        except Exception as e:
            print(f"[RISK] ⚠️ Error fetching positions: {e}")
            import traceback
            traceback.print_exc()
            positions = []
        
        if not positions:
            if not hasattr(self, '_empty_pos_logged') or not self._empty_pos_logged:
                print("[RISK] No open positions found across brokers — monitoring idle")
                self._empty_pos_logged = True
            self._last_positions_snapshot = []
            self._update_monitored_symbols([])
            return
        self._empty_pos_logged = False
        
        if _fill_watch_active:
            self._check_fill_watch_detected(positions)

        self._rest_repair_cycle_keys.clear()
        self._update_prices_from_hub(positions)
        await self._detect_and_fix_stuck_prices(positions)
        self._last_positions_snapshot = positions
        self._update_monitored_symbols(positions)
        
        if positions:
            current_keys = {p.position_key for p in positions}
            if not hasattr(self, '_prev_position_keys'):
                self._prev_position_keys = set()
            
            new_keys = current_keys - self._prev_position_keys
            removed_keys = self._prev_position_keys - current_keys

            flickered_removed = set()
            flickered_new = set()
            _flicker_canonical_map = {}
            if new_keys and removed_keys:
                if not hasattr(self, '_known_brokers'):
                    self._known_brokers = set()
                for p in positions:
                    self._known_brokers.add(p.broker)

                def _parse_key(k):
                    if k.endswith('_stock'):
                        broker_sym = k[:-len('_stock')]
                        for bk in sorted(self._known_brokers, key=len, reverse=True):
                            if broker_sym.startswith(bk + '_'):
                                return bk, broker_sym[len(bk)+1:], 'stock', '', ''
                        last_us = broker_sym.rfind('_')
                        if last_us > 0:
                            return broker_sym[:last_us], broker_sym[last_us+1:], 'stock', '', ''
                        return None, None, None, None, None
                    for bk in sorted(self._known_brokers, key=len, reverse=True):
                        prefix = bk + '_'
                        if k.startswith(prefix):
                            rest = k[len(prefix):]
                            rp = rest.split('_')
                            if len(rp) >= 4:
                                return bk, rp[0], rp[1], rp[2], rp[3]
                            elif len(rp) == 3:
                                return bk, rp[0], rp[1], rp[2], ''
                            elif len(rp) == 2:
                                return bk, rp[0], rp[1], '', ''
                            break
                    segs = k.split('_')
                    if len(segs) == 5:
                        return segs[0], segs[1], segs[2], segs[3], segs[4]
                    if len(segs) == 4:
                        return segs[0], segs[1], segs[2], segs[3], ''
                    return None, None, None, None, None

                def _is_degraded(strike_val, exp_val, dir_val):
                    if strike_val == 'stock':
                        return True
                    return strike_val in ('0.0', '0', 'None', '') or not dir_val or exp_val in ('', 'None')

                for nk in list(new_keys):
                    nb, ns, nstrike, nexp, ndir = _parse_key(nk)
                    if nb is None:
                        continue
                    is_nk_degraded = _is_degraded(nstrike, nexp, ndir)
                    for rk in list(removed_keys):
                        if rk in flickered_removed:
                            continue
                        rb, rs, rstrike, rexp, rdir = _parse_key(rk)
                        if rb is None or rb != nb or rs != ns:
                            continue
                        is_rk_degraded = _is_degraded(rstrike, rexp, rdir)
                        is_stock_option_flip = (nstrike == 'stock') != (rstrike == 'stock')
                        is_expiry_flicker = (not is_stock_option_flip and nstrike == rstrike and ndir == rdir and nexp != rexp)
                        if is_nk_degraded != is_rk_degraded or is_stock_option_flip or is_expiry_flicker:
                            flickered_removed.add(rk)
                            flickered_new.add(nk)
                            if is_expiry_flicker and not is_nk_degraded and not is_rk_degraded:
                                canonical = rk if (rexp and not nexp) else (nk if (nexp and not rexp) else rk)
                                degraded = nk if canonical == rk else rk
                            else:
                                canonical = rk if is_nk_degraded else nk
                                degraded = nk if is_nk_degraded else rk
                            _flicker_canonical_map[degraded] = canonical
                            print(f"[RISK] ⚠️ Position key flicker detected: {degraded} ↔ {canonical} "
                                  f"(Webull metadata inconsistency, keeping canonical key)")
                            break

            real_new_keys = new_keys - flickered_new
            real_removed_keys = removed_keys - flickered_removed

            canonical_keys = set(current_keys)
            for nk in flickered_new:
                canonical = _flicker_canonical_map.get(nk)
                if canonical and canonical != nk:
                    canonical_keys.discard(nk)
                    canonical_keys.add(canonical)
                    cb, cs, cstrike, cexp, cdir = _parse_key(canonical)
                    if cb and cstrike != 'stock' and cexp:
                        for p in positions:
                            if p.position_key == nk and p.broker == cb and p.symbol == cs:
                                if p.asset != 'option':
                                    p.asset = 'option'
                                if cstrike and cstrike not in ('0.0', '0', ''):
                                    try:
                                        p.strike = float(cstrike)
                                    except (ValueError, TypeError):
                                        pass
                                if cexp:
                                    p.expiry = cexp
                                if cdir:
                                    p.direction = cdir
                                break

            if real_new_keys:
                for nk in real_new_keys:
                    matching = [p for p in positions if p.position_key == nk]
                    if matching:
                        p = matching[0]
                        print(f"[RISK] 🆕 NEW POSITION DETECTED: {p.symbol} on {p.broker} "
                              f"(qty={p.quantity}, avg_cost=${p.avg_cost}, current=${p.current_price}) — "
                              f"risk engine will evaluate immediately")
            
            if real_removed_keys:
                for rk in real_removed_keys:
                    print(f"[RISK] 📤 Position closed externally: {rk}")
            
            self._prev_position_keys = canonical_keys
            
            import time as _t
            if not hasattr(self, '_last_monitoring_summary_ts'):
                self._last_monitoring_summary_ts = 0
            now = _t.time()
            if new_keys or removed_keys or (now - self._last_monitoring_summary_ts > 30):
                self._last_monitoring_summary_ts = now
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
        
        if not hasattr(self, '_permanent_failure_keys'):
            self._permanent_failure_keys = self._load_permanent_failures()
        
        _pf_upper = {k.upper() for k in self._permanent_failure_keys}
        for position in positions:
            try:
                pos_key = position.position_key
                if pos_key in self._permanent_failure_keys or pos_key.upper() in _pf_upper:
                    call_put = self._normalize_call_put(position.direction) if position.asset == 'option' else None
                    reopened_trade_id = self.db_adapter.get_open_trade_id_for_position(
                        symbol=position.symbol, asset_type=position.asset, broker=position.broker,
                        strike=position.strike, expiry=position.expiry, call_put=call_put
                    )
                    if reopened_trade_id:
                        self._permanent_failure_keys.discard(pos_key)
                        for k in list(self._permanent_failure_keys):
                            if k.upper() == pos_key.upper():
                                self._permanent_failure_keys.discard(k)
                        _pf_upper = {k.upper() for k in self._permanent_failure_keys}
                        self._save_permanent_failures()
                        print(f"[RISK] ✓ Cleared permanent failure for {pos_key} — new trade #{reopened_trade_id} found")
                    else:
                        continue
                await self._evaluate_position(position, risk_settings, broker_position_keys)
            except Exception as e:
                print(f"[RISK] ⚠️ Error processing position {position.symbol}: {e}")
        
        if not hasattr(self, '_stale_cleanup_counter'):
            self._stale_cleanup_counter = 0
        self._stale_cleanup_counter += 1
        if self._stale_cleanup_counter >= 20 and broker_position_keys:
            self._stale_cleanup_counter = 0
            stale_count = self.cache.cleanup_stale(broker_position_keys)
            if stale_count > 0:
                print(f"[RISK] 🧹 Periodic cleanup: removed {stale_count} stale cache entries")
            if hasattr(self, '_auto_imported_keys'):
                stale_imports = self._auto_imported_keys - broker_position_keys
                if stale_imports:
                    self._auto_imported_keys -= stale_imports
        
        import time as _save_t
        if not hasattr(self, '_last_cache_save_ts'):
            self._last_cache_save_ts = 0
        _now_save = _save_t.monotonic()
        if (_now_save - self._last_cache_save_ts) >= 2.0:
            self.cache.save()
            self._last_cache_save_ts = _now_save
    
    async def _fetch_all_positions(self) -> List[PositionSnapshot]:
        """Fetch positions from all brokers — hub-first, zero API cost when possible.
        
        Priority chain for Webull:
        1. WebullDataHub streaming/cached positions (zero API cost)
        2. position_fetcher() which itself uses hub cache then REST fallback
        3. In-memory cached snapshots from last successful fetch
        
        REST Cache (10s TTL): When hub misses, REST results are cached per-broker
        for 10 seconds. Prices are updated each cycle via _update_prices_from_hub()
        using streaming data. The cache is force-bypassed when a streaming hub
        signals an order event (new fill/cancel), ensuring new positions are
        detected within 1 cycle.
        
        This ensures the risk engine NEVER goes blind due to rate limiting.
        """
        positions = []
        rate_manager = get_rate_limit_manager() if RATE_LIMIT_AVAILABLE else None
        
        import time as _time
        
        webull_snapshots = None
        
        _force_webull = getattr(self, '_force_webull_rest_refresh', False)
        _force_global = getattr(self, '_force_rest_refresh', False)
        _hub_max_age = 0 if (_force_webull or _force_global) else 20
        if _force_webull:
            self._force_webull_rest_refresh = False

        if _force_webull or _force_global:
            _wb_rate_ok = True
            if rate_manager:
                _wb_rate_ok, _ = rate_manager.can_make_request('webull')
            if _wb_rate_ok:
                try:
                    from src.services.webull_data_hub import get_webull_data_hub as _gwdh
                    _fhub = _gwdh()
                    _raw_wb = self._get_raw_webull_client()
                    if _raw_wb:
                        if rate_manager:
                            rate_manager.record_request('webull')
                        await _fhub.refresh_positions_once(_raw_wb)
                except Exception:
                    pass
        
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            hub_positions = hub.get_positions(max_age_seconds=_hub_max_age)
            if hub_positions is not None and len(hub_positions) == 0:
                _empty_age = hub.get_positions_age()
                if _empty_age > 2.0:
                    hub_positions = None
            if hub_positions is not None and len(hub_positions) > 0:
                fetched = []
                for pos in hub_positions:
                    position_qty = float(pos.get('position', 0))
                    if position_qty <= 0:
                        continue
                    symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                    asset_type = pos.get('assetType', 'unknown')
                    is_option = ('optionId' in pos or 'strikePrice' in pos or 'expireDate' in pos or asset_type in ('option', 'OPTION', 'OPT'))
                    
                    if not is_option and hasattr(self, '_webull_enrichment_cache'):
                        _tid_check = pos.get('tickerId', 0) or pos.get('ticker', {}).get('tickerId', 0)
                        _oid_check = pos.get('optionId', 0)
                        for _ck in [f"oid_{_oid_check}" if _oid_check else None, f"tid_{_tid_check}" if _tid_check else None]:
                            if _ck and _ck in self._webull_enrichment_cache:
                                is_option = True
                                print(f"[RISK] ✓ Reclassified {symbol} as option via enrichment cache (key={_ck})")
                                break
                        if not is_option and hasattr(self, '_stable_option_symbols'):
                            _bs_key = f"Webull_{symbol}"
                            _stable_meta = self._stable_option_symbols.get(_bs_key)
                            if _stable_meta:
                                _has_real_stock = any(
                                    p.broker == 'Webull' and p.symbol == symbol and p.asset == 'stock'
                                    for p in getattr(self, '_last_webull_positions', []) or []
                                    if hasattr(p, 'asset')
                                )
                                if not _has_real_stock:
                                    is_option = True
                                    print(f"[RISK] ✓ Reclassified {symbol} as option via stable symbol cache")

                    if is_option:
                        ticker_id = pos.get('tickerId', 0) or pos.get('ticker', {}).get('tickerId', 0)
                        strike = float(pos.get('strikePrice', 0))
                        option_id = pos.get('optionId', ticker_id)
                        raw_dir = (pos.get('direction', '') or '').upper()
                        if raw_dir in ('CALL', 'C'):
                            direction = 'C'
                        elif raw_dir in ('PUT', 'P'):
                            direction = 'P'
                        else:
                            direction = raw_dir[:1] if raw_dir else ''
                        raw_exp = pos.get('expireDate', '')

                        if not hasattr(self, '_webull_enrichment_cache'):
                            self._webull_enrichment_cache = {}
                        if not hasattr(self, '_webull_enrichment_active_keys'):
                            self._webull_enrichment_active_keys = set()

                        enrich_keys = []
                        if option_id:
                            enrich_keys.append(f"oid_{option_id}")
                        if ticker_id:
                            enrich_keys.append(f"tid_{ticker_id}")
                        if not enrich_keys:
                            enrich_keys.append(f"sym_{symbol}_{raw_exp}_{direction}")

                        for ek in enrich_keys:
                            self._webull_enrichment_active_keys.add(ek)

                        enrichment_data = {'strike': strike, 'direction': direction, 'expiry': raw_exp}
                        if strike and strike > 0.0 and direction:
                            for ek in enrich_keys:
                                self._webull_enrichment_cache[ek] = enrichment_data
                            if not hasattr(self, '_stable_option_symbols'):
                                self._stable_option_symbols = {}
                            self._stable_option_symbols[f"Webull_{symbol}"] = enrichment_data

                        if (not strike or strike == 0.0) and (option_id or ticker_id):
                            try:
                                wb_broker = getattr(self, '_webull_broker', None) or getattr(self.bot, 'broker', None)
                                if wb_broker and hasattr(wb_broker, 'get_option_details_by_id'):
                                    reverse = wb_broker.get_option_details_by_id(option_id)
                                    if not reverse and ticker_id:
                                        reverse = wb_broker.get_option_details_by_id(ticker_id)
                                    if reverse:
                                        strike = reverse['strike']
                                        direction = reverse['option_type']
                                        raw_exp = reverse['expiry']
                                        enrichment_data = {'strike': strike, 'direction': direction, 'expiry': raw_exp}
                                        for ek in enrich_keys:
                                            self._webull_enrichment_cache[ek] = enrichment_data
                                        print(f"[RISK] ✓ Reverse cache enriched Webull position: {symbol} {strike} {direction} {raw_exp}")
                            except Exception:
                                pass

                        if not strike or strike == 0.0 or not direction or not raw_exp:
                            for ek in enrich_keys:
                                cached = self._webull_enrichment_cache.get(ek)
                                if cached:
                                    if not strike or strike == 0.0:
                                        strike = cached['strike']
                                    if not direction:
                                        direction = cached['direction']
                                    if not raw_exp:
                                        raw_exp = cached['expiry']
                                    print(f"[RISK] ✓ Used cached enrichment for Webull position: {symbol} {strike} {direction} {raw_exp}")
                                    break

                        expiry = ''
                        if raw_exp and '-' in raw_exp:
                            try:
                                from datetime import datetime as _dt
                                ed = _dt.strptime(raw_exp, '%Y-%m-%d')
                                expiry = ed.strftime('%m/%d') if ed.year == _dt.now().year else ed.strftime('%m/%d/%y')
                            except:
                                expiry = raw_exp
                        
                        opt_raw_symbol = None
                        if ticker_id:
                            opt_raw_symbol = str(ticker_id)
                        elif option_id:
                            opt_raw_symbol = str(option_id)
                        opt_current_price = self._resolve_webull_option_price(pos, position_qty, symbol)
                        snap_data = {
                            'broker': 'Webull', 'asset': 'option', 'symbol': symbol,
                            'quantity': position_qty, 'avg_cost': float(pos.get('costPrice', 0)),
                            'current_price': opt_current_price,
                            'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                            'option_id': option_id, 'strike': strike, 'expiry': expiry,
                            'direction': direction, 'ticker_id': ticker_id,
                            'raw_symbol': opt_raw_symbol
                        }
                        fetched.append(self._to_snapshot(snap_data))
                    else:
                        quantity = position_qty
                        current_price = self._resolve_webull_stock_price(pos, quantity)
                        snap_data = {
                            'broker': 'Webull', 'asset': 'stock', 'symbol': symbol,
                            'quantity': quantity, 'avg_cost': float(pos.get('costPrice', 0)),
                            'current_price': current_price,
                            'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                            'ticker_id': pos.get('ticker', {}).get('tickerId', 0)
                        }
                        fetched.append(self._to_snapshot(snap_data))
                
                if fetched:
                    webull_snapshots = fetched
                    self._last_webull_positions = fetched
                    self._webull_cache_ts = _time.time()
                    positions.extend(fetched)
            elif hub_positions is not None:
                hub_age = hub.get_positions_age()
                if hub_age < 2:
                    webull_snapshots = []
                    self._last_webull_positions = []
                    self._webull_cache_ts = _time.time()
        except ImportError:
            pass
        except Exception as e:
            pass
        
        _REST_CACHE_TTL = 10
        if _force_global:
            self._force_rest_refresh = False
            _REST_CACHE_TTL = 0

        async def _fetch_webull_rest():
            if webull_snapshots is not None:
                return []
            cache_age = _time.time() - getattr(self, '_webull_cache_ts', 0)
            if hasattr(self, '_last_webull_positions') and self._last_webull_positions is not None and cache_age < _REST_CACHE_TTL:
                return list(self._last_webull_positions)
            if rate_manager:
                can_proceed, wait_time = rate_manager.can_make_request('webull')
                if not can_proceed:
                    if hasattr(self, '_last_webull_positions') and self._last_webull_positions and cache_age < 120:
                        return list(self._last_webull_positions)
                    return []
                rate_manager.record_request('webull')
            try:
                from src.services.webull_data_hub import get_webull_data_hub
                _hub = get_webull_data_hub()
                _raw_wb = self._get_raw_webull_client()
                if _raw_wb:
                    await _hub.refresh_positions_once(_raw_wb)
                else:
                    if not hasattr(self, '_wb_resolve_warn_ts'):
                        self._wb_resolve_warn_ts = 0
                        self._wb_resolve_warn_total = 0
                    self._wb_resolve_warn_total += 1
                    import time as _wt
                    if (_wt.time() - self._wb_resolve_warn_ts) > 60:
                        self._wb_resolve_warn_ts = _wt.time()
                        print(f"[RISK] ⚠️ Could not resolve Webull broker for REST refresh — using cached data (count={self._wb_resolve_warn_total})")
                _refreshed = _hub.get_positions(max_age_seconds=30)
                if _refreshed is not None and len(_refreshed) > 0:
                    fetched = []
                    for pos in _refreshed:
                        position_qty = float(pos.get('position', 0))
                        if position_qty <= 0:
                            continue
                        symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                        is_option = ('optionId' in pos or 'strikePrice' in pos or 'expireDate' in pos)
                        if not is_option and hasattr(self, '_stable_option_symbols'):
                            _bs_key = f"Webull_{symbol}"
                            if _bs_key in self._stable_option_symbols:
                                is_option = True
                        if not is_option:
                            quantity = position_qty
                            current_price = self._resolve_webull_stock_price(pos, quantity)
                            snap_data = {
                                'broker': 'Webull', 'asset': 'stock', 'symbol': symbol,
                                'quantity': quantity, 'avg_cost': float(pos.get('costPrice', 0)),
                                'current_price': current_price,
                                'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                                'ticker_id': pos.get('ticker', {}).get('tickerId', 0)
                            }
                            fetched.append(self._to_snapshot(snap_data))
                        else:
                            _rest_strike = float(pos.get('strikePrice', 0))
                            _rest_expiry = pos.get('expireDate', '')
                            _rest_dir = (pos.get('direction', '') or '').upper()[:1]
                            if (not _rest_strike or not _rest_expiry or not _rest_dir) and hasattr(self, '_webull_enrichment_cache'):
                                _rest_oid = pos.get('optionId', 0)
                                _rest_tid = pos.get('tickerId', 0) or pos.get('ticker', {}).get('tickerId', 0)
                                for _rck in [f"oid_{_rest_oid}" if _rest_oid else None, f"tid_{_rest_tid}" if _rest_tid else None]:
                                    if _rck:
                                        _rc = self._webull_enrichment_cache.get(_rck)
                                        if _rc:
                                            if not _rest_strike or _rest_strike == 0.0:
                                                _rest_strike = _rc.get('strike', _rest_strike)
                                            if not _rest_dir:
                                                _rest_dir = _rc.get('direction', _rest_dir)
                                            if not _rest_expiry:
                                                _rest_expiry = _rc.get('expiry', _rest_expiry)
                                            break
                            opt_current_price = self._resolve_webull_option_price(pos, position_qty, symbol)
                            snap_data = {
                                'broker': 'Webull', 'asset': 'option', 'symbol': symbol,
                                'quantity': position_qty, 'avg_cost': float(pos.get('costPrice', 0)),
                                'current_price': opt_current_price,
                                'unrealized_pl': float(pos.get('unrealizedProfitLoss', 0)),
                                'option_id': pos.get('optionId', 0),
                                'strike': _rest_strike, 'expiry': _rest_expiry,
                                'direction': _rest_dir,
                                'ticker_id': pos.get('tickerId', 0) or pos.get('ticker', {}).get('tickerId', 0)
                            }
                            fetched.append(self._to_snapshot(snap_data))
                    if fetched:
                        self._last_webull_positions = fetched
                        self._webull_cache_ts = _time.time()
                        print(f"[RISK] ✓ REST refresh: {len(fetched)} Webull positions updated via hub")
                        return fetched
            except Exception as rest_err:
                print(f"[RISK] ⚠️ REST position refresh failed: {rest_err}")
            if hasattr(self, '_last_webull_positions') and self._last_webull_positions and cache_age < 120:
                return list(self._last_webull_positions)
            return []

        async def _fetch_alpaca_cached():
            if not (self.alpaca_broker and getattr(self.alpaca_broker, 'connected', False)):
                return []
            try:
                alpaca_cache_age = _time.time() - getattr(self, '_alpaca_cache_ts', 0)
                if hasattr(self, '_last_alpaca_positions') and self._last_alpaca_positions is not None and alpaca_cache_age < _REST_CACHE_TTL:
                    return list(self._last_alpaca_positions)
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('alpaca')
                    if not can_proceed:
                        if hasattr(self, '_last_alpaca_positions') and self._last_alpaca_positions and alpaca_cache_age < 120:
                            return list(self._last_alpaca_positions)
                        return []
                    rate_manager.record_request('alpaca')
                alpaca_positions = await self._fetch_alpaca_positions()
                self._last_alpaca_positions = alpaca_positions
                self._alpaca_cache_ts = _time.time()
                return alpaca_positions
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch Alpaca positions: {e}")
                if hasattr(self, '_last_alpaca_positions') and self._last_alpaca_positions:
                    if (_time.time() - getattr(self, '_alpaca_cache_ts', 0)) < 30:
                        return list(self._last_alpaca_positions)
                return []

        async def _fetch_schwab_cached():
            if not self.schwab_broker:
                return []
            try:
                schwab_cache_age = _time.time() - getattr(self, '_schwab_cache_ts', 0)
                if hasattr(self, '_last_schwab_positions') and self._last_schwab_positions is not None and schwab_cache_age < _REST_CACHE_TTL:
                    return list(self._last_schwab_positions)
                _schwab_streaming = False
                try:
                    from src.services.schwab_data_hub import get_schwab_data_hub
                    schwab_hub = get_schwab_data_hub()
                    _schwab_streaming = schwab_hub.is_streaming()
                    hub_pos = schwab_hub.get_positions(detailed=True)
                    if hub_pos is not None:
                        schwab_positions = []
                        for pos in hub_pos:
                            schwab_positions.append(PositionSnapshot(
                                symbol=pos.get('symbol', ''),
                                quantity=abs(float(pos.get('quantity', 0))),
                                avg_cost=float(pos.get('avg_cost', 0)),
                                current_price=float(pos.get('current_price', 0)),
                                asset=pos.get('asset', 'stock'),
                                broker='SCHWAB',
                                strike=pos.get('strike'),
                                expiry=pos.get('expiry'),
                                direction=pos.get('direction'),
                                raw_symbol=pos.get('raw_symbol')
                            ))
                        self._last_schwab_positions = schwab_positions
                        self._schwab_cache_ts = _time.time()
                        return schwab_positions
                    elif _schwab_streaming and hub_pos is not None:
                        self._last_schwab_positions = []
                        self._schwab_cache_ts = _time.time()
                        return []
                except (ImportError, Exception):
                    pass
                if _schwab_streaming:
                    if hasattr(self, '_last_schwab_positions') and self._last_schwab_positions and schwab_cache_age < 120:
                        return list(self._last_schwab_positions)
                    return []
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('schwab')
                    if not can_proceed:
                        if hasattr(self, '_last_schwab_positions') and self._last_schwab_positions and schwab_cache_age < 120:
                            return list(self._last_schwab_positions)
                        return []
                    is_auth = self.schwab_broker.is_authenticated()
                    if not is_auth:
                        return []
                    rate_manager.record_request('schwab')
                else:
                    is_auth = self.schwab_broker.is_authenticated()
                    if not is_auth:
                        return []
                schwab_positions = await self._fetch_schwab_positions()
                self._last_schwab_positions = schwab_positions
                self._schwab_cache_ts = _time.time()
                return schwab_positions
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch Schwab positions: {e}")
                if hasattr(self, '_last_schwab_positions') and self._last_schwab_positions:
                    if (_time.time() - getattr(self, '_schwab_cache_ts', 0)) < 30:
                        return list(self._last_schwab_positions)
                return []

        async def _fetch_ibkr_cached():
            if not (self.ibkr_broker and getattr(self.ibkr_broker, 'connected', False)):
                return []
            try:
                try:
                    from src.services.ibkr_data_hub import get_ibkr_data_hub
                    ibkr_hub = get_ibkr_data_hub()
                    if ibkr_hub.is_streaming():
                        hub_pos = ibkr_hub.get_positions(max_age_seconds=20)
                        if hub_pos is not None and len(hub_pos) > 0:
                            broker_label = 'IBKR_LIVE' if not getattr(self.ibkr_broker, 'paper_trade', True) else 'IBKR_PAPER'
                            snapshots = []
                            for p in hub_pos:
                                snap = PositionSnapshot(
                                    symbol=p.get('symbol', ''),
                                    quantity=p.get('quantity', 0),
                                    avg_cost=p.get('avg_cost', 0),
                                    current_price=0,
                                    asset=p.get('asset', 'stock'),
                                    broker=broker_label,
                                    strike=p.get('strike', 0),
                                    expiry=p.get('expiry', ''),
                                    direction=p.get('direction', ''),
                                    raw_symbol=p.get('raw_symbol', p.get('symbol', ''))
                                )
                                snapshots.append(snap)
                            self._last_ibkr_positions = snapshots
                            self._ibkr_cache_ts = _time.time()
                            return snapshots
                except ImportError:
                    pass

                ibkr_cache_age = _time.time() - getattr(self, '_ibkr_cache_ts', 0)
                if hasattr(self, '_last_ibkr_positions') and self._last_ibkr_positions is not None and ibkr_cache_age < _REST_CACHE_TTL:
                    return list(self._last_ibkr_positions)
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('ibkr')
                    if not can_proceed:
                        if hasattr(self, '_last_ibkr_positions') and self._last_ibkr_positions and ibkr_cache_age < 120:
                            return list(self._last_ibkr_positions)
                        return []
                    rate_manager.record_request('ibkr')
                ibkr_positions = await self._fetch_ibkr_positions()
                self._last_ibkr_positions = ibkr_positions
                self._ibkr_cache_ts = _time.time()
                return ibkr_positions
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch IBKR positions: {e}")
                if hasattr(self, '_last_ibkr_positions') and self._last_ibkr_positions:
                    if (_time.time() - getattr(self, '_ibkr_cache_ts', 0)) < 30:
                        return list(self._last_ibkr_positions)
                return []

        async def _fetch_tastytrade_cached():
            if not (self.tastytrade_broker and getattr(self.tastytrade_broker, 'connected', False)):
                return []
            try:
                tt_cache_age = _time.time() - getattr(self, '_tastytrade_cache_ts', 0)
                if hasattr(self, '_last_tastytrade_positions') and self._last_tastytrade_positions is not None and tt_cache_age < _REST_CACHE_TTL:
                    return list(self._last_tastytrade_positions)
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('tastytrade')
                    if not can_proceed:
                        if hasattr(self, '_last_tastytrade_positions') and self._last_tastytrade_positions and tt_cache_age < 120:
                            return list(self._last_tastytrade_positions)
                        return []
                    rate_manager.record_request('tastytrade')
                tastytrade_positions = await self._fetch_tastytrade_positions()
                self._last_tastytrade_positions = tastytrade_positions
                self._tastytrade_cache_ts = _time.time()
                return tastytrade_positions
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch Tastytrade positions: {e}")
                if hasattr(self, '_last_tastytrade_positions') and self._last_tastytrade_positions:
                    if (_time.time() - getattr(self, '_tastytrade_cache_ts', 0)) < 30:
                        return list(self._last_tastytrade_positions)
                return []

        async def _fetch_robinhood_cached():
            if not self.robinhood_broker:
                return []
            rh_connected = getattr(self.robinhood_broker, 'connected', None)
            rh_logged_in = getattr(self.robinhood_broker, '_logged_in', None)
            rh_ready = rh_connected or rh_logged_in or (rh_connected is None and rh_logged_in is None)
            if not rh_ready:
                return []
            try:
                rh_cache_age = _time.time() - getattr(self, '_robinhood_cache_ts', 0)
                if hasattr(self, '_last_robinhood_positions') and self._last_robinhood_positions is not None and rh_cache_age < _REST_CACHE_TTL:
                    return list(self._last_robinhood_positions)
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('robinhood')
                    if not can_proceed:
                        if hasattr(self, '_last_robinhood_positions') and self._last_robinhood_positions and rh_cache_age < 120:
                            return list(self._last_robinhood_positions)
                        return []
                    rate_manager.record_request('robinhood')
                robinhood_positions = await self._fetch_robinhood_positions()
                self._last_robinhood_positions = robinhood_positions
                self._robinhood_cache_ts = _time.time()
                return robinhood_positions
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch Robinhood positions: {e}")
                if hasattr(self, '_last_robinhood_positions') and self._last_robinhood_positions:
                    if (_time.time() - getattr(self, '_robinhood_cache_ts', 0)) < 30:
                        return list(self._last_robinhood_positions)
                return []

        async def _fetch_trading212_cached():
            if not self.trading212_broker:
                return []
            if not getattr(self.trading212_broker, 'connected', False):
                return []
            try:
                try:
                    from src.services.trading212_data_hub import get_trading212_data_hub
                    hub = get_trading212_data_hub()
                    hub_positions = hub.get_positions(max_age_seconds=10)
                    if hub_positions is not None and not hub.is_stale:
                        from src.risk.position_monitor import PositionSnapshot
                        t212_snaps = []
                        for pos in hub_positions:
                            broker_label = 'TRADING212'
                            if not getattr(self.trading212_broker, 'is_live', True):
                                broker_label = 'TRADING212_PAPER'
                            sym = pos.get('symbol', '')
                            qty = float(pos.get('quantity', 0))
                            avg = float(pos.get('avg_cost', 0))
                            cur = float(pos.get('current_price', 0))
                            snap = PositionSnapshot(
                                symbol=sym, asset='stock',
                                strike=None, expiry=None,
                                quantity=qty, avg_cost=avg, current_price=cur,
                                broker=broker_label, direction=None,
                            )
                            t212_snaps.append(snap)
                        self._last_trading212_positions = t212_snaps
                        self._trading212_cache_ts = _time.time()
                        return t212_snaps
                except Exception:
                    pass

                t212_cache_age = _time.time() - getattr(self, '_trading212_cache_ts', 0)
                if hasattr(self, '_last_trading212_positions') and self._last_trading212_positions is not None and t212_cache_age < _REST_CACHE_TTL:
                    return list(self._last_trading212_positions)
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('trading212')
                    if not can_proceed:
                        if hasattr(self, '_last_trading212_positions') and self._last_trading212_positions and t212_cache_age < 120:
                            return list(self._last_trading212_positions)
                        return []
                    rate_manager.record_request('trading212')
                trading212_positions = await self._fetch_trading212_positions()
                self._last_trading212_positions = trading212_positions
                self._trading212_cache_ts = _time.time()
                return trading212_positions
            except Exception as e:
                print(f"[RISK] Warning: Could not fetch Trading 212 positions: {e}")
                if hasattr(self, '_last_trading212_positions') and self._last_trading212_positions:
                    if (_time.time() - getattr(self, '_trading212_cache_ts', 0)) < 30:
                        return list(self._last_trading212_positions)
                return []

        results = await asyncio.gather(
            _fetch_webull_rest(),
            _fetch_alpaca_cached(),
            _fetch_schwab_cached(),
            _fetch_ibkr_cached(),
            _fetch_tastytrade_cached(),
            _fetch_robinhood_cached(),
            _fetch_trading212_cached(),
            return_exceptions=True
        )
        for r in results:
            if isinstance(r, list):
                positions.extend(r)
            elif isinstance(r, Exception):
                print(f"[RISK] ⚠️ Parallel fetch error: {r}")
        
        if hasattr(self, '_webull_enrichment_cache') and hasattr(self, '_webull_enrichment_active_keys'):
            if self._webull_enrichment_active_keys:
                stale_keys = set(self._webull_enrichment_cache.keys()) - self._webull_enrichment_active_keys
                for sk in stale_keys:
                    del self._webull_enrichment_cache[sk]
            self._webull_enrichment_active_keys = set()

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
                
                raw_sym = pos.get('symbol', '')
                normalized_sym = normalize_index_symbol(raw_sym) if asset_type == 'option' else raw_sym
                positions.append(PositionSnapshot(
                    symbol=normalized_sym,
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
                    
                    raw_sym = f"{symbol}_{expiry_raw}_{contract.strike}_{contract.right}"
                    positions.append(PositionSnapshot(
                        symbol=normalize_index_symbol(symbol),
                        quantity=quantity,
                        avg_cost=avg_cost / 100 if avg_cost > 0 else 0,
                        current_price=0,
                        asset='option',
                        broker=broker_label,
                        strike=contract.strike,
                        expiry=expiry,
                        direction=contract.right,
                        raw_symbol=raw_sym
                    ))
                else:
                    positions.append(PositionSnapshot(
                        symbol=symbol,
                        quantity=quantity,
                        avg_cost=avg_cost,
                        current_price=0,
                        asset='stock',
                        broker=broker_label,
                        raw_symbol=symbol
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
                    
                    tt_sym = pos.get('symbol', '')
                    normalized_tt_sym = normalize_index_symbol(tt_sym) if asset_type == 'option' else tt_sym
                    positions.append(PositionSnapshot(
                        symbol=normalized_tt_sym,
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
                    
                    rh_sym = pos.get('symbol', '')
                    normalized_rh_sym = normalize_index_symbol(rh_sym) if pos_type == 'option' else rh_sym
                    positions.append(PositionSnapshot(
                        symbol=normalized_rh_sym,
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

    async def _fetch_trading212_positions(self) -> List[PositionSnapshot]:
        """Fetch and parse Trading 212 positions (UK/EU stocks only)."""
        positions = []

        if not self.trading212_broker:
            return positions

        try:
            raw_positions = await self.trading212_broker.get_positions() or []

            for pos in raw_positions:
                broker_label = 'TRADING212'
                if not getattr(self.trading212_broker, 'is_live', True):
                    broker_label = 'TRADING212_PAPER'

                positions.append(PositionSnapshot(
                    symbol=pos.get('symbol', ''),
                    quantity=abs(float(pos.get('quantity', 0))),
                    avg_cost=float(pos.get('avg_cost', 0) or 0),
                    current_price=float(pos.get('current_price', 0) or 0),
                    asset='stock',
                    broker=broker_label,
                    strike=None,
                    expiry=None,
                    direction=None
                ))
        except Exception as e:
            print(f"[RISK] Error fetching Trading 212 positions: {e}")

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
                enriched = self._enrich_position_from_trade(position, trade_id, pos_key, broker_position_keys)
                if enriched:
                    position = enriched[0]
                    pos_key = enriched[1]
                    cache = self.cache.get_or_create(
                        position,
                        db_price_targets=getattr(self, '_db_price_targets', None)
                    )
                self.cache.set_trade_id(pos_key, trade_id)
            else:
                if not hasattr(self, '_auto_imported_keys'):
                    self._auto_imported_keys = set()
                
                if pos_key not in self._auto_imported_keys:
                    self._auto_imported_keys.add(pos_key)
                    
                    try:
                        new_trade_id = self.db_adapter.auto_import_manual_position(position)
                        if new_trade_id:
                            trade_id = new_trade_id
                            self.cache.set_trade_id(pos_key, trade_id)
                            print(f"[RISK] ⚡ INSTANT IMPORT: Manual position detected and imported in <1s: "
                                  f"{pos_key} → trade #{trade_id} "
                                  f"(broker={position.broker}, symbol={position.symbol}, "
                                  f"qty={position.quantity}, entry=${position.avg_cost}"
                                  f"{f', strike={position.strike}, expiry={position.expiry}' if position.asset == 'option' else ''}"
                                  f") — global risk settings NOW ACTIVE")
                        else:
                            print(f"[RISK] ⚠️ Auto-import failed for {pos_key} — monitoring with global risk settings (no state persistence)")
                    except Exception as e:
                        print(f"[RISK] ⚠️ Auto-import error for {pos_key}: {e}")
        
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
                position.broker,
                trade_id=trade_id
            )
            self.cache.apply_settings_with_versioning(pos_key, channel_settings)
            
            if channel_settings:
                print(f"[RISK] Using per-channel settings from '{channel_settings.channel_name}': "
                      f"Targets={channel_settings.profit_target_1_pct}%/"
                      f"{channel_settings.profit_target_2_pct}%/{channel_settings.profit_target_3_pct}%, "
                      f"StopLoss={channel_settings.stop_loss_pct}%, ExitMode={channel_settings.exit_strategy_mode}")
        
        if not channel_settings and not risk_settings.enabled:
            self._log_position_status(position, cache, channel_settings, pct_change)
            return
        
        # Check exit_strategy_mode - if 'signal', skip automated risk evaluation
        # 'signal' mode = follow trader exit signals only, no automated exits
        # 'risk' mode = use automated risk management only
        # 'hybrid' mode = both trader signals AND automated exits
        # Exception: EMA risk still runs in 'signal' mode when explicitly enabled
        if channel_settings and channel_settings.exit_strategy_mode == 'signal':
            if channel_settings.ema_risk_enabled:
                self._log_position_status(position, cache, channel_settings, pct_change)
                ema_decision = self._evaluate_enhanced_risk(position, cache, channel_settings, position_snapshot=position, ema_only=True)
                if ema_decision and ema_decision.should_exit:
                    from src.services.market_hours import is_regular_market_hours, is_extended_hours
                    if position.asset == 'option':
                        market_open = is_regular_market_hours()
                    else:
                        market_open = is_regular_market_hours() or is_extended_hours()
                    if not market_open:
                        if not hasattr(self, '_after_hours_logged'):
                            self._after_hours_logged = set()
                        if pos_key not in self._after_hours_logged:
                            self._after_hours_logged.add(pos_key)
                            print(f"[RISK] ⏸️ AFTER HOURS — suppressing EMA exit for {pos_key} "
                                  f"(reason: {ema_decision.reason}). Will re-evaluate when market opens.")
                        return
                    if hasattr(self, '_after_hours_logged'):
                        self._after_hours_logged.discard(pos_key)
                    await self._execute_exit(position, cache, ema_decision, channel_settings)
                return
            return
        
        self._log_position_status(position, cache, channel_settings, pct_change)
        
        decision = self._evaluate_exit_conditions(
            position, cache, channel_settings, risk_settings
        )
        
        if decision.should_exit:
            from src.services.market_hours import is_regular_market_hours, is_extended_hours
            if position.asset == 'option':
                market_open = is_regular_market_hours()
            else:
                market_open = is_regular_market_hours() or is_extended_hours()
            if not market_open:
                if not hasattr(self, '_after_hours_logged'):
                    self._after_hours_logged = set()
                if pos_key not in self._after_hours_logged:
                    self._after_hours_logged.add(pos_key)
                    print(f"[RISK] ⏸️ AFTER HOURS — suppressing exit for {pos_key} "
                          f"(reason: {decision.reason}). Will re-evaluate when market opens.")
                return
            if hasattr(self, '_after_hours_logged'):
                self._after_hours_logged.discard(pos_key)
            await self._execute_exit(position, cache, decision, channel_settings)
    
    def _evaluate_exit_conditions(
        self,
        position: PositionSnapshot,
        cache: PositionCacheEntry,
        channel_settings: Optional[ChannelRiskSettings],
        risk_settings: RiskSettings
    ) -> ExitDecision:
        """Evaluate all exit conditions in priority order including Enhanced Risk v2.0."""
        
        _repair_key = f"{position.broker}_{position.symbol}_{position.asset}"
        _is_repair_cycle = _repair_key in self._rest_repair_cycle_keys

        freshness_result = self._check_price_freshness(position, cache, channel_settings)
        if freshness_result is not None:
            return freshness_result

        if _repair_key in self._price_unverified:
            import time as _sv
            session_unv = self._get_market_session()
            if session_unv in ('regular', 'extended'):
                unv = self._price_unverified[_repair_key]
                unv_age = _sv.time() - unv['since']
                if unv_age < 30:
                    if not unv.get('logged'):
                        print(f"[RISK] 🛡️ STALENESS GATE: {position.symbol} price ${position.current_price:.2f} "
                              f"unverified (all sources returned same frozen price) — blocking exits for up to 30s")
                        unv['logged'] = True
                    return ExitDecision.no_exit()
                else:
                    del self._price_unverified[_repair_key]
            else:
                del self._price_unverified[_repair_key]

        tracker = self._stuck_price_tracker.get(_repair_key)
        if tracker and not _is_repair_cycle:
            import time as _st
            change_age = _st.time() - tracker['last_changed']
            if change_age > self._STALENESS_EXIT_BLOCK_THRESHOLD:
                session = self._get_market_session()
                if session in ('regular', 'extended'):
                    if not hasattr(self, '_staleness_block_logged'):
                        self._staleness_block_logged = {}
                    _sbl_key = f"{_repair_key}_{int(change_age)//10}"
                    if _sbl_key not in self._staleness_block_logged:
                        self._staleness_block_logged[_sbl_key] = True
                        print(f"[RISK] 🛡️ STALENESS GATE: {position.symbol} price unchanged for "
                              f"{change_age:.0f}s (>{self._STALENESS_EXIT_BLOCK_THRESHOLD}s) — "
                              f"blocking exit until fresh price arrives")
                    return ExitDecision.no_exit()

        decision = evaluate_price_based_stops(position, cache)
        if decision.should_exit:
            if not _is_repair_cycle:
                return decision
        
        if channel_settings:
            decision = evaluate_channel_stop_loss(position, cache, channel_settings)
            if decision.should_exit:
                if not _is_repair_cycle:
                    return decision
        
        if _is_repair_cycle:
            return ExitDecision.no_exit()
        
        if channel_settings and channel_settings.has_tiered_targets:
            if channel_settings.escalation_only_mode:
                tier_thresholds = {
                    1: channel_settings.profit_target_1_pct,
                    2: channel_settings.profit_target_2_pct,
                    3: channel_settings.profit_target_3_pct,
                    4: channel_settings.profit_target_4_pct
                }
                pnl_pct = position.pct_change if hasattr(position, 'pct_change') else 0
                has_sl_mechanism = channel_settings.enable_dynamic_sl or channel_settings.enable_early_trailing
                for tier in [1, 2, 3, 4]:
                    threshold = tier_thresholds.get(tier, 0)
                    if threshold <= 0:
                        continue
                    tier_attr = f'tier{tier}_hit'
                    already_hit = getattr(cache, tier_attr, False)
                    if not already_hit and pnl_pct >= threshold:
                        setattr(cache, tier_attr, True)
                        if has_sl_mechanism:
                            print(f"[RISK] ESCALATION ONLY: T{tier} hit ({pnl_pct:.1f}% >= {threshold}%) — tier marked for SL escalation, NO partial sell")
                        else:
                            print(f"[RISK] ⚠️ ESCALATION ONLY: T{tier} hit ({pnl_pct:.1f}% >= {threshold}%) — WARNING: Dynamic SL and Early Trailing are both disabled, SL will NOT escalate")
            else:
                decision = evaluate_tiered_targets(position, cache, channel_settings)
                if decision.should_exit:
                    decision.reason = format_tier_reason(decision, channel_settings.channel_name)
                    return decision
        
        if channel_settings and (channel_settings.enable_dynamic_sl or channel_settings.enable_giveback_guard or channel_settings.ema_risk_enabled):
            engine_decision = self._evaluate_enhanced_risk(position, cache, channel_settings, position_snapshot=position)
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
        channel_settings: ChannelRiskSettings,
        position_snapshot: PositionSnapshot = None,
        ema_only: bool = False
    ) -> Optional[ExitDecision]:
        """
        Evaluate Enhanced Risk v2.0 features: Dynamic SL, Giveback Guard, and EMA Risk.
        Updates cache state and returns exit decision if triggered.
        When ema_only=True (signal mode), non-EMA risk features are disabled so only
        EMA exits can fire.
        """
        if ema_only:
            from dataclasses import replace
            channel_settings = replace(
                channel_settings,
                stop_loss_pct=0.0,
                enable_dynamic_sl=False,
                enable_giveback_guard=False,
                enable_early_trailing=False,
                trailing_stop_pct=0.0,
                profit_target_1_pct=0.0,
                profit_target_2_pct=0.0,
                profit_target_3_pct=0.0,
                profit_target_4_pct=0.0,
            )

        original_qty = cache.original_qty if cache.original_qty else int(position.quantity)
        state = TradeState(
            entry_price=cache.entry_price,
            current_price=position.current_price,
            qty=original_qty,
            remaining_qty=int(position.quantity)
        )
        state.copy_from_cache(cache)

        if channel_settings.ema_risk_enabled and position_snapshot:
            try:
                from .ema_engine import get_candle_service
                candle_svc = get_candle_service()
                if candle_svc and candle_svc.is_global_enabled():
                    ema_symbol = position_snapshot.symbol
                    tf = channel_settings.ema_timeframe_minutes
                    pd = channel_settings.ema_period

                    is_option = position_snapshot.direction in ('C', 'Call', 'call', 'P', 'Put', 'put')
                    yf_only = is_option and channel_settings.ema_use_underlying
                    ext_hours = getattr(channel_settings, 'ema_extended_hours', False)
                    candle_svc.subscribe_symbol(ema_symbol, timeframe=tf, period=pd, yfinance_only=yf_only, extended_hours=ext_hours)

                    ema_state = candle_svc.get_ema_state(ema_symbol, timeframe=tf, period=pd)
                    state.ema_value = ema_state.value
                    state.ema_cross_state = ema_state.cross_state
                    state.ema_candles_count = ema_state.candles_count
                    state.ema_no_trend_count = cache.ema_no_trend_count
                    if ema_state.last_candle:
                        state.ema_last_candle = ema_state.last_candle.to_dict()

                    if position_snapshot.direction in ('C', 'Call', 'call'):
                        state.position_direction = 'C'
                    elif position_snapshot.direction in ('P', 'Put', 'put'):
                        state.position_direction = 'P'
                    else:
                        state.position_direction = 'stock'
            except Exception as e:
                print(f"[RISK] EMA state lookup failed for {position_snapshot.symbol}: {e}")

        actions, updated_state = evaluate_exit_actions(state, channel_settings, verbose=False)
        
        old_max_pnl = cache.max_pnl_seen
        old_dsl = cache.dynamic_sl_price
        old_giveback = cache.giveback_guard_active
        old_tier_hits = (cache.tier1_hit, cache.tier2_hit, cache.tier3_hit, cache.tier4_hit)
        
        cache.max_pnl_seen = updated_state.max_pnl_seen
        cache.dynamic_sl_price = updated_state.dynamic_sl_price
        cache.giveback_guard_active = updated_state.giveback_guard_active
        cache.last_evaluated_price = updated_state.last_evaluated_price
        cache.tier1_hit = updated_state.pt1_hit
        cache.tier2_hit = updated_state.pt2_hit
        cache.tier3_hit = updated_state.pt3_hit
        cache.tier4_hit = updated_state.pt4_hit
        cache.ema_no_trend_count = updated_state.ema_no_trend_count
        if updated_state.highest_price > cache.highest_price:
            cache.highest_price = updated_state.highest_price
        
        new_tier_hits = (cache.tier1_hit, cache.tier2_hit, cache.tier3_hit, cache.tier4_hit)
        if new_tier_hits != old_tier_hits:
            for i, (old_h, new_h) in enumerate(zip(old_tier_hits, new_tier_hits), 1):
                if new_h and not old_h:
                    print(f"[RISK] PT{i} HIT for {position.position_key} (pnl={position.pct_change:.1f}%)")
        
        persist_updates = {}
        if updated_state.max_pnl_seen > old_max_pnl:
            persist_updates['max_pnl_seen'] = updated_state.max_pnl_seen
        if updated_state.dynamic_sl_price != old_dsl:
            persist_updates['dynamic_sl_price'] = updated_state.dynamic_sl_price
        if updated_state.giveback_guard_active and not old_giveback:
            persist_updates['giveback_guard_active'] = True
        if new_tier_hits != old_tier_hits:
            for i, (old_h, new_h) in enumerate(zip(old_tier_hits, new_tier_hits), 1):
                if new_h and not old_h:
                    persist_updates[f'tier{i}_hit'] = True
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
                elif 'Early trailing' in action.reason or 'early trailing' in action.reason:
                    return ExitDecision(
                        should_exit=True,
                        reason=f"EARLY TRAIL [{channel_name}] {action.reason}",
                        exit_qty=action.qty,
                        is_partial=False,
                        risk_trigger='early_trailing'
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

            elif action.action_type == ActionType.EMA_EXIT:
                channel_name = channel_settings.channel_name
                return ExitDecision(
                    should_exit=True,
                    reason=f"EMA EXIT [{channel_name}] {action.reason}",
                    exit_qty=action.qty,
                    is_partial=(action.qty < int(position.quantity)),
                    risk_trigger='ema_exit'
                )

            elif action.action_type == ActionType.EMA_NO_TREND_EXIT:
                cache.ema_no_trend_count = updated_state.ema_no_trend_count
                channel_name = channel_settings.channel_name
                return ExitDecision(
                    should_exit=True,
                    reason=f"EMA NO-TREND [{channel_name}] {action.reason}",
                    exit_qty=action.qty,
                    is_partial=False,
                    risk_trigger='ema_no_trend'
                )

            elif action.action_type == ActionType.EMA_ESCALATE_STOP and action.new_stop_price:
                if cache.dynamic_sl_price is None or action.new_stop_price > cache.dynamic_sl_price:
                    cache.dynamic_sl_price = action.new_stop_price
                    print(f"[RISK] 📊 EMA Stop escalated to ${action.new_stop_price:.2f} ({action.reason})")

        cache.ema_no_trend_count = updated_state.ema_no_trend_count
        cache.ema_last_eval_candle_ts = updated_state.ema_last_eval_candle_ts
        cache.ema_post_entry_candles = updated_state.ema_post_entry_candles
        if updated_state.ema_cross_state and updated_state.ema_cross_state not in ('seeding', 'frozen', ''):
            cache.ema_last_cross_state = updated_state.ema_cross_state

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
        
        # Check for permanent/unrecoverable failure (expired symbol, invalid contract, etc.)
        if self.cache.is_permanent_failure(pos_key):
            pf_reason = self.cache.get_permanent_failure_reason(pos_key) or 'Unknown'
            print(f"[RISK] 🛑 PERMANENT FAILURE — skipping retries for {pos_key}")
            print(f"[RISK] 🛑 Reason: {pf_reason}")
            print(f"[RISK] 🛑 Auto-closing position in database (symbol expired/invalid)")
            try:
                trade_id = self.cache.get_trade_id(pos_key)
                if trade_id:
                    from gui_app.database import close_trade
                    entry_price = position.avg_cost or 0
                    pnl = -entry_price * position.quantity if entry_price else 0
                    pnl_pct = -100.0 if entry_price else 0
                    close_trade(trade_id, close_price=0, pnl=pnl, pnl_percent=pnl_pct)
                    print(f"[RISK] 🛑 Trade #{trade_id} marked as closed in database (expired worthless)")
                self.cache.remove(pos_key)
                if not hasattr(self, '_permanent_failure_keys'):
                    self._permanent_failure_keys = self._load_permanent_failures()
                self._permanent_failure_keys.add(pos_key)
                self._save_permanent_failures()
                print(f"[RISK] 🛑 Position {pos_key} removed from risk monitoring cache")
                print(f"[RISK] 🛑 Position added to permanent failure blocklist (persisted to disk)")
                try:
                    from gui_app.discord_notifier import send_notification
                    send_notification(
                        title="Position Auto-Closed (Expired)",
                        description=f"**{pos_key}**\n{pf_reason}\n\nPosition removed from monitoring. Check broker account for any cleanup needed.",
                        color=0xFF5252
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"[RISK] 🛑 Error during auto-close cleanup: {e}")
            return
        
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
        
        if not decision.is_partial:
            from src.risk.exit_lease_manager import get_exit_lease_manager, OWNER_RISK_ENGINE
            lease_mgr = get_exit_lease_manager()
            tier_label = getattr(decision, 'tier', None)
            if not lease_mgr.acquire(pos_key, OWNER_RISK_ENGINE, tier=tier_label):
                lease_info = lease_mgr.get_state(pos_key)
                print(f"[RISK] Exit lease active for {pos_key} (owner={lease_info['owner']}, age={lease_info['age']:.1f}s) — skipping duplicate exit")
                return
            self.cache.mark_closing(pos_key)
        
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
        
        current_price = position.current_price
        entry_price = position.avg_cost
        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price and entry_price > 0 else 0.0
        cache: Optional[PositionCacheEntry] = self.cache.get(pos_key) if hasattr(self.cache, 'get') else None
        
        is_stop_exit = 'STOP LOSS' in decision.reason and 'TRAILING' not in decision.reason
        is_trailing_exit = 'TRAILING STOP' in decision.reason or 'TRAILING' in decision.reason
        is_profit_exit = 'TARGET' in decision.reason or 'PROFIT' in decision.reason
        is_giveback_exit = 'GIVEBACK' in decision.reason
        
        exit_qty = int(decision.exit_qty) if decision.exit_qty else 0
        
        # Send notification for stop loss triggers
        if is_stop_exit:
            try:
                from gui_app.discord_notifier import notify_stop_loss_triggered
                notify_stop_loss_triggered(
                    symbol=position.symbol,
                    broker=position.broker,
                    entry_price=entry_price,
                    exit_price=current_price,
                    loss_percent=abs(pnl_pct),
                    quantity=exit_qty,
                    channel=channel_settings.channel_name if channel_settings else None
                )
            except Exception as notify_err:
                print(f"[NOTIFY] Warning: Could not send stop loss notification: {notify_err}")
        
        # Send notification for trailing stop triggers
        if is_trailing_exit:
            try:
                from gui_app.discord_notifier import notify_trailing_stop_triggered
                trail_type = "early" if "EARLY" in decision.reason else "standard"
                notify_trailing_stop_triggered(
                    symbol=position.symbol,
                    broker=position.broker,
                    trail_type=trail_type,
                    profit_percent=pnl_pct,
                    exit_price=current_price,
                    quantity=exit_qty,
                    channel=channel_settings.channel_name if channel_settings else None
                )
            except Exception as notify_err:
                print(f"[NOTIFY] Warning: Could not send trailing stop notification: {notify_err}")
        
        # Send notification for giveback guard triggers
        if is_giveback_exit:
            try:
                from gui_app.discord_notifier import notify_giveback_guard_triggered
                max_profit_seen = cache.max_pnl_seen if cache and hasattr(cache, 'max_pnl_seen') else pnl_pct
                giveback_pct_val = channel_settings.giveback_allowed_pct if channel_settings else 30.0
                notify_giveback_guard_triggered(
                    symbol=position.symbol,
                    broker=position.broker,
                    max_profit=max_profit_seen,
                    current_profit=pnl_pct,
                    giveback_pct=giveback_pct_val,
                    exit_price=current_price,
                    quantity=exit_qty,
                    channel=channel_settings.channel_name if channel_settings else None
                )
            except Exception as notify_err:
                print(f"[NOTIFY] Warning: Could not send giveback guard notification: {notify_err}")
        
        # Send notification for profit target hits
        if is_profit_exit and pnl_pct > 0:
            try:
                from gui_app.discord_notifier import notify_profit_target_hit
                tier = 1
                if 'TARGET 2' in decision.reason or 'TARGET2' in decision.reason:
                    tier = 2
                elif 'TARGET 3' in decision.reason or 'TARGET3' in decision.reason:
                    tier = 3
                elif 'TARGET 4' in decision.reason or 'TARGET4' in decision.reason:
                    tier = 4
                notify_profit_target_hit(
                    symbol=position.symbol,
                    broker=position.broker,
                    target_tier=tier,
                    profit_percent=pnl_pct,
                    exit_price=current_price,
                    quantity=exit_qty,
                    channel=channel_settings.channel_name if channel_settings else None
                )
            except Exception as notify_err:
                print(f"[NOTIFY] Warning: Could not send profit target notification: {notify_err}")
        
        try:
            from gui_app.database import record_order_event
            if is_stop_exit:
                evt_type = 'STOP_LOSS'
                evt_severity = 'critical'
            elif is_trailing_exit:
                evt_type = 'EARLY_TRAILING' if 'EARLY' in decision.reason else 'TRAILING_STOP'
                evt_severity = 'warning'
            elif is_giveback_exit:
                evt_type = 'GIVEBACK_GUARD'
                evt_severity = 'warning'
            elif is_profit_exit:
                evt_type = 'PROFIT_TARGET'
                evt_severity = 'info'
            else:
                evt_type = 'EXIT_TRIGGERED'
                evt_severity = 'info'
            record_order_event(
                evt_type,
                symbol=position.symbol,
                broker=position.broker,
                direction='STC',
                asset_type=position.asset,
                quantity=exit_qty,
                price=current_price,
                channel_name=channel_settings.channel_name if channel_settings else None,
                channel_id=channel_settings.channel_id if channel_settings else None,
                status='TRIGGERED',
                reason=decision.reason,
                details=f"Entry: ${entry_price:.2f} | P&L: {pnl_pct:.2f}%",
                severity=evt_severity,
                source='risk_manager',
                position_key=pos_key
            )
        except Exception:
            pass
        
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
                    if not decision.is_partial:
                        self.cache.clear_closing(pos_key)
                        from src.risk.exit_lease_manager import get_exit_lease_manager, OWNER_RISK_ENGINE as _OWN_ARB
                        get_exit_lease_manager().release(pos_key, _OWN_ARB)
                    return
                
                print(f"[RISK] Exit approved by arbiter (hybrid mode)")
            except Exception as e:
                print(f"[RISK] Arbiter check failed, proceeding with exit: {e}")
        
        try:
            stc_signal = self._build_stc_signal(position, decision)
            if stc_signal is None:
                if not decision.is_partial:
                    self.cache.clear_closing(pos_key)
                    from src.risk.exit_lease_manager import get_exit_lease_manager, OWNER_RISK_ENGINE as _OWN
                    get_exit_lease_manager().release(pos_key, _OWN)
                return
            
            hub_quotes = self._get_streaming_bid_ask(position)
            hub_bid = hub_quotes['bid']
            hub_ask = hub_quotes['ask']
            hub_mid = hub_quotes['mid']
            hub_src = hub_quotes['source']
            is_penny_stock = position.asset == 'stock' and position.current_price < 1.0
            if hub_bid > 0 or hub_ask > 0:
                last_price = stc_signal['price']
                spread_pct = 0
                if hub_bid > 0 and hub_ask > 0:
                    spread_pct = (hub_ask - hub_bid) / hub_bid * 100
                if is_penny_stock and hub_bid > 0:
                    stc_signal['price'] = hub_bid
                    print(f"[RISK] 💰 Penny stock exit: bid ${hub_bid:.4f} "
                          f"(ask ${hub_ask:.4f}, mid ${hub_mid:.4f}, last ${last_price:.4f}, spread {spread_pct:.1f}%) "
                          f"via {hub_src}")
                elif is_stop_exit or is_trailing_exit or is_giveback_exit:
                    if hub_bid > 0:
                        stc_signal['price'] = hub_bid
                        print(f"[RISK] 💰 Exit price: bid ${hub_bid:.2f} "
                              f"(ask ${hub_ask:.2f}, mid ${hub_mid:.2f}, last ${last_price:.2f}, spread {spread_pct:.1f}%) "
                              f"via {hub_src}")
                    else:
                        print(f"[RISK] Hub has ask-only (${hub_ask:.2f}), no bid — using last ${last_price:.2f} for SL exit")
                elif is_profit_exit:
                    if hub_mid > 0 and spread_pct < 50:
                        stc_signal['price'] = hub_mid
                        print(f"[RISK] 💰 Exit price: mid ${hub_mid:.2f} "
                              f"(bid ${hub_bid:.2f}, ask ${hub_ask:.2f}, last ${last_price:.2f}, spread {spread_pct:.1f}%) "
                              f"via {hub_src}")
                    elif hub_mid > 0 and spread_pct >= 50:
                        print(f"[RISK] ⚠️ Wide spread {spread_pct:.1f}% (bid ${hub_bid:.2f}, ask ${hub_ask:.2f}) — "
                              f"using last ${last_price:.2f} for PT exit")
                    elif hub_bid > 0:
                        stc_signal['price'] = hub_bid
                        print(f"[RISK] 💰 PT exit: bid-only ${hub_bid:.2f} (no ask, last ${last_price:.2f}) via {hub_src}")
                    else:
                        print(f"[RISK] Hub partial quote (bid=0, ask=${hub_ask:.2f}) — using last ${last_price:.2f}")
                else:
                    if hub_mid > 0 and spread_pct < 50:
                        stc_signal['price'] = hub_mid
                        print(f"[RISK] 💰 Exit price: mid ${hub_mid:.2f} "
                              f"(bid ${hub_bid:.2f}, ask ${hub_ask:.2f}, spread {spread_pct:.1f}%) via {hub_src}")
                    elif hub_bid > 0:
                        stc_signal['price'] = hub_bid
                        print(f"[RISK] 💰 Exit price: bid ${hub_bid:.2f} (wide spread/partial, last ${last_price:.2f}) via {hub_src}")
            
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
                if channel_settings and channel_settings.channel_id:
                    stc_signal['channel_id'] = channel_settings.channel_id
                    channel_record_id = self.db_adapter.get_channel_record_id(
                        channel_settings.channel_id
                    )
                    if channel_record_id:
                        stc_signal['channel_record_id'] = channel_record_id
                    print(f"[RISK] ✓ Fallback channel_id={channel_settings.channel_id} from channel settings")
            
            # Add market order flag if limit orders have failed multiple times
            # OR if sl_order_mode is 'market' for stop loss exits
            use_market = self.cache.should_use_market_order(pos_key)
            
            # Check if stop loss should use market order immediately
            # Use risk_trigger for accurate detection (stop_loss, trailing_stop, early_trailing, giveback_guard)
            sl_triggers = ('stop_loss', 'trailing_stop', 'early_trailing', 'giveback_guard')
            is_sl_type_exit = decision.risk_trigger in sl_triggers
            if is_sl_type_exit and channel_settings and channel_settings.sl_order_mode == 'market':
                use_market = True
                print(f"[RISK] 📊 SL Market Order mode enabled - using market order for {decision.risk_trigger}")
            
            # Apply SL limit offset for limit orders on SL-type exits
            # This sets the limit price lower than trigger price to improve fill probability
            if is_sl_type_exit and channel_settings and channel_settings.sl_order_mode == 'limit' and not use_market:
                sl_offset = channel_settings.sl_limit_offset or 0.03
                if sl_offset > 0:
                    original_price = stc_signal['price']
                    offset_price = round(original_price * (1 - sl_offset), 2)
                    stc_signal['price'] = offset_price
                    stc_signal['_sl_limit_offset_applied'] = True
                    print(f"[RISK] 📊 SL Limit Offset: trigger ${original_price:.2f} → limit ${offset_price:.2f} ({sl_offset*100:.1f}% below)")
            
            is_pt_exit = decision.risk_trigger == 'profit_target'
            if is_pt_exit and channel_settings and not use_market:
                if channel_settings.trim_order_mode == 'market':
                    use_market = True
                    tier_label = f"T{decision.tier_hit}" if decision.tier_hit else "PT"
                    print(f"[RISK] 📊 Trim Market Order mode - using market order for {tier_label}")
                elif channel_settings.trim_order_mode == 'limit':
                    trim_price = get_trim_order_price(position.current_price, channel_settings, is_sell=True)
                    if trim_price is not None:
                        original_price = stc_signal['price']
                        stc_signal['price'] = trim_price
                        offset_mode = getattr(channel_settings, 'trim_limit_offset_mode', 'dollar')
                        if offset_mode == 'percent':
                            offset_display = f"{channel_settings.trim_limit_offset_pct}%"
                        else:
                            offset_display = f"${channel_settings.trim_limit_offset}"
                        print(f"[RISK] 📊 Trim Limit Order: market ${original_price:.2f} → limit ${trim_price:.2f} ({offset_display} offset)")
            
            if not use_market and is_penny_stock:
                use_market = True
                print(f"[RISK] 📊 Penny stock (${position.current_price:.4f}) — forcing market order for fast exit")

            if not use_market and 'TRADING212' in position.broker.upper():
                if is_sl_type_exit or decision.risk_trigger in ('ema_exit', 'ema_no_trend', 'profit_target'):
                    use_market = True
                    print(f"[RISK] 📊 Trading212 has no bid/ask streaming — using market order for {decision.risk_trigger}")

            if use_market:
                stc_signal['_use_market_order'] = True
                print(f"[RISK] 📊 Market order mode - using current price ${position.current_price:.2f}")
            
            stc_signal['_exit_marker_key'] = pos_key
            
            await self.order_queue.put(stc_signal)
            print(f"[RISK] STC order queued for {pos_key} via {position.broker} (queue_id={id(self.order_queue)}, qsize={self.order_queue.qsize()}): {stc_signal}")
            
            import threading
            def _thread_exit_executor():
                import time as _t
                _t.sleep(5)
                try:
                    from src.risk.exit_lease_manager import get_exit_lease_manager, OWNER_WORKER, OWNER_BACKUP, LEASE_EXECUTING
                    lease_mgr = get_exit_lease_manager()
                    lease_info = lease_mgr.get_state(pos_key)
                    if lease_info['owner'] == OWNER_WORKER and lease_info['state'] == LEASE_EXECUTING:
                        print(f"[RISK] [DIRECT-EXIT] {pos_key} already being executed by worker — skipping")
                        return
                    with self._exit_executed_lock:
                        if pos_key in self._exit_executed_keys:
                            print(f"[RISK] [DIRECT-EXIT] {pos_key} already executed by worker — skipping")
                            return
                    if not self.cache.is_closing(pos_key):
                        entry = self.cache.get(pos_key)
                        if entry and hasattr(entry, 'exit_retry_count') and entry.exit_retry_count > 0:
                            print(f"[RISK] [DIRECT-EXIT] {pos_key} closing reset due to FAILED exit (retries={entry.exit_retry_count}) — will retry on next risk cycle")
                        else:
                            print(f"[RISK] [DIRECT-EXIT] {pos_key} no longer closing — worker handled it")
                        return
                    from src.risk.exit_lease_manager import OWNER_RISK_ENGINE
                    if not lease_mgr.transfer(pos_key, OWNER_BACKUP, LEASE_EXECUTING, expected_owner=OWNER_RISK_ENGINE):
                        current_lease = lease_mgr.get_state(pos_key)
                        print(f"[RISK] [DIRECT-EXIT] {pos_key} lease owned by {current_lease['owner']} — skipping backup")
                        return
                    with self._exit_executed_lock:
                        if pos_key in self._exit_executed_keys:
                            return
                        self._exit_executed_keys.add(pos_key)
                    print(f"[RISK] [DIRECT-EXIT] ⚡ Worker hasn't handled {pos_key} after 5s — executing directly")
                    bot_loop = self.loop
                    if bot_loop and bot_loop.is_running():
                        future = asyncio.run_coroutine_threadsafe(
                            self._direct_execute_exit(stc_signal, pos_key), bot_loop
                        )
                        try:
                            future.result(timeout=15)
                        except Exception as fut_ex:
                            print(f"[RISK] [DIRECT-EXIT] ✗ {pos_key} execution error: {fut_ex}")
                    else:
                        loop = asyncio.new_event_loop()
                        try:
                            loop.run_until_complete(self._direct_execute_exit(stc_signal, pos_key))
                        finally:
                            loop.close()
                except Exception as ex:
                    print(f"[RISK] [DIRECT-EXIT] ✗ Thread execution failed for {pos_key}: {ex}")
                    import traceback
                    traceback.print_exc()
            
            _exit_thread = threading.Thread(target=_thread_exit_executor, daemon=True, name=f"risk-exit-{pos_key}")
            _exit_thread.start()
            
        except Exception as e:
            self.cache.reset_closing(pos_key)
            try:
                from src.risk.exit_lease_manager import get_exit_lease_manager
                get_exit_lease_manager().force_release(pos_key)
            except Exception:
                pass
            print(f"[RISK] ✗ Failed to queue STC order for {pos_key}: {e}")
    
    async def _direct_execute_exit(self, stc_signal: dict, pos_key: str):
        broker_name = stc_signal.get('broker', '')
        broker_upper = broker_name.upper()
        asset_type = stc_signal.get('asset', 'option')
        
        broker_instance = None
        if 'ROBINHOOD' in broker_upper:
            broker_instance = self.robinhood_broker
        elif 'SCHWAB' in broker_upper:
            broker_instance = self.schwab_broker
        elif 'ALPACA' in broker_upper:
            broker_instance = self.alpaca_broker
        elif 'IBKR' in broker_upper:
            broker_instance = self.ibkr_broker
        elif 'TASTYTRADE' in broker_upper:
            broker_instance = self.tastytrade_broker
        elif 'TRADING212' in broker_upper:
            broker_instance = self.trading212_broker
        elif 'WEBULL_PAPER' in broker_upper:
            broker_instance = getattr(self, 'webull_paper_broker', None) or (getattr(self.bot, 'webull_paper', None) if hasattr(self, 'bot') and self.bot else None)
        elif 'WEBULL' in broker_upper:
            broker_instance = getattr(self, 'webull_broker', None) or (self.bot.webull if hasattr(self, 'bot') and self.bot else None)
        
        if not broker_instance:
            print(f"[RISK] [DIRECT-EXIT] ✗ No broker instance for {broker_name}")
            return
        
        try:
            order_price = stc_signal['price']
            if stc_signal.get('_use_market_order'):
                order_price = None

            if asset_type == 'option':
                option_kwargs = {
                    'symbol': stc_signal['symbol'],
                    'strike': stc_signal.get('strike'),
                    'expiry': stc_signal.get('expiry'),
                    'option_type': stc_signal.get('opt_type'),
                    'action': 'STC',
                    'quantity': stc_signal['qty'],
                    'price': order_price,
                }
                if broker_upper in ('WEBULL', 'WEBULL_PAPER', 'SCHWAB'):
                    option_kwargs['option_id'] = stc_signal.get('option_id')
                    option_kwargs['_risk_management_order'] = True
                    if order_price is None:
                        option_kwargs['price'] = stc_signal['price']
                result = await broker_instance.place_option_order(**option_kwargs)
            else:
                result = await broker_instance.place_stock_order(
                    symbol=stc_signal['symbol'],
                    quantity=stc_signal['qty'],
                    price=order_price,
                    action='STC',
                )
            
            order_id = None
            if isinstance(result, dict):
                order_id = result.get('order_id') or result.get('orderId') or result.get('id')
            elif result:
                order_id = str(result)
            
            if order_id:
                print(f"[RISK] [DIRECT-EXIT] ✓ {pos_key} exit order placed: {order_id}")
                try:
                    from src.database.trade_db import record_trade_execution
                    record_trade_execution(
                        signal=stc_signal,
                        broker_name=broker_name,
                        order_id=str(order_id),
                        status='FILLED',
                        execution_type='risk_direct_exit'
                    )
                except Exception:
                    pass
            else:
                print(f"[RISK] [DIRECT-EXIT] ⚠️ {pos_key} result: {result}")
            self.release_exit_marker(pos_key)
        except Exception as e:
            print(f"[RISK] [DIRECT-EXIT] ✗ {pos_key} execution failed: {e}")
            import traceback
            traceback.print_exc()
            self.release_exit_marker(pos_key)

    def _get_streaming_bid_ask(self, position: PositionSnapshot) -> Dict[str, float]:
        """Get real-time bid/ask from streaming hubs for accurate exit pricing.
        
        Returns dict with 'bid', 'ask', 'mid', 'source' keys.
        bid/ask/mid are 0 when unavailable. Accepts partial quotes (bid-only).
        Checks WebullDataHub first, then SchwabDataHub, then IBKRDataHub.
        Hub staleness is enforced by the hubs themselves (QUOTE_STALE_THRESHOLD=120s).
        """
        result = {'bid': 0, 'ask': 0, 'mid': 0, 'source': ''}

        def _extract_quotes(data, source_name):
            if not data:
                return None
            bid = float(data.get('bid', 0) or 0)
            ask = float(data.get('ask', 0) or 0)
            last = float(data.get('last', 0) or data.get('price', 0) or 0)
            if bid > 0 or ask > 0:
                mid = round((bid + ask) / 2, 2) if bid > 0 and ask > 0 else 0
                return {'bid': bid, 'ask': ask, 'mid': mid, 'last': last, 'source': source_name}
            return None

        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming():
                lookup_keys = []
                if position.asset == 'option':
                    if hasattr(position, 'raw_symbol') and position.raw_symbol:
                        lookup_keys.append(position.raw_symbol)
                    if position.symbol:
                        lookup_keys.append(position.symbol)
                    if position.option_id:
                        lookup_keys.append(str(position.option_id))
                else:
                    if position.symbol:
                        lookup_keys.append(position.symbol)
                for lookup_key in lookup_keys:
                    q = _extract_quotes(hub.get_quote_detailed(lookup_key), 'webull_hub')
                    if q:
                        return q
        except Exception:
            pass

        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            schwab_hub = get_schwab_data_hub()
            if schwab_hub.is_streaming():
                if position.asset == 'option' and position.expiry and position.strike:
                    expiry = position.expiry or ''
                    if '/' in expiry:
                        parts = expiry.split('/')
                        if len(parts) == 3:
                            expiry = f"20{parts[2]}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                        elif len(parts) == 2:
                            import datetime
                            year = datetime.datetime.now().year
                            expiry = f"{year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}"
                    if '-' in expiry:
                        opt_type = (position.direction or '').upper()
                        if opt_type == 'CALL': opt_type = 'C'
                        elif opt_type == 'PUT': opt_type = 'P'
                        elif opt_type and opt_type[0] in ('C', 'P'): opt_type = opt_type[0]
                        else: opt_type = ''
                        if opt_type:
                            from src.brokers.schwab_broker import SchwabBroker
                            occ = SchwabBroker._build_option_symbol(None, position.symbol, expiry, position.strike, opt_type)
                            q = _extract_quotes(schwab_hub.get_quote_detailed(occ), 'schwab_hub')
                            if q:
                                return q
                elif position.asset != 'option':
                    q = _extract_quotes(schwab_hub.get_quote_detailed(position.symbol), 'schwab_hub')
                    if q:
                        return q
        except Exception:
            pass

        try:
            from src.services.ibkr_data_hub import get_ibkr_data_hub
            ibkr_hub = get_ibkr_data_hub()
            if ibkr_hub.is_streaming():
                lookup_key = None
                if position.asset == 'option':
                    lookup_key = getattr(position, 'raw_symbol', None) or None
                else:
                    lookup_key = position.symbol
                if lookup_key:
                    q = _extract_quotes(ibkr_hub.get_quote_detailed(lookup_key), 'ibkr_hub')
                    if q:
                        return q
        except Exception:
            pass

        return result

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
            elif direction and direction[0] in ('C', 'P'):
                opt_type = direction[0]
            else:
                opt_type = ''
                try:
                    from gui_app.database import get_trade_by_id
                    trade_id = getattr(position, '_trade_id', None) or self.cache.get_trade_id(position.position_key)
                    if trade_id:
                        trade = get_trade_by_id(trade_id)
                        if trade:
                            db_opt = (trade.get('option_type', '') or trade.get('opt_type', '') or '').upper()
                            if db_opt in ('C', 'P', 'CALL', 'PUT'):
                                opt_type = 'C' if db_opt in ('C', 'CALL') else 'P'
                                print(f"[RISK] ✓ Inferred opt_type={opt_type} from DB trade #{trade_id} for {position.position_key}")
                except Exception:
                    pass
                if not opt_type:
                    print(f"[RISK] ⚠️ UNKNOWN direction for {position.position_key} — cannot construct STC (strike={position.strike}, expiry={expiry_iso})")
                    return None
            
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
        
        Industry-grade approach:
        1. Group executed/tracking orders by broker+symbol
        2. For each group, pick the MOST RECENT order that maps to an OPEN trade
        3. Always seed SL/PT from that order (overwriting stale values)
        4. Clean up cache entries from terminal orders (expired/cancelled/closed)
        
        This prevents stale SL/PT from old orders causing premature exits on re-entries.
        """
        try:
            from gui_app.database import get_connection
            import json
            from datetime import datetime as dt
            
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT co.id, co.symbol, co.channel_id, co.broker_primary,
                       co.stop_loss_pct, co.stop_loss_fixed, co.stop_loss_type, co.stop_loss_value,
                       co.take_profit_targets, co.target_ranges, co.trigger_price,
                       co.trailing_stop_enabled, co.leave_runner, co.status as order_status,
                       co.created_at as order_created_at
                FROM conditional_orders co
                WHERE co.status IN ('EXECUTED', 'TRACKING')
                AND co.created_at >= datetime('now', '-7 days')
                ORDER BY co.created_at DESC
            ''')
            
            executed_orders = cursor.fetchall()
            if not executed_orders:
                return 0
            
            open_trade_symbols = set()
            try:
                cursor.execute('''
                    SELECT UPPER(symbol) as symbol, broker, id as trade_id
                    FROM trades WHERE status = 'OPEN'
                ''')
                for row in cursor.fetchall():
                    open_trade_symbols.add((row['symbol'], row['broker']))
            except Exception:
                pass
            
            best_orders = {}
            for order in executed_orders:
                order_id = order['id']
                symbol = order['symbol'].upper()
                broker = order['broker_primary']
                group_key = f"{broker}_{symbol}"
                
                has_open_trade = (symbol, broker) in open_trade_symbols
                
                if group_key not in best_orders:
                    best_orders[group_key] = (order, has_open_trade)
                else:
                    existing_order, existing_has_open = best_orders[group_key]
                    if has_open_trade and not existing_has_open:
                        best_orders[group_key] = (order, has_open_trade)
                    elif has_open_trade == existing_has_open:
                        if order_id > existing_order['id']:
                            best_orders[group_key] = (order, has_open_trade)
            
            reconciled_count = 0
            for group_key, (order, has_open_trade) in best_orders.items():
                order_id = order['id']
                symbol = order['symbol'].upper()
                broker = order['broker_primary']
                trigger_price = order['trigger_price']
                
                if not has_open_trade:
                    pos_key_stock = f"{broker}_{symbol}_stock"
                    if self.cache.get(pos_key_stock):
                        self.cache.remove(pos_key_stock)
                        print(f"[RISK] 🧹 Cleaned stale cache for {symbol} (no open trade, order #{order_id})")
                    continue
                
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
                if profit_targets_raw and trigger_price:
                    try:
                        if isinstance(profit_targets_raw, str):
                            pts = json.loads(profit_targets_raw)
                        else:
                            pts = profit_targets_raw
                        
                        if isinstance(pts, list) and pts:
                            first_pt = pts[0]
                            if isinstance(first_pt, (int, float)):
                                pt_price = trigger_price * (1 + float(first_pt) / 100)
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
                    is_new_instance = (
                        cache_entry.source_order_id is None or
                        cache_entry.source_order_id != order_id
                    )
                    
                    if is_new_instance:
                        if sl_price:
                            cache_entry.stop_loss_price = sl_price
                        if pt_price:
                            cache_entry.profit_target_price = pt_price
                        cache_entry.source_order_id = order_id
                        cache_entry.seed_time = dt.now().isoformat()
                        cache_entry.manual_sl_price = None
                        cache_entry.manual_sl_pct = None
                        cache_entry.manual_pt_targets = None
                        cache_entry.dynamic_sl_price = None
                        cache_entry.tier1_hit = False
                        cache_entry.tier2_hit = False
                        cache_entry.tier3_hit = False
                        cache_entry.tier4_hit = False
                        cache_entry.max_pnl_seen = 0.0
                        cache_entry.giveback_guard_active = False
                        cache_entry.early_trailing_active = False
                        cache_entry.early_stop_price = None
                        cache_entry.early_steps_locked = 0
                        reconciled_count += 1
                        sl_display = f"${sl_price:.2f}" if sl_price else "N/A"
                        pt_display = f"${pt_price:.2f}" if pt_price else "N/A"
                        print(f"[RISK] 🔗 Linked {symbol} to conditional order #{order_id} "
                              f"(SL: {sl_display}, PT: {pt_display}) [new instance]")
                    else:
                        if sl_price and not cache_entry.stop_loss_price:
                            cache_entry.stop_loss_price = sl_price
                        if pt_price and not cache_entry.profit_target_price:
                            cache_entry.profit_target_price = pt_price
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
                        broker=broker,
                        source_order_id=order_id,
                        seed_time=dt.now().isoformat()
                    )
                    reconciled_count += 1
                    print(f"[RISK] ✨ Created cache entry for {symbol} from conditional order #{order_id}")
            
            terminal_cleaned = self._cleanup_terminal_order_cache(conn)
            if terminal_cleaned > 0:
                print(f"[RISK] 🧹 Cleaned {terminal_cleaned} stale cache entries from terminal orders")
            
            if reconciled_count > 0 or terminal_cleaned > 0:
                self.cache.save()
            
            return reconciled_count
            
        except Exception as e:
            print(f"[RISK] Error reconciling conditional orders: {e}")
            import traceback
            traceback.print_exc()
            return 0
    
    def _cleanup_terminal_order_cache(self, conn=None) -> int:
        """
        Clean up cache entries from conditional orders in terminal states
        (EXPIRED, CANCELED, CANCELLED, ERROR, FAILED) that have no matching open trade.
        """
        try:
            from gui_app.database import get_connection as _get_conn
            if conn is None:
                conn = _get_conn()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT DISTINCT co.symbol, co.broker_primary
                FROM conditional_orders co
                WHERE co.status IN ('EXPIRED', 'CANCELED', 'CANCELLED', 'ERROR', 'FAILED')
                AND co.created_at >= datetime('now', '-7 days')
            ''')
            terminal_orders = cursor.fetchall()
            
            if not terminal_orders:
                return 0
            
            cleaned = 0
            for order in terminal_orders:
                symbol = order['symbol'].upper()
                broker = order['broker_primary']
                pos_key = f"{broker}_{symbol}_stock"
                
                cache_entry = self.cache.get(pos_key)
                if not cache_entry:
                    continue
                
                cursor.execute('''
                    SELECT COUNT(*) as cnt FROM trades
                    WHERE UPPER(symbol) = ? AND broker = ? AND status = 'OPEN'
                ''', (symbol, broker))
                row = cursor.fetchone()
                has_open = row['cnt'] > 0 if row else False
                
                if not has_open:
                    self.cache.remove(pos_key)
                    cleaned += 1
            
            return cleaned
        except Exception as e:
            print(f"[RISK] Error cleaning terminal order cache: {e}")
            return 0
    
    _HUB_PRICE_MAX_AGE = 30

    def _get_raw_webull_client(self):
        wb_broker = self._webull_broker
        if not wb_broker:
            try:
                if hasattr(self.position_fetcher, '__self__'):
                    _pf_self = self.position_fetcher.__self__
                    if hasattr(_pf_self, 'wb') or hasattr(_pf_self, '_client'):
                        wb_broker = _pf_self
                        self._webull_broker = wb_broker
            except Exception:
                pass
        if wb_broker:
            client = getattr(wb_broker, '_client', None) or getattr(wb_broker, 'wb', None)
            if client:
                return client
        return None

    def _check_price_freshness(self, position, cache, channel_settings) -> Optional['ExitDecision']:
        import time as _ft
        pos_key = f"{position.broker}_{position.symbol}_{position.asset}"

        if not hasattr(self, '_price_confirmed_fresh'):
            self._price_confirmed_fresh = {}

        if pos_key in self._price_confirmed_fresh:
            return None

        entry_price = cache.entry_price
        current_price = position.current_price

        if entry_price <= 0 or current_price <= 0:
            self._price_confirmed_fresh[pos_key] = _ft.time()
            return None

        deviation_pct = abs(current_price - entry_price) / entry_price * 100

        sl_pct = 0
        if channel_settings and channel_settings.stop_loss_pct > 0:
            sl_pct = channel_settings.stop_loss_pct
        elif cache.stop_loss_price and entry_price > 0:
            sl_pct = abs(entry_price - cache.stop_loss_price) / entry_price * 100

        if sl_pct <= 0:
            self._price_confirmed_fresh[pos_key] = _ft.time()
            return None

        is_loss = current_price < entry_price
        if is_loss and deviation_pct > sl_pct * 1.5:
            session = self._get_market_session()
            if session == 'extended':
                fresh_price = None
                try:
                    from src.services.webull_data_hub import get_webull_data_hub
                    hub = get_webull_data_hub()
                    if hub:
                        fresh_price = self._get_fresh_hub_price(hub, position.symbol, max_age=60)
                except Exception:
                    pass
                if not fresh_price:
                    try:
                        from src.services.schwab_data_hub import get_schwab_data_hub
                        s_hub = get_schwab_data_hub()
                        if s_hub:
                            fresh_price = self._get_fresh_hub_price(s_hub, position.symbol, max_age=60)
                    except Exception:
                        pass
                if not fresh_price:
                    try:
                        from src.services.ibkr_data_hub import get_ibkr_data_hub
                        ib_hub = get_ibkr_data_hub()
                        if ib_hub and ib_hub.is_streaming():
                            fresh_price = self._get_fresh_hub_price(ib_hub, position.symbol, max_age=60)
                    except Exception:
                        pass

                if fresh_price and fresh_price > 0:
                    fresh_dev = abs(fresh_price - entry_price) / entry_price * 100
                    if fresh_dev < sl_pct:
                        print(f"[RISK] 🛡️ FRESHNESS GUARD: {position.symbol} position price ${current_price:.2f} "
                              f"looks stale (prev close?) — streaming says ${fresh_price:.2f} "
                              f"({fresh_dev:.1f}% vs entry ${entry_price:.2f}) — BLOCKING false SL exit")
                        position.current_price = fresh_price
                        self._price_confirmed_fresh[pos_key] = _ft.time()
                        return ExitDecision.no_exit()
                    else:
                        print(f"[RISK] ⚠️ FRESHNESS: {position.symbol} streaming confirms loss "
                              f"${fresh_price:.2f} ({fresh_dev:.1f}% from entry ${entry_price:.2f}) "
                              f"— allowing SL evaluation")
                        self._price_confirmed_fresh[pos_key] = _ft.time()
                        return None

                if not hasattr(self, '_price_deferred_once'):
                    self._price_deferred_once = {}
                if pos_key not in self._price_deferred_once:
                    self._price_deferred_once[pos_key] = _ft.time()
                    print(f"[RISK] 🛡️ FRESHNESS GUARD: {position.symbol} first-cycle price ${current_price:.2f} "
                          f"deviates {deviation_pct:.1f}% from entry ${entry_price:.2f} during extended hours — "
                          f"deferring SL for 1 cycle to verify")
                    return ExitDecision.no_exit()
                else:
                    print(f"[RISK] ⚠️ FRESHNESS: {position.symbol} already deferred once — "
                          f"allowing SL evaluation (price ${current_price:.2f}, no stream confirmation)")
                    self._price_confirmed_fresh[pos_key] = _ft.time()
                    return None

        self._price_confirmed_fresh[pos_key] = _ft.time()
        return None

    def _resolve_webull_option_price(self, pos: dict, quantity: float, symbol: str = '') -> float:
        latest = float(pos.get('latestPrice', 0) or 0)
        last = float(pos.get('lastPrice', 0) or 0)
        cost_price = float(pos.get('costPrice', 0) or 0)
        market_value = float(pos.get('marketValue', 0))
        mv_price = market_value / (quantity * 100) if quantity > 0 else 0

        direct_price = latest if latest > 0 else last

        if direct_price > 0 and cost_price > 0:
            ratio = direct_price / cost_price if cost_price > 0 else 0
            if ratio > 50:
                if not hasattr(self, '_wb_opt_price_warn_ts'):
                    self._wb_opt_price_warn_ts = {}
                import time as _owt
                _now = _owt.time()
                _sym = symbol or pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
                if _sym not in self._wb_opt_price_warn_ts or (_now - self._wb_opt_price_warn_ts.get(_sym, 0)) > 30:
                    self._wb_opt_price_warn_ts[_sym] = _now
                    print(f"[RISK] ⚠️ OPTION PRICE GUARD: {_sym} latestPrice=${direct_price:.2f} is {ratio:.0f}x entry ${cost_price:.2f} "
                          f"— likely underlying index price, not option premium. Using marketValue-derived price ${mv_price:.4f}" if mv_price > 0
                          else f"[RISK] ⚠️ OPTION PRICE GUARD: {_sym} latestPrice=${direct_price:.2f} is {ratio:.0f}x entry ${cost_price:.2f} "
                               f"— likely underlying index price, not option premium. Falling back to entry price")
                if mv_price > 0:
                    mv_ratio = mv_price / cost_price if cost_price > 0 else 0
                    if mv_ratio < 50:
                        return mv_price
                return cost_price

        if direct_price > 0:
            return direct_price

        if mv_price > 0:
            return mv_price

        return cost_price

    def _resolve_webull_stock_price(self, pos: dict, quantity: float) -> float:
        latest = float(pos.get('latestPrice', 0) or 0)
        last = float(pos.get('lastPrice', 0) or 0)
        market_value = float(pos.get('marketValue', 0))
        mv_price = market_value / quantity if quantity > 0 else 0
        cost_price = float(pos.get('costPrice', 0) or 0)

        direct_price = latest if latest > 0 else last
        if direct_price > 0:
            return direct_price

        symbol = pos.get('ticker', {}).get('symbol', '') or pos.get('symbol', '')
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub:
                hub_price = self._get_fresh_hub_price(hub, symbol, max_age=60)
                if hub_price and hub_price > 0:
                    return hub_price
        except Exception:
            pass

        if mv_price > 0 and cost_price > 0:
            deviation = abs(mv_price - cost_price) / cost_price if cost_price > 0 else 0
            if deviation > 0.25:
                session = self._get_market_session()
                if session == 'extended':
                    if not hasattr(self, '_wb_mv_warn_ts'):
                        self._wb_mv_warn_ts = {}
                    import time as _wt
                    _now = _wt.time()
                    if symbol not in self._wb_mv_warn_ts or (_now - self._wb_mv_warn_ts[symbol]) > 60:
                        self._wb_mv_warn_ts[symbol] = _now
                        print(f"[RISK] ⚠️ Webull {symbol}: marketValue price ${mv_price:.2f} deviates "
                              f"{deviation*100:.0f}% from entry ${cost_price:.2f} during extended hours — "
                              f"possible stale previous-close, using entry as safe fallback")
                    return cost_price

        return mv_price if mv_price > 0 else cost_price

    def _get_fresh_hub_price(self, hub, symbol, max_age=None):
        if max_age is None:
            max_age = self._HUB_PRICE_MAX_AGE
        import time as _t
        quote = hub.get_quote(symbol)
        if not quote:
            return None
        age = _t.time() - quote.timestamp
        if age > max_age:
            return None
        price = quote.last if hasattr(quote, 'last') else None
        if not price or price <= 0:
            return None
        return price

    def _get_hub_quote_age(self, hub, symbol):
        import time as _t
        quote = hub.get_quote(symbol)
        if not quote:
            return None
        return _t.time() - quote.timestamp

    def _get_hub_quote_ts(self, hub, symbol):
        quote = hub.get_quote(symbol)
        if not quote:
            return None
        return quote.timestamp

    def _get_market_session(self):
        from datetime import datetime
        try:
            import pytz
            et = pytz.timezone('US/Eastern')
            now_et = datetime.now(et)
        except Exception:
            import os, time as _tz_time
            os.environ.setdefault('TZ', 'America/New_York')
            _tz_time.tzset()
            now_et = datetime.now()
        wd = now_et.weekday()
        if wd >= 5:
            return 'closed'
        t = now_et.hour * 60 + now_et.minute
        if 570 <= t < 960:
            return 'regular'
        if 240 <= t < 570 or 960 <= t < 1200:
            return 'extended'
        return 'closed'

    def _is_market_hours(self):
        return self._get_market_session() != 'closed'

    async def _detect_and_fix_stuck_prices(self, positions: list):
        import time as _t
        now = _t.time()
        session = self._get_market_session()
        rest_cooldown = 3.0 if session == 'regular' else (10.0 if session == 'extended' else 30.0)
        _MAX_REST_REPAIRS_PER_CYCLE = 3
        rest_repairs_this_cycle = 0

        effective_threshold = self._STUCK_PRICE_THRESHOLD_EXTENDED if session == 'extended' else self._STUCK_PRICE_THRESHOLD_REGULAR

        stuck_candidates = []
        for pos in positions:
            key = self._pos_tracking_key(pos)
            tracker = self._stuck_price_tracker.get(key)
            if tracker is None:
                self._stuck_price_tracker[key] = {
                    'last_price': pos.current_price,
                    'last_changed': now,
                    'rest_refreshed': 0
                }
                continue
            if abs(pos.current_price - tracker['last_price']) > 0.0001:
                tracker['last_price'] = pos.current_price
                tracker['last_changed'] = now
                tracker['rest_refreshed'] = 0
                if key in self._price_unverified:
                    del self._price_unverified[key]
                continue
            stuck_seconds = now - tracker['last_changed']

            if session == 'extended' and stuck_seconds >= 2:
                cache_entry = self.cache.get(key) or self.cache.get(f"{pos.broker}_{pos.symbol}")
                if cache_entry and cache_entry.entry_price > 0:
                    entry = cache_entry.entry_price
                    dev = abs(pos.current_price - entry) / entry
                    if dev > 0.15 and pos.current_price < entry:
                        if (now - tracker.get('rest_refreshed', 0)) >= rest_cooldown:
                            print(f"[RISK] 🔍 PREV-CLOSE DETECT: {pos.symbol} price ${pos.current_price:.2f} "
                                  f"is {dev*100:.0f}% below entry ${entry:.2f} during extended hours — forcing refresh")
                            stuck_candidates.append((stuck_seconds, pos, key, tracker))
                            continue

            if stuck_seconds < effective_threshold:
                continue
            if (now - tracker.get('rest_refreshed', 0)) < rest_cooldown:
                continue
            stuck_candidates.append((stuck_seconds, pos, key, tracker))

        stuck_candidates.sort(key=lambda x: -x[0])

        for stuck_seconds, pos, key, tracker in stuck_candidates:
            try:
                fresh_price = self._try_cross_hub_price(pos, now)
                source = 'cross-hub'
                _rest_checked = False
                if not fresh_price or abs(fresh_price - pos.current_price) < 0.0001:
                    if rest_repairs_this_cycle < _MAX_REST_REPAIRS_PER_CYCLE:
                        _rest_checked = True
                        tracker['rest_refreshed'] = now
                        rest_price = await self._try_rest_quote(pos)
                        if rest_price and rest_price > 0:
                            fresh_price = rest_price
                            rest_via = getattr(self, '_last_rest_source', None)
                            source = f'REST/{rest_via}' if rest_via else 'REST'
                            rest_repairs_this_cycle += 1
                if fresh_price and fresh_price > 0 and abs(fresh_price - pos.current_price) > 0.0001:
                    if session == 'extended' and _rest_checked:
                        cache_entry = self.cache.get(key) or self.cache.get(f"{pos.broker}_{pos.symbol}")
                        if cache_entry and cache_entry.entry_price > 0:
                            entry = cache_entry.entry_price
                            rest_dev = abs(fresh_price - entry) / entry
                            stream_dev = abs(pos.current_price - entry) / entry
                            if rest_dev > 0.20 and fresh_price < entry and stream_dev < 0.15:
                                print(f"[RISK] 🛡️ PREV-CLOSE REJECT: {pos.symbol} REST returned ${fresh_price:.2f} "
                                      f"({rest_dev*100:.0f}% from entry ${entry:.2f}) but streaming has "
                                      f"${pos.current_price:.2f} ({stream_dev*100:.1f}%) — REST price is likely "
                                      f"previous close, not premarket. Keeping streaming price.")
                                tracker['rest_refreshed'] = now
                                continue
                    print(f"[RISK] 🔄 STUCK PRICE FIX ({source}): {pos.broker} {pos.symbol} "
                          f"was ${pos.current_price:.4f} (frozen {stuck_seconds:.0f}s) → ${fresh_price:.4f}")
                    pos.current_price = fresh_price
                    tracker['last_price'] = fresh_price
                    tracker['last_changed'] = now
                    self._rest_repaired_prices[key] = {
                        'price': fresh_price, 'until': now + self._HUB_PRICE_MAX_AGE,
                        'created_at': now
                    }
                    self._rest_repair_cycle_keys[key] = now
                    if key in self._price_unverified:
                        del self._price_unverified[key]
                elif stuck_seconds >= self._STALENESS_EXIT_BLOCK_THRESHOLD and _rest_checked:
                    if key not in self._price_unverified:
                        self._price_unverified[key] = {'since': now, 'logged': False}
                        print(f"[RISK] ⚠️ UNVERIFIED: {pos.broker} {pos.symbol} frozen {stuck_seconds:.0f}s — "
                              f"all sources returned same price ${pos.current_price:.4f} — marking unverified")
            except Exception as e:
                if not hasattr(self, '_stuck_fix_err_logged'):
                    self._stuck_fix_err_logged = True
                    print(f"[RISK] ⚠️ Stuck price fix error: {e}")
        active_keys = {self._pos_tracking_key(p) for p in positions}
        stale_keys = [k for k in self._stuck_price_tracker if k not in active_keys]
        for k in stale_keys:
            del self._stuck_price_tracker[k]
        stale_repair = [k for k in self._rest_repaired_prices if k not in active_keys]
        for k in stale_repair:
            del self._rest_repaired_prices[k]
        if hasattr(self, '_price_confirmed_fresh'):
            stale_fresh = [k for k in self._price_confirmed_fresh if k not in active_keys]
            for k in stale_fresh:
                del self._price_confirmed_fresh[k]
        if hasattr(self, '_price_deferred_once'):
            stale_defer = [k for k in self._price_deferred_once if k not in active_keys]
            for k in stale_defer:
                del self._price_deferred_once[k]
        stale_unverified = [k for k in self._price_unverified if k not in active_keys]
        for k in stale_unverified:
            del self._price_unverified[k]
        if hasattr(self, '_staleness_block_logged'):
            stale_sbl = [k for k in self._staleness_block_logged if not any(k.startswith(ak) for ak in active_keys)]
            for k in stale_sbl:
                del self._staleness_block_logged[k]

    @staticmethod
    def _pos_tracking_key(pos):
        if pos.asset == 'option' and (pos.strike or pos.expiry or pos.direction):
            return f"{pos.broker}_{pos.symbol}_{pos.asset}_{pos.strike}_{pos.expiry}_{pos.direction}"
        return f"{pos.broker}_{pos.symbol}_{pos.asset}"

    @staticmethod
    def _normalize_expiry_yyyymmdd(expiry):
        if not expiry:
            return ''
        e = str(expiry).strip()
        clean = e.replace('-', '')
        if len(clean) == 8 and clean.isdigit():
            return clean
        if '/' in e:
            parts = e.split('/')
            if len(parts) == 3:
                m, d, y = parts
                if len(y) == 2:
                    y = '20' + y
                return f"{y}{m.zfill(2)}{d.zfill(2)}"
            elif len(parts) == 2:
                import datetime
                m, d = parts
                today = datetime.date.today()
                candidate = datetime.date(today.year, int(m), int(d))
                if candidate < today:
                    candidate = datetime.date(today.year + 1, int(m), int(d))
                return candidate.strftime('%Y%m%d')
        return clean

    _INDEX_TO_CANONICAL = {
        'SPX': 'SPX', 'SPXW': 'SPX',
        'NDX': 'NDX', 'NDXP': 'NDX',
        'VIX': 'VIX', 'VIXW': 'VIX',
        'RUT': 'RUT', 'RUTW': 'RUT',
        'DJX': 'DJX', 'DJXW': 'DJX',
    }
    _HUB_INDEX_SYMBOLS = {
        'Webull': {'SPX': 'SPX', 'NDX': 'NDX', 'VIX': 'VIX', 'RUT': 'RUT', 'DJX': 'DJX'},
        'Schwab': {'SPX': 'SPXW', 'NDX': 'NDXP', 'VIX': 'VIXW', 'RUT': 'RUTW', 'DJX': 'DJXW'},
        'IBKR': {'SPX': 'SPX', 'NDX': 'NDX', 'VIX': 'VIX', 'RUT': 'RUT', 'DJX': 'DJX'},
        'T212': {'SPX': 'SPX', 'NDX': 'NDX', 'VIX': 'VIX', 'RUT': 'RUT', 'DJX': 'DJX'},
    }

    def _normalize_symbol_for_hub(self, symbol, target_hub_name):
        upper = (symbol or '').upper()
        canonical = self._INDEX_TO_CANONICAL.get(upper)
        if canonical:
            hub_map = self._HUB_INDEX_SYMBOLS.get(target_hub_name, {})
            return hub_map.get(canonical, upper)
        return upper

    def _get_option_hub_keys(self, pos, target_hub_name):
        keys = []
        if not pos.strike or not pos.expiry or not pos.direction:
            if pos.raw_symbol:
                keys.append(pos.raw_symbol)
            return keys
        underlying = self._normalize_symbol_for_hub(pos.symbol, target_hub_name)
        expiry_norm = self._normalize_expiry_yyyymmdd(pos.expiry)
        if not expiry_norm or len(expiry_norm) != 8:
            if pos.raw_symbol:
                keys.append(pos.raw_symbol)
            return keys
        if target_hub_name == 'Schwab':
            try:
                expiry_str = expiry_norm
                expiry_short = expiry_str[2:] if len(expiry_str) == 8 else expiry_str
                right = 'C' if pos.direction.upper() in ('C', 'CALL') else 'P'
                strike_int = int(float(pos.strike) * 1000)
                occ = f"{underlying:<6}{expiry_short}{right}{strike_int:08d}"
                keys.append(occ)
            except Exception:
                pass
        elif target_hub_name == 'IBKR':
            try:
                right = 'C' if pos.direction.upper() in ('C', 'CALL') else 'P'
                strike_val = float(pos.strike)
                ibkr_key = f"{underlying}_{expiry_norm}_{strike_val}_{right}"
                keys.append(ibkr_key)
            except Exception:
                pass
        if pos.raw_symbol and pos.raw_symbol not in keys:
            keys.append(pos.raw_symbol)
        return keys

    def _try_cross_hub_price(self, pos, now):
        broker_upper = (pos.broker or '').upper()
        is_option = pos.asset == 'option'
        alt_hubs = []
        if 'WEBULL' not in broker_upper:
            try:
                from src.services.webull_data_hub import get_webull_data_hub
                wb_hub = get_webull_data_hub()
                if wb_hub.is_streaming():
                    alt_hubs.append(('Webull', wb_hub))
            except Exception:
                pass
        if 'SCHWAB' not in broker_upper:
            try:
                from src.services.schwab_data_hub import get_schwab_data_hub
                sc_hub = get_schwab_data_hub()
                if sc_hub.is_streaming():
                    alt_hubs.append(('Schwab', sc_hub))
            except Exception:
                pass
        if 'IBKR' not in broker_upper:
            try:
                from src.services.ibkr_data_hub import get_ibkr_data_hub
                ib_hub = get_ibkr_data_hub()
                if ib_hub.is_streaming():
                    alt_hubs.append(('IBKR', ib_hub))
            except Exception:
                pass
        for hub_name, hub in alt_hubs:
            if is_option:
                opt_keys = self._get_option_hub_keys(pos, hub_name)
                for ok in opt_keys:
                    price = self._get_fresh_hub_price(hub, ok, max_age=2)
                    if price and price > 0:
                        return price
            else:
                norm_sym = self._normalize_symbol_for_hub(pos.symbol, hub_name)
                price = self._get_fresh_hub_price(hub, norm_sym, max_age=2)
                if price and price > 0:
                    return price
        if not is_option and 'TRADING212' not in broker_upper:
            try:
                from src.services.trading212_data_hub import get_trading212_data_hub
                t212_hub = get_trading212_data_hub()
                if t212_hub:
                    import time as _t
                    norm_sym = self._normalize_symbol_for_hub(pos.symbol, 'T212')
                    t212_price = t212_hub.get_quote_price(norm_sym)
                    t212_ts = t212_hub.get_quote_timestamp(norm_sym)
                    if t212_price and t212_price > 0 and t212_ts and (_t.time() - t212_ts) < 2:
                        return t212_price
            except Exception:
                pass
        return None

    async def _try_rest_quote(self, pos):
        current = pos.current_price
        broker_upper = (pos.broker or '').upper()
        self._last_rest_source = None
        is_option = pos.asset == 'option'

        if not is_option:
            if 'WEBULL' in broker_upper:
                price = await self._try_schwab_rest_quote(pos.symbol)
                if price and price > 0 and abs(price - current) > 0.0001:
                    self._last_rest_source = 'Schwab'
                    return price
                price = await self._try_webull_rest_quote(pos.symbol)
                if price and price > 0 and abs(price - current) > 0.0001:
                    self._last_rest_source = 'Webull'
                    return price
            elif 'SCHWAB' in broker_upper:
                price = await self._try_webull_rest_quote(pos.symbol)
                if price and price > 0 and abs(price - current) > 0.0001:
                    self._last_rest_source = 'Webull'
                    return price
                price = await self._try_schwab_rest_quote(pos.symbol)
                if price and price > 0 and abs(price - current) > 0.0001:
                    self._last_rest_source = 'Schwab'
                    return price
            else:
                price = await self._try_schwab_rest_quote(pos.symbol)
                if price and price > 0 and abs(price - current) > 0.0001:
                    self._last_rest_source = 'Schwab'
                    return price
                price = await self._try_webull_rest_quote(pos.symbol)
                if price and price > 0 and abs(price - current) > 0.0001:
                    self._last_rest_source = 'Webull'
                    return price

        if not is_option:
            price = await self._try_broker_get_quote(pos)
            if price and price > 0 and abs(price - current) > 0.0001:
                self._last_rest_source = pos.broker
                return price
        return None

    async def _try_webull_rest_quote(self, symbol):
        raw_client = self._get_raw_webull_client()
        if not raw_client or not hasattr(raw_client, 'get_quote'):
            return None
        try:
            sym = symbol
            raw_quote = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, lambda: raw_client.get_quote(stock=sym)),
                timeout=5.0)
            if raw_quote and isinstance(raw_quote, dict):
                ask = float(raw_quote.get('askPrice', 0) or 0)
                bid = float(raw_quote.get('bidPrice', 0) or 0)
                last = float(raw_quote.get('last', 0) or 0)
                pre_mkt = float(raw_quote.get('preMarketPrice', 0) or raw_quote.get('pPrice', 0) or 0)
                close = float(raw_quote.get('close', 0) or 0)
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                if pre_mkt > 0:
                    return pre_mkt
                if last > 0:
                    return last
                if close > 0:
                    return close
        except asyncio.TimeoutError:
            return None
        except Exception:
            pass
        return None

    async def _try_schwab_rest_quote(self, symbol):
        if not self.schwab_broker:
            return None
        try:
            sb = self.schwab_broker
            result = await asyncio.wait_for(self._schwab_rest_inner(sb, symbol), timeout=5.0)
            return result
        except asyncio.TimeoutError:
            return None
        except Exception:
            pass
        return None

    async def _schwab_rest_inner(self, sb, symbol):
        if not await sb._ensure_valid_token():
            return None
        response = await sb._make_request(
            'GET',
            'https://api.schwabapi.com/marketdata/v1/quotes',
            params={'symbols': symbol, 'indicative': 'false',
                    'needExtendedHoursData': 'true', 'needPreviousClose': 'true'}
        )
        if response and response.status_code == 200:
            data = response.json()
            if symbol in data:
                quote = data[symbol].get('quote', {})
                bid = float(quote.get('bidPrice', 0) or 0)
                ask = float(quote.get('askPrice', 0) or 0)
                last = float(quote.get('lastPrice', 0) or 0)
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                elif last > 0:
                    return last
        return None

    async def _try_broker_get_quote(self, pos):
        broker_upper = (pos.broker or '').upper()
        broker_instance = None
        if 'ALPACA' in broker_upper:
            broker_instance = self.alpaca_broker
        elif 'TASTYTRADE' in broker_upper:
            broker_instance = self.tastytrade_broker
        elif 'ROBINHOOD' in broker_upper:
            broker_instance = self.robinhood_broker
        elif 'IBKR' in broker_upper:
            broker_instance = self.ibkr_broker
        elif 'TRADING212' in broker_upper or 'T212' in broker_upper:
            broker_instance = self.trading212_broker
        if not broker_instance or not hasattr(broker_instance, 'get_quote'):
            return None
        try:
            result = await asyncio.wait_for(
                broker_instance.get_quote(pos.symbol), timeout=5.0)
            if isinstance(result, (int, float)) and result > 0:
                return float(result)
        except asyncio.TimeoutError:
            return None
        except Exception:
            pass
        return None

    def _is_rest_repair_active(self, pos, hub_quote_age=None, hub_quote_ts=None):
        """Check if a REST-repaired price is protecting this position from hub overwrite.
        
        The guard is released early only if the hub tick is genuinely NEW —
        meaning its timestamp is newer than when the repair was created.
        A stale tick with age < 3s just means the subscription is recent,
        not that the market data changed.
        """
        import time as _rt
        key = self._pos_tracking_key(pos)
        repair = self._rest_repaired_prices.get(key)
        if not repair:
            return False
        if _rt.time() > repair['until']:
            del self._rest_repaired_prices[key]
            return False
        if hub_quote_ts is not None and hub_quote_ts > repair.get('created_at', 0):
            del self._rest_repaired_prices[key]
            return False
        return True

    def _update_prices_from_hub(self, positions: list):
        """Update position prices from streaming hubs if available.
        
        When streaming is active (Webull MQTT or Schwab WebSocket), position 
        prices from REST may be stale. This method updates current_price with 
        real-time streaming data from both hubs, providing zero-API-cost updates.
        
        STALENESS GUARD: Only overrides REST price if the streaming quote is
        fresher than _HUB_PRICE_MAX_AGE seconds (default 30s). For low-volume
        symbols where MQTT updates are infrequent, the REST position price
        (refreshed every 10s) is kept instead of a stale streaming quote.
        
        REST REPAIR GUARD: If _detect_and_fix_stuck_prices recently wrote a
        fresh REST price, hub overlay will NOT overwrite it for 10 seconds —
        unless the hub price materially differs (>0.5% from repaired price),
        indicating the stream has genuinely recovered.
        """
        webull_updated = 0
        schwab_updated = 0
        stale_skipped = 0
        _hub_updated_ids = set()
        
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            if hub.is_streaming():
                for pos in positions:
                    if pos.broker != 'Webull':
                        continue
                    if pos.asset == 'option':
                        price = None
                        for lk in [pos.raw_symbol, pos.symbol]:
                            if lk:
                                price = self._get_fresh_hub_price(hub, lk)
                                if price:
                                    break
                        if not price:
                            lk_check = pos.raw_symbol or pos.symbol
                            if lk_check and hub.get_quote_price(lk_check):
                                stale_skipped += 1
                            continue
                    else:
                        price = self._get_fresh_hub_price(hub, pos.symbol)
                        if not price:
                            if hub.get_quote_price(pos.symbol):
                                stale_skipped += 1
                            continue
                    if price and price > 0:
                        _hub_ts = self._get_hub_quote_ts(hub, pos.symbol)
                        _rk = self._pos_tracking_key(pos)
                        if self._is_rest_repair_active(pos, hub_quote_ts=_hub_ts):
                            repair = self._rest_repaired_prices[_rk]
                            if abs(price - repair['price']) > max(0.02, repair['price'] * 0.005):
                                pos.current_price = price
                                del self._rest_repaired_prices[_rk]
                                webull_updated += 1
                                _hub_updated_ids.add(id(pos))
                        else:
                            pos.current_price = price
                            webull_updated += 1
                            _hub_updated_ids.add(id(pos))
        except ImportError:
            pass
        except Exception as e:
            print(f"[RISK] ⚠️ Webull hub price update error: {e}")
        
        try:
            from src.services.schwab_data_hub import get_schwab_data_hub
            schwab_hub = get_schwab_data_hub()
            if schwab_hub.is_streaming():
                for pos in positions:
                    if 'SCHWAB' not in pos.broker.upper():
                        continue
                    if pos.asset == 'option':
                        lookup_sym = pos.raw_symbol if pos.raw_symbol else None
                        if not lookup_sym:
                            continue
                        price = self._get_fresh_hub_price(schwab_hub, lookup_sym)
                        if not price:
                            if schwab_hub.get_quote_price(lookup_sym):
                                stale_skipped += 1
                            continue
                    else:
                        price = self._get_fresh_hub_price(schwab_hub, pos.symbol)
                        if not price:
                            if schwab_hub.get_quote_price(pos.symbol):
                                stale_skipped += 1
                            continue
                    if price and price > 0:
                        _lookup = pos.raw_symbol if pos.asset == 'option' and pos.raw_symbol else pos.symbol
                        _hub_ts = self._get_hub_quote_ts(schwab_hub, _lookup)
                        _rk = self._pos_tracking_key(pos)
                        if self._is_rest_repair_active(pos, hub_quote_ts=_hub_ts):
                            repair = self._rest_repaired_prices[_rk]
                            if abs(price - repair['price']) > max(0.02, repair['price'] * 0.005):
                                pos.current_price = price
                                del self._rest_repaired_prices[_rk]
                                schwab_updated += 1
                                _hub_updated_ids.add(id(pos))
                        else:
                            pos.current_price = price
                            schwab_updated += 1
                            _hub_updated_ids.add(id(pos))
        except ImportError:
            pass
        except Exception as e:
            print(f"[RISK] ⚠️ Schwab hub price update error: {e}")
        
        ibkr_updated = 0
        try:
            from src.services.ibkr_data_hub import get_ibkr_data_hub
            ibkr_hub = get_ibkr_data_hub()
            if ibkr_hub.is_streaming():
                for pos in positions:
                    if 'IBKR' not in pos.broker.upper():
                        continue
                    if pos.asset == 'option':
                        lookup_sym = pos.raw_symbol if pos.raw_symbol else None
                        if not lookup_sym:
                            continue
                        price = self._get_fresh_hub_price(ibkr_hub, lookup_sym)
                        if not price:
                            if ibkr_hub.get_quote_price(lookup_sym):
                                stale_skipped += 1
                            continue
                    else:
                        price = self._get_fresh_hub_price(ibkr_hub, pos.symbol)
                        if not price:
                            if ibkr_hub.get_quote_price(pos.symbol):
                                stale_skipped += 1
                            continue
                    if price and price > 0:
                        _lookup = pos.raw_symbol if pos.asset == 'option' and pos.raw_symbol else pos.symbol
                        _hub_ts = self._get_hub_quote_ts(ibkr_hub, _lookup)
                        _rk = self._pos_tracking_key(pos)
                        if self._is_rest_repair_active(pos, hub_quote_ts=_hub_ts):
                            repair = self._rest_repaired_prices[_rk]
                            if abs(price - repair['price']) > max(0.02, repair['price'] * 0.005):
                                pos.current_price = price
                                del self._rest_repaired_prices[_rk]
                                ibkr_updated += 1
                                _hub_updated_ids.add(id(pos))
                        else:
                            pos.current_price = price
                            ibkr_updated += 1
                            _hub_updated_ids.add(id(pos))
        except ImportError:
            pass
        except Exception as e:
            print(f"[RISK] ⚠️ IBKR hub price update error: {e}")

        tastytrade_updated = 0
        try:
            import time as _tt_time
            from src.services.tastytrade_data_hub import get_tastytrade_data_hub
            tt_hub = get_tastytrade_data_hub()
            if tt_hub.is_streaming():
                _now = _tt_time.time()
                for pos in positions:
                    if 'TASTYTRADE' not in pos.broker.upper():
                        continue
                    if pos.asset == 'option':
                        lookup_sym = pos.raw_symbol if pos.raw_symbol else None
                        if not lookup_sym:
                            continue
                        price = self._get_fresh_hub_price(tt_hub, lookup_sym)
                        if not price:
                            if tt_hub.get_quote_price(lookup_sym):
                                stale_skipped += 1
                            continue
                    else:
                        price = self._get_fresh_hub_price(tt_hub, pos.symbol)
                        if not price:
                            if tt_hub.get_quote_price(pos.symbol):
                                stale_skipped += 1
                            continue
                    if price and price > 0:
                        _lookup = pos.raw_symbol if pos.asset == 'option' and pos.raw_symbol else pos.symbol
                        _tt_quote = tt_hub.get_quote(_lookup)
                        _hub_ts = _tt_quote.timestamp if _tt_quote else None
                        _rk = self._pos_tracking_key(pos)
                        if self._is_rest_repair_active(pos, hub_quote_ts=_hub_ts):
                            repair = self._rest_repaired_prices[_rk]
                            if abs(price - repair['price']) > max(0.02, repair['price'] * 0.005):
                                pos.current_price = price
                                del self._rest_repaired_prices[_rk]
                                tastytrade_updated += 1
                                _hub_updated_ids.add(id(pos))
                        else:
                            pos.current_price = price
                            tastytrade_updated += 1
                            _hub_updated_ids.add(id(pos))
        except ImportError:
            pass
        except Exception as e:
            print(f"[RISK] ⚠️ Tastytrade hub price update error: {e}")

        t212_updated = 0
        try:
            import time as _t212_time
            from src.services.trading212_data_hub import get_trading212_data_hub
            t212_hub = get_trading212_data_hub()
            if t212_hub and not t212_hub.is_stale:
                _now = _t212_time.time()
                for pos in positions:
                    if 'TRADING212' not in pos.broker.upper():
                        continue
                    if pos.asset == 'option':
                        continue
                    price = t212_hub.get_quote_price(pos.symbol)
                    if price and price > 0:
                        ts = t212_hub.get_quote_timestamp(pos.symbol)
                        if ts and (_now - ts) > self._HUB_PRICE_MAX_AGE:
                            continue
                        pos.current_price = price
                        t212_updated += 1
                        _hub_updated_ids.add(id(pos))
        except ImportError:
            pass
        except Exception as e:
            print(f"[RISK] ⚠️ Trading212 hub price update error: {e}")

        cross_updated = 0
        for pos in positions:
            if id(pos) in _hub_updated_ids:
                continue
            _broker_upper = pos.broker.upper()
            _is_opt = pos.asset == 'option'
            _cross_candidates = []
            if 'WEBULL' not in _broker_upper:
                try:
                    from src.services.webull_data_hub import get_webull_data_hub
                    wb_hub = get_webull_data_hub()
                    if wb_hub.is_streaming():
                        if _is_opt:
                            for _ok in self._get_option_hub_keys(pos, 'Webull'):
                                _p = self._get_fresh_hub_price(wb_hub, _ok)
                                if _p and _p > 0:
                                    _cross_candidates.append((_p, self._get_hub_quote_ts(wb_hub, _ok), 'Webull'))
                                    break
                        else:
                            _lk = self._normalize_symbol_for_hub(pos.symbol, 'Webull')
                            _p = self._get_fresh_hub_price(wb_hub, _lk)
                            if _p and _p > 0:
                                _cross_candidates.append((_p, self._get_hub_quote_ts(wb_hub, _lk), 'Webull'))
                except Exception:
                    pass
            if 'SCHWAB' not in _broker_upper:
                try:
                    from src.services.schwab_data_hub import get_schwab_data_hub
                    sc_hub = get_schwab_data_hub()
                    if sc_hub.is_streaming():
                        if _is_opt:
                            for _ok in self._get_option_hub_keys(pos, 'Schwab'):
                                _p = self._get_fresh_hub_price(sc_hub, _ok)
                                if _p and _p > 0:
                                    _cross_candidates.append((_p, self._get_hub_quote_ts(sc_hub, _ok), 'Schwab'))
                                    break
                        else:
                            _lk = self._normalize_symbol_for_hub(pos.symbol, 'Schwab')
                            _p = self._get_fresh_hub_price(sc_hub, _lk)
                            if _p and _p > 0:
                                _cross_candidates.append((_p, self._get_hub_quote_ts(sc_hub, _lk), 'Schwab'))
                except Exception:
                    pass
            if 'IBKR' not in _broker_upper:
                try:
                    from src.services.ibkr_data_hub import get_ibkr_data_hub
                    ib_hub = get_ibkr_data_hub()
                    if ib_hub.is_streaming():
                        if _is_opt:
                            for _ok in self._get_option_hub_keys(pos, 'IBKR'):
                                _p = self._get_fresh_hub_price(ib_hub, _ok)
                                if _p and _p > 0:
                                    _cross_candidates.append((_p, self._get_hub_quote_ts(ib_hub, _ok), 'IBKR'))
                                    break
                        else:
                            _lk = self._normalize_symbol_for_hub(pos.symbol, 'IBKR')
                            _p = self._get_fresh_hub_price(ib_hub, _lk)
                            if _p and _p > 0:
                                _cross_candidates.append((_p, self._get_hub_quote_ts(ib_hub, _lk), 'IBKR'))
                except Exception:
                    pass
            if 'TASTYTRADE' not in _broker_upper:
                try:
                    from src.services.tastytrade_data_hub import get_tastytrade_data_hub
                    tt_cx_hub = get_tastytrade_data_hub()
                    if tt_cx_hub.is_streaming():
                        if _is_opt:
                            for _ok in self._get_option_hub_keys(pos, 'Tastytrade'):
                                _p = self._get_fresh_hub_price(tt_cx_hub, _ok)
                                if _p and _p > 0:
                                    _tt_q = tt_cx_hub.get_quote(_ok)
                                    _tt_ts = _tt_q.timestamp if _tt_q else None
                                    _cross_candidates.append((_p, _tt_ts, 'Tastytrade'))
                                    break
                        else:
                            _p = self._get_fresh_hub_price(tt_cx_hub, pos.symbol)
                            if _p and _p > 0:
                                _tt_q = tt_cx_hub.get_quote(pos.symbol)
                                _tt_ts = _tt_q.timestamp if _tt_q else None
                                _cross_candidates.append((_p, _tt_ts, 'Tastytrade'))
                except Exception:
                    pass
            if not _is_opt and 'TRADING212' not in _broker_upper:
                try:
                    import time as _cx_time
                    from src.services.trading212_data_hub import get_trading212_data_hub
                    t212_hub = get_trading212_data_hub()
                    if t212_hub and not t212_hub.is_stale:
                        _cx_now = _cx_time.time()
                        _lk = self._normalize_symbol_for_hub(pos.symbol, 'T212')
                        t212_price = t212_hub.get_quote_price(_lk)
                        t212_ts = t212_hub.get_quote_timestamp(_lk)
                        if t212_price and t212_price > 0 and t212_ts and (_cx_now - t212_ts) < self._HUB_PRICE_MAX_AGE:
                            _cross_candidates.append((t212_price, t212_ts, 'T212'))
                except Exception:
                    pass
            _cross_applied = False
            _repair_key = self._pos_tracking_key(pos)
            for _cp, _ct, _cs in _cross_candidates:
                if self._is_rest_repair_active(pos, hub_quote_ts=_ct):
                    repair = self._rest_repaired_prices.get(_repair_key)
                    if repair and abs(_cp - repair['price']) > max(0.02, repair['price'] * 0.005):
                        pos.current_price = _cp
                        del self._rest_repaired_prices[_repair_key]
                        cross_updated += 1
                        _hub_updated_ids.add(id(pos))
                        _cross_applied = True
                        _cross_source = _cs
                        break
                else:
                    pos.current_price = _cp
                    cross_updated += 1
                    _hub_updated_ids.add(id(pos))
                    _cross_applied = True
                    _cross_source = _cs
                    break
            if _cross_applied:
                if not hasattr(self, '_cross_hub_logged'):
                    self._cross_hub_logged = set()
                _cross_log_key = self._pos_tracking_key(pos)
                if _cross_log_key not in self._cross_hub_logged:
                    self._cross_hub_logged.add(_cross_log_key)
                    _desc = pos.symbol
                    if _is_opt:
                        _desc = f"{pos.symbol} {pos.strike}{pos.direction} {pos.expiry}"
                    print(f"[RISK] 🔄 CROSS-HUB: {pos.broker} {_desc} price sourced from {_cross_source} streaming hub → ${pos.current_price:.4f}")

        if stale_skipped > 0:
            if not hasattr(self, '_stale_skip_count'):
                self._stale_skip_count = 0
            self._stale_skip_count += stale_skipped
            if self._stale_skip_count <= 3 or self._stale_skip_count % 60 == 0:
                print(f"[RISK] ⚠️ Skipped {stale_skipped} stale streaming quote(s) (>{self._HUB_PRICE_MAX_AGE}s old) — using REST price instead")

        total = webull_updated + schwab_updated + ibkr_updated + tastytrade_updated + t212_updated + cross_updated
        if total > 0 and not hasattr(self, '_hub_update_logged'):
            parts = []
            if webull_updated > 0:
                parts.append(f"Webull({webull_updated})")
            if schwab_updated > 0:
                parts.append(f"Schwab({schwab_updated})")
            if ibkr_updated > 0:
                parts.append(f"IBKR({ibkr_updated})")
            if tastytrade_updated > 0:
                parts.append(f"Tastytrade({tastytrade_updated})")
            if t212_updated > 0:
                parts.append(f"T212({t212_updated})")
            if cross_updated > 0:
                parts.append(f"CrossBroker({cross_updated})")
            print(f"[RISK] ✓ Streaming hub: updated {total} position prices [{', '.join(parts)}]")
            self._hub_update_logged = True

        try:
            from src.services.unified_price_hub import get_unified_price_hub
            uph = get_unified_price_hub()
            if uph._shadow_mode and uph._poll_running:
                for pos in positions:
                    if pos.current_price and pos.current_price > 0:
                        uph.shadow_compare(pos.symbol, pos.current_price, f"{pos.broker}_risk")
        except Exception:
            pass


    def _to_snapshot(self, pos: Dict) -> PositionSnapshot:
        """Convert raw position dict to PositionSnapshot."""
        strike = pos.get('strike')
        direction = pos.get('direction')
        expiry = pos.get('expiry')
        option_id = pos.get('option_id')
        broker = pos.get('broker', 'UNKNOWN')
        asset = pos.get('asset', 'stock')

        if asset == 'option' and broker == 'Webull' and (not strike or float(strike or 0) == 0.0 or not direction):
            if hasattr(self, '_webull_enrichment_cache'):
                lookup_keys = []
                if option_id:
                    lookup_keys.append(f"oid_{option_id}")
                ticker_id = pos.get('ticker_id', '')
                if ticker_id:
                    lookup_keys.append(f"tid_{ticker_id}")
                if not lookup_keys:
                    lookup_keys.append(f"sym_{pos.get('symbol', '')}_{expiry}_{direction or ''}")
                for lk in lookup_keys:
                    cached = self._webull_enrichment_cache.get(lk)
                    if cached:
                        if not strike or float(strike or 0) == 0.0:
                            strike = cached['strike']
                        if not direction:
                            direction = cached['direction']
                        if not expiry:
                            expiry = cached['expiry']
                        break

        raw_sym = pos.get('symbol', '')
        pos_symbol = normalize_index_symbol(raw_sym) if asset == 'option' else raw_sym

        return PositionSnapshot(
            symbol=pos_symbol,
            quantity=float(pos.get('quantity', 0)),
            avg_cost=float(pos.get('avg_cost', 0)),
            current_price=float(pos.get('current_price', 0)),
            asset=asset,
            broker=broker,
            strike=strike,
            expiry=expiry,
            direction=direction,
            raw_symbol=pos.get('raw_symbol'),
            option_id=option_id
        )
    
    def _enrich_position_from_trade(
        self, 
        position: 'PositionSnapshot', 
        trade_id: int, 
        old_pos_key: str,
        broker_position_keys: set
    ) -> Optional[tuple]:
        """Enrich a position snapshot with correct strike/direction/expiry from the DB trade.
        
        Called when fuzzy match found a trade_id but the position has bad metadata
        (e.g. strike=0.0, no direction — common with Webull index options like SPX).
        Returns (enriched_position, new_pos_key) or None if no enrichment needed/possible.
        """
        needs_enrichment = (
            position.asset == 'option' and 
            (not position.strike or position.strike == 0.0 or not position.direction or not position.expiry)
        )
        if not needs_enrichment or not self.db_adapter or not self.db_adapter._db:
            return None
            
        try:
            conn = self.db_adapter._db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT strike, expiry, call_put FROM trades WHERE id = ?
            ''', (trade_id,))
            row = cursor.fetchone()
            if not row:
                return None
                
            db_strike, db_expiry, db_call_put = row
            if not db_strike or db_strike == 0.0:
                return None
                
            position.strike = float(db_strike)
            if db_call_put:
                position.direction = self._normalize_call_put(db_call_put) or db_call_put.upper()
            if db_expiry and not position.expiry:
                position.expiry = db_expiry
                
            new_pos_key = position.position_key
            
            if old_pos_key != new_pos_key:
                broker_position_keys.discard(old_pos_key)
                broker_position_keys.add(new_pos_key)
                
                self.cache.rename_key(old_pos_key, new_pos_key, trade_id=trade_id)

                if hasattr(self, '_webull_enrichment_cache'):
                    enrich_keys = []
                    if position.option_id:
                        enrich_keys.append(f"oid_{position.option_id}")
                    enrichment_data = {
                        'strike': position.strike, 
                        'direction': position.direction, 
                        'expiry': position.expiry
                    }
                    for ek in enrich_keys:
                        self._webull_enrichment_cache[ek] = enrichment_data

                print(f"[RISK] ✓ DB enrichment: {old_pos_key} → {new_pos_key} "
                      f"(trade #{trade_id}: strike={db_strike}, {db_call_put}, expiry={db_expiry})")
                return (position, new_pos_key)
            
            return None
        except Exception as e:
            print(f"[RISK] ⚠️ DB enrichment failed for trade #{trade_id}: {e}")
            return None

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
            
            if channel_settings.ema_risk_enabled:
                ema_cs = getattr(cache, 'ema_last_cross_state', '')
                if ema_cs and ema_cs not in ('', 'unknown', 'seeding'):
                    enhanced_status += f" | [EMA ✓] {ema_cs}"
                else:
                    enhanced_status += f" | [EMA] seeding ({channel_settings.ema_timeframe_minutes}m/{channel_settings.ema_period}p)"
        
        if sl_price or target_price:
            print(f"[RISK] [{channel_name}] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | SL: ${sl_price or 'N/A'} | Target: ${target_price or 'N/A'} | Qty: {qty}{trailing_status}{enhanced_status}")
        elif channel_settings:
            sl_display = f"{channel_settings.stop_loss_pct}%"
            if cache and cache.manual_sl_price is not None:
                sl_display = f"${cache.manual_sl_price:.2f} [OVERRIDE]"
            elif cache and cache.manual_sl_pct is not None:
                sl_display = f"{cache.manual_sl_pct:.1f}% [OVERRIDE]"
            print(f"[RISK] [{channel_name}] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | Targets: {channel_settings.profit_target_1_pct}/"
                  f"{channel_settings.profit_target_2_pct}/{channel_settings.profit_target_3_pct}% | "
                  f"SL: {sl_display} | {trailing_display} | Qty: {qty}{trailing_status}{enhanced_status}")
        else:
            print(f"[RISK] [Manual Trade] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | Qty: {qty}{trailing_status}")
