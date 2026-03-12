# BotifyTrades — macOS Setup Guide

Complete step-by-step instructions to install and run BotifyTrades on your Mac.
No programming or coding knowledge required.

---

## What's in Your Package

When you download or receive BotifyTrades, you should have:

| File | What It Does |
|---|---|
| `BotifyTrades` | The main application (run this!) |
| `config.ini` | Trading settings configuration |
| `GET_DISCORD_TOKEN.html` | Easy one-click Discord token extractor |
| `GET_WEBULL_TOKENS.html` | Step-by-step Webull credential guide |

---

## System Requirements

- macOS 12 (Monterey) or later
- Active internet connection
- Discord account
- At least one broker account (Webull, Alpaca, Schwab, Robinhood, IBKR, or Tastytrade)
- ~500 MB free disk space

---

## Step 1: Extract the Files

1. Locate the downloaded BotifyTrades `.zip` file (usually in your **Downloads** folder)
2. **Double-click** the `.zip` file to extract it
3. A folder called `BotifyTrades` will appear
4. **Drag this folder** to a permanent location — your **Desktop** or **Documents** folder works great

---

## Step 2: Allow the App to Run (macOS Security)

macOS blocks apps from unidentified developers by default. You need to allow BotifyTrades to run:

### First Attempt

1. Open the `BotifyTrades` folder
2. **Right-click** (or Control-click) the `BotifyTrades` file
3. Select **Open** from the menu
4. A warning will appear — click **Open** to confirm

> If you double-click instead of right-clicking, macOS may block it with no "Open" option. Always **right-click → Open** the first time.

### If You See "BotifyTrades cannot be opened"

1. Open **System Settings** (click the Apple menu → System Settings)
2. Go to **Privacy & Security**
3. Scroll down — you will see a message like:
   *"BotifyTrades was blocked from use because it is not from an identified developer"*
4. Click **Open Anyway**
5. Enter your Mac password when prompted
6. Go back to the `BotifyTrades` folder and **double-click** the file again
7. Click **Open** in the final confirmation dialog

### Alternative: Remove Quarantine via Terminal

If the above doesn't work, open **Terminal** (press `Cmd + Space`, type "Terminal", hit Enter) and run:

```bash
xattr -rd com.apple.quarantine ~/Desktop/BotifyTrades/BotifyTrades
```

(Adjust the path if you placed the folder somewhere else, e.g., replace `Desktop` with `Documents`)

---

## Step 3: First Run — License Activation

When you run BotifyTrades for the first time:

1. **Double-click** `BotifyTrades` (or right-click → Open)
2. A Terminal window will open with the setup wizard
3. Your **Machine ID** will be displayed — a 16-character code unique to your Mac
4. **Copy your Machine ID** and send it to your bot provider to receive your license key
5. Once you have your license key, paste it when prompted
6. You will see a confirmation:

```
✅ LICENSE ACTIVATED SUCCESSFULLY!
✓ Customer: your_name
✓ Bound to machine: abc123def456ghi7
✓ Expires: 2026-04-12 12:30
✓ Days Remaining: 30
```

---

## Step 4: Get Your Discord Token

The setup wizard will ask for your Discord token. Here's how to get it:

### Easy Method (Recommended)

1. In your BotifyTrades folder, **double-click** `GET_DISCORD_TOKEN.html`
2. It opens in your web browser with a green button
3. **Drag the green button** to your browser's bookmarks bar
4. Go to https://discord.com/app and log in
5. **Click the bookmarklet** you just added to your bookmarks bar
6. Your token is automatically copied to your clipboard
7. Go back to the BotifyTrades setup wizard and **paste** it (`Cmd + V`)

### Manual Method

1. Open Discord in **Safari or Chrome** (not the desktop app): https://discord.com/app
2. Log in to your account
3. Press `Cmd + Option + I` to open Developer Tools
4. Click the **Console** tab
5. Paste this command and press `Enter`:

```javascript
(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
```

6. A long token string appears — **copy it** (highlight and `Cmd + C`)
7. Paste into the setup wizard

---

## Step 5: Configure Webull Credentials

The wizard will ask for your Webull credentials. You can use either method:

### Option A: Token Authentication (Recommended)

1. Open `GET_WEBULL_TOKENS.html` from your BotifyTrades folder
2. Follow the visual step-by-step guide to extract:
   - **Access Token**
   - **Refresh Token**
   - **Device ID (DID)**
3. Enter your **6-digit Webull trading PIN**
4. Paste each value into the setup wizard when prompted

### Option B: Username & Password

Simply enter your Webull email and password when the wizard asks.

---

## Step 6: Disable AirPlay Receiver (Important!)

macOS uses **port 5000** for AirPlay Receiver, which conflicts with the BotifyTrades web dashboard. You must disable it:

1. Click the **Apple menu** (top-left corner) → **System Settings**
2. Go to **General** → **AirDrop & Handoff**
3. Turn **OFF** the **AirPlay Receiver** toggle

> Without this step, the web dashboard will not load.

---

## Step 7: Start Trading

1. **Double-click** `BotifyTrades` to launch
2. The bot will start and you will see:

```
============================================================
BotifyTrades — Automated Trading Platform
============================================================
[DATABASE] ✓ Database initialized
[CONFIG]   ✓ All settings loaded successfully
[GUI]      ✓ Web control panel started on port 5000
[MAIN]     ✓ Discord bot is ready and connected
```

3. **Keep the Terminal window open** — closing it stops the bot

---

## Step 8: Open the Web Dashboard

While the bot is running, open your web browser and go to:

```
http://localhost:5000
```

From the dashboard you can:

- View and manage active positions
- Connect additional brokers (Alpaca, Schwab, Robinhood, IBKR, Tastytrade)
- Set up Discord channel monitoring
- Configure risk management (stop-loss, profit targets, daily P&L limits)
- View full trade history and performance analytics
- Adjust all settings without editing files

---

## Step 9: Configure Additional Brokers (Optional)

In the web dashboard, click **Settings** to add more brokers:

| Broker | What You Need |
|---|---|
| **Webull** | Access Token, Refresh Token, Device ID, Trade PIN |
| **Alpaca** | API Key + Secret Key (free at https://alpaca.markets) |
| **Schwab** | OAuth2 — follow the in-app authorization flow |
| **Robinhood** | Username, Password, optional MFA code |
| **IBKR** | TWS/Gateway connection settings |
| **Tastytrade** | Username + Password |

---

## Daily Usage

Every time you want to run the bot:

1. Open the `BotifyTrades` folder
2. **Double-click** `BotifyTrades`
3. Wait for the startup messages to appear
4. Open `http://localhost:5000` in your browser to monitor
5. **Leave the Terminal window open** while trading

To stop the bot: close the Terminal window, or press `Ctrl + C` in the Terminal.

---

## Running the Bot in the Background

If you want the bot to keep running even after closing the Terminal:

1. Open **Terminal** (press `Cmd + Space`, type "Terminal", hit Enter)
2. Navigate to your BotifyTrades folder:

```bash
cd ~/Desktop/BotifyTrades
```

3. Start the bot in the background:

```bash
nohup ./BotifyTrades > bot_output.log 2>&1 &
```

4. You can now close Terminal — the bot keeps running

To check if it's still running:

```bash
ps aux | grep BotifyTrades
```

To stop it:

```bash
pkill -f BotifyTrades
```

To view the live log:

```bash
tail -f ~/Desktop/BotifyTrades/bot_output.log
```

---

## Updating BotifyTrades

When you receive a new version:

1. **Stop the bot** (close Terminal or press `Ctrl + C`)
2. Replace the `BotifyTrades` file in your folder with the new one
3. **Right-click → Open** the new file (macOS security step — first time only)
4. Your settings, license, and credentials are preserved automatically

---

## Troubleshooting

### "BotifyTrades can't be opened because Apple cannot check it for malicious software"
Right-click the file → click **Open** → click **Open** again. Or go to System Settings → Privacy & Security → click **Open Anyway**. See Step 2 for full instructions.

### "Permission denied" when trying to run
Open Terminal and make the file executable:
```bash
chmod +x ~/Desktop/BotifyTrades/BotifyTrades
```

### Web dashboard not loading at localhost:5000
- Make sure the bot is running (Terminal window should be open with startup messages)
- Disable AirPlay Receiver (see Step 6)
- Try `http://127.0.0.1:5000` instead
- If still not working, try a different port: before launching the bot, open Terminal and run:
  ```bash
  export GUI_PORT=8080
  ./BotifyTrades
  ```
  Then open `http://localhost:8080`

### "Invalid or expired license"
Contact support for a license renewal. Your Machine ID is shown when the bot starts.

### "Discord token error"
Your Discord token may have expired. Get a new one using `GET_DISCORD_TOKEN.html` (see Step 4) and re-enter it in the web dashboard under Settings.

### Bot not executing trades
- Check that Discord channels are configured in the web dashboard
- Verify broker credentials are correct under Settings
- Check the Terminal window for error messages

### Bot crashes on startup
- Make sure you have an active internet connection
- Verify macOS is version 12 or later (Apple menu → About This Mac)
- Try running from Terminal to see the error:
  ```bash
  cd ~/Desktop/BotifyTrades
  ./BotifyTrades
  ```

---

## Important Safety Notes

- **Start with paper trading** — enable `paper_trade` in Settings before using real money
- **Monitor the bot** — check positions regularly through the web dashboard
- **Keep your credentials secure** — never share your Discord token, license key, or broker credentials
- **Your license is hardware-locked** — it only works on this specific Mac. Contact support if you get a new computer.

---

## Quick Reference

| Action | How |
|---|---|
| Start bot | Double-click `BotifyTrades` |
| Stop bot | Close Terminal window or press `Ctrl + C` |
| Open dashboard | Go to `http://localhost:5000` in browser |
| Run in background | `nohup ./BotifyTrades > bot_output.log 2>&1 &` |
| Stop background bot | `pkill -f BotifyTrades` |
| Fix macOS security block | Right-click → Open → Open |
| Fix permission denied | `chmod +x BotifyTrades` |
| Fix port 5000 conflict | Disable AirPlay Receiver in System Settings |

---

## Support

If you need help:
- Include your **Machine ID** (shown when the bot starts)
- Describe what happened and any error messages you see
- Take a screenshot of the Terminal window if possible
