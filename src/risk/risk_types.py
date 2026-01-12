"""
Risk Management Types
=====================
Shared dataclasses and types for the risk management module.
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


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
    """Per-channel risk settings with tiered targets."""
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
    stop_loss_pct: float = 0.0
    trailing_stop_pct: float = 0.0
    trailing_activation_pct: float = 15.0
    leave_runner_enabled: bool = False  # Keep portion after profit targets
    leave_runner_pct: float = 25.0  # Percentage of position to leave as runner
    trim_order_mode: str = 'market'  # 'market' or 'limit' for trim orders
    trim_limit_offset: float = 0.01  # Offset for limit orders (e.g., 0.01 = $0.01)
    exit_strategy_mode: str = 'signal'  # 'signal' = follow trader, 'risk' = auto exits, 'hybrid' = both
    
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
                self.trailing_stop_pct > 0)


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
    def trailing_stop(cls, reason: str, qty: int, channel_name: str = "Global") -> 'ExitDecision':
        """Factory for trailing stop exit."""
        return cls(
            should_exit=True,
            reason=f"TRAILING STOP [{channel_name}] {reason}",
            exit_qty=qty,
            is_partial=False,
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
    stop_loss_price: Optional[float] = None
    profit_target_price: Optional[float] = None
    broker: str = ""
    raw_symbol: Optional[str] = None
    channel_settings: Optional[ChannelRiskSettings] = None
    
    tier1_hit: bool = False
    tier2_hit: bool = False
    tier3_hit: bool = False
    tier4_hit: bool = False
    
    # Pending risk orders awaiting fill confirmation
    pending_orders: Dict[str, Any] = field(default_factory=dict)  # order_id -> PendingRiskOrder dict
    
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
            'pending_orders': self.pending_orders,
            'created_at': self.created_at.isoformat()
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
    
    def update_highest_price(self, current_price: float, position_key: str = None, verbose: bool = False) -> bool:
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
    
    def add_pending_order(self, order_id: str, tier: int, qty_expected: int) -> None:
        """Track a new pending risk order."""
        self.pending_orders[order_id] = {
            'order_id': order_id,
            'tier': tier,
            'qty_expected': qty_expected,
            'qty_filled': 0,
            'status': 'pending',
            'created_at': datetime.now().isoformat()
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
