# BotifyTrades - Discord Trading Bot

## Version
**v3.5.0 - MILESTONE 5** (2025-12-18)

## Recent Changes (Milestone 5) - Database Synchronization Fixes
- **Fixed _save_trade_to_db() Signature**: Corrected function to use dict parameter instead of kwargs
- **Order ID Tracking**: Now saves order_id to database for proper trade-to-order matching
- **Quantity Sync from Broker**: Database quantities now sync with actual broker positions in real-time
- **60-Second Grace Period**: PENDING trades won't be prematurely closed (prevents race condition)
- **Broker Name Normalization**: All broker names now saved as uppercase for consistency
- **Close Reason Tracking**: Added close_reason field when sync closes positions

## Previous Milestone (4)
- **Alpaca Index Options Rejection**: Clear error when attempting index options on Alpaca
  - SPX, SPXW, NDX, NDXP, RUT, VIX, etc. NOT supported on Alpaca (CBOE cash-settled)
  - Error message suggests using Tastytrade/IBKR or QQQ/SPY alternatives
- **Enhanced Option Order Messages**: Meaningful success/failure messages with details
  - Success: Shows action, quantity, symbol, strike, expiry, price, order type, total cost
  - Failures: Specific error messages for invalid symbols, insufficient funds, expired contracts, account issues
- **Robinhood Broker Integration**: Added support for Robinhood brokerage via robin-stocks library
  - Stocks: Market, Limit, Stop orders supported
  - Options: Limit orders only (Robinhood API constraint)
  - 2FA Authentication: TOTP-based authentication with pyotp
  - WARNING: No paper trading mode - all trades are LIVE
  - Unofficial API: May break if Robinhood updates backend
- **GitHub README Enhancement**: Comprehensive README for better search visibility

## Previous Milestone (3)
- **SPX/NDX Shorthand Format**: Added support for quick 0DTE signals like "6900c" → BTO 1 SPX 6900C, auto-detects symbol based on strike (≥10000 = NDX, <10000 = SPX)
- **Slippage Settings Fix**: Fixed bug where slippage protection was not respecting GUI toggle - now reads directly from slippage_settings table
- **Message Purge System**: Configurable retention dropdown (1/3/7/14/30 days) in Signals tab
- **Live Position Status Fix**: Live brokerage positions now correctly show "OPEN" status when merged with broker data
- **TRADE IDEA Fallback**: Auto Signal Conversion now falls back to originating channel's broker settings when target not configured

## Overview
BotifyTrades is a cross-platform Discord self-bot designed for automated stock and options trading. It provides automated trading across Webull, Alpaca, Interactive Brokers, Tastytrade, and Robinhood, featuring advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The bot monitors Discord for trading signals, executes trades with pre-trade swing analysis, AI-powered post-trade analysis, and interactive commands, all managed via a Flask web control panel. The project aims to provide a robust, automated trading solution, enhancing user control and analytical capabilities in a Discord-centric workflow, with a focus on comprehensive automation and analytical tools.

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
Core technologies include `discord.py-self` and `webull`. The system employs a true dual-broker architecture for live and paper trading, with platform-specific credential encryption. A separate thread runs the web GUI, communicating via SQLite. Order execution is managed by an asynchronous, queue-based system. Signal parsing uses a multi-layer approach: 1) Learned formats from database (AI-taught), 2) Built-in regex patterns, 3) AI fallback for unrecognized formats. The system supports per-channel user filtering and a "TRADE IDEA" format. Risk management features automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all configurable via the GUI and stored in SQLite. Pre-trade analysis uses technical indicators, and post-execution analysis leverages OpenAI GPT models. Real-time market data is integrated, and interactive Discord commands enable on-demand analysis. The Auto Signal Conversion system executes stock alerts as Alpaca BRACKET ORDERs. Position sizing correctly applies to paper trades. An error monitoring system provides automatic detection, logging, and AI assistant contextual help. Licensing involves server-side validation with machine binding and an offline grace period.

### AI-Powered Signal Format Learning
The system features a "teach once, use forever" approach for learning new signal formats:
- **Teaching via Chatbot**: Users can teach new formats by saying "Teach this format: [signal example]"
- **One-time AI Cost**: AI analyzes the format once and creates a reusable parsing template
- **Database Storage**: Learned formats are stored in `signal_formats` table with regex patterns and field mappings
- **Caching**: Parse results are cached in `signal_format_cache` to avoid duplicate processing
- **Management**: View, enable/disable, or delete formats via chatbot commands or API (`/api/signal-formats`)
- **Fallback Hierarchy**: Learned formats > Built-in regex > AI parsing (if OpenAI key configured)
- **Key Files**: `gui_app/format_trainer.py` (FormatTrainer service), `gui_app/chat_assistant.py` (chat intents)

### Feature Specifications
The system supports a dual-mode channel system for simultaneous execution and tracking with FIFO-based P&L tracking, and Multi-Broker Execution for trades across multiple accounts with per-channel broker selection. It handles market orders, comprehensive PNL page filtering, and per-channel position sizing. A Portfolio Simulation Engine projects portfolio growth. Authentication includes a setup wizard, secure login, password recovery, and a waitlist/referral system. The dashboard features live price refresh from Webull. Per-channel risk settings allow independent operation, supporting 3-tier profit targets with partial exits and trailing stops. A mandatory user agreement/risk disclosure is stored persistently.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, and Robinhood. The system emphasizes user experience through an interactive setup wizard, GUI-based credential management, automatic license renewal, and extensive documentation. Deployment options include Windows, Linux (with systemd), and AWS EC2. The Discord bot runs in a dedicated thread with an isolated asyncio event loop. Broker credentials are loaded hierarchically. Discord channel IDs and all bot settings, including signal regex patterns and allowed author/guild IDs, are GUI-manageable and stored in SQLite. Per-channel risk management can override global defaults. The `/packaging/` directory consolidates platform-specific build scripts. The `/license/` module handles licensing, supporting legacy, machine-bound, and activation-based licenses with a dedicated GUI. The BrokerSyncService handles case-insensitive broker name matching. Options data retrieval prioritizes Webull for live prices. A unified position key format (`{BROKER}_{SYMBOL}_{STRIKE}_{EXPIRY}_{C/P}`) is used across the system. The system employs a dual-build license architecture separating Admin and User deployments for license management and bot operation.

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
- **robin-stocks**: Robinhood brokerage integration (unofficial)
- **pyotp**: TOTP 2FA code generation for Robinhood
- **ALPHA_VANTAGE_API_KEY**: Market data
- **FINNHUB_API_KEY**: Market data
- **OPENAI_API_KEY**: AI analysis
- **ALPACA_API_KEY**: Alpaca brokerage
- **ALPACA_SECRET_KEY**: Alpaca brokerage
- **GMAIL_APP_PASSWORD**: For Gmail SMTP
- **SMTP_PASSWORD**: For custom SMTP