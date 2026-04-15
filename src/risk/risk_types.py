"""
Risk Management Types
=====================
Shared dataclasses and types for the risk management module.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime

INDEX_OPTION_NORMALIZE = {
    'SPXW': 'SPX',
    'NDXP': 'NDX',
    'RUTW': 'RUT',
    'DJXW': 'DJX',
    'VIXW': 'VIX',
}

def normalize_index_symbol(symbol: str) -> str:
    if not symbol:
        return symbol
    return INDEX_OPTION_NORMALIZE.get(symbol.upper(), symbol)


@dataclass
class PositionSnapshot:
    """Snapshot of a broker position for risk evaluation."""
    symbol: str
    quantity: float
    avg_cost: float
    current_price: float
    asset: str  # 'stock' or 'option'
    broker: str  # 'Webull', 'ALPACA_PAPER', 'ALPACA_LIVE', 'IBKR'
    
    strike: Optional[float] = None
    expiry: Optional[str] = None
    direction: Optional[str] = None  # 'C' or 'P' for options
    raw_symbol: Optional[str] = None  # Original symbol for execution (Alpaca OCC format)
    option_id: Optional[int] = None
    
    @property
    def position_key(self) -> str:
        """Generate unique position key including broker for monitoring cache."""
        if self.asset == 'option':
            return f"{self.broker}_{self.symbol}_{self.strike}_{self.expiry}_{self.direction}"
        return f"{self.broker}_{self.symbol}_stock"
    
    @property
    def db_key(self) -> str:
        """Generate position key for database lookups (no broker prefix)."""
        if self.asset == 'option':
            return f"{self.symbol}_{self.strike}_{self.expiry}_{self.direction}"
        return f"{self.symbol}_stock"
    
    @property
    def pct_change(self) -> float:
        """Calculate percentage change from entry."""
        if self.avg_cost <= 0:
            return 0.0
        return ((self.current_price - self.avg_cost) / self.avg_cost) * 100


@dataclass
class RiskSettings:
    """Global risk management settings."""
    enabled: bool = False
    profit_target_percent: float = 0.0
    stop_loss_percent: float = 0.0
    trailing_stop_percent: float = 0.0
    trailing_activation_pct: float = 15.0  # Default activation threshold


@dataclass
class ChannelRiskSettings:
    """Per-channel risk settings with tiered targets and enhanced risk features."""
    channel_id: str
    channel_name: str
    profit_target_1_pct: float = 0.0  # Tier 1 target
    profit_target_2_pct: float = 0.0  # Tier 2 target
    profit_target_3_pct: float = 0.0  # Tier 3 target
    profit_target_4_pct: float = 0.0  # Tier 4 target (new)
    profit_target_qty_1: Optional[int] = None  # Custom qty for T1 (None = auto-calculate)
    profit_target_qty_2: Optional[int] = None  # Custom qty for T2
    profit_target_qty_3: Optional[int] = None  # Custom qty for T3
    profit_target_qty_4: Optional[int] = None  # Custom qty for T4
    profit_target_trim_pct_1: Optional[float] = None  # Custom trim % for T1 (None = auto)
    profit_target_trim_pct_2: Optional[float] = None  # Custom trim % for T2
    profit_target_trim_pct_3: Optional[float] = None  # Custom trim % for T3
    profit_target_trim_pct_4: Optional[float] = None  # Custom trim % for T4
    stop_loss_pct: float = 0.0
    trailing_stop_pct: float = 0.0
    trailing_activation_pct: float = 15.0
    leave_runner_enabled: bool = False  # Keep portion after profit targets
    leave_runner_pct: float = 25.0  # Percentage of position to leave as runner
    trim_order_mode: str = 'market'  # 'market' or 'limit' for trim orders
    sl_order_mode: str = 'limit'  # 'market' or 'limit' for stop loss orders
    trim_limit_offset: float = 0.01  # Offset for limit orders (e.g., 0.01 = $0.01)
    trim_limit_offset_mode: str = 'dollar'  # 'dollar' or 'percent' for trim offset type
    trim_limit_offset_pct: float = 2.0  # Percentage offset for limit orders (e.g., 2.0 = 2% below)
    sl_limit_offset: float = 0.03  # Offset % for SL limit orders (e.g., 0.03 = SL triggers at -10%, limit at -13%)
    exit_strategy_mode: str = 'signal'  # 'signal' = follow trader, 'risk' = auto exits, 'hybrid' = both
    
    # Enhanced Risk Management Settings
    enable_dynamic_sl: bool = False  # Dynamic SL escalation after PT hits
    enable_giveback_guard: bool = False  # Max profit giveback protection
    giveback_allowed_pct: float = 30.0  # Max giveback % before forced exit
    dynamic_sl_profile: str = 'standard'  # 'conservative', 'standard', 'aggressive'
    
    # Early Trailing Stop Settings (percentage-based breakeven + profit locking)
    enable_early_trailing: bool = False  # Enable early trailing stop
    early_trailing_activation_pct: float = 5.0  # Move to breakeven at this % gain
    early_trailing_step_pct: float = 3.0  # Lock profit in this % increments

    escalation_only_mode: bool = False
    
    broker_bracket_mode: str = 'both'  # 'both', 'sl_only', 'pt_only', 'none'
    
    @property
    def allows_broker_sl(self) -> bool:
        return self.broker_bracket_mode in ('both', 'sl_only')
    
    @property
    def allows_broker_pt(self) -> bool:
        return self.broker_bracket_mode in ('both', 'pt_only')
    
    # EMA Risk Management Settings (EMA-5 Candlestick Risk Engine)
    ema_risk_enabled: bool = False
    ema_period: int = 5
    ema_timeframe_minutes: int = 5
    ema_buffer_pct: float = 0.1
    ema_exit_enabled: bool = True
    ema_escalation_enabled: bool = True
    ema_extended_hours: bool = False
    ema_use_underlying: bool = True
    ema_no_trend_candles: int = 3
    
    @property
    def has_tiered_targets(self) -> bool:
        """Check if tiered profit targets are configured."""
        return (self.profit_target_1_pct > 0 or self.profit_target_2_pct > 0 or 
                self.profit_target_3_pct > 0 or self.profit_target_4_pct > 0)
    
    @property
    def has_any_settings(self) -> bool:
        """Check if any risk settings are configured."""
        return (self.has_tiered_targets or 
                self.stop_loss_pct > 0 or 
                self.trailing_stop_pct > 0 or
                self.enable_early_trailing or
                self.ema_risk_enabled)
    
    def compute_settings_hash(self) -> str:
        """
        Compute a hash of the risk settings for versioning.
        Used to detect when settings change mid-position.
        """
        import hashlib
        key_fields = (
            self.profit_target_1_pct, self.profit_target_2_pct,
            self.profit_target_3_pct, self.profit_target_4_pct,
            self.profit_target_qty_1, self.profit_target_qty_2,
            self.profit_target_qty_3, self.profit_target_qty_4,
            self.profit_target_trim_pct_1, self.profit_target_trim_pct_2,
            self.profit_target_trim_pct_3, self.profit_target_trim_pct_4,
            self.stop_loss_pct, self.trailing_stop_pct,
            self.trailing_activation_pct, self.leave_runner_enabled,
            self.leave_runner_pct, self.exit_strategy_mode,
            self.enable_dynamic_sl, self.enable_giveback_guard,
            self.giveback_allowed_pct, self.dynamic_sl_profile,
            self.enable_early_trailing, self.early_trailing_activation_pct,
            self.early_trailing_step_pct,
            self.trim_order_mode, self.trim_limit_offset_mode, self.trim_limit_offset_pct,
            self.sl_order_mode, self.sl_limit_offset,
            self.ema_risk_enabled, self.ema_period, self.ema_timeframe_minutes,
            self.ema_buffer_pct, self.ema_exit_enabled, self.ema_escalation_enabled,
            self.ema_no_trend_candles, self.ema_extended_hours, self.ema_use_underlying,
            self.escalation_only_mode, self.broker_bracket_mode
        )
        hash_input = str(key_fields).encode()
        return hashlib.md5(hash_input).hexdigest()[:12]


@dataclass
class ExitDecision:
    """Result of risk evaluation - whether to exit and why."""
    should_exit: bool = False
    reason: str = ""
    exit_qty: int = 0
    is_partial: bool = False  # True for tiered partial exits
    risk_trigger: str = ""  # 'profit_target', 'stop_loss', 'trailing_stop', 'risk_management'
    tier_hit: Optional[int] = None  # 1, 2, or 3 for tiered targets
    
    @classmethod
    def no_exit(cls) -> 'ExitDecision':
        """Factory for no-exit decision."""
        return cls(should_exit=False)
    
    @classmethod
    def stop_loss(cls, reason: str, qty: int, channel_name: str = "Global") -> 'ExitDecision':
        """Factory for stop loss exit."""
        return cls(
            should_exit=True,
            reason=f"STOP LOSS [{channel_name}] {reason}",
            exit_qty=qty,
            is_partial=False,
            risk_trigger='stop_loss'
        )
    
    @classmethod
    def dynamic_sl(cls, reason: str, qty: int, channel_name: str = "Global") -> 'ExitDecision':
        return cls(
            should_exit=True,
            reason=f"DYNAMIC SL [{channel_name}] {reason}",
            exit_qty=qty,
            is_partial=False,
            risk_trigger='dynamic_sl'
        )

    @classmethod
    def profit_target(cls, reason: str, qty: int, channel_name: str = "Global", 
                      tier: Optional[int] = None, is_partial: bool = False) -> 'ExitDecision':
        """Factory for profit target exit."""
        tier_prefix = f"TIER {tier} TARGET" if tier else "PROFIT TARGET"
        return cls(
            should_exit=True,
            reason=f"{tier_prefix} [{channel_name}] {reason}",
            exit_qty=qty,
            is_partial=is_partial,
            risk_trigger='profit_target',
            tier_hit=tier
        )
    
    @classmethod
    def trailing_stop(cls, reason: str, qty: int, channel_name: str = "Global", 
                      is_partial: bool = False) -> 'ExitDecision':
        """Factory for trailing stop exit (supports Leave Runner partial exits)."""
        return cls(
            should_exit=True,
            reason=f"TRAILING STOP [{channel_name}] {reason}",
            exit_qty=qty,
            is_partial=is_partial,
            risk_trigger='trailing_stop'
        )


@dataclass
class PendingRiskOrder:
    """Tracks a pending risk management order awaiting fill confirmation."""
    order_id: str
    tier: int  # 1, 2, 3, 4 or 0 for stop-loss/trailing
    qty_expected: int
    qty_filled: int = 0
    status: str = 'pending'  # 'pending', 'filled', 'partial', 'cancelled', 'failed'
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'order_id': self.order_id,
            'tier': self.tier,
            'qty_expected': self.qty_expected,
            'qty_filled': self.qty_filled,
            'status': self.status,
            'created_at': self.created_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PendingRiskOrder':
        created_str = data.pop('created_at', None)
        order = cls(**data)
        if created_str:
            try:
                order.created_at = datetime.fromisoformat(created_str)
            except:
                pass
        return order


@dataclass
class PositionCacheEntry:
    """Cached state for a position being monitored."""
    entry_price: float
    highest_price: float
    trailing_activated: bool = False
    closing: bool = False
    closing_cycles: int = 0
    closing_since: float = 0
    stop_loss_price: Optional[float] = None
    profit_target_price: Optional[float] = None
    broker: str = ""
    raw_symbol: Optional[str] = None
    channel_settings: Optional[ChannelRiskSettings] = None
    original_qty: Optional[int] = None
    
    tier1_hit: bool = False
    tier2_hit: bool = False
    tier3_hit: bool = False
    tier4_hit: bool = False
    
    # Enhanced risk state
    max_pnl_seen: float = 0.0  # Track max PnL % for giveback guard
    dynamic_sl_price: Optional[float] = None  # Current dynamic SL after PT escalation
    giveback_guard_active: bool = False  # Giveback guard activated (after PT2)
    last_evaluated_price: Optional[float] = None  # For idempotency checks
    trailing_stop_price: Optional[float] = None  # Current trailing stop price
    risk_settings_hash: Optional[str] = None  # Hash of settings when position opened
    
    # Early Trailing Stop state
    early_trailing_active: bool = False  # True once breakeven locked
    early_stop_price: Optional[float] = None  # Current early trailing stop price
    early_steps_locked: int = 0  # Number of profit steps locked (0=breakeven, 1=+step%, 2=+2*step%, ...)

    # EMA Risk state (position-level tracking, EMA value lives in CandlePreWarmService)
    ema_no_trend_count: int = 0
    ema_last_cross_state: str = 'unknown'
    ema_last_eval_candle_ts: Optional[float] = None
    ema_post_entry_candles: int = 0
    
    # Position instance identity - prevents stale SL/PT from old orders
    source_order_id: Optional[int] = None  # Conditional order ID that seeded this entry
    source_trade_id: Optional[int] = None  # Trade record ID for this position instance
    seed_time: Optional[str] = None  # ISO timestamp when SL/PT were last seeded
    
    # Manual SL/PT overrides from signal provider follow-up messages
    manual_sl_price: Optional[float] = None  # Fixed price SL override (e.g., "SL at 1.88")
    manual_sl_pct: Optional[float] = None  # Percentage SL override (e.g., "SL 11%")
    manual_pt_targets: Optional[list] = None  # PT targets override from follow-up
    
    broker_stop_order_id: Optional[str] = None
    broker_pt_order_id: Optional[str] = None
    broker_pt_tier: int = 0
    broker_orders_placed: bool = False
    
    # Pending risk orders awaiting fill confirmation
    pending_orders: Dict[str, Any] = field(default_factory=dict)  # order_id -> PendingRiskOrder dict
    
    # Failed order retry tracking (industry-grade)
    exit_retry_count: int = 0  # Number of failed exit attempts
    exit_retry_cooldown_until: Optional[datetime] = None  # When retry is allowed
    last_exit_failure_reason: Optional[str] = None  # Last failure message
    use_market_order: bool = False  # Switch to market after limit fails
    
    created_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON persistence."""
        return {
            'entry_price': self.entry_price,
            'highest_price': self.highest_price,
            'trailing_activated': self.trailing_activated,
            'closing': self.closing,
            'closing_cycles': self.closing_cycles,
            'stop_loss_price': self.stop_loss_price,
            'profit_target_price': self.profit_target_price,
            'broker': self.broker,
            'raw_symbol': self.raw_symbol,
            'tier1_hit': self.tier1_hit,
            'tier2_hit': self.tier2_hit,
            'tier3_hit': self.tier3_hit,
            'tier4_hit': self.tier4_hit,
            'original_qty': self.original_qty,
            'pending_orders': self.pending_orders,
            'created_at': self.created_at.isoformat(),
            'max_pnl_seen': self.max_pnl_seen,
            'dynamic_sl_price': self.dynamic_sl_price,
            'giveback_guard_active': self.giveback_guard_active,
            'last_evaluated_price': self.last_evaluated_price,
            'early_trailing_active': self.early_trailing_active,
            'early_stop_price': self.early_stop_price,
            'early_steps_locked': self.early_steps_locked,
            'manual_sl_price': self.manual_sl_price,
            'manual_sl_pct': self.manual_sl_pct,
            'manual_pt_targets': self.manual_pt_targets,
            'source_order_id': self.source_order_id,
            'source_trade_id': self.source_trade_id,
            'seed_time': self.seed_time,
            'ema_no_trend_count': self.ema_no_trend_count,
            'ema_last_cross_state': self.ema_last_cross_state,
            'ema_last_eval_candle_ts': self.ema_last_eval_candle_ts,
            'ema_post_entry_candles': self.ema_post_entry_candles,
            'broker_stop_order_id': self.broker_stop_order_id,
            'broker_pt_order_id': self.broker_pt_order_id,
            'broker_pt_tier': self.broker_pt_tier,
            'broker_orders_placed': self.broker_orders_placed
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PositionCacheEntry':
        """Deserialize from JSON."""
        created_str = data.pop('created_at', None)
        pending = data.pop('pending_orders', {})
        entry = cls(**{k: v for k, v in data.items() if k != 'channel_settings'})
        entry.pending_orders = pending if isinstance(pending, dict) else {}
        if created_str:
            try:
                entry.created_at = datetime.fromisoformat(created_str)
            except:
                pass
        return entry
    
    def reset_closing(self) -> None:
        """Reset closing state after stuck position detection."""
        self.closing = False
        self.closing_cycles = 0
        self.closing_since = 0
    
    def update_highest_price(self, current_price: float, position_key: Optional[str] = None, verbose: bool = False) -> bool:
        """Track highest price for trailing stop. Returns True if new high was set."""
        if current_price > self.highest_price:
            old_high = self.highest_price
            self.highest_price = current_price
            if verbose and position_key and self.trailing_activated:
                print(f"[TRAIL] 📈 {position_key}: New high ${old_high:.2f} → ${current_price:.2f}")
            return True
        return False
    
    def has_pending_order_for_tier(self, tier: int) -> bool:
        """Check if there's already a pending order for this tier."""
        for order_data in self.pending_orders.values():
            if order_data.get('tier') == tier and order_data.get('status') == 'pending':
                return True
        return False
    
    def add_pending_order(self, order_id: str, tier: int, qty_expected: int, trade_id: int = None) -> None:
        """Track a new pending risk order."""
        self.pending_orders[order_id] = {
            'order_id': order_id,
            'tier': tier,
            'qty_expected': qty_expected,
            'qty_filled': 0,
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'trade_id': trade_id
        }
    
    def update_pending_order(self, order_id: str, status: str, qty_filled: int = 0) -> Optional[int]:
        """Update pending order status. Returns tier number if order exists."""
        if order_id in self.pending_orders:
            self.pending_orders[order_id]['status'] = status
            self.pending_orders[order_id]['qty_filled'] = qty_filled
            return self.pending_orders[order_id].get('tier')
        return None
    
    def remove_pending_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Remove a pending order and return its data."""
        return self.pending_orders.pop(order_id, None)
    
    def get_pending_orders_for_tier(self, tier: int) -> list:
        """Get all pending orders for a specific tier."""
        return [o for o in self.pending_orders.values() 
                if o.get('tier') == tier and o.get('status') == 'pending']
    
    def clear_failed_pending_orders(self) -> list:
        """Remove failed/cancelled pending orders and return their tier numbers."""
        failed_tiers = []
        to_remove = []
        for order_id, order_data in self.pending_orders.items():
            if order_data.get('status') in ('failed', 'cancelled'):
                failed_tiers.append(order_data.get('tier'))
                to_remove.append(order_id)
        for order_id in to_remove:
            del self.pending_orders[order_id]
        return failed_tiers
    
    # Industry-grade retry management
    MAX_FAST_RETRIES = 5  # Fast retries with exponential backoff
    MARKET_ORDER_THRESHOLD = 2  # Switch to market after N limit order failures
    EXTENDED_RETRY_INTERVAL = 300  # 5 minutes between extended retries
    extended_retry_mode: bool = False  # Persistent retry after fast retries exhausted
    exhausted_notified: bool = False  # Track if Discord notification was sent
    is_emergency_exit: bool = False  # Flag for stop loss / emergency exits (faster retry)
    permanent_failure: bool = False  # Set True when error is unrecoverable (expired symbol, etc.)
    permanent_failure_reason: Optional[str] = None
    no_position_streak: int = 0
    
    PERMANENT_ERROR_PATTERNS = [
        'symbol is expired', 'expired', 'symbol not found', 'invalid symbol',
        'contract is no longer', 'does not exist', 'delisted', 'not tradeable',
        'no longer available', 'contract expired', 'invalid contract',
        'unknown symbol', 'security not found', 'instrument not found',
    ]
    
    NO_POSITION_PATTERNS = [
        'no stock position', 'no option position',
        'insufficient position', 'position not found',
        'no shares available', 'no position to sell',
    ]
    NO_POSITION_PERMANENT_THRESHOLD = 3
    
    def _is_permanent_error(self, reason: str) -> bool:
        """Check if error indicates a permanent/unrecoverable failure."""
        if not reason:
            return False
        reason_lower = reason.lower()
        return any(pattern in reason_lower for pattern in self.PERMANENT_ERROR_PATTERNS)
    
    def _is_no_position_error(self, reason: str) -> bool:
        """Check if broker confirmed no matching position exists for exit."""
        if not reason:
            return False
        reason_lower = reason.lower()
        return any(pattern in reason_lower for pattern in self.NO_POSITION_PATTERNS)
    
    def record_exit_failure(self, reason: str, is_stop_loss: bool = False) -> None:
        """Record a failed exit attempt with backoff.
        
        Args:
            reason: Failure reason message
            is_stop_loss: If True, use FAST emergency retry timing (5s, 10s, 15s max)
        """
        from datetime import timedelta
        self.exit_retry_count += 1
        self.last_exit_failure_reason = reason
        
        if self._is_permanent_error(reason):
            self.permanent_failure = True
            self.permanent_failure_reason = reason
            print(f"[RISK-RETRY] 🛑 PERMANENT FAILURE detected — stopping all retries for this position")
            print(f"[RISK-RETRY] 🛑 Reason: {reason}")
            print(f"[RISK-RETRY] 🛑 Position should be removed from tracking (expired/invalid symbol)")
            return
        
        if self._is_no_position_error(reason):
            self.no_position_streak += 1
            if self.no_position_streak >= self.NO_POSITION_PERMANENT_THRESHOLD:
                self.permanent_failure = True
                self.permanent_failure_reason = reason
                print(f"[RISK-RETRY] 🛑 BROKER CONFIRMED no position for {self.no_position_streak} consecutive attempts")
                print(f"[RISK-RETRY] 🛑 Reason: {reason}")
                print(f"[RISK-RETRY] 🛑 Position is phantom (never filled or already closed) — removing from risk tracking")
                return
            else:
                print(f"[RISK-RETRY] ⚠️ No-position response from broker (streak {self.no_position_streak}/{self.NO_POSITION_PERMANENT_THRESHOLD}) — will retry")
        else:
            self.no_position_streak = 0
        
        # Track if this is an emergency exit (stop loss)
        if is_stop_loss:
            self.is_emergency_exit = True
        
        is_transient_broker_error = reason and ('system' in reason.lower() and 'busy' in reason.lower())
        
        if self.is_emergency_exit:
            backoff_seconds = min(3 * self.exit_retry_count, 10)
            phase = "EMERGENCY"
            self.use_market_order = True
        elif is_transient_broker_error and self.exit_retry_count <= self.MAX_FAST_RETRIES:
            backoff_seconds = min(5 * self.exit_retry_count, 15)
            phase = "FAST-TRANSIENT"
        elif self.exit_retry_count <= self.MAX_FAST_RETRIES:
            backoff_seconds = min(max(2, 3 * (2 ** (self.exit_retry_count - 1))), 10)
            phase = "FAST"
        else:
            # Extended retry phase: Fixed 5-minute intervals, keep trying forever
            self.extended_retry_mode = True
            backoff_seconds = self.EXTENDED_RETRY_INTERVAL
            phase = "EXTENDED"
        
        self.exit_retry_cooldown_until = datetime.now() + timedelta(seconds=backoff_seconds)
        
        # Switch to market order after threshold (for non-emergency)
        if not self.is_emergency_exit and self.exit_retry_count >= self.MARKET_ORDER_THRESHOLD:
            self.use_market_order = True
        
        if phase == "EMERGENCY":
            print(f"[RISK-RETRY] ⚡ EMERGENCY EXIT failed (attempt {self.exit_retry_count}): {reason}")
            print(f"[RISK-RETRY] ⚡ Fast retry in {backoff_seconds}s with MARKET ORDER")
        elif phase == "FAST-TRANSIENT":
            print(f"[RISK-RETRY] ⚡ Broker transient error (attempt {self.exit_retry_count}/{self.MAX_FAST_RETRIES}): {reason}")
            print(f"[RISK-RETRY] Quick retry in {backoff_seconds}s, market_order={self.use_market_order}")
        elif phase == "FAST":
            print(f"[RISK-RETRY] Exit failed (attempt {self.exit_retry_count}/{self.MAX_FAST_RETRIES}): {reason}")
            print(f"[RISK-RETRY] Next retry in {backoff_seconds}s, market_order={self.use_market_order}")
        else:
            print(f"[RISK-RETRY] EXTENDED MODE - Exit failed (attempt {self.exit_retry_count}): {reason}")
            print(f"[RISK-RETRY] Will retry in {backoff_seconds // 60} minutes (persistent until success)")
    
    def can_retry_exit(self) -> bool:
        """Check if retry is allowed (cooldown expired). Stops on permanent failures."""
        if self.permanent_failure:
            return False
        if self.exit_retry_cooldown_until and datetime.now() < self.exit_retry_cooldown_until:
            return False
        return True
    
    def retry_cooldown_remaining(self) -> float:
        """Get seconds remaining in cooldown, or 0 if ready."""
        if not self.exit_retry_cooldown_until:
            return 0.0
        remaining = (self.exit_retry_cooldown_until - datetime.now()).total_seconds()
        return max(0.0, remaining)
    
    def reset_exit_retry_state(self) -> None:
        """Reset retry state after successful exit."""
        self.exit_retry_count = 0
        self.exit_retry_cooldown_until = None
        self.last_exit_failure_reason = None
        self.use_market_order = False
        self.extended_retry_mode = False
        self.exhausted_notified = False
        self.is_emergency_exit = False
    
    def in_extended_retry_mode(self) -> bool:
        """Check if position is in extended retry mode (persistent retries every 5 min)."""
        return self.exit_retry_count >= self.MAX_FAST_RETRIES
    
    def needs_extended_notification(self) -> bool:
        """Check if Discord notification needed for entering extended mode."""
        if self.exit_retry_count == self.MAX_FAST_RETRIES and not self.exhausted_notified:
            self.exhausted_notified = True
            return True
        return False
