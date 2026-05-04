# Signal Relay Architecture — Implementation Plan

**Version:** 1.0  
**Date:** April 29, 2026  
**Status:** Approved for Development  
**Depends on:** v9.3.3 release (completed)  
**HTML Reference:** `docs/signal_ingestion_architecture.html`

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Architecture Decision](#2-architecture-decision)
3. [System Components](#3-system-components)
4. [Phase 1: Cloud Relay + Selfbot Bridge](#4-phase-1-cloud-relay--selfbot-bridge)
5. [Phase 2: Desktop App Relay Client](#5-phase-2-desktop-app-relay-client)
6. [Phase 3: Provider Micro-Bot Kit](#6-phase-3-provider-micro-bot-kit)
7. [Phase 4: Provider Marketplace + Analytics](#7-phase-4-provider-marketplace--analytics)
8. [API Specification](#8-api-specification)
9. [Database Schema Changes](#9-database-schema-changes)
10. [Security Model](#10-security-model)
11. [Infrastructure & Deployment](#11-infrastructure--deployment)
12. [Failure Modes & Recovery](#12-failure-modes--recovery)
13. [Migration Path](#13-migration-path)
14. [Cost Analysis](#14-cost-analysis)
15. [Testing Strategy](#15-testing-strategy)
16. [Open Questions](#16-open-questions)

---

## 1. Problem Statement

### Current State
- 1,000+ users each run a Discord **selfbot** (`discord.py-self`) on their own machine
- Each user's personal Discord account is at risk of termination (violates Discord ToS)
- User must extract Discord token via browser DevTools — confusing for non-technical users
- Token invalidation on password change forces reconfiguration
- Commercial distribution of selfbot software creates legal exposure
- BotifyTrades cannot grow because "install a selfbot" is a dealbreaker for most traders

### Root Cause
Discord has **no outgoing webhook** and **no OAuth2 scope for reading messages**. The only ways to read messages from a Discord server are:
1. An official bot added by the server admin
2. A user account logged into the server (selfbot)

### Constraint from Partner Provider
- Provider admin will **not** add an official Discord bot to their server
- Provider **will** cooperate with forwarding (add a dedicated account, run a script, etc.)
- End users' Discord accounts must be **100% safe**

### Target State
- **Zero selfbot on user machines** — users never provide a Discord token
- ToS risk concentrated on **one disposable cloud account** (or eliminated entirely with micro-bot)
- Users can receive signals without having Discord at all
- Multiple signal sources (Discord, TradingView, Telegram, custom) unified through one relay

---

## 2. Architecture Decision

### Three-Tier Signal Ingestion

| Tier | Method | ToS Risk | Latency | When to Use |
|------|--------|----------|---------|-------------|
| **Tier 1** | Webhook API | Zero | <100ms | TradingView alerts, Zapier, custom integrations |
| **Tier 2** | Cloud Selfbot Bridge | 1 disposable account | <150ms | Provider won't add any bot |
| **Tier 3** | Official Discord Bot | Zero | <100ms | Provider adds BotifyTrades bot |

### Key Design Principle
All three tiers feed into the **same cloud relay server**. The relay normalizes, deduplicates, and fans out via WebSocket. The user's desktop app never knows which tier the signal came from.

### Why Not Carl-bot / MEE6 / Zapier?
- **Carl-bot / MEE6**: Can only mirror within Discord (channel-to-channel). Cannot POST to external HTTP endpoints.
- **Zapier / Make / IFTTT**: Add their own bot to the server (same constraint), and polling-based latency (1-15 min) is unacceptable for day trading.
- **Pipedream**: Best of the automation tools (event-driven, <1s latency), but still requires adding a bot.
- **Discord Webhooks**: Incoming-only. Cannot read messages out of a channel.

Full analysis: `docs/signal_ingestion_architecture.html` → "Deep Dive" section.

---

## 3. System Components

### 3.1 Cloud Relay Server (NEW — separate codebase)

```
relay_server/
├── app.py                    # FastAPI application entrypoint
├── config.py                 # Provider configs, API keys, environment
├── requirements.txt          # fastapi, uvicorn, websockets, discord.py-self, redis
├── Dockerfile                # Container for deployment
├── docker-compose.yml        # Relay + Redis
│
├── ingest/
│   ├── __init__.py
│   ├── router.py             # POST /api/v1/signals — webhook ingest endpoint
│   ├── provider_adapter.py   # Normalize inputs from different sources
│   └── dedup.py              # TTL-based signal deduplication (Redis)
│
├── bridge/
│   ├── __init__.py
│   ├── selfbot_reader.py     # discord.py-self — reads provider channels
│   ├── bridge_manager.py     # Manage multiple bridge accounts per provider
│   └── health_monitor.py     # Detect disconnects, alert on ban
│
├── dispatch/
│   ├── __init__.py
│   ├── ws_server.py          # WebSocket server for desktop app connections
│   ├── subscriber_mgr.py     # Track users + their channel subscriptions
│   └── fanout.py             # Route signals to subscribed WebSocket clients
│
├── auth/
│   ├── __init__.py
│   ├── license_validator.py  # Validate license key + machine fingerprint
│   ├── api_key_manager.py    # Generate/validate provider API keys
│   └── jwt_handler.py        # Issue JWTs for WebSocket auth
│
└── tests/
    ├── test_ingest.py
    ├── test_dedup.py
    ├── test_fanout.py
    └── test_bridge.py
```

### 3.2 Desktop App Changes (minimal additions to existing codebase)

```
src/relay/
├── __init__.py
├── relay_client.py           # WebSocket client — connects to cloud relay
├── relay_config.py           # Relay URL, auth token, subscriptions
└── relay_types.py            # RelaySignal dataclass

gui_app/
├── templates/signal_sources.html   # New tab in settings UI
└── static/js/signal_sources.js     # Signal source management
```

### 3.3 Provider Micro-Bot Kit (turnkey package for providers)

```
provider_kit/
├── signal_forwarder.py       # 20-line Discord bot script
├── Dockerfile                # One-command deployment
├── docker-compose.yml
├── .env.example              # BOT_TOKEN, RELAY_API_KEY, CHANNEL_IDS
└── README.md                 # Setup guide for providers (5 min)
```

---

## 4. Phase 1: Cloud Relay + Selfbot Bridge

**Timeline:** Week 1-2  
**Goal:** Deploy cloud relay, connect partner provider via selfbot bridge, first end-to-end signal flow.

### 4.1 Cloud Relay Server

#### Task 1.1: FastAPI Skeleton
- [ ] FastAPI app with CORS, health check endpoint
- [ ] Environment-based configuration (relay URL, Redis URL, license server URL)
- [ ] Docker + docker-compose setup with Redis
- [ ] Deploy to VPS (DigitalOcean/Hetzner, $10-20/mo)

#### Task 1.2: Webhook Ingest Endpoint
```
POST /api/v1/signals
Authorization: Bearer <provider_api_key>
Content-Type: application/json

{
  "content": "BTO SPY 580C 05/02 @2.50",
  "embeds": [...],
  "author": "bishop",
  "channel": "signals",
  "provider_id": "partner_xyz",
  "timestamp": "2026-04-30T10:30:00Z"
}

Response: {"status": "relayed", "signal_id": "sig_abc123", "subscribers": 42}
```
- [ ] HMAC signature validation on provider API key
- [ ] Rate limiting per provider (100 signals/min default)
- [ ] Request logging (signal_id, provider, timestamp, subscriber count)
- [ ] Accept both structured JSON and raw text (auto-detect)

#### Task 1.3: Provider Adapter Layer
- [ ] `ProviderAdapter` base class with `normalize(raw_payload) -> SignalMessage`
- [ ] `SelfbotAdapter` — normalizes discord.py-self `on_message` events
- [ ] `WebhookAdapter` — normalizes raw HTTP POST payloads
- [ ] `TradingViewAdapter` — normalizes TradingView alert format
- [ ] `SignalMessage` schema:
  ```python
  @dataclass
  class SignalMessage:
      signal_id: str          # UUID
      provider_id: str        # "partner_xyz"
      channel_name: str       # "signals"
      channel_id: str         # Discord channel ID or custom
      author: str             # Signal author name
      content: str            # Raw text content
      embeds: List[dict]      # Discord embed data (if any)
      timestamp: datetime     # Original message timestamp
      source_type: str        # "selfbot_bridge" | "webhook" | "tradingview" | "bot"
      message_hash: str       # SHA256 of content+timestamp for dedup
  ```

#### Task 1.4: Signal Deduplication
- [ ] Redis-based TTL dedup (key: `dedup:{message_hash}`, TTL: 60s)
- [ ] Cross-source dedup (same signal from selfbot + webhook only executes once)
- [ ] Dedup stats endpoint: `GET /api/v1/stats/dedup`

### 4.2 Selfbot Bridge

#### Task 1.5: Bridge Reader
- [ ] `discord.py-self` client that connects with bridge account token
- [ ] Configure channels per provider via `config.py` or environment
- [ ] `on_message` handler: filter by channel ID, normalize, POST to ingest endpoint (localhost)
- [ ] Auto-reconnect with exponential backoff on disconnect
- [ ] Log all messages read (debug) and signals forwarded (info)

#### Task 1.6: Bridge Account Management
- [ ] Store bridge account tokens encrypted (Fernet, key from env)
- [ ] Support multiple bridge accounts (one per provider, or backup accounts)
- [ ] Health check: detect `on_disconnect`, alert via webhook (Slack/Discord/email)
- [ ] Token rotation: swap to backup account on ban detection
- [ ] Account aging strategy: don't use freshly-created accounts immediately

#### Task 1.7: Ban Detection & Recovery
- [ ] Monitor for `discord.errors.LoginFailure` or connection rejection
- [ ] Alert BotifyTrades ops on ban (webhook to ops Slack channel)
- [ ] Auto-swap to backup account if available
- [ ] Log ban events with timestamp, account age, last activity
- [ ] Recovery playbook document for ops team

### 4.3 WebSocket Dispatch

#### Task 1.8: WebSocket Server
- [ ] `websockets` library server at `wss://relay.botifytrades.com/ws`
- [ ] TLS termination via nginx reverse proxy or Caddy
- [ ] Connection auth: client sends JWT on connect, server validates
- [ ] JWT contains: `license_key`, `machine_id`, `subscriptions[]`
- [ ] Ping/pong heartbeat every 30s, disconnect stale clients after 90s

#### Task 1.9: Subscriber Management
- [ ] In-memory subscriber registry: `{user_id: {ws_connection, subscriptions[]}}`
- [ ] Subscription = `{provider_id, channel_name}`
- [ ] REST endpoints for subscription management:
  ```
  GET  /api/v1/providers              # List available providers
  GET  /api/v1/providers/{id}/channels # List provider channels
  POST /api/v1/subscribe              # Subscribe to channels
  DELETE /api/v1/subscribe/{id}       # Unsubscribe
  ```
- [ ] Persist subscriptions in Redis (survive relay restart)

#### Task 1.10: Fan-Out Logic
- [ ] On signal ingest: look up all users subscribed to `{provider_id, channel_name}`
- [ ] Send `SignalMessage` JSON to each subscriber's WebSocket
- [ ] Track delivery: `delivered_to`, `failed_to` counts per signal
- [ ] Missed-signal buffer: last 50 signals per channel, replayed on reconnect
- [ ] Fan-out metrics: signals/sec, subscribers/signal, latency

### 4.4 Auth Layer

#### Task 1.11: License Validation
- [ ] Call existing license server to validate license key
- [ ] Cache validation result for 1 hour (reduce license server load)
- [ ] Machine fingerprint check (same logic as desktop app)
- [ ] Reject connections from expired/revoked licenses

#### Task 1.12: API Key Management
- [ ] Generate unique API keys per provider: `prvd_<provider_id>_<random>`
- [ ] Store hashed API keys in Redis
- [ ] Rate limit per API key
- [ ] Key rotation: generate new key, grace period for old key (24h)

---

## 5. Phase 2: Desktop App Relay Client

**Timeline:** Week 2-3  
**Goal:** Desktop app connects to cloud relay, receives signals, feeds into existing parsing pipeline.

### 5.1 Relay Client Module

#### Task 2.1: WebSocket Client (`src/relay/relay_client.py`)
```python
class RelayClient:
    def __init__(self, relay_url, license_key, machine_id, signal_queue):
        self.relay_url = relay_url          # wss://relay.botifytrades.com/ws
        self.license_key = license_key
        self.machine_id = machine_id
        self.signal_queue = signal_queue    # Same queue as selfbot/telegram
        self._ws = None
        self._running = False

    async def connect(self):
        """Connect to relay, authenticate, receive signals."""
        # 1. Get JWT from relay auth endpoint
        # 2. Connect WebSocket with JWT
        # 3. Send subscription list
        # 4. Loop: receive signals, put on signal_queue

    async def _on_signal(self, signal_json):
        """Convert relay signal to format expected by _process_message."""
        # Create a synthetic message dict matching what the parsers expect
        # Put on signal_queue for processing by existing pipeline

    async def reconnect(self):
        """Exponential backoff reconnect: 1s, 2s, 4s, 8s, max 60s."""
```
- [ ] Implement WebSocket client with `websockets` library
- [ ] JWT auth flow: `POST /api/v1/auth` with license key → get JWT → connect WS
- [ ] Signal conversion: `RelaySignal` → synthetic message dict for existing parsers
- [ ] Exponential backoff reconnect (1s → 2s → 4s → 8s → max 60s)
- [ ] Connection status tracking (connected/disconnected/reconnecting)
- [ ] Thread-safe signal queue submission (same `sync_signal_queue` as Telegram listener)

#### Task 2.2: Integration with Main Bot (`src/selfbot_webull.py`)

Insertion point: `on_ready()` handler (around line 10243).

```python
# Start relay client alongside Discord selfbot
if self.relay_config and self.relay_config.enabled:
    self.relay_client = RelayClient(
        relay_url=self.relay_config.relay_url,
        license_key=self.license_key,
        machine_id=self.machine_fingerprint,
        signal_queue=self.sync_signal_queue
    )
    asyncio.create_task(self.relay_client.connect())
    print("[RELAY] Cloud relay client started")
```
- [ ] Load relay config from database or config file
- [ ] Start relay client as asyncio task in `on_ready()`
- [ ] Relay signals go through same `_process_message()` pipeline
- [ ] Relay source tagged as `SignalSource.RELAY` in `SignalParsingPipeline`
- [ ] Dedup between relay signals and local selfbot signals (if user runs both)

#### Task 2.3: Relay Config (`src/relay/relay_config.py`)
```python
@dataclass
class RelayConfig:
    enabled: bool = False
    relay_url: str = "wss://relay.botifytrades.com/ws"
    license_key: str = ""
    machine_id: str = ""
    subscriptions: List[dict] = field(default_factory=list)  # [{provider_id, channel}]
    auto_reconnect: bool = True
    max_reconnect_delay: int = 60
```
- [ ] Load from `bot_data.db` → `relay_config` table
- [ ] Save/update from GUI settings tab
- [ ] Default: disabled (opt-in)

### 5.2 GUI Integration

#### Task 2.4: Signal Sources Settings Tab
New tab in Settings page: **Signal Sources**

Sections:
1. **Cloud Relay Connection**
   - Status indicator (connected/disconnected/reconnecting)
   - Relay URL (default: `wss://relay.botifytrades.com/ws`)
   - Enable/disable toggle
   - Personal webhook URL display (for Tier 1): `https://relay.botifytrades.com/hook/usr_{key}`

2. **Available Providers**
   - List fetched from relay: `GET /api/v1/providers`
   - Each provider shows: name, channel count, subscriber count
   - Subscribe/unsubscribe toggle per channel
   - Channel → risk settings mapping (reuses existing channel settings)

3. **Signal Sources Status**
   - Active sources: Discord selfbot, Telegram, Cloud Relay
   - Signal count per source (last 24h)
   - Last signal received timestamp per source

- [ ] HTML template: `gui_app/templates/signal_sources.html`
- [ ] JavaScript: `gui_app/static/js/signal_sources.js`
- [ ] Flask routes: `GET/POST /settings/relay` in `gui_app/routes.py`
- [ ] API routes: `GET /api/relay/status`, `POST /api/relay/subscribe`

#### Task 2.5: Dashboard Relay Status Widget
- [ ] Add relay connection status to main dashboard
- [ ] Show "Relay: Connected (3 channels)" or "Relay: Disconnected"
- [ ] Signal source breakdown in activity feed

---

## 6. Phase 3: Provider Micro-Bot Kit

**Timeline:** Week 3-4  
**Goal:** Turnkey package for providers who are willing to run their own official bot.

### 6.1 Provider Kit Package

#### Task 3.1: `signal_forwarder.py`
- [ ] 20-line script using official `discord.py` (not selfbot)
- [ ] Environment-variable config: `BOT_TOKEN`, `RELAY_API_KEY`, `CHANNEL_IDS`
- [ ] Forwards message content + embeds + author + channel to relay
- [ ] Error handling: retry POST on failure, log errors
- [ ] Tested against relay ingest endpoint

#### Task 3.2: Docker Package
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY signal_forwarder.py .
CMD ["python", "signal_forwarder.py"]
```
- [ ] Dockerfile with minimal footprint (~100MB image)
- [ ] `docker-compose.yml` with `.env` file support
- [ ] `README.md` with 5-minute setup guide
- [ ] Tested on Linux, macOS, Windows Docker Desktop

#### Task 3.3: Provider Onboarding Portal
- [ ] Web page where provider registers: name, server name, channel list
- [ ] Generates API key for the provider
- [ ] Provides bot invite URL with minimal permissions (View Channels + Read Message History)
- [ ] Downloads pre-configured `docker-compose.yml` with their API key

### 6.2 Provider Admin Dashboard

#### Task 3.4: Provider-facing Stats
- [ ] `GET /api/v1/provider/{id}/stats` — signals forwarded, subscribers, uptime
- [ ] Simple HTML dashboard for providers to see their signal delivery stats
- [ ] Alert provider if bridge/bot goes offline

---

## 7. Phase 4: Provider Marketplace + Analytics

**Timeline:** Week 5-8  
**Goal:** Signal analytics, provider discovery, selfbot deprecation.

### 7.1 Signal Analytics

#### Task 4.1: Signal Performance Tracking
- [ ] Track per-signal: provider, channel, symbol, action, timestamp
- [ ] Track per-signal: how many users received, how many executed, fill rate
- [ ] Provider channel leaderboard: win rate, average P&L, signal frequency
- [ ] User-facing analytics tab in desktop app

#### Task 4.2: Provider Marketplace
- [ ] Browse available providers in desktop app
- [ ] Provider profiles: description, track record, channel list, subscriber count
- [ ] One-click subscribe to provider channels
- [ ] Rating/review system (after using provider for 30+ days)

### 7.2 Selfbot Deprecation

#### Task 4.3: Migration Wizard
- [ ] Detect if user currently uses Discord selfbot
- [ ] Show migration prompt: "Switch to Cloud Relay — safer, easier, same signals"
- [ ] Auto-map existing channel IDs to relay provider channels
- [ ] Allow running both selfbot + relay in parallel during transition
- [ ] After 30 days, prompt to disable selfbot entirely

#### Task 4.4: Telegram Relay
- [ ] Extend cloud relay to accept Telegram signals (same pattern as Discord bridge)
- [ ] Telegram bot relay (official Telegram Bot API) — providers add bot to their group
- [ ] Normalize Telegram messages through same adapter layer

---

## 8. API Specification

### 8.1 Relay Server REST API

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/v1/signals` | Provider API key | Ingest a signal |
| `POST` | `/api/v1/auth` | License key | Get JWT for WebSocket |
| `GET` | `/api/v1/providers` | JWT | List available providers |
| `GET` | `/api/v1/providers/{id}/channels` | JWT | List provider channels |
| `POST` | `/api/v1/subscribe` | JWT | Subscribe to channel(s) |
| `DELETE` | `/api/v1/subscribe/{id}` | JWT | Unsubscribe from channel |
| `GET` | `/api/v1/stats` | JWT | User's signal stats |
| `GET` | `/api/v1/provider/{id}/stats` | Provider API key | Provider's delivery stats |
| `GET` | `/health` | None | Health check |

### 8.2 WebSocket Protocol

**Connection:**
```
wss://relay.botifytrades.com/ws?token=<JWT>
```

**Server → Client (signal delivery):**
```json
{
  "type": "signal",
  "signal_id": "sig_abc123",
  "provider_id": "partner_xyz",
  "channel": "signals",
  "author": "bishop",
  "content": "BTO SPY 580C 05/02 @2.50",
  "embeds": [],
  "timestamp": "2026-04-30T10:30:00Z",
  "source_type": "selfbot_bridge"
}
```

**Server → Client (status):**
```json
{
  "type": "status",
  "providers_online": ["partner_xyz", "phoenix"],
  "providers_offline": [],
  "your_subscriptions": 5,
  "connected_users": 342
}
```

**Client → Server (subscribe):**
```json
{
  "type": "subscribe",
  "provider_id": "partner_xyz",
  "channels": ["signals", "options-0dte"]
}
```

**Heartbeat:**
```json
{"type": "ping"}  →  {"type": "pong"}
```

### 8.3 Signal Ingest Payload (Tier 1 — Webhook)

**Structured format:**
```json
{
  "action": "BTO",
  "symbol": "SPY",
  "strike": 580,
  "expiry": "2026-05-02",
  "opt_type": "C",
  "price": 2.50,
  "source": "tradingview",
  "channel": "my-alerts"
}
```

**Raw text format (auto-detected):**
```json
{
  "content": "BTO SPY 580C 05/02 @2.50",
  "channel": "my-alerts"
}
```

**TradingView format:**
```json
{
  "ticker": "SPY",
  "action": "buy",
  "price": "{{close}}",
  "message": "BTO SPY 580C 05/02"
}
```

---

## 9. Database Schema Changes

### 9.1 Desktop App (`bot_data.db`)

**New table: `relay_config`**
```sql
CREATE TABLE IF NOT EXISTS relay_config (
    id INTEGER PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    relay_url TEXT DEFAULT 'wss://relay.botifytrades.com/ws',
    jwt_token TEXT,
    jwt_expires_at TEXT,
    last_connected_at TEXT,
    auto_reconnect INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

**New table: `relay_subscriptions`**
```sql
CREATE TABLE IF NOT EXISTS relay_subscriptions (
    id INTEGER PRIMARY KEY,
    provider_id TEXT NOT NULL,
    provider_name TEXT,
    channel_name TEXT NOT NULL,
    channel_settings_id INTEGER,          -- FK to channel_risk_settings
    enabled INTEGER DEFAULT 1,
    subscribed_at TEXT DEFAULT (datetime('now')),
    UNIQUE(provider_id, channel_name)
);
```

**Modify `signal_routing_mappings`:**
```sql
ALTER TABLE signal_routing_mappings ADD COLUMN source_type TEXT DEFAULT 'discord';
ALTER TABLE signal_routing_mappings ADD COLUMN relay_provider_id TEXT;
```

### 9.2 Cloud Relay (Redis)

```
# Dedup cache
dedup:{message_hash}         → "1"                     TTL 60s

# Subscriber registry
subscribers:{user_id}        → {ws_id, subscriptions}  TTL on disconnect

# Provider state
provider:{provider_id}:state → "online" | "offline"    No TTL
provider:{provider_id}:stats → {signals_today, ...}    TTL 24h

# Missed-signal buffer
signals:{provider_id}:{channel} → [last 50 signals]    TTL 1h

# API key validation cache
apikey:{hash}                → provider_id              TTL 1h

# License validation cache
license:{license_key}        → {valid, expires_at}      TTL 1h
```

---

## 10. Security Model

### 10.1 What Never Leaves the Desktop

| Data | Location | Encryption |
|------|----------|------------|
| Broker API keys/tokens | `bot_data.db` | AES-256 + Windows DPAPI / macOS Keychain |
| Schwab OAuth tokens | `schwab_tokens.enc` | AES-256 + machine-specific key |
| Position cache | `.position_cache.json` | Plaintext (local only) |
| Trade history | `bot_data.db` | Plaintext (local only) |
| Risk settings | `bot_data.db` | Plaintext (local only) |

### 10.2 What the Cloud Relay Sees

| Data | Purpose | Retention |
|------|---------|-----------|
| Raw signal text | Route to subscribers | 60 seconds (dedup TTL) |
| Provider ID + channel | Routing | Session-duration |
| License key hash | Auth | Cached 1 hour |
| Machine fingerprint | Auth | Not stored (validated then discarded) |
| WebSocket connection metadata | Routing | Session-duration |

### 10.3 What the Cloud Relay Never Sees

- Broker credentials (API keys, tokens, passwords)
- User positions or P&L
- Order history
- Risk settings or channel configurations
- Personal information beyond license key

### 10.4 Transport Security

- WebSocket: TLS 1.3 (wss://)
- REST API: HTTPS only (TLS 1.2+)
- Provider API keys: HMAC-SHA256 signed
- JWTs: RS256 signed, 24h expiry, include machine fingerprint claim
- Redis: password-protected, localhost-only binding

---

## 11. Infrastructure & Deployment

### 11.1 Cloud Relay Server

**Minimum viable deployment:**
```
1x VPS (DigitalOcean/Hetzner)
├── 2 vCPU, 4GB RAM, 80GB SSD
├── Ubuntu 22.04
├── Docker + docker-compose
├── nginx (TLS termination, reverse proxy)
├── Let's Encrypt SSL certificate
└── Cost: ~$20/month
```

**Services:**
```yaml
# docker-compose.yml
services:
  relay:
    build: .
    ports:
      - "8080:8080"     # HTTP/WS (behind nginx)
    environment:
      - REDIS_URL=redis://redis:6379
      - LICENSE_SERVER_URL=https://license.botifytrades.com
      - BRIDGE_TOKENS_ENC_KEY=${BRIDGE_KEY}
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data

  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./certs:/etc/letsencrypt
```

### 11.2 Domain & DNS

```
relay.botifytrades.com    → VPS IP (A record)
api.botifytrades.com      → same VPS or separate (CNAME)
```

### 11.3 Monitoring

- **Uptime:** UptimeRobot or similar on `https://relay.botifytrades.com/health`
- **Metrics:** Prometheus endpoint at `/metrics` (signals/sec, connections, latency)
- **Alerts:** Webhook to Slack/Discord on: relay down, bridge disconnected, error rate spike
- **Logs:** Structured JSON logging, rotated daily, 30-day retention

---

## 12. Failure Modes & Recovery

| Failure | Impact | Detection | Recovery | Downtime |
|---------|--------|-----------|----------|----------|
| Selfbot account banned | Signals from that provider stop | `LoginFailure` exception | Swap to backup account, provider re-adds | 5-30 min |
| Relay server crash | All relay signals stop | Health check fails | Docker auto-restart (restart: always) | <1 min |
| Redis crash | Dedup + subscriptions lost | Health check | Redis auto-restart, clients reconnect | <1 min |
| User WebSocket disconnects | User misses signals | Client-side detection | Auto-reconnect with backoff, replay buffer | 1-10s |
| Provider changes channel structure | Signals not detected | No signals from channel for N minutes | Alert ops, update channel config | Manual |
| TLS cert expires | All connections fail | Cert monitoring | Auto-renew via Certbot/Let's Encrypt | 0 (auto) |
| VPS goes down | Everything stops | UptimeRobot alert | Backup VPS with same Docker setup | 5-15 min |

### Key Resilience Property
When the cloud relay is down, **existing positions and risk management continue running locally** on all user desktop apps. SL/PT/OCO brackets are already placed at the broker. Only new signal ingestion pauses.

---

## 13. Migration Path

### For Existing Users (selfbot → relay)

```
Phase 1: Both modes available
├── User can run selfbot AND relay simultaneously
├── Cross-source dedup prevents double execution
└── User sees signal source in activity feed

Phase 2: Relay recommended
├── Settings shows "Recommended: Cloud Relay" badge
├── Migration wizard maps existing channel IDs to relay providers
└── Selfbot mode labeled "Legacy (Advanced)"

Phase 3: Selfbot deprecated
├── Selfbot hidden behind "Advanced" toggle
├── New users never see selfbot option
└── Existing selfbot users get periodic migration prompts
```

### For the Partner Provider (current → bridge)

```
Step 1: BotifyTrades creates dedicated Discord account
Step 2: Provider admin adds account to their server (2 clicks)
Step 3: Cloud relay connects selfbot bridge
Step 4: All users subscribed to provider receive signals via relay
Step 5: Users disable their personal selfbots for this provider
```

### For Future Providers (micro-bot)

```
Step 1: Provider clicks invite link on BotifyTrades website
Step 2: Provider selects signal channels in portal
Step 3: Provider downloads pre-configured docker-compose.yml
Step 4: Provider runs: docker-compose up -d
Step 5: Provider's channels appear in user catalog
```

---

## 14. Cost Analysis

### Cloud Relay Infrastructure

| Component | Cost/month | Notes |
|-----------|-----------|-------|
| VPS (2 vCPU, 4GB RAM) | $20 | Handles 1000+ concurrent WebSocket connections |
| Domain (relay.botifytrades.com) | $0 | Subdomain of existing domain |
| Redis | $0 | Runs on same VPS |
| SSL Certificate | $0 | Let's Encrypt |
| Monitoring (UptimeRobot) | $0 | Free tier sufficient |
| **Total** | **$20/mo** | |

### Scaling Costs (future)

| Users | VPS Spec | Cost/month |
|-------|----------|-----------|
| 1-500 | 2 vCPU / 4GB | $20 |
| 500-2000 | 4 vCPU / 8GB | $40 |
| 2000-5000 | 8 vCPU / 16GB | $80 |
| 5000+ | Load-balanced cluster | $200+ |

### Break-even
At $20/month infrastructure cost, even a single paying user covers the relay server cost.

---

## 15. Testing Strategy

### 15.1 Unit Tests

```
tests/relay/
├── test_relay_client.py       # WebSocket client connect/reconnect/auth
├── test_signal_conversion.py  # RelaySignal → _process_message format
├── test_dedup_crosssource.py  # Relay + selfbot dedup
└── test_relay_config.py       # Config load/save from DB
```

### 15.2 Integration Tests

| Test | What it validates |
|------|-------------------|
| Bridge → Relay → WebSocket → Client | End-to-end signal flow |
| Webhook POST → Relay → Client | Tier 1 webhook flow |
| Auth failure → reject | License validation |
| Bridge disconnect → reconnect | Resilience |
| Duplicate signal → single execution | Cross-source dedup |
| 100 concurrent clients | Fan-out performance |

### 15.3 End-to-End Acceptance Tests

1. **Signal flow:** Provider posts in Discord → bridge reads → relay fans out → desktop app parses → order appears in queue
2. **Webhook flow:** POST to `/api/v1/signals` → relay fans out → desktop app receives
3. **Reconnection:** Kill relay server → desktop app reconnects automatically → signals resume
4. **Ban recovery:** Simulate bridge ban → backup account activates → signals resume
5. **Cross-source dedup:** Same signal via selfbot + relay → executes only once

### 15.4 Load Testing

- Tool: `locust` or `k6`
- Target: 1000 concurrent WebSocket connections, 10 signals/second fan-out
- Measure: latency p50/p95/p99, memory usage, CPU usage

---

## 16. Open Questions

### Must Resolve Before Phase 1

1. **VPS provider:** DigitalOcean vs Hetzner vs Vultr — which region minimizes latency to US market hours users?
2. **Bridge account setup:** Who creates the dedicated Discord account? BotifyTrades ops or the provider?
3. **Relay URL:** `relay.botifytrades.com` or `api.botifytrades.com/relay`?
4. **Signal parsing location:** Parse on relay server (pre-parsed signals to clients) or parse on client (raw signals to clients)?
   - **Recommendation:** Parse on client. Keeps relay stateless and dumb. Client already has the full parsing pipeline.

### Can Decide During Implementation

5. **Redis persistence:** RDB snapshots or AOF? Subscriptions should survive restart.
6. **Missed-signal buffer size:** 50 signals per channel? 100? Configurable?
7. **JWT expiry:** 24 hours? 7 days? Shorter = more secure, longer = fewer re-auths.
8. **Multiple relay servers:** Need load balancing eventually? Not for v1.

### Future Considerations

9. **Mobile app:** Could a mobile client connect to the same relay for signal notifications?
10. **Signal marketplace monetization:** Revenue share with providers? Commission per subscriber?
11. **White-label:** Can providers run their own relay for their subscribers?

---

## Appendix A: Existing Codebase Integration Points

| File | Line(s) | Integration Point |
|------|---------|-------------------|
| `src/selfbot_webull.py` | 10243-10375 | `on_ready()` — start relay client here |
| `src/selfbot_webull.py` | 11426-11625 | `_process_message()` — relay signals enter here |
| `src/services/signal_parsing_pipeline.py` | 1-50 | `SignalSource` enum — add `RELAY` variant |
| `src/services/signal_parsing_pipeline.py` | 52-80 | `ParsedSignal` dataclass — relay signals must match this |
| `src/services/signal_routing_engine.py` | 79 | `RoutingMappingConfig.destination_url` — could point to relay |
| `src/telegram_client/listener.py` | all | Pattern to follow for relay client (external source → queue) |
| `gui_app/database.py` | 1711-1756 | `signal_routing_mappings` table — add `source_type` column |
| `gui_app/routes.py` | various | Add `/settings/relay` routes |
| `gui_app/templates/settings.html` | tab list | Add "Signal Sources" tab |

## Appendix B: Latency Budget

```
Target: Signal → Order < 200ms (excluding broker fill time)

Budget breakdown:
  Discord Gateway → Bridge selfbot on_message:     50ms
  Bridge → Relay ingest (localhost):                 1ms
  Relay parse + dedup + lookup:                      5ms
  Relay → WebSocket to user (network):           20-80ms
  User app receive + parse + queue:                 10ms
  Order placement to broker API:                   ~50ms
  ─────────────────────────────────────────────────────
  Total:                                       136-196ms  ✅ Under 200ms

  Broker fill time (not in our control):       100-500ms
```

## Appendix C: Provider Onboarding Checklist

- [ ] Provider agrees to participate
- [ ] Decide approach: A (cloud bridge), B (provider-hosted), or C (micro-bot)
- [ ] For approach A: Provider adds bridge account to their server
- [ ] For approach B: Provider receives Docker package + API key
- [ ] For approach C: Provider creates bot at discord.com/developers, receives script
- [ ] Configure channel list in relay server
- [ ] Test end-to-end signal flow with test message
- [ ] Provider appears in user catalog
- [ ] Monitor first 24h of live signals
- [ ] Confirm signal format compatibility with parsing pipeline
