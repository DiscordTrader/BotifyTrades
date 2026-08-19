<p align="center">
  <img src="https://img.shields.io/badge/BotifyTrades-v16.1.8-blueviolet?style=for-the-badge&logo=bitcoin&logoColor=white" alt="Version"/>
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Brokers-7-green?style=for-the-badge&logo=tradingview&logoColor=white" alt="Brokers"/>
  <img src="https://img.shields.io/badge/Signal_Parsers-188+-orange?style=for-the-badge&logo=regex&logoColor=white" alt="Parsers"/>
  <img src="https://img.shields.io/badge/Lines_of_Code-300K-red?style=for-the-badge&logo=codacy&logoColor=white" alt="LOC"/>
</p>

<h1 align="center">BotifyTrades</h1>

<p align="center">
  <strong>AI-Powered Multi-Broker Trade Execution Engine</strong><br/>
  <em>Decode any signal. Arm every broker. Execute in milliseconds.</em>
</p>

<p align="center">
  <a href="#-quick-start">Quick Start</a> &bull;
  <a href="#-features">Features</a> &bull;
  <a href="#-supported-brokers">Brokers</a> &bull;
  <a href="#-signal-detection">Signal Detection</a> &bull;
  <a href="#-risk-engine">Risk Engine</a> &bull;
  <a href="#-architecture">Architecture</a>
</p>

---

> **A trading bot that monitors Discord & Telegram for signals and auto-executes across 7 brokers simultaneously** &mdash; with 188 regex parsers, triple-AI fallback, real-time streaming, and an institutional-grade risk engine that runs 300,000 lines of production Python.

```
Discord/Telegram Signal ──> 188 Regex Parsers ──> Risk Engine ──> 7 Brokers (simultaneous)
         │                         │                    │               │
         │                    No match?             4-tier PT       Schwab, Webull
         │                         │               Dynamic SL      Alpaca, IBKR
         └── AI Fallback ──────────┘               Trailing        Tastytrade
             (Claude/GPT/Gemini)                   EMA-gated       Robinhood (Agentic MCP)
                                                   Per-author      Trading212, Questrade
                                                                   
```

---

## Why BotifyTrades?

Most trading bots parse one format from one channel into one broker. **BotifyTrades parses any format from any channel into every broker** &mdash; simultaneously.

| Problem | BotifyTrades Solution |
|---|---|
| Signal providers all use different formats | 188 regex parsers + AI fallback that learns new formats |
| Manual copy-paste loses seconds on entries | Sub-second execution across all 7 brokers at once |
| One broker goes down, you miss the trade | Multi-broker redundancy &mdash; if Webull is down, Schwab still fills |
| No risk management on signal trades | 4-tier profit targets, dynamic SL, trailing stops, EMA gating, per-channel rules |
| Can't track P&L across brokers | Unified dashboard with real-time streaming from all brokers |
| Different risk per signal provider | Per-channel AND per-author risk overrides |

---

## Quick Start

### Download & Run (Recommended)

Download the latest executable from [Releases](https://github.com/DiscordTrader/BotifyTrades/releases) &mdash; standalone desktop app, no Python needed.

**Windows:**
```
1. Download QuantumPulse_Trading_Bot.exe from Releases
2. Double-click to launch
3. Open http://localhost:5000 in your browser
4. Configure Discord token, brokers, and channels via the web GUI
```

**macOS:**
```
1. Download QuantumPulse_Trading_Bot_macOS from Releases
2. chmod +x QuantumPulse_Trading_Bot_macOS
3. ./QuantumPulse_Trading_Bot_macOS
4. Open http://localhost:5000 in your browser
```

**Linux:**
```
1. Download QuantumPulse_Trading_Bot_linux from Releases
2. chmod +x QuantumPulse_Trading_Bot_linux
3. ./QuantumPulse_Trading_Bot_linux
4. Open http://localhost:5000 in your browser
```

### Auto-Restart (Production)

**Windows** &mdash; double-click `run_forever.bat` (auto-restarts on crash, logs to files)

**Linux/macOS:**
```bash
./run_daemon.sh start    # Starts in background with auto-restart
./run_daemon.sh status   # Check if running
./run_daemon.sh stop     # Graceful shutdown
```

---

## Features

### Signal Intelligence Engine

<table>
<tr>
<td width="50%">

**188 Regex Parsers**
- Priority-ordered format registry
- 75+ channel-family coverage
- Options, stocks, futures, crypto
- BTO/STC, natural language, embeds
- Conditional triggers ("if SPY breaks $555")
- Expiry validation before execution

</td>
<td width="50%">

**Triple-AI Fallback**
- Unmatched signals &rarr; Claude / GPT / Gemini
- Structured extraction (symbol, action, price, strike)
- Confidence gating (&ge; 0.8 to execute)
- Works on stocks AND options
- Auto-learn: discovers new formats from history
- User approval before registering new patterns

</td>
</tr>
</table>

### Multi-Broker Execution

| Broker | Stocks | Options | Futures | Crypto | Streaming | Paper | Market |
|--------|:------:|:-------:|:-------:|:------:|:---------:|:-----:|:------:|
| **Schwab** | &check; | &check; | &cross; | &cross; | WebSocket | &cross; | US |
| **Webull** | &check; | &check; | &check; | &check; | MQTT | &check; | US |
| **Webull Official** | &check; | &check; | &cross; | &cross; | REST + WebSocket | &check; | US/UK |
| **Alpaca** | &check; | &check; | &cross; | &check; | WebSocket | &check; | US |
| **Interactive Brokers** | &check; | &check; | &check; | &cross; | TWS/Gateway | &check; | US/EU/Asia |
| **Tastytrade** | &check; | &check; | &check; | &cross; | DXLink | &check; | US |
| **Robinhood (Agentic)** | &check; | &check; | &cross; | &check; | MCP (REST) | &cross; | US |
| **Robinhood (Classic)** | &check; | &check; | &cross; | &check; | REST | &cross; | US |
| **Trading212** | &check; | &cross; | &cross; | &cross; | REST | &check; | UK/EU |

> Every signal fires across **all connected brokers simultaneously**. Partial fills on one broker don't block others.

### Robinhood Agentic Trading (MCP)

Robinhood's official [Agentic Trading MCP server](https://robinhood.com/us/en/agentic-trading/) integration:

- **OAuth authentication** &mdash; connect through Robinhood's login flow, tokens auto-refresh
- **Dedicated agentic account** &mdash; trades scoped to a separately funded sub-account
- **Equities, options, and crypto** &mdash; full order lifecycle (review &rarr; place &rarr; fill)
- **Live quotes** via `get_equity_quotes` / `get_option_quotes` MCP tools
- **Option chain browsing** &mdash; strike/expiry selection for option signals
- **Extended hours** &mdash; auto MARKET&rarr;LIMIT conversion outside 9:35-16:00 ET
- **Hot-connect** &mdash; authorize via web GUI, broker goes live without restart

### Risk Engine (Institutional-Grade)

```
Signal Detected
  │
  ├─ Asset Type Gate ── stocks/options/futures/crypto enabled for this channel?
  │
  ├─ Position Sizing ── % of buying power, fixed qty, or signal-specified
  │
  ├─ Entry ── market/limit, price increment rounding, slippage check
  │
  ├─ Profit Targets (4 tiers) ── independent qty per tier, trim percentages
  │    ├─ PT1: 10% → sell 25%
  │    ├─ PT2: 20% → sell 25%
  │    ├─ PT3: 30% → sell 25%
  │    └─ PT4: 50% → sell remaining (or leave runner)
  │
  ├─ Stop Loss ── static, dynamic (ratchets up with peak P&L), or EMA-gated
  │    ├─ Dynamic SL: escalates from -10% → -5% → -3% as profit grows
  │    ├─ Trailing Stop: activates after threshold, trails by X%
  │    └─ Early Trailing: tighter trail before first profit target
  │
  ├─ EMA Risk Overlay ── only exit when EMA confirms (reduces whipsaws)
  │
  ├─ Giveback Guard ── if position gave back X% from peak, force exit
  │
  ├─ PT Near-Lock ── locks profits near each tier (soft + hard thresholds)
  │
  ├─ Broker Brackets ── native SL/PT orders on broker side (Schwab, IBKR, Alpaca, TT)
  │
  └─ Per-Author Overrides ── different risk rules per signal provider
```

### Per-Channel & Per-Author Control

Every channel gets independent risk settings. **Every signal author within a channel** can have custom overrides:

```
Channel: "ProTrader Alerts"
  ├─ Default: SL=10%, PT1=15%, PT2=25%, trailing=5%
  ├─ Author "kobe824mamba": SL=8%, PT1=12%  (more conservative)
  └─ Author "phoenix88804": trailing=8%     (wider trailing)
```

### Futures Trading

Full futures pipeline &mdash; from signal detection to execution:

- **Natural language parsing**: `"NQ longs @ 27700"`, `"ES shorts @ 5500"`
- **Contract specs**: Multipliers (ES=50x, NQ=20x, MES=5x), tick sizes, session hours
- **Micro conversion**: Auto-convert ES &rarr; MES when account is too small
- **Session filtering**: Regular hours only, or extended/globex
- **PnL calculation**: Correct multiplier for all asset types

### Unified Price Hub (UPH)

Cross-broker price aggregation with streaming from all sources:

| Source | Protocol | Latency |
|--------|----------|---------|
| IBKR reqMktData | TWS streaming | ~200ms |
| IBKR reqTickByTickData | Tick-by-tick | ~100&mu;s |
| Schwab | WebSocket (LEVELONE) | ~300ms |
| Webull | MQTT pub/sub | ~200ms |
| Tastytrade | DXLink (Quote + Trade + TimeAndSale) | ~200ms |
| Alpaca | WebSocket (SIP/IEX) | ~150ms |

The UPH resolves the best available price across all connected hubs, with stuck-price detection and REST fallback for illiquid symbols.

### Real-Time Dashboard

<table>
<tr>
<td width="33%">

**Live Positions**
- Real-time P&L streaming
- Multi-broker aggregation
- Tier hit tracking
- Entry/current/target prices

</td>
<td width="33%">

**Trade History**
- Filled orders with slippage
- Execution timestamps
- Win rate & avg P&L
- Per-channel breakdown

</td>
<td width="33%">

**Risk Monitor**
- Active risk cycles
- Broker health status
- Position count per broker
- Conditional order queue

</td>
</tr>
</table>

### Conditional Orders

Price-level triggers that fire when conditions are met:

```
"SPY 555 resistance, calls above 548 support, puts below 0DTE"
  → Creates 2 conditional orders
  → StreamingPriceMonitor watches SPY via UPH (all brokers)
  → Price hits 555? → BTO CALL, execute across all brokers
  → Price drops to 548? → BTO PUT, execute across all brokers
```

### Telegram Integration

- Monitor Telegram channels alongside Discord
- Same parser pipeline, same risk engine, same execution
- Channel-level settings inherited

### Relay Server (Platform Mode)

Connect to the BotifyTrades relay server for signal streaming without a Discord selfbot:

- **Platform authentication** via Discord/Google OAuth
- **WebSocket connection** to `wss://botifytrades.com/ws/bot`
- **Provider browsing** &mdash; subscribe to signal channels from the dashboard
- **Auto-channel creation** on subscribe
- **Remote access** &mdash; monitor positions, pause trading, close trades from mobile

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     SIGNAL SOURCES                          │
│  Discord  │  Telegram (Telethon)  │  Relay WS    │
└──────────┬──────────┴────────┬──────────────┴──────┬────────┘
           │                   │                     │
           ▼                   ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   SIGNAL PARSER PIPELINE                     │
│  188 Regex Parsers (priority-ordered)                       │
│  → AI Fallback (Claude / GPT-4 / Gemini)                    │
│  → Auto-Learn (extracts history, proposes patterns)         │
│  → Expiry Validation → Asset Type Gate                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     RISK ENGINE                              │
│  ChannelRiskSettings → Per-Author Overrides                 │
│  Position Sizing → 4-Tier Profit Targets                    │
│  Dynamic SL → Trailing → EMA Gating → Giveback Guard        │
│  Broker Brackets (SL/PT on exchange) → Conditional Orders   │
└──────────────────────────┬──────────────────────────────────┘
                           │
     ┌────────┬────────┬───┼───┬────────┬────────┬────────┐
     ▼        ▼        ▼   ▼   ▼        ▼        ▼        ▼
┌────────┐┌────────┐┌──────┐┌──────┐┌────────┐┌────────┐┌──────────┐
│ Schwab ││ Webull ││Alpaca││ IBKR ││Tasty-  ││Robin-  ││Trading212│
│  WS    ││  MQTT  ││  WS  ││ TWS  ││trade   ││hood    ││  REST    │
│        ││        ││      ││      ││DXLink  ││MCP     ││          │
└────────┘└────────┘└──────┘└──────┘└────────┘└────────┘└──────────┘
     │        │        │       │        │         │          │
     └────────┴────────┴───┬───┴────────┴─────────┴──────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              UNIFIED PRICE HUB & MONITORING                  │
│  Real-time streaming from ALL brokers                       │
│  Position sync every 15s │ Risk eval every cycle            │
│  Dashboard (Flask) │ Health monitor │ P&L engine            │
└─────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology |
|---|---|
| **Core** | Python 3.11, asyncio, 300K lines |
| **Discord** | discord.py-self |
| **Telegram** | Telethon (relay client) |
| **Web GUI** | Flask + vanilla JS dashboard |
| **Desktop** | PySide6 system tray, PyInstaller |
| **Database** | SQLite (91 tables, WAL mode) |
| **Streaming** | WebSocket (Schwab/Alpaca), MQTT (Webull), DXLink (Tastytrade), TWS (IBKR), MCP (Robinhood) |
| **AI** | Claude API, OpenAI API, Gemini API |
| **Build** | PyInstaller + PyArmor obfuscation |
| **CI/CD** | GitHub Actions (Windows/Linux/macOS) |

---

## Signal Format Examples

BotifyTrades parses **all of these** automatically:

```python
# Standard options
"BTO 2 AAPL 190C 12/20 @3.50"
"STC TSLA 400P @ $12.80"

# Natural language
"Taking a position in NVDA at $125"
"All out of MSFT here, +15%"
"Trimming half GOOGL for 30% gain"

# Structured (Temple ZZ style)
"SYMBOL: SPY ✅ Entry: $555 ❌ SL: $548 🎯 PT1: $560 🎯 PT2: $570"

# Embeds (Nitro Trades, etc.)
"Contract: QQQ $670p | Price: $1.72 | Trim: 29% | SL to b/e"

# Futures
"NQ longs @ 27700"
"ES shorts @ 5500"

# Conditional
"SPY 555 resistance, calls above 548 support puts below 0DTE"

# Multi-line, multi-target
"BTO TSLA $322.5P 8/1
 SL: $3.30
 PT1: $4.50
 PT2: $5.80"
```

---

## Configuration

### Channel Settings (Web GUI)

Each Discord/Telegram channel is independently configurable:

| Setting | Description |
|---|---|
| **Brokers** | Which brokers execute signals from this channel |
| **Risk Profile** | SL%, PT1-4%, trailing%, dynamic SL profile |
| **Asset Types** | Enable/disable stocks, options, futures, crypto |
| **Position Sizing** | % of buying power, fixed qty, or signal-derived |
| **Exit Strategy** | Risk-managed, trailing-only, or manual |
| **EMA Overlay** | Period, timeframe, buffer &mdash; only exit when EMA confirms |
| **Author Overrides** | Per-signal-provider risk adjustments |
| **Conditional Orders** | Auto-create price-level triggers |

### Global Settings

| Setting | Description |
|---|---|
| **AI Provider** | Claude / OpenAI / Gemini / Disabled |
| **Max Positions** | Global position limit across all brokers |
| **Daily Loss Limit** | Auto-pause if daily P&L hits threshold |
| **Circuit Breaker** | Stop trading after N consecutive losses |
| **Paper Mode** | Test without real money (Webull, Alpaca, IBKR, Tastytrade) |

---

## Database Schema

91 tables tracking every aspect of the trading lifecycle:

| Category | Tables | Purpose |
|---|---|---|
| **Core** | `trades`, `channels`, `signal_lots` | Trade state, channel config, signal tracking |
| **Execution** | `execution_lots`, `filled_orders` | Per-leg fill tracking with timestamps |
| **Risk** | `conditional_orders`, `position_risk_settings` | Active risk rules, conditional triggers |
| **Routing** | `signal_routing_mappings` | Signal &rarr; channel &rarr; broker routing |
| **Monitoring** | `signal_verification_tables`, `execution_tracking` | Audit trail, verification |
| **Settings** | `global_risk_settings`, `author_risk_overrides` | Global + per-author risk config |

---

## By the Numbers

| Metric | Value |
|---|---|
| Lines of code | **300,000+** |
| Source files | **290+** |
| Test files | **72** (26K lines) |
| E2E tests | **888** |
| Signal parsers | **188** |
| Broker integrations | **7** |
| DB tables | **91** |
| Asset types | **4** (stocks, options, futures, crypto) |
| AI providers | **3** (Claude, GPT, Gemini) |
| Markets | **2** (US, UK/EU) |

---

## Disclaimer

> **This software executes real trades with real money.** Always test with paper trading first. Past performance does not guarantee future results. The authors are not responsible for financial losses. Use at your own risk.

BotifyTrades is a software automation tool only. It does not provide financial advice, trading recommendations, or investment guidance.

---

<p align="center">
  <strong>Built by traders, for traders.</strong><br/>
  <em>Stop copy-pasting signals. Start executing them.</em>
</p>

<p align="center">
  <a href="https://github.com/DiscordTrader/BotifyTrades/releases">
    <img src="https://img.shields.io/badge/Download-Latest_Release-brightgreen?style=for-the-badge&logo=github" alt="Download"/>
  </a>
</p>
