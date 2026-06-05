# BotifyTrades Mobile App Architecture

## Overview

Mobile companion app for the BotifyTrades desktop bot. The domain **botifytrades.com** acts as a lightweight relay hub — it authenticates users and bridges the mobile app to the user's desktop bot. All trading stays local on the user's machine. No broker credentials ever leave the desktop.

```
┌──────────────┐       WebSocket        ┌─────────────────────┐       Push / WS       ┌──────────────┐
│  Desktop Bot │ ◄────────────────────► │  botifytrades.com   │ ◄──────────────────► │  Mobile App  │
│  (user PC)   │   outbound WSS :443    │  (Relay Server)     │   HTTPS + WSS        │  (phone)     │
│              │                        │                     │                       │              │
│ • Brokers    │   status/positions ──► │ • Auth (JWT)        │ ◄── commands          │ • Dashboard  │
│ • Risk       │   ◄── commands         │ • WS Relay          │ ──► status/alerts     │ • Positions  │
│ • Trades     │   alerts ──►           │ • Push (FCM/APNS)   │                       │ • Controls   │
│ • Signals    │                        │ • Bot Registry      │                       │ • Alerts     │
└──────────────┘                        └─────────────────────┘                       └──────────────┘
```

**Key principle**: botifytrades.com is a relay, not a SaaS. It never sees broker credentials, never executes trades, never stores positions long-term. It's a dumb pipe with authentication.

---

## 1. Domain Relay Server (botifytrades.com)

### Tech Stack
| Component | Technology | Why |
|-----------|-----------|-----|
| Runtime | Node.js or Python (FastAPI) | WebSocket-native, async |
| WebSocket | Socket.IO or native WS | Reliable reconnection, rooms |
| Auth | JWT + refresh tokens | Stateless, works for both bot and mobile |
| Database | PostgreSQL | User accounts, bot registrations, device tokens |
| Push | Firebase Cloud Messaging (FCM) + APNS | Cross-platform push notifications |
| Hosting | Hostinger VPS / DigitalOcean / Railway | Your domain, your control |
| SSL | Let's Encrypt / Cloudflare | WSS requires TLS |

### API Endpoints

```
POST   /api/auth/register          # User registration (email, password)
POST   /api/auth/login             # User login → JWT + refresh token
POST   /api/auth/refresh           # Refresh JWT
POST   /api/auth/forgot-password   # Password reset

POST   /api/bot/register           # Desktop bot registers (returns pairing_code)
POST   /api/bot/pair               # Mobile enters pairing_code to link
GET    /api/bot/status             # Get bot online/offline status
DELETE /api/bot/unpair             # Unlink a bot

POST   /api/devices/register       # Register mobile device for push notifications
DELETE /api/devices/:id            # Unregister device

WSS    /ws/bot                     # Desktop bot WebSocket connection
WSS    /ws/mobile                  # Mobile app WebSocket connection
```

### WebSocket Protocol

**Bot → Server (upstream)**
```json
{"type": "heartbeat", "ts": 1716000000}
{"type": "status", "data": {"brokers": [...], "positions": 5, "pnl": 234.50, "risk_active": true}}
{"type": "positions", "data": [{"symbol": "AAPL", "qty": 10, "entry": 185.50, "current": 187.20, "pnl": 17.00, "broker": "SCHWAB"}]}
{"type": "alert", "data": {"level": "info", "msg": "SL triggered AAPL -$23.00", "ts": 1716000000}}
{"type": "trade", "data": {"action": "BTO", "symbol": "SPY 450C", "qty": 2, "price": 3.50, "broker": "SCHWAB"}}
{"type": "conditional_orders", "data": [{"id": 55, "symbol": "OSG", "trigger": 5.00, "current": 4.80, "direction": "ABOVE"}]}
```

**Server → Bot (downstream commands from mobile)**
```json
{"type": "command", "action": "pause_trading"}
{"type": "command", "action": "resume_trading"}
{"type": "command", "action": "close_position", "data": {"symbol": "AAPL", "broker": "SCHWAB"}}
{"type": "command", "action": "close_all"}
{"type": "command", "action": "cancel_conditional", "data": {"order_id": 55}}
{"type": "command", "action": "request_status"}
{"type": "command", "action": "request_positions"}
```

**Server → Mobile (downstream)**
```json
{"type": "bot_status", "online": true, "data": {...}}
{"type": "positions_update", "data": [...]}
{"type": "alert", "data": {"level": "warning", "msg": "Daily loss limit 80% reached"}}
{"type": "trade_notification", "data": {"action": "STC", "symbol": "SPY", "pnl": 45.00}}
{"type": "command_ack", "action": "pause_trading", "success": true}
```

### Server Data Model

```sql
-- Users table
CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) UNIQUE NOT NULL,
    password    VARCHAR(255) NOT NULL,  -- bcrypt hash
    name        VARCHAR(100),
    created_at  TIMESTAMP DEFAULT NOW(),
    plan        VARCHAR(20) DEFAULT 'free'  -- free, pro (for future)
);

-- Bot registrations (one user can have multiple bots)
CREATE TABLE bots (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER REFERENCES users(id),
    bot_token     VARCHAR(64) UNIQUE NOT NULL,  -- API key for bot auth
    pairing_code  VARCHAR(8),                    -- 6-digit code, expires in 10min
    pairing_exp   TIMESTAMP,
    name          VARCHAR(100) DEFAULT 'My Bot',
    last_seen     TIMESTAMP,
    is_online     BOOLEAN DEFAULT FALSE,
    version       VARCHAR(20),
    created_at    TIMESTAMP DEFAULT NOW()
);

-- Mobile devices for push notifications
CREATE TABLE devices (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id),
    platform    VARCHAR(10) NOT NULL,  -- ios, android
    push_token  TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Alert preferences
CREATE TABLE alert_prefs (
    user_id         INTEGER REFERENCES users(id) PRIMARY KEY,
    trade_fills     BOOLEAN DEFAULT TRUE,
    risk_exits      BOOLEAN DEFAULT TRUE,
    daily_pnl       BOOLEAN DEFAULT TRUE,
    bot_disconnect  BOOLEAN DEFAULT TRUE,
    price_alerts    BOOLEAN DEFAULT TRUE
);
```

### Server Security

- **No broker credentials** stored or transmitted through the server
- **No trade data persisted** — server is stateless relay, positions are in-memory per session
- **Bot token** is generated on the server, stored in desktop bot's local config
- **End-to-end optional**: messages can be encrypted with a shared key between bot and mobile (server can't read)
- **Rate limiting**: 100 commands/min per user, 10 close_position/min
- **IP allowlist** optional for bot connections

---

## 2. Desktop Bot Integration

### New Module: `src/services/relay_client.py`

The desktop bot adds a WebSocket client that connects outbound to botifytrades.com. Since it's outbound, it works behind NAT, firewalls, and routers without port forwarding.

```
Desktop Bot Architecture (existing + new)
─────────────────────────────────────────
┌─────────────────────────────────────────────────────┐
│ Desktop Bot (selfbot_webull.py)                     │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐ │
│  │ Brokers  │  │ Risk     │  │ Relay Client  NEW │ │
│  │ (Schwab, │  │ Engine   │  │                   │ │
│  │  IBKR..) │  │          │  │ • WSS outbound    │ │
│  └────┬─────┘  └────┬─────┘  │ • Sends status    │ │
│       │              │        │ • Receives cmds   │ │
│       │              │        │ • Auto-reconnect  │ │
│  ┌────┴──────────────┴───┐    │ • Heartbeat 30s   │ │
│  │  Position Monitor     │    └─────────┬─────────┘ │
│  │  Conditional Orders   │              │           │
│  │  Flask GUI            │◄─────────────┘           │
│  └───────────────────────┘   (reads same state)     │
└─────────────────────────────────────────────────────┘
```

### Relay Client Features

| Feature | Interval | Details |
|---------|----------|---------|
| Heartbeat | 30s | Keeps connection alive, server marks bot online/offline |
| Status push | 15s | Broker connections, position count, daily P&L, risk state |
| Position sync | 5s (if open) | Full position list with live P&L (only when positions exist) |
| Trade alerts | Instant | On every fill, exit, SL/PT trigger — also fires push notification |
| Conditional orders | 15s | Active conditional order list with current prices |
| Command handling | Instant | Pause/resume, close position, cancel orders |

### Pairing Flow

```
1. User creates account on botifytrades.com (web or mobile)
2. User clicks "Add Bot" → server generates a bot_token
3. User enters bot_token in desktop bot Settings → Remote Access
4. Desktop bot connects to wss://botifytrades.com/ws/bot?token=xxx
5. Server validates token, marks bot online
6. Mobile app shows bot as connected
```

Alternative easy pairing:
```
1. Desktop bot shows 6-digit pairing code on GUI (valid 10 min)
2. User opens mobile app → "Add Bot" → enters 6-digit code
3. Server links mobile device to bot
4. Done — no token copy-paste needed
```

### Settings UI Addition (Desktop Bot)

New section in Settings → Remote Access:
```
┌─────────────────────────────────────────────┐
│  📱 Remote Access                           │
│                                             │
│  Status: 🟢 Connected to botifytrades.com  │
│  Bot ID: BTF-a8x92k                        │
│  Mobile devices: 1 paired                  │
│                                             │
│  [Generate Pairing Code]  [Disconnect]     │
│                                             │
│  ☑ Send trade notifications                │
│  ☑ Send risk alerts                        │
│  ☑ Allow remote pause/resume               │
│  ☐ Allow remote position close             │
│  ☐ Allow remote close all                  │
│                                             │
│  Permissions control what mobile can do.   │
│  Close/CloseAll disabled by default.       │
└─────────────────────────────────────────────┘
```

---

## 3. Mobile App

### Tech Stack
| Component | Choice | Why |
|-----------|--------|-----|
| Framework | **Flutter** | Single codebase → iOS + Android, fast dev, good WS support |
| State | Riverpod | Reactive, handles WebSocket streams well |
| WebSocket | `web_socket_channel` | Dart-native, auto-reconnect |
| Push | `firebase_messaging` | FCM for Android, APNS via FCM for iOS |
| Auth | JWT stored in secure storage | `flutter_secure_storage` |
| Charts | `fl_chart` | Lightweight P&L charts |
| Local DB | Hive or Isar | Cache positions/alerts offline |

### App Screens

```
📱 BotifyTrades Mobile
│
├── 🔐 Login / Register
│
├── 🏠 Dashboard
│   ├── Bot status (online/offline dot)
│   ├── Daily P&L card (big number, +/- color)
│   ├── Open positions count
│   ├── Active brokers badges
│   ├── Risk status (active/paused/halted)
│   └── Quick actions: [Pause] [Resume]
│
├── 📊 Positions
│   ├── List of open positions
│   │   ├── Symbol, qty, entry, current, P&L, broker
│   │   ├── SL/PT levels shown as progress bar
│   │   └── [Close] button (if permitted)
│   ├── Pull-to-refresh
│   └── Auto-updates via WebSocket
│
├── ⏱️ Conditional Orders
│   ├── Active orders with trigger/current/distance
│   ├── [Cancel] button
│   └── Price progress bar
│
├── 📜 Trade History (today)
│   ├── Recent fills with P&L
│   ├── Filter by broker
│   └── Running total
│
├── 🔔 Alerts
│   ├── Trade fills (BTO/STC with P&L)
│   ├── Risk events (SL hit, daily limit, halt)
│   ├── Bot disconnect/reconnect
│   └── Mark as read / clear
│
├── ⚙️ Settings
│   ├── Notification preferences
│   ├── Bot management (pair/unpair)
│   ├── Account settings
│   └── Dark/light theme
│
└── ❌ Close All (confirmation dialog, if permitted)
```

### Push Notification Categories

| Category | Priority | Example |
|----------|----------|---------|
| Trade Fill | High | "BTO AAPL 185C x5 @ $3.50 via Schwab" |
| Position Exit | High | "STC AAPL 185C — SL triggered, P&L: -$120" |
| Risk Alert | Critical | "Daily loss limit reached — trading paused" |
| Bot Offline | Medium | "Your bot disconnected at 10:32 AM" |
| Bot Online | Low | "Your bot is back online" |
| Conditional Trigger | High | "Conditional order #55 OSG triggered at $5.02" |
| Daily Summary | Low | "Daily P&L: +$345 (8 trades, 75% win rate)" — sent at market close |

---

## 4. Data Flow Examples

### Example 1: User checks positions on phone

```
Mobile App                    botifytrades.com               Desktop Bot
    │                              │                              │
    │──── WSS connect ────────────►│                              │
    │     (JWT auth)               │                              │
    │                              │◄──── WSS already connected ──│
    │                              │                              │
    │──── request_positions ──────►│                              │
    │                              │──── command: request_pos ───►│
    │                              │                              │
    │                              │◄──── positions data ─────────│
    │◄──── positions_update ───────│                              │
    │     (renders list)           │                              │
```

### Example 2: SL triggered → push notification

```
Desktop Bot                   botifytrades.com               Mobile App
    │                              │                              │
    │ (SL triggers locally)        │                              │
    │                              │                              │
    │──── alert: SL AAPL -$120 ──►│                              │
    │                              │──── push notification ──────►│ (phone buzzes)
    │                              │──── WSS alert ─────────────►│ (if app open)
    │                              │                              │
    │──── updated positions ──────►│                              │
    │                              │──── positions_update ──────►│
```

### Example 3: User closes position from phone

```
Mobile App                    botifytrades.com               Desktop Bot
    │                              │                              │
    │──── close_position ─────────►│                              │
    │     {symbol: AAPL,           │                              │
    │      broker: SCHWAB}         │                              │
    │                              │──── command: close_pos ─────►│
    │                              │                              │
    │                              │     (bot executes locally)   │
    │                              │                              │
    │                              │◄──── command_ack: success ───│
    │◄──── command_ack ────────────│                              │
    │                              │                              │
    │                              │◄──── trade: STC AAPL +$45 ──│
    │◄──── trade_notification ─────│                              │
```

---

## 5. Security Model

```
What botifytrades.com KNOWS          What it NEVER sees
──────────────────────────────       ──────────────────────────────
✓ User email + hashed password       ✗ Broker credentials
✓ Bot online/offline status          ✗ Broker API keys/tokens
✓ Bot version                        ✗ Discord token
✓ Device push tokens                 ✗ Account numbers
✓ Relay messages (transient)         ✗ Full trade history (permanent)
                                     ✗ Position sizes / account balance
                                       (only transient in WebSocket relay)
```

### Optional End-to-End Encryption

For users who want extra privacy, the bot and mobile app can share an encryption key (set during pairing). All WebSocket message payloads are AES-256-GCM encrypted — the server relays encrypted blobs it cannot read.

```
Pairing generates: shared_key (shown as QR code or 32-char key)
Bot encrypts:      AES-256-GCM(payload, shared_key) → server relays blob
Mobile decrypts:   AES-256-GCM(blob, shared_key) → readable data
Server sees:       {"type": "encrypted", "data": "base64blob..."}
```

---

## 6. Implementation Phases

### Phase 1: Relay Server + Desktop Integration (2-3 weeks)
- [ ] User registration/login API on botifytrades.com
- [ ] WebSocket relay server (Node.js or FastAPI)
- [ ] Bot registration + pairing code flow
- [ ] `relay_client.py` module in desktop bot
- [ ] Status + heartbeat push from bot
- [ ] Settings UI for Remote Access in desktop bot
- [ ] Basic web dashboard at botifytrades.com/dashboard (test before mobile)

### Phase 2: Mobile App MVP (3-4 weeks)
- [ ] Flutter project setup (iOS + Android)
- [ ] Login/register screens
- [ ] Bot pairing flow (enter code)
- [ ] Dashboard screen (P&L, status, broker badges)
- [ ] Positions list (real-time via WebSocket)
- [ ] Push notifications (FCM/APNS) for trade fills + risk alerts
- [ ] Pause/resume trading command

### Phase 3: Full Mobile + Polish (2-3 weeks)
- [ ] Conditional orders screen
- [ ] Trade history (today's trades)
- [ ] Close position from mobile (with confirmation)
- [ ] Alert inbox with read/unread
- [ ] Daily P&L summary push at market close
- [ ] Bot disconnect/reconnect alerts
- [ ] Settings: notification preferences, theme
- [ ] App Store + Play Store submission

### Phase 4: Enhancements (ongoing)
- [ ] Multi-bot support (user has bots on multiple machines)
- [ ] End-to-end encryption option
- [ ] P&L charts (daily/weekly/monthly)
- [ ] Apple Watch / WearOS complication (P&L glance)
- [ ] Widget for home screen (daily P&L)
- [ ] Biometric lock (Face ID / fingerprint)

---

## 7. Server Cost Estimate

| Component | Cost/month | Notes |
|-----------|-----------|-------|
| VPS (relay server) | $5-12 | DigitalOcean/Hostinger, 1 vCPU is enough for <500 users |
| Domain (already owned) | $0 | botifytrades.com |
| SSL | $0 | Let's Encrypt / Cloudflare |
| Firebase (push) | $0 | Free tier: 500k notifications/day |
| PostgreSQL | $0 | Runs on same VPS |
| Apple Developer | $99/year | Required for App Store |
| Google Play | $25 one-time | Required for Play Store |
| **Total** | **~$15/month** | Scales to hundreds of users |

The relay architecture is extremely cheap to operate because the server does no computation — it just authenticates and forwards WebSocket messages.

---

## 8. Desktop Bot Code Changes Required

### New files
```
src/services/relay_client.py       # WebSocket client to botifytrades.com (~400 lines)
gui_app/templates/remote.html      # Settings UI for Remote Access
```

### Modified files
```
src/selfbot_webull.py              # Initialize relay_client on startup
gui_app/routes.py                  # API endpoints for pairing, status
src/risk/position_monitor.py       # Emit trade/risk events to relay
src/services/conditional_orders/   # Emit conditional order updates
```

### relay_client.py Skeleton

```python
class RelayClient:
    def __init__(self, bot_token: str, server_url: str = "wss://botifytrades.com/ws/bot"):
        self._token = bot_token
        self._url = server_url
        self._ws = None
        self._connected = False
        self._permissions = {
            'send_trades': True,
            'send_alerts': True,
            'allow_pause': True,
            'allow_close': False,      # Disabled by default
            'allow_close_all': False,  # Disabled by default
        }

    async def connect(self): ...
    async def _heartbeat_loop(self): ...
    async def send_status(self, status: dict): ...
    async def send_positions(self, positions: list): ...
    async def send_alert(self, alert: dict): ...
    async def send_trade(self, trade: dict): ...
    async def _handle_command(self, msg: dict): ...
    async def _on_disconnect(self): ...
```

---

## Summary

| Aspect | Decision |
|--------|----------|
| Architecture | Hub-and-spoke relay (not SaaS) |
| Server role | Auth + WebSocket relay only |
| Trading execution | 100% on desktop bot (local) |
| Broker credentials | Never leave desktop |
| Mobile framework | Flutter (iOS + Android) |
| Server tech | Node.js or FastAPI + PostgreSQL |
| Push notifications | FCM + APNS |
| Pairing | 6-digit code or bot token |
| Security | JWT auth, optional E2E encryption |
| Cost | ~$15/month server |
| Timeline | ~8-10 weeks to full mobile app |
