# BotifyTrades - Multi-Platform Trading Bot

## Overview
BotifyTrades is a cross-platform trading automation bot for Discord and Telegram, designed for automated stock and options trading across multiple brokers. Its primary purpose is to make sophisticated trading accessible and efficient by integrating advanced trading functionalities within messaging platforms. Key capabilities include automated execution, advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The project targets markets in the USA, Canada, and India.

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

**Unified Signal Parsing Pipeline** (`src/services/signal_parsing_pipeline.py`): A 5-tier architecture for signal detection with security gating:
- Tier 1: Embed parsers (Spy-Sniper, Sir Goldman)
- Tier 2: SignalFormatRegistry (Jake, Slem, STACK$, Foxtrades, Learned Patterns)
- Tier 3: Trader-specific parsers (Bishop, EvaPanda, etc.)
- Tier 4: Standard BTO/STC regex
- Tier 5: AI Fallback (OpenAI, async, confidence-gated)

**Foxtrades Natural Language Parser** (`src/signals/foxtrades_parser.py`): Detects natural language stock signals like "Taking a position in $SYMBOL average $PRICE", "All out of $SYMBOL", with 8 registered patterns covering ENTRY/EXIT/TRIM actions.

**Bronze Swings Natural Language Parser** (`src/signals/bronze_swings_parser.py`): Detects swing trading stock signals with 10 patterns:
- ENTRY: "Taken a starter position on", "Taken a position on", "Entered", "Long swing"
- ADD: "Added to SYMBOL", "SYMBOL added average price"
- EXIT: "Closed position on", "SYMBOL position closed", "Closed SYMBOL"
- TRIM: "taken profits", "secured profits"

**Phoenix Natural Language Parser** (`src/services/signal_format_registry.py`): Detects Phoenix stock signals with 7 patterns:
- ENTRY: "<@&role> SYMBOL over PRICE SL PRICE", "<@&role> SYMBOL PRICE SL X%"
- TRIM: "selling X% here SYMBOL", "selling X% more SYMBOL", "leaving X% here SYMBOL"
- EXIT: "hit SL", "got a loss with SYMBOL"

**AI Signal Parser** (`src/services/ai_signal_parser.py`): OpenAI-powered fallback with async processing, rate limiting (3 concurrent max), result caching, and confidence scoring. AI signals are blocked by default until admin approval.

**Learned Patterns System**: Database-stored patterns (`learned_patterns` table) with governance workflow (pending → active status). Admin approval required before learned patterns can execute trades. Patterns store action, asset_type, confidence metadata.

**Security Gating**: All AI and learned-pattern signals include `execution_allowed`, `requires_approval`, `admin_approved` flags. The pipeline blocks unapproved signals before they reach any execution path. Confidence threshold (≥0.8) enforced via `can_execute()` method.

**Signal Deduplication**: 5-minute TTL using message hash to prevent duplicate signal processing.

Risk management features GUI-configurable automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all stored in SQLite. The system includes pre-trade analysis with technical indicators, post-execution analysis with OpenAI GPT models, real-time market data integration, and interactive Discord commands. An error monitoring system provides automatic detection, logging, and AI assistant contextual help.

The system supports a dual-mode channel system for simultaneous execution and signal forwarding, FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection. A strict routing architecture ensures signals only route to channel-configured brokers. Per-channel risk settings allow independent operation, supporting 4-tier profit targets, trailing stops, and Leave Runner functionality. An Exit Strategy Mode is configurable per channel. Position Matching for Ambiguous Exit Signals links exit signals to open positions, and Trade Monitor automatically detects and posts broker-executed trades as Discord signals.

An Enhanced Portfolio Simulation Engine v2.0 provides industry-grade portfolio analysis. Telegram Integration supports reading trading signals from Telegram groups/channels. Market-Specific Channel Pages manage India and Canada markets. A Conditional Order Monitoring System monitors price conditions and executes orders when triggered. An Expiry Resolver Service automatically picks the next valid expiry for Indian F&O signals.

Filled Orders Tracking syncs filled orders from broker APIs into a local database with automatic sync and deduplication. Execution-Based P&L Tracking provides professional-grade P&L calculation, including slippage and latency metrics. A Two-Tier P&L Architecture separates theoretical signal performance (Signal P&L) from actual broker execution results (Execution P&L).

The Bot Lifecycle Manager provides centralized control via system tray and web GUI. A Signal Tracking System offers comprehensive lifecycle tracking for all signals. The QA Workflow Validation System ensures the complete signal-to-execution pipeline with integrated tests and CI/CD.

The Order Management System (OMS) and Risk Management System (RMS) provide dynamic SL/PT management via Discord message edits. The Exit Order Arbiter arbitrates between signal-driven and risk-driven exit requests. A Circuit Breaker provides emergency trading halt controls. Exit Strategy Modes include Signal, Risk, and Hybrid. Industry-grade Risk State Persistence ensures all risk state (Tier Hit, Dynamic SL Price, Giveback Guard, Trailing Stop, Settings Versioning) survives bot restarts with startup reconciliation. Enhanced Risk Management v2.0 provides Dynamic SL Escalation and Max Profit Giveback Guard.

**Early Trailing Stop** (`src/risk/early_trailing.py`): Percentage-based trailing stop with breakeven-first approach:
- State machine: INACTIVE → BREAKEVEN_LOCKED → PROFIT_LOCKED
- Moves stop to entry (breakeven) after X% gain (default 5%), then locks profit in Y% steps (default 3%)
- Mutually exclusive with legacy Trailing Stop (enforced in UI and RiskEngine)
- Broker-aware price monitoring using position.broker_id for API routing
- Adaptive polling: 1s near stop, 5s mid-range, 10s far buffer

**Broker-Aware Price Monitoring** (`src/services/price_monitor_service.py`): Routes quote requests to position's connected broker with fallback chain:
- Position broker → Other connected brokers → Finnhub → yfinance
- Broker capability map in `src/services/broker_capabilities.py` (Alpaca/Schwab/IBKR/Robinhood support both stocks and options)

**Broker Health Monitor** (`src/services/broker_health_monitor.py`): Industry-grade centralized broker connection and buying power monitoring:
- Thread-safe singleton with RLock protection on all shared state (broker states, cache, notifications, callbacks)
- Real-time connection status tracking with disconnect reason classification (TOKEN_EXPIRED, API_ERROR, AUTH_FAILED, RATE_LIMITED, NETWORK_ERROR, etc.)
- Fail-safe pre-trade validation: blocks on unknown brokers, missing cache, any error status, invalid price/qty
- Integer quantity enforcement for options contracts (prevents fractional contract orders)
- Any error_code automatically forces is_connected=False for defensive trading protection
- Cache invalidation on disconnect, notification cooldown reset on reconnect
- Broker-specific buying power field mapping for 11+ brokers (Webull, Alpaca, Robinhood, Schwab, IBKR, Tastytrade, Questrade, Zerodha, Upstox, Dhan)
- Normalized broker name handling (uppercase) for consistent lookups across all methods
- Trade rejection recording with reason (rejection_reason and rejected_at columns in trades table)
- Dashboard notifications for broker disconnects with cooldown (5 min) to prevent spam
- API endpoints: `/api/brokers/health`, `/api/brokers/notifications`, `/api/trades/rejected`
- Integrated with BrokerSyncService for automatic status updates during sync cycles

**Unfilled Order Chaser** (`src/services/unfilled_order_chaser.py`): Industry-grade exit order management:
- Monitors pending exit orders for stale status (unfilled beyond timeout threshold)
- Calculates mid-price from current bid/ask spread for better fills
- Cancels stale orders and replaces with mid-price limit orders
- Configurable chase timeout (default 30s), max attempts (default 3), poll interval (5s)
- Integrates with risk management STC orders for automatic tracking
- Database settings: `order_chase_enabled`, `order_chase_timeout_seconds`, `order_chase_max_attempts`, `order_chase_poll_interval`
- Per-channel and per-mapping granular control with three-tier fallback: mapping → channel → global
- NULL value means "use parent setting" (channel falls back to global, mapping falls back to channel then global)
- UI toggles in Channel Execution and Signal Routing pages with tri-state dropdowns (Global Default / Override On / Override Off)

A PriceMonitorService provides real-time price monitoring for open positions with multi-broker data source fallback. A Service Orchestrator manages priority-based background services with dynamic activation, API budget allocation, and broker-specific rate limiting. Order-Level Deduplication prevents duplicate order execution. Startup Settings Validation flags critical configuration issues. Position Sizing Priority is hierarchical. Proportional Exit Logic calculates proportional exits for partial exit signals. Signal Routing with Per-Mapping Risk Settings enables source-to-destination Discord channel routing with independent risk management. The Forwarding-Only Signal Routing Engine (`src/services/signal_routing_engine.py`) provides webhook-based signal forwarding with position tracking and real-time P&L monitoring, featuring a Position Ledger, Stale Price Gating, Shared ExitArbiter, and a Webhook Retry Queue.

**Isolated Execution Flows** (Critical Architecture):
- **Channel Execution**: Direct broker trading tracked in `trades` table with broker-specific positions
- **Signal Routing**: Webhook forwarding tracked in `position_ledger` table with `source_type='signal_routing'`
- These flows are architecturally isolated - broker execution does NOT create position_ledger entries
- Position Ledger API filters by `source_type='signal_routing'` to prevent cross-flow contamination The NDX→QQQ Conversion Service (`src/services/ndx_qqq_converter.py`) enables channels with limited NDX access to trade equivalent QQQ options. The Sir Goldman Signal Parser (`src/signals/sir_goldman_parser.py`) parses embed-based trading signals, supporting ENTRY/EXIT/TRIM signals.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, Robinhood, Charles Schwab, Questrade, Upstox, Zerodha, and DhanQ. The License Validation System provides industry-standard license activation. The Discord bot runs in a dedicated thread. Broker credentials and all bot settings are GUI-manageable and stored in SQLite. Security features include admin password management, rate limiting, and session-based authentication.

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