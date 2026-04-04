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
- **WebSocket Streaming**: Utilizes Webull MQTT and an optimized Schwab WebSocket system for real-time quotes and orders, providing sub-100ms pricing for conditional orders and quick trade options chains. Options chain UI uses poll-first architecture (500ms interval to `/api/options/stream-quotes`) with optional SSE upgrade via `/api/options/chain-stream`. Includes cross-broker streaming subscription (Webull→Schwab OCC key cross-sub) and immediate BTO symbol subscription. Key format normalization: Webull hub stores underscore keys (`SPY_654_C`), Schwab hub stores OCC keys (`SPY   260401C00654000`), frontend uses underscore. All endpoints convert between formats.
- **Daily P&L Limit System**: Per-broker daily P&L tracking against SOD equity snapshots, with configurable dollar and percentage limits for profit targets and loss limits. Max Daily Trades enforcement works independently of the P&L dollar/percentage master toggle — trade counting and locking activate whenever a trade limit is configured, even if the full P&L system is disabled. Stale P&L locks (loss/profit) are normalized when P&L is disabled so they don't block trade-limit enforcement.
- **Broker Sync Service**: Reconciles database state with actual broker states, detecting order fills/cancellations, position changes, and account updates. Adaptive fill sync cadence: every cycle when PENDING/OPEN trades exist, every 5 cycles when idle.
- **Fill Accuracy Architecture**: A five-layer fill-to-PNL pipeline ensures accurate tracking of entry and exit fills. Unified `process_filled_order_event()` in `gui_app/database.py` propagates fills to both `trades` and `signal_lots`/`lot_closures` tables via single idempotent call with `BEGIN IMMEDIATE` transaction safety. Channel-strict matching: all fallback lot matching requires known `channel_id` to prevent cross-channel P&L contamination. Position-disappearance closures using `last_sync` prices are tagged `provisional_sync` and overwritten when deterministic fills arrive.
- **Order Chaser Service**: Monitors unfilled exit/entry orders and replaces stale ones with better prices, tracking all STC orders (risk management and signal STCs).
- **Security & Authentication**: Implements admin account management, password hashing, email recovery, session-based authentication, rate limiting, and encrypted broker credentials, with Schwab OAuth using CSRF state tokens and PKCE.
- **Database Architecture**: Uses SQLite with WAL mode for concurrent read/write operations, storing trading data and encrypted credentials. Includes retry mechanisms for critical exit bookkeeping.
- **AI Analysis**: Integrates OpenAI GPT for pre-trade/post-trade analysis, an AI chat assistant, and AI command toggles.
- **Risk Engine Direct Exit Architecture**: Dual-path exit execution system (primary queue-based, backup daemon thread at 5s for direct calls) with an Exit Lease Manager to prevent duplicate exits.
- **Risk Engine Speed Optimizations**: Lowered interval floor, early-wake sleep chunking, cached service checks, throttled cache saves, parallel broker fetches, REST position cache, hub-first approaches, cross-broker price updates, and a staleness guard.
- **Event-Driven Fill Watch System**: Activates rapid position polling after BTO orders, with broker-specific intervals, detecting new positions or quantity increases.
- **Risk Engine Staleness Gate**: Pre-execution staleness protection for risk exits with REST/cross-hub validated override. States: `_rest_confirmed_this_cycle` (REST returned different price, per-cycle), `_rest_validated_same` (REST or cross-hub confirmed same price is real, 30s TTL). Validation requires passing sanity checks (no 30%+ deviation rejection). Repair cycles allow exit evaluation only when REST-confirmed. Partial exits protected by `_partial_exit_in_flight` (per-tier, 30s TTL) preventing double-trim. Cross-hub zombie detection via `_is_hub_live()` requires actual tick receipt (`_last_quote_ts > 0`) and recency (< 120s). Worker lease is fail-closed (exceptions skip exit instead of proceeding). `dynamic_sl` classified as SL-type for market order routing.
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
- **Progressive Broker Bracket Orders**: In risk/hybrid exit mode, broker-side SL stop + PT1 limit orders are placed immediately after entry fill detection. When each PT tier hits, the next PT is placed at broker and dynamic SL is updated via the existing `_sync_stop_to_broker` flow. Cascade is idempotent (guarded by `broker_pt_tier` inside per-position lock), and outstanding bracket orders are cancelled before full exits. All bracket ops (SYNC_STOP, PLACE_PT) are serialized through a per-position `asyncio.PriorityQueue` worker (`_enqueue_broker_op`), with SYNC_STOP at priority 10 and PT placement at priority 20, guaranteeing SL updates always execute before PT cascades. Single cascade trigger path in `evaluate_tiered_targets`. Failed PT placements retry up to 2 times with 1s delay. All PT orders are registered with the order chaser via `_register_pt_with_chaser`; when the chaser replaces a stale PT order, it syncs `cache.broker_pt_order_id` back to the risk cache via `_sync_broker_pt_order_id`. Chaser uses progressive price escalation: attempt 1 = mid-price (bid+ask avg), attempt 2 = bid price (aggressive fill), attempt 3 = market order (price=0, guaranteed fill). Market order replacements are tracked with max chase_attempts to prevent re-chasing. If the 3rd-attempt market order also fails, it records exit failure so the risk engine retries. Supported brokers: Schwab, Alpaca. Cache fields: `broker_pt_order_id`, `broker_pt_tier`, `broker_orders_placed`.
- **Unsettled Funds Position Sizing Fix**: Caps `sizing_base`, `buying_power`, and `options_buying_power` to `settled_cash` when available, preventing Good Faith Violations.
- **Session-Aware REST Price Guard**: REST fallback methods reject stale `last`/`lastPrice` values outside regular trading hours, accepting only bid/ask midpoint or Webull pPrice during extended hours.
- **SYNC-RISK Coordination Guard**: `broker_sync_service.py` checks the risk engine position cache before cancelling or closing trades, preventing erroneous actions due to transient broker API issues.
- **Channel Inheritance on Auto-Import**: `auto_import_manual_position` now inherits `channel_id` from OPEN/PENDING trades first (with full option identity matching including call_put), then falls back to recently-closed trades within 1hr. Risk engine pre-loads trade→position mappings at startup and refreshes every 30s, ensuring channel risk settings work even when Broker Sync Service is disabled.
- **Staleness Gate Selective Blocking**: Staleness gate no longer blanket-blocks all exits. It sets a `_staleness_is_blocking` flag and only blocks stop-loss type exits (SL, dynamic SL, trailing stop, giveback guard, EMA exits). Profit targets always pass through even on stale prices — selling at a stale high is favorable.
- **Stale Tier Flag Fix (Same-Symbol Re-Entry)**: Three-layer fix preventing stale `pt1_hit`/tier flags from carrying over when the same stock is re-entered on the same broker: (1) Zero-position cache cleanup runs after 3 consecutive cleanup windows with 0 positions and no active leases/pending orders/fill watches. (2) Trade-ID rollover detection in `get_or_create()` checks if the cached trade_id points to a CLOSED/CANCELLED trade — if so, full risk state reset regardless of closing/giveback flags. (3) Pending order fill confirmation now stores and validates `trade_id` to reject stale fills from a previous trade instance.
- **SPX Index Price Contamination Guard**: Routing engine price monitoring could misclassify options as equities when `position.strike` was 0/None, causing hub lookups to return the SPX index price (~$6,487) instead of the option premium (~$6.30). Fix: improved `is_option` detection using both `strike` and `option_type`, skip hub lookups for options with missing strike, and added a >50x entry-price ratio guard on both hub and REST prices to reject underlying index prices masquerading as option premiums.
- **Options Chain Multi-Broker Streaming Fix (5-part)**: Cross-subscription was sending Webull's numeric ticker IDs (e.g., `1059081524`) to Schwab's WebSocket which expects OCC symbols (`SPY   260401C00654000`). (1) Frontend now sends `expiry` in subscribe-stream request for OCC key construction. (2) Cross-sub builds proper OCC keys from `symbol.ljust(6) + YYMMDD + C/P + strike*1000 zfill(8)`. (3) `WebullDataHub.get_quote()` now accepts optional `max_age` parameter — chain overlay was failing with TypeError. (4) `SchwabDataHub` now has `_quotes_lock` for thread-safe access — stream-quotes endpoint was skipping Schwab entirely. (5) All three data paths (chain overlay, stream-quotes, SSE chain-stream) convert OCC→underscore format for frontend compatibility.
- **Advanced Tab Nesting Fix**: The `risk-tab-advanced` div in `channels.js` was nested INSIDE the `risk-tab-targets` div due to a missing `</div>` closing tag. When `switchRiskTab()` hid the targets pane, the advanced pane (as a child) was also hidden. Fixed by adding the missing closing div to make both tabs siblings. Also quoted all channel.id references in onclick handlers as strings to prevent JS precision loss on 18-19 digit Discord IDs.
- **Multi-Broker STC Qty Fix (3-part)**: (1) STC DB save now writes one trade per successful broker with actual `executed_qty` instead of a single shared entry using `signal['qty']`. (2) Added `original_quantity` column to trades table — set on BTO insert, preserved by sync when broker qty decreases after partial exits. (3) Initial trim qty query includes `original_quantity` for better estimates; TRIM FIX per-broker recalculation remains the authoritative correction.
- **Partial Exit PNL Fix (4-part)**: (1) STC trades now auto-link to BTO via `origin_trade_id` at save time (lookup open + closed BTO). (2) `reconcile_trade_fill_price` now calculates and sets PNL on individual STC trade records (not just BTO aggregate). (3) `broker_closed_position` in sync service aggregates PNL from all linked STCs using `original_quantity` instead of reduced qty. (4) Dashboard shows `original_quantity` for closed BTO trades with partial exits.
- **Daily PNL Baseline Fix**: `update_broker_pnl` was using the 9:30am SOD snapshot as baseline, which included unrealized gains from pre-market positions. When those positions closed for profit, the gains were invisible because they were already baked into the SOD baseline. Fix: always use the pre-market (4am) snapshot as baseline when available, capturing the full day's PNL. Also updates `sod_equity` in the locked-state branch so the corrected baseline propagates even when a broker is already locked.
- **Exit Notification Classification Fix**: Notification dispatch in `position_monitor.py` was using fragile reason-string matching (`'STOP LOSS' in reason`, `'TRAILING' in reason`) to classify exit types. Dynamic SL exits showed as "stop loss hit", EMA exits sent no notification at all, and early trailing exits were missed (reason "EARLY TRAIL" doesn't contain "TRAILING"). Fix: dispatch now keys off `decision.risk_trigger` field (`stop_loss`, `dynamic_sl`, `trailing_stop`, `early_trailing`, `profit_target`, `giveback_guard`, `ema_exit`, `ema_no_trend`). Added `ExitDecision.dynamic_sl()` factory, `notify_dynamic_sl_triggered()` and `notify_ema_exit_triggered()` notification functions, and proper event recording for `DYNAMIC_SL`, `EMA_EXIT`, `EMA_NO_TREND` event types.

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