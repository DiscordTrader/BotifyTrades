# BotifyTrades - Multi-Platform Trading Bot

## Overview
BotifyTrades is a cross-platform trading automation bot for Discord and Telegram, designed for automated stock and options trading across multiple brokers in the USA, Canada, and India. It offers automated execution, advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The bot monitors messaging platforms for trading signals, executes trades with pre-trade swing analysis, AI-powered post-trade analysis, and interactive commands, all managed via a Flask web control panel. The project aims to provide a robust, automated trading solution, enhancing user control and analytical capabilities within a messaging-centric workflow, with a focus on comprehensive automation and analytical tools.

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
The bot features a Flask-based web control panel with a dark theme, real-time dashboards, dynamic channel management, live trade monitoring, and a System Health Page. Broker-specific Live Analytics pages emulate Webull/Thinkorswim-style dashboards. An integrated AI chat assistant provides smart FAQ and intent-based support. The options trading interface is optimized for performance, enabling strike-targeted lookup and displaying detailed order inputs with Greeks. A PySide6-based setup wizard guides first-time users through configuration.

### Technical Implementations
Core technologies include `discord.py-self` and `webull`. It employs a true dual-broker architecture for live and paper trading, with platform-specific credential encryption. Order execution uses an asynchronous, queue-based system. Signal parsing follows a multi-layer approach: learned formats from a database (AI-taught), built-in regex patterns (supporting both US and India formats), and AI fallback. This includes support for Indian market signals (e.g., "BUY NIFTY 24000 CE @ 145"), DTE notation (e.g., "0DTE"), Bishop format (multi-line entry/exit), Discord Embed extraction, and EvaPanda format (embed-based with "Open"/"Close" titles). Risk management includes automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all GUI-configurable and stored in SQLite. Pre-trade analysis uses technical indicators, and post-execution analysis leverages OpenAI GPT models. Real-time market data is integrated, and interactive Discord commands enable on-demand analysis. The Auto Signal Conversion system executes stock alerts as Alpaca BRACKET ORDERs. An error monitoring system provides automatic detection, logging, and AI assistant contextual help. A "teach once, use forever" feature allows users to teach new signal formats via a chatbot.

The **Signal Verification Service** (`services/signal_verification.py`) detects paper trading and impossible fills using real-time broker data (Webull, Tastytrade, Alpaca) prioritized over delayed sources (yfinance), historical quote capture, time-window tolerance (±30 seconds), and confidence scoring. It identifies red flags like IMPOSSIBLE_FILL and STALE_QUOTE.

### Feature Specifications
The system supports a dual-mode channel system for simultaneous execution and signal forwarding, FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection. It handles market orders, comprehensive PNL page filtering, and per-channel position sizing. Per-channel risk settings allow independent operation, supporting 4-tier profit targets with customizable trim quantities, Market/Limit trim order modes, trailing stops, and **Leave Runner functionality**. **Exit Strategy Mode** allows configuration per channel to follow trader signals (`signal`), automated risk management (`risk`), or both (`hybrid`). **Position Matching for Ambiguous Exit Signals** automatically links exit signals to the most recent open position from that channel. The Trade Monitor feature automatically detects and posts broker-executed trades as BTO/STC signals to Discord. A debug report system allows users to submit filtered error logs.

The **Portfolio Simulation Engine** (`services/simulation.py`) projects portfolio growth using various position sizing modes (`fixed`, `percent_start`, `percent_current`), trade validation, a daily realism model, and dollar-cost slippage. The **Copy Trader 1:1 Performance Report** (`services/simulation.py`) evaluates a trader's actual performance using original trade sizes, calculating capital requirements and performance metrics (return %, win rate, drawdown). The **Risk Optimizer** (`services/simulation.py`) finds optimal position sizing for a custom portfolio using the enhanced simulation engine, testing various percent and fixed-dollar amounts, employing an industry-grade scoring formula, and providing detailed comparison tables and rationale.

**Dual-Action Channel Mappings** support simultaneous execution and signal forwarding via `execute_on_source` and `forward_enabled` flags, with flexible destination types (`webhook` or `channel`).

**Telegram Integration** supports reading trading signals from Telegram groups/channels using a Telethon user client. It features a cross-thread architecture, unified signal processing with Discord, GUI management of Telegram settings, session persistence, and channel-aware routing for independent risk settings and broker selection. Per-channel settings include broker override, default quantity (applied only when signal lacks explicit quantity), position size percentage, exit strategy mode (signal/risk/hybrid), and full risk management configuration (profit targets, stop loss, trailing stops). The unified channel lookup (`get_channel_by_telegram_id`) normalizes Telegram IDs with -100 prefix handling for proper database matching.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, Robinhood, Questrade, Upstox, Zerodha, and DhanQ. The system emphasizes user experience through an interactive setup wizard, GUI-based credential management, and automatic license renewal. The Discord bot runs in a dedicated thread with an isolated asyncio event loop. Broker credentials are loaded hierarchically. Discord channel IDs and all bot settings, including signal regex patterns and allowed author/guild IDs, are GUI-manageable and stored in SQLite. Per-channel risk management can override global defaults. The system employs a dual-build license architecture separating Admin and User deployments.

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
- **ALPHA_VANTAGE_API_KEY**: Market data
- **FINNHUB_API_KEY**: Market data
- **GMAIL_APP_PASSWORD**: For Gmail SMTP
- **SMTP_PASSWORD**: For custom SMTP