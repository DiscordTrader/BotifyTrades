# 🎉 7-Day FREE Trial Setup - Demo Guide

## What's New?

The Discord Trading Bot now includes an **automated 7-day free trial** during installation! No license key purchase required to try it out.

---

## Installation Flow

### When you run the bot for the first time:

```
======================================================================
Discord Trading Bot - First-Time Setup
======================================================================

Step 1: License Activation
======================================================================

Choose your license option:

  1) 🆓 7-Day FREE Trial (No purchase required)
  2) 💳 Subscription License (Enter license key)

Select option (1 or 2): _
```

---

## Option 1: Free Trial (Recommended for New Users)

### When you select **Option 1**:

```
Select option (1 or 2): 1

🎉 ACTIVATING FREE 7-DAY TRIAL...

✅ FREE TRIAL ACTIVATED SUCCESSFULLY!
   ✓ Trial Period: 7 days
   ✓ Expires: 2025-11-24 12:45
   ✓ Customer ID: 2f1b33d3c093429e

   📌 Your trial license key has been auto-generated.
   📌 After 7 days, you can purchase a subscription license.

```

**What happens:**
- ✅ The system **automatically generates** a 7-day trial license
- ✅ **No license key needed** - it's created for you
- ✅ Unique customer ID assigned to your trial
- ✅ Trial expires in exactly 7 days
- ✅ Full access to all bot features during trial

**Then you continue with:**
- Discord token setup
- Webull credentials
- Trading PIN
- API keys (optional)

---

## Option 2: Subscription License (For Paying Customers)

### When you select **Option 2**:

```
Select option (1 or 2): 2

╔==========================================================╗
║                                                          ║
║          🔑 YOUR MACHINE ID (Copy this!)                ║
║                                                          ║
║              a3f9c8e2b1d4567890abcdef12345678            ║
║                                                          ║
╚==========================================================╝

📋 INSTRUCTIONS:
   1. Copy your Machine ID above
   2. Send it to the bot provider via email/support
   3. You will receive a license key bound to THIS computer
   4. Paste the license key below

⚠️  IMPORTANT: The license will ONLY work on THIS computer
   If you change hardware, you'll need a new license

Enter your subscription license key: _
```

**What happens:**
- Your unique **Machine ID** is displayed
- You send it to support to purchase a license
- You receive a **hardware-locked** license key
- Enter the license key when prompted
- License is validated and activated

---

## Technical Details

### How Trial Licenses Work

1. **Automatic Generation**: When you choose "Free Trial", the setup wizard calls:
   ```python
   trial_license_key = LicenseManager.generate_license(
       days=7,
       customer_id=f"trial_{uuid.uuid4().hex[:16]}"
   )
   ```

2. **Validation**: Trial licenses use the same validation system as paid licenses:
   - HMAC-SHA256 signature verification
   - Expiration date checking
   - Tamper protection

3. **Storage**: Trial license is saved in your encrypted credentials file:
   - Windows: `C:\Users\YourName\.discord_trading_bot\credentials.enc`
   - Encrypted with Windows DPAPI (your Windows account)

4. **Expiration**: After 7 days, you'll see:
   ```
   ❌ License expired X days ago (expired on 2025-11-24)
   ```

### Upgrading from Trial to Subscription

When your trial expires:

1. **Delete** the credentials file:
   ```cmd
   rmdir /s %USERPROFILE%\.discord_trading_bot
   ```

2. **Restart** the bot - setup wizard runs again

3. **Choose Option 2** this time

4. **Enter your purchased license key**

5. Done! ✅

---

## Benefits of This System

### For Users:
- ✅ **No commitment** - Try before you buy
- ✅ **Instant access** - No waiting for license approval
- ✅ **Full features** - Complete bot functionality during trial
- ✅ **Easy setup** - One-click trial activation

### For Developers:
- ✅ **Automatic** - No manual trial key generation
- ✅ **Secure** - Same HMAC signing as paid licenses
- ✅ **Trackable** - Unique customer IDs for each trial
- ✅ **Conversion-friendly** - Easy upgrade path to paid

---

## Code Reference

**Setup Wizard** (`src/setup_wizard.py`):
- Lines 117-169: Trial license generation flow
- Lines 170-225: Subscription license flow

**License Manager** (`src/license_manager.py`):
- `generate_license()`: Creates signed license keys
- `validate_license()`: Validates and checks expiration

---

## FAQ

**Q: Can I extend my trial?**
A: No, trials are fixed at 7 days. After expiration, purchase a subscription.

**Q: Do trial users have access to all features?**
A: Yes! Trial and subscription licenses have identical feature access.

**Q: What happens to my data after trial expires?**
A: Your trade history, settings, and channels are preserved. Just need a new license to continue.

**Q: Can I run multiple trials?**
A: Each trial generates a unique customer ID. The system doesn't prevent multiple trials, but it's meant for one-time evaluation.

---

## Summary

The 7-day free trial makes it **incredibly easy** for new users to:
- ✅ Install the bot in under 5 minutes
- ✅ Test all features with real trading (paper mode recommended!)
- ✅ Evaluate the bot's performance before purchasing
- ✅ Upgrade seamlessly when ready

**No barriers, no friction, just instant access to try the bot!** 🚀
