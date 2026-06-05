# Alpaca API Setup Guide - Free Option Chain Data

This bot now uses **Alpaca API** for live option chain data with Greeks (Delta, Gamma, Theta, Vega). Alpaca provides **FREE** market data with paper trading accounts!

## ✅ Why Alpaca?

- **100% FREE** with paper trading account
- **No brokerage account required** for market data
- **Live option chains** with real-time quotes
- **Greeks included** (Delta, Gamma, Theta, Vega, Rho)
- **Professional Python SDK** (`alpaca-py`)
- **Works alongside Webull** - use Alpaca for data, Webull for execution

---

## 📋 Step 1: Create Free Alpaca Account

1. Go to: https://alpaca.markets
2. Click **"Sign Up"** (top right)
3. Choose **"Paper Trading"** (completely free, no credit card needed)
4. Fill out the registration form:
   - Email address
   - Password
   - Basic information
5. Verify your email
6. Login to your Alpaca dashboard

**⏱ Time: 2-3 minutes**

---

## 🔑 Step 2: Get Your API Keys

1. Login to: https://app.alpaca.markets
2. Click **"API Keys"** in the left sidebar
3. You'll see:
   - **API Key ID** (example: `PKXXXXXXXXXXXXXX`)
   - **Secret Key** (example: `XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`)
4. Click **"Regenerate Key"** if needed
5. **IMPORTANT:** Copy both keys immediately - the secret key won't be shown again!

**📝 Keys Format:**
- **API Key**: Starts with `PK` (paper) or `AK` (live)
- **Secret Key**: 40-character alphanumeric string

---

## 🔐 Step 3: Add Keys to Replit Secrets

### **If running on Replit:**

1. Click **"Tools"** → **"Secrets"** in left sidebar
2. Add two new secrets:

**Secret 1:**
- **Key:** `ALPACA_API_KEY`
- **Value:** Your API Key ID (starts with PK)

**Secret 2:**
- **Key:** `ALPACA_SECRET_KEY`
- **Value:** Your Secret Key (40 characters)

3. Click **"Add secret"** for each

### **If running locally (.env file):**

1. Open your `.env` file (or create it in project root)
2. Add these lines:

```env
ALPACA_API_KEY=PKXXXXXXXXXXXXXX
ALPACA_SECRET_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

3. Save the file
4. **NEVER commit `.env` to git** (already in `.gitignore`)

---

## ✅ Step 4: Verify Setup

1. Restart the Discord bot:
   - **Replit:** Click "Stop" then "Run" button
   - **Local:** Stop (Ctrl+C) and restart: `python src/selfbot_webull.py`

2. Check the console logs for:
   ```
   [AlpacaDataProvider] Initialized with API key: PKXXXXXX...
   ✅ Connection test successful! Found XXX SPY contracts
   ```

3. Test the Option Chain viewer:
   - Go to: http://127.0.0.1:5000/options
   - Enter a symbol (e.g., **AAPL**)
   - Click **"Load Chain"**
   - You should see calls/puts with Greeks!

---

## 🔒 Security Notes

✅ **DO:**
- Store keys in environment variables/Replit Secrets
- Use paper trading keys for development
- Regenerate keys if exposed

❌ **DON'T:**
- Hardcode keys in source code
- Share keys in Discord/GitHub
- Commit `.env` file to version control

---

## 🎯 What You Get

With Alpaca integration, your Option Chain viewer now shows:

- **✅ Live Prices:** Real-time bid/ask/last prices
- **✅ Greeks:** Delta, Gamma, Theta, Vega, Rho
- **✅ Implied Volatility:** Live IV calculations
- **✅ Volume:** Contract volume
- **✅ All Strikes:** Complete option chain
- **✅ All Expirations:** Every expiry date available

---

## 🔄 Dual Setup: Alpaca + Webull

Your bot now uses:
- **Alpaca** → Option chain data (this guide)
- **Webull** → Trade execution (existing setup)

**Both work together!** You get the best of both:
- Free market data from Alpaca
- Real trading through Webull

---

## ❓ Troubleshooting

### Error: "Alpaca data provider not configured"
**Solution:** Add `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` to environment secrets

### Error: "Connection test failed"
**Solution:** 
1. Verify keys are correct (no extra spaces)
2. Regenerate keys in Alpaca dashboard
3. Ensure you're using **paper trading** keys (start with `PK`)

### Error: "403 Forbidden"
**Solution:** Your API keys are invalid - regenerate them

### No data showing in Option Chain
**Solution:** 
1. Check console logs for errors
2. Try a liquid symbol like **SPY** or **AAPL**
3. Verify bot is running and web server is accessible

---

## 📚 Additional Resources

- **Alpaca Dashboard:** https://app.alpaca.markets
- **Alpaca Docs:** https://alpaca.markets/docs
- **Option Chain API:** https://docs.alpaca.markets/reference/optionchain
- **Python SDK Guide:** https://alpaca.markets/sdks/python/

---

## 💬 Support

**Questions?** Check the bot console logs for detailed error messages.

**Still stuck?** Verify:
1. ✅ Alpaca account created (paper trading)
2. ✅ API keys copied correctly
3. ✅ Keys added to Replit Secrets or `.env`
4. ✅ Bot restarted after adding keys

---

**🎉 That's it! Your bot now has professional-grade option chain data for free!**
