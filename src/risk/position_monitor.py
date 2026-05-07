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
import inspect
import re
from typing import Optional, List, Dict, Any, Callable, Awaitable
from pathlib import Path


async def _await_if_needed(result):
    """Handle tastytrade SDK calls that may be sync or async depending on version."""
    if inspect.isawaitable(result):
        return await result
    return result

def _round_to_cboe_increment(price: float, is_sell: bool = False, is_stop_trigger: bool = False) -> float:
    import math
    if price <= 0:
        return 0.05
    if price < 3.00:
        increment = 0.05
    else:
        increment = 0.10
    ticks = round(price / increment, 8)
    if is_stop_trigger:
        if is_sell:
            rounded = math.ceil(ticks) * increment
        else:
            rounded = math.floor(ticks) * increment
    else:
        if is_sell:
            rounded = math.floor(ticks) * increment
        else:
            rounded = math.ceil(ticks) * increment
    rounded = round(rounded, 2)
    if rounded <= 0:
        rounded = increment
    return rounded

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
from .risk_engine import (
    evaluate_exit_actions, 
    TradeState, 
    RiskAction, 
    ActionType,
    DYNAMIC_SL_PROFILES,
    calculate_dynamic_sl
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
    
    _channels_risk_cache = None
    _channels_risk_cache_ts = 0

    def count_channels_with_risk(self) -> int:
        """Count channels with risk management explicitly enabled (cached 5s)."""
        import time as _t
        now = _t.monotonic()
        if self._channels_risk_cache is not None and (now - self._channels_risk_cache_ts) < 5:
            return self._channels_risk_cache
        if not self._db:
            return 0
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM channels 
                WHERE risk_management_enabled = 1
            ''')
            count = cursor.fetchone()[0]
            RiskDBAdapter._channels_risk_cache = count
            RiskDBAdapter._channels_risk_cache_ts = now
            return count
        except Exception as e:
            print(f"[RISK] Warning: Could not count channels with risk: {e}")
            return 0

    _open_trades_cache = None
    _open_trades_cache_ts = 0

    def count_open_trades(self, connected_brokers=None) -> int:
        """Count open BTO trades (cached 2s to avoid DB overhead every cycle).
        If connected_brokers is provided, only count trades on those brokers."""
        import time as _t
        now = _t.monotonic()
        _cache_key = frozenset(connected_brokers) if connected_brokers else None
        _cached = getattr(self, '_open_trades_cache_ext', None)
        if _cached and _cached[0] == _cache_key and (now - _cached[2]) < 2:
            return _cached[1]
        if not self._db:
            return 0
        try:
            conn = self._db.get_connection()
            cursor = conn.cursor()
            if connected_brokers:
                placeholders = ','.join(['?' for _ in connected_brokers])
                cursor.execute(
                    f"SELECT COUNT(*) FROM trades WHERE status = 'OPEN' AND direction = 'BTO' AND broker IN ({placeholders})",
                    list(connected_brokers)
                )
            else:
                cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN' AND direction = 'BTO'")
            count = cursor.fetchone()[0]
            self._open_trades_cache_ext = (_cache_key, count, now)
            RiskDBAdapter._open_trades_cache = count
            RiskDBAdapter._open_trades_cache_ts = now
            return count
        except Exception:
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
                       sl_order_type, escalation_only_mode,
                       ema_risk_enabled, ema_period, ema_timeframe_minutes, ema_buffer_pct,
                       ema_exit_enabled, ema_escalation_enabled, ema_extended_hours,
                       ema_use_underlying, ema_no_trend_candles,
                       trim_limit_offset, trim_limit_offset_mode, trim_limit_offset_pct,
                       sl_limit_offset,
                       pt1_trim_pct, pt2_trim_pct, pt3_trim_pct, pt4_trim_pct
                FROM signal_routing_mappings
                WHERE id = ?
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
            
            ema_risk_enabled = bool(row[28]) if len(row) > 28 and row[28] else False
            ema_period = row[29] if len(row) > 29 and row[29] is not None else 5
            ema_timeframe_minutes = row[30] if len(row) > 30 and row[30] is not None else 5
            ema_buffer_pct = row[31] if len(row) > 31 and row[31] is not None else 0.1
            ema_exit_enabled = bool(row[32]) if len(row) > 32 and row[32] is not None else True
            ema_escalation_enabled = bool(row[33]) if len(row) > 33 and row[33] is not None else True
            ema_extended_hours = bool(row[34]) if len(row) > 34 and row[34] else False
            ema_use_underlying = bool(row[35]) if len(row) > 35 and row[35] is not None else True
            ema_no_trend_candles = row[36] if len(row) > 36 and row[36] is not None else 3
            r_trim_limit_offset = row[37] if len(row) > 37 and row[37] is not None else 0.01
            r_trim_limit_offset_mode = row[38] if len(row) > 38 and row[38] else 'dollar'
            r_trim_limit_offset_pct = row[39] if len(row) > 39 and row[39] is not None else 2.0
            r_sl_limit_offset = row[40] if len(row) > 40 and row[40] is not None else 0.03
            r_pt1_trim_pct = row[41] if len(row) > 41 else None
            r_pt2_trim_pct = row[42] if len(row) > 42 else None
            r_pt3_trim_pct = row[43] if len(row) > 43 else None
            r_pt4_trim_pct = row[44] if len(row) > 44 else None
            
            exit_strategy = row[21] if len(row) > 21 and row[21] else 'risk'
            has_any_risk_config = (
                sl > 0 or pt1 > 0 or pt2 > 0 or pt3 > 0 or pt4 > 0 or 
                trail > 0 or enable_early_trailing or dynamic_sl_enabled or 
                giveback_enabled or ema_risk_enabled or escalation_only or
                exit_strategy != 'risk'
            )
            
            if not has_any_risk_config:
                return None
            
            _source_bracket_mode = 'both'
            _source_ch_id = str(row[2]) if row[2] else None
            if _source_ch_id:
                try:
                    cursor.execute('''
                        SELECT broker_bracket_mode FROM channels
                        WHERE discord_channel_id = ? OR CAST(id AS TEXT) = ? OR telegram_chat_id = ?
                        LIMIT 1
                    ''', (_source_ch_id, _source_ch_id, _source_ch_id))
                    _bbm_row = cursor.fetchone()
                    if _bbm_row and _bbm_row[0]:
                        _source_bracket_mode = _bbm_row[0]
                except Exception:
                    pass
            
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
                profit_target_trim_pct_1=r_pt1_trim_pct,
                profit_target_trim_pct_2=r_pt2_trim_pct,
                profit_target_trim_pct_3=r_pt3_trim_pct,
                profit_target_trim_pct_4=r_pt4_trim_pct,
                stop_loss_pct=sl,
                trailing_stop_pct=trail,
                trailing_activation_pct=trail_activation,
                leave_runner_enabled=leave_runner_enabled,
                leave_runner_pct=leave_runner_pct,
                trim_order_mode=trim_order_type,
                sl_order_mode=sl_order_type,
                trim_limit_offset=r_trim_limit_offset,
                trim_limit_offset_mode=r_trim_limit_offset_mode,
                trim_limit_offset_pct=r_trim_limit_offset_pct,
                sl_limit_offset=r_sl_limit_offset,
                exit_strategy_mode=exit_mode,
                enable_dynamic_sl=dynamic_sl_enabled,
                dynamic_sl_profile=sl_profile,
                enable_giveback_guard=giveback_enabled,
                giveback_allowed_pct=giveback_pct,
                enable_early_trailing=enable_early_trailing,
                early_trailing_activation_pct=early_trailing_activation_pct,
                early_trailing_step_pct=early_trailing_step_pct,
                escalation_only_mode=escalation_only,
                ema_risk_enabled=ema_risk_enabled,
                ema_period=ema_period,
                ema_timeframe_minutes=ema_timeframe_minutes,
                ema_buffer_pct=ema_buffer_pct,
                ema_exit_enabled=ema_exit_enabled,
                ema_escalation_enabled=ema_escalation_enabled,
                ema_extended_hours=ema_extended_hours,
                ema_use_underlying=ema_use_underlying,
                ema_no_trend_candles=ema_no_trend_candles,
                broker_bracket_mode=_source_bracket_mode,
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
                                   c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode,
                                   c.profit_target_trim_pct_1, c.profit_target_trim_pct_2,
                                   c.profit_target_trim_pct_3, c.profit_target_trim_pct_4,
                                   c.broker_bracket_mode
                            FROM trades t
                            LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id 
                                OR t.channel_id = CAST(c.id AS TEXT)
                                OR t.channel_id = c.telegram_chat_id)
                            WHERE t.symbol IN ({sym_placeholders}) AND t.asset_type = 'option' AND t.strike = ? AND t.expiry = ? AND t.call_put = ?
                            AND LOWER(t.broker) = LOWER(?)
                            AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                            AND COALESCE(LOWER(TRIM(t.source)), '') NOT IN ('sync', 'risk_auto_import')
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
                                   c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode,
                                   c.profit_target_trim_pct_1, c.profit_target_trim_pct_2,
                                   c.profit_target_trim_pct_3, c.profit_target_trim_pct_4,
                                   c.broker_bracket_mode
                            FROM trades t
                            LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id 
                                OR t.channel_id = CAST(c.id AS TEXT)
                                OR t.channel_id = c.telegram_chat_id)
                            WHERE t.symbol IN ({sym_placeholders}) AND t.asset_type = 'option' AND t.strike = ? AND t.expiry = ? AND t.call_put = ?
                            AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                            AND COALESCE(LOWER(TRIM(t.source)), '') NOT IN ('sync', 'risk_auto_import')
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
                               c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode,
                               c.profit_target_trim_pct_1, c.profit_target_trim_pct_2,
                               c.profit_target_trim_pct_3, c.profit_target_trim_pct_4,
                               c.broker_bracket_mode
                        FROM trades t
                        LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id 
                            OR t.channel_id = CAST(c.id AS TEXT)
                            OR t.channel_id = c.telegram_chat_id)
                        WHERE t.id = ?
                        AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                        AND COALESCE(LOWER(TRIM(t.source)), '') NOT IN ('sync', 'risk_auto_import')
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
                               c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode,
                               c.profit_target_trim_pct_1, c.profit_target_trim_pct_2,
                               c.profit_target_trim_pct_3, c.profit_target_trim_pct_4,
                               c.broker_bracket_mode
                        FROM trades t
                        LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id
                            OR t.channel_id = CAST(c.id AS TEXT)
                            OR t.channel_id = c.telegram_chat_id)
                        WHERE t.symbol IN ({sym_placeholders}) AND t.asset_type = 'stock'
                        AND LOWER(t.broker) = LOWER(?)
                        AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                        AND COALESCE(LOWER(TRIM(t.source)), '') NOT IN ('sync', 'risk_auto_import')
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
                               c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode,
                               c.profit_target_trim_pct_1, c.profit_target_trim_pct_2,
                               c.profit_target_trim_pct_3, c.profit_target_trim_pct_4,
                               c.broker_bracket_mode
                        FROM trades t
                        LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id
                            OR t.channel_id = CAST(c.id AS TEXT)
                            OR t.channel_id = c.telegram_chat_id)
                        WHERE t.symbol IN ({sym_placeholders}) AND t.asset_type = 'stock'
                        AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                        AND COALESCE(LOWER(TRIM(t.source)), '') NOT IN ('sync', 'risk_auto_import')
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
                               c.ema_use_underlying, c.ema_no_trend_candles, c.escalation_only_mode,
                               c.profit_target_trim_pct_1, c.profit_target_trim_pct_2,
                               c.profit_target_trim_pct_3, c.profit_target_trim_pct_4,
                               c.broker_bracket_mode
                        FROM trades t
                        LEFT JOIN channels c ON (t.channel_id = c.discord_channel_id
                            OR t.channel_id = CAST(c.id AS TEXT)
                            OR t.channel_id = c.telegram_chat_id)
                        WHERE t.id = ?
                        AND t.status IN ('OPEN', 'PENDING', 'PARTIAL') AND t.direction = 'BTO'
                        AND COALESCE(LOWER(TRIM(t.source)), '') NOT IN ('sync', 'risk_auto_import')
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
                channel_name_from_join = row[7] if len(row) > 7 else None
                risk_enabled = row[8] if len(row) > 8 else 0
                use_global = row[34] if (len(row) > 34 and row[34] is not None) else 1  # Default: use global (backwards compat, handles NULL from LEFT JOIN)
                
                if channel_name_from_join is None and row[0]:
                    try:
                        channel_id_val = str(row[0])
                        cursor.execute('''
                            SELECT risk_management_enabled, use_global_risk_settings, name,
                                   profit_target_1_pct, profit_target_2_pct, profit_target_3_pct,
                                   stop_loss_pct, trailing_stop_pct, trailing_activation_pct,
                                   leave_runner_enabled, leave_runner_pct, profit_target_4_pct,
                                   profit_target_qty_1, profit_target_qty_2, profit_target_qty_3, profit_target_qty_4,
                                   trim_order_mode, trim_limit_offset, exit_strategy_mode,
                                   enable_dynamic_sl, enable_giveback_guard, giveback_allowed_pct, dynamic_sl_profile,
                                   enable_early_trailing, early_trailing_activation_pct, early_trailing_step_pct,
                                   sl_order_mode, sl_limit_offset, trim_limit_offset_mode, trim_limit_offset_pct,
                                   ema_risk_enabled, ema_period, ema_timeframe_minutes, ema_buffer_pct,
                                   ema_exit_enabled, ema_escalation_enabled, ema_extended_hours,
                                   ema_use_underlying, ema_no_trend_candles, escalation_only_mode,
                                   profit_target_trim_pct_1, profit_target_trim_pct_2,
                                   profit_target_trim_pct_3, profit_target_trim_pct_4,
                                   broker_bracket_mode
                            FROM channels
                            WHERE discord_channel_id = ? OR CAST(id AS TEXT) = ? OR telegram_chat_id = ?
                            LIMIT 1
                        ''', (channel_id_val, channel_id_val, channel_id_val))
                        ch_row = cursor.fetchone()
                        if ch_row:
                            risk_enabled = ch_row[0] if ch_row[0] is not None else 0
                            use_global = ch_row[1] if ch_row[1] is not None else 1
                            channel_name_from_join = ch_row[2]
                            row = list(row)
                            row[7] = ch_row[2]   # name
                            row[8] = ch_row[0]   # risk_management_enabled
                            row[1] = ch_row[3]   # profit_target_1_pct
                            row[2] = ch_row[4]   # profit_target_2_pct
                            row[3] = ch_row[5]   # profit_target_3_pct
                            row[4] = ch_row[6]   # stop_loss_pct
                            row[5] = ch_row[7]   # trailing_stop_pct
                            row[6] = ch_row[8]   # trailing_activation_pct
                            row[9] = ch_row[9]   # leave_runner_enabled
                            row[10] = ch_row[10]  # leave_runner_pct
                            row[11] = ch_row[11]  # profit_target_4_pct
                            row[12] = ch_row[12]  # profit_target_qty_1
                            row[13] = ch_row[13]  # profit_target_qty_2
                            row[14] = ch_row[14]  # profit_target_qty_3
                            row[15] = ch_row[15]  # profit_target_qty_4
                            row[16] = ch_row[16]  # trim_order_mode
                            row[17] = ch_row[17]  # trim_limit_offset
                            row[18] = ch_row[18]  # exit_strategy_mode
                            row[19] = ch_row[19]  # enable_dynamic_sl
                            row[20] = ch_row[20]  # enable_giveback_guard
                            row[21] = ch_row[21]  # giveback_allowed_pct
                            row[22] = ch_row[22]  # dynamic_sl_profile
                            row[24] = ch_row[23]  # enable_early_trailing
                            row[25] = ch_row[24]  # early_trailing_activation_pct
                            row[26] = ch_row[25]  # early_trailing_step_pct
                            row[30] = ch_row[26]  # sl_order_mode
                            row[31] = ch_row[27]  # sl_limit_offset
                            row[32] = ch_row[28]  # trim_limit_offset_mode
                            row[33] = ch_row[29]  # trim_limit_offset_pct
                            row[34] = ch_row[1]   # use_global_risk_settings
                            if len(row) > 35: row[35] = ch_row[30]  # ema_risk_enabled
                            if len(row) > 36: row[36] = ch_row[31]  # ema_period
                            if len(row) > 37: row[37] = ch_row[32]  # ema_timeframe_minutes
                            if len(row) > 38: row[38] = ch_row[33]  # ema_buffer_pct
                            if len(row) > 39: row[39] = ch_row[34]  # ema_exit_enabled
                            if len(row) > 40: row[40] = ch_row[35]  # ema_escalation_enabled
                            if len(row) > 41: row[41] = ch_row[36]  # ema_extended_hours
                            if len(row) > 42: row[42] = ch_row[37]  # ema_use_underlying
                            if len(row) > 43: row[43] = ch_row[38]  # ema_no_trend_candles
                            if len(row) > 44: row[44] = ch_row[39]  # escalation_only_mode
                            while len(row) < 50:
                                row.append(None)
                            row[45] = ch_row[40]  # profit_target_trim_pct_1
                            row[46] = ch_row[41]  # profit_target_trim_pct_2
                            row[47] = ch_row[42]  # profit_target_trim_pct_3
                            row[48] = ch_row[43]  # profit_target_trim_pct_4
                            row[49] = ch_row[44]  # broker_bracket_mode
                            print(f"[RISK] ✓ Channel settings recovered via direct lookup for '{channel_name_from_join}' (LEFT JOIN fallback)")
                    except Exception as e:
                        print(f"[RISK] ⚠️ Direct channel lookup fallback failed: {e}")
                
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
                                broker_bracket_mode=row[49] if len(row) > 49 and row[49] else 'none',
                            )
                    ch_sl = row[4] or 0
                    ch_pt1 = row[1] or 0
                    if ch_sl > 0 or ch_pt1 > 0:
                        channel_name = row[7] or 'Unknown'
                        channel_exit_mode = row[18] if len(row) > 18 and row[18] else 'hybrid'
                        print(f"[RISK] ✓ Using channel SL/PT for bracket seeding (global risk OFF, use_global=ON, "
                              f"SL={ch_sl}%, PT1={ch_pt1}%, exit_mode={channel_exit_mode})")
                        return ChannelRiskSettings(
                            channel_id=str(row[0]),
                            channel_name=channel_name,
                            profit_target_1_pct=ch_pt1,
                            profit_target_2_pct=row[2] or 0,
                            profit_target_3_pct=row[3] or 0,
                            profit_target_4_pct=row[11] or 0,
                            profit_target_qty_1=row[12] if len(row) > 12 else None,
                            profit_target_qty_2=row[13] if len(row) > 13 else None,
                            profit_target_qty_3=row[14] if len(row) > 14 else None,
                            profit_target_qty_4=row[15] if len(row) > 15 else None,
                            profit_target_trim_pct_1=row[45] if len(row) > 45 else None,
                            profit_target_trim_pct_2=row[46] if len(row) > 46 else None,
                            profit_target_trim_pct_3=row[47] if len(row) > 47 else None,
                            profit_target_trim_pct_4=row[48] if len(row) > 48 else None,
                            stop_loss_pct=ch_sl,
                            trailing_stop_pct=row[5] or 0,
                            trailing_activation_pct=row[6] or 15.0,
                            exit_strategy_mode=channel_exit_mode,
                            leave_runner_enabled=bool(row[9]) if len(row) > 9 and row[9] else False,
                            leave_runner_pct=row[10] if len(row) > 10 and row[10] else 25.0,
                            trim_order_mode=row[16] if len(row) > 16 and row[16] else 'market',
                            trim_limit_offset=row[17] if len(row) > 17 and row[17] is not None else 0.01,
                            trim_limit_offset_mode=row[32] if len(row) > 32 and row[32] else 'dollar',
                            trim_limit_offset_pct=row[33] if len(row) > 33 and row[33] is not None else 2.0,
                            sl_order_mode=row[30] if len(row) > 30 and row[30] else 'limit',
                            sl_limit_offset=row[31] if len(row) > 31 and row[31] is not None else 0.03,
                            enable_dynamic_sl=bool(row[19]) if len(row) > 19 and row[19] else False,
                            enable_giveback_guard=bool(row[20]) if len(row) > 20 and row[20] else False,
                            giveback_allowed_pct=row[21] if len(row) > 21 and row[21] is not None else 30.0,
                            dynamic_sl_profile=row[22] if len(row) > 22 and row[22] else 'standard',
                            enable_early_trailing=bool(row[24]) if len(row) > 24 and row[24] else False,
                            early_trailing_activation_pct=row[25] if len(row) > 25 and row[25] is not None else 5.0,
                            early_trailing_step_pct=row[26] if len(row) > 26 and row[26] is not None else 3.0,
                            ema_risk_enabled=bool(row[35]) if len(row) > 35 and row[35] else False,
                            ema_period=row[36] if len(row) > 36 and row[36] is not None else 5,
                            ema_timeframe_minutes=row[37] if len(row) > 37 and row[37] is not None else 5,
                            ema_buffer_pct=row[38] if len(row) > 38 and row[38] is not None else 0.1,
                            ema_exit_enabled=bool(row[39]) if len(row) > 39 and row[39] is not None else True,
                            ema_escalation_enabled=bool(row[40]) if len(row) > 40 and row[40] is not None else True,
                            ema_extended_hours=bool(row[41]) if len(row) > 41 and row[41] else False,
                            ema_use_underlying=bool(row[42]) if len(row) > 42 and row[42] is not None else True,
                            ema_no_trend_candles=row[43] if len(row) > 43 and row[43] is not None else 3,
                            escalation_only_mode=bool(row[44]) if len(row) > 44 and row[44] else False,
                            broker_bracket_mode=row[49] if len(row) > 49 and row[49] else 'none',
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
                
                trim_pct1 = row[45] if len(row) > 45 else None
                trim_pct2 = row[46] if len(row) > 46 else None
                trim_pct3 = row[47] if len(row) > 47 else None
                trim_pct4 = row[48] if len(row) > 48 else None
                
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
                    profit_target_trim_pct_1=trim_pct1,
                    profit_target_trim_pct_2=trim_pct2,
                    profit_target_trim_pct_3=trim_pct3,
                    profit_target_trim_pct_4=trim_pct4,
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
                    escalation_only_mode=escalation_only_mode,
                    broker_bracket_mode=row[49] if len(row) > 49 and row[49] else 'none',
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
                                AND status IN ('OPEN', 'PENDING', 'PARTIAL') AND direction = 'BTO'
                                AND LOWER(broker) = LOWER(?)
                                ORDER BY id DESC LIMIT 1
                            ''', (sym_try, strike, exp_try, cp_normalized, broker))
                        else:
                            cursor.execute('''
                                SELECT id FROM trades
                                WHERE symbol = ? AND asset_type = 'option'
                                AND strike = ? AND expiry = ?
                                AND status IN ('OPEN', 'PENDING', 'PARTIAL') AND direction = 'BTO'
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
                        AND strike = ? AND status IN ('OPEN', 'PENDING', 'PARTIAL') AND direction = 'BTO'
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
                                AND status IN ('OPEN', 'PENDING', 'PARTIAL') AND direction = 'BTO'
                                AND LOWER(broker) = LOWER(?) AND expiry = ? AND call_put = ?
                                ORDER BY id DESC
                            ''', (sym_try, broker, exp_try, cp_normalized))
                        elif exp_try:
                            cursor.execute('''
                                SELECT id FROM trades
                                WHERE symbol = ? AND asset_type = 'option'
                                AND status IN ('OPEN', 'PENDING', 'PARTIAL') AND direction = 'BTO'
                                AND LOWER(broker) = LOWER(?) AND expiry = ?
                                ORDER BY id DESC
                            ''', (sym_try, broker, exp_try))
                        else:
                            cursor.execute('''
                                SELECT id FROM trades
                                WHERE symbol = ? AND asset_type = 'option'
                                AND status IN ('OPEN', 'PENDING', 'PARTIAL') AND direction = 'BTO'
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
                        SELECT id, channel_id FROM trades
                        WHERE symbol = ? AND asset_type = 'stock'
                        AND status IN ('OPEN', 'PENDING', 'PARTIAL') AND direction = 'BTO'
                        AND LOWER(broker) = LOWER(?)
                        ORDER BY id DESC LIMIT 5
                    ''', (sym_try, broker))
                    rows = cursor.fetchall()
                    if len(rows) == 1:
                        return rows[0][0]
                    elif len(rows) > 1:
                        unique_channels = set(r[1] for r in rows if r[1])
                        if len(unique_channels) <= 1:
                            return rows[0][0]
                        print(f"[RISK] 🛡️ AMBIGUITY GUARD: {len(rows)} stock trades for {sym_try} on {broker} "
                              f"across {len(unique_channels)} channels — returning newest to avoid cross-channel risk")
                        return rows[0][0]
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
            
            inherited_channel_id = None
            try:
                from gui_app.database import get_trades
                open_trades = get_trades(status='OPEN', limit=500)
                pending_trades = get_trades(status='PENDING', limit=500)
                for ot in (open_trades + pending_trades):
                    if ((ot.get('symbol') or '').upper() == position.symbol.upper() and
                        (ot.get('broker') or '').upper() == position.broker.upper() and
                        ot.get('channel_id')):
                        _ot_source = (ot.get('source') or '').strip().lower()
                        if _ot_source not in ('discord', 'signal', 'sync_routing'):
                            continue
                        if position.asset == 'option':
                            _ot_strike = str(ot.get('strike') or '').rstrip('0').rstrip('.')
                            _pos_strike = str(position.strike or '').rstrip('0').rstrip('.')
                            _ot_cp = (ot.get('call_put') or '').upper()[:1]
                            _pos_cp = (call_put or '').upper()[:1]
                            if (_ot_strike == _pos_strike and
                                str(ot.get('expiry') or '') == str(position.expiry or '') and
                                _ot_cp == _pos_cp):
                                inherited_channel_id = ot['channel_id']
                                print(f"[RISK] ✓ Inherited channel_id={inherited_channel_id} from "
                                      f"existing trade #{ot.get('id')} (source='{_ot_source}') for {position.symbol}")
                                break
                        else:
                            inherited_channel_id = ot['channel_id']
                            print(f"[RISK] ✓ Inherited channel_id={inherited_channel_id} from "
                                  f"existing trade #{ot.get('id')} (source='{_ot_source}') for {position.symbol}")
                            break
                if not inherited_channel_id:
                    recent_closed = get_trades(status='CLOSED', limit=50)
                    for rc in recent_closed:
                        if ((rc.get('symbol') or '').upper() == position.symbol.upper() and
                            (rc.get('broker') or '').upper() == position.broker.upper() and
                            rc.get('channel_id')):
                            _rc_source = (rc.get('source') or '').strip().lower()
                            if _rc_source not in ('discord', 'signal', 'sync_routing'):
                                continue
                            if position.asset == 'option':
                                _rc_strike = str(rc.get('strike') or '').rstrip('0').rstrip('.')
                                _rc_cp = (rc.get('call_put') or '').upper()[:1]
                                if (_rc_strike != _pos_strike or
                                    str(rc.get('expiry') or '') != str(position.expiry or '') or
                                    _rc_cp != _pos_cp):
                                    continue
                            closed_at = rc.get('closed_at')
                            if closed_at:
                                try:
                                    closed_time = datetime.fromisoformat(str(closed_at).replace('Z', '+00:00'))
                                    if hasattr(closed_time, 'timestamp'):
                                        elapsed = (datetime.now() - closed_time.replace(tzinfo=None)).total_seconds()
                                    else:
                                        elapsed = 0
                                    if 0 <= elapsed < 3600:
                                        inherited_channel_id = rc['channel_id']
                                        print(f"[RISK] ✓ Inherited channel_id={inherited_channel_id} from "
                                              f"recently-closed trade #{rc.get('id')} (source='{_rc_source}') for {position.symbol}")
                                        break
                                except Exception:
                                    pass
            except Exception:
                pass

            if not inherited_channel_id:
                print(f"[RISK] 🛡️ AUTO-IMPORT {position.symbol} on {position.broker}: "
                      f"no trusted signal trade found — importing as MANUAL trade (no channel risk)")

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
                'channel_id': inherited_channel_id,
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
    
    DEFAULT_MONITORING_INTERVAL = 0.2  # seconds - sub-second risk evaluation via streaming cache
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
        
        self._connected_broker_names_cache = None
        self._connected_broker_names_ts = 0
        
        self._stuck_price_tracker = {}
        self._STUCK_PRICE_THRESHOLD = 2
        self._rest_repaired_prices = {}
        self._rest_repair_cycle_keys = {}
        self._STALENESS_EXIT_BLOCK_THRESHOLD = 5
        self._rest_confirmed_this_cycle = {}
        self._rest_validated_same = {}
        self._partial_exit_in_flight = {}
        
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
        self._interval_extremes = {}
        self._interval_extremes_lock = _threading.Lock()

        self._broker_ops_queues = {}
        self._broker_ops_workers = {}
        self._broker_ops_pending = {}

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
                with open(self._PERMANENT_FAILURES_FILE, 'r', encoding='utf-8') as f:
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
            with open(self._PERMANENT_FAILURES_FILE, 'w', encoding='utf-8') as f:
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
            q = data.get('quote')
            if not symbol:
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
                self._dirty_symbols[symbol] = tick_ts
            tick_price = 0.0
            if q:
                if hasattr(q, 'last') and q.last and q.last > 0:
                    tick_price = float(q.last)
                elif hasattr(q, 'mark') and q.mark and q.mark > 0:
                    tick_price = float(q.mark)
                elif isinstance(q, dict):
                    tick_price = float(q.get('last', 0) or q.get('mark', 0) or q.get('price', 0) or 0)
            if not tick_price:
                tick_price = float(data.get('price', 0) or data.get('last', 0) or 0)
            if tick_price > 0:
                with self._interval_extremes_lock:
                    ext = self._interval_extremes.get(symbol)
                    if ext is None:
                        self._interval_extremes[symbol] = {'high': tick_price, 'low': tick_price}
                    else:
                        if tick_price > ext['high']:
                            ext['high'] = tick_price
                        if tick_price < ext['low']:
                            ext['low'] = tick_price
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

            with self._interval_extremes_lock:
                interval_snapshot = dict(self._interval_extremes)
                self._interval_extremes.clear()

            dirty_symbol_names = set(dirty.keys())
            earliest_tick = min(dirty.values())

            positions = self._last_positions_snapshot
            if not positions:
                return

            for pos in positions:
                ext = None
                if pos.asset == 'option':
                    if hasattr(pos, 'raw_symbol') and pos.raw_symbol:
                        ext = interval_snapshot.get(pos.raw_symbol.upper())
                else:
                    sym = pos.symbol.upper()
                    ext = interval_snapshot.get(sym)
                    if not ext and hasattr(pos, 'raw_symbol') and pos.raw_symbol:
                        ext = interval_snapshot.get(pos.raw_symbol.upper())
                if ext:
                    pos._interval_high = ext['high']
                    pos._interval_low = ext['low']

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
            if tick_to_eval_ms > getattr(self, '_tick_eval_max_latency_ms', 0):
                self._tick_eval_max_latency_ms = tick_to_eval_ms

            _should_log_tick = (
                self._tick_eval_count <= 5
                or self._tick_eval_count % 100 == 0
                or tick_to_eval_ms > 200
                or eval_elapsed_ms > 100
            )
            if _should_log_tick:
                avg_latency = self._tick_eval_total_latency_ms / self._tick_eval_count
                _max_lat = getattr(self, '_tick_eval_max_latency_ms', 0)
                print(f"[RISK] ⚡ Tick eval #{self._tick_eval_count}: {evaluated} pos in {eval_elapsed_ms:.0f}ms | "
                      f"tick→eval: {tick_to_eval_ms:.0f}ms | avg: {avg_latency:.0f}ms | max: {_max_lat:.0f}ms | "
                      f"dirty: {', '.join(sorted(dirty_symbol_names)[:3])}")

    async def start_monitoring(self) -> None:
        """Start the position monitoring loop with enable gate and standby support."""
        cached_count = self.cache.load()
        if cached_count > 0:
            print(f"[RISK] Loaded {cached_count} cached positions")
        
        risk_restored = self.cache.restore_full_risk_state_from_db()
        if risk_restored > 0:
            print(f"[RISK] ✓ Restored full risk state (tier hits, dynamic SL, giveback) for {risk_restored} positions")
        
        trade_mappings = self.cache.populate_trade_id_mappings()
        if trade_mappings > 0:
            print(f"[RISK] ✓ Pre-loaded {trade_mappings} trade→position mappings at startup")
        
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
                    if not hasattr(self, '_cycle_max_ms'):
                        self._cycle_max_ms = 0
                    if _cycle_elapsed_ms > self._cycle_max_ms:
                        self._cycle_max_ms = _cycle_elapsed_ms
                    _should_log_timing = (
                        self._cycle_timing_log_counter <= 5
                        or self._cycle_timing_log_counter % 50 == 0
                        or _cycle_elapsed_ms > 500
                    )
                    if _should_log_timing:
                        _detail = getattr(self, '_last_cycle_timing_detail', '')
                        _slow = " ⚠️ SLOW" if _cycle_elapsed_ms > 1000 else ""
                        _ticks = getattr(self, '_tick_eval_count', 0)
                        print(f"[RISK] ⏱ Cycle #{self._cycle_timing_log_counter}: {_cycle_elapsed_ms:.0f}ms{_detail} | ticks={_ticks} max_cycle={self._cycle_max_ms:.0f}ms{_slow}")
                    interval = self._get_adaptive_interval()
                    _sleep_start = _cycle_t.monotonic()
                    _order_event_woke = False
                    while True:
                        _remaining = interval - (_cycle_t.monotonic() - _sleep_start)
                        if _remaining <= 0:
                            break
                        _has_reason = getattr(self, '_has_open_positions_or_watches_cache', True) or self._has_active_fill_watches()
                        try:
                            from src.services.webull_data_hub import get_webull_data_hub
                            if get_webull_data_hub().check_risk_eval_requested():
                                if _has_reason:
                                    print("[RISK] ⚡ Early wake: order event from Webull stream")
                                    self._force_rest_refresh = True
                                    _order_event_woke = True
                                    break
                        except Exception:
                            pass
                        try:
                            from src.services.schwab_data_hub import get_schwab_data_hub
                            if get_schwab_data_hub().check_risk_eval_requested():
                                if _has_reason:
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
                                if _has_reason:
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
                if self._heartbeat_counter >= 150:
                    self._heartbeat_counter = 0
                    cache_count = len(self.cache.get_all_risk_states()) if self.cache else 0
                    _tc = getattr(self, '_tick_eval_count', 0)
                    _cc = getattr(self, '_cycle_timing_log_counter', 0)
                    _max_c = getattr(self, '_cycle_max_ms', 0)
                    _max_t = getattr(self, '_tick_eval_max_latency_ms', 0)
                    _avg_t = (self._tick_eval_total_latency_ms / _tc) if _tc > 0 else 0
                    _stream_status = "live" if not self._standby_mode else "standby"
                    try:
                        from src.services.schwab_data_hub import get_schwab_data_hub
                        _s_hub = get_schwab_data_hub()
                        if _s_hub.is_streaming():
                            _s_age = self._get_hub_quote_age(_s_hub, 'SPY')
                            _stream_status = f"schwab-stream(age={_s_age:.0f}s)" if _s_age is not None else "schwab-stream(no-quote)"
                    except Exception:
                        pass
                    print(f"[RISK] ♥ Heartbeat: cycles={_cc} ticks={_tc} | cycle_max={_max_c:.0f}ms tick_avg={_avg_t:.0f}ms tick_max={_max_t:.0f}ms | "
                          f"cache={cache_count} stream={_stream_status}")
                    
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
    
    def _get_connected_broker_names(self):
        """Return set of broker name strings for connected brokers (cached 10s)."""
        import time as _cbn_t
        _now = _cbn_t.monotonic()
        if self._connected_broker_names_cache is not None and (_now - self._connected_broker_names_ts) < 10:
            return self._connected_broker_names_cache
        names = set()
        if self._webull_broker and getattr(self._webull_broker, 'connected', False):
            names.add('Webull')
            names.add('WEBULL')
        if self.schwab_broker and (getattr(self.schwab_broker, 'connected', False) or getattr(self.schwab_broker, 'is_authenticated', lambda: False)()):
            names.add('SCHWAB')
            names.add('Schwab')
        if self.tastytrade_broker and getattr(self.tastytrade_broker, 'connected', False):
            names.add('TASTYTRADE_LIVE')
            names.add('TASTYTRADE')
        if self.alpaca_broker and getattr(self.alpaca_broker, 'connected', False):
            names.add('ALPACA_PAPER')
            names.add('ALPACA_LIVE')
        if self.robinhood_broker and (getattr(self.robinhood_broker, 'connected', False) or getattr(self.robinhood_broker, '_logged_in', False)):
            names.add('ROBINHOOD')
        if self.ibkr_broker and getattr(self.ibkr_broker, 'connected', False):
            names.add('IBKR_LIVE')
            names.add('IBKR_PAPER')
        self._connected_broker_names_cache = names
        self._connected_broker_names_ts = _now
        return names

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
            import time as _int_t
            _int_now = _int_t.monotonic()
            _cached = getattr(self, '_adaptive_interval_cache', None)
            if _cached and (_int_now - _cached[1]) < 5:
                return _cached[0]
            from gui_app.database import get_global_risk_settings
            settings = get_global_risk_settings()
            custom_interval = settings.get('risk_check_interval_seconds')
            if custom_interval is not None:
                interval = float(custom_interval)
                if 0.2 <= interval <= 60:
                    self._adaptive_interval_cache = (interval, _int_now)
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
        
        if not hasattr(self, '_last_trade_mapping_refresh'):
            self._last_trade_mapping_refresh = 0
        import time as _tmr_time
        _tmr_now = _tmr_time.time()
        if (_tmr_now - self._last_trade_mapping_refresh) > 30:
            self._last_trade_mapping_refresh = _tmr_now
            try:
                _new_mappings = self.cache.populate_trade_id_mappings()
                if _new_mappings > 0:
                    print(f"[RISK] ✓ Refreshed trade mappings: {_new_mappings} new mapping(s)")
            except Exception:
                pass
        
        check_and_process_invalidation_request()
        
        risk_settings = self._get_risk_settings()
        
        if not risk_settings.enabled:
            channel_count = self.db_adapter.count_channels_with_risk()
            if channel_count == 0:
                return
            else:
                if not hasattr(self, '_per_channel_risk_log_ts'):
                    self._per_channel_risk_log_ts = 0
                import time as _pcrl_t
                _pcrl_now = _pcrl_t.monotonic()
                if (_pcrl_now - self._per_channel_risk_log_ts) > 30:
                    print(f"[RISK] Per-channel risk ACTIVE for {channel_count} channel(s)")
                    self._per_channel_risk_log_ts = _pcrl_now
        
        import time as _mc_time
        _mc_t0 = _mc_time.monotonic()
        _now = _mc_time.time()
        _last_refresh = getattr(self, '_last_periodic_webull_rest_ts', 0)

        _streaming_live = False
        try:
            from src.services.webull_data_hub import get_webull_data_hub as _check_hub
            _streaming_live = _check_hub().is_streaming()
        except Exception:
            pass
        if not _streaming_live:
            try:
                from src.services.schwab_data_hub import get_schwab_data_hub as _check_schwab
                _streaming_live = _check_schwab().is_streaming()
            except Exception:
                pass
        if not _streaming_live:
            try:
                from src.services.ibkr_data_hub import get_ibkr_data_hub as _check_ibkr
                _streaming_live = _check_ibkr().is_streaming()
            except Exception:
                pass
        if not _streaming_live:
            try:
                from src.services.tastytrade_data_hub import get_tastytrade_data_hub as _check_tt
                _streaming_live = _check_tt().is_streaming()
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

        _has_open_positions_or_watches = _fill_watch_active or bool(getattr(self, '_last_positions_snapshot', None))
        if not _has_open_positions_or_watches:
            try:
                _connected = self._get_connected_broker_names()
                _open_count = self.db_adapter.count_open_trades(connected_brokers=_connected) if _connected else self.db_adapter.count_open_trades()
            except Exception:
                _open_count = 1
            self._last_db_open_count = _open_count
            _has_open_positions_or_watches = _open_count > 0
        self._has_open_positions_or_watches_cache = _has_open_positions_or_watches

        _pos_refresh_interval = self._POSITION_REST_REFRESH_INTERVAL if _streaming_live else self._PERIODIC_REST_FALLBACK_INTERVAL

        if (_now - _last_refresh) > _pos_refresh_interval:
            if _has_open_positions_or_watches:
                self._force_webull_rest_refresh = True
            self._last_periodic_webull_rest_ts = _now

        _mc_t1 = _mc_time.monotonic()

        if _streaming_live:
            if not getattr(self, '_streaming_mode_logged', False):
                print(f"[RISK] ✓ Streaming live — quotes via MQTT, position refresh every {self._POSITION_REST_REFRESH_INTERVAL}s")
                self._streaming_mode_logged = True
            self._rest_fallback_logged = False
        else:
            if not getattr(self, '_rest_fallback_logged', False) and _has_open_positions_or_watches:
                print(f"[RISK] ⚠️ Streaming dead — REST fallback active (every {self._PERIODIC_REST_FALLBACK_INTERVAL}s)")
                self._rest_fallback_logged = True
            self._streaming_mode_logged = False
        
        _mc_t2 = _mc_time.monotonic()
        try:
            positions = await self._fetch_all_positions()
        except Exception as e:
            print(f"[RISK] ⚠️ Error fetching positions: {e}")
            import traceback
            traceback.print_exc()
            positions = []
        _mc_t3 = _mc_time.monotonic()
        
        if not positions:
            if not hasattr(self, '_empty_pos_logged') or not self._empty_pos_logged:
                print("[RISK] No open positions found across brokers — monitoring idle")
                self._empty_pos_logged = True
            self._last_positions_snapshot = []
            self._update_monitored_symbols([])
            self._rest_validated_same.clear()
            self._rest_confirmed_this_cycle.clear()
            self._partial_exit_in_flight.clear()
            _fetch_ms = (_mc_t3 - _mc_t2) * 1000
            _setup_ms = (_mc_t1 - _mc_t0) * 1000
            self._last_cycle_timing_detail = f" [setup={_setup_ms:.0f}ms fetch={_fetch_ms:.0f}ms pos=0]"
            return
        self._empty_pos_logged = False
        
        if _fill_watch_active:
            self._check_fill_watch_detected(positions)

        self._rest_repair_cycle_keys.clear()
        self._rest_confirmed_this_cycle.clear()
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
                    if not hasattr(self, '_removal_debounce'):
                        self._removal_debounce = {}
                    self._removal_debounce.pop(nk, None)
            
            if not hasattr(self, '_removal_debounce'):
                self._removal_debounce = {}
            if real_removed_keys:
                import time as _dbt
                _db_now = _dbt.time()
                for rk in real_removed_keys:
                    if rk not in self._removal_debounce:
                        self._removal_debounce[rk] = _db_now
                    elif (_db_now - self._removal_debounce[rk]) >= 5.0:
                        print(f"[RISK] 📤 Position closed externally: {rk}")
                        self._removal_debounce.pop(rk, None)
                canonical_keys = canonical_keys | {rk for rk in real_removed_keys if rk in self._removal_debounce}
            _stale_debounce = [k for k in self._removal_debounce if k not in (real_removed_keys or set()) and k not in canonical_keys]
            for sk in _stale_debounce:
                self._removal_debounce.pop(sk, None)
            
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
        if not hasattr(self, '_zero_position_cleanup_count'):
            self._zero_position_cleanup_count = 0
        self._stale_cleanup_counter += 1
        if self._stale_cleanup_counter >= 20:
            self._stale_cleanup_counter = 0
            if broker_position_keys:
                self._zero_position_cleanup_count = 0
                stale_count = self.cache.cleanup_stale(broker_position_keys)
                if stale_count > 0:
                    print(f"[RISK] 🧹 Periodic cleanup: removed {stale_count} stale cache entries")
                if hasattr(self, '_auto_imported_keys'):
                    stale_imports = self._auto_imported_keys - broker_position_keys
                    if stale_imports:
                        self._auto_imported_keys -= stale_imports
                if hasattr(self, '_pending_trade_match_keys'):
                    stale_pending = self._pending_trade_match_keys - broker_position_keys
                    if stale_pending:
                        self._pending_trade_match_keys -= stale_pending
                if hasattr(self, '_skipped_external_logged'):
                    stale_skipped = self._skipped_external_logged - broker_position_keys
                    if stale_skipped:
                        self._skipped_external_logged -= stale_skipped
            elif len(self.cache) > 0:
                self._zero_position_cleanup_count += 1
                if self._zero_position_cleanup_count >= 3:
                    _safe_to_clean = True
                    try:
                        from src.risk.exit_lease_manager import get_exit_lease_manager
                        lease_mgr = get_exit_lease_manager()
                        has_active_lease = any(lease_mgr.is_active(k) for k in self.cache.get_all_keys())
                        if has_active_lease:
                            _safe_to_clean = False
                            print(f"[RISK] ⏳ Zero-position cleanup deferred — active exit lease(s) detected")
                    except Exception:
                        pass
                    if _safe_to_clean and self.cache.has_any_pending_orders():
                        _safe_to_clean = False
                        print(f"[RISK] ⏳ Zero-position cleanup deferred — pending risk orders exist")
                    if _safe_to_clean and self._has_active_fill_watches():
                        _safe_to_clean = False
                        print(f"[RISK] ⏳ Zero-position cleanup deferred — active fill watches")
                    if _safe_to_clean:
                        stale_count = self.cache.cleanup_stale(set())
                        if stale_count > 0:
                            print(f"[RISK] 🧹 Zero-position cleanup: removed {stale_count} orphaned cache entries "
                                  f"(0 broker positions for {self._zero_position_cleanup_count} cleanup windows)")
                        self._zero_position_cleanup_count = 0
                        if hasattr(self, '_auto_imported_keys'):
                            self._auto_imported_keys.clear()
        
        import time as _save_t
        if not hasattr(self, '_last_cache_save_ts'):
            self._last_cache_save_ts = 0
        _now_save = _save_t.monotonic()
        if (_now_save - self._last_cache_save_ts) >= 2.0:
            self.cache.save()
            self._last_cache_save_ts = _now_save

        if not hasattr(self, '_risk_status_log_ts'):
            self._risk_status_log_ts = 0
        if not hasattr(self, '_risk_last_logged_prices'):
            self._risk_last_logged_prices = {}
        import time as _rsl_t
        _rsl_now = _rsl_t.monotonic()
        _status_interval_elapsed = (_rsl_now - self._risk_status_log_ts) >= 10
        for pos in positions:
            _rk = self._pos_tracking_key(pos)
            _cache = self.cache.get(_rk) or self.cache.get(f"{pos.broker}_{pos.symbol}")
            if not _cache or not _cache.entry_price or _cache.entry_price <= 0:
                continue
            _pnl_pct = ((pos.current_price - _cache.entry_price) / _cache.entry_price) * 100
            _sl_val = getattr(_cache, 'dynamic_sl_price', None) or getattr(_cache, 'stop_loss_price', None)
            _pt_val = getattr(_cache, 'profit_target_price', None)
            _sl_str = f"SL=${_sl_val:.2f}" if _sl_val and _sl_val > 0 else "SL=—"
            _pt_str = f"PT=${_pt_val:.2f}" if _pt_val and _pt_val > 0 else "PT=—"
            _prev_price = self._risk_last_logged_prices.get(_rk, 0)
            _price_changed = abs(pos.current_price - _prev_price) > 0.0001
            _sl_dist = ""
            if _sl_val and _sl_val > 0:
                _sl_dist_pct = ((pos.current_price - _sl_val) / _sl_val) * 100
                _sl_dist = f" | SL-dist={_sl_dist_pct:.1f}%"
            _should_log = (
                _status_interval_elapsed
                or (_price_changed and abs(pos.current_price - _prev_price) / max(_prev_price, 0.01) > 0.003)
            )
            if _should_log:
                _trailing_str = ""
                _ts_price = getattr(_cache, 'trailing_stop_price', None)
                if _ts_price and _ts_price > 0:
                    _trailing_str = f" | TS=${_ts_price:.2f}"
                _high = getattr(_cache, 'highest_price', 0)
                _high_str = f" | high=${_high:.2f}" if _high and _high > 0 else ""
                print(f"[RISK] 📡 {pos.symbol} ${pos.current_price:.2f} ({_pnl_pct:+.1f}%) | entry=${_cache.entry_price:.2f} | {_sl_str} {_pt_str}{_trailing_str}{_high_str}{_sl_dist} | {pos.broker}")
                self._risk_last_logged_prices[_rk] = pos.current_price
        if _status_interval_elapsed:
            self._risk_status_log_ts = _rsl_now

        _mc_t4 = _mc_time.monotonic()
        _setup_ms = (_mc_t1 - _mc_t0) * 1000
        _fetch_ms = (_mc_t3 - _mc_t2) * 1000
        _eval_ms = (_mc_t4 - _mc_t3) * 1000
        self._last_cycle_timing_detail = (
            f" [setup={_setup_ms:.0f}ms fetch={_fetch_ms:.0f}ms eval={_eval_ms:.0f}ms pos={len(positions)}]"
        )
    
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

        _has_open = getattr(self, '_has_open_positions_or_watches_cache', True)
        if _force_webull or _force_global:
            if not _has_open:
                try:
                    _connected = self._get_connected_broker_names()
                    _open_count = self.db_adapter.count_open_trades(connected_brokers=_connected) if _connected else self.db_adapter.count_open_trades()
                except Exception:
                    _open_count = 1
                _has_open = _open_count > 0 or self._has_active_fill_watches()
            if _has_open:
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
                            try:
                                await asyncio.wait_for(_fhub.refresh_positions_once(_raw_wb), timeout=3.0)
                            except asyncio.TimeoutError:
                                print("[RISK] ⚠️ Webull REST refresh timed out (3s) — using cached data")
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
                    
                    if not is_option:
                        _upper_sym = (symbol or '').upper()
                        if _upper_sym in self._INDEX_TO_CANONICAL:
                            is_option = True
                            print(f"[RISK] ✓ INDEX GUARD: Forced {symbol} to option (index symbols are always options, never stocks)")

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
            if _has_open:
                _REST_CACHE_TTL = 0

        async def _fetch_webull_rest():
            if webull_snapshots is not None:
                return []
            if not _has_open and not self._has_active_fill_watches():
                _now_disc = _time.time()
                _disc_age = _now_disc - getattr(self, '_webull_discovery_ts', 0)
                if _disc_age < 60:
                    return []
                self._webull_discovery_ts = _now_disc
                self._schwab_discovery_ts = _now_disc
                self._tastytrade_discovery_ts = _now_disc
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
                        if not is_option:
                            _upper_sym = (symbol or '').upper()
                            if _upper_sym in self._INDEX_TO_CANONICAL:
                                is_option = True
                                print(f"[RISK] ✓ INDEX GUARD: Forced {symbol} to option (fallback path — index symbols are always options)")
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
                _hub_succeeded = False
                try:
                    from src.services.schwab_data_hub import get_schwab_data_hub
                    schwab_hub = get_schwab_data_hub()
                    _schwab_streaming = schwab_hub.is_streaming() or getattr(schwab_hub, '_streaming_active', False)
                    hub_pos = schwab_hub.get_positions(detailed=True)
                    if hub_pos is not None:
                        _hub_succeeded = True
                        schwab_positions = []
                        for pos in hub_pos:
                            _schwab_asset = pos.get('asset', 'stock')
                            _schwab_sym = pos.get('symbol', '')
                            if _schwab_asset == 'stock' and (_schwab_sym or '').upper() in self._INDEX_TO_CANONICAL:
                                _schwab_asset = 'option'
                                print(f"[RISK] ✓ INDEX GUARD: Forced Schwab hub {_schwab_sym} to option")
                            schwab_positions.append(PositionSnapshot(
                                symbol=_schwab_sym,
                                quantity=abs(float(pos.get('quantity', 0))),
                                avg_cost=float(pos.get('avg_cost', 0)),
                                current_price=float(pos.get('current_price', 0)),
                                asset=_schwab_asset,
                                broker='SCHWAB',
                                strike=pos.get('strike'),
                                expiry=pos.get('expiry'),
                                direction=pos.get('direction'),
                                raw_symbol=pos.get('raw_symbol')
                            ))
                        if schwab_positions or not (hasattr(self, '_last_schwab_positions') and self._last_schwab_positions):
                            self._last_schwab_positions = schwab_positions
                            self._schwab_cache_ts = _time.time()
                        elif not schwab_positions and hasattr(self, '_last_schwab_positions') and self._last_schwab_positions:
                            _open_schwab_trades = 0
                            try:
                                from gui_app.database import get_connection as _gc_schwab
                                _sc = _gc_schwab()
                                _sc_cur = _sc.cursor()
                                _sc_cur.execute("SELECT COUNT(*) FROM trades WHERE UPPER(broker) = 'SCHWAB' AND status IN ('OPEN','PENDING','PARTIAL') AND direction = 'BTO'")
                                _open_schwab_trades = _sc_cur.fetchone()[0]
                            except Exception:
                                pass
                            if _open_schwab_trades > 0:
                                _stale_age = schwab_cache_age
                                if _stale_age < 120:
                                    return list(self._last_schwab_positions)
                            self._last_schwab_positions = []
                            self._schwab_cache_ts = _time.time()
                        return list(self._last_schwab_positions) if self._last_schwab_positions else schwab_positions
                    elif _schwab_streaming and hub_pos is not None:
                        self._last_schwab_positions = []
                        self._schwab_cache_ts = _time.time()
                        return []
                except ImportError:
                    pass
                except Exception as _hub_err:
                    print(f"[RISK] ⚠️ Schwab hub fetch error: {_hub_err}")
                if _schwab_streaming:
                    if hasattr(self, '_last_schwab_positions') and self._last_schwab_positions is not None and schwab_cache_age < _REST_CACHE_TTL:
                        return list(self._last_schwab_positions)
                if not _has_open and not self._has_active_fill_watches():
                    _disc_age = _time.time() - getattr(self, '_schwab_discovery_ts', 0)
                    if _disc_age < 60:
                        return []
                    self._schwab_discovery_ts = _time.time()
                if rate_manager:
                    can_proceed, wait_time = rate_manager.can_make_request('schwab')
                    if not can_proceed:
                        if hasattr(self, '_last_schwab_positions') and self._last_schwab_positions is not None and len(self._last_schwab_positions) > 0 and schwab_cache_age < 120:
                            return list(self._last_schwab_positions)
                        _open_schwab_trades = 0
                        try:
                            from gui_app.database import get_connection as _gc_schwab2
                            _sc2 = _gc_schwab2()
                            _sc2_cur = _sc2.cursor()
                            _sc2_cur.execute("SELECT COUNT(*) FROM trades WHERE UPPER(broker) = 'SCHWAB' AND status IN ('OPEN','PENDING','PARTIAL') AND direction = 'BTO'")
                            _open_schwab_trades = _sc2_cur.fetchone()[0]
                        except Exception:
                            pass
                        if _open_schwab_trades > 0 and not _hub_succeeded:
                            try:
                                _broker_cached = getattr(self.schwab_broker, '_last_valid_positions', None)
                                if _broker_cached and len(_broker_cached) > 0:
                                    schwab_positions = []
                                    for pos in _broker_cached:
                                        _schwab_asset = pos.get('asset', 'stock')
                                        _schwab_sym = pos.get('symbol', '')
                                        if _schwab_asset == 'stock' and (_schwab_sym or '').upper() in self._INDEX_TO_CANONICAL:
                                            _schwab_asset = 'option'
                                        schwab_positions.append(PositionSnapshot(
                                            symbol=_schwab_sym,
                                            quantity=abs(float(pos.get('quantity', 0))),
                                            avg_cost=float(pos.get('avg_cost', 0)),
                                            current_price=float(pos.get('current_price', 0)),
                                            asset=_schwab_asset,
                                            broker='SCHWAB',
                                            strike=pos.get('strike'),
                                            expiry=pos.get('expiry'),
                                            direction=pos.get('direction'),
                                            raw_symbol=pos.get('raw_symbol')
                                        ))
                                    if schwab_positions:
                                        self._last_schwab_positions = schwab_positions
                                        self._schwab_cache_ts = _time.time()
                                        return schwab_positions
                            except Exception:
                                pass
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
                if hasattr(self, '_last_schwab_positions') and self._last_schwab_positions is not None and len(self._last_schwab_positions) > 0:
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
                                _ibkr_asset = p.get('asset', 'stock')
                                _ibkr_sym = p.get('symbol', '')
                                if _ibkr_asset == 'stock' and (_ibkr_sym or '').upper() in self._INDEX_TO_CANONICAL:
                                    _ibkr_asset = 'option'
                                    print(f"[RISK] ✓ INDEX GUARD: Forced IBKR hub {_ibkr_sym} to option")
                                snap = PositionSnapshot(
                                    symbol=_ibkr_sym,
                                    quantity=p.get('quantity', 0),
                                    avg_cost=p.get('avg_cost', 0),
                                    current_price=0,
                                    asset=_ibkr_asset,
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
                if not _has_open and not self._has_active_fill_watches():
                    _disc_age = _time.time() - getattr(self, '_tastytrade_discovery_ts', 0)
                    if _disc_age < 60:
                        return []
                    self._tastytrade_discovery_ts = _time.time()
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

        async def _timed(name, coro):
            _t0 = _time.time()
            r = await coro
            _elapsed = (_time.time() - _t0) * 1000
            if _elapsed > 100:
                print(f"[RISK] ⏱ {name}: {_elapsed:.0f}ms")
            return r

        results = await asyncio.gather(
            _timed('webull', _fetch_webull_rest()),
            _timed('alpaca', _fetch_alpaca_cached()),
            _timed('schwab', _fetch_schwab_cached()),
            _timed('ibkr', _fetch_ibkr_cached()),
            _timed('tastytrade', _fetch_tastytrade_cached()),
            _timed('robinhood', _fetch_robinhood_cached()),
            _timed('trading212', _fetch_trading212_cached()),
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
            if not is_option and hasattr(ap, 'asset_class'):
                is_option = str(getattr(ap, 'asset_class', '')).lower() == 'us_option'
            if not is_option:
                _upper_sym = (symbol or '').upper()
                if _upper_sym in self._INDEX_TO_CANONICAL:
                    is_option = True
                    print(f"[RISK] ✓ INDEX GUARD: Forced Alpaca {symbol} to option (index symbols are always options)")
            
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
                if asset_type == 'stock' and (raw_sym or '').upper() in self._INDEX_TO_CANONICAL:
                    asset_type = 'option'
                    print(f"[RISK] ✓ INDEX GUARD: Forced Schwab REST {raw_sym} to option")
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
                raw_positions = await _await_if_needed(
                    await asyncio.to_thread(self.tastytrade_broker.get_all_positions)
                ) or []
                
                for pos in raw_positions:
                    asset_type = pos.get('asset_type', 'stock')
                    tt_sym = pos.get('symbol', '')
                    _tt_underlying = pos.get('underlying_symbol', tt_sym)
                    if asset_type == 'stock' and (_tt_underlying or '').upper() in self._INDEX_TO_CANONICAL:
                        asset_type = 'option'
                        print(f"[RISK] ✓ INDEX GUARD: Forced Tastytrade {_tt_underlying} to option")
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
                    rh_sym = pos.get('symbol', '')
                    if pos_type == 'stock' and (rh_sym or '').upper() in self._INDEX_TO_CANONICAL:
                        pos_type = 'option'
                        print(f"[RISK] ✓ INDEX GUARD: Forced Robinhood {rh_sym} to option")
                    
                    call_put = None
                    if pos.get('option_type') == 'call':
                        call_put = 'C'
                    elif pos.get('option_type') == 'put':
                        call_put = 'P'
                    
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
                if not hasattr(self, '_pending_trade_match_keys'):
                    self._pending_trade_match_keys = set()
                was_pending = pos_key in self._pending_trade_match_keys
                if was_pending:
                    self._pending_trade_match_keys.discard(pos_key)
                    if hasattr(self, '_skipped_external_logged'):
                        self._skipped_external_logged.discard(pos_key)
                    print(f"[RISK] 🆕 TRADE MATCHED: {position.symbol} on {position.broker} "
                          f"now linked to trade #{trade_id} "
                          f"(qty={position.quantity}, avg_cost=${position.avg_cost}, current=${position.current_price}) — "
                          f"risk engine activating")
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
                _recovered = False
                try:
                    from gui_app.database import get_connection as _get_recover_conn
                    _rc = _get_recover_conn()
                    _rcur = _rc.cursor()
                    _rcur.execute('''
                        SELECT id, executed_price, quantity, original_quantity, stop_loss_price, 
                               profit_target_price, conditional_order_id, channel_id, source,
                               risk_settings_hash, closed_at
                        FROM trades
                        WHERE UPPER(symbol) = UPPER(?) AND UPPER(broker) = UPPER(?)
                          AND status = 'CLOSED' AND close_reason = 'broker_closed_position'
                          AND asset_type = ?
                          AND closed_at >= datetime('now', '-30 minutes')
                        ORDER BY closed_at DESC LIMIT 1
                    ''', (position.symbol, position.broker, position.asset))
                    _false_closed = _rcur.fetchone()
                    if _false_closed:
                        _fc_id = _false_closed['id']
                        _fc_closed_at = _false_closed['closed_at'] or ''
                        _rc.execute('''
                            UPDATE trades SET status = 'OPEN', close_reason = NULL, closed_at = NULL,
                                             pnl = NULL, pnl_percent = NULL
                            WHERE id = ?
                        ''', (_fc_id,))
                        _rc.commit()
                        trade_id = _fc_id
                        self.cache.set_trade_id(pos_key, trade_id)
                        if hasattr(self, '_skipped_external_logged'):
                            self._skipped_external_logged.discard(pos_key)
                        if hasattr(self, '_pending_trade_match_keys'):
                            self._pending_trade_match_keys.discard(pos_key)
                        print(f"[RISK] 🔄 FALSE CLOSE RECOVERY: Re-opened trade #{_fc_id} for {pos_key} "
                              f"(was falsely closed as broker_closed_position at {_fc_closed_at}, "
                              f"position still exists on broker: qty={position.quantity}, price=${position.current_price})")
                        _recovered = True
                        try:
                            _rcur.execute('''
                                DELETE FROM lot_closures WHERE lot_id IN (
                                    SELECT sl.id FROM signal_lots sl WHERE sl.trade_id = ?
                                ) AND exit_reason = 'broker_closed_position'
                            ''', (_fc_id,))
                            _rc.commit()
                        except Exception:
                            pass
                except Exception as _recover_err:
                    print(f"[RISK] ⚠️ False close recovery check error: {_recover_err}")
                
                if _recovered:
                    pass
                else:
                    # GHOST POSITION SUPPRESSION:
                    # If the broker REST cache still echoes a position that the local DB has
                    # legitimately CLOSED (risk-engine exit, manual exit, signal STC, etc.),
                    # do NOT continue evaluating or logging — it misleads the user into thinking
                    # the position is still active. Skip silently and let cleanup_stale() drop
                    # the cache entry once the broker stream catches up.
                    try:
                        from gui_app.database import get_connection as _get_ghost_conn
                        _ghc = _get_ghost_conn()
                        _ghcur = _ghc.cursor()
                        _ghost_call_put = self._normalize_call_put(position.direction) if position.asset == 'option' else None
                        # First, check for ANY conflicting OPEN/PENDING/PARTIAL trade for the same
                        # instrument identity. If one exists, the broker echo belongs to a legitimate
                        # active trade — do NOT suppress (e.g., rapid re-entry into same contract).
                        if position.asset == 'option':
                            _ghcur.execute('''
                                SELECT 1 FROM trades
                                WHERE UPPER(symbol) = UPPER(?) AND UPPER(broker) = UPPER(?)
                                  AND status IN ('OPEN','PENDING','PARTIAL') AND asset_type = 'option'
                                  AND strike = ? AND expiry = ? AND call_put = ?
                                LIMIT 1
                            ''', (position.symbol, position.broker, position.strike,
                                  position.expiry, _ghost_call_put))
                        else:
                            _ghcur.execute('''
                                SELECT 1 FROM trades
                                WHERE UPPER(symbol) = UPPER(?) AND UPPER(broker) = UPPER(?)
                                  AND status IN ('OPEN','PENDING','PARTIAL') AND asset_type = 'stock'
                                LIMIT 1
                            ''', (position.symbol, position.broker))
                        _conflict = _ghcur.fetchone()
                        _ghost_row = None
                        if not _conflict:
                            if position.asset == 'option':
                                _ghcur.execute('''
                                    SELECT id, close_reason, closed_at FROM trades
                                    WHERE UPPER(symbol) = UPPER(?) AND UPPER(broker) = UPPER(?)
                                      AND status = 'CLOSED' AND asset_type = 'option'
                                      AND strike = ? AND expiry = ? AND call_put = ?
                                      AND closed_at >= datetime('now', '-10 minutes')
                                      AND (close_reason IS NULL OR LOWER(close_reason) != 'broker_closed_position')
                                    ORDER BY closed_at DESC LIMIT 1
                                ''', (position.symbol, position.broker, position.strike,
                                      position.expiry, _ghost_call_put))
                            else:
                                _ghcur.execute('''
                                    SELECT id, close_reason, closed_at FROM trades
                                    WHERE UPPER(symbol) = UPPER(?) AND UPPER(broker) = UPPER(?)
                                      AND status = 'CLOSED' AND asset_type = 'stock'
                                      AND closed_at >= datetime('now', '-10 minutes')
                                      AND (close_reason IS NULL OR LOWER(close_reason) != 'broker_closed_position')
                                    ORDER BY closed_at DESC LIMIT 1
                                ''', (position.symbol, position.broker))
                            _ghost_row = _ghcur.fetchone()
                        if _ghost_row:
                            if not hasattr(self, '_ghost_position_logged'):
                                self._ghost_position_logged = set()
                            broker_position_keys.discard(pos_key)
                            if pos_key not in self._ghost_position_logged:
                                self._ghost_position_logged.add(pos_key)
                                _gh_id = _ghost_row[0] if not hasattr(_ghost_row, 'keys') else _ghost_row['id']
                                _gh_reason = (_ghost_row[1] if not hasattr(_ghost_row, 'keys') else _ghost_row['close_reason']) or 'manual'
                                _gh_at = (_ghost_row[2] if not hasattr(_ghost_row, 'keys') else _ghost_row['closed_at']) or 'unknown'
                                print(f"[RISK] 👻 GHOST POSITION: {pos_key} closed in DB "
                                      f"(trade #{_gh_id}, reason={_gh_reason}, at {_gh_at}) "
                                      f"but broker still echoes — suppressing eval until broker cache clears")
                            return
                    except Exception as _ghost_err:
                        print(f"[RISK] ⚠️ Ghost position check error: {_ghost_err}")

                    if not hasattr(self, '_pending_trade_match_keys'):
                        self._pending_trade_match_keys = set()
                    self._pending_trade_match_keys.add(pos_key)
                    
                    auto_import_enabled = False
                    try:
                        import time as _ai_time
                        _ai_now = _ai_time.monotonic()
                        _ai_cached = getattr(self, '_auto_import_cache', None)
                        if _ai_cached and (_ai_now - _ai_cached[1]) < 10:
                            auto_import_enabled = _ai_cached[0]
                        else:
                            from gui_app.database import get_setting as _get_setting_ai
                            auto_import_setting = _get_setting_ai('auto_import_external', 'false')
                            auto_import_enabled = auto_import_setting.lower() == 'true'
                            self._auto_import_cache = (auto_import_enabled, _ai_now)
                    except Exception:
                        pass
                    
                    if not auto_import_enabled:
                        if not hasattr(self, '_skipped_external_logged'):
                            self._skipped_external_logged = set()
                        if pos_key not in self._skipped_external_logged:
                            self._skipped_external_logged.add(pos_key)
                            print(f"[RISK] ⏭️ Skipping external position {pos_key} — auto-import disabled (will re-check for trade match)")
                        return
                
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
        
        if position.avg_cost <= 0:
            if not hasattr(self, '_zero_entry_logged'):
                self._zero_entry_logged = set()
            if pos_key not in self._zero_entry_logged:
                self._zero_entry_logged.add(pos_key)
                print(f"[RISK] 🛡️ ENTRY GUARD: {pos_key} has zero/negative avg_cost (${position.avg_cost}) — "
                      f"skipping risk evaluation until entry price is resolved")
            return

        _ABSURD_PNL_THRESHOLD = 500.0
        if abs(pct_change) > _ABSURD_PNL_THRESHOLD:
            if not hasattr(self, '_absurd_pnl_defer'):
                self._absurd_pnl_defer = {}
            import time as _apt
            _defer_info = self._absurd_pnl_defer.get(pos_key)
            if _defer_info is None:
                self._absurd_pnl_defer[pos_key] = {'since': _apt.time(), 'count': 1}
                print(f"[RISK] 🛡️ ABSURD PNL GUARD: {pos_key} showing {pct_change:.1f}% "
                      f"(entry=${position.avg_cost}, current=${position.current_price}) — "
                      f"deferring exit for data stabilization")
                return
            elif _defer_info['count'] < 3:
                _defer_info['count'] += 1
                print(f"[RISK] 🛡️ ABSURD PNL GUARD: {pos_key} still at {pct_change:.1f}% "
                      f"— defer cycle {_defer_info['count']}/3")
                return
            else:
                elapsed = _apt.time() - _defer_info['since']
                print(f"[RISK] ⚠️ ABSURD PNL GUARD: {pos_key} at {pct_change:.1f}% persisted through "
                      f"3 cycles ({elapsed:.1f}s) — proceeding with evaluation (may be genuine)")
                del self._absurd_pnl_defer[pos_key]

        if hasattr(self, '_zero_entry_logged') and pos_key in self._zero_entry_logged:
            self._zero_entry_logged.discard(pos_key)
        if hasattr(self, '_absurd_pnl_defer') and pos_key in self._absurd_pnl_defer:
            del self._absurd_pnl_defer[pos_key]

        channel_settings = cache.channel_settings
        _needs_source_validation = False
        if channel_settings is None:
            if trade_id is None:
                channel_settings = None
                print(f"[RISK] 🛡️ {position.symbol} on {position.broker}: no trade_id — skipping channel settings lookup (global risk only)")
            else:
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
            _needs_source_validation = True
        elif channel_settings and trade_id:
            import time as _reval_time
            _last_revalidation = getattr(cache, '_last_source_revalidation', 0)
            if (_reval_time.monotonic() - _last_revalidation) > 60:
                _needs_source_validation = True
                cache._last_source_revalidation = _reval_time.monotonic()

        if _needs_source_validation and channel_settings and trade_id:
            try:
                _conn = self.db_adapter._db.get_connection() if self.db_adapter._db else None
                if _conn:
                    _cur = _conn.cursor()
                    _cur.execute('SELECT source, channel_id FROM trades WHERE id = ?', (trade_id,))
                    _src_row = _cur.fetchone()
                    _trade_source = (_src_row[0] or '').strip().lower() if _src_row else ''
                    _trade_channel_id = _src_row[1] if _src_row else None
                    _TRUSTED_SOURCES = ('discord', 'signal', 'sync_routing')
                    _BLOCKED_SOURCES = ('sync', 'risk_auto_import')
                    if _trade_source in _BLOCKED_SOURCES:
                        print(f"[RISK] 🛡️ BLOCKED channel settings for {position.symbol}: trade #{trade_id} was auto-imported "
                              f"(source='{_trade_source}'), NOT a real signal from '{channel_settings.channel_name}' — treating as manual trade")
                        channel_settings = None
                    elif _trade_source not in _TRUSTED_SOURCES and _trade_channel_id:
                        _has_real_signal_trade = False
                        try:
                            _SYMBOL_ALIASES = {
                                'SPX': ['SPXW'], 'SPXW': ['SPX'],
                                'NDX': ['NDXP'], 'NDXP': ['NDX'],
                                'VIX': ['VIXW'], 'VIXW': ['VIX'],
                                'RUT': ['RUTW'], 'RUTW': ['RUT'],
                                'DJX': ['DJXW'], 'DJXW': ['DJX'],
                            }
                            _syms = [position.symbol] + _SYMBOL_ALIASES.get(position.symbol.upper(), [])
                            _sym_phs = ','.join(['?' for _ in _syms])
                            _cur.execute(f'''
                                SELECT COUNT(*) FROM trades 
                                WHERE id != ? AND UPPER(symbol) IN ({_sym_phs}) AND UPPER(broker) = UPPER(?)
                                AND channel_id = ? AND source IN ('discord', 'signal', 'sync_routing')
                                AND status IN ('OPEN', 'PENDING', 'PARTIAL') AND direction = 'BTO'
                            ''', (trade_id, *[s.upper() for s in _syms], position.broker, _trade_channel_id))
                            _signal_count = _cur.fetchone()[0]
                            _has_real_signal_trade = _signal_count > 0
                        except Exception:
                            pass
                        if not _has_real_signal_trade:
                            print(f"[RISK] 🛡️ BLOCKED channel settings for {position.symbol}: trade #{trade_id} "
                                  f"(source='{_trade_source}') has channel_id={_trade_channel_id} but no active signal trade "
                                  f"from '{channel_settings.channel_name}' justifies it — treating as manual trade")
                            channel_settings = None
                        else:
                            print(f"[RISK] ✓ Trade #{trade_id} (source='{_trade_source}') validated: "
                                  f"active signal trade exists for {position.symbol} on channel '{channel_settings.channel_name}'")
            except Exception as _src_err:
                print(f"[RISK] ⚠️ Could not verify trade source for #{trade_id}: {_src_err}")
            self.cache.apply_settings_with_versioning(pos_key, channel_settings)
        elif cache.channel_settings is None and _needs_source_validation:
            self.cache.apply_settings_with_versioning(pos_key, channel_settings)

        if _needs_source_validation:
            if channel_settings:
                print(f"[RISK] 📋 {position.symbol} (trade #{trade_id}, broker={position.broker}): "
                      f"CHANNEL RISK active — channel='{channel_settings.channel_name}', "
                      f"SL={channel_settings.stop_loss_pct}%, "
                      f"PT1={channel_settings.profit_target_1_pct}%")
            else:
                print(f"[RISK] 📋 {position.symbol} (trade #{trade_id}, broker={position.broker}): "
                      f"NO CHANNEL RISK — using global settings only (manual/unlinked trade)")
            
            if channel_settings:
                print(f"[RISK] Using per-channel settings from '{channel_settings.channel_name}': "
                      f"Targets={channel_settings.profit_target_1_pct}%/"
                      f"{channel_settings.profit_target_2_pct}%/{channel_settings.profit_target_3_pct}%, "
                      f"StopLoss={channel_settings.stop_loss_pct}%, ExitMode={channel_settings.exit_strategy_mode}")
        
        if not channel_settings and not risk_settings.enabled:
            self._log_position_status(position, cache, channel_settings, pct_change)
            return

        _bbm_check = getattr(channel_settings, 'broker_bracket_mode', 'none') if channel_settings else 'none'

        _bracket_fill_handled = await self._detect_and_handle_bracket_fill(position, cache, channel_settings)

        if cache.broker_orders_placed and not cache.broker_stop_order_id and not cache.broker_pt_order_id and not cache.broker_oco_order_id and _bbm_check != 'none':
            if not _bracket_fill_handled:
                print(f"[RISK] 🔄 Bracket state stale for {position.symbol} — no active broker orders found, resetting for fresh placement")
                cache.broker_orders_placed = False
                cache._bracket_attempt_count = 0

        _current_qty = int(position.quantity)
        _bracket_qty = getattr(cache, '_bracket_placed_qty', 0)
        if cache.broker_orders_placed and _bracket_qty > 0 and _current_qty > _bracket_qty and _bbm_check != 'none':
            print(f"[RISK] 🔄 Scale-in detected for {position.symbol}: bracket qty={_bracket_qty} → position qty={_current_qty} — cancelling old brackets and re-placing")
            try:
                await self._cancel_broker_bracket_orders(position, cache, cancel_stop=True, cancel_pt=True)
            except Exception as _cancel_err:
                print(f"[RISK] ⚠️ Failed to cancel old brackets on scale-in: {_cancel_err}")
            cache.broker_orders_placed = False
            cache.broker_stop_order_id = None
            cache.broker_pt_order_id = None
            cache.broker_oco_order_id = None
            cache.broker_oco_qty = 0
            cache._bracket_attempt_count = 0
            cache._bracket_placed_qty = 0

        if channel_settings and not cache.broker_orders_placed:
            _bracket_attempts = getattr(cache, '_bracket_attempt_count', 0)
            if _bracket_attempts >= 3:
                if _bracket_attempts == 3:
                    print(f"[RISK] ⚠️ Bracket placement failed 3 times for {position.symbol} on {position.broker} — giving up (risk engine will manage exits)")
                    cache._bracket_attempt_count = _bracket_attempts + 1
            else:
                _exit_mode = channel_settings.exit_strategy_mode
                _has_levels = (channel_settings.stop_loss_pct > 0 or channel_settings.profit_target_1_pct > 0)
                if _has_levels:
                    try:
                        cache._bracket_attempt_count = _bracket_attempts + 1
                        await self._place_initial_broker_bracket(position, cache, channel_settings)
                        if cache.broker_orders_placed:
                            cache._bracket_placed_qty = int(position.quantity)
                    except Exception as e:
                        print(f"[RISK] ⚠️ Initial broker bracket failed attempt {_bracket_attempts + 1}/3 (non-blocking): {e}")
                elif not _has_levels:
                    print(f"[RISK] ⏭ No SL/PT levels configured — skipping broker bracket (exit_mode={_exit_mode})")

        if cache.broker_orders_placed and not cache.broker_stop_order_id and not cache.closing:
            if getattr(cache, '_pending_broker_sl_replace', False):
                _sl_price = getattr(cache, '_pending_sl_replace_price', 0)
                _cancelled_at = getattr(cache, '_sl_cancelled_at', 0)
                import time as _t_sl
                _elapsed = _t_sl.time() - _cancelled_at if _cancelled_at else 999
                if _sl_price and _sl_price > 0 and _elapsed >= 15 and not self.cache.is_closing(pos_key):
                    print(f"[RISK] 🔄 Re-placing broker SL at ${_sl_price:.2f} for {int(position.quantity)} shares (deferred {_elapsed:.0f}s after PT cancel)")
                    cache._pending_broker_sl_replace = False
                    cache._pending_sl_replace_price = None
                    cache._sl_cancelled_at = None
                    self._enqueue_broker_op(pos_key, 'REPLACE_STOP_AFTER_PT', 10,
                        lambda _p=position, _c=cache, _sp=_sl_price: self._sync_stop_to_broker(_p, _c, _sp))

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
            if getattr(decision, '_broker_pt_needs_cancel', False):
                _pt_oid = getattr(decision, '_broker_pt_order_id', None)
                _t = getattr(decision, '_broker_pt_tier_hit', 1)
                if _pt_oid:
                    self._enqueue_broker_op(pos_key, 'CANCEL_PT_FOR_LOCAL', 5,
                        lambda _p=position, _c=cache: self._cancel_broker_bracket_orders(_p, _c, cancel_stop=False, cancel_pt=True))
                    print(f"[RISK] 📋 PT{_t} hit: cancelling broker PT order #{_pt_oid} — local partial sell will execute")
                self._enqueue_broker_op(pos_key, f'PLACE_PT{_t+1}', 20,
                    lambda _p=position, _c=cache, _cs=channel_settings, _th=_t: self._place_next_pt_bracket(_p, _c, _cs, _th))
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
        _tracking_key = self._pos_tracking_key(position)
        _is_repair_cycle = _repair_key in self._rest_repair_cycle_keys or _tracking_key in self._rest_repair_cycle_keys
        _is_rest_confirmed = _repair_key in self._rest_confirmed_this_cycle or _tracking_key in self._rest_confirmed_this_cycle
        _is_rest_validated_same = _repair_key in self._rest_validated_same or _tracking_key in self._rest_validated_same

        freshness_result = self._check_price_freshness(position, cache, channel_settings)
        if freshness_result is not None:
            return freshness_result

        _staleness_is_blocking = False
        _staleness_change_age = 0
        _rest_override_available = _is_rest_confirmed or _is_rest_validated_same
        tracker = self._stuck_price_tracker.get(_repair_key) or self._stuck_price_tracker.get(_tracking_key)
        if tracker and not (_is_repair_cycle and not _is_rest_confirmed):
            import time as _st
            change_age = _st.time() - tracker['last_changed']
            _staleness_change_age = change_age
            session = self._get_market_session()
            _effective_threshold = self._STALENESS_EXIT_BLOCK_THRESHOLD
            if session == 'extended':
                _effective_threshold = 300
            if change_age > _effective_threshold:
                if session in ('regular', 'extended'):
                    if _rest_override_available:
                        if not hasattr(self, '_rest_override_logged'):
                            self._rest_override_logged = {}
                        _ro_key = f"{_repair_key}_{int(change_age)//30}"
                        if _ro_key not in self._rest_override_logged:
                            self._rest_override_logged[_ro_key] = True
                            _override_src = "REST-confirmed fresh" if _is_rest_confirmed else "REST-validated same"
                            print(f"[RISK] ✓ STALENESS OVERRIDE: {position.symbol} price ${position.current_price:.2f} "
                                  f"stale {change_age:.0f}s but {_override_src} — allowing SL evaluation")
                    elif change_age > 60 and tracker.get('rest_checked_ok', 0) > tracker.get('last_changed', 0):
                        if not hasattr(self, '_max_stale_override_logged'):
                            self._max_stale_override_logged = {}
                        _mso_key = f"{_repair_key}_{int(change_age)//60}"
                        if _mso_key not in self._max_stale_override_logged:
                            self._max_stale_override_logged[_mso_key] = True
                            print(f"[RISK] ✓ MAX STALENESS OVERRIDE: {position.symbol} price ${position.current_price:.2f} "
                                  f"unchanged {change_age:.0f}s — REST checked, allowing SL evaluation (60s safety limit)")
                    else:
                        _staleness_is_blocking = True
            elif change_age > self._STALENESS_EXIT_BLOCK_THRESHOLD and session == 'extended':
                _ext_pos_key = f"{position.broker}_{position.symbol}_{position.asset}"
                _rest_price = None
                try:
                    from src.services.webull_data_hub import get_webull_data_hub
                    _hub = get_webull_data_hub()
                    if _hub:
                        _rest_price = _hub.get_quote_price(position.symbol)
                except Exception:
                    pass
                if _rest_price and abs(_rest_price - position.current_price) / max(position.current_price, 0.001) < 0.02:
                    if not hasattr(self, '_ext_hours_staleness_bypass_logged'):
                        self._ext_hours_staleness_bypass_logged = set()
                    if _ext_pos_key not in self._ext_hours_staleness_bypass_logged:
                        self._ext_hours_staleness_bypass_logged.add(_ext_pos_key)
                        print(f"[RISK] ✓ EXTENDED HOURS: {position.symbol} price ${position.current_price:.4f} "
                              f"confirmed by REST (${_rest_price:.4f}) — allowing exit evaluation "
                              f"despite {change_age:.0f}s staleness")

        decision = evaluate_price_based_stops(position, cache)
        if decision.should_exit:
            _allow_eval = not _is_repair_cycle or _is_rest_confirmed
            if _allow_eval:
                if channel_settings and channel_settings.escalation_only_mode and decision.risk_trigger == 'profit_target':
                    pass
                elif _staleness_is_blocking and decision.risk_trigger in ('stop_loss', 'stop_loss_price'):
                    if not hasattr(self, '_staleness_block_logged'):
                        self._staleness_block_logged = {}
                    _sbl_key = f"{_repair_key}_{int(_staleness_change_age)//30}"
                    if _sbl_key not in self._staleness_block_logged:
                        self._staleness_block_logged[_sbl_key] = True
                        print(f"[RISK] 🛡️ STALENESS GATE: {position.symbol} price unchanged for "
                              f"{_staleness_change_age:.0f}s — blocking STOP LOSS exit "
                              f"until fresh price arrives (profit targets still allowed)")
                    return ExitDecision.no_exit()
                else:
                    if _staleness_is_blocking and decision.risk_trigger == 'profit_target':
                        print(f"[RISK] ✓ STALENESS BYPASS: {position.symbol} profit target hit "
                              f"— allowing exit despite {_staleness_change_age:.0f}s stale price "
                              f"(selling at stale HIGH is favorable)")
                    return decision
        
        if channel_settings:
            decision = evaluate_channel_stop_loss(position, cache, channel_settings)
            if decision.should_exit:
                _allow_csl = not _is_repair_cycle or _is_rest_confirmed
                if _allow_csl:
                    if _staleness_is_blocking:
                        if not hasattr(self, '_staleness_block_logged'):
                            self._staleness_block_logged = {}
                        _sbl_key = f"{_repair_key}_csl_{int(_staleness_change_age)//30}"
                        if _sbl_key not in self._staleness_block_logged:
                            self._staleness_block_logged[_sbl_key] = True
                            print(f"[RISK] 🛡️ STALENESS GATE: {position.symbol} price unchanged for "
                                  f"{_staleness_change_age:.0f}s — blocking channel STOP LOSS exit "
                                  f"until fresh price arrives")
                        return ExitDecision.no_exit()
                    return decision
        
        if _is_repair_cycle and not _is_rest_confirmed:
            return ExitDecision.no_exit()
        elif _is_repair_cycle and _is_rest_confirmed:
            print(f"[RISK] ✓ REST CONFIRMED CYCLE: {position.symbol} — REST-verified price ${position.current_price:.2f}, "
                  f"proceeding with exit evaluation (repair cycle override)")
        
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
                    _tier_hit = getattr(decision, 'tier_hit', None) or getattr(decision, 'tier', None)
                    if cache.broker_oco_order_id and _tier_hit and cache.broker_pt_tier == _tier_hit:
                        print(f"[RISK] 📋 OCO bracket managing T{_tier_hit} PT — suppressing software sell (OCO will handle at broker)")
                        return ExitDecision.no_exit()
                    _broker_manages_pt = _tier_hit and cache.broker_orders_placed and cache.broker_pt_order_id
                    if _broker_manages_pt:
                        decision._broker_pt_needs_cancel = True
                        decision._broker_pt_order_id = cache.broker_pt_order_id
                        decision._broker_pt_tier_hit = _tier_hit
                    return decision
        
        if channel_settings and channel_settings.ema_risk_enabled and channel_settings.stop_loss_pct > 0:
            try:
                from .ema_engine import get_candle_service
                _cs = get_candle_service()
                if _cs:
                    _tf = channel_settings.ema_timeframe_minutes
                    _pd = channel_settings.ema_period
                    _ema_st = _cs.get_ema_state(position.symbol, timeframe=_tf, period=_pd)
                    if _ema_st and _ema_st.last_candle and _ema_st.last_candle_time:
                        import time as _time_mod
                        _candle_age = _time_mod.time() - _ema_st.last_candle_time
                        _max_candle_age = _tf * 60 * 3
                        if _candle_age <= _max_candle_age:
                            _candle_close = _ema_st.last_candle.close
                            if _candle_close and cache.entry_price > 0:
                                _candle_pct = ((_candle_close - cache.entry_price) / cache.entry_price) * 100
                                if _candle_pct <= -channel_settings.stop_loss_pct:
                                    _cname = channel_settings.channel_name
                                    _allow_candle_sl = not _is_repair_cycle or _is_rest_confirmed
                                    if _allow_candle_sl and not _staleness_is_blocking:
                                        print(f"[RISK] CANDLE SL: {position.symbol} candle close ${_candle_close:.2f} shows "
                                              f"{_candle_pct:.1f}% loss (streaming ${position.current_price:.2f} lagged) "
                                              f"— triggering SL at candle price")
                                        return ExitDecision(
                                            should_exit=True,
                                            reason=f"STOP LOSS [{_cname}] Hard SL hit ({_candle_pct:.1f}% <= -{channel_settings.stop_loss_pct:.1f}%)",
                                            exit_qty=int(position.quantity),
                                            is_partial=False,
                                            risk_trigger='stop_loss'
                                        )
            except Exception as _csl_err:
                pass

        if channel_settings and (channel_settings.enable_dynamic_sl or channel_settings.enable_giveback_guard or channel_settings.ema_risk_enabled or channel_settings.enable_early_trailing):
            engine_decision = self._evaluate_enhanced_risk(position, cache, channel_settings, position_snapshot=position)
            if engine_decision and engine_decision.should_exit:
                _trigger = getattr(engine_decision, 'risk_trigger', '') or ''
                _is_sl_type = any(k in _trigger.lower() for k in ('stop', 'sl', 'giveback', 'ema_cross', 'ema_exit', 'ema_no_trend', 'early_trailing', 'trailing'))
                if _staleness_is_blocking and _is_sl_type:
                    if not hasattr(self, '_staleness_block_logged'):
                        self._staleness_block_logged = {}
                    _sbl_key = f"{_repair_key}_enh_{int(_staleness_change_age)//30}"
                    if _sbl_key not in self._staleness_block_logged:
                        self._staleness_block_logged[_sbl_key] = True
                        print(f"[RISK] 🛡️ STALENESS GATE: {position.symbol} price unchanged for "
                              f"{_staleness_change_age:.0f}s — blocking enhanced risk exit ({_trigger}) "
                              f"until fresh price arrives")
                    return ExitDecision.no_exit()
                return engine_decision
        
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
            if _staleness_is_blocking:
                if not hasattr(self, '_staleness_block_logged'):
                    self._staleness_block_logged = {}
                _sbl_key = f"{_repair_key}_trail_{int(_staleness_change_age)//30}"
                if _sbl_key not in self._staleness_block_logged:
                    self._staleness_block_logged[_sbl_key] = True
                    print(f"[RISK] 🛡️ STALENESS GATE: {position.symbol} price unchanged for "
                          f"{_staleness_change_age:.0f}s — blocking trailing stop exit "
                          f"until fresh price arrives")
                return ExitDecision.no_exit()
            return decision
        
        if not channel_settings:
            decision = evaluate_global_risk(position, cache, risk_settings)
            if decision.should_exit:
                _glob_trigger = getattr(decision, 'risk_trigger', '') or ''
                if _staleness_is_blocking and _glob_trigger != 'profit_target':
                    if not hasattr(self, '_staleness_block_logged'):
                        self._staleness_block_logged = {}
                    _sbl_key = f"{_repair_key}_glob_{int(_staleness_change_age)//30}"
                    if _sbl_key not in self._staleness_block_logged:
                        self._staleness_block_logged[_sbl_key] = True
                        print(f"[RISK] 🛡️ STALENESS GATE: {position.symbol} price unchanged for "
                              f"{_staleness_change_age:.0f}s — blocking global risk exit ({_glob_trigger}) "
                              f"until fresh price arrives")
                    return ExitDecision.no_exit()
                if _staleness_is_blocking and _glob_trigger == 'profit_target':
                    print(f"[RISK] ✓ STALENESS BYPASS: {position.symbol} global profit target hit "
                          f"— allowing exit despite {_staleness_change_age:.0f}s stale price")
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
        state.interval_high = getattr(position, '_interval_high', None)
        state.interval_low = getattr(position, '_interval_low', None)

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
        cache.early_trailing_active = updated_state.early_trailing_active
        cache.early_stop_price = updated_state.early_stop_price
        cache.early_steps_locked = updated_state.early_steps_locked
        if updated_state.highest_price > cache.highest_price:
            cache.highest_price = updated_state.highest_price
        
        if channel_settings.escalation_only_mode and channel_settings.has_tiered_targets:
            current_pnl = updated_state.pnl_pct
            tier_thresholds = {
                1: channel_settings.profit_target_1_pct,
                2: channel_settings.profit_target_2_pct,
                3: channel_settings.profit_target_3_pct,
                4: channel_settings.profit_target_4_pct
            }
            for tier in [1, 2, 3, 4]:
                threshold = tier_thresholds.get(tier, 0)
                if threshold <= 0:
                    continue
                tier_attr = f'tier{tier}_hit'
                if not getattr(cache, tier_attr, False) and current_pnl >= threshold:
                    setattr(cache, tier_attr, True)
                    print(f"[RISK] ESCALATION ONLY: T{tier} hit ({current_pnl:.1f}% >= {threshold}%) — tier marked for SL escalation, NO partial sell")

            if cache.tier1_hit or cache.tier2_hit or cache.tier3_hit or cache.tier4_hit:
                pts_hit = {1: cache.tier1_hit, 2: cache.tier2_hit, 3: cache.tier3_hit, 4: cache.tier4_hit}
                current_px = position.current_price if hasattr(position, 'current_price') else None
                new_dynamic_sl = calculate_dynamic_sl(cache.entry_price, pts_hit, channel_settings.dynamic_sl_profile, current_price=current_px)

                configured_tiers = [t for t in [1,2,3,4] if tier_thresholds.get(t, 0) > 0]
                all_configured_hit = all(pts_hit.get(t, False) for t in configured_tiers) if configured_tiers else False
                if all_configured_hit and configured_tiers and current_pnl > 0:
                    from src.risk.risk_engine import DYNAMIC_SL_PROFILES
                    _profile_name = channel_settings.dynamic_sl_profile or 'standard'
                    _profile = DYNAMIC_SL_PROFILES.get(_profile_name, DYNAMIC_SL_PROFILES['standard'])
                    highest_configured = max(configured_tiers)
                    highest_tier_pct = tier_thresholds[highest_configured]
                    highest_sl_pct = _profile.get(f'pt{highest_configured}_sl_pct', 0)
                    giveback_pct = highest_tier_pct - highest_sl_pct
                    if giveback_pct < 1:
                        giveback_pct = 5.0
                    if current_pnl > highest_tier_pct:
                        ratchet_sl_pct = current_pnl - giveback_pct
                        ratchet_sl_price = cache.entry_price * (1 + ratchet_sl_pct / 100)
                        if current_px and ratchet_sl_price >= current_px:
                            ratchet_sl_price = current_px * 0.98
                        if new_dynamic_sl is None or ratchet_sl_price > new_dynamic_sl:
                            new_dynamic_sl = ratchet_sl_price

                if new_dynamic_sl and (cache.dynamic_sl_price is None or new_dynamic_sl > cache.dynamic_sl_price):
                    old_escalation_sl = cache.dynamic_sl_price
                    cache.dynamic_sl_price = new_dynamic_sl
                    _sl_pnl = ((new_dynamic_sl / cache.entry_price) - 1) * 100
                    print(f"[RISK] Dynamic SL escalated to ${new_dynamic_sl:.2f} (+{_sl_pnl:.1f}%) after PT tier hit (escalation_only)")
                    self.cache.update_enhanced_risk_state(position.position_key, dynamic_sl_price=new_dynamic_sl)
                    if cache.broker_orders_placed and (cache.broker_stop_order_id or cache.broker_oco_order_id):
                        pos_key = position.position_key
                        _esc_sp = new_dynamic_sl
                        _old_sl_str = f"${old_escalation_sl:.2f}" if old_escalation_sl else "none"
                        print(f"[RISK] 🔄 Syncing broker stop to escalated SL ${_esc_sp:.2f} (was {_old_sl_str})")
                        self._enqueue_broker_op(pos_key, 'SYNC_STOP', 10,
                            lambda _p=position, _c=cache, _sp=_esc_sp: self._sync_stop_to_broker(_p, _c, _sp))

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
                    return ExitDecision.dynamic_sl(action.reason, action.qty, channel_name)
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
                    pos_key = position.position_key
                    _new_sp = action.new_stop_price
                    self._enqueue_broker_op(pos_key, 'SYNC_STOP', 10,
                        lambda _p=position, _c=cache, _sp=_new_sp: self._sync_stop_to_broker(_p, _c, _sp))
            
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
                if action.new_stop_price and cache.broker_orders_placed and (cache.broker_stop_order_id or cache.broker_oco_order_id):
                    _et_sp = action.new_stop_price
                    pos_key = position.position_key
                    self._enqueue_broker_op(pos_key, 'SYNC_STOP', 10,
                        lambda _p=position, _c=cache, _sp=_et_sp: self._sync_stop_to_broker(_p, _c, _sp))

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
                if cache.broker_orders_placed and (cache.broker_stop_order_id or cache.broker_oco_order_id):
                    _et_sp = action.new_stop_price
                    pos_key = position.position_key
                    self._enqueue_broker_op(pos_key, 'SYNC_STOP', 10,
                        lambda _p=position, _c=cache, _sp=_et_sp: self._sync_stop_to_broker(_p, _c, _sp))

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

    def _enqueue_broker_op(self, pos_key: str, op_type: str, priority: int, coro_factory):
        import asyncio
        if pos_key not in self._broker_ops_queues:
            self._broker_ops_queues[pos_key] = asyncio.PriorityQueue()
        if pos_key not in self._broker_ops_pending:
            self._broker_ops_pending[pos_key] = set()

        _stop_ops = {'SYNC_STOP', 'RESIZE_STOP'}
        _dedup_key = 'STOP_SYNC' if op_type in _stop_ops else op_type
        if _dedup_key in self._broker_ops_pending[pos_key]:
            return

        self._broker_ops_pending[pos_key].add(_dedup_key)
        queue = self._broker_ops_queues[pos_key]
        queue.put_nowait((priority, id(coro_factory), op_type, coro_factory))

        existing = self._broker_ops_workers.get(pos_key)
        if existing is None or existing.done():
            self._broker_ops_workers[pos_key] = asyncio.ensure_future(self._broker_ops_worker(pos_key))

    async def _broker_ops_worker(self, pos_key: str):
        import asyncio
        queue = self._broker_ops_queues.get(pos_key)
        if not queue:
            return

        while True:
            await asyncio.sleep(0)
            if queue.empty():
                break

            try:
                priority, _id, op_type, coro_factory = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            _stop_ops = {'SYNC_STOP', 'RESIZE_STOP'}
            _dedup_key = 'STOP_SYNC' if op_type in _stop_ops else op_type
            pending = self._broker_ops_pending.get(pos_key)
            if pending:
                pending.discard(_dedup_key)

            try:
                coro = coro_factory()
                await coro
            except Exception as e:
                print(f"[RISK] ⚠️ Broker op '{op_type}' failed for {pos_key}: {e}")
            finally:
                queue.task_done()

            await asyncio.sleep(0)

    async def _register_pt_with_chaser(self, order_id: str, broker_name: str, position, cache, qty, price, is_option: bool):
        try:
            from src.services.unfilled_order_chaser import get_order_chaser
            chaser = get_order_chaser()
            if not chaser:
                return
            pos_key = getattr(position, 'position_key', '') or f"{position.broker}_{position.symbol}"
            asset_type = getattr(position, 'asset', 'stock')
            await chaser.track_exit_order(
                order_id=order_id,
                broker_id=broker_name,
                symbol=position.symbol,
                asset_type=asset_type,
                quantity=qty,
                price=price,
                action='STC',
                position_key=pos_key,
                strike=getattr(position, 'strike', None),
                expiry=getattr(position, 'expiry', None),
                call_put=getattr(position, 'direction', None),
                is_risk_order=True
            )
            print(f"[RISK] 📋 Registered PT order {order_id} with order chaser for {pos_key}")
        except Exception as e:
            print(f"[RISK] ⚠️ Could not register PT with chaser: {e}")

    async def _place_tastytrade_stock_limit_gtc(self, broker_instance, symbol, qty, price, action='STC'):
        try:
            from tastytrade.instruments import Equity as _TTEq
            from tastytrade.order import NewOrder as _TTOrder, OrderAction as _TTAction, OrderTimeInForce as _TTTIF, OrderType as _TTType
            from decimal import Decimal as _TTDec
            from src.broker_interface import OrderResult
            if not broker_instance._ensure_session_valid():
                return OrderResult(success=False, message='TastyTrade session invalid', symbol=symbol, action=action)
            tt_eq = await _await_if_needed(
                await asyncio.to_thread(_TTEq.get, broker_instance.session, symbol)
            )
            order_action = _TTAction.SELL_TO_CLOSE if action.upper() in ('STC', 'SELL') else _TTAction.BUY_TO_OPEN
            leg = tt_eq.build_leg(_TTDec(str(qty)), order_action)
            price_decimal = _TTDec(str(price))
            order = _TTOrder(
                time_in_force=_TTTIF.GTC,
                order_type=_TTType.LIMIT,
                legs=[leg],
                price=price_decimal
            )
            response = await _await_if_needed(
                await asyncio.to_thread(
                    broker_instance.account.place_order,
                    broker_instance.session, order, dry_run=False
                )
            )
            if response and hasattr(response, 'order') and response.order:
                return OrderResult(success=True, order_id=str(response.order.id), symbol=symbol, action=action, quantity=qty, price=price)
            return OrderResult(success=True, order_id=None, symbol=symbol, action=action, quantity=qty, price=price, message='TastyTrade GTC order submitted but no order ID returned')
        except Exception as e:
            from src.broker_interface import OrderResult
            return OrderResult(success=False, message=str(e), symbol=symbol, action=action)

    def _resolve_webull_option_id(self, broker_instance, position):
        try:
            _opt_id = getattr(position, 'option_id', None)
            if _opt_id:
                return str(_opt_id)
            if hasattr(broker_instance, 'get_cached_option_id'):
                _cached = broker_instance.get_cached_option_id(
                    position.symbol,
                    position.strike,
                    position.expiry or '',
                    position.direction or 'C'
                )
                if _cached:
                    return str(_cached)
        except Exception as e:
            print(f"[RISK] ⚠️ Webull option_id resolution failed: {e}")
        return None

    def _resolve_webull_ticker_id(self, wb_client, symbol: str):
        tId = None
        try:
            from src.services.webull_data_hub import get_webull_data_hub
            hub = get_webull_data_hub()
            cached_tid = hub.get_ticker_id(symbol.upper())
            if cached_tid:
                tId = int(cached_tid)
        except Exception:
            pass
        if not tId:
            try:
                tId = wb_client.get_ticker(symbol)
            except Exception:
                pass
        return tId

    def _get_broker_instance_for_bracket(self, broker_name: str):
        broker_upper = broker_name.upper()
        if broker_upper == 'SCHWAB':
            return self.schwab_broker
        elif broker_upper in ('ALPACA', 'ALPACA_PAPER', 'ALPACA_LIVE'):
            return self.alpaca_broker
        elif 'IBKR' in broker_upper:
            return self.ibkr_broker
        elif 'TASTYTRADE' in broker_upper:
            return self.tastytrade_broker
        elif 'TRADING212' in broker_upper:
            return self.trading212_broker
        elif 'ROBINHOOD' in broker_upper:
            return self.robinhood_broker
        elif 'WEBULL_PAPER' in broker_upper:
            return getattr(self, 'webull_paper_broker', None) or (getattr(self.bot, 'webull_paper', None) if hasattr(self, 'bot') and self.bot else None)
        elif 'WEBULL' in broker_upper:
            return getattr(self, 'webull_broker', None) or (self.bot.webull if hasattr(self, 'bot') and self.bot else None)
        return None

    async def _detect_and_handle_bracket_fill(self, position, cache, channel_settings) -> bool:
        """Detect if a broker bracket (OCO/standalone) was filled and handle tier marking + cascade.
        Returns True if a fill was detected and processed."""
        if cache.broker_oco_order_id:
            check_id = cache.broker_oco_order_id
            _check_type = 'oco'
        elif cache.broker_pt_order_id:
            check_id = cache.broker_pt_order_id
            _check_type = 'standalone_pt'
        elif cache.broker_stop_order_id:
            check_id = cache.broker_stop_order_id
            _check_type = 'standalone_sl'
        else:
            return False

        import time as _bf_time
        if not hasattr(self, '_bracket_check_times'):
            self._bracket_check_times = {}
        pos_key = position.position_key
        last_check = self._bracket_check_times.get(pos_key, 0)
        if (_bf_time.time() - last_check) < 15:
            return False
        self._bracket_check_times[pos_key] = _bf_time.time()

        broker_name = (position.broker or '').upper()
        broker_instance = self._get_broker_instance_for_bracket(broker_name)
        if not broker_instance or not hasattr(broker_instance, 'get_order_status'):
            return False
        try:
            status_info = await broker_instance.get_order_status(check_id)
        except Exception as e:
            print(f"[RISK] ⚠️ Bracket status check failed for {pos_key}: {e}")
            return False
        if not status_info:
            return False

        status = (status_info.get('status') or '').lower()
        if status in ('pending', 'pending_activation', 'partial'):
            return False

        fill_leg = status_info.get('fill_leg')
        if status == 'filled' and not fill_leg:
            if _check_type == 'standalone_pt':
                fill_leg = 'pt'
            elif _check_type == 'standalone_sl':
                fill_leg = 'sl'
            elif cache.broker_oco_pt_price and cache.broker_oco_sl_price:
                fill_price = status_info.get('average_price', 0)
                if fill_price > 0:
                    pt_dist = abs(fill_price - cache.broker_oco_pt_price)
                    sl_dist = abs(fill_price - cache.broker_oco_sl_price)
                    fill_leg = 'pt' if pt_dist < sl_dist else 'sl'

        if status != 'filled':
            if status in ('cancelled', 'rejected', 'expired'):
                print(f"[RISK] 🔄 Bracket {check_id} is {status} for {pos_key} — clearing for fresh placement")
                self._clear_bracket_state(cache)
                cache.broker_orders_placed = False
            return False

        tier = cache.broker_pt_tier or 1
        fill_qty = status_info.get('fill_leg_qty', 0) or status_info.get('filled_quantity', 0)
        fill_price = status_info.get('fill_leg_price', 0) or status_info.get('average_price', 0)

        if fill_leg == 'pt':
            print(f"[RISK] ✅ BRACKET PT{tier} FILLED for {pos_key} (qty={fill_qty}, price=${fill_price:.2f}) — marking tier + cascading")
            self.cache.mark_tier_hit(pos_key, tier)
            if cache.broker_stop_order_id and cache.broker_stop_order_id != cache.broker_oco_order_id:
                try:
                    await broker_instance.cancel_order(cache.broker_stop_order_id)
                    print(f"[RISK] 🔄 Cancelled orphaned standalone SL #{cache.broker_stop_order_id} after PT{tier} fill")
                except Exception as _cancel_err:
                    print(f"[RISK] ⚠️ Orphaned SL cancel failed (non-blocking): {_cancel_err}")
            cache._last_bracket_pt_price = cache.broker_oco_pt_price
            cache._last_bracket_sl_price = cache.broker_oco_sl_price
            cache._last_bracket_fill_tier = tier
            self._clear_bracket_state(cache)

            if channel_settings and channel_settings.enable_dynamic_sl:
                pts_hit = {1: cache.tier1_hit, 2: cache.tier2_hit, 3: cache.tier3_hit, 4: cache.tier4_hit}
                from src.risk.risk_engine import calculate_dynamic_sl
                new_dsl = calculate_dynamic_sl(
                    cache.entry_price, pts_hit,
                    channel_settings.dynamic_sl_profile or 'standard',
                    current_price=position.current_price
                )
                if new_dsl and (cache.dynamic_sl_price is None or new_dsl > cache.dynamic_sl_price):
                    old_dsl = cache.dynamic_sl_price
                    cache.dynamic_sl_price = new_dsl
                    _sl_pnl = ((new_dsl / cache.entry_price) - 1) * 100 if cache.entry_price > 0 else 0
                    print(f"[RISK] 🔒 Dynamic SL escalated to ${new_dsl:.2f} (+{_sl_pnl:.1f}%) after bracket PT{tier} fill")
                    self.cache.update_enhanced_risk_state(pos_key, dynamic_sl_price=new_dsl)

            self._enqueue_broker_op(pos_key, f'CASCADE_PT{tier+1}', 20,
                lambda _p=position, _c=cache, _cs=channel_settings, _t=tier: self._place_next_pt_bracket(_p, _c, _cs, _t))
            return True

        elif fill_leg == 'sl':
            print(f"[RISK] 🛑 BRACKET SL FILLED for {pos_key} (qty={fill_qty}, price=${fill_price:.2f}) — position exiting via broker stop")
            cache._last_bracket_pt_price = cache.broker_oco_pt_price
            cache._last_bracket_sl_price = cache.broker_oco_sl_price
            self._clear_bracket_state(cache)
            cache.broker_orders_placed = True
            return True

        print(f"[RISK] ⚠️ Bracket {check_id} filled for {pos_key} but could not determine which leg — clearing brackets")
        self._clear_bracket_state(cache)
        return True

    def _clear_bracket_state(self, cache):
        cache.broker_stop_order_id = None
        cache.broker_pt_order_id = None
        cache.broker_oco_order_id = None
        cache.broker_oco_sl_price = None
        cache.broker_oco_pt_price = None
        cache.broker_oco_qty = 0
        cache.broker_pt_tier = 0
        cache.broker_orders_placed = False
        if hasattr(cache, '_bracket_placed_qty'):
            cache._bracket_placed_qty = 0
        if hasattr(cache, '_bracket_attempt_count'):
            cache._bracket_attempt_count = 0

    async def _place_initial_broker_bracket(self, position, cache, channel_settings):
        broker_name = position.broker.upper() if hasattr(position, 'broker') else ''

        _bbm = getattr(channel_settings, 'broker_bracket_mode', 'none')
        if _bbm == 'none':
            print(f"[RISK] ⏭ Broker bracket mode is 'none' — skipping all broker bracket orders for {position.symbol}")
            cache.broker_orders_placed = True
            return

        entry_price = cache.entry_price
        if entry_price <= 0:
            return

        sl_pct = channel_settings.stop_loss_pct

        _target_tier = 1
        for _t in [1, 2, 3, 4]:
            _t_pct = getattr(channel_settings, f'profit_target_{_t}_pct', 0) or 0
            if _t_pct > 0 and not getattr(cache, f'tier{_t}_hit', False):
                _target_tier = _t
                break
        pt1_pct = getattr(channel_settings, f'profit_target_{_target_tier}_pct', 0) or 0
        if sl_pct <= 0 and pt1_pct <= 0:
            return

        broker_instance = self._get_broker_instance_for_bracket(broker_name)
        if not broker_instance:
            print(f"[RISK] ⚠️ No broker instance for {broker_name} — bracket placement deferred (will retry)")
            if hasattr(cache, '_bracket_attempt_count') and cache._bracket_attempt_count > 0:
                cache._bracket_attempt_count -= 1
            return

        pos_key = cache.position_key if hasattr(cache, 'position_key') else f"{position.symbol}_{position.broker}"
        if not hasattr(self, '_broker_stop_locks'):
            self._broker_stop_locks = {}
        if pos_key not in self._broker_stop_locks:
            import asyncio as _aio
            self._broker_stop_locks[pos_key] = _aio.Lock()
        async with self._broker_stop_locks[pos_key]:
            qty = int(position.quantity)
            symbol = getattr(cache, 'raw_symbol', None) or getattr(position, 'raw_symbol', None) or position.symbol
            asset_type = getattr(position, 'asset', 'stock')
            is_option = asset_type.lower() in ('option', 'options')

            _allows_sl = getattr(channel_settings, 'allows_broker_sl', True)
            _allows_pt = getattr(channel_settings, 'allows_broker_pt', True)
            sl_price = round(entry_price * (1 - sl_pct / 100), 4) if sl_pct > 0 and _allows_sl else None
            if cache.dynamic_sl_price and cache.dynamic_sl_price > 0 and _allows_sl:
                if sl_price is None or cache.dynamic_sl_price > sl_price:
                    sl_price = round(cache.dynamic_sl_price, 4)
            pt1_price = round(entry_price * (1 + pt1_pct / 100), 4) if pt1_pct > 0 and _allows_pt else None
            if not sl_price and not pt1_price:
                print(f"[RISK] ⏭ Broker bracket mode '{_bbm}' — no orders to place for {position.symbol}")
                cache.broker_orders_placed = True
                return

            from src.risk.risk_engine import calculate_tier_quantities
            enabled_tiers = []
            for tier, attr in [(1, 'profit_target_1_pct'), (2, 'profit_target_2_pct'),
                               (3, 'profit_target_3_pct'), (4, 'profit_target_4_pct')]:
                pct = getattr(channel_settings, attr, 0) or 0
                if pct > 0:
                    enabled_tiers.append(tier)

            leave_runner = channel_settings.leave_runner_pct if channel_settings.leave_runner_enabled else 0
            escalation_only = getattr(channel_settings, 'escalation_only_mode', False)

            custom_qtys = {t: getattr(channel_settings, f'profit_target_qty_{t}', None) for t in enabled_tiers}
            custom_trim_pcts = {t: getattr(channel_settings, f'profit_target_trim_pct_{t}', None) for t in enabled_tiers}
            tier_qtys = calculate_tier_quantities(qty, leave_runner, enabled_tiers, custom_qtys, custom_trim_pcts) if not escalation_only else {}
            pt1_qty = tier_qtys.get(_target_tier, 0) if not escalation_only else 0

            _sl_display = f"${sl_price:.2f}" if sl_price else "N/A"
            _pt1_display = f"${pt1_price:.2f}" if pt1_price else "N/A"
            _bracket_exit_mode = getattr(channel_settings, 'exit_strategy_mode', 'unknown')
            _tier_label = f"PT{_target_tier}" if _target_tier > 1 else "PT1"
            print(f"[RISK] 📋 PROGRESSIVE BRACKET: {position.symbol} entry=${entry_price:.2f} "
                  f"SL={_sl_display} {_tier_label}={_pt1_display} (qty={qty}, {_tier_label.lower()}_qty={pt1_qty}) broker={broker_name} exit_mode={_bracket_exit_mode}")

            if not sl_price and (not pt1_price or pt1_qty <= 0):
                _reasons = []
                if not sl_price and _allows_sl:
                    _reasons.append("no SL level")
                elif not _allows_sl:
                    _reasons.append(f"SL excluded by mode '{_bbm}'")
                if escalation_only:
                    _reasons.append("escalation-only (no PT trim)")
                elif not pt1_price:
                    _reasons.append(f"PT excluded by mode '{_bbm}'")
                print(f"[RISK] ⏭ No bracket orders to place for {position.symbol}: {', '.join(_reasons)} — risk engine manages exits")
                cache.broker_orders_placed = True
                return

            if broker_name == 'SCHWAB' and self.schwab_broker:
                try:
                    if not self.schwab_broker.is_authenticated():
                        print(f"[RISK] ⚠️ Schwab not authenticated, skip initial bracket")
                        return

                    if hasattr(self.schwab_broker, '_cancel_conflicting_sell_orders'):
                        try:
                            await self.schwab_broker._cancel_conflicting_sell_orders(symbol, 'OPTION' if is_option else 'EQUITY')
                        except Exception as _cc_err:
                            print(f"[RISK] ⚠️ Pre-bracket cancel for {symbol} failed: {_cc_err}")

                    _asset_type = 'OPTION' if is_option else 'EQUITY'
                    _schwab_stop_symbol = symbol
                    if is_option and hasattr(self.schwab_broker, '_build_option_symbol'):
                        _opt_expiry = getattr(position, 'expiry', '') or ''
                        _opt_strike = getattr(position, 'strike', 0) or 0
                        _opt_dir = (getattr(position, 'direction', '') or 'C').upper()
                        _opt_cp = 'C' if _opt_dir in ('C', 'CALL') else 'P'
                        try:
                            from datetime import datetime as _dt
                            if '/' in _opt_expiry:
                                _parts = _opt_expiry.split('/')
                                if len(_parts) == 2:
                                    _m, _d = _parts
                                    _opt_expiry_fmt = f"{_dt.now().year}-{int(_m):02d}-{int(_d):02d}"
                                elif len(_parts) == 3:
                                    _m, _d, _y = _parts
                                    if len(_y) == 2:
                                        _y = f"20{_y}"
                                    _opt_expiry_fmt = f"{_y}-{int(_m):02d}-{int(_d):02d}"
                                else:
                                    _opt_expiry_fmt = _opt_expiry
                            elif len(_opt_expiry) == 10 and '-' in _opt_expiry:
                                _opt_expiry_fmt = _opt_expiry
                            else:
                                _opt_expiry_fmt = _opt_expiry
                            _schwab_stop_symbol = self.schwab_broker._build_option_symbol(
                                position.symbol, _opt_expiry_fmt, _opt_strike, _opt_cp
                            )
                            if 'INVALID_EXPIRY' in _schwab_stop_symbol:
                                print(f"[RISK] ⚠️ Schwab OCC build returned invalid: {_schwab_stop_symbol} — skipping option stop order")
                                _schwab_stop_symbol = None
                            else:
                                print(f"[RISK] 📐 Schwab option SL: built OCC symbol {_schwab_stop_symbol}")
                        except Exception as _occ_err:
                            print(f"[RISK] ⚠️ Schwab OCC build failed: {_occ_err} — skipping option stop order")
                            _schwab_stop_symbol = None

                    _trim_mode = getattr(channel_settings, 'trim_order_mode', 'limit') or 'limit'
                    _use_oco = sl_price and sl_price > 0 and pt1_price and pt1_price > 0 and pt1_qty > 0 and not is_option and _trim_mode != 'market'
                    _remainder_qty = qty - pt1_qty if pt1_qty > 0 else qty
                    if _trim_mode == 'market' and sl_price and sl_price > 0:
                        print(f"[RISK] 📋 trim_order_mode='market' — skipping OCO, risk engine will handle PT sells")

                    if _use_oco and _schwab_stop_symbol:
                        oco_result = await self.schwab_broker.place_oco_order(
                            symbol=_schwab_stop_symbol,
                            quantity=pt1_qty,
                            stop_loss_price=sl_price,
                            profit_target_price=pt1_price,
                            side='sell',
                            asset_type=_asset_type
                        )
                        if oco_result and oco_result.success and oco_result.order_id:
                            cache.broker_oco_order_id = str(oco_result.order_id)
                            cache.broker_oco_sl_price = sl_price
                            cache.broker_oco_pt_price = pt1_price
                            cache.broker_oco_qty = pt1_qty
                            cache.broker_pt_order_id = str(oco_result.order_id)
                            cache.broker_pt_tier = _target_tier
                            print(f"[RISK] ✅ Schwab OCO placed: #{oco_result.order_id} SL=${sl_price:.2f} PT{_target_tier}=${pt1_price:.2f} (qty={pt1_qty})")
                        else:
                            msg = getattr(oco_result, 'message', 'unknown') if oco_result else 'no result'
                            print(f"[RISK] ⚠️ Schwab OCO order failed: {msg} — falling back to separate orders")
                            _use_oco = False

                        if _use_oco and _remainder_qty > 0 and _schwab_stop_symbol:
                            sl_result = await self.schwab_broker.place_stop_order(
                                symbol=_schwab_stop_symbol,
                                quantity=_remainder_qty,
                                stop_price=sl_price,
                                side='sell',
                                asset_type=_asset_type,
                                duration='GOOD_TILL_CANCEL'
                            )
                            if sl_result and sl_result.success and sl_result.order_id:
                                cache.broker_stop_order_id = str(sl_result.order_id)
                                print(f"[RISK] ✅ Schwab standalone SL placed: #{sl_result.order_id} at ${sl_price:.2f} (qty={_remainder_qty})")
                            else:
                                msg = getattr(sl_result, 'message', 'unknown') if sl_result else 'no result'
                                print(f"[RISK] ⚠️ Schwab standalone SL failed: {msg}")

                    if not _use_oco:
                        if sl_price and sl_price > 0 and _schwab_stop_symbol:
                            sl_result = await self.schwab_broker.place_stop_order(
                                symbol=_schwab_stop_symbol,
                                quantity=qty,
                                stop_price=sl_price,
                                side='sell_to_close' if is_option else 'sell',
                                asset_type=_asset_type,
                                duration='GOOD_TILL_CANCEL'
                            )
                            if sl_result and sl_result.success and sl_result.order_id:
                                cache.broker_stop_order_id = str(sl_result.order_id)
                                print(f"[RISK] ✅ Broker SL placed: Schwab stop #{sl_result.order_id} at ${sl_price:.2f} (qty={qty})")
                            else:
                                msg = getattr(sl_result, 'message', 'unknown') if sl_result else 'no result'
                                print(f"[RISK] ⚠️ Schwab SL order failed: {msg}")

                        if pt1_price and pt1_price > 0 and pt1_qty > 0:
                            pt_result = await self.schwab_broker.place_option_order(
                                symbol=position.symbol,
                                strike=position.strike,
                                expiry=position.expiry,
                                option_type=position.direction or 'C',
                                action='STC',
                                quantity=pt1_qty,
                                price=pt1_price,
                                _skip_cancel_check=True
                            ) if is_option else await self.schwab_broker.place_stock_order(
                                symbol=symbol,
                                action='STC',
                                quantity=pt1_qty,
                                price=pt1_price,
                                _skip_cancel_check=True
                            )
                            if pt_result and pt_result.success and pt_result.order_id:
                                cache.broker_pt_order_id = str(pt_result.order_id)
                                cache.broker_pt_tier = _target_tier
                                print(f"[RISK] ✅ Broker PT{_target_tier} placed: Schwab limit #{pt_result.order_id} at ${pt1_price:.2f} (qty={pt1_qty})")
                                await self._register_pt_with_chaser(str(pt_result.order_id), broker_name, position, cache, pt1_qty, pt1_price, is_option)
                            else:
                                msg = getattr(pt_result, 'message', 'unknown') if pt_result else 'no result'
                                print(f"[RISK] ⚠️ Schwab PT{_target_tier} order failed: {msg}")

                    if cache.broker_stop_order_id or cache.broker_pt_order_id or cache.broker_oco_order_id:
                        cache.broker_orders_placed = True

                except Exception as e:
                    print(f"[RISK] ⚠️ Schwab initial bracket error: {e}")

            elif broker_name in ('ALPACA', 'ALPACA_PAPER', 'ALPACA_LIVE') and self.alpaca_broker:
                try:
                    if not getattr(self.alpaca_broker, 'connected', False):
                        print(f"[RISK] ⚠️ Alpaca not connected, skip initial bracket")
                        return

                    if hasattr(self.alpaca_broker, 'trading_client'):
                        from alpaca.trading.requests import StopOrderRequest, LimitOrderRequest
                        from alpaca.trading.enums import OrderSide, TimeInForce, PositionIntent

                        _alpaca_index_syms = {'SPX', 'SPXW', 'NDX', 'NDXP', 'RUT', 'RUTW', 'VIX', 'VIXW', 'XSP', 'DJX'}
                        _alpaca_underlying = (getattr(position, 'symbol', '') or symbol).upper().strip()
                        if is_option and _alpaca_underlying in _alpaca_index_syms:
                            print(f"[RISK] ⚠️ Alpaca does not support index options ({symbol}) — bracket placement skipped")
                            cache.broker_orders_placed = True
                            return

                        _alpaca_tif = TimeInForce.DAY if is_option else TimeInForce.GTC
                        _alpaca_intent = PositionIntent.SELL_TO_CLOSE if is_option else None
                        if sl_price and sl_price > 0:
                            _alpaca_sl = round(sl_price, 2)
                            _sl_kwargs = dict(
                                symbol=symbol,
                                qty=qty,
                                side=OrderSide.SELL,
                                stop_price=_alpaca_sl,
                                time_in_force=_alpaca_tif
                            )
                            if _alpaca_intent:
                                _sl_kwargs['position_intent'] = _alpaca_intent
                            sl_req = StopOrderRequest(**_sl_kwargs)
                            sl_order = self.alpaca_broker.trading_client.submit_order(sl_req)
                            if sl_order and sl_order.id:
                                cache.broker_stop_order_id = str(sl_order.id)
                                print(f"[RISK] ✅ Broker SL placed: Alpaca stop #{sl_order.id} at ${sl_price:.2f} (qty={qty})")

                        if pt1_price and pt1_price > 0 and pt1_qty > 0:
                            _alpaca_pt = round(pt1_price, 2)
                            _pt_kwargs = dict(
                                symbol=symbol,
                                qty=pt1_qty,
                                side=OrderSide.SELL,
                                limit_price=_alpaca_pt,
                                time_in_force=_alpaca_tif
                            )
                            if _alpaca_intent:
                                _pt_kwargs['position_intent'] = _alpaca_intent
                            pt_req = LimitOrderRequest(**_pt_kwargs)
                            pt_order = self.alpaca_broker.trading_client.submit_order(pt_req)
                            if pt_order and pt_order.id:
                                cache.broker_pt_order_id = str(pt_order.id)
                                cache.broker_pt_tier = _target_tier
                                print(f"[RISK] ✅ Broker PT1 placed: Alpaca limit #{pt_order.id} at ${pt1_price:.2f} (qty={pt1_qty})")
                                await self._register_pt_with_chaser(str(pt_order.id), broker_name, position, cache, pt1_qty, pt1_price, is_option)

                        if cache.broker_stop_order_id or cache.broker_pt_order_id:
                            cache.broker_orders_placed = True
                except Exception as e:
                    print(f"[RISK] ⚠️ Alpaca initial bracket error: {e}")

            elif 'IBKR' in broker_name and self.ibkr_broker:
                try:
                    if not self.ibkr_broker.ib.isConnected():
                        print(f"[RISK] ⚠️ IBKR not connected, skip initial bracket")
                        return

                    from ib_insync import StopOrder, LimitOrder as IBLimitOrder, Stock as IBStock, Option as IBOption

                    if is_option:
                        expiry_fmt = self.ibkr_broker._normalize_expiry_yyyymmdd(position.expiry or '')
                        right = 'C' if (position.direction or '').upper() in ('C', 'CALL') else 'P'
                        contract = IBOption(position.symbol, expiry_fmt, position.strike, right, 'SMART')
                    else:
                        contract = IBStock(symbol, 'SMART', 'USD')
                    await self.ibkr_broker.ib.qualifyContractsAsync(contract)

                    _ibkr_ok_statuses = ('Submitted', 'PreSubmitted', 'PendingSubmit', 'Filled', 'ApiPending')
                    _ibkr_sl = sl_price
                    _ibkr_pt1 = pt1_price
                    if is_option:
                        if _ibkr_sl and _ibkr_sl > 0:
                            _ibkr_sl = _round_to_cboe_increment(_ibkr_sl, is_sell=True, is_stop_trigger=True)
                            if _ibkr_sl != sl_price:
                                print(f"[RISK] 📐 IBKR option SL CBOE snap: ${sl_price:.2f} → ${_ibkr_sl:.2f} (stop trigger: round up)")
                        if _ibkr_pt1 and _ibkr_pt1 > 0:
                            _ibkr_pt1 = _round_to_cboe_increment(_ibkr_pt1, is_sell=True)
                            if _ibkr_pt1 != pt1_price:
                                print(f"[RISK] 📐 IBKR option PT1 CBOE snap: ${pt1_price:.2f} → ${_ibkr_pt1:.2f}")

                    _ibkr_oca_group = None
                    _both_legs = (_ibkr_sl and _ibkr_sl > 0) and (_ibkr_pt1 and _ibkr_pt1 > 0 and pt1_qty > 0)
                    if _both_legs:
                        import time as _oca_time
                        _ibkr_oca_group = f"BT_{symbol}_{int(_oca_time.time())}"

                    if _ibkr_sl and _ibkr_sl > 0:
                        sl_order = StopOrder('SELL', qty, _ibkr_sl)
                        sl_order.tif = 'GTC'
                        sl_order.outsideRth = self.ibkr_broker._get_extended_hours_enabled()
                        if _ibkr_oca_group:
                            sl_order.ocaGroup = _ibkr_oca_group
                            sl_order.ocaType = 2
                        sl_trade = self.ibkr_broker.ib.placeOrder(contract, sl_order)
                        await asyncio.sleep(1)
                        if sl_trade and sl_trade.orderStatus.status in _ibkr_ok_statuses:
                            cache.broker_stop_order_id = str(sl_trade.order.orderId)
                            print(f"[RISK] ✅ Broker SL placed: IBKR stop #{sl_trade.order.orderId} at ${_ibkr_sl:.2f} (qty={qty}) [GTC{', OCA=' + _ibkr_oca_group if _ibkr_oca_group else ''}]")
                        else:
                            print(f"[RISK] ⚠️ IBKR SL order failed: {sl_trade.orderStatus.status if sl_trade else 'no trade'}")

                    if _ibkr_pt1 and _ibkr_pt1 > 0 and pt1_qty > 0:
                        pt_order = IBLimitOrder('SELL', pt1_qty, _ibkr_pt1)
                        pt_order.tif = 'GTC'
                        pt_order.outsideRth = self.ibkr_broker._get_extended_hours_enabled()
                        if _ibkr_oca_group:
                            pt_order.ocaGroup = _ibkr_oca_group
                            pt_order.ocaType = 2
                        pt_trade = self.ibkr_broker.ib.placeOrder(contract, pt_order)
                        await asyncio.sleep(1)
                        if pt_trade and pt_trade.orderStatus.status in _ibkr_ok_statuses:
                            cache.broker_pt_order_id = str(pt_trade.order.orderId)
                            cache.broker_pt_tier = _target_tier
                            cache.broker_oco_order_id = _ibkr_oca_group
                            print(f"[RISK] ✅ Broker PT1 placed: IBKR limit #{pt_trade.order.orderId} at ${pt1_price:.2f} (qty={pt1_qty}) [GTC{', OCA=' + _ibkr_oca_group if _ibkr_oca_group else ''}]")
                            await self._register_pt_with_chaser(str(pt_trade.order.orderId), broker_name, position, cache, pt1_qty, pt1_price, is_option)
                        else:
                            print(f"[RISK] ⚠️ IBKR PT1 order failed: {pt_trade.orderStatus.status if pt_trade else 'no trade'}")

                    if cache.broker_stop_order_id or cache.broker_pt_order_id:
                        cache.broker_orders_placed = True
                except Exception as e:
                    print(f"[RISK] ⚠️ IBKR initial bracket error: {e}")

            elif 'TASTYTRADE' in broker_name and self.tastytrade_broker:
                try:
                    from tastytrade.instruments import Equity as TTEquity
                    from tastytrade.order import NewOrder as TTNewOrder, OrderAction as TTOrderAction, OrderTimeInForce as TTTIF, OrderType as TTOrderType
                    from decimal import Decimal as TTDecimal

                    if not self.tastytrade_broker._ensure_session_valid():
                        print(f"[RISK] ⚠️ TastyTrade session invalid, skip initial bracket")
                        return

                    if sl_price and sl_price > 0 and not is_option:
                        tt_equity = await _await_if_needed(
                            await asyncio.to_thread(TTEquity.get, self.tastytrade_broker.session, symbol)
                        )
                        sl_leg = tt_equity.build_leg(TTDecimal(str(qty)), TTOrderAction.SELL_TO_CLOSE)
                        sl_tt_order = TTNewOrder(
                            time_in_force=TTTIF.GTC,
                            order_type=TTOrderType.STOP,
                            legs=[sl_leg],
                            stop_trigger=TTDecimal(str(sl_price))
                        )
                        sl_resp = await _await_if_needed(
                            await asyncio.to_thread(
                                self.tastytrade_broker.account.place_order,
                                self.tastytrade_broker.session, sl_tt_order, dry_run=False
                            )
                        )
                        if sl_resp and hasattr(sl_resp, 'order') and sl_resp.order:
                            cache.broker_stop_order_id = str(sl_resp.order.id)
                            print(f"[RISK] ✅ Broker SL placed: TastyTrade stop #{sl_resp.order.id} at ${sl_price:.2f} (qty={qty})")
                        else:
                            print(f"[RISK] ⚠️ TastyTrade SL order submitted but no order ID returned — cannot track for cancel")

                    if sl_price and sl_price > 0 and is_option:
                        _tt_sl = _round_to_cboe_increment(sl_price, is_sell=True)
                        if _tt_sl != sl_price:
                            print(f"[RISK] 📐 TastyTrade option SL CBOE snap: ${sl_price:.2f} → ${_tt_sl:.2f}")
                        sl_result = await self.tastytrade_broker.place_option_order(
                            symbol=position.symbol,
                            strike=position.strike,
                            expiry=position.expiry or '',
                            option_type=position.direction or 'C',
                            action='STC',
                            quantity=qty,
                            price=_tt_sl
                        )
                        if sl_result and sl_result.success:
                            _sl_oid = getattr(sl_result, 'order_id', None)
                            if _sl_oid:
                                cache.broker_stop_order_id = str(_sl_oid)
                            print(f"[RISK] ✅ Broker SL placed: TastyTrade option limit #{_sl_oid or 'submitted'} at ${_tt_sl:.2f} (qty={qty}) [limit used - options don't support stop orders on TastyTrade]")
                        else:
                            msg = getattr(sl_result, 'message', 'unknown') if sl_result else 'no result'
                            print(f"[RISK] ⚠️ TastyTrade option SL order failed: {msg}")

                    if pt1_price and pt1_price > 0 and pt1_qty > 0:
                        if is_option:
                            _tt_pt = _round_to_cboe_increment(pt1_price, is_sell=True)
                            if _tt_pt != pt1_price:
                                print(f"[RISK] 📐 TastyTrade option PT1 CBOE snap: ${pt1_price:.2f} → ${_tt_pt:.2f}")
                            pt_result = await self.tastytrade_broker.place_option_order(
                                symbol=position.symbol,
                                strike=position.strike,
                                expiry=position.expiry or '',
                                option_type=position.direction or 'C',
                                action='STC',
                                quantity=pt1_qty,
                                price=_tt_pt
                            )
                        else:
                            pt_result = await self._place_tastytrade_stock_limit_gtc(
                                self.tastytrade_broker, symbol, pt1_qty, pt1_price, action='STC'
                            )
                        if pt_result and pt_result.success:
                            _pt_oid = getattr(pt_result, 'order_id', None)
                            if _pt_oid:
                                cache.broker_pt_order_id = str(_pt_oid)
                            cache.broker_pt_tier = _target_tier
                            print(f"[RISK] ✅ Broker PT1 placed: TastyTrade limit #{_pt_oid or 'submitted'} at ${pt1_price:.2f} (qty={pt1_qty}){' [GTC]' if not is_option else ' [DAY]'}")
                            if _pt_oid:
                                await self._register_pt_with_chaser(str(_pt_oid), broker_name, position, cache, pt1_qty, pt1_price, is_option)
                        else:
                            msg = getattr(pt_result, 'message', 'unknown') if pt_result else 'no result'
                            print(f"[RISK] ⚠️ TastyTrade PT1 order failed: {msg}")

                    if cache.broker_stop_order_id or cache.broker_pt_order_id:
                        cache.broker_orders_placed = True
                except Exception as e:
                    print(f"[RISK] ⚠️ TastyTrade initial bracket error: {e}")

            elif 'TRADING212' in broker_name and self.trading212_broker:
                try:
                    if not getattr(self.trading212_broker, 'connected', False):
                        print(f"[RISK] ⚠️ Trading212 not connected, skip initial bracket")
                        return
                    if not getattr(self.trading212_broker, '_instruments_ready', False):
                        print(f"[RISK] ⚠️ Trading212 instrument cache still loading, skip initial bracket — will retry on next cycle")
                        return

                    if is_option:
                        print(f"[RISK] ⚠️ Trading212 does not support options — bracket orders for stocks only")
                        cache.broker_orders_placed = True
                        return

                    if sl_price and sl_price > 0:
                        sl_result = await self.trading212_broker.place_stop_order(
                            symbol=symbol,
                            action='STC',
                            quantity=qty,
                            stop_price=sl_price
                        )
                        if sl_result and sl_result.success and sl_result.order_id:
                            cache.broker_stop_order_id = str(sl_result.order_id)
                            print(f"[RISK] ✅ Broker SL placed: Trading212 stop #{sl_result.order_id} at ${sl_price:.2f} (qty={qty})")
                        else:
                            msg = getattr(sl_result, 'message', 'unknown') if sl_result else 'no result'
                            print(f"[RISK] ⚠️ Trading212 SL order failed: {msg}")

                    if pt1_price and pt1_price > 0 and pt1_qty > 0:
                        pt_result = await self.trading212_broker.place_stock_order(
                            symbol=symbol,
                            action='STC',
                            quantity=pt1_qty,
                            price=pt1_price
                        )
                        if pt_result and pt_result.success and pt_result.order_id:
                            cache.broker_pt_order_id = str(pt_result.order_id)
                            cache.broker_pt_tier = _target_tier
                            print(f"[RISK] ✅ Broker PT1 placed: Trading212 limit #{pt_result.order_id} at ${pt1_price:.2f} (qty={pt1_qty})")
                            await self._register_pt_with_chaser(str(pt_result.order_id), broker_name, position, cache, pt1_qty, pt1_price, is_option)
                        else:
                            msg = getattr(pt_result, 'message', 'unknown') if pt_result else 'no result'
                            print(f"[RISK] ⚠️ Trading212 PT1 order failed: {msg}")

                    if cache.broker_stop_order_id or cache.broker_pt_order_id:
                        cache.broker_orders_placed = True
                except Exception as e:
                    print(f"[RISK] ⚠️ Trading212 initial bracket error: {e}")

            elif 'ROBINHOOD' in broker_name and self.robinhood_broker:
                try:
                    if not getattr(self.robinhood_broker, '_logged_in', False):
                        print(f"[RISK] ⚠️ Robinhood not logged in, skip initial bracket")
                        return

                    if sl_price and sl_price > 0 and not is_option:
                        sl_result = await self.robinhood_broker.place_stock_order(
                            symbol=symbol,
                            action='STC',
                            quantity=qty,
                            stop_price=sl_price
                        )
                        if sl_result and sl_result.success and sl_result.order_id:
                            cache.broker_stop_order_id = str(sl_result.order_id)
                            print(f"[RISK] ✅ Broker SL placed: Robinhood stop #{sl_result.order_id} at ${sl_price:.2f} (qty={qty})")
                        else:
                            msg = getattr(sl_result, 'message', 'unknown') if sl_result else 'no result'
                            print(f"[RISK] ⚠️ Robinhood SL order failed: {msg}")
                    elif sl_price and sl_price > 0 and is_option:
                        print(f"[RISK] ⚠️ Robinhood does not support stop orders for options — SL will be monitored locally")

                    if pt1_price and pt1_price > 0 and pt1_qty > 0:
                        if is_option:
                            pt_result = await self.robinhood_broker.place_option_order(
                                symbol=position.symbol,
                                strike=position.strike,
                                expiry=position.expiry or '',
                                option_type=position.direction or 'C',
                                action='STC',
                                quantity=pt1_qty,
                                price=pt1_price
                            )
                        else:
                            pt_result = await self.robinhood_broker.place_stock_order(
                                symbol=symbol,
                                action='STC',
                                quantity=pt1_qty,
                                price=pt1_price
                            )
                        if pt_result and pt_result.success and pt_result.order_id:
                            cache.broker_pt_order_id = str(pt_result.order_id)
                            cache.broker_pt_tier = _target_tier
                            print(f"[RISK] ✅ Broker PT1 placed: Robinhood limit #{pt_result.order_id} at ${pt1_price:.2f} (qty={pt1_qty})")
                            await self._register_pt_with_chaser(str(pt_result.order_id), broker_name, position, cache, pt1_qty, pt1_price, is_option)
                        else:
                            msg = getattr(pt_result, 'message', 'unknown') if pt_result else 'no result'
                            print(f"[RISK] ⚠️ Robinhood PT1 order failed: {msg}")

                    if cache.broker_stop_order_id or cache.broker_pt_order_id:
                        cache.broker_orders_placed = True
                except Exception as e:
                    print(f"[RISK] ⚠️ Robinhood initial bracket error: {e}")

            elif 'WEBULL' in broker_name and broker_instance:
                try:
                    _wb_client = getattr(broker_instance, '_client', None) or getattr(broker_instance, 'wb', None)
                    if not _wb_client:
                        print(f"[RISK] ⚠️ Webull not connected (no client), skip initial bracket")
                        return

                    _wb_tId = await asyncio.to_thread(self._resolve_webull_ticker_id, _wb_client, symbol)
                    if not _wb_tId:
                        print(f"[RISK] ⚠️ Webull ticker ID not found for {symbol}, skip initial bracket")
                        return

                    if sl_price and sl_price > 0 and not is_option:
                        _sl_price_r = round(sl_price, 4 if sl_price < 1.0 else 2)
                        _wb_sl_placed = False
                        for _ext_hrs in [True, False]:
                            def _wb_sl_order(_c=_wb_client, _s=symbol, _p=_sl_price_r, _q=qty, _t=_wb_tId, _eh=_ext_hrs):
                                return _c.place_order(
                                    stock=_s,
                                    tId=int(_t),
                                    stpPrice=_p,
                                    action='SELL',
                                    orderType='STP',
                                    enforce='GTC',
                                    quant=_q,
                                    outsideRegularTradingHour=_eh
                                )
                            sl_resp = await asyncio.to_thread(_wb_sl_order)
                            print(f"[RISK] [DEBUG] Webull SL response (extHrs={_ext_hrs}): {sl_resp}")
                            if sl_resp and not sl_resp.get('msg'):
                                _sl_oid = str(sl_resp.get('data', {}).get('orderId', '')) if isinstance(sl_resp.get('data'), dict) else str(sl_resp.get('orderId', ''))
                                if _sl_oid:
                                    cache.broker_stop_order_id = _sl_oid
                                    print(f"[RISK] ✅ Broker SL placed: Webull stop #{_sl_oid} at ${sl_price:.2f} (qty={qty})")
                                    _wb_sl_placed = True
                                    break
                            else:
                                _err = sl_resp.get('msg', 'unknown') if sl_resp else 'no response'
                                if _ext_hrs:
                                    print(f"[RISK] ⚠️ Webull SL failed (extHrs=True): {_err} — retrying with extHrs=False")
                                else:
                                    print(f"[RISK] ⚠️ Webull SL order failed: {_err} — SL will be monitored locally")
                        if not _wb_sl_placed:
                            import time as _time
                            _fail_count = getattr(cache, '_webull_stp_fail_count', 0) + 1
                            cache._webull_stp_fail_count = _fail_count
                            cache._webull_stp_last_fail_time = _time.time()
                            print(f"[RISK] ⚠️ Webull SL failed ({_fail_count}) — will retry on next cycle")
                    elif sl_price and sl_price > 0 and is_option:
                        print(f"[RISK] ⚠️ Webull does not support stop orders for options — SL will be monitored locally")

                    if pt1_price and pt1_price > 0 and pt1_qty > 0:
                        if is_option:
                            _wb_opt_id = self._resolve_webull_option_id(broker_instance, position)
                            if not _wb_opt_id:
                                print(f"[RISK] ⚠️ Webull PT1 skipped — could not resolve option_id for {position.symbol}")
                            else:
                                pt_result = await broker_instance.place_option_order(
                                    symbol=position.symbol,
                                    strike=position.strike,
                                    expiry=position.expiry or '',
                                    option_type=position.direction or 'C',
                                    action='STC',
                                    quantity=pt1_qty,
                                    price=pt1_price,
                                    option_id=_wb_opt_id
                                )
                                if pt_result and pt_result.success and pt_result.order_id:
                                    cache.broker_pt_order_id = str(pt_result.order_id)
                                    cache.broker_pt_tier = _target_tier
                                    print(f"[RISK] ✅ Broker PT1 placed: Webull option limit #{pt_result.order_id} at ${pt1_price:.2f} (qty={pt1_qty})")
                                    await self._register_pt_with_chaser(str(pt_result.order_id), broker_name, position, cache, pt1_qty, pt1_price, is_option)
                                else:
                                    msg = getattr(pt_result, 'message', 'unknown') if pt_result else 'no result'
                                    print(f"[RISK] ⚠️ Webull PT1 option order failed: {msg}")
                        else:
                            _pt_price_r = round(pt1_price, 4 if pt1_price < 1.0 else 2)
                            def _wb_pt_order(_c=_wb_client, _s=symbol, _p=_pt_price_r, _q=pt1_qty, _t=_wb_tId):
                                return _c.place_order(
                                    stock=_s,
                                    tId=int(_t),
                                    price=_p,
                                    action='SELL',
                                    orderType='LMT',
                                    enforce='GTC',
                                    quant=_q,
                                    outsideRegularTradingHour=True
                                )
                            pt_resp = await asyncio.to_thread(_wb_pt_order)
                            print(f"[RISK] [DEBUG] Webull PT1 response: {pt_resp}")
                            if pt_resp and not pt_resp.get('msg'):
                                _pt_oid = str(pt_resp.get('data', {}).get('orderId', '')) if isinstance(pt_resp.get('data'), dict) else str(pt_resp.get('orderId', ''))
                                if not _pt_oid:
                                    _pt_oid = str(pt_resp.get('orderId', ''))
                                if _pt_oid:
                                    cache.broker_pt_order_id = _pt_oid
                                    cache.broker_pt_tier = _target_tier
                                    print(f"[RISK] ✅ Broker PT1 placed: Webull limit #{_pt_oid} at ${pt1_price:.2f} (qty={pt1_qty})")
                                    await self._register_pt_with_chaser(_pt_oid, broker_name, position, cache, pt1_qty, pt1_price, is_option)
                                else:
                                    print(f"[RISK] ⚠️ Webull PT1 placed but no orderId in response: {pt_resp}")
                            else:
                                print(f"[RISK] ⚠️ Webull PT1 order failed: {pt_resp.get('msg', 'unknown') if pt_resp else 'no response'}")

                    if cache.broker_stop_order_id or cache.broker_pt_order_id:
                        cache.broker_orders_placed = True
                except Exception as e:
                    print(f"[RISK] ⚠️ Webull initial bracket error: {e}")

    async def _place_next_pt_bracket(self, position, cache, channel_settings, completed_tier: int):
        if not hasattr(self, '_broker_stop_locks'):
            self._broker_stop_locks = {}
        pos_key = getattr(position, 'position_key', '') or f"{position.broker}_{position.symbol}"
        if pos_key not in self._broker_stop_locks:
            import asyncio
            self._broker_stop_locks[pos_key] = asyncio.Lock()
        async with self._broker_stop_locks[pos_key]:
            if cache.broker_pt_tier >= completed_tier + 1:
                return
            if cache.closing:
                print(f"[RISK] ⏭️ Skipping PT cascade — position is closing")
                return
            await self._place_next_pt_bracket_inner(position, cache, channel_settings, completed_tier)

        if (cache.broker_stop_order_id or cache.broker_oco_order_id) and not cache.closing:
            _current_sl = cache.dynamic_sl_price or cache.early_stop_price or cache.stop_loss_price
            if _current_sl and _current_sl > 0:
                _oco_covers_all = (cache.broker_oco_sl_price and abs(cache.broker_oco_sl_price - _current_sl) < 0.005
                                   and cache.broker_oco_qty >= int(position.quantity))
                if _oco_covers_all:
                    pass
                else:
                    print(f"[RISK] 📋 PROGRESSIVE: Resizing broker stop after PT{completed_tier} fill — syncing to remaining qty at ${_current_sl:.2f}")
                    self._enqueue_broker_op(pos_key, 'RESIZE_STOP', 15,
                        lambda _p=position, _c=cache, _sp=_current_sl: self._sync_stop_to_broker(_p, _c, _sp))

    async def _place_next_pt_bracket_inner(self, position, cache, channel_settings, completed_tier: int, _retry_count: int = 0):
        if not getattr(channel_settings, 'allows_broker_pt', False):
            print(f"[RISK] ⏭ Broker bracket mode '{getattr(channel_settings, 'broker_bracket_mode', 'none')}' — skipping PT{completed_tier + 1} broker order for {position.symbol}")
            return

        broker_name = position.broker.upper() if hasattr(position, 'broker') else ''
        broker_instance = self._get_broker_instance_for_bracket(broker_name)
        if not broker_instance:
            return

        entry_price = cache.entry_price
        if entry_price <= 0:
            return

        next_tier = completed_tier + 1
        pt_attr = f'profit_target_{next_tier}_pct'
        next_pt_pct = getattr(channel_settings, pt_attr, 0) or 0
        if next_pt_pct <= 0:
            print(f"[RISK] 📋 PROGRESSIVE: PT{completed_tier} complete, no PT{next_tier} configured — SL protection only")
            return

        next_pt_price = round(entry_price * (1 + next_pt_pct / 100), 4)

        _trim_mode = getattr(channel_settings, 'trim_order_mode', 'limit') or 'limit'
        if _trim_mode == 'market':
            print(f"[RISK] 📋 PROGRESSIVE: PT{next_tier} skipped — trim_order_mode is 'market', risk engine will handle exit")
            return

        from src.risk.risk_engine import calculate_tier_quantities
        enabled_tiers = []
        for tier, attr in [(1, 'profit_target_1_pct'), (2, 'profit_target_2_pct'),
                           (3, 'profit_target_3_pct'), (4, 'profit_target_4_pct')]:
            pct = getattr(channel_settings, attr, 0) or 0
            if pct > 0:
                enabled_tiers.append(tier)

        qty = cache.original_qty or int(position.quantity)
        leave_runner = channel_settings.leave_runner_pct if channel_settings.leave_runner_enabled else 0
        escalation_only = getattr(channel_settings, 'escalation_only_mode', False)

        custom_qtys = {t: getattr(channel_settings, f'profit_target_qty_{t}', None) for t in enabled_tiers}
        custom_trim_pcts = {t: getattr(channel_settings, f'profit_target_trim_pct_{t}', None) for t in enabled_tiers}
        tier_qtys = calculate_tier_quantities(qty, leave_runner, enabled_tiers, custom_qtys, custom_trim_pcts) if not escalation_only else {}
        next_qty = tier_qtys.get(next_tier, 0) if not escalation_only else 0

        if next_qty <= 0:
            print(f"[RISK] 📋 PROGRESSIVE: PT{next_tier} qty=0, skipping broker order")
            return

        remaining_qty = int(position.quantity)
        if next_qty > remaining_qty:
            next_qty = remaining_qty
        if next_qty <= 0:
            print(f"[RISK] ⏭ PROGRESSIVE: Remaining qty insufficient for PT{next_tier} — skipping")
            return

        symbol = getattr(cache, 'raw_symbol', None) or getattr(position, 'raw_symbol', None) or position.symbol
        asset_type = getattr(position, 'asset', 'stock')
        is_option = asset_type.lower() in ('option', 'options')

        print(f"[RISK] 📋 PROGRESSIVE: Placing PT{next_tier} at ${next_pt_price:.2f} (qty={next_qty}) after PT{completed_tier} fill")

        if broker_name == 'SCHWAB' and self.schwab_broker:
            try:
                if not self.schwab_broker.is_authenticated():
                    return

                if cache.broker_pt_order_id:
                    if cache.broker_pt_order_id != cache.broker_oco_order_id:
                        try:
                            await self.schwab_broker.cancel_order(cache.broker_pt_order_id)
                        except Exception:
                            pass
                    cache.broker_pt_order_id = None

                _current_sl = cache.dynamic_sl_price or cache.early_stop_price or cache.stop_loss_price
                _cascade_trim_mode = getattr(channel_settings, 'trim_order_mode', 'limit') or 'limit'
                _use_oco = _current_sl and _current_sl > 0 and not is_option and _cascade_trim_mode != 'market'
                if _cascade_trim_mode == 'market' and _current_sl:
                    print(f"[RISK] 📋 CASCADE: trim_order_mode='market' — skipping OCO, using standalone limit for PT{next_tier}")

                if _use_oco:
                    if cache.broker_oco_order_id:
                        _old_oco_id = cache.broker_oco_order_id
                        _cancel_res = await self.schwab_broker.cancel_order(cache.broker_oco_order_id)
                        if _cancel_res.get('success'):
                            print(f"[RISK] 🔄 Cancelled old OCO #{cache.broker_oco_order_id} for cascade")
                            _oco_status = await self.schwab_broker.get_order_status(_old_oco_id)
                            if _oco_status and _oco_status.get('status') == 'filled':
                                print(f"[RISK] ⚠️ OCO #{_old_oco_id} was FILLED during cancel — skipping cascade to prevent double-sell")
                                cache.broker_oco_order_id = None
                                cache.broker_oco_sl_price = None
                                cache.broker_oco_pt_price = None
                                cache.broker_oco_qty = 0
                                return
                        else:
                            _cmsg = _cancel_res.get('message', '')
                            if '404' in _cmsg or '400' in _cmsg or '409' in _cmsg:
                                print(f"[RISK] 🔄 Old OCO #{cache.broker_oco_order_id} already dead ({_cmsg}) — proceeding with cascade")
                            else:
                                print(f"[RISK] ⚠️ OCO cancel failed: {_cmsg} — aborting cascade to prevent double-sell")
                                return
                        if cache.broker_stop_order_id == _old_oco_id:
                            cache.broker_stop_order_id = None
                        cache.broker_oco_order_id = None
                        cache.broker_oco_sl_price = None
                        cache.broker_oco_pt_price = None
                        cache.broker_oco_qty = 0

                    oco_result = await self.schwab_broker.place_oco_order(
                        symbol=symbol,
                        quantity=next_qty,
                        stop_loss_price=_current_sl,
                        profit_target_price=next_pt_price,
                        side='sell',
                        asset_type='EQUITY'
                    )
                    if oco_result and oco_result.success and oco_result.order_id:
                        cache.broker_oco_order_id = str(oco_result.order_id)
                        cache.broker_oco_sl_price = _current_sl
                        cache.broker_oco_pt_price = next_pt_price
                        cache.broker_oco_qty = next_qty
                        cache.broker_pt_order_id = str(oco_result.order_id)
                        cache.broker_pt_tier = next_tier
                        print(f"[RISK] ✅ Schwab OCO PT{next_tier}: #{oco_result.order_id} SL=${_current_sl:.2f} PT=${next_pt_price:.2f} (qty={next_qty})")
                    else:
                        msg = getattr(oco_result, 'message', 'unknown') if oco_result else 'no result'
                        print(f"[RISK] ⚠️ Schwab OCO PT{next_tier} failed: {msg} — falling back to limit order")
                        _use_oco = False

                if not _use_oco:
                    pt_result = await self.schwab_broker.place_option_order(
                        symbol=position.symbol,
                        strike=position.strike,
                        expiry=position.expiry,
                        option_type=position.direction or 'C',
                        action='STC',
                        quantity=next_qty,
                        price=next_pt_price,
                        _skip_cancel_check=True
                    ) if is_option else await self.schwab_broker.place_stock_order(
                        symbol=symbol,
                        action='STC',
                        quantity=next_qty,
                        price=next_pt_price,
                        _skip_cancel_check=True
                    )
                    if pt_result and pt_result.success and pt_result.order_id:
                        cache.broker_pt_order_id = str(pt_result.order_id)
                        cache.broker_pt_tier = next_tier
                        print(f"[RISK] ✅ Broker PT{next_tier} placed: Schwab limit #{pt_result.order_id} at ${next_pt_price:.2f} (qty={next_qty})")
                        await self._register_pt_with_chaser(str(pt_result.order_id), broker_name, position, cache, next_qty, next_pt_price, is_option)
                    else:
                        msg = getattr(pt_result, 'message', 'unknown') if pt_result else 'no result'
                        print(f"[RISK] ⚠️ Schwab PT{next_tier} order failed: {msg}")
                        if _retry_count < 2:
                            import asyncio
                            await asyncio.sleep(1)
                            return await self._place_next_pt_bracket_inner(position, cache, channel_settings, completed_tier, _retry_count + 1)
            except Exception as e:
                print(f"[RISK] ⚠️ Schwab PT{next_tier} bracket error: {e}")
                if _retry_count < 2:
                    import asyncio
                    await asyncio.sleep(1)
                    return await self._place_next_pt_bracket_inner(position, cache, channel_settings, completed_tier, _retry_count + 1)

        elif broker_name in ('ALPACA', 'ALPACA_PAPER', 'ALPACA_LIVE') and self.alpaca_broker:
            try:
                if not getattr(self.alpaca_broker, 'connected', False):
                    return

                if cache.broker_pt_order_id:
                    try:
                        self.alpaca_broker.trading_client.cancel_order_by_id(cache.broker_pt_order_id)
                    except Exception:
                        pass
                    cache.broker_pt_order_id = None

                if hasattr(self.alpaca_broker, 'trading_client'):
                    from alpaca.trading.requests import LimitOrderRequest
                    from alpaca.trading.enums import OrderSide, TimeInForce
                    _alpaca_tif = TimeInForce.DAY if is_option else TimeInForce.GTC
                    pt_req = LimitOrderRequest(
                        symbol=symbol,
                        qty=next_qty,
                        side=OrderSide.SELL,
                        limit_price=next_pt_price,
                        time_in_force=_alpaca_tif
                    )
                    pt_order = self.alpaca_broker.trading_client.submit_order(pt_req)
                    if pt_order and pt_order.id:
                        cache.broker_pt_order_id = str(pt_order.id)
                        cache.broker_pt_tier = next_tier
                        print(f"[RISK] ✅ Broker PT{next_tier} placed: Alpaca limit #{pt_order.id} at ${next_pt_price:.2f} (qty={next_qty})")
                        await self._register_pt_with_chaser(str(pt_order.id), broker_name, position, cache, next_qty, next_pt_price, is_option)
                    else:
                        print(f"[RISK] ⚠️ Alpaca PT{next_tier} order returned no ID")
                        if _retry_count < 2:
                            import asyncio
                            await asyncio.sleep(1)
                            return await self._place_next_pt_bracket_inner(position, cache, channel_settings, completed_tier, _retry_count + 1)
            except Exception as e:
                print(f"[RISK] ⚠️ Alpaca PT{next_tier} bracket error: {e}")
                if _retry_count < 2:
                    import asyncio
                    await asyncio.sleep(1)
                    return await self._place_next_pt_bracket_inner(position, cache, channel_settings, completed_tier, _retry_count + 1)

        elif 'IBKR' in broker_name and self.ibkr_broker:
            try:
                if cache.broker_pt_order_id:
                    try:
                        _cancel_asset = 'option' if is_option else 'stock'
                        await self._cancel_single_order(broker_name, cache.broker_pt_order_id, broker_instance, asset_type=_cancel_asset)
                    except Exception:
                        pass
                    cache.broker_pt_order_id = None

                from ib_insync import LimitOrder as _IBLimitPT, Stock as _IBStockPT, Option as _IBOptionPT
                if is_option:
                    expiry_fmt = self.ibkr_broker._normalize_expiry_yyyymmdd(position.expiry or '')
                    right = 'C' if (position.direction or '').upper() in ('C', 'CALL') else 'P'
                    _pt_contract = _IBOptionPT(position.symbol, expiry_fmt, position.strike, right, 'SMART')
                else:
                    _pt_contract = _IBStockPT(symbol, 'SMART', 'USD')
                await self.ibkr_broker.ib.qualifyContractsAsync(_pt_contract)

                _pt_price_ibkr = next_pt_price
                if is_option:
                    _pt_price_ibkr = _round_to_cboe_increment(next_pt_price, is_sell=True)

                pt_order = _IBLimitPT('SELL', next_qty, _pt_price_ibkr)
                pt_order.tif = 'GTC'
                pt_order.outsideRth = self.ibkr_broker._get_extended_hours_enabled()
                _oca_group = cache.broker_oco_order_id
                if _oca_group and cache.broker_stop_order_id:
                    pt_order.ocaGroup = _oca_group
                    pt_order.ocaType = 2
                elif cache.broker_stop_order_id:
                    import time as _oca_time
                    _oca_group = f"BT_{symbol}_{int(_oca_time.time())}"
                    pt_order.ocaGroup = _oca_group
                    pt_order.ocaType = 2
                    cache.broker_oco_order_id = _oca_group

                pt_trade = self.ibkr_broker.ib.placeOrder(_pt_contract, pt_order)
                await asyncio.sleep(1)
                _ibkr_pt_ok = ('Submitted', 'PreSubmitted', 'PendingSubmit', 'Filled', 'ApiPending')
                if pt_trade and pt_trade.orderStatus.status in _ibkr_pt_ok:
                    cache.broker_pt_order_id = str(pt_trade.order.orderId)
                    cache.broker_pt_tier = next_tier
                    print(f"[RISK] ✅ Broker PT{next_tier} placed: IBKR limit #{pt_trade.order.orderId} at ${next_pt_price:.2f} (qty={next_qty}) [GTC, OCA={_oca_group or 'none'}]")
                    await self._register_pt_with_chaser(str(pt_trade.order.orderId), broker_name, position, cache, next_qty, next_pt_price, is_option)
                else:
                    print(f"[RISK] ⚠️ IBKR PT{next_tier} order failed: {pt_trade.orderStatus.status if pt_trade else 'no trade'}")
                    if _retry_count < 2:
                        await asyncio.sleep(1)
                        return await self._place_next_pt_bracket_inner(position, cache, channel_settings, completed_tier, _retry_count + 1)
            except Exception as e:
                print(f"[RISK] ⚠️ IBKR PT{next_tier} bracket error: {e}")
                if _retry_count < 2:
                    await asyncio.sleep(1)
                    return await self._place_next_pt_bracket_inner(position, cache, channel_settings, completed_tier, _retry_count + 1)

        else:
            try:
                if cache.broker_pt_order_id:
                    try:
                        _cancel_asset = 'option' if is_option else 'stock'
                        await self._cancel_single_order(broker_name, cache.broker_pt_order_id, broker_instance, asset_type=_cancel_asset)
                    except Exception:
                        pass
                    cache.broker_pt_order_id = None

                if is_option:
                    pt_result = await self._place_generic_pt_option(broker_name, broker_instance, position, next_qty, next_pt_price)
                else:
                    pt_result = await self._place_generic_pt_stock(broker_name, broker_instance, symbol, next_qty, next_pt_price)

                if pt_result and getattr(pt_result, 'success', False):
                    _pt_oid = getattr(pt_result, 'order_id', None) or f"{broker_name}_pt{next_tier}"
                    cache.broker_pt_order_id = str(_pt_oid)
                    cache.broker_pt_tier = next_tier
                    print(f"[RISK] ✅ Broker PT{next_tier} placed: {broker_name} limit #{_pt_oid} at ${next_pt_price:.2f} (qty={next_qty})")
                    await self._register_pt_with_chaser(str(_pt_oid), broker_name, position, cache, next_qty, next_pt_price, is_option)
                elif pt_result:
                    msg = getattr(pt_result, 'message', 'unknown')
                    print(f"[RISK] ⚠️ {broker_name} PT{next_tier} order failed: {msg}")
                    if _retry_count < 2:
                        await asyncio.sleep(1)
                        return await self._place_next_pt_bracket_inner(position, cache, channel_settings, completed_tier, _retry_count + 1)
            except Exception as e:
                print(f"[RISK] ⚠️ {broker_name} PT{next_tier} bracket error: {e}")
                if _retry_count < 2:
                    await asyncio.sleep(1)
                    return await self._place_next_pt_bracket_inner(position, cache, channel_settings, completed_tier, _retry_count + 1)

    async def _place_generic_pt_stock(self, broker_name, broker_instance, symbol, qty, price):
        if 'IBKR' in broker_name:
            return await broker_instance.place_stock_order(symbol=symbol, action='STC', quantity=qty, price=price)
        elif 'TASTYTRADE' in broker_name:
            return await self._place_tastytrade_stock_limit_gtc(broker_instance, symbol, qty, price, action='STC')
        elif 'TRADING212' in broker_name:
            return await broker_instance.place_stock_order(symbol=symbol, action='STC', quantity=qty, price=price)
        elif 'ROBINHOOD' in broker_name:
            return await broker_instance.place_stock_order(symbol=symbol, action='STC', quantity=qty, price=price)
        elif 'WEBULL' in broker_name:
            _wb_c = getattr(broker_instance, '_client', None) or getattr(broker_instance, 'wb', None)
            if not _wb_c:
                from src.broker_interface import OrderResult
                return OrderResult(success=False, message='Webull client not connected', symbol=symbol, action='STC')
            _wb_tid = await asyncio.to_thread(self._resolve_webull_ticker_id, _wb_c, symbol)
            if not _wb_tid:
                from src.broker_interface import OrderResult
                return OrderResult(success=False, message=f'Webull ticker ID not found for {symbol}', symbol=symbol, action='STC')
            _pt_p = round(price, 4 if price < 1.0 else 2)
            def _wb_pt(_c=_wb_c, _s=symbol, _p=_pt_p, _q=qty, _t=_wb_tid):
                return _c.place_order(
                    stock=_s, tId=int(_t), price=_p, action='SELL',
                    orderType='LMT', enforce='GTC', quant=_q,
                    outsideRegularTradingHour=True
                )
            resp = await asyncio.to_thread(_wb_pt)
            if resp and not resp.get('msg'):
                _oid = str(resp.get('orderId', ''))
                from src.broker_interface import OrderResult
                return OrderResult(success=True, order_id=_oid, symbol=symbol, action='STC', quantity=qty, price=price)
            else:
                from src.broker_interface import OrderResult
                return OrderResult(success=False, message=resp.get('msg', 'unknown') if resp else 'no response', symbol=symbol, action='STC')
        return None

    async def _place_generic_pt_option(self, broker_name, broker_instance, position, qty, price):
        if 'TRADING212' in broker_name:
            print(f"[RISK] ⚠️ Trading212 does not support options — PT cascade skipped")
            return None
        kwargs = dict(
            symbol=position.symbol,
            strike=position.strike,
            expiry=position.expiry or '',
            option_type=position.direction or 'C',
            action='STC',
            quantity=qty,
            price=price
        )
        if 'WEBULL' in broker_name:
            _wb_opt_id = self._resolve_webull_option_id(broker_instance, position)
            if not _wb_opt_id:
                print(f"[RISK] ⚠️ Webull PT cascade skipped — could not resolve option_id for {position.symbol}")
                return None
            kwargs['option_id'] = _wb_opt_id
        return await broker_instance.place_option_order(**kwargs)

    async def _cancel_single_order(self, broker_name, order_id, broker_instance=None, asset_type='stock'):
        if not order_id or str(order_id).startswith(('tt_', 'wb_')):
            return False
        broker_upper = broker_name.upper()
        result = None
        try:
            if broker_upper == 'SCHWAB' and self.schwab_broker:
                result = await self.schwab_broker.cancel_order(order_id)
            elif broker_upper in ('ALPACA', 'ALPACA_PAPER', 'ALPACA_LIVE') and self.alpaca_broker:
                if hasattr(self.alpaca_broker, 'trading_client'):
                    self.alpaca_broker.trading_client.cancel_order_by_id(order_id)
                    return True
                elif hasattr(self.alpaca_broker, 'cancel_order'):
                    result = await self.alpaca_broker.cancel_order(order_id)
            elif 'IBKR' in broker_upper and self.ibkr_broker:
                result = await self.ibkr_broker.cancel_order(order_id)
            elif 'TASTYTRADE' in broker_upper and self.tastytrade_broker:
                result = await self.tastytrade_broker.cancel_order(order_id)
            elif 'TRADING212' in broker_upper and self.trading212_broker:
                result = await self.trading212_broker.cancel_order(order_id)
            elif 'ROBINHOOD' in broker_upper and self.robinhood_broker:
                _rh_type = 'option' if asset_type.lower() in ('option', 'options') else 'stock'
                result = await self.robinhood_broker.cancel_order(order_id, order_type=_rh_type)
            elif 'WEBULL' in broker_upper and broker_instance:
                result = await broker_instance.cancel_order(order_id)
        except Exception as e:
            print(f"[RISK] ⚠️ Cancel order {order_id} on {broker_name} error: {e}")
            return False
        if isinstance(result, bool):
            return result
        if isinstance(result, dict):
            return result.get('success', False)
        return bool(result)

    async def _cancel_broker_bracket_orders(self, position, cache, cancel_stop=True, cancel_pt=True):
        if not hasattr(self, '_broker_stop_locks'):
            self._broker_stop_locks = {}
        pos_key = getattr(position, 'position_key', '') or f"{position.broker}_{position.symbol}"
        if pos_key not in self._broker_stop_locks:
            import asyncio
            self._broker_stop_locks[pos_key] = asyncio.Lock()
        async with self._broker_stop_locks[pos_key]:
            await self._cancel_broker_bracket_orders_inner(position, cache, cancel_stop=cancel_stop, cancel_pt=cancel_pt)

    async def _cancel_broker_bracket_orders_inner(self, position, cache, cancel_stop=True, cancel_pt=True):
        broker_name = position.broker.upper() if hasattr(position, 'broker') else ''
        asset_type = getattr(position, 'asset', 'stock')
        orders_to_cancel = []

        if cache.broker_oco_order_id:
            orders_to_cancel.append(('OCO', cache.broker_oco_order_id))

        if cancel_stop and cache.broker_stop_order_id:
            orders_to_cancel.append(('SL', cache.broker_stop_order_id))
        if cancel_pt and cache.broker_pt_order_id and cache.broker_pt_order_id != cache.broker_oco_order_id:
            orders_to_cancel.append((f'PT{cache.broker_pt_tier}', cache.broker_pt_order_id))

        if not orders_to_cancel:
            return

        print(f"[RISK] 🧹 Cancelling {len(orders_to_cancel)} outstanding bracket order(s) for {position.symbol}")

        broker_instance = self._get_broker_instance_for_bracket(broker_name)
        for label, order_id in orders_to_cancel:
            try:
                ok = await self._cancel_single_order(broker_name, order_id, broker_instance, asset_type=asset_type)
                if ok:
                    print(f"[RISK] ✅ Cancelled broker {label} order #{order_id}")
                else:
                    print(f"[RISK] ⚠️ Broker {label} order #{order_id} cancel returned failure (may already be filled/cancelled)")
            except Exception as e:
                print(f"[RISK] ⚠️ Failed to cancel broker {label} order #{order_id}: {e}")

        if cache.broker_oco_order_id:
            cache.broker_oco_order_id = None
            cache.broker_oco_sl_price = None
            cache.broker_oco_pt_price = None
            cache.broker_oco_qty = 0
        if cancel_stop:
            cache.broker_stop_order_id = None
        if cancel_pt:
            cache.broker_pt_order_id = None

    async def _sync_stop_to_broker(self, position, cache, new_stop_price: float):
        if not hasattr(self, '_broker_stop_locks'):
            self._broker_stop_locks = {}
        pos_key = getattr(position, 'position_key', '') or f"{position.broker}_{position.symbol}"
        if pos_key not in self._broker_stop_locks:
            import asyncio
            self._broker_stop_locks[pos_key] = asyncio.Lock()

        async with self._broker_stop_locks[pos_key]:
            if cache.dynamic_sl_price and new_stop_price < cache.dynamic_sl_price:
                print(f"[RISK] ⚠️ Broker stop sync skipped: requested ${new_stop_price:.2f} < current dynamic SL ${cache.dynamic_sl_price:.2f}")
                return
            await self._sync_stop_to_broker_inner(position, cache, new_stop_price)

    async def _sync_stop_to_broker_inner(self, position, cache, new_stop_price: float):
        if cache.closing:
            print(f"[RISK] ⏭️ Skipping broker stop sync — position is closing")
            return

        _ch_settings = getattr(cache, 'channel_settings', None)
        if _ch_settings and not getattr(_ch_settings, 'allows_broker_sl', True):
            return

        broker_name = position.broker.upper() if hasattr(position, 'broker') else ''
        symbol = getattr(cache, 'raw_symbol', None) or getattr(position, 'raw_symbol', None) or position.symbol
        qty = int(position.quantity)
        asset_type = getattr(position, 'asset', 'stock')

        if broker_name == 'SCHWAB' and self.schwab_broker:
            try:
                if not self.schwab_broker.is_authenticated():
                    print(f"[RISK] ⚠️ Schwab not authenticated, skip broker stop sync")
                    return

                if cache.broker_oco_order_id:
                    _oco_pt_price = cache.broker_oco_pt_price
                    _oco_qty = cache.broker_oco_qty
                    _old_oco_id = cache.broker_oco_order_id
                    _cancel_res = await self.schwab_broker.cancel_order(cache.broker_oco_order_id)
                    if _cancel_res.get('success'):
                        print(f"[RISK] 🔄 Cancelled OCO #{cache.broker_oco_order_id} for SL update")
                        _oco_status = await self.schwab_broker.get_order_status(_old_oco_id)
                        if _oco_status and _oco_status.get('status') == 'filled':
                            print(f"[RISK] ⚠️ OCO #{_old_oco_id} was FILLED during cancel — skipping SL sync to prevent double-sell")
                            cache.broker_oco_order_id = None
                            cache.broker_oco_sl_price = None
                            cache.broker_oco_pt_price = None
                            cache.broker_oco_qty = 0
                            return
                    else:
                        _cmsg = _cancel_res.get('message', '')
                        if '404' in _cmsg or '400' in _cmsg or '409' in _cmsg:
                            print(f"[RISK] 🔄 OCO #{cache.broker_oco_order_id} already dead ({_cmsg}) — proceeding with SL sync")
                        else:
                            print(f"[RISK] ⚠️ OCO cancel failed: {_cmsg} — aborting SL sync to prevent duplicate orders")
                            return
                    if cache.broker_stop_order_id == _old_oco_id:
                        cache.broker_stop_order_id = None
                    cache.broker_oco_order_id = None
                    cache.broker_oco_sl_price = None
                    cache.broker_oco_pt_price = None
                    cache.broker_oco_qty = 0
                    cache.broker_pt_order_id = None

                    if _oco_pt_price and _oco_qty > 0:
                        oco_result = await self.schwab_broker.place_oco_order(
                            symbol=symbol,
                            quantity=_oco_qty,
                            stop_loss_price=new_stop_price,
                            profit_target_price=_oco_pt_price,
                            side='sell',
                            asset_type='EQUITY'
                        )
                        if oco_result and oco_result.success and oco_result.order_id:
                            cache.broker_oco_order_id = str(oco_result.order_id)
                            cache.broker_oco_sl_price = new_stop_price
                            cache.broker_oco_pt_price = _oco_pt_price
                            cache.broker_oco_qty = _oco_qty
                            cache.broker_pt_order_id = str(oco_result.order_id)
                            print(f"[RISK] ✅ OCO re-placed: #{oco_result.order_id} SL=${new_stop_price:.2f} PT=${_oco_pt_price:.2f} (qty={_oco_qty})")
                        else:
                            msg = getattr(oco_result, 'message', 'unknown') if oco_result else 'no result'
                            print(f"[RISK] ⚠️ OCO re-place failed: {msg} — falling back to standalone PT limit")
                            _is_opt = asset_type.lower() in ('option', 'options')
                            if _oco_pt_price and _oco_qty > 0:
                                pt_result = await self.schwab_broker.place_option_order(
                                    symbol=position.symbol,
                                    strike=getattr(position, 'strike', 0),
                                    expiry=getattr(position, 'expiry', ''),
                                    option_type=getattr(position, 'direction', 'C') or 'C',
                                    action='STC',
                                    quantity=_oco_qty,
                                    price=_oco_pt_price,
                                    _skip_cancel_check=True
                                ) if _is_opt else await self.schwab_broker.place_stock_order(
                                    symbol=symbol,
                                    action='STC',
                                    quantity=_oco_qty,
                                    price=_oco_pt_price,
                                    _skip_cancel_check=True
                                )
                                if pt_result and pt_result.success and pt_result.order_id:
                                    cache.broker_pt_order_id = str(pt_result.order_id)
                                    print(f"[RISK] ✅ Standalone PT fallback: #{pt_result.order_id} at ${_oco_pt_price:.2f} (qty={_oco_qty})")
                                else:
                                    _pt_msg = getattr(pt_result, 'message', 'unknown') if pt_result else 'no result'
                                    print(f"[RISK] ⚠️ Standalone PT fallback also failed: {_pt_msg}")

                if cache.broker_stop_order_id:
                    cancel_result = await self.schwab_broker.cancel_order(cache.broker_stop_order_id)
                    if cancel_result.get('success'):
                        print(f"[RISK] 🔄 Cancelled old broker stop #{cache.broker_stop_order_id}")
                        cache.broker_stop_order_id = None
                    else:
                        _cancel_msg = cancel_result.get('message', '')
                        if '404' in _cancel_msg or '400' in _cancel_msg or '409' in _cancel_msg:
                            print(f"[RISK] 🔄 Old stop #{cache.broker_stop_order_id} already dead ({_cancel_msg}) — proceeding")
                            cache.broker_stop_order_id = None
                        else:
                            print(f"[RISK] ⚠️ Cancel old stop failed: {_cancel_msg} — retrying in 10s")
                            _pk = getattr(position, 'position_key', '') or f"{position.broker}_{position.symbol}"
                            self._enqueue_broker_op(_pk, 'SYNC_STOP', 10,
                                lambda _p=position, _c=cache, _sp=new_stop_price: self._sync_stop_to_broker(_p, _c, _sp))
                            return

                _is_opt = asset_type.lower() in ('option', 'options')
                _schwab_sync_symbol = symbol
                if _is_opt and hasattr(self.schwab_broker, '_build_option_symbol'):
                    try:
                        from datetime import datetime as _dt
                        _opt_expiry = getattr(position, 'expiry', '') or ''
                        _opt_strike = getattr(position, 'strike', 0) or 0
                        _opt_dir = (getattr(position, 'direction', '') or 'C').upper()
                        _opt_cp = 'C' if _opt_dir in ('C', 'CALL') else 'P'
                        if '/' in _opt_expiry:
                            _parts = _opt_expiry.split('/')
                            if len(_parts) == 2:
                                _m, _d = _parts
                                _opt_expiry_fmt = f"{_dt.now().year}-{int(_m):02d}-{int(_d):02d}"
                            elif len(_parts) == 3:
                                _m, _d, _y = _parts
                                if len(_y) == 2:
                                    _y = f"20{_y}"
                                _opt_expiry_fmt = f"{_y}-{int(_m):02d}-{int(_d):02d}"
                            else:
                                _opt_expiry_fmt = _opt_expiry
                        elif len(_opt_expiry) == 10 and '-' in _opt_expiry:
                            _opt_expiry_fmt = _opt_expiry
                        else:
                            _opt_expiry_fmt = _opt_expiry
                        _schwab_sync_symbol = self.schwab_broker._build_option_symbol(
                            position.symbol, _opt_expiry_fmt, _opt_strike, _opt_cp
                        )
                        if 'INVALID_EXPIRY' in _schwab_sync_symbol:
                            print(f"[RISK] ⚠️ Schwab OCC build returned invalid in stop sync: {_schwab_sync_symbol} — skipping")
                            return
                        print(f"[RISK] 📐 Schwab option stop sync: OCC symbol {_schwab_sync_symbol}")
                    except Exception as _occ_err:
                        print(f"[RISK] ⚠️ Schwab OCC build failed in stop sync: {_occ_err} — skipping")
                        return

                _stop_qty = qty
                if cache.broker_oco_qty > 0:
                    _stop_qty = qty - cache.broker_oco_qty
                if _stop_qty <= 0:
                    print(f"[RISK] ⏭ Standalone stop qty=0 (OCO covers all shares) — skipping")
                else:
                    result = await self.schwab_broker.place_stop_order(
                        symbol=_schwab_sync_symbol,
                        quantity=_stop_qty,
                        stop_price=new_stop_price,
                        side='sell_to_close' if _is_opt else 'sell',
                        asset_type='OPTION' if _is_opt else 'EQUITY',
                        duration='GOOD_TILL_CANCEL'
                    )

                    if result and result.success and result.order_id:
                        cache.broker_stop_order_id = str(result.order_id)
                        print(f"[RISK] ✅ Broker stop synced: Schwab stop #{result.order_id} at ${new_stop_price:.2f} (qty={_stop_qty})")
                    else:
                        msg = getattr(result, 'message', 'unknown') if result else 'no result'
                        print(f"[RISK] ⚠️ Schwab stop order failed: {msg}")
            except Exception as e:
                print(f"[RISK] ⚠️ Schwab broker stop sync error: {e}")

        elif broker_name in ('ALPACA', 'ALPACA_PAPER', 'ALPACA_LIVE') and self.alpaca_broker:
            try:
                if not getattr(self.alpaca_broker, 'connected', False):
                    print(f"[RISK] ⚠️ Alpaca not connected, skip broker stop sync")
                    return

                if cache.broker_stop_order_id:
                    try:
                        if hasattr(self.alpaca_broker, 'trading_client'):
                            self.alpaca_broker.trading_client.cancel_order_by_id(cache.broker_stop_order_id)
                        elif hasattr(self.alpaca_broker, 'cancel_order'):
                            await self.alpaca_broker.cancel_order(cache.broker_stop_order_id)
                        print(f"[RISK] 🔄 Cancelled old Alpaca stop #{cache.broker_stop_order_id}")
                        cache.broker_stop_order_id = None
                    except Exception:
                        pass

                if hasattr(self.alpaca_broker, 'trading_client'):
                    from alpaca.trading.requests import StopOrderRequest
                    from alpaca.trading.enums import OrderSide, TimeInForce, PositionIntent
                    _is_opt = asset_type.lower() in ('option', 'options')
                    if _is_opt:
                        _alpaca_idx = {'SPX', 'SPXW', 'NDX', 'NDXP', 'RUT', 'RUTW', 'VIX', 'VIXW', 'XSP', 'DJX'}
                        _alpaca_und = (getattr(position, 'symbol', '') or symbol).upper().strip()
                        if _alpaca_und in _alpaca_idx:
                            print(f"[RISK] ⚠️ Alpaca does not support index options ({_alpaca_und}) — stop sync skipped")
                            return
                    _tif = TimeInForce.DAY if _is_opt else TimeInForce.GTC
                    _alpaca_stp = round(new_stop_price, 2)
                    _sync_kwargs = dict(
                        symbol=symbol,
                        qty=qty,
                        side=OrderSide.SELL,
                        stop_price=_alpaca_stp,
                        time_in_force=_tif
                    )
                    if _is_opt:
                        _sync_kwargs['position_intent'] = PositionIntent.SELL_TO_CLOSE
                    req = StopOrderRequest(**_sync_kwargs)
                    order = self.alpaca_broker.trading_client.submit_order(req)
                    if order and order.id:
                        cache.broker_stop_order_id = str(order.id)
                        print(f"[RISK] ✅ Broker stop synced: Alpaca stop #{order.id} at ${_alpaca_stp:.2f}")
                    else:
                        print(f"[RISK] ⚠️ Alpaca stop order returned no ID")
            except Exception as e:
                print(f"[RISK] ⚠️ Alpaca broker stop sync error: {e}")

        else:
            broker_instance = self._get_broker_instance_for_bracket(broker_name)
            if not broker_instance:
                return
            _is_opt = asset_type.lower() in ('option', 'options')
            try:
                if cache.broker_stop_order_id:
                    try:
                        _cancel_ok = await self._cancel_single_order(broker_name, cache.broker_stop_order_id, broker_instance, asset_type=asset_type)
                        if _cancel_ok:
                            print(f"[RISK] 🔄 Cancelled old {broker_name} stop #{cache.broker_stop_order_id}")
                        else:
                            print(f"[RISK] 🔄 Old {broker_name} stop #{cache.broker_stop_order_id} cancel returned false (may be already filled/cancelled)")
                        cache.broker_stop_order_id = None
                    except Exception as ce:
                        print(f"[RISK] ⚠️ Cancel old {broker_name} stop failed: {ce} — skipping new stop to avoid duplicates")
                        return

                if 'IBKR' in broker_name:
                    from ib_insync import StopOrder as IBStopOrder, Stock as _IBStock, Option as _IBOption
                    if _is_opt:
                        expiry_fmt = self.ibkr_broker._normalize_expiry_yyyymmdd(position.expiry or '')
                        right = 'C' if (position.direction or '').upper() in ('C', 'CALL') else 'P'
                        contract = _IBOption(position.symbol, expiry_fmt, position.strike, right, 'SMART')
                    else:
                        contract = _IBStock(symbol, 'SMART', 'USD')
                    await self.ibkr_broker.ib.qualifyContractsAsync(contract)
                    _ibkr_sync_stop = new_stop_price
                    if _is_opt:
                        _ibkr_sync_stop = _round_to_cboe_increment(new_stop_price, is_sell=True, is_stop_trigger=True)
                        if _ibkr_sync_stop != new_stop_price:
                            print(f"[RISK] 📐 IBKR option stop sync CBOE snap: ${new_stop_price:.2f} → ${_ibkr_sync_stop:.2f} (stop trigger: round up)")
                    sl_order = IBStopOrder('SELL', qty, _ibkr_sync_stop)
                    sl_order.tif = 'GTC'
                    sl_order.outsideRth = self.ibkr_broker._get_extended_hours_enabled()
                    _oca_group = cache.broker_oco_order_id
                    if _oca_group and cache.broker_pt_order_id:
                        sl_order.ocaGroup = _oca_group
                        sl_order.ocaType = 2
                    elif cache.broker_pt_order_id:
                        import time as _oca_time
                        _oca_group = f"BT_{symbol}_{int(_oca_time.time())}"
                        sl_order.ocaGroup = _oca_group
                        sl_order.ocaType = 2
                        cache.broker_oco_order_id = _oca_group
                    sl_trade = self.ibkr_broker.ib.placeOrder(contract, sl_order)
                    await asyncio.sleep(1)
                    _ibkr_sync_ok = ('Submitted', 'PreSubmitted', 'PendingSubmit', 'Filled', 'ApiPending')
                    if sl_trade and sl_trade.orderStatus.status in _ibkr_sync_ok:
                        cache.broker_stop_order_id = str(sl_trade.order.orderId)
                        print(f"[RISK] ✅ Broker stop synced: IBKR stop #{sl_trade.order.orderId} at ${new_stop_price:.2f} [GTC{', OCA=' + _oca_group if _oca_group else ''}]")
                    else:
                        print(f"[RISK] ⚠️ IBKR stop sync failed: {sl_trade.orderStatus.status if sl_trade else 'no trade'}")

                elif 'TASTYTRADE' in broker_name:
                    if not _is_opt:
                        from tastytrade.instruments import Equity as _TTEq
                        from tastytrade.order import NewOrder as _TTOrder, OrderAction as _TTAction, OrderTimeInForce as _TTTIF, OrderType as _TTType
                        from decimal import Decimal as _TTDec
                        if not self.tastytrade_broker._ensure_session_valid():
                            print(f"[RISK] ⚠️ TastyTrade session invalid, skip stop sync")
                            return
                        tt_eq = await _await_if_needed(
                            await asyncio.to_thread(_TTEq.get, self.tastytrade_broker.session, symbol)
                        )
                        sl_leg = tt_eq.build_leg(_TTDec(str(qty)), _TTAction.SELL_TO_CLOSE)
                        sl_ord = _TTOrder(
                            time_in_force=_TTTIF.GTC,
                            order_type=_TTType.STOP,
                            legs=[sl_leg],
                            stop_trigger=_TTDec(str(new_stop_price))
                        )
                        sl_resp = await _await_if_needed(
                            await asyncio.to_thread(
                                self.tastytrade_broker.account.place_order,
                                self.tastytrade_broker.session, sl_ord, dry_run=False
                            )
                        )
                        if sl_resp and hasattr(sl_resp, 'order') and sl_resp.order:
                            cache.broker_stop_order_id = str(sl_resp.order.id)
                            print(f"[RISK] ✅ Broker stop synced: TastyTrade stop #{sl_resp.order.id} at ${new_stop_price:.2f}")
                        else:
                            print(f"[RISK] ⚠️ TastyTrade stop sync submitted but no order ID returned — cannot track for cancel")
                    else:
                        _tt_sync_sl = _round_to_cboe_increment(new_stop_price, is_sell=True)
                        if _tt_sync_sl != new_stop_price:
                            print(f"[RISK] 📐 TastyTrade option stop sync CBOE snap: ${new_stop_price:.2f} → ${_tt_sync_sl:.2f}")
                        sl_result = await self.tastytrade_broker.place_option_order(
                            symbol=position.symbol, strike=position.strike,
                            expiry=position.expiry or '', option_type=position.direction or 'C',
                            action='STC', quantity=qty, price=_tt_sync_sl
                        )
                        if sl_result and sl_result.success:
                            _sl_oid = getattr(sl_result, 'order_id', None)
                            if _sl_oid:
                                cache.broker_stop_order_id = str(_sl_oid)
                            print(f"[RISK] ✅ Broker stop synced: TastyTrade option limit #{_sl_oid or 'submitted'} at ${new_stop_price:.2f} [options use limit, not stop]")

                elif 'TRADING212' in broker_name:
                    if _is_opt:
                        return
                    sl_result = await self.trading212_broker.place_stop_order(
                        symbol=symbol, action='STC', quantity=qty, stop_price=new_stop_price
                    )
                    if sl_result and sl_result.success and sl_result.order_id:
                        cache.broker_stop_order_id = str(sl_result.order_id)
                        print(f"[RISK] ✅ Broker stop synced: Trading212 stop #{sl_result.order_id} at ${new_stop_price:.2f}")
                    else:
                        msg = getattr(sl_result, 'message', 'unknown') if sl_result else 'no result'
                        print(f"[RISK] ⚠️ Trading212 stop sync failed: {msg}")

                elif 'ROBINHOOD' in broker_name:
                    if _is_opt:
                        print(f"[RISK] ⚠️ Robinhood options don't support stop orders — dynamic SL monitored locally")
                        return
                    sl_result = await self.robinhood_broker.place_stock_order(
                        symbol=symbol, action='STC', quantity=qty, stop_price=new_stop_price
                    )
                    if sl_result and sl_result.success and sl_result.order_id:
                        cache.broker_stop_order_id = str(sl_result.order_id)
                        print(f"[RISK] ✅ Broker stop synced: Robinhood stop #{sl_result.order_id} at ${new_stop_price:.2f}")
                    else:
                        msg = getattr(sl_result, 'message', 'unknown') if sl_result else 'no result'
                        print(f"[RISK] ⚠️ Robinhood stop sync failed: {msg}")

                elif 'WEBULL' in broker_name:
                    if _is_opt:
                        print(f"[RISK] ⚠️ Webull options don't support stop orders — dynamic SL monitored locally")
                        return
                    _wb_c2 = getattr(broker_instance, '_client', None) or getattr(broker_instance, 'wb', None)
                    if not _wb_c2:
                        print(f"[RISK] ⚠️ Webull client not connected — cannot sync stop")
                        return
                    _wb_tId2 = await asyncio.to_thread(self._resolve_webull_ticker_id, _wb_c2, symbol)
                    if not _wb_tId2:
                        print(f"[RISK] ⚠️ Webull ticker ID not found for {symbol} — cannot sync stop")
                        return
                    _stp_r = round(new_stop_price, 4 if new_stop_price < 1.0 else 2)
                    for _ext_hrs in [True, False]:
                        def _wb_stop_sync(_c=_wb_c2, _s=symbol, _p=_stp_r, _q=qty, _t=_wb_tId2, _eh=_ext_hrs):
                            return _c.place_order(
                                stock=_s, tId=int(_t), stpPrice=_p, action='SELL',
                                orderType='STP', enforce='GTC', quant=_q,
                                outsideRegularTradingHour=_eh
                            )
                        sl_resp = await asyncio.to_thread(_wb_stop_sync)
                        print(f"[RISK] [DEBUG] Webull stop sync response (extHrs={_ext_hrs}): {sl_resp}")
                        if sl_resp and not sl_resp.get('msg'):
                            _sl_oid = str(sl_resp.get('data', {}).get('orderId', '')) if isinstance(sl_resp.get('data'), dict) else str(sl_resp.get('orderId', ''))
                            if _sl_oid:
                                cache.broker_stop_order_id = _sl_oid
                                print(f"[RISK] ✅ Broker stop synced: Webull stop #{_sl_oid} at ${new_stop_price:.2f}")
                                break
                        else:
                            _err = sl_resp.get('msg', 'unknown') if sl_resp else 'no response'
                            if _ext_hrs:
                                print(f"[RISK] ⚠️ Webull stop sync failed (extHrs=True): {_err} — retrying")
                            else:
                                print(f"[RISK] ⚠️ Webull stop sync failed: {_err} — SL monitored locally")

            except Exception as e:
                print(f"[RISK] ⚠️ {broker_name} broker stop sync error: {e}")

    async def _replace_broker_pt(self, position_key: str, new_pt_price: float, trade_id: int = None):
        """Replace the live broker PT order with a new price (signal target update).
        Called from PHOENIX TGT handler when a follow-up target message arrives."""
        cache = self.cache.get(position_key)
        if not cache:
            print(f"[RISK PT REPLACE] ⚠️ No cache entry for {position_key}")
            return False

        if cache.closing:
            print(f"[RISK PT REPLACE] ⏭️ Position {position_key} is closing — skip PT replace")
            return False

        if not cache.broker_orders_placed:
            print(f"[RISK PT REPLACE] ⏭️ No broker orders placed yet for {position_key}")
            return False

        if cache.original_qty and hasattr(cache, '_current_qty'):
            pass

        broker_name = (cache.broker or '').upper()
        symbol = cache.raw_symbol or position_key.split('_')[1] if '_' in position_key else position_key

        if broker_name == 'SCHWAB' and self.schwab_broker:
            try:
                if not self.schwab_broker.is_authenticated():
                    print(f"[RISK PT REPLACE] ⚠️ Schwab not authenticated")
                    return False

                if cache.broker_oco_order_id:
                    _oco_sl_price = cache.broker_oco_sl_price
                    _oco_qty = cache.broker_oco_qty
                    _old_oco_id = cache.broker_oco_order_id
                    _old_pt = cache.broker_oco_pt_price

                    if _old_pt and abs(_old_pt - new_pt_price) < 0.001:
                        print(f"[RISK PT REPLACE] ⏭️ PT already at ${new_pt_price:.4f} — no change needed")
                        return True

                    _cancel_res = await self.schwab_broker.cancel_order(_old_oco_id)
                    if _cancel_res.get('success'):
                        print(f"[RISK PT REPLACE] 🔄 Cancelled OCO #{_old_oco_id} for PT update")
                        _oco_status = await self.schwab_broker.get_order_status(_old_oco_id)
                        if _oco_status and _oco_status.get('status') == 'filled':
                            print(f"[RISK PT REPLACE] ⚠️ OCO #{_old_oco_id} already FILLED — cannot update PT")
                            cache.broker_oco_order_id = None
                            cache.broker_oco_sl_price = None
                            cache.broker_oco_pt_price = None
                            cache.broker_oco_qty = 0
                            return False
                    else:
                        _cmsg = _cancel_res.get('message', '')
                        if '404' in _cmsg or '400' in _cmsg or '409' in _cmsg:
                            print(f"[RISK PT REPLACE] 🔄 OCO #{_old_oco_id} already dead ({_cmsg}) — placing fresh bracket")
                        else:
                            print(f"[RISK PT REPLACE] ⚠️ OCO cancel failed: {_cmsg} — aborting")
                            return False

                    if cache.broker_stop_order_id == _old_oco_id:
                        cache.broker_stop_order_id = None
                    cache.broker_oco_order_id = None
                    cache.broker_oco_sl_price = None
                    cache.broker_oco_pt_price = None
                    cache.broker_oco_qty = 0
                    cache.broker_pt_order_id = None

                    if _oco_sl_price and _oco_qty > 0:
                        oco_result = await self.schwab_broker.place_oco_order(
                            symbol=symbol,
                            quantity=_oco_qty,
                            stop_loss_price=_oco_sl_price,
                            profit_target_price=new_pt_price,
                            side='sell',
                            asset_type='EQUITY'
                        )
                        if oco_result and oco_result.success and oco_result.order_id:
                            cache.broker_oco_order_id = str(oco_result.order_id)
                            cache.broker_oco_sl_price = _oco_sl_price
                            cache.broker_oco_pt_price = new_pt_price
                            cache.broker_oco_qty = _oco_qty
                            cache.broker_pt_order_id = str(oco_result.order_id)
                            print(f"[RISK PT REPLACE] ✅ OCO re-placed: #{oco_result.order_id} SL=${_oco_sl_price:.2f} PT=${new_pt_price:.2f} (was ${_old_pt:.2f})")
                            return True
                        else:
                            msg = getattr(oco_result, 'message', 'unknown') if oco_result else 'no result'
                            print(f"[RISK PT REPLACE] ⚠️ OCO re-place failed: {msg} — placing standalone SL for protection")
                            sl_fallback = await self.schwab_broker.place_stop_order(
                                symbol=symbol, quantity=_oco_qty,
                                stop_price=_oco_sl_price, side='sell',
                                asset_type='EQUITY', duration='GOOD_TILL_CANCEL'
                            )
                            if sl_fallback and sl_fallback.success and sl_fallback.order_id:
                                cache.broker_stop_order_id = str(sl_fallback.order_id)
                                print(f"[RISK PT REPLACE] ✅ SL fallback placed: #{sl_fallback.order_id} at ${_oco_sl_price:.2f}")
                            else:
                                print(f"[RISK PT REPLACE] ⚠️ SL fallback also failed — position UNPROTECTED")
                            return False
                    else:
                        print(f"[RISK PT REPLACE] ⚠️ No SL price or qty for OCO — cannot re-place")
                        return False

                elif cache.broker_pt_order_id:
                    _cancel_res = await self.schwab_broker.cancel_order(cache.broker_pt_order_id)
                    if _cancel_res.get('success'):
                        print(f"[RISK PT REPLACE] 🔄 Cancelled standalone PT #{cache.broker_pt_order_id}")
                    else:
                        _cmsg = _cancel_res.get('message', '')
                        if '404' in _cmsg or '400' in _cmsg or '409' in _cmsg:
                            print(f"[RISK PT REPLACE] 🔄 PT #{cache.broker_pt_order_id} already dead")
                        else:
                            print(f"[RISK PT REPLACE] ⚠️ PT cancel failed: {_cmsg}")
                            return False

                    _pt_qty = cache.broker_oco_qty or (cache.original_qty or 0)
                    if _pt_qty <= 0:
                        print(f"[RISK PT REPLACE] ⚠️ No qty for standalone PT")
                        return False

                    pt_result = await self.schwab_broker.place_stock_order(
                        symbol=symbol,
                        action='STC',
                        quantity=_pt_qty,
                        price=new_pt_price,
                        _skip_cancel_check=True
                    )
                    if pt_result and pt_result.success and pt_result.order_id:
                        cache.broker_pt_order_id = str(pt_result.order_id)
                        print(f"[RISK PT REPLACE] ✅ Standalone PT replaced: #{pt_result.order_id} at ${new_pt_price:.2f}")
                        return True
                    else:
                        msg = getattr(pt_result, 'message', 'unknown') if pt_result else 'no result'
                        print(f"[RISK PT REPLACE] ⚠️ Standalone PT failed: {msg}")
                        return False
                else:
                    print(f"[RISK PT REPLACE] ⏭️ No OCO or PT order to replace for {position_key}")
                    return False

            except Exception as e:
                print(f"[RISK PT REPLACE] ⚠️ Schwab error: {e}")
                return False

        elif 'IBKR' in broker_name and self.ibkr_broker:
            try:
                if not cache.broker_pt_order_id:
                    print(f"[RISK PT REPLACE] ⏭️ No IBKR PT order to modify for {position_key}")
                    return False

                pt_order_id = int(cache.broker_pt_order_id)
                from ib_insync import LimitOrder as _IBLimitPT, Stock as _IBStockPT, Option as _IBOptionPT
                _is_opt = '_option' in position_key
                if _is_opt:
                    print(f"[RISK PT REPLACE] ⚠️ IBKR option PT modify not yet supported")
                    return False
                contract = _IBStockPT(symbol, 'SMART', 'USD')
                await self.ibkr_broker.ib.qualifyContractsAsync(contract)

                _existing_trade = None
                for t in self.ibkr_broker.ib.openTrades():
                    if t.order.orderId == pt_order_id:
                        _existing_trade = t
                        break

                if not _existing_trade:
                    print(f"[RISK PT REPLACE] ⚠️ IBKR PT order #{pt_order_id} not found in open trades (may be filled)")
                    return False

                _existing_trade.order.lmtPrice = new_pt_price
                self.ibkr_broker.ib.placeOrder(contract, _existing_trade.order)
                await asyncio.sleep(1)
                print(f"[RISK PT REPLACE] ✅ IBKR PT #{pt_order_id} modified: new limit ${new_pt_price:.2f}")
                cache.broker_oco_pt_price = new_pt_price
                return True

            except Exception as e:
                print(f"[RISK PT REPLACE] ⚠️ IBKR error: {e}")
                return False

        else:
            print(f"[RISK PT REPLACE] ⏭️ Broker {broker_name} not supported for PT replace")
            return False

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
        
        if decision.is_partial:
            _tier = getattr(decision, 'tier_hit', None) or getattr(decision, 'tier', None)
            if _tier:
                _flight_key = f"{pos_key}_T{_tier}"
                import time as _pf
                _flight_ts = self._partial_exit_in_flight.get(_flight_key, 0)
                if (_pf.time() - _flight_ts) < 30:
                    print(f"[RISK] Partial exit T{_tier} already in-flight for {pos_key} — skipping duplicate")
                    return
                self._partial_exit_in_flight[_flight_key] = _pf.time()
        else:
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

        _need_replace_stop = False
        _old_stop_price = None
        _had_oco = False
        if cache and cache.broker_orders_placed:
            if cache.broker_stop_order_id or cache.broker_pt_order_id or cache.broker_oco_order_id:
                try:
                    _had_oco = bool(cache.broker_oco_order_id)
                    if decision.is_partial:
                        _old_stop_price = cache.dynamic_sl_price or getattr(cache, '_last_broker_stop_price', None)
                        if not _old_stop_price and hasattr(cache, 'entry_price') and cache.entry_price > 0:
                            _ch = getattr(cache, 'channel_settings', None)
                            _sl_pct = getattr(_ch, 'stop_loss_pct', 0) if _ch else 0
                            if _sl_pct > 0:
                                _old_stop_price = round(cache.entry_price * (1 - _sl_pct / 100), 4)
                        await self._cancel_broker_bracket_orders(position, cache, cancel_stop=True, cancel_pt=True)
                        if not _had_oco:
                            _need_replace_stop = True
                            print(f"[RISK] 🔄 Cancelled broker SL before partial PT exit (will re-place after fill)")
                        else:
                            print(f"[RISK] 🔄 Cancelled OCO bracket for partial PT exit (cascade will re-place)")
                    else:
                        await self._cancel_broker_bracket_orders(position, cache)
                except Exception as e:
                    bracket_type = "OCO + bracket" if _had_oco else "bracket"
                    print(f"[RISK] ⚠️ {bracket_type} order cleanup failed (non-blocking): {e}")
        
        trigger = decision.risk_trigger or ''
        is_dynamic_sl = trigger == 'dynamic_sl' or (trigger == 'stop_loss' and 'Dynamic SL' in decision.reason)
        is_stop_exit = trigger == 'stop_loss' and not is_dynamic_sl
        is_trailing_exit = trigger == 'trailing_stop' or trigger == 'early_trailing'
        is_profit_exit = trigger == 'profit_target'
        is_giveback_exit = trigger == 'giveback_guard'
        is_ema_exit = trigger in ('ema_exit', 'ema_no_trend')
        
        if not trigger:
            if 'STOP LOSS' in decision.reason and 'TRAILING' not in decision.reason:
                is_stop_exit = not is_dynamic_sl
            elif 'TRAILING' in decision.reason:
                is_trailing_exit = True
            elif 'TARGET' in decision.reason or 'PROFIT' in decision.reason:
                is_profit_exit = True
            elif 'GIVEBACK' in decision.reason:
                is_giveback_exit = True
            elif 'EMA' in decision.reason:
                is_ema_exit = True
        
        exit_qty = int(decision.exit_qty) if decision.exit_qty else 0
        
        if is_dynamic_sl:
            try:
                from gui_app.discord_notifier import notify_dynamic_sl_triggered
                dsl_price = cache.dynamic_sl_price if cache and hasattr(cache, 'dynamic_sl_price') and cache.dynamic_sl_price else 0
                notify_dynamic_sl_triggered(
                    symbol=position.symbol,
                    broker=position.broker,
                    entry_price=entry_price,
                    exit_price=current_price,
                    dynamic_sl_price=dsl_price,
                    pnl_percent=pnl_pct,
                    quantity=exit_qty,
                    channel=channel_settings.channel_name if channel_settings else None
                )
            except Exception as notify_err:
                print(f"[NOTIFY] Warning: Could not send dynamic SL notification: {notify_err}")
        
        elif is_stop_exit:
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
        
        elif is_trailing_exit:
            try:
                from gui_app.discord_notifier import notify_trailing_stop_triggered
                trail_type = "early" if trigger == 'early_trailing' or "EARLY" in decision.reason else "standard"
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
        
        elif is_giveback_exit:
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
        
        elif is_ema_exit:
            try:
                from gui_app.discord_notifier import notify_ema_exit_triggered
                notify_ema_exit_triggered(
                    symbol=position.symbol,
                    broker=position.broker,
                    exit_type=trigger or 'ema_exit',
                    pnl_percent=pnl_pct,
                    exit_price=current_price,
                    quantity=exit_qty,
                    reason=decision.reason,
                    channel=channel_settings.channel_name if channel_settings else None
                )
            except Exception as notify_err:
                print(f"[NOTIFY] Warning: Could not send EMA exit notification: {notify_err}")
        
        elif is_profit_exit and pnl_pct > 0:
            try:
                from gui_app.discord_notifier import notify_profit_target_hit
                tier = 1
                if 'TARGET 2' in decision.reason or 'TARGET2' in decision.reason or 'TIER 2' in decision.reason:
                    tier = 2
                elif 'TARGET 3' in decision.reason or 'TARGET3' in decision.reason or 'TIER 3' in decision.reason:
                    tier = 3
                elif 'TARGET 4' in decision.reason or 'TARGET4' in decision.reason or 'TIER 4' in decision.reason:
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
            if is_dynamic_sl:
                evt_type = 'DYNAMIC_SL'
                evt_severity = 'warning'
            elif is_stop_exit:
                evt_type = 'STOP_LOSS'
                evt_severity = 'critical'
            elif is_trailing_exit:
                evt_type = 'EARLY_TRAILING' if trigger == 'early_trailing' or 'EARLY' in decision.reason else 'TRAILING_STOP'
                evt_severity = 'warning'
            elif is_giveback_exit:
                evt_type = 'GIVEBACK_GUARD'
                evt_severity = 'warning'
            elif is_ema_exit:
                evt_type = 'EMA_EXIT' if trigger != 'ema_no_trend' else 'EMA_NO_TREND'
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
                        self.cache.reset_closing(pos_key)
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
                    self.cache.reset_closing(pos_key)
                    from src.risk.exit_lease_manager import get_exit_lease_manager, OWNER_RISK_ENGINE as _OWN
                    get_exit_lease_manager().release(pos_key, _OWN)
                return
            
            hub_quotes = self._get_streaming_bid_ask(position)
            hub_bid = hub_quotes['bid']
            hub_ask = hub_quotes['ask']
            hub_mid = hub_quotes['mid']
            hub_src = hub_quotes['source']
            _penny_ref_price = hub_bid if hub_bid > 0 else (hub_mid if hub_mid > 0 else position.current_price)
            is_penny_stock = position.asset == 'stock' and _penny_ref_price < 1.0
            if hub_bid > 0 or hub_ask > 0:
                last_price = stc_signal['price']
                spread_pct = 0
                if hub_bid > 0 and hub_ask > 0:
                    spread_pct = (hub_ask - hub_bid) / hub_bid * 100
                if is_penny_stock and (hub_bid > 0 or hub_mid > 0):
                    _penny_retry = 0
                    _penny_cache = self.cache.get(pos_key)
                    if _penny_cache:
                        _penny_retry = _penny_cache.exit_retry_count
                    _penny_is_sl = (is_stop_exit or is_trailing_exit or is_giveback_exit)
                    _penny_spread_ok = spread_pct < 8
                    if _penny_is_sl:
                        if hub_bid > 0:
                            stc_signal['price'] = hub_bid
                            print(f"[RISK] 💰 Penny stock SL exit: bid ${hub_bid:.4f} "
                                  f"(ask ${hub_ask:.4f}, mid ${hub_mid:.4f}, last ${last_price:.4f}, spread {spread_pct:.1f}%) "
                                  f"via {hub_src}")
                        elif hub_mid > 0:
                            stc_signal['price'] = hub_mid
                            print(f"[RISK] 💰 Penny stock SL exit: mid ${hub_mid:.4f} (no bid, last ${last_price:.4f}) via {hub_src}")
                    elif _penny_retry == 0 and hub_mid > 0 and _penny_spread_ok:
                        stc_signal['price'] = hub_mid
                        print(f"[RISK] 💰 Penny stock exit (try #1 mid): ${hub_mid:.4f} "
                              f"(bid ${hub_bid:.4f}, ask ${hub_ask:.4f}, last ${last_price:.4f}, spread {spread_pct:.1f}%) "
                              f"via {hub_src}")
                    elif hub_bid > 0:
                        stc_signal['price'] = hub_bid
                        _retry_label = f"try #{_penny_retry + 1} bid" if _penny_retry > 0 else "wide-spread bid"
                        print(f"[RISK] 💰 Penny stock exit ({_retry_label}): ${hub_bid:.4f} "
                              f"(ask ${hub_ask:.4f}, mid ${hub_mid:.4f}, last ${last_price:.4f}, spread {spread_pct:.1f}%) "
                              f"via {hub_src}")
                    elif hub_mid > 0:
                        stc_signal['price'] = hub_mid
                        print(f"[RISK] 💰 Penny stock exit (mid-only): ${hub_mid:.4f} (last ${last_price:.4f}) via {hub_src}")
                elif is_stop_exit or is_trailing_exit or is_giveback_exit:
                    if hub_bid > 0 and spread_pct < 50:
                        stc_signal['price'] = hub_bid
                        print(f"[RISK] 💰 Exit price: bid ${hub_bid:.2f} "
                              f"(ask ${hub_ask:.2f}, mid ${hub_mid:.2f}, last ${last_price:.2f}, spread {spread_pct:.1f}%) "
                              f"via {hub_src}")
                    elif hub_bid > 0 and spread_pct >= 50 and last_price > 0:
                        stc_signal['price'] = last_price
                        print(f"[RISK] ⚠️ Wide spread {spread_pct:.1f}% on SL exit (bid ${hub_bid:.2f}, ask ${hub_ask:.2f}) — "
                              f"using last ${last_price:.2f} instead of stale bid")
                    elif hub_bid > 0:
                        stc_signal['price'] = hub_bid
                        print(f"[RISK] 💰 SL exit: bid ${hub_bid:.2f} (wide spread but no last price) via {hub_src}")
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
            
            sl_triggers = ('stop_loss', 'trailing_stop', 'early_trailing', 'giveback_guard', 'dynamic_sl')
            is_sl_type_exit = decision.risk_trigger in sl_triggers
            if is_sl_type_exit and channel_settings and channel_settings.sl_order_mode == 'market':
                use_market = True
                print(f"[RISK] 📊 SL Market Order mode enabled - using market order for {decision.risk_trigger}")

            _emergency_triggers = ('stop_loss', 'dynamic_sl')
            if not use_market and is_sl_type_exit and decision.risk_trigger in _emergency_triggers:
                use_market = True
                print(f"[RISK] 📊 TIERED URGENCY: {decision.risk_trigger} → auto market order (critical SL exit)")

            if not use_market and is_sl_type_exit and decision.risk_trigger in ('trailing_stop', 'early_trailing', 'giveback_guard'):
                stc_signal['_aggressive_chase'] = True
                stc_signal['_chase_max_attempts'] = 1
                stc_signal['_chase_timeout'] = 1
                print(f"[RISK] 📊 TIERED URGENCY: {decision.risk_trigger} → aggressive chase (1 attempt, 1s)")

            if not use_market and is_sl_type_exit and cache and cache.entry_price > 0:
                _raw_pnl = ((position.current_price - cache.entry_price) / cache.entry_price) * 100
                if _raw_pnl < 0:
                    _loss_pct = abs(_raw_pnl)
                    _configured_sl = channel_settings.stop_loss_pct if channel_settings and channel_settings.stop_loss_pct > 0 else 15.0
                    if _loss_pct >= _configured_sl * 2:
                        use_market = True
                        print(f"[RISK] 📊 EMERGENCY OVERRIDE: loss {_loss_pct:.1f}% >= 2x SL {_configured_sl}% → immediate market order")

            if is_sl_type_exit and channel_settings and channel_settings.sl_order_mode == 'limit' and not use_market:
                sl_offset = channel_settings.sl_limit_offset if channel_settings.sl_limit_offset is not None else 0.03
                if sl_offset > 0:
                    original_price = stc_signal['price']
                    _sl_precision = 4 if is_penny_stock else 2
                    offset_price = round(original_price * (1 - sl_offset), _sl_precision)
                    stc_signal['price'] = offset_price
                    stc_signal['_sl_limit_offset_applied'] = True
                    print(f"[RISK] 📊 SL Limit Offset: trigger ${original_price:.4f} → limit ${offset_price:.4f} ({sl_offset*100:.1f}% below)")
            
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
                print(f"[RISK] 📊 Penny stock (${position.current_price:.4f}) — using limit order per channel settings")

            if not use_market and 'TRADING212' in position.broker.upper():
                if getattr(self.trading212_broker, 'is_live', False):
                    pass
                else:
                    use_market = True
                    print(f"[RISK] 📊 Trading212 DEMO exit → market order (trigger: {decision.risk_trigger or 'unknown'})")

            if use_market:
                stc_signal['_use_market_order'] = True
                print(f"[RISK] 📊 Market order mode - using current price ${position.current_price:.2f}")
            
            stc_signal['_exit_marker_key'] = pos_key
            
            await self.order_queue.put(stc_signal)
            print(f"[RISK] STC order queued for {pos_key} via {position.broker} (queue_id={id(self.order_queue)}, qsize={self.order_queue.qsize()}): {stc_signal}")

            if _need_replace_stop and cache:
                import time as _tmod
                _replace_price = _old_stop_price if _old_stop_price and _old_stop_price > 0 else (cache.dynamic_sl_price if cache.dynamic_sl_price is not None else cache.early_stop_price if cache.early_stop_price is not None else cache.stop_loss_price) or 0
                if _replace_price and _replace_price > 0:
                    cache._pending_broker_sl_replace = True
                    cache._pending_sl_replace_price = _replace_price
                    cache._sl_cancelled_at = _tmod.time()
                    print(f"[RISK] 🔄 Will re-place broker SL at ${_replace_price:.2f} after PT sell fills (deferred ~15s)")

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
                _exit_expiry = stc_signal.get('expiry', '')
                _exit_expiry_year = stc_signal.get('expiry_year')
                if 'IBKR' in broker_upper or 'TASTYTRADE' in broker_upper:
                    if _exit_expiry_year and '/' in _exit_expiry and '-' not in _exit_expiry:
                        _parts = _exit_expiry.split('/')
                        if len(_parts) == 2:
                            _exit_expiry = f"{_exit_expiry_year}-{_parts[0].zfill(2)}-{_parts[1].zfill(2)}"
                option_kwargs = {
                    'symbol': stc_signal['symbol'],
                    'strike': stc_signal.get('strike'),
                    'expiry': _exit_expiry,
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
                _stk_exit_kwargs = {
                    'symbol': stc_signal['symbol'],
                    'quantity': stc_signal['qty'],
                    'price': order_price,
                    'action': 'STC',
                }
                if 'WEBULL' in broker_upper and stc_signal.get('price'):
                    import inspect
                    _stk_sig = inspect.signature(broker_instance.place_stock_order)
                    _accepts_kwargs = any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in _stk_sig.parameters.values()
                    )
                    if _accepts_kwargs:
                        _stk_exit_kwargs['_signal_price_fallback'] = stc_signal['price']
                        if stc_signal.get('_use_market_order'):
                            _stk_exit_kwargs['force_market'] = True
                result = await broker_instance.place_stock_order(**_stk_exit_kwargs)
            
            order_id = None
            if isinstance(result, dict):
                order_id = result.get('order_id') or result.get('orderId') or result.get('id')
            elif hasattr(result, 'success'):
                if result.success:
                    order_id = getattr(result, 'order_id', None) or getattr(result, 'orderId', None)
                    if not order_id and hasattr(result, 'data') and isinstance(result.data, dict):
                        order_id = result.data.get('order_id') or result.data.get('orderId')
                    if not order_id:
                        order_id = f"ok-{pos_key[:20]}"
                else:
                    _fail_msg = getattr(result, 'message', str(result))
                    print(f"[RISK] [DIRECT-EXIT] ⚠️ {pos_key} broker returned failure: {_fail_msg}")
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
                print(f"[RISK] [DIRECT-EXIT] ⚠️ {pos_key} no order_id — resetting closing state for retry")
                is_sl = stc_signal.get('risk_trigger', '') in ('stop_loss', 'trailing_stop', 'early_trailing', 'giveback_guard')
                self.cache.record_exit_failure(pos_key, reason="direct_exit_no_order_id", is_stop_loss=is_sl)
            self.release_exit_marker(pos_key)
        except Exception as e:
            print(f"[RISK] [DIRECT-EXIT] ✗ {pos_key} execution failed: {e}")
            import traceback
            traceback.print_exc()
            is_sl = stc_signal.get('risk_trigger', '') in ('stop_loss', 'trailing_stop', 'early_trailing', 'giveback_guard')
            self.cache.record_exit_failure(pos_key, reason=f"direct_exit_exception: {e}", is_stop_loss=is_sl)
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
                _mid_precision = 4 if (bid > 0 and bid < 1.0) or (ask > 0 and ask < 1.0) else 2
                mid = round((bid + ask) / 2, _mid_precision) if bid > 0 and ask > 0 else 0
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
        if not position.current_price or position.current_price <= 0:
            print(f"[RISK] ⚠️ Cannot build STC signal for {position.position_key} — current_price is ${position.current_price} (no valid price)")
            return None
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
                    SELECT UPPER(symbol) as symbol, UPPER(broker) as broker, id as trade_id
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
                
                has_open_trade = (symbol, (broker or '').upper()) in open_trade_symbols
                
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
                _is_opt_pos = position.asset == 'option'
                _fresh_lookup = position.raw_symbol if (_is_opt_pos and hasattr(position, 'raw_symbol') and position.raw_symbol) else position.symbol
                try:
                    from src.services.webull_data_hub import get_webull_data_hub
                    hub = get_webull_data_hub()
                    if hub:
                        fresh_price = self._get_fresh_hub_price(hub, _fresh_lookup, max_age=60)
                except Exception:
                    pass
                if not fresh_price:
                    try:
                        from src.services.schwab_data_hub import get_schwab_data_hub
                        s_hub = get_schwab_data_hub()
                        if s_hub:
                            _schwab_lk = _fresh_lookup
                            if _is_opt_pos:
                                _s_keys = self._get_option_hub_keys(position, 'Schwab')
                                _schwab_lk = _s_keys[0] if _s_keys else _fresh_lookup
                            fresh_price = self._get_fresh_hub_price(s_hub, _schwab_lk, max_age=60)
                    except Exception:
                        pass
                if not fresh_price:
                    try:
                        from src.services.ibkr_data_hub import get_ibkr_data_hub
                        ib_hub = get_ibkr_data_hub()
                        if ib_hub and ib_hub.is_streaming():
                            _ibkr_lk = _fresh_lookup
                            if _is_opt_pos:
                                _i_keys = self._get_option_hub_keys(position, 'IBKR')
                                _ibkr_lk = _i_keys[0] if _i_keys else _fresh_lookup
                            fresh_price = self._get_fresh_hub_price(ib_hub, _ibkr_lk, max_age=60)
                    except Exception:
                        pass
                if fresh_price and _is_opt_pos and entry_price > 0 and (fresh_price / entry_price) > 50:
                    fresh_price = None

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
        if hasattr(quote, 'last') and quote.last and quote.last > 0:
            return quote.last
        if hasattr(quote, 'bid') and hasattr(quote, 'ask'):
            bid = quote.bid or 0
            ask = quote.ask or 0
            if bid > 0 and ask > 0:
                return (bid + ask) / 2
            if bid > 0:
                return bid
            if ask > 0:
                return ask
        return None

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

        _tracked_keys = set(self.cache.get_all_trade_id_keys())

        stuck_candidates = []
        for pos in positions:
            key = self._pos_tracking_key(pos)
            _pos_key = pos.position_key
            if _pos_key not in _tracked_keys:
                tracker = self._stuck_price_tracker.get(key)
                if tracker is None:
                    self._stuck_price_tracker[key] = {
                        'last_price': pos.current_price,
                        'last_changed': now,
                        'rest_refreshed': 0
                    }
                elif abs(pos.current_price - tracker['last_price']) > 0.0001:
                    tracker['last_price'] = pos.current_price
                    tracker['last_changed'] = now
                continue
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
                if key in self._rest_validated_same:
                    del self._rest_validated_same[key]
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

            effective_threshold = self._STUCK_PRICE_THRESHOLD
            if session == 'extended':
                effective_threshold = 15.0
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
                _cross_hub_confirmed_same = False
                _sanity_rejected = False
                if fresh_price and fresh_price > 0 and abs(fresh_price - pos.current_price) < 0.0001:
                    _cross_hub_confirmed_same = True
                if not fresh_price or abs(fresh_price - pos.current_price) < 0.0001:
                    _already_validated = key in self._rest_validated_same
                    _rest_limit = _MAX_REST_REPAIRS_PER_CYCLE if not _already_validated else _MAX_REST_REPAIRS_PER_CYCLE + 4
                    if rest_repairs_this_cycle < _rest_limit:
                        tracker['rest_refreshed'] = now
                        rest_price = await self._try_rest_quote(pos)
                        _rest_checked = rest_price is not None
                        if _rest_checked:
                            tracker['rest_checked_ok'] = now
                        if rest_price and rest_price > 0:
                            fresh_price = rest_price
                            rest_via = getattr(self, '_last_rest_source', None)
                            source = f'REST/{rest_via}' if rest_via else 'REST'
                            if abs(rest_price - pos.current_price) > 0.0001:
                                rest_repairs_this_cycle += 1
                if fresh_price and fresh_price > 0 and source and 'REST' in source:
                    cache_entry = self.cache.get(key) or self.cache.get(f"{pos.broker}_{pos.symbol}")
                    if cache_entry and cache_entry.entry_price > 0:
                        entry = cache_entry.entry_price
                        rest_deviation = abs(fresh_price - entry) / entry if entry > 0 else 0
                        streaming_deviation = abs(pos.current_price - entry) / entry if entry > 0 else 0
                        if rest_deviation > 0.30 and streaming_deviation < 0.10:
                            print(f"[RISK] 🛡️ REST SANITY REJECT: {pos.symbol} REST=${fresh_price:.2f} "
                                  f"is {rest_deviation*100:.0f}% from entry ${entry:.2f} but streaming "
                                  f"shows ${pos.current_price:.2f} ({streaming_deviation*100:.1f}% dev) — rejecting stale REST price")
                            fresh_price = None
                            _sanity_rejected = True
                    if fresh_price and fresh_price > 0 and pos.current_price > 0:
                        price_jump = abs(fresh_price - pos.current_price) / pos.current_price
                        _jump_threshold = 0.30 if session == 'regular' else 0.80
                        if price_jump > _jump_threshold:
                            print(f"[RISK] 🛡️ REST SANITY REJECT: {pos.symbol} REST=${fresh_price:.2f} "
                                  f"is {price_jump*100:.0f}% jump from streaming ${pos.current_price:.2f} — "
                                  f"rejecting suspicious REST price (session={session})")
                            fresh_price = None
                            _sanity_rejected = True

                if fresh_price and fresh_price > 0 and abs(fresh_price - pos.current_price) > 0.0001:
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
                    self._rest_confirmed_this_cycle[key] = now
                    if key in self._rest_validated_same:
                        del self._rest_validated_same[key]
                elif not _sanity_rejected and (_rest_checked or _cross_hub_confirmed_same):
                    if stuck_seconds >= self._STUCK_PRICE_THRESHOLD:
                        import time as _vs
                        _val_source = 'REST' if _rest_checked else 'cross-hub'
                        self._rest_validated_same[key] = _vs.time()
                        if stuck_seconds >= self._STALENESS_EXIT_BLOCK_THRESHOLD:
                            print(f"[RISK] ✓ PRICE VALIDATED ({_val_source}): {pos.broker} {pos.symbol} frozen {stuck_seconds:.0f}s — "
                                  f"confirmed price ${pos.current_price:.4f} is real (same from all sources)")
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
        stale_in_flight = [k for k in self._partial_exit_in_flight if not any(k.startswith(ak) for ak in active_keys)]
        for k in stale_in_flight:
            del self._partial_exit_in_flight[k]
        stale_validated = [k for k in self._rest_validated_same if k not in active_keys]
        for k in stale_validated:
            del self._rest_validated_same[k]
        import time as _ttl_check
        _ttl_expired = [k for k, ts in self._rest_validated_same.items() 
                        if (_ttl_check.time() - ts) > 60]
        for k in _ttl_expired:
            del self._rest_validated_same[k]
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

    @staticmethod
    def _is_hub_live(hub):
        import time as _hl
        ts = getattr(hub, '_last_quote_ts', 0)
        if ts <= 0:
            return False
        if (_hl.time() - ts) > 120:
            return False
        return True

    def _try_cross_hub_price(self, pos, now):
        broker_upper = (pos.broker or '').upper()
        is_option = pos.asset == 'option'
        alt_hubs = []
        if 'WEBULL' not in broker_upper:
            try:
                from src.services.webull_data_hub import get_webull_data_hub
                wb_hub = get_webull_data_hub()
                if wb_hub.is_streaming() and self._is_hub_live(wb_hub):
                    alt_hubs.append(('Webull', wb_hub))
            except Exception:
                pass
        if 'SCHWAB' not in broker_upper:
            try:
                from src.services.schwab_data_hub import get_schwab_data_hub
                sc_hub = get_schwab_data_hub()
                if sc_hub.is_streaming() and self._is_hub_live(sc_hub):
                    alt_hubs.append(('Schwab', sc_hub))
            except Exception:
                pass
        if 'IBKR' not in broker_upper:
            try:
                from src.services.ibkr_data_hub import get_ibkr_data_hub
                ib_hub = get_ibkr_data_hub()
                if ib_hub.is_streaming() and self._is_hub_live(ib_hub):
                    alt_hubs.append(('IBKR', ib_hub))
            except Exception:
                pass
        if 'TASTYTRADE' not in broker_upper and 'TASTY' not in broker_upper:
            try:
                from src.services.tastytrade_data_hub import get_tastytrade_data_hub
                tt_hub = get_tastytrade_data_hub()
                if tt_hub and tt_hub.is_streaming() and self._is_hub_live(tt_hub):
                    alt_hubs.append(('Tastytrade', tt_hub))
            except Exception:
                pass
        for hub_name, hub in alt_hubs:
            if is_option:
                opt_keys = self._get_option_hub_keys(pos, hub_name)
                for ok in opt_keys:
                    price = self._get_fresh_hub_price(hub, ok, max_age=2)
                    if price and price > 0:
                        if pos.avg_cost > 0 and (price / pos.avg_cost) > 50:
                            continue
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

        _last_valid_rest = None
        if not is_option:
            if 'WEBULL' in broker_upper:
                price = await self._try_schwab_rest_quote(pos.symbol)
                if price and price > 0:
                    _last_valid_rest = price
                    if abs(price - current) > 0.0001:
                        self._last_rest_source = 'Schwab'
                        return price
                price = await self._try_webull_rest_quote(pos.symbol)
                if price and price > 0:
                    _last_valid_rest = price
                    if abs(price - current) > 0.0001:
                        self._last_rest_source = 'Webull'
                        return price
            elif 'SCHWAB' in broker_upper:
                price = await self._try_webull_rest_quote(pos.symbol)
                if price and price > 0:
                    _last_valid_rest = price
                    if abs(price - current) > 0.0001:
                        self._last_rest_source = 'Webull'
                        return price
                price = await self._try_schwab_rest_quote(pos.symbol)
                if price and price > 0:
                    _last_valid_rest = price
                    if abs(price - current) > 0.0001:
                        self._last_rest_source = 'Schwab'
                        return price
            else:
                price = await self._try_schwab_rest_quote(pos.symbol)
                if price and price > 0:
                    _last_valid_rest = price
                    if abs(price - current) > 0.0001:
                        self._last_rest_source = 'Schwab'
                        return price
                price = await self._try_webull_rest_quote(pos.symbol)
                if price and price > 0:
                    _last_valid_rest = price
                    if abs(price - current) > 0.0001:
                        self._last_rest_source = 'Webull'
                        return price

        if not is_option:
            price = await self._try_broker_get_quote(pos)
            if price and price > 0:
                _last_valid_rest = price
                if abs(price - current) > 0.0001:
                    self._last_rest_source = pos.broker
                    return price
        if _last_valid_rest and _last_valid_rest > 0:
            self._last_rest_source = 'confirmed-same'
            return _last_valid_rest
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
                premarket_price = float(raw_quote.get('pPrice', 0) or 0)
                session = self._get_market_session()
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                elif premarket_price > 0:
                    return premarket_price
                elif session == 'regular' and last > 0:
                    return last
                elif session != 'regular' and last > 0:
                    print(f"[RISK] 🛡️ REST GUARD: Webull {symbol} REST returned last=${last:.2f} "
                          f"with bid/ask=0 during {session} hours — rejecting stale close/last price")
                    return None
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
                    'needExtendedHoursData': 'true'}
        )
        if response and response.status_code == 200:
            data = response.json()
            if symbol in data:
                quote = data[symbol].get('quote', {})
                bid = float(quote.get('bidPrice', 0) or 0)
                ask = float(quote.get('askPrice', 0) or 0)
                last = float(quote.get('lastPrice', 0) or 0)
                session = self._get_market_session()
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                elif session == 'regular' and last > 0:
                    return last
                elif session != 'regular' and last > 0:
                    print(f"[RISK] 🛡️ REST GUARD: Schwab {symbol} REST returned lastPrice=${last:.2f} "
                          f"with bid/ask=0 during {session} hours — rejecting RTH-only lastPrice")
                    return None
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
                        if pos.raw_symbol:
                            price = self._get_fresh_hub_price(hub, pos.raw_symbol)
                        if not price:
                            lk_check = pos.raw_symbol
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
                        if pos.asset == 'option' and pos.avg_cost > 0:
                            _hub_ratio = price / pos.avg_cost
                            if _hub_ratio > 50:
                                _sym = pos.symbol or pos.raw_symbol or '?'
                                if not hasattr(self, '_hub_idx_guard_ts'):
                                    self._hub_idx_guard_ts = {}
                                import time as _hig
                                _hig_now = _hig.time()
                                if _sym not in self._hub_idx_guard_ts or (_hig_now - self._hub_idx_guard_ts.get(_sym, 0)) > 30:
                                    self._hub_idx_guard_ts[_sym] = _hig_now
                                    print(f"[RISK] ⚠️ HUB INDEX GUARD: {_sym} hub price ${price:.2f} is {_hub_ratio:.0f}x entry ${pos.avg_cost:.2f} "
                                          f"— likely underlying index price leaked into option quote. Rejecting hub price.")
                                continue
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
                        if pos.asset == 'option' and pos.avg_cost > 0 and (price / pos.avg_cost) > 50:
                            _sym = pos.symbol or pos.raw_symbol or '?'
                            if not hasattr(self, '_hub_idx_guard_ts'):
                                self._hub_idx_guard_ts = {}
                            import time as _hig2
                            _hig2_now = _hig2.time()
                            if _sym not in self._hub_idx_guard_ts or (_hig2_now - self._hub_idx_guard_ts.get(_sym, 0)) > 30:
                                self._hub_idx_guard_ts[_sym] = _hig2_now
                                print(f"[RISK] ⚠️ HUB INDEX GUARD: Schwab {_sym} hub price ${price:.2f} is {price/pos.avg_cost:.0f}x entry ${pos.avg_cost:.2f} — rejecting")
                            continue
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
                        if pos.asset == 'option' and pos.avg_cost > 0 and (price / pos.avg_cost) > 50:
                            _sym = pos.symbol or pos.raw_symbol or '?'
                            if not hasattr(self, '_hub_idx_guard_ts'):
                                self._hub_idx_guard_ts = {}
                            import time as _hig3
                            _hig3_now = _hig3.time()
                            if _sym not in self._hub_idx_guard_ts or (_hig3_now - self._hub_idx_guard_ts.get(_sym, 0)) > 30:
                                self._hub_idx_guard_ts[_sym] = _hig3_now
                                print(f"[RISK] ⚠️ HUB INDEX GUARD: IBKR {_sym} hub price ${price:.2f} is {price/pos.avg_cost:.0f}x entry ${pos.avg_cost:.2f} — rejecting")
                            continue
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
                        if pos.asset == 'option' and pos.avg_cost > 0 and (price / pos.avg_cost) > 50:
                            _sym = pos.symbol or pos.raw_symbol or '?'
                            if not hasattr(self, '_hub_idx_guard_ts'):
                                self._hub_idx_guard_ts = {}
                            _hig4_now = _tt_time.time()
                            if _sym not in self._hub_idx_guard_ts or (_hig4_now - self._hub_idx_guard_ts.get(_sym, 0)) > 30:
                                self._hub_idx_guard_ts[_sym] = _hig4_now
                                print(f"[RISK] ⚠️ HUB INDEX GUARD: TastyTrade {_sym} hub price ${price:.2f} is {price/pos.avg_cost:.0f}x entry ${pos.avg_cost:.2f} — rejecting")
                            continue
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
                if _is_opt and pos.avg_cost > 0 and (_cp / pos.avg_cost) > 50:
                    continue
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
                        broker_upper = (pos.broker or '').upper()
                        if broker_upper in ('TRADING212',):
                            continue
                        uph.shadow_compare(
                            pos.symbol,
                            pos.current_price,
                            f"{pos.broker}_risk",
                            asset_type=pos.asset,
                            broker_hint=pos.broker,
                            raw_symbol=pos.raw_symbol,
                        )
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

        # COLD-START / STALE INDICATOR:
        # If current_price equals entry exactly AND we have NEVER observed a
        # price different from entry for this position, the broker REST is just
        # echoing the fill price (marketValue = qty × avg_cost) because the live
        # quote/stream hasn't arrived yet. Tag the line so the user knows it's
        # not real movement. The tag clears permanently the moment ANY tick
        # differs from entry — even if price later returns to entry.
        if not hasattr(self, '_init_real_tick_seen'):
            self._init_real_tick_seen = set()
        _init_tag = ""
        try:
            if current and entry and abs(current - entry) >= 1e-6:
                self._init_real_tick_seen.add(pos_key)
            elif current and entry and pos_key not in self._init_real_tick_seen:
                _init_tag = " | [INIT]"
        except Exception:
            pass
        
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
                  f"Entry: ${entry:.2f} | SL: ${sl_price or 'N/A'} | Target: ${target_price or 'N/A'} | Qty: {qty}{trailing_status}{enhanced_status}{_init_tag}")
        elif channel_settings:
            sl_display = f"{channel_settings.stop_loss_pct}%"
            if cache and cache.manual_sl_price is not None:
                sl_display = f"${cache.manual_sl_price:.2f} [OVERRIDE]"
            elif cache and cache.manual_sl_pct is not None:
                sl_display = f"{cache.manual_sl_pct:.1f}% [OVERRIDE]"
            print(f"[RISK] [{channel_name}] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | Targets: {channel_settings.profit_target_1_pct}/"
                  f"{channel_settings.profit_target_2_pct}/{channel_settings.profit_target_3_pct}% | "
                  f"SL: {sl_display} | {trailing_display} | Qty: {qty}{trailing_status}{enhanced_status}{_init_tag}")
        else:
            print(f"[RISK] [Manual Trade] {pos_key}: ${current:.2f} ({pct_change:+.2f}%) | "
                  f"Entry: ${entry:.2f} | Qty: {qty}{trailing_status}{_init_tag}")
