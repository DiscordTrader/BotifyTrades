# BotifyTrades - Multi-Platform Trading Bot

## Overview
BotifyTrades is a cross-platform trading automation bot for Discord and Telegram, designed for automated stock and options trading across multiple brokers. Its primary purpose is to make sophisticated trading accessible and efficient by integrating advanced trading functionalities within messaging platforms. Key capabilities include automated execution, advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The project targets markets in the USA and Canada, aiming to provide a robust solution for automated trading and make sophisticated trading accessible and efficient.

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
The bot features a Flask-based web control panel with a dark theme, real-time dashboards, dynamic channel management, and live trade monitoring. Broker-specific Live Analytics pages and an integrated AI chat assistant are included. The options trading interface is optimized for strike-targeted lookup and detailed order inputs with Greeks. A PySide6-based setup wizard guides first-time users.

### Technical Implementations
Core technologies include `discord.py-self` for Discord and `webull` for brokerage. It utilizes a true dual-broker architecture for live and paper trading, with platform-specific credential encryption and an asynchronous, queue-based order execution system.

**Unified Signal Parsing Pipeline**: A 5-tier architecture for signal detection with security gating, including embed parsers, signal format registries, trader-specific parsers, standard BTO/STC regex, and an AI Fallback. Natural language parsers are implemented for various signal formats, with AI and learned-pattern signals requiring admin approval and confidence thresholds. Signal deduplication is implemented with a 5-minute TTL.

**Risk Management**: Features GUI-configurable automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all stored in SQLite. Includes pre-trade analysis, post-execution analysis with OpenAI GPT models, real-time market data integration, and interactive Discord commands. An error monitoring system provides automatic detection, logging, and AI assistant contextual help. A dual-mode channel system for simultaneous execution and signal forwarding, FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection are supported. Per-channel risk settings allow independent operation, including 4-tier profit targets, trailing stops, and Leave Runner functionality. Position Matching handles ambiguous exit signals, and Trade Monitor detects and posts broker-executed trades.

**Enhanced Portfolio Simulation Engine v2.0**: Provides industry-grade portfolio analysis.

**Performance Analytics Dashboard v2.0**: Industry-grade performance analytics page with custom date range picker, per-broker isolated performance cards, 30+ performance metrics, a trade journal, paginated trade list, time-series breakdown charts, P&L heatmaps, edge analysis, and various financial charts (Chart.js).

**Conditional Order Monitoring System**: Monitors price conditions and executes orders when triggered, with an automatic monitor upgrade mechanism.

**Limit Cap Protection**: Prevents chasing runaway prices on conditional orders by setting a maximum limit price, configurable per channel.

**Filled Orders Tracking**: Syncs filled orders from broker APIs into a local database with automatic sync and deduplication.

**Execution-Based P&L Tracking**: Provides professional-grade P&L calculation, including slippage and latency metrics, with a Two-Tier P&L Architecture.

**Order Management System (OMS) and Risk Management System (RMS)**: Provide dynamic SL/PT management via Discord message edits. The Exit Order Arbiter uses threading.Lock for cross-thread safety. A Circuit Breaker provides emergency trading halt controls. Industry-grade Risk State Persistence ensures all risk state survives bot restarts. Enhanced Risk Management v2.0 provides Dynamic SL Escalation and Max Profit Giveback Guard.

**Follow-up SL/PT Updates**: Signal providers can update stop-loss for both pending and filled positions using various formats.

**Early Trailing Stop**: A percentage-based trailing stop with a breakeven-first approach.

**Stop Loss Order Type**: Per-channel option to use Market or Limit orders for stop loss exits, with retries before switching to market.

**SL Limit Offset**: Configurable percentage offset for limit orders to improve fill probability.

**Entry Order Mode**: Per-channel option to force market orders on BTO entries for faster fills, or use limit orders.

**Broker-Aware Price Monitoring**: Routes quote requests to the position's connected broker with a fallback chain.

**Schwab Global 429 Rate Limit Protection**: Centralized rate limit mitigation for Schwab API with global backoff timer, escalating backoff, and priority for exit orders.

**Broker Health Monitor**: A centralized, thread-safe system for real-time broker connection status and buying power monitoring.

**Settled Cash Validation**: Industry-grade good faith violation prevention across all major brokers.

**Unfilled Order Chaser**: Monitors pending exit orders, cancels stale ones, and replaces them with mid-price limit orders.

**Notification System**: Real-time alerting for critical trading events via Discord webhooks and desktop browser notifications.

**Log File Upload & Debug**: The AI chat assistant supports uploading .log/.txt/.csv files for automated debugging, categorizing lines, building context, and using OpenAI for analysis.

**Isolated Execution Flows**: Critical architecture separating Channel Execution from Signal Routing.

**NDX→QQQ Conversion Service**: Enables channels with limited NDX access to trade equivalent QQQ options.

**Dynamic Position Sizing with Signal Override**: Intelligent position size calculation based on actual buying power, with signal provider override capabilities.

**Per-Channel Ticker Filter**: Restricts trading to specific symbols per channel, with modes for OFF, ALLOW LIST, or BLOCK LIST.

**Channel Scanner**: Admin-only feature that scans Discord channel message history to discover signal formats, normalize messages, cluster templates, and generate regex patterns for admin approval.

**Universal Order Placement Resilience Layer**: A 3-layer architecture providing fault tolerance across all 11 brokers, including error classification, circuit breakers, and orchestrated retry budgets.

**Live Monitoring Performance Layer**: Industry-grade position monitoring with zero-lag UX. Features a background snapshot daemon, cached data retrieval, real-time frontend updates, quick-close buttons, toast notifications, and a Dashboard Risk Engine with status indicators for each position.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, Robinhood, Charles Schwab, Questrade, Upstox, Zerodha, and DhanQ. A License Validation System provides industry-standard license activation. The Discord bot runs in a dedicated thread. Broker credentials and all bot settings are GUI-manageable and stored in SQLite. Security features include admin password management, rate limiting, and session-based authentication.

## External Dependencies

- **Python**: 3.8+
- **PySide6**: Setup wizard GUI
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