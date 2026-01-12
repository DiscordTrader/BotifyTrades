# BotifyTrades - Multi-Platform Trading Bot

## Overview
BotifyTrades is a cross-platform trading automation bot for Discord and Telegram, designed for automated stock and options trading across multiple brokers in the USA, Canada, and India. Its primary purpose is to provide automated execution, advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The project aims to deliver a robust, automated trading solution, enhancing user control and analytical capabilities within a messaging-centric workflow, ultimately making sophisticated trading accessible and efficient.

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
The bot features a Flask-based web control panel with a dark theme, real-time dashboards, dynamic channel management, live trade monitoring, and a System Health Page. Broker-specific Live Analytics pages emulate professional trading platforms. An integrated AI chat assistant provides smart FAQ and intent-based support. The options trading interface is optimized for performance, enabling strike-targeted lookup and displaying detailed order inputs with Greeks. A PySide6-based setup wizard guides first-time users through configuration, with a splash screen and system tray integration.

### Technical Implementations
Core technologies include `discord.py-self` and `webull`. It employs a true dual-broker architecture for live and paper trading, with platform-specific credential encryption. Order execution uses an asynchronous, queue-based system. Signal parsing uses a multi-layer approach supporting learned formats, built-in regex, and AI fallback, with a Signal Format Registry providing modular signal parsing with priority-based format matching. Supported trader formats include STACK$, Jake/Optioneering, and Slem. Risk management includes automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all GUI-configurable and stored in SQLite. Pre-trade analysis uses technical indicators, and post-execution analysis leverages OpenAI GPT models. Real-time market data is integrated, and interactive Discord commands enable on-demand analysis. The Auto Signal Conversion system executes stock alerts as Alpaca BRACKET ORDERs. An error monitoring system provides automatic detection, logging, and AI assistant contextual help.

The Signal Verification Service detects paper trading and impossible fills using real-time broker data, historical quote capture, time-window tolerance, and confidence scoring. It supports entry-time verification, order size analysis, red flag detection, and a tiered confidence scoring system across 6 real-time data sources (Webull, Tastytrade, Schwab, IBKR, Robinhood, yfinance). Async broker integrations use thread-safe bridge patterns. IBKR, Tastytrade, and Robinhood integrations are robust, with specific features like OAuth2 authentication and TOTP 2FA. Extended Hours Trading Support is enabled across major US brokers with per-broker settings and specific implementation details for Schwab, Alpaca, IBKR, Robinhood, Webull, and Tastytrade.

The system supports a dual-mode channel system for simultaneous execution and signal forwarding, FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection. It handles market orders, comprehensive PNL page filtering, and per-channel position sizing. Per-channel risk settings allow independent operation, supporting 4-tier profit targets with customizable trim quantities, Market/Limit trim order modes, trailing stops, and Leave Runner functionality. Per-Channel Slippage Protection allows channel-specific thresholds. Exit Strategy Mode allows configuration per channel to follow trader signals, automated risk management, or both. Position Matching for Ambiguous Exit Signals automatically links exit signals to the most recent open position. The Trade Monitor feature automatically detects and posts broker-executed trades as BTO/STC signals to Discord.

The Enhanced Portfolio Simulation Engine v2.0 provides industry-grade portfolio analysis with Monte Carlo Simulation, Theta Decay Modeling, Correlation/Concentration Risk Analysis, Risk Scenario Presets, and Comprehensive Portfolio Projection. The Copy Trader 1:1 Performance Report evaluates a trader's actual performance, and the Risk Optimizer finds optimal position sizing.

Dual-Action Channel Mappings support simultaneous execution and signal forwarding. Telegram Integration supports reading trading signals from Telegram groups/channels. Market-Specific Channel Pages provide dedicated management for India Markets (NSE/BSE/MCX with DhanQ, Upstox, Zerodha), and Canada Markets (TSX/CSE/NEO with Questrade). India Markets Page features a unified broker selector, compact stat cards, tabbed data views, and unified API endpoints, ensuring market isolation.

The Conditional Order Monitoring System monitors price conditions and executes orders when triggered, supporting signals with "over/above" and "under/below" triggers, SL/PT, and position sizing, using a three-tier price monitoring fallback. The Expiry Resolver Service automatically picks the next valid expiry for Indian F&O signals when not specified.

Filled Orders Tracking syncs filled orders from broker APIs into a local database table, with automatic sync, deduplication, and multi-broker support. India Broker Sync extends BrokerSyncService to sync positions and orders from all connected India brokers using async-safe patterns. Execution-Based P&L Tracking provides professional-grade P&L calculation based on actual broker fills, including slippage tracking, latency metrics, and race condition protection. The Pending Order Metadata Bridge captures signal context at order placement and hydrates execution_lots when fills arrive via BrokerSyncService.

A Two-Tier P&L Architecture provides separation between theoretical signal performance and actual broker execution results. It includes Signal P&L (broker-agnostic, theoretical performance) and Execution P&L (per-broker entries showing actual fills, slippage, and latency). Key features include multi-broker attribution, channel and user filtering, exit source tracking, and a master-detail UX pattern with expandable rows.

The Bot Lifecycle Manager provides centralized control for bot stop/restart operations via system tray and web GUI, including REST API endpoints, a dashboard control panel, graceful shutdown signaling, and packaged executable restart handling.

The Signal Tracking System provides comprehensive lifecycle tracking for all signals from detection through broker execution with full audit trails. The QA Workflow Validation System provides comprehensive registry-based validation ensuring the complete signal-to-execution pipeline remains intact.

### OMS/RMS Architecture (January 2026)

The Order Management System (OMS) and Risk Management System (RMS) provide industry-grade dynamic SL/PT management for signals that update via Discord message edits (C1apped-style) or WaxUI update patterns.

**Core Services** (src/services/):
- **WaxUI Entry Registry**: Links update signals to original entries using ticker matching, with holding state tracking (Full→Most→Majority→Half→Runners→Closed), profit ladder parsing, and trailing stop detection
- **Exit Order Arbiter**: Arbitrates between signal-driven and risk-driven exit requests using precedence matrix (Manual > Circuit Breaker > Signal/Risk/Hybrid), enforcing the CRITICAL rule that SL can NEVER be lowered in hybrid mode
- **Signal Exit Manager**: Manages complete order lifecycle with broker-aware modify flow (Alpaca/Schwab/IBKR use REPLACE, Robinhood/Webull/Tastytrade use cancel+new), debouncing (100ms window), and idempotent exit handling
- **Circuit Breaker**: Emergency trading halt controls with global/per-channel halt, daily loss limit enforcement, position count limits, and error threshold tracking

**Exit Strategy Modes**:
- **Signal Mode**: Exits follow trader signals exactly, trailing/channel SL ignored
- **Risk Mode**: Exits follow channel risk settings (trailing stops), signal SL ignored
- **Hybrid Mode**: Uses TIGHTER protection (higher SL for long positions), SL can only move UP

**Database Schema Additions**:
- `signal_instances`: Added discord_message_id, original_sl, current_sl, sl_version (optimistic locking), exit_processed (idempotency), exit_source, broker columns
- `channels`: Added signal_update_automation, exit_strategy_mode_override, use_global_risk_settings, channel_daily_loss_limit, circuit_breaker_enabled columns
- `global_risk_settings`: New table for enable_signal_update_automation, exit_strategy_mode, enable_circuit_breaker, global_daily_loss_limit
- `risk_events`: Immutable audit log for all SL changes, exits, and PT hits

**on_message_edit Handler**: Detects Discord message edits on tracked signals, parses updated SL/PT from embeds, routes through ExitOrderArbiter, updates broker orders via SignalExitManager with full audit logging. Gates with `signal_update_automation` check before processing.

**Position Monitor Integration**: The risk/position_monitor.py now integrates with ExitOrderArbiter in hybrid mode. Exit decisions route through the arbiter using appropriate source tags ('trailing' for trailing stops, 'channel' for PT/SL hits). This ensures hybrid mode enforces the "SL can never be lowered" rule consistently.

**API Endpoints**:
- `GET /api/settings/global-risk`: Fetch global OMS/RMS settings
- `POST /api/settings/global-risk`: Update global OMS/RMS settings

**Feature Defaults**: All new features default to OFF to prevent surprise behavior changes for existing users (grandfather strategy).

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, Robinhood, Charles Schwab, Questrade, Upstox, Zerodha, and DhanQ. Upstox Integration provides V3 HFT API trading for Indian markets. Charles Schwab Integration provides OAuth2-authenticated trading with automatic token refresh, handled by a SchwabTokenManager singleton. Automatic OAuth Callback implements an industry-standard OAuth flow with a temporary HTTPS callback server, PKCE for security, automatic code capture and token exchange, secure token storage using OS keyring, and multi-account support. A Full US Broker QA Pipeline provides consistent integration patterns across all supported US brokers, including BrokerSyncService position/order syncing, SignalVerificationService real-time quotes, RiskManager position monitoring, conditional order routing support, and System Health status checks. UI templates use consistent broker identifiers for channel configuration.

The License Validation System provides industry-standard license activation integrated into the startup splash screen with a state machine controller, background validation worker, trial activation, subscription key entry, and offline grace period. The system emphasizes user experience through an interactive setup wizard, GUI-based credential management, and automatic license renewal. The Discord bot runs in a dedicated thread. Broker credentials are loaded hierarchically. Discord channel IDs and all bot settings, including signal regex patterns and allowed author/guild IDs, are GUI-manageable and stored in SQLite. Per-channel risk management can override global defaults. Security features include admin password management, rate limiting on login attempts, session-based authentication, and local password recovery.

## External Dependencies

- **Python**: 3.8+
- **PySide6** or **PyQt5**: Setup wizard GUI
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
- **robin-stocks**: Robinhood brokerage integration
- **pyotp**: TOTP 2FA code generation
- **Telethon**: Telegram user client
- **httpx**: HTTP client for Schwab API
- **ALPHA_VANTAGE_API_KEY**: Market data
- **FINNHUB_API_KEY**: Market data
- **GMAIL_APP_PASSWORD**: For Gmail SMTP
- **SMTP_PASSWORD**: For custom SMTP