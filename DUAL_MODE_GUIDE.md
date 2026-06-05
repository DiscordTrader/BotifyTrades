## License System - Dual Mode Configuration

Your bot supports **two license modes**. Choose based on your needs:

---

## 🔧 Mode 1: OFFLINE (Machine ID Upfront)

**How It Works:**
1. Customer runs bot → sees their Machine ID
2. Customer sends you their Machine ID
3. You generate machine-bound license
4. Customer enters license → activated!
5. Works 100% offline

**Pros:**
- ✅ Zero server costs
- ✅ 100% offline operation
- ✅ Strong hardware binding
- ✅ No AWS/cloud setup needed

**Cons:**
- ⚠️ Customer must share Machine ID (extra step)
- ⚠️ Manual license generation per customer

**Best For:**
- Small-medium scale (< 100 customers)
- Zero budget for servers
- Manual sales process

**Cost:** $0/month

---

## ☁️ Mode 2: SERVER (Auto-Activation)

**How It Works:**
1. Customer receives license key (no Machine ID)
2. Customer runs bot → enters license
3. Bot connects to YOUR server to activate
4. Server binds license to machine
5. Works offline after first activation

**Pros:**
- ✅ No Machine ID sharing (better UX)
- ✅ Automatic activation
- ✅ Prevents license reuse (enforced by server)
- ✅ Scalable for many customers

**Cons:**
- ⚠️ Requires AWS/cloud setup
- ⚠️ Monthly server costs (~$5-10)
- ⚠️ Requires internet for first activation

**Best For:**
- Medium-large scale (100+ customers)
- Automated sales/distribution
- Best customer experience

**Cost:** ~$5-10/month

---

## 🔄 Switching Modes

### Currently Active: OFFLINE MODE

To switch to SERVER MODE (after AWS setup):

**File:** `src/setup_wizard.py`  
**Line:** 11

```python
# Change this line:
LICENSE_MODE = 'offline'  # Current

# To this:
LICENSE_MODE = 'server'   # After AWS setup
```

Then rebuild:
```bash
build_protected.bat
```

---

## 📦 Current Setup (OFFLINE MODE)

### For You (Seller):

#### Step 1: Build Protected Executable
```bash
build_protected.bat
```

#### Step 2: Customer Sends Machine ID

Customer runs `GET_MACHINE_ID.bat` or looks at setup wizard:
```
╔═════════════════════════════════════════════════════════╗
║                                                         ║
║  🔑 YOUR MACHINE ID (Copy this!)                       ║
║                                                         ║
║  abc123def456ghi7                                      ║
║                                                         ║
╚═════════════════════════════════════════════════════════╝
```

#### Step 3: Generate License for That Machine
```bash
python generate_license_secure.py \
  --customer john_doe \
  --machine abc123def456ghi7 \
  --days 30
```

#### Step 4: Send License to Customer

Customer pastes license → ✅ Activated!

---

### For Customer:

#### What They Receive:
```
TradingBot_Package/
  ├── DiscordTradingBot.exe
  ├── GET_MACHINE_ID.bat    ← Run this FIRST
  ├── config.ini
  └── SETUP_GUIDE.txt
```

#### Customer Flow:
1. Run `GET_MACHINE_ID.bat`
2. Copy Machine ID
3. Send to you (email/support)
4. Receive license key from you
5. Run `DiscordTradingBot.exe`
6. Paste license key
7. ✅ Activated!

---

## 📝 Customer Setup Instructions Template

Include this in `SETUP_GUIDE.txt`:

```
=======================================================================
Discord Trading Bot - Setup Instructions
=======================================================================

STEP 1: GET YOUR MACHINE ID
----------------------------
1. Double-click "GET_MACHINE_ID.bat"
2. Copy the Machine ID shown (16 characters)
3. Send it to: support@yourcompany.com
   Subject: "License Request - [Your Name]"
4. Wait for license key (usually within 24 hours)

Example Machine ID: abc123def456ghi7


STEP 2: ACTIVATE YOUR LICENSE
------------------------------
1. Once you receive your license key via email
2. Double-click "DiscordTradingBot.exe"
3. Setup wizard will show YOUR Machine ID again:

   ╔═════════════════════════════════════════════════════════╗
   ║  🔑 YOUR MACHINE ID                                    ║
   ║  abc123def456ghi7                                      ║
   ╚═════════════════════════════════════════════════════════╝

4. Enter your license key when prompted
5. Continue with Discord/Webull setup


STEP 3: CONFIGURE TRADING
--------------------------
Follow the wizard to set up:
- Discord token
- Webull credentials
- Trading channels
- Paper trading mode (recommended for testing)


IMPORTANT NOTES:
----------------
⚠️  Your license is HARDWARE-LOCKED to this computer
⚠️  It will NOT work on any other machine
⚠️  If you change hardware, contact support for new license

💡 Keep your Machine ID saved for renewals!

SUPPORT:
--------
Email: support@yourcompany.com
Hours: Mon-Fri 9AM-5PM EST
=======================================================================
```

---

## 🔐 Security Comparison

| Feature | OFFLINE Mode | SERVER Mode |
|---------|--------------|-------------|
| License sharing prevention | ✅ Strong | ✅ Strongest |
| Offline operation | ✅ 100% | ⚠️ After first activation |
| Hardware binding | ✅ Cryptographic | ✅ Server-enforced |
| License revocation | ❌ Wait for expiry | ✅ Real-time |
| Setup complexity | ⭐⭐ (Machine ID step) | ⭐⭐⭐ (AWS required) |
| Customer UX | ⭐⭐ (Manual) | ⭐⭐⭐ (Automatic) |
| Monthly cost | $0 | $5-10 |

---

## 🎯 Recommendations

### Start with OFFLINE MODE if:
- You have < 50 customers
- Budget is tight ($0/month)
- Manual sales process is acceptable
- You're testing the market

### Upgrade to SERVER MODE when:
- You have 50-100+ customers
- Manual process becomes bottleneck
- Want best customer experience
- Ready to invest $5-10/month

---

## 🚀 Files Included

### OFFLINE Mode (Current):
- `src/license_manager_secure.py` - Validates machine-bound licenses
- `generate_license_secure.py` - Generates licenses with Machine ID
- `GET_MACHINE_ID.bat` - Customer tool to get Machine ID
- `build_protected.bat` - Builds obfuscated exe

### SERVER Mode (Future):
- `src/license_manager_activation.py` - Server activation client
- `generate_license_activation.py` - Generates activation licenses
- `server/` - AWS Lambda activation server (when you set up)

---

## ✅ Current Build Status

**Active Mode:** OFFLINE  
**Protection:** PyArmor Obfuscation + Machine Binding  
**Cost:** $0/month  
**Ready to distribute:** ✅ YES

**Next Steps:**
1. Build exe: `build_protected.bat`
2. Test with your own Machine ID
3. Create customer package template
4. Start selling!

When ready for AWS/SERVER mode, contact me for setup instructions.
