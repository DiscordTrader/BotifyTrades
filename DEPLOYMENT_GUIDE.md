# 🚀 Discord Trading Bot - Complete Deployment Guide

## Table of Contents
1. [Running on Your Local Machine](#1-running-on-your-local-machine)
2. [System Requirements](#2-system-requirements)
3. [Sharing with Others](#3-sharing-with-others)
4. [Building Standalone Executable](#4-building-standalone-executable)

---

## 1. Running on Your Local Machine

### Quick Start (Any OS)

#### Step 1: Download from Replit
1. Click the **three dots** (⋮) in Replit top menu
2. Select **"Download as zip"**
3. Extract the ZIP to your computer (e.g., `C:\TradingBot` on Windows or `~/TradingBot` on Mac/Linux)

#### Step 2: Install Python
- **Windows/Mac**: Download Python 3.11+ from [python.org](https://www.python.org/downloads/)
- **Linux**: Already installed (check with `python3 --version`)

#### Step 3: Install Dependencies
Open terminal/command prompt in the bot folder:

**Windows:**
```cmd
cd C:\TradingBot
pip install -r requirements.txt
```

**Mac/Linux:**
```bash
cd ~/TradingBot
pip3 install -r requirements.txt
```

#### Step 4: Configure Credentials
Copy the example config:
```bash
cp config.ini.example config.ini
```

Edit `config.ini` with your credentials:
```ini
[Discord]
TOKEN = your_discord_token_here

[Webull]
EMAIL = your_webull_email
PASSWORD = your_webull_password
DID = your_device_id
ACCESS_TOKEN = token_here
REFRESH_TOKEN = token_here

[API_Keys]
ALPHA_VANTAGE_API_KEY = your_key_here
FINNHUB_API_KEY = your_key_here
OPENAI_API_KEY = your_key_here

[License]
LICENSE_KEY = your_license_key
```

#### Step 5: Run the Bot
**Windows:**
```cmd
python src/selfbot_webull.py
```

**Mac/Linux:**
```bash
python3 src/selfbot_webull.py
```

The bot will:
- Start the Discord bot
- Launch Flask web GUI on http://127.0.0.1:5000
- Display status in terminal

#### Step 6: Access Web Control Panel
Open your browser and go to:
```
http://127.0.0.1:5000
```

---

## 2. System Requirements

### Minimum Requirements
| Component | Requirement |
|-----------|-------------|
| **OS** | Windows 10+, macOS 10.15+, or Linux (Ubuntu 20.04+) |
| **Python** | 3.11 or higher |
| **RAM** | 4 GB minimum, 8 GB recommended |
| **Storage** | 500 MB free space |
| **Internet** | Stable broadband connection |
| **Browser** | Chrome, Firefox, Safari, or Edge (for web GUI) |

### Required Credentials
1. **Discord Token** - Your Discord account token (use `GET_DISCORD_TOKEN.html`)
2. **Webull Account** - Email, password, device ID, access/refresh tokens (use `GET_WEBULL_TOKENS.html`)
3. **API Keys** (optional but recommended):
   - Alpha Vantage API key (free at alphavantage.co)
   - Finnhub API key (free at finnhub.io)
   - OpenAI API key (for AI analysis - platform.openai.com)
4. **License Key** - Machine-bound license key

### Python Dependencies
All dependencies are in `requirements.txt`:
```
discord.py-self>=1.9.0    # Discord integration
webull>=0.2.0             # Webull broker API
Flask>=3.0.0              # Web control panel
openai>=2.0.0             # AI trade analysis
cryptography>=41.0.0      # Secure credential storage
pywin32>=306              # Windows credential encryption (Windows only)
alpaca-py                 # Alpaca broker (optional)
ib-insync                 # Interactive Brokers (optional)
aiohttp                   # Async HTTP requests
ta                        # Technical analysis indicators
yfinance                  # Market data
```

---

## 3. Sharing with Others

### Option A: Share Python Source Code (Developers)

**Best for:** Technical users who want to customize the bot

1. **Compress the folder:**
   ```bash
   # Exclude unnecessary files
   zip -r TradingBot.zip . -x "*.pyc" -x "__pycache__/*" -x "bot_data.db" -x ".git/*"
   ```

2. **Include a README:**
   Create a simple `SETUP.txt`:
   ```
   QUICK SETUP GUIDE
   
   1. Install Python 3.11+ from python.org
   2. Open terminal/command prompt
   3. Run: pip install -r requirements.txt
   4. Copy config.ini.example to config.ini
   5. Edit config.ini with your credentials
   6. Run: python src/selfbot_webull.py
   7. Open browser: http://127.0.0.1:5000
   
   Helper Tools:
   - GET_DISCORD_TOKEN.html - Extract Discord token
   - GET_WEBULL_TOKENS.html - Get Webull credentials
   - GET_MACHINE_ID.bat - Get machine ID for license
   ```

3. **Share via:**
   - Cloud storage (Google Drive, Dropbox)
   - Private GitHub repository
   - Email/messaging (if small enough)

### Option B: Share as Windows Executable (Easiest for Customers)

**Best for:** Non-technical users who just want to use the bot

See Section 4 below for building standalone `.exe`

---

## 4. Building Standalone Executable (.exe for Windows)

### Why Bundle as EXE?
✅ No Python installation required  
✅ One-click to run  
✅ All dependencies included  
✅ Professional distribution  
✅ Works on any Windows 10+ machine  

### Build Process (Windows Only)

#### Prerequisites
- Windows 10/11 machine
- Python 3.11+ installed
- All dependencies installed (`pip install -r requirements.txt`)

#### Method 1: Quick Build (Recommended)

**Step 1:** Open Command Prompt in bot folder
```cmd
cd C:\TradingBot
```

**Step 2:** Run the build script
```cmd
build_exe.bat
```

This will:
1. Check for PyInstaller (installs if missing)
2. Check for pywin32 (installs if missing)
3. Build standalone EXE (takes 2-3 minutes)
4. Output to `dist\DiscordTradingBot\DiscordTradingBot.exe`

**Step 3:** Create distribution package
```cmd
create_distribution.bat
```

This creates `TradingBot-Distribution\` folder with:
```
TradingBot-Distribution/
├── DiscordTradingBot.exe         # Main executable
├── config.ini.example             # Configuration template
├── GET_DISCORD_TOKEN.html         # Helper tool
├── GET_WEBULL_TOKENS.html         # Helper tool
├── GET_MACHINE_ID.bat             # License tool
├── SETUP_GUIDE.txt                # Customer instructions
└── README.md                      # Full documentation
```

**Step 4:** Compress and share
```cmd
# The script automatically creates TradingBot-Distribution.zip
```

#### Method 2: Manual Build

If the script doesn't work, build manually:

```cmd
# Install PyInstaller
pip install pyinstaller

# Build the executable
pyinstaller build_exe.spec

# Executable will be in dist\DiscordTradingBot\DiscordTradingBot.exe
```

### What Gets Bundled?

The `.exe` file includes:
- ✅ Python interpreter (no Python installation needed)
- ✅ All Python dependencies (Flask, Discord, Webull, etc.)
- ✅ Web GUI templates and CSS files
- ✅ SQLite database engine
- ✅ All bot source code

**File Size:** ~150-200 MB (normal for bundled Python apps)

### Distribution Package Contents

Your customers receive:
```
📦 TradingBot-Distribution.zip (200-250 MB)
│
└── 📁 DiscordTradingBot/
    ├── 🚀 DiscordTradingBot.exe       # Main program
    ├── ⚙️ config.ini.example           # Settings template
    ├── 🔑 GET_DISCORD_TOKEN.html       # Token extractor
    ├── 🔑 GET_WEBULL_TOKENS.html       # Webull helper
    ├── 🆔 GET_MACHINE_ID.bat           # License helper
    ├── 📖 SETUP_GUIDE.txt              # Step-by-step instructions
    └── 📋 README.md                    # Full documentation
```

### Customer Setup (Their Side)

They only need to:

1. **Extract ZIP** to `C:\TradingBot`
2. **Run `DiscordTradingBot.exe`** (first-time setup wizard)
3. **Follow interactive wizard:**
   - Enter Discord token (use `GET_DISCORD_TOKEN.html`)
   - Enter Webull credentials (use `GET_WEBULL_TOKENS.html`)
   - Enter API keys (optional)
   - Enter license key
4. **Open browser** to http://127.0.0.1:5000
5. **Done!** Bot is running

No Python, no pip, no command line needed!

---

## Platform-Specific Notes

### Windows
- ✅ Full support for `.exe` bundling
- ✅ DPAPI encryption for credentials
- ✅ PyInstaller works perfectly
- ⚠️ Windows Defender may flag the `.exe` (false positive) - add exclusion

### macOS
- ⚠️ Cannot build Windows `.exe` on Mac
- ✅ Can run Python version directly
- ℹ️ Use `python3` instead of `python`
- ℹ️ Use `pip3` instead of `pip`

### Linux
- ⚠️ Cannot build Windows `.exe` on Linux
- ✅ Can run Python version directly
- ℹ️ May need to install additional system packages:
  ```bash
  sudo apt-get update
  sudo apt-get install python3-pip python3-dev
  ```

---

## Licensing System

The bot uses **machine-bound licensing**:
- Each license is tied to specific hardware
- Machine ID generated from hardware fingerprint
- License includes expiration date
- Automatic renewal prompts

**To get machine ID:**
```cmd
# Windows
GET_MACHINE_ID.bat

# Mac/Linux
python3 -c "import platform; import hashlib; print(hashlib.sha256(f'{platform.node()}{platform.machine()}'.encode()).hexdigest()[:16])"
```

---

## Cloud Deployment (24/7 Running)

### Option 1: Keep Running on Replit
- ✅ Already configured
- ✅ 24/7 uptime
- ⚠️ Limited to Replit environment

### Option 2: Cloud VPS (Recommended for Production)

**Popular VPS Providers:**
- DigitalOcean ($6/month)
- Linode ($5/month)
- AWS EC2 (free tier available)
- Google Cloud Compute (free tier available)

**Setup on VPS:**
```bash
# SSH into VPS
ssh user@your-vps-ip

# Install Python
sudo apt update
sudo apt install python3 python3-pip

# Upload bot files
# (Use SFTP or git clone)

# Install dependencies
pip3 install -r requirements.txt

# Run with screen (keeps running after logout)
screen -S tradingbot
python3 src/selfbot_webull.py

# Detach: Ctrl+A then D
# Reattach: screen -r tradingbot
```

---

## Troubleshooting

### Bot won't start
- ✅ Check Python version: `python --version` (must be 3.11+)
- ✅ Reinstall dependencies: `pip install -r requirements.txt --force-reinstall`
- ✅ Check `config.ini` for typos

### Web GUI not loading
- ✅ Check terminal for Flask startup message
- ✅ Try http://localhost:5000 instead of 127.0.0.1:5000
- ✅ Check firewall isn't blocking port 5000

### PyInstaller build fails
- ✅ Run `PYINSTALLER_FIX.bat` to reinstall PyInstaller
- ✅ Check Python version (must be 3.11, not 3.12+)
- ✅ Disable antivirus temporarily during build

### License key not working
- ✅ Verify machine ID matches: `GET_MACHINE_ID.bat`
- ✅ Check license expiration date
- ✅ Ensure no typos in license key

---

## Summary

### For Personal Use:
1. Download from Replit
2. Install Python 3.11+
3. Run `pip install -r requirements.txt`
4. Edit `config.ini`
5. Run `python src/selfbot_webull.py`

### For Sharing (Non-Technical Users):
1. Build Windows executable: `build_exe.bat`
2. Create distribution: `create_distribution.bat`
3. Share the ZIP file
4. They just run the `.exe`!

### For 24/7 Production:
1. Deploy to cloud VPS
2. Use `screen` to keep running
3. Set up auto-restart on crashes

---

**Need Help?** Check these files:
- `BUILD_EXE_QUICKSTART.md` - Quick build guide
- `BUILD_TROUBLESHOOTING.md` - Common issues
- `EXE_SETUP.md` - Customer setup guide
- `LOCAL_SETUP.md` - Local development setup
