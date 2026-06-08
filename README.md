# BotifyTrades v11.1.7

**Next-Gen Signal Intelligence** | AI-Powered Multi-Broker Execution | Decode Any Signal. Arm Every Broker.

An AI-powered desktop trading bot that monitors Discord channels for trading signals and automatically executes trades across 5 brokers. 130+ regex parsers with multi-provider AI fallback, intelligent risk management, auto-learning format discovery, and real-time position monitoring.

---

## Key Features

### AI Signal Intelligence
| Capability | Description |
|-----------|-------------|
| **130+ Regex Parsers** | Priority-ordered format registry across 75+ channel families |
| **AI Fallback Parsing** | Unrecognized signals analyzed by AI in real-time |
| **3 AI Providers** | Claude (Anthropic), OpenAI, Gemini (Google) |
| **Auto-Learn Pipeline** | AI discovers new signal formats from channel history |
| **Format Approval Flow** | AI proposes patterns, user approves before activation |
| **Confidence Gating** | Only executes when AI confidence >= 0.8 |
| **Non-Signal Rejection** | Trained to reject watchlists, recaps, commentary, price updates |

### Multi-Broker Execution
| Broker | Stocks | Options | Paper | Streaming |
|--------|--------|---------|-------|-----------|
| Schwab | Yes | Yes | No | WebSocket |
| Webull | Yes | Yes | Yes | MQTT |
| Alpaca | Yes | Yes | Yes | WebSocket |
| Interactive Brokers | Yes | Yes | Yes | TWS/Gateway |
| Tastytrade | Yes | Yes | Yes | DXLink |

### Signal Detection (130+ Formats)
- **Structured Formats**: `SYMBOL ✅ PRICE ❌ SL 🎯 TARGETS` (Temple ZZ, multi-line)
- **Standard BTO/STC**: `BTO 2 AAPL 190C 12/20 @3.50` (options + stocks)
- **Natural Language**: "Taking a position in $NAMM at 2.38", "All out of ROLR"
- **Breakout Triggers**: "SMTK will enter only if it breaks 0.55 for 0.60...0.65"
- **Channel-Specific**: Phoenix, ProTrader, AbTrades, Jacob, Ashley, Angela, Rocky, Viking, and 60+ more
- **Conditional Orders**: Price-level triggers with SL/PT that execute when conditions are met
- **Expiry Validation**: Rejects expired options with clear error before hitting any broker

### AI-Powered Capabilities

**Signal Recognition** - When no regex parser matches:
- Multi-provider AI (Claude, Gemini, OpenAI) analyzes the message in real-time
- Extracts symbol, action, price, strike, expiry, stop loss, profit targets
- Works on both mapped channels (signal routing) and regular execution channels
- Handles stocks AND options signals

**Auto-Learn Format Discovery**:
- Extract last 1000 messages from any Discord channel
- AI + heuristic hybrid analysis identifies buy/sell patterns
- Candidates presented to user for approval via chatbot
- Approved formats auto-register in the signal format registry
- Channel-scoped format isolation via `allowed_signal_formats`

**AI Chat Assistant**:
- Natural language trade queries ("what happened with UNH trade?")
- Channel analysis and format training via conversation
- Real-time trade data, P&L history, and broker status

Configure in **Settings > AI & Market Data APIs**:
- Select AI Provider (Claude / OpenAI / Gemini / Disabled)
- Enter API key for your chosen provider

### Risk Management
- **Tiered Profit Targets**: PT1-PT4 with configurable percentages
- **Dynamic Stop Loss**: Ratchet SL based on peak P&L, not just current price
- **Trailing Stops**: Activation threshold + trail percentage
- **OCO Brackets**: One-Cancels-Other bracket orders (Schwab native)
- **Per-Channel Settings**: Independent risk profiles per Discord channel
- **Position Sizing**: Percentage-based sizing per channel with broker buying power calculation
- **Leave Runner**: Keep a percentage of position for extended moves

### Position Monitoring
- **Real-Time Streaming**: Schwab WebSocket + Webull MQTT for instant price updates
- **Unified Price Hub**: Cross-broker price aggregation with sub-second updates
- **Options Dynamic Subscribe**: New option positions auto-subscribed to streaming
- **Peak Tracking**: `max_pnl_seen` tracks interval highs for accurate tier evaluation
- **Multi-Lot Support**: Independent tracking per signal instance
- **Broker Sync**: 15-second reconciliation loop across all brokers

### Desktop Application
- **PyInstaller Build**: Standalone EXE for Windows
- **Flask Web GUI**: Browser-based control panel on localhost:5000
- **PySide6 Tray**: System tray icon with splash screen
- **Architecture Page**: Premium landing page with neural network branding
- **Auto-Update**: Version checking and upgrade support

## Signal Flow

```
Discord / Telegram Message
  -> Regex Parsers (130+ formats, priority-ordered)
    -> Match? -> Expiry Validation -> Conditional Order -> Execute on all brokers
    -> No match? -> AI Fallback (Claude / Gemini / OpenAI)
      -> Confidence >= 0.8? -> Conditional Order -> Execute on all brokers
      -> Low confidence? -> Log and skip
  -> Auto-Learn Pipeline (background)
    -> Extract channel history -> AI + heuristic analysis
    -> Propose new formats -> User approval -> Register pattern
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
- **AI**: Select provider and enter API key in Settings > AI & Market Data APIs

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Core | Python 3.11, asyncio |
| Discord | discord.py (selfbot) |
| Web GUI | Flask, PySide6 (tray) |
| Database | SQLite |
| HTTP | httpx (async) |
| Streaming | WebSocket (Schwab), MQTT (Webull) |
| AI | Claude API, OpenAI API, Gemini API |
| Build | PyInstaller + PyArmor |
| CI/CD | GitHub Actions |

## Disclaimer

This software executes real trades with real money. Always test with paper trading first. Use at your own risk. No warranty provided.
