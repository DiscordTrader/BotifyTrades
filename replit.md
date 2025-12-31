# BotifyTrades - Discord Trading Bot

## Overview
BotifyTrades is a cross-platform Discord self-bot designed for automated stock and options trading across multiple brokers in the USA, Canada, and India. It offers automated trading, advanced analytics, a dual-broker architecture for paper and live trading, and comprehensive risk management. The bot monitors Discord for trading signals, executes trades with pre-trade swing analysis, AI-powered post-trade analysis, and interactive commands, all managed via a Flask web control panel. The project aims to provide a robust, automated trading solution, enhancing user control and analytical capabilities within a Discord-centric workflow, with a focus on comprehensive automation and analytical tools.

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
The bot features a Flask-based web control panel with a dark theme, real-time dashboards, dynamic channel management, live trade monitoring, and a System Health Page. Broker-specific Live Analytics pages emulate Webull/Thinkorswim-style dashboards. An integrated AI chat assistant provides smart FAQ and intent-based support. The options trading interface is optimized for performance, enabling strike-targeted lookup and displaying detailed order inputs with Greeks. A PySide6-based setup wizard guides first-time users through configuration.

### Technical Implementations
Core technologies include `discord.py-self` and `webull`. It employs a true dual-broker architecture for live and paper trading, with platform-specific credential encryption. Order execution uses an asynchronous, queue-based system. Signal parsing follows a multi-layer approach: learned formats from a database (AI-taught), built-in regex patterns (supporting both US and India formats), and AI fallback. **Indian Signal Format Support**: The system now recognizes Indian market signals like "BUY NIFTY 24000 CE @ 145" with CE/PE option types, DD MMM expiry formats, automatic NSE lot size calculation, and weekly/monthly expiry detection for NIFTY/BANKNIFTY. **DTE Format Support**: Recognizes "0DTE", "1DTE", "2DTE" etc. notation (e.g., "BTO $QQQ 621c 0DTE @0.74") and automatically converts to the correct expiry date. **Bishop Format Support**: Recognizes multi-line entry format "I'm Entering" + "Option: SPX 6900 P 12/30" + "Entry: 1.00" as BTO signals, and "Trimming SPX 6900 P 12/30 @$1.30" as STC signals. **Discord Embed Extraction**: The bot now extracts text from Discord embeds (title, description, fields) and combines it with message content for parsing, enabling support for signals posted inside embeds like Bishop's ZTRADEZ channel. **EvaPanda Format Support**: Recognizes embed-based signals with "Open" title for BTO entries and "Close" title for STC exits, parsing format "BTO FSLR 01/16/26 300C @ 3.25 (Swing)" with MM/DD/YY expiry dates. Risk management includes automated profit targets, stop losses, trailing stops, intelligent price slippage protection, and auto-quantity calculation, all GUI-configurable and stored in SQLite. Pre-trade analysis uses technical indicators, and post-execution analysis leverages OpenAI GPT models. Real-time market data is integrated, and interactive Discord commands enable on-demand analysis. The Auto Signal Conversion system executes stock alerts as Alpaca BRACKET ORDERs. An error monitoring system provides automatic detection, logging, and AI assistant contextual help. A "teach once, use forever" feature allows users to teach new signal formats via a chatbot, storing reusable parsing templates.

**Signal Verification Service (Industry-Grade)**: Located in `services/signal_verification.py`, this service detects paper trading and impossible fills through:
- **Real-time broker data priority**: Webull > Tastytrade > Alpaca > yfinance (delayed fallback)
- **Historical quote capture**: `capture_quote_at_signal_time()` stores bid/ask/volume at signal detection for accurate verification
- **Time-window tolerance**: ±30 seconds (TIME_WINDOW_TOLERANCE constant) validates quote freshness
- **Confidence scoring**: +10 for valid historical quotes, -15 for STALE_QUOTE red flag, -5 for delayed data sources
- **Red flags**: IMPOSSIBLE_FILL, STALE_QUOTE, OUTSIDE_SPREAD, SUSPICIOUS_VOLUME, etc.
- Brokers are wired at startup via `set_broker_clients()` for real-time market data access

### Feature Specifications
The system supports a dual-mode channel system for simultaneous execution and tracking with FIFO-based P&L tracking, and Multi-Broker Execution across multiple accounts with per-channel broker selection. It handles market orders, comprehensive PNL page filtering, and per-channel position sizing. Per-channel risk settings allow independent operation, supporting 3-tier profit targets with partial exits, trailing stops, and **Leave Runner functionality** (keep a configurable % of position after hitting profit targets to capture additional gains). The Trade Monitor feature automatically detects and posts broker-executed trades as BTO/STC signals to Discord. A debug report system allows users to submit filtered error logs to the admin.

**Per-Channel Risk Management Fields (Enhanced 4-Tier System)**: Each channel can independently configure:
- Profit Targets 1/2/3/4 (P1/P2/P3/P4) - up to 500% each with suggested defaults of 10%, 20%, 30%, 40%
- **Custom Trim Quantities**: Specify exact contracts to trim at each tier (e.g., 2, 2, 3, 2). Leave empty for auto-calculation with equal split.
- **Trim Order Mode**: Choose between Market (immediate fill) or Limit orders (psychological pricing at .04/.09 levels)
- **Limit Order Offset**: Configurable offset for limit orders (default $0.01)
- Stop Loss % - maximum 100%
- Trailing Stop % with Activation %
- Leave Runner - toggle enabled/disabled with configurable percentage (default 25%)
- All settings stored in SQLite `channels` table with columns: `profit_target_4_pct`, `profit_target_qty_1-4`, `trim_order_mode`, `trim_limit_offset`

**Portfolio Simulation Engine (Enhanced)**: Located in `services/simulation.py::run_exact_historical_simulation()`. Projects YOUR portfolio growth using YOUR position sizing with industry-standard realism. Key features:
- **Position sizing modes**: `fixed` ($ per trade), `percent_start` (flat % of starting portfolio), `percent_current` (compounding % of current balance)
- **Trade validation**: Long options + stocks only with categorized skip reasons (unsupported_type, cannot_afford, below_minimum, daily_capacity, daily_trade_limit, missing_data)
- **Daily realism model**: `daily_alloc_pct` (default 60%), `daily_recycle_turns` (default 2x), `max_trades_per_day` (hard limit 25)
- **Daily capacity formula**: `balance * daily_alloc_pct * daily_recycle_turns`
- **Dollar-cost slippage model**: Position-based scaling with base + size factor
- **Comprehensive skip tracking**: Every skipped trade recorded with reason and statistics
- **Daily stats**: Trading days, avg trades/day, max trades in a day
- **API endpoint**: `/api/simulate/historical`
- **Backward compatibility**: `percent` maps to `percent_start`

**Copy Trader 1:1 Performance Report**: A portfolio-INDEPENDENT analysis tool that evaluates a trader's actual performance using their original trade sizes. Located in `services/simulation.py::run_copy_1to1_report()`. Key features:
- Uses original trade quantities from database (NOT user's portfolio)
- Calculates capital requirements: `recommended_portfolio = peak_single_trade_outlay / risk_cap`
- Performance metrics: return %, win rate, profit factor, expectancy, max drawdown, worst trade, max consecutive losses
- Filters for long options only (skips stocks with "Unsupported" reason)
- Optional slippage model: 0.5% base + size factor (capped at 3%)
- Risk cap selector: 10% (Conservative) or 25% (Moderate)
- API endpoint: `/api/simulate/copy1to1`

**Risk Optimizer (Industry-Grade)**: Located in `services/simulation.py::run_risk_optimizer()`. Finds optimal position sizing for a custom portfolio using the enhanced simulation engine. Key features:
- **Candidate generation**: Tests 10 percent values (1-25%) AND 5 fixed-$ amounts (1-10% of portfolio)
- **Sizing basis selector**: `percent_start` (flat bet - safer) or `percent_current` (compounding)
- **Industry-grade scoring formula**: `(growth / drawdown) × (0.6 + 0.4 × coverage) × (1 / (1 + tail_penalty)) × stability`
- **Guardrails**: Coverage ≥50%, Drawdown ≤60%, Balance >0 (disqualifies otherwise)
- **Fallback mode**: When no candidate meets guardrails, selects highest coverage with warning
- **Comprehensive comparison table**: Mode, risk value, executed/skipped trades, coverage %, profit factor, score
- **Skip breakdown**: Affordability vs daily capacity reasons shown per candidate
- **Rationale bullets**: Why this sizing, trade-offs, and notes with daily capacity info
- **Daily realism params**: `daily_alloc_pct`, `daily_recycle_turns`, `max_trades_per_day`
- **Slippage toggle**: ON by default (0.5% base + size factor)
- **API endpoint**: `/api/simulate/optimizer`

**Dual-Action Channel Mappings (Admin Build)**: Channel mappings now support simultaneous execution AND signal forwarding via `execute_on_source` and `forward_enabled` flags. **Flexible Destination Types**: Mappings support two destination types: `webhook` (Discord webhook URL) or `channel` (Discord channel ID). When forwarding to a channel, the bot sends the signal directly to the destination channel using the Discord client. The `format_as_bto_stc` flag ensures signals are forwarded in BTO/STC format only. All mapping features are admin-only via `@admin_feature_required` decorator.

### System Design Choices
The architecture is modular, structured into `src/` and `gui_app/` directories. Configuration uses database-stored encrypted credentials, with `config.ini` as a fallback. It features robust error handling, logging, and a multi-broker abstraction for Webull, Alpaca, Interactive Brokers, Tastytrade, Robinhood, Questrade, Upstox, Zerodha, and DhanQ (DhanHQ v2 API). The system emphasizes user experience through an interactive setup wizard, GUI-based credential management, and automatic license renewal. The Discord bot runs in a dedicated thread with an isolated asyncio event loop. Broker credentials are loaded hierarchically. Discord channel IDs and all bot settings, including signal regex patterns and allowed author/guild IDs, are GUI-manageable and stored in SQLite. Per-channel risk management can override global defaults. The system employs a dual-build license architecture separating Admin and User deployments.

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
- **robin-stocks**: Robinhood brokerage integration (unofficial)
- **pyotp**: TOTP 2FA code generation
- **ALPHA_VANTAGE_API_KEY**: Market data
- **FINNHUB_API_KEY**: Market data
- **GMAIL_APP_PASSWORD**: For Gmail SMTP
- **SMTP_PASSWORD**: For custom SMTP