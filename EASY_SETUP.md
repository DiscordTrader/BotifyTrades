# ⚡ EASY SETUP GUIDE (Recommended Method)

This is the **easiest and most reliable** way to set up the bot on your local machine using a `.env` file.

---

## 🎯 Quick Start (3 Steps)

### Step 1: Download and Extract

1. In Replit, click **3-dot menu (⋮)** → **"Download as zip"**
2. Extract the zip to a folder (e.g., `C:\TradingBot`)

### Step 2: Install Python and Dependencies
##### Uday Botify
```bash
# Check if Python 3.11+ is installed
python --version

# If not installed, download from: https://python.org/downloads/

# Install dependencies
pip install -r requirements.txt
```

### Step 3: Create .env File

1. **Copy** the `.env.example` file
2. **Rename** it to `.env` (remove `.example`)
3. **Edit** `.env` and fill in your credentials:

```bash
DISCORD_USER_TOKEN=your_actual_discord_token
WEBULL_ACCESS_TOKEN=your_actual_access_token
WEBULL_REFRESH_TOKEN=your_actual_refresh_token
WEBULL_DID=your_actual_device_id
WEBULL_TRADE_PIN=123456
```

**⚠️ IMPORTANT:** NO quotes around the values!

---

## 🔑 Getting Your Credentials

### Discord Token

1. Open Discord in **Chrome/Firefox** (not the app!)
2. Press **F12** to open Developer Tools
3. Go to **Console** tab
4. Paste this code and press Enter:
   ```javascript
   (webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
   ```
5. Copy the token that appears
6. Paste it into your `.env` file as `DISCORD_USER_TOKEN=`

### Webull Tokens

1. Open **Webull website** in your browser and log in
2. Press **F12** → **Application** tab (Chrome) or **Storage** tab (Firefox)
3. Click **Cookies** → select Webull domain
4. Find and copy these cookies:
   - `access_token` → paste as `WEBULL_ACCESS_TOKEN=`
   - `refresh_token` → paste as `WEBULL_REFRESH_TOKEN=`
   - `did` → paste as `WEBULL_DID=`

### Trading PIN

Just your 6-digit Webull PIN for trading.

---

## ✅ Run the Bot

### Option A: Quick Validation + Run
```bash
# Validate your setup first
python test_setup.py

# If all checks pass, run the bot
python src/selfbot_webull.py
```

### Option B: Use Launcher (Windows)
```bash
# Double-click this file
run.bat
```

### Option C: Use Launcher (Mac/Linux)
```bash
chmod +x run.sh
./run.sh
```

---

## 🎉 Success!

You should see:
```
✓ Logged in as your_username
✓ Monitoring channels
✓ Login successful
✓ Worker started; processing signals.
```

---

## ❓ Troubleshooting

### "401 Unauthorized" Error

**Cause:** Invalid Discord token

**Fix:**
1. Get a fresh token (Discord tokens expire)
2. Make sure you copied the ENTIRE token
3. Make sure there are NO quotes in your `.env` file

### "Module not found" Error

**Fix:**
```bash
pip install -r requirements.txt
```

### Bot doesn't see messages

**Fix:**
1. Check `config.ini` has correct `channel_ids`
2. Make sure `allow_self_messages = true` if testing with your own account

### Still not working?

Check `TROUBLESHOOTING.md` for detailed solutions!

---

## 🔒 Security Notes

- ✅ `.env` file is already in `.gitignore` (safe)
- ✅ Never commit `.env` to git
- ✅ Never share your tokens
- ✅ Test with `paper_trade = true` first

---

## ⭐ Why This Method is Better

| Method | Ease of Use | Reliability | Cross-Platform |
|--------|-------------|-------------|----------------|
| ✅ `.env` file | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ✅ Works everywhere |
| Manual `set` command | ⭐⭐ | ⭐⭐ | ❌ Different per OS |
| System env vars | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ Complex setup |

**The .env file approach:**
- ✅ Works the same on Windows, Mac, and Linux
- ✅ No need to remember commands
- ✅ No need to set variables every time
- ✅ Easy to update and backup

---

**You're ready to trade!** 🚀
