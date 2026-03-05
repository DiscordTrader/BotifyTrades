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
The web control panel, built with Flask, provides real-time dashboards for broker status, live positions, P&L, and risk statuses. It includes detailed trade monitoring, performance analytics, intuitive settings, and visual feedback mechanisms like streaming indicators.

**Technical Implementations:**
- **Signal Sources**: Integrates with Discord and Telegram, utilizing a 5-tier parsing system (dedicated parsers, regex, AI fallback) for embed parsing, regex matching, and AI-powered detection, with deduplication and follow-up SL/PT updates.
- **Risk Management Engine**: A multi-layered system with global and per-channel settings, configurable Stop Loss, Trailing Stop, four Profit Targets, Dynamic SL Escalation, Max Profit Giveback Guard, EMA-5 Candlestick Risk Engine, and a "Leave Runner" feature. Risk states are persistent, and exit pricing prioritizes streaming hub bid/ask.
- **Position Sizing**: Per-channel percentage-based sizing uses live broker data for options and stocks, considering specific buying power metrics across brokers. A "Start-of-Day Balance Mode" offers an alternative using cached balances.
- **Order Execution System**: An asynchronous, queue-based system for multi-broker order execution, featuring per-channel broker selection and a Universal Order Placement Resilience Layer with error classification, circuit breakers, and retries. Includes hub-first slippage checks and an Order Chaser service.
- **Order Management System (OMS)**: Handles dynamic SL/PT management, exit order arbitration, position matching, and FIFO-based P&L tracking, supporting 12 types of exit source classifications.
- **WebSocket Streaming**: Utilizes Webull MQTT and an optimized Schwab WebSocket system for real-time quotes and orders, providing sub-100ms pricing for conditional orders and quick trade options chains, with automatic REST fallback.
- **Daily P&L Limit System**: Per-broker daily P&L tracking against start-of-day equity snapshots, with configurable dollar and percentage limits for profit targets and loss limits. Locks brokers from new BTO entries when thresholds are hit and resets at market open. Real-time P&L refresh on Webull order fills via MQTT streaming and immediate post-BTO account refresh for all brokers. Dashboard polls every 15s.
- **Broker Sync Service**: Reconciles database state with actual broker states, detecting order fills/cancellations, position changes, and account updates, also feeding daily P&L limit service.
- **Notification System**: Provides Discord webhook and desktop browser notifications for trading events.
- **Security & Authentication**: Implements admin account management, password hashing, email recovery, session-based authentication, rate limiting, and encrypted broker credentials. Schwab OAuth uses CSRF state tokens, PKCE, and a postMessage-based popup flow.
- **Database Architecture**: Uses SQLite with WAL mode for concurrent read/write operations, storing critical trading data and encrypted credentials.
- **AI Analysis**: Integrates OpenAI GPT for pre-trade and post-trade analysis, an AI chat assistant, and AI command toggles.
- **Risk Engine Direct Exit Architecture**: Dual-path exit execution system ensuring stop-loss orders execute even when the event loop is blocked, using a primary queue-based path and a backup daemon thread for direct broker calls.
- **Streaming Hub-First Architecture**: All price-fetching services prioritize WebullDataHub and SchwabDataHub before making REST API calls to reduce latency and errors.

**System Design Choices:**
- **Broker Isolation**: Prevents data cross-contamination by isolating each broker's streaming data.
- **Thread Safety**: All shared states are protected by locks.
- **Queue-Based Execution**: Signals are processed asynchronously.
- **Hub-First Architecture**: Prioritizes cached streaming data over REST API calls.
- **Graceful Degradation**: Automatically falls back to REST polling if streaming services are unavailable.
- **Modular Broker Abstraction**: Uses a common interface for diverse broker APIs.
- **Market Isolation**: Conditional order services for different markets operate independently.
- **Conditional Order Guards**: Includes per-channel Breakout Reset Guard and Limit Cap.

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