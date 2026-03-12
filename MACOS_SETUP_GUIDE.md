# BotifyTrades v6.2.6 — macOS Setup Guide

Complete step-by-step instructions to install and run BotifyTrades on your Mac.
No programming or coding knowledge required.

---

## Which Download Do I Need?

| Your Mac Type | Download File |
|---|---|
| **Apple Silicon** (M1, M2, M3, M4) | `BotifyTrades-macOS-Silicon.tar.gz` |
| **Intel-based Mac** | `BotifyTrades-macOS-Intel.tar.gz` |

**Not sure which Mac you have?** Click the **Apple menu** (top-left corner) → **About This Mac**.
- If it says **Apple M1/M2/M3/M4** → download the **Silicon** version
- If it says **Intel** → download the **Intel** version

---

## Step 1: Download

Go to the BotifyTrades releases page and download the `.tar.gz` file for your Mac type.
The file will appear in your **Downloads** folder.

---

## Step 2: Extract the File

### Option A: Double-Click (Easiest)

1. Open **Finder** and go to your **Downloads** folder
2. **Double-click** the `BotifyTrades-macOS-Silicon.tar.gz` (or `Intel.tar.gz`) file
3. macOS will extract it automatically — a `BotifyTrades` file will appear in the same folder

### Option B: Using Terminal

1. Open **Terminal** (press `Cmd + Space`, type "Terminal", hit Enter)
2. Run:

```bash
cd ~/Downloads
tar -xzf BotifyTrades-macOS-Silicon.tar.gz
```

(Replace `Silicon` with `Intel` if you downloaded the Intel version)

---

## Step 3: Move to a Permanent Location

Drag the extracted `BotifyTrades` file (or folder) to a permanent location. We recommend creating a folder on your **Desktop**:

1. On your Desktop, **right-click** → **New Folder** → name it `BotifyTrades`
2. Move the extracted file into that folder

---

## Step 4: Make It Executable and Allow It to Run

macOS requires two things before you can run a downloaded application: it needs permission to execute, and it needs to bypass the security check for unidentified developers.

Open **Terminal** (press `Cmd + Space`, type "Terminal", hit Enter) and run these two commands:

```bash
chmod +x ~/Desktop/BotifyTrades/BotifyTrades
```

```bash
xattr -rd com.apple.quarantine ~/Desktop/BotifyTrades/BotifyTrades
```

- The first command gives the file permission to run as a program
- The second command removes the macOS quarantine flag so it won't be blocked

> **Adjust the path** if you placed the file somewhere other than `~/Desktop/BotifyTrades/`

---

## Step 5: Run BotifyTrades

Still in Terminal, start the bot:

```bash
~/Desktop/BotifyTrades/BotifyTrades
```

You should see the bot start up:

```
============================================================
BotifyTrades v6.2.6 — Automated Trading Platform
============================================================
[DATABASE] ✓ Database initialized
[CONFIG]   ✓ All settings loaded successfully
[GUI]      ✓ Web control panel started on port 5000
[MAIN]     ✓ Discord bot is ready and connected
```

**Keep this Terminal window open** — closing it stops the bot.

---

## Step 6: If macOS Still Blocks It

If you see a message like *"BotifyTrades can't be opened because Apple cannot check it for malicious software"*:

1. Click the **Apple menu** (top-left corner) → **System Settings**
2. Go to **Privacy & Security**
3. Scroll down — you will see:
   *"BotifyTrades was blocked from use because it is not from an identified developer"*
4. Click **Open Anyway**
5. Enter your Mac password when prompted
6. Go back to Terminal and run the command from Step 5 again

---

## Step 7: First Run — License Activation

On the first run, the setup wizard will appear:

1. Your **Machine ID** will be displayed — a 16-character code unique to your Mac
2. **Copy your Machine ID** and send it to your bot provider to receive your license key
3. Once you have your license key, paste it when prompted
4. You will see:

```
✅ LICENSE ACTIVATED SUCCESSFULLY!
✓ Customer: your_name
✓ Bound to machine: abc123def456ghi7
✓ Expires: 2026-04-12 12:30
✓ Days Remaining: 30
```

---

## Step 8: Get Your Discord Token

The setup wizard will ask for your Discord token:

1. Open Discord in **Safari or Chrome** (not the desktop app): https://discord.com/app
2. Log in to your account
3. Press `Cmd + Option + I` to open Developer Tools
4. Click the **Console** tab
5. Paste this command and press `Enter`:

```javascript
(webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
```

6. A long token string appears — **copy it** (`Cmd + C`)
7. Paste into the setup wizard (`Cmd + V`)

> **Tip:** If a `GET_DISCORD_TOKEN.html` file was included in your download, you can double-click it for an even easier one-click method.

---

## Step 9: Configure Webull Credentials

The wizard will ask for your Webull credentials:

- **Access Token** — from Webull browser cookies
- **Refresh Token** — from Webull browser cookies
- **Device ID (DID)** — from Webull browser cookies
- **6-digit Trading PIN** — your Webull PIN

> **Tip:** If a `GET_WEBULL_TOKENS.html` file was included in your download, double-click it for a visual step-by-step guide on extracting these values.

---

## Step 10: Disable AirPlay Receiver (Important!)

macOS Monterey and later uses **port 5000** for AirPlay Receiver, which conflicts with the BotifyTrades web dashboard.

1. Click the **Apple menu** → **System Settings**
2. Go to **General** → **AirDrop & Handoff**
3. Turn **OFF** the **AirPlay Receiver** toggle

> Without this step, the web dashboard will not load.

---

## Step 11: Open the Web Dashboard

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
- Adjust all settings without editing any files

---

## Step 12: Configure Additional Brokers (Optional)

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

1. Open **Terminal** (`Cmd + Space`, type "Terminal", hit Enter)
2. Run:

```bash
~/Desktop/BotifyTrades/BotifyTrades
```

3. Wait for the startup messages to appear
4. Open `http://localhost:5000` in your browser to monitor
5. **Leave Terminal open** while trading

To stop the bot: press `Ctrl + C` in the Terminal, or close the Terminal window.

---

## Running the Bot in the Background

If you want the bot to keep running even after closing Terminal:

```bash
nohup ~/Desktop/BotifyTrades/BotifyTrades > ~/Desktop/BotifyTrades/bot_output.log 2>&1 &
```

You can now close Terminal — the bot keeps running.

**Check if it's still running:**

```bash
ps aux | grep BotifyTrades
```

**Stop the background bot:**

```bash
pkill -f BotifyTrades
```

**View the live log:**

```bash
tail -f ~/Desktop/BotifyTrades/bot_output.log
```

---

## Updating to a New Version

When a new version is released:

1. **Stop the bot** (press `Ctrl + C` or run `pkill -f BotifyTrades`)
2. Download the new `.tar.gz` file from the releases page
3. Extract it (double-click or use `tar -xzf`)
4. Replace the old `BotifyTrades` file with the new one
5. Run the permission commands again:

```bash
chmod +x ~/Desktop/BotifyTrades/BotifyTrades
xattr -rd com.apple.quarantine ~/Desktop/BotifyTrades/BotifyTrades
```

6. Start the bot — your settings, license, and credentials are preserved automatically

---

## Troubleshooting

### "BotifyTrades can't be opened because Apple cannot check it for malicious software"
Run these commands in Terminal:
```bash
chmod +x ~/Desktop/BotifyTrades/BotifyTrades
xattr -rd com.apple.quarantine ~/Desktop/BotifyTrades/BotifyTrades
```
Then try running it again. If still blocked, go to System Settings → Privacy & Security → click **Open Anyway**.

### "Permission denied"
```bash
chmod +x ~/Desktop/BotifyTrades/BotifyTrades
```

### "zsh: exec format error"
You downloaded the wrong version for your Mac. Check which Mac you have (Apple menu → About This Mac) and download the correct one:
- Apple M1/M2/M3/M4 → `BotifyTrades-macOS-Silicon.tar.gz`
- Intel → `BotifyTrades-macOS-Intel.tar.gz`

### Web dashboard not loading at localhost:5000
- Make sure the bot is running (Terminal should show startup messages)
- Disable AirPlay Receiver (see Step 10)
- Try `http://127.0.0.1:5000` instead
- If still not working, use a different port:
  ```bash
  export GUI_PORT=8080
  ~/Desktop/BotifyTrades/BotifyTrades
  ```
  Then open `http://localhost:8080`

### "Invalid or expired license"
Contact support for a license renewal. Your Machine ID is shown when the bot starts.

### "Discord token error"
Your Discord token may have expired. Get a new one (see Step 8) and re-enter it in the web dashboard under Settings.

### Bot not executing trades
- Check that Discord channels are configured in the web dashboard
- Verify broker credentials are correct under Settings
- Check the Terminal window for error messages

### Bot crashes immediately
- Make sure you have an active internet connection
- Verify macOS is version 12 or later (Apple menu → About This Mac)
- Run from Terminal to see the full error output:
  ```bash
  ~/Desktop/BotifyTrades/BotifyTrades
  ```

---

## Important Safety Notes

- **Start with paper trading** — enable `paper_trade` in Settings before using real money
- **Monitor the bot** — check positions regularly through the web dashboard
- **Keep your credentials secure** — never share your Discord token, license key, or broker credentials
- **Your license is hardware-locked** — it only works on this specific Mac. Contact support if you get a new computer

---

## Quick Reference

| Action | Command |
|---|---|
| Run the bot | `~/Desktop/BotifyTrades/BotifyTrades` |
| Stop the bot | `Ctrl + C` in Terminal |
| Open dashboard | `http://localhost:5000` in browser |
| Run in background | `nohup ~/Desktop/BotifyTrades/BotifyTrades > ~/Desktop/BotifyTrades/bot_output.log 2>&1 &` |
| Stop background bot | `pkill -f BotifyTrades` |
| Fix security block | `chmod +x BotifyTrades && xattr -rd com.apple.quarantine BotifyTrades` |
| Fix port 5000 conflict | Disable AirPlay Receiver in System Settings |
| Check your Mac type | Apple menu → About This Mac |

---

## Support

If you need help:
- Include your **Machine ID** (shown when the bot starts)
- Describe what happened and any error messages you see
- Take a screenshot of the Terminal window if possible
