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
- **Position Sizing**: Per-channel percentage-based sizing uses live broker data for both option and stock trades, considering specific buying power metrics across different brokers. A "Start-of-Day Balance Mode" offers an alternative sizing mechanism using a cached snapshot of balances.
- **Order Execution System**: An asynchronous, queue-based system for multi-broker order execution, featuring per-channel broker selection and a Universal Order Placement Resilience Layer with error classification, circuit breakers, and retries. It incorporates hub-first slippage checks and an Order Chaser service for managing unfilled orders.
- **Order Management System (OMS)**: Handles dynamic SL/PT management, exit order arbitration, position matching, and FIFO-based P&L tracking. It supports 12 types of exit source classifications, mapping risk engine triggers to specific exit sources.
- **WebSocket Streaming**: Utilizes Webull MQTT and a 5-tier optimized Schwab WebSocket system for real-time quotes and orders. These centralized, thread-safe data hubs provide sub-100ms pricing for conditional orders and quick trade options chains, with automatic REST fallback.
- **Broker Sync Service**: A regular service to reconcile database state with actual broker states, detecting order fills/cancellations, position changes, and account updates.
- **Notification System**: Provides Discord webhook notifications for various trading events and desktop browser notifications.
- **Security & Authentication**: Implements admin account management with password hashing, email recovery, session-based authentication, rate limiting, and encrypted broker credentials.
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

## Risk Engine Direct Exit Architecture

The risk engine now has a dual-path exit execution system to ensure stop-loss orders ALWAYS execute, even when the event loop is blocked:

1. **Primary path**: STC signal queued to `order_queue` → Worker picks up immediately (bypasses sync_ready gate for `_risk_management_order` signals)
2. **Backup path**: A daemon thread waits 8 seconds, then checks if the worker handled the order. If not (queue still has items AND position still marked closing), the thread creates its own event loop and calls the broker's sell function directly.

Key changes:
- **Worker sync bypass**: Worker starts processing immediately after `broker_ready`. Risk orders (`_risk_management_order=True`) execute without waiting for `sync_ready`. Regular BTO signals are held until first sync completes.
- **Parallel broker sync**: `broker_sync_service.py` runs all broker syncs in parallel (not sequential) with a 30s shared deadline. Each broker's `_fetch_account_info` has a 15s timeout.
- **Stale closing flags**: `position_cache.py` clears `closing=True` flags on startup to prevent risk engine from skipping positions where previous exit orders failed.
- **Direct exit thread**: `position_monitor.py` spawns a daemon thread per STC order as a safety net. If the event loop is blocked (e.g., by Robinhood's synchronous HTTP calls via robin_stocks), the thread executes independently.