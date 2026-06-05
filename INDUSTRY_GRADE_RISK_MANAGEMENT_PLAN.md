# 🚀 COMPLETE DEVELOPMENT PROMPT: Industry-Grade Risk Management System for BotifyTrades

## Project Overview

Implement a comprehensive, industry-grade Order Management System (OMS) and Risk Management System (RMS) for BotifyTrades. This includes dynamic SL/PT management for C1apped-style signals, centralized exit arbitration, circuit breakers, and a complete Help Center with onboarding.

---

## TABLE OF CONTENTS

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [Phase 1: Database Schema](#phase-1-database-schema)
4. [Phase 2: SignalExitManager Service](#phase-2-signalexitmanager-service)
5. [Phase 3: ExitOrderArbiter Service](#phase-3-exitorderarbiter-service)
6. [Phase 4: CircuitBreaker Service](#phase-4-circuitbreaker-service)
7. [Phase 5: Broker Integration Layer](#phase-5-broker-integration-layer)
8. [Phase 6: Event Bus & Notifications](#phase-6-event-bus--notifications)
9. [Phase 7: API Routes](#phase-7-api-routes)
10. [Phase 8: UI Templates](#phase-8-ui-templates)
11. [Phase 9: Help Center & Onboarding](#phase-9-help-center--onboarding)
12. [Phase 10: Selfbot Integration](#phase-10-selfbot-integration)
13. [Phase 11: P&L Reconciliation](#phase-11-pnl-reconciliation)
14. [Phase 12: Testing Strategy](#phase-12-testing-strategy)
15. [Phase 13: Deployment & Rollout](#phase-13-deployment--rollout)
16. [Appendix: Complete Code](#appendix-complete-code)

---

## EXECUTIVE SUMMARY

### Current Gaps Identified

| Gap | Severity | Description |
|-----|----------|-------------|
| No centralized order state machine | 🔴 Critical | Orders mutated ad-hoc across services |
| No event bus for order lifecycle | 🔴 Critical | Point-to-point calls, no durability |
| No exit order arbiter | 🔴 Critical | Risk/Signal compete without precedence |
| No circuit breaker/kill switch | 🔴 Critical | Can't halt trading in emergency |
| No daily loss limits | 🔴 Critical | Unlimited losses possible |
| No order timeout enforcement | 🔴 Critical | Orders can hang indefinitely |
| Signal instances lack order IDs | 🔴 Critical | Can't track/modify broker orders |
| No broker capability registry | 🟠 High | UI shows unsupported features |
| No P&L reconciliation for modified orders | 🟠 High | Execution P&L inaccurate |
| No onboarding wizard | 🟡 Medium | Users confused by settings |
| No help content | 🟡 Medium | No documentation for features |

### Implementation Timeline

| Phase | Duration | Priority | Dependencies |
|-------|----------|----------|--------------|
| Phase 1: Database Schema | 1 day | P0 | None |
| Phase 4: Circuit Breaker | 0.5 day | P0 | Phase 1 |
| Phase 2: SignalExitManager | 2 days | P0 | Phase 1 |
| Phase 3: ExitOrderArbiter | 1 day | P0 | Phase 2 |
| Phase 5: Broker Integration | 1 day | P0 | Phase 2, 3 |
| Phase 6: Event Bus | 1 day | P1 | Phase 2, 3 |
| Phase 7: API Routes | 1 day | P1 | Phase 1-4 |
| Phase 8: UI Templates | 2 days | P1 | Phase 7 |
| Phase 9: Help Center | 1.5 days | P2 | Phase 8 |
| Phase 10: Selfbot Integration | 1 day | P0 | Phase 2, 3, 4 |
| Phase 11: P&L Reconciliation | 1 day | P1 | Phase 6 |
| Phase 12: Testing | 2 days | P0 | All |
| Phase 13: Deployment | 0.5 day | P0 | Phase 12 |

**Total: ~15 days**

---

## ARCHITECTURE OVERVIEW

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           TRADING CONTROL PLANE                              │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐              │
│  │ CIRCUIT BREAKER │  │ DAILY LOSS      │  │ POSITION        │              │
│  │ (Kill Switch)   │  │ LIMIT           │  │ LIMITS          │              │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘              │
│           └────────────────────┼────────────────────┘                        │
│                                ▼                                             │
│                    ┌───────────────────────┐                                 │
│                    │   RISK GATE           │  ← All orders pass through     │
│                    │   (Pre-trade checks)  │                                 │
│                    └───────────┬───────────┘                                 │
└────────────────────────────────┼─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        ORDER MANAGEMENT SYSTEM                               │
├──────────────────────────────────────────────────────────────────────────────┤
│                    ┌───────────────────────┐                                 │
│                    │  ORDER STATE MACHINE  │                                 │
│                    │  (FSM + Event Bus)    │                                 │
│                    └───────────┬───────────┘                                 │
│                                │                                             │
│    ┌───────────────────────────┼───────────────────────────┐                 │
│    ▼                           ▼                           ▼                 │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐           │
│  │ Signal Exit  │    │ Risk Manager     │    │ Conditional      │           │
│  │ Manager      │    │ (PT/SL/Trailing) │    │ Order Router     │           │
│  └──────┬───────┘    └────────┬─────────┘    └────────┬─────────┘           │
│         └──────────────────────┼──────────────────────┘                      │
│                                ▼                                             │
│                    ┌───────────────────────┐                                 │
│                    │   EXIT ORDER ARBITER  │  ← Precedence + Locking        │
│                    └───────────┬───────────┘                                 │
└────────────────────────────────┼─────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        BROKER ABSTRACTION LAYER                              │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │ Capability Registry: { canModify, canBracket, maxOrdersPerSec }   │     │
│  │ Rate Limiter: Per-broker throttling                                │     │
│  │ Timeout Handler: Auto-cancel aged orders                           │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│         │              │              │              │              │        │
│         ▼              ▼              ▼              ▼              ▼        │
│     Alpaca       Robinhood        Schwab         IBKR        Tastytrade    │
└──────────────────────────────────────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        EVENT BUS & NOTIFICATIONS                             │
├──────────────────────────────────────────────────────────────────────────────┤
│  Events: OrderCreated, OrderModified, OrderCancelled, OrderFilled,          │
│          SLUpdated, PTHit, CircuitBreakerTriggered, DailyLimitReached       │
│                                                                              │
│  Subscribers: BrokerSyncService, PnLTracker, RiskMonitor, UIWebSocket       │
└──────────────────────────────────────────────────────────────────────────────┘
                                 ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        MONITORING & OPERATIONS                               │
├──────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ Order Sweep  │  │ Position     │  │ P&L          │  │ Health       │     │
│  │ (Timeout)    │  │ Reconcile    │  │ Guardrails   │  │ Heartbeat    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘     │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## PHASE 1: DATABASE SCHEMA

### File: `gui_app/database.py`

Add the following migrations after existing channel migrations:

```python
# ============================================================================
# INDUSTRY-GRADE RISK MANAGEMENT SCHEMA UPDATES
# ============================================================================

# 1. Add order tracking columns to channels table
try:
    cursor.execute('SELECT sl_order_id FROM channels LIMIT 1')
except:
    cursor.execute('ALTER TABLE channels ADD COLUMN sl_order_id TEXT DEFAULT NULL')
    cursor.execute('ALTER TABLE channels ADD COLUMN pt_order_ids TEXT DEFAULT NULL')
    cursor.execute('ALTER TABLE channels ADD COLUMN order_timeout_minutes INTEGER DEFAULT 5')
    cursor.execute('ALTER TABLE channels ADD COLUMN max_daily_loss REAL DEFAULT NULL')
    cursor.execute('ALTER TABLE channels ADD COLUMN max_positions INTEGER DEFAULT 10')
    cursor.execute('ALTER TABLE channels ADD COLUMN max_position_pct REAL DEFAULT 25.0')
    cursor.execute('ALTER TABLE channels ADD COLUMN circuit_breaker_enabled INTEGER DEFAULT 1')
    print("[DATABASE] ✓ Added order tracking and risk limit columns to channels")

# 2. Add stop loss type column
try:
    cursor.execute('SELECT stop_loss_type FROM channels LIMIT 1')
except:
    cursor.execute("ALTER TABLE channels ADD COLUMN stop_loss_type TEXT DEFAULT 'percentage'")
    cursor.execute('ALTER TABLE channels ADD COLUMN stop_loss_fixed REAL DEFAULT NULL')
    print("[DATABASE] ✓ Added stop_loss_type column")

# 3. Create order_states table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS order_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_instance_id INTEGER,
        broker TEXT NOT NULL,
        order_type TEXT NOT NULL,
        broker_order_id TEXT,
        status TEXT DEFAULT 'pending',
        original_price REAL,
        current_price REAL,
        quantity INTEGER,
        filled_quantity INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        replaced_by_id INTEGER,
        cancel_reason TEXT,
        timeout_at TIMESTAMP,
        retry_count INTEGER DEFAULT 0,
        FOREIGN KEY (signal_instance_id) REFERENCES signal_instances(id),
        FOREIGN KEY (replaced_by_id) REFERENCES order_states(id)
    )
''')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_states_signal ON order_states(signal_instance_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_states_broker_order ON order_states(broker_order_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_states_status ON order_states(status)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_states_timeout ON order_states(timeout_at)')
print("[DATABASE] ✓ Created order_states table")

# 4. Create risk_limits table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS risk_limits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scope TEXT NOT NULL,
        scope_id TEXT,
        limit_type TEXT NOT NULL,
        limit_value REAL NOT NULL,
        current_value REAL DEFAULT 0,
        is_breached INTEGER DEFAULT 0,
        last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reset_frequency TEXT DEFAULT 'daily',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_risk_limits_scope ON risk_limits(scope, scope_id)')
cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_risk_limits_unique ON risk_limits(scope, scope_id, limit_type)')
print("[DATABASE] ✓ Created risk_limits table")

# 5. Create risk_events table (audit log)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS risk_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        channel_id TEXT,
        signal_instance_id INTEGER,
        order_state_id INTEGER,
        old_value TEXT,
        new_value TEXT,
        reason TEXT,
        metadata TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_risk_events_type ON risk_events(event_type)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_risk_events_channel ON risk_events(channel_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_risk_events_created ON risk_events(created_at)')
print("[DATABASE] ✓ Created risk_events table")

# 6. Create broker_capabilities table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS broker_capabilities (
        broker TEXT PRIMARY KEY,
        can_modify_order INTEGER DEFAULT 0,
        can_replace_order INTEGER DEFAULT 0,
        supports_bracket INTEGER DEFAULT 0,
        supports_oco INTEGER DEFAULT 0,
        supports_trailing_stop INTEGER DEFAULT 0,
        supports_extended_hours INTEGER DEFAULT 0,
        max_gtc_days INTEGER DEFAULT 90,
        rate_limit_per_second INTEGER DEFAULT 5,
        min_order_interval_ms INTEGER DEFAULT 100,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# Insert default broker capabilities
broker_caps = [
    ('alpaca', 0, 1, 1, 1, 0, 1, 90, 10, 100),
    ('robinhood', 0, 0, 1, 1, 0, 1, 90, 5, 200),
    ('schwab', 0, 1, 1, 1, 1, 1, 60, 5, 200),
    ('ibkr', 1, 1, 1, 1, 1, 1, 90, 20, 50),
    ('tastytrade', 0, 0, 0, 1, 0, 1, 90, 5, 200),
    ('webull', 0, 0, 0, 0, 0, 1, 90, 5, 300),
]
for cap in broker_caps:
    cursor.execute('''
        INSERT OR IGNORE INTO broker_capabilities 
        (broker, can_modify_order, can_replace_order, supports_bracket, supports_oco, 
         supports_trailing_stop, supports_extended_hours, max_gtc_days, rate_limit_per_second, min_order_interval_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', cap)
print("[DATABASE] ✓ Created broker_capabilities table")

# 7. Create global_settings table for circuit breaker
cursor.execute('''
    CREATE TABLE IF NOT EXISTS global_risk_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        trading_halted INTEGER DEFAULT 0,
        halt_reason TEXT,
        halt_timestamp TIMESTAMP,
        global_daily_loss_limit REAL DEFAULT NULL,
        global_max_positions INTEGER DEFAULT 50,
        order_timeout_default_minutes INTEGER DEFAULT 5,
        enable_stale_quote_protection INTEGER DEFAULT 1,
        stale_quote_threshold_seconds INTEGER DEFAULT 30,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
cursor.execute('INSERT OR IGNORE INTO global_risk_settings (id) VALUES (1)')
print("[DATABASE] ✓ Created global_risk_settings table")

# 8. Update signal_instances table with order tracking
try:
    cursor.execute('SELECT sl_order_id FROM signal_instances LIMIT 1')
except:
    cursor.execute('ALTER TABLE signal_instances ADD COLUMN sl_order_id TEXT DEFAULT NULL')
    cursor.execute('ALTER TABLE signal_instances ADD COLUMN pt_order_ids TEXT DEFAULT NULL')
    cursor.execute('ALTER TABLE signal_instances ADD COLUMN current_sl_price REAL DEFAULT NULL')
    cursor.execute('ALTER TABLE signal_instances ADD COLUMN filled_pt_levels TEXT DEFAULT NULL')
    cursor.execute('ALTER TABLE signal_instances ADD COLUMN remaining_qty INTEGER DEFAULT NULL')
    cursor.execute('ALTER TABLE signal_instances ADD COLUMN exit_strategy_mode TEXT DEFAULT NULL')
    cursor.execute('ALTER TABLE signal_instances ADD COLUMN broker TEXT DEFAULT NULL')
    print("[DATABASE] ✓ Added order tracking columns to signal_instances")

# 9. Create order_update_queue table for debouncing
cursor.execute('''
    CREATE TABLE IF NOT EXISTS order_update_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_instance_id INTEGER NOT NULL,
        update_type TEXT NOT NULL,
        new_value TEXT,
        source TEXT,
        priority INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        processed_at TIMESTAMP,
        error_message TEXT,
        FOREIGN KEY (signal_instance_id) REFERENCES signal_instances(id)
    )
''')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_queue_status ON order_update_queue(status)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_queue_signal ON order_update_queue(signal_instance_id)')
print("[DATABASE] ✓ Created order_update_queue table")
```

### Database Helper Functions

Add these functions to `gui_app/database.py`:

```python
# ============================================================================
# ORDER STATE MANAGEMENT FUNCTIONS
# ============================================================================

def create_order_state(signal_instance_id: int, broker: str, order_type: str,
                       broker_order_id: str, price: float, quantity: int,
                       timeout_minutes: int = 5) -> int:
    """Create a new order state record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    timeout_at = datetime.now() + timedelta(minutes=timeout_minutes)
    cursor.execute('''
        INSERT INTO order_states 
        (signal_instance_id, broker, order_type, broker_order_id, status,
         original_price, current_price, quantity, timeout_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)
    ''', (signal_instance_id, broker, order_type, broker_order_id, price, price, quantity, timeout_at))
    conn.commit()
    order_id = cursor.lastrowid
    conn.close()
    return order_id


def update_order_state(order_id: int, status: str = None, new_price: float = None,
                       filled_qty: int = None, cancel_reason: str = None,
                       replaced_by_id: int = None) -> bool:
    """Update an order state record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    updates = ['updated_at = CURRENT_TIMESTAMP']
    params = []
    
    if status:
        updates.append('status = ?')
        params.append(status)
    if new_price is not None:
        updates.append('current_price = ?')
        params.append(new_price)
    if filled_qty is not None:
        updates.append('filled_quantity = ?')
        params.append(filled_qty)
    if cancel_reason:
        updates.append('cancel_reason = ?')
        params.append(cancel_reason)
    if replaced_by_id:
        updates.append('replaced_by_id = ?')
        params.append(replaced_by_id)
    
    params.append(order_id)
    cursor.execute(f"UPDATE order_states SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    return success


def get_active_sl_order(signal_instance_id: int) -> Optional[Dict]:
    """Get the current active stop loss order for a signal instance."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM order_states 
        WHERE signal_instance_id = ? AND order_type = 'stop_loss' AND status = 'active'
        ORDER BY id DESC LIMIT 1
    ''', (signal_instance_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_active_orders(signal_instance_id: int) -> List[Dict]:
    """Get all active orders for a signal instance."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM order_states 
        WHERE signal_instance_id = ? AND status = 'active'
    ''', (signal_instance_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_timed_out_orders() -> List[Dict]:
    """Get orders that have exceeded their timeout."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM order_states 
        WHERE status = 'active' AND timeout_at < CURRENT_TIMESTAMP
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def log_risk_event(event_type: str, channel_id: str = None, 
                   signal_instance_id: int = None, order_state_id: int = None,
                   old_value: str = None, new_value: str = None, 
                   reason: str = None, metadata: dict = None):
    """Log a risk event for audit trail."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO risk_events 
        (event_type, channel_id, signal_instance_id, order_state_id, 
         old_value, new_value, reason, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (event_type, channel_id, signal_instance_id, order_state_id,
          old_value, new_value, reason, json.dumps(metadata) if metadata else None))
    conn.commit()
    conn.close()


def get_broker_capabilities(broker: str) -> Dict:
    """Get capabilities for a specific broker."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM broker_capabilities WHERE broker = ?', (broker.lower(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}


def get_global_risk_settings() -> Dict:
    """Get global risk settings including circuit breaker status."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM global_risk_settings WHERE id = 1')
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}


def set_trading_halt(halted: bool, reason: str = None):
    """Set global trading halt (circuit breaker)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if halted:
        cursor.execute('''
            UPDATE global_risk_settings 
            SET trading_halted = 1, halt_reason = ?, halt_timestamp = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''', (reason,))
    else:
        cursor.execute('''
            UPDATE global_risk_settings 
            SET trading_halted = 0, halt_reason = NULL, halt_timestamp = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        ''')
    conn.commit()
    conn.close()
    log_risk_event('circuit_breaker', reason=reason if halted else 'Trading resumed')


def is_trading_halted() -> Tuple[bool, Optional[str]]:
    """Check if trading is globally halted."""
    settings = get_global_risk_settings()
    return (settings.get('trading_halted', 0) == 1, settings.get('halt_reason'))
```

---

## PHASE 2: SIGNALEXITMANAGER SERVICE

### File: `src/services/signal_exit_manager.py` (NEW FILE)

```python
"""
SignalExitManager - Industry-grade dynamic SL/PT management for signal-based trading.

Handles:
- Dynamic stop loss modification when trader updates signals
- Profit target tracking and partial exits
- Broker-agnostic order modification (replace or cancel+recreate)
- Exit strategy mode precedence (signal, risk, hybrid)
- Event logging for audit trail
- Debouncing for rapid signal updates
- Timeout handling for stuck operations
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import time

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    PENDING = 'pending'
    ACTIVE = 'active'
    FILLED = 'filled'
    CANCELLED = 'cancelled'
    REPLACED = 'replaced'
    EXPIRED = 'expired'
    FAILED = 'failed'


class ExitStrategyMode(Enum):
    SIGNAL = 'signal'
    RISK = 'risk'
    HYBRID = 'hybrid'


@dataclass
class PendingUpdate:
    """Represents a pending SL/PT update for debouncing."""
    signal_instance_id: int
    update_type: str
    new_value: float
    source: str
    timestamp: float = field(default_factory=time.time)
    priority: int = 0


class SignalExitManager:
    """
    Centralized manager for exit order lifecycle.
    
    Features:
    1. Track broker order IDs for SL/PT orders
    2. Handle signal updates (modify/replace SL orders)
    3. Apply precedence rules for hybrid mode
    4. Log all changes for audit trail
    5. Debounce rapid updates (100ms window)
    6. Retry failed operations (3 attempts)
    7. Timeout handling for stuck operations
    """
    
    DEBOUNCE_MS = 100  # Debounce window for rapid updates
    MAX_RETRIES = 3
    OPERATION_TIMEOUT_SECONDS = 30
    
    def __init__(self, db_path: str = 'bot_data.db'):
        self.db_path = db_path
        self._locks = {}  # signal_instance_id -> asyncio.Lock
        self._broker_registry = {}  # broker_name -> broker_instance
        self._pending_updates = defaultdict(list)  # signal_instance_id -> [PendingUpdate]
        self._debounce_tasks = {}  # signal_instance_id -> asyncio.Task
        self._initialized = False
        
    def _get_lock(self, signal_instance_id: int) -> asyncio.Lock:
        """Get or create a lock for a signal instance."""
        if signal_instance_id not in self._locks:
            self._locks[signal_instance_id] = asyncio.Lock()
        return self._locks[signal_instance_id]
    
    def register_broker(self, name: str, broker_instance):
        """Register a broker instance for order operations."""
        self._broker_registry[name.lower()] = broker_instance
        logger.info(f"[SignalExitManager] Registered broker: {name}")
        
    def unregister_broker(self, name: str):
        """Unregister a broker instance."""
        if name.lower() in self._broker_registry:
            del self._broker_registry[name.lower()]
            logger.info(f"[SignalExitManager] Unregistered broker: {name}")
    
    async def initialize(self):
        """Initialize the manager - call on startup."""
        if self._initialized:
            return
        
        # Start background tasks
        asyncio.create_task(self._order_timeout_sweep())
        asyncio.create_task(self._debounce_processor())
        
        self._initialized = True
        logger.info("[SignalExitManager] Initialized")
    
    async def _order_timeout_sweep(self):
        """Background task to handle timed-out orders."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                from gui_app.database import get_timed_out_orders, update_order_state, log_risk_event
                
                timed_out = get_timed_out_orders()
                for order in timed_out:
                    logger.warning(f"[SignalExitManager] Order timeout: {order['id']} ({order['order_type']})")
                    
                    # Try to cancel at broker
                    broker = self._broker_registry.get(order['broker'].lower())
                    if broker and order['broker_order_id']:
                        try:
                            await broker.cancel_order(order['broker_order_id'])
                        except Exception as e:
                            logger.error(f"Failed to cancel timed-out order: {e}")
                    
                    # Update state
                    update_order_state(order['id'], status='expired', cancel_reason='timeout')
                    log_risk_event('order_timeout', 
                                   signal_instance_id=order['signal_instance_id'],
                                   order_state_id=order['id'])
                    
            except Exception as e:
                logger.error(f"[SignalExitManager] Timeout sweep error: {e}")
    
    async def _debounce_processor(self):
        """Background task to process debounced updates."""
        while True:
            try:
                await asyncio.sleep(0.05)  # 50ms tick
                
                now = time.time()
                for signal_id, updates in list(self._pending_updates.items()):
                    if not updates:
                        continue
                    
                    # Check if oldest update is past debounce window
                    oldest = min(u.timestamp for u in updates)
                    if now - oldest >= self.DEBOUNCE_MS / 1000:
                        # Get highest priority update of each type
                        by_type = defaultdict(list)
                        for u in updates:
                            by_type[u.update_type].append(u)
                        
                        # Process the latest update of each type
                        for update_type, type_updates in by_type.items():
                            latest = max(type_updates, key=lambda u: (u.priority, u.timestamp))
                            asyncio.create_task(self._process_debounced_update(latest))
                        
                        # Clear processed updates
                        self._pending_updates[signal_id] = []
                        
            except Exception as e:
                logger.error(f"[SignalExitManager] Debounce processor error: {e}")
    
    async def _process_debounced_update(self, update: PendingUpdate):
        """Process a debounced update."""
        if update.update_type == 'stop_loss':
            await self._do_sl_update(update.signal_instance_id, update.new_value, update.source)
    
    async def handle_new_entry(
        self,
        signal_instance_id: int,
        broker: str,
        ticker: str,
        entry_price: float,
        stop_loss: Optional[float],
        profit_targets: List[float],
        quantity: int,
        exit_strategy_mode: str = 'signal'
    ) -> Dict[str, Any]:
        """
        Handle a new signal entry - place bracket order with SL/PT.
        """
        async with self._get_lock(signal_instance_id):
            result = {
                'success': False,
                'entry_order_id': None,
                'sl_order_id': None,
                'pt_order_ids': [],
                'error': None
            }
            
            broker_instance = self._broker_registry.get(broker.lower())
            if not broker_instance:
                result['error'] = f"Broker {broker} not registered"
                logger.error(f"[SignalExitManager] {result['error']}")
                return result
            
            from gui_app.database import get_broker_capabilities, create_order_state, log_risk_event
            
            capabilities = get_broker_capabilities(broker)
            
            try:
                if capabilities.get('supports_bracket') and stop_loss:
                    # Use native bracket order
                    pt1 = profit_targets[0] if profit_targets else None
                    
                    order_result = await asyncio.wait_for(
                        broker_instance.place_bracket_order(
                            symbol=ticker,
                            action='BTO',
                            quantity=quantity,
                            stop_loss_price=stop_loss,
                            profit_target_price=pt1,
                            entry_price=entry_price
                        ),
                        timeout=self.OPERATION_TIMEOUT_SECONDS
                    )
                    
                    if order_result.get('success'):
                        result['success'] = True
                        result['entry_order_id'] = order_result.get('order_id')
                        
                        # Store SL order state
                        sl_order_id = order_result.get('sl_order_id') or order_result.get('order_id')
                        result['sl_order_id'] = sl_order_id
                        
                        create_order_state(
                            signal_instance_id, broker, 'stop_loss',
                            sl_order_id, stop_loss, quantity
                        )
                        
                        if pt1:
                            pt_order_id = order_result.get('pt_order_id') or order_result.get('order_id')
                            result['pt_order_ids'] = [pt_order_id]
                            create_order_state(
                                signal_instance_id, broker, 'profit_target',
                                pt_order_id, pt1, quantity
                            )
                        
                        log_risk_event(
                            'entry_with_bracket',
                            signal_instance_id=signal_instance_id,
                            new_value=json.dumps({'sl': stop_loss, 'pt': profit_targets[:1]}),
                            metadata={'broker': broker, 'ticker': ticker}
                        )
                        
                        logger.info(f"[SignalExitManager] Bracket entry: {ticker} SL=${stop_loss} PT1=${pt1}")
                else:
                    # Place entry only, then separate SL order
                    entry_result = await asyncio.wait_for(
                        broker_instance.place_order(
                            symbol=ticker,
                            action='BTO',
                            quantity=quantity,
                            price=entry_price
                        ),
                        timeout=self.OPERATION_TIMEOUT_SECONDS
                    )
                    
                    if entry_result.get('success'):
                        result['entry_order_id'] = entry_result.get('order_id')
                        
                        # Place separate SL order
                        if stop_loss:
                            sl_result = await asyncio.wait_for(
                                broker_instance.place_stop_order(
                                    symbol=ticker,
                                    action='STC',
                                    quantity=quantity,
                                    stop_price=stop_loss
                                ),
                                timeout=self.OPERATION_TIMEOUT_SECONDS
                            )
                            
                            if sl_result.get('success'):
                                result['sl_order_id'] = sl_result.get('order_id')
                                create_order_state(
                                    signal_instance_id, broker, 'stop_loss',
                                    result['sl_order_id'], stop_loss, quantity
                                )
                        
                        result['success'] = True
                        log_risk_event(
                            'entry_separate_sl',
                            signal_instance_id=signal_instance_id,
                            new_value=json.dumps({'sl': stop_loss}),
                            metadata={'broker': broker, 'ticker': ticker}
                        )
                        
            except asyncio.TimeoutError:
                result['error'] = "Operation timed out"
                logger.error(f"[SignalExitManager] Entry timeout for {ticker}")
            except Exception as e:
                result['error'] = str(e)
                logger.error(f"[SignalExitManager] Entry error: {e}")
                
            return result
    
    async def queue_sl_update(
        self,
        signal_instance_id: int,
        new_sl_price: float,
        source: str = 'signal',
        priority: int = 0
    ):
        """Queue an SL update for debouncing."""
        update = PendingUpdate(
            signal_instance_id=signal_instance_id,
            update_type='stop_loss',
            new_value=new_sl_price,
            source=source,
            priority=priority
        )
        self._pending_updates[signal_instance_id].append(update)
        logger.debug(f"[SignalExitManager] Queued SL update: {signal_instance_id} -> ${new_sl_price}")
    
    async def handle_sl_update(
        self,
        signal_instance_id: int,
        new_sl_price: float,
        exit_strategy_mode: str = 'signal',
        source: str = 'signal'
    ) -> Dict[str, Any]:
        """
        Handle stop loss update - queues for debouncing.
        For immediate execution, use _do_sl_update directly.
        """
        priority = 1 if source == 'signal' else 0
        await self.queue_sl_update(signal_instance_id, new_sl_price, source, priority)
        return {'queued': True, 'signal_instance_id': signal_instance_id}
    
    async def _do_sl_update(
        self,
        signal_instance_id: int,
        new_sl_price: float,
        source: str = 'signal'
    ) -> Dict[str, Any]:
        """
        Execute stop loss update (internal, after debouncing).
        """
        async with self._get_lock(signal_instance_id):
            result = {
                'success': False,
                'old_sl': None,
                'new_sl': new_sl_price,
                'action': None,
                'error': None
            }
            
            from gui_app.database import (
                get_active_sl_order, get_broker_capabilities, update_order_state,
                create_order_state, log_risk_event
            )
            
            order_state = get_active_sl_order(signal_instance_id)
            if not order_state:
                result['error'] = "No active SL order found"
                return result
            
            result['old_sl'] = order_state['current_price']
            broker = order_state['broker']
            
            broker_instance = self._broker_registry.get(broker.lower())
            if not broker_instance:
                result['error'] = f"Broker {broker} not registered"
                return result
            
            capabilities = get_broker_capabilities(broker)
            
            # Retry logic
            for attempt in range(self.MAX_RETRIES):
                try:
                    if capabilities.get('can_replace_order'):
                        # Fast path: replace order (Alpaca, Schwab)
                        replace_result = await asyncio.wait_for(
                            broker_instance.replace_order(
                                order_id=order_state['broker_order_id'],
                                stop_price=new_sl_price
                            ),
                            timeout=self.OPERATION_TIMEOUT_SECONDS
                        )
                        
                        if replace_result.get('success'):
                            result['success'] = True
                            result['action'] = 'replaced'
                            new_order_id = replace_result.get('new_order_id', order_state['broker_order_id'])
                            update_order_state(
                                order_state['id'],
                                status='replaced',
                                new_price=new_sl_price
                            )
                            # Create new order state for the replacement
                            create_order_state(
                                signal_instance_id, broker, 'stop_loss',
                                new_order_id, new_sl_price,
                                order_state['quantity'] - order_state['filled_quantity']
                            )
                            break
                            
                    elif capabilities.get('can_modify_order'):
                        # IBKR style: modify in place
                        modify_result = await asyncio.wait_for(
                            broker_instance.modify_order(
                                order_id=order_state['broker_order_id'],
                                stop_price=new_sl_price
                            ),
                            timeout=self.OPERATION_TIMEOUT_SECONDS
                        )
                        
                        if modify_result.get('success'):
                            result['success'] = True
                            result['action'] = 'modified'
                            update_order_state(
                                order_state['id'],
                                new_price=new_sl_price
                            )
                            break
                    else:
                        # Slow path: cancel and recreate (Robinhood, Webull)
                        cancel_result = await asyncio.wait_for(
                            broker_instance.cancel_order(order_state['broker_order_id']),
                            timeout=self.OPERATION_TIMEOUT_SECONDS
                        )
                        
                        if cancel_result.get('success') or cancel_result == True:
                            # Get signal info for ticker
                            from gui_app.database import get_signal_instance_by_id
                            signal_info = get_signal_instance_by_id(signal_instance_id)
                            
                            if signal_info:
                                new_sl_result = await asyncio.wait_for(
                                    broker_instance.place_stop_order(
                                        symbol=signal_info['ticker'],
                                        action='STC',
                                        quantity=order_state['quantity'] - order_state['filled_quantity'],
                                        stop_price=new_sl_price
                                    ),
                                    timeout=self.OPERATION_TIMEOUT_SECONDS
                                )
                                
                                if new_sl_result.get('success'):
                                    result['success'] = True
                                    result['action'] = 'cancel_replace'
                                    update_order_state(
                                        order_state['id'],
                                        status='cancelled',
                                        cancel_reason='sl_update'
                                    )
                                    create_order_state(
                                        signal_instance_id, broker, 'stop_loss',
                                        new_sl_result.get('order_id'), new_sl_price,
                                        order_state['quantity'] - order_state['filled_quantity']
                                    )
                                    break
                                    
                except asyncio.TimeoutError:
                    logger.warning(f"[SignalExitManager] SL update attempt {attempt+1} timed out")
                    if attempt == self.MAX_RETRIES - 1:
                        result['error'] = "Operation timed out after retries"
                except Exception as e:
                    logger.error(f"[SignalExitManager] SL update attempt {attempt+1} error: {e}")
                    if attempt == self.MAX_RETRIES - 1:
                        result['error'] = str(e)
                
                # Wait before retry
                if attempt < self.MAX_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
            
            if result['success']:
                log_risk_event(
                    'sl_modified',
                    signal_instance_id=signal_instance_id,
                    order_state_id=order_state['id'],
                    old_value=str(result['old_sl']),
                    new_value=str(new_sl_price),
                    reason=f"Signal update via {result['action']}"
                )
                logger.info(f"[SignalExitManager] SL updated: ${result['old_sl']} -> ${new_sl_price} ({result['action']})")
            
            return result
    
    async def handle_exit_signal(
        self,
        signal_instance_id: int,
        exit_type: str = 'all_out'
    ) -> Dict[str, Any]:
        """
        Handle trader's exit signal (all out, closed, etc.)
        """
        async with self._get_lock(signal_instance_id):
            result = {
                'success': False,
                'cancelled_orders': [],
                'error': None
            }
            
            from gui_app.database import get_all_active_orders, update_order_state, log_risk_event
            
            active_orders = get_all_active_orders(signal_instance_id)
            
            for order in active_orders:
                broker_instance = self._broker_registry.get(order['broker'].lower())
                if broker_instance and order['broker_order_id']:
                    try:
                        await asyncio.wait_for(
                            broker_instance.cancel_order(order['broker_order_id']),
                            timeout=10
                        )
                        result['cancelled_orders'].append(order['broker_order_id'])
                        update_order_state(
                            order['id'],
                            status='cancelled',
                            cancel_reason='exit_signal'
                        )
                    except Exception as e:
                        logger.error(f"[SignalExitManager] Cancel failed: {e}")
            
            log_risk_event(
                'exit_signal',
                signal_instance_id=signal_instance_id,
                reason=exit_type,
                metadata={'cancelled_count': len(result['cancelled_orders'])}
            )
            
            result['success'] = True
            logger.info(f"[SignalExitManager] Exit signal processed: {exit_type}, cancelled {len(result['cancelled_orders'])} orders")
            
            return result


# Global instance
signal_exit_manager = SignalExitManager()
```

---

## PHASE 3: EXITORDERARBITER SERVICE

### File: `src/services/exit_order_arbiter.py` (NEW FILE)

```python
"""
ExitOrderArbiter - Centralized arbitration for exit orders.

Prevents conflicts between SignalExitManager and RiskManager.
Applies precedence rules for hybrid mode.
Ensures thread-safe order modifications.
"""

import asyncio
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class UpdateSource(Enum):
    SIGNAL = 'signal'       # From trader's signal update
    TRAILING = 'trailing'   # From trailing stop calculation
    RISK = 'risk'          # From channel risk settings
    MANUAL = 'manual'      # From user manual override


class ExitOrderArbiter:
    """
    Single source of truth for exit order decisions.
    
    Precedence Rules (Hybrid Mode):
    1. Signal SL can only RAISE the floor (never lower for long positions)
    2. Trailing stop applies AFTER signal SL
    3. First valid stop wins, duplicates are deduplicated
    4. Trader's explicit exit ("all out") ALWAYS wins
    5. Manual user override has highest priority
    
    Thread Safety:
    - Each signal instance has its own lock
    - Updates are serialized per signal
    - Cross-signal updates can happen in parallel
    """
    
    def __init__(self):
        self._locks = {}
        self._last_updates = {}  # signal_instance_id -> (source, timestamp, value)
        
    def _get_lock(self, signal_instance_id: int) -> asyncio.Lock:
        if signal_instance_id not in self._locks:
            self._locks[signal_instance_id] = asyncio.Lock()
        return self._locks[signal_instance_id]
    
    async def request_sl_update(
        self,
        signal_instance_id: int,
        source: str,
        new_sl_price: float,
        current_sl_price: float,
        exit_strategy_mode: str,
        position_direction: str = 'long'
    ) -> Dict:
        """
        Request to update stop loss. Arbiter decides if update should proceed.
        
        Args:
            signal_instance_id: The signal instance to update
            source: Who is requesting (signal, trailing, risk, manual)
            new_sl_price: Proposed new stop loss price
            current_sl_price: Current stop loss price
            exit_strategy_mode: signal, risk, or hybrid
            position_direction: long or short
        
        Returns:
            {
                'approved': bool,
                'final_sl': float,
                'reason': str
            }
        """
        async with self._get_lock(signal_instance_id):
            result = {
                'approved': False,
                'final_sl': current_sl_price,
                'reason': ''
            }
            
            # Manual override always wins
            if source == 'manual':
                result['approved'] = True
                result['final_sl'] = new_sl_price
                result['reason'] = 'Manual override accepted'
                self._record_update(signal_instance_id, source, new_sl_price)
                return result
            
            if exit_strategy_mode == 'signal':
                # Only signal source can update
                if source == 'signal':
                    result['approved'] = True
                    result['final_sl'] = new_sl_price
                    result['reason'] = 'Signal mode: signal update accepted'
                    self._record_update(signal_instance_id, source, new_sl_price)
                else:
                    result['reason'] = f'Signal mode: {source} updates ignored'
                    
            elif exit_strategy_mode == 'risk':
                # Only risk/trailing sources can update
                if source in ['trailing', 'risk']:
                    result['approved'] = True
                    result['final_sl'] = new_sl_price
                    result['reason'] = 'Risk mode: risk update accepted'
                    self._record_update(signal_instance_id, source, new_sl_price)
                else:
                    result['reason'] = f'Risk mode: {source} updates ignored'
                    
            elif exit_strategy_mode == 'hybrid':
                # Hybrid: tightest protection wins
                # For long positions: higher SL = tighter
                # For short positions: lower SL = tighter
                is_tighter = (
                    (position_direction == 'long' and new_sl_price > current_sl_price) or
                    (position_direction == 'short' and new_sl_price < current_sl_price)
                )
                
                if is_tighter:
                    result['approved'] = True
                    result['final_sl'] = new_sl_price
                    result['reason'] = f'Hybrid mode: {source} tightened SL {current_sl_price} -> {new_sl_price}'
                    self._record_update(signal_instance_id, source, new_sl_price)
                else:
                    result['reason'] = f'Hybrid mode: {source} would loosen SL, rejected'
            
            logger.info(f"[Arbiter] SL request: {source} {current_sl_price} -> {new_sl_price} = {result['approved']} ({result['reason']})")
            return result
    
    async def request_exit(
        self,
        signal_instance_id: int,
        source: str,
        reason: str
    ) -> Dict:
        """
        Request to close position. 
        Trader's explicit exit always wins; other exits are logged.
        """
        async with self._get_lock(signal_instance_id):
            # All exit requests are approved, but we log the source
            logger.info(f"[Arbiter] Exit approved: {source} - {reason}")
            return {
                'approved': True,
                'source': source,
                'reason': reason
            }
    
    def _record_update(self, signal_instance_id: int, source: str, value: float):
        """Record the last update for deduplication."""
        self._last_updates[signal_instance_id] = (source, datetime.now(), value)
    
    def get_last_update(self, signal_instance_id: int) -> Optional[Tuple[str, datetime, float]]:
        """Get the last update for a signal instance."""
        return self._last_updates.get(signal_instance_id)
    
    def cleanup(self, signal_instance_id: int):
        """Clean up state for a closed signal instance."""
        if signal_instance_id in self._locks:
            del self._locks[signal_instance_id]
        if signal_instance_id in self._last_updates:
            del self._last_updates[signal_instance_id]


# Global instance
exit_order_arbiter = ExitOrderArbiter()
```

---

## PHASE 4: CIRCUITBREAKER SERVICE

### File: `src/services/circuit_breaker.py` (NEW FILE)

```python
"""
CircuitBreaker - Global kill switch and risk limits.

Features:
- Global kill switch to halt all trading instantly
- Per-channel daily loss limits
- Global daily loss limit
- Max position limits
- Real-time P&L monitoring
- Automatic halt on limit breach
"""

import asyncio
import logging
from datetime import datetime, date
from typing import Dict, Optional, List, Tuple
import sqlite3

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    Global risk control system.
    
    Provides:
    1. Instant kill switch to halt all trading
    2. Automatic halt when daily loss limit reached
    3. Per-channel and global position limits
    4. Pre-trade validation gate
    """
    
    def __init__(self, db_path: str = 'bot_data.db'):
        self.db_path = db_path
        self._cache_ttl = 30  # Cache P&L for 30 seconds
        self._pnl_cache = {}  # channel_id -> (pnl, timestamp)
        self._position_cache = {}  # channel_id -> (count, timestamp)
        
    @property
    def is_halted(self) -> bool:
        """Check if trading is globally halted."""
        from gui_app.database import is_trading_halted
        halted, _ = is_trading_halted()
        return halted
    
    @property
    def halt_reason(self) -> Optional[str]:
        """Get the reason for trading halt."""
        from gui_app.database import is_trading_halted
        _, reason = is_trading_halted()
        return reason
    
    def halt_trading(self, reason: str):
        """Emergency stop all trading."""
        from gui_app.database import set_trading_halt, log_risk_event
        set_trading_halt(True, reason)
        logger.critical(f"[CIRCUIT BREAKER] ⚠️ TRADING HALTED: {reason}")
        
        # TODO: Cancel all open orders
        # This would iterate through active orders and cancel them
    
    def resume_trading(self):
        """Resume trading after halt."""
        from gui_app.database import set_trading_halt
        set_trading_halt(False)
        logger.info("[CIRCUIT BREAKER] ✓ Trading resumed")
    
    async def check_trade_allowed(
        self,
        channel_id: str,
        trade_value: float = 0,
        broker: str = None
    ) -> Dict:
        """
        Pre-trade validation gate.
        
        Checks:
        1. Global halt status
        2. Channel circuit breaker enabled
        3. Daily loss limit (global and per-channel)
        4. Max positions limit
        5. Max position size
        
        Returns:
            {
                'allowed': bool,
                'reason': str,
                'limits': {...}
            }
        """
        # Check global halt first
        if self.is_halted:
            return {
                'allowed': False,
                'reason': f'Trading halted: {self.halt_reason}',
                'limits': {}
            }
        
        # Get channel and global limits
        channel_limits = self._get_channel_limits(channel_id)
        global_limits = self._get_global_limits()
        
        # Check if channel circuit breaker is enabled
        if not channel_limits.get('circuit_breaker_enabled', True):
            # Circuit breaker disabled for this channel, allow trade
            return {
                'allowed': True,
                'reason': 'Circuit breaker disabled for channel',
                'limits': channel_limits
            }
        
        # Check global daily loss limit
        if global_limits.get('global_daily_loss_limit'):
            total_pnl = self._get_global_today_pnl()
            if total_pnl < -global_limits['global_daily_loss_limit']:
                self.halt_trading(f"Global daily loss limit reached: ${abs(total_pnl):.2f}")
                return {
                    'allowed': False,
                    'reason': f"Global daily loss limit reached: ${abs(total_pnl):.2f}",
                    'limits': global_limits
                }
        
        # Check channel daily loss limit
        if channel_limits.get('max_daily_loss'):
            channel_pnl = self._get_today_pnl(channel_id)
            if channel_pnl < -channel_limits['max_daily_loss']:
                return {
                    'allowed': False,
                    'reason': f"Channel daily loss limit reached: ${abs(channel_pnl):.2f} / ${channel_limits['max_daily_loss']:.2f}",
                    'limits': channel_limits
                }
        
        # Check channel max positions
        if channel_limits.get('max_positions'):
            open_positions = self._get_open_position_count(channel_id)
            if open_positions >= channel_limits['max_positions']:
                return {
                    'allowed': False,
                    'reason': f"Max positions reached: {open_positions} / {channel_limits['max_positions']}",
                    'limits': channel_limits
                }
        
        # Check global max positions
        if global_limits.get('global_max_positions'):
            total_positions = self._get_total_position_count()
            if total_positions >= global_limits['global_max_positions']:
                return {
                    'allowed': False,
                    'reason': f"Global max positions reached: {total_positions} / {global_limits['global_max_positions']}",
                    'limits': global_limits
                }
        
        return {
            'allowed': True,
            'reason': 'All risk checks passed',
            'limits': channel_limits
        }
    
    def _get_channel_limits(self, channel_id: str) -> Dict:
        """Get risk limits for a channel."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT max_daily_loss, max_positions, max_position_pct, 
                   circuit_breaker_enabled, order_timeout_minutes
            FROM channels WHERE channel_id = ?
        ''', (channel_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}
    
    def _get_global_limits(self) -> Dict:
        """Get global risk settings."""
        from gui_app.database import get_global_risk_settings
        return get_global_risk_settings()
    
    def _get_today_pnl(self, channel_id: str) -> float:
        """Get today's P&L for a channel with caching."""
        now = datetime.now()
        cached = self._pnl_cache.get(channel_id)
        
        if cached and (now - cached[1]).total_seconds() < self._cache_ttl:
            return cached[0]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        today = date.today().isoformat()
        cursor.execute('''
            SELECT COALESCE(SUM(pnl), 0) 
            FROM trades 
            WHERE channel_id = ? AND DATE(closed_at) = ?
        ''', (channel_id, today))
        result = cursor.fetchone()
        conn.close()
        
        pnl = result[0] if result else 0.0
        self._pnl_cache[channel_id] = (pnl, now)
        return pnl
    
    def _get_global_today_pnl(self) -> float:
        """Get total P&L across all channels for today."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        today = date.today().isoformat()
        cursor.execute('''
            SELECT COALESCE(SUM(pnl), 0) 
            FROM trades 
            WHERE DATE(closed_at) = ?
        ''', (today,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0.0
    
    def _get_open_position_count(self, channel_id: str) -> int:
        """Get count of open positions for a channel with caching."""
        now = datetime.now()
        cached = self._position_cache.get(channel_id)
        
        if cached and (now - cached[1]).total_seconds() < self._cache_ttl:
            return cached[0]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM signal_instances 
            WHERE channel_id = ? AND status = 'open'
        ''', (channel_id,))
        result = cursor.fetchone()
        conn.close()
        
        count = result[0] if result else 0
        self._position_cache[channel_id] = (count, now)
        return count
    
    def _get_total_position_count(self) -> int:
        """Get total open positions across all channels."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM signal_instances WHERE status = 'open'")
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else 0
    
    def invalidate_cache(self, channel_id: str = None):
        """Invalidate P&L and position cache."""
        if channel_id:
            self._pnl_cache.pop(channel_id, None)
            self._position_cache.pop(channel_id, None)
        else:
            self._pnl_cache.clear()
            self._position_cache.clear()


# Global instance
circuit_breaker = CircuitBreaker()
```

---

## PHASE 5: BROKER INTEGRATION LAYER

### File: `src/services/broker_integration.py` (NEW FILE)

```python
"""
Broker Integration Layer - Unified broker registration and capability discovery.

Provides:
- Centralized broker registration for all services
- Capability discovery for order modifications
- Rate limiting per broker
- Normalized API for order operations
"""

import asyncio
import logging
from typing import Dict, Optional, Any
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class BrokerIntegration:
    """
    Centralized broker management.
    
    Responsibilities:
    1. Register broker instances on startup
    2. Provide capability information to services
    3. Rate limit broker API calls
    4. Normalize order operation APIs
    """
    
    def __init__(self, db_path: str = 'bot_data.db'):
        self.db_path = db_path
        self._brokers = {}  # broker_name -> instance
        self._last_call = {}  # broker_name -> timestamp
        self._capabilities_cache = {}
        
    def register(self, name: str, broker_instance):
        """Register a broker instance."""
        name_lower = name.lower()
        self._brokers[name_lower] = broker_instance
        
        # Also register with SignalExitManager
        from src.services.signal_exit_manager import signal_exit_manager
        signal_exit_manager.register_broker(name, broker_instance)
        
        logger.info(f"[BrokerIntegration] Registered: {name}")
        
    def unregister(self, name: str):
        """Unregister a broker instance."""
        name_lower = name.lower()
        if name_lower in self._brokers:
            del self._brokers[name_lower]
            
            from src.services.signal_exit_manager import signal_exit_manager
            signal_exit_manager.unregister_broker(name)
            
            logger.info(f"[BrokerIntegration] Unregistered: {name}")
    
    def get_broker(self, name: str) -> Optional[Any]:
        """Get a registered broker instance."""
        return self._brokers.get(name.lower())
    
    def get_all_brokers(self) -> Dict[str, Any]:
        """Get all registered brokers."""
        return dict(self._brokers)
    
    def get_capabilities(self, name: str) -> Dict:
        """Get capabilities for a broker."""
        name_lower = name.lower()
        
        if name_lower in self._capabilities_cache:
            return self._capabilities_cache[name_lower]
        
        from gui_app.database import get_broker_capabilities
        caps = get_broker_capabilities(name_lower)
        self._capabilities_cache[name_lower] = caps
        return caps
    
    async def rate_limited_call(self, broker_name: str, coro):
        """Execute a broker call with rate limiting."""
        name_lower = broker_name.lower()
        caps = self.get_capabilities(name_lower)
        min_interval = caps.get('min_order_interval_ms', 100) / 1000
        
        # Wait if needed
        last = self._last_call.get(name_lower, 0)
        elapsed = time.time() - last
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        
        self._last_call[name_lower] = time.time()
        return await coro
    
    def can_modify_orders(self, broker_name: str) -> bool:
        """Check if broker supports order modification."""
        caps = self.get_capabilities(broker_name)
        return caps.get('can_modify_order', False) or caps.get('can_replace_order', False)
    
    def supports_bracket(self, broker_name: str) -> bool:
        """Check if broker supports bracket orders."""
        caps = self.get_capabilities(broker_name)
        return caps.get('supports_bracket', False)
    
    def supports_trailing_stop(self, broker_name: str) -> bool:
        """Check if broker supports native trailing stops."""
        caps = self.get_capabilities(broker_name)
        return caps.get('supports_trailing_stop', False)


# Global instance
broker_integration = BrokerIntegration()


def register_brokers_on_startup():
    """
    Call this function during bot startup to register all connected brokers.
    This should be called after broker instances are created.
    """
    # This function should be called from selfbot_webull.py after broker initialization
    # Example:
    # if webull_broker:
    #     broker_integration.register('webull', webull_broker)
    # if alpaca_broker:
    #     broker_integration.register('alpaca', alpaca_broker)
    pass
```

---

## PHASE 6: EVENT BUS & NOTIFICATIONS

### File: `src/services/event_bus.py` (NEW FILE)

```python
"""
Event Bus - Pub/Sub system for order lifecycle events.

Provides:
- Decoupled event publishing and subscription
- Async event handlers
- Event logging for audit
- Durable event queue (optional)
"""

import asyncio
import logging
from typing import Callable, Dict, List, Any
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import json

logger = logging.getLogger(__name__)


class EventType(Enum):
    # Order events
    ORDER_CREATED = 'order_created'
    ORDER_MODIFIED = 'order_modified'
    ORDER_CANCELLED = 'order_cancelled'
    ORDER_FILLED = 'order_filled'
    ORDER_REPLACED = 'order_replaced'
    ORDER_EXPIRED = 'order_expired'
    
    # Risk events
    SL_UPDATED = 'sl_updated'
    PT_HIT = 'pt_hit'
    TRAILING_ACTIVATED = 'trailing_activated'
    
    # Control events
    CIRCUIT_BREAKER_TRIGGERED = 'circuit_breaker_triggered'
    CIRCUIT_BREAKER_RESET = 'circuit_breaker_reset'
    DAILY_LIMIT_REACHED = 'daily_limit_reached'
    
    # Position events
    POSITION_OPENED = 'position_opened'
    POSITION_CLOSED = 'position_closed'
    POSITION_PARTIAL_CLOSE = 'position_partial_close'


@dataclass
class Event:
    type: EventType
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = 'system'
    
    def to_dict(self) -> Dict:
        return {
            'type': self.type.value,
            'data': self.data,
            'timestamp': self.timestamp.isoformat(),
            'source': self.source
        }


class EventBus:
    """
    Simple in-memory event bus with async support.
    
    Usage:
        # Subscribe
        event_bus.subscribe(EventType.ORDER_FILLED, my_handler)
        
        # Publish
        await event_bus.publish(Event(EventType.ORDER_FILLED, {'order_id': '123'}))
    """
    
    def __init__(self, persist_events: bool = True):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._persist_events = persist_events
        
    def subscribe(self, event_type: EventType, handler: Callable):
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug(f"[EventBus] Subscribed to {event_type.value}")
        
    def unsubscribe(self, event_type: EventType, handler: Callable):
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(handler)
            
    async def publish(self, event: Event):
        """Publish an event to all subscribers."""
        # Persist to database if enabled
        if self._persist_events:
            self._persist_event(event)
        
        # Notify subscribers
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"[EventBus] Handler error for {event.type.value}: {e}")
        
        logger.debug(f"[EventBus] Published {event.type.value} to {len(handlers)} handlers")
    
    def _persist_event(self, event: Event):
        """Persist event to risk_events table."""
        from gui_app.database import log_risk_event
        log_risk_event(
            event_type=event.type.value,
            channel_id=event.data.get('channel_id'),
            signal_instance_id=event.data.get('signal_instance_id'),
            order_state_id=event.data.get('order_state_id'),
            old_value=event.data.get('old_value'),
            new_value=event.data.get('new_value'),
            reason=event.data.get('reason'),
            metadata=event.data
        )


# Global instance
event_bus = EventBus()


# Register default handlers
def setup_default_handlers():
    """Set up default event handlers."""
    
    async def on_order_filled(event: Event):
        """Handle order filled events."""
        # Notify BrokerSyncService
        # Update P&L tracking
        logger.info(f"[EventBus] Order filled: {event.data}")
    
    async def on_sl_updated(event: Event):
        """Handle SL update events."""
        # Could notify UI via WebSocket
        logger.info(f"[EventBus] SL updated: {event.data}")
    
    async def on_circuit_breaker(event: Event):
        """Handle circuit breaker events."""
        # Send notification to user
        logger.warning(f"[EventBus] Circuit breaker: {event.data}")
    
    event_bus.subscribe(EventType.ORDER_FILLED, on_order_filled)
    event_bus.subscribe(EventType.SL_UPDATED, on_sl_updated)
    event_bus.subscribe(EventType.CIRCUIT_BREAKER_TRIGGERED, on_circuit_breaker)
```

---

## PHASE 7: API ROUTES

### File: `gui_app/routes.py` (ADD TO EXISTING)

Add these routes to the existing routes.py file:

```python
# ============================================================================
# RISK MANAGEMENT API ROUTES
# ============================================================================

from datetime import date, datetime

# ==================== RISK DASHBOARD ====================

@app.route('/risk')
@login_required
def risk_dashboard():
    """Risk dashboard page."""
    return render_template('risk_dashboard.html')


@app.route('/api/risk/dashboard', methods=['GET'])
@login_required
def get_risk_dashboard_data():
    """Get risk dashboard data."""
    from src.services.circuit_breaker import circuit_breaker
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Global status
    global_settings = get_global_risk_settings()
    global_status = {
        'trading_halted': global_settings.get('trading_halted', 0) == 1,
        'halt_reason': global_settings.get('halt_reason'),
        'halt_timestamp': global_settings.get('halt_timestamp')
    }
    
    # Channels with risk settings
    cursor.execute('''
        SELECT channel_id, channel_name, exit_strategy_mode, 
               stop_loss_pct, trailing_stop_pct, trailing_activation_pct,
               max_daily_loss, max_positions, max_position_pct,
               circuit_breaker_enabled
        FROM channels WHERE is_active = 1
    ''')
    channels = [dict(row) for row in cursor.fetchall()]
    
    # Get open positions per channel
    for ch in channels:
        cursor.execute('''
            SELECT COUNT(*) FROM signal_instances 
            WHERE channel_id = ? AND status = 'open'
        ''', (ch['channel_id'],))
        ch['open_positions'] = cursor.fetchone()[0]
        
        # Get today's P&L
        today = date.today().isoformat()
        cursor.execute('''
            SELECT COALESCE(SUM(pnl), 0) FROM trades 
            WHERE channel_id = ? AND DATE(closed_at) = ?
        ''', (ch['channel_id'], today))
        ch['today_pnl'] = cursor.fetchone()[0] or 0
    
    # Total stats
    today = date.today().isoformat()
    cursor.execute('''
        SELECT COALESCE(SUM(pnl), 0) as total_pnl, COUNT(*) as trade_count
        FROM trades WHERE DATE(closed_at) = ?
    ''', (today,))
    today_summary = dict(cursor.fetchone())
    
    cursor.execute("SELECT COUNT(*) FROM signal_instances WHERE status = 'open'")
    total_open_positions = cursor.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'global_status': global_status,
        'global_settings': {
            'daily_loss_limit': global_settings.get('global_daily_loss_limit'),
            'max_positions': global_settings.get('global_max_positions'),
            'order_timeout': global_settings.get('order_timeout_default_minutes')
        },
        'channels': channels,
        'today_pnl': today_summary['total_pnl'],
        'today_trades': today_summary['trade_count'],
        'open_positions': total_open_positions
    })


@app.route('/api/risk/circuit-breaker', methods=['POST'])
@login_required
def toggle_circuit_breaker():
    """Toggle circuit breaker (halt/resume trading)."""
    from src.services.circuit_breaker import circuit_breaker
    
    data = request.get_json()
    action = data.get('action')
    reason = data.get('reason', 'Manual toggle')
    
    if action == 'halt':
        circuit_breaker.halt_trading(reason)
        return jsonify({'success': True, 'status': 'halted', 'reason': reason})
    elif action == 'resume':
        circuit_breaker.resume_trading()
        return jsonify({'success': True, 'status': 'active'})
    else:
        return jsonify({'success': False, 'error': 'Invalid action'}), 400


@app.route('/api/risk/limits/global', methods=['GET', 'PUT'])
@login_required
def global_risk_limits():
    """Get or update global risk limits."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if request.method == 'GET':
        return jsonify(get_global_risk_settings())
    
    else:  # PUT
        data = request.get_json()
        updates = []
        params = []
        
        fields = ['global_daily_loss_limit', 'global_max_positions', 
                  'order_timeout_default_minutes', 'enable_stale_quote_protection',
                  'stale_quote_threshold_seconds']
        
        for field in fields:
            if field in data:
                updates.append(f'{field} = ?')
                params.append(data[field])
        
        if updates:
            updates.append('updated_at = CURRENT_TIMESTAMP')
            cursor.execute(f'''
                UPDATE global_risk_settings SET {', '.join(updates)}
                WHERE id = 1
            ''', params)
            conn.commit()
        
        conn.close()
        return jsonify({'success': True})


@app.route('/api/risk/limits/<channel_id>', methods=['GET', 'PUT'])
@login_required
def channel_risk_limits(channel_id):
    """Get or update channel risk limits."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if request.method == 'GET':
        cursor.execute('''
            SELECT max_daily_loss, max_positions, max_position_pct,
                   order_timeout_minutes, circuit_breaker_enabled,
                   stop_loss_type, stop_loss_pct, stop_loss_fixed,
                   trailing_stop_pct, trailing_activation_pct,
                   exit_strategy_mode
            FROM channels WHERE channel_id = ?
        ''', (channel_id,))
        row = cursor.fetchone()
        conn.close()
        return jsonify(dict(row) if row else {})
    
    else:  # PUT
        data = request.get_json()
        updates = []
        params = []
        
        fields = ['max_daily_loss', 'max_positions', 'max_position_pct',
                  'order_timeout_minutes', 'circuit_breaker_enabled',
                  'stop_loss_type', 'stop_loss_pct', 'stop_loss_fixed',
                  'trailing_stop_pct', 'trailing_activation_pct',
                  'exit_strategy_mode']
        
        for field in fields:
            if field in data:
                updates.append(f'{field} = ?')
                params.append(data[field])
        
        if updates:
            params.append(channel_id)
            cursor.execute(f'''
                UPDATE channels SET {', '.join(updates)}
                WHERE channel_id = ?
            ''', params)
            conn.commit()
        
        conn.close()
        return jsonify({'success': True})


@app.route('/api/risk/events', methods=['GET'])
@login_required
def get_risk_events():
    """Get recent risk events (audit log)."""
    limit = request.args.get('limit', 100, type=int)
    event_type = request.args.get('type')
    channel_id = request.args.get('channel_id')
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = 'SELECT * FROM risk_events WHERE 1=1'
    params = []
    
    if event_type:
        query += ' AND event_type = ?'
        params.append(event_type)
    if channel_id:
        query += ' AND channel_id = ?'
        params.append(channel_id)
    
    query += ' ORDER BY created_at DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify(events)


# ==================== BROKER CAPABILITIES ====================

@app.route('/api/brokers/capabilities', methods=['GET'])
@login_required
def get_all_broker_capabilities():
    """Get capabilities for all brokers."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM broker_capabilities')
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route('/api/brokers/capabilities/<broker>', methods=['GET'])
@login_required
def get_single_broker_capabilities(broker):
    """Get capabilities for a specific broker."""
    caps = get_broker_capabilities(broker.lower())
    return jsonify(caps)


# ==================== ORDER STATES ====================

@app.route('/api/orders/states', methods=['GET'])
@login_required
def get_order_states():
    """Get order states for debugging/monitoring."""
    signal_instance_id = request.args.get('signal_instance_id', type=int)
    status = request.args.get('status')
    limit = request.args.get('limit', 100, type=int)
    
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = 'SELECT * FROM order_states WHERE 1=1'
    params = []
    
    if signal_instance_id:
        query += ' AND signal_instance_id = ?'
        params.append(signal_instance_id)
    if status:
        query += ' AND status = ?'
        params.append(status)
    
    query += ' ORDER BY id DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    states = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify(states)


# ==================== HELP CENTER ====================

@app.route('/help')
def help_center():
    """Help center page."""
    return render_template('help.html')


@app.route('/api/help/topics', methods=['GET'])
def get_help_topics():
    """Get help topics structure."""
    topics = {
        'getting_started': {
            'title': 'Getting Started',
            'icon': '🚀',
            'sections': [
                {'id': 'quick-start', 'title': 'Quick Start Guide'},
                {'id': 'connect-broker', 'title': 'Connect Your Broker'},
                {'id': 'add-channel', 'title': 'Add Your First Channel'},
                {'id': 'first-trade', 'title': 'Your First Trade'}
            ]
        },
        'risk_management': {
            'title': 'Risk Management',
            'icon': '🛡️',
            'sections': [
                {'id': 'exit-strategies', 'title': 'Exit Strategy Modes'},
                {'id': 'stop-loss', 'title': 'Stop Loss Configuration'},
                {'id': 'trailing-stops', 'title': 'Trailing Stops'},
                {'id': 'profit-targets', 'title': 'Profit Targets'},
                {'id': 'position-sizing', 'title': 'Position Sizing'},
                {'id': 'circuit-breaker', 'title': 'Circuit Breaker & Kill Switch'},
                {'id': 'daily-limits', 'title': 'Daily Loss Limits'}
            ]
        },
        'order_types': {
            'title': 'Order Types',
            'icon': '📊',
            'sections': [
                {'id': 'market-limit', 'title': 'Market vs Limit Orders'},
                {'id': 'bracket-orders', 'title': 'Bracket Orders'},
                {'id': 'conditional', 'title': 'Conditional Orders'},
                {'id': 'timeouts', 'title': 'Order Timeouts'},
                {'id': 'extended-hours', 'title': 'Extended Hours Trading'}
            ]
        },
        'brokers': {
            'title': 'Broker Guides',
            'icon': '🔌',
            'sections': [
                {'id': 'alpaca', 'title': 'Alpaca'},
                {'id': 'robinhood', 'title': 'Robinhood'},
                {'id': 'schwab', 'title': 'Charles Schwab'},
                {'id': 'ibkr', 'title': 'Interactive Brokers'},
                {'id': 'tastytrade', 'title': 'Tastytrade'},
                {'id': 'webull', 'title': 'Webull'}
            ]
        },
        'signals': {
            'title': 'Signal Channels',
            'icon': '📡',
            'sections': [
                {'id': 'discord-setup', 'title': 'Discord Setup'},
                {'id': 'telegram-setup', 'title': 'Telegram Setup'},
                {'id': 'signal-formats', 'title': 'Supported Signal Formats'},
                {'id': 'c1apped', 'title': 'C1apped / TRADE IDEA Format'},
                {'id': 'per-channel', 'title': 'Per-Channel Settings'}
            ]
        },
        'pnl': {
            'title': 'P&L Tracking',
            'icon': '📈',
            'sections': [
                {'id': 'signal-pnl', 'title': 'Signal P&L'},
                {'id': 'execution-pnl', 'title': 'Execution P&L'},
                {'id': 'slippage', 'title': 'Slippage Tracking'},
                {'id': 'performance', 'title': 'Performance Metrics'}
            ]
        }
    }
    return jsonify(topics)


@app.route('/api/help/content/<topic_id>/<section_id>', methods=['GET'])
def get_help_content(topic_id, section_id):
    """Get help content for a specific section."""
    # Help content - could be stored in files or database
    content = HELP_CONTENT.get(f"{topic_id}/{section_id}", 
                               "<p>Content coming soon...</p>")
    return jsonify({'content': content})


# Help content dictionary (could be moved to files)
HELP_CONTENT = {
    'getting_started/quick-start': '''
        <h1>🚀 Quick Start Guide</h1>
        <p>Get your trading bot running in 4 simple steps:</p>
        <div class="steps">
            <div class="step">
                <h3>Step 1: Connect Your Broker</h3>
                <p>Go to the Brokers page and add your brokerage credentials.</p>
            </div>
            <div class="step">
                <h3>Step 2: Add Signal Channels</h3>
                <p>Configure Discord or Telegram channels you want to copy trades from.</p>
            </div>
            <div class="step">
                <h3>Step 3: Set Risk Limits</h3>
                <p>Configure stop loss, profit targets, and daily limits.</p>
            </div>
            <div class="step">
                <h3>Step 4: Enable & Trade</h3>
                <p>Turn on your channels and monitor on the Risk Dashboard.</p>
            </div>
        </div>
    ''',
    'risk_management/exit-strategies': '''
        <h1>🛡️ Exit Strategy Modes</h1>
        <p>Each channel can use one of three exit strategies:</p>
        
        <h2>Signal Mode</h2>
        <p>Follow the trader's exact stop loss and profit targets. When they update their stops, your stops update too.</p>
        <div class="info-box">Best for: Traders you trust completely</div>
        
        <h2>Risk Mode</h2>
        <p>Use your own automated risk management. Set your own stop loss percentage, trailing stops, and profit targets.</p>
        <div class="info-box">Best for: Consistent risk management across all signals</div>
        
        <h2>Hybrid Mode</h2>
        <p>Both are active. The tightest protection wins.</p>
        <ul>
            <li>If trader raises SL to $1.15 and your trailing is at $1.12 → Uses $1.15</li>
            <li>If trader's SL is $1.03 but your trailing moves to $1.10 → Uses $1.10</li>
        </ul>
        <div class="warning-box">In Hybrid mode, stops can only move UP (tighter), never down.</div>
    ''',
    'risk_management/circuit-breaker': '''
        <h1>🔴 Circuit Breaker & Kill Switch</h1>
        <p>Emergency controls to protect your account.</p>
        
        <h2>Kill Switch</h2>
        <p>Instantly halt ALL trading across all channels. Use this in emergencies.</p>
        <div class="warning-box">The Kill Switch will attempt to cancel all open orders when activated.</div>
        
        <h2>Daily Loss Limit</h2>
        <p>Automatically stops trading when your daily losses exceed a threshold.</p>
        <ul>
            <li><strong>Global Limit:</strong> Applies across all channels</li>
            <li><strong>Per-Channel Limit:</strong> Set different limits for each channel</li>
        </ul>
        
        <h2>Position Limits</h2>
        <p>Limit the number of concurrent positions:</p>
        <ul>
            <li><strong>Global Max:</strong> Total positions across all channels</li>
            <li><strong>Per-Channel Max:</strong> Positions per individual channel</li>
        </ul>
    '''
}
```

---

## SUMMARY: FILES TO CREATE/MODIFY

### New Files to Create

| File | Description |
|------|-------------|
| `src/services/signal_exit_manager.py` | Dynamic SL/PT management with debouncing |
| `src/services/exit_order_arbiter.py` | Centralized exit decision making |
| `src/services/circuit_breaker.py` | Global risk controls & kill switch |
| `src/services/broker_integration.py` | Unified broker registration |
| `src/services/event_bus.py` | Pub/Sub for order events |
| `gui_app/templates/risk_dashboard.html` | Risk overview page |
| `gui_app/templates/help.html` | Help center |
| `help/` directory | Markdown help content files |

### Files to Modify

| File | Changes |
|------|---------|
| `gui_app/database.py` | New tables, columns, helper functions |
| `gui_app/routes.py` | New API endpoints for risk management |
| `gui_app/templates/base.html` | Add Risk & Help to navigation |
| `gui_app/templates/channels.html` | Enhanced risk settings UI |
| `src/selfbot_webull.py` | Integration with new services |

### Database Changes

| Table | Type | Description |
|-------|------|-------------|
| `channels` | MODIFY | Add risk limit columns |
| `signal_instances` | MODIFY | Add order tracking columns |
| `order_states` | NEW | Track order lifecycle |
| `risk_limits` | NEW | Store risk limits |
| `risk_events` | NEW | Audit log |
| `broker_capabilities` | NEW | Broker feature flags |
| `global_risk_settings` | NEW | Global settings & circuit breaker |
| `order_update_queue` | NEW | Debounce queue |

---

## TESTING STRATEGY

### Unit Tests

```python
# tests/test_signal_exit_manager.py
# tests/test_exit_order_arbiter.py
# tests/test_circuit_breaker.py
```

### Integration Tests

1. **Broker Cancel/Replace Flow**
   - Test with mock broker
   - Test timeout handling
   - Test retry logic

2. **Hybrid Mode Precedence**
   - Signal raises SL → should update
   - Signal lowers SL → should reject
   - Trailing raises SL → should update

3. **Circuit Breaker**
   - Daily limit breach → halt
   - Kill switch → cancel orders
   - Resume → allow trades

### Paper Trading Validation

1. Enable paper trading for 1 channel
2. Run for 24 hours with test signals
3. Verify:
   - SL updates propagate to broker
   - Circuit breaker triggers correctly
   - P&L tracking is accurate
   - No orphaned orders

---

## DEPLOYMENT CHECKLIST

- [ ] Run database migrations
- [ ] Test with paper trading only
- [ ] Enable feature flags
- [ ] Monitor logs for errors
- [ ] Verify P&L calculations
- [ ] Test circuit breaker manually
- [ ] Document rollback procedure
- [ ] Enable for 1 live channel
- [ ] Monitor for 24 hours
- [ ] Gradual rollout to all channels

---

## ROLLBACK PLAN

If issues discovered:

1. **Immediate:** Use kill switch to halt trading
2. **Revert code:** Deploy previous version
3. **Database:** New tables are additive, no data loss
4. **Channels:** Reset to `exit_strategy_mode='signal'` (original behavior)

---

*Generated: January 12, 2026*
*Version: 1.0*
*Author: BotifyTrades Development Team*
