# BotifyTrades - EXE Quick Start Guide

## What's Ready

Your Discord Trading Bot can be packaged as a **standalone executable** with:
- **PyArmor obfuscation** - License code protection
- **Interactive setup wizard** - Secure credential storage
- **Cross-platform support** - Windows, Linux, macOS

---

## How to Build

**NO GIT REQUIRED** - Version is read from `upgrade/version.py`

### Windows

```batch
cd packaging\windows\scripts
build.bat
```

Output: `packaging\windows\dist\BotifyTrades.exe`

### Linux

```bash
cd packaging/linux/scripts
chmod +x build.sh
./build.sh
```

Output: `packaging/linux/dist/BotifyTrades`

### macOS

```bash
cd packaging/macos/scripts
chmod +x build.sh
./build.sh
```

Output: `packaging/macos/dist/BotifyTrades`

---

## Prerequisites

### All Platforms

1. Python 3.8+ installed
2. Project dependencies installed: `pip install -r requirements.txt`

### Windows Specific

- `pywin32` (for Windows DPAPI encryption)

### Build Dependencies (auto-installed)

- `pyarmor` - Code obfuscation
- `pyinstaller` - Executable packaging
- `upx` (optional) - Compression

---

## Build Process

The build script automatically:

1. Checks for Python, PyArmor, PyInstaller
2. Backs up original license files
3. Obfuscates license code with PyArmor
4. Builds standalone executable
5. Compresses with UPX (if available)
6. Creates distribution package
7. Restores original files (cleanup)

---

## Security Features

### PyArmor Obfuscation
- License validation code is obfuscated
- Makes reverse engineering difficult
- Runtime protection for sensitive code

### Windows DPAPI Encryption
- Credentials encrypted with Windows Data Protection API
- Only the user's Windows account can decrypt
- Credentials cannot be decrypted on another computer

### How Credentials Work
1. User runs EXE for the first time
2. Interactive wizard prompts for credentials
3. Credentials encrypted and stored securely
4. On subsequent runs, credentials auto-load

---

## Distribution Checklist

Before sharing the executable:

- [ ] Test on a clean machine (no Python installed)
- [ ] Verify setup wizard launches on first run
- [ ] Confirm credentials persist across restarts
- [ ] Test signal detection and position monitoring
- [ ] **Never include your personal credentials**
- [ ] **Never include your personal config.ini**

---

## Important Warnings

### Legal & Terms of Service
- **Discord Self-Bots VIOLATE Discord's ToS** - accounts may be terminated
- Distribute for **personal use only**
- **No warranty** - users accept all risks

### Trading Risks
- Bot executes **real trades with real money**
- Always test with `paper_trade = true` first
- You can lose your entire investment

### Security
- Never distribute your personal credentials
- Users must obtain their own tokens
- Each user runs the wizard for their own credentials

---

## Troubleshooting

### Build fails with "PyArmor not found"
```bash
pip install pyarmor
```

### EXE crashes immediately
- Check console output for errors
- Ensure config files are in the same folder
- Run from Command Prompt/Terminal to see errors

### Credentials don't persist
- Check folder permissions
- Verify pywin32 is installed (Windows)
- Try deleting credentials folder and re-run wizard

### macOS Security Block
If blocked by Gatekeeper:
```bash
xattr -cr ./BotifyTrades
```
Or right-click and select "Open"

---

## Version Information

Version is displayed at startup:
```
============================================================
BUILD VERSION: v2.1.35
============================================================
```

To update version, edit `upgrade/version.py`:
```python
APP_VERSION = "2.1.35"
BUILD_DATE = "2025-12-11"
```
