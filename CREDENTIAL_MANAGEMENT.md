# 🔐 Credential Management Guide

**QuantumPulse Bot** - Secure credential storage and management

---

## ✅ How Credentials Are Handled

### **Key Points:**
- ❌ **NOT saved to config.ini**
- ✅ **Asked at runtime** (first launch)
- ✅ **Encrypted storage** (Windows DPAPI)
- ✅ **Updateable via GUI** (Settings page)
- ✅ **Secure location** (`~/.discord_trading_bot/credentials.dat`)

---

## 🎬 First Run Experience

When customer runs the .exe for the first time:

```
C:\dist> DiscordTradingBot.exe

============================================================
    Ψ∿ QuantumPulse - First-Time Setup
============================================================

📝 This wizard will collect your credentials and store them securely.
⚠️  WARNING: These credentials give full access to your accounts!

============================================================
Step 1: License Activation
============================================================

Choose your license option:

  1) 🆓 7-Day FREE Trial (No purchase required)
  2) 💳 Subscription License (Enter license key)

Select option (1 or 2): _
```

### **If they choose Option 1 (Free Trial):**
```
🎉 ACTIVATING FREE 7-DAY TRIAL...

✅ FREE TRIAL ACTIVATED SUCCESSFULLY!
   ✓ Trial Period: 7 days
   ✓ Expires: 2025-11-26
   ✓ Customer ID: abc123def456

   📌 Your trial license key has been auto-generated.
   📌 After 7 days, you can purchase a subscription license.
```

### **If they choose Option 2 (Subscription):**
```
💳 SUBSCRIPTION LICENSE ACTIVATION

Please enter your license key: [paste key here]

Validating license...

🎉 LICENSE ACTIVATED!
   ✓ Customer: john_doe
   ✓ Expires: 2025-12-19
   ✓ Days Remaining: 30
   ✓ Machine ID: Verified
```

---

## 🔑 Credential Collection

After license activation, wizard collects credentials:

### **Step 2: Discord Token**
```
============================================================
Step 2: Discord Configuration
============================================================

Enter your Discord user token: [paste token]

✓ Discord token saved
```

**Helper Tool:** Customer can use `GET_DISCORD_TOKEN.html` included in dist folder

---

### **Step 3: Webull Credentials**
```
============================================================
Step 3: Webull Configuration
============================================================

Choose authentication method:
  1) Email/Password (Recommended - Auto token refresh)
  2) Existing Tokens (Manual)

Select option (1 or 2): 1

Enter Webull email: user@example.com
Enter Webull password: [hidden]
Enter 6-digit trading PIN: [hidden]

✓ Webull credentials saved
```

**Helper Tool:** Customer can use `GET_WEBULL_TOKENS.html` for token-based auth

---

### **Step 4: API Keys (Optional)**
```
============================================================
Step 4: API Keys (Optional)
============================================================

AI Analysis (OpenAI):
  Enter OpenAI API key (or press Enter to skip): [paste or skip]

Market Data (Alpha Vantage):
  Enter Alpha Vantage API key (or press Enter to skip): [paste or skip]

News Feed (Finnhub):
  Enter Finnhub API key (or press Enter to skip): [paste or skip]

✓ API keys saved
```

---

### **Setup Complete!**
```
============================================================
✅ SETUP COMPLETE!
============================================================

Credentials encrypted and saved:
  Location: C:\Users\YourName\.discord_trading_bot\credentials.dat
  Encryption: Windows DPAPI
  Access: Only your Windows account can decrypt

Starting bot...
Flask GUI available at: http://127.0.0.1:5000
```

---

## 🔒 How Credentials Are Stored

### **Storage Location:**
```
Windows: C:\Users\YourName\.discord_trading_bot\credentials.dat
Mac:     /Users/YourName/.discord_trading_bot/credentials.dat
Linux:   /home/YourName/.discord_trading_bot/credentials.dat
```

### **Encryption Method:**

**Windows (DPAPI):**
```python
import win32crypt

# Encrypt credentials
encrypted = win32crypt.CryptProtectData(
    json_data,
    'Discord Trading Bot Credentials',
    None, None, None, 0
)

# Save to disk
Path.home() / '.discord_trading_bot' / 'credentials.dat'
```

**Security:**
- ✅ Only current Windows user can decrypt
- ✅ Cannot decrypt on another computer
- ✅ Cannot decrypt by another user
- ✅ Tied to Windows user account

**Mac/Linux (Base64 - Basic Protection):**
```python
import base64

# Encode credentials (not secure encryption!)
encoded = base64.b64encode(json_data)
```

**Security:**
- ⚠️ Basic encoding only (not true encryption)
- ⚠️ Recommended for Windows deployment only

---

## 🔄 Updating Credentials

Customers can update credentials in two ways:

### **Method A: Flask GUI Settings Page (Recommended)**

1. **Start the bot:**
   ```
   DiscordTradingBot.exe
   ```

2. **Open browser:**
   ```
   http://127.0.0.1:5000
   ```

3. **Navigate to Settings:**
   - Click **"Settings"** in the left sidebar

4. **Update credentials:**
   ```
   Discord Configuration:
     Discord User Token: [update here]
   
   Webull Configuration:
     Webull Email: [update here]
     Webull Password: [update here]
     Trading PIN: [update here]
   
   API Keys:
     OpenAI API Key: [update here]
     Alpha Vantage API Key: [update here]
     Finnhub API Key: [update here]
   
   License:
     License Key: [update here]
   ```

5. **Save changes:**
   - Click **"Save All Settings"**
   - Bot automatically reloads

---

### **Method B: Re-run Setup Wizard**

1. **Delete credentials file:**
   ```
   Windows: del %USERPROFILE%\.discord_trading_bot\credentials.dat
   Mac:     rm ~/.discord_trading_bot/credentials.dat
   Linux:   rm ~/.discord_trading_bot/credentials.dat
   ```

2. **Run bot again:**
   ```
   DiscordTradingBot.exe
   ```

3. **Setup wizard appears again**

---

## 🛡️ Security Best Practices

### **For Developers (You):**

✅ **DO:**
- Keep SECRET_KEY secure (never share)
- Use build_PyArmor.bat for public distribution
- Test on clean Windows VM before distributing
- Include helper tools in dist folder

❌ **DON'T:**
- Commit SECRET_KEY to public GitHub
- Share your .exe with SECRET_KEY embedded
- Save customer credentials on your machine
- Log decrypted credentials to console

---

### **For Customers:**

✅ **DO:**
- Run setup wizard only once
- Keep credentials.dat file private
- Use Flask GUI to update credentials
- Enable 2FA on Discord/Webull accounts

❌ **DON'T:**
- Share credentials.dat file
- Run .exe from untrusted sources
- Share Discord token publicly
- Disable Windows DPAPI

---

## 📊 Credential Flow Diagram

```
Customer runs .exe
        ↓
Check: credentials.dat exists?
        ↓
    NO ─────→ Run Setup Wizard
        │         ↓
        │     Collect credentials
        │         ↓
        │     Encrypt with DPAPI
        │         ↓
        │     Save to credentials.dat
        │         ↓
        └─────→ Load credentials
                  ↓
              Start bot
                  ↓
         Flask GUI running
                  ↓
    Settings page allows updates
```

---

## 🔧 Troubleshooting

### **Problem: Setup wizard doesn't appear**
**Solution:**
```
Check if credentials.dat already exists:
  dir %USERPROFILE%\.discord_trading_bot\credentials.dat

If exists, delete it:
  del %USERPROFILE%\.discord_trading_bot\credentials.dat

Run .exe again
```

---

### **Problem: "Failed to decrypt credentials"**
**Cause:** credentials.dat created by different Windows user

**Solution:**
```
Delete credentials.dat:
  del %USERPROFILE%\.discord_trading_bot\credentials.dat

Run .exe again to create new encrypted file
```

---

### **Problem: Webull credentials expired**
**Solution:**
```
Option A: Update via GUI Settings page
Option B: Delete credentials.dat and re-run wizard
```

---

### **Problem: Discord token invalid**
**Solution:**
```
1. Get new token from GET_DISCORD_TOKEN.html
2. Update via Flask GUI Settings page
3. Save changes
```

---

## 📋 Credentials Checklist

Before distributing .exe to customers, verify:

```
✅ Setup wizard prompts for credentials on first run
✅ Credentials NOT saved to config.ini
✅ credentials.dat created in correct location
✅ credentials.dat encrypted (Windows DPAPI)
✅ Flask GUI Settings page allows updates
✅ Helper tools included in dist folder:
   - GET_DISCORD_TOKEN.html
   - GET_WEBULL_TOKENS.html
   - GET_MACHINE_ID.bat
✅ README.txt explains credential flow
```

---

## 🎯 Summary

| Question | Answer |
|----------|--------|
| **Where are credentials saved?** | `~/.discord_trading_bot/credentials.dat` |
| **Are they saved to config.ini?** | ❌ No |
| **Are they encrypted?** | ✅ Yes (Windows DPAPI) |
| **Can customer update them?** | ✅ Yes (Flask GUI or re-run wizard) |
| **Can they be transferred to another PC?** | ❌ No (DPAPI tied to Windows account) |
| **What if Discord token expires?** | Update via Settings page |
| **What if Webull password changes?** | Update via Settings page |
| **Is it secure?** | ✅ Yes on Windows, ⚠️ Basic on Mac/Linux |

---

🔒 **Secure, User-Friendly, Professional!**
