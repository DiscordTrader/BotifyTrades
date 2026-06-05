# Database Consolidation Plan

## Overview
Consolidate from 3 databases to 2 clean, purpose-specific databases.

## Before Consolidation
| Database | Size | Status |
|----------|------|--------|
| `bot_data.db` | 659 KB | **MAIN** - Keep and split |
| `botify_trades.db` | 0 bytes | **DELETED** - Empty orphan |
| `trading_bot.db` | 0 bytes | **DELETED** - Empty orphan |

## After Consolidation

### 1. `license_server.db` (Admin Build Only)
Tables for license management - only included in admin server build.

| Table | Purpose | Rows |
|-------|---------|------|
| `server_licenses` | License keys, status, expiry | Licenses |
| `server_machines` | Machine bindings per license | Devices |
| `server_trials` | Trial tracking per machine | Trials |
| `license_validation_log` | Audit trail of validations | Logs |

### 2. `bot_data.db` (User Build)
Tables for trading operations - included in user EXE build.

| Table | Purpose |
|-------|---------|
| `app_users` | Admin panel users |
| `channels` | Monitored Discord channels |
| `channel_allowed_users` | Per-channel author filters |
| `signals` | Captured trading signals |
| `signal_lots` | Position lots for PNL tracking |
| `trades` | Executed trades |
| `lot_closures` | Closed lots with P&L |
| `config` | Encrypted broker credentials |
| `settings` | General settings |
| `trading_settings` | Trade execution settings |
| `risk_management_settings` | Global risk settings |
| `position_risk_settings` | Per-position risk overrides |
| `slippage_settings` | Slippage protection config |
| `discord_settings` | Discord notifications |
| `ai_settings` | AI analysis settings |
| `email_config` | Email notification config |
| `error_logs` | Error tracking |
| `known_issues` | Issue patterns for AI assistant |
| `performance_snapshots` | Portfolio snapshots |
| `conversion_channels` | Auto-convert channels |
| `end_users` | User dashboard accounts |
| `user_subscriptions` | User subscription tiers |
| `waitlist` | Waitlist signups |
| `password_reset_tokens` | Password reset tokens |

## Migration Strategy

### Phase 1: Immediate (Completed)
- [x] Delete empty orphan databases (`botify_trades.db`, `trading_bot.db`)
- [x] Document table categorization

### Phase 2: License Server Separation (Future)
1. Create `license_server.db` with license tables only
2. Update `gui_app/database.py` to use separate connection for license tables
3. Add `LICENSE_DB_PATH` environment variable
4. Update admin routes to use license database

### Phase 3: Build Separation
- **Admin Build**: Both databases included
- **User Build**: Only `bot_data.db` included (no license server tables)

## Table Schemas

### License Server Tables

```sql
-- server_licenses
CREATE TABLE server_licenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    license_key TEXT UNIQUE NOT NULL,
    license_type TEXT NOT NULL CHECK(license_type IN ('trial', 'subscription', 'lifetime', 'beta')),
    customer_id TEXT,
    customer_email TEXT,
    customer_name TEXT,
    machine_id TEXT,
    machine_info TEXT,
    max_devices INTEGER DEFAULT 1,
    devices_used INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'expired', 'revoked', 'suspended')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    activated_at TIMESTAMP,
    expires_at TIMESTAMP,
    last_validated_at TIMESTAMP,
    last_validated_ip TEXT,
    notes TEXT
);

-- server_machines
CREATE TABLE server_machines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    license_id INTEGER NOT NULL,
    machine_id TEXT NOT NULL,
    machine_name TEXT,
    machine_info TEXT,
    first_seen_ip TEXT,
    last_seen_ip TEXT,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (license_id) REFERENCES server_licenses(id),
    UNIQUE(license_id, machine_id)
);

-- server_trials
CREATE TABLE server_trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id TEXT UNIQUE NOT NULL,
    license_key TEXT NOT NULL,
    first_ip TEXT,
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'expired', 'converted')),
    converted_to_license_id INTEGER,
    FOREIGN KEY (converted_to_license_id) REFERENCES server_licenses(id)
);

-- license_validation_log
CREATE TABLE license_validation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    license_key TEXT,
    machine_id TEXT,
    action TEXT NOT NULL CHECK(action IN ('validate', 'activate', 'trial_request', 'revoke', 'deactivate')),
    result TEXT NOT NULL CHECK(result IN ('success', 'failed', 'blocked', 'rate_limited')),
    ip_address TEXT,
    user_agent TEXT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Notes
- Current implementation keeps all tables in `bot_data.db` for simplicity
- Separation will happen during Flask blueprint refactoring (Phase 5-6)
- No data migration needed - just code changes to use separate connections
