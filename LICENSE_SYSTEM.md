# Discord Trading Bot - Licensing System Documentation

## Overview
The Discord Trading Bot now includes a comprehensive time-based licensing system. This ensures that only authorized users with valid license keys can run the bot. The system supports flexible expiration periods (7 days, 15 days, or custom durations) and validates licenses on every bot startup.

## For Users: Getting Started with Licenses

### First-Time Setup
When you run the bot for the first time, the interactive setup wizard will prompt you for a license key:

```
============================================================
Discord Trading Bot - First-Time Setup
============================================================

Step 1: License Key
============================================================
This bot requires a valid license key to operate.
If you don't have a license key, contact the bot administrator.

Enter your license key: [paste your license key here]
```

After entering your license key, the system will validate it and display:
- ✅ License validity status
- Customer ID
- Issue date
- Expiration date
- Days remaining

### License Key Format
License keys are long base64-encoded strings that look like this:
```
eyJjdXN0b21lcl9pZCI6ICJ0ZXN0X2N1c3RvbWVyIiwgImRheXMiOiAzMCwgImV4cGlyZXMiOiAiMjAyNS0xMi0xNFQxNjo1MDozMS4yMTAyMTEiLCAiaXNzdWVkIjogIjIwMjUtMTEtMTRUMTY6NTA6MzEuMjEwMjIzIn06Oj6jRJAFwixRkWPPdeElmkQaZYPqx4RAj4OaOHGijswD
```

### Using License Keys

#### Option 1: Setup Wizard (Recommended for Local Deployment)
Run the setup wizard when first launching the bot:
```bash
python src/selfbot_webull.py
```
The wizard will prompt for your license key and store it securely in encrypted credentials.

#### Option 2: Environment Variable (Recommended for Replit/VPS)
Set the `LICENSE_KEY` environment variable:

**Replit Secrets:**
1. Go to Tools → Secrets
2. Add a new secret: `LICENSE_KEY`
3. Paste your license key value
4. Restart the bot

**Command Line (Linux/Mac):**
```bash
export LICENSE_KEY="your_license_key_here"
python src/selfbot_webull.py
```

**Command Line (Windows):**
```cmd
set LICENSE_KEY=your_license_key_here
python src/selfbot_webull.py
```

### License Expiration
The bot checks your license on every startup and displays:
- ✅ Valid license status with days remaining
- ⚠️ Warning when license has 7 or fewer days remaining
- ❌ Error and bot shutdown if license is expired

Example output:
```
[LICENSE] ✅ License valid - 25 days remaining (expires on 2025-12-14)
[LICENSE]   Customer: john_doe
[LICENSE]   Expires: 2025-12-14 16:50
```

### Expired License
If your license expires, you'll see:
```
[LICENSE] ❌ License expired 5 days ago (expired on 2025-11-09)
ERROR: Invalid or expired license. Please contact the bot administrator for a new license key.
```

Contact the bot administrator to renew your license.

---

## For Administrators: Generating License Keys

### Quick Start
Generate license keys using the `generate_license.py` script:

```bash
# Interactive mode (easiest)
python generate_license.py

# Command line mode
python generate_license.py --days 30 --customer "john_doe"
```

### Common License Durations

#### 7-Day Trial License
```bash
python generate_license.py --days 7 --customer "trial_user"
```

#### 30-Day Monthly License
```bash
python generate_license.py --days 30 --customer "monthly_customer"
```

#### 90-Day Quarterly License
```bash
python generate_license.py --days 90 --customer "quarterly_customer"
```

#### 365-Day Yearly License
```bash
python generate_license.py --days 365 --customer "yearly_customer"
```

#### Custom Duration
```bash
python generate_license.py --days 180 --customer "custom_customer"
```

### Batch License Generation
Generate multiple licenses at once:
```bash
python generate_license.py --days 30 --customer "batch_user" --batch 10
```
This creates 10 licenses (batch_user_1, batch_user_2, ..., batch_user_10).

### Interactive Mode
Run without arguments for an interactive wizard:
```bash
python generate_license.py
```

You'll be prompted to:
1. Select duration (7d, 15d, 30d, 90d, 365d, or custom)
2. Enter customer ID (optional)

Example output:
```
======================================================================
Discord Trading Bot - License Key Generator
======================================================================

Select license duration:
  1) 7 days (Trial)
  2) 15 days
  3) 30 days (Monthly)
  4) 90 days (Quarterly)
  5) 365 days (Yearly)
  6) Custom

Enter choice (1-6): 3
Enter customer ID (optional, press Enter to skip): john_doe

======================================================================
Generating 1 license key(s) - 30 days validity
======================================================================

License #1:
  Customer: john_doe
  Duration: 30 days
  Key: eyJjdXN0b21lcl9pZCI6ICJqb2huX2RvZSIsICJkYXlzIjogMzAsIC...
  
  Status: ✅ License valid - 29 days remaining (expires on 2025-12-14)
  Expires: 2025-12-14 16:50

======================================================================
License generation complete!

📋 Next steps:
  1. Copy the license key above
  2. Send it to your customer
  3. Customer enters it when running the bot for the first time
======================================================================
```

### Security Best Practices

#### Protect the Secret Key
The license system uses HMAC-SHA256 signing with a secret key defined in `src/license_manager.py`:

```python
SECRET_KEY = b"YOUR_SECRET_KEY_CHANGE_THIS_IN_PRODUCTION_12345"
```

**IMPORTANT: Change this secret key before distributing the bot!**

1. Generate a random 32-byte secret:
```python
import secrets
print(secrets.token_hex(32))
```

2. Update `src/license_manager.py`:
```python
SECRET_KEY = b"your_new_random_secret_key_here"
```

3. **Never share this secret key with customers** - they only receive license keys, not the secret

#### License Key Distribution
- Generate unique license keys for each customer
- Track customer IDs in your records
- Use the `--customer` parameter to identify who each license belongs to
- Keep a backup of generated licenses in case customers lose them

#### License Renewal
When a customer's license expires:
1. Generate a new license with the same or different duration
2. Send the new license key to the customer
3. Customer updates their license key (setup wizard or environment variable)

---

## Technical Details

### License Key Structure
Each license key contains:
- **Customer ID**: Identifier for tracking (e.g., "john_doe")
- **Issue Date**: When the license was created
- **Expiration Date**: When the license expires
- **Duration**: Number of days the license is valid
- **HMAC Signature**: Cryptographic signature to prevent tampering

The license data is JSON-encoded, signed with HMAC-SHA256, and base64-encoded for easy copying.

### Validation Process
On every bot startup:
1. License key is loaded from wizard credentials or `LICENSE_KEY` environment variable
2. Base64 decoding
3. HMAC signature verification (prevents tampering)
4. Expiration check
5. Days remaining calculation
6. Bot startup proceeds if valid, or exits with error if invalid/expired

### Storage Locations

#### Local Deployment (Setup Wizard)
- License stored in: `~/.discord_trading_bot/credentials.dat`
- Encrypted using Windows DPAPI (Windows) or base64 (Mac/Linux)
- Loaded automatically on bot startup

#### Replit/VPS Deployment (Environment Variable)
- License stored in: Replit Secrets or shell environment
- Not persisted in code files (secure)
- Loaded via `os.getenv('LICENSE_KEY')`

### Error Messages

| Error | Meaning | Solution |
|-------|---------|----------|
| `License signature verification failed` | Key was tampered with or invalid | Get a new license from administrator |
| `License expired X days ago` | License has expired | Contact administrator for renewal |
| `No license key found` | Missing LICENSE_KEY | Set environment variable or run setup wizard |
| `License key cannot be empty` | Empty input during setup | Enter a valid license key |

---

## FAQ

### How do I check my license expiration date?
The bot displays your license info on every startup:
```
[LICENSE] ✅ License valid - 25 days remaining (expires on 2025-12-14)
```

### Can I transfer my license to another machine?
Yes! License keys are not machine-specific. Simply:
1. Copy your license key
2. Run setup wizard on the new machine or set LICENSE_KEY environment variable
3. Enter the same license key

### What happens if my license expires while the bot is running?
The bot only checks licenses on startup. If your license expires while the bot is running, it will continue until restarted. On next startup, it will fail validation.

### Can I extend my license before it expires?
Yes! Simply get a new license key from the administrator and update it using the setup wizard or environment variable.

### How do I update my license key?
**Option 1: Setup Wizard**
```bash
python src/setup_wizard.py
# Answer "yes" to reconfigure
# Enter new license key when prompted
```

**Option 2: Environment Variable**
Update the `LICENSE_KEY` value in Replit Secrets or your shell environment, then restart the bot.

### Why does the bot stop immediately after starting?
If you see:
```
[LICENSE] ❌ No license key found
ERROR: License key required to run the bot.
```
You need to either:
1. Run the setup wizard to enter your license key, OR
2. Set the LICENSE_KEY environment variable

---

## Troubleshooting

### "License signature verification failed"
- You entered an invalid or corrupted license key
- Copy the license key carefully (it's case-sensitive and whitespace-sensitive)
- Contact the administrator for a new license

### "License key required to run the bot"
- No license key found in credentials or environment
- Run setup wizard: `python src/setup_wizard.py`
- Or set LICENSE_KEY environment variable

### Bot starts but shows "⚠️ License manager not available"
- This means the licensing module couldn't be imported
- Check that `src/license_manager.py` exists
- This is a fallback warning; bot will run without license validation (not recommended)

### "License expired X days ago"
- Your license has expired
- Contact the bot administrator for a renewal
- They will generate a new license key with extended expiration

---

## License System Files

- `src/license_manager.py` - Core licensing logic (validation, HMAC signing)
- `generate_license.py` - Admin tool for generating license keys
- `src/setup_wizard.py` - Interactive setup (includes license prompt)
- `src/selfbot_webull.py` - Bot startup (validates license before running)
- `LICENSE_SYSTEM.md` - This documentation file

---

## Security Notes

1. **License keys are not passwords** - They can be safely copied/stored in text files
2. **Secret key must remain private** - Only administrators should have access to `license_manager.py` secret
3. **HMAC signing prevents tampering** - Users cannot modify license expiration dates
4. **No phone-home validation** - License validation happens locally (offline-friendly)
5. **Credentials encryption** - Setup wizard encrypts stored credentials using Windows DPAPI or base64

---

## Support

For license-related issues:
- Users: Contact your bot administrator for new/renewed licenses
- Administrators: Refer to the "For Administrators" section or review `src/license_manager.py` code

For technical support:
- Check the troubleshooting section above
- Review bot console logs for detailed error messages
- Ensure you're using the latest bot version
