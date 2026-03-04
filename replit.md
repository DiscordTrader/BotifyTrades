# BotifyTrades — Compressed Documentation

## Overview

BotifyTrades is a production-grade, cross-platform automated trading bot designed to monitor Discord and Telegram for trade signals and execute them across multiple brokers. It features a comprehensive Flask-based web control panel with real-time dashboards, advanced risk management, WebSocket streaming, AI-powered analysis, and detailed portfolio analytics. The project aims to provide automated trading capabilities for US and Canadian markets, offering users a powerful tool for managing and optimizing their trading strategies.

## User Preferences

- **Security**: Always use environment variables (Replit Secrets) for credentials and license keys
- **Testing**: Test with paper_trade = true before enabling live trading
- **Monitoring**: Review console logs regularly for trade execution
- **Channel filtering**: Only process signals from designated channels
- **Deployment**: Prefer local machine or cloud VPS for 24/7 operation
- **Licensing**: All deployments require a valid license key (set via LICENSE_KEY environment variable or setup wizard)
- **Authentication**: First-time users are guided through setup wizard to create admin account with email recovery

## System Architecture

**UI/UX Decisions:**
The web control panel is built with Flask, providing a responsive and interactive user experience. Key UI/UX features include:
- **Real-time Dashboards**: `index.html` offers an immediate overview of broker status, live positions, P&L, and risk statuses. Uses smart differential DOM updates — position cards only rebuild when positions are added/removed; price/P&L updates happen in-place via cached element references and `requestAnimationFrame` to eliminate full-page re-renders every 30s. Drawer state (expanded risk/close panels) persists across data refreshes.
- **Trade Monitoring**: `trades.html` includes five tabs for live positions (with real-time price updates and glowing effects), pending orders, filled orders, signals, and an event log.
- **Performance Analytics**: `performance.html` provides Signal P&L analytics via `performance_analytics.py` reading from `lot_closures` table (separate from Execution P&L in `pnl_tracker.html`). Features broker-filtered breakdown (12 brokers: WEBULL, WEBULL_PAPER, ALPACA, ALPACA_PAPER, SCHWAB, ROBINHOOD, TASTYTRADE_LIVE/PAPER, IBKR_LIVE/PAPER, QUESTRADE, UPSTOX), trade journaling, time-series charts, P&L heatmaps, and edge analysis (with EMA_EXIT/EARLY_TRAILING exit reason classification) using Chart.js. Broker filter uses `UPPER()` comparison via `_build_broker_filter()` JOIN through `lot_closures→signal_lots→trades`. Broker resolution chain: `trades.broker` → `channels.enabled_brokers[0]` → `'Unknown'` (for orphaned lot_closures where signal_lots.trade_id is NULL and old channel IDs no longer exist).
- **Intuitive Settings**: Dedicated sections for Discord, Telegram, Brokers, Trading, Risk Management, Notifications, and AI Analysis ensure easy configuration.
- **Visual Feedback**: Streaming indicators, glow effects on price changes, and staleness indicators provide clear status updates.

**Technical Implementations:**
- **Signal Sources**: Integrates with Discord (via `discord.py-self`) and Telegram (via Telethon) for signal monitoring, supporting embed parsing, regex matching, and AI-powered detection.
- **5-Tier Signal Parsing**: Employs a tiered parsing system starting from embed parsers, moving to standard formats, trader-specific patterns, regex, and finally an AI fallback using OpenAI GPT. Features include deduplication, market order support, follow-up SL/PT updates, and configurable regex patterns.
- **Risk Management Engine**: A comprehensive, multi-layered risk management system with global and per-channel settings. It includes configurable Stop Loss (SL), Trailing Stop, four Profit Targets (PTs), Dynamic SL Escalation, Max Profit Giveback Guard, EMA-5 Candlestick Risk Engine, and a "Leave Runner" feature. Risk states are persistent across restarts. Exit pricing uses streaming hub bid/ask when available: **bid price** for SL/trailing/giveback exits (realistic sell-side pricing), **mid price** for profit target exits (fair value). Falls back to broker's last trade price when hubs are offline.
- **EMA-5 Candlestick Risk Engine** (`src/risk/ema_engine.py`): Builds OHLC candles from WebSocket streaming ticks and computes rolling EMA for exit/escalation signals. Priority 2.5 in risk chain (after Dynamic SL, before Giveback Guard). Components: CandleAggregator (per-symbol thread-safe candle builder with per-symbol locks), EMAEngine (SMA-seeded rolling EMA), EMAExitEvaluator (pure function cross detection for CALL/PUT/STOCK), CandlePreWarmService (singleton managing all symbol tracking, pre-warms SPY/QQQ/SPX/NDX at startup, dynamic subscription for other symbols up to 50). **Data sources**: 1) WebSocket streaming hub ticks (Webull MQTT / Schwab WS) — quote objects use `.last` and `.close_price` attributes (NOT `.last_price`/`.close`), 2) REST poll fallback every ~5s via yfinance for symbols not streamed by any hub (e.g., Alpaca-only positions), 3) yfinance historical candle pre-seeding for instant EMA availability at startup. **yfinance-only mode**: For option positions with `ema_use_underlying=1`, streaming hub ticks are skipped (they carry the option contract price, not the underlying stock price) and yfinance polling provides correct underlying stock prices at 5-second intervals. All time calculations use Eastern Time (zoneinfo/pytz) for correct candle boundaries and market hours gating. Respects exit_strategy_mode gating (signal=disabled, risk=active, hybrid=arbiter). Per-channel settings in channels.js UI with cyan/teal theme.
- **Position Sizing**: Per-channel percentage-based position sizing (`position_size_pct`) uses **live broker data** fetched at order time (not cached start-of-day). For **option trades**, budget uses `options_buying_power` (non-leveraged, cash-secured); for **stock trades**, budget uses `buying_power` (may include margin leverage). Broker-specific: Webull (`optionBuyingPower` vs `dayBuyingPower`), Schwab (`optionBuyingPower` vs `buyingPower`), Tastytrade (`derivative_buying_power` vs `equity_buying_power`), Alpaca (`options_buying_power` vs `buying_power`). IBKR/Robinhood fall back to general `buying_power` for both (no separate options BP field). Questrade has no standardized BP fields — sizing rejects with $0 error. Channel `max_position_size` dollar cap applies after budget calculation.
- **Order Execution System**: An asynchronous, queue-based system for multi-broker order execution, featuring per-channel broker selection and a Universal Order Placement Resilience Layer with error classification, circuit breakers, and orchestrated retry budgets. **Hub-First Slippage**: Both option and stock slippage checks try streaming hub cache (WebullDataHub/SchwabDataHub) before falling back to REST API calls, eliminating ~10s REST latency when streaming data is available. Option ID and ticker ID caches prevent duplicate REST lookups across slippage check and order placement. Alpaca supports sub-penny pricing (4 decimal places) for stocks under $1.00. **Order Chaser** (`src/services/unfilled_order_chaser.py`): Monitors unfilled entry/exit orders and replaces them at updated prices. Entry tracking populates `call_put` from signal dict key `opt_type` (primary), then `call_put`, then `direction`. Defensive guards prevent option orders from falling through to stock-price quote paths when option fields are missing — returns None with warning log instead of misquoting.
- **Order Management System (OMS)**: Handles dynamic SL/PT management, exit order arbitration, position matching, and FIFO-based P&L tracking with both execution-based and mark-to-market P&L. Exit source classification supports 12 types: SIGNAL, PT1-PT4, STOP_LOSS, TRAILING, EARLY_TRAILING, EMA, GIVEBACK, RISK, MANUAL. The `map_risk_trigger_to_exit_source()` function maps risk engine triggers (ema_exit, ema_no_trend, giveback_guard, early_trailing, etc.) to the correct exit_source enum for the execution_closures table. Database CHECK constraint auto-migrates for existing databases.
- **WebSocket Streaming**: Utilizes Webull MQTT for real-time quotes and orders, and a 5-tier optimized Schwab WebSocket streaming system for Level One equities and options. Both employ centralized, thread-safe data hubs with TTL invalidation and hub-first lookups. Streaming hubs are now wired into the conditional order price monitor via `StreamingPriceMonitor`, providing sub-100ms pricing with zero API calls and automatic REST fallback when hubs are not streaming. The Quick Trade Options Chain subscribes option contracts to WebSocket streaming (Webull MQTT topic 105 / Schwab LEVELONE_OPTIONS) via `/api/options/subscribe-stream`, then polls cached hub quotes at 300ms via `/api/options/stream-quotes` for industry-grade flash price updates with green/red flash effects, while full chain REST refresh runs every 15s in background for Greeks/OI/volume. Chain REST cache TTL is 10 seconds. Hub keys are normalized (e.g., `SPY_600.0_C` → `SPY_600_C` alias) for consistent frontend lookups. Quick-chain loads seed REST bid/ask/last into the streaming hub so prices are available immediately before streaming ticks arrive.
- **Broker Sync Service**: A 30-second cycle service to reconcile database state with actual broker states, detecting filled/cancelled orders, position changes, and account info updates.
- **Notification System**: Provides Discord webhook notifications for various events (order filled/failed/cancelled, risk events, position updates) and desktop browser notifications.
- **Security & Authentication**: Implements admin account management with password hashing and email recovery, session-based authentication, rate limiting, and encrypted broker credentials using the `cryptography` library.
- **Database Architecture**: Uses SQLite with WAL mode for concurrent read/write operations, thread-safe connections, and stores critical trading data and encrypted credentials.
- **AI Analysis**: Integrates OpenAI GPT for pre-trade and post-trade analysis, an AI chat assistant, and AI command toggles.

**System Design Choices:**
- **Broker Isolation**: Ensures that each broker's streaming data only feeds its own positions, preventing data cross-contamination.
- **Thread Safety**: All shared states are protected by locks for cross-thread safety.
- **Queue-Based Execution**: Signals are processed asynchronously through a queue, ensuring non-blocking signal detection.
- **Hub-First Architecture**: Prioritizes cached streaming data before resorting to REST API calls.
- **Graceful Degradation**: Automatically falls back to REST polling if streaming services become unavailable.
- **Modular Broker Abstraction**: A common interface is used to manage diverse broker APIs.
- **Market Isolation**: Conditional order services for US, India, and Canada operate independently.
- **Conditional Order Guards**: Per-channel **Breakout Reset Guard** (`breakout_reset_enabled`, default ON) requires price to pull back past the trigger before firing if price is already beyond trigger at order creation. Per-channel **Limit Cap** (`limit_cap_enabled`/`limit_cap_pct`) sets a price ceiling/floor on the resulting limit order to prevent chasing.

## External Dependencies

- **Python 3.8+**: Core runtime environment.
- **Flask**: Web framework for the control panel.
- **discord.py-self**: Discord user account API for signal monitoring.
- **Telethon**: Telegram user client for signal monitoring.
- **Webull, alpaca-py, ib-insync, robin-stocks**: SDKs for respective brokerage integrations.
- **httpx**: HTTP client for Schwab API.
- **openai**: For AI analysis and chat assistant.
- **cryptography**: For encrypting sensitive credentials.
- **yfinance**: For market data access.
- **ta**: For technical analysis calculations.
- **aiohttp**: Asynchronous HTTP client.
- **pyotp**: For TOTP 2FA code generation.
- **PySide6**: Used for the first-time setup wizard GUI on Windows.
- **paho-mqtt**: For Webull MQTT streaming.
- **Chart.js**: Frontend library for data visualization.