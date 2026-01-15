# BotifyTrades - Multi-Platform Trading Bot

## Overview
BotifyTrades is a cross-platform trading automation bot for Discord and Telegram, designed for automated stock and options trading across multiple brokers in the USA, Canada, and India. It provides automated execution, advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The project's vision is to make sophisticated trading accessible and efficient by integrating advanced trading functionalities within messaging platforms.

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
Core technologies include `discord.py-self` for Discord integration and `webull` for brokerage. It employs a true dual-broker architecture for live and paper trading, with platform-specific credential encryption. Order execution uses an asynchronous, queue-based system. Signal parsing uses a multi-layer approach supporting learned formats, built-in regex, and AI fallback. Risk management includes automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all GUI-configurable and stored in SQLite. Pre-trade analysis uses technical indicators, and post-execution analysis leverages OpenAI GPT models. Real-time market data is integrated, and interactive Discord commands enable on-demand analysis. An error monitoring system provides automatic detection, logging, and AI assistant contextual help.

The Signal Verification Service detects paper trading and impossible fills using real-time broker data and confidence scoring. Async broker integrations use thread-safe bridge patterns. The system supports a dual-mode channel system for simultaneous execution and signal forwarding, FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection. **STRICT ROUTING ARCHITECTURE**: Signals route ONLY to channel-configured brokers - if a channel has `execute_enabled=1` but no `enabled_brokers` assigned, signals are REJECTED (not routed to any default/primary broker). The settings validator raises CRITICAL errors for such misconfigurations at startup. Per-channel risk settings allow independent operation, supporting 4-tier profit targets, trailing stops, and Leave Runner functionality. Exit Strategy Mode allows configuration per channel to follow trader signals, automated risk management, or both. Position Matching for Ambiguous Exit Signals automatically links exit signals to the most recent open position. The Trade Monitor feature automatically detects and posts broker-executed trades as BTO/STC signals to Discord.

The Enhanced Portfolio Simulation Engine v2.0 provides industry-grade portfolio analysis with Monte Carlo Simulation, Theta Decay Modeling, Correlation/Concentration Risk Analysis, Risk Scenario Presets, and Comprehensive Portfolio Projection. Telegram Integration supports reading trading signals from Telegram groups/channels. Market-Specific Channel Pages provide dedicated management for India Markets (NSE/BSE/MCX with DhanQ, Upstox, Zerodha) and Canada Markets (TSX/CSE/NEO with Questrade). The Conditional Order Monitoring System monitors price conditions and executes orders when triggered, supporting signals with "over/above" and "under/below" triggers, SL/PT, and position sizing. **Channel Settings Linkage**: All channel-level execution controls (timeout, position sizing, exit strategy mode, slippage protection, trailing stop) now properly flow to conditional orders with full audit trail tracking via `settings_source` metadata. Timeout precedence: `order_timeout_minutes` → `conditional_order_timeout_minutes` → `conditional_order_expiry` (legacy). Trailing stop is enabled when `trailing_stop_pct > 0`. The Expiry Resolver Service automatically picks the next valid expiry for Indian F&O signals when not specified.

Filled Orders Tracking syncs filled orders from broker APIs into a local database table with automatic sync and deduplication. Execution-Based P&L Tracking provides professional-grade P&L calculation based on actual broker fills, including slippage tracking, latency metrics, and race condition protection. A Two-Tier P&L Architecture provides separation between theoretical signal performance (Signal P&L) and actual broker execution results (Execution P&L).

The Bot Lifecycle Manager provides centralized control for bot stop/restart operations via system tray and web GUI, including REST API endpoints and graceful shutdown signaling. The Signal Tracking System provides comprehensive lifecycle tracking for all signals from detection through broker execution with full audit trails. The QA Workflow Validation System ensures the complete signal-to-execution pipeline remains intact. The **Integrated QA Framework** includes 76 integration tests, 24 unit tests, and E2E workflow tests accessible directly from the System Health page, with GitHub Actions CI/CD running tests automatically on every code push to prevent regressions.

The Order Management System (OMS) and Risk Management System (RMS) provide dynamic SL/PT management for signals that update via Discord message edits, with a WaxUI Entry Registry linking update signals to original entries. The Exit Order Arbiter arbitrates between signal-driven and risk-driven exit requests, enforcing that stop loss can never be lowered in hybrid mode. The Signal Exit Manager handles the complete order lifecycle with broker-aware modify flows. A Circuit Breaker provides emergency trading halt controls with global/per-channel halt, daily loss limit enforcement, and position count limits. Exit Strategy Modes include Signal Mode, Risk Mode, and Hybrid Mode. Trailing stop state persists to the database across bot restarts for robust position management.

**Enhanced Risk Management v2.0**: The Risk Engine (`src/risk/risk_engine.py`) provides industry-grade exit evaluation with:
- **Dynamic SL Escalation**: Automatically moves stop loss after profit targets are hit. Three profiles available:
  - Conservative (PT1→BE, PT2→+3%, PT3→+10%, PT4→+20%)
  - Standard (PT1→BE, PT2→+5%, PT3→+15%, PT4→+25%)
  - Aggressive (PT1→-2%, PT2→BE, PT3→+10%, PT4→+20%)
- **Max Profit Giveback Guard**: Exits position when profit drops more than X% from peak (configurable, default 30%). Activates after PT2 hit OR when max PnL exceeds trailing activation threshold.
- **Exit Priority Order**: Hard SL → Dynamic SL → Giveback Guard → Trailing Stop → Runner Exit (highest to lowest priority)
- **Idempotent Design**: Pure function architecture with `last_evaluated_price` tracking prevents duplicate actions on repeated evaluations.
- **Complete Integration**: Risk engine fully integrated into position_monitor.py via `_evaluate_enhanced_risk()` method. Cache state updates (max_pnl_seen, dynamic_sl_price, giveback_guard_active) persist across monitoring cycles.
- **Enhanced Logging**: Position status logs show `[DYN-SL ✓] $1.05 (+5%)` and `[GIVEBACK ✓] Max:50%, Exit@35%` for full visibility.

Database columns: `enable_dynamic_sl`, `enable_giveback_guard`, `giveback_allowed_pct`, `dynamic_sl_profile` in channels table. GUI configuration in Risk Management panel with profile dropdown and percentage inputs. Test coverage: 26 unit tests + 14 integration tests verify complete UI→DB→Risk Engine→Broker flow.

A Service Orchestrator manages priority-based background services with dynamic activation, API budget allocation, and broker-specific rate limiting, featuring a `RateLimitManager` for token bucket rate limiting and automatic 429 backoff. Services like RiskManager and Trade Monitor have enable gates, and their configurations are stored in `service_registry`, `broker_limits`, and `service_metrics` database tables. Flask API endpoints manage services and broker limits. The orchestrator defines dynamic monitoring intervals based on verified broker API rate limits for various services, allowing for efficient resource utilization.

Order-Level Deduplication prevents duplicate order execution at the worker level. Discord and Telegram signals with message_id are tracked to prevent duplicate events from executing twice. Manual/relay trades are assigned a UUID at execution time for tracking. This complements the message-level deduplication in on_message handler. **Signal Lot Idempotency**: The `create_signal_lot()` function includes idempotent checks based on `signal_id` to prevent duplicate PNL entries from message retries or duplicate processing.

**Startup Settings Validation**: The settings validator runs at bot startup and flags CRITICAL issues: (1) channels with `execute_enabled=1` but no `enabled_brokers` assigned, (2) channels with `risk_management_enabled=1` but no `stop_loss_pct` configured. Trailing stops only work on the upside after profit thresholds are reached, so a stop loss is mandatory for downside protection.

**Position Sizing Priority** (Channel settings ALWAYS override signal quantity):
1. Channel QTY (fixed contracts) - HIGHEST PRIORITY
2. Channel Size % (percentage-based sizing from buying power)
3. Signal quantity (from "BTO 20 SPY...") - only used if no channel settings
4. Global default_quantity
5. Max position size calculation (if enabled)
6. Fallback to 1 contract

When both QTY and Size% are set on a channel, QTY takes priority (deterministic override). Example: Signal "BTO 20 SPY" with channel QTY=5 → executes 5 contracts. Signal "BTO 20 SPY" with channel Size%=30 → calculates qty from 30% of buying power.

**Proportional Exit Logic**: When traders post partial exit signals (STC for less than their full position), the bot calculates the proportional exit based on the trader's exit percentage. The `signal_qty` field tracks the trader's original quantity separately from the bot's executed quantity. Example: Trader enters 20 contracts → Bot executes 5. Trader exits 10 (50%) → Bot exits `ceil(5 * 0.5) = 3`. Trader exits 5 (25%) → Bot exits `ceil(5 * 0.25) = 2` (capped at remaining). This ensures accurate proportional exits without rounding drift across multiple partial closes.

**Proportional Exit Architecture**: The proportional exit logic is implemented in TWO locations for complete coverage:
1. **PNL Tracking** (line ~8148): Calculates accurate P&L with proportional exit quantities
2. **Broker Execution** (line ~9155): Applies proportional exit to `opt['qty']` BEFORE queuing to ANY broker

This ensures ALL brokers (current and future) and ALL channels automatically get proportional exits - it's broker-agnostic and channel-agnostic. The calculation uses `get_open_position_for_symbol()` which retrieves the `signal_qty` (trader's original), `original_qty` (our executed), and `remaining_qty` (what's left) to compute the correct proportional exit.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, Robinhood, Charles Schwab, Questrade, Upstox, Zerodha, and DhanQ. The License Validation System provides industry-standard license activation. The Discord bot runs in a dedicated thread. Broker credentials and all bot settings are GUI-manageable and stored in SQLite. Security features include admin password management, rate limiting on login attempts, session-based authentication, and local password recovery.

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