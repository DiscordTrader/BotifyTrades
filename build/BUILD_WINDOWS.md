# Ψ∿ QuantumPulse - Windows Build Guide

**Build Date:** 2025-11-21
**OS:** Windows 10/11 (64-bit)
**Python:** 3.8 - 3.11

## Prerequisites

### 1. Install Python 3.11
- Download from https://www.python.org/downloads/
- ✅ Check "Add Python to PATH"
- ✅ Check "Install pip"

### 2. Install Visual C++ Build Tools (Optional but Recommended)
- Required for some dependencies to compile
- Download: https://visualstudio.microsoft.com/downloads/
- Select "Desktop development with C++"

## Build Steps

### Step 1: Install Build Dependencies
```powershell
pip install --upgrade pip setuptools wheel
pip install pyinstaller
```

### Step 2: Install Project Dependencies
```powershell
pip install -r requirements.txt
```

### Step 3: Run Build
```powershell
pyinstaller build_windows.spec
```

### Step 4: Output Location
```
dist/QuantumPulse_Windows_Build_2025-11-21/
├── QuantumPulse.exe (Main executable)
├── gui_app/
├── src/
├── config.ini
└── replit.md
```

## Running the Executable

### Method 1: Direct Execution
```powershell
cd dist\QuantumPulse_Windows_Build_2025-11-21
.\QuantumPulse.exe
```

### Method 2: Command Line with Arguments
```powershell
.\QuantumPulse.exe --config path/to/config.ini
```

### Method 3: Create Batch Launcher
```batch
@echo off
cd /d "%~dp0"
QuantumPulse.exe
pause
```

## Configuration

### 1. Set Environment Variables
```powershell
$env:ALPACA_API_KEY = "your_api_key"
$env:ALPACA_SECRET_KEY = "your_secret_key"
$env:DISCORD_USER_TOKEN = "your_token"
$env:OPENAI_API_KEY = "your_key"
```

Or in System Environment Variables:
1. Win + X → Environment Variables
2. Click "Environment Variables"
3. Add new user/system variables

### 2. Edit config.ini
```ini
[discord]
channel_ids = 551065756557639680, 1386424654209618050

[brokers]
enable_alpaca = true

[alpaca]
paper_trade = true
```

## Running as Windows Service (Optional)

### Using NSSM (Non-Sucking Service Manager)
```powershell
# Download NSSM from https://nssm.cc/

# Install service
nssm install QuantumPulse "C:\path\to\QuantumPulse.exe"

# Start service
nssm start QuantumPulse

# View logs
nssm dump QuantumPulse
```

### Using Windows Task Scheduler
1. Open Task Scheduler
2. Create Basic Task
3. Set Trigger (At startup or specific time)
4. Set Action: Start program → `QuantumPulse.exe`
5. Set Run with highest privileges

## Troubleshooting

### Issue: "Python not found"
- Reinstall Python with PATH enabled
- Or use full path: `C:\Python311\python.exe`

### Issue: "Module not found" Error
- Reinstall requirements: `pip install -r requirements.txt`
- Clear build: `rmdir /s dist build`
- Rebuild: `pyinstaller build_windows.spec`

### Issue: WebSocket/SSL Errors
- Install Visual C++ Build Tools
- Run: `pip install --upgrade cryptography pywin32`

### Issue: Alpaca Connection Failed
- Verify API keys in environment variables
- Test connection: Check logs for "unauthorized"
- Ensure paper trading is enabled

### Issue: Discord Connection Failed
- Check Discord token validity
- Verify channels are accessible
- Check channel IDs in config.ini

## Building from Source vs EXE

### EXE Advantages:
- ✅ No Python required on target machine
- ✅ Single file distribution
- ✅ Faster startup
- ✅ Code obfuscation (harder to reverse)

### Source Advantages:
- ✅ Easier debugging
- ✅ Faster development
- ✅ Cross-platform (copy to Linux/Mac)

## Advanced: Code Obfuscation (Optional)

To hide source code using PyArmor:
```powershell
pip install pyarmor
pyarmor obfuscate --restrict src/selfbot_webull.py
```

Then rebuild with obfuscated code.

## Performance

- **Startup Time:** 5-10 seconds
- **Memory Usage:** 200-400 MB
- **CPU Usage:** <5% idle, varies during trading
- **Network:** Requires consistent internet connection

## Security Best Practices

1. ✅ Store API keys in environment variables (not config.ini)
2. ✅ Use Windows Credential Manager for sensitive data
3. ✅ Run with restricted user account (non-admin)
4. ✅ Use firewall to restrict outbound ports
5. ✅ Keep Windows and Python updated

## Support & Issues

For issues, check:
1. Console output for error messages
2. Discord logs in application directory
3. Event Viewer for system errors
4. Firewall/Antivirus blocking connections

---

**Build Date:** 2025-11-21
**Status:** ✅ Production Ready
