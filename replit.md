# BotifyTrades - Discord Trading Bot

## Overview
BotifyTrades is a cross-platform Discord self-bot designed for automated stock and options trading across multiple brokers including Webull, Alpaca, Interactive Brokers, Tastytrade, and Robinhood. It offers automated trading, advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The bot monitors Discord for trading signals, executes trades with pre-trade swing analysis, AI-powered post-trade analysis, and interactive commands, all managed via a Flask web control panel. The project's core purpose is to provide a robust, automated trading solution, enhancing user control and analytical capabilities within a Discord-centric workflow, with a focus on comprehensive automation and analytical tools.

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
The bot features a Flask-based web control panel with a dark theme, real-time dashboards, dynamic channel management, live trade monitoring, and a System Health Page. Broker-specific Live Analytics pages emulate Webull/Thinkorswim-style dashboards. An integrated AI chat assistant provides smart FAQ and intent-based support. The options trading interface is optimized for performance, enabling strike-targeted lookup and displaying detailed order inputs with Greeks.

### Technical Implementations
Core technologies include `discord.py-self` and `webull`. It employs a true dual-broker architecture for live and paper trading, with platform-specific credential encryption. A separate thread manages the web GUI, communicating via SQLite. Order execution uses an asynchronous, queue-based system. Signal parsing follows a multi-layer approach: learned formats from a database (AI-taught), built-in regex patterns, and AI fallback. The system supports per-channel user filtering and a "TRADE IDEA" format. Risk management includes automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all GUI-configurable and stored in SQLite. Pre-trade analysis uses technical indicators, and post-execution analysis leverages OpenAI GPT models. Real-time market data is integrated, and interactive Discord commands enable on-demand analysis. The Auto Signal Conversion system executes stock alerts as Alpaca BRACKET ORDERs. Position sizing applies correctly to paper trades. An error monitoring system provides automatic detection, logging, and AI assistant contextual help. Licensing involves server-side validation with machine binding.

### AI-Powered Signal Format Learning
The system includes a "teach once, use forever" feature for learning new signal formats. Users can teach new formats via a chatbot, and the AI analyzes the format to create a reusable parsing template. Learned formats are stored in a `signal_formats` database table with regex patterns and field mappings, and parse results are cached. Management of these formats is available via chatbot commands or an API. The fallback hierarchy for signal parsing is learned formats, then built-in regex, then AI parsing.

### Feature Specifications
The system supports a dual-mode channel system for simultaneous execution and tracking with FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection. It handles market orders, comprehensive PNL page filtering, and per-channel position sizing. A Portfolio Simulation Engine projects portfolio growth. Authentication includes a setup wizard, secure login, password recovery, and a waitlist/referral system. The dashboard features live price refresh from Webull. Per-channel risk settings allow independent operation, supporting 3-tier profit targets with partial exits and trailing stops. A mandatory user agreement/risk disclosure is stored persistently.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, and Robinhood. The system emphasizes user experience through an interactive setup wizard, GUI-based credential management, automatic license renewal, and extensive documentation. Deployment options include Windows, Linux (with systemd), and AWS EC2. The Discord bot runs in a dedicated thread with an isolated asyncio event loop. Broker credentials are loaded hierarchically. Discord channel IDs and all bot settings, including signal regex patterns and allowed author/guild IDs, are GUI-manageable and stored in SQLite. Per-channel risk management can override global defaults. The `/packaging/` directory consolidates platform-specific build scripts. The `/license/` module handles licensing, supporting legacy, machine-bound, and activation-based licenses with a dedicated GUI. The BrokerSyncService handles case-insensitive broker name matching. Options data retrieval prioritizes Webull for live prices. A unified position key format (`{BROKER}_{SYMBOL}_{STRIKE}_{EXPIRY}_{C/P}`) is used across the system. The system employs a dual-build license architecture separating Admin and User deployments.

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