# Discord Trading Bot - Windows EXE Setup Guide

⚠️ **CRITICAL WARNINGS - READ BEFORE USING** ⚠️

1. **Discord Terms of Service Violation**: This bot is a self-bot which **explicitly violates Discord's Terms of Service**. Using this may result in **permanent account termination**. 

2. **Trading Risk**: This bot executes **real trades with real money**. You can lose your entire investment.

3. **Legal Liability**: Using this software for commercial purposes or distributing it may expose you to legal liability. This software violates Discord's ToS and should be used for **personal use only at your own risk**.

4. **No Warranty**: This software is provided AS-IS with absolutely no guarantees or warranty of any kind.

By continuing, you acknowledge these risks and agree to use this software solely at your own risk.

---

## Quick Start

### Step 1: Extract Files
Extract the downloaded ZIP file to a folder on your computer (e.g., `C:\TradingBot\`)

### Step 2: Configure Settings

1. **Copy the configuration template:**
   - Find `config.ini.example`
   - Copy it and rename to `config.ini`

2. **Edit config.ini:**
   - Open `config.ini` with Notepad
   - Update the channel IDs to your Discord channels
   - Save the file

### Step 3: Run the Bot (First Time)

**Interactive Setup Wizard:**

1. Double-click `DiscordTradingBot.exe`
2. The **interactive setup wizard** will automatically launch on first run
3. **Choose your license option:**
   - **Option 1: 🆓 7-Day FREE Trial** - No license key needed! The wizard will automatically generate a 7-day trial license for you
   - **Option 2: 💳 Subscription License** - Enter your purchased license key
4. Follow the prompts to enter:
   - Discord user token
   - Webull tokens OR username/password
   - 6-digit trading PIN
5. Credentials are **encrypted and stored locally** at:
   - `C:\Users\YourName\.discord_trading_bot\credentials.enc`
6. The bot will then start automatically

**Important Notes:**
- You only need to run the setup wizard once
- Credentials are encrypted using **Windows DPAPI** (Data Protection API)
- Only your Windows user account can decrypt the credentials
- Never share your credentials or the encrypted file
- To reconfigure, delete the `.discord_trading_bot` folder in your user directory and restart
- **Security**: DPAPI ties encryption to your Windows account - credentials cannot be decrypted on another computer or by another user

### Step 4: Using the Bot

After initial setup:

1. Double-click `DiscordTradingBot.exe` to start
2. Bot loads saved credentials automatically
3. Console shows position updates and signals
4. Leave window open while bot runs
5. Press Ctrl+C to stop the bot

## Distribution Package

When distributing the EXE to others, include these files:

```
TradingBot/
├── DiscordTradingBot.exe    ← Main executable
├── config.ini.example        ← Configuration template
├── EXE_SETUP.md             ← This setup guide
└── README.md                ← User documentation
```

**Do NOT include:**
- Your personal `config.ini` (contains channel IDs)
- Any files with credentials or tokens

## Getting Your Credentials

### Discord User Token
1. Open Discord in browser (not app)
2. Press F12 to open Developer Tools
3. Go to Console tab
4. Type: `(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()`
5. Copy the token (without quotes)

### Webull Tokens
Run this Python script once to get your tokens:

```python
from webull import webull
wb = webull()
wb.login('your_email@example.com', 'your_password')
print(f"Access Token: {wb.access_token}")
print(f"Refresh Token: {wb.refresh_token}")
print(f"Device ID: {wb.did}")
```

Save these tokens - you'll need them for the environment variables.

## Troubleshooting

### "The system cannot find the path specified"
- Make sure `config.ini` exists in the same folder as the EXE
- Check that environment variables are set correctly

### "Discord login failed"
- Verify your DISCORD_USER_TOKEN is correct
- Token may have expired - get a new one

### "Webull login failed"
- Check your Webull tokens are valid
- Tokens expire - you may need to re-login and get new ones

### Bot doesn't respond to signals
- Verify channel_ids in config.ini match your Discord channels
- Check that the bot account is a member of those channels
- Ensure `discovery_mode = true` in config.ini

## Security Notes

⚠️ **Important Security Warnings:**

1. **Never share your tokens** - They give full access to your accounts
2. **Keep credentials private** - Don't commit them to Git or share screenshots
3. **Environment variables are secure** - Better than storing in files
4. **EXE can be decompiled** - Don't distribute with your personal credentials

## Support

For issues or questions, check the main README.md file for:
- Signal format examples
- Configuration options
- Risk management settings
- Common troubleshooting

---

**Disclaimer:** This is a self-bot which violates Discord's Terms of Service. Use at your own risk. The bot executes real trades with real money - always test with paper trading first.
