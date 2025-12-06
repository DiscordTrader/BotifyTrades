# Troubleshooting Guide - Local Machine Setup

## Common Error: "401 Unauthorized - Improper token has been passed"

### What This Means
Your Discord user token is either:
- Not set in environment variables correctly
- Invalid or expired
- Has extra spaces or quotes around it

---

## ✅ Solution Steps

### Step 1: Verify Your Discord Token is Valid

1. Open Discord in your **browser** (not the app)
2. Press **F12** to open Developer Tools
3. Go to **Console** tab
4. Paste this code and press Enter:
   ```javascript
   (webpackChunkdiscord_app.push([[''],{},e=>{m=[];for(let c in e.c)m.push(e.c[c])}]),m).find(m=>m?.exports?.default?.getToken!==void 0).exports.default.getToken()
   ```
5. Copy the token that appears (it's a long string)

### Step 2: Set Environment Variable Correctly

**Important Rules:**
- ❌ **NO quotes** around the token value
- ❌ **NO spaces** before or after the token
- ❌ **NO extra characters**

#### Windows PowerShell:
```powershell
# WRONG - has quotes
$env:DISCORD_USER_TOKEN="your_token_here"

# CORRECT - no quotes
$env:DISCORD_USER_TOKEN=your_token_here
```

#### Windows Command Prompt:
```cmd
REM CORRECT way
set DISCORD_USER_TOKEN=your_actual_token_here
```

#### Mac/Linux:
```bash
# CORRECT way (quotes are okay in bash)
export DISCORD_USER_TOKEN="your_token_here"
```

### Step 3: Verify Environment Variable is Set

**Windows:**
```cmd
echo %DISCORD_USER_TOKEN%
```

**PowerShell:**
```powershell
echo $env:DISCORD_USER_TOKEN
```

**Mac/Linux:**
```bash
echo $DISCORD_USER_TOKEN
```

You should see your token printed. If it says nothing or shows the variable name itself, it's not set.

### Step 4: Run Bot in Same Terminal

**CRITICAL:** You must run the bot in the **same terminal window** where you set the environment variable!

```bash
# Set the variable
set DISCORD_USER_TOKEN=your_token

# Run bot IMMEDIATELY in same window
python src/selfbot_webull.py
```

---

## Package Validation (Optional)

If you want to check for package conflicts:

### Check Installed Packages
```bash
pip list
```

### Uninstall All Discord Packages
```bash
pip uninstall discord discord.py discord.py-self -y
```

### Reinstall Correct Version
```bash
pip install discord.py-self==2.0.1
```

### Verify Installation
```bash
python -c "import discord; print(discord.__version__)"
```

---

## Testing Your Setup

### Quick Test Script

Create a file `test_token.py`:

```python
import os

token = os.getenv('DISCORD_USER_TOKEN')

if not token:
    print("❌ DISCORD_USER_TOKEN not set!")
    print("Set it with: set DISCORD_USER_TOKEN=your_token")
else:
    print(f"✅ Token found: {token[:20]}...")
    print(f"✅ Token length: {len(token)} characters")
    
    # Discord tokens should be around 70+ characters
    if len(token) < 50:
        print("⚠️  Token seems too short! Make sure you copied the full token.")
    else:
        print("✅ Token length looks good!")
```

Run it:
```bash
python test_token.py
```

---

## Complete Setup Example (Windows)

```cmd
REM Step 1: Navigate to bot folder
cd C:\Docs\Trading\DiscordWebullBot\DiscordWebullBot

REM Step 2: Set ALL environment variables (no quotes!)
set DISCORD_USER_TOKEN=MTIzNDU2Nzg5MDEyMzQ1Njc4OTAuGabCdE.X1Y2Z3_long_token_here
set WEBULL_ACCESS_TOKEN=your_webull_access_token
set WEBULL_REFRESH_TOKEN=your_webull_refresh_token
set WEBULL_DID=your_device_id
set WEBULL_TRADE_PIN=123456

REM Step 3: Verify token is set
echo %DISCORD_USER_TOKEN%

REM Step 4: Run bot
python src/selfbot_webull.py
```

---

## Still Not Working?

### Check These:

1. **Token expired?** Discord tokens can expire. Get a fresh one from browser.

2. **Copied correctly?** Make sure you copied the ENTIRE token, no spaces at start/end.

3. **Using Discord app?** Token extraction only works in **browser**, not desktop app.

4. **Account locked?** Discord might have flagged your account. Check if you can log in normally.

5. **Running in same terminal?** Environment variables only last in the terminal session where they're set.

---

## Alternative: Use .env File (Easier)

Instead of setting env vars manually, create a `.env` file:

### Step 1: Install python-dotenv
```bash
pip install python-dotenv
```

### Step 2: Create `.env` file in bot folder
```
DISCORD_USER_TOKEN=your_token_here
WEBULL_ACCESS_TOKEN=your_access_token
WEBULL_REFRESH_TOKEN=your_refresh_token
WEBULL_DID=your_device_id
WEBULL_TRADE_PIN=123456
```

### Step 3: Update bot code to load .env

Add at the top of `selfbot_webull.py`:
```python
from dotenv import load_dotenv
load_dotenv()  # Load .env file
```

Now you don't need to set environment variables manually!

---

## Quick Checklist

- [ ] Got fresh Discord token from browser (F12 → Console)
- [ ] Set DISCORD_USER_TOKEN without quotes (Windows CMD/PowerShell)
- [ ] Verified token is set with `echo %DISCORD_USER_TOKEN%`
- [ ] Set all other required env vars (Webull tokens, PIN)
- [ ] Running bot in **same terminal** where vars were set
- [ ] Token is 70+ characters long
- [ ] No extra spaces or quotes in token value

---

**Most common fix:** Get a fresh token and set it without quotes in the same terminal where you run the bot!
