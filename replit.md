# BotifyTrades - Multi-Platform Trading Bot

## Overview
BotifyTrades is a cross-platform trading automation bot for Discord and Telegram, designed for automated stock and options trading across multiple brokers. Its primary purpose is to make sophisticated trading accessible and efficient by integrating advanced trading functionalities within messaging platforms. Key capabilities include automated execution, advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The project targets markets in the USA and Canada, aiming to provide a robust solution for automated trading.

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

**Unified Signal Parsing Pipeline**: A 5-tier architecture for signal detection with security gating, including embed parsers, signal format registries, trader-specific parsers, standard BTO/STC regex, and an AI Fallback. Specific natural language parsers are implemented for various signal formats (e.g., Foxtrades, Bronze Swings, Phoenix). AI and learned-pattern signals require admin approval and meet confidence thresholds before execution. Signal deduplication is implemented with a 5-minute TTL.

**Bishop Signal Parser**: Parses Market Bishop format signals with entry range handling, including trim and exit signals. When an entry has a range, the bot uses the higher price for order execution.

**Sir Goldman Signal Parser**: Parses Sir Goldman embed-based signals, handling entry, trim, and exit signals. Entry signals without explicit expiry default to today's date (0DTE/lotto assumption). TRIM/EXIT signals lacking strike/expiry information automatically lookup the original BTO position from the database.

**Risk Management**: Features GUI-configurable automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all stored in SQLite. Includes pre-trade analysis, post-execution analysis with OpenAI GPT models, real-time market data integration, and interactive Discord commands. An error monitoring system provides automatic detection, logging, and AI assistant contextual help. A dual-mode channel system for simultaneous execution and signal forwarding, FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection are supported. Per-channel risk settings allow independent operation, including 4-tier profit targets, trailing stops, and Leave Runner functionality. Position Matching handles ambiguous exit signals, and Trade Monitor detects and posts broker-executed trades.

**Enhanced Portfolio Simulation Engine v2.0**: Provides industry-grade portfolio analysis.

**Performance Analytics Dashboard v2.0**: Industry-grade performance analytics page (`gui_app/performance_analytics.py`) with:
- Custom date range picker (1D/1W/1M/3M/1Y/ALL + custom start/end dates)
- Per-broker isolated performance cards (no cross-broker data mixing)
- 30+ performance metrics: P&L, win rate, profit factor, Sharpe ratio, max drawdown, expectancy, risk:reward, streaks
- Trade journal with expandable partial exit details (entry/exit prices, quantities, exit reasons)
- Paginated trade list with symbol/status filters and sorting
- Time-series breakdown charts (daily/weekly/monthly/yearly)
- Day-of-week and hour-of-day P&L heatmaps
- Edge analysis by symbol, asset type, direction, source, channel, and exit reason
- Equity curve, daily P&L bars, win/loss distribution charts (Chart.js)
- API endpoint: `/api/performance-v2` with section-based loading for efficiency

**Conditional Order Monitoring System**: Monitors price conditions and executes orders when triggered. Includes an automatic monitor upgrade mechanism that switches from Finnhub/yfinance fallback to broker's real-time data when brokers register.

**Limit Cap Protection**: Prevents chasing runaway prices on conditional orders by setting a maximum limit price. This is configurable per channel, where `limit_price = trigger_price × (1 + limit_cap_pct/100)`.

**Filled Orders Tracking**: Syncs filled orders from broker APIs into a local database with automatic sync and deduplication.

**Execution-Based P&L Tracking**: Provides professional-grade P&L calculation, including slippage and latency metrics, with a Two-Tier P&L Architecture.

**Order Management System (OMS) and Risk Management System (RMS)**: Provide dynamic SL/PT management via Discord message edits. The Exit Order Arbiter uses threading.Lock for cross-thread safety (preventing double-sells between signal STC and risk-triggered exits from different threads). A Circuit Breaker provides emergency trading halt controls. Industry-grade Risk State Persistence ensures all risk state survives bot restarts. Enhanced Risk Management v2.0 provides Dynamic SL Escalation and Max Profit Giveback Guard.

**Follow-up SL/PT Updates**: Signal providers can update stop-loss for both pending and filled positions using various formats (e.g., "SL to $X", "moving my SL to X"). These updates override dynamic or channel default settings and are displayed in the risk monitor.

**Early Trailing Stop**: A percentage-based trailing stop with a breakeven-first approach that moves the stop to entry after a specified gain and then locks in profit.

**Stop Loss Order Type**: Per-channel option to use Market or Limit orders for stop loss exits. Limit orders are the default, retrying multiple times before switching to market orders. Market orders are used immediately for fastest exit.

**SL Limit Offset**: When using Limit orders for stop loss exits, a configurable percentage offset is added between the trigger price and the limit price (default 3%) to improve fill probability.

**Entry Order Mode**: Per-channel option to force market orders on BTO entries for faster fills, prioritizing speed over price, or use limit orders for better fill control.

**Broker-Aware Price Monitoring**: Routes quote requests to the position's connected broker with a fallback chain (other connected brokers, Finnhub, yfinance).

**Broker Health Monitor**: A centralized, thread-safe system for real-time broker connection status and buying power monitoring. Includes disconnect reason classification, fail-safe pre-trade validation, integer quantity enforcement for options, cache invalidation, and normalized broker name handling.

**Settled Cash Validation**: Industry-grade good faith violation prevention across all major brokers. Pre-trade validation blocks BTO orders when settled cash is negative or insufficient. STC orders bypass validation.

**Unfilled Order Chaser**: Monitors pending exit orders, cancels stale ones, and replaces them with mid-price limit orders, with startup restoration for pending orders.

**Notification System**: Real-time alerting for critical trading events via Discord webhooks and desktop browser notifications. Includes notification bell UI in the dashboard with popup panel, configurable webhook URL, and polling-based desktop notifications. Supported alert types: order failures, stop loss triggers, profit target hits, and order fills (BTO/STC).

**Isolated Execution Flows**: Critical architecture separating Channel Execution (direct broker trading) from Signal Routing (webhook forwarding).

**NDX→QQQ Conversion Service**: Enables channels with limited NDX access to trade equivalent QQQ options.

**Dynamic Position Sizing with Signal Override**: Intelligent position size calculation based on actual buying power. Signal provider's percentage (e.g., "12.5% OF ACCOUNT") can override channel settings, or a "Force My Size %" toggle can be used to ignore signal percentages.

**Per-Channel Ticker Filter**: Restricts trading to specific symbols per channel, with modes for OFF, ALLOW LIST, or BLOCK LIST. Applied to BTO signals only, using the underlying symbol for options.

**Channel Scanner**: Admin-only feature that scans Discord channel message history (up to 2000 messages) using pure pattern matching (no AI) to discover signal formats. Normalizes messages by replacing tickers/prices/strikes/expiries with placeholders, clusters similar templates, and generates regex patterns. Detected patterns are saved as "pending" and require admin approval before activation in the signal parsing pipeline. UI accessible via "Scan Formats" button on channel cards (admin build only), with a modal showing scan results, pattern cards with action type/confidence/examples, and pattern management (approve/disable/delete). Service: `src/services/channel_scanner.py`, API: `/api/channels/<id>/scan` + `/api/scanner/*`.

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