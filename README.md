# BotifyTrades - Discord Trading Bot

**Version 3.5.0** | Multi-Broker Discord Trading Automation

A Discord self-bot that automatically detects BTO/STC trading signals in Discord channels and executes trades across multiple brokers (Webull, Alpaca, Tastytrade, IBKR, Robinhood).

## What's New in v3.5.0 (Milestone 5)
- Fixed database synchronization bugs for reliable trade tracking
- Quantity sync from broker positions in real-time
- 60-second grace period prevents premature trade closures
- Order ID tracking for proper trade-to-order matching
- Broker name normalization for consistency

## ⚠️ Important Disclaimers

1. **Discord Self-Bots**: Using self-bots violates Discord's Terms of Service and may result in account termination. Use at your own risk.
2. **Trading Risk**: This bot executes real trades with real money. Always test with paper trading first.
3. **No Warranty**: This software is provided as-is with no guarantees. You are responsible for all trades executed.

## Features

- ✅ **Multi-Broker Support**: Webull, Alpaca, Tastytrade, IBKR, Robinhood
- ✅ **Options & Stocks**: Full support for both asset types
- ✅ **Paper Trading**: Safe testing with Alpaca Paper, IBKR Paper
- ✅ **Risk Management**: Automated stop-loss, profit targets, trailing stops
- ✅ **Web Control Panel**: Flask-based GUI for easy management
- ✅ **Real-time Sync**: Database stays synchronized with broker positions
- ✅ **AI Signal Learning**: Teach custom signal formats once, use forever
- ✅ **Per-Channel Settings**: Independent risk settings per Discord channel
- ✅ **PNL Tracking**: Comprehensive profit/loss analytics and leaderboard

## Signal Formats

### Options
```
BTO 2 HOOD 67C 05/23 @0.74
BTO 1 RKLB 50c 11/14 @4.50
STC 1 AAPL 190P 11/15 @3.10
```

Format: `BTO/STC QTY SYMBOL STRIKE[C/P] MM/DD @PRICE`

### Stocks
```
BTO 10 AAPL @189.50
STC 5 AMD @128.20
```

Format: `BTO/STC QTY SYMBOL @PRICE`

## Deployment Options

### Option 1: Windows EXE (Standalone Executable)
**Best for:** Non-technical users, easy distribution

1. Download the pre-built EXE package
2. Follow setup guide in `EXE_SETUP.md`
3. No Python installation required
4. See `build_instructions.md` to build your own EXE

### Option 2: Run on Replit (Cloud)
**Best for:** Testing, development, 24/7 operation

- Use Replit Secrets for credentials (most secure)
- Keep browser tab open or use Reserved VM
- Follow setup instructions below

### Option 3: Run on Local Machine (Python)
**Best for:** Development, testing, full control

- Requires Python 3.11+
- Works on Windows, Mac, and Linux
- Full source code access and customization
- See detailed setup instructions below

---

## Local Machine Setup Guide

### Prerequisites

- **Python 3.11 or higher** ([Download here](https://www.python.org/downloads/))
- **pip** (Python package manager - included with Python)
- **Git** (optional, for cloning the repository)
- Stable internet connection

### Step 1: Download the Project

**Option A: Clone with Git**
```bash
git clone <your-repo-url>
cd discord-trading-bot
```

**Option B: Download ZIP**
1. Download this Replit as a ZIP file
2. Extract to a folder on your computer
3. Open terminal/command prompt in that folder

### Step 2: Install Dependencies

**Windows (Command Prompt or PowerShell):**
```bash
pip install -r requirements.txt
```

**Mac/Linux:**
```bash
pip3 install -r requirements.txt
```

**Manual Installation (if requirements.txt missing):**
```bash
pip install discord.py-self==2.0.1 webull==0.6.1 openai==2.0.0 yfinance==0.2.0 ta==0.11.0 aiohttp==3.9.0 requests==2.28.0
```

### Step 3: Configure Settings

1. Open `config.ini` in a text editor
2. Update channel IDs, trading settings, and preferences
3. Set `paper_trade = true` for testing (recommended)

```ini
[discord]
channel_ids = YOUR_CHANNEL_ID_1,YOUR_CHANNEL_ID_2

[webull]
paper_trade = true  # Start with paper trading!
```

### Step 4: Set Up Credentials

You have **two options** for credential storage:

#### Option A: Environment Variables (Recommended - More Secure)

**Windows (PowerShell):**
```powershell
$env:DISCORD_USER_TOKEN="your_discord_token_here"
$env:WEBULL_USERNAME="your_email@example.com"
$env:WEBULL_PASSWORD="your_password"
$env:WEBULL_TRADE_PIN="123456"
$env:FINNHUB_API_KEY="your_finnhub_key"
$env:ALPHA_VANTAGE_API_KEY="your_alphavantage_key"
$env:OPENAI_API_KEY="your_openai_key"
```

**Windows (Command Prompt):**
```cmd
set DISCORD_USER_TOKEN=your_discord_token_here
set WEBULL_USERNAME=your_email@example.com
set WEBULL_PASSWORD=your_password
set WEBULL_TRADE_PIN=123456
set FINNHUB_API_KEY=your_finnhub_key
set ALPHA_VANTAGE_API_KEY=your_alphavantage_key
set OPENAI_API_KEY=your_openai_key
```

**Mac/Linux:**
```bash
export DISCORD_USER_TOKEN="your_discord_token_here"
export WEBULL_USERNAME="your_email@example.com"
export WEBULL_PASSWORD="your_password"
export WEBULL_TRADE_PIN="123456"
export FINNHUB_API_KEY="your_finnhub_key"
export ALPHA_VANTAGE_API_KEY="your_alphavantage_key"
export OPENAI_API_KEY="your_openai_key"
```

**Make Environment Variables Permanent:**

Windows: Add to System Environment Variables via Control Panel
Mac/Linux: Add to `~/.bashrc` or `~/.zshrc`:
```bash
echo 'export DISCORD_USER_TOKEN="your_token"' >> ~/.bashrc
source ~/.bashrc
```

#### Option B: Interactive Setup Wizard (Easier for Beginners)

Simply run the bot without setting environment variables:
```bash
python src/selfbot_webull.py
```

The bot will prompt you to enter credentials interactively. They will be encrypted and saved locally.

**⚠️ Note for Mac/Linux users:** The encryption on Mac/Linux uses basic protection. Windows users get stronger encryption via DPAPI.

### Step 5: Get API Keys (Free)

**Discord User Token:**
1. Open Discord in your browser
2. Press F12 → Console tab
3. Paste: `(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()`
4. Copy the token

**Finnhub API Key (Free - 60 calls/min):**
- Sign up at https://finnhub.io/register
- Get your free API key from dashboard

**Alpha Vantage API Key (Free - 25-500 calls/day):**
- Get free key at https://www.alphavantage.co/support/#api-key

**OpenAI API Key:**
- Sign up at https://platform.openai.com/
- Create API key in dashboard
- *Alternative:* Use Replit AI integration (no OpenAI key needed)

### Step 6: Run the Bot

```bash
python src/selfbot_webull.py
```

You should see:
```
[Discord] ✓ Logged in as YourUsername#0
[Webull] ✓ Login successful
[Discord] ✓ Monitoring channels:
  - #channel-name in Server Name
[Init] ✓ Worker started; processing signals.
```

### Step 7: Test with Paper Trading

1. Ensure `paper_trade = true` in config.ini
2. Post a test signal in your monitored Discord channel:
   ```
   BTO AAPL 150C 12/20 @2.50
   ```
3. Check console logs - you should see the signal detected
4. Verify it's a paper trade (no real order placed)

---

## 24/7 Deployment Options

### Local Machine Limitations

⚠️ **Important:** When running on your local machine:
- Bot stops when you close the terminal/window
- Bot stops when your computer sleeps or shuts down
- Internet disconnections will stop the bot
- You must keep your computer running 24/7

### Recommended for 24/7 Trading

#### Option 1: Cloud VPS (Virtual Private Server)
**Best for:** Reliable 24/7 automated trading

**Providers:**
- **DigitalOcean** ($6/month) - [digitalocean.com](https://www.digitalocean.com/)
- **Linode/Akamai** ($5/month) - [linode.com](https://www.linode.com/)
- **AWS Lightsail** ($3.50/month) - [aws.amazon.com/lightsail/](https://aws.amazon.com/lightsail/)
- **Vultr** ($2.50/month) - [vultr.com](https://www.vultr.com/)

**VPS Setup:**
```bash
# 1. SSH into your VPS
ssh root@your-vps-ip

# 2. Install Python
sudo apt update
sudo apt install python3.11 python3-pip git -y

# 3. Clone your bot
git clone <your-repo>
cd discord-trading-bot

# 4. Install dependencies
pip3 install -r requirements.txt

# 5. Set environment variables
nano ~/.bashrc  # Add export commands

# 6. Run bot in background with screen/tmux
screen -S trading-bot
python3 src/selfbot_webull.py

# Press Ctrl+A, then D to detach
# Bot keeps running even after you disconnect!
```

#### Option 2: Keep Local Computer Running 24/7
- Disable sleep mode
- Configure auto-restart on crashes
- Use a dedicated computer (old laptop works great)

#### Option 3: Replit (Easiest, but costs credits)
- Already set up in this environment
- Automatic restarts
- Built-in secrets management
- No server maintenance required

---

## Comparison: Local vs Cloud vs Replit

| Feature | Local Machine | Cloud VPS | Replit |
|---------|--------------|-----------|---------|
| **Cost** | Free | $3-6/month | Uses credits |
| **24/7 Uptime** | ❌ (must keep PC on) | ✅ | ✅ |
| **Setup Difficulty** | Easy | Medium | Easiest |
| **Auto-restart** | ❌ | ✅ (with setup) | ✅ |
| **Customization** | ✅ Full | ✅ Full | ⚠️ Limited |
| **Security** | ⚠️ Your responsibility | ⚠️ Your responsibility | ✅ Built-in |
| **Best For** | Testing/Dev | Serious traders | Quick start |

---

## Setup Instructions

### 1. Configure Settings

Edit `config.ini`:

```ini
[discord]
channel_ids = YOUR_CHANNEL_ID_1,YOUR_CHANNEL_ID_2
allowed_author_ids = OPTIONAL_AUTHOR_ID_FILTER
allowed_guild_ids = OPTIONAL_GUILD_ID_FILTER

[webull]
paper_trade = true  # Set to false for live trading
```

### 2. Set Credentials via Replit Secrets (REQUIRED - ONLY SECURE METHOD)

**⚠️ SECURITY WARNING**: You MUST use Replit Secrets for all credentials. Never store credentials in config.ini.

Click the 🔒 **Secrets** icon in the left sidebar and add:

**Required Secrets:**
- `DISCORD_USER_TOKEN` - Your Discord user token
- `WEBULL_TRADE_PIN` - Your 6-digit trading PIN

**Choose ONE authentication method:**

**Method A: Username/Password (Will prompt for login)**
- `WEBULL_USERNAME` - Your Webull email
- `WEBULL_PASSWORD` - Your Webull password

**Method B: Saved Tokens (Faster, no login prompt)**
- `WEBULL_ACCESS_TOKEN` - Your Webull access token
- `WEBULL_REFRESH_TOKEN` - Your Webull refresh token
- `WEBULL_DID` - Your Webull device ID

**How to get your Discord user token:**
1. Open Discord in your browser
2. Press F12 to open Developer Tools
3. Go to Console tab
4. Paste: `(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()`
5. Copy the token and add it to Replit Secrets as `DISCORD_USER_TOKEN`

**How to get Webull tokens (Method B):**
1. Open https://app.webull.com in your browser and log in
2. Press F12 → Console tab
3. Paste this code:
```javascript
console.log(JSON.stringify({
  accessToken: sessionStorage.accessToken || localStorage.accessToken || localStorage.ACCESS_TOKEN || '',
  refreshToken: sessionStorage.refreshToken || localStorage.refreshToken || localStorage.REFRESH_TOKEN || '',
  did: sessionStorage.did || localStorage.did || sessionStorage.deviceId || localStorage.deviceId || ''
}));
```
4. Copy the values and add them to Replit Secrets as `WEBULL_ACCESS_TOKEN`, `WEBULL_REFRESH_TOKEN`, and `WEBULL_DID`

## Running the Bot

The bot will start automatically when you run the Repl. Check the console for:
- ✓ Discord login confirmation
- ✓ Webull login confirmation
- ✓ List of monitored channels
- ✓ Paper trading mode status

## Testing

1. **Start with paper trading enabled** (`paper_trade = true`)
2. Send a test signal in a monitored channel
3. Check console logs to verify signal detection
4. Verify the paper trade is logged (no real order placed)

## Safety Features

- **Paper Trading Mode**: Test without risking real money
- **Author Filtering**: Only accept signals from specific users
- **Guild Filtering**: Only monitor specific servers
- **Channel Filtering**: Only specific channels are monitored
- **Comprehensive Logging**: All actions are logged for review

## Troubleshooting

### Bot not detecting signals
- Verify channel IDs are correct in config.ini
- Check author/guild filters aren't blocking messages
- Review console logs for parsing errors

### Webull login fails
- Verify credentials are correct
- Check if 2FA is enabled (may need manual token bootstrap)
- Ensure trade PIN is exactly 6 digits

### Orders not executing
- Check if paper_trade is enabled
- Verify Webull account has sufficient funds
- Review console logs for specific errors

## Security Best Practices

1. ✅ Use environment variables for all sensitive data
2. ✅ Keep config.ini in .gitignore
3. ✅ Never share your Discord token or Webull credentials
4. ✅ Start with paper trading enabled
5. ✅ Monitor logs regularly for suspicious activity

## Support

This is unofficial software. For issues:
1. Check console logs for error messages
2. Verify all credentials are correct
3. Test with paper trading first
4. Review signal format carefully

## License

Use at your own risk. No warranty provided.
