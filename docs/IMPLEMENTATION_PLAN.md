# BotifyTrades — SaaS Transformation Implementation Plan

**Version:** 1.0  
**Date:** April 19, 2026  
**Status:** Draft  
**Classification:** Internal

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Assessment](#2-current-state-assessment)
3. [Target Architecture](#3-target-architecture)
4. [Phase 1 — Centralized Price Server + SnapTrade](#4-phase-1--centralized-price-server--snaptrade)
5. [Phase 2 — Backend Risk Engine & Conditional Orders](#5-phase-2--backend-risk-engine--conditional-orders)
6. [Phase 3 — Full Multi-Tenant SaaS Platform](#6-phase-3--full-multi-tenant-saas-platform)
7. [Infrastructure & Deployment](#7-infrastructure--deployment)
8. [Data Architecture](#8-data-architecture)
9. [Security & Compliance](#9-security--compliance)
10. [Monitoring & Observability](#10-monitoring--observability)
11. [Cost Analysis](#11-cost-analysis)
12. [Risk Register](#12-risk-register)
13. [Success Metrics](#13-success-metrics)
14. [Appendix](#14-appendix)

---

## 1. Executive Summary

### Objective

Transform BotifyTrades from a single-user desktop trading bot into a scalable, cloud-native, multi-tenant SaaS platform with:

- **Centralized market data** via Polygon.io (replacing per-user broker streaming)
- **Unified broker execution** via SnapTrade (replacing 5 custom broker SDKs)
- **Backend risk management** (eliminating the "bot offline = no risk" problem)
- **Subscription revenue model** with tiered pricing

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Market data vendor | Polygon.io ($199-499/mo) | Licensed redistribution, 99.9% SLA, 10-50ms latency |
| Broker integration | SnapTrade | 20+ brokers, OAuth2, managed auth |
| Master-to-Bot protocol | WebSocket + Redis Pub/Sub | 10-50ms latency, 50K concurrent clients |
| Cloud provider | AWS (primary) | Best financial services ecosystem |
| Phased rollout | 3 phases over 8-14 months | De-risks transformation |

### Timeline Overview

```
Phase 1: Centralized Price + SnapTrade     [Weeks 1-6]      ████████░░░░░░░░░░░░
Phase 2: Backend Risk Engine               [Months 2-5]     ░░░░████████████░░░░
Phase 3: Full Multi-Tenant SaaS            [Months 5-12]    ░░░░░░░░░░░░████████
```

---

## 2. Current State Assessment

### Architecture Summary

Each user runs an independent bot instance with:

| Component | Current Implementation | File Path |
|-----------|----------------------|-----------|
| Price Streaming | Per-user Webull MQTT, Schwab WS, Tastytrade DXLink | `src/services/webull_streaming_client.py`, `schwab_streaming_client.py` |
| Price Aggregation | UnifiedPriceHub (local singleton) | `src/services/unified_price_hub.py` |
| Conditional Orders | Local price monitoring with broker fallback chain | `src/services/conditional_orders/us_service.py` |
| Risk Engine | Local 1-second monitoring cycle | `src/risk/position_monitor.py`, `risk_engine.py` |
| Position Tracking | Local PositionLedger + BrokerSync | `src/services/position_ledger.py`, `broker_sync_service.py` |
| Broker Connections | 5 custom SDKs (Webull, Schwab, Tastytrade, IBKR, Alpaca) | `src/brokers/*.py` |
| Signal Intake | Discord selfbot | `src/selfbot_webull.py` |

### Current Limitations

1. Every user must configure and maintain broker streaming credentials
2. Price data quality depends on each user's network and broker token health
3. If user closes bot, risk engine stops — open positions are unmonitored
4. 5 separate broker SDKs require independent maintenance
5. No centralized monitoring or admin visibility
6. No revenue model beyond one-time license sales
7. Broker data redistribution would violate Terms of Service

---

## 3. Target Architecture

### High-Level Design

```
┌──────────────────────────────────────────────────────────────────┐
│                       MASTER APPLICATION                          │
│                                                                    │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐ │
│  │ Polygon.io │  │ Schwab WS  │  │ Webull MQTT│  │ Tastytrade │ │
│  │ (Primary)  │  │ (Backup 1) │  │ (Backup 2) │  │ (Backup 3) │ │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘ │
│        └────────────────┼───────────────┼───────────────┘        │
│                         ▼                                         │
│              ┌─────────────────────┐                              │
│              │  Price Aggregator   │                              │
│              │  (UnifiedPriceHub)  │                              │
│              └──────────┬──────────┘                              │
│                         ▼                                         │
│              ┌─────────────────────┐                              │
│              │   Redis Pub/Sub     │                              │
│              └──────────┬──────────┘                              │
│                         ▼                                         │
│  ┌──────────────────────────────────────────────────────────────┐│
│  │              WebSocket Gateway (Authenticated)               ││
│  │         Smart Subscription: Only symbols users watch         ││
│  └─────┬──────────────┬──────────────┬──────────────┬──────────┘│
│        │              │              │              │            │
│  Phase 2+:  ┌─────────────────┐  ┌──────────────┐              │
│             │ Conditional     │  │ Risk Engine  │              │
│             │ Order Engine    │  │ (all users)  │              │
│             └─────────────────┘  └──────────────┘              │
│                                                                    │
│  Phase 3+:  ┌─────────────────┐  ┌──────────────┐              │
│             │ User Management │  │ Billing      │              │
│             │ (multi-tenant)  │  │ (Stripe)     │              │
│             └─────────────────┘  └──────────────┘              │
└────────┬──────────────┬──────────────┬──────────────┬──────────┘
         ▼              ▼              ▼              ▼
    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │ User 1  │    │ User 2  │    │ User 3  │    │ User N  │
    │  Bot    │    │  Bot    │    │  Bot    │    │  Bot    │
    └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘
         │              │              │              │
         └──────────────┼──────────────┼──────────────┘
                        ▼
              ┌─────────────────────┐
              │   SnapTrade API     │
              │  (20+ Brokers)      │
              │  Schwab │ Webull    │
              │  IBKR │ Tastytrade  │
              │  Fidelity │ ...     │
              └─────────────────────┘
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Market Data | Polygon.io WebSocket | Primary real-time price feed |
| Message Broker | Redis 7.x (Pub/Sub + Streams) | Internal price distribution |
| WebSocket Gateway | Python (websockets) or Go | Client-facing price API |
| API Server | FastAPI (Python) | REST API for user management, settings |
| Database | PostgreSQL 16 | Multi-tenant user data, settings, trade history |
| Cache | Redis | Session cache, rate limiting, price cache |
| Broker Execution | SnapTrade SDK | Order placement across 20+ brokers |
| Task Queue | Celery + Redis | Background jobs (reports, notifications) |
| Cloud | AWS (ECS/EKS) | Container orchestration |
| Monitoring | Prometheus + Grafana | Metrics, alerting, dashboards |
| Logging | ELK Stack or CloudWatch | Centralized log aggregation |

---

## 4. Phase 1 — Centralized Price Server + SnapTrade

**Timeline:** Weeks 1-6  
**Risk Level:** Low  
**Target Users:** 100-500  

### 4.1 Objectives

- Build Master Price Server with Polygon.io integration
- Create WebSocket API for user bots to receive prices
- Integrate SnapTrade for broker execution in user bot
- Keep risk engine and conditional orders on user bot (unchanged)
- Validate architecture before deeper investment

### 4.2 Deliverables

#### Week 1-2: Master Price Server Core

```
master_server/
├── main.py                          # Entry point
├── config.py                        # Configuration management
├── requirements.txt
├── docker-compose.yml
│
├── data_sources/
│   ├── __init__.py
│   ├── base_source.py               # Abstract data source interface
│   ├── polygon_source.py            # Polygon.io WebSocket client
│   ├── schwab_backup_source.py      # Schwab WS failover
│   └── webull_backup_source.py      # Webull MQTT failover
│
├── aggregator/
│   ├── __init__.py
│   ├── price_aggregator.py          # Multi-source price aggregation
│   ├── quote_model.py               # UnifiedQuote dataclass
│   └── failover_manager.py          # Auto-switch on source failure
│
├── distribution/
│   ├── __init__.py
│   ├── redis_publisher.py           # Publish prices to Redis Pub/Sub
│   ├── websocket_gateway.py         # Client-facing WebSocket server
│   ├── subscription_manager.py      # Track which symbols each client needs
│   └── auth_middleware.py           # API key validation for connections
│
└── monitoring/
    ├── __init__.py
    ├── health_check.py              # /health endpoint
    ├── metrics.py                   # Prometheus metrics
    └── data_quality.py              # Staleness detection, gap alerts
```

**Key Implementation Details:**

**price_aggregator.py:**
```python
# Responsibilities:
# - Receive ticks from active data source (Polygon primary)
# - Validate tick data (price > 0, timestamp reasonable)
# - Detect source staleness (no update > 5 seconds)
# - Auto-failover to backup source
# - Publish validated quotes to Redis
#
# Quote freshness levels (reuse existing model):
#   fresh: ≤3s | aging: ≤5s | stale: ≤10s | degraded: ≤30s
```

**websocket_gateway.py:**
```python
# Responsibilities:
# - Accept authenticated WebSocket connections from user bots
# - Each client sends subscription list: {"subscribe": ["AAPL", "SPY", "TSLA"]}
# - Server pushes only subscribed symbols to each client
# - Heartbeat every 15 seconds (detect dead connections)
# - Reconnection handling with subscription restore
#
# Message format (JSON):
# {
#     "type": "quote",
#     "symbol": "AAPL",
#     "bid": 185.42,
#     "ask": 185.44,
#     "last": 185.43,
#     "volume": 1523400,
#     "timestamp": 1713484800.123,
#     "source": "polygon"
# }
```

**subscription_manager.py:**
```python
# Smart subscription filtering:
# - Track all symbols across all connected clients
# - Subscribe to Polygon only for symbols at least one client needs
# - Unsubscribe when last client watching a symbol disconnects
# - Prevents subscribing to 8000+ symbols unnecessarily
# - Aggregate subscription changes (batch every 500ms)
```

#### Week 2-3: User Bot Price Client

Modify the existing user bot to receive prices from Master instead of broker streaming.

**New file: `src/services/master_price_client.py`**

```python
# MasterPriceClient replaces direct broker streaming as price source
#
# Responsibilities:
# - Connect to Master WebSocket with API key auth
# - Subscribe to symbols needed by conditional orders + risk engine
# - Feed prices into existing UnifiedPriceHub
# - Auto-reconnect with exponential backoff
# - Fallback to direct broker streaming if Master unavailable
#
# Integration point:
# - UnifiedPriceHub.register_source("master", master_price_client)
# - Priority: master > broker_streaming > broker_rest
#
# Configuration:
#   MASTER_WS_URL=wss://price.botifytrades.com/ws
#   MASTER_API_KEY=user_api_key_here
#   MASTER_FALLBACK_ENABLED=true
```

**Modifications to existing files:**

| File | Change | Description |
|------|--------|-------------|
| `src/services/unified_price_hub.py` | Add `master` source priority | Master becomes highest priority source |
| `src/selfbot_webull.py` | Initialize MasterPriceClient | Connect on startup if MASTER_WS_URL configured |
| `src/services/conditional_orders/us_service.py` | Update price fallback chain | Master → broker streaming → broker REST |
| `src/risk/position_monitor.py` | Update price fetch | Use UnifiedPriceHub (which now prefers Master) |

#### Week 3-4: SnapTrade Integration

**New file: `src/brokers/snaptrade_broker.py`**

```python
# SnapTradeBroker implements BrokerInterface
#
# Responsibilities:
# - User authentication via SnapTrade OAuth redirect
# - Place orders (market, limit, stop) via SnapTrade API
# - Fetch positions and account balances
# - Handle order status callbacks
#
# Key methods (implementing BrokerInterface):
#   connect()                → Initialize SnapTrade session
#   place_order()            → POST /trade/{accountId}/orders
#   get_positions()          → GET /accounts/{accountId}/positions
#   get_pending_orders()     → GET /accounts/{accountId}/orders
#   cancel_order()           → DELETE /trade/{accountId}/orders/{orderId}
#   get_account()            → GET /accounts/{accountId}
#
# Authentication flow:
#   1. User enters SnapTrade user_id + user_secret in bot settings
#   2. Bot generates redirect URL via SnapTrade SDK
#   3. User completes broker OAuth in browser
#   4. SnapTrade stores encrypted credentials (never touches our server)
#   5. Bot receives authorization_id for subsequent API calls
#
# Configuration:
#   SNAPTRADE_CLIENT_ID=your_client_id
#   SNAPTRADE_CONSUMER_KEY=your_consumer_key
#   SNAPTRADE_USER_ID=user_generated_id
#   SNAPTRADE_USER_SECRET=user_generated_secret
```

**Modifications to existing files:**

| File | Change | Description |
|------|--------|-------------|
| `src/broker_interface.py` | No change | SnapTradeBroker implements existing interface |
| `src/broker_manager.py` | Add `snaptrade` to broker factory | Register new broker type |
| `gui_app/database.py` | Add SnapTrade credential columns | Store user_id, user_secret, authorization_id |
| `src/selfbot_webull.py` | Add SnapTrade initialization | Initialize if SNAPTRADE config present |

#### Week 4-5: SnapTrade GUI Integration

**Modifications to GUI:**

| Component | Change |
|-----------|--------|
| Settings Page | Add SnapTrade section with "Connect Broker" button |
| Broker Connection | OAuth redirect flow (opens browser for broker login) |
| Broker Status | Show connected broker name, account type, connection health |
| Order Execution | Route orders through SnapTrade when selected as active broker |

#### Week 5-6: Testing & Deployment

**Test Matrix:**

| Test Case | Description | Priority |
|-----------|-------------|----------|
| Price delivery | Master → User Bot price latency < 100ms | P0 |
| Price failover | Master down → fallback to direct broker | P0 |
| SnapTrade order | Place market order via SnapTrade | P0 |
| SnapTrade positions | Fetch and display positions | P0 |
| Conditional trigger | Conditional order triggers from Master price | P0 |
| Risk monitoring | Risk engine evaluates using Master prices | P0 |
| Reconnection | Bot reconnects to Master after disconnect | P1 |
| Multi-symbol | 200+ symbols streaming simultaneously | P1 |
| Load test | 100 concurrent bot connections | P1 |
| Stale detection | Alert when price data > 10s old | P2 |

**Deployment Plan:**

1. Deploy Master Price Server to AWS ECS (single instance initially)
2. Configure Polygon.io WebSocket connection
3. Set up Redis for Pub/Sub
4. Configure SSL/TLS for WebSocket gateway
5. Generate API keys for beta testers
6. Roll out to 10 beta users first
7. Monitor latency, error rates, connection stability for 1 week
8. Expand to 50 users, then 100+

### 4.3 Phase 1 Success Criteria

- [ ] Master Price Server receives Polygon data with < 50ms latency
- [ ] User bots connect and receive subscribed symbols within 2 seconds
- [ ] Price failover activates within 5 seconds of source failure
- [ ] SnapTrade order placement succeeds for Schwab and Webull
- [ ] Conditional orders trigger correctly from Master prices
- [ ] Risk engine operates normally with Master price source
- [ ] 100 concurrent connections sustained without degradation
- [ ] Zero data loss during Master restart (reconnection works)

---

## 5. Phase 2 — Backend Risk Engine & Conditional Orders

**Timeline:** Months 2-5 (after Phase 1 validation)  
**Risk Level:** Medium-High  
**Target Users:** 1,000+  

### 5.1 Objectives

- Move conditional order monitoring to Master Application
- Move risk engine to Master Application (solves "bot offline" problem)
- User bot becomes thin client (signal parsing + UI + settings)
- Add WebSocket push notifications for trade events

### 5.2 Architecture Changes

```
BEFORE (Phase 1):                          AFTER (Phase 2):

User Bot:                                  User Bot (Thin Client):
  ├── Signal Parser        ✓                 ├── Signal Parser        ✓
  ├── Conditional Orders   ← MOVES →         ├── Settings UI          ✓
  ├── Risk Engine          ← MOVES →         ├── Trade Notifications  ✓
  ├── Position Ledger      ← MOVES →         └── SnapTrade Auth       ✓
  ├── Exit Dispatcher      ← MOVES →
  └── SnapTrade Execution  ✓               Master Application:
                                              ├── Price Server         ✓ (from Phase 1)
Master:                                       ├── Conditional Orders   ★ NEW
  └── Price Server         ✓                  ├── Risk Engine          ★ NEW
                                              ├── Position Ledger      ★ NEW
                                              ├── Exit Dispatcher      ★ NEW
                                              ├── SnapTrade Execution  ★ NEW
                                              └── User Session Manager ★ NEW
```

### 5.3 Deliverables

#### Month 2: Multi-Tenant Data Layer

```
master_server/
├── database/
│   ├── models.py                    # SQLAlchemy/Peewee models
│   ├── migrations/                  # Alembic migrations
│   │
│   ├── tables:
│   │   ├── users                    # User accounts, API keys
│   │   ├── user_channels            # Per-user Discord channel configs
│   │   ├── channel_risk_settings    # Per-user, per-channel risk rules
│   │   ├── conditional_orders       # All users' pending orders
│   │   ├── positions                # All users' open positions (ledger)
│   │   ├── trades                   # Trade history with P&L
│   │   ├── broker_connections       # SnapTrade auth per user
│   │   └── audit_log               # All actions for compliance
│   │
│   └── tenant_isolation.py          # Row-level security, user_id filtering
```

**Data isolation strategy:**

```
Every query includes user_id filter:
  SELECT * FROM positions WHERE user_id = :uid AND status = 'open'

No cross-tenant data leakage possible:
  - All models have user_id foreign key (NOT NULL)
  - Database views enforce row-level security
  - API layer validates user_id matches authenticated session
  - Logging includes user_id for audit trail
```

#### Month 2-3: Backend Conditional Order Engine

```
master_server/
├── conditional_orders/
│   ├── engine.py                    # Main conditional order processor
│   ├── order_store.py               # CRUD operations on conditional_orders table
│   ├── price_evaluator.py           # Price condition evaluation (over/under/crosses)
│   └── execution_dispatcher.py      # Route triggered orders to SnapTrade
```

**Key design decisions:**

| Decision | Approach | Rationale |
|----------|----------|-----------|
| Order storage | PostgreSQL (persistent) | Survives server restart |
| Price evaluation | Event-driven (Redis subscription) | Sub-second reaction to price changes |
| Execution | Async task queue (Celery) | Retry logic, error handling, audit trail |
| User isolation | user_id on every order | Strict multi-tenant separation |

**Workflow:**

```
1. User bot sends conditional order via REST API:
   POST /api/v1/orders/conditional
   {
     "user_id": "usr_123",
     "symbol": "BZAI",
     "condition": "over",
     "price": 2.40,
     "action": "BUY",
     "quantity": 100,
     "stop_loss_pct": 10,
     "channel_id": "discord_channel_456"
   }

2. Master stores order in PostgreSQL (status: PENDING_MONITOR)

3. Master subscribes to BZAI price via Redis Pub/Sub
   (if not already subscribed for another user)

4. On each price tick for BZAI:
   - Fetch all PENDING_MONITOR orders for BZAI
   - Evaluate condition: last_price > 2.40?
   - If met: status → TRIGGERED

5. Triggered order dispatched to SnapTrade:
   - Fetch user's broker connection from DB
   - Place order via SnapTrade API
   - Update order status: EXECUTING → FILLED/FAILED

6. Push notification to user bot via WebSocket:
   {
     "type": "order_triggered",
     "symbol": "BZAI",
     "fill_price": 2.42,
     "quantity": 100,
     "broker": "schwab"
   }
```

#### Month 3-4: Backend Risk Engine

```
master_server/
├── risk_engine/
│   ├── manager.py                   # Main risk monitoring loop
│   ├── evaluator.py                 # Port of risk_engine.py evaluate_exit_actions()
│   ├── position_cache.py            # Port of position_cache.py (per-user state)
│   ├── trailing_stop.py             # Port of trailing_stop.py
│   ├── exit_arbiter.py              # Port of exit_order_arbiter.py
│   ├── exit_dispatcher.py           # Execute exits via SnapTrade
│   └── user_risk_store.py           # Per-user risk settings from DB
```

**Critical design: Multi-user risk monitoring**

```
Current (single-user):
  - 1 RiskManager instance
  - 1-second loop evaluates all positions
  - Direct broker execution

Backend (multi-user):
  - 1 RiskManager instance handles ALL users
  - Event-driven: price tick → evaluate affected positions
  - Partitioned by symbol for parallelism:
      Worker 1: AAPL, AMZN, GOOGL positions (all users)
      Worker 2: SPY, QQQ, TSLA positions (all users)
      Worker N: assigns dynamically by load

  - Position lookup: symbol → [user1_position, user2_position, ...]
  - Each user's risk settings loaded from DB (cached 10s)
  - Exit orders dispatched per-user via their SnapTrade connection
```

**Scaling model:**

| Users | Concurrent Positions | Risk Eval/sec | Workers Needed |
|-------|---------------------|---------------|----------------|
| 100 | ~500 | ~500 | 1 |
| 500 | ~2,500 | ~2,500 | 2-3 |
| 1,000 | ~5,000 | ~5,000 | 4-5 |
| 5,000 | ~25,000 | ~25,000 | 10-15 |

#### Month 4-5: User Bot Thin Client Conversion

**Remove from user bot:**
- `src/services/conditional_orders/` → Backend handles this
- `src/risk/` → Backend handles this
- `src/services/position_ledger.py` → Backend handles this
- `src/services/exit_dispatcher.py` → Backend handles this
- `src/services/price_monitor_service.py` → Backend handles this
- `src/services/broker_sync_service.py` → Backend handles this

**Add to user bot:**

```
src/
├── api_client/
│   ├── master_api.py                # REST API client for Master
│   │   Methods:
│   │   - submit_conditional_order()
│   │   - get_positions()
│   │   - get_trade_history()
│   │   - update_risk_settings()
│   │   - connect_broker()
│   │
│   └── event_stream.py              # WebSocket client for real-time events
│       Events received:
│       - order_triggered
│       - position_opened
│       - position_closed (partial/full)
│       - risk_alert (approaching SL)
│       - system_notification
```

**User bot now does:**
1. Parse Discord signals
2. Submit conditional orders to Master API
3. Display positions/trades from Master API
4. Show real-time events from Master WebSocket
5. Settings management (stored on Master)

### 5.4 Phase 2 API Specification

#### REST API Endpoints

```
Authentication:
  POST   /api/v1/auth/register          # Create user account
  POST   /api/v1/auth/login             # Get JWT token
  POST   /api/v1/auth/refresh           # Refresh JWT token

Broker:
  POST   /api/v1/broker/connect         # Initiate SnapTrade OAuth
  GET    /api/v1/broker/status           # Connection status
  DELETE /api/v1/broker/disconnect       # Remove broker connection
  GET    /api/v1/broker/accounts         # List connected accounts

Conditional Orders:
  POST   /api/v1/orders/conditional      # Create conditional order
  GET    /api/v1/orders/conditional      # List all orders (active/history)
  DELETE /api/v1/orders/conditional/:id  # Cancel pending order
  GET    /api/v1/orders/conditional/:id  # Get order details + status

Positions:
  GET    /api/v1/positions               # All open positions
  GET    /api/v1/positions/:id           # Position detail + exit history
  POST   /api/v1/positions/:id/close     # Manual close request

Risk Settings:
  GET    /api/v1/risk/channels           # List channel risk configs
  PUT    /api/v1/risk/channels/:id       # Update channel risk settings
  GET    /api/v1/risk/global             # Global risk settings
  PUT    /api/v1/risk/global             # Update global risk settings

Trade History:
  GET    /api/v1/trades                  # Trade history with P&L
  GET    /api/v1/trades/summary          # P&L summary by period
  GET    /api/v1/trades/export           # CSV export

System:
  GET    /api/v1/system/health           # Health check
  GET    /api/v1/system/status           # Data source status, latency
```

#### WebSocket Events (Master → User Bot)

```json
// Connection
{"type": "connected", "user_id": "usr_123", "server_time": 1713484800}

// Price updates (subscribed symbols only)
{"type": "quote", "symbol": "AAPL", "last": 185.43, "bid": 185.42, "ask": 185.44}

// Order lifecycle
{"type": "order_monitoring", "order_id": "ord_456", "symbol": "BZAI", "condition": "over 2.40"}
{"type": "order_triggered", "order_id": "ord_456", "symbol": "BZAI", "fill_price": 2.42}
{"type": "order_failed", "order_id": "ord_456", "reason": "insufficient_funds"}

// Position lifecycle
{"type": "position_opened", "position_id": "pos_789", "symbol": "BZAI", "qty": 100, "entry": 2.42}
{"type": "risk_update", "position_id": "pos_789", "current_price": 2.55, "pnl_pct": 5.37}
{"type": "risk_alert", "position_id": "pos_789", "alert": "approaching_sl", "distance_pct": 2.1}
{"type": "partial_exit", "position_id": "pos_789", "exit_qty": 25, "exit_price": 2.65, "reason": "PT1"}
{"type": "position_closed", "position_id": "pos_789", "total_pnl": 15.30, "reason": "trailing_stop"}

// System
{"type": "heartbeat", "server_time": 1713484815}
{"type": "data_source_change", "from": "polygon", "to": "schwab", "reason": "polygon_timeout"}
```

### 5.5 Phase 2 Success Criteria

- [ ] Conditional orders process correctly for 100+ concurrent users
- [ ] Risk engine monitors all user positions with < 2-second evaluation cycle
- [ ] Positions remain monitored even when user bot is offline
- [ ] Exit orders execute via SnapTrade within 500ms of risk trigger
- [ ] WebSocket events delivered to user bot within 100ms
- [ ] Zero cross-tenant data leakage (security audit passes)
- [ ] 99.5% uptime for risk engine over 30-day period
- [ ] All trade actions logged to audit trail

---

## 6. Phase 3 — Full Multi-Tenant SaaS Platform

**Timeline:** Months 5-12  
**Risk Level:** High (business transformation, not just technical)  
**Target Users:** 10,000+  

### 6.1 Objectives

- Replace desktop bot with web-based dashboard
- Multi-tenant user management with roles and permissions
- Subscription billing via Stripe
- Admin panel for monitoring all users and system health
- Mobile-responsive design

### 6.2 Deliverables

#### Web Dashboard

```
web_dashboard/
├── frontend/                        # React + TypeScript
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx        # Portfolio overview, P&L chart
│   │   │   ├── Positions.tsx        # Live positions with risk status
│   │   │   ├── Orders.tsx           # Conditional orders management
│   │   │   ├── Channels.tsx         # Discord channel configuration
│   │   │   ├── RiskSettings.tsx     # Per-channel risk configuration
│   │   │   ├── TradeHistory.tsx     # Historical trades with analytics
│   │   │   ├── BrokerConnect.tsx    # SnapTrade broker onboarding
│   │   │   ├── Settings.tsx         # Account settings, API keys
│   │   │   └── Billing.tsx          # Subscription management
│   │   │
│   │   ├── components/
│   │   │   ├── LivePriceCard.tsx    # Real-time price display
│   │   │   ├── PositionRow.tsx      # Position with live P&L
│   │   │   ├── RiskGauge.tsx        # Visual risk indicator
│   │   │   ├── PnLChart.tsx         # D3/Recharts P&L visualization
│   │   │   └── TradeNotification.tsx # Toast notifications
│   │   │
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts      # Real-time event stream
│   │   │   └── useApi.ts            # REST API client
│   │   │
│   │   └── store/                   # Zustand/Redux state
│   │
│   └── package.json
│
└── admin/                           # Admin panel (separate app)
    ├── UserManagement.tsx           # View/manage all users
    ├── SystemHealth.tsx             # Data source status, latency
    ├── ActivePositions.tsx          # All users' positions (admin view)
    ├── RevenueMetrics.tsx           # MRR, churn, growth
    └── AuditLog.tsx                 # System-wide audit trail
```

#### Subscription Billing

| Plan | Price | Features |
|------|-------|----------|
| **Starter** | $29/mo | 1 broker, 3 channels, basic risk (SL + 2 PT tiers) |
| **Pro** | $79/mo | 3 brokers, 10 channels, full risk engine, trailing stops |
| **Premium** | $149/mo | Unlimited brokers/channels, EMA exits, giveback guard, priority support |
| **Enterprise** | Custom | API access, custom integrations, dedicated support |

**Stripe Integration:**

```
master_server/
├── billing/
│   ├── stripe_client.py             # Stripe API integration
│   ├── subscription_manager.py      # Create/update/cancel subscriptions
│   ├── webhook_handler.py           # Stripe webhook events
│   ├── usage_metering.py            # Track feature usage per user
│   └── invoice_generator.py         # Monthly invoices
```

#### User Onboarding Flow

```
Step 1: Sign Up
  → Email + password registration
  → Email verification

Step 2: Connect Broker
  → Select broker from SnapTrade list
  → Complete OAuth in browser
  → Verify connection with test balance fetch

Step 3: Configure Channels
  → Enter Discord channel IDs to monitor
  → Map channels to broker accounts
  → Set position sizing per channel

Step 4: Set Risk Rules
  → Configure stop loss, profit targets per channel
  → Enable/disable trailing stops, EMA exits
  → Set max position limits

Step 5: Activate
  → Choose subscription plan
  → Enter payment method
  → Bot begins monitoring signals
```

### 6.3 Phase 3 Success Criteria

- [ ] Web dashboard handles 1,000+ concurrent users
- [ ] Subscription billing processes payments correctly
- [ ] Admin panel provides full system visibility
- [ ] User onboarding completes in under 5 minutes
- [ ] Mobile-responsive design works on all devices
- [ ] 99.9% uptime for web application
- [ ] Customer support workflow established

---

## 7. Infrastructure & Deployment

### AWS Architecture

```
Region: us-east-1 (primary), us-west-2 (failover)

┌─────────────────────────────────────────────────┐
│                    VPC                           │
│                                                   │
│  ┌─────────────┐     ┌─────────────────────┐    │
│  │ ALB         │────▶│ ECS Cluster          │    │
│  │ (HTTPS)     │     │  ├── price-server    │    │
│  └─────────────┘     │  ├── api-server      │    │
│                       │  ├── risk-engine     │    │
│                       │  ├── ws-gateway      │    │
│                       │  └── web-dashboard   │    │
│                       └─────────────────────┘    │
│                                                   │
│  ┌─────────────┐     ┌─────────────────────┐    │
│  │ ElastiCache │     │ RDS PostgreSQL       │    │
│  │ (Redis 7)   │     │ (Multi-AZ)          │    │
│  └─────────────┘     └─────────────────────┘    │
│                                                   │
│  ┌─────────────┐     ┌─────────────────────┐    │
│  │ CloudWatch  │     │ S3                   │    │
│  │ (Logs)      │     │ (Backups, exports)   │    │
│  └─────────────┘     └─────────────────────┘    │
└─────────────────────────────────────────────────┘
```

### Container Definitions

| Service | CPU | Memory | Min Instances | Max Instances |
|---------|-----|--------|---------------|---------------|
| price-server | 512 | 1GB | 1 | 2 |
| api-server | 256 | 512MB | 2 | 10 |
| risk-engine | 1024 | 2GB | 1 | 5 |
| ws-gateway | 512 | 1GB | 2 | 10 |
| web-dashboard | 256 | 256MB | 2 | 5 |

### Auto-Scaling Policies

| Service | Metric | Scale Up | Scale Down |
|---------|--------|----------|------------|
| api-server | CPU > 70% | +1 instance | CPU < 30% |
| ws-gateway | Connections > 5000/instance | +1 instance | Connections < 1000 |
| risk-engine | Eval latency > 2s | +1 worker | Eval latency < 500ms |

---

## 8. Data Architecture

### Database Schema (PostgreSQL)

```sql
-- Core tables (Phase 2+)

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    api_key         VARCHAR(64) UNIQUE NOT NULL,
    plan            VARCHAR(20) DEFAULT 'starter',
    stripe_customer_id VARCHAR(64),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_active_at  TIMESTAMPTZ
);

CREATE TABLE broker_connections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    broker_name     VARCHAR(50) NOT NULL,
    snaptrade_user_id     VARCHAR(255),
    snaptrade_user_secret VARCHAR(255),
    authorization_id      VARCHAR(255),
    account_id      VARCHAR(100),
    account_type    VARCHAR(20),
    status          VARCHAR(20) DEFAULT 'active',
    connected_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE channel_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    channel_id      VARCHAR(50) NOT NULL,
    channel_name    VARCHAR(100),
    broker_id       UUID REFERENCES broker_connections(id),
    enabled         BOOLEAN DEFAULT TRUE,
    -- Risk settings
    risk_enabled    BOOLEAN DEFAULT TRUE,
    stop_loss_pct   DECIMAL(5,2),
    pt1_pct         DECIMAL(5,2),
    pt1_qty_pct     DECIMAL(5,2),
    pt2_pct         DECIMAL(5,2),
    pt2_qty_pct     DECIMAL(5,2),
    pt3_pct         DECIMAL(5,2),
    pt3_qty_pct     DECIMAL(5,2),
    pt4_pct         DECIMAL(5,2),
    pt4_qty_pct     DECIMAL(5,2),
    trailing_stop_pct       DECIMAL(5,2),
    trailing_activation_pct DECIMAL(5,2),
    exit_strategy_mode      VARCHAR(10) DEFAULT 'hybrid',
    -- Position sizing
    default_quantity        INTEGER,
    max_position_size       DECIMAL(10,2),
    UNIQUE(user_id, channel_id)
);

CREATE TABLE conditional_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    channel_id      VARCHAR(50),
    symbol          VARCHAR(20) NOT NULL,
    condition_type  VARCHAR(10) NOT NULL,  -- over, under, crosses
    condition_price DECIMAL(10,4) NOT NULL,
    action          VARCHAR(10) NOT NULL,  -- BUY, SELL
    quantity        INTEGER,
    stop_loss_pct   DECIMAL(5,2),
    status          VARCHAR(20) DEFAULT 'pending_monitor',
    broker_id       UUID REFERENCES broker_connections(id),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    triggered_at    TIMESTAMPTZ,
    filled_at       TIMESTAMPTZ,
    fill_price      DECIMAL(10,4),
    error_message   TEXT
);

CREATE TABLE positions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    order_id        UUID REFERENCES conditional_orders(id),
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(10) NOT NULL,
    entry_qty       INTEGER NOT NULL,
    remaining_qty   INTEGER NOT NULL,
    entry_price     DECIMAL(10,4) NOT NULL,
    current_price   DECIMAL(10,4),
    stop_loss_price DECIMAL(10,4),
    status          VARCHAR(20) DEFAULT 'open',
    -- Risk state
    highest_price   DECIMAL(10,4),
    max_pnl_seen    DECIMAL(10,4),
    trailing_activated BOOLEAN DEFAULT FALSE,
    dynamic_sl_price   DECIMAL(10,4),
    pt1_hit         BOOLEAN DEFAULT FALSE,
    pt2_hit         BOOLEAN DEFAULT FALSE,
    pt3_hit         BOOLEAN DEFAULT FALSE,
    pt4_hit         BOOLEAN DEFAULT FALSE,
    -- Timestamps
    opened_at       TIMESTAMPTZ DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    close_reason    VARCHAR(30)
);

CREATE TABLE trade_exits (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    position_id     UUID REFERENCES positions(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    exit_qty        INTEGER NOT NULL,
    exit_price      DECIMAL(10,4) NOT NULL,
    exit_reason     VARCHAR(30) NOT NULL,
    realized_pnl    DECIMAL(10,4),
    exited_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_orders_user_status ON conditional_orders(user_id, status);
CREATE INDEX idx_orders_symbol_status ON conditional_orders(symbol, status) WHERE status = 'pending_monitor';
CREATE INDEX idx_positions_user_status ON positions(user_id, status);
CREATE INDEX idx_positions_symbol_status ON positions(symbol, status) WHERE status = 'open';
CREATE INDEX idx_exits_position ON trade_exits(position_id);
```

### Data Migration Strategy

```
Phase 1: No database migration needed (user bot keeps local SQLite)

Phase 2: Migration from local SQLite to central PostgreSQL
  Step 1: Export user's local data (channels, risk settings, trade history)
  Step 2: Create user account on Master
  Step 3: Import settings via API
  Step 4: Active positions manually reconciled
  Step 5: Historical trades imported as read-only archive

Phase 3: SQLite fully deprecated, all data in PostgreSQL
```

---

## 9. Security & Compliance

### Authentication & Authorization

| Layer | Mechanism | Details |
|-------|-----------|---------|
| User → API | JWT (RS256) | 15-min access token, 7-day refresh token |
| User → WebSocket | JWT in connection header | Validated on connect, re-validated on refresh |
| Bot → Master | API Key | Unique per user, rotatable, rate-limited |
| Broker Auth | SnapTrade OAuth2 | Credentials never touch our servers |
| Admin | JWT + MFA (TOTP) | Required for admin panel access |

### Data Protection

| Data Type | Protection | Storage |
|-----------|-----------|---------|
| User passwords | bcrypt (cost 12) | PostgreSQL |
| API keys | SHA-256 hash (lookup), AES-256 (display once) | PostgreSQL |
| SnapTrade secrets | AES-256-GCM at rest | PostgreSQL + KMS |
| Trade data | Row-level security (user_id filter) | PostgreSQL |
| Price data | Not sensitive (public market data) | Redis (ephemeral) |
| Audit logs | Append-only, tamper-evident | PostgreSQL + S3 archive |

### Rate Limiting

| Endpoint | Limit | Window |
|----------|-------|--------|
| REST API | 120 requests | per minute |
| WebSocket messages | 60 messages | per minute |
| Order submission | 10 orders | per minute |
| Auth endpoints | 5 attempts | per minute |

### Compliance Considerations

- **Market Data Redistribution**: Polygon.io business plan includes redistribution rights
- **Broker Data**: SnapTrade handles all compliance for broker integrations
- **User Data**: GDPR-ready data model (delete user = cascade delete all data)
- **Financial Advice**: Platform is execution-only, no investment advice provided
- **Audit Trail**: All order/trade actions logged with timestamps and user context

---

## 10. Monitoring & Observability

### Metrics Dashboard

| Metric | Source | Alert Threshold |
|--------|--------|----------------|
| Price feed latency | price-server | > 100ms for 30s |
| Price feed staleness | price-server | No update for 10s |
| WebSocket connections | ws-gateway | > 80% capacity |
| Risk eval cycle time | risk-engine | > 2 seconds |
| Order execution time | api-server | > 1 second |
| SnapTrade API errors | api-server | > 5% error rate |
| Database query time | PostgreSQL | p99 > 100ms |
| Redis memory usage | ElastiCache | > 80% |
| Active positions count | risk-engine | Informational |
| P&L by user (aggregate) | api-server | Informational |

### Alerting Tiers

| Tier | Response Time | Channel | Example |
|------|--------------|---------|---------|
| P0 - Critical | < 5 min | PagerDuty + SMS | Price feed down, risk engine stopped |
| P1 - High | < 30 min | Slack #alerts | High error rate, degraded latency |
| P2 - Medium | < 4 hours | Slack #monitoring | Elevated resource usage |
| P3 - Low | Next business day | Email | Non-critical warnings |

### Health Check Endpoints

```
GET /health              → { "status": "healthy", "uptime": 86400 }
GET /health/detailed     → {
  "price_feed": { "status": "connected", "source": "polygon", "latency_ms": 23 },
  "redis": { "status": "connected", "memory_pct": 34 },
  "database": { "status": "connected", "query_p99_ms": 12 },
  "risk_engine": { "status": "running", "positions_monitored": 2847 },
  "ws_gateway": { "status": "running", "active_connections": 342 }
}
```

---

## 11. Cost Analysis

### Monthly Infrastructure Costs

#### Phase 1 (100 users)

| Service | Specification | Monthly Cost |
|---------|--------------|-------------|
| Polygon.io | Business plan | $199-499 |
| AWS ECS | 1x t3.medium (price server) | $30 |
| ElastiCache | cache.t3.micro (Redis) | $13 |
| ALB | Application Load Balancer | $22 |
| CloudWatch | Logs + metrics | $10 |
| Domain + SSL | Route 53 + ACM | $5 |
| **Total** | | **$279-579/mo** |

#### Phase 2 (1,000 users)

| Service | Specification | Monthly Cost |
|---------|--------------|-------------|
| Polygon.io | Business plan | $499 |
| AWS ECS | 4x t3.medium (all services) | $120 |
| RDS PostgreSQL | db.t3.medium (Multi-AZ) | $140 |
| ElastiCache | cache.t3.small (Redis) | $26 |
| ALB | Application Load Balancer | $30 |
| CloudWatch | Logs + metrics | $30 |
| S3 | Backups + exports | $5 |
| **Total** | | **$850/mo** |

#### Phase 3 (10,000 users)

| Service | Specification | Monthly Cost |
|---------|--------------|-------------|
| Polygon.io | Enterprise plan | $499 |
| AWS ECS/EKS | 10-15 containers (auto-scaling) | $500 |
| RDS PostgreSQL | db.r6g.large (Multi-AZ) | $400 |
| ElastiCache | cache.r6g.large (Redis cluster) | $200 |
| ALB | Application Load Balancer | $50 |
| CloudFront | CDN for web dashboard | $30 |
| CloudWatch | Logs + metrics + alarms | $100 |
| S3 | Backups, exports, static assets | $20 |
| Stripe fees | 2.9% + $0.30 per transaction | Variable |
| **Total** | | **~$1,800/mo** |

### Revenue Model

| Users | Plan Mix | MRR | Infrastructure | Gross Margin |
|-------|----------|-----|----------------|-------------|
| 50 | 70% Starter, 30% Pro | $1,830 | $400 | 78% |
| 200 | 60% Starter, 30% Pro, 10% Premium | $9,360 | $600 | 94% |
| 1,000 | 50% Starter, 35% Pro, 15% Premium | $55,600 | $850 | 98% |
| 5,000 | 40% Starter, 40% Pro, 20% Premium | $297,000 | $1,400 | 99.5% |

**Break-even: ~15 subscribers** (Phase 1 costs covered)

---

## 12. Risk Register

| # | Risk | Probability | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | Polygon.io outage | Low | Critical | Auto-failover to Schwab WS, then Webull MQTT |
| R2 | SnapTrade API changes | Medium | High | Maintain direct SDK fallback for top 3 brokers |
| R3 | Cross-tenant data leak | Low | Critical | Row-level security, penetration testing, audit |
| R4 | Risk engine crash with open positions | Low | Critical | Watchdog process, auto-restart, position state in PostgreSQL |
| R5 | SnapTrade bracket order limitations | High | Medium | Direct SDK fallback for complex exits |
| R6 | User migration resistance | Medium | Medium | Run both modes in parallel, gradual migration |
| R7 | Index options data gaps (SPX/NDX) | High | Medium | Schwab streaming backup for index options |
| R8 | Regulatory concerns | Low | High | Legal review, clear "execution only" positioning |
| R9 | WebSocket connection storms (reconnect) | Medium | Medium | Exponential backoff, connection queuing |
| R10 | Database growth at scale | Low | Medium | Partitioning by user_id, archival policy for old trades |

---

## 13. Success Metrics

### Phase 1 KPIs

| Metric | Target | Measurement |
|--------|--------|-------------|
| Price delivery latency | < 50ms (p95) | Prometheus histogram |
| Price feed uptime | > 99.5% | Uptime monitor |
| SnapTrade order success rate | > 98% | API response tracking |
| User onboarding time | < 10 minutes | Funnel analytics |
| Beta user satisfaction | > 4/5 rating | Survey |

### Phase 2 KPIs

| Metric | Target | Measurement |
|--------|--------|-------------|
| Risk eval cycle time | < 2 seconds (p99) | Prometheus histogram |
| Position monitoring uptime | > 99.9% | Health check |
| Cross-tenant isolation | 0 violations | Security audit |
| API response time | < 200ms (p95) | ALB metrics |
| Concurrent users supported | 1,000+ | Load testing |

### Phase 3 KPIs

| Metric | Target | Measurement |
|--------|--------|-------------|
| Monthly Recurring Revenue | $10K+ by month 6 | Stripe dashboard |
| User activation rate | > 60% (sign up → first trade) | Funnel analytics |
| Monthly churn rate | < 5% | Subscription analytics |
| Net Promoter Score | > 40 | Quarterly survey |
| Support ticket resolution | < 24 hours (p90) | Help desk metrics |

---

## 14. Appendix

### A. File Reference — Current Architecture

| Component | File Path |
|-----------|-----------|
| Main Bot Entry | `src/selfbot_webull.py` |
| Unified Price Hub | `src/services/unified_price_hub.py` |
| Webull MQTT Streaming | `src/services/webull_streaming_client.py` |
| Schwab WebSocket Streaming | `src/services/schwab_streaming_client.py` |
| Tastytrade DXLink | `src/services/tastytrade_data_hub.py` |
| Webull Data Hub | `src/services/webull_data_hub.py` |
| Schwab Data Hub | `src/services/schwab_data_hub.py` |
| Conditional Order Service | `src/services/conditional_order_service.py` |
| US Conditional Orders | `src/services/conditional_orders/us_service.py` |
| Risk Manager | `src/risk/position_monitor.py` |
| Risk Engine (evaluator) | `src/risk/risk_engine.py` |
| Trailing Stop Logic | `src/risk/trailing_stop.py` |
| Position Cache | `src/risk/position_cache.py` |
| Position Ledger | `src/services/position_ledger.py` |
| Broker Sync Service | `src/services/broker_sync_service.py` |
| Exit Order Arbiter | `src/services/exit_order_arbiter.py` |
| Exit Dispatcher | `src/services/exit_dispatcher.py` |
| Broker Interface | `src/broker_interface.py` |
| Broker Manager | `src/broker_manager.py` |
| Webull Broker | `src/brokers/webull_broker.py` |
| Schwab Broker | `src/brokers/schwab_broker.py` |
| Tastytrade Broker | `src/brokers/tastytrade_broker.py` |
| IBKR Broker | `src/brokers/ibkr_broker.py` |
| Alpaca Broker | `src/brokers/alpaca_broker.py` |
| GUI Database | `gui_app/database.py` |
| Price Monitor Service | `src/services/price_monitor_service.py` |

### B. Glossary

| Term | Definition |
|------|-----------|
| **UnifiedPriceHub** | Singleton that aggregates prices from multiple data sources into one API |
| **Conditional Order** | An order that activates when a price condition is met (e.g., "BZAI over 2.40") |
| **Risk Engine** | System that monitors open positions and enforces SL/PT/trailing stop rules |
| **Position Ledger** | Single source of truth for all signal-based positions and their P&L |
| **Exit Arbiter** | Decides whether signal-driven or risk-driven exit takes precedence |
| **SnapTrade** | Third-party API providing unified broker access via OAuth2 |
| **Polygon.io** | Market data vendor providing real-time stock and options prices |
| **Data Hub** | Per-broker singleton that caches quotes, positions, and orders |
| **MQTT** | Message protocol used by Webull for real-time price streaming |
| **DXLink** | Tastytrade's real-time streaming protocol (built on DXFeed) |

### C. Decision Log

| Date | Decision | Alternatives Considered | Rationale |
|------|----------|------------------------|-----------|
| 2026-04-19 | Polygon.io as primary data vendor | Alpaca Data, Tradier, IEX Cloud, Broker-only | Best latency + SLA + redistribution rights |
| 2026-04-19 | SnapTrade for broker integration | Direct SDK maintenance, Plaid | 20+ broker coverage, managed OAuth, no credential handling |
| 2026-04-19 | WebSocket for Master→Bot communication | gRPC, SSE, HTTP polling | Bidirectional, widely supported, 10-50ms latency |
| 2026-04-19 | PostgreSQL for multi-tenant data | MySQL, MongoDB, CockroachDB | Row-level security, JSONB for flexible settings, proven at scale |
| 2026-04-19 | AWS for cloud hosting | GCP, Azure, Self-hosted | Best financial services ecosystem, ECS simplicity |
| 2026-04-19 | Phased rollout (3 phases) | Big-bang migration | De-risks transformation, validates each layer independently |

---

*This document is a living plan. Update as decisions are made and phases are completed.*
