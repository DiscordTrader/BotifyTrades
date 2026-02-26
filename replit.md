# BotifyTrades — Compressed Documentation

## Overview

BotifyTrades is a production-grade, cross-platform automated trading bot designed to monitor Discord and Telegram for trade signals and execute them across multiple brokers. It features a comprehensive Flask-based web control panel with real-time dashboards, advanced risk management, WebSocket streaming, AI-powered analysis, and detailed portfolio analytics. The project aims to provide automated trading capabilities for US, Canadian, and Indian markets, offering users a powerful tool for managing and optimizing their trading strategies.

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
- **Real-time Dashboards**: `index.html` offers an immediate overview of broker status, live positions, P&L, and risk statuses.
- **Trade Monitoring**: `trades.html` includes five tabs for live positions (with real-time price updates and glowing effects), pending orders, filled orders, signals, and an event log.
- **Performance Analytics**: `analytics.html` provides over 30 performance metrics, trade journaling, time-series charts, P&L heatmaps, and edge analysis using Chart.js.
- **Intuitive Settings**: Dedicated sections for Discord, Telegram, Brokers, Trading, Risk Management, Notifications, and AI Analysis ensure easy configuration.
- **Visual Feedback**: Streaming indicators, glow effects on price changes, and staleness indicators provide clear status updates.

**Technical Implementations:**
- **Signal Sources**: Integrates with Discord (via `discord.py-self`) and Telegram (via Telethon) for signal monitoring, supporting embed parsing, regex matching, and AI-powered detection.
- **5-Tier Signal Parsing**: Employs a tiered parsing system starting from embed parsers, moving to standard formats, trader-specific patterns, regex, and finally an AI fallback using OpenAI GPT. Features include deduplication, market order support, follow-up SL/PT updates, and configurable regex patterns.
- **Risk Management Engine**: A comprehensive, multi-layered risk management system with global and per-channel settings. It includes configurable Stop Loss (SL), Trailing Stop, four Profit Targets (PTs), Dynamic SL Escalation, Max Profit Giveback Guard, and a "Leave Runner" feature. Risk states are persistent across restarts. Exit pricing uses streaming hub bid/ask when available: **bid price** for SL/trailing/giveback exits (realistic sell-side pricing), **mid price** for profit target exits (fair value). Falls back to broker's last trade price when hubs are offline.
- **Order Execution System**: An asynchronous, queue-based system for multi-broker order execution, featuring per-channel broker selection and a Universal Order Placement Resilience Layer with error classification, circuit breakers, and orchestrated retry budgets.
- **Order Management System (OMS)**: Handles dynamic SL/PT management, exit order arbitration, position matching, and FIFO-based P&L tracking with both execution-based and mark-to-market P&L.
- **WebSocket Streaming**: Utilizes Webull MQTT for real-time quotes and orders, and a 5-tier optimized Schwab WebSocket streaming system for Level One equities and options. Both employ centralized, thread-safe data hubs with TTL invalidation and hub-first lookups. Streaming hubs are now wired into the conditional order price monitor via `StreamingPriceMonitor`, providing sub-100ms pricing with zero API calls and automatic REST fallback when hubs are not streaming. The Quick Trade Options Chain subscribes option contracts to WebSocket streaming (Webull MQTT topic 105 / Schwab LEVELONE_OPTIONS) via `/api/options/subscribe-stream`, then polls cached hub quotes at 300ms via `/api/options/stream-quotes` for industry-grade flash price updates with green/red flash effects, while full chain REST refresh runs every 15s in background for Greeks/OI/volume.
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