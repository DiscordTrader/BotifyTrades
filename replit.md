# BotifyTrades - Multi-Platform Trading Bot

## Overview
BotifyTrades is a cross-platform trading automation bot for Discord and Telegram, designed for automated stock and options trading across multiple brokers in the USA, Canada, and India. Its core purpose is to provide automated execution, advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The project aims to make sophisticated trading accessible and efficient by integrating advanced trading functionalities within messaging platforms.

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

The Signal Verification Service detects paper trading and impossible fills using real-time broker data and confidence scoring across multiple data sources. Async broker integrations use thread-safe bridge patterns. The system supports a dual-mode channel system for simultaneous execution and signal forwarding, FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection. Per-channel risk settings allow independent operation, supporting 4-tier profit targets, trailing stops, and Leave Runner functionality. Exit Strategy Mode allows configuration per channel to follow trader signals, automated risk management, or both. Position Matching for Ambiguous Exit Signals automatically links exit signals to the most recent open position. The Trade Monitor feature automatically detects and posts broker-executed trades as BTO/STC signals to Discord.

The Enhanced Portfolio Simulation Engine v2.0 provides industry-grade portfolio analysis with Monte Carlo Simulation, Theta Decay Modeling, Correlation/Concentration Risk Analysis, Risk Scenario Presets, and Comprehensive Portfolio Projection. Telegram Integration supports reading trading signals from Telegram groups/channels. Market-Specific Channel Pages provide dedicated management for India Markets (NSE/BSE/MCX with DhanQ, Upstox, Zerodha) and Canada Markets (TSX/CSE/NEO with Questrade). The Conditional Order Monitoring System monitors price conditions and executes orders when triggered, supporting signals with "over/above" and "under/below" triggers, SL/PT, and position sizing. The Expiry Resolver Service automatically picks the next valid expiry for Indian F&O signals when not specified.

Filled Orders Tracking syncs filled orders from broker APIs into a local database table with automatic sync and deduplication. Execution-Based P&L Tracking provides professional-grade P&L calculation based on actual broker fills, including slippage tracking, latency metrics, and race condition protection. A Two-Tier P&L Architecture provides separation between theoretical signal performance (Signal P&L) and actual broker execution results (Execution P&L).

The Bot Lifecycle Manager provides centralized control for bot stop/restart operations via system tray and web GUI, including REST API endpoints and graceful shutdown signaling. The Signal Tracking System provides comprehensive lifecycle tracking for all signals from detection through broker execution with full audit trails. The QA Workflow Validation System ensures the complete signal-to-execution pipeline remains intact.

The Order Management System (OMS) and Risk Management System (RMS) provide dynamic SL/PT management for signals that update via Discord message edits, with a WaxUI Entry Registry linking update signals to original entries. The Exit Order Arbiter arbitrates between signal-driven and risk-driven exit requests, enforcing that stop loss can never be lowered in hybrid mode. The Signal Exit Manager handles the complete order lifecycle with broker-aware modify flows. A Circuit Breaker provides emergency trading halt controls with global/per-channel halt, daily loss limit enforcement, and position count limits. Exit Strategy Modes include Signal Mode, Risk Mode, and Hybrid Mode. Trailing stop state (activation status, highest price watermark) now persists to the database across bot restarts for robust position management.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, Robinhood, Charles Schwab, Questrade, Upstox, Zerodha, and DhanQ. The License Validation System provides industry-standard license activation integrated into the startup splash screen. The Discord bot runs in a dedicated thread. Broker credentials and all bot settings are GUI-manageable and stored in SQLite. Security features include admin password management, rate limiting on login attempts, session-based authentication, and local password recovery.

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

## Future Implementation: Service Orchestrator

### Overview
Industry-grade Service Orchestrator for priority-based background service management with dynamic activation, API budget allocation, and broker-specific rate limiting.

### Verified Broker API Rate Limits

| Broker | Market Data | Orders | Critical Notes |
|--------|-------------|--------|----------------|
| **Webull** | ~1 req/s, 60/min safe | 15/min actions | Unofficial API, bursty bans |
| **Alpaca** | 200/min, 1/s burst | 200/min, 10 orders/s | Has streaming WebSocket |
| **Robinhood** | 120/10min shared | ~1/s order limit | 429 triggers 15min lockout |
| **IBKR** | 50 msg/s | 60 historical/min | Pacing violations lock channel |
| **Tastytrade** | 120/min | Shared limit | Has streaming WebSocket |
| **Schwab** | 120/min | 20 orders/min | 10k/day rolling limit |
| **Questrade** | 20/s, 100k/day | Shared | Canadian broker |
| **Upstox** | 40/s, 3000/min | 60 orders/min | Indian broker |
| **Zerodha** | 3/s | 60 orders/min hard cap | Indian broker |
| **DhanQ** | 30/s, 1000/min | Shared | Indian broker |

### Service Priority & Dynamic Intervals

| Service | Priority | Market Hours | After Hours | Activation Condition |
|---------|----------|-------------|-------------|---------------------|
| **Order Execution** | Critical | Immediate | Immediate | Always ready |
| **Risk Manager** | High | 3-5s | 10s | Any channel has risk enabled |
| **Conditional Orders** | High | 4s | 12s | Pending orders exist |
| **Position Sync** | Medium | 6s | 18s | Open positions exist |
| **Options Chain** | Low | 30s cache | 60s | Active options trading |
| **Balance Fetch** | Background | 90s | 180s | Always (low priority) |

### Dynamic Activation Logic
```
Every 5s (orchestration tick):
├── Check: risk_enabled on any channel?
│   └── YES → Run RiskManager at 3-5s
│   └── NO  → Pause RiskManager
├── Check: Conditional orders pending?
│   └── YES → Monitor at 4s
│   └── NO  → Suspend monitoring
├── Check: Open positions exist?
│   └── YES → Position sync at 6s
│   └── NO  → Reduce to 30s heartbeat
├── Check: Options activity?
│   └── YES → Warm cache
│   └── NO  → On-demand only
└── Broker disconnected?
    └── Skip + exponential backoff
```

### Database Schema Required
```sql
CREATE TABLE service_registry (
    service_id TEXT PRIMARY KEY,
    display_name TEXT,
    broker_scope TEXT,  -- 'all', 'webull', 'alpaca', etc.
    default_interval INTEGER,
    min_interval INTEGER,
    max_interval INTEGER,
    priority INTEGER DEFAULT 5,
    enabled INTEGER DEFAULT 1,
    last_run TIMESTAMP,
    last_result TEXT,
    status TEXT DEFAULT 'idle'  -- running, paused, error, idle
);

CREATE TABLE broker_limits (
    broker_name TEXT PRIMARY KEY,
    data_limit_per_min INTEGER,
    order_limit_per_min INTEGER,
    current_calls INTEGER DEFAULT 0,
    window_start TIMESTAMP,
    last_429_at TIMESTAMP
);

CREATE TABLE service_metrics (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    service_id TEXT,
    calls_made INTEGER,
    latency_ms INTEGER,
    errors INTEGER,
    rate_limit_hits INTEGER
);
```

### Routes Requiring Orchestrator Wiring
- `/api/trades/merged` → Position Sync Service
- `/api/risk/status` → Risk Monitor Service  
- `/api/broker/status` → Broker Sync Service
- `/api/place_order` → Order Execution (priority)
- `/api/cancel_order` → Order Execution (priority)
- `/api/sync_positions` → Position Sync Service
- `/api/conditional_orders/*` → Conditional Orders Service
- `/api/options/chain/*` → Options Chain Service
- `/api/broker/balance/*` → Balance Fetch Service

### UI Enhancement (settings.html Background Services card)
Currently has basic toggles for Broker Sync and Risk Monitor (lines 1297-1327).

**Required Enhancements:**
1. Service list table with Name | Priority | Interval | Status | Last Run | Actions
2. Per-service controls: Toggle, Priority dropdown (1-10), Interval input
3. Per-broker rate limit gauges with 429 error counts
4. Real-time status indicators (Running/Paused/Error/Idle)
5. Manual "Run Now" button per service

### Implementation Checklist
1. Create `service_registry` table + migration
2. Create `broker_limits` table with verified limits
3. Build `ServiceOrchestrator` class with priority queue
4. Create per-broker token bucket throttlers
5. Wire RiskManager to check `risk_monitor_enabled`
6. Wire Conditional Orders to check enable state
7. Add service status tracking (last_run, status)
8. Enhance UI with full service controls
9. Add rate limit gauges to UI
10. Create `/api/services/*` endpoints
11. Add service metrics logging
12. Implement WebSocket for real-time status