# 🔨 Build Methods Guide - QuantumPulse

**Two build methods available:**
1. **build_simple.bat** - Basic protection (PyInstaller only)
2. **build_PyArmor.bat** - Strong protection (PyArmor + PyInstaller)

---

## 🎯 Which Build Method Should I Use?

| Use Case | Recommended Method | Why? |
|----------|-------------------|------|
| **Personal use / Testing** | `build_simple.bat` | Free, fast builds |
| **Small customer base (<10)** | `build_simple.bat` | Basic protection sufficient |
| **Public distribution** | `build_PyArmor.bat` | Prevents reverse engineering |
| **Commercial sales** | `build_PyArmor.bat` | Professional-grade protection |
| **High-value product** | `build_PyArmor.bat` | Makes cracking very difficult |

---

## ⚙️ Method 1: build_simple.bat (Basic Protection)

### **Protection Level:** ⭐⭐ BASIC

### **Features:**
- ✅ Hardware-bound licenses
- ✅ HMAC-signed activation keys
- ✅ Fast build time (3-5 minutes)
- ❌ No code obfuscation
- ❌ Source code extractable

### **How to Build:**

```batch
build_simple.bat
```

**Output:** `dist\DiscordTradingBot.exe`

### **When to Use:**
- Personal use
- Testing
- Small trusted customer base
- Cost-conscious distribution

### **Security Note:**
- .exe can be extracted with `pyinstxtractor`
- SECRET_KEY visible in bytecode
- License checks can be bypassed by skilled developers
- Time to crack: ~30 minutes

---

## 🔒 Method 2: build_PyArmor.bat (Strong Protection)

### **Protection Level:** ⭐⭐⭐⭐ STRONG

### **Features:**
- ✅ PyArmor code obfuscation
- ✅ Encrypted bytecode
- ✅ Anti-debugging protection
- ✅ Hardware-bound licenses
- ✅ SECRET_KEY hidden from extraction
- ⚠️ Slower build time (5-8 minutes)
- 💰 Requires PyArmor ($99/year)

### **How to Build:**

```batch
REM Install PyArmor first (one-time)
pip install pyarmor

REM Then build
build_PyArmor.bat
```

**Output:** `dist\DiscordTradingBot.exe` (PROTECTED)

### **When to Use:**
- Public distribution
- Commercial sales
- High-value products
- Professional-grade protection needed

### **Security Note:**
- Source code encrypted with PyArmor
- SECRET_KEY cannot be easily extracted
- Anti-debugging measures active
- License checks protected from bypass
- Time to crack: weeks/months (expert-level required)

### **PyArmor Licensing:**

| Version | Cost | Features |
|---------|------|----------|
| **Free Trial** | $0 | Limited builds |
| **Basic** | $99/year | Recommended for commercial use |
| **Pro** | $599/year | Advanced features |

**Get license:** https://pyarmor.dashingsoft.com/pricing.html

---

## 📦 Distribution Package (Both Methods)

After building with either method, your distribution package includes:

```
dist\
  ├── DiscordTradingBot.exe       ← Main executable
  ├── config.ini                  ← Bot configuration
  ├── GET_DISCORD_TOKEN.html      ← Helper tool
  ├── GET_WEBULL_TOKENS.html      ← Helper tool
  └── GET_MACHINE_ID.bat          ← Helper tool
```

---

## 🔐 License Generation (Same for Both Methods)

Both build methods use the **same license system**: `generate_license_secure.py`

```batch
python generate_license_secure.py --customer john_doe --machine MACHINE_ID --days 30
```

**Important:**
1. Customer must share their Machine ID **first**
2. Customer runs `GET_MACHINE_ID.bat` to get their Machine ID
3. License is hardware-bound (cannot be transferred)
4. Works offline (no server required)

**Step-by-step:**
```batch
# 1. Customer runs this and sends you the ID:
GET_MACHINE_ID.bat
# Output: Machine ID: 05db47931c6a8c9e

# 2. You generate license for them:
python generate_license_secure.py --customer john_doe --machine 05db47931c6a8c9e --days 30

# 3. Send customer the license key from output
```

---

## 💾 Credential Storage (Same for Both Methods)

### **How Credentials Work:**

1. **NOT saved to config.ini** ✅
2. **Asked at runtime** on first launch ✅
3. **Encrypted storage** using Windows DPAPI ✅
4. **Updateable via GUI** Settings page ✅

### **First Run Experience:**

```
1. Customer runs: DiscordTradingBot.exe

2. Setup Wizard appears:
   ┌─────────────────────────────────────┐
   │ Ψ∿ QuantumPulse - First-Time Setup │
   └─────────────────────────────────────┘
   
   Step 1: License Activation
     1) 🆓 7-Day FREE Trial
     2) 💳 Subscription License
   
   Step 2: Discord Token
     Enter your Discord user token:
     
   Step 3: Webull Credentials
     Enter Webull email:
     Enter Webull password:
     Enter 6-digit trading PIN:
   
   ✅ Setup Complete!

3. Credentials encrypted and saved:
   Location: C:\Users\YourName\.discord_trading_bot\credentials.dat
   Encryption: Windows DPAPI
   Access: Only this Windows user can decrypt

4. Bot starts automatically
```

### **Updating Credentials Later:**

**Option A: Via Flask GUI (Recommended)**
1. Bot running → Open browser: `http://127.0.0.1:5000`
2. Go to **Settings** page
3. Update credentials
4. Click **Save**

**Option B: Re-run Setup Wizard**
1. Delete: `C:\Users\YourName\.discord_trading_bot\credentials.dat`
2. Run: `DiscordTradingBot.exe`
3. Setup wizard runs again

---

## ⚡ Quick Comparison

| Feature | build_simple.bat | build_PyArmor.bat |
|---------|-----------------|-------------------|
| **Build Time** | 3-5 min | 5-8 min |
| **Cost** | Free | $99/year |
| **Code Protection** | ❌ None | ✅ Strong |
| **License System** | ✅ Hardware-bound | ✅ Hardware-bound |
| **Credential Storage** | ✅ Encrypted DPAPI | ✅ Encrypted DPAPI |
| **SECRET_KEY Protection** | ❌ Extractable | ✅ Hidden |
| **Crack Difficulty** | ⭐⭐ Easy | ⭐⭐⭐⭐ Very Hard |
| **Recommended For** | Testing, Personal | Public Sales |

---

## 🎬 Complete Workflow Examples

### **Example 1: Personal Use (Free)**

```batch
# Build
build_simple.bat

# Test yourself
cd dist
DiscordTradingBot.exe

# Generate license for yourself
python generate_license_secure.py --customer YourName --machine YOUR_MACHINE_ID --days 365

# Done!
```

**Cost:** $0

---

### **Example 2: Commercial Sales (Professional)**

```batch
# ONE-TIME: Install PyArmor
pip install pyarmor

# Build protected version
build_PyArmor.bat

# Get customer's Machine ID
# (Customer runs GET_MACHINE_ID.bat and sends you the ID)

# Generate license
python generate_license_secure.py --customer john_doe --machine CUSTOMER_MACHINE_ID --days 30

# Send customer:
#   1. dist\ folder (entire folder)
#   2. License key (from console output)

# Customer:
#   1. Runs DiscordTradingBot.exe
#   2. Chooses Option 2 (Subscription License)
#   3. Pastes license key
#   4. Completes setup wizard
#   5. Bot starts!
```

**Cost:** $99/year (PyArmor)  
**Protection:** Strong  
**Recommended for:** Public distribution

---

## 🔍 Build Verification

After building, verify your .exe:

```batch
# Check file exists
dir dist\DiscordTradingBot.exe

# Check file size (should be 30-50 MB)
dir dist\DiscordTradingBot.exe | find "DiscordTradingBot.exe"

# Test run
cd dist
DiscordTradingBot.exe
```

---

## ❓ FAQ

### **Q: Which method should I use?**
A: For personal use → `build_simple.bat`  
   For public sales → `build_PyArmor.bat`

### **Q: Can customers share the .exe?**
A: Yes, they can share the .exe file, but each person needs their own license key tied to their specific machine.

### **Q: Can customers share their license?**
A: No. Licenses are hardware-bound to one specific computer.

### **Q: Do credentials get saved to config.ini?**
A: No. Credentials are encrypted and saved to `~/.discord_trading_bot/credentials.dat`

### **Q: How do customers update their Discord token if it expires?**
A: Via Flask GUI Settings page (`http://127.0.0.1:5000/settings`) or delete credentials.dat and re-run wizard.

### **Q: Is build_simple.bat secure enough?**
A: For small customer base and trusted users, yes. For public distribution, use build_PyArmor.bat.

### **Q: How much does PyArmor cost?**
A: $99/year (Basic) - Recommended for commercial use

### **Q: Can I try PyArmor for free?**
A: Yes, PyArmor has a free trial with limited builds.

---

## 📞 Summary

| Goal | Build Method | Cost | Protection |
|------|-------------|------|------------|
| **Test bot yourself** | build_simple.bat | Free | Basic |
| **Sell to 5-10 friends** | build_simple.bat | Free | Basic |
| **Public distribution** | build_PyArmor.bat | $99/year | Strong |
| **Commercial product** | build_PyArmor.bat | $99/year | Strong |

**Bottom Line:**
- Start with `build_simple.bat` (free)
- Upgrade to `build_PyArmor.bat` when you start selling publicly
- Both methods have the same license system and credential storage

🚀 **Happy Building!**
