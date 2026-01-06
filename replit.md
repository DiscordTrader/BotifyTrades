# BotifyTrades - Multi-Platform Trading Bot

## Overview
BotifyTrades is a cross-platform trading automation bot for Discord and Telegram, designed for automated stock and options trading across multiple brokers in the USA, Canada, and India. It offers automated execution, advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The bot monitors messaging platforms for trading signals, executes trades with pre-trade swing analysis, AI-powered post-trade analysis, and interactive commands, all managed via a Flask web control panel. The project aims to provide a robust, automated trading solution, enhancing user control and analytical capabilities within a messaging-centric workflow, with a focus on comprehensive automation and analytical tools.

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
The bot features a Flask-based web control panel with a dark theme, real-time dashboards, dynamic channel management, live trade monitoring, and a System Health Page. Broker-specific Live Analytics pages emulate Webull/Thinkorswim-style dashboards. An integrated AI chat assistant provides smart FAQ and intent-based support. The options trading interface is optimized for performance, enabling strike-targeted lookup and displaying detailed order inputs with Greeks. A PySide6-based setup wizard guides first-time users through configuration. Professional desktop application behavior is provided via a PySide6 splash screen and system tray integration (Windows/macOS/Linux).

### Technical Implementations
Core technologies include `discord.py-self` and `webull`. It employs a true dual-broker architecture for live and paper trading, with platform-specific credential encryption. Order execution uses an asynchronous, queue-based system. Signal parsing follows a multi-layer approach: learned formats from a database (AI-taught), built-in regex patterns, and AI fallback, supporting various formats including Indian market signals, DTE notation, Bishop format, Discord Embed extraction, and EvaPanda format. Risk management includes automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all GUI-configurable and stored in SQLite. Pre-trade analysis uses technical indicators, and post-execution analysis leverages OpenAI GPT models. Real-time market data is integrated, and interactive Discord commands enable on-demand analysis. The Auto Signal Conversion system executes stock alerts as Alpaca BRACKET ORDERs. An error monitoring system provides automatic detection, logging, and AI assistant contextual help. A "teach once, use forever" feature allows users to teach new signal formats via a chatbot.

The **Signal Verification Service** detects paper trading and impossible fills using real-time broker data (Webull, Tastytrade, Alpaca) prioritized over delayed sources (yfinance), historical quote capture, time-window tolerance (±30 seconds), and confidence scoring.

### Feature Specifications
The system supports a dual-mode channel system for simultaneous execution and signal forwarding, FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection. It handles market orders, comprehensive PNL page filtering, and per-channel position sizing. Per-channel risk settings allow independent operation, supporting 4-tier profit targets with customizable trim quantities, Market/Limit trim order modes, trailing stops, and **Leave Runner functionality**. **Exit Strategy Mode** allows configuration per channel to follow trader signals (`signal`), automated risk management (`risk`), or both (`hybrid`). **Position Matching for Ambiguous Exit Signals** automatically links exit signals to the most recent open position from that channel. The Trade Monitor feature automatically detects and posts broker-executed trades as BTO/STC signals to Discord. A debug report system allows users to submit filtered error logs.

The **Portfolio Simulation Engine** projects portfolio growth using various position sizing modes (`fixed`, `percent_start`, `percent_current`), trade validation, a daily realism model, and dollar-cost slippage. The **Copy Trader 1:1 Performance Report** evaluates a trader's actual performance using original trade sizes, calculating capital requirements and performance metrics (return %, win rate, drawdown). The **Risk Optimizer** finds optimal position sizing for a custom portfolio using the enhanced simulation engine, testing various percent and fixed-dollar amounts, employing an industry-grade scoring formula, and providing detailed comparison tables and rationale.

**Dual-Action Channel Mappings** support simultaneous execution and signal forwarding via `execute_on_source` and `forward_enabled` flags, with flexible destination types (`webhook` or `channel`).

**Telegram Integration** supports reading trading signals from Telegram groups/channels using a Telethon user client, featuring a cross-thread architecture, unified signal processing with Discord, GUI management, and channel-aware routing for independent risk settings and broker selection.

**Market-Specific Channel Pages** provide dedicated management for regional markets: India Markets (NSE/BSE/MCX with DhanQ, Upstox, Zerodha), and Canada Markets (TSX/CSE/NEO with Questrade).

**Conditional Order Monitoring System** monitors price conditions and executes orders when triggered, supporting signals with "over/above" and "under/below" triggers, SL/PT, and position sizing. It uses a three-tier price monitoring fallback (broker-native APIs → Finnhub API → yfinance). Indian market conditional orders are supported via Upstox/Zerodha APIs or yfinance.

**Expiry Resolver Service** (`src/services/expiry_resolver.py`) automatically picks the next valid expiry for Indian F&O signals when not specified:
- Fetches instrument masters from broker APIs (Upstox V2 option contracts, Zerodha instrument master)
- TTL-based caching (12 hours default) to minimize API calls
- Supports multiple date formats: MM/DD, YYYY-MM-DD, DD-MMM-YY, DDMMMYY, month codes (JAN, FEB)
- Symbol alias normalization: NIFTY50 → NIFTY, BANK NIFTY → BANKNIFTY
- Resolves both OPTIONS (strike + option type) and FUTURES (month code)
- Falls back to hardcoded expiry calculation if broker API unavailable
- NSE weekly expiry: **Tuesday** (effective September 2025) for NIFTY only
- Monthly expiry: Last Tuesday for BANKNIFTY, FINNIFTY, MIDCPNIFTY, stock F&O

**Signal Tracking System** provides comprehensive lifecycle tracking for all signals from detection through broker execution with full audit trails. Features include:
- Full signal lifecycle states: DETECTED → VALIDATED → SUBMITTED → EXECUTED/REJECTED/FAILED
- Immutable audit trail via `signal_event_transitions` table recording every state change
- Filtering by symbol, channel, author, broker, platform (Discord/Telegram), and market region
- Market codes: 'US' (USA), 'IN' (India), 'CA' (Canada) - stored in database market column
- Market-specific signal history pages: `/signals`, `/signals/us`, `/signals/india`, `/signals/canada`
- API endpoints: `/api/signals/history` (filtered), `/api/signals/<id>` (detail with transitions), `/api/signals/statistics`, `/api/signals/export` (CSV)
- P&L tracking per signal with realized P&L and percentage tracking
- Broker response and error logging for debugging failed trades
- India signal parsing: `parse_india_option_signal()`, `parse_india_stock_signal()` with NSE/BSE formats
- US signal parsing: Standard BTO/STC format with regex patterns

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, Robinhood, Charles Schwab, Questrade, Upstox, Zerodha, and DhanQ.

**Upstox Integration** provides V3 HFT API trading for Indian markets (NSE/BSE) with auto-slicing, 24-hour token management, an API blackout window, and a pending order queue with GUI management for AMO orders.

**Charles Schwab Integration** provides OAuth2-authenticated trading, managing token refresh and supporting Schwab's OCC Options Format.

The system emphasizes user experience through an interactive setup wizard, GUI-based credential management, and automatic license renewal. The Discord bot runs in a dedicated thread with an isolated asyncio event loop. Broker credentials are loaded hierarchically. Discord channel IDs and all bot settings, including signal regex patterns and allowed author/guild IDs, are GUI-manageable and stored in SQLite. Per-channel risk management can override global defaults. The system employs a dual-build license architecture separating Admin and User deployments.

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

## Milestones

### INDIA 1 - Conditional Order Monitoring for India Markets (January 6, 2026)
**Status: ✅ COMPLETE**

Implemented automatic conditional order monitoring and execution for India market options via Upstox broker integration.

**Features Delivered:**
- Real-time price monitoring via Upstox V3 LTP API for Indian F&O instruments
- ABOVE/BELOW trigger detection with automatic execution when market conditions are met
- Telegram signal parsing for Indian options with conditional triggers (e.g., "BUY NIFTY 26100 CE ABOVE ₹160")
- Full execution pipeline: Signal → Conditional Order → Price Monitor → Trigger → Upstox Order
- Support for stop loss and multi-target profit taking from signals
- Proper status tracking: ACTIVE_MONITORING → TRIGGERED → EXECUTING → EXECUTED
- IndiaPriceMonitor class with broker-native LTP polling (~1 second intervals)
- Automatic expiry resolution for NIFTY/BANKNIFTY weekly options

**Key Files:**
- `src/services/conditional_order_service.py` - Core monitoring service with IndiaPriceMonitor
- `src/selfbot_webull.py` - Execution callback and signal queue integration
- `src/brokers/upstox_broker.py` - V3 LTP API and order placement
- `gui_app/database.py` - Conditional order storage and status updates

**Fixes Applied:**
- Resolved logging visibility (stdout→stderr for workflow logs)
- Fixed profit targets parsing for both JSON arrays and comma-separated strings
- Corrected status update from TRACKING to EXECUTED on success

## Architecture Review (January 6, 2026)

### Database Architecture
- **Primary Database**: `bot_data.db` (single source of truth)
- **License Database**: `license_server.db` (license validation)
- All modules correctly reference `bot_data.db` via `gui_app/database.py`

### Cross-Market Support Status

| Feature | US Markets | India Markets | Canada Markets |
|---------|-----------|---------------|----------------|
| Signal Parsing | ✅ BTO/STC regex | ✅ NSE/BSE F&O | ⚠️ Basic only |
| Conditional Orders | ⚠️ Finnhub/yfinance | ✅ Upstox V3 LTP | ⚠️ Finnhub/yfinance |
| Broker Integration | ✅ Webull, Alpaca | ✅ Upstox, Zerodha, DhanQ | ✅ Questrade |
| Expiry Resolution | N/A | ✅ Auto-resolve | N/A |

### Per-Channel Settings (Discord & Telegram)
- ✅ Position sizing (`position_size_pct`)
- ✅ Per-channel risk settings (profit targets, stop loss, trailing stops)
- ✅ Broker override per channel (`broker_override`, `enabled_brokers`)
- ✅ Exit strategy mode per channel
- ✅ Conditional order settings per channel
- ✅ Market assignment per channel (US/IN/CA)
- ✅ Unified channel table supports both `discord_channel_id` and `telegram_chat_id`

### Known Gaps (Future Work)
1. **US/Canada Conditional Orders**: Currently use fallback price monitors (Finnhub/yfinance) rather than broker-native APIs
2. **Canada Signal Parsing**: No dedicated `parse_canada_*` functions - uses US patterns
3. **BrokerPriceMonitor**: Implemented but not integrated for Webull/Alpaca conditional orders

### Security
- ✅ Admin password no longer has hardcoded default (requires env var or setup wizard)
- ✅ Rate limiting on login attempts
- ✅ Session-based authentication with user database