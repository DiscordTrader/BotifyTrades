# BotifyTrades - Discord Trading Bot

## Overview
BotifyTrades is a cross-platform Discord self-bot designed for automated stock and options trading. It offers automated trading across Webull, Alpaca, and Interactive Brokers, featuring advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The bot monitors Discord for trading signals, executes trades with pre-trade swing analysis, AI-powered post-trade analysis, and interactive commands, all managed via a Flask web control panel. The project aims to provide a robust, automated trading solution, enhancing user control and analytical capabilities in the Discord environment.

## Architecture Principles

**See `ARCHITECTURE.md` for full details.**

### Recent Changes (Dec 7, 2025)
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