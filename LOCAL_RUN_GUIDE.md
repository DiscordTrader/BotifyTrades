# Ψ∿ QuantumPulse - Local Machine Setup Guide

This guide will help you run **QuantumPulse** on your local Windows, Mac, or Linux machine.

---

## 📋 **Prerequisites**

Before you begin, make sure you have:

✅ **Python 3.11+** installed ([Download here](https://www.python.org/downloads/))  
✅ **Discord User Token** (get it with `GET_DISCORD_TOKEN.html`)  
✅ **Webull Credentials** (get them with `GET_WEBULL_TOKENS.html`)  
✅ **API Keys** (optional, for advanced features):
   - OpenAI API Key (for AI trade analysis)
   - Alpha Vantage API Key (for option flow scanning)
   - Finnhub API Key (for real-time news)
   - Alpaca API Key (for live option chains)

---

## 🚀 **Quick Start (3 Steps)**

### **Windows:**
```bash
# 1. Run automatic setup
setup_local.bat

# 2. Edit config.ini with your credentials
notepad config.ini

# 3. Start the bot
run.bat
```

### **Mac/Linux:**
```bash
# 1. Make scripts executable
chmod +x setup_local.sh run.sh

# 2. Run automatic setup
./setup_local.sh

# 3. Edit config.ini with your credentials
nano config.ini

# 4. Start the bot
./run.sh
```

---

## 📦 **Manual Installation (If Needed)**

If the automatic setup doesn't work, follow these manual steps:

### **1. Install Python Dependencies**
```bash
pip install -r requirements.txt
```

### **2. Create Configuration File**
Copy the example config and edit it:
```bash
# Windows
copy config.ini.example config.ini

# Mac/Linux
cp config.ini.example config.ini
```

### **3. Configure Your Credentials**

Edit `config.ini` and add:

```ini
[Discord]
user_token = YOUR_DISCORD_USER_TOKEN

[Webull]
access_token = YOUR_WEBULL_ACCESS_TOKEN
refresh_token = YOUR_WEBULL_REFRESH_TOKEN
trade_pin = YOUR_6_DIGIT_PIN
device_id = YOUR_DEVICE_ID

[License]
license_key = YOUR_LICENSE_KEY_OR_TRIAL

[API_Keys]
openai_api_key = YOUR_OPENAI_KEY (optional)
alpha_vantage_api_key = YOUR_ALPHAVANTAGE_KEY (optional)
finnhub_api_key = YOUR_FINNHUB_KEY (optional)
alpaca_api_key = YOUR_ALPACA_KEY (optional)
alpaca_secret_key = YOUR_ALPACA_SECRET (optional)
```

### **4. Run the Bot**
```bash
# Windows
python src/selfbot_webull.py

# Mac/Linux
python3 src/selfbot_webull.py
```

---

## 🖥️ **Web GUI Access**

Once the bot is running, the **Flask web control panel** automatically starts on:

```
http://127.0.0.1:5000
```

Open this URL in your browser to access the QuantumPulse dashboard with:
- 📊 **Dashboard** - Real-time stats, live positions, pending/filled orders
- 🎯 **Execution Channels** - Configure which Discord channels to trade
- 📈 **Tracking Channels** - Monitor performance without executing trades
- 💼 **Trades** - View all executed trades with P&L
- ⚙️ **Settings** - Configure credentials, webhooks, and API keys
- 🔔 **Options** - Live option chains with Greeks (Alpaca API)
- 🏆 **Leaderboard** - Channel performance rankings

---

## ⚙️ **Configuration Precedence (Important!)**

QuantumPulse loads settings in this priority order:

1. **GUI Settings Page** (highest priority) - Stored in encrypted database
2. **Environment Variables** (`.env` file or system env vars)
3. **config.ini file** (lowest priority) - Fallback configuration

**What This Means:**
- Settings in GUI override `.env` values
- `.env` values override `config.ini` values
- You can mix sources (e.g., use `.env` for credentials, GUI for trading settings)

**Best Practices:**
- ✅ **Development**: Use `.env` file for easy credential management
- ✅ **Testing**: Use `config.ini` for quick config changes
- ✅ **Production**: Use GUI Settings page for live deployments (more secure)

**Validation Warnings:**
- ⚠️ The bot **validates credentials on startup** - watch console logs for errors
- ⚠️ Missing required credentials will prevent bot startup
- ⚠️ Optional API keys (OpenAI, Finnhub, etc.) only disable those specific features
- ⚠️ Always check `requirements.txt` matches your Python environment

---

## 🔐 **Getting Your Credentials**

### **Discord User Token**
1. Open `GET_DISCORD_TOKEN.html` in your browser
2. Log in to Discord Web
3. Press `F12` to open Developer Tools
4. Follow the on-screen instructions
5. Copy your token to `config.ini`

### **Webull Tokens**
1. Open `GET_WEBULL_TOKENS.html` in your browser
2. Follow the interactive setup wizard
3. Copy tokens to `config.ini`

### **License Key**
- **Free Trial**: Run the bot without a license - it auto-generates a 7-day trial
- **Subscription**: Enter your license key in Settings page or `config.ini`

---

## 🎯 **Features Available Locally**

✅ **All GUI Features** - Full Flask control panel  
✅ **Discord Signal Monitoring** - Auto-trade from Discord signals  
✅ **Webull Order Execution** - Stocks & options  
✅ **AI Trade Analysis** - OpenAI-powered analysis (requires API key)  
✅ **Option Flow Scanning** - Alpha Vantage integration (requires API key)  
✅ **Real-Time News** - Finnhub integration (requires API key)  
✅ **Live Option Chains** - Alpaca API with Greeks (requires API key)  
✅ **Discord Notifications** - Trade confirmations via webhook  
✅ **Risk Management** - Profit targets, stop losses, trailing stops  
✅ **Performance Tracking** - Channel leaderboards, P&L analytics  

---

## 🛠️ **Troubleshooting**

### **"Python not found"**
- Install Python 3.11+ and make sure "Add to PATH" is checked during installation
- Windows: Restart your terminal after installing Python

### **"Module not found" errors**
```bash
# Windows
python -m pip install -r requirements.txt

# Mac/Linux
python3 -m pip install -r requirements.txt
```

**If still failing:**
- Make sure `requirements.txt` is complete and up-to-date
- Try upgrading pip: `python -m pip install --upgrade pip`
- Check Python version is 3.11+ : `python --version`

### **"Discord token invalid"**
- Re-generate your token using `GET_DISCORD_TOKEN.html`
- Make sure there are no spaces or quotes in `config.ini`

### **"Webull login failed"**
- Check your tokens are correct
- Webull tokens expire - re-generate them using `GET_WEBULL_TOKENS.html`
- Make sure your trade PIN is exactly 6 digits

### **Web GUI won't load**
- Check if the bot is running (look for "Flask app running on 127.0.0.1:5000")
- Try: `http://127.0.0.1:5000` or `http://localhost:5000`
- Make sure port 5000 isn't being used by another app

### **"License expired"**
- The bot includes a 7-day free trial
- After trial, you need a subscription license key
- Enter your key in Settings page or `config.ini`

---

## 📊 **Performance & System Requirements**

**Minimum Requirements:**
- CPU: Dual-core 2.0+ GHz
- RAM: 2GB available
- Storage: 500MB free space
- Internet: Stable connection

**Recommended:**
- CPU: Quad-core 2.5+ GHz
- RAM: 4GB available
- Storage: 1GB free space
- Internet: High-speed broadband (for real-time data)

---

## 🔒 **Security Best Practices**

⚠️ **NEVER share your:**
- Discord user token
- Webull access/refresh tokens
- Trade PIN
- API keys
- License key

✅ **Recommended:**
- Keep your `config.ini` private
- Use strong passwords
- Enable 2FA on Discord and Webull
- Store credentials in environment variables (not config file)
- Never commit credentials to Git

---

## 📚 **Additional Resources**

- **Discord Setup:** `GET_DISCORD_TOKEN.html`
- **Webull Setup:** `GET_WEBULL_TOKENS.html`
- **License Info:** `LICENSE_SYSTEM.md`
- **AI Analysis Guide:** `AI_ANALYSIS_GUIDE.md`
- **Alpaca Setup:** `ALPACA_SETUP_GUIDE.md`
- **Multi-Broker Guide:** `MULTI_BROKER_INTEGRATION_GUIDE.md`

---

## 💡 **Tips for Best Results**

1. **Start with Paper Trading** - Set `paper_trade = true` in config.ini to test
2. **Use Small Position Sizes** - Start with small trades to test the system
3. **Monitor the Logs** - Watch the console output for trade execution
4. **Check the GUI** - Use the web dashboard to monitor positions
5. **Set Up Webhooks** - Get Discord notifications for all trades
6. **Enable AI Analysis** - Get OpenAI insights on your trades (optional)

---

## 🆘 **Support**

If you encounter issues:
1. Check the console logs for error messages
2. Review `TROUBLESHOOTING.md`
3. Verify all credentials are correct
4. Make sure Python 3.11+ is installed
5. Try running setup scripts again

---

## 🎉 **You're Ready!**

QuantumPulse is now running on your local machine with:
- ✨ **Professional Web GUI** with real-time data
- 🤖 **Automated Discord Trading** from signals
- 📊 **Live Position Monitoring** with P&L tracking
- 🎯 **Risk Management** with stop losses & profit targets
- 🧠 **AI-Powered Analysis** (if API keys configured)

**Happy Trading!** 🚀
