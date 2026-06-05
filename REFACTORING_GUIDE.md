# BotifyTrades v2.0 - Complete Refactoring Guide

**Document Version:** 1.0  
**Created:** December 5, 2025  
**Purpose:** Comprehensive project documentation for refactoring into a new Replit project

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Application Overview](#application-overview)
3. [Architecture Deep Dive](#architecture-deep-dive)
4. [Database Schema](#database-schema)
5. [Core Features & Flows](#core-features--flows)
6. [Code Analysis - Files to Refactor](#code-analysis---files-to-refactor)
7. [Proposed New Architecture](#proposed-new-architecture)
8. [Admin vs User Build Separation](#admin-vs-user-build-separation)
9. [Database Consolidation Plan](#database-consolidation-plan)
10. [Implementation Phases](#implementation-phases)
11. [Required Secrets & Environment Variables](#required-secrets--environment-variables)
12. [How to Import into New Replit](#how-to-import-into-new-replit)

---

## Executive Summary

### What is BotifyTrades?
A cross-platform Discord self-bot for automated stock and options trading across multiple brokers (Webull, Alpaca, Interactive Brokers). Features include:
- Discord signal monitoring and auto-execution
- Multi-broker support with paper/live trading
- AI-powered trade analysis
- Risk management (stop losses, profit targets, trailing stops)
- Web-based control panel
- License server for subscription management

### Current Problems
| Problem | Impact | Solution |
|---------|--------|----------|
| `selfbot_webull.py` is 6,666 lines | Hard to maintain, changes break things | Split into ~15 modular files |
| `routes.py` is 8,793 lines | Same issue | Split into route modules |
| 5 database files | Confusion, schema mismatches | Consolidate to 2 (admin + user) |
| Single build type | Can't separate admin from users | Create 2 build pipelines |

### Target State
- **Modular codebase** with features in separate files
- **2 databases**: `license_server.db` (admin) + `bot_data.db` (user)
- **2 builds**: Admin (license management) + User (trading bot)

---

## Application Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DISCORD                                      │
│  (Monitors channels for trading signals like "BTO AAPL 150C 12/20") │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    DISCORD SELF-BOT                                  │
│  src/selfbot_webull.py (SelfClient class)                           │
│  - Parses signals using regex                                        │
│  - Routes to correct broker                                          │
│  - Queues orders for execution                                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              ┌──────────┐   ┌──────────┐   ┌──────────┐
              │ WEBULL   │   │ ALPACA   │   │  IBKR    │
              │ BROKER   │   │ BROKER   │   │ BROKER   │
              └──────────┘   └──────────┘   └──────────┘
                    │               │               │
                    └───────────────┼───────────────┘
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    RISK MANAGEMENT                                   │
│  - Per-channel profit targets (tiered: T1/T2/T3)                    │
│  - Global stop losses                                                │
│  - Trailing stops                                                    │
│  - Position monitoring (30-second cycles)                           │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    WEB CONTROL PANEL                                 │
│  gui_app/ (Flask)                                                   │
│  - Dashboard, Settings, Channels, Trades, PNL Tracking              │
│  - License Admin Panel                                               │
│  - Broker Analytics                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
/
├── src/                          # Core bot source code
│   ├── selfbot_webull.py         # MAIN FILE (6,666 lines) - NEEDS SPLITTING
│   ├── brokers/                  # Broker implementations (already modular)
│   │   ├── webull_broker.py
│   │   ├── alpaca_broker.py
│   │   └── ibkr_broker.py
│   ├── ai_analyzer.py            # AI trade analysis
│   ├── broker_manager.py         # Multi-broker routing
│   ├── license_client.py         # License validation client
│   ├── swing_analyzer.py         # Pre-trade analysis
│   └── trade_tracker.py          # Post-trade tracking
│
├── gui_app/                      # Flask web application
│   ├── app.py                    # Flask app entry
│   ├── routes.py                 # ALL ROUTES (8,793 lines) - NEEDS SPLITTING
│   ├── database.py               # Database layer (4,206 lines)
│   ├── templates/                # HTML templates (25 files)
│   └── static/                   # CSS, JS, images
│
├── license_server/               # License server (separate deployment)
│   ├── main.py                   # FastAPI license server
│   ├── admin_cli.py              # CLI for license management
│   └── generate_rsa_keys.py      # Key generation
│
├── bot_data.db                   # MAIN DATABASE (836 KB, 29 tables)
├── gui_app/bot_settings.db       # LEGACY DATABASE (schema mismatch)
└── 3 empty orphan DBs            # DELETE THESE
```

---

## Architecture Deep Dive

### Signal Processing Flow

```
Discord Message Received
         │
         ▼
┌─────────────────────────────────┐
│ 1. MESSAGE FILTERING            │
│    - Check channel is monitored │
│    - Check author is allowed    │
│    - Check not already processed│
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 2. SIGNAL PARSING               │
│    - Option: BTO AAPL 150C 12/20 @1.50
│    - Stock: BTO AAPL @150.00    │
│    - Uses regex patterns        │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 3. DATABASE LOGGING             │
│    - Save to signals table      │
│    - Create lot for PNL tracking│
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 4. PRE-TRADE ANALYSIS (Optional)│
│    - Swing analysis confidence  │
│    - Skip low-confidence trades │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 5. ORDER QUEUE                  │
│    - Add to asyncio.Queue       │
│    - Worker processes in order  │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 6. BROKER SELECTION             │
│    - Per-channel broker config  │
│    - Signal prefix override     │
│    - Paper vs Live routing      │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 7. SLIPPAGE PROTECTION          │
│    - Compare signal price to    │
│      current market price       │
│    - Wait or abort if too high  │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 8. ORDER EXECUTION              │
│    - Call broker API            │
│    - Handle errors/retries      │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ 9. POST-EXECUTION               │
│    - Discord notification       │
│    - Database trade record      │
│    - Schedule AI follow-up      │
└─────────────────────────────────┘
```

### Risk Management System

```
RISK MANAGEMENT HIERARCHY
═════════════════════════

PRIORITY 1: Per-Channel Settings (trades with channel_id)
├── Tiered Profit Targets
│   ├── Tier 1: e.g., +20% → Close 1/3 position
│   ├── Tier 2: e.g., +40% → Close 1/2 remaining
│   └── Tier 3: e.g., +60% → Close all remaining
├── Per-Channel Stop Loss: e.g., -15%
└── Per-Channel Trailing Stop: e.g., 10% after activation

PRIORITY 2: Global Settings (fallback for trades without channel_id)
├── Global Profit Target: e.g., +25%
├── Global Stop Loss: e.g., -10%
└── Global Trailing Stop: e.g., 15%

MODES:
- HYBRID: Per-channel first, global fallback
- GLOBAL ONLY: All trades use global settings
- PER-CHANNEL ONLY: Only channel-linked trades get risk mgmt
```

### License System Flow

```
USER CLIENT                         LICENSE SERVER
    │                                    │
    │  POST /api/v1/licenses/validate    │
    │  {license_key, machine_id}         │
    ├───────────────────────────────────►│
    │                                    │
    │                           ┌────────┴────────┐
    │                           │ 1. Verify HMAC  │
    │                           │ 2. Check DB     │
    │                           │ 3. Check expiry │
    │                           │ 4. Check machine│
    │                           │ 5. Generate JWT │
    │                           └────────┬────────┘
    │                                    │
    │  {valid: true, token: "eyJ..."}    │
    │◄───────────────────────────────────┤
    │                                    │
    │  Store JWT locally (24hr offline)  │
    │                                    │
```

---

## Database Schema

### Active Database: `bot_data.db` (29 tables)

#### LICENSE TABLES (Admin Build Only)
| Table | Columns | Rows | Purpose |
|-------|---------|------|---------|
| `server_licenses` | license_key, customer_id, status, expires_at, devices_used, max_devices | 18 | License records |
| `server_machines` | license_id, machine_id, activated_at, is_active | 17 | Device bindings |
| `license_validation_log` | license_key, machine_id, result, timestamp | 73 | Audit trail |
| `server_trials` | email, machine_id, trial_start, trial_end | 4 | Trial licenses |

#### TRADING TABLES (User Build Only)
| Table | Columns | Rows | Purpose |
|-------|---------|------|---------|
| `trades` | id, symbol, direction, entry_price, quantity, channel_id, broker, status | 439 | Trade records |
| `signals` | id, symbol, action, price, channel_id, message_id, parsed_at | 1176 | Signal history |
| `signal_lots` | id, signal_id, quantity, entry_price, remaining_qty | 581 | FIFO lot tracking |
| `lot_closures` | id, lot_id, closed_qty, close_price, pnl, pnl_percent | 502 | PNL records |

#### SETTINGS TABLES (Both Builds)
| Table | Columns | Rows | Purpose |
|-------|---------|------|---------|
| `channels` | discord_channel_id, name, category, execute_enabled, track_enabled, profit_target_1/2/3_pct, stop_loss_pct, trailing_stop_pct | 14 | Channel config |
| `settings` | key, value | 11 | Key-value settings |
| `config` | key, value_encrypted | 4 | Encrypted config |
| `risk_management_settings` | enabled, profit_target_percent, stop_loss_percent, trailing_stop_percent | 1 | Global risk |
| `trading_settings` | max_position_size, auto_qty_calculation, paper_trade | 1 | Trading config |
| `slippage_settings` | enabled, threshold_percent, wait_seconds | 1 | Slippage config |

#### USER MANAGEMENT TABLES (Both Builds)
| Table | Columns | Rows | Purpose |
|-------|---------|------|---------|
| `app_users` | id, username, email, password_hash, is_admin | 1 | Web panel users |
| `channel_allowed_users` | channel_id, discord_user_id, discord_username | 4 | Per-channel filtering |

---

## Core Features & Flows

### Feature 1: Signal Parsing
**Location:** `src/selfbot_webull.py` lines 3916-4007

```python
# Option signal regex
OPT_REGEX = r'^(?:BTO|STC)\s+(\w+)\s+(\d+(?:\.\d+)?)[CP]\s+(\d{1,2}/\d{1,2})\s*@?\s*\$?(\d+(?:\.\d+)?)'
# Matches: "BTO AAPL 150C 12/20 @1.50"

# Stock signal regex  
STK_REGEX = r'^(?:BTO|STC)\s+(\w+)\s*@?\s*\$?(\d+(?:\.\d+)?)'
# Matches: "BTO AAPL @150.00"
```

**Recommended Module:** `src/signals/parser.py`

### Feature 2: Multi-Broker Execution
**Location:** `src/broker_manager.py`, `src/brokers/`

```python
class BrokerManager:
    brokers = {
        'WEBULL': WebullBroker,
        'WEBULL_PAPER': WebullBroker (paper mode),
        'ALPACA': AlpacaBroker,
        'ALPACA_PAPER': AlpacaBroker (paper mode),
        'IBKR': IBKRBroker
    }
```

**Already modular - no changes needed**

### Feature 3: Risk Management
**Location:** `src/selfbot_webull.py` lines 3113-3915 (800 lines!)

```python
async def monitor_positions(self, order_queue, alpaca_broker):
    """
    - Runs every 30 seconds
    - Fetches positions from all brokers
    - Applies per-channel or global risk settings
    - Queues exit orders when thresholds hit
    """
```

**Recommended Module:** `src/risk/position_monitor.py`

### Feature 4: AI Analysis
**Location:** `src/ai_analyzer.py`, `src/trade_tracker.py`

```python
class TradeAnalyzer:
    # Uses OpenAI GPT for trade analysis
    # Post-trade follow-up at 30min, 1hr, 1day

class SentimentAnalyzer:
    # Analyzes Discord message sentiment
```

**Already modular - no changes needed**

### Feature 5: Web Control Panel
**Location:** `gui_app/routes.py` (8,793 lines, 231 functions!)

Key route groups:
- `/` - Dashboard
- `/channels` - Channel management
- `/trades` - Trade history
- `/pnl` - PNL tracking
- `/settings` - Bot configuration
- `/options` - Options trading interface
- `/api/admin/licenses/*` - License admin (Admin build only)

**Recommended Split:**
```
gui_app/routes/
├── __init__.py
├── dashboard.py      # Dashboard routes
├── channels.py       # Channel management
├── trades.py         # Trade history
├── pnl.py           # PNL tracking
├── settings.py       # Configuration
├── options.py        # Options interface
├── auth.py          # Login/logout
├── api_trading.py   # Trading API endpoints
├── api_data.py      # Data API endpoints
└── admin_licenses.py # License admin (Admin build only)
```

---

## Code Analysis - Files to Refactor

### Priority 1: `src/selfbot_webull.py` (6,666 lines)

| Lines | Feature | Target Module | Complexity |
|-------|---------|---------------|------------|
| 1-128 | SSL/Debug setup | `core/bootstrap.py` | Low |
| 130-353 | Print overrides | `core/output_handler.py` | Low |
| 354-440 | License helpers | `licensing/helpers.py` | Medium |
| 441-1240 | Config loading | `core/config_loader.py` | Medium |
| 1241-1563 | Settings getters | `core/settings.py` | Low |
| 1564-3112 | WebullBroker (in-file) | Move to `brokers/webull_broker.py` | High |
| 3113-3915 | Risk monitoring | `risk/position_monitor.py` | High |
| 3916-4007 | Signal parsing | `signals/parser.py` | Medium |
| 4008-4418 | SelfClient init | `discord/client.py` | Medium |
| 4419-4465 | Schedulers | `discord/schedulers.py` | Low |
| 4466-5141 | Commands | `discord/commands/*.py` | Medium |
| 5142-5538 | on_message | `discord/message_handler.py` | High |
| 5539-5805 | Broker execution | `execution/broker_executor.py` | Medium |
| 5806-6532 | Worker | `execution/order_worker.py` | High |
| 6533-6666 | Thread mgmt | `core/thread_manager.py` | Low |

### Priority 2: `gui_app/routes.py` (8,793 lines)

| Lines (approx) | Feature | Target Module |
|----------------|---------|---------------|
| 1-500 | Auth, decorators | `routes/auth.py` |
| 500-1500 | Dashboard, channels | `routes/dashboard.py`, `routes/channels.py` |
| 1500-2500 | Trades, signals | `routes/trades.py` |
| 2500-3500 | PNL, performance | `routes/pnl.py` |
| 3500-4500 | Settings, config | `routes/settings.py` |
| 4500-5500 | Options interface | `routes/options.py` |
| 5500-6500 | Trading API | `routes/api_trading.py` |
| 6500-7500 | Data API | `routes/api_data.py` |
| 7500-8793 | License admin | `routes/admin_licenses.py` |

### Priority 3: `gui_app/database.py` (4,206 lines)

| Lines | Feature | Target Module |
|-------|---------|---------------|
| 1-300 | Connection, helpers | `database/connection.py` |
| 300-600 | Channel operations | `database/channels.py` |
| 600-1200 | Trade operations | `database/trades.py` |
| 1200-1800 | Settings operations | `database/settings.py` |
| 1800-2400 | PNL/Lot operations | `database/pnl.py` |
| 2400-3000 | License operations | `database/licenses.py` |
| 3000-4206 | Schema, migrations | `database/schema.py` |

---

## Proposed New Architecture

### File Structure After Refactor

```
src/
├── core/
│   ├── __init__.py
│   ├── bootstrap.py           # SSL, paths, early imports
│   ├── config_loader.py       # Load credentials from DB/config
│   ├── settings.py            # Settings getters
│   ├── output_handler.py      # Print overrides, debug mode
│   ├── utilities.py           # Symbol fixing, helpers
│   └── thread_manager.py      # Thread management
│
├── discord/
│   ├── __init__.py
│   ├── client.py              # SelfClient class (core only)
│   ├── message_handler.py     # on_message routing
│   ├── schedulers.py          # Token refresh, analysis tasks
│   └── commands/
│       ├── __init__.py
│       ├── analyze.py         # !analyze command
│       ├── ask.py             # !ask command
│       ├── scanflow.py        # !scanflow command
│       └── convert.py         # Signal conversion
│
├── signals/
│   ├── __init__.py
│   ├── parser.py              # Signal regex parsing
│   └── validator.py           # Signal validation
│
├── execution/
│   ├── __init__.py
│   ├── order_worker.py        # Order queue worker
│   ├── broker_executor.py     # Multi-broker execution
│   └── slippage.py           # Slippage protection
│
├── risk/
│   ├── __init__.py
│   ├── position_monitor.py    # Main monitoring loop
│   ├── tiered_targets.py      # Per-channel profit targets
│   └── global_risk.py         # Global stop/targets
│
├── brokers/                   # (Already exists - consolidate)
│   ├── __init__.py
│   ├── base_broker.py
│   ├── webull_broker.py       # CONSOLIDATE in-file broker here
│   ├── alpaca_broker.py
│   └── ibkr_broker.py
│
├── licensing/
│   ├── __init__.py
│   ├── client.py              # License validation
│   └── helpers.py             # Cache, validators
│
└── main.py                    # Entry point

gui_app/
├── routes/
│   ├── __init__.py            # Register all routes
│   ├── auth.py
│   ├── dashboard.py
│   ├── channels.py
│   ├── trades.py
│   ├── pnl.py
│   ├── settings.py
│   ├── options.py
│   ├── api_trading.py
│   ├── api_data.py
│   └── admin_licenses.py      # ADMIN BUILD ONLY
│
├── database/
│   ├── __init__.py
│   ├── connection.py
│   ├── channels.py
│   ├── trades.py
│   ├── settings.py
│   ├── pnl.py
│   ├── licenses.py            # ADMIN BUILD ONLY
│   └── schema.py
│
├── templates/
├── static/
└── app.py
```

---

## Admin vs User Build Separation

### Build Differences

| Component | Admin Build | User Build |
|-----------|-------------|------------|
| License server | ✅ Included | ❌ Excluded |
| License admin panel | ✅ `/admin/licenses` | ❌ Hidden |
| License validation | Server-side | Client-side only |
| Database | `license_server.db` + `bot_data.db` | `bot_data.db` only |
| Trading functionality | ✅ Full | ✅ Full |
| Web panel | ✅ Full + Admin | ✅ Full (no admin) |

### Database Separation

```
ADMIN BUILD:
├── license_server.db          # License-only tables
│   ├── server_licenses
│   ├── server_machines
│   ├── license_validation_log
│   └── server_trials
│
└── bot_data.db                # Everything else
    ├── trades, signals, lot_closures
    ├── channels, settings, config
    └── app_users, etc.

USER BUILD:
└── bot_data.db                # Trading + settings only
    ├── trades, signals, lot_closures
    ├── channels, settings, config
    └── app_users (for web panel auth)
```

### Build Configuration

Create build manifests:

```python
# packaging/admin_build.py
INCLUDE_MODULES = [
    'license_server/',
    'gui_app/routes/admin_licenses.py',
    'gui_app/database/licenses.py',
]
DATABASE_FILES = ['license_server.db', 'bot_data.db']

# packaging/user_build.py
EXCLUDE_MODULES = [
    'license_server/',
    'gui_app/routes/admin_licenses.py',
    'gui_app/database/licenses.py',
]
DATABASE_FILES = ['bot_data.db']
```

---

## Database Consolidation Plan

### Phase 1: Cleanup (Safe)
1. Delete empty orphan databases:
   - `trading_bot.db` (0 KB)
   - `botify_trades.db` (0 KB)
   - `botifytrades.db` (0 KB)

2. Backup legacy database:
   - Rename `gui_app/bot_settings.db` → `gui_app/bot_settings.db.bak`

### Phase 2: Update Scripts
Update these files to use `bot_data.db`:
- `scripts/migrations.py` (line: `'gui_app/bot_settings.db'`)
- `scripts/validate_before_deploy.py` (line: `'gui_app/bot_settings.db'`)
- `scripts/validate_schema.py` (lines referencing legacy DBs)
- `scripts/system_diagnostics.py` (default db_path)

### Phase 3: License DB Isolation
1. Create `license_server.db` with schema:
```sql
CREATE TABLE server_licenses (...);
CREATE TABLE server_machines (...);
CREATE TABLE license_validation_log (...);
CREATE TABLE server_trials (...);
```

2. Migrate data from `bot_data.db` license tables
3. Update `gui_app/database.py` to use conditional DB path

### Phase 4: Verification
- Run all diagnostics
- Test license server endpoints
- Test trading functionality
- Test risk monitoring

---

## Implementation Phases

### Phase 0: Setup (Day 1)
- [ ] Create new Replit project
- [ ] Import code from GitHub
- [ ] Configure secrets
- [ ] Verify bot starts

### Phase 1: Database Cleanup (Day 1-2)
- [ ] Delete empty orphan DBs
- [ ] Update script paths
- [ ] Test diagnostics pass

### Phase 2: Core Modularization (Day 3-5)
- [ ] Create `src/core/` modules
- [ ] Extract utilities and config
- [ ] Test bot starts with new structure

### Phase 3: Feature Extraction (Day 6-10)
- [ ] Extract signal parsing
- [ ] Extract risk monitoring
- [ ] Extract Discord commands
- [ ] Test all features work

### Phase 4: GUI Route Split (Day 11-15)
- [ ] Create route modules
- [ ] Split `routes.py`
- [ ] Test web panel

### Phase 5: Database Isolation (Day 16-18)
- [ ] Create `license_server.db`
- [ ] Migrate license tables
- [ ] Test license system

### Phase 6: Build Separation (Day 19-20)
- [ ] Create build manifests
- [ ] Test admin build
- [ ] Test user build

---

## Required Secrets & Environment Variables

### Required Secrets (Sensitive - Set in Replit Secrets)
```
ADMIN_PASSWORD          # Web panel admin password
DISCORD_TOKEN           # Discord self-bot token
WEBULL_ACCESS_TOKEN     # Webull auth token
WEBULL_REFRESH_TOKEN    # Webull refresh token
ALPACA_API_KEY          # Alpaca API key
ALPACA_SECRET_KEY       # Alpaca secret
OPENAI_API_KEY          # For AI analysis
LICENSE_RSA_PRIVATE_KEY # License signing key
```

### Optional Secrets
```
ALPHA_VANTAGE_API_KEY   # Option flow scanning
FINNHUB_API_KEY         # News service
GOOGLE_OAUTH_CLIENT_ID  # Google login
GOOGLE_OAUTH_CLIENT_SECRET
IBKR_HOST               # Interactive Brokers
IBKR_PORT
```

### Environment Variables (Non-sensitive)
```
DATABASE_PATH=bot_data.db
LICENSE_SERVER_URL=https://license.botifytrades.com
DEBUG_MODE=false
```

---

## How to Import into New Replit

### Step 1: Push to GitHub
```bash
# In current Replit
git add .
git commit -m "Prepare for refactoring"
git push origin main
```

### Step 2: Create New Replit
1. Go to [replit.com/import](https://replit.com/import)
2. Select **GitHub**
3. Connect your GitHub account if not already
4. Select your repository
5. Click **Import**

### Step 3: Configure New Replit
1. Go to **Secrets** tab
2. Add all required secrets (see above)
3. Run the bot to verify it starts:
   ```bash
   python src/selfbot_webull.py
   ```

### Step 4: Start Refactoring
Follow the implementation phases above in the new Replit.

### Important Notes
- **Never run two bots with same Discord token** (will conflict)
- Keep original Replit for production
- New Replit is for development only
- Test thoroughly before replacing production

---

## Contact & Support

For questions about this refactoring guide:
- Review the `replit.md` file for additional context
- Check the `TROUBLESHOOTING.md` for common issues
- Consult existing documentation in project root

---

*Document created: December 5, 2025*
*Last updated: December 5, 2025*
