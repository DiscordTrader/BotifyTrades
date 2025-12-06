# 🌐 Cross-Platform Build Guide - Windows & Linux

## 📋 Overview

QuantumPulse supports building on both **Windows** and **Linux** platforms with two build methods each:

| Platform | Simple Build | Protected Build |
|----------|--------------|-----------------|
| **Windows** | `build_simple.bat` | `build_PyArmor.bat` |
| **Linux** | `build_linux_simple.sh` | `build_linux_protected.sh` |

---

## 🪟 **Windows Builds**

### **Simple Build (Free)**

**Features:**
- ✅ PyInstaller compilation
- ✅ Hardware-bound licenses
- ✅ Basic protection
- ⚠️ Source code can be extracted with tools

**Command:**
```batch
build_simple.bat
```

**Output:**
- `dist\DiscordTradingBot.exe` (~50-80 MB)
- Protection Level: ⭐⭐ BASIC

---

### **Protected Build (PyArmor - $99/year)**

**Features:**
- ✅ PyArmor code obfuscation
- ✅ Encrypted bytecode
- ✅ Anti-debugging protection
- ✅ Hardware-bound licenses
- ✅ SECRET_KEY hidden from extraction
- ✅ Very hard to crack

**Command:**
```batch
build_PyArmor.bat
```

**Output:**
- `dist\DiscordTradingBot.exe` (~60-90 MB)
- Protection Level: ⭐⭐⭐⭐ STRONG

**PyArmor License:**
- Free: Limited features (200 files)
- Basic: $99/year (unlimited files)
- Pro: $599/year (advanced features)
- Get license: https://pyarmor.dashingsoft.com/pricing.html

---

## 🐧 **Linux Builds**

### **Simple Build (Free)**

**Features:**
- ✅ PyInstaller compilation
- ✅ Hardware-bound licenses
- ✅ Cross-platform encryption (Fernet)
- ✅ Systemd service support
- ⚠️ Source code can be extracted

**Command:**
```bash
chmod +x build_linux_simple.sh
./build_linux_simple.sh
```

**Output:**
- `dist/DiscordTradingBot` (~60-90 MB)
- Protection Level: ⭐⭐ BASIC

---

### **Protected Build (PyArmor - $99/year)**

**Features:**
- ✅ PyArmor code obfuscation
- ✅ Encrypted bytecode
- ✅ Anti-debugging protection
- ✅ Hardware-bound licenses
- ✅ SECRET_KEY hidden
- ✅ Production-ready security

**Command:**
```bash
chmod +x build_linux_protected.sh
./build_linux_protected.sh
```

**Output:**
- `dist/DiscordTradingBot` (~70-100 MB)
- Protection Level: ⭐⭐⭐⭐ STRONG

---

## 🔐 Credential Encryption (Platform-Specific)

### **Windows:**
- **Method:** Windows DPAPI (Data Protection API)
- **Storage:** `%USERPROFILE%\.discord_trading_bot\credentials.dat`
- **Security:** OS-level encryption, machine-bound
- **Module:** `win32crypt`

### **Linux:**
- **Method:** cryptography.Fernet + machine fingerprint
- **Storage:** `~/.discord_trading_bot/credentials.dat`
- **Security:** AES encryption with machine-derived key
- **Module:** `cryptography.fernet`

**Both methods:**
- ✅ Credentials encrypted at rest
- ✅ Cannot be copied to another machine
- ✅ No plaintext in config files
- ✅ Configurable via Flask GUI

---

## 🔑 License System (Cross-Platform)

### **License Format:**
```
base64(json_payload):hmac_signature
```

**Payload:**
```json
{
  "customer_id": "username",
  "machine_id": "05db47931c6a8c9e",
  "expires": 1795058344,
  "issued": 1763522344
}
```

### **Generate License (Same for Both Platforms):**

```bash
# Windows
python generate_license_secure.py --customer NAME --machine MACHINE_ID --days 365

# Linux
python3 generate_license_secure.py --customer NAME --machine MACHINE_ID --days 365
```

### **Get Machine ID:**

**Windows:**
```batch
cd dist
GET_MACHINE_ID.bat
```

**Linux:**
```bash
cd dist
./get_machine_id.sh
```

---

## 📊 Build Comparison

| Feature | Simple Build | Protected Build |
|---------|--------------|-----------------|
| **Cost** | Free | $99/year (PyArmor) |
| **Build Time** | 2-3 min | 5-8 min |
| **File Size** | Smaller | Slightly larger |
| **Protection** | Basic | Strong |
| **Code Extraction** | Easy | Very hard |
| **Reverse Engineering** | Medium | Very hard |
| **License Binding** | ✅ Yes | ✅ Yes |
| **Encryption** | ✅ Yes | ✅ Yes + obfuscation |
| **Recommended For** | Testing, personal use | Production, commercial |

---

## 🚀 Build Process Flow

### **Simple Build:**
```
1. Install dependencies
2. Clean build directories
3. Run PyInstaller
4. Copy helper files
5. Done! (2-3 minutes)
```

### **Protected Build:**
```
1. Install dependencies (+ PyArmor)
2. Clean build directories
3. Backup source code
4. Obfuscate with PyArmor
5. Overwrite source with obfuscated code
6. Run PyInstaller
7. Restore original source
8. Copy helper files
9. Done! (5-8 minutes)
```

---

## 🛠️ Dependencies Comparison

### **Windows-Only Dependencies:**
```
win32crypt (DPAPI encryption)
pywintypes (Windows API)
win32api (Windows system info)
win32con (Windows constants)
wmi (Windows Management Instrumentation)
```

### **Linux-Only Dependencies:**
```
keyring (Optional: credential storage)
secretstorage (Optional: GNOME keyring)
psutil (System info, replaces wmi)
```

### **Cross-Platform Dependencies:**
```
cryptography (Fernet encryption)
flask (Web GUI)
discord.py-self (Discord integration)
webull (Brokerage API)
openai (AI analysis)
yfinance (Market data)
ta (Technical analysis)
aiohttp (Async HTTP)
```

---

## 📦 Distribution Package

### **Windows Package:**
```
dist\
  ├── DiscordTradingBot.exe (Main executable)
  ├── config.ini (Configuration template)
  ├── GET_DISCORD_TOKEN.html (Helper tool)
  ├── GET_WEBULL_TOKENS.html (Helper tool)
  ├── GET_MACHINE_ID.bat (Machine ID tool)
  ├── BUILD_METHODS_GUIDE.md (Documentation)
  └── CREDENTIAL_MANAGEMENT.md (Documentation)
```

### **Linux Package:**
```
dist/
  ├── DiscordTradingBot (Main executable)
  ├── config.ini (Configuration template)
  ├── GET_DISCORD_TOKEN.html (Helper tool)
  ├── GET_WEBULL_TOKENS.html (Helper tool)
  ├── get_machine_id.sh (Machine ID tool)
  ├── BUILD_METHODS_GUIDE.md (Documentation)
  └── CREDENTIAL_MANAGEMENT.md (Documentation)
```

---

## ⚙️ Spec File Differences

### **build_exe.spec (Windows):**
- Includes `win32crypt`, `pywintypes`, `win32api`, `wmi`
- No `keyring`, `secretstorage`, `psutil`
- Builds `.exe` with console window

### **build_linux.spec (Linux):**
- Excludes `win32crypt`, `pywintypes`, `win32api`, `wmi`
- Includes `keyring`, `secretstorage`, `psutil`
- Builds Linux binary with console output

---

## 🔄 Cross-Platform Development Workflow

### **Develop on Windows, Deploy on Linux:**

```bash
# 1. Develop and test on Windows
build_simple.bat
dist\DiscordTradingBot.exe

# 2. Push to Git
git add .
git commit -m "Update bot"
git push

# 3. Pull on Linux server
ssh user@server
cd /opt/discord-trading-bot
git pull

# 4. Build on Linux
./build_linux_simple.sh

# 5. Deploy as systemd service
sudo systemctl restart discord-trading-bot
```

---

## 🎯 Recommendations

### **For Development/Testing:**
- ✅ Use **Simple Build** (free, fast)
- ✅ Test on both Windows and Linux
- ✅ Use virtual machines for cross-platform testing

### **For Personal Use:**
- ✅ Use **Simple Build** (free)
- ✅ Deploy on your preferred platform
- ✅ Credentials stay encrypted

### **For Commercial Distribution:**
- ✅ Use **Protected Build** (PyArmor)
- ✅ Invest in PyArmor license ($99/year)
- ✅ Build for both platforms
- ✅ Distribute with documentation

### **For High-Value Products:**
- ✅ Use **Protected Build** (PyArmor Pro)
- ✅ Additional obfuscation layers
- ✅ License server integration
- ✅ Regular security updates

---

## 📚 Platform-Specific Guides

- **Windows:** `LOCAL_RUN_GUIDE.md`
- **Linux:** `LINUX_DEPLOYMENT.md`
- **AWS EC2:** `AWS_QUICK_START.sh`
- **Build Methods:** `BUILD_METHODS_GUIDE.md`
- **Credentials:** `CREDENTIAL_MANAGEMENT.md`

---

## ✅ Quick Reference

| Task | Windows | Linux |
|------|---------|-------|
| **Simple Build** | `build_simple.bat` | `./build_linux_simple.sh` |
| **Protected Build** | `build_PyArmor.bat` | `./build_linux_protected.sh` |
| **Get Machine ID** | `GET_MACHINE_ID.bat` | `./get_machine_id.sh` |
| **Generate License** | `python generate_license_secure.py` | `python3 generate_license_secure.py` |
| **Run Bot** | `DiscordTradingBot.exe` | `./DiscordTradingBot` |
| **Credential Storage** | `%USERPROFILE%\.discord_trading_bot\` | `~/.discord_trading_bot/` |

---

## 🎯 Summary

**QuantumPulse is fully cross-platform:**
- ✅ Windows & Linux support
- ✅ Platform-specific credential encryption
- ✅ Identical feature set
- ✅ Same license format
- ✅ Two build methods per platform
- ✅ Complete documentation

**Choose your build method based on:**
- 💰 **Budget:** Simple (free) vs Protected ($99/year)
- 🔒 **Security needs:** Basic vs Strong protection
- 📦 **Distribution:** Personal vs Commercial

**🚀 You're ready to build on any platform!**
