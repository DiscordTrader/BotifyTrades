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

**Unified Signal Parsing Pipeline**: A 5-tier architecture for signal detection with security gating, including embed parsers, signal format registries, trader-specific parsers, standard BTO/STC regex, and an AI Fallback (OpenAI, async, confidence-gated). Specific natural language parsers are implemented for various signal formats (e.g., Foxtrades, Bronze Swings, Phoenix). AI and learned-pattern signals require admin approval and meet confidence thresholds before execution. Signal deduplication is implemented with a 5-minute TTL.

**Bishop Signal Parser** (`src/signals/parser.py`, `src/selfbot_webull.py`): Parses Market Bishop format signals with entry range handling:
- Entry signals: "**Option:** SOFI 24.5 P 2/20 **Entry:** 1.58-1.60"
- Trim signals: "Trimming CAT 640 C 1/16 @$11.25"
- Exit signals: "Got stopped out at $1.65"
- **Entry Range Handling** (January 2026): When entry has a range (e.g., 1.58-1.60), the bot uses the HIGHER price for order execution to improve fill probability

**Sir Goldman Signal Parser** (`src/signals/sir_goldman_parser.py`, February 2026): Parses Sir Goldman embed-based signals:
- Entry signals: "ENTRY | **$SPX 6780p @ 2.45 lotto**" → BTO SPX 6780P @ 2.45
- Trim signals: "TRIM | **$SPX 3.2! +31%**" → STC with position lookup
- Exit signals: "EXIT | **Out rest here at BE**" → STC with breakeven handling
- **0DTE Expiry Default**: Entry signals without explicit expiry default to today's date (0DTE/lotto assumption)
- **Position Lookup for Exits**: TRIM/EXIT signals that lack strike/expiry info automatically lookup the original BTO position from the database to get complete contract details

**Risk Management**: Features GUI-configurable automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all stored in SQLite. Includes pre-trade analysis, post-execution analysis with OpenAI GPT models, real-time market data integration, and interactive Discord commands. An error monitoring system provides automatic detection, logging, and AI assistant contextual help. A dual-mode channel system for simultaneous execution and signal forwarding, FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection are supported. Per-channel risk settings allow independent operation, including 4-tier profit targets, trailing stops, and Leave Runner functionality. Position Matching handles ambiguous exit signals, and Trade Monitor detects and posts broker-executed trades.

**Enhanced Portfolio Simulation Engine v2.0**: Provides industry-grade portfolio analysis.

**Conditional Order Monitoring System**: Monitors price conditions and executes orders when triggered. Features automatic monitor upgrade mechanism - when brokers register after order restoration (during startup), monitors using Finnhub/yfinance fallback automatically upgrade to use the broker's real-time data for accurate pre-market pricing.

**Limit Cap Protection** (February 2026): Prevents chasing runaway prices on conditional orders by setting a maximum limit price:
- **Per-channel configuration**: Enable/disable and set cap percentage via Trading → Execution page (LimCap toggle)
- **Calculation**: limit_price = trigger_price × (1 + limit_cap_pct/100). E.g., trigger $2.60 + 5% cap = $2.73 max buy price
- **Execution**: Order fills at market or better up to limit_price; won't fill if price already ran beyond cap
- **Order Chaser Integration**: limit_cap_price acts as absolute ceiling in max_chase_price calculation (min of limit_cap, slippage, entry_range)
- **Interaction with Slippage**: Both can coexist - effective cap = min(limit_cap_pct, slippage_max_pct)

**Filled Orders Tracking**: Syncs filled orders from broker APIs into a local database with automatic sync and deduplication.

**Execution-Based P&L Tracking**: Provides professional-grade P&L calculation, including slippage and latency metrics, with a Two-Tier P&L Architecture separating theoretical signal performance from actual broker execution.

**Order Management System (OMS) and Risk Management System (RMS)**: Provide dynamic SL/PT management via Discord message edits. The Exit Order Arbiter arbitrates between signal-driven and risk-driven exit requests. A Circuit Breaker provides emergency trading halt controls. Industry-grade Risk State Persistence ensures all risk state survives bot restarts. Enhanced Risk Management v2.0 provides Dynamic SL Escalation and Max Profit Giveback Guard.

**Follow-up SL/PT Updates** (February 2026): Signal providers can update stop-loss for both pending and filled positions:
- **Supported formats**: "SL to $X", "moving my SL to X", "SL to 15%", "moving my SL to 11%"
- **Pending orders**: Updates conditional order trigger price in database
- **Filled positions**: Applies manual override to active position cache with database persistence
- **Precedence**: Manual override > Dynamic SL > Channel default
- **Display**: Risk monitor shows [OVERRIDE] tag when manual SL is active

**Early Trailing Stop**: A percentage-based trailing stop with a breakeven-first approach that moves the stop to entry after a specified gain and then locks in profit.

**Stop Loss Order Type** (February 2026): Per-channel option to use Market or Limit orders for stop loss exits:
- **Configuration**: Trading → Risk Settings modal, under "Order Settings" section
- **Limit (default)**: Uses limit orders first, retries 3x, then switches to market orders
- **Market**: Uses market orders immediately for fastest exit when SL triggers
- **Use case**: Market orders recommended for volatile assets where SL speed is critical

**Broker-Aware Price Monitoring**: Routes quote requests to the position's connected broker with a fallback chain (other connected brokers, Finnhub, yfinance).

**Broker Health Monitor**: A centralized, thread-safe system for real-time broker connection status and buying power monitoring. It includes disconnect reason classification, fail-safe pre-trade validation, integer quantity enforcement for options, cache invalidation, and normalized broker name handling. Order processing waits for both broker connection and the first sync cycle to complete before processing signals.

**Settled Cash Validation** (January 2026): Industry-grade good faith violation prevention across all major brokers:
- **Webull**: Uses `settled_cash` field to block trades when funds are unsettled
- **Alpaca**: Uses `cash_withdrawable` and `non_marginable_buying_power` (conservative minimum)
- **Robinhood**: Uses `cash_available_for_withdrawal` as settled cash equivalent
- **Schwab**: Uses `cashAvailableForTrading` with fallback to `availableFunds`
- Pre-trade validation blocks BTO orders when settled cash is negative or insufficient
- STC orders (sell-to-close) bypass validation as they sell existing positions
- Dashboard displays Settled Cash and Unsettled Cash with color-coded warnings (red for negative)

**Unfilled Order Chaser**: Monitors pending exit orders, cancels stale ones, and replaces them with mid-price limit orders. It includes startup restoration for pending orders from the database.

**Isolated Execution Flows**: Critical architecture separating Channel Execution (direct broker trading) from Signal Routing (webhook forwarding), ensuring no cross-flow contamination.

**NDX→QQQ Conversion Service**: Enables channels with limited NDX access to trade equivalent QQQ options.

**Dynamic Position Sizing with Signal Override** (February 2026): Intelligent position size calculation based on actual buying power:
- **Signal percentage priority**: Signal provider's position size (e.g., "12.5% OF ACCOUNT") can override channel settings
- **Force My Size %**: Per-channel toggle to ignore signal's percentage and always use channel's SIZE % setting
- **Dynamic calculation**: Quantity is calculated at execution time based on actual broker buying power, not static max_position_size
- **Configuration**: Trading → Channels page, under Execute panel - toggle "Force My Size %"
- **Use case**: When signal provider suggests large allocations but you want to limit risk with smaller positions

**Per-Channel Ticker Filter** (February 2026): Restrict trading to specific symbols per channel, useful when a signal provider excels at certain tickers but underperforms on others:
- **Three modes**: OFF (trade all), ALLOW LIST (only trade listed symbols), BLOCK LIST (block listed symbols)
- **Configuration**: Trading → Execution page, click 🎯 button in Actions column
- **Filter logic**: Applied to BTO signals only (exits always go through), uses underlying symbol for options
- **Case-insensitive**: "spy, qqq" matches SPY, QQQ, etc.
- **Database fields**: `ticker_filter_mode` (off/allow/block), `ticker_filter_list` (comma-separated symbols)

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