# Windows EXE - Quick Start Guide

## ✅ What's Ready

Your Discord Trading Bot can now be packaged as a **standalone Windows executable** with an **interactive setup wizard** that securely stores credentials.

---

## 🚀 How to Build the EXE

### Step 1: Prepare Your Environment

On your **Windows machine** (not Replit):

1. Install Python 3.11+ from [python.org](https://www.python.org/downloads/)
2. Download your project files from Replit

### Step 2: Install Dependencies

Open Command Prompt in your project folder:

```bash
pip install -r requirements.txt
```

This installs:
- All trading bot dependencies
- `pywin32` (for Windows DPAPI encryption)

### Step 3: Build the EXE

Simply run:

```bash
build_exe.bat
```

This automated script will:
- Check for PyInstaller (installs if needed)
- Check for pywin32 (installs if needed)
- Build a standalone EXE (takes 2-3 minutes)
- Output to `dist\DiscordTradingBot.exe`

### Step 4: Create Distribution Package

```bash
create_distribution.bat
```

This creates a `TradingBot-Distribution\` folder with:
- `DiscordTradingBot.exe` (the standalone executable)
- `config.ini.example` (configuration template)
- `EXE_SETUP.md` (user setup instructions)
- `README.md` (documentation)

###Step 5: Test Before Distributing

1. Copy the `TradingBot-Distribution\` folder to a test location
2. Run `DiscordTradingBot.exe`
3. Complete the interactive setup wizard
4. Verify the bot connects and monitors positions

---

## 🔒 Security Features

### Windows DPAPI Encryption
- Credentials are encrypted using **Windows Data Protection API**
- Only your Windows user account can decrypt them
- Credentials cannot be decrypted on another computer
- Provides true security (not just obfuscation)

### How It Works
1. User runs EXE for the first time
2. Interactive wizard prompts for credentials
3. Credentials encrypted with Windows DPAPI
4. Stored at: `C:\Users\YourName\.discord_trading_bot\credentials.dat`
5. On subsequent runs, credentials auto-load

---

## 📦 Distribution Checklist

Before sharing the EXE with others:

- [ ] Test on a clean Windows machine (no Python installed)
- [ ] Verify setup wizard launches on first run
- [ ] Confirm credentials persist across restarts
- [ ] Test signal detection and position monitoring
- [ ] **Add strong legal disclaimers** (see EXE_SETUP.md)
- [ ] **Never include your personal credentials** in the distribution
- [ ] **Never include your personal config.ini** (use config.ini.example)

---

## ⚠️ Important Warnings

### Legal & Terms of Service
- **Discord Self-Bots VIOLATE Discord's ToS** - accounts may be terminated
- Distribute for **personal use only** to avoid legal liability
- **No warranty** - users accept all risks

### Trading Risks
- Bot executes **real trades with real money**
- Always test with `paper_trade = true` first
- You can lose your entire investment

### Security
- Never distribute your personal credentials
- Users must obtain their own Discord/Webull tokens
- Each user runs the wizard to set up their own credentials

---

## 🎯 Next Steps (Phase 2)

The current implementation is **Phase 1: Simple EXE**. For Phase 2, you can add:

### Licensing System Features
1. **License Key Validation**
   - Time-based expiration (7 days, 365 days, etc.)
   - Machine-specific activation
   - Online or offline validation

2. **Obfuscation** (makes decompilation harder)
   - PyArmor or similar tools
   - Code obfuscation

3. **Usage Tracking**
   - License server (requires hosting)
   - Activation/deactivation system

**Current Setup is Ready:** The credential storage and setup wizard are designed to integrate with licensing in Phase 2.

---

## 📝 Files You Created

| File | Purpose |
|------|---------|
| `src/setup_wizard.py` | Interactive credential collection and DPAPI encryption |
| `build_exe.bat` | Automated PyInstaller build script |
| `create_distribution.bat` | Package EXE for distribution |
| `build_instructions.md` | Developer build guide |
| `EXE_SETUP.md` | End-user setup instructions with warnings |
| `BUILD_EXE_QUICKSTART.md` | This file - quick reference |

---

## 🆘 Troubleshooting

### "pywin32 not found" during build
```bash
pip install pywin32
```

### EXE crashes immediately
- Check console output for errors
- Ensure `config.ini.example` is in the same folder as the EXE
- Try running from Command Prompt to see error messages

### Credentials don't persist
- Check folder permissions for `C:\Users\YourName\.discord_trading_bot\`
- Verify pywin32 is installed
- Try deleting the folder and re-running setup wizard

### Build takes too long
- Normal build time: 2-3 minutes
- First build is slower (downloads dependencies)

---

**You're Ready to Build!** Run `build_exe.bat` on your Windows machine to create the standalone executable.
