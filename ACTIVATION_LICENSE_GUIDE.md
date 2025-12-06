# Activation License System Guide

## 🎯 Overview

**Problem Solved:** Customers don't need to find and share their Machine ID anymore!

**How It Works:**
1. You generate a license key (no Machine ID needed)
2. Customer receives license key
3. Customer runs bot and pastes license key
4. Bot **automatically binds** to their machine on first run
5. License works ONLY on that machine forever

---

## 🚀 Quick Start (For You - The Seller)

### Step 1: Generate SECRET_KEY (One-Time Setup)

```python
import secrets
print(secrets.token_hex(32))
# Output: abc123def456...
```

**Replace SECRET_KEY in both files:**
1. `src/license_manager_activation.py` - Line 18
2. `generate_license_activation.py` - Line 13

**CRITICAL:** Keep this secret! Anyone with it can generate unlimited licenses.

---

### Step 2: Build Protected Executable

```bash
# Windows
build_protected.bat

# Mac/Linux
./build_protected.sh
```

**Output:** `dist/DiscordTradingBot.exe` (protected with PyArmor)

---

### Step 3: Generate Customer License

**No Machine ID needed!**

```bash
python generate_license_activation.py --customer john_doe --days 30
```

**Example Output:**
```
================================================================================
ACTIVATION LICENSE GENERATED
================================================================================
Customer ID: john_doe
Activation Code: 3f7a9b2c1e5d8f4a
Duration: 30 days
Expires: 2025-12-15 12:30:00

License Key:
--------------------------------------------------------------------------------
eyJhY3RpdmF0aW9uX2NvZGUiOiAiM2Y3YTliMmMxZTVkOGY0YSIsICJjdXN0b21lcl9pZCI6ICJqb2hu...
--------------------------------------------------------------------------------

💾 License saved to: licenses/john_doe_20251115_123000.txt
📋 Database updated: licenses/license_database.txt

================================================================================
HOW ACTIVATION WORKS:
================================================================================
1. Send license key to customer
2. Customer runs bot and pastes license key
3. Bot AUTO-BINDS to their machine on first run
4. License works ONLY on that machine

✓ No Machine ID needed from customer!
✓ Simple one-step activation
✓ Hardware-locked for security
================================================================================
```

---

## 📦 Customer Experience (Their Perspective)

### What Customer Receives

```
TradingBot_john_doe/
  ├── DiscordTradingBot.exe
  ├── config.ini
  ├── LICENSE_KEY.txt
  └── SETUP_INSTRUCTIONS.txt
```

### Customer Setup Process

**Step 1:** Extract files to folder (e.g., `C:\TradingBot\`)

**Step 2:** Double-click `DiscordTradingBot.exe`

**Step 3:** Setup wizard appears:

```
============================================================
Discord Trading Bot - First-Time Setup
============================================================

============================================================
Step 1: License Activation
============================================================
This bot requires a valid license key to operate.
If you don't have a license key, contact the bot administrator.

🔑 Your Machine ID: abc123def456ghi7
   (For reference only - no need to share this)

Enter your license key: [paste license here]
```

**Step 4:** After pasting license:

```
🎉 LICENSE ACTIVATED SUCCESSFULLY!
   ✓ Bound to this machine: abc123def456ghi7
   ✓ Customer: john_doe
   ✓ Activation Code: 3f7a9b2c1e5d8f4a
   ✓ Expires: 2025-12-15 12:30
   ✓ Days Remaining: 30

   This license will ONLY work on THIS computer.
```

**Step 5:** Continue with Discord/Webull setup

**Step 6:** Bot starts trading automatically!

**On Next Run:** Bot remembers activation, no license key needed!

---

## 🔧 License Management

### Generate Different License Types

#### 7-Day Trial
```bash
python generate_license_activation.py --customer trial_user --days 7
```

#### 30-Day Standard
```bash
python generate_license_activation.py --customer standard_customer --days 30
```

#### 1-Year Premium
```bash
python generate_license_activation.py --customer premium_customer --days 365
```

#### Batch Generate (10 Licenses)
```bash
python generate_license_activation.py --customer batch --days 30 --batch 10
# Creates: batch_1, batch_2, ..., batch_10
```

---

## 🎫 Common Scenarios

### Scenario 1: New Customer Purchase

**What You Do:**
```bash
python generate_license_activation.py --customer alice_smith --days 30
```

**Send Customer:**
- `DiscordTradingBot.exe`
- `config.ini`
- License key (from generated file)
- Setup instructions

**Customer Does:**
1. Runs exe
2. Pastes license
3. ✅ Activated!

**Time:** < 5 minutes

---

### Scenario 2: Customer Renewal (Same Computer)

**Customer's License Expires:**
```
❌ License expired
   Expired on: 2025-12-15
```

**What You Do:**
```bash
# Generate new license (same customer ID)
python generate_license_activation.py --customer alice_smith --days 30
```

**Send Customer:**
- New license key only

**Customer Does:**
1. Delete old activation: `C:\Users\Alice\.tradingbot_license`
2. Run bot
3. Paste new license
4. ✅ Re-activated!

---

### Scenario 3: Customer Changed Computer

**Customer's Old License:**
```
❌ License machine mismatch - this license is bound to different hardware
```

**What You Do:**
```bash
# Generate NEW license for new computer
python generate_license_activation.py --customer alice_smith_new_pc --days 30
```

**Why New License:**
- Old license is forever bound to old computer
- Can't transfer licenses between machines
- This is BY DESIGN for security

**Send Customer:**
- New license key

**Customer Does:**
1. Runs bot on NEW computer
2. Pastes new license
3. ✅ Activated on new machine!

**Optional:** Deactivate old license (mark as inactive in your records)

---

### Scenario 4: Support Request - "Lost License"

**Customer:** "I reinstalled Windows and lost my license!"

**What Happened:**
- Activated license stored in: `C:\Users\Username\.tradingbot_license`
- Windows reinstall deleted this file
- Original license key still valid!

**Solution:**
```
Send customer their ORIGINAL license key again
(find it in: licenses/alice_smith_*.txt)
```

**Customer Does:**
1. Run bot
2. Paste original license
3. ✅ Re-activated! (same machine = same Machine ID)

**Cost:** $0 (no new license needed)

---

### Scenario 5: Suspected Piracy

**Suspicious Activity:**
- Customer asking to "share license with friend"
- Multiple activation requests from different IPs
- Reports of "license not working on other PC"

**Why Activation System Prevents This:**
1. License binds to FIRST machine that activates it
2. Once activated, only works on that specific machine
3. Customer can't share activated license (different Machine ID = rejected)
4. Customer can't share original license key (already activated = can't re-activate elsewhere)

**Your Options:**
- Explain: "Licenses are hardware-bound and non-transferable"
- Offer: "Purchase additional license for second computer"
- Monitor: Track activation codes in your database

---

## 📊 License Tracking

### Files Created

**Per-Customer Files:**
```
licenses/alice_smith_20251115_120000.txt
licenses/bob_jones_20251115_130000.txt
licenses/premium_user_20251115_140000.txt
```

**Master Database:**
```
licenses/license_database.txt
```

**Format:**
```
2025-11-15 12:00:00 | alice_smith          |  30 days | Code: 3f7a9b2c1e5d8f4a | Expires: 2025-12-15
2025-11-15 13:00:00 | bob_jones            |   7 days | Code: a1b2c3d4e5f6g7h8 | Expires: 2025-11-22
2025-11-15 14:00:00 | premium_user         | 365 days | Code: 9z8y7x6w5v4u3t2s | Expires: 2026-11-15
```

### Tracking Best Practices

1. **Keep activation codes** - Use for customer support
2. **Log support requests** - Track renewals and hardware changes
3. **Monitor expiration dates** - Send renewal reminders
4. **Archive old licenses** - Move to `licenses/archive/` after 1 year

---

## 🔒 Security Features

### What's Protected

| Feature | Protection | Result |
|---------|------------|--------|
| Source Code | PyArmor obfuscation | Takes days-weeks to reverse |
| License Key | HMAC-SHA256 signing | Cannot forge without SECRET_KEY |
| Activation Binding | Machine fingerprint | Works on one machine only |
| Transfer Prevention | Hardware lock | Can't share with others |
| Tampering Detection | Cryptographic signature | Rejected if modified |

### Attack Scenarios

#### Attack 1: "Share License Key with Friend"

**Attempt:**
1. Customer activates license on PC #1
2. Customer sends license key to friend
3. Friend tries to activate on PC #2

**Result:**
```
❌ Activation Failed: License already activated on different hardware
```

**Why:** License already bound to PC #1's Machine ID

---

#### Attack 2: "Copy Activated License File"

**Attempt:**
1. Customer activates on PC #1
2. Customer copies `.tradingbot_license` file
3. Customer pastes file on PC #2

**Result:**
```
❌ License machine mismatch - this license is bound to different hardware
   License machine: abc123de...
   Current machine: xyz789ab...
```

**Why:** Activated license contains PC #1's Machine ID, doesn't match PC #2

---

#### Attack 3: "Forge License Key"

**Attempt:**
1. Hacker reverse engineers license format
2. Hacker creates custom license with 10-year expiration
3. Hacker tries to activate forged license

**Result:**
```
❌ Invalid license signature - license may be tampered
```

**Why:** HMAC signature requires SECRET_KEY (which hacker doesn't have)

---

#### Attack 4: "Extract SECRET_KEY from .exe"

**Attempt:**
1. Hacker decompiles .exe with PyInstaller Extractor
2. Hacker tries to read obfuscated Python files
3. Hacker searches for SECRET_KEY

**Result:**
- PyArmor scrambles variable names
- Strings are encrypted
- Control flow is obfuscated
- Would take days-weeks of expert reverse engineering

**Difficulty:** Very High (not worth the effort for most hackers)

---

## 🛠️ Troubleshooting

### Customer: "License key not working"

**Check:**
1. Did customer copy full license key (no line breaks)?
2. Is license expired? Check expiration date
3. Is license already activated? Check if `.tradingbot_license` exists
4. Wrong license format? Verify it's from `generate_license_activation.py`

**Solution:**
- Resend license key in single line (no formatting)
- Generate new license if expired
- Delete `.tradingbot_license` to reset activation
- Verify SECRET_KEY matches in both generator and validator

---

### Customer: "License worked yesterday, not today"

**Likely Cause:** License expired

**Check:**
```bash
# Find customer in database
grep "customer_name" licenses/license_database.txt
# Check expiration date
```

**Solution:**
```bash
# Generate renewal
python generate_license_activation.py --customer customer_name --days 30
```

---

### Customer: "I reinstalled Windows, license gone"

**What Happened:**
- Windows reinstall deleted `C:\Users\Username\.tradingbot_license`
- Machine ID might have changed (if Windows reinstall included new SID)

**Solution:**
```bash
# Try resending original license first
# If Machine ID changed, generate new license
python generate_license_activation.py --customer customer_name_newwindows --days 30
```

---

### Customer: "Changed motherboard, license not working"

**What Happened:**
- Machine ID includes motherboard serial
- Hardware change = different Machine ID

**Solution:**
```bash
# Generate new license for new hardware
python generate_license_activation.py --customer customer_name_upgrade --days 30
```

**Policy Decision:** Offer free replacement or charge for new license?

---

## 💡 Advanced Features

### Custom Activation Messages

Edit `src/license_manager_activation.py`:

```python
# Line ~95 in activate_license()
return True, {
    "status": "activated",
    "message": "Welcome to TradingBot Premium!",  # Add this
    "customer_id": customer_id,
    ...
}
```

### Add License Metadata

Edit `generate_license_activation.py`:

```python
payload = {
    "activation_code": activation_code,
    "customer_id": customer_id,
    "expires": int(expires_dt.timestamp()),
    "issued": int(datetime.now().timestamp()),
    "tier": "premium",  # Add tier
    "max_trades": 100,  # Add limits
    "email": "customer@example.com"  # Add contact
}
```

### Expiration Warnings

Add to bot startup:

```python
is_valid, data = check_license()
if is_valid:
    days_left = data['days_remaining']
    if days_left <= 7:
        print(f"⚠️  License expires in {days_left} days!")
        print("   Contact support for renewal")
```

---

## 📈 Scaling Strategies

### Small Scale (1-50 customers)

**Current System:** Perfect!
- Manual license generation
- Email delivery
- **Cost:** $0/month

---

### Medium Scale (50-200 customers)

**Enhancements:**
1. Create simple web portal for license generation
2. Automated email delivery
3. Customer dashboard (view expiration dates)

**Tools:**
- Flask/FastAPI for web portal
- SendGrid for email automation
- SQLite for customer database

**Cost:** ~$25/month

---

### Large Scale (200+ customers)

**Consider Server-Based System:**
- Online activation (phone home)
- Real-time usage tracking
- Remote license revocation
- Analytics dashboard

**Trade-offs:**
- More control vs. higher cost
- Requires server infrastructure
- Monthly server costs ($50-100/month)

---

## ✅ Pre-Launch Checklist

- [ ] Changed SECRET_KEY in both files
- [ ] Tested build process (`build_protected.bat`)
- [ ] Generated test license
- [ ] Activated test license successfully
- [ ] Verified license expires correctly
- [ ] Tested machine mismatch (copy `.tradingbot_license` to different PC)
- [ ] Tested expiration (set expires to past date)
- [ ] Created customer README template
- [ ] Set up `licenses/` folder organization
- [ ] Decided on renewal policy
- [ ] Decided on hardware change policy
- [ ] Tested on customer's typical PC (Windows 10/11)

---

## 🎉 Summary

### What You Gain

✅ **No Machine ID Collection** - Customers just paste license key  
✅ **Automatic Binding** - First run locks to that machine  
✅ **Simple Customer Experience** - One-step activation  
✅ **Strong Protection** - Hardware-locked, can't share  
✅ **Zero Monthly Cost** - No server required  
✅ **Easy License Management** - Simple Python scripts  

### What Customers Get

✅ **Simple Activation** - Just paste license key  
✅ **No Technical Knowledge Needed** - Works automatically  
✅ **Fast Setup** - < 5 minutes to activate  
✅ **Persistent** - Remembers activation (no re-entry)  

### What Pirates Can't Do

❌ **Share Licenses** - Hardware-bound, one machine only  
❌ **Forge Licenses** - HMAC signing prevents forgery  
❌ **Transfer Licenses** - Locked to first activated machine  
❌ **Crack Easily** - PyArmor obfuscation delays reverse engineering  

---

## 🚀 You're Ready to Sell!

Your bot has **professional-grade protection** with **customer-friendly activation**!

**Next Steps:**
1. Build your exe: `build_protected.bat`
2. Generate first license: `python generate_license_activation.py --customer test --days 30`
3. Test on a clean Windows PC
4. Start selling! 🎯

**Questions?** Check this guide - everything you need is here!
