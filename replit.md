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
The web control panel, built with Flask, provides real-time dashboards for broker status, live positions, P&L, and risk statuses. It includes detailed trade monitoring, performance analytics, intuitive settings, and visual feedback mechanisms like streaming indicators.
- **Performance Dashboard (Calendar View)**: Redesigned `/performance` page with top stats row (Realized P&L, Avg Win/Loss ratio, Profit Factor, Average Drawdown, Trade Win %), monthly calendar grid with daily P&L/trade count/win rate per cell, weekly summary cards, cumulative daily P&L area chart, and tabbed Recent Trades / Open Positions table. Calendar supports month navigation and broker filtering. Data served via `get_calendar_data()` in `performance_analytics.py` through the `/api/performance-v2?section=calendar` endpoint.

### Technical Implementations
- **Signal Sources**: Integrates with Discord and Telegram, utilizing a 5-tier parsing system (dedicated parsers, regex, AI fallback) for embed parsing, regex matching, and AI-powered detection, with deduplication and follow-up SL/PT updates.
- **Risk Management Engine**: A multi-layered system with global and per-channel settings, configurable Stop Loss, Trailing Stop, four Profit Targets, Dynamic SL Escalation, Max Profit Giveback Guard, EMA-5 Candlestick Risk Engine, and a "Leave Runner" feature. Risk states are persistent, and exit pricing prioritizes streaming hub bid/ask.
- **Position Sizing**: Per-channel percentage-based sizing uses live broker data for options and stocks, considering specific buying power metrics across brokers. Three balance modes: "Live", "Pre-Market", and "Start-of-Day".
- **Order Execution System**: An asynchronous, queue-based system for multi-broker order execution, featuring per-channel broker selection and a Universal Order Placement Resilience Layer with error classification, circuit breakers, and retries. Includes hub-first slippage checks and an Order Chaser service.
- **Order Management System (OMS)**: Handles dynamic SL/PT management, exit order arbitration, position matching, and FIFO-based P&L tracking, supporting 12 types of exit source classifications. It features universal risk exit P&L recording, multi-lot overflow closure, broker fill price reconciliation, and consolidated fill-based P&L.
- **Risk STC Position Guard Bypass**: The stock STC position pre-check guard (selfbot_webull.py) that calls `get_positions_detailed()` before placing an exit order now skips the hard-reject for risk management STCs (`_risk_management_order=True`). Previously, if the REST API momentarily returned no position, the guard would block the exit BEFORE the market order was ever attempted — causing infinite retries. Now risk STCs proceed to attempt the order; the broker itself rejects if truly empty. Regular signal STCs still get hard-rejected (safety). Combined with `no_position_streak` in risk_types.py: if the broker confirms "no position" on 3 consecutive actual order attempts, the position is marked permanent failure (phantom). Streak resets on any non-position error, preventing false drops on real positions with transient issues.
- **IBKR Cross-Loop Quote Fix**: IBKRBroker `get_quote()`, `get_quote_detailed()`, and `get_option_quote()` now safely dispatch IB API calls (`qualifyContractsAsync`, `reqMktData`) to the IB event loop when called from a different async loop (risk engine, conditional orders). Uses `asyncio.run_coroutine_threadsafe()` + `asyncio.wrap_future()` (non-blocking) instead of direct `await` which threw "This event loop is already running". Each method has an `_impl` variant that runs on IB's loop, and the public method routes via `_is_on_ib_loop()` check. Fails fast with `None` if no IB loop is available. Event loop captured via `get_running_loop()` during `connect()`.
- **IBKR Position Refresh Event Callback Fix**: `IBKRDataHub._refresh_positions_from_ib()` now uses `ib.portfolio()` (cached, instant, no network request) when called from event callbacks (`_on_position_event`, `_on_order_status`), and `ib.positions()` (network request) only from the periodic reconciliation loop where it's safe. This fixes the "Position refresh after order event failed: 'positions'" error caused by `ib.positions()` making a network call inside an ib_insync event callback. The `avg_cost` field is handled for both `Position.avgCost` and `PortfolioItem.averageCost` types.
- **REST Repair Guard — Timestamp-Based Protection**: The `_is_rest_repair_active()` guard now uses hub tick timestamp comparison instead of age-based. When the STUCK PRICE FIX corrects a frozen streaming price via REST, the repaired price is protected until a genuinely NEW hub tick arrives (timestamp > repair creation time). Previously, stale cached ticks with age < 3s could release the guard, causing the stale stream price to overwrite the REST correction on the very next cycle. Also raised the material-difference override threshold from 0.3% to 0.5%.
- **Direct Exit Cross-Loop Fix**: `_direct_execute_exit()` backup thread now dispatches to the bot's main event loop via `asyncio.run_coroutine_threadsafe(coro, self.loop)` instead of creating `asyncio.new_event_loop()`. This prevents "Future attached to a different loop" errors when broker `place_stock_order()` internally awaits futures bound to the main loop.
- **Fast Exit Tuning (Phase 1)**: Exit retry backoff reduced from 15s/30s/60s/120s to 4s/6s/10s/10s (4s floor avoids racing 4s order chaser timeout). Emergency backoff reduced from 5s/10s/15s to 3s/6s/9s/10s. Market order threshold lowered from 3 to 2 failed limit orders. Penny stocks (<$1) always use bid-price exits, force market orders, and get 4-decimal price precision in limit payloads. Extended-hours market-to-limit conversion uses 8% offset for penny stocks (vs 3% for normal). `find_open_bto_trade()` includes PENDING status for faster exit attribution with OPEN/PARTIAL priority ordering via CASE expression. Backup thread reduced from 10s to 5s.
- **WebSocket Streaming**: Utilizes Webull MQTT and an optimized Schwab WebSocket system for real-time quotes and orders, providing sub-100ms pricing for conditional orders and quick trade options chains, with automatic REST fallback. Includes cross-broker streaming subscription and immediate BTO symbol subscription.
- **Daily P&L Limit System**: Per-broker daily P&L tracking against SOD equity snapshots, with configurable dollar and percentage limits for profit targets and loss limits. Locks brokers from new BTO entries when thresholds are hit and resets at configured time. Also includes a configurable "Max Daily Trades Per Broker" limit.
- **Broker Closed Position Fill Recovery**: Automatically queries execution closures and filled orders for actual exit fill price when a position vanishes from the broker. Includes a historical fill backfill mechanism.
- **Broker Sync Service**: Reconciles database state with actual broker states, detecting order fills/cancellations, position changes, and account updates. Features mid-sync order interrupt, pre-queue sync pause, and async yield points.
- **Order Chaser Service**: Monitors unfilled exit/entry orders and replaces stale ones with better prices. It's DST-aware, verifies order status to prevent false fills, and tracks all STC orders (risk management and signal STCs).
- **Schwab Stock Exit Order Strategy**: Uses true MARKET orders during regular market hours for stock STC exits to avoid price-band rejection, and aggressive LIMIT orders during extended hours.
- **Schwab OrderSessionPolicy**: Auto-detects premarket/after-hours and uses `GOOD_TILL_CANCEL` duration when session is `SEAMLESS`.
- **Position Cache Flip-Flop Guard**: Detects and prevents entry price oscillation when broker data alternates between two values for the same position key.
- **Broker Health Monitor**: Tracks broker states and notifications, providing GUI compatibility for displaying connection status.
- **IBKR Dashboard Wiring**: Ensures IBKR and all brokers show on the dashboard even when disconnected, with credentials-based fallback for disconnected states.
- **Schwab Token Auto-Refresh**: `SchwabTokenManager` singleton refreshes access tokens before expiry and handles hot-reconnection.
- **Sub-1s Order Execution Optimizations**: Includes parse-time option_id prefetch, 30s prewarm for market data, slippage REST elimination when possible, FAST-PATH timing for execution breakdown, and cache-first position sizing.
- **Notification System**: Provides Discord webhook and desktop browser notifications for trading events.
- **Security & Authentication**: Implements admin account management, password hashing, email recovery, session-based authentication, rate limiting, and encrypted broker credentials, with Schwab OAuth using CSRF state tokens and PKCE.
- **Database Architecture**: Uses SQLite with WAL mode for concurrent read/write operations, storing trading data and encrypted credentials. Includes retry mechanisms for critical exit bookkeeping.
- **AI Analysis**: Integrates OpenAI GPT for pre-trade/post-trade analysis, an AI chat assistant, and AI command toggles.
- **Risk Engine Direct Exit Architecture**: Dual-path exit execution system (primary queue-based, backup daemon thread at 5s for direct calls) with an Exit Lease Manager to prevent duplicate exits.
- **Risk Engine Speed Optimizations**: Lowered interval floor, early-wake sleep chunking, cached service checks, throttled cache saves, parallel broker fetches, REST position cache, SchwabDataHub hub-first approach, cross-broker price updates, and a staleness guard. Includes a stuck price detection and fix mechanism with cascading REST fallback.
- **Event-Driven Fill Watch System**: After any BTO order succeeds (all brokers), `notify_order_placed()` activates rapid position polling with broker-specific intervals respecting API rate limits: Schwab/IBKR/Alpaca/Tastytrade at 0.5s, Webull at 2.0s (30 req/min limit), Robinhood at 8.0s, Trading212 at 5.0s. Detects new positions by symbol match (new position) or quantity increase (scale-in), with baseline snapshot at order placement time. Expires after 30s (order chaser handles slow fills). Also triggers `request_risk_eval()` for immediate early wake. Hub `refresh_positions_once()` path now respects rate limiter to prevent unthrottled REST calls. All fill watch REST calls go through `RateLimitManager.can_make_request()` — excess calls fall back to cached data (120s TTL).
- **Risk Engine Staleness Gate**: Pre-execution staleness protection for risk exits. Two-layer defense: (1) If price unchanged >10s during market hours, exits are blocked until fresh price arrives (`_STALENESS_EXIT_BLOCK_THRESHOLD`). (2) "Unverified price quarantine" — when `_detect_and_fix_stuck_prices` probes all sources (cross-hub + REST) and none return a different price, the position is marked `_price_unverified` for up to 30s, blocking all exits. Both gates auto-clear when price changes or quarantine expires. Only active during regular/extended market hours. Extended hours freshness guard (`_check_price_freshness`) probes Webull → Schwab → IBKR hubs (60s max_age) when a position shows >1.5x SL loss during pre-market/after-hours, blocking false exits from stale previous-close prices.
- **Webull Stock Price Fix**: Addresses inaccurate pre-market `current_price` for Webull stock positions by prioritizing `latestPrice`, `lastPrice`, and streaming hub quotes, with a freshness guard and forced REST refresh for significantly deviated prices.
- **Trading212 Data Hub & Integration**: Provides a portfolio-based price cache for T212 positions, integrating with the risk engine and conditional order service. Features a real-time T212 architecture with cross-broker streaming prices, scheduled snapshots, SSE push to frontend, and hub-first risk engine. T212 conditional orders for unowned symbols now actively fetch quotes from cross-broker hubs (Webull/Schwab/IBKR) every 3s, resolving the gap where `get_quote_price()` returned None for symbols not in the portfolio.
- **IBKRDataHub Streaming**: Provides real-time IBKR position and price streaming via `ib_insync` native events, managing `reqMktData` subscriptions and integrating with the risk engine. `get_quote()` enforces `QUOTE_STALE_THRESHOLD` (30s) by default — stale quotes are rejected unless a larger `max_age` is explicitly passed. Extended hours fix: `_on_pending_tickers` no longer blindly stores `ticker.close` (previous day close) as `q.last` — close is only used as an initial seed for brand-new symbols. For existing symbols, bid/ask mid is preferred when last is unavailable. Per-quote `q.timestamp` only refreshes when real market data (bid/ask/last) arrives, preventing stale close-only updates from defeating staleness checks. `_last_quote_ts` (hub liveness) still updates on every tick event to keep `is_streaming()` accurate.
- **Cross-Hub Price Sourcing (position_monitor)**: `_try_cross_hub_price()` cascades Webull → Schwab → IBKR (via `get_quote()` interface) → T212 (via direct `get_quote_price()`/`get_quote_timestamp()` adapter, max_age=2s). T212 uses a custom adapter because its DataHub has no `get_quote()` or `is_streaming()` methods.
- **T212 Options Guard**: `create_order()` in conditional orders base.py rejects at creation time when broker is T212 and signal is option-like (`strike` OR `asset_type=='option'` OR `opt_type+expiry`).
- **Cross-Broker Alt REST Quote Fallback**: When a conditional order uses a cross-broker streaming hub (e.g., Schwab order monitored via Webull hub), `StreamingPriceMonitor` and `BrokerPriceMonitor` now fall through to other connected brokers' REST `get_quote()` APIs when the primary hub broker can't quote the symbol. Applies to all cross-broker scenarios (not just T212). Uses live reference to `broker_instances` dict (via `if is not None` identity check, not truthiness) so brokers added after monitor creation are automatically visible.
- **T212 Full API Coverage**: Client (`trading212_client.py`) updated to use current `/equity/positions` endpoint (was legacy `/equity/portfolio`). Added `place_stop_order()` (trigger at stopPrice → market), `place_stop_limit_order()` (trigger at stopPrice → limit at limitPrice), `get_position(ticker)` (single-position query), and `get_exchanges()` (exchange metadata/schedules). Broker (`trading212_broker.py`) exposes `place_stop_order()` and `place_stop_limit_order()` methods; `place_stock_order()` auto-routes to stop/stop-limit when `stop_price`/`limit_price` kwargs are present.
- **IBKR Quote-on-Trigger**: IBKR added to QOT broker matching in selfbot_webull.py so IBKR conditional orders get fresh quotes before execution.
- **Streaming Liveness TTL**: Data hubs track `_last_quote_ts` to detect silently dead streams and gracefully degrade to REST fallback.
- **Webull Option Streaming Fixes**: Ensures correct option subscription and price overlay for Webull options in the streaming hub.
- **Streaming Hub-First Architecture**: Comprehensive hub-first + REST fallback pattern across all services, caching account info, positions, orders, and quotes.
- **Conditional Order Frozen Price Detection**: StreamingPriceMonitor detects price frozen ≥3s (market hours only), probes cross-broker streaming hubs first, then broker REST. Fallback chain: streaming hub → cross-broker hub → broker REST. Cross-hub stale confirmation escalates to REST when all hubs return same stale price. All external price services (Finnhub, yfinance) removed from conditional order monitoring — price sourcing is entirely broker-based via streaming hubs and REST APIs.

- **Execution Idempotency**: Per-order asyncio.Lock + set guard + DB CAS status check prevents duplicate trade execution during monitor upgrades/restarts. Terminal statuses (TRIGGERED/EXECUTING/EXECUTED/EXPIRED/CANCELLED/ERROR) block re-entry.
- **Staleness Guard (Price Change Tracking)**: `get_staleness_seconds()` now tracks time since last price CHANGE, not last poll. Frozen feeds trigger the 30s staleness block even while polls succeed.
- **Monitor Failure Recovery**: `_on_monitor_done` marks orders as ERROR on monitor crash and attempts automatic restart with a new monitor. Failed restarts set ERROR status with details.
- **Rate Limit Enforcement**: REST fallback calls in StreamingPriceMonitor and frozen probes check `RateLimitTracker.can_make_call()` and call `record_call()` on each API hit.
- **Cross-Hub Cache**: Shared class-level hub reference cache (30s TTL) eliminates redundant dynamic imports across all monitors. Both StreamingPriceMonitor and BrokerPriceMonitor use the same cache.
- **Cleanup Race Fix**: `_cleanup_order` awaits task cancellation with 2s timeout. `cancel_order` waits for monitor stop. `shutdown` stops all monitors before cancelling tasks. All paths clean up execution locks and sets via guaranteed `_executing_orders.discard()` + `_execution_locks.pop()` on every return path (staleness block, circuit breaker, channel halt, daily P&L limit, broker recovery fail, callback success/error).
- **Trading212 Market Order Override**: Expands the T212-specific market order override to also force market orders for EMA exits and profit targets, ensuring all risk-triggered exits execute immediately.
- **Bracket SL/PT Channel Resolution**: Fixes issues where positions with signal-embedded SL/PT were not showing proper risk protection due to NULL handling and missing trade ID fallbacks.
- **Channel Pre-Configured Defaults**: Database initialization applies recommended risk settings for default channels on fresh installs.
- **Jacob Signal Format Support**: Supports 9 registry patterns for Jacob's stock signal channel covering exits, trims, and SL updates, along with explicit STO blocking.
- **Waxui Signal Handling Improvements**: Comprehensive waxui exit signal parsing supporting 8 signal types (Close, Stopped Out, Trim, More, Implicit Trim, Reduced Risk, Added, Trail Stop) with robust quantity calculation.
- **EMA Period Change Bug Fix**: Ensures that changing a channel's EMA period correctly creates and wires the new EMA engine.
- **IBKR Connection Stability Fix**: Addresses IBKR connect-disconnect loops by resolving ClientId collisions, event loop conflicts, and eager disconnects.

### System Design Choices
- **Broker Isolation**: Prevents data cross-contamination by isolating each broker's streaming data.
- **Thread Safety**: All shared states are protected by locks.
- **Priority Queue Execution**: Risk management exits are prioritized over normal entries.
- **Unprotected Trades Banner**: Critical dashboard banner to identify trades lacking risk protection.
- **Hub-First Architecture**: Prioritizes cached streaming data over REST API calls.
- **Graceful Degradation**: Automatically falls back to REST polling if streaming services are unavailable.
- **Modular Broker Abstraction**: Uses a common interface for diverse broker APIs (Webull, Alpaca, Schwab, IBKR, Tastytrade, Robinhood, Trading 212).
- **Help Center**: Comprehensive `/help` route with onboarding, broker connection guides, channel settings, risk management diagrams, and entry settings guide.
- **International Broker Visibility**: `get_brokers_by_country()` includes international brokers (Schwab, IBKR, Alpaca) for non-US country codes.
- **Schwab Order Status Completeness**: Expanded `status_map` to cover all Schwab API statuses for accurate order tracking.
- **Schwab Aggressive Exit Pricing**: Converts MARKET STC orders to aggressive LIMIT orders to avoid rejection.
- **Market Isolation**: Conditional order services for different markets operate independently.
- **Multi-Broker Conditional Order Dedup Fix**: Prevents same-symbol multi-broker conditional orders from being blocked as duplicates.
- **Fallback Source Broker Recovery Gate**: Allows a grace period for broker recovery when conditional orders trigger on fallback price sources.
- **Conditional Order Guards**: Includes per-channel Breakout Reset Guard and Limit Cap.
- **Limit Cap Market Mode Bug Fix**: Ensures limit cap is respected even in market order channels.
- **Conditional Order Streaming Architecture**: Uses `StreamingPriceMonitor` and `BrokerPriceMonitor` with a robust fallback chain for price data. Includes brokerless monitor upgrade: when a `StreamingPriceMonitor` is created at P4 priority (hub exists but broker hasn't connected yet), `_upgrade_fallback_monitors()` detects `broker_instance=None` monitors and rebuilds them once the broker registers. The full upgrade chain is P4→P3→P1 as each subsystem comes online. Auto-discovery incrementally re-checks for newly connected brokers/hubs on every `_start_monitor` call (no early-return when some brokers are already registered), ensuring late-connecting brokers like IBKR get their hub registered for conditional orders tagged to them.
- **Risk Engine Price Flow**: Features both full cycle and incremental event-driven evaluation paths.
- **Single-Application Trigger Offset**: Offset applied once at conditional order creation, with global fallback.
- **Stock BUY Funds-Check Fix**: Ensures `account_data` and `account_info` are initialized for accurate funds checks.
- **Balance Mode Inner Funds-Check Alignment**: Inner broker funds checks respect the channel's Balance Mode (Pre-Market/Start-of-Day).
- **Webull Option Direction Normalization**: Handles various option direction formats to prevent misclassification.
- **Reverse Option ID Cache**: Maintains a reverse cache for Webull option IDs for accurate lookups.
- **Webull Position Key Stabilization**: Six-layer defense against intermittent `strike=0.0` for SPX/index options, preventing false "closed externally" and missed profit targets.
- **Risk Engine DB Enrichment for Index Options**: Enriches position snapshots with correct strike/direction/expiry from matched DB trades.
- **Sync Pre-Enrichment**: Recovers missing option details from DB OPEN/PENDING BTO trades before full sync.
- **IBKR Expiry Format Normalization**: Handles various expiry formats for IBKR contract construction.
- **Risk Engine Safe STC Construction**: Returns `None` for STC signals with unknown direction, ensuring clean exit lease release.
- **Permanent Failure Auto-Clear on Reopened Trades**: Auto-clears blocklisted symbols from permanent failures if a new trade is opened.
- **Schwab Fresh Quote for Orders**: Uses `max_age` parameter to get fresh quotes for order placement.
- **STC option_id Copy-Through**: Copies `option_id` and `expiry_full` from matched broker positions for Webull STC execution.
- **Order Chaser Replacement Orders**: Uses `option_type=` kwarg for option replacement orders.
- **Schwab Streaming Subscribe**: Checks both `assetType` and `asset` fields for option subscription.
- **Slippage Enforcement Deferral**: Logs slippage warnings but defers enforcement to broker pipeline.
- **Entry Confirmation Independence**: Bypasses `conditional_order_enabled` for creating conditional orders from entry confirmation signals.
- **Dynamic Offset Recalculation**: Recalculates trigger and limit prices based on `original_signal_price`.
- **Webull Account Type Selection**: Allows selecting Margin/Cash/IRA account types.
- **Signal Exit Broker Routing Fix**: Ensures `broker` field is included in all signal-based STC paths.
- **Worker Routing Type Safety Fix**: Handles both list and string types for `enabled_brokers` to prevent routing rejections.
- **Phoenix BTO/STC Execution Gap Fix**: Correctly routes Phoenix stock BTO/STC actions with proper field mapping.
- **Trading212 Event Loop Mismatch Fix (v7.1.9)**: Fixed `asyncio.Lock` in `Trading212RateLimiter`, `DuplicateOrderGuard`, and `aiohttp.ClientSession` in `Trading212Client` being bound to the wrong event loop. Locks and sessions are now lazily initialized on first use, with automatic re-creation when accessed from a different event loop. This prevented conditional order monitors from starting on T212 (`"got Future attached to a different loop"`) and blocked position fetching (`"Lock is bound to a different event loop"`).

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