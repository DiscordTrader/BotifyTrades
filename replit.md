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

**UI/UX Decisions:**
The web control panel is built with Flask, providing a responsive and interactive user experience. Key UI/UX features include real-time dashboards for broker status, live positions, P&L, and risk statuses; detailed trade monitoring with five tabs for various order states and an event log; performance analytics offering signal P&L breakdowns, trade journaling, and edge analysis; intuitive settings sections for easy configuration; a rich channel settings modal with four tabs for granular control; and visual feedback mechanisms like streaming indicators and glow effects for clear status updates.

**Technical Implementations:**
- **Signal Sources**: Integrates with Discord and Telegram for signal monitoring, supporting embed parsing, regex matching, and AI-powered detection. A 5-tier signal parsing system includes dedicated parsers for specific formats (e.g., Hengy Alerts), regex, and AI fallback, with features like deduplication and follow-up SL/PT updates.
- **Risk Management Engine**: A multi-layered system with global and per-channel settings, including configurable Stop Loss, Trailing Stop, four Profit Targets, Dynamic SL Escalation, Max Profit Giveback Guard, EMA-5 Candlestick Risk Engine, and a "Leave Runner" feature. Risk states are persistent, and exit pricing prioritizes streaming hub bid/ask.
- **EMA-5 Candlestick Risk Engine**: Builds OHLC candles from WebSocket streaming ticks and computes rolling EMA for exit/escalation signals. It utilizes streaming hubs, yfinance REST polling, and historical data pre-seeding, with specific handling for option underlying prices and market hours.
- **Position Sizing**: Per-channel percentage-based sizing uses live broker data for both option and stock trades, considering specific buying power metrics across different brokers. A "Start-of-Day Balance Mode" offers an alternative sizing mechanism using a cached snapshot of balances. All buying power checks differentiate between option orders (using `optionBuyingPower`/`options_buying_power`) and stock orders (using `buyingPower`/`buying_power`) across all brokers. The health monitor has per-broker field mappings for options vs stocks BP extraction.
- **Order Execution System**: An asynchronous, queue-based system for multi-broker order execution, featuring per-channel broker selection and a Universal Order Placement Resilience Layer with error classification, circuit breakers, and retries. It incorporates hub-first slippage checks and an Order Chaser service for managing unfilled orders.
- **Order Management System (OMS)**: Handles dynamic SL/PT management, exit order arbitration, position matching, and FIFO-based P&L tracking. It supports 12 types of exit source classifications, mapping risk engine triggers to specific exit sources.
- **WebSocket Streaming**: Utilizes Webull MQTT and a 5-tier optimized Schwab WebSocket system for real-time quotes and orders. These centralized, thread-safe data hubs provide sub-100ms pricing for conditional orders and quick trade options chains, with automatic REST fallback.
- **Broker Sync Service**: A regular service to reconcile database state with actual broker states, detecting order fills/cancellations, position changes, and account updates.
- **Notification System**: Provides Discord webhook notifications for various trading events and desktop browser notifications.
- **Security & Authentication**: Implements admin account management with password hashing, email recovery, session-based authentication, rate limiting, and encrypted broker credentials. Schwab OAuth uses CSRF state tokens (single-use, 10-min TTL), PKCE, and postMessage-based popup flow with auto-close. Local flow uses a standalone HTTPS callback server on port 8182 that captures the auth code, then the settings page polls `/schwab/oauth-status` to trigger the token exchange.
- **Database Architecture**: Uses SQLite with WAL mode for concurrent read/write operations, storing critical trading data and encrypted credentials.
- **AI Analysis**: Integrates OpenAI GPT for pre-trade and post-trade analysis, an AI chat assistant, and AI command toggles.

**System Design Choices:**
- **Broker Isolation**: Prevents data cross-contamination by ensuring each broker's streaming data feeds only its own positions.
- **Thread Safety**: All shared states are protected by locks.
- **Queue-Based Execution**: Signals are processed asynchronously for non-blocking signal detection.
- **Hub-First Architecture**: Prioritizes cached streaming data before resorting to REST API calls.
- **Graceful Degradation**: Automatically falls back to REST polling if streaming services are unavailable.
- **Modular Broker Abstraction**: Uses a common interface for diverse broker APIs.
- **Market Isolation**: Conditional order services for different markets operate independently.
- **Conditional Order Guards**: Includes per-channel Breakout Reset Guard and Limit Cap to prevent undesirable order execution.

## External Dependencies

- **Python 3.8+**: Core runtime environment.
- **Flask**: Web framework.
- **discord.py-self**: Discord API.
- **Telethon**: Telegram client.
- **Webull, alpaca-py, ib-insync, robin-stocks**: Broker SDKs.
- **httpx**: HTTP client for Schwab API.
- **openai**: For AI analysis.
- **cryptography**: For encryption.
- **yfinance**: For market data.
- **ta**: For technical analysis.
- **aiohttp**: Asynchronous HTTP client.
- **pyotp**: For TOTP 2FA.
- **PySide6**: For setup wizard GUI.
- **paho-mqtt**: For Webull MQTT.
- **Chart.js**: Frontend data visualization.

## Critical Bug Fixes (March 2026)

### SCHWAB Sync Hang Fix
- **Root cause**: `asyncio.to_thread(httpx.Client)` pattern — blocked OS threads cannot be cancelled by `asyncio.wait_for`
- **Fix**: All Schwab HTTP calls now use `httpx.AsyncClient` (natively async, properly cancellable)
- **Files**: `src/brokers/schwab_broker.py`

### Routing Engine Hang Fix (ExitArbiter Lock Leak)
- **Root cause**: `ExitArbiter` returns `threading.Lock`, but code used `asyncio.wait_for(lock.acquire(), timeout=0.1)`. Since `lock.acquire()` is synchronous (returns `True` immediately), `asyncio.wait_for(True)` raises `TypeError`, preventing `acquired = True` from being set, so the `finally` block never released the lock. On next loop iteration, `lock.acquire()` blocked the event loop forever.
- **Fix**: Replaced `asyncio.wait_for(lock.acquire(), timeout=0.1)` with `lock.acquire(blocking=False)` — instant non-blocking acquire compatible with `threading.Lock`
- **Files**: `src/services/signal_routing_engine.py` (two locations: `_handle_risk_exit` and `handle_signal_exit`)

### SPXW/Index Option Alias Fix
- **Root cause**: Signal parser extracts "SPXW" from Discord messages, but brokers only recognize "SPX". Webull's `wb.get_ticker('SPXW')` throws `ValueError: TickerId could not be found`. Schwab's OCC symbol builder generates `SPXW  260304C...` instead of `SPX   260304C...`.
- **Fix**: Added `INDEX_ALIASES_IN` dict (`SPXW→SPX`, `NDXP→NDX`, `VIXW→VIX`, `RUTW→RUT`) applied at all broker API call points:
  - Webull `_blocking_place`: `broker_sym = fix_symbol(symbol, "in")` used for `get_ticker()`, `_get_market_price()`, and position matching
  - Webull `_get_current_option_quote`: normalized symbol for `get_option_quote(stock=...)` 
  - Webull `_build_option_hub_func`: normalized symbol for OCC key construction in slippage check
  - Webull prewarm cache: SPX entries also stored under SPXW alias key for instant cache hits
  - Schwab: NO alias needed — Schwab natively uses CBOE root symbols (SPXW, NDXP, etc.) in OCC format. Initial SPXW→SPX conversion was incorrect and reverted after live testing showed `SPX   260304C06885000` rejected by Schwab API.
  - Alpaca: Does not support index options at all — clean rejection with helpful error message already in place
- **Files**: `src/selfbot_webull.py`, `src/brokers/schwab_broker.py`

### Webhook Timeout Fix
- **Root cause**: `aiohttp.ClientSession` in routing engine had no timeout (default 300s), halting the routing engine whenever a webhook endpoint was slow
- **Fix**: `aiohttp.ClientSession` now created with `ClientTimeout(total=10)`; `_handle_risk_exit` wrapped with `asyncio.wait_for(timeout=15.0)`
- **Files**: `src/services/signal_routing_engine.py`

### Latency Optimizations (March 2026)
- **Slippage REST skip**: When hub has no price AND option_id isn't cached (first-time SPX trade), skips the 5-6s options chain REST lookup if `allow_when_no_quote=true`. Limit price protects against adverse fills. If option_id IS cached (from prewarm or prior trade), REST quote proceeds normally.
- **Cached BP checks**: Universal multi-broker BP check and Webull `_blocking_place` BP check now use health monitor's cached account data (0ms) instead of live API calls (~500ms each). Falls back to live API if cache unavailable.
- **Files**: `src/selfbot_webull.py`

## Risk Engine Direct Exit Architecture

The risk engine now has a dual-path exit execution system to ensure stop-loss orders ALWAYS execute, even when the event loop is blocked:

1. **Primary path**: STC signal queued to `order_queue` → Worker picks up immediately (bypasses sync_ready gate for `_risk_management_order` signals)
2. **Backup path**: A daemon thread waits 8 seconds, then checks if the worker handled the order. If not (queue still has items AND position still marked closing), the thread creates its own event loop and calls the broker's sell function directly.

Key changes:
- **Worker sync bypass**: Worker starts processing immediately after `broker_ready`. Risk orders (`_risk_management_order=True`) execute without waiting for `sync_ready`. Regular BTO signals are held until first sync completes.
- **Parallel broker sync**: `broker_sync_service.py` runs all broker syncs in parallel (not sequential) with a 30s shared deadline. Each broker's `_fetch_account_info` has a 15s timeout.
- **Stale closing flags**: `position_cache.py` clears `closing=True` flags on startup to prevent risk engine from skipping positions where previous exit orders failed.
- **Direct exit thread**: `position_monitor.py` spawns a daemon thread per STC order as a safety net. If the event loop is blocked (e.g., by Robinhood's synchronous HTTP calls via robin_stocks), the thread executes independently.
- **After-hours gate**: Risk engine suppresses exit orders outside trading hours. Options: regular hours only (9:30-4:00 ET). Stocks: regular + extended hours (4:00 AM - 8:00 PM ET). Logs `⏸️ AFTER HOURS` once per position, re-evaluates when market opens.
- **SPX/SPXW alias normalization**: Applied across all matching layers — `position_monitor.py` (risk settings lookup, trade ID matching), `selfbot_webull.py` (STC position matching), `live_snapshot.py` (`_make_match_key` canonicalizes SPXW→SPX, NDXP→NDX), `broker_sync_service.py` (`_normalize_symbol` includes NDXP).

## Signal Parser — Phoenix & JaCOB

- **Phoenix** (`signal_format_registry.py`): Small-cap stock momentum signals. Entry patterns: "SYMBOL over PRICE SL X%", "in SYMBOL PRICE SL X%", "taking position SYMBOL PRICE". Exit patterns: "selling X% here SYMBOL", "leaving X%", "out of SYMBOL", "SL hit with SYMBOL", "SYMBOL SL hit". Handles typos (ocer/ober/iver). Role pings stripped by `parse()` before matching — patterns use `^\s*` anchors, not `<@&\d+>`.
- **JaCOB** (`parser.py`): Structured stock signals with bracket order data. Format: "ENTERED LONG/SHORT: $SYMBOL / ENTRY: $PRICE / S.L: $PRICE / 1st Target: $PRICE". Supports position sizing ("X% OF ACCOUNT"). Returns `_bracket_order=True`, `_calculate_qty=True`.
- **Learned patterns**: Reserved word filter in `_parse_learned_pattern_with_metadata` prevents "HERE", "MORE", "NOW" etc. from being captured as symbols.
- **Entry Confirmation** (`entry_confirmation_pct`): Per-channel setting that requires price to go +X% above the signal's watching price before executing. Works for all signal types: Phoenix stock entries, JaCOB bracket orders, option BTO signals, and explicit conditional orders. Routes through the conditional order service. Bypasses `conditional_order_enabled` check (works independently). Does NOT double-apply with `trigger_offset_percent`. All Phoenix parsers now consistently set `trigger_price` for the watching price.