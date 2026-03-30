# BotifyTrades — Compressed Documentation

## Overview

BotifyTrades is a production-grade, cross-platform automated trading bot designed to monitor Discord and Telegram for trade signals and execute them across multiple brokers for US and Canadian markets. It features a comprehensive Flask-based web control panel with real-time dashboards, advanced risk management, WebSocket streaming, AI-powered analysis, and detailed portfolio analytics. The project aims to provide automated trading capabilities, offering users a powerful tool for managing and optimizing their trading strategies.

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
The web control panel, built with Flask, provides real-time dashboards for broker status, live positions, P&L, and risk statuses. It includes detailed trade monitoring, performance analytics, intuitive settings, and visual feedback mechanisms like streaming indicators. A redesigned performance dashboard offers a calendar view with key metrics, daily P&L, trade counts, and cumulative P&L charts.

### Technical Implementations
- **Signal Sources**: Integrates with Discord and Telegram, using a 5-tier parsing system (dedicated parsers, regex, AI fallback) for robust signal detection, deduplication, and follow-up updates.
- **Risk Management Engine**: A multi-layered system with global and per-channel settings, configurable Stop Loss, Trailing Stop, four Profit Targets, Dynamic SL Escalation, Max Profit Giveback Guard, EMA-5 Candlestick Risk Engine, and a "Leave Runner" feature. Risk states are persistent and exit pricing prioritizes streaming hub bid/ask.
- **Position Sizing**: Per-channel percentage-based sizing uses live broker data, considering specific buying power metrics across brokers and three balance modes: "Live", "Pre-Market", and "Start-of-Day."
- **Order Execution System**: An asynchronous, queue-based system for multi-broker order execution, featuring per-channel broker selection and a Universal Order Placement Resilience Layer with error classification, circuit breakers, and retries. Includes hub-first slippage checks and an Order Chaser service.
- **Order Management System (OMS)**: Handles dynamic SL/PT management, exit order arbitration, position matching, and FIFO-based P&L tracking, supporting 12 types of exit source classifications. It features universal risk exit P&L recording, multi-lot overflow closure, broker fill price reconciliation, and consolidated fill-based P&L.
- **WebSocket Streaming**: Utilizes Webull MQTT and an optimized Schwab WebSocket system for real-time quotes and orders, providing sub-100ms pricing for conditional orders and quick trade options chains, with automatic REST fallback. Includes cross-broker streaming subscription and immediate BTO symbol subscription.
- **Daily P&L Limit System**: Per-broker daily P&L tracking against SOD equity snapshots, with configurable dollar and percentage limits for profit targets and loss limits. Max Daily Trades enforcement works independently of the P&L dollar/percentage master toggle — trade counting and locking activate whenever a trade limit is configured, even if the full P&L system is disabled. Stale P&L locks (loss/profit) are normalized when P&L is disabled so they don't block trade-limit enforcement.
- **Broker Sync Service**: Reconciles database state with actual broker states, detecting order fills/cancellations, position changes, and account updates.
- **Fill Accuracy Architecture**: A five-layer fill-to-PNL pipeline ensures accurate tracking of entry and exit fills, resolving issues with stale fill prices and ensuring proper lot closure.
- **Order Chaser Service**: Monitors unfilled exit/entry orders and replaces stale ones with better prices, tracking all STC orders (risk management and signal STCs).
- **Security & Authentication**: Implements admin account management, password hashing, email recovery, session-based authentication, rate limiting, and encrypted broker credentials, with Schwab OAuth using CSRF state tokens and PKCE.
- **Database Architecture**: Uses SQLite with WAL mode for concurrent read/write operations, storing trading data and encrypted credentials. Includes retry mechanisms for critical exit bookkeeping.
- **AI Analysis**: Integrates OpenAI GPT for pre-trade/post-trade analysis, an AI chat assistant, and AI command toggles.
- **Risk Engine Direct Exit Architecture**: Dual-path exit execution system (primary queue-based, backup daemon thread at 5s for direct calls) with an Exit Lease Manager to prevent duplicate exits.
- **Risk Engine Speed Optimizations**: Lowered interval floor, early-wake sleep chunking, cached service checks, throttled cache saves, parallel broker fetches, REST position cache, hub-first approaches, cross-broker price updates, and a staleness guard.
- **Event-Driven Fill Watch System**: Activates rapid position polling after BTO orders, with broker-specific intervals, detecting new positions or quantity increases.
- **Risk Engine Staleness Gate**: Implements pre-execution staleness protection for risk exits, blocking exits if price is unchanged for a set duration or if prices are unverified across all sources.
- **Trading212 Data Hub & Integration**: Provides a portfolio-based price cache for T212 positions, integrating with the risk engine and conditional order service, with real-time architecture and cross-broker streaming.
- **IBKRDataHub Streaming**: Provides real-time IBKR position and price streaming via `ib_insync` native events, managing `reqMktData` subscriptions and integrating with the risk engine.
- **Cross-Hub Price Sourcing**: Cascades through multiple data hubs (Webull → Schwab → IBKR → Tastytrade → T212) to find the freshest price for both stocks and options, normalizing symbols and expiry formats.
- **Unified Price Hub (Phase B - Shadow Mode)**: A singleton service wrapping all existing data hubs into a single aggregated price cache, currently in shadow mode for comparison against the risk engine's prices.
- **Conditional Order Frozen Price Detection**: `StreamingPriceMonitor` detects frozen prices, probing cross-broker streaming hubs and then broker REST APIs, with a robust fallback chain.
- **Execution Idempotency**: Prevents duplicate trade execution using per-order asyncio.Lock, set guards, and database CAS status checks.
- **Monitor Failure Recovery**: Marks orders as ERROR on monitor crash and attempts automatic restart, setting ERROR status with details if restarts fail.
- **Rate Limit Enforcement**: REST fallback calls and frozen probes check and record API calls against a rate limit tracker.
- **Risk Management Parity (Signal Routing Engine)**: Ensures full risk parity between the Position Monitor and Signal Routing Engine, incorporating EMA and early trailing stops into virtual positions.
- **Trading212 Event Loop Mismatch Fix**: Addresses `asyncio.Lock` and `aiohttp.ClientSession` binding issues to ensure proper function of conditional order monitors and position fetching.

### System Design Choices
- **Broker Isolation**: Prevents data cross-contamination by isolating each broker's streaming data.
- **Thread Safety**: All shared states are protected by locks.
- **Priority Queue Execution**: Risk management exits are prioritized over normal entries.
- **Unprotected Trades Banner**: Critical dashboard banner to identify trades lacking risk protection.
- **Hub-First Architecture**: Prioritizes cached streaming data over REST API calls.
- **Graceful Degradation**: Automatically falls back to REST polling if streaming services are unavailable.
- **Modular Broker Abstraction**: Uses a common interface for diverse broker APIs (Webull, Alpaca, Schwab, IBKR, Tastytrade, Robinhood, Trading 212).
- **Help Center**: Comprehensive `/help` route with onboarding, broker connection guides, and risk management diagrams.
- **Market Isolation**: Conditional order services for different markets operate independently.
- **Conditional Order Streaming Architecture**: Uses `StreamingPriceMonitor` and `BrokerPriceMonitor` with a robust fallback chain for price data, including brokerless monitor upgrades.
- **Risk Engine Price Flow**: Features both full cycle and incremental event-driven evaluation paths.
- **Unsettled Funds Position Sizing Fix**: Caps `sizing_base`, `buying_power`, and `options_buying_power` to `settled_cash` when available, preventing Good Faith Violations.
- **Session-Aware REST Price Guard**: REST fallback methods reject stale `last`/`lastPrice` values outside regular trading hours, accepting only bid/ask midpoint or Webull pPrice during extended hours.
- **SYNC-RISK Coordination Guard**: `broker_sync_service.py` checks the risk engine position cache before cancelling or closing trades, preventing erroneous actions due to transient broker API issues.
- **Channel Inheritance on Auto-Import**: `auto_import_manual_position` now inherits `channel_id` from recently-closed trades for consistent risk settings.
- **Advanced Tab Nesting Fix**: The `risk-tab-advanced` div in `channels.js` was nested INSIDE the `risk-tab-targets` div due to a missing `</div>` closing tag. When `switchRiskTab()` hid the targets pane, the advanced pane (as a child) was also hidden. Fixed by adding the missing closing div to make both tabs siblings. Also quoted all channel.id references in onclick handlers as strings to prevent JS precision loss on 18-19 digit Discord IDs.
- **Multi-Broker STC Qty Fix (3-part)**: (1) STC DB save now writes one trade per successful broker with actual `executed_qty` instead of a single shared entry using `signal['qty']`. (2) Added `original_quantity` column to trades table — set on BTO insert, preserved by sync when broker qty decreases after partial exits. (3) Initial trim qty query includes `original_quantity` for better estimates; TRIM FIX per-broker recalculation remains the authoritative correction.

## External Dependencies

- **Python 3.8+**
- **Flask**
- **discord.py-self**
- **Telethon**
- **Webull SDK**
- **alpaca-py**
- **ib-insync**
- **robin-stocks**
- **httpx**
- **aiohttp**
- **openai**
- **cryptography**
- **yfinance**
- **ta**
- **pyotp**
- **PySide6**
- **paho-mqtt**
- **Chart.js**