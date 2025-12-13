# BotifyTrades - Discord Trading Bot

## Overview
BotifyTrades is a cross-platform Discord self-bot designed for automated stock and options trading. It offers automated trading across Webull, Alpaca, Interactive Brokers, and Tastytrade, featuring advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The bot monitors Discord for trading signals, executes trades with pre-trade swing analysis, AI-powered post-trade analysis, and interactive commands, all managed via a Flask web control panel. The project aims to provide a robust, automated trading solution, enhancing user control and analytical capabilities in the Discord environment, with a focus on comprehensive automation and analytical tools within a Discord-centric workflow.

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
The bot utilizes a Flask-based web control panel with a dark theme, real-time dashboards, dynamic channel management, live trade monitoring, and a System Health Page. Broker-specific Live Analytics pages offer Webull/Thinkorswim-style dashboards. An integrated AI chat assistant provides smart FAQ and intent-based support. The options trading interface is optimized for performance, enabling strike-targeted lookup and displaying detailed order inputs with Greeks.

### Technical Implementations
Core technologies include `discord.py-self` and `webull`. The system employs a true dual-broker architecture for live and paper trading, with platform-specific credential encryption. A separate thread runs the web GUI, communicating via SQLite. Order execution is managed by an asynchronous, queue-based system. Signal parsing uses regex and supports per-channel user filtering and a "TRADE IDEA" format. Risk management features automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all configurable via the GUI and stored in SQLite. Pre-trade analysis uses technical indicators, and post-execution analysis leverages OpenAI GPT models. Real-time market data is integrated, and interactive Discord commands enable on-demand analysis. The Auto Signal Conversion system executes stock alerts as Alpaca BRACKET ORDERs. Position sizing correctly applies to paper trades. An error monitoring system provides automatic detection, logging, and AI assistant contextual help. Licensing involves server-side validation with machine binding and an offline grace period.

### Feature Specifications
The system supports a dual-mode channel system for simultaneous execution and tracking with FIFO-based P&L tracking, and Multi-Broker Execution for trades across multiple accounts with per-channel broker selection. It handles market orders, comprehensive PNL page filtering, and per-channel position sizing. A Portfolio Simulation Engine projects portfolio growth. Authentication includes a setup wizard, secure login, password recovery, and a waitlist/referral system. The dashboard features live price refresh from Webull. Per-channel risk settings allow independent operation, supporting 3-tier profit targets with partial exits and trailing stops. A mandatory user agreement/risk disclosure is stored persistently.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, and Interactive Brokers. The system emphasizes user experience through an interactive setup wizard, GUI-based credential management, automatic license renewal, and extensive documentation. Deployment options include Windows, Linux (with systemd), and AWS EC2. The Discord bot runs in a dedicated thread with an isolated asyncio event loop. Broker credentials are loaded hierarchically. Discord channel IDs and all bot settings, including signal regex patterns and allowed author/guild IDs, are GUI-manageable and stored in SQLite. Per-channel risk management can override global defaults. The `/packaging/` directory consolidates platform-specific build scripts. The `/license/` module handles licensing, supporting legacy, machine-bound, and activation-based licenses with a dedicated GUI. The BrokerSyncService handles case-insensitive broker name matching. Options data retrieval prioritizes Webull for live prices. A unified position key format (`{BROKER}_{SYMBOL}_{STRIKE}_{EXPIRY}_{C/P}`) is used across the system. The system employs a dual-build license architecture separating Admin and User deployments for license management and bot operation.

## Recent Changes

### v3.2.1 - Waxui Alert Format Support (2025-12-13)
- **NEW: Waxui LOTTO entry format** - Parses "SPX here 12/05 6880C Avg. 4.00" and ".35" price formats
- **NEW: Waxui trim signals** - "Trim SPX here" triggers partial exit (HALF)
- **NEW: Waxui close signals** - "Closed SPX here" or "Close SPX here" triggers full exit (ALL)
- **AUTO-QTY: Waxui entries** - Auto-calculates quantity based on max_position_size settings
- **PATTERNS: src/selfbot_webull.py** - Added WAXUI_ENTRY_REGEX, WAXUI_TRIM_REGEX, WAXUI_CLOSE_REGEX
- **EXIT TYPES** - Trim sets _exit_type="HALF", Close sets _exit_type="ALL" for position lookup

### v3.2.0 - Tastytrade Broker Integration (2025-12-12)
- **NEW: Tastytrade broker support** - Full integration with Tastytrade API for stocks and options trading
- **NEW: TastytradeBroker class** - Implements BrokerInterface at `src/brokers/tastytrade_broker.py`
- **NEW: Tastytrade credentials UI** - Settings page has paper and live credential sections
- **NEW: Multi-broker execution** - Tastytrade available in per-channel broker selection
- **NEW: BrokerSyncService integration** - Tastytrade positions sync to database
- **NEW: Risk management routing** - Exit orders route correctly to Tastytrade

### v3.1.7 - GUI Region Metadata Preservation Fix (2025-12-12)
- **ROOT CAUSE FIX: GUI "rzone" error** - GUI save credentials now preserves zone_var, rzone, region_id metadata
- **FIX: Consistency between bot and GUI** - Main bot worked because it had monkey-patch, GUI was losing region data
- **FIX: Clear-tokens preserves region** - Clearing tokens no longer loses region metadata
- **CLARIFIED: Replit vs Local difference** - Both now use same region handling pattern

### v3.1.6 - Web Token Detection & GUI-Bot Token Consistency (2025-12-12)
- **FIX: Web token detection** - GUI now rejects `dc_us_tech` web tokens that can't access trading API
- **FIX: Token validation in save** - GUI Settings validates tokens before saving to database
- **FIX: webull_auth.py** - Detects web tokens early and gives clear guidance to use email/password login
- **IMPROVED: Error messages** - Explains difference between web tokens (browser) and mobile tokens (trading API)
- **CLARIFIED: Token types** - Web tokens from app.webull.com cannot trade, only mobile tokens work

### v3.1.5 - Webull Library Monkey-Patch for Missing rzone (2025-12-12)
- **ROOT CAUSE FIX: Webull library get_account_id() crash** - Library expects 'rzone' in API response but Webull removed it
- **FIX: Monkey-patch webull.get_account_id()** - Uses .get() with fallback instead of direct key access
- **FIX: Applied to both webull and paper_webull classes** - Patch runs at module load time
- **FIX: Main bot imports webull_auth early** - Ensures patch is applied before any webull usage
- **IMPROVED: Token expiration messages** - Now clearly tells users to get fresh tokens with instructions

### v3.1.4 - Webull API v2 Region Metadata Fix (2025-12-12)
- **ROOT CAUSE FIX: KeyError 'rzone'** - Webull API changed in Nov 2025 to require region metadata (rzone, region_id, zone_id)
- **FIX: Credential storage extended** - Now persists and restores region metadata alongside tokens
- **FIX: Both GUI and bot auth paths** - Applied consistent region handling to webull_auth.py AND selfbot_webull.py
- **FIX: _apply_tokens updated** - Main bot now supports region_data parameter for session restoration
- **FIX: Session save includes region** - _save_session extracts and persists rzone from webull client session
- **IMPROVED: Defensive restoration** - Warns when region metadata is missing instead of crashing

### v3.1.3 - Webull Auth Schema Drift Fix & CI/CD Pipeline (2025-12-12)
- **FIX: KeyError 'rzone' handling** - Added specific KeyError catch for Webull API schema changes
- **FIX: Stale token detection** - Tokens now marked stale with friendly message when API schema drifts
- **NEW: GitHub Actions CI/CD** - Automated PyArmor-protected builds for Windows/Linux
- **NEW: PowerShell build syntax** - Windows builds now use native PowerShell instead of CMD
- **IMPROVED: Error messages** - Stale tokens prompt user to re-enter instead of cryptic KeyError

### v2.1.35 - Webull Auth Error Handling Fix (2025-12-11)
- **CRITICAL FIX: `_try_saved_session` return type bug** - Fixed boolean check on dict return (always truthy)
- **FIX: Specific error messages** - Token verification now returns actual error reason, not generic message
- **FIX: JSON/CAPTCHA error handling** - Routes.py now catches CAPTCHA-blocked errors with friendly message
- **IMPROVED: Error messages include actionable guidance** - Users see exactly what to do to fix issues
- Error scenarios: No credentials, no token, verification failed, API blocked, session restore error

### v2.1.34 - Position Sync & Stale Trade Cleanup (2025-12-11)
- **NEW: Sync Positions Button** - Dashboard and Performance pages now have a "Sync Positions" button
- **NEW: `/api/sync-positions` endpoint** - Compares database trades with actual broker positions
- **NEW: `sync_positions_with_broker()` function** - Marks expired/closed positions as CLOSED in database
- **FIX: Stale positions detection** - Expired options (like ONDS 12/05) now properly detected and closeable
- **DEBUG: Enhanced sync logging** - `[SYNC-API]` logs show exactly what positions are being synced
- Sync works for Webull, ALPACA_PAPER, and ALPACA_LIVE brokers
- Position key matching: Symbol-only for stocks, SYMBOL_STRIKE_EXPIRY_C/P for options

### v2.1.31 - Bot Trades Tab & All-Broker Performance (2025-12-11)
- **NEW: Isolated Bot Trades Tab** - Shows ONLY Discord signal-executed trades with channel attribution
- **NEW: All-Broker Performance Page** - Shows ALL positions from ALL configured brokers (not channel-filtered)
- Bot Trades: LEFT JOIN fix for deleted channels, corrected column names (direction, executed_price)
- Performance: New `/api/broker-performance` endpoint returns metrics from trades table directly
- Database: `get_all_broker_performance()` and `get_all_broker_trades()` functions with user_id filtering
- Multi-tenant safety: Backwards compatible user_id filtering (shows historical trades + current user's trades)
- Filters: Channel Name, Symbol, Status, Broker dropdowns on both pages

## Critical Implementation Patterns (DO NOT BREAK)

### Options Page (gui_app/templates/options.html)
- **Expiration Data**: Uses Alpaca's `OptionChainRequest` (market data API) - NOT the TradingClient paper API which has limited data
- **Cache Variable**: `expiryCache` must be declared as `let` (not `const`) because it's reassigned when broker changes
- **Credential Loading**: AlpacaDataProvider loads credentials from database via `get_alpaca_settings()` function, matching the main bot pattern
- **Async Threading**: Flask routes use `asyncio.run()` to execute async provider methods in the synchronous Flask context

### AlpacaDataProvider (src/data_providers/alpaca_data_provider.py)
- **Market Data Client**: Uses `OptionHistoricalDataClient` for complete options data (not paper-limited)
- **Expiration Parsing**: Extracts dates from OCC symbol format (e.g., SPY241220C00600000 → 2024-12-20)
- **Database Credentials**: Must use `get_alpaca_settings()` from gui_app.database for credential loading

### Position Key Format
- Unified format: `{BROKER}_{SYMBOL}_{STRIKE}_{EXPIRY}_{C/P}`
- Expiry dates normalized to YYYY-MM-DD to prevent duplicate trades

### BrokerSyncService
- Inherits `channel_id` from signal for both Webull and Alpaca live trading
- Uses case-insensitive broker name matching

## External Dependencies

- **Python**: 3.8+
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
- **ALPHA_VANTAGE_API_KEY**: Market data
- **FINNHUB_API_KEY**: Market data
- **OPENAI_API_KEY**: AI analysis
- **ALPACA_API_KEY**: Alpaca brokerage
- **ALPACA_SECRET_KEY**: Alpaca brokerage
- **GMAIL_APP_PASSWORD**: For Gmail SMTP
- **SMTP_PASSWORD**: For custom SMTP