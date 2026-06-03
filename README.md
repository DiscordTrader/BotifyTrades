# BotifyTrades v10.2.9

**Multi-Broker Automated Trading Bot** | Discord Signal Detection | AI-Powered Parsing | Risk Management

A desktop trading bot that monitors Discord channels for trading signals and automatically executes trades across multiple brokers with built-in risk management, position monitoring, and AI fallback parsing.

## Key Features

### Multi-Broker Execution
| Broker | Stocks | Options | Paper | Streaming |
|--------|--------|---------|-------|-----------|
| Schwab | Yes | Yes | No | WebSocket |
| Webull | Yes | Yes | Yes | REST |
| Alpaca | Yes | Yes | Yes | WebSocket |
| Interactive Brokers | Yes | Yes | Yes | TWS/Gateway |
| Tastytrade | Yes | Yes | Yes | REST |

### Signal Detection (140+ Formats)
- **Regex-Based Parsers**: 140 registered formats across 75+ channel families
- **Structured Formats**: `SYMBOL ✅ PRICE ❌ SL 🎯 TARGETS` (TEMPLE-BOOM, ZZ)
- **Standard BTO/STC**: `BTO 2 AAPL 190C 12/20 @3.50`
- **Natural Language**: "Taking a position in $NAMM at 2.38", "All out of ROLR"
- **Channel-Specific**: Phoenix, ProTrader, AbTrades, Sir Goldman, Jacob, Slem, Jake, Ashley, Angela, Rocky, Infra Trade, Equity Genie, and more
- **Conditional Orders**: Break/over triggers with SL/PT that execute when price hits target

### AI-Powered Signal Recognition
When no regex parser matches a signal, the bot falls back to AI-based parsing:

- **Multi-Provider Support**: Choose between Claude (Anthropic), OpenAI, or Replit AI
- **Trained on All Channels**: Auto-loads 49+ curated examples from all 75 channel families at startup
- **Options + Stocks**: AI extracts symbol, strike, C/P, expiry, price from any format
- **Confidence Gating**: Only executes when AI confidence >= 0.8 (prevents false positives)
- **Non-Signal Rejection**: Trained to reject watchlists, recaps, commentary, and price updates
- **Self-Maintaining**: When new regex formats are added, AI training updates automatically
- **Trade Analysis**: Post-trade AI analysis with technical insights (supports all providers)
- **Sentiment Analysis**: Channel message sentiment tracking for market pulse

Configure in **Admin > Settings > AI & Market Data APIs**:
- Select AI Provider (Claude / OpenAI / Replit AI / Disabled)
- Enter API key for your chosen provider
- AI features: signal fallback parsing, format learning, trade analysis, sentiment analysis

### Risk Management
- **Tiered Profit Targets**: PT1-PT4 with configurable percentages
- **Dynamic Stop Loss**: Ratchet SL based on peak P&L, not just current price
- **Trailing Stops**: Activation threshold + trail percentage
- **OCO Brackets**: One-Cancels-Other bracket orders (Schwab native)
- **$0 Price Guard**: Centralized guard prevents false SL triggers on new positions
- **Per-Channel Settings**: Independent risk profiles per Discord channel
- **Leave Runner**: Keep a percentage of position for extended moves

### Position Monitoring
- **Real-Time Streaming**: Schwab WebSocket for instant price updates
- **Options Dynamic Subscribe**: New option positions auto-subscribed to streaming
- **Peak Tracking**: `max_pnl_seen` tracks interval highs for accurate tier evaluation
- **Multi-Lot Support**: Independent tracking per signal instance

### Desktop Application
- **PyInstaller Build**: Standalone EXE for Windows/Mac/Linux
- **Flask Web GUI**: Browser-based control panel on localhost
- **PySide6 Tray**: System tray icon with splash screen
- **Auto-Update**: Version checking and upgrade support

## Signal Flow

```
Discord Message
  -> Regex Parsers (140+ formats, priority-ordered)
    -> Match? -> Route to channel broker(s) -> Execute
    -> No match? -> AI Fallback (if enabled)
      -> Confidence >= 0.8? -> Route to channel broker(s) -> Execute
      -> Low confidence? -> Log and skip
```

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run
```bash
python src/selfbot_webull.py
```
Open `http://localhost:5000` in your browser.

### 3. Configure via Web GUI
- **Discord**: Enter your user token
- **Brokers**: Configure credentials for each broker
- **Channels**: Add Discord channel IDs, assign brokers, set risk parameters
- **AI**: Select provider and enter API key in Admin > Settings > AI & Market Data APIs

## Disclaimer

This software executes real trades with real money. Always test with paper trading first. Use at your own risk. No warranty provided.
