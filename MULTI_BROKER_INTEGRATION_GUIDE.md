# Multi-Broker Integration Guide

## 🎯 Overview

This bot has a **complete multi-broker architecture** ready to support trading on:
- ✅ **Webull** (currently active)
- ✅ **Alpaca** (commission-free, official API)
- ✅ **Interactive Brokers (IBKR)** (professional trading, global markets)

**Current Status:** Architecture complete, **not yet integrated** into main bot.

**Why not integrated?** To keep your working Webull bot stable and safe. Integration requires careful testing with real broker accounts.

---

## 📂 What's Been Built

### Core Architecture

| File | Description | Status |
|------|-------------|--------|
| `src/broker_interface.py` | Base abstraction layer with BrokerInterface, OrderResult, BrokerFactory | ✅ Complete |
| `src/brokers/webull_broker.py` | Webull implementation using broker interface | ✅ Complete |
| `src/brokers/alpaca_broker.py` | Alpaca implementation with official SDK | ✅ Complete |
| `src/brokers/ibkr_broker.py` | Interactive Brokers implementation | ✅ Complete |
| `src/brokers/__init__.py` | Broker registration with factory | ✅ Complete |
| `src/broker_manager.py` | Multi-broker routing and management | ✅ Complete |
| `config.ini` | Multi-broker configuration sections | ✅ Complete |

### What Works Now

✅ **BrokerManager** can:
- Initialize multiple brokers simultaneously
- Extract broker prefix from signals: `[ALPACA] BTO SPY @450`
- Route orders to the correct broker
- Fall back to default broker for unprefixed signals
- Safely handle unknown/disabled brokers

✅ **Configuration** supports:
- Per-broker enable/disable flags
- Individual credential sections for each broker
- Broker selection methods (prefix, channel, default)
- Paper trading mode for each broker

✅ **Security**:
- Environment variable support for all credentials
- No hardcoded secrets
- Safe credential handling

---

## 🚀 How to Complete Integration (When Ready)

### Prerequisites

Before enabling multi-broker support, you need:

1. **Broker Accounts & Credentials:**
   - ✅ Webull (already have)
   - 🔲 Alpaca account (if using): https://alpaca.markets/
   - 🔲 IBKR account (if using): https://www.interactivebrokers.com/

2. **API Keys:**
   - **Alpaca**: Get from https://app.alpaca.markets/paper/dashboard/overview
   - **IBKR**: Install TWS or IB Gateway and enable API access

3. **Packages Installed:**
   - ✅ `alpaca-py` (already installed)
   - ✅ `ib-insync` (already installed)

---

## 📝 Integration Steps

### Step 1: Set Up Broker Credentials

#### For Alpaca:
```bash
# Set environment variables (recommended)
export ALPACA_API_KEY="your_alpaca_key"
export ALPACA_API_SECRET="your_alpaca_secret"

# Or add to config.ini [alpaca] section:
api_key = your_alpaca_key
api_secret = your_alpaca_secret
paper_trade = true
```

#### For Interactive Brokers:
```bash
# Install and configure TWS or IB Gateway first
# Then set environment variables (optional):
export IBKR_HOST="127.0.0.1"
export IBKR_PORT="7497"  # 7497=paper, 7496=live
export IBKR_CLIENT_ID="1"

# Or configure in config.ini [ibkr] section (already there)
```

### Step 2: Enable Multi-Broker in Config

Edit `config.ini`:

```ini
[brokers]
# 🚧 Set this to true when ready to enable multi-broker
enable_multibroker = true

# Enable the brokers you want to use
enable_webull = true
enable_alpaca = true   # Set to true if you have Alpaca account
enable_ibkr = false     # Set to true if you have IBKR + TWS running

# Default broker for signals without prefix
default_broker = WEBULL

# How to select broker: prefix, channel, or default
broker_selection_method = prefix
```

### Step 3: Integrate BrokerManager into Main Bot

This requires modifying `src/selfbot_webull.py`:

#### A. Add imports at the top:
```python
# Add after existing imports
if ENABLE_MULTIBROKER:
    from src.broker_manager import BrokerManager
    import src.brokers  # This registers all broker implementations
```

#### B. Modify DiscordBot.__init__:
```python
def __init__(self, **kwargs):
    # ... existing code ...
    
    # Add broker manager support
    self.broker_manager = None
    self.use_multibroker = ENABLE_MULTIBROKER
```

#### C. Modify setup() method:
```python
async def setup(self):
    if self.use_multibroker:
        # Use BrokerManager
        self.broker_manager = BrokerManager(MULTIBROKER_CONFIG)
        if await self.broker_manager.initialize():
            print("[BROKER] ✓ Multi-broker manager initialized")
            self.broker_ready.set()
        else:
            print("[BROKER] ✗ Multi-broker initialization failed")
            return
    else:
        # Use existing Webull-only code
        self.broker = WebullBroker(loop=self.loop)
        try:
            await self.broker.login()
            print("[Webull] ✓ Login successful")
            self.broker_ready.set()
        except Exception as e:
            print("[Webull] ✗ Login failed:", e)
            return
    
    # ... rest of setup ...
```

#### D. Update signal parsing to extract broker prefix:
```python
async def on_message(self, message: discord.Message):
    # ... existing code ...
    
    # Extract broker prefix if multibroker enabled
    broker_name = None
    clean_content = message.content
    
    if self.use_multibroker and self.broker_manager:
        broker_name, clean_content = self.broker_manager.extract_broker_from_signal(message.content)
    
    # Use clean_content for pattern matching (prefix stripped)
    # ... existing pattern matching code ...
```

#### E. Route orders through BrokerManager:
```python
async def worker(self):
    while True:
        ch_id, sig = await self.order_queue.get()
        try:
            if self.use_multibroker:
                # Route through broker manager
                if sig['asset'] == 'option':
                    result = await self.broker_manager.place_option_order(
                        broker_name=sig.get('broker'),
                        symbol=sig['symbol'],
                        strike=sig['strike'],
                        expiry=sig['expiry'],
                        option_type=sig['opt_type'],
                        action=sig['action'],
                        quantity=sig['qty'],
                        price=sig['price'],
                        expiry_year=sig.get('expiry_year')
                    )
                else:
                    result = await self.broker_manager.place_stock_order(
                        broker_name=sig.get('broker'),
                        symbol=sig['symbol'],
                        action=sig['action'],
                        quantity=sig['qty'],
                        price=sig['price']
                    )
                
                if result.success:
                    print(f"[ORDER] ✓ {result.message}")
                else:
                    print(f"[ORDER] ✗ {result.message}")
            else:
                # Use existing Webull-only code
                # ... existing order placement code ...
```

### Step 4: Test Thoroughly

1. **Test with enable_multibroker = false** (Webull-only)
   - Verify existing functionality still works

2. **Test with enable_multibroker = true, only Webull enabled**
   - Should work identically to Webull-only mode

3. **Test broker prefix parsing**:
   - Send: `[ALPACA] BTO SPY @450`
   - Verify it routes to Alpaca

4. **Test fallback**:
   - Send: `[UNKNOWN] BTO AAPL @150`
   - Verify prefix is stripped and routes to default broker

5. **Test each broker independently**:
   - Test Webull orders
   - Test Alpaca orders (if enabled)
   - Test IBKR orders (if enabled)

---

## 🎯 Signal Format with Multi-Broker

### Prefixed Signals (Routes to Specific Broker)
```
[ALPACA] BTO 10 SPY @450
[IBKR] BTO TSLA 200c 12/15 @5
[WEBULL] STC 5 AAPL @180
```

### Unprefixed Signals (Uses Default Broker)
```
BTO 10 SPY @450        # Routes to default_broker
STC AAPL 200c 12/15 @5 # Routes to default_broker
```

### Invalid Prefix (Strips and Uses Default)
```
[DISABLED] BTO SPY @450    # Prefix stripped, routes to default
[UNKNOWN] STC AAPL @180    # Prefix stripped, routes to default
```

---

## ⚙️ Configuration Reference

### Broker Selection Methods

| Method | Description | Use Case |
|--------|-------------|----------|
| `prefix` | Use `[BROKER]` prefix in signals | Most flexible, signal-by-signal control |
| `channel` | Route based on channel ID | Future feature: channel-specific brokers |
| `default` | Always use default broker | Ignores all prefixes |

### Broker Settings

Each broker has its own configuration section:

```ini
[webull]
username = 
password = 
trade_pin = 
access_token = 
refresh_token = 
did = 
paper_trade = false

[alpaca]
api_key = 
api_secret = 
paper_trade = true

[ibkr]
host = 127.0.0.1
port = 7497           # 7497=paper, 7496=live
client_id = 1
paper_trade = true
```

---

## 🔒 Security Best Practices

1. **Use Environment Variables** for credentials (recommended):
   ```bash
   export ALPACA_API_KEY="your_key"
   export ALPACA_API_SECRET="your_secret"
   export IBKR_HOST="127.0.0.1"
   ```

2. **Never commit credentials** to git
   - Credentials should be in environment or Replit Secrets
   - Config.ini should have empty values

3. **Start with paper trading**:
   - Set `paper_trade = true` for all brokers initially
   - Test thoroughly before enabling live trading

4. **Monitor logs carefully**:
   - Check broker initialization
   - Verify order routing
   - Watch for errors

---

## 🐛 Troubleshooting

### "Broker not available"
- **Cause**: Broker disabled or failed to connect
- **Fix**: Check broker credentials and `enable_<broker>` flag

### "Unknown broker in signal, using default"
- **Cause**: Broker prefix not recognized or broker disabled
- **Fix**: Verify broker name spelling and enable flag

### Orders going to wrong broker
- **Cause**: Broker selection method misconfigured
- **Fix**: Check `broker_selection_method` in config.ini

### IBKR connection failed
- **Cause**: TWS/Gateway not running or API not enabled
- **Fix**: 
  1. Start TWS or IB Gateway
  2. Enable API access in settings
  3. Check host/port configuration

### Alpaca "Invalid API key"
- **Cause**: Wrong API keys or paper/live mismatch
- **Fix**: 
  1. Verify API keys from Alpaca dashboard
  2. Make sure using paper keys for paper trading

---

## 📊 Architecture Overview

```
Discord Signal
      ↓
[Broker Prefix Extraction]
      ↓
   ┌────────────────┐
   │ BrokerManager  │
   └────────────────┘
      ↓         ↓         ↓
  ┌─────┐   ┌──────┐   ┌──────┐
  │ WB  │   │ ALPC │   │ IBKR │
  └─────┘   └──────┘   └──────┘
      ↓         ↓         ↓
   [Order Execution on respective platforms]
```

---

## 📈 Future Enhancements

- [ ] Channel-based routing (route specific channels to specific brokers)
- [ ] Per-broker position tracking
- [ ] Cross-broker portfolio view
- [ ] Broker-specific risk management
- [ ] Order mirroring (place same order on multiple brokers)

---

## 🆘 Need Help?

1. **Test with paper trading first** - Always start safe
2. **Check logs** - BrokerManager logs all routing decisions
3. **Verify credentials** - Most issues are authentication-related
4. **Start with one broker** - Enable Webull only, then add others

---

## ✅ Validation Checklist

Before enabling multi-broker in production:

- [ ] All broker credentials configured
- [ ] Paper trading enabled for new brokers
- [ ] Tested signal parsing with prefixes
- [ ] Tested fallback to default broker
- [ ] Verified each broker connects successfully
- [ ] Tested order placement on each broker
- [ ] Monitored logs for errors
- [ ] Reviewed all orders in broker dashboards
- [ ] Comfortable with multi-broker behavior

---

**Remember:** Your current Webull-only bot is working perfectly. Only enable multi-broker when you're ready to test with real broker accounts!
