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
    
    trailing_stop_pct: float = 0.0
    trailing_activation_pct: float = 15.0
    leave_runner_enabled: bool = False
    leave_runner_size_pct: float = 25.0
    
    dynamic_sl_escalation_enabled: bool = False
    sl_escalation_profile: str = "standard"
    max_profit_giveback_enabled: bool = False
    max_profit_giveback_pct: float = 30.0


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
            trailing_stop_pct=mapping.get('trailing_stop_pct', 0.0) or 0.0,
            trailing_activation_pct=mapping.get('trailing_activation_pct', 15.0) or 15.0,
            leave_runner_enabled=bool(mapping.get('leave_runner_enabled', 0)),
            leave_runner_size_pct=mapping.get('leave_runner_size_pct', 25.0) or 25.0,
            dynamic_sl_escalation_enabled=bool(mapping.get('dynamic_sl_escalation_enabled', 0)),
            sl_escalation_profile=mapping.get('sl_escalation_profile', 'standard') or 'standard',
            max_profit_giveback_enabled=bool(mapping.get('max_profit_giveback_enabled', 0)),
            max_profit_giveback_pct=mapping.get('max_profit_giveback_pct', 30.0) or 30.0,
        )
        
        self._configs[config.source_channel_id] = config
        return config
    
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
        
        if exit_reason in (ExitReason.STOP_LOSS, ExitReason.TRAILING_STOP, ExitReason.GIVEBACK_GUARD):
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
        
        if exit_reason in pt_quantities:
            fixed_qty = pt_quantities.get(exit_reason)
            if fixed_qty and fixed_qty > 0:
                return min(fixed_qty, max_exit_qty)
            
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
        
        Exit Priority (first match wins):
        1. Stop Loss (price below SL threshold)
        2. Trailing Stop (if active and triggered)
        3. Profit Targets (PT1 → PT4, checking which levels already hit)
        """
        if position.remaining_qty <= 0:
            return None, 0.0
        
        # Use entry_price (signal's entry alert price) as cost basis for PT/SL calculations
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
        
        if pnl_pct <= -config.stop_loss_pct:
            return ExitReason.STOP_LOSS, pnl_pct
        
        if config.dynamic_sl_escalation_enabled and position.dynamic_sl_price is not None:
            if current_price <= position.dynamic_sl_price:
                return ExitReason.STOP_LOSS, pnl_pct
        
        if config.max_profit_giveback_enabled and position.giveback_guard_active:
            if position.max_pnl_seen > 0:
                giveback_threshold = position.max_pnl_seen * (1 - config.max_profit_giveback_pct / 100)
                if pnl_pct <= giveback_threshold:
                    return ExitReason.GIVEBACK_GUARD, pnl_pct
        
        if position.trailing_stop_active and config.trailing_stop_pct > 0:
            max_pnl = position.max_pnl_seen
            trailing_threshold = max_pnl - config.trailing_stop_pct
            if pnl_pct <= trailing_threshold and max_pnl > 0:
                return ExitReason.TRAILING_STOP, pnl_pct
        
        pt_targets = [
            (ExitReason.PT4, config.pt4_pct, "pt4"),
            (ExitReason.PT3, config.pt3_pct, "pt3"),
            (ExitReason.PT2, config.pt2_pct, "pt2"),
            (ExitReason.PT1, config.pt1_pct, "pt1"),
        ]
        
        for exit_reason, target_pct, level_key in pt_targets:
            if level_key not in pt_levels_hit and pnl_pct >= target_pct:
                return exit_reason, pnl_pct
        
        if position.id is not None:
            self._update_enhanced_risk_state(position, config, pnl_pct, pt_levels_hit, cost_basis)
        
        return None, pnl_pct
    
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
            pt2_activated = "pt2" in pt_levels_hit
            activation_threshold = config.pt1_pct
            
            if not position.giveback_guard_active and (pt2_activated or pnl_pct >= activation_threshold):
                self.ledger.update_giveback_guard(position.id, True, pnl_pct)
                print(f"[ROUTING_ENGINE] 🛡️ Giveback guard activated at {pnl_pct:.1f}%")
            elif position.giveback_guard_active and pnl_pct > position.max_pnl_seen:
                self.ledger.update_giveback_guard(position.id, True, pnl_pct)
        
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
            try:
                await asyncio.wait_for(lock.acquire(), timeout=0.1)
                acquired = True
            except asyncio.TimeoutError:
                print(f"[ROUTING_ENGINE] ⏭️ Exit already in progress for {position.option_key}")
                return False
            
            # ===== POSITION STATE GATE (RISK FLOW) =====
            # Fresh check after acquiring lock to handle race with signal exits
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
            
            # Use fresh position data for exit calculation
            position = fresh_position
            # ===== END POSITION STATE GATE =====
            
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
                
                print(f"[ROUTING_ENGINE] ✓ Risk exit: {exit_reason.value.upper()} for {position.option_key}")
            
            return success
            
        except Exception as e:
            print(f"[ROUTING_ENGINE] ❌ Risk exit error for {position.option_key}: {e}")
            return False
        finally:
            if acquired and lock.locked():
                lock.release()
    
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
                                if loop_count <= 3 or loop_count % 100 == 0:
                                    sys.stderr.write(f"[ROUTING_ENGINE] ⏭️  Skipping expired position {position.symbol} {position.strike}{position.option_type} {expiry_fmt} (expired {(today - expiry_date).days} day(s) ago)\n")
                                    sys.stderr.flush()
                                position.current_price = 0.01
                                continue
                        except (ValueError, TypeError):
                            pass
                        
                        pos_key = getattr(position, 'option_key', None) or f"{position.symbol}_{expiry_fmt}_{position.strike}_{position.option_type}"
                        fail_count = _quote_fail_counts.get(pos_key, 0)
                        if fail_count >= 5:
                            skip_interval = min(fail_count * 5, 60)
                            if loop_count % (skip_interval // 2 + 1) != 0:
                                continue
                        
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
                        if quote_result.success:
                            _quote_fail_counts.pop(pos_key, None)
                        else:
                            _quote_fail_counts[pos_key] = fail_count + 1
                        if loop_count <= 3:
                            error_info = quote_result.error if not quote_result.success else ""
                            sys.stderr.write(f"[ROUTING_ENGINE] {position.symbol} {position.strike}{position.option_type} {expiry_fmt}: price={price} (entry={position.entry_price}) brokers={connected_brokers} {error_info}\n")
                            sys.stderr.flush()
                        if price and price > 0:
                            self.ledger.update_price(position.id, price, staleness_sec=0)
                            position.current_price = price
                            position.price_staleness_sec = 0
                    except Exception as price_err:
                        sys.stderr.write(f"[ROUTING_ENGINE] ⚠️ Price fetch failed for {position.option_key}: {price_err}\n")
                        sys.stderr.flush()
                        continue
                    
                    can_eval, reason = self.can_evaluate_risk(position)
                    if not can_eval:
                        if loop_count <= 3:
                            sys.stderr.write(f"[ROUTING_ENGINE] {position.option_key}: SKIP risk eval - {reason}\n")
                            sys.stderr.flush()
                        continue
                    
                    config = self.get_routing_config(position.routing_mapping_id)
                    if not config:
                        if loop_count <= 3:
                            sys.stderr.write(f"[ROUTING_ENGINE] {position.option_key}: SKIP - no config for mapping {position.routing_mapping_id}\n")
                            sys.stderr.flush()
                        continue
                    
                    exit_reason, pnl_pct = self.evaluate_position_risk(position, config)
                    if loop_count <= 3:
                        sys.stderr.write(f"[ROUTING_ENGINE] {position.option_key}: pnl={pnl_pct:.1f}% exit_reason={exit_reason}\n")
                        sys.stderr.flush()
                    
                    if exit_reason:
                        await self._handle_risk_exit(position, config, exit_reason, pnl_pct)
                
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
            try:
                await asyncio.wait_for(lock.acquire(), timeout=0.1)
                acquired = True
            except asyncio.TimeoutError:
                print(f"[ROUTING_ENGINE] ⏭️ Exit already in progress for {position.option_key}")
                return False
            
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
            self._session = aiohttp.ClientSession()
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
