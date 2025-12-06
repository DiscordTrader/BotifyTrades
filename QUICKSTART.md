# ⚡ QuantumPulse - Quick Start Guide

**ONE BUILD. ONE LICENSE. DONE.**

---

## 🎯 Overview

This bot has **ONE simple workflow**:
1. **Build the .exe** (Windows only)
2. **Generate license keys** for yourself or customers
3. **Run and activate** the bot

---

## 🔨 STEP 1: Build the .exe (ONE TIME ONLY)

### Windows:
```bash
BUILD_AND_RUN.bat
```

### Mac/Linux:
```bash
chmod +x build.sh
./build.sh
```

**What this does:**
- ✅ Installs dependencies
- ✅ Cleans previous builds
- ✅ Builds `dist/DiscordTradingBot.exe`
- ✅ Copies config.ini to dist folder

**Output:** `dist/DiscordTradingBot.exe` (ready to distribute)

---

## 🔑 STEP 2: Generate License Keys

### For yourself (365-day license):
```bash
python generate_license_activation.py --customer YourName --days 365
```

### For customers:
```bash
# 7-day trial
python generate_license_activation.py --customer trial_user --days 7

# 30-day subscription
python generate_license_activation.py --customer john_doe --days 30

# 1-year subscription
python generate_license_activation.py --customer premium_customer --days 365
```

**Output:**
```
License Key:
eyJhY3RpdmF0aW9uX2NvZGUiOiAiODcwMzU0NGZjMzRhNzIxMiIsICJjdXN0b21lcl9pZCI6ICJVZGF5...
```

**Copy this license key** - you'll need it for activation.

---

## 🚀 STEP 3: Run the Bot

### First Run:
1. Double-click: `dist\DiscordTradingBot.exe`
2. Choose **Option 2** (Subscription License)
3. **Paste your license key**
4. Bot automatically binds to your computer
5. Continue setup (Discord token, Webull credentials, etc.)

### License Activation:
```
Enter your subscription license key: [paste here]

🎉 LICENSE ACTIVATED!
   ✓ Bound to machine: abc123def456
   ✓ Customer: YourName
   ✓ Expires: 2026-11-18
   ✓ Days Remaining: 365

   This license will ONLY work on THIS computer.
```

### Next Runs:
- Bot remembers activation
- Just double-click `DiscordTradingBot.exe` and it starts automatically

---

## 📦 Distribute to Customers

Send customers a folder containing:
```
QuantumPulse_Bot/
  ├── DiscordTradingBot.exe     (from dist folder)
  ├── config.ini                (from dist folder)
  └── LICENSE_KEY.txt           (license you generated for them)
```

**Customer instructions:**
1. Extract folder
2. Run DiscordTradingBot.exe
3. Choose Option 2
4. Paste license key from LICENSE_KEY.txt
5. Done! Bot activated.

---

## 🔧 Files You Need to Know

| File | Purpose | When to Use |
|------|---------|-------------|
| `BUILD_AND_RUN.bat` | Build the .exe | Once, before distributing |
| `generate_license_activation.py` | Create license keys | Every time you sell/give access |
| `dist/DiscordTradingBot.exe` | The bot executable | Distribute to customers |
| `config.ini` | Bot configuration | Edit for API keys, settings |

---

## 🛠️ Files You Can IGNORE

These are old/redundant files - **you don't need them:**
- ❌ `build.bat`, `build_simple.bat`, `build_FINAL.bat` (use BUILD_AND_RUN.bat instead)
- ❌ `generate_license.py`, `generate_license_secure.py` (use generate_license_activation.py instead)
- ❌ All the `.md` guides except this QUICKSTART.md

---

## ⚙️ How the License System Works

### Auto-Activation (What Customers See):
1. Customer receives license key
2. Customer runs .exe and pastes license
3. **Bot automatically binds** to their computer's hardware
4. License works ONLY on that specific computer
5. Cannot be shared or transferred

### Security:
- ✅ Hardware-locked (prevents piracy)
- ✅ Cryptographically signed (prevents tampering)
- ✅ Offline validation (works without internet)
- ✅ Time-limited (auto-expires after X days)

---

## 🔐 SECRET_KEY Management

**CRITICAL:** Your `SECRET_KEY` in these files must match:
- ✅ `src/license_manager_activation.py` - line 24
- ✅ `generate_license_activation.py` - line 19

**Current SECRET_KEY (pre-configured):**
```python
SECRET_KEY = b"01690f93dc8536b80ddc194e47970d07fd85d3bb8758d5e0744e429edb8c876dd2d8e227a16f4d3b09beac10c9c2984a"
```

**⚠️ NEVER share this SECRET_KEY with customers!**
- Only share license keys you generate
- Keep SECRET_KEY private (like a password)

---

## ❓ Troubleshooting

### "Build failed" error:
```bash
pip install pyinstaller --upgrade
BUILD_AND_RUN.bat
```

### "License validation failed":
- Make sure SECRET_KEY matches in both files
- Regenerate license after changing SECRET_KEY
- Check for copy-paste errors (no spaces/line breaks)

### "License expired":
- Generate new license with longer duration
- Customer updates license via Settings page in bot

---

## ✅ Complete Workflow Example

```bash
# 1. Build .exe (one time)
BUILD_AND_RUN.bat

# 2. Generate license for customer "Alice" (30 days)
python generate_license_activation.py --customer Alice --days 30

# Output:
# License Key: eyJhY3RpdmF0aW9uX2NvZGUiOi...

# 3. Send to customer:
# - dist/DiscordTradingBot.exe
# - dist/config.ini
# - License key (via email)

# 4. Customer runs DiscordTradingBot.exe and pastes license
# 5. Done! Bot activated and running.
```

---

## 📞 Support

If you encounter issues:
1. Check this guide first
2. Verify SECRET_KEY matches in both files
3. Rebuild with `BUILD_AND_RUN.bat`
4. Regenerate license keys after any SECRET_KEY changes

---

**That's it! Keep it simple. One build process. One license generator. Everything works together.** 🚀
