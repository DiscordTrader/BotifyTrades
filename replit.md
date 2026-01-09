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
Core technologies include `discord.py-self` and `webull`. It employs a true dual-broker architecture for live and paper trading, with platform-specific credential encryption. Order execution uses an asynchronous, queue-based system. Signal parsing uses a multi-layer approach supporting learned formats, built-in regex, and AI fallback. Risk management includes automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all GUI-configurable and stored in SQLite. Pre-trade analysis uses technical indicators, and post-execution analysis leverages OpenAI GPT models. Real-time market data is integrated, and interactive Discord commands enable on-demand analysis. The Auto Signal Conversion system executes stock alerts as Alpaca BRACKET ORDERs. An error monitoring system provides automatic detection, logging, and AI assistant contextual help.

The **Signal Verification Service** detects paper trading and impossible fills using real-time broker data, historical quote capture, time-window tolerance, and confidence scoring. Key features include entry-time verification, order size analysis, red flag detection (e.g., position size exceeding liquidity, impossible fills, extreme price deviation), and a tiered confidence scoring system.

The system supports a dual-mode channel system for simultaneous execution and signal forwarding, FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection. It handles market orders, comprehensive PNL page filtering, and per-channel position sizing. Per-channel risk settings allow independent operation, supporting 4-tier profit targets with customizable trim quantities, Market/Limit trim order modes, trailing stops, and **Leave Runner functionality**. **Exit Strategy Mode** allows configuration per channel to follow trader signals, automated risk management, or both. **Position Matching for Ambiguous Exit Signals** automatically links exit signals to the most recent open position. The Trade Monitor feature automatically detects and posts broker-executed trades as BTO/STC signals to Discord.

The **Enhanced Portfolio Simulation Engine v2.0** provides industry-grade portfolio analysis with Monte Carlo Simulation, per-trade Theta Decay Modeling, Correlation/Concentration Risk Analysis, Risk Scenario Presets, and Comprehensive Portfolio Projection. The **Copy Trader 1:1 Performance Report** evaluates a trader's actual performance, and the **Risk Optimizer** finds optimal position sizing.

**Dual-Action Channel Mappings** support simultaneous execution and signal forwarding via `execute_on_source` and `forward_enabled` flags, with flexible destination types. **Telegram Integration** supports reading trading signals from Telegram groups/channels. **Market-Specific Channel Pages** provide dedicated management for India Markets (NSE/BSE/MCX with DhanQ, Upstox, Zerodha), and Canada Markets (TSX/CSE/NEO with Questrade).

The **Conditional Order Monitoring System** monitors price conditions and executes orders when triggered, supporting signals with "over/above" and "under/below" triggers, SL/PT, and position sizing. It uses a three-tier price monitoring fallback (broker-native APIs → Finnhub API → yfinance). The **Expiry Resolver Service** automatically picks the next valid expiry for Indian F&O signals when not specified.

**Filled Orders Tracking** syncs filled orders from broker APIs (Webull, Alpaca) into a local database table, featuring automatic sync, deduplication, multi-broker support, and a dedicated UI tab. **Execution-Based P&L Tracking** provides professional-grade P&L calculation based on actual broker fills rather than theoretical signal prices, including slippage tracking, latency metrics, and race condition protection. The **Pending Order Metadata Bridge** (Jan 2026) captures signal context at order placement (channel_id, message_id, timestamps, analyst sizing, PositionSizingService outputs) and hydrates execution_lots when fills arrive via BrokerSyncService. Uses BEGIN IMMEDIATE atomic transactions for FIFO integrity in concurrent STC fills.

The **Bot Lifecycle Manager** (Jan 2026) provides centralized control for bot stop/restart operations via system tray and web GUI. Features include REST API endpoints (`/api/bot/status`, `/api/bot/stop`, `/api/bot/restart`), dashboard control panel with gradient buttons and status indicators, graceful shutdown signaling, and packaged executable restart handling (Windows startfile, macOS open command, Linux exec).

The **Signal Tracking System** provides comprehensive lifecycle tracking for all signals from detection through broker execution with full audit trails, supporting filtering, P&L tracking, and error logging. The **QA Workflow Validation System** provides comprehensive registry-based validation ensuring the complete signal-to-execution pipeline remains intact through 11 stages from Signal Detection to Risk Monitoring.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, Robinhood, Charles Schwab, Questrade, Upstox, Zerodha, and DhanQ. **Upstox Integration** provides V3 HFT API trading for Indian markets with auto-slicing and a pending order queue. **Charles Schwab Integration** provides OAuth2-authenticated trading.

The **License Validation System** provides industry-standard license activation integrated into the startup splash screen with a state machine controller, background validation worker, trial activation, subscription key entry, and offline grace period. The system emphasizes user experience through an interactive setup wizard, GUI-based credential management, and automatic license renewal. The Discord bot runs in a dedicated thread. Broker credentials are loaded hierarchically. Discord channel IDs and all bot settings, including signal regex patterns and allowed author/guild IDs, are GUI-manageable and stored in SQLite. Per-channel risk management can override global defaults. Security features include admin password management, rate limiting on login attempts, session-based authentication, and local password recovery.

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