# PyInstaller Build Troubleshooting Guide

## Common Issue: Antivirus Blocking Build

### Problem
Build fails with error:
```
FileNotFoundError: The system cannot find the file specified: '...\dist\DiscordTradingBot.exe'
```

### Cause
Windows Defender (or other antivirus) deletes the .exe file during build because PyInstaller executables often trigger false positives.

### Solutions

#### Option 1: Add Folder Exclusion (Recommended)

**Windows Defender:**
1. Open Windows Security
2. Go to Virus & threat protection → Manage settings
3. Scroll to Exclusions → Add or remove exclusions
4. Add an exclusion → Folder
5. Select your bot project folder
6. Run build.bat again

**Other Antivirus Software:**
- Similar process - add your project folder to exclusions/whitelist

#### Option 2: Temporarily Disable Antivirus

1. Disable Windows Defender temporarily
2. Run build.bat
3. Immediately re-enable after build completes
4. Add dist\DiscordTradingBot.exe to exclusions

#### Option 3: Check if Build Actually Succeeded

Sometimes the exe is created despite the error:
```cmd
cd dist
dir DiscordTradingBot.exe
```

If the file exists, the build succeeded!

---

## Other Common Build Errors

### "PyInstaller not found"
```bash
pip install pyinstaller
```

### "Module not found: discord"
```bash
pip install discord.py-self
```

### "Module not found: webull"
```bash
pip install webull
```

### "Module not found: openai"
```bash
pip install openai
```

### Install All Dependencies
```bash
pip install discord.py-self webull openai ta yfinance aiohttp requests pywin32
```

### Clean Build (Start Fresh)
```cmd
rmdir /s /q build
rmdir /s /q dist
build.bat
```

---

## Verifying Successful Build

After build completes, you should have:
```
dist/
  ├── DiscordTradingBot.exe  (50-150 MB typical)
  └── config.ini
```

Test the exe:
```cmd
cd dist
DiscordTradingBot.exe
```

Expected output: "License key required" (this is correct!)

---

## For Customers: Running the Exe

### Windows Defender Warning

When customers run your exe for the first time, Windows Defender may show:
```
Windows protected your PC
Microsoft Defender SmartScreen prevented an unrecognized app from starting
```

**This is normal!** To run:
1. Click "More info"
2. Click "Run anyway"

### Permanent Solution for Customers

Add to Windows Defender exclusions:
1. Right-click DiscordTradingBot.exe
2. Select "Scan with Windows Defender"
3. After scan completes, go to Windows Security
4. Virus & threat protection → Protection history
5. Find the blocked item
6. Select "Allow on device"

---

## Advanced: Code Signing (Prevents Antivirus Issues)

For professional distribution, consider code signing:

1. **Purchase code signing certificate** ($50-300/year)
   - Sectigo, DigiCert, GlobalSign

2. **Sign the executable:**
```cmd
signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com DiscordTradingBot.exe
```

Benefits:
- Eliminates Windows Defender warnings
- Builds trust with customers
- Required for large-scale distribution

---

## Still Having Issues?

1. Make sure you have Python 3.11+ installed
2. Verify all dependencies are installed: `pip list`
3. Try building on a different Windows machine
4. Check disk space (need ~500MB free)
5. Run Command Prompt as Administrator

---

## Quick Checklist

- [ ] Antivirus exclusion added for project folder
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] Secret key changed in src/license_manager.py
- [ ] Clean build (deleted build/ and dist/ folders)
- [ ] Ran build.bat
- [ ] Verified DiscordTradingBot.exe exists in dist/
- [ ] Tested exe (should ask for license)
