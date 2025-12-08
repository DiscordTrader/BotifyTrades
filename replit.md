# BotifyTrades - Discord Trading Bot

## Overview
BotifyTrades is a cross-platform Discord self-bot designed for automated stock and options trading. It offers automated trading across Webull, Alpaca, and Interactive Brokers, featuring advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The bot monitors Discord for trading signals, executes trades with pre-trade swing analysis, AI-powered post-trade analysis, and interactive commands, all managed via a Flask web control panel. The project aims to provide a robust, automated trading solution, enhancing user control and analytical capabilities in the Discord environment.

## Architecture Principles

**See `ARCHITECTURE.md` for full details.**

### Recent Changes (Dec 8, 2025)
- **v2.1.23**: Upgrade system now auto-exits app after EXE update for seamless replacement
- **v2.1.23**: Upgrade system now prints prominent status summary to console (UPGRADE COMPLETE/FAILED box)
- **v2.1.23**: GitHub workflow fix - publish-to-public runs even if one platform build fails
- **v2.1.22**: Comprehensive diagnostics system - verifies settings sync, broker connectivity, license, Discord
- **v2.1.22**: New /api/diagnostics endpoint for on-demand health checks
- **v2.1.22**: Startup diagnostics runs automatically and prints summary to console
- **v2.1.22**: Risk management sync check compares DB vs runtime values
- **v2.1.22**: Fix options chain not loading - Webull API now returns list directly instead of dict
- **v2.1.22**: Fix find_open_bto_trade database import error in risk monitoring
- **v2.1.20**: Two-repo architecture - public releases repo for auto-updates, private source repo
- **v2.1.20**: Upgrade checker now points to BotifyTrades-Releases (public) instead of BotifyTradesv2 (private)
- **v2.1.20**: GitHub Actions automatically mirrors releases to public repo
- **v2.1.19**: Upgrade system now fully implements EXE replacement - extracts ZIP, replaces EXE, auto-restarts
- **v2.1.19**: Token-only mode now only requires access_token (refresh_token optional/dummy value allowed)
- **v2.1.19**: Added Windows batch script updater for seamless EXE upgrades
- **v2.1.18**: Token-only mode for Webull - bypasses captcha by using browser-extracted tokens
- **v2.1.18**: Settings UI now shows token extraction guide and clear tokens button
- **v2.1.18**: Webull credentials update now auto-clears old tokens when email/password changes
- **v2.1.18**: Added API endpoint to manually clear Webull tokens (/api/brokers/credentials/webull/clear-tokens)
- **v2.1.18**: BUILD VERSION now shows actual release version instead of debug string
- **v2.1.18**: Webull account type detection (Margin/Cash/IRA) - displays in Settings after connection
- **v2.1.18**: Account info badge shows type with color coding (orange=Margin, green=Cash, purple=IRA)
- **v2.1.14**: Fix "Check Schema" error in packaged builds - now shows success message instead of migration error
- **v2.1.13**: Fixed position sizing for options - now executes when buying power can afford 1 contract even if % budget cannot
- **v2.1.13**: Position size fallback to buying power when percentage budget is too small for minimum order
- **v2.1.11**: Fix License diagnostic: use validate_license() instead of legacy is_valid
- **v2.1.11**: Fix Database diagnostic: correct table name users -> app_users
- **v2.1.11**: Fix Broker pages: early credential check prevents hanging
- **v2.1.11**: Fix Option chain: load credentials from database, standalone broker/loop
- **v2.1.10**: License validation now contacts server FIRST for fresh expiry data
- **v2.1.10**: Fixes license extensions not reflecting (was using stale cached data)
- **v2.1.9**: Fixed upgrade system database path detection (searches exe dir, cwd, env var)
- **v2.1.9**: Fixes "Database file does not exist" error when upgrading packaged EXE
- **v2.1.8**: Dashboard positions now show Discord channel name that triggered each trade
- **v2.1.8**: Channel source badges display in broker analytics (Webull Live, Alpaca Paper/Live, IBKR Live/Paper)
- **v2.1.8**: Added green color variant to channel badge CSS for better visual distinction
- **v2.1.7**: RSA private key moved to RSA_PRIVATE_KEY environment variable (security fix)
- **v2.1.7**: Signed tokens now created using env var, server gracefully falls back if not set
- **v2.1.6**: Refactored license_client.py into src/license/ package (types, crypto, cache, client, heartbeat modules)
- **v2.1.6**: All modules under 500 lines for Pyarmor trial compatibility
- **v2.1.6**: Backward-compatible wrapper maintains all existing imports
- **v2.1.5**: Added fallback URL support to license client (primary: api.botifytrades.com, fallback: Replit)
- **v2.1.5**: License client now automatically tries backup servers if primary is unreachable
- **v2.1.4**: User Agreement updated to v2.0 with License Server terms (heartbeat, machine binding, anti-tampering)
- **v2.1.4**: Professional consent UI with new Section 8 highlighting license validation requirements
- **v2.1.3**: Admin License Server UI completely redesigned with professional BT branding
- **v2.1.3**: Added executive dashboard with KPIs, recent activity feed, and quick actions
- **v2.1.3**: Added audit log page for tracking all admin actions
- **v2.1.3**: Added settings page with server info and password change
- **v2.1.3**: Improved SSL fallback handling in license client for Windows compatibility
- **v2.1.2**: Enhanced license extension feature with quick buttons and custom input
- **v2.1.1**: Fixed upgrade checker GitHub config (was pointing to wrong repo)
- **v2.1.1**: Added license heartbeat system for runtime re-validation
- **v2.1.1**: Added detailed upgrade debug logging

### Dual-Build Separation
| Build | Entry Point | Package | Database | Purpose |
|-------|-------------|---------|----------|---------|
| **Admin License Server** | `admin_server.py` | `admin_panel/` | `license_server.db` | License management ONLY |
| **User Trading Bot** | `selfbot_webull.py` | `gui_app/` + `src/` | `bot_data.db` | Full trading functionality |

### Core Rules
1. **SINGLE DATABASE**: Only `bot_data.db` (user build) and `license_server.db` (admin build) - never create additional database files
2. **ADAPTER PATTERN**: All modules access database through adapters, never direct imports from gui_app/database.py
3. **NO DUPLICATES**: One file per responsibility, search before creating new files
4. **PLUGGABLE MODULES**: Self-contained modules in `src/`, communicate via callbacks
5. **STRICT BUILD SEPARATION**: Admin build has NO trading features; User build requires license
6. **CONSISTENCY CHECK**: Run `python scripts/check_consistency.py --quick` after changes
7. **NO NAME CONFLICTS**: Never name local modules the same as third-party packages (e.g., `src/webull_auth/` not `src/webull/`)

### Module Structure
```
src/{module}/
├── __init__.py      # Public exports only
├── types.py         # Data classes (zero dependencies)
├── {feature}.py     # Pure functions (testable)
└── {manager}.py     # Coordinator with adapter
```

## User Preferences
- **Security**: Always use environment variables (Replit Secrets) for credentials and license keys
- **Testing**: Test with paper_trade = true before enabling live trading
- **Monitoring**: Review console logs regularly for trade execution
- **Channel filtering**: Only process signals from designated channels
- **Deployment**: Prefer local machine or cloud VPS for 24/7 operation
- **Licensing**: All deployments require a valid license key (set via LICENSE_KEY environment variable or setup wizard)
- **Authentication**: First-time users are guided through setup wizard to create admin account with email recovery

## System Architecture

### UI/UX Decisions
The bot utilizes a Flask-based web control panel with a dark theme, real-time dashboards, dynamic channel management, live trade monitoring, and a System Health Page. Broker-specific Live Analytics pages offer Webull/Thinkorswim-style dashboards. An integrated AI chat assistant provides smart FAQ and intent-based support. The options trading interface is optimized for performance, enabling strike-targeted lookup and displaying detailed order inputs with Greeks.

### Technical Implementations
Core technologies include `discord.py-self` and `webull`. The system employs a true dual-broker architecture for live and paper trading, with platform-specific credential encryption. A separate thread runs the web GUI, communicating via SQLite. Order execution is managed by an asynchronous, queue-based system. Signal parsing uses regex and supports per-channel user filtering and a "TRADE IDEA" format. Risk management features automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all configurable via the GUI and stored in SQLite. Pre-trade analysis uses technical indicators, and post-execution analysis leverages OpenAI GPT models. Real-time market data is integrated, and interactive Discord commands enable on-demand analysis. The Auto Signal Conversion system executes stock alerts as Alpaca BRACKET ORDERs. Position sizing correctly applies to paper trades. An error monitoring system provides automatic detection, logging, and AI assistant contextual help. Licensing involves server-side validation with machine binding and an offline grace period.

### Feature Specifications
The system supports a dual-mode channel system for simultaneous execution and tracking with FIFO-based P&L tracking, and Multi-Broker Execution for trades across multiple accounts with per-channel broker selection. It handles market orders, comprehensive PNL page filtering, and per-channel position sizing. A Portfolio Simulation Engine projects portfolio growth. Authentication includes a setup wizard, secure login, password recovery, and a waitlist/referral system. The dashboard features live price refresh from Webull. Per-channel risk settings allow independent operation, supporting 3-tier profit targets with partial exits and trailing stops. A mandatory user agreement/risk disclosure is stored persistently.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, and Interactive Brokers. The system emphasizes user experience through an interactive setup wizard, GUI-based credential management, automatic license renewal, and extensive documentation. Deployment options include Windows, Linux (with systemd), and AWS EC2. The Discord bot runs in a dedicated thread with an isolated asyncio event loop. Broker credentials are loaded hierarchically. Discord channel IDs and all bot settings, including signal regex patterns and allowed author/guild IDs, are GUI-manageable and stored in SQLite. Per-channel risk management can override global defaults. The `/packaging/` directory consolidates platform-specific build scripts. The `/license/` module handles licensing, supporting legacy, machine-bound, and activation-based licenses with a dedicated GUI. The BrokerSyncService handles case-insensitive broker name matching. Options data retrieval prioritizes Webull for live prices. A unified position key format (`{BROKER}_{SYMBOL}_{STRIKE}_{EXPIRY}_{C/P}`) is used across the system. The system employs a dual-build license architecture separating Admin and User deployments for license management and bot operation.

## External Dependencies

- **Python**: 3.8+
- **discord.py-self**: Discord API interaction
- **webull**: Webull brokerage integration
- **Flask**: Web GUI framework
- **cryptography**: Encryption utilities
- **requests**: HTTP client
- **openai**: AI analysis (GPT models)
- **ta**: Technical analysis library
- **yfinance**: Market data access
- **aiohttp**: Asynchronous HTTP client
- **alpaca-py**: Alpaca brokerage integration
- **ib-insync**: Interactive Brokers integration
- **ALPHA_VANTAGE_API_KEY**: Market data
- **FINNHUB_API_KEY**: Market data
- **OPENAI_API_KEY**: AI analysis
- **ALPACA_API_KEY**: Alpaca brokerage
- **ALPACA_SECRET_KEY**: Alpaca brokerage
- **GMAIL_APP_PASSWORD**: For Gmail SMTP
- **SMTP_PASSWORD**: For custom SMTP