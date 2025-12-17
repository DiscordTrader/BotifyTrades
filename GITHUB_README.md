# BotifyTrades

[![Version](https://img.shields.io/badge/version-3.3.0-blue.svg)](https://github.com/DiscordTrader/BotifyTrades/releases)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20AWS-lightgrey.svg)](https://github.com/DiscordTrader/BotifyTrades/releases)

**Automated Discord Trading Bot for Webull, Alpaca, Interactive Brokers & Tastytrade**

BotifyTrades is a powerful cross-platform Discord self-bot that monitors trading signal channels and automatically executes trades across multiple brokerages. Perfect for traders who follow Discord alert services and want to automate their order execution.

---

## Key Features

### Multi-Broker Support
- **Webull** - Live and paper trading with real-time market data
- **Alpaca** - Commission-free stock and options trading
- **Interactive Brokers (IBKR)** - Professional-grade execution
- **Tastytrade** - Options-focused brokerage integration

### Intelligent Signal Parsing
- **AI-Powered Learning** - Teach the bot new signal formats once, and it remembers forever
- **Multi-Format Support** - Handles BTO, STC, stock alerts, options contracts, and more
- **Per-Channel Configuration** - Different settings for different Discord channels
- **User Filtering** - Only execute signals from specific trusted traders

### Advanced Risk Management
- **Tiered Profit Targets** - PT1, PT2, PT3 with automatic partial exits
- **Stop Loss Protection** - Configurable stop losses per channel or globally
- **Trailing Stops** - Lock in profits as trades move in your favor
- **Slippage Protection** - Prevent overpaying on fast-moving options
- **Position Sizing** - Fixed quantity, percentage of portfolio, or trader's exact size

### Web Control Panel
- **Real-Time Dashboard** - Monitor all positions, P&L, and trade history
- **Professional GUI** - Dark theme interface with live analytics
- **AI Chat Assistant** - Get help and manage the bot through natural conversation
- **Leaderboard** - Track performance by channel and trader
- **Portfolio Simulator** - Backtest strategies with historical data

### Trade Analytics
- **P&L Tracking** - Comprehensive profit/loss with FIFO lot matching
- **Win Rate Statistics** - Per-channel and per-trader performance metrics
- **Capital Requirements Calculator** - Know exactly how much capital you need
- **AI Post-Trade Analysis** - GPT-powered insights on every trade

---

## Supported Signal Formats

BotifyTrades understands a wide variety of trading signal formats:

```
BTO AAPL 150C 12/20 @ 2.50
STC TSLA 200P 1/17 @ 5.00
AAPL 150C 12/20 entry 2.50
Bought SPY 450C 0DTE @ 1.25
6900c                          ← SPX/NDX shorthand for 0DTE
TRADE IDEA: NVDA 500C 1/17
```

Don't see your format? Simply teach the bot using the AI chat assistant!

---

## Quick Start

### Download
Get the latest release from the [Releases Page](https://github.com/DiscordTrader/BotifyTrades/releases)

### Requirements
- Python 3.8 or higher
- Discord account token
- Brokerage account(s) with API access
- License key (contact for pricing)

### Installation

**Windows:**
```bash
# Extract the release ZIP
# Run the installer or execute directly:
python src/selfbot_webull.py
```

**Linux:**
```bash
# Extract and install dependencies
pip install -r requirements.txt

# Run the bot
python src/selfbot_webull.py
```

### First-Time Setup
1. Launch the bot to start the setup wizard
2. Create your admin account with email recovery
3. Enter your Discord token
4. Configure your broker credentials
5. Add Discord channels to monitor
6. Set your risk management preferences

---

## Web GUI Dashboard

Access the control panel at `http://localhost:5000` after starting the bot.

### Dashboard Features
- Live position monitoring with real-time prices
- Trade history with filtering and search
- Channel management and configuration
- Broker credential management (encrypted)
- Risk settings per channel
- Performance analytics and charts
- AI-powered chat assistant

---

## Configuration

All settings are managed through the web GUI. Key configuration options:

| Setting | Description |
|---------|-------------|
| Discord Channels | Channels to monitor for signals |
| Broker Selection | Which broker to use per channel |
| Position Sizing | Fixed amount or % of portfolio |
| Profit Targets | PT1/PT2/PT3 percentages and quantities |
| Stop Loss | Automatic stop loss percentage |
| Trailing Stop | Enable/disable trailing stops |
| Slippage | Maximum acceptable price deviation |
| User Filter | Only trade signals from specific users |

---

## Deployment Options

- **Local Machine** - Run on your Windows/Mac/Linux computer
- **Cloud VPS** - Deploy to AWS, DigitalOcean, or any Linux server
- **24/7 Operation** - Systemd service for Linux auto-start

---

## Security

- All broker credentials are encrypted at rest
- License keys are machine-bound for protection
- No credentials are ever transmitted externally
- Open-source signal parsing (you can audit the code)

---

## Support

- **Documentation**: Check the releases for detailed setup guides
- **Issues**: Open a GitHub issue for bugs or feature requests
- **Discord**: Join our community for help and discussion

---

## License

BotifyTrades is proprietary software. A valid license key is required for operation.
Contact for licensing and pricing information.

---

## Disclaimer

Trading stocks and options involves substantial risk of loss. BotifyTrades is a tool to automate trade execution based on signals you choose to follow. Past performance does not guarantee future results. Always paper trade first and never risk more than you can afford to lose.

---

**Made for Discord traders who want to automate their execution**

[Download Latest Release](https://github.com/DiscordTrader/BotifyTrades/releases) | [Report Issues](https://github.com/DiscordTrader/BotifyTrades/issues)
