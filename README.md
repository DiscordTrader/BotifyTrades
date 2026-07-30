<p align="center">
  <img src="https://img.shields.io/badge/BotifyTrades-v15.1.0-blueviolet?style=for-the-badge&logo=bitcoin&logoColor=white" alt="Version"/>
  <img src="https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Brokers-5-green?style=for-the-badge&logo=tradingview&logoColor=white" alt="Brokers"/>
  <img src="https://img.shields.io/badge/Signal_Parsers-188+-orange?style=for-the-badge&logo=regex&logoColor=white" alt="Parsers"/>
  <img src="https://img.shields.io/badge/Lines_of_Code-275K-red?style=for-the-badge&logo=codacy&logoColor=white" alt="LOC"/>
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

> **A trading bot that monitors Discord & Telegram for signals and auto-executes across 5 brokers simultaneously** &mdash; with 188 regex parsers, triple-AI fallback, real-time streaming, and an institutional-grade risk engine that runs 275,000 lines of production Python.

```
Discord/Telegram Signal ──> 188 Regex Parsers ──> Risk Engine ──> 5 Brokers (simultaneous)
         │                         │                    │               │
         │                    No match?             4-tier PT       Schwab
         │                         │               Dynamic SL       Webull
         └── AI Fallback ──────────┘               Trailing        Alpaca
             (Claude/GPT/Gemini)                   EMA-gated        IBKR
                                                   Per-author     Tastytrade
```

---

## Why BotifyTrades?

Most trading bots parse one format from one channel into one broker. **BotifyTrades parses any format from any channel into every broker** &mdash; simultaneously.

| Problem | BotifyTrades Solution |
|---|---|
| Signal providers all use different formats | 188 regex parsers + AI fallback that learns new formats |
| Manual copy-paste loses seconds on entries | Sub-second execution across all 5 brokers at once |
| One broker goes down, you miss the trade | Multi-broker redundancy &mdash; if Webull is down, Schwab still fills |
| No risk management on signal trades | 4-tier profit targets, dynamic SL, trailing stops, EMA gating, per-channel rules |
| Can't track P&L across brokers | Unified dashboard with real-time streaming from all brokers |
| Different risk per signal provider | Per-channel AND per-author risk overrides |

---

## Quick Start

### Prerequisites
- Python 3.11+
- A Discord user token ([guide](https://www.androidauthority.com/get-discord-token-3149920/))
- At least one broker account (Webull, Schwab, Alpaca, IBKR, or Tastytrade)

### Install & Run

```bash
# Clone
git clone https://github.com/DiscordTrader/BotifyTrades.git
cd BotifyTrades

# Install dependencies
pip install -r requirements.txt

# Launch
python src/selfbot_webull.py
```

Open **http://localhost:5000** &rarr; Configure Discord token, brokers, and channels.

### One-Click Install (Windows)

Download the latest `.exe` from [Releases](https://github.com/DiscordTrader/BotifyTrades/releases) &mdash; standalone desktop app with system tray, no Python needed.

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

| Broker | Stocks | Options | Futures | Crypto | Streaming | Paper |
|--------|:------:|:-------:|:-------:|:------:|:---------:|:-----:|
| **Schwab** | &check; | &check; | &cross; | &cross; | WebSocket | &cross; |
| **Webull** | &check; | &check; | &check; | &check; | MQTT | &check; |
| **Alpaca** | &check; | &check; | &cross; | &check; | WebSocket | &check; |
| **Interactive Brokers** | &check; | &check; | &check; | &cross; | TWS/Gateway | &check; |
| **Tastytrade** | &check; | &check; | &check; | &cross; | DXLink | &check; |

> Every signal fires across **all connected brokers simultaneously**. Partial fills on one broker don't block others.

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

### Asset Type Gating

Control exactly what each channel can trade:

| Setting | Effect |
|---|---|
| Stocks &check; Options &check; Futures &cross; Crypto &cross; | Only stock and option signals execute |
| Stocks &cross; Options &check; | Options-only channel (ignores stock signals) |
| Futures &check; | Futures signals detected and executed (ES, NQ, CL, GC...) |

### Futures Trading

Full futures pipeline &mdash; from signal detection to execution:

- **Natural language parsing**: `"NQ longs @ 27700"`, `"ES shorts @ 5500"`
- **Contract specs**: Multipliers (ES=50x, NQ=20x, MES=5x), tick sizes, session hours
- **Micro conversion**: Auto-convert ES &rarr; MES when account is too small
- **Session filtering**: Regular hours only, or extended/globex
- **PnL calculation**: Correct multiplier for all asset types

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
  → StreamingPriceMonitor watches SPY via all brokers
  → Price hits 555? → BTO CALL, execute across all brokers
  → Price drops to 548? → BTO PUT, execute across all brokers
```

### Telegram Integration

- Monitor Telegram channels alongside Discord
- Same parser pipeline, same risk engine, same execution
- Channel-level settings inherited

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     SIGNAL SOURCES                          │
│  Discord (selfbot)  │  Telegram (relay)  │  API webhooks    │
└──────────┬──────────┴────────┬───────────┴──────┬───────────┘
           │                   │                  │
           ▼                   ▼                  ▼
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
│  Conditional Orders → StreamingPriceMonitor                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  Schwab  │ │  Webull  │ │  Alpaca  │ │   IBKR   │ │Tastytrade│
│WebSocket │ │   MQTT   │ │WebSocket │ │TWS/Gateway│ │  DXLink  │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
              │            │            │
              ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────┐
│              UNIFIED PRICE HUB & MONITORING                  │
│  Real-time streaming from ALL brokers                       │
│  Position sync every 15s │ Risk eval every cycle            │
│  Dashboard (Flask) │ Health monitor │ Execution logs        │
└─────────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology |
|---|---|
| **Core** | Python 3.11, asyncio, 275K lines |
| **Discord** | discord.py-self (selfbot) |
| **Telegram** | Telethon (relay client) |
| **Web GUI** | Flask + vanilla JS dashboard |
| **Desktop** | PySide6 system tray, PyInstaller |
| **Database** | SQLite (91 tables, WAL mode) |
| **Streaming** | WebSocket (Schwab), MQTT (Webull), DXLink (Tastytrade) |
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
| **EMA Overlay** | Period, timeframe, buffer — only exit when EMA confirms |
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
| Lines of code | **275,878** |
| Source files | **268** |
| Test files | **72** (26K lines) |
| Signal parsers | **188** |
| Broker integrations | **5** |
| DB tables | **91** |
| Commits | **5,894** |
| Asset types | **4** (stocks, options, futures, crypto) |
| AI providers | **3** (Claude, GPT, Gemini) |

---

## Roadmap

- [ ] **Image Signal Parsing** &mdash; Vision AI for broker screenshot alerts (Robinhood, Webull, ThinkorSwim)
- [ ] **Voice Channel Monitoring** &mdash; Speech-to-text for verbal trading calls
- [ ] **TradingView Webhooks** &mdash; Direct alert-to-execution pipeline
- [ ] **Options Flow Scanner** &mdash; Unusual activity detection
- [ ] **Mobile Companion** &mdash; React Native app for monitoring on the go

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
