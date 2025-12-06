# 🔐 QuantumPulse - Complete License Generation Guide

## 📊 License System Overview

Your **QuantumPulse Discord Trading Bot** includes **THREE license authorization systems**. Choose the one that fits your business model:

---

## **License Systems Comparison**

| Feature | **Simple Time-Based** | **Machine-Bound** | **Server-Based** |
|---------|---------------------|------------------|------------------|
| **Hardware Locked** | ❌ No | ✅ Yes | ✅ Yes |
| **Requires Server** | ❌ No | ❌ No | ✅ Yes |
| **Remote Revocation** | ❌ No | ❌ No | ✅ Yes |
| **Customer Complexity** | ⭐ Easy | ⭐⭐ Medium | ⭐⭐⭐ Complex |
| **Machine ID Required** | ❌ Not needed | ⚠️ Must share OR auto-bind | ✅ Auto-binds |
| **Offline Operation** | ✅ Always | ✅ Always | ⚠️ 24hr grace period |
| **Monthly Server Cost** | $0 | $0 | $14 |
| **Security Level** | ⭐⭐ Medium | ⭐⭐⭐ High | ⭐⭐⭐⭐ Very High |
| **Best For** | Free trials | Selling access | Enterprise/SaaS |

---

## **🎯 SYSTEM 1: Simple Time-Based Licenses**

### **Overview**
- License contains: Customer ID + Expiration Date + HMAC signature
- NOT bound to hardware - can transfer between machines
- Validated locally (100% offline)
- Tamper-proof with cryptographic signing

### **Pros & Cons**
✅ Simple for customers (no Machine ID needed)  
✅ Can transfer between machines  
✅ Works 100% offline  
✅ Zero server costs  
❌ Customers can share license with friends  
❌ Can't remotely revoke licenses  

### **Best Used For:**
- Free trials (7-day)
- Personal use
- Low-value products
- MVP testing

---

### **📝 Generation Steps - Simple Time-Based**

#### **Step 1: One-Time Setup (Change SECRET_KEY)**

```bash
# Generate secure secret key (64 characters)
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**Output example:**
```
e4f9b2a8c3d1f5e7a2b4c6d8e0f1a3b5c7d9e1f3a5b7c9d1e3f5a7b9c1d3e5f7
```

**Update the secret in `src/license_manager.py` (line 19):**
```python
SECRET_KEY = b"e4f9b2a8c3d1f5e7a2b4c6d8e0f1a3b5c7d9e1f3a5b7c9d1e3f5a7b9c1d3e5f7"
```

⚠️ **CRITICAL:** Never share this secret with customers! Keep it private.

---

#### **Step 2: Generate License Keys**

**Interactive Mode (Recommended):**
```bash
python generate_license.py
```

**Menu options:**
```
1) 7 days (Trial)
2) 15 days
3) 30 days (Monthly)
4) 90 days (Quarterly)
5) 365 days (Yearly)
6) Custom
```

**Command Line Mode:**
```bash
# 7-day trial
python generate_license.py --days 7 --customer "trial_user_123"

# 30-day monthly subscription
python generate_license.py --days 30 --customer "john_doe"

# 365-day yearly subscription
python generate_license.py --days 365 --customer "vip_customer"

# Custom duration (180 days = 6 months)
python generate_license.py --days 180 --customer "custom_user"
```

**Batch Generation (Multiple licenses):**
```bash
# Generate 10 trial licenses
python generate_license.py --days 7 --customer "batch_trial" --batch 10

# Creates: batch_trial_1, batch_trial_2, ... batch_trial_10
```

---

#### **Step 3: Send License to Customer**

**Example license key:**
```
eyJjdXN0b21lcl9pZCI6ICJqb2huX2RvZSIsICJkYXlzIjogMzAsICJleHBpcmVzIjogIjIwMjUtMTItMTRUMTY6NTA6MzEuMjEwMjExIiwgImlzc3VlZCI6ICIyMDI1LTExLTE0VDE2OjUwOjMxLjIxMDIyMyJ9Ojo+o0SQBcIsUZFjz3XhJZpEGmWD6seEQI+DmjhxoXMzA=
```

**Customer activation:**
1. Customer runs bot: `python src/selfbot_webull.py`
2. Setup wizard prompts for license key
3. Customer pastes license key
4. Bot validates and starts

---

## **🔒 SYSTEM 2: Machine-Bound Licenses (Recommended)**

### **Overview**
- License is **locked to specific hardware fingerprint**
- Uses unique identifiers from Windows/Mac/Linux hardware
- Validated locally (100% offline)
- License works **ONLY on that specific computer**

### **Hardware Fingerprinting**
- **Windows**: MachineGuid, Hardware UUID, Motherboard Serial
- **Mac**: Hardware UUID, System Serial Number
- **Linux**: /etc/machine-id, DBUS ID, System UUID

### **Pros & Cons**
✅ **Hardware-locked** - prevents sharing/piracy  
✅ Works 100% offline  
✅ No server costs  
✅ Auto-activation option (great UX)  
❌ Can't remotely revoke (must wait for expiration)  
❌ Customer must get new license if they change PC  

### **Best Used For:**
- **Selling bot access** (prevents piracy)
- AWS/VPS deployments
- Paid subscriptions
- Protecting intellectual property

---

### **📝 Generation Steps - Machine-Bound**

#### **Method A: Auto-Activation (Best Customer Experience)**

This method automatically binds the license to customer's hardware on first run.

**Step 1: Change SECRET_KEY**

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**Update `src/license_manager_activation.py` (line 18):**
```python
SECRET_KEY = b"your_new_64_char_secret_here"
```

**Also update `generate_license_activation.py` (line 13):**
```python
SECRET_KEY = b"your_new_64_char_secret_here"
```

---

**Step 2: Generate Auto-Bind License**

```bash
# 7-day trial
python generate_license_activation.py --customer trial_user --days 7

# 30-day monthly
python generate_license_activation.py --customer john_doe --days 30

# 365-day yearly
python generate_license_activation.py --customer vip_customer --days 365
```

**Example output:**
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

**Step 3: Customer Activation**

1. Customer receives license key
2. Customer runs bot: `python src/selfbot_webull.py`
3. Setup wizard shows:
   ```
   🔑 Your Machine ID: abc123def456ghi7
      (For reference only - no need to share this)
   
   Enter your license key: [paste here]
   ```
4. Customer pastes license
5. Bot automatically binds to their hardware:
   ```
   🎉 LICENSE ACTIVATED SUCCESSFULLY!
      ✓ Bound to this machine: abc123def456ghi7
      ✓ Customer: john_doe
      ✓ Expires: 2025-12-15 12:30
      ✓ Days Remaining: 30
   
      This license will ONLY work on THIS computer.
   ```

---

#### **Method B: Manual Activation (Pre-Bind to Machine ID)**

This method requires customer to share their Machine ID first.

**Step 1: Customer Gets Machine ID**

**Windows:**
```bash
GET_MACHINE_ID.bat
```

**Mac/Linux:**
```bash
python3 -c "from src.machine_fingerprint import get_machine_id; print(get_machine_id())"
```

**Customer shares Machine ID with you:**
```
Machine ID: abc123def456ghi7
```

---

**Step 2: Generate Pre-Bound License**

```bash
python generate_license_secure.py \
  --customer john_doe \
  --machine abc123def456ghi7 \
  --days 30
```

**Step 3: Send License to Customer**

Customer pastes license, bot validates machine ID matches.

---

## **🌐 SYSTEM 3: Server-Based Authorization (Enterprise)**

### **Overview**
- Full license server (FastAPI + PostgreSQL)
- Bot validates with YOUR server every 24 hours
- Server issues JWT token for offline grace period
- Remote revocation, analytics, audit logging

### **Architecture**
```
Customer Bot → Your License Server (API) → PostgreSQL Database
                    ↓
              24hr JWT Token
                    ↓
          Offline operation until token expires
```

### **Pros & Cons**
✅ **Remote revocation** - block pirated copies instantly  
✅ **Usage analytics** - track validations, usage patterns  
✅ **Machine binding** - hardware-locked per license  
✅ **Audit logging** - see who uses what, when  
✅ **Flexible activation** - control max devices per license  
❌ **Server costs** ~$14/month (DigitalOcean/Heroku)  
❌ **Requires internet** (24hr offline grace period)  
❌ **More complex** setup and maintenance  

### **Best Used For:**
- High-value products ($100+/month)
- SaaS subscription businesses
- Enterprise customers
- Maximum anti-piracy protection

---

### **📝 Setup Steps - Server-Based**

#### **Step 1: Generate Server Keys**

```python
import secrets
print(f"LICENSE_SECRET_KEY={secrets.token_hex(32)}")
print(f"JWT_SECRET={secrets.token_hex(32)}")
print(f"ADMIN_API_KEY={secrets.token_hex(16)}")
```

**Example output:**
```
LICENSE_SECRET_KEY=e4f9b2a8c3d1f5e7a2b4c6d8e0f1a3b5c7d9e1f3a5b7c9d1e3f5a7b9c1d3e5f7
JWT_SECRET=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2
ADMIN_API_KEY=f1e2d3c4b5a69788
```

---

#### **Step 2: Deploy License Server**

**Recommended: DigitalOcean App Platform**

1. Create new App on DigitalOcean
2. Connect GitHub repo → `license_server/` folder
3. Add PostgreSQL database ($7/mo)
4. Set environment variables:
   ```
   LICENSE_SECRET_KEY=...
   JWT_SECRET=...
   ADMIN_API_KEY=...
   DATABASE_URL=postgresql://...
   ```
5. Deploy!

**Alternative: Heroku**
```bash
cd license_server
heroku create your-license-server
heroku addons:create heroku-postgresql:mini
heroku config:set LICENSE_SECRET_KEY="..."
heroku config:set JWT_SECRET="..."
heroku config:set ADMIN_API_KEY="..."
git push heroku main
```

**Server runs at:** `https://your-license-server.herokuapp.com`

---

#### **Step 3: Generate License via API**

```bash
curl -X POST https://your-server.com/api/v1/admin/licenses \
  -H "X-API-Key: your_admin_api_key" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "john_doe",
    "days": 30,
    "max_activations": 1,
    "notes": "Monthly subscription"
  }'
```

**Response:**
```json
{
  "license_key": "john_doe:1702598400:8a7f2c:signature",
  "customer_id": "john_doe",
  "expires_at": "2025-12-15T00:00:00",
  "days": 30
}
```

---

#### **Step 4: Customer Activation**

Customer enters license key in bot → Bot contacts your server → Server validates + returns 24hr JWT token → Bot runs offline for 24 hours

---

#### **Step 5: Revoke License (if needed)**

```bash
curl -X POST https://your-server.com/api/v1/admin/licenses/LICENSE_KEY/revoke \
  -H "X-API-Key: your_admin_api_key"
```

**Response:**
```json
{
  "revoked": true,
  "license_key": "john_doe:1702598400:8a7f2c:signature"
}
```

Customer's next validation attempt (within 24hrs) will fail.

---

## **🎯 Which System Should You Choose?**

### **Decision Tree:**

```
Are you selling the bot for money?
├─ NO → Use SYSTEM 1: Simple Time-Based
│
└─ YES → Do you need to prevent sharing/piracy?
    ├─ NO → Use SYSTEM 1: Simple Time-Based
    │
    └─ YES → Is your product high-value (>$50/month)?
        ├─ NO → Use SYSTEM 2: Machine-Bound (Auto-Activation)
        │        ✓ Best balance: Security + Simplicity
        │        ✓ No server costs
        │        ✓ Prevents sharing
        │
        └─ YES → Use SYSTEM 3: Server-Based
                 ✓ Maximum security
                 ✓ Remote revocation
                 ✓ Usage analytics
                 ✓ Worth $14/month for high-value products
```

---

## **📋 Quick Reference Commands**

### **Simple Time-Based:**
```bash
# Generate 30-day license
python generate_license.py --days 30 --customer john_doe
```

### **Machine-Bound (Auto-Activation):**
```bash
# Generate auto-bind license
python generate_license_activation.py --customer john_doe --days 30
```

### **Machine-Bound (Manual):**
```bash
# Customer gets Machine ID
python3 -c "from src.machine_fingerprint import get_machine_id; print(get_machine_id())"

# Generate pre-bound license
python generate_license_secure.py --customer john_doe --machine abc123def456 --days 30
```

### **Server-Based:**
```bash
# Generate license via API
curl -X POST https://your-server.com/api/v1/admin/licenses \
  -H "X-API-Key: your_key" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "john_doe", "days": 30}'
```

---

## **🔒 Security Best Practices**

### **1. Protect Your SECRET_KEY**
- ✅ Change default SECRET_KEY before distribution
- ✅ Keep SECRET_KEY private (never share with customers)
- ✅ Use strong 64-character random hex
- ✅ Store in environment variables, not in code
- ❌ Never commit SECRET_KEY to Git

### **2. Customer Distribution**
- ✅ Only share license keys (not SECRET_KEY)
- ✅ Track customer IDs in your records
- ✅ Keep backup of generated licenses
- ✅ Use unique customer IDs (email, username, etc.)

### **3. License Renewal**
- ✅ Generate new license before expiration
- ✅ Send renewal reminders at 7 days remaining
- ✅ Customer updates license via setup wizard or Settings page

---

## **💡 Pricing Strategy Recommendations**

If selling bot access:

| License Type | Duration | Suggested Price | Target |
|--------------|----------|----------------|--------|
| **Trial** | 7 days | $0 - $25 | Free trial / testing |
| **Monthly** | 30 days | $50 - $150 | Standard users |
| **Quarterly** | 90 days | $125 - $350 | 15% discount (3 months) |
| **Yearly** | 365 days | $400 - $1,200 | 30% discount (12 months) |
| **Lifetime** | 3650 days | $1,500 - $5,000 | Premium tier |

Adjust based on:
- Bot performance/win rate
- Market competition
- Target audience (retail vs institutional)
- Features included (AI analysis, live data feeds, etc.)

---

## **📦 Files Reference**

### **Simple Time-Based:**
- `src/license_manager.py` - Core validation logic
- `generate_license.py` - License generation tool
- `LICENSE_SYSTEM.md` - Full documentation

### **Machine-Bound:**
- `src/machine_fingerprint.py` - Hardware fingerprinting
- `src/license_manager_secure.py` - Validation (manual binding)
- `src/license_manager_activation.py` - Validation (auto-binding)
- `generate_license_activation.py` - Auto-bind license generator
- `generate_license_secure.py` - Manual-bind license generator
- `GET_MACHINE_ID.bat` - Customer tool (Windows)
- `ACTIVATION_LICENSE_GUIDE.md` - Full activation guide

### **Server-Based:**
- `license_server/main.py` - FastAPI server
- `license_server/admin_cli.py` - Admin CLI tool
- `license_server/README.md` - Server setup guide
- `license_server/requirements.txt` - Server dependencies
- `src/license_client.py` - Bot-side server client

---

## **🆘 Troubleshooting**

### **"License signature verification failed"**
- License key was tampered with or corrupted
- SECRET_KEY mismatch between generator and validator
- Copy license key carefully (case-sensitive, no spaces)

### **"License machine mismatch"**
- License bound to different hardware
- Customer changed computers
- Generate new license for new machine

### **"License expired X days ago"**
- License has expired
- Generate renewal license for customer
- Customer updates via setup wizard

### **"No license key found"**
- Customer hasn't activated yet
- Run setup wizard or set LICENSE_KEY environment variable
- Check `config.ini` for license_key field

---

## **✅ Final Checklist**

Before distributing your bot:

```bash
✅ Changed SECRET_KEY in license manager
✅ Tested license generation
✅ Tested customer activation flow
✅ Created license database/tracking system
✅ Prepared customer documentation
✅ Set up renewal reminders (optional)
✅ Configured payment processing (if selling)
✅ Built PyInstaller .exe (for Windows distribution)
✅ Protected code with PyArmor (optional obfuscation)
```

---

## **🎉 You're Ready!**

Your **QuantumPulse Discord Trading Bot** is now equipped with professional license management!

**Recommended for most users:** **Machine-Bound with Auto-Activation** (System 2)
- Best security vs simplicity balance
- No server costs
- Prevents piracy
- Great customer experience

**Questions or need help?** Refer to the detailed documentation files or test the license generation locally before distributing to customers.

**Happy Trading & Licensing!** 🚀📈🔐
