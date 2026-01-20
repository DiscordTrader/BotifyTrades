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
    ExitArbiter,
    ExitReason,
    PartialExit
)
from src.services.price_monitor_service import get_price_monitor, PriceMonitorService
from src.services.market_hours import (
    get_market_status,
    is_options_trading_hours,
    format_market_status
)


class ExitStrategyMode(Enum):
    SIGNAL = "signal"
    RISK = "risk"
    HYBRID = "hybrid"


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
        )
        
        self._configs[config.source_channel_id] = config
        return config
    
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
                if config.exit_strategy_mode == 'signal':
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
        
        bto_message = f"BTO {quantity} {symbol} ${strike}{option_type} @ {entry_price:.2f}"
        
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
        pnl_pct: float = 0.0
    ) -> bool:
        """
        Post STC signal to webhook with retry and dedupe.
        
        Two-phase update:
        1. Post webhook
        2. If success, update ledger
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
        
        pnl_str = f"+{pnl_pct:.1f}%" if pnl_pct >= 0 else f"{pnl_pct:.1f}%"
        reason_str = ""
        if exit_reason != ExitReason.SIGNAL:
            reason_str = f" [{exit_reason.value.upper()}]"
        
        stc_message = (
            f"STC {exit_qty} {position.symbol} "
            f"${position.strike}{position.option_type} "
            f"@ {exit_price:.2f} ({pnl_str}){reason_str}"
        )
        
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
            
            self.ledger.record_partial_exit(
                position_id=position.id or 0,
                exit_qty=exit_qty,
                exit_price=exit_price,
                exit_reason=exit_reason.value
            )
            
            print(f"[ROUTING_ENGINE] ✓ STC posted: {stc_message}")
            return True
        else:
            self._webhook_queue.append(webhook_msg)
            print(f"[ROUTING_ENGINE] ⚠️ STC queued for retry: {stc_message}")
            return False
    
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
