# Conditional Orders Guide

Conditional orders let BotifyTrades watch a price level and automatically execute a trade when the price crosses your trigger. Instead of placing an order immediately, the bot monitors in real time and fires only when conditions are met.

---

## How It Works

1. A signal arrives (from Discord, Telegram, or manual entry) with a price condition
2. The bot creates a pending conditional order and begins monitoring the price
3. When the price crosses the trigger level, the bot executes the trade on your assigned broker
4. Stop loss, profit targets, and trailing stops are applied automatically

---

## Signal Formats

### Basic Entry Signals

| Signal | Meaning |
|--------|---------|
| `AAPL over 250` | Buy AAPL when price goes above $250 |
| `SPY under 680` | Buy SPY when price drops below $680 |
| `LVRO over 1.30 SL 10% PT 1.43` | Buy LVRO above $1.30 with 10% stop loss and $1.43 profit target |
| `AAPL over 250 10% of ACCOUNT PT 260 SL 240` | Buy AAPL above $250, use 10% of account, PT at $260, SL at $240 |

### Alternative Word Order

| Signal | Meaning |
|--------|---------|
| `ABOVE SPY 500` | Same as "SPY over 500" |
| `BELOW QQQ 607` | Same as "QQQ under 607" |

### Typo Tolerance

The parser handles common typos: `ocer`, `ober`, `ovwe`, `ovre`, `ovr`, `abve`, `abov` are all treated as "over".

### Price Ranges

| Signal | Meaning |
|--------|---------|
| `FRSX over 2.35-2.40` | Trigger at $2.35 (first price used as trigger) |

### Stop Loss Formats

| Format | Example |
|--------|---------|
| Percentage | `SL 10%` or `stop loss 10%` or `stop 5%` |
| Fixed price | `SL 240` or `stop loss $1.20` or `stop 2.30` |

### Profit Target Formats

| Format | Example |
|--------|---------|
| Single target | `PT 260` or `profit target $1.43` or `target 5%` |
| Multiple targets | `PT 1.43, 1.50, 1.60` (up to 4 targets) |
| Target ranges | `first target 16.60-17` or `second target 35-35.50` |
| Percentage targets | `PT 10%` or `target 5%` |

### Position Sizing

| Format | Example |
|--------|---------|
| Account percentage | `10% of ACCOUNT` or `10% portfolio` |
| Fixed quantity | `qty 100` or `100 shares` or `50 contracts` |

### Exit Signals

| Signal | Meaning |
|--------|---------|
| `selling 80% MLTX` | Sell 80% of MLTX position |
| `out of POLA` | Full exit from POLA |
| `trimming GITS` | Trim ~50% of GITS |
| `leaving 10% MLTX` | Sell down to 10% runner |

---

## Complete Signal Examples

```
LVRO over 1.30 SL 10% profit target 1.43
SPY under 680 stop loss 2% take profit 675
AAPL over 250 10% of ACCOUNT PT 260 SL 240
FRSX over 2.35-2.4 SL $2.10 PT 2.60, 2.80, 3.00
BELOW QQQ 607 stop 1% target 600
```

---

## Global Settings (Settings Page)

These apply to all conditional orders unless overridden at the channel level.

| Setting | Description |
|---------|-------------|
| **Enable Service** | Master on/off for conditional order monitoring |
| **Default Expiry** | How long orders stay active: End of Day (4 PM), 1 Hour, 4 Hours, or 1 Day |
| **Global Trigger Offset** | Shift trigger price by a percentage or dollar amount (positive = further from price, negative = closer) |
| **Entry Price Offset** | Adjust the limit order price when triggered: +X% for aggressive fills, -X% for patient fills |
| **Auto-Execute** | Automatically place the trade when the condition is met |

### Global Risk Management (OMS/RMS)

| Setting | Description |
|---------|-------------|
| **Default Exit Strategy Mode** | `Signal` (follow trader exits), `Risk` (automated SL/PT only), or `Hybrid` (use tighter protection) |
| **Circuit Breaker** | Emergency halt when daily loss limit or error thresholds are hit |
| **Daily Loss Limit** | Stop all trading if daily losses exceed this dollar amount |
| **Max Open Positions** | Maximum simultaneous positions allowed |
| **Daily P&L Limits** | Per-broker loss/profit caps in dollars or percentage, with warning thresholds |
| **Risk Check Interval** | How often the risk engine checks positions (default: 1 second, minimum: 0.2 seconds) |

---

## Channel-Level Settings (Channels Page > Conditional Tab)

Each Discord/Telegram channel can have its own conditional order settings that override global defaults.

| Setting | Description |
|---------|-------------|
| **Enable Conditional Orders** | Turn conditional orders on/off for this channel |
| **Order Timeout** | Auto-cancel unfilled orders after X minutes (applies to all order types) |
| **Conditional Timeout** | Separate timeout specifically for conditional orders |
| **Entry Confirmation Buffer** | Only enter when price goes +X% above the signal's trigger price (confirms momentum) |
| **Breakout Reset Guard** | When price is already past the trigger at order creation, require a pullback before allowing trigger (prevents immediate execution on stale signals) |
| **Trigger Offset Mode** | Percent or Dollar offset to shift the trigger price |
| **Trigger Offset Value** | How much to shift: positive = further from current price, negative = closer |
| **Exit Strategy Mode** | `Signal` (follow trader), `Risk` (auto SL/PT), or `Hybrid` (both, SL can only tighten) |
| **Limit Cap** | Price ceiling for buy orders (trigger + X%) to prevent chasing runaway prices |
| **Slippage Protection** | Abort entry if current price has moved too far from the signal price |
| **Trailing Stop** | Activate a trailing stop after a specified gain percentage |

---

## Breakout Reset Guard

**Purpose:** Prevents a conditional order from triggering immediately when the price has already moved past the trigger level before monitoring starts.

**How it works:**
1. Signal arrives: "AAPL over 250" but AAPL is already at $252
2. With guard ON (default): Bot waits for AAPL to pull back below $250, then watches for it to cross back above $250
3. With guard OFF: Bot would trigger immediately since $252 > $250

**When to disable:** If you trust the signal source and want immediate execution regardless of current price.

---

## Limit Cap Protection

**Purpose:** Prevents chasing runaway prices after a trigger fires.

**How it works:**
- For BUY orders: Sets a maximum price = trigger + cap% (ceiling)
- For SELL orders: Sets a minimum price = trigger - cap% (floor)

**Example:** Trigger at $250 with 5% limit cap = maximum buy price of $262.50. If the price has already run to $270 by the time the order reaches the broker, it will be a limit order at $262.50 instead of a market order.

---

## Price Monitoring Chain

The bot uses a fallback chain to get real-time prices, in order of preference:

1. **Streaming (WebSocket/MQTT)** - Sub-100ms latency via Webull or Schwab data hubs
2. **Broker REST API** - Real-time polling via connected broker accounts
3. **Finnhub API** - Free real-time US stock data (requires API key)
4. **yfinance** - Free fallback with ~15 minute delay

When a faster source becomes available (e.g., broker finishes connecting), the bot automatically upgrades existing monitors from slower sources.

---

## Market Isolation

Conditional orders are routed to market-specific services:

| Market | Brokers | Service |
|--------|---------|---------|
| **US** | Webull, Alpaca, Robinhood, Schwab, IBKR, Tastytrade | US Conditional Order Service |
| **India** | Upstox, Zerodha | India Conditional Order Service |
| **Canada** | (future) | Canada Conditional Order Service |

Each market has its own isolated event loop, rate limiters, and price monitor chain. US signals never interfere with India order processing, and vice versa.

---

## Order Lifecycle

```
PENDING → ACTIVE_MONITORING → TRIGGERED → EXECUTED
                  ↓                ↓
               EXPIRED          FAILED
                  ↓
              CANCELLED
```

1. **PENDING** - Order created, waiting for monitoring to start
2. **ACTIVE_MONITORING** - Price is being watched in real time
3. **TRIGGERED** - Price crossed the trigger level
4. **EXECUTED** - Trade was placed on the broker
5. **EXPIRED** - Order timed out before triggering
6. **FAILED** - Execution failed (broker error, insufficient funds, etc.)
7. **CANCELLED** - Manually cancelled by user

---

## Safety Checks at Execution

When a conditional order triggers, the following checks run before placing the trade:

1. **Final Expiry Guard** - Rejects if order expired between trigger and execution
2. **DB Status Check** - Rejects if order was cancelled/expired in the database
3. **Price Staleness Guard** - Rejects if the last price update is older than 30 seconds
4. **Slippage Protection** - Rejects if current price has drifted too far (if enabled)
5. **Limit Cap** - Converts to limit order at capped price (if enabled)
6. **Daily P&L Check** - Blocks BTO if broker's daily loss limit is hit

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/conditional_orders` | GET | List all conditional orders (supports `status` and `market` filters) |
| `/api/conditional_orders/status` | GET | Get service status |
| `/api/conditional_orders/live_prices` | GET | Get current monitored prices |
| `/api/conditional_orders/<id>/cancel` | POST | Cancel a specific order |
| `/api/settings/conditional_orders` | GET | Get global settings |
| `/api/settings/conditional_orders` | POST | Update global settings |

---

## Dashboard View

The main dashboard shows active conditional orders with:
- Symbol and trigger condition (over/under price)
- Current live price and distance to trigger
- Assigned broker
- Stop loss and profit target levels
- Time remaining before expiry
- Status badge (Monitoring, Triggered, Expired, etc.)

---

## Quick Setup Checklist

1. Go to **Settings** and enable the Conditional Order Service
2. Set a default expiry (recommended: End of Day)
3. Configure global trigger offset if desired
4. Go to **Channels** and open a channel's settings
5. Click the **Conditional** tab
6. Enable conditional orders for that channel
7. Set a timeout (recommended: 60-240 minutes)
8. Optionally enable Breakout Reset Guard (on by default)
9. Assign brokers in the channel's **Trading** tab
10. Send a test signal like `AAPL over 250` in the configured channel
