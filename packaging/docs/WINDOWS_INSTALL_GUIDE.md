# Discord Trading Bot - Windows Installation Guide

## Quick Start (5 Minutes)

### Step 1: Download Files
1. Download this entire `Windows_Distribution` folder
2. Extract to `C:\DiscordBot` (or any location you prefer)

### Step 2: Install Python
1. Download Python 3.11+ from https://www.python.org/downloads/
2. **IMPORTANT**: Check "Add Python to PATH" during installation
3. Verify installation:
   ```cmd
   python --version
   ```

### Step 3: Install Dependencies
Open Command Prompt in the bot folder:
```cmd
cd C:\DiscordBot
pip install -r requirements.txt
```

### Step 4: Configure Your Bot
Edit `config.ini` and add your credentials:

```ini
[discord]
discord_user_token = YOUR_DISCORD_TOKEN_HERE

[webull]
access_token = YOUR_WEBULL_ACCESS_TOKEN
refresh_token = YOUR_WEBULL_REFRESH_TOKEN
did = YOUR_WEBULL_DID
trade_pin = YOUR_6_DIGIT_PIN
```

#### How to Get Discord Token:
1. Open Discord in Chrome/Edge browser (not the app)
2. Press F12 (Developer Tools)
3. Go to Console tab
4. Paste this command:
   ```javascript
   (webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
   ```
5. Copy the entire token (70 characters)

#### How to Get Webull Tokens:
Run this once in Python:
```python
from webull import webull
wb = webull()
wb.login('your_email@example.com', 'your_password')
print(f"access_token = {wb.access_token}")
print(f"refresh_token = {wb.refresh_token}")
print(f"did = {wb.did}")
```

### Step 5: Update Channel IDs
In `config.ini`, set the channels you want to monitor:
```ini
[discord]
channel_ids = 123456789, 987654321
```

To find channel IDs:
1. Right-click any channel in Discord
2. Click "Copy Channel ID"

### Step 6: Run the Bot
```cmd
cd C:\DiscordBot
python src\selfbot_webull.py
```

## Security Warnings

⚠️ **CRITICAL WARNINGS:**
- This violates Discord's Terms of Service - use at your own risk
- Never share your Discord token or Webull credentials
- The bot executes REAL trades with REAL money
- Always test with `paper_trade = true` first

## Testing

Before enabling live trading:
1. Set `paper_trade = true` in config.ini
2. Run the bot and test with fake signals
3. Verify trades execute correctly in paper mode
4. Only then set `paper_trade = false` for live trading

## Troubleshooting

### "Improper token" Error
- Get a fresh token from Discord browser
- Make sure you copied the ENTIRE 70-character token
- No spaces before/after the token in config.ini

### "Module not found" Error
```cmd
pip install -r requirements.txt
```

### Bot doesn't see messages
- Enable `discovery_mode = true` to see all messages
- Verify your channel IDs are correct
- Check that you're in the Discord channels

## Configuration Options

### Risk Management
```ini
[risk_management]
enable_risk_management = true
profit_target_percent = 20    # Sell at 20% profit
stop_loss_percent = 10         # Sell at 10% loss
trailing_stop_percent = 5      # 5% trailing stop
```

### Signal Patterns
The bot recognizes:
- Options: `BTO 10 AAPL 150 C 12/19 @2.50`
- Stocks: `BTO 100 TSLA @250.00`
- With $ signs: `BTO $AAPL 150C 12/19 @2.50`
- Auto quantity: `BTO AAPL 150C 12/19 @2.50` (calculates qty from max_position_size)

## Support

This is a self-hosted bot. For issues:
1. Check logs for error messages
2. Verify all credentials are correct
3. Test with paper trading first
4. Review configuration settings

## Legal Disclaimer

This software is provided "as is" without warranty. Use at your own risk. The authors are not responsible for:
- Trading losses
- Discord account bans
- Webull account issues
- Any other damages
