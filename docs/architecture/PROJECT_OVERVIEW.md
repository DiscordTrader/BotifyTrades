# BotifyTrades v12 — Project Overview

**AI-Powered Multi-Broker Trading Bot** | Discord/Telegram Signal Intelligence | Automated Execution

A Python 3.11 desktop application that monitors Discord and Telegram channels for trading signals, parses them via 157+ regex formats with AI fallback, and automatically executes trades across 12 brokers. Includes a Flask web GUI (250+ endpoints), real-time position monitoring, a 6-level risk management engine, and PyInstaller packaging for Windows/macOS/Linux.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Entry Points](#entry-points)
3. [Signal Processing Pipeline](#signal-processing-pipeline)
4. [Broker Integrations](#broker-integrations)
5. [Risk Management Engine](#risk-management-engine)
6. [Services Layer](#services-layer)
7. [Web GUI & API](#web-gui--api)
8. [Database Schema](#database-schema)
9. [Background Jobs & Loops](#background-jobs--loops)
10. [Peripheral Systems](#peripheral-systems)
11. [Build & Deployment](#build--deployment)
12. [Technical Debt](#technical-debt)
13. [File Size Inventory](#file-size-inventory)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           ENTRY POINT                                    │
│                     src/selfbot_webull.py (23.6K lines)                   │
│   Discord Selfbot  |  Telegram Listener  |  Flask GUI Thread             │
└────────┬───────────────────┬──────────────────────┬──────────────────────┘
         │                   │                      │
    ┌────▼────┐        ┌─────▼─────┐          ┌─────▼─────┐
    │ Discord │        │ Telegram  │          │ Flask GUI │
    │on_message│       │ bridge()  │          │ :5000     │
    └────┬────┘        └─────┬─────┘          └─────┬─────┘
         │                   │                      │
         └───────────┬───────┘            ┌─────────┘
                     ▼                    ▼
         ┌───────────────────┐   ┌───────────────────┐
         │  Signal Parsing   │   │  routes.py 23.5K   │
         │  Pipeline (5-tier)│   │  250+ endpoints    │
         └────────┬──────────┘   │  database.py 15.4K │
                  ▼              │  74 SQLite tables   │
         ┌───────────────────┐   └───────────────────┘
         │  Order Queue      │
         │  (Priority-based) │
         └────────┬──────────┘
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    BROKER LAYER (12 brokers)                     │
│  Schwab│Webull│IBKR│Alpaca│Tastytrade│Robinhood│Trading212│...  │
│  BrokerInterface ABC → OrderResult dataclass                     │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DATA HUB LAYER                                │
│  WebullDataHub(MQTT) │ SchwabDataHub(WS) │ IBKRDataHub(TWS)     │
│  TastetradeDataHub(DXLink) │ Trading212DataHub                   │
│                    ▼                                             │
│              UnifiedPriceHub (cross-broker aggregation)           │
└─────────────────────────────┬───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   RISK ENGINE (0.2s loop)                        │
│  position_monitor.py (10.3K lines) — RiskManager singleton       │
│  6-level exit priority chain │ PositionCache persistence         │
│  Industry-grade retry │ Exit lease system │ Multi-broker fetch    │
└─────────────────────────────────────────────────────────────────┘
```

### Key Patterns

- **Singleton + Event Bus**: All data hubs and services are thread-safe singletons connected via on/off/emit events
- **Hub-First Pricing**: Every price lookup checks streaming WebSocket caches before REST API fallback (zero API cost)
- **Priority Queue**: Risk-triggered exits take precedence over normal signal orders
- **Thread Model**: Discord bot runs in its own asyncio event loop thread; Telegram in another; Flask GUI in a daemon thread; risk monitoring as an asyncio task within the Discord loop

---

## Entry Points

### Primary: `src/selfbot_webull.py`

The monolithic main file (23,597 lines / 1.4MB) containing the entire bot lifecycle:

```
if __name__ == '__main__':              # L23132
├── multiprocessing.freeze_support()    # PyInstaller support
├── atexit.register(cleanup_resources)  # DB close, task cancel, GC
├── Single instance check               # Prevents duplicate runs
├── argparse: --port, --wizard, --no-gui
├── GUI Mode (frozen + display):
│   ├── PySide6 QApplication + SplashScreen
│   ├── License validation gate
│   └── do_startup() thread → run_bot_startup()
└── Console Mode:
    └── run_bot_startup() → run_main_loop()

run_bot_startup():                      # L22878
├── start_gui_server()                  # Flask in daemon thread (:5000)
├── Init UnifiedPriceHub
├── Start Discord bot thread            # asyncio.run(discord_main())
├── Start Telegram bot thread           # asyncio.run(telegram_main())
├── Wait for Discord ready (30s)
└── Wait for Telegram ready (15s)
```

### Secondary Entry Points

| File | Purpose |
|------|---------|
| `gui_app/app.py` | Flask factory (`create_app()` + `start_gui_server()`) |
| `admin_panel/app.py` | License admin Flask app |
| `agent_studio/run.py` | Agent Studio Flask app (separate port) |
| `license_server/main.py` | FastAPI license server (PostgreSQL) |
| `start.py` | Minimal wrapper calling `selfbot_webull` |
| `wsgi.py` | WSGI entry for Gunicorn deployment |

### Classes in `selfbot_webull.py`

| Class | Lines | Purpose |
|-------|-------|---------|
| `SelfClient(discord.Client)` | L7347–22600 | Core Discord bot — event handlers, signal processing, broker init, worker loop |
| `WebullBroker` | L2026–7300 | Webull SDK wrapper (duplicated from `src/brokers/`) |
| `_PriorityOrderQueue` | L7319 | asyncio.Queue with risk/normal priority levels |
| `SlippageDecision(Enum)` | L1998 | IMMEDIATE / WAIT / ABORT |

---

## Signal Processing Pipeline

Five-tier parsing cascade, first match wins:

```
Discord/Telegram Message
  │
  ├─ Tier 1: Embed Parsers (Spy-Sniper, Sir Goldman)
  │     └── Specialized parsers for Discord embed formats
  │
  ├─ Tier 2: SignalFormatRegistry (157 builtin regex formats)
  │     └── src/services/signal_format_registry.py (4763 lines)
  │     └── Priority-ordered (0-100), organized by trader family:
  │         Jake, Slem, STACK$, Foxtrades, Bronze Swings, Phoenix,
  │         Jacob, ProTrader, Quick-Swing, Temple ZZ, Ashley, Angela,
  │         Rocky, Infra Trade, AbTrades + learned patterns from DB
  │
  ├─ Tier 3: Channel-Specific Parsers (src/signals/)
  │     └── 17 parser files: temple (56KB), spy_sniper (19KB),
  │         equity_genie (18KB), sir_goldman (12.7KB), bronze_swings,
  │         kc_trades, namrood, foxtrades, viking, jpm, hengy, eagle,
  │         abtrades, bullwinkle, jake, bishop, evapanda, toon
  │     └── Plus core parser.py (3339 lines, 15+ regex pattern groups)
  │
  ├─ Tier 4: Standard BTO/STC Regex
  │     └── OPT_REGEX, STK_REGEX (compiled from DB or defaults)
  │     └── DTE_OPT_REGEX, TRADE_ECHO_REGEX, ~15 more patterns
  │
  └─ Tier 5: AI Fallback (confidence >= 0.8)
        └── src/services/ai_signal_parser.py (763 lines)
        └── Providers: OpenAI (gpt-4o-mini), Claude (claude-haiku-4-5),
            Gemini (gemini-2.0-flash)
        └── MD5-keyed 1hr cache, asyncio.Semaphore(3) rate limit
        └── Few-shot prompting with registry examples
        └── Security: requires admin approval for auto-execution
```

### Auto-Learn Pipeline

`src/services/format_learning_pipeline.py` (443 lines) — discovers new signal formats:

1. Extract last 1000 messages from Discord channel
2. Hybrid analysis: heuristic regex scan + AI (FormatTrainer)
3. Cross-validate against existing registry, deduplicate
4. Present candidates with confidence scores for user approval
5. Approved formats auto-register in SignalFormatRegistry

---

## Broker Integrations

### Interface

`src/broker_interface.py` defines `BrokerInterface` ABC with 7 abstract methods:

```python
connect() → bool
disconnect()
get_account_info() → dict
get_positions() → dict
place_stock_order(symbol, action, quantity, price, ...) → OrderResult
place_option_order(symbol, strike, expiry, option_type, action, quantity, price, ...) → OrderResult
get_quote(symbol) → dict
```

Returns standardized `OrderResult(success, order_id, message, price, quantity, symbol, action)`.

### Registered Brokers (12)

| Broker | File | Lines | Size | Auth | Stocks | Options |
|--------|------|-------|------|------|--------|---------|
| **Schwab** | `schwab_broker.py` | 3712 | 183KB | OAuth2 (code→tokens) | ✓ | ✓ |
| **Webull** (legacy) | `webull_broker.py` | 1833 | 86KB | Token (access+refresh+did) | ✓ | ✓ |
| **Webull Official** | `webull_official/` | ~1600 | 96KB | HMAC-SHA1 + mobile approval | ✓ | ✓ |
| **IBKR** | `ibkr_broker.py` | 1150 | 52KB | TCP socket to TWS/Gateway | ✓ | ✓ |
| **Alpaca** | `alpaca_broker.py` | 1213 | 56KB | API key + secret | ✓ | ✓ |
| **Tastytrade** | `tastytrade_broker.py` | 1473 | 68KB | OAuth2 (refresh_token) | ✓ | ✓ |
| **Robinhood** | `robinhood_broker.py` | 1112 | 48KB | User/pass + TOTP 2FA | ✓ | ✓ |
| **Trading212** | `trading212_broker.py` | ~750 | 29KB | API key | ✓ | ✗ |
| **Questrade** | `questrade_broker.py` | 234 | 8KB | API key | stub | stub |
| **Zerodha** | `zerodha_broker.py` | ~870 | 36KB | India market | ✓ | ✓ |
| **Upstox** | `upstox_broker.py` | ~1626 | 72KB | India market | ✓ | ✓ |
| **DhanQ** | `dhanq_broker.py` | ~1103 | 42KB | India market | ✓ | ✓ |

### Orchestration

`src/broker_manager.py` (358 lines) — **strict routing** with no default broker fallback. All trades specify a broker via channel configuration or `[BROKER]` message prefix. Selection methods: `prefix` / `channel` / `default`.

### Key Broker-Specific Details

- **Schwab**: API budget tracking (120 calls/min, throttle at 96), 429 global backoff, price band rejection auto-retry, OCO bracket orders, CBOE option increment rounding
- **Webull Official**: HMAC-SHA1 request signing, token creation polls mobile app approval every 5s (120s timeout)
- **IBKR**: ib_insync event-driven architecture, auto-fallback TWS↔Gateway ports, event loop circuit breaker for REST quotes (10min cooldown)
- **Robinhood**: Unofficial `robin-stocks` library — **no paper trading, all trades LIVE**
- **All**: Extended hours auto-detection (MARKET→LIMIT conversion), auto-adjust quantity on insufficient funds, settled vs unsettled cash tracking

---

## Risk Management Engine

### Architecture

`src/risk/` — 11 files, ~15,319 lines, ~788KB

The risk system runs as a persistent async loop (0.2s default interval) evaluating all open positions against streaming WebSocket prices.

### Core Components

| File | Lines | Purpose |
|------|-------|---------|
| `position_monitor.py` | 10,293 | **RiskManager** singleton — monitoring loop, position fetching for 8+ brokers, exit execution, bracket management, order chasing |
| `risk_engine.py` | 790 | Pure-function evaluator: `evaluate_exit_actions(state, config) → (actions, state)` |
| `risk_types.py` | 654 | Core types: `PositionSnapshot`, `RiskSettings`, `ChannelRiskSettings` (60+ fields), `ExitDecision`, `PendingRiskOrder` |
| `position_cache.py` | 1,353 | Thread-safe position state persistence (.position_cache.json + DB), entry-price flip-flop detection, industry-grade retry |
| `ema_engine.py` | 1,110 | EMA-5 candlestick risk engine: `CandleAggregator` → `EMAEngine` → `EMAExitEvaluator`, pre-warm service for SPY/QQQ/SPX/NDX |
| `tiered_targets.py` | 402 | PT1–PT4 partial exits with custom qty/trim%/auto-split, leave-runner reservation |
| `trailing_stop.py` | 162 | Traditional trailing stop: activate at threshold, trail below highest price |
| `early_trailing.py` | 222 | State machine (INACTIVE→BREAKEVEN_LOCKED→PROFIT_LOCKED), step-based profit locking |
| `exit_lease_manager.py` | 135 | Thread-safe lease system preventing duplicate exit orders (180s expiry) |
| `global_risk.py` | 99 | Fallback evaluator for positions without channel settings |

### 6-Level Exit Priority Chain

Evaluated in strict order by `risk_engine.evaluate_exit_actions()`:

| Priority | Exit Type | Trigger | Action |
|----------|-----------|---------|--------|
| 1 | **Hard Stop Loss** | PnL ≤ −SL% | Full exit |
| 2 | **Dynamic SL** | Escalating SL after PT hits (3 profiles: conservative/standard/aggressive) | Move stop |
| 2.5 | **EMA Exit** | 5-min candle crosses through EMA line | Full exit or escalate stop |
| 3 | **Giveback Guard** | PnL drops below `max_pnl × (1 − giveback%)` | Full exit |
| 4 | **Early Trailing** | Breakeven lock at activation%, then step% profit lock | Full exit |
| 4.5 | **PT Near-Lock** | Tight trailing when within threshold% of unmet PT | Partial/full exit |
| 5 | **Tiered Profit Targets** | PT1–PT4 hit sequentially | Partial exits (custom qty/trim%) |
| 6 | **Legacy Trailing Stop** | Activated at threshold%, trails below peak | Full exit |

### Position Cache Retry System

Industry-grade exit order retry built into `position_cache.py`:

- **Fast mode**: 5 retries with exponential backoff (3s–10s)
- **Extended mode**: 5-minute intervals, indefinite
- **Emergency mode**: 3s–10s max (for stop-losses only)
- **Market-order escalation**: After 2 limit failures, auto-switches to market
- **Permanent failure detection**: Expired/delisted symbols, 3 consecutive no-position streaks

### Channel Risk Settings

`ChannelRiskSettings` has 60+ configurable fields per Discord channel:

- 4-tier profit targets with independent pct/qty/trim_pct per tier
- Stop loss, trailing stop, trailing activation
- Leave-runner (keep % of position for extended moves)
- Trim/SL order modes (market/limit with configurable offset)
- Exit strategy mode: SIGNAL / RISK / HYBRID
- Dynamic SL profile: conservative / standard / aggressive
- Giveback guard, early trailing, PT near-lock
- EMA risk (period, timeframe, buffer, escalation)
- Broker bracket mode (OCO orders)

---

## Services Layer

`src/services/` — 49 Python files + `conditional_orders/` subdirectory (5 files), ~2.85MB

### Data Hubs (Streaming Price Infrastructure)

| Hub | Protocol | File |
|-----|----------|------|
| `WebullDataHub` | MQTT via `wspush.webullbroker.com:443` | `webull_data_hub.py` (454 lines) |
| `SchwabDataHub` | WebSocket (LEVELONE_EQUITIES/OPTIONS) | `schwab_data_hub.py` (364 lines) |
| `IBKRDataHub` | ib_insync native events (pendingTickersEvent) | `ibkr_data_hub.py` (983 lines) |
| `TastetradeDataHub` | DXLink streaming | `tastytrade_data_hub.py` (17.4KB) |
| `Trading212DataHub` | REST polling | `trading212_data_hub.py` (11KB) |
| **UnifiedPriceHub** | Aggregates all hubs | `unified_price_hub.py` (782 lines) |

UnifiedPriceHub provides `UnifiedQuote` objects with bid/ask/last/greeks per symbol. Freshness classification: fresh (<3s) / aging (<5s) / stale (<10s) / degraded (<30s) / unverified.

### Position Management Services

| Service | File | Lines | Purpose |
|---------|------|-------|---------|
| `BrokerSyncService` | `broker_sync_service.py` | 4453 | 30s reconciliation loop across 14+ brokers |
| `PositionLedger` | `position_ledger.py` | 991 | Single Source of Truth for signal-based positions (SQLite-backed) |
| `SignalExitManager` | `signal_exit_manager.py` | 800 | Signal provider SL/PT lifecycle, edit debouncing (100ms) |
| `ExitOrderArbiter` | `exit_order_arbiter.py` | 327 | Signal vs risk exit precedence (SIGNAL/RISK/HYBRID modes) |
| `ExitDispatcher` | `exit_dispatcher.py` | ~300 | Unified exit routing from signal/risk/manual sources |
| `UnfilledOrderChaser` | `unfilled_order_chaser.py` | 2271 | Replaces stale pending orders with better prices (1s timeout, 3 max attempts) |

### Signal Processing Services

| Service | File | Lines | Purpose |
|---------|------|-------|---------|
| `SignalFormatRegistry` | `signal_format_registry.py` | 4763 | 157 builtin regex format handlers + learned patterns |
| `AISignalParser` | `ai_signal_parser.py` | 763 | Multi-provider AI parsing with caching and confidence gating |
| `SignalParsingPipeline` | `signal_parsing_pipeline.py` | 491 | Unified 5-tier parsing with dedup (5-min TTL) |
| `SignalRoutingEngine` | `signal_routing_engine.py` | 1740 | Forwarding-only architecture for webhook-based signal delivery |
| `FormatLearningPipeline` | `format_learning_pipeline.py` | 443 | Auto-discovery of new signal formats from channel history |
| `SignalVerificationService` | `signal_verification.py` | 1500 | Verifies signals against real-time market data, trust scoring |

### Safety & Control Services

| Service | File | Lines | Purpose |
|---------|------|-------|---------|
| `CircuitBreaker` | `circuit_breaker.py` | 318 | Global kill switch, per-channel halts, daily loss limits |
| `BrokerHealthMonitor` | `broker_health_monitor.py` | 827 | Connection/buying power monitoring for 14 broker variants |
| `DailyPnLLimitService` | `daily_pnl_limit_service.py` | 548 | Realized+unrealized P&L per broker against daily loss/profit limits |
| `QuoteAggregator` | `quote_aggregator.py` | 686 | Multi-broker quote fetching with priority-based fallback |

### Conditional Orders

`src/services/conditional_orders/` — market-routed conditional order system:

| File | Lines | Purpose |
|------|-------|---------|
| `base.py` | 3014 | Abstract base with `OrderStatus` enum, `StreamingPriceMonitor` (250ms), `BrokerPriceMonitor` |
| `router.py` | ~230 | Routes orders to market-specific services (US/India/Canada) |
| `us_service.py` | ~280 | US market conditional orders |
| `india_service.py` | ~280 | India market (NSE) with Upstox/Zerodha |
| `canada_service.py` | ~100 | Canada market with Questrade |

Plus legacy `conditional_order_service.py` (1539 lines) — older non-routed version, both coexist.

### Other Notable Services

| Service | File | Size | Purpose |
|---------|------|------|---------|
| `Simulation` | `simulation.py` | 147KB | Monte Carlo, Kelly Criterion, risk optimization |
| `RelayClient` | `relay_client.py` | 24KB | WebSocket relay for mobile app remote access |
| `ExpiryResolver` | `expiry_resolver.py` | 28KB | Resolves ambiguous expiry dates (0DTE, weekly, etc.) |
| `NDX/QQQ Converter` | `ndx_qqq_converter.py` | 25KB | Index-to-ETF option mapping |
| `BrokerLifecycleManager` | `lifecycle_manager.py` | 13KB | Start/stop/restart for Discord/Telegram processes |
| `RateLimitManager` | `rate_limit_manager.py` | 11KB | Per-broker API rate limiting with sliding window |
| `MarketHours` | `market_hours.py` | 5KB | US market open/close/pre-market/after-hours detection |

---

## Web GUI & API

### Flask App

`gui_app/app.py` — Factory pattern, started as a daemon thread on `0.0.0.0:5000`.

- **Auth**: Session-based with `login_required` / `admin_required` decorators
- **Rate limiting**: 5 login attempts per 5 minutes per IP
- **Build types**: `ADMIN` (full access) vs `USER` (restricted features)
- **No blueprints** except `schwab_auth` OAuth2 flow — all other routes in monolithic `register_routes(app)`

### Route Categories (~250 endpoints)

| Category | Example Endpoints | Count |
|----------|-------------------|-------|
| **Pages** | `/`, `/trades`, `/settings`, `/channels`, `/options`, `/pnl`, `/leaderboard` | ~25 |
| **Channel CRUD** | `/api/channels` (GET/POST), `/api/channels/<id>` (PUT/DELETE), `/api/channels/<id>/scan` | ~10 |
| **Trade Management** | `/api/trades`, `/api/trades/<id>/close`, `/api/trades/close-all`, `/api/filled-orders` | ~15 |
| **Broker Balances** | `/api/schwab/balance`, `/api/webull/balance`, `/api/ibkr/balance`, ... | 8 |
| **Broker Positions** | `/api/<broker>/positions/<symbol>/close`, `/api/orders/<broker>/<id>/cancel` | ~10 |
| **Options** | `/api/options/chain`, `/api/options/order`, `/api/options/chain-stream` (SSE) | ~10 |
| **Settings** | `/api/settings`, `/api/settings/risk_management`, `/api/settings/ai_analysis`, ... | ~20 |
| **Broker Credentials** | `/api/brokers/credentials/<broker>` (GET/POST) for 9 broker types | ~20 |
| **PnL & Analytics** | `/api/pnl/detailed`, `/api/leaderboard`, `/api/performance`, `/api/broker-performance` | ~15 |
| **Simulation** | `/api/simulate`, `/api/simulate/monte-carlo`, `/api/simulate/optimizer` | ~12 |
| **AI Chat** | `/api/chat` (POST), `/api/chat/upload-log`, `/api/chat/suggestions` | ~7 |
| **Signal Formats** | `/api/signal-formats`, `/api/signal-formats/test-parse`, `/api/signal-formats/discover` | ~6 |
| **Signal Routing** | `/api/admin/signal-routing` (CRUD), `/api/admin/signal-routing/risk/<id>` | ~8 |
| **Conditional Orders** | `/api/conditional_orders` (GET), `/api/conditional_orders/<id>/cancel` | ~7 |
| **License** | `/api/license/activate`, `/api/license/validate`, `/api/license/deactivate` | ~6 |
| **Webhook** | `/api/webhook/config`, `/api/webhook/post_bto`, `/api/webhook/channels` | ~8 |
| **System** | `/api/bot/status`, `/api/bot/restart`, `/api/health/full`, `/api/upgrade/*` | ~20 |

### SSE Streaming Endpoints

1. **`/api/snapshot/stream`** — Real-time position updates pushed from `live_snapshot.py` daemon
2. **`/api/options/chain-stream`** — Real-time option chain quotes (80ms batch interval)

### GUI Modules

| Module | File | Lines | Purpose |
|--------|------|-------|---------|
| Routes | `routes.py` | 23,491 | All HTTP endpoints |
| Database | `database.py` | 15,383 | SQLite CRUD for 74 tables |
| Chat Assistant | `chat_assistant.py` | 4,727 | AI chatbot (50-topic knowledge base + OpenAI/Claude/Gemini) |
| Live Snapshot | `live_snapshot.py` | 1,484 | Background position polling → SSE push |
| Schwab OAuth | `schwab_auth.py` | 1,182 | Schwab OAuth2 Blueprint with token manager |
| Performance | `performance_analytics.py` | 1,163 | Trading performance calculations (EST/EDT) |
| Trade Monitor | `trade_monitor.py` | 1,020 | Monitors broker accounts, posts to Discord webhooks |
| Format Trainer | `format_trainer.py` | 759 | AI-powered signal format learning |
| Webhook Service | `webhook_service.py` | 705 | Posts BTO/STC signals to Discord webhooks |
| Config Service | `config_service.py` | ~170 | Fernet encryption for credentials (env → file → derive → generate) |

### HTML Templates (40+ pages)

Key templates by size:

| Template | Size | Purpose |
|----------|------|---------|
| `settings.html` | 298KB | All settings (brokers, risk, AI, Discord, trading) |
| `trades.html` | 229KB | Live trading monitor with SSE integration |
| `help.html` | 206KB | Comprehensive documentation/FAQ |
| `index.html` | 194KB | Dashboard with stats grid, balances, positions |
| `channels.html` | 180KB | Channel CRUD, broker assignment, risk per channel |
| `simulation.html` | 144KB | Portfolio simulation, Monte Carlo, risk optimizer |
| `signal_routing.html` | 97KB | Admin-only signal routing configuration |
| `architecture.html` | 95KB | System architecture visualization |

---

## Database Schema

**SQLite** (`bot_data.db`) with WAL mode, 30s timeout, `PRAGMA synchronous=NORMAL`.

### 74 Tables Organized by Domain

#### Core Trading (12 tables)

| Table | Rows | Purpose |
|-------|------|---------|
| `channels` | 13 | Discord channel configuration with broker assignments and risk settings |
| `trades` | 537 | Trade records (open/closed) with entry/exit prices, broker, P&L |
| `signals` | 229 | Parsed signal records with source channel, action, parsed fields |
| `signal_lots` | 304 | Individual signal lot tracking for multi-lot positions |
| `lot_closures` | 267 | Lot closure records with P&L |
| `execution_lots` | 430 | Broker execution lot tracking |
| `execution_closures` | 275 | Execution closure records |
| `filled_orders` | 690 | Completed order records across all brokers |
| `conditional_orders` | 334 | Price-level triggers with SL/PT awaiting execution |
| `conditional_order_audit` | 3,742 | Audit trail for conditional order state changes |
| `order_events` | 12,295 | Chronological order event log (placed, filled, cancelled, etc.) |
| `pending_order_metadata` | 452 | Metadata for orders awaiting fill |

#### Risk Management (6 tables)

| Table | Purpose |
|-------|---------|
| `risk_management_settings` | Per-channel risk configuration |
| `global_risk_settings` | Global SL/TP/trailing defaults |
| `position_risk_settings` | Per-position risk overrides |
| `daily_pnl_state` | Daily P&L tracking per broker |
| `risk_events` | Risk action audit log |
| `slippage_settings` | Slippage protection configuration |

#### Broker (6 tables)

| Table | Purpose |
|-------|---------|
| `broker_credentials` | Encrypted broker auth credentials |
| `broker_profiles` | Broker configuration profiles |
| `broker_states` | Connection status per broker variant (17 variants) |
| `broker_sync_state` | Last sync timestamp per broker |
| `broker_limits` | Per-broker rate/position limits |
| `broker_notifications` | Broker health alert state |

#### Signal Processing (11 tables)

| Table | Purpose |
|-------|---------|
| `signal_formats` | 11 registered signal format definitions |
| `signal_format_cache` | Cached format parse results |
| `signal_instances` | Per-signal instance tracking |
| `signal_event_transitions` | Signal lifecycle state changes |
| `signal_verifications` | Signal verification results |
| `verification_stats` | Aggregate verification statistics |
| `signal_routing_mappings` | Admin signal routing rules |
| `learned_patterns` | 4 AI-learned signal patterns |
| `format_candidates` | 14 pending format candidates for approval |
| `channel_messages` | 3,519 cached Discord channel messages |
| `channel_learning_state` | Per-channel format learning progress |

#### Configuration (8 tables)

| Table | Purpose |
|-------|---------|
| `settings` | 18 key-value application settings |
| `config` | 7 encrypted key-value entries (Fernet) |
| `ai_settings` | AI provider and model configuration |
| `trading_settings` | Trading behavior settings |
| `discord_settings` | Discord connection settings |
| `telegram_settings` | Telegram integration config |
| `email_config` | SMTP email settings |
| `trade_monitor_settings` | Trade monitor polling config |

#### Users & License (10 tables)

| Table | Purpose |
|-------|---------|
| `app_users` | 1 admin user |
| `end_users` | End-user accounts |
| `user_subscriptions` | Subscription tracking |
| `password_reset_tokens` | Password reset flow |
| `channel_allowed_users` | Per-channel user whitelist |
| `local_license` | Local license storage |
| `server_licenses` | Server-issued license records |
| `server_trials` | Trial license tracking |
| `server_machines` | Machine ID binding |
| `license_validation_log` | License validation audit |

#### Operations (12+ tables)

| Table | Purpose |
|-------|---------|
| `error_logs` | 170 application error records |
| `notification_log` | 1,236 notification records |
| `synced_orders` | 152 broker-synced order records |
| `service_registry` | 6 background service registrations |
| `service_metrics` | Service health metrics |
| `webhook_config/channels/positions/closures` | Webhook system state |
| `countries` | 3 market country definitions |
| `watchlist` | User watchlist entries |
| `known_issues` | 7 tracked known issues |
| `debug_reports` | Debug report submissions |

### Schema Management

- All tables created in `gui_app/database.py::init_db()` with `CREATE TABLE IF NOT EXISTS`
- Backward compatibility via `ALTER TABLE ... ADD COLUMN` migrations (inline, no versioned migration system for main tables)
- QA system (`qa/migration_manager.py`) provides versioned migrations separately but is not the primary mechanism

---

## Background Jobs & Loops

### In Discord Event Loop (asyncio tasks)

| Job | Location | Interval | Purpose |
|-----|----------|----------|---------|
| `worker()` | L19815 | Continuous | Main order processing loop — dequeues signals, resolves qty/broker, places orders |
| `telegram_signal_bridge()` | L19632 | Continuous | Polls thread-safe Queue from Telegram thread → async order queue |
| `risk_manager.start_monitoring()` | L8922 | 0.2s | Position monitoring + risk evaluation |
| `_gateway_watchdog()` | L8861 | Continuous | Force Discord reconnect if no messages for 2 min |
| `token_refresh_scheduler()` | L8961 | 12h | Webull/broker token refresh |
| `trade_analysis_scheduler()` | L8883 | Configurable | Post-trade AI analysis |
| `sentiment_task()` | L8957 | Periodic | Discord message sentiment analysis |
| `_sod_balance_scheduler()` | L9219 | Daily | Start-of-day balance snapshots |
| EMA risk engine task | L8992 | Tick-driven | Candlestick aggregation + EMA evaluation |
| License network monitor | — | 600s | License server connectivity check |

### In Separate Threads

| Job | Thread | Interval | Purpose |
|-----|--------|----------|---------|
| Flask GUI server | Daemon thread | Continuous | Web GUI on `:5000` |
| Discord bot | Dedicated thread | Continuous | `asyncio.run(discord_main())` |
| Telegram listener | Dedicated thread | Continuous | `asyncio.run(telegram_main())` |
| Live snapshot poller | Daemon thread | 3–6s per broker | Fetches positions → SSE push |
| `_proactive_refresh_loop()` | WebullBroker thread | 10min | Token refresh during market hours |
| `_start_power_resume_monitor()` | Windows thread | Continuous | Sleep/wake detection |
| Trade monitor | Background | 5s (market) / 30s (off) | Monitors broker accounts → Discord webhooks |

### Periodic Services

| Service | Interval | Purpose |
|---------|----------|---------|
| `BrokerSyncService` | 30s | Reconciles DB trades with live broker positions |
| `UnfilledOrderChaser` | 0.5s poll | Replaces stale pending orders with better prices |
| `BrokerHealthMonitor` | Warmup + continuous | Tracks connection status for 17 broker variants |
| `ConditionalOrderService` | 250ms (streaming) | Monitors price levels for conditional order triggers |
| `DailyPnLLimitService` | Per-trade | Checks realized+unrealized against daily limits |

---

## Peripheral Systems

### Diagnostics (`src/diagnostics/`)

12 health checks across 9 categories: database connection/schema, risk settings sync, broker connectivity (Webull/Alpaca/IBKR), Discord token, options chain availability, license status, version updates.

### AI Analyzer (`src/ai_analyzer.py`)

- **TradeAnalyzer**: Post-trade technical analysis via OpenAI/Claude/Gemini (Greeks, probability, risk/reward)
- **SentimentAnalyzer**: Buffers Discord messages (max 100), analyzes when ≥10 accumulated — extracts discussed stocks, market pulse, contrarian signals

### Upgrade System (`upgrade/`)

Full auto-update pipeline: version checker (GitHub Releases API) → readiness checks (disk space, no active trades, DB integrity) → backup (JSON snapshots) → download → checksum verify → apply → post-upgrade validation. Version: 12.1.9.

### License System (3-tier)

1. **Local HMAC**: `license/client/manager.py` — base64(JSON) + HMAC-SHA256 signature, offline-only
2. **RSA Client-Server**: `license/client/client.py` — RSA-signed tokens with offline grace period
3. **FastAPI Server**: `license_server/main.py` — PostgreSQL backend, JWT tokens, trial/activate/validate/deactivate

### Agent Studio (`agent_studio/`)

6-agent AI development pipeline: Orchestrator → Architect → [Approval Gate] → Developer ↔ Tester ↔ Reviewer → DevOps. Features: git branch management, rollback, SemVer auto-bump, cost tracking. Includes VSCode extension (.vsix).

### QA System (`qa/`)

YAML registry-driven validation: 6 registry files define expected features/schema/routes/workflows/dependencies. `QAValidator` checks DB schema compliance. `MigrationManager` provides versioned up/down migrations.

### PySide6 UI (`ui/`)

10-page setup wizard: welcome → app mode → Discord → broker selection → credentials → channels → risk management → notifications → privacy → review. PyQt5 fallback with console-mode last resort.

---

## Build & Deployment

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Core | Python 3.11, asyncio |
| Discord | discord.py-self (selfbot) |
| Telegram | Telethon |
| Web GUI | Flask 3.0 (daemon thread on :5000) |
| Desktop | PySide6 (system tray + splash screen) |
| Database | SQLite (WAL mode) |
| HTTP | httpx (async), requests |
| Streaming | WebSocket (Schwab), MQTT (Webull), ib_insync (IBKR), DXLink (Tastytrade) |
| AI | Anthropic, OpenAI, Google GenAI |
| Build | PyInstaller + PyArmor (obfuscation) |
| CI/CD | GitHub Actions (2 workflows, 4 platforms) |

### CI/CD Workflows

Two parallel workflows in `.github/workflows/`:

- **`build-user.yml`** — Public release, `BUILD_TYPE='USER'`, restricted features
- **`build-admin.yml`** — Private release, `BUILD_TYPE='ADMIN'`, full access

**4-platform matrix**: Windows, Linux, macOS Intel (macos-15-intel), macOS Silicon (macos-14)

**Pipeline**: Checkout → Python 3.11 → pip install → PyArmor license restore → obfuscate `src/` → copy PyArmor runtime → PyInstaller build → upload artifact (90-day retention)

### Packaging

PyInstaller specs in `packaging/windows|macos|linux/specs/`. Entry point: `src/selfbot_webull.py`. 30+ hidden imports. UPX compression, no console window. macOS: ad-hoc code signing.

---

## Technical Debt

### Critical: God Files

The codebase has several extremely large monolithic files that concentrate too much responsibility:

| File | Lines | Size | Issue |
|------|-------|------|-------|
| `src/selfbot_webull.py` | 23,597 | 1.4MB | Entire bot lifecycle: classes, parsers, config, startup, worker, 30+ regex patterns, ~10K-line `_process_message()` |
| `gui_app/routes.py` | 23,491 | 1.1MB | 250+ endpoints in a single `register_routes()` function, no blueprints |
| `gui_app/database.py` | 15,383 | 618KB | 74 tables in one `init_db()`, all CRUD in one file, inline SQL throughout |
| `src/risk/position_monitor.py` | 10,293 | 573KB | God-object: monitoring loop + 8-broker position fetching + exit execution + bracket management + order chasing |
| `src/services/broker_sync_service.py` | 4,453 | 257KB | 14+ broker sync logic in one class |
| `gui_app/chat_assistant.py` | 4,727 | 201KB | Massive inline knowledge base dict (~50 topics) |
| `src/services/signal_format_registry.py` | 4,763 | 196KB | 157 regex handlers in one file |
| `src/services/simulation.py` | 3,642 | 147KB | Standalone simulation engine mixed into services |
| `src/services/unfilled_order_chaser.py` | 2,271 | 113KB | Entry + exit chasing in one overgrown class |

### Architectural Issues

1. **Duplicated WebullBroker**: A 5K-line `WebullBroker` class lives in `selfbot_webull.py` (L2026–7300) in addition to the one in `src/brokers/webull_broker.py`
2. **Two conditional order systems**: `conditional_order_service.py` (legacy) and `conditional_orders/` (new, market-routed) both coexist
3. **Deprecated code still present**: `discord_notifier.py` replaced by `trade_monitor.py` but not removed
4. **Brittle DB row-index access**: Database results accessed by positional index (`row[23]`, `row[45]`) instead of named columns — a schema change breaks everything
5. **Massive SQL duplication**: Same ~55-column SELECT query copy-pasted 6+ times in `RiskDBAdapter` with slight variations
6. **No formal state machine**: Position lifecycle tracked via boolean flags rather than an explicit state enum
7. **BrokerManager doesn't initialize all brokers**: Only 5 of 12 registered brokers are initialized in `broker_manager.py` — Tastytrade, Robinhood, and India brokers initialized separately in `selfbot_webull.py`
8. **CBOE rounding duplicated**: `_round_to_cboe_increment()` implemented independently in both `schwab_broker.py` and `webull_broker.py`

### Code Quality

- **Print-based logging**: `smart_print()` replaces `builtins.print` with DB-logging — no structured logging framework
- **Heavy global mutable state**: 30+ global variables in `selfbot_webull.py` (credentials, flags, config, module availability booleans)
- **No request validation**: Manual `request.json` parsing everywhere in routes.py, no schema validation framework
- **Enormous HTML templates**: `settings.html` (298KB), `trades.html` (229KB) with inline JavaScript — no build pipeline
- **Lazy imports everywhere**: `from gui_app.database import ...` scattered inside method bodies, creating tight coupling between services and GUI layers
- **EMA engine couples to broker internals**: `_try_broker_candles` hardcodes accessor chains like `webull_hub._broker._wb.get_bars()`

### Missing Infrastructure

- No structured logging (log levels, JSON output, log aggregation)
- No database migration framework for the main app (only QA has one)
- No API documentation (OpenAPI/Swagger)
- No request/response schema validation
- No integration test coverage for most broker flows
- No type checking (mypy) or linting in CI
- E2E test directory exists but is empty

---

## File Size Inventory

### Top 20 Files by Size

| # | File | Size | Lines |
|---|------|------|-------|
| 1 | `src/selfbot_webull.py` | 1.4MB | 23,597 |
| 2 | `gui_app/routes.py` | 1.1MB | 23,491 |
| 3 | `gui_app/database.py` | 618KB | 15,383 |
| 4 | `src/risk/position_monitor.py` | 573KB | 10,293 |
| 5 | `src/services/broker_sync_service.py` | 257KB | 4,453 |
| 6 | `gui_app/chat_assistant.py` | 201KB | 4,727 |
| 7 | `src/services/signal_format_registry.py` | 196KB | 4,763 |
| 8 | `src/brokers/schwab_broker.py` | 183KB | 3,712 |
| 9 | `src/services/conditional_orders/base.py` | 150KB | 3,014 |
| 10 | `src/services/simulation.py` | 147KB | 3,642 |
| 11 | `src/signals/parser.py` | 119KB | 3,339 |
| 12 | `src/services/unfilled_order_chaser.py` | 113KB | 2,271 |
| 13 | `src/brokers/webull_broker.py` | 86KB | 1,833 |
| 14 | `src/services/signal_routing_engine.py` | 75KB | 1,740 |
| 15 | `src/brokers/upstox_broker.py` | 72KB | 1,626 |
| 16 | `src/services/conditional_order_service.py` | 70KB | 1,539 |
| 17 | `src/risk/position_cache.py` | 69KB | 1,353 |
| 18 | `src/brokers/tastytrade_broker.py` | 68KB | 1,473 |
| 19 | `src/services/signal_verification.py` | 65KB | 1,500 |
| 20 | `gui_app/live_snapshot.py` | 58KB | 1,484 |

### Module Totals (approximate)

| Module | Files | Total Size | Total Lines |
|--------|-------|------------|-------------|
| `src/` (core bot) | 1 | 1.4MB | 23,597 |
| `src/risk/` | 11 | 788KB | 15,319 |
| `src/services/` | 54 | 2.85MB | ~45,000 |
| `src/brokers/` | 15 | ~830KB | ~17,000 |
| `src/signals/` | 18 | ~300KB | ~7,500 |
| `src/core/` | 15 | ~120KB | ~3,500 |
| `gui_app/` | 20 | ~2.4MB | ~55,000 |
| **Total** | ~134 | **~8.7MB** | **~167,000** |
