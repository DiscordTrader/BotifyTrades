# Discord Trading Bot - Distribution Guide

## For Bot Administrators: How to Build and Distribute

This guide explains how to build the bot into a standalone executable and distribute it to customers.

---

## Prerequisites

Before building, ensure you have:
1. ✅ Python 3.11+ installed
2. ✅ All bot dependencies installed (`pip install -r requirements.txt`)
3. ✅ **Changed the SECRET_KEY** in `src/license_manager.py` (critical!)
4. ✅ Tested the bot in your development environment

---

## Step 1: Change the Secret Key (CRITICAL!)

**⚠️ WARNING: Do this BEFORE building the exe!**

1. Generate a secure random key:
```python
import secrets
print(secrets.token_hex(32))
```

2. Open `src/license_manager.py` and replace line 18:
```python
SECRET_KEY = b"your_generated_secret_here"
```

3. **Save the file** and **never share this secret** with customers!

---

## Step 2: Build the Executable

### Option A: Windows Build (Recommended for Distribution)

1. Open Command Prompt or PowerShell
2. Navigate to the bot directory
3. Run the build script:
```cmd
build.bat
```

The script will:
- Install PyInstaller if needed
- Clean previous builds
- Build `DiscordTradingBot.exe`
- Copy `config.ini` to the `dist/` folder

### Option B: Linux/Mac Build

1. Open Terminal
2. Navigate to the bot directory
3. Make the script executable:
```bash
chmod +x build.sh
```
4. Run the build script:
```bash
./build.sh
```

### Option C: Manual Build (Any Platform)

```bash
# Install PyInstaller
pip install pyinstaller

# Build using the spec file
pyinstaller build_exe.spec --clean --noconfirm

# Manually copy config.ini to dist/
cp config.ini dist/
```

---

## Step 3: Verify the Build

After building, check the `dist/` folder:

```
dist/
  ├── DiscordTradingBot.exe  (Windows) or DiscordTradingBot (Linux/Mac)
  └── config.ini
```

**Test the executable:**
```cmd
cd dist
DiscordTradingBot.exe
```

The bot should:
1. ❌ Fail with "License key required" message (expected - no license yet)
2. ✅ Show all configuration loading correctly

---

## Step 4: Generate Customer License Keys

Use the `generate_license.py` script to create licenses:

```bash
# Interactive mode
python generate_license.py

# Command line
python generate_license.py --days 30 --customer "john_doe"

# Common scenarios
python generate_license.py --days 7 --customer "trial_user"      # 7-day trial
python generate_license.py --days 30 --customer "monthly_user"   # Monthly
python generate_license.py --days 365 --customer "yearly_user"   # Yearly

# Batch generation
python generate_license.py --days 30 --customer "batch" --batch 10
```

**Save the generated license keys** for your records!

---

## Step 5: Prepare Distribution Package

Create a distribution package for each customer:

### Recommended Package Structure

```
DiscordTradingBot_v1.0/
  ├── DiscordTradingBot.exe      (The bot executable)
  ├── config.ini                  (Configuration template)
  ├── README.txt                  (Setup instructions - see below)
  └── LICENSE_KEY.txt             (Customer's license key)
```

### README.txt Template

Create a `README.txt` file for customers:

```
=============================================================
Discord Trading Bot - Setup Instructions
=============================================================

Thank you for your purchase!

STEP 1: INSTALL (FIRST TIME ONLY)
----------------------------------
1. Extract all files to a folder (e.g., C:\TradingBot\)
2. Open config.ini with Notepad
3. Edit the settings:
   - channel_ids = Your Discord channel IDs (comma-separated)
   - paper_trade = false (for live trading) or true (for testing)
   - Other settings as needed
4. Save and close config.ini

STEP 2: FIRST RUN - LICENSE ACTIVATION
---------------------------------------
1. Double-click DiscordTradingBot.exe
2. The setup wizard will appear
3. When prompted for license key, paste the key from LICENSE_KEY.txt
4. Follow the wizard to enter:
   - Your Discord user token
   - Your Webull credentials
   - Optional API keys (OpenAI, Alpha Vantage, Finnhub)
5. Setup is complete!

STEP 3: RUNNING THE BOT
------------------------
1. Double-click DiscordTradingBot.exe
2. The bot will validate your license and start
3. Monitor the console window for trading activity
4. Keep the window open while the bot runs

IMPORTANT NOTES:
----------------
• Your license expires on: [EXPIRATION_DATE]
• Contact support for license renewal: [YOUR_EMAIL]
• Always test with paper_trade = true before live trading
• Keep your credentials and license key secure
• Do not share your license key with others

TROUBLESHOOTING:
----------------
• "License key required" - Enter your license key during setup
• "Invalid license" - Contact support for a new license
• "Discord token error" - Re-run setup wizard to update token
• Bot not trading - Check channel_ids in config.ini

SUPPORT:
--------
Email: [YOUR_SUPPORT_EMAIL]
Discord: [YOUR_DISCORD_SUPPORT]

=============================================================
```

---

## Step 6: Distribution Methods

### Method A: Direct Delivery (Recommended)

1. Create a password-protected ZIP file:
```
DiscordTradingBot_john_doe.zip (password: johndoe2025)
  ├── DiscordTradingBot.exe
  ├── config.ini
  ├── README.txt
  └── LICENSE_KEY.txt
```

2. Send via:
   - Email (for small files < 25MB)
   - File sharing (Google Drive, Dropbox, WeTransfer)
   - Private Discord DM

3. Provide the password separately (via SMS or Discord)

### Method B: Download Portal

Host the files on a private server with:
- Customer login system
- Download links with expiration
- License key delivery system

### Method C: USB/Physical Media

For high-value customers:
- Pre-configure everything on a USB drive
- Test before delivery
- Include printed setup instructions

---

## What Customers Need

**Minimum Distribution:**
1. ✅ `DiscordTradingBot.exe` - The bot executable
2. ✅ `config.ini` - Configuration file
3. ✅ License key (in LICENSE_KEY.txt or via email)
4. ✅ Setup instructions (README.txt)

**Optional Additions:**
- Sample config.ini with explanations
- Video tutorial link
- Troubleshooting guide
- Your support contact info

---

## Security Best Practices

### Before Distribution:

1. ✅ **Secret key changed** in `src/license_manager.py`
2. ✅ **No hardcoded credentials** in the source code
3. ✅ **Test build on clean machine** without Python installed
4. ✅ **Virus scan** the executable (false positives are common with PyInstaller)
5. ✅ **License system tested** with valid/invalid/expired keys

### For Customers:

1. ⚠️ **License keys are unique** - each customer gets their own
2. ⚠️ **Track license assignments** (who has which license)
3. ⚠️ **Keep customer records** (name, license key, expiration date)
4. ⚠️ **Renewal system** - remind customers before expiration

---

## License Management Best Practices

### Customer Database Spreadsheet

Keep a record of all licenses:

| Customer Name | Email | License Key | Duration | Issued Date | Expires Date | Status |
|---------------|-------|-------------|----------|-------------|--------------|--------|
| John Doe | john@example.com | eyJjdXN0... | 30 days | 2025-11-14 | 2025-12-14 | Active |
| Jane Smith | jane@example.com | eyJjdXN0... | 365 days | 2025-11-14 | 2026-11-14 | Active |

### Renewal Workflow

1. **7 days before expiration**: Send renewal reminder email
2. **At expiration**: License stops working (bot won't start)
3. **Customer requests renewal**: Generate new license key
4. **Send new key**: Customer updates via setup wizard or env variable

### Handling Refunds/Cancellations

If you need to revoke a license early:
- You **cannot remotely disable** a license (it's validated locally)
- Options:
  1. Don't renew when it expires
  2. Generate a new SECRET_KEY (invalidates ALL licenses - use carefully!)
  3. Release a new version with a new SECRET_KEY

---

## Troubleshooting Build Issues

### "PyInstaller not found"
```bash
pip install pyinstaller
```

### "Module not found" errors
```bash
# Install all dependencies
pip install -r requirements.txt

# Or individually
pip install discord.py-self webull openai ta yfinance aiohttp requests
```

### "win32crypt not found" (Windows)
```bash
pip install pywin32
```

### Large .exe file size
This is normal! The exe includes:
- Python interpreter
- All dependencies
- Your bot code

Typical size: 50-150 MB

### Antivirus False Positives

**IMPORTANT:** PyInstaller executables ALWAYS trigger antivirus warnings. This is normal!

**During Build:**
- Windows Defender may delete the .exe as it's being created
- **Solution**: Add your project folder to Windows Defender exclusions BEFORE building
- See BUILD_TROUBLESHOOTING.md for detailed steps

**For Customers:**
- Windows will show "Windows protected your PC" warning
- **Customer solution**: Click "More info" → "Run anyway"
- Or add DiscordTradingBot.exe to exclusions

**Professional Fix:**
1. Code-sign the executable (requires certificate $50-300/year)
2. Eliminates all antivirus warnings
3. Recommended for commercial distribution

---

## Build File Reference

| File | Purpose |
|------|---------|
| `build_exe.spec` | PyInstaller configuration (what to bundle) |
| `build.bat` | Windows build script (automated) |
| `build.sh` | Linux/Mac build script (automated) |
| `generate_license.py` | Admin tool to create license keys |
| `dist/` | Output folder with distributable files |

---

## Version Control

When releasing updates:

1. Update version number in `src/selfbot_webull.py`
2. Rebuild the executable
3. Test thoroughly
4. Notify customers of update
5. Provide download link for new version
6. **Keep the same SECRET_KEY** (unless migrating licenses)

---

## Support Resources

- **For Customers**: Point them to LICENSE_SYSTEM.md (user section)
- **For You**: See LICENSE_SYSTEM.md (admin section)
- **Build Issues**: Check PyInstaller documentation

---

## Quick Reference: Distribution Checklist

Before sending to customer:

- [ ] Secret key changed in license_manager.py
- [ ] Bot tested in development
- [ ] Executable built successfully
- [ ] Executable tested on clean machine
- [ ] config.ini template prepared
- [ ] License key generated for customer
- [ ] README.txt customized with expiration date
- [ ] ZIP file password-protected
- [ ] Customer added to license tracking spreadsheet
- [ ] Support contact info provided

---

## Summary

**You distribute:**
1. `DiscordTradingBot.exe` - The bot (with licensing enforced)
2. `config.ini` - Configuration template
3. License key - Customer-specific, time-limited
4. README.txt - Setup instructions

**Customer gets:**
- A working bot that requires their license key
- Configuration control via config.ini
- Automatic license validation on every run
- Secure credential storage via setup wizard

**You retain:**
- Source code (never distribute)
- Secret key (in license_manager.py)
- generate_license.py script (admin-only)
- Customer license database

This ensures your bot is protected while providing a smooth customer experience!
