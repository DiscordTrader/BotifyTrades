# Ψ∿ QuantumPulse - GUI Screenshots Guide

Professional Discord Trading Bot for Webull with Alpaca Paper Trading Integration

---

## 📊 Page Descriptions & Features

### 1. **Dashboard** (`/`)
**Purpose:** Overview of bot performance and account health

**Key Metrics Displayed:**
- Execution Channels: 0 (live trading channels)
- Tracking Channels: 7 (paper trading/monitoring channels)
- Open Positions: 0
- Today's P&L: $0.00

**Account Balance Section:**
- Buying Power: $1,617.25
- Net Liquidation: $2,437.25
- Unrealized P&L: -$348.00 (loss)
- Cash Balance: $1,617.25

**Live Trading Monitor:**
- 1 open position, 0 closed today
- Tabs: Live Positions | Pending Orders | Filled Orders

**Design:** Dark gradient cards with cyan/teal accents, professional trading terminal style

---

### 2. **Execution** (`/execution`)
**Purpose:** Manage trading channels with paper trading account overview

**Paper Trading & Account Info Section:**
- Status: ✓ Execution : ENABLED
- Buying Power: $39,791.98
- Net Liquidation: $20,000.00
- Unrealized P&L: +$0.00
- Cash Balance: $20,000.00
- Live Positions: 0 (No open positions)
- Pending Orders: 1 (BIDU 251121P00110000 1 BUY, Limit: $0.00)
- Auto-refresh: Every 5 seconds

**Channel Management:**
- Tabs: Execution Channels | Tracking Channels
- Add Channel button
- Can create execution and tracking channels
- Configure risk management per channel

**Design:** Professional gradient containers with electric blue borders

---

### 3. **Channels** (`/channels`)
**Purpose:** Centralized channel configuration and management

**Add New Channel Form:**
- Channel Type selector (Execution/Tracking)
- Channel Name input
- Discord Channel ID input (with paste help text)
- Execute Trades checkbox
- Track Only checkbox
- Action buttons: Add | Cancel

**Active Channels Table:**
- Columns: ID | Discord Channel ID | Name | Execute | Track | Mode | Active | Actions
- Shows all configured channels
- Edit/Delete per channel

**Design:** Clean form layout with professional styling

---

### 4. **PNL** (`/pnl`)
**Purpose:** Comprehensive profit & loss tracking and position monitoring

**Performance Summary:**
- Total Signals: 50
- BTO Signals: 34
- STC Signals: 16
- Total P&L: $20,290.00
- Average Return: +14.13%

**Filters:**
- Channel Filter dropdown
- Time Period selector

**Live Positions Table:**
- BIDU 110.0P 11/21: 1 contract @ $1.04, 0/1 closed, +$0.00 P&L, 0.0% return
- BIDU 110.0P 11/21: 1 contract @ $1.04, 0/1 closed, +$0.00 P&L, 0.0% return
- SPXW 6635.0C 11/20: 20 contracts @ $0.75, 0/20 closed, +$0.00 P&L, 0.0% return
- BULL 10.0C 11/21: 100 shares @ $0.11, 0/100 closed, +$0.00 P&L, 0.0% return

**Design:** Professional trading layout with color-coded P&L (green positive, red negative)

---

### 5. **Leaderboard** (`/leaderboard`)
**Purpose:** Rank channels and users by performance metrics

**Top Performer:**
- Channel: options
- Win Rate: 0.0%
- Total P&L: $0.00
- Trades: 0

**Summary Stats:**
- Total Channels: 7
- Total Trades: 0
- Avg Win Rate: 0.0%
- Total P&L: $0.00

**Leaderboard Tabs:**
- Channels (Active)
- Users

**Time Period Filters:**
- All Time (Selected)
- 30 Days
- 7 Days
- Today

**Rankings Table:**
- Rank | Channel | Win Rate | Wins | Losses | Total Trades | Total P&L | Avg Return
- Top Channels: options, Cblast-alerts

**Design:** Trophy-style header with stat cards and sortable table

---

### 6. **Trades** (`/trades`)
**Purpose:** Live trade monitoring and order management

**Features:**
- Refresh Prices button
- Trade tabs: Live Positions | Pending Orders | Filled Orders
- Auto-loading indicator
- Real-time price updates

**Status:** Loading (data fetching from Alpaca/Webull)

**Design:** Professional trading dashboard with live data streaming

---

### 7. **Options** (`/options`)
**Purpose:** Option chain viewer and options trading interface

**Features:**
- Symbol search (with placeholder "ENTER SYMBOL (E.G., AAPL)")
- Load Chain button
- Option chain display (with real Alpaca data)
- Strike prices, Greeks (Delta, Gamma, Theta, Vega)
- Bid/Ask spreads
- IV (Implied Volatility)

**Connected to:** Alpaca API for real market data

**Design:** Clean search interface with blue accent buttons

---

### 8. **Settings** (`/settings`) - ⭐ NEW REDESIGN
**Purpose:** Configure bot credentials, API keys, and trading parameters

**Professional Card Layout with 9 Configuration Sections:**

#### Card 1: 💹 Alpaca Paper Trading
- Alpaca API Key (password field)
- Alpaca Secret Key (password field)
- Save Credentials button
- Link to Alpaca Paper Dashboard

#### Card 2: 🔑 Discord Setup
- Discord User Token (password field)
- Help text: "Copy from browser console (not bot token)"

#### Card 3: 📢 Trade Notifications
- Enable/Disable toggle
- Webhook URL input
- Channel ID input
- Integration guide

#### Card 4: 💼 Webull Broker
- Email input
- Password input
- Device ID (DID) input
- Paper Trading Mode toggle

#### Card 5: 🤖 AI & Market Data APIs
- OpenAI API Key (for AI trade analysis)
- Alpha Vantage Key (for option flow scanning)
- Finnhub API Key (for market news & data)

#### Card 6: 🛡️ Slippage Protection
- Enable/Disable toggle
- Maximum Threshold slider (1-50%)
- Real-time percentage display
- Explanation: "Reject trades if price differs from signal by more than this %"

#### Card 7: 📊 Risk Management
- Enable/Disable monitoring
- Profit Target slider (0-100%)
- Stop Loss slider (0-100%)
- Trailing Stop slider (0-50%)

#### Card 8: 🧠 AI Analysis
- Enable/Disable toggle
- AI Model selector (GPT-4o Mini recommended / GPT-4o)
- Sentiment Analysis toggle
- Warning: "Can be expensive if enabled"

#### Card 9: 💰 Trading Limits
- Max Position Size slider ($100-$10,000)
- Auto-quantity calculation help text

**Global Success/Error Message Display**
- Shows at top of page
- Green for success, Red for error
- Auto-hides after 5 seconds

**Design:** Dark gradient cards (teal to blue), electric blue borders, smooth transitions, hover effects

---

### 9. **Signals** (`/signals`)
**Purpose:** Historical signal log with execution details

**Filter Controls:**
- Channel filter dropdown
- Time period selector
- Refresh button

**Signal Statistics:**
- Total Signals: 50
- BTO Signals: 34 (green)
- STC Signals: 16
- Total P&L: $20,290.00
- Average Return: +14.13%

**Signal History Table:**
Columns: Timestamp | Channel | Direction (BTO/STC) | Symbol | Quantity | Price | Closed Qty | P&L | Return % | Status

**Sample Signals:**
- 11/20/2025, 9:39:15 PM | options | BTO | BIDU | 1 | $1.04 | 0 | +$0.00 | +0.00% | OPEN
- 11/20/2025, 8:45:05 PM | options | BTO | BIDU | 1 | $1.04 | 0 | +$0.00 | +0.00% | OPEN
- 11/20/2025, 8:43:31 PM | options | BTO | SPXW | 20 | $0.75 | 0 | +$0.00 | +0.00% | OPEN
- 11/20/2025, 8:42:15 PM | member-alerts | BTO | BULL | 100 | $0.11 | 0 | +$0.00 | +0.00% | OPEN
- 11/20/2025, 8:40:12 PM | Cblast-alerts | BTO | BULL | 100 | $0.11 | 0 | +$0.00 | +0.00% | OPEN

**Design:** Professional table with time-series data, color-coded status badges

---

## 🎨 UI Design System

### Colors Used:
- **Primary Background:** #0a0e17 (dark navy)
- **Secondary Background:** #141821 (dark gray)
- **Card Background:** #1a1f2e (dark teal-gray)
- **Accent Primary:** #00d4ff (electric cyan)
- **Accent Secondary:** #0080ff (electric blue)
- **Success:** #00ff88 (bright green)
- **Warning:** #ffd700 (gold)
- **Error:** #ff6b6b (red)
- **Text Primary:** #ffffff (white)
- **Text Secondary:** #b4b8c5 (light gray)

### Typography:
- **Brand Font:** Orbitron (for section titles - futuristic)
- **UI Font:** Inter (for body text - professional)
- **Mono Font:** Consolas/Monaco (for technical data)

### Components:
- Gradient cards with cyan/blue borders
- Professional input fields with focus states
- Smooth sliders with real-time value display
- Toggle switches with glow effects
- Gradient buttons with hover animations
- Professional data tables with stripe styling
- Responsive grid layouts

---

## 📱 Key Features Summary

✅ **Paper Trading**: Real Alpaca paper account with $40,000 starting balance
✅ **Dual-Broker**: Webull (live) + Alpaca (paper)
✅ **Channel Management**: Execution (live) & Tracking (paper) channels
✅ **Risk Management**: Profit targets, stop losses, trailing stops per channel
✅ **Settings GUI**: Configure all credentials and parameters without config.ini
✅ **Real-time Data**: Auto-refresh every 5 seconds
✅ **Signal Tracking**: Complete FIFO P&L tracking
✅ **Live Positions**: Monitor all open trades
✅ **Professional Design**: Dark trading terminal UI with electric blue theme
✅ **API Integration**: Alpaca, Webull, OpenAI, Alpha Vantage, Finnhub

---

## 🚀 How to Share

1. **Save Screenshots:** Right-click each page screenshot in the GUI and save with format:
   - `quantumpulse-dashboard.png`
   - `quantumpulse-execution.png`
   - `quantumpulse-channels.png`
   - `quantumpulse-pnl.png`
   - `quantumpulse-leaderboard.png`
   - `quantumpulse-trades.png`
   - `quantumpulse-options.png`
   - `quantumpulse-settings.png`
   - `quantumpulse-signals.png`

2. **Use This Guide:** Share this document alongside screenshots for detailed explanation

3. **Directory Structure:**
   ```
   QuantumPulse-Screenshots/
   ├── SCREENSHOTS_GUIDE.md (this file)
   ├── quantumpulse-dashboard.png
   ├── quantumpulse-execution.png
   ├── quantumpulse-channels.png
   ├── quantumpulse-pnl.png
   ├── quantumpulse-leaderboard.png
   ├── quantumpulse-trades.png
   ├── quantumpulse-options.png
   ├── quantumpulse-settings.png
   └── quantumpulse-signals.png
   ```

---

**Ψ∿ QuantumPulse** - Professional AI-Powered Trading Bot for Discord
