# Simplified Strong Protection Guide

## 🛡️ What You Get

**Protection Level:** Strong (days to crack, hardware-bound)  
**Cost:** $0/month (one-time PyArmor license optional)  
**Setup Time:** 30-60 minutes  

### Features

✅ **PyArmor Obfuscation** - Source code scrambled and encrypted  
✅ **Machine Binding** - Licenses tied to customer's specific hardware  
✅ **HMAC Signing** - Cryptographically signed licenses (cannot be forged)  
✅ **No Server Required** - Works 100% offline  
✅ **Easy Distribution** - Just .exe + config + license key  

### Limitations

❌ **No Remote Revocation** - Can't block licenses remotely (must wait for expiration)  
❌ **No Usage Tracking** - Can't see who's using the bot  
❌ **Hardware Changes** - Customer needs new license if they change PC  

---

## 🚀 Quick Start (3 Steps)

### Step 1: Generate SECRET_KEY (One-Time)

```python
import secrets
print(secrets.token_hex(32))
# Output: abc123def456...
```

**Replace SECRET_KEY in these files:**
1. `src/license_manager_secure.py` - Line 16
2. `generate_license_secure.py` - Line 12

**CRITICAL:** Keep this secret secure! Anyone with this can generate unlimited licenses.

---

### Step 2: Build Protected Executable

#### Windows:
```cmd
build_protected.bat
```

#### Mac/Linux:
```bash
chmod +x build_protected.sh
./build_protected.sh
```

**What it does:**
1. Obfuscates all source code with PyArmor
2. Builds standalone .exe with PyInstaller
3. Restores original source code
4. Creates `dist/DiscordTradingBot.exe`

**Build time:** 2-5 minutes

---

### Step 3: Generate Customer Licenses

#### Get Customer's Machine ID

Send customer this command to run on THEIR machine:

**Windows:**
```cmd
python -c "from src.machine_fingerprint import get_machine_id; print(get_machine_id())"
```

**Or include in exe:**
Customer runs: `DiscordTradingBot.exe` → Setup wizard shows their Machine ID

#### Generate License

```bash
python generate_license_secure.py \
  --customer john_doe \
  --machine abc123def456ghi7 \
  --days 30
```

**Output:**
```
================================================================================
LICENSE KEY GENERATED SUCCESSFULLY
================================================================================
Customer ID: john_doe
Duration: 30 days
Expires: 2025-12-15 12:30:00
Machine ID: abc123def456ghi7

License Key:
--------------------------------------------------------------------------------
eyJjdXN0b21lcl9pZCI6ICJqb2huX2RvZSIsICJtYWNoaW5lX2lkIjogImFiYzEyM...
--------------------------------------------------------------------------------

💾 License saved to: licenses/john_doe_20251115_123000.txt
📋 Database updated: licenses/license_database.txt
================================================================================
```

---

## 📦 Customer Distribution

Send each customer:

```
TradingBot_john_doe/
  ├── DiscordTradingBot.exe  (Protected executable)
  ├── config.ini             (Configuration template)
  ├── LICENSE_KEY.txt        (Their unique machine-bound license)
  └── README.txt             (Setup instructions)
```

### README.txt Template

```
=======================================================================
Discord Trading Bot - Setup Instructions
=======================================================================

STEP 1: SETUP
-------------
1. Extract all files to a folder (e.g., C:\TradingBot\)
2. Edit config.ini:
   - channel_ids = YOUR_DISCORD_CHANNEL_IDS
   - paper_trade = true (for testing) or false (for live trading)
3. Save config.ini

STEP 2: FIRST RUN
-----------------
1. Double-click DiscordTradingBot.exe
2. Setup wizard will appear
3. When asked for license key, paste from LICENSE_KEY.txt
4. Enter Discord token and Webull credentials
5. Done! Bot will start automatically

YOUR LICENSE:
-------------
- Duration: 30 days
- Expires: 2025-12-15
- Bound to THIS computer only

IMPORTANT:
----------
⚠️  This license is HARDWARE-BOUND
⚠️  It will NOT work on any other computer
⚠️  If you change your PC, contact us for new license

SUPPORT:
--------
Email: your_support@email.com
=======================================================================
```

---

## 🔧 License Management

### Common Scenarios

#### 1. Generate 7-Day Trial
```bash
python generate_license_secure.py --customer trial_user --machine abc123def456ghi7 --days 7
```

#### 2. Generate 1-Year License
```bash
python generate_license_secure.py --customer premium_customer --machine abc123def456ghi7 --days 365
```

#### 3. Renewal (Same Customer, Same Machine)
```bash
python generate_license_secure.py --customer john_doe --machine abc123def456ghi7 --days 30
```

#### 4. Customer Changed Hardware
Customer must provide NEW machine ID, then:
```bash
python generate_license_secure.py --customer john_doe --machine xyz789abc012def3 --days 30
```

#### 5. Batch Generate (10 Licenses, Same Machine)
```bash
python generate_license_secure.py --customer batch --machine abc123def456ghi7 --days 30 --batch 10
# Creates: batch_1, batch_2, ..., batch_10
```

---

## 📊 License Tracking

All generated licenses are automatically tracked in `licenses/` folder:

```
licenses/
  ├── john_doe_20251115_120000.txt      (Individual license files)
  ├── jane_smith_20251115_130000.txt
  ├── premium_user_20251115_140000.txt
  └── license_database.txt              (Master database)
```

**license_database.txt** format:
```
2025-11-15 12:00:00 | john_doe             |  30 days | Machine: abc123def456ghi | Expires: 2025-12-15
2025-11-15 13:00:00 | jane_smith           |   7 days | Machine: xyz789abc012def | Expires: 2025-11-22
2025-11-15 14:00:00 | premium_user         | 365 days | Machine: qwe456rty789asd | Expires: 2026-11-15
```

---

## 🔒 Security Features

### What's Protected

✅ **Source Code**
- All Python files obfuscated with PyArmor
- Variable names scrambled
- String encryption
- Control flow obfuscation
- Bytecode encryption

✅ **License System**
- HMAC-SHA256 cryptographic signing
- Timing-safe signature comparison
- Machine fingerprint validation
- Expiration enforcement

✅ **SECRET_KEY**
- Embedded in obfuscated code (very hard to extract)
- Not in plaintext anywhere
- Would require deobfuscating PyArmor first (difficult)

### Attack Resistance

| Attack Method | Protection | Time to Crack |
|---------------|------------|---------------|
| Simple decompile | PyArmor obfuscation | Days-Weeks |
| Extract SECRET_KEY | PyArmor + code scrambling | Weeks |
| Forge license | HMAC signing | Impossible without SECRET_KEY |
| Transfer license | Machine binding | Blocked (wrong hardware) |
| Bypass validation | Obfuscated code flow | Days-Weeks |

**Reality Check:** Determined expert with weeks of effort CAN crack this. But for most users, it's not worth the time vs. just buying a license.

---

## 💰 Cost Breakdown

| Item | Cost | Frequency |
|------|------|-----------|
| PyArmor Free | $0 | One-time |
| PyArmor Pro (optional) | $299/year | Annual |
| PyInstaller | $0 | Free |
| Distribution | $0 | Free |
| **Total (Basic)** | **$0** | **-** |
| **Total (Pro)** | **$299/year** | **Annual** |

**PyArmor Free vs Pro:**
- **Free:** Good obfuscation, suitable for small-scale (< 100 users)
- **Pro:** Stronger obfuscation, anti-debugging, commercial license, unlimited users

**Recommendation:** Start with Free, upgrade to Pro if you exceed 100 customers or need stronger protection.

---

## 🐛 Troubleshooting

### Build Issues

**"PyArmor not found"**
```bash
pip install pyarmor
```

**"PyInstaller not found"**
```bash
pip install pyinstaller
```

**Build fails during obfuscation**
- Check PyArmor is installed: `pyarmor --version`
- Try: `pyarmor gen --clean src/`

**Exe size too large**
- Normal for PyInstaller (50-150 MB)
- Includes Python interpreter + all dependencies

### License Issues

**"Invalid license format"**
- Check license key copied correctly (no line breaks)
- Verify it's from `generate_license_secure.py`

**"License machine mismatch"**
- License is bound to different hardware
- Generate new license with correct machine ID

**"License expired"**
- License duration ended
- Generate renewal license with same customer_id

**Customer can't get Machine ID**
- Ensure bot exe is on their machine
- Run: `python -c "from src.machine_fingerprint import get_machine_id; print(get_machine_id())"`
- Or check setup wizard output (displays Machine ID)

---

## 📈 Scaling

### Small Scale (1-20 Customers)
- Use PyArmor Free
- Manual license generation
- Email distribution
- **Cost:** $0/month

### Medium Scale (20-100 Customers)
- Consider PyArmor Pro ($299/year)
- Create distribution portal (simple website)
- Automated email delivery
- **Cost:** $25/month

### Large Scale (100+ Customers)
- Upgrade to PyArmor Pro
- Consider server-side validation (Option A from earlier)
- Automated license management system
- Usage analytics
- **Cost:** $50-100/month (includes server)

---

## 🎓 Advanced Tips

### 1. Change SECRET_KEY Periodically

**Every 6-12 months:**
1. Generate new SECRET_KEY
2. Update both files (`license_manager_secure.py` and `generate_license_secure.py`)
3. Rebuild exe
4. Regenerate all active licenses with new key
5. Send updated exe + new licenses to customers

**Why:** If SECRET_KEY is ever extracted, rotating it invalidates all cracked versions.

### 2. Add Version Checking

In `license_manager_secure.py`:
```python
MIN_VERSION = "1.2.0"  # Force customers to update

def validate_license(license_key: str) -> Tuple[bool, dict]:
    # ... existing code ...
    
    # Check version in license payload
    if payload.get('min_version') and payload['min_version'] > CURRENT_VERSION:
        return False, {"error": "Please update to latest version"}
```

### 3. Track Support Requests

Create `customer_support.txt`:
```
2025-11-15 | john_doe | Machine changed - issued new license
2025-11-16 | jane_smith | Extended trial by 7 days
2025-11-17 | premium_user | Renewal sent - 365 days
```

### 4. Watermark Builds

Add customer ID to build:
```python
# In license_manager_secure.py
DISTRIBUTOR_ID = "reseller_abc"  # Different for each distributor
# Include in license validation logging
```

---

## ✅ Final Checklist

Before distributing to first customer:

- [ ] Changed SECRET_KEY in both files
- [ ] Tested build_protected.bat/sh successfully
- [ ] Verified exe size (50-150 MB is normal)
- [ ] Tested exe runs without Python installed
- [ ] Generated test license and validated it works
- [ ] Tested machine mismatch (license from different machine ID fails)
- [ ] Tested expired license (fails correctly)
- [ ] Created README.txt for customers
- [ ] Set up licenses/ folder tracking
- [ ] Windows Defender exclusion added (if needed)

---

## 🎉 You're Ready!

Your bot now has **strong protection**:

✅ Obfuscated source code (PyArmor)  
✅ Machine-bound licenses (hardware fingerprinting)  
✅ Cryptographic signing (HMAC-SHA256)  
✅ No monthly server costs  
✅ Simple distribution process  

**Protection Level:** Strong  
**Crack Difficulty:** Days-Weeks for experts  
**Cost:** $0-299/year  
**Customer Experience:** Simple setup  

Start selling with confidence! 🚀
