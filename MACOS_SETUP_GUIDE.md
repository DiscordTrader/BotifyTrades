# BotifyTrades — macOS Setup Guide

Complete step-by-step instructions to clone, install, configure, and run BotifyTrades on macOS.

---

## Prerequisites

- macOS 12 (Monterey) or later
- Internet connection
- A Discord account (for the self-bot token)
- At least one broker account (Webull, Alpaca, Schwab, etc.)

---

## Step 1: Install Homebrew (if not already installed)

Open **Terminal** (press `Cmd + Space`, type "Terminal", hit Enter) and run:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After it finishes, follow any on-screen instructions to add Homebrew to your PATH (it will tell you exactly what to paste).

Verify it works:

```bash
brew --version
```

---

## Step 2: Install Python 3.11

```bash
brew install python@3.11
```

Verify the version:

```bash
python3.11 --version
```

You should see something like `Python 3.11.x`.

---

## Step 3: Install Git (if not already installed)

```bash
brew install git
```

Verify:

```bash
git --version
```

---

## Step 4: Clone the Repository

Navigate to where you want the project (e.g., your home folder):

```bash
cd ~
git clone <YOUR_REPO_URL> BotifyTrades
cd BotifyTrades
```

Replace `<YOUR_REPO_URL>` with your actual Git repository URL.

---

## Step 5: Create a Virtual Environment

```bash
python3.11 -m venv venv
source venv/bin/activate
```

Your terminal prompt should now show `(venv)` at the beginning. You must run `source venv/bin/activate` every time you open a new Terminal window before running the bot.

---

## Step 6: Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Note:** The `pywin32` package in requirements.txt is Windows-only and will be automatically skipped on macOS.

If you see errors about `PySide6`, you can safely ignore it — it is only used for the optional system tray icon on Windows. The bot and web dashboard work without it.

---

## Step 7: Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Open it in a text editor:

```bash
nano .env
```

Fill in at minimum:

| Variable | Description | How to Get It |
|---|---|---|
| `DISCORD_USER_TOKEN` | Your Discord self-bot token | See Step 8 below |
| `WEBULL_ACCESS_TOKEN` | Webull access token | From Webull browser cookies |
| `WEBULL_REFRESH_TOKEN` | Webull refresh token | From Webull browser cookies |
| `WEBULL_DID` | Webull device ID | From Webull browser cookies |
| `WEBULL_TRADE_PIN` | Your 6-digit Webull trading PIN | Your Webull PIN |

Save and close (`Ctrl + X`, then `Y`, then `Enter` in nano).

**Tip:** You can also configure all credentials later through the Web GUI (Step 10).

---

## Step 8: Get Your Discord Token

1. Open **Discord in a web browser** (not the desktop app): https://discord.com/app
2. Log in to your account
3. Press `Cmd + Option + I` to open Developer Tools
4. Click the **Console** tab
5. Paste this and press Enter:

```javascript
(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
```

6. Copy the token that appears (long string in quotes)
7. Paste it into your `.env` file as `DISCORD_USER_TOKEN` (without quotes)

---

## Step 9: Important — macOS Port 5000 Conflict

macOS Monterey and later uses **port 5000 for AirPlay Receiver**. BotifyTrades uses port 5000 for its web dashboard. You have two options:

**Option A (Recommended): Disable AirPlay Receiver**

1. Open **System Settings** (or System Preferences on older macOS)
2. Go to **General** > **AirDrop & Handoff**
3. Turn OFF **AirPlay Receiver**

**Option B: Use a Different Port**

Set a custom port before starting the bot:

```bash
export GUI_PORT=8080
```

Then access the dashboard at `http://localhost:8080` instead of `http://localhost:5000`.

---

## Step 10: Start the Bot

Make sure your virtual environment is activated (you should see `(venv)` in your prompt):

```bash
source venv/bin/activate
```

Then start the bot:

```bash
python src/selfbot_webull.py
```

You should see startup messages:

```
============================================================
BUILD VERSION: DEV
============================================================
[DATABASE] ✓ Database initialized
[CONFIG] ✓ All settings loaded successfully
[GUI] ✓ Web control panel started on port 5000
[MAIN] ✓ Discord bot is ready and connected
```

---

## Step 11: Open the Web Dashboard

Open your browser and go to:

```
http://localhost:5000
```

(or `http://localhost:8080` if you changed the port)

From the dashboard you can:

- Connect and configure brokers (Webull, Alpaca, Schwab, Robinhood, IBKR, Tastytrade)
- Set up Discord channel monitoring
- Configure risk management (stop-loss, profit targets, trailing stops)
- View active positions and trade history
- Manage all settings without editing config files

---

## Step 12: Configure Broker Credentials (via Web GUI)

In the web dashboard, go to **Settings** and configure your broker(s):

### Webull
- Access Token, Refresh Token, Device ID (DID), Trade PIN

### Alpaca (Paper Trading)
- API Key and Secret Key from https://alpaca.markets

### Schwab
- Uses OAuth2 — follow the in-app authorization flow

### Robinhood
- Username, Password, and optional MFA code

---

## Running in the Background

To keep the bot running after you close the Terminal:

```bash
nohup python src/selfbot_webull.py > bot_output.log 2>&1 &
```

To stop it later:

```bash
pkill -f selfbot_webull.py
```

To view the live log:

```bash
tail -f bot_output.log
```

---

## Updating from Git

When there are updates available:

```bash
cd ~/BotifyTrades
source venv/bin/activate
git pull origin main
pip install -r requirements.txt
```

Then restart the bot.

---

## Troubleshooting

### "Command not found: python3.11"
Run `brew install python@3.11` and make sure Homebrew's bin directory is in your PATH.

### "Address already in use" (port 5000)
Either disable AirPlay Receiver (see Step 9) or use `export GUI_PORT=8080`.

### "ModuleNotFoundError"
Make sure your virtual environment is activated: `source venv/bin/activate`

### Bot connects but no trades execute
- Check that Discord channels are configured in the web dashboard
- Verify broker credentials are correct
- Check the `logs/bot.log` file for detailed error messages

### SSL Certificate errors
```bash
pip install certifi
```

### Web dashboard not loading
- Verify the bot is running (check Terminal for errors)
- Try `http://127.0.0.1:5000` instead of `localhost`
- Check if another app is using port 5000

---

## Quick Reference

| Action | Command |
|---|---|
| Activate environment | `source venv/bin/activate` |
| Start bot | `python src/selfbot_webull.py` |
| Start bot (background) | `nohup python src/selfbot_webull.py > bot_output.log 2>&1 &` |
| Stop bot (background) | `pkill -f selfbot_webull.py` |
| View logs | `tail -f logs/bot.log` |
| Open dashboard | `http://localhost:5000` |
| Update from Git | `git pull origin main && pip install -r requirements.txt` |
| Change port | `export GUI_PORT=8080` |
