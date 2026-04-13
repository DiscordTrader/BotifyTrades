"""
Signal Routing Engine
======================
Core engine for signal routing with forwarding-only architecture.
No broker execution - uses broker API only for price monitoring.

Features:
- BTO forwarding with configurable quantity (fixed QTY or Size %)
- Real-time price monitoring via broker API (read-only)
- Risk-based exits using monitored prices
- Webhook posting with retry and dedupe
- Stale price protection
- Market hours awareness
"""

import asyncio
import aiohttp
import time
import json
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import math

from src.services.position_ledger import (
    get_position_ledger,
    LedgerPosition,
    PositionLedger,
    PositionStatus,
    ExitArbiter,
    ExitReason,
    PartialExit
)
from src.services.price_monitor_service import get_price_monitor, PriceMonitorService
from src.services.quote_aggregator import get_quote_aggregator
from src.services.market_hours import (
    get_market_status,
    is_options_trading_hours,
    format_market_status
)


class ExitStrategyMode(Enum):
    SIGNAL = "signal"
    RISK = "risk"
    HYBRID = "hybrid"


DYNAMIC_SL_PROFILES = {
    'conservative': {
        'pt1_sl_pct': 0,
        'pt2_sl_pct': 3,
        'pt3_sl_pct': 10,
        'pt4_sl_pct': 20
    },
    'standard': {
        'pt1_sl_pct': 0,
        'pt2_sl_pct': 5,
        'pt3_sl_pct': 15,
        'pt4_sl_pct': 25
    },
    'aggressive': {
        'pt1_sl_pct': -2,
        'pt2_sl_pct': 0,
        'pt3_sl_pct': 10,
        'pt4_sl_pct': 20
    }
}


@dataclass
class RoutingMappingConfig:
    """Configuration for a signal routing mapping."""
    id: int = 0
    name: str = ""
    source_channel_id: str = ""
    destination_url: str = ""
    
    default_quantity: int = 1
    size_percent: Optional[float] = None
    
    enable_forwarding: bool = True
    enable_risk_management: bool = True
    exit_strategy_mode: ExitStrategyMode = ExitStrategyMode.RISK
    
    stop_loss_pct: float = 25.0
    pt1_pct: float = 15.0
    pt2_pct: float = 30.0
    pt3_pct: float = 50.0
    pt4_pct: float = 100.0
    pt1_qty: Optional[int] = None
    pt2_qty: Optional[int] = None
    pt3_qty: Optional[int] = None
    pt4_qty: Optional[int] = None
    pt1_trim_pct: Optional[float] = None
    pt2_trim_pct: Optional[float] = None
    pt3_trim_pct: Optional[float] = None
    pt4_trim_pct: Optional[float] = None
    
    trailing_stop_pct: float = 0.0
    trailing_activation_pct: float = 15.0
    leave_runner_enabled: bool = False
    leave_runner_size_pct: float = 25.0
    
    dynamic_sl_escalation_enabled: bool = False
    sl_escalation_profile: str = "standard"
    max_profit_giveback_enabled: bool = False
    max_profit_giveback_pct: float = 30.0
    
    enable_early_trailing: bool = False
    early_trailing_activation_pct: float = 5.0
    early_trailing_step_pct: float = 3.0
    escalation_only_mode: bool = False
    
    ema_risk_enabled: bool = False
    ema_period: int = 5
    ema_timeframe_minutes: int = 5
    ema_buffer_pct: float = 0.1
    ema_exit_enabled: bool = True
    ema_escalation_enabled: bool = True
    ema_extended_hours: bool = False
    ema_use_underlying: bool = True
    ema_no_trend_candles: int = 3
    
    trim_order_type: str = 'market'
    sl_order_type: str = 'limit'
    trim_limit_offset: float = 0.01
    trim_limit_offset_mode: str = 'dollar'
    trim_limit_offset_pct: float = 2.0
    sl_limit_offset: float = 0.03


@dataclass
class WebhookMessage:
    """A message queued for webhook delivery."""
    id: str = ""
    url: str = ""
    content: str = ""
    position_id: int = 0
    exit_reason: str = ""
    exit_qty: int = 0
    attempts: int = 0
    max_attempts: int = 3
    created_at: float = field(default_factory=time.time)
    last_attempt: float = 0.0
    delivered: bool = False


class SignalRoutingEngine:
    """
    Core engine for signal routing with forwarding-only architecture.
    
    Flow:
    1. Entry: Forward BTO to webhook, register in ledger
    2. Monitor: Fetch prices from broker API (read-only)
    3. Exit: Post STC with current price when conditions met
    """
    
    _instance: Optional['SignalRoutingEngine'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.ledger = get_position_ledger()
        self.price_monitor = get_price_monitor()
        self.exit_arbiter = self.ledger.exit_arbiter
        
        self._configs: Dict[str, RoutingMappingConfig] = {}
        self._webhook_queue: List[WebhookMessage] = []
        self._webhook_delivered: Set[str] = set()
        self._session: Optional[aiohttp.ClientSession] = None
        
        self._stale_price_threshold_sec = 30
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._ema_last_candle_ts: Dict[str, Any] = {}
        
        self._initialized = True
        print("[ROUTING_ENGINE] ✓ SignalRoutingEngine initialized (using shared ExitArbiter)")
    
    def _preload_all_routing_configs(self) -> int:
        """
        Preload all enabled routing configs from database.
        
        Called at startup to ensure all configs are available for
        risk evaluation of existing positions.
        
        Returns: Number of configs loaded
        """
        loaded = 0
        try:
            from gui_app.database import get_signal_routing_mappings
            mappings = get_signal_routing_mappings(enabled_only=True)
            
            for mapping in mappings:
                config = self.load_mapping_config(mapping)
                loaded += 1
                print(f"[ROUTING_ENGINE] Preloaded config id={config.id} for channel {config.source_channel_id}")
            
        except Exception as e:
            import traceback
            print(f"[ROUTING_ENGINE] ⚠️ Failed to preload routing configs: {e}")
            traceback.print_exc()
        
        return loaded
    
    async def fetch_initial_mark_price(self, position_id: int, position: LedgerPosition) -> bool:
        """
        Fetch and set initial_mark_price immediately after position creation.
        
        This eliminates the delay from waiting for the poll loop.
        Called right after create_position() to get instant price data.
        
        Returns True if price was successfully fetched and set.
        """
        try:
            if not self.price_monitor:
                print(f"[ROUTING_ENGINE] ⚠️ Price monitor not available for immediate fetch")
                return False
            
            price = await self.price_monitor.get_option_price(
                symbol=position.symbol,
                strike=position.strike,
                expiry=position.expiry,
                option_type=position.option_type
            )
            
            if price and price > 0:
                self.ledger.update_price(position_id, price, staleness_sec=0)
                print(f"[ROUTING_ENGINE] ✓ Immediate mark price: ${price:.2f} for {position.option_key}")
                return True
            else:
                print(f"[ROUTING_ENGINE] ⚠️ Could not fetch immediate price for {position.option_key}")
                return False
                
        except Exception as e:
            print(f"[ROUTING_ENGINE] ⚠️ Immediate price fetch failed: {e}")
            return False
    
    def load_mapping_config(self, mapping: Dict[str, Any]) -> RoutingMappingConfig:
        """Load configuration from database mapping dict."""
        exit_mode_str = mapping.get('exit_strategy_mode', 'risk')
        try:
            exit_mode = ExitStrategyMode(exit_mode_str)
        except ValueError:
            exit_mode = ExitStrategyMode.RISK
        
        config = RoutingMappingConfig(
            id=mapping.get('id', 0),
            name=mapping.get('name', ''),
            source_channel_id=str(mapping.get('source_channel_id', '')),
            destination_url=mapping.get('destination_url', ''),
            default_quantity=mapping.get('default_quantity', 1) or 1,
            size_percent=mapping.get('default_dollar_amount'),
            enable_forwarding=bool(mapping.get('enable_forwarding', 1)),
            enable_risk_management=bool(mapping.get('enable_risk_management', 1)),
            exit_strategy_mode=exit_mode,
            stop_loss_pct=mapping.get('stop_loss_pct', 25.0) or 25.0,
            pt1_pct=mapping.get('pt1_pct', 15.0) or 15.0,
            pt2_pct=mapping.get('pt2_pct', 30.0) or 30.0,
            pt3_pct=mapping.get('pt3_pct', 50.0) or 50.0,
            pt4_pct=mapping.get('pt4_pct', 100.0) or 100.0,
            pt1_qty=mapping.get('pt1_qty'),
            pt2_qty=mapping.get('pt2_qty'),
            pt3_qty=mapping.get('pt3_qty'),
            pt4_qty=mapping.get('pt4_qty'),
            pt1_trim_pct=mapping.get('pt1_trim_pct'),
            pt2_trim_pct=mapping.get('pt2_trim_pct'),
            pt3_trim_pct=mapping.get('pt3_trim_pct'),
            pt4_trim_pct=mapping.get('pt4_trim_pct'),
            trailing_stop_pct=mapping.get('trailing_stop_pct', 0.0) or 0.0,
            trailing_activation_pct=mapping.get('trailing_activation_pct', 15.0) or 15.0,
            leave_runner_enabled=bool(mapping.get('leave_runner_enabled', 0)),
            leave_runner_size_pct=mapping.get('leave_runner_size_pct', 25.0) or 25.0,
            dynamic_sl_escalation_enabled=bool(mapping.get('dynamic_sl_escalation_enabled', 0)),
            sl_escalation_profile=mapping.get('sl_escalation_profile', 'standard') or 'standard',
            max_profit_giveback_enabled=bool(mapping.get('max_profit_giveback_enabled', 0)),
            max_profit_giveback_pct=mapping.get('max_profit_giveback_pct', 30.0) or 30.0,
            enable_early_trailing=bool(mapping.get('enable_early_trailing', 0)),
            early_trailing_activation_pct=mapping.get('early_trailing_activation_pct', 5.0) or 5.0,
            early_trailing_step_pct=mapping.get('early_trailing_step_pct', 3.0) or 3.0,
            escalation_only_mode=bool(mapping.get('escalation_only_mode', 0)),
            ema_risk_enabled=bool(mapping.get('ema_risk_enabled', 0)),
            ema_period=mapping.get('ema_period', 5) or 5,
            ema_timeframe_minutes=mapping.get('ema_timeframe_minutes', 5) or 5,
            ema_buffer_pct=mapping.get('ema_buffer_pct', 0.1) if mapping.get('ema_buffer_pct') is not None else 0.1,
            ema_exit_enabled=bool(mapping.get('ema_exit_enabled', 1)) if mapping.get('ema_exit_enabled') is not None else True,
            ema_escalation_enabled=bool(mapping.get('ema_escalation_enabled', 1)) if mapping.get('ema_escalation_enabled') is not None else True,
            ema_extended_hours=bool(mapping.get('ema_extended_hours', 0)),
            ema_use_underlying=bool(mapping.get('ema_use_underlying', 1)) if mapping.get('ema_use_underlying') is not None else True,
            ema_no_trend_candles=mapping.get('ema_no_trend_candles', 3) or 3,
            trim_order_type=mapping.get('trim_order_type', 'market') or 'market',
            sl_order_type=mapping.get('sl_order_type', 'limit') or 'limit',
            trim_limit_offset=mapping.get('trim_limit_offset', 0.01) if mapping.get('trim_limit_offset') is not None else 0.01,
            trim_limit_offset_mode=mapping.get('trim_limit_offset_mode', 'dollar') or 'dollar',
            trim_limit_offset_pct=mapping.get('trim_limit_offset_pct', 2.0) if mapping.get('trim_limit_offset_pct') is not None else 2.0,
            sl_limit_offset=mapping.get('sl_limit_offset', 0.03) if mapping.get('sl_limit_offset') is not None else 0.03,
        )
        
        self._configs[config.source_channel_id] = config
        return config
    
    def request_config_invalidation(self, source_channel_id: Optional[str] = None):
        """Thread-safe request for config cache invalidation from Flask threads.
        
        Sets a flag that the routing engine's monitoring loop will process.
        This avoids cross-thread dict mutation.
        
        Args:
            source_channel_id: If provided, only invalidate that channel's config.
                             If None, invalidate all configs.
        """
        if not hasattr(self, '_pending_invalidations'):
            self._pending_invalidations: list = []
        self._pending_invalidations.append(source_channel_id)
        print(f"[ROUTING_ENGINE] ♻️ Config invalidation requested for: {source_channel_id or 'ALL'}")
    
    def _process_pending_invalidations(self):
        """Process any pending config invalidation requests (called from engine's own loop)."""
        if not hasattr(self, '_pending_invalidations') or not self._pending_invalidations:
            return
        
        pending = list(self._pending_invalidations)
        self._pending_invalidations.clear()
        
        if None in pending:
            self._configs.clear()
            count = self._preload_all_routing_configs()
            print(f"[ROUTING_ENGINE] ♻️ Reloaded all routing configs ({count} loaded)")
        else:
            for channel_id in set(pending):
                if channel_id in self._configs:
                    del self._configs[channel_id]
                    print(f"[ROUTING_ENGINE] ♻️ Invalidated config cache for channel {channel_id}")
            for channel_id in set(pending):
                try:
                    from gui_app.database import get_signal_routing_by_source
                    mapping = get_signal_routing_by_source(channel_id)
                    if mapping and mapping.get('enabled'):
                        self.load_mapping_config(mapping)
                        print(f"[ROUTING_ENGINE] ♻️ Reloaded config for channel {channel_id}")
                except Exception as e:
                    print(f"[ROUTING_ENGINE] ⚠️ Could not reload config for {channel_id}: {e}")
    
    def get_routing_config(self, routing_mapping_id: Optional[int]) -> Optional[RoutingMappingConfig]:
        """Get routing config by mapping ID."""
        if routing_mapping_id is None:
            return None
        for config in self._configs.values():
            if config.id == routing_mapping_id:
                return config
        return None
    
    def calculate_position_quantity(
        self,
        config: RoutingMappingConfig,
        signal_quantity: Optional[int] = None,
        entry_price: float = 0.0,
        account_balance: float = 0.0
    ) -> int:
        """
        Calculate position quantity based on settings.
        
        Priority:
        1. Fixed QTY from mapping (if set)
        2. Size % calculation (if set and account balance available)
        3. Signal quantity (if provided)
        4. Default to 1
        """
        if config.default_quantity and config.default_quantity > 0:
            return config.default_quantity
        
        if config.size_percent and entry_price > 0 and account_balance > 0:
            position_value = account_balance * (config.size_percent / 100.0)
            contract_cost = entry_price * 100
            qty = int(position_value / contract_cost)
            return max(1, qty)
        
        if signal_quantity and signal_quantity > 0:
            return signal_quantity
        
        return 1
    
    def resolve_signal_exit_qty(
        self,
        position: LedgerPosition,
        signal: dict,
        config: Optional[RoutingMappingConfig] = None
    ) -> int:
        remaining = position.remaining_qty
        if remaining <= 0:
            return 0

        is_full = signal.get('is_full_exit', False) or signal.get('_phoenix_exit', False)
        is_trim = signal.get('is_trim', False) or signal.get('_phoenix_trim', False)
        trim_pct = signal.get('trim_percentage') or signal.get('trim_percent')
        signal_qty = signal.get('qty', 0) or 0

        runner_size = 0
        if config and config.leave_runner_enabled and not is_full:
            runner_size = max(1, int(math.floor(
                position.entry_qty * (config.leave_runner_size_pct / 100.0)
            )))
        max_exit_qty = max(0, remaining - runner_size) if not is_full else remaining

        if is_full:
            return remaining

        if trim_pct and float(trim_pct) > 0:
            pct = float(trim_pct)
            calculated = max(1, int(math.ceil(remaining * (pct / 100.0))))
            return min(calculated, max_exit_qty)

        if signal_qty > 0:
            if signal_qty <= remaining:
                return min(signal_qty, max_exit_qty)
            else:
                conservative_qty = max(1, int(math.ceil(remaining * 0.5)))
                print(f"[ROUTING_ENGINE] ⚠️ Signal qty ({signal_qty}) > user remaining ({remaining}) — ambiguous trim, conservative 50% = {conservative_qty}")
                return min(conservative_qty, max_exit_qty)

        if is_trim:
            half_qty = max(1, remaining // 2)
            return min(half_qty, max_exit_qty)

        return max_exit_qty if max_exit_qty > 0 else remaining

    def calculate_exit_quantity(
        self,
        position: LedgerPosition,
        exit_reason: ExitReason,
        config: RoutingMappingConfig,
        trim_percent: Optional[float] = None
    ) -> int:
        """
        Calculate exit quantity with proper rounding.
        
        Rules:
        - Use floor() rounding (conservative)
        - Never exceed remaining_qty
        - Respect leave_runner settings
        - If calculated qty = 0, return 0 (caller should skip)
        """
        remaining = position.remaining_qty
        if remaining <= 0:
            return 0
        
        runner_size = 0
        if config.leave_runner_enabled:
            runner_size = max(1, int(math.floor(
                position.entry_qty * (config.leave_runner_size_pct / 100.0)
            )))
        
        max_exit_qty = max(0, remaining - runner_size)
        
        if exit_reason in (ExitReason.STOP_LOSS, ExitReason.TRAILING_STOP, ExitReason.GIVEBACK_GUARD, ExitReason.EARLY_TRAILING, ExitReason.EMA_EXIT):
            return remaining
        
        if exit_reason == ExitReason.SIGNAL and trim_percent:
            calculated = int(math.floor(position.entry_qty * (trim_percent / 100.0)))
            return min(max(0, calculated), max_exit_qty)
        
        pt_quantities = {
            ExitReason.PT1: config.pt1_qty,
            ExitReason.PT2: config.pt2_qty,
            ExitReason.PT3: config.pt3_qty,
            ExitReason.PT4: config.pt4_qty,
        }
        pt_trim_pcts = {
            ExitReason.PT1: config.pt1_trim_pct,
            ExitReason.PT2: config.pt2_trim_pct,
            ExitReason.PT3: config.pt3_trim_pct,
            ExitReason.PT4: config.pt4_trim_pct,
        }
        
        if exit_reason in pt_quantities:
            fixed_qty = pt_quantities.get(exit_reason)
            if fixed_qty is not None and fixed_qty > 0:
                return min(fixed_qty, max_exit_qty)
            
            trim_pct_val = pt_trim_pcts.get(exit_reason)
            if trim_pct_val is not None and trim_pct_val > 0:
                calculated = int(math.floor(max_exit_qty * (trim_pct_val / 100.0)))
                return min(max(0, calculated), max_exit_qty)
            
            default_pct = 25.0
            calculated = int(math.floor(position.entry_qty * (default_pct / 100.0)))
            return min(max(1, calculated), max_exit_qty)
        
        return min(1, remaining)
    
    def is_price_fresh(self, position: LedgerPosition) -> Tuple[bool, int]:
        """
        Check if position price is fresh enough for risk decisions.
        
        Returns:
            Tuple of (is_fresh, staleness_seconds)
        """
        staleness = position.price_staleness_sec
        is_fresh = staleness <= self._stale_price_threshold_sec
        return is_fresh, staleness
    
    def can_evaluate_risk(self, position: LedgerPosition) -> Tuple[bool, str]:
        """
        Check if risk evaluation is allowed for this position.
        
        Checks:
        1. Exit strategy mode (signal mode = no automated exits)
        2. Risk management enabled
        3. Market hours (options only trade during regular hours)
        4. Price freshness
        """
        if position.routing_mapping_id:
            config = self.get_routing_config(position.routing_mapping_id)
            if config:
                if config.exit_strategy_mode == ExitStrategyMode.SIGNAL:
                    return False, "Exit strategy = signal only - no automated exits"
                
                if not config.enable_risk_management:
                    return False, "Risk management disabled for this mapping"
        
        market_status, risk_allowed = get_market_status()
        if not risk_allowed:
            return False, f"Market {market_status} - risk monitoring paused"
        
        is_fresh, staleness = self.is_price_fresh(position)
        if not is_fresh:
            return False, f"Price stale ({staleness}s old) - skipping risk check"
        
        return True, "OK"
    
    def evaluate_position_risk(
        self,
        position: LedgerPosition,
        config: RoutingMappingConfig
    ) -> Tuple[Optional[ExitReason], float]:
        """
        Evaluate risk conditions for a position.
        
        Returns:
            Tuple of (exit_reason, current_pnl_pct) or (None, pnl_pct) if no exit triggered
        
        Exit Priority (first match wins — matches System 1 ordering):
        1. Stop Loss (hard SL threshold)
        2. Dynamic SL (escalated price-based SL)
        3. EMA Risk (trend reversal exit)
        4. Giveback Guard (max profit drawdown)
        5. Early Trailing Stop (breakeven + step locks)
        6. Profit Targets PT1-PT4 (escalation_only: mark tier without exit)
        7. Legacy Trailing Stop (if active and triggered)
        """
        if position.remaining_qty <= 0:
            return None, 0.0
        
        cost_basis = position.entry_price
        if cost_basis <= 0:
            return None, 0.0
        
        current_price = position.current_price
        if current_price <= 0:
            return None, 0.0
        
        pnl_pct = ((current_price - cost_basis) / cost_basis) * 100
        
        pt_levels_hit = set()
        try:
            pt_levels_hit = set(json.loads(position.pt_levels_hit or "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        
        if config.stop_loss_pct > 0 and pnl_pct <= -config.stop_loss_pct:
            return ExitReason.STOP_LOSS, pnl_pct
        
        if config.dynamic_sl_escalation_enabled and position.dynamic_sl_price is not None:
            if current_price <= position.dynamic_sl_price:
                return ExitReason.STOP_LOSS, pnl_pct
        
        if config.ema_risk_enabled:
            ema_exit = self._evaluate_ema_risk(position, config, pnl_pct)
            if ema_exit is not None:
                return ema_exit, pnl_pct
        
        if config.max_profit_giveback_enabled and position.giveback_guard_active:
            if position.max_pnl_seen > 0:
                giveback_threshold = position.max_pnl_seen * (1 - config.max_profit_giveback_pct / 100)
                if pnl_pct <= giveback_threshold:
                    return ExitReason.GIVEBACK_GUARD, pnl_pct
        
        if config.enable_early_trailing and config.early_trailing_activation_pct > 0:
            early_exit = self._evaluate_early_trailing(position, config, pnl_pct, cost_basis)
            if early_exit is not None:
                return early_exit, pnl_pct
        
        pt_targets = [
            (ExitReason.PT4, config.pt4_pct, "pt4"),
            (ExitReason.PT3, config.pt3_pct, "pt3"),
            (ExitReason.PT2, config.pt2_pct, "pt2"),
            (ExitReason.PT1, config.pt1_pct, "pt1"),
        ]
        
        if config.escalation_only_mode:
            for exit_reason, target_pct, level_key in pt_targets:
                if target_pct > 0 and level_key not in pt_levels_hit and pnl_pct >= target_pct:
                    pt_levels_hit.add(level_key)
                    if position.id is not None:
                        self.ledger.update_pt_levels(position.id, list(pt_levels_hit))
                        tier_num = level_key.replace("pt", "")
                        print(f"[ROUTING_ENGINE] ESCALATION ONLY: PT{tier_num} hit ({pnl_pct:.1f}% >= {target_pct}%) — tier marked, NO exit")
        else:
            for exit_reason, target_pct, level_key in pt_targets:
                if target_pct > 0 and level_key not in pt_levels_hit and pnl_pct >= target_pct:
                    return exit_reason, pnl_pct
        
        if not config.enable_early_trailing and position.trailing_stop_active and config.trailing_stop_pct > 0:
            max_pnl = position.max_pnl_seen
            trailing_threshold = max_pnl - config.trailing_stop_pct
            if pnl_pct <= trailing_threshold and max_pnl > 0:
                return ExitReason.TRAILING_STOP, pnl_pct
        
        if position.id is not None:
            self._update_enhanced_risk_state(position, config, pnl_pct, pt_levels_hit, cost_basis)
        
        return None, pnl_pct
    
    def _evaluate_early_trailing(
        self,
        position: LedgerPosition,
        config: RoutingMappingConfig,
        pnl_pct: float,
        cost_basis: float
    ) -> Optional[ExitReason]:
        """Evaluate early trailing stop: breakeven at activation, then step-locked profit."""
        activation_pct = config.early_trailing_activation_pct
        step_pct = config.early_trailing_step_pct if config.early_trailing_step_pct > 0 else 3.0
        
        if not position.early_trailing_active:
            if pnl_pct >= activation_pct:
                stop_price = cost_basis
                self.ledger.update_early_trailing_state(
                    position.id, active=True, stop_price=stop_price, steps_locked=0
                )
                position.early_trailing_active = True
                position.early_stop_price = stop_price
                position.early_steps_locked = 0
                print(f"[ROUTING_ENGINE] ✓ Early Trailing ACTIVATED at {pnl_pct:.1f}% — breakeven locked at ${stop_price:.2f}")
            return None
        
        current_price = position.current_price
        if position.early_stop_price is not None and current_price <= position.early_stop_price:
            return ExitReason.EARLY_TRAILING
        
        expected_steps = int((pnl_pct - activation_pct) / step_pct)
        expected_steps = max(0, expected_steps)
        
        if expected_steps > (position.early_steps_locked or 0):
            new_steps = expected_steps
            new_stop_pct = new_steps * step_pct
            new_stop_price = cost_basis * (1 + new_stop_pct / 100)
            if position.early_stop_price is None or new_stop_price > position.early_stop_price:
                old_stop = position.early_stop_price
                self.ledger.update_early_trailing_state(
                    position.id, active=True, stop_price=new_stop_price, steps_locked=new_steps
                )
                position.early_stop_price = new_stop_price
                position.early_steps_locked = new_steps
                old_display = f"${old_stop:.2f}" if old_stop else "entry"
                print(f"[ROUTING_ENGINE] 📈 Early Trail PROFIT LOCKED: {old_display} → ${new_stop_price:.2f} (step {new_steps})")
        
        return None
    
    def _evaluate_ema_risk(
        self,
        position: LedgerPosition,
        config: RoutingMappingConfig,
        pnl_pct: float
    ) -> Optional[ExitReason]:
        """Evaluate EMA trend risk using CandlePreWarmService."""
        try:
            from src.risk.ema_engine import get_candle_service
            candle_svc = get_candle_service()
            if not candle_svc or not candle_svc.is_global_enabled():
                return None
            
            ema_symbol = position.symbol
            tf = config.ema_timeframe_minutes
            pd_val = config.ema_period
            
            is_option = position.option_type in ('C', 'Call', 'call', 'P', 'Put', 'put')
            yf_only = is_option and config.ema_use_underlying
            candle_svc.subscribe_symbol(ema_symbol, timeframe=tf, period=pd_val, yfinance_only=yf_only, extended_hours=config.ema_extended_hours)
            
            ema_state = candle_svc.get_ema_state(ema_symbol, timeframe=tf, period=pd_val)
            if ema_state is None or ema_state.value is None:
                return None
            
            cross_state = ema_state.cross_state
            buffer_pct = config.ema_buffer_pct
            
            if config.ema_exit_enabled and cross_state == 'below':
                if ema_state.value > 0:
                    distance_pct = ((position.current_price - ema_state.value) / ema_state.value) * 100
                    if distance_pct <= -buffer_pct:
                        print(f"[ROUTING_ENGINE] 📊 EMA EXIT: {ema_symbol} price ${position.current_price:.2f} crossed below EMA ${ema_state.value:.2f}")
                        return ExitReason.EMA_EXIT
            
            if config.ema_escalation_enabled and cross_state == 'below':
                if config.dynamic_sl_escalation_enabled and position.dynamic_sl_price is not None:
                    new_sl = position.current_price * 0.99
                    if new_sl > position.dynamic_sl_price:
                        self.ledger.update_dynamic_sl(position.id, new_sl)
                        print(f"[ROUTING_ENGINE] 📊 EMA SL ESCALATION: SL tightened to ${new_sl:.2f} on EMA cross")
            
            last_candle_ts = None
            if ema_state.last_candle and hasattr(ema_state.last_candle, 'timestamp'):
                last_candle_ts = ema_state.last_candle.timestamp
            elif ema_state.last_candle and hasattr(ema_state.last_candle, 'ts'):
                last_candle_ts = ema_state.last_candle.ts
            
            ema_key = position.id
            last_eval_ts = self._ema_last_candle_ts.get(ema_key)
            is_new_candle = last_candle_ts is not None and last_candle_ts != last_eval_ts
            
            if is_new_candle:
                self._ema_last_candle_ts[ema_key] = last_candle_ts
                
                if cross_state in ('flat', 'no_trend', None):
                    new_count = (position.ema_no_trend_count or 0) + 1
                    if new_count >= config.ema_no_trend_candles:
                        print(f"[ROUTING_ENGINE] 📊 EMA NO-TREND EXIT: {new_count} candles with no clear trend")
                        return ExitReason.EMA_EXIT
                    if position.id is not None:
                        self.ledger.update_ema_no_trend_count(position.id, new_count)
                        position.ema_no_trend_count = new_count
                else:
                    if position.ema_no_trend_count > 0 and position.id is not None:
                        self.ledger.update_ema_no_trend_count(position.id, 0)
                        position.ema_no_trend_count = 0
            
        except Exception as e:
            print(f"[ROUTING_ENGINE] EMA evaluation error for {position.symbol}: {e}")
        
        return None
    
    def _calculate_dynamic_sl_price(
        self,
        entry_price: float,
        pt_levels_hit: set,
        profile: str = 'standard'
    ) -> Optional[float]:
        """
        Calculate dynamic stop loss price based on PT hits.
        Returns new SL price or None if no escalation.
        """
        profile_config = DYNAMIC_SL_PROFILES.get(profile, DYNAMIC_SL_PROFILES['standard'])
        
        highest_tier_hit = 0
        for tier in [4, 3, 2, 1]:
            if f"pt{tier}" in pt_levels_hit:
                highest_tier_hit = tier
                break
        
        if highest_tier_hit == 0:
            return None
        
        sl_pct = profile_config.get(f'pt{highest_tier_hit}_sl_pct', 0)
        return entry_price * (1 + sl_pct / 100)
    
    def _update_enhanced_risk_state(
        self,
        position: LedgerPosition,
        config: RoutingMappingConfig,
        pnl_pct: float,
        pt_levels_hit: set,
        cost_basis: float
    ):
        """
        Update Enhanced Risk Management V2.0 state:
        - Dynamic SL Escalation (move SL after PT hits)
        - Max Profit Giveback Guard (activate and track)
        - Trailing Stop State
        """
        if config.dynamic_sl_escalation_enabled and len(pt_levels_hit) > 0:
            new_dynamic_sl = self._calculate_dynamic_sl_price(
                cost_basis,
                pt_levels_hit,
                config.sl_escalation_profile
            )
            
            if new_dynamic_sl is not None:
                if position.dynamic_sl_price is None or new_dynamic_sl > position.dynamic_sl_price:
                    self.ledger.update_dynamic_sl(position.id, new_dynamic_sl)
                    print(f"[ROUTING_ENGINE] 📈 Dynamic SL escalated to ${new_dynamic_sl:.2f} after PT hit")
        
        if config.max_profit_giveback_enabled:
            if config.trailing_stop_pct > 0 and config.trailing_activation_pct > 0:
                giveback_activation_threshold = config.trailing_activation_pct
            elif config.enable_early_trailing and config.early_trailing_activation_pct > 0:
                giveback_activation_threshold = config.early_trailing_activation_pct
            else:
                giveback_activation_threshold = 30
            pt2_activated = "pt2" in pt_levels_hit
            max_pnl = max(position.max_pnl_seen, pnl_pct)
            
            if not position.giveback_guard_active and (pt2_activated or max_pnl >= giveback_activation_threshold):
                self.ledger.update_giveback_guard(position.id, True, max_pnl)
                print(f"[ROUTING_ENGINE] 🛡️ Giveback guard activated (max_pnl={max_pnl:.1f}%)")
            elif position.giveback_guard_active and pnl_pct > position.max_pnl_seen:
                self.ledger.update_giveback_guard(position.id, True, pnl_pct)
        
        if not config.enable_early_trailing and config.trailing_stop_pct > 0:
            if pnl_pct >= config.trailing_activation_pct and not position.trailing_stop_active:
                self.ledger.update_trailing_state(
                    position.id,
                    trailing_active=True,
                    max_pnl_seen=pnl_pct
                )
            elif position.trailing_stop_active and pnl_pct > position.max_pnl_seen:
                self.ledger.update_trailing_state(
                    position.id,
                    trailing_active=True,
                    max_pnl_seen=pnl_pct
                )
        elif pnl_pct > position.max_pnl_seen:
            self.ledger.update_max_pnl(position.id, pnl_pct)
    
    async def _handle_risk_exit(
        self,
        position: LedgerPosition,
        config: RoutingMappingConfig,
        exit_reason: ExitReason,
        pnl_pct: float
    ) -> bool:
        """
        Handle a risk-triggered exit with ExitArbiter coordination.
        
        Flow:
        1. Acquire exit lock (prevents signal exit race)
        2. Calculate exit quantity
        3. Post STC to webhook
        4. Release lock
        
        Returns True if exit was successfully processed.
        """
        lock = self.exit_arbiter.get_lock(
            position.option_key,
            position.broker_id,
            position.account_id,
            routing_mapping_id=position.routing_mapping_id
        )
        
        acquired = False
        try:
            if not lock.acquire(blocking=False):
                print(f"[ROUTING_ENGINE] ⏭️ Exit already in progress for {position.option_key}")
                return False
            acquired = True
            
            if position.id is None:
                print(f"[ROUTING_ENGINE] ⏭️ Position has no ID: {position.option_key}")
                return False
            fresh_position = self.ledger.get_position(position.id)
            if not fresh_position:
                print(f"[ROUTING_ENGINE] ⏭️ Position no longer exists: {position.option_key}")
                return False
            
            if fresh_position.status == PositionStatus.CLOSED.value or fresh_position.remaining_qty <= 0:
                print(f"[ROUTING_ENGINE] ⏭️ Position already closed by signal exit: {position.option_key} - skipping risk exit")
                return False
            
            position = fresh_position
            
            exit_qty = self.calculate_exit_quantity(position, exit_reason, config)
            if exit_qty <= 0:
                print(f"[ROUTING_ENGINE] ⏭️ No exit qty for {position.option_key} - skipping")
                return False
            
            success = await self.post_stc_signal(
                config=config,
                position=position,
                exit_qty=exit_qty,
                exit_price=position.current_price,
                exit_reason=exit_reason,
                pnl_pct=pnl_pct
            )
            
            if success:
                if exit_reason in (ExitReason.PT1, ExitReason.PT2, ExitReason.PT3, ExitReason.PT4):
                    self._mark_pt_level_hit(position, exit_reason)
                
                if exit_qty >= position.remaining_qty:
                    self._cleanup_position_state(position.id)
                print(f"[ROUTING_ENGINE] ✓ Risk exit: {exit_reason.value.upper()} for {position.option_key}")
            
            return success
            
        except Exception as e:
            print(f"[ROUTING_ENGINE] ❌ Risk exit error for {position.option_key}: {e}")
            return False
        finally:
            if acquired and lock.locked():
                lock.release()
    
    def _cleanup_position_state(self, position_id: int):
        self._ema_last_candle_ts.pop(position_id, None)
    
    def _mark_pt_level_hit(self, position: LedgerPosition, exit_reason: ExitReason):
        """Mark a profit target level as hit in the position."""
        if position.id is None:
            return
        
        pt_map = {
            ExitReason.PT1: "pt1",
            ExitReason.PT2: "pt2",
            ExitReason.PT3: "pt3",
            ExitReason.PT4: "pt4",
        }
        level_key = pt_map.get(exit_reason)
        if not level_key:
            return
        
        try:
            pt_levels_hit = set(json.loads(position.pt_levels_hit or "[]"))
            pt_levels_hit.add(level_key)
            self.ledger.update_pt_levels(position.id, list(pt_levels_hit))
        except (json.JSONDecodeError, TypeError):
            self.ledger.update_pt_levels(position.id, [level_key])
    
    async def _risk_monitor_loop(self):
        """
        Main risk monitoring loop.
        
        Polls positions every 3 seconds:
        1. Get all open positions for routed signals
        2. Fetch and update prices from price monitor
        3. Evaluate risk conditions
        4. Trigger STC webhooks when conditions met
        """
        import sys
        sys.stderr.write("[ROUTING_ENGINE] ✓ Risk monitoring loop started\n")
        sys.stderr.flush()
        
        loaded = self._preload_all_routing_configs()
        sys.stderr.write(f"[ROUTING_ENGINE] ✓ Preloaded {loaded} routing configs from database\n")
        sys.stderr.flush()
        
        loop_count = 0
        _quote_fail_counts = {}
        while self._running:
            try:
                self._process_pending_invalidations()
                
                loop_count += 1
                positions = self.ledger.get_open_positions()
                
                routed_positions = [
                    p for p in positions if p.routing_mapping_id is not None
                ]
                
                if loop_count <= 3 or loop_count % 20 == 0:
                    sys.stderr.write(f"[ROUTING_ENGINE] Loop #{loop_count}: {len(positions)} positions, {len(routed_positions)} routed\n")
                    sys.stderr.flush()
                
                for position in routed_positions:
                    if position.remaining_qty <= 0:
                        continue
                    
                    if position.id is None:
                        continue
                    
                    try:
                        expiry_fmt = position.expiry
                        if '/' in expiry_fmt:
                            parts = expiry_fmt.split('/')
                            if len(parts) == 2:
                                year = datetime.now().year
                                expiry_fmt = f"{year}-{int(parts[0]):02d}-{int(parts[1]):02d}"
                        
                        try:
                            from datetime import date
                            expiry_date = datetime.strptime(expiry_fmt, "%Y-%m-%d").date()
                            today = date.today()
                            if expiry_date < today:
                                days_expired = (today - expiry_date).days
                                sys.stderr.write(f"[ROUTING_ENGINE] 📅 Expired position detected: {position.symbol} {position.strike}{position.option_type} {expiry_fmt} (expired {days_expired} day(s) ago)\n")
                                sys.stderr.flush()
                                position.current_price = 0.01
                                try:
                                    dedupe = f"expired_{position.id}_{expiry_fmt}"
                                    result = self.ledger.record_partial_exit(
                                        position_id=position.id,
                                        exit_qty=position.remaining_qty,
                                        exit_price=0.01,
                                        exit_reason=ExitReason.EXPIRED.value,
                                        dedupe_key=dedupe
                                    )
                                    if result:
                                        self._cleanup_position_state(position.id)
                                        sys.stderr.write(f"[ROUTING_ENGINE] ✅ Auto-closed expired position {position.symbol} {position.strike}{position.option_type} in ledger (P&L: ${result.exit_pnl_dollar:.2f})\n")
                                        sys.stderr.flush()
                                        config = self.get_routing_config(position.routing_mapping_id)
                                        if config:
                                            try:
                                                pnl_pct = -100.0 if position.entry_price > 0 else 0.0
                                                await self.post_stc_signal(
                                                    config=config,
                                                    position=position,
                                                    exit_qty=position.remaining_qty,
                                                    exit_price=0.01,
                                                    exit_reason=ExitReason.EXPIRED,
                                                    pnl_pct=pnl_pct
                                                )
                                            except Exception:
                                                pass
                                    else:
                                        sys.stderr.write(f"[ROUTING_ENGINE] ⏭️ Expired position already closed: {position.symbol}\n")
                                        sys.stderr.flush()
                                except Exception as exp_err:
                                    sys.stderr.write(f"[ROUTING_ENGINE] ❌ Error auto-closing expired position: {exp_err}\n")
                                    sys.stderr.flush()
                                continue
                        except (ValueError, TypeError):
                            pass
                        
                        pos_key = getattr(position, 'option_key', None) or f"{position.symbol}_{expiry_fmt}_{position.strike}_{position.option_type}"
                        fail_count = _quote_fail_counts.get(pos_key, 0)
                        if fail_count >= 5:
                            skip_interval = min(2 ** (fail_count - 4), 120)
                            if loop_count % skip_interval != 0:
                                continue
                        
                        # ── Hub-first pricing (Webull MQTT / Schwab WebSocket) ────────────
                        # Check streaming hubs before any REST call. Zero API cost, sub-100ms.
                        price = None
                        _hub_source = None
                        occ_key = getattr(position, 'option_key', None)
                        is_option = bool(position.strike) or bool(getattr(position, 'option_type', None))

                        schwab_occ = None
                        if is_option and position.strike and position.strike > 0:
                            try:
                                _ot = (position.option_type or 'C').upper()
                                _ep = expiry_fmt.split('-')
                                if len(_ep) == 3:
                                    _sym = position.symbol.upper()
                                    _schwab_sym = 'SPXW' if _sym == 'SPX' else _sym
                                    schwab_occ = f"{_schwab_sym.ljust(6)}{_ep[0][2:]}{_ep[1]}{_ep[2]}{_ot}{int(float(position.strike) * 1000):08d}"
                            except Exception:
                                pass

                        if is_option and (not position.strike or position.strike == 0):
                            pass
                        else:
                            try:
                                from src.services.webull_data_hub import get_webull_data_hub
                                _wb_hub = get_webull_data_hub()
                                if _wb_hub.is_streaming():
                                    _lookup = occ_key if is_option else position.symbol
                                    if _lookup:
                                        price = _wb_hub.get_quote_price(_lookup)
                                        if price and price > 0:
                                            _hub_source = 'webull_hub'
                            except Exception:
                                pass
                            if not price:
                                try:
                                    from src.services.schwab_data_hub import get_schwab_data_hub
                                    _sw_hub = get_schwab_data_hub()
                                    if _sw_hub.is_streaming():
                                        _lookup = schwab_occ if (is_option and schwab_occ) else (occ_key if is_option else position.symbol)
                                        if _lookup:
                                            _sw_data = _sw_hub.get_quote_detailed(_lookup)
                                            if _sw_data:
                                                _bid = _sw_data.get('bid', 0) or 0
                                                _ask = _sw_data.get('ask', 0) or 0
                                                _last = _sw_data.get('last', 0) or 0
                                                if _bid > 0 and _ask > 0:
                                                    price = (_bid + _ask) / 2
                                                elif _last > 0:
                                                    price = _last
                                                if price and price > 0:
                                                    _hub_source = 'schwab_hub'
                                except Exception:
                                    pass

                        if price and price > 0 and position.entry_price > 0:
                            ratio = price / position.entry_price
                            if ratio > 50:
                                sys.stderr.write(
                                    f"[ROUTING_ENGINE] ⚠️ INDEX PRICE GUARD: {position.symbol} "
                                    f"price ${price:.2f} is {ratio:.0f}x entry ${position.entry_price:.2f} "
                                    f"— likely underlying index, NOT option premium. Rejecting.\n"
                                )
                                sys.stderr.flush()
                                price = None
                                _hub_source = None

                        if price and price > 0:
                            _quote_fail_counts.pop(pos_key, None)
                        else:
                            # Hub miss — fall back to REST via QuoteAggregator
                            quote_agg = get_quote_aggregator()
                            from src.services.quote_aggregator import BrokerCapability
                            connected_brokers = quote_agg.get_connected_brokers(BrokerCapability.OPTION_QUOTE)
                            quote_result = await asyncio.get_event_loop().run_in_executor(
                                None,
                                lambda: quote_agg.get_option_quote(
                                    symbol=position.symbol,
                                    strike=position.strike,
                                    opt_type=position.option_type,
                                    expiry=expiry_fmt
                                )
                            )
                            price = quote_result.mid if quote_result.success else None
                            if price and price > 0 and position.entry_price > 0:
                                ratio = price / position.entry_price
                                if ratio > 50:
                                    sys.stderr.write(
                                        f"[ROUTING_ENGINE] ⚠️ INDEX PRICE GUARD (REST): {position.symbol} "
                                        f"price ${price:.2f} is {ratio:.0f}x entry ${position.entry_price:.2f} "
                                        f"— likely underlying index, NOT option premium. Rejecting.\n"
                                    )
                                    sys.stderr.flush()
                                    price = None
                            if price and price > 0:
                                _quote_fail_counts.pop(pos_key, None)
                            else:
                                _quote_fail_counts[pos_key] = fail_count + 1
                        should_log_detail = loop_count <= 3 or loop_count % 20 == 0
                        _price_src = _hub_source or 'rest'
                        if should_log_detail or (price is None):
                            sys.stderr.write(f"[ROUTING_ENGINE] {position.symbol} {position.strike}{position.option_type} {expiry_fmt}: price={price} src={_price_src} (entry={position.entry_price})\n")
                            sys.stderr.flush()
                        if price and price > 0:
                            self.ledger.update_price(position.id, price, staleness_sec=0)
                            position.current_price = price
                            position.price_staleness_sec = 0
                        else:
                            staleness = position.price_staleness_sec + 5
                            self.ledger.update_price(position.id, position.current_price, staleness_sec=staleness)
                            position.price_staleness_sec = staleness
                            if should_log_detail:
                                sys.stderr.write(f"[ROUTING_ENGINE] {position.option_key}: No live price - staleness {staleness}s, skipping risk eval\n")
                                sys.stderr.flush()
                            continue
                    except Exception as price_err:
                        sys.stderr.write(f"[ROUTING_ENGINE] ⚠️ Price fetch failed for {position.option_key}: {price_err}\n")
                        sys.stderr.flush()
                        continue
                    
                    can_eval, reason = self.can_evaluate_risk(position)
                    if not can_eval:
                        if should_log_detail:
                            sys.stderr.write(f"[ROUTING_ENGINE] {position.option_key}: SKIP risk eval - {reason}\n")
                            sys.stderr.flush()
                        continue
                    
                    config = self.get_routing_config(position.routing_mapping_id)
                    if not config:
                        if should_log_detail:
                            sys.stderr.write(f"[ROUTING_ENGINE] {position.option_key}: SKIP - no config for mapping {position.routing_mapping_id}\n")
                            sys.stderr.flush()
                        continue
                    
                    exit_reason, pnl_pct = self.evaluate_position_risk(position, config)
                    if should_log_detail:
                        sys.stderr.write(f"[ROUTING_ENGINE] {position.option_key}: pnl={pnl_pct:.1f}% exit_reason={exit_reason} (SL={config.stop_loss_pct}% PT1={config.pt1_pct}%)\n")
                        sys.stderr.flush()
                    
                    if exit_reason:
                        try:
                            await asyncio.wait_for(
                                self._handle_risk_exit(position, config, exit_reason, pnl_pct),
                                timeout=15.0
                            )
                        except asyncio.TimeoutError:
                            print(f"[ROUTING_ENGINE] ⚠️ Risk exit timed out for {position.option_key}")
                
                await self.process_webhook_retry_queue()
                
            except Exception as e:
                print(f"[ROUTING_ENGINE] ⚠️ Risk monitor error: {e}")
            
            await asyncio.sleep(2)
        
        print("[ROUTING_ENGINE] ✗ Risk monitoring loop stopped")
    
    async def start_risk_monitor(self):
        """Start the risk monitoring loop."""
        import sys
        sys.stderr.write(f"[ROUTING_ENGINE] start_risk_monitor called, _running={self._running}\n")
        sys.stderr.flush()
        
        if self._running:
            sys.stderr.write("[ROUTING_ENGINE] Already running, skipping\n")
            sys.stderr.flush()
            return
        
        self._running = True
        try:
            self._monitor_task = asyncio.create_task(self._risk_monitor_loop())
            
            def task_done_callback(task):
                try:
                    exc = task.exception()
                    if exc:
                        import traceback
                        sys.stderr.write(f"[ROUTING_ENGINE] ❌ Task error: {exc}\n")
                        sys.stderr.write(f"[ROUTING_ENGINE] Traceback: {traceback.format_exception(type(exc), exc, exc.__traceback__)}\n")
                        sys.stderr.flush()
                except asyncio.CancelledError:
                    sys.stderr.write("[ROUTING_ENGINE] Task was cancelled\n")
                    sys.stderr.flush()
            
            self._monitor_task.add_done_callback(task_done_callback)
            sys.stderr.write(f"[ROUTING_ENGINE] Task created: {self._monitor_task}\n")
            sys.stderr.flush()
            await asyncio.sleep(0.5)
            sys.stderr.write(f"[ROUTING_ENGINE] Task state after 0.5s: {self._monitor_task}\n")
            sys.stderr.flush()
            print("[ROUTING_ENGINE] ✓ Risk monitor started", flush=True)
        except Exception as e:
            sys.stderr.write(f"[ROUTING_ENGINE] Error creating task: {e}\n")
            import traceback
            sys.stderr.write(f"{traceback.format_exc()}\n")
            sys.stderr.flush()
    
    async def stop_risk_monitor(self):
        """Stop the risk monitoring loop."""
        if not self._running:
            return
        
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        
        print("[ROUTING_ENGINE] ✗ Risk monitor stopped")
    
    def get_or_load_config_for_channel(self, channel_id: str) -> Optional[RoutingMappingConfig]:
        """
        Get config from cache or load from database.
        
        Used by external callers (like selfbot) to check if a channel is routed.
        """
        if channel_id in self._configs:
            return self._configs.get(channel_id)
        
        try:
            from gui_app.database import get_signal_routing_by_source
            mapping = get_signal_routing_by_source(channel_id)
            if mapping and mapping.get('enabled'):
                return self.load_mapping_config(mapping)
        except Exception as e:
            print(f"[ROUTING_ENGINE] ⚠️ Could not load mapping for channel {channel_id}: {e}")
        
        return None
    
    async def handle_signal_exit(
        self,
        channel_id: str,
        signal: dict,
        message_id: str = ""
    ) -> bool:
        """
        Handle a signal-based STC exit with ExitArbiter coordination.
        
        Called when a trader STC signal (e.g., Bishop Trimming) is detected
        from a routed source channel. This forwards the STC to the webhook
        while coordinating with risk exits to prevent duplicates.
        
        Args:
            channel_id: Source channel ID
            signal: Parsed signal dict with symbol, strike, expiry, etc.
            message_id: Original Discord message ID for dedupe
        
        Returns:
            True if STC was forwarded, False otherwise
        """
        config = self.get_or_load_config_for_channel(channel_id)
        if not config:
            return False
        
        if not config.enable_forwarding or not config.destination_url:
            return False
        
        if config.exit_strategy_mode == ExitStrategyMode.RISK:
            print(f"[ROUTING_ENGINE] ⏭️ Signal exit skipped - exit_strategy = risk only")
            return False
        
        symbol = signal.get('symbol', '').upper()
        strike = signal.get('strike')
        expiry = signal.get('expiry')
        opt_type = signal.get('opt_type', '').upper()
        exit_price = signal.get('price', 0.0)
        exit_qty = signal.get('qty', 0)
        trim_percent = signal.get('trim_percent')  # e.g., 30 for @$30%
        is_percent_trim = signal.get('_bishop_trim_percent', False)
        
        position = self.find_matching_position(
            symbol=symbol,
            routing_mapping_id=config.id,
            strike=float(strike) if strike else None,
            expiry=expiry,
            option_type=opt_type
        )
        
        if not position:
            print(f"[ROUTING_ENGINE] ⚠️ No matching position for signal STC: {symbol}")
            return False
        
        lock = self.exit_arbiter.get_lock(
            position.option_key,
            position.broker_id,
            position.account_id,
            routing_mapping_id=position.routing_mapping_id
        )
        
        acquired = False
        try:
            if not lock.acquire(blocking=False):
                print(f"[ROUTING_ENGINE] ⏭️ Exit already in progress for {position.option_key}")
                return False
            acquired = True
            
            # ===== POSITION STATE GATE =====
            # Fresh check after acquiring lock to handle race conditions
            # Risk manager may have closed position while we waited for lock
            if position.id is None:
                print(f"[ROUTING_ENGINE] ⏭️ Position has no ID: {position.option_key}")
                return False
            fresh_position = self.ledger.get_position(position.id)
            if not fresh_position:
                print(f"[ROUTING_ENGINE] ⏭️ Position no longer exists: {position.option_key}")
                return False
            
            if fresh_position.status == PositionStatus.CLOSED.value or fresh_position.remaining_qty <= 0:
                print(f"[ROUTING_ENGINE] ⏭️ Position already closed by risk settings: {symbol} - skipping signal STC")
                return False
            
            # Use fresh position data for exit calculation
            position = fresh_position
            # ===== END POSITION STATE GATE =====
            
            actual_exit_qty = self.resolve_signal_exit_qty(position, signal, config)
            if actual_exit_qty <= 0:
                actual_exit_qty = exit_qty if exit_qty > 0 else position.remaining_qty
                actual_exit_qty = min(actual_exit_qty, position.remaining_qty)
            
            if actual_exit_qty <= 0:
                return False
            
            if exit_price <= 0 and position.current_price > 0:
                exit_price = position.current_price
            
            # Use entry_price (signal's entry alert price) as cost basis
            cost_basis = position.entry_price
            pnl_pct = ((exit_price - cost_basis) / cost_basis * 100) if cost_basis > 0 else 0.0
            
            success = await self.post_stc_signal(
                config=config,
                position=position,
                exit_qty=actual_exit_qty,
                exit_price=exit_price,
                exit_reason=ExitReason.SIGNAL,
                pnl_pct=pnl_pct,
                trim_percent=trim_percent if is_percent_trim else None
            )
            
            if success:
                if actual_exit_qty >= position.remaining_qty:
                    self._cleanup_position_state(position.id)
                if is_percent_trim:
                    print(f"[ROUTING_ENGINE] ✓ Signal STC forwarded: {symbol} @ {trim_percent}%")
                else:
                    print(f"[ROUTING_ENGINE] ✓ Signal STC forwarded: {symbol} @ ${exit_price:.2f}")
            
            return success
            
        except Exception as e:
            print(f"[ROUTING_ENGINE] ❌ Signal exit error: {e}")
            return False
        finally:
            if acquired and lock.locked():
                lock.release()
    
    def find_matching_position(
        self,
        symbol: str,
        routing_mapping_id: Optional[int] = None,
        strike: Optional[float] = None,
        expiry: Optional[str] = None,
        option_type: Optional[str] = None
    ) -> Optional[LedgerPosition]:
        """
        Find matching position for ambiguous exit signals.
        
        Priority:
        1. Exact match (symbol + strike + expiry + type)
        2. Same routing_mapping_id + symbol
        3. Most recent entry_time
        4. Highest remaining_qty
        
        Returns None if ambiguous (multiple matches with equal priority).
        """
        positions = self.ledger.get_open_positions()
        
        if not positions:
            return None
        
        candidates = [p for p in positions if p.symbol.upper() == symbol.upper()]
        
        if not candidates:
            return None
        
        if strike and expiry and option_type:
            exact = [
                p for p in candidates
                if p.strike == strike
                and p.expiry == expiry
                and p.option_type.upper() == option_type.upper()
            ]
            if len(exact) == 1:
                return exact[0]
        
        if routing_mapping_id:
            routed = [p for p in candidates if p.routing_mapping_id == routing_mapping_id]
            if len(routed) == 1:
                return routed[0]
            candidates = routed if routed else candidates
        
        candidates.sort(key=lambda p: p.entry_time, reverse=True)
        
        if len(candidates) == 1:
            return candidates[0]
        
        if len(candidates) > 1:
            top = candidates[0]
            second = candidates[1]
            if top.entry_time != second.entry_time:
                return top
            
            if top.remaining_qty > second.remaining_qty:
                return top
            elif top.remaining_qty < second.remaining_qty:
                return second
            
            print(f"[ROUTING_ENGINE] ⚠️ Ambiguous position match for {symbol} - skipping")
            return None
        
        return None
    
    def _generate_message_id(
        self,
        position_id: int,
        exit_reason: str,
        exit_qty: int
    ) -> str:
        """Generate unique message ID for webhook dedupe.
        
        Note: Excludes time to ensure same exit event gets same ID for dedupe.
        TTL for dedupe set: entries auto-expire when position closes.
        """
        data = f"{position_id}:{exit_reason}:{exit_qty}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def post_bto_signal(
        self,
        config: RoutingMappingConfig,
        symbol: str,
        strike: float,
        option_type: str,
        expiry: str,
        entry_price: float,
        quantity: int,
        message_id: str = ""
    ) -> Tuple[bool, Optional[int]]:
        """
        Forward BTO signal to webhook and register position.
        
        Returns:
            Tuple of (success, position_id)
        """
        if not config.enable_forwarding or not config.destination_url:
            print(f"[ROUTING_ENGINE] Forwarding disabled or no destination URL")
            return False, None
        
        option_key = f"{symbol}_{expiry}_{strike}_{option_type}"
        
        bto_message = f"@everyone\nBTO {symbol} {strike}{option_type} {expiry} @ {entry_price}\n*Not financial advice, for educational purposes only.*"
        
        position = LedgerPosition(
            option_key=option_key,
            symbol=symbol,
            expiry=expiry,
            strike=strike,
            option_type=option_type,
            channel_id=config.source_channel_id,
            broker_id="",
            account_id="",
            entry_qty=quantity,
            remaining_qty=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            price_updated_at=datetime.now().isoformat(),
            status="open",
            entry_time=datetime.now().isoformat(),
            entry_message_id=message_id,
            source_type="signal_routing",
            routing_mapping_id=config.id
        )
        
        try:
            session = await self._get_session()
            
            marker = f"\n||ROUTING:{config.id}:{option_key}||"
            webhook_content = bto_message + marker
            
            async with session.post(
                config.destination_url,
                json={"content": webhook_content}
            ) as resp:
                if resp.status in (200, 204):
                    position_id = self.ledger.create_position(position)
                    
                    if position_id and position_id > 0:
                        position.id = position_id
                        self.price_monitor.register_position(position)
                        
                        try:
                            initial_price = await self.price_monitor.get_option_price(
                                symbol=symbol,
                                strike=strike,
                                expiry=expiry,
                                option_type=option_type
                            )
                            if initial_price and initial_price > 0:
                                self.ledger.update_price(position_id, initial_price, staleness_sec=0)
                                print(f"[ROUTING_ENGINE] ✓ Initial mark price set: ${initial_price:.2f}")
                        except Exception as mark_err:
                            print(f"[ROUTING_ENGINE] ⚠️ Could not fetch initial mark price: {mark_err}")
                    
                    print(f"[ROUTING_ENGINE] ✓ BTO forwarded: {bto_message}")
                    return True, position_id
                else:
                    print(f"[ROUTING_ENGINE] Webhook failed: HTTP {resp.status}")
                    return False, None
                    
        except Exception as e:
            print(f"[ROUTING_ENGINE] BTO webhook error: {e}")
            return False, None
    
    async def post_stc_signal(
        self,
        config: RoutingMappingConfig,
        position: LedgerPosition,
        exit_qty: int,
        exit_price: float,
        exit_reason: ExitReason,
        pnl_pct: float = 0.0,
        trim_percent: Optional[float] = None
    ) -> bool:
        """
        Post STC signal to webhook with retry and dedupe.
        
        Two-phase update:
        1. Post webhook
        2. If success, update ledger
        
        Args:
            trim_percent: If set, format message with percentage (e.g., @ 30%) instead of price
        """
        if not config.enable_forwarding or not config.destination_url:
            return False
        
        msg_id = self._generate_message_id(
            position.id or 0,
            exit_reason.value,
            exit_qty
        )
        
        if msg_id in self._webhook_delivered:
            print(f"[ROUTING_ENGINE] ⏭️ Duplicate STC skipped: {msg_id}")
            return True
        
        exit_label = ""
        if exit_reason == ExitReason.STOP_LOSS:
            exit_label = " [SL]"
        elif exit_reason == ExitReason.PT1:
            exit_label = " [PT1]"
        elif exit_reason == ExitReason.PT2:
            exit_label = " [PT2]"
        elif exit_reason == ExitReason.PT3:
            exit_label = " [PT3]"
        elif exit_reason == ExitReason.PT4:
            exit_label = " [PT4]"
        elif exit_reason == ExitReason.TRAILING_STOP:
            exit_label = " [TRAIL]"
        
        # Format price display: percentage for trim signals, dollar amount for others
        if trim_percent is not None:
            price_display = f"{trim_percent:.0f}%"
        else:
            price_display = f"${exit_price:.2f}" if exit_price > 0 else "MKT"
        
        stc_message = (
            f"@everyone\n"
            f"STC ${position.symbol} {position.strike} {position.option_type} "
            f"{position.expiry} @ {price_display}{exit_label}\n"
            f"*Not financial advice, for educational purposes only.*"
        )
        
        # ===== LEDGER-FIRST ORDERING =====
        # Industry-grade approach: Update ledger BEFORE webhook to prevent duplicates
        # If webhook fails, position is already updated; retries won't double-exit
        
        # Record exit in ledger first with dedupe_key
        exit_record = self.ledger.record_partial_exit(
            position_id=position.id or 0,
            exit_qty=exit_qty,
            exit_price=exit_price,
            exit_reason=exit_reason.value,
            dedupe_key=msg_id
        )
        
        if not exit_record:
            # Exit already recorded (idempotency) or position closed
            print(f"[ROUTING_ENGINE] ⏭️ Exit already processed or position closed: {msg_id}")
            return True  # Return True since exit is already handled
        
        # Now attempt webhook delivery
        webhook_msg = WebhookMessage(
            id=msg_id,
            url=config.destination_url,
            content=stc_message,
            position_id=position.id or 0,
            exit_reason=exit_reason.value,
            exit_qty=exit_qty
        )
        
        success = await self._deliver_webhook(webhook_msg)
        
        if success:
            self._webhook_delivered.add(msg_id)
            print(f"[ROUTING_ENGINE] ✓ STC posted: {stc_message}")
            return True
        else:
            # Ledger already updated; queue webhook for retry only
            self._webhook_queue.append(webhook_msg)
            print(f"[ROUTING_ENGINE] ⚠️ STC queued for retry (ledger already updated): {stc_message}")
            return True  # Return True since exit was recorded
        # ===== END LEDGER-FIRST ORDERING =====
    
    async def _deliver_webhook(self, msg: WebhookMessage) -> bool:
        """Attempt to deliver a webhook message."""
        try:
            session = await self._get_session()
            
            marker = f"\n||STC:{msg.id}||"
            content = msg.content + marker
            
            async with session.post(
                msg.url,
                json={"content": content}
            ) as resp:
                msg.attempts += 1
                msg.last_attempt = time.time()
                
                if resp.status in (200, 204):
                    msg.delivered = True
                    return True
                else:
                    print(f"[ROUTING_ENGINE] Webhook attempt {msg.attempts} failed: HTTP {resp.status}")
                    return False
                    
        except Exception as e:
            msg.attempts += 1
            msg.last_attempt = time.time()
            print(f"[ROUTING_ENGINE] Webhook error: {e}")
            return False
    
    async def process_webhook_retry_queue(self):
        """Process queued webhook messages that failed initial delivery."""
        if not self._webhook_queue:
            return
        
        retry_ready = [
            msg for msg in self._webhook_queue
            if not msg.delivered
            and msg.attempts < msg.max_attempts
            and time.time() - msg.last_attempt > 5.0
        ]
        
        for msg in retry_ready:
            success = await self._deliver_webhook(msg)
            if success:
                self._webhook_delivered.add(msg.id)
                self._webhook_queue.remove(msg)
        
        self._webhook_queue = [
            msg for msg in self._webhook_queue
            if not msg.delivered and msg.attempts < msg.max_attempts
        ]
    
    async def close(self):
        """Clean up resources."""
        if self._session and not self._session.closed:
            await self._session.close()


_engine_instance: Optional[SignalRoutingEngine] = None


def get_signal_routing_engine() -> SignalRoutingEngine:
    """Get singleton instance of SignalRoutingEngine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = SignalRoutingEngine()
    return _engine_instance
