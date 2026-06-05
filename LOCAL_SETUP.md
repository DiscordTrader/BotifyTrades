# Local Machine Setup Guide

This guide will help you run the Discord Trading Bot on your local computer (Windows, Mac, or Linux).

---

## 📋 Prerequisites

1. **Python 3.11** installed on your computer
   - Download from: https://www.python.org/downloads/
   - During installation, check "Add Python to PATH"

2. **Your credentials ready:**
   - Discord user token
   - Webull access token, refresh token, and DID
   - Webull trading PIN

---

## 🚀 Quick Start Guide

### Step 1: Download Files from Replit

1. In Replit, click the **3 dots menu** (⋮) next to "Files"
2. Click **"Download as zip"**
3. Extract the zip file to a folder on your computer (e.g., `C:\TradingBot` or `~/TradingBot`)

### Step 2: Install Python Dependencies

Open Terminal (Mac/Linux) or Command Prompt (Windows) in the bot folder:

```bash
# Navigate to the bot folder
cd path/to/your/bot/folder

# Install required packages
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables

**IMPORTANT:** Set these environment variables with your credentials.

#### Windows (Command Prompt) - RECOMMENDED:
```cmd
REM CRITICAL: NO quotes around values in Command Prompt!
set DISCORD_USER_TOKEN=your_discord_token_here
set WEBULL_ACCESS_TOKEN=your_webull_access_token
set WEBULL_REFRESH_TOKEN=your_webull_refresh_token
set WEBULL_DID=your_webull_device_id
set WEBULL_TRADE_PIN=123456
```

#### Windows (PowerShell):
```powershell
# NO quotes for PowerShell either
$env:DISCORD_USER_TOKEN=your_discord_token_here
$env:WEBULL_ACCESS_TOKEN=your_webull_access_token
$env:WEBULL_REFRESH_TOKEN=your_webull_refresh_token
$env:WEBULL_DID=your_webull_device_id
$env:WEBULL_TRADE_PIN=123456
```

#### Mac/Linux (Terminal):
```bash
export DISCORD_USER_TOKEN="your_discord_token_here"
export WEBULL_ACCESS_TOKEN="your_webull_access_token"
export WEBULL_REFRESH_TOKEN="your_webull_refresh_token"
export WEBULL_DID="your_webull_device_id"
export WEBULL_TRADE_PIN="123456"
```

**⚠️ COMMON MISTAKES:**
- ❌ Adding quotes on Windows Command Prompt/PowerShell
- ❌ Using wrong quote type (use `"` not `'` on Windows)
- ❌ Extra spaces before/after the value
- ❌ Setting variables in one terminal, running bot in another

**Note:** These environment variables only last for the current terminal session. See "Permanent Setup" below for a permanent solution.

### Step 4: Configure Channel IDs

Edit `config.ini` and make sure your Discord channel IDs are set:

```ini
[discord]
channel_ids = 551065756557639680, 1386424654209618050
```

### Step 5: Validate Your Setup (Recommended)

Before running the bot, validate everything is configured correctly:

```bash
python test_setup.py
```

This will check:
- ✅ Python version
- ✅ Required packages installed
- ✅ Environment variables set correctly
- ✅ Discord token format and length
- ✅ Config file exists

Fix any errors before continuing!

### Step 6: Run the Bot

In the same terminal window where you set the environment variables:

**Option A: Use the launcher (validates first):**
```bash
# Windows
run.bat

# Mac/Linux
./run.sh
```

**Option B: Run directly:**
```bash
python src/selfbot_webull.py
```

You should see:
```
✓ Logged in as your_username
✓ Monitoring channels
✓ Login successful
✓ Worker started; processing signals.
```

**If you get "401 Unauthorized" error:**
See `TROUBLESHOOTING.md` for detailed solutions!

---

## 🔒 Permanent Environment Variable Setup

### Windows (Permanent):

1. Press `Win + R`, type `sysdm.cpl`, press Enter
2. Go to **Advanced** tab → **Environment Variables**
3. Under "User variables", click **New** for each variable:
   - Variable name: `DISCORD_USER_TOKEN`
   - Variable value: `your_token_here`
4. Repeat for all 5 variables
5. Click OK, restart your terminal

### Mac/Linux (Permanent):

Add to your `~/.bashrc` or `~/.zshrc` file:

```bash
export DISCORD_USER_TOKEN="your_discord_token_here"
export WEBULL_ACCESS_TOKEN="your_webull_access_token"
export WEBULL_REFRESH_TOKEN="your_webull_refresh_token"
export WEBULL_DID="your_webull_device_id"
export WEBULL_TRADE_PIN="123456"
```

Then reload: `source ~/.bashrc` or `source ~/.zshrc`

---

## 🔄 Running Bot 24/7

### Option 1: Keep Terminal Open
- Just leave the terminal window open
- Bot will run as long as terminal is open and computer is on

### Option 2: Run as Background Process (Linux/Mac)

```bash
# Run in background
nohup python src/selfbot_webull.py &

# Check if running
ps aux | grep selfbot

# Stop the bot
pkill -f selfbot_webull.py
```

### Option 3: Run as Windows Service

Use a tool like **NSSM** (Non-Sucking Service Manager):
1. Download NSSM from: https://nssm.cc/download
2. Run: `nssm install TradingBot`
3. Set path to python.exe and arguments to `src/selfbot_webull.py`
4. Service will auto-start with Windows

---

## 📝 Configuration Reference

### config.ini Settings

```ini
[discord]
# Your Discord channel IDs (comma-separated)
channel_ids = 551065756557639680, 1386424654209618050

# Allow processing your own messages (for testing)
allow_self_messages = true

[webull]
# Trading settings
paper_trade = false  # Set to true for paper trading
time_in_force = GTC  # Good Till Cancelled
```

### Environment Variables Needed

| Variable | Description | Example |
|----------|-------------|---------|
| `DISCORD_USER_TOKEN` | Your Discord user token | `MTIzNDU2Nzg5...` |
| `WEBULL_ACCESS_TOKEN` | Webull access token | `eyJhbGciOiJ...` |
| `WEBULL_REFRESH_TOKEN` | Webull refresh token | `eyJhbGciOiJ...` |
| `WEBULL_DID` | Webull device ID | `q9etza5szyy3...` |
| `WEBULL_TRADE_PIN` | 6-digit trading PIN | `123456` |

---

## 🐛 Troubleshooting

### "Module not found" error
```bash
pip install --upgrade -r requirements.txt
```

### "Discord token invalid"
- Make sure your token is correct and not expired
- Token should NOT have quotes in environment variable

### "Webull login failed"
- Verify your access_token, refresh_token, and DID are correct
- Check that WEBULL_TRADE_PIN is set

### Bot doesn't see messages
- Make sure channel_ids in config.ini are correct
- Check that allow_self_messages is set appropriately

### Bot crashes on startup
- Check that all environment variables are set
- Verify config.ini exists and is properly formatted

---

## ⚠️ Important Notes

1. **Keep your computer on:** Bot stops if computer sleeps or shuts down
2. **Internet required:** Bot needs constant internet connection
3. **Discord TOS:** Self-bots violate Discord Terms of Service
4. **Live trading:** Set `paper_trade = true` for testing first
5. **Security:** Never share your tokens or PIN with anyone

---

## 🆘 Getting Help

If you encounter issues:

1. Check the console output for error messages
2. Verify all environment variables are set correctly
3. Make sure config.ini has the right channel IDs
4. Test with paper trading mode first
5. Check that Python 3.11+ is installed

---

## ✅ Quick Checklist

- [ ] Python 3.11+ installed
- [ ] Downloaded bot files from Replit
- [ ] Installed dependencies (`pip install -r requirements.txt`)
- [ ] Set all 5 environment variables
- [ ] Configured channel_ids in config.ini
- [ ] Set paper_trade = true for first test
- [ ] Run `python src/selfbot_webull.py`
- [ ] See "Worker started" message
- [ ] Test with a signal in monitored channel

---

**You're ready to trade!** 🚀
