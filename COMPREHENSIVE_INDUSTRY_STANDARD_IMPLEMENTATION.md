# 🏗️ BotifyTrades: Comprehensive Industry-Standard Implementation Plan

## Complete Gap Analysis & Remediation for WaxUI, C1apped, Risk Management & Conditional Orders

---

## TABLE OF CONTENTS

1. [Executive Summary](#executive-summary)
2. [Gap Analysis by Component](#gap-analysis-by-component)
3. [Phase 1: Database Schema](#phase-1-database-schema)
4. [Phase 2: Core Services](#phase-2-core-services)
5. [Phase 3: Risk Management](#phase-3-risk-management)
6. [Phase 4: C1apped/TRADE IDEA Enhancement](#phase-4-c1appedtrade-idea-enhancement)
7. [Phase 5: Conditional Orders V2](#phase-5-conditional-orders-v2)
8. [Phase 6: WaxUI Component Library](#phase-6-waxui-component-library)
9. [Phase 7: API Routes](#phase-7-api-routes)
10. [Phase 8: UI Templates](#phase-8-ui-templates)
11. [Phase 9: Workflow Integration](#phase-9-workflow-integration)
12. [Phase 10: Testing & Rollout](#phase-10-testing--rollout)
13. [File Reference Matrix](#file-reference-matrix)
14. [Implementation Code](#implementation-code)

---

## EXECUTIVE SUMMARY

### Current State vs Industry Standard

| Component | Current State | Industry Standard | Gap Severity |
|-----------|---------------|-------------------|--------------|
| **WaxUI** | Static fragments, no component registry | Modular components with theming | 🟡 Medium |
| **C1apped Parser** | Strikethrough fixed, no state machine | Full OMS with order tracking | 🔴 Critical |
| **Risk Management** | Basic per-channel settings | Circuit breaker, limits, arbiter | 🔴 Critical |
| **Conditional Orders** | Basic trigger monitoring | Resilient polling, risk integration | 🟠 High |
| **Exit Strategy** | Inconsistent modes | Centralized arbiter with precedence | 🔴 Critical |
| **Order Tracking** | No broker order IDs | Full lifecycle state machine | 🔴 Critical |
| **P&L Reconciliation** | Signal-based only | Execution-based with slippage | 🟠 High |
| **Audit Trail** | Minimal logging | Full event log with replay | 🟡 Medium |

### Implementation Timeline

| Phase | Duration | Priority | Breaking Risk |
|-------|----------|----------|---------------|
| Phase 1: Database Schema | 1 day | P0 | Low (additive) |
| Phase 2: Core Services | 2 days | P0 | Medium (feature flag) |
| Phase 3: Risk Management | 1.5 days | P0 | Low (additive) |
| Phase 4: C1apped Enhancement | 1.5 days | P0 | Medium (feature flag) |
| Phase 5: Conditional Orders V2 | 1 day | P1 | Medium (feature flag) |
| Phase 6: WaxUI | 2 days | P2 | Low (additive) |
| Phase 7: API Routes | 1 day | P1 | Low (additive) |
| Phase 8: UI Templates | 2 days | P1 | Low (additive) |
| Phase 9: Integration | 1 day | P0 | Medium |
| Phase 10: Testing | 2 days | P0 | None |

**Total: ~15 days**

### Feature Flags for Safe Rollout

```python
FEATURE_FLAGS = {
    'enable_signal_exit_manager': False,  # Phase 2
    'enable_exit_arbiter': False,         # Phase 2
    'enable_circuit_breaker': True,       # Phase 3 (safe to enable)
    'enable_conditional_v2': False,       # Phase 5
    'enable_waxui': False,                # Phase 6
    'enable_event_bus': False,            # Phase 9
}
```

---

## GAP ANALYSIS BY COMPONENT

### 1. WaxUI

**Current State:**
- Static HTML fragments included directly in templates
- No component registry or macro system
- Inconsistent styling across pages
- No theming tokens (colors, spacing, fonts)
- No JS event binding system

**Gaps Identified:**
| Gap | Impact | Implementation Needed |
|-----|--------|----------------------|
| No component registry | Code duplication | Create `/src/gui/waxui/components.py` |
| No theming tokens | Inconsistent look | Create `/gui_app/static/css/tokens.css` |
| No responsive layouts | Mobile issues | Add responsive mixins |
| No error state handling | Poor UX | Add error/loading states to components |
| No form validation | Data issues | Add JS validation layer |

**Files to Create/Modify:**
```
gui_app/
├── templates/
│   ├── partials/
│   │   ├── waxui/
│   │   │   ├── button.html
│   │   │   ├── card.html
│   │   │   ├── form_input.html
│   │   │   ├── modal.html
│   │   │   ├── table.html
│   │   │   ├── toggle.html
│   │   │   └── tooltip.html
│   │   └── _macros.html
│   └── components/
│       ├── risk_settings_card.html
│       ├── channel_row.html
│       └── order_state_badge.html
├── static/
│   ├── css/
│   │   ├── tokens.css
│   │   └── waxui.css
│   └── js/
│       ├── waxui.js
│       └── event_bus.js
```

---

### 2. C1apped/TRADE IDEA Signal Handling

**Current State:**
- Parser handles strikethrough detection (recently fixed)
- Extracts SL/PT from TRADE IDEA format
- Converts to stock signal format
- Direct execution without state machine

**Gaps Identified:**
| Gap | Impact | Implementation Needed |
|-----|--------|----------------------|
| No order ID tracking | Can't modify orders | Add to signal_instances |
| No debouncing | API rate limit issues | Add 100ms debounce queue |
| No exit reconciliation | Partial fills lost | Track per-leg fills |
| No hybrid mode | Competing exits | ExitOrderArbiter |
| No update propagation | SL changes lost | SignalExitManager |
| No "trim" handling | Manual close needed | Parse trim percentages |

**Signal Flow (Current vs Target):**

```
CURRENT FLOW:
Signal → Parser → Execute → (done)
                    ↓
            (no tracking of broker orders)

TARGET FLOW:
Signal → Parser → RiskGate → SignalExitManager → Broker
                     ↓              ↓                ↓
              CircuitBreaker   OrderStates     EventBus
                     ↓              ↓                ↓
              DailyLimits    ExitArbiter     P&L Tracker
```

**Files Affected:**
```
src/
├── signals/
│   └── parser.py              # Add trim parsing, exit detection
├── services/
│   ├── signal_exit_manager.py # NEW: Order lifecycle manager
│   ├── exit_order_arbiter.py  # NEW: Precedence rules
│   └── broker_integration.py  # NEW: Unified broker registry
└── selfbot_webull.py          # Integration points
```

---

### 3. Risk Management

**Current State:**
- Per-channel: stop_loss_pct, profit_target_pct, trailing_stop_pct
- Global: slippage_settings, risk_management_settings, trading_settings
- Exit strategy mode stored but inconsistently enforced
- No circuit breaker or kill switch
- No daily loss limits

**Gaps Identified:**
| Gap | Impact | Implementation Needed |
|-----|--------|----------------------|
| No kill switch | Can't stop in emergency | global_risk_settings table |
| No daily loss limit | Unlimited losses | Add to channels + global |
| No position limits | Over-exposure | max_positions column |
| Inconsistent exit modes | Competing logic | Centralized arbiter |
| No order timeout | Hung orders | timeout_at column |
| No risk event logging | No audit trail | risk_events table |
| No broker capabilities | Wrong UI options | broker_capabilities table |

**Database Tables Needed:**
```sql
-- New tables
order_states          -- Track order lifecycle
risk_limits           -- Per-scope limits
risk_events           -- Audit log
broker_capabilities   -- Broker feature flags
global_risk_settings  -- Circuit breaker + global limits
order_update_queue    -- Debounce queue

-- Modified tables
channels              -- Add: max_daily_loss, max_positions, order_timeout_minutes, 
                      --      circuit_breaker_enabled, stop_loss_type, stop_loss_fixed
signal_instances      -- Add: sl_order_id, pt_order_ids, current_sl_price, 
                      --      remaining_qty, exit_strategy_mode, broker
```

---

### 4. Conditional Orders

**Current State:**
- Basic trigger monitoring in `src/services/conditional_orders`
- Handles "over/above" and "under/below" triggers
- Three-tier price monitoring fallback
- No integration with new risk system

**Gaps Identified:**
| Gap | Impact | Implementation Needed |
|-----|--------|----------------------|
| No risk gate check | Trades bypass limits | Integrate with CircuitBreaker |
| No hybrid exit | Conflicting orders | Route through ExitArbiter |
| Fragile price polling | Missed triggers | Add retry + fallback |
| No trigger registry | Hard to track | Centralized trigger store |
| No condition timeout | Stale triggers | Add expiry mechanism |
| No partial fill handling | Qty mismatch | Track remaining qty |

**Files Affected:**
```
src/services/
├── conditional_orders.py      # Enhance with risk integration
├── conditional_trigger_registry.py  # NEW: Centralized registry
└── price_monitor.py           # NEW: Resilient price polling
```

---

### 5. Routes & API

**Current State:**
- `/api/settings/risk_management` - Basic global settings
- `/api/channels/<id>` - Channel CRUD
- `/api/trades/<id>/risk-settings` - Per-trade settings
- No circuit breaker endpoints
- No order state queries
- No audit export

**Gaps Identified:**
| Gap | Impact | Implementation Needed |
|-----|--------|----------------------|
| No circuit breaker API | Can't halt via UI | POST /api/risk/circuit-breaker |
| No risk dashboard API | No overview | GET /api/risk/dashboard |
| No order states API | No debugging | GET /api/order-states |
| No risk events API | No audit | GET /api/risk/events |
| No broker caps API | UI can't adapt | GET /api/brokers/capabilities |
| No help content API | No documentation | GET /api/help/* |

**New Endpoints:**
```python
# Risk Management
GET  /api/risk/dashboard           # Dashboard data
POST /api/risk/circuit-breaker     # Toggle kill switch
GET  /api/risk/limits/global       # Global limits
PUT  /api/risk/limits/global       # Update global limits
GET  /api/risk/limits/<channel>    # Channel limits
PUT  /api/risk/limits/<channel>    # Update channel limits
GET  /api/risk/events              # Audit log

# Order States
GET  /api/order-states             # Query order states
GET  /api/order-states/<id>        # Single order state

# Broker Capabilities
GET  /api/brokers/capabilities     # All brokers
GET  /api/brokers/capabilities/<b> # Single broker

# Conditional Orders V2
GET  /api/conditional/triggers     # Active triggers
POST /api/conditional/triggers     # Create trigger
DELETE /api/conditional/triggers/<id>  # Cancel trigger

# Help Center
GET  /api/help/topics              # Topic structure
GET  /api/help/content/<t>/<s>     # Section content
```

---

### 6. UI Templates

**Current Templates:**
- `channels.html` - Channel management
- `channels_india.html` - India markets
- `channels_canada.html` - Canada markets
- `settings.html` - Global settings
- `execution.html` - Execution settings
- `pnl_tracker.html` - P&L tracking
- `telegram.html` - Telegram channels

**Gaps Identified:**
| Gap | Impact | Implementation Needed |
|-----|--------|----------------------|
| No risk dashboard | No overview | risk_dashboard.html |
| No help center | No documentation | help.html |
| Scattered risk settings | Confusing UX | Consolidate in channels |
| No broker capability UI | Wrong options shown | Conditional rendering |
| No order states view | No debugging | order_states.html |
| Inconsistent styling | Poor UX | WaxUI components |

**New Templates:**
```
gui_app/templates/
├── risk_dashboard.html    # NEW: Risk overview + kill switch
├── help.html              # NEW: Help center
├── order_states.html      # NEW: Order debugging (admin)
└── onboarding/
    ├── welcome.html       # NEW: First-time setup
    ├── connect_broker.html
    ├── add_channel.html
    └── configure_risk.html
```

---

### 7. Workflow Integration

**Current Flow:**
```
Discord/Telegram → Parser → Execute → Store Trade
                              ↓
                    (no lifecycle management)
```

**Target Flow:**
```
Discord/Telegram
      ↓
   Parser (extract signal data)
      ↓
   RiskGate (circuit breaker, limits)
      ↓
   SignalExitManager (create/update orders)
      ↓
   ExitOrderArbiter (precedence rules)
      ↓
   BrokerIntegration (rate limit, execute)
      ↓
   EventBus (publish events)
      ↓
   ┌─────────────────────────────┐
   │ Subscribers:                │
   │ - OrderStates (persistence) │
   │ - P&L Tracker (reconcile)   │
   │ - RiskMonitor (limits)      │
   │ - UI (WebSocket/polling)    │
   └─────────────────────────────┘
```

---

## PHASE 1: DATABASE SCHEMA

### File: `gui_app/database.py`

Add after existing migrations:

```python
# ============================================================================
# INDUSTRY-STANDARD OMS/RMS SCHEMA UPDATES
# ============================================================================

def migrate_oms_rms_schema(cursor):
    """Migrate database to support industry-grade OMS/RMS."""
    
    # ---- 1. CHANNELS TABLE EXTENSIONS ----
    channel_columns = [
        ('max_daily_loss', 'REAL DEFAULT NULL'),
        ('max_positions', 'INTEGER DEFAULT 10'),
        ('max_position_pct', 'REAL DEFAULT 25.0'),
        ('order_timeout_minutes', 'INTEGER DEFAULT 5'),
        ('circuit_breaker_enabled', 'INTEGER DEFAULT 1'),
        ('stop_loss_type', "TEXT DEFAULT 'percentage'"),
        ('stop_loss_fixed', 'REAL DEFAULT NULL'),
    ]
    
    for col_name, col_def in channel_columns:
        try:
            cursor.execute(f'SELECT {col_name} FROM channels LIMIT 1')
        except:
            cursor.execute(f'ALTER TABLE channels ADD COLUMN {col_name} {col_def}')
            print(f"[DATABASE] ✓ Added {col_name} to channels")
    
    # ---- 2. SIGNAL_INSTANCES TABLE EXTENSIONS ----
    signal_columns = [
        ('sl_order_id', 'TEXT DEFAULT NULL'),
        ('pt_order_ids', 'TEXT DEFAULT NULL'),
        ('current_sl_price', 'REAL DEFAULT NULL'),
        ('filled_pt_levels', 'TEXT DEFAULT NULL'),
        ('remaining_qty', 'INTEGER DEFAULT NULL'),
        ('exit_strategy_mode', 'TEXT DEFAULT NULL'),
        ('broker', 'TEXT DEFAULT NULL'),
    ]
    
    for col_name, col_def in signal_columns:
        try:
            cursor.execute(f'SELECT {col_name} FROM signal_instances LIMIT 1')
        except:
            cursor.execute(f'ALTER TABLE signal_instances ADD COLUMN {col_name} {col_def}')
            print(f"[DATABASE] ✓ Added {col_name} to signal_instances")
    
    # ---- 3. ORDER_STATES TABLE ----
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
    
    # ---- 4. RISK_LIMITS TABLE ----
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
    
    # ---- 5. RISK_EVENTS TABLE ----
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
    
    # ---- 6. BROKER_CAPABILITIES TABLE ----
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
    
    broker_caps = [
        ('alpaca', 0, 1, 1, 1, 0, 1, 90, 10, 100),
        ('robinhood', 0, 0, 1, 1, 0, 1, 90, 5, 200),
        ('schwab', 0, 1, 1, 1, 1, 1, 60, 5, 200),
        ('ibkr', 1, 1, 1, 1, 1, 1, 90, 20, 50),
        ('tastytrade', 0, 0, 0, 1, 0, 1, 90, 5, 200),
        ('webull', 0, 0, 0, 0, 0, 1, 90, 5, 300),
        ('questrade', 0, 0, 0, 0, 0, 1, 90, 5, 200),
        ('dhanq', 0, 0, 0, 0, 0, 0, 90, 5, 300),
        ('upstox', 0, 0, 0, 0, 0, 0, 90, 5, 200),
        ('zerodha', 0, 0, 0, 0, 0, 0, 90, 5, 200),
    ]
    for cap in broker_caps:
        cursor.execute('''
            INSERT OR IGNORE INTO broker_capabilities 
            (broker, can_modify_order, can_replace_order, supports_bracket, supports_oco, 
             supports_trailing_stop, supports_extended_hours, max_gtc_days, 
             rate_limit_per_second, min_order_interval_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', cap)
    print("[DATABASE] ✓ Created broker_capabilities table")
    
    # ---- 7. GLOBAL_RISK_SETTINGS TABLE ----
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
    
    # ---- 8. ORDER_UPDATE_QUEUE TABLE ----
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
    
    # ---- 9. CONDITIONAL_TRIGGERS TABLE ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS conditional_triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            signal_instance_id INTEGER,
            ticker TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            trigger_price REAL NOT NULL,
            action TEXT NOT NULL,
            quantity INTEGER,
            stop_loss REAL,
            profit_target REAL,
            status TEXT DEFAULT 'pending',
            expires_at TIMESTAMP,
            triggered_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT,
            FOREIGN KEY (signal_instance_id) REFERENCES signal_instances(id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cond_triggers_status ON conditional_triggers(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cond_triggers_ticker ON conditional_triggers(ticker)')
    print("[DATABASE] ✓ Created conditional_triggers table")
    
    # ---- 10. FEATURE_FLAGS TABLE ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feature_flags (
            flag_name TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    default_flags = [
        ('enable_signal_exit_manager', 0, 'Enable SignalExitManager for order lifecycle'),
        ('enable_exit_arbiter', 0, 'Enable ExitOrderArbiter for precedence rules'),
        ('enable_circuit_breaker', 1, 'Enable circuit breaker and kill switch'),
        ('enable_conditional_v2', 0, 'Enable Conditional Orders V2'),
        ('enable_waxui', 0, 'Enable WaxUI component library'),
        ('enable_event_bus', 0, 'Enable event bus for order events'),
    ]
    for flag in default_flags:
        cursor.execute('''
            INSERT OR IGNORE INTO feature_flags (flag_name, enabled, description)
            VALUES (?, ?, ?)
        ''', flag)
    print("[DATABASE] ✓ Created feature_flags table")


# Add to init_db() function:
# migrate_oms_rms_schema(cursor)
```

### Database Helper Functions

```python
# ============================================================================
# OMS/RMS DATABASE HELPER FUNCTIONS
# ============================================================================

def get_feature_flag(flag_name: str) -> bool:
    """Check if a feature flag is enabled."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT enabled FROM feature_flags WHERE flag_name = ?', (flag_name,))
    row = cursor.fetchone()
    conn.close()
    return row[0] == 1 if row else False


def set_feature_flag(flag_name: str, enabled: bool):
    """Set a feature flag."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE feature_flags SET enabled = ?, updated_at = CURRENT_TIMESTAMP
        WHERE flag_name = ?
    ''', (1 if enabled else 0, flag_name))
    conn.commit()
    conn.close()


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


def update_order_state(order_id: int, **kwargs) -> bool:
    """Update an order state record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    updates = ['updated_at = CURRENT_TIMESTAMP']
    params = []
    
    valid_fields = ['status', 'current_price', 'filled_quantity', 'cancel_reason', 'replaced_by_id']
    for field in valid_fields:
        if field in kwargs and kwargs[field] is not None:
            updates.append(f'{field} = ?')
            params.append(kwargs[field])
    
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


def log_risk_event(event_type: str, **kwargs):
    """Log a risk event for audit trail."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO risk_events 
        (event_type, channel_id, signal_instance_id, order_state_id, 
         old_value, new_value, reason, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        event_type,
        kwargs.get('channel_id'),
        kwargs.get('signal_instance_id'),
        kwargs.get('order_state_id'),
        kwargs.get('old_value'),
        kwargs.get('new_value'),
        kwargs.get('reason'),
        json.dumps(kwargs.get('metadata')) if kwargs.get('metadata') else None
    ))
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


def create_conditional_trigger(channel_id: str, ticker: str, trigger_type: str,
                                trigger_price: float, action: str, quantity: int,
                                stop_loss: float = None, profit_target: float = None,
                                expires_hours: int = 24) -> int:
    """Create a new conditional trigger."""
    conn = get_db_connection()
    cursor = conn.cursor()
    expires_at = datetime.now() + timedelta(hours=expires_hours)
    cursor.execute('''
        INSERT INTO conditional_triggers 
        (channel_id, ticker, trigger_type, trigger_price, action, quantity,
         stop_loss, profit_target, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (channel_id, ticker, trigger_type, trigger_price, action, quantity,
          stop_loss, profit_target, expires_at))
    conn.commit()
    trigger_id = cursor.lastrowid
    conn.close()
    return trigger_id


def get_active_conditional_triggers(ticker: str = None) -> List[Dict]:
    """Get active conditional triggers, optionally filtered by ticker."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if ticker:
        cursor.execute('''
            SELECT * FROM conditional_triggers 
            WHERE status = 'pending' AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            AND ticker = ?
        ''', (ticker,))
    else:
        cursor.execute('''
            SELECT * FROM conditional_triggers 
            WHERE status = 'pending' AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        ''')
    
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
```

---

## PHASE 2: CORE SERVICES

### File: `src/services/signal_exit_manager.py`

See the complete implementation in [INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md](./INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md)

Key features:
- Order lifecycle management
- 100ms debounce queue for rapid updates
- Broker-agnostic order modification (replace or cancel+recreate)
- 30s operation timeout with 3 retry attempts
- Event logging for audit trail

### File: `src/services/exit_order_arbiter.py`

See the complete implementation in [INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md](./INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md)

Key features:
- Precedence rules for hybrid mode
- Thread-safe per-signal locking
- SL can only move UP (tighter) in hybrid mode
- Manual override has highest priority
- Trader exit always wins

### File: `src/services/circuit_breaker.py`

See the complete implementation in [INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md](./INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md)

Key features:
- Global kill switch
- Per-channel daily loss limits
- Global daily loss limit with auto-halt
- Max position limits
- P&L caching with 30s TTL

### File: `src/services/broker_integration.py`

See the complete implementation in [INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md](./INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md)

Key features:
- Centralized broker registration
- Capability discovery
- Rate limiting per broker
- Normalized order API

### File: `src/services/event_bus.py`

See the complete implementation in [INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md](./INDUSTRY_GRADE_RISK_MANAGEMENT_PLAN.md)

Key features:
- Pub/sub for order lifecycle events
- Async event handlers
- Event persistence to risk_events table
- Default handlers for common events

---

## FILE REFERENCE MATRIX

### New Files to Create

| Path | Description | Phase |
|------|-------------|-------|
| `src/services/signal_exit_manager.py` | Order lifecycle manager | 2 |
| `src/services/exit_order_arbiter.py` | Exit precedence rules | 2 |
| `src/services/circuit_breaker.py` | Kill switch & limits | 3 |
| `src/services/broker_integration.py` | Broker registry | 2 |
| `src/services/event_bus.py` | Pub/sub events | 9 |
| `src/services/conditional_trigger_registry.py` | Trigger tracking | 5 |
| `src/services/price_monitor.py` | Resilient price polling | 5 |
| `gui_app/templates/risk_dashboard.html` | Risk overview | 8 |
| `gui_app/templates/help.html` | Help center | 8 |
| `gui_app/templates/order_states.html` | Order debugging | 8 |
| `gui_app/templates/onboarding/welcome.html` | First-time setup | 8 |
| `gui_app/templates/partials/waxui/*.html` | UI components | 6 |
| `gui_app/static/css/tokens.css` | Design tokens | 6 |
| `gui_app/static/css/waxui.css` | Component styles | 6 |
| `gui_app/static/js/waxui.js` | Component JS | 6 |
| `help/*.md` | Help content files | 8 |

### Files to Modify

| Path | Changes | Phase |
|------|---------|-------|
| `gui_app/database.py` | Add OMS/RMS schema migrations | 1 |
| `gui_app/routes.py` | Add risk management endpoints | 7 |
| `gui_app/templates/base.html` | Add Risk & Help nav links | 8 |
| `gui_app/templates/channels.html` | Enhanced risk settings UI | 8 |
| `gui_app/templates/settings.html` | Global risk settings | 8 |
| `src/selfbot_webull.py` | SignalExitManager integration | 4 |
| `src/signals/parser.py` | Add trim parsing, exit detection | 4 |
| `src/services/conditional_orders.py` | V2 enhancements | 5 |

---

## IMPLEMENTATION ORDER

### Critical Path (Do First)

1. **Database Schema** (Phase 1) - Foundation for everything
2. **CircuitBreaker** (Phase 3) - Safety first
3. **SignalExitManager** (Phase 2) - Core order management
4. **ExitOrderArbiter** (Phase 2) - Precedence rules
5. **Selfbot Integration** (Phase 4) - Wire it all together

### Secondary Path (Do After Core)

6. **API Routes** (Phase 7) - Expose functionality
7. **UI Templates** (Phase 8) - User interface
8. **Conditional Orders V2** (Phase 5) - Enhanced triggers

### Polish Path (Do Last)

9. **WaxUI Components** (Phase 6) - Consistent styling
10. **Event Bus** (Phase 9) - Full decoupling
11. **Testing & Rollout** (Phase 10) - Validation

---

## ROLLBACK PROCEDURES

### Database Rollback

All migrations are additive with defaults. To rollback:

```sql
-- Remove new columns (if needed)
-- ALTER TABLE channels DROP COLUMN max_daily_loss;
-- etc.

-- Remove new tables
DROP TABLE IF EXISTS order_states;
DROP TABLE IF EXISTS risk_limits;
DROP TABLE IF EXISTS risk_events;
DROP TABLE IF EXISTS broker_capabilities;
DROP TABLE IF EXISTS global_risk_settings;
DROP TABLE IF EXISTS order_update_queue;
DROP TABLE IF EXISTS conditional_triggers;
DROP TABLE IF EXISTS feature_flags;
```

### Feature Flag Rollback

Disable feature flags to revert to old behavior:

```python
set_feature_flag('enable_signal_exit_manager', False)
set_feature_flag('enable_exit_arbiter', False)
set_feature_flag('enable_conditional_v2', False)
```

### Code Rollback

Git revert to previous commit or restore from checkpoint.

---

## SUCCESS CRITERIA

### Phase Completion Checklist

- [ ] **Phase 1**: All migrations run without error, existing data preserved
- [ ] **Phase 2**: SignalExitManager handles new entries, SL updates, exits
- [ ] **Phase 3**: Circuit breaker halts/resumes trading, limits enforced
- [ ] **Phase 4**: C1apped signals use SignalExitManager, SL updates propagate
- [ ] **Phase 5**: Conditional triggers integrate with risk checks
- [ ] **Phase 6**: WaxUI components render correctly across pages
- [ ] **Phase 7**: All API endpoints return correct data, auth protected
- [ ] **Phase 8**: Risk dashboard shows live data, help content loads
- [ ] **Phase 9**: Events flow through event bus, subscribers notified
- [ ] **Phase 10**: Paper trading validation passes, no regressions

### Final Validation

- [ ] Kill switch halts all trading within 1 second
- [ ] Daily loss limit auto-halts when exceeded
- [ ] SL updates propagate to broker within 2 seconds
- [ ] Hybrid mode correctly applies tightest protection
- [ ] No orphaned orders after exits
- [ ] P&L tracking matches broker fills
- [ ] UI responsive and consistent across pages

---

*Generated: January 12, 2026*
*Version: 2.0*
*Scope: Complete OMS/RMS Implementation*
