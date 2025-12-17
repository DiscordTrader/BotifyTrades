# BotifyTrades

Automated Discord Trading Bot for Webull, Alpaca, Interactive Brokers & Tastytrade

BotifyTrades is an advanced cross-platform Discord self-bot designed to monitor trading signal channels and automatically execute trades across multiple brokerages. It is a perfect solution for traders following Discord alert services who want automated trade execution.

## Key Features

### Multi-Broker Support
- **Webull**: Live and paper trading with real-time market data.
- **Alpaca**: Commission-free stock and options trading.
- **Interactive Brokers (IBKR)**: Professional-grade execution.
- **Tastytrade**: Options-focused brokerage integration.

### Intelligent Signal Parsing
- **AI-Powered Learning**: Teach the bot new signal formats once, and it remembers forever.
- **Multi-Format Support**: Handles BTO, STC, stock alerts, options contracts, and more.
- **Per-Channel Configuration**: Different settings for specific Discord channels.
- **User Filtering**: Execute signals from trusted traders only.

### Advanced Risk Management
- **Tiered Profit Targets**: PT1, PT2, PT3 with automatic partial exits.
- **Stop Loss Protection**: Configurable stop losses per channel or globally.
- **Trailing Stops**: Lock in profits as trades move in your favor.
- **Slippage Protection**: Prevent overpaying on fast-moving options.
- **Position Sizing**: Fixed quantity, percentage of portfolio, or trader's specified size.

### Web Control Panel
- **Real-Time Dashboard**: Monitor positions, P&L, and trade history.
- **Professional GUI**: Dark-themed interface with live analytics.
- **AI Chat Assistant**: Manage the bot through natural conversation.
- **Leaderboard**: Performance tracking by channel and trader.
- **Portfolio Simulator**: Backtest strategies with historical data.

### Trade Analytics
- **P&L Tracking**: Comprehensive profit/loss reports with FIFO matching.
- **Win Rate Statistics**: Performance metrics by channel and trader.
- **Capital Requirements Calculator**: Calculate exact capital needs.
- **AI Post-Trade Analysis**: Insights for every trade powered by GPT.

## Supported Signal Formats

BotifyTrades understands various trading signal formats, including:
- `BTO AAPL 150C 12/20 @ 2.50`
- `STC TSLA 200P 1/17 @ 5.00`
- `AAPL 150C 12/20 entry 2.50`
- `Bought SPY 450C 0DTE @ 1.25`
- `6900c         ← SPX/NDX shorthand for 0DTE`
- `TRADE IDEA: NVDA 500C 1/17`

Don’t see your format? Teach the bot using the AI chat assistant!

## Quick Start

### Download
Get the latest release from the [Releases Page](https://github.com/DiscordTrader/BotifyTrades/releases).

### Requirements
- Python 3.8 or higher
- Discord account token
- Brokerage account(s) with API access
- License key (contact for pricing)

### Installation

#### Windows
```bash
# Extract the release ZIP
# Run the installer or execute directly:
python src/selfbot_webull.py
```

#### Linux
```bash
# Extract and install dependencies
pip install -r requirements.txt
# Run the bot
python src/selfbot_webull.py
```

### First-Time Setup
1. Launch the bot to start the setup wizard.
2. Create your admin account with email recovery.
3. Enter your Discord token.
4. Configure your broker credentials.
5. Add Discord channels to monitor.
6. Set your risk management preferences.

### Web GUI Dashboard
Access the control panel at `http://localhost:5000` after starting the bot.

#### Dashboard Features
- Live position monitoring with real-time prices.
- Trade history with filtering and search.
- Channel management and configuration.
- Broker credential management (encrypted).
- Risk settings per channel.
- Performance analytics and charts.
- AI-powered chat assistant.

### Configuration
All settings are managed through the web GUI. Example configuration options:

| Setting            | Description                                 |
|--------------------|---------------------------------------------|
| **Discord Channels** | Channels to monitor for signals             |
| **Broker Selection**  | Brokerage to use per channel               |
| **Position Sizing**   | Fixed amount or percentage of portfolio    |
| **Profit Targets**    | PT1/PT2/PT3 percentages and quantities     |
| **Stop Loss**         | Automatic stop loss percentage            |
| **Trailing Stop**     | Enable/Disable trailing stops             |
| **Slippage**          | Maximum acceptable price deviation        |
| **User Filter**       | Trade signals only from specific users    |

## Deployment Options
- **Local Machine**: Use on your Windows/Mac/Linux computer.
- **Cloud VPS**: Deploy to AWS, DigitalOcean, or any Linux server.
- **24/7 Operation**: Systemd service for Linux auto-start.

## Security
- All broker credentials are encrypted at rest.
- License keys are machine-bound for protection.
- No credentials are ever transmitted externally.
- Open-source signal parsing for transparency and auditing.

## Support
- **Documentation**: Available with each release.
- **Issues**: Open a GitHub issue for bugs or features.
- **Community Discord**: Join for help and discussion.

## License
BotifyTrades is proprietary software. A valid license key is required. Contact for licensing and pricing details.

## Disclaimer
Trading stocks and options involves substantial risk. BotifyTrades is a tool to automate execution for chosen signals. Past performance does not guarantee future results. Always paper trade first and never risk more than you can afford.

---

Made for Discord traders who want to automate their execution.

[Download Latest Release](https://github.com/DiscordTrader/BotifyTrades/releases) | [Report Issues](https://github.com/DiscordTrader/BotifyTrades/issues)