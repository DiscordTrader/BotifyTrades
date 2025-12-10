# BotifyTrades - Pluggable Architecture Guide

**Version:** 1.2  
**Last Updated:** December 10, 2025  
**Purpose:** Define architecture principles for scalable, pluggable features

---

## Dual-Build Architecture

BotifyTrades uses a **strict dual-build separation** between Admin and User deployments:

```
┌─────────────────────────────────────────────────────────────────────┐
│                      DUAL-BUILD SEPARATION                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ADMIN LICENSE SERVER              USER TRADING BOT                 │
│  ─────────────────────             ────────────────────             │
│  Entry: admin_server.py            Entry: selfbot_webull.py         │
│  Package: admin_panel/             Package: gui_app/ + src/         │
│  Database: license_server.db       Database: bot_data.db            │
│                                                                     │
│  Features:                         Features:                        │
│  ├─ Admin authentication           ├─ Discord trading bot           │
│  ├─ License CRUD                   ├─ Webull/Alpaca/IBKR brokers    │
│  ├─ Device activation mgmt         ├─ Trading dashboard             │
│  ├─ License validation API         ├─ Position monitoring           │
│  └─ Audit logging                  ├─ Risk management               │
│                                    ├─ AI analysis                   │
│  ❌ NO trading features            └─ Signal parsing                │
│  ❌ NO broker connections                                           │
│  ❌ NO dashboard/P&L               ✓ Requires valid license         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Build Separation Rules

| Rule | Admin Build | User Build |
|------|-------------|------------|
| **Entry Point** | `admin_server.py` | `selfbot_webull.py` |
| **Flask Package** | `admin_panel/` | `gui_app/` |
| **Database** | `license_server.db` | `bot_data.db` |
| **Trading Features** | ❌ Never | ✓ Always |
| **Broker Connections** | ❌ Never | ✓ Always |
| **License Required** | ❌ No | ✓ Yes |
| **Deployment** | Replit (you) | User's machine (EXE) |

### Why Separation Matters

1. **Security**: Admin has RSA signing keys; users don't get admin tools
2. **Resource Isolation**: Trading bot runs on user machines, not your Replit
3. **Clean Boundaries**: Each build has clear, single responsibility
4. **Scalability**: License server handles many user bots

---

## Core Principles

### 1. SINGLE DATABASE RULE

```
┌─────────────────────────────────────────────────────────┐
│                    DATABASES                             │
├─────────────────────────────────────────────────────────┤
│  bot_data.db          → User Build (trading bot)        │
│  license_server.db    → Admin Build (license server)    │
│                                                          │
│  ❌ NEVER create additional .db or .sqlite files        │
│  ❌ NEVER create module-specific databases              │
│  ✓  All modules use adapter pattern to access DB        │
└─────────────────────────────────────────────────────────┘
```

**Database Access Pattern:**
- `gui_app/database.py` - Single source of truth for DB operations
- All modules access DB through **adapters** (never direct imports)
- Adapters receive DB reference at initialization

### 2. PLUGGABLE MODULE PATTERN

All feature modules follow the **Adapter Pattern**:

```python
# ✅ CORRECT: Module uses adapter for DB access
class RiskManager:
    def __init__(self, db_adapter: RiskDBAdapter):
        self.db_adapter = db_adapter  # Injected dependency
    
# ✅ CORRECT: Adapter wraps external dependency
class RiskDBAdapter:
    def __init__(self, db=None):
        self._db = db  # Optional - graceful degradation
    
# ❌ WRONG: Direct import creates coupling
from gui_app.database import get_connection  # Never do this in modules
```

### 3. MODULE STRUCTURE

```
src/
├── {module_name}/
│   ├── __init__.py      # Public exports only
│   ├── types.py         # Data classes, no dependencies
│   ├── {feature}.py     # Pure functions, no side effects
│   └── {manager}.py     # Coordinator class with adapter
```

**Module Requirements:**
- Each module is self-contained
- Types/data classes have ZERO external dependencies
- Pure functions for business logic (testable)
- Single manager class coordinates the module
- Adapters isolate external dependencies

### 4. NO DUPLICATE FILES

```
┌─────────────────────────────────────────────────────────┐
│                 FILE OWNERSHIP                           │
├─────────────────────────────────────────────────────────┤
│  ONE file per responsibility                             │
│  ONE module per feature domain                           │
│  ONE database per build target                           │
│                                                          │
│  Before creating a file:                                 │
│  1. Search for existing implementation                   │
│  2. Extend existing file if possible                     │
│  3. Create new only if new domain/responsibility         │
└─────────────────────────────────────────────────────────┘
```

**Consistency Check Command:**
```bash
python scripts/check_consistency.py --quick   # Quick validation
python scripts/check_consistency.py --full    # Deep analysis
```

---

## Module Registration

### Current Modules

| Module | Owner File | Adapter | Database |
|--------|-----------|---------|----------|
| `core` | `src/core/bootstrap.py` | N/A | N/A |
| `discord_client` | `src/discord_client/client.py` | DiscordDBAdapter | bot_data.db |
| `signals` | `src/signals/parser.py` | N/A (pure) | N/A |
| `risk` | `src/risk/position_monitor.py` | RiskDBAdapter | bot_data.db | **Single source** - no legacy fallbacks |
| `brokers` | `src/brokers/__init__.py` | N/A | N/A |
| `execution` | `src/execution/` | TBD | bot_data.db |

### Adding a New Module

1. **Create module directory:**
   ```
   src/{module_name}/
   ├── __init__.py      # Export public API
   ├── types.py         # Data classes
   └── {module}.py      # Implementation
   ```

2. **Create adapter if DB access needed:**
   ```python
   class {Module}DBAdapter:
       def __init__(self, db=None):
           self._db = db
   ```

3. **Register in this document** (Module Registration table)

4. **Run consistency check:**
   ```bash
   python scripts/check_consistency.py --quick
   ```

---

## Integration Points

### Wiring Modules to Main Application

```python
# In src/selfbot_webull.py or main entry point

# 1. Import adapters, not modules directly
from src.risk import RiskManager, RiskDBAdapter

# 2. Create adapter with DB reference
db = Database()  # Single database instance
risk_adapter = RiskDBAdapter(db)

# 3. Create manager with adapter
risk_manager = RiskManager(
    db_adapter=risk_adapter,
    position_fetcher=self.get_open_positions,
    order_queue=self.order_queue
)

# 4. Wire callbacks (loose coupling)
risk_manager.on_exit_triggered = self.handle_exit_order
```

### Event-Based Communication

Modules communicate via callbacks/events, not direct calls:

```python
# ✅ CORRECT: Callback-based communication
risk_manager.on_exit_triggered = lambda pos, reason: order_queue.put(...)

# ❌ WRONG: Direct coupling
risk_manager.selfbot = self  # Creates circular dependency
```

---

## Database Schema Extensions

When a module needs new DB tables/columns:

1. **Add to gui_app/database.py** (single source)
2. **Add migration in ensure_tables()**
3. **Update adapter to use new schema**
4. **Run consistency check**

```python
# In gui_app/database.py
def ensure_tables(conn):
    # ... existing tables ...
    
    # New module table (add here, not in module)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS {module}_data (
            id INTEGER PRIMARY KEY,
            ...
        )
    ''')
```

---

## Anti-Patterns to Avoid

### ❌ Don't Do This

```python
# 1. Multiple database files
Path('risk_cache.db')      # Wrong - use single DB
Path('positions.sqlite')   # Wrong - use single DB

# 2. Direct database imports in modules
from gui_app.database import get_connection  # Wrong - use adapter

# 3. Circular dependencies
from src.selfbot_webull import SelfClient  # Wrong in modules

# 4. Global state in modules
_global_positions = {}  # Wrong - pass via constructor

# 5. Duplicate implementations
def parse_signal(...):  # Check if exists in src/signals/
```

### ✅ Do This Instead

```python
# 1. Single database via adapter
class ModuleDBAdapter:
    def __init__(self, db=None):
        self._db = db  # Receives single DB instance

# 2. Dependency injection
class ModuleManager:
    def __init__(self, db_adapter, external_service):
        self.db = db_adapter
        self.service = external_service

# 3. Pure functions for logic
def evaluate_condition(data: DataClass) -> Result:
    return Result(...)  # No side effects, easily testable

# 4. Callbacks for communication
self.on_event = None  # Set by parent at runtime
```

---

## Validation Commands

```bash
# Quick check (run after changes)
python scripts/check_consistency.py --quick

# Full check (run before deploy)
python scripts/check_consistency.py --full

# Check for duplicate files
find . -name "*.py" | xargs grep -l "class SameClass" | wc -l

# Check database files (should be 1-2 only)
find . -name "*.db" -o -name "*.sqlite"
```

---

## Summary

| Principle | Rule |
|-----------|------|
| **Single Database** | One .db per build (bot_data.db for user, license_server.db for admin) |
| **Adapter Pattern** | All modules access DB through adapters, never direct imports |
| **No Duplicates** | One file per responsibility, search before creating |
| **Pluggable** | Modules are self-contained, communicate via callbacks |
| **Pure Logic** | Business logic in pure functions, side effects in adapters |
| **Consistency** | Run check_consistency.py after every change |
