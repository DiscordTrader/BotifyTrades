<p align="center">
  <img src="https://img.shields.io/badge/BotifyTrades-v10.2.5-00d4ff?style=for-the-badge&labelColor=1a1a2e" alt="Version"/>
  <img src="https://img.shields.io/badge/Brokers-7+ Supported-blueviolet?style=for-the-badge&labelColor=1a1a2e" alt="Brokers"/>
  <img src="https://img.shields.io/badge/Platform-Win%20%7C%20Mac%20%7C%20Linux-green?style=for-the-badge&labelColor=1a1a2e" alt="Platform"/>
  <img src="https://img.shields.io/github/downloads/DiscordTrader/BotifyTrades/total?style=for-the-badge&color=ff6b6b&labelColor=1a1a2e&label=Downloads" alt="Downloads"/>
  <img src="https://img.shields.io/github/v/release/DiscordTrader/BotifyTrades?style=for-the-badge&color=ffd93d&labelColor=1a1a2e&label=Latest" alt="Latest Release"/>
</p>

<h1 align="center">BotifyTrades</h1>
<h3 align="center">The Most Powerful Discord-to-Broker Trading Bot</h3>

<p align="center">
  Automatically execute trades from Discord signals across 7+ brokers.<br/>
  Options, stocks, OCO brackets, tiered profit targets, trailing stops — all hands-free.<br/>
  <strong>One app. Every broker. Zero manual entry.</strong>
</p>

<p align="center">
  <a href="https://github.com/DiscordTrader/BotifyTrades/releases/latest"><img src="https://img.shields.io/badge/DOWNLOAD%20NOW-00d4ff?style=for-the-badge&logo=windows&logoColor=white" alt="Download"/></a>
  <a href="https://botifytrades.com"><img src="https://img.shields.io/badge/WEBSITE-blueviolet?style=for-the-badge&logo=google-chrome&logoColor=white" alt="Website"/></a>
  <a href="https://github.com/DiscordTrader/BotifyTrades/discussions"><img src="https://img.shields.io/badge/COMMUNITY-ffd93d?style=for-the-badge&logo=discord&logoColor=black" alt="Community"/></a>
</p>

---

## Why BotifyTrades?

You're in a Discord trading group. A signal drops: `BTO 5 SPY 550C 6/20 @ 2.15`. By the time you open your broker, find the contract, type the order — the price has moved. Every. Single. Time.

**BotifyTrades eliminates that.** It reads Discord signals in real-time and fires orders to your broker in milliseconds. Not a webhook relay. Not a copy-paste tool. A full execution engine with risk management that professionals actually use.

---

## Supported Brokers

<table>
<tr>
<td align="center" width="140"><strong>Schwab</strong><br/><sub>Stocks + Options</sub></td>
<td align="center" width="140"><strong>Interactive Brokers</strong><br/><sub>Stocks + Options</sub></td>
<td align="center" width="140"><strong>Webull</strong><br/><sub>Stocks + Options</sub></td>
<td align="center" width="140"><strong>Tastytrade</strong><br/><sub>Stocks + Options</sub></td>
</tr>
<tr>
<td align="center" width="140"><strong>Alpaca</strong><br/><sub>Stocks + Options</sub></td>
<td align="center" width="140"><strong>Robinhood</strong><br/><sub>Stocks + Options</sub></td>
<td align="center" width="140"><strong>Trading 212</strong><br/><sub>Stocks</sub></td>
<td align="center" width="140"><strong>+ More</strong><br/><sub>Modular adapter system</sub></td>
</tr>
</table>

> Trade the same signal across multiple brokers simultaneously. Each broker has independent settings, position tracking, and risk management.

---

## Features at a Glance

### Signal Parsing — 70+ Formats, Zero Configuration

BotifyTrades understands signals from the most popular Discord trading groups out of the box. No regex setup. No custom formatting. Just point it at a channel and it works.

```
BTO 5 SPY 550C 6/20 @ 2.15          # Standard option format
STC SPY 550C 6/20 @ 3.50             # Sell-to-close
BTO 100 AAPL @ 185.50                # Stock entry
PLTR 22.50C 7/18 x5 @ 1.20          # Alternative format
Sold all TSLA calls at 4.80          # Natural language exit
Taking profits on NVDA — out half    # Partial exit
Stop loss hit on AMD                 # Auto-detected exit
```

**Supported signal styles include:**
- Standard BTO/STC with strike, expiry, and price
- Natural language entries and exits ("Bought", "Sold all", "Taking profits")
- Ticker-only exits (auto-matches open positions)
- Partial exits with percentage or quantity
- Stop loss and profit target updates
- Conditional/breakout entries ("Break 2.82 for 3.12")
- Structured entries with entry/stop/target levels
- 0DTE and weekly formats
- Index option conversion (SPX/NDX)

### Risk Management — Set It and Forget It

<table>
<tr>
<td width="50%">

**Stop Loss Protection**
- Fixed percentage stop loss
- Trailing stops with custom activation
- Dynamic stop loss (EMA-based)
- Early trailing (lock in breakeven)
- Per-channel risk overrides

</td>
<td width="50%">

**Profit Targets**
- Multi-tier profit targets (up to 4 levels)
- Partial exits at each tier
- Giveback guard (protect unrealized gains)
- Runner management (let winners run)
- Auto-scale remaining position

</td>
</tr>
</table>

**Bracket Orders & OCO** — Place stop loss + profit target as a single OCO (One-Cancels-Other) bracket. When one fills, the other cancels automatically. Supported on Schwab, IBKR, and Tastytrade.

**Daily P&L Limits** — Set a daily loss limit. When hit, the bot auto-closes all positions and pauses trading for the day. No emotional revenge trading.

**Conditional Orders** — "Buy AAPL if it breaks $190" — the bot monitors price and executes only when your condition is met.

### Live Web Dashboard

A full trading control panel runs locally in your browser. No cloud. No latency. Everything on your machine.

**Dashboard**
- Real-time P&L across all brokers
- Position cards with live price streaming
- Quick-close buttons (Bid / Mid / Market)
- Risk status badges (SL active, trailing, PT hit)
- Daily P&L progress bar with limit warnings

**Trades & Positions**
- Live positions with entry price, current price, unrealized P&L
- Pending orders with status tracking
- Trade history with full audit trail
- One-click position close with price selection

**Performance Analytics**
- Win rate, average gain, average loss
- P&L by channel, by broker, by day
- Calendar heatmap visualization
- Channel leaderboard rankings
- Equity curve tracking

**Settings**
- Per-channel execution toggle (Execute vs. Track-only)
- Per-channel risk overrides (SL%, PT levels, trailing)
- Broker credential management with test-connection
- Signal pattern configuration
- Slippage protection thresholds

### Multi-Channel, Multi-Broker Routing

```
Channel A (Phoenix Alerts)  -->  Schwab   [Execute, 2 contracts, trailing SL]
Channel B (Day Trade Room)  -->  IBKR     [Execute, 5 contracts, OCO brackets]  
Channel C (Swing Plays)     -->  Webull   [Track only, no execution]
Channel D (Stock Picks)     -->  Alpaca   [Execute, 100 shares, 5% SL]
```

Each channel gets its own:
- Broker assignment
- Position sizing (contracts or shares)
- Risk profile (SL, PT, trailing)
- Execution mode (execute or track-only)
- Slippage protection threshold

### Real-Time Price Streaming

BotifyTrades connects directly to broker WebSocket feeds for live pricing:

- **Unified Price Hub** — aggregates quotes from all connected brokers
- **Sub-second price updates** — streaming bid/ask/last from broker data feeds
- **Smart quote routing** — uses the best available price across brokers
- **Price flashing** — green/red flash on price changes in the dashboard

### Additional Features

| Feature | Description |
|---------|-------------|
| **Paper Trading** | Test strategies risk-free with simulated execution (Webull, Alpaca, IBKR) |
| **Option Chain Viewer** | Browse live option chains with Greeks and moneyness indicators |
| **Signal History** | Full audit trail of every parsed signal with match details |
| **Order Chaser** | Automatically re-submits unfilled limit orders at updated prices |
| **Position Sync** | Reconciles bot state with actual broker positions continuously |
| **Circuit Breaker** | Halts trading on connection issues to prevent orphaned orders |
| **Index Conversion** | Automatically converts SPX/NDX signals to tradeable contracts |
| **Slippage Guard** | Rejects orders when price has moved beyond your threshold |
| **Market Hours** | Respects market hours per exchange — no wasted orders |
| **News Integration** | Real-time news feed for active positions (Finnhub) |
| **Mobile Relay** | Forward signals and alerts to your phone |
| **Webhook Support** | Send/receive signals via webhooks for external integrations |

---

## Quick Start

### 1. Download

<table>
<tr>
<td align="center"><a href="https://github.com/DiscordTrader/BotifyTrades/releases/latest"><strong>Windows</strong></a><br/><code>BotifyTrades-Windows.exe</code></td>
<td align="center"><a href="https://github.com/DiscordTrader/BotifyTrades/releases/latest"><strong>macOS (Intel)</strong></a><br/><code>BotifyTrades-macOS-Intel.tar.gz</code></td>
</tr>
<tr>
<td align="center"><a href="https://github.com/DiscordTrader/BotifyTrades/releases/latest"><strong>macOS (Silicon)</strong></a><br/><code>BotifyTrades-macOS-Silicon.tar.gz</code></td>
<td align="center"><a href="https://github.com/DiscordTrader/BotifyTrades/releases/latest"><strong>Linux</strong></a><br/><code>BotifyTrades-Linux</code></td>
</tr>
</table>

### 2. Run

Just double-click the executable. A setup wizard walks you through:

1. **License activation** — enter your license key (7-day free trial available)
2. **Broker credentials** — securely stored with OS-level encryption (Windows DPAPI / macOS Keychain)
3. **Discord token** — your user token for reading channels
4. **Channel setup** — pick which channels to monitor and which brokers to route to

### 3. Trade

Open the web dashboard at `http://localhost:5000` and you're live. The bot monitors your Discord channels and executes trades automatically based on your risk settings.

---

## How It Works

```
Discord Signal                    Your Broker
     |                                 ^
     v                                 |
 [Signal Parser]                  [Order Engine]
     |                                 ^
     v                                 |
 [Format Registry]               [Risk Manager]
  70+ patterns                   SL / PT / Trail
     |                                 ^
     v                                 |
 [Route to Broker] -----> [Position Monitor]
  Per-channel config        Real-time tracking
```

1. **Signal drops** in a Discord channel you're monitoring
2. **Parser matches** the message against 70+ known formats
3. **Risk engine** applies your stop loss, profit targets, and position sizing
4. **Order fires** to your assigned broker via direct API
5. **Position monitor** tracks the trade with real-time streaming prices
6. **Auto-exits** when stop loss or profit targets are hit

---

## Security

- **Credentials encrypted at rest** using Windows DPAPI / macOS Keychain
- **No cloud dependency** — everything runs locally on your machine
- **No data collection** — your trades, positions, and broker credentials never leave your computer
- **Obfuscated binaries** — source code is protected in distributed builds
- **Secure broker connections** — TLS/SSL for all API communications

---

## Requirements

- Windows 10+, macOS 12+, or Ubuntu 20.04+
- Internet connection
- Broker account with API access enabled
- Discord account

---

## FAQ

<details>
<summary><strong>Is this a selfbot? Will my Discord account get banned?</strong></summary>
<br/>
BotifyTrades uses a Discord user token to read messages in channels you're already a member of. It only reads — it never sends messages, reacts, or interacts. Use at your own discretion and review Discord's Terms of Service.
</details>

<details>
<summary><strong>Which Discord trading groups work with this?</strong></summary>
<br/>
BotifyTrades supports 70+ signal formats out of the box. Most popular trading groups use one of these formats. If your group uses a unique format, you can configure custom patterns in the settings.
</details>

<details>
<summary><strong>Can I use multiple brokers at the same time?</strong></summary>
<br/>
Yes. You can connect all your brokers simultaneously and route different channels to different brokers. You can even execute the same signal across multiple brokers.
</details>

<details>
<summary><strong>Is paper trading supported?</strong></summary>
<br/>
Yes. Webull, Alpaca, and IBKR all support paper trading mode. You can test strategies risk-free before going live.
</details>

<details>
<summary><strong>What happens if my internet disconnects?</strong></summary>
<br/>
The circuit breaker detects disconnections and pauses execution. Existing positions retain their broker-side stop loss and profit target orders (OCO brackets). When connection restores, the bot resumes automatically.
</details>

<details>
<summary><strong>Can I set different risk settings per channel?</strong></summary>
<br/>
Yes. Each channel can have its own stop loss percentage, profit target levels, trailing stop configuration, position size, and broker assignment. A conservative channel can have tight stops while an aggressive channel runs with wider ranges.
</details>

---

## Support & Community

- **Issues & Bugs**: [GitHub Issues](https://github.com/DiscordTrader/BotifyTrades/issues)
- **Discussions**: [GitHub Discussions](https://github.com/DiscordTrader/BotifyTrades/discussions)
- **Website**: [botifytrades.com](https://botifytrades.com)

---

<p align="center">
  <strong>Stop missing trades. Start automating.</strong><br/><br/>
  <a href="https://github.com/DiscordTrader/BotifyTrades/releases/latest">
    <img src="https://img.shields.io/badge/DOWNLOAD%20BOTIFYTRADES-00d4ff?style=for-the-badge&logo=github&logoColor=white" alt="Download"/>
  </a>
</p>

<p align="center">
  <sub>BotifyTrades is a software automation tool. It does not provide financial advice or trading recommendations. All trading decisions and outcomes are your responsibility. Trading options and stocks involves risk of loss.</sub>
</p>
