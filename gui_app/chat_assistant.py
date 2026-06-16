"""
BotifyTrades AI Chat Assistant
Smart FAQ + Intent-Based Help System with Error Monitoring
"""
import re
from typing import Dict, List, Tuple, Optional
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone

KNOWLEDGE_BASE = {
    "getting_started": {
        "keywords": ["start", "begin", "setup", "first time", "new user", "how to use", "getting started", "introduction", "guide"],
        "title": "Getting Started with BotifyTrades",
        "content": """Welcome to BotifyTrades! Here's how to get started:

**Step 1: Setup Your Account**
When you first access BotifyTrades, you'll be guided through a setup wizard to create your admin account with a username, email, and secure password.

**Step 2: Configure Your Broker**
Go to **Admin → Settings → Brokers** section and connect at least one broker:
• **Schwab** - OAuth connection, click "Connect with Schwab"
• **Webull** - Email/password login with DID
• **Alpaca** - API key + secret (paper trading available)
• **IBKR** - TWS/Gateway host, port, client ID
• **Tastytrade** - Username + password or OAuth
• **Robinhood** - Email + password + 2FA TOTP secret

**Step 3: Add Discord Channels**
Go to **Trading → Channels** page and add Discord channels to monitor:
• Click "Add Channel", paste the Discord Channel ID and give it a name
• Toggle **Execute** (places real broker orders) and/or **Track** (P&L tracking only)
• Assign a broker in the **Execution** column for each channel

**Step 4: Link Brokers to Channels**
Go to **Trading → Execution** page to assign which broker(s) execute trades for each channel.
• Select one or multiple brokers per channel (multi-broker execution supported)

**Step 5: Configure Risk Management**
Set profit targets, stop losses, and trailing stops in **Admin → Settings → Risk Management** (global defaults).
Override per-channel in **Trading → Channels → click channel → Per-Channel Risk** settings.

**Step 6: Configure Position Sizing**
In each channel's settings, set position size %, max position $, or fixed default quantity.

You're all set! The bot monitors your channels and executes/tracks trades automatically."""
    },
    
    "dashboard": {
        "keywords": ["dashboard", "home", "main page", "overview", "stats", "statistics", "account balance", "positions", "open trades"],
        "title": "Dashboard Overview",
        "content": """The Dashboard is your command center showing real-time trading data:

**Stats Grid (Top)**
• Execution Channels - Number of channels where bot executes trades
• Tracking Channels - Number of channels being monitored for P&L
• Open Positions - Current live positions in your account
• Position P&L - Today's profit/loss from Webull's Day P&L

**Account Balance Section**
• Use the Broker dropdown to switch between: Webull LIVE, Webull PAPER, Alpaca LIVE, Alpaca PAPER, IBKR LIVE, IBKR PAPER
• Shows: Buying Power, Net Liquidation, Unrealized P&L, Cash Balance
• Click "Hide Balance" toggle for privacy mode (blurs sensitive numbers)

**Live Trading Monitor**
Three tabs showing your trades:
• **Live Positions** - Currently open positions with real-time P&L
• **Pending Orders** - Orders waiting to be filled
• **Filled Orders** - Recently completed trades

**Quick Actions**
Links to add Execution/Tracking channels, view Leaderboard, and access Settings."""
    },
    
    "channels": {
        "keywords": ["channel", "channels", "discord channel", "add channel", "execution", "tracking", "monitor", "configure channel", "channel settings", "channel features", "how many channels", "configured channels"],
        "title": "Channel Configuration & Settings",
        "content": """Channels are Discord channels the bot monitors for trading signals. Found in **Trading → Channels** page.

**Two Types of Channels:**
1. **Execution Channels** - Bot automatically places REAL orders with your broker
2. **Tracking Channels** - Bot tracks signals for P&L without executing trades

**Adding a Channel:**
1. Enable Developer Mode in Discord (Settings → Advanced → Developer Mode)
2. Right-click the Discord channel → Copy ID
3. Go to **Trading → Channels** page in the bot dashboard
4. Click **Add Channel**, paste the Channel ID and enter a friendly name
5. Toggle **Execute** (real broker orders) and/or **Track** (P&L tracking only)
6. Assign a broker in the Execution column
7. Click Save

**Channel Features:**
- **Dual-Mode** - A channel can be both Execute AND Track simultaneously
- **Broker Override** - Assign a specific broker per channel (e.g., Webull PAPER for one, Alpaca for another)
- **Multi-Broker Execution** - Execute the same signal on multiple brokers at once
- **Allowed Users** - Filter signals by specific Discord users only (by User ID)
- **Ticker Filter** - Restrict trading to specific symbols. Modes: OFF, ALLOW LIST (only trade these), BLOCK LIST (don't trade these). Applied to BTO signals only
- **Conditional Orders** - Enable "over/under" trigger-based orders per channel. Configure auto-execute, expiry time, and trigger offset
- **NDX to QQQ Conversion** - Channels with limited NDX access can auto-convert to equivalent QQQ options with configurable delta matching
- **Signal Update Automation** - Automatically apply signal provider's SL/PT updates to existing positions
- **Trade Summary** - Enable per-channel trade summaries posted to a webhook
- **Paper Trade Mode** - Toggle paper trading per channel for testing
- **Market Selection** - US, Canada (CA), or India (IN) market
- **Max Positions** - Limit how many open positions this channel can have at once (0 = unlimited)
- **Daily Loss Limit** - Maximum dollar loss per day before the channel stops trading (0 = unlimited)
- **Circuit Breaker** - Emergency trading halt when daily loss limit is hit

**Position Sizing Options:**
- **Position Size %** - Percentage of buying power to use per trade (execution)
- **Tracking Position Size %** - Separate sizing for paper/tracking trades
- **Default Quantity** - Fixed number of contracts/shares (overrides % sizing)
- **Max Position Size $** - Dollar cap on any single position
- **Force My Size %** - Ignore signal provider's percentage and always use your channel setting

**Order Mode Options:**
- **Entry Order Mode** - Limit (default, better price) or Market (faster fill, prioritizes speed)
- **SL Order Mode** - Limit (default, retries before switching to market) or Market (immediate exit)
- **SL Limit Offset** - When using Limit SL, adds a % offset between trigger and limit price (default 3%) for better fills
- **Trim Order Mode** - Market (default) or Limit for profit target exits
- **Trim Limit Offset** - Dollar or percentage offset for limit trim orders

**Conditional Order Settings:**
- **Enable Conditional Orders** - Turn on/off "over/under" price trigger monitoring
- **Auto Execute** - Automatically execute when price condition is met
- **Order Expiry** - How long conditional orders remain active
- **Trigger Offset** - Buffer % added to trigger price to avoid false triggers
- **Limit Cap** - Maximum limit price as % above trigger (prevents chasing runaway prices)
- **Slippage Protection** - Maximum allowed slippage % before rejecting the order

**Order Chasing:**
- **Exit Order Chase** - Monitor unfilled exit orders, cancel stale ones, replace with mid-price
- **Entry Order Chase** - Chase unfilled entry orders with updated prices

**Reset Tracking** - Clears all signals/lots/closures for that channel to start fresh."""
    },
    
    "execution_mode": {
        "keywords": ["execution mode", "execute mode", "trade execution", "auto execute"],
        "title": "Channel Execution Mode",
        "content": """Each channel has two modes that can be enabled independently:

**Execution Mode** - Bot places REAL orders with your broker
- Requires a connected broker
- Supports all risk management features
- Best for: Automated trading with trusted signal providers

**Tracking Mode** - Bot monitors signals WITHOUT placing orders
- Tracks theoretical P&L based on entry/exit signals
- Uses paper trading position sizing
- Best for: Evaluating signal providers before committing real money

**Dual-Mode** - A channel can be BOTH Execute AND Track simultaneously. Useful for live trading while also maintaining a paper trail.

Configure in **Trading > Execution > Channel Management**."""
    },

    "broker_override": {
        "keywords": ["broker override", "channel broker", "per channel broker", "assign broker"],
        "title": "Per-Channel Broker Override",
        "content": """Assign a specific broker to each channel for independent trading.

**How It Works:**
- By default, channels use the global broker (usually Webull)
- Override lets you assign ANY connected broker to a specific channel
- Each channel trades independently on its assigned broker

**Use Cases:**
- Channel A → Webull LIVE (real money)
- Channel B → Webull PAPER (testing)
- Channel C → Alpaca PAPER (different strategy)
- Channel D → Schwab (different account)

**Setup:** Trading > Execution > Channel Management > Select channel > Broker Override dropdown

**Multi-Broker Execution** - Execute the SAME signal on multiple brokers simultaneously. Enable per channel."""
    },

    "conditional_orders": {
        "keywords": ["conditional orders", "conditional order", "over under", "price trigger", "trigger order", "trigger based"],
        "title": "Conditional Orders",
        "content": """Conditional orders execute when a price condition is met (e.g., "BTO SPY 450C over $2.50").

**Channel Settings:**
- **Enable Conditional Orders** - Turn on monitoring
- **Auto Execute** - Automatically execute when condition met (vs. manual confirmation)
- **Order Expiry** - How long orders remain active (e.g., 60 minutes)
- **Trigger Offset** - Buffer % added to trigger price to avoid false triggers
- **Limit Cap** - Maximum limit price as % above trigger (prevents chasing runaway prices, e.g., 5% cap means max pay is 105% of trigger)
- **Slippage Protection** - Maximum allowed slippage % before rejecting

**Monitor Upgrade:** Automatically switches from Finnhub/yfinance to broker's real-time data when brokers connect.

Configure in **Trading > Execution > Channel Management > Conditional Order Settings**."""
    },

    "ticker_filter": {
        "keywords": ["ticker filter", "symbol filter", "allow list", "block list", "restrict symbols", "filter tickers"],
        "title": "Per-Channel Ticker Filter",
        "content": """Restrict trading to specific symbols per channel.

**Modes:**
- **OFF** - Trade all symbols (default)
- **ALLOW LIST** - Only trade symbols on this list
- **BLOCK LIST** - Trade everything EXCEPT symbols on this list

**Rules:**
- Applied to BTO signals only (exits always allowed)
- Uses the underlying symbol for options (e.g., SPY for SPY 450C)
- Case-insensitive matching

**Examples:**
- ALLOW LIST: SPY, QQQ, AAPL → Only trades these 3 tickers
- BLOCK LIST: TSLA, NVDA → Trades everything except these

Configure in **Trading > Execution > Channel Management > Ticker Filter**."""
    },

    "ndx_to_qqq": {
        "keywords": ["ndx to qqq", "ndx qqq", "index conversion", "ndx conversion", "ndx"],
        "title": "NDX→QQQ Conversion",
        "content": """Automatically convert NDX (Nasdaq 100 Index) options signals to equivalent QQQ (ETF) options.

**Why?** Some channels post NDX options which require large accounts. QQQ options are much more affordable and track the same index.

**How It Works:**
1. Bot detects NDX option signal
2. Converts to equivalent QQQ strike using delta matching
3. Places QQQ order instead

**Settings:**
- **Enable** - Toggle conversion on/off per channel
- **Delta Matching** - Finds the QQQ strike with closest delta to the NDX strike

Configure in **Trading > Execution > Channel Management > NDX→QQQ**."""
    },

    "position_sizing": {
        "keywords": ["position sizing", "position size", "how many contracts", "auto quantity", "buying power percentage", "force my size"],
        "title": "Position Sizing",
        "content": """Controls how many contracts/shares to buy per trade. Configure per channel.

**Options:**
- **Position Size %** - % of buying power per trade (e.g., 5% of $100k = $5,000 per trade)
- **Tracking Size %** - Separate % for paper/tracking trades
- **Default Quantity** - Fixed number of contracts/shares (overrides % calculation)
- **Max Position Size $** - Dollar cap on any single position
- **Force My Size %** - Ignore signal provider's percentage and always use YOUR setting

**Signal Override:**
Signal providers can include position size (e.g., "12.5% OF ACCOUNT"). With Force My Size OFF, the signal's % overrides your channel setting. With Force My Size ON, your channel setting always wins.

**Calculation:** `quantity = (buying_power × position_size_pct) / option_price`
Automatically rounds to whole contracts.

Configure in **Trading > Execution > Channel Management > Position Sizing**."""
    },

    "entry_order_mode": {
        "keywords": ["entry order mode", "entry mode", "market entry", "limit entry", "entry order type"],
        "title": "Entry Order Mode",
        "content": """Choose how BTO (entry) orders are placed per channel.

**Options:**
- **Limit** (default) - Places limit order at signal price. Better price control, may not fill if price moves
- **Market** - Places market order for fastest fill. Prioritizes speed over price, may have slippage

**When to Use Market:**
- Fast-moving signals where speed matters
- 0DTE/scalping strategies
- Signal providers with tight windows

**When to Use Limit:**
- Swing trades where a few cents matter
- Conservative approach
- Higher-priced options

Configure in **Trading > Execution > Channel Management > Entry Order Mode**."""
    },

    "order_chasing": {
        "keywords": ["order chasing", "order chase", "unfilled orders", "chase order", "entry chase", "exit chase"],
        "title": "Order Chasing",
        "content": """Monitors unfilled orders and replaces them with updated prices.

**Exit Order Chase:**
- Watches pending exit (STC) orders
- If unfilled after timeout, cancels and replaces with mid-price limit order
- Ensures exits happen even when prices move

**Entry Order Chase:**
- Watches pending entry (BTO) orders  
- If unfilled, updates price to current mid-price
- Helps get into positions when market moves

**Settings:**
- **Enable** - Toggle chase on/off per channel
- **Timeout** - How long to wait before chasing (seconds)
- **Max Retries** - Maximum number of chase attempts

**Startup Restoration:** Pending orders from before restart are automatically restored for chasing.

Configure in **Trading > Execution > Channel Management > Order Chasing**."""
    },

    "signal_update_automation": {
        "keywords": ["signal update", "signal automation", "SL update", "follow-up update", "signal provider update"],
        "title": "Signal Update Automation",
        "content": """Automatically apply signal provider's follow-up updates to existing positions.

**What It Does:**
When a signal provider sends an update (e.g., "SL to $5.00", "moving my SL to 4.50"), the bot:
1. Detects the update message
2. Finds the matching open position
3. Updates the stop loss/profit target automatically

**Supported Update Formats:**
- "SL to $X" / "stop loss $X"
- "moving my SL to X"
- "new SL X" / "adjusted SL to X"
- "PT to $X" / "take profit $X"

**Behavior:**
- Updates override channel default AND dynamic SL settings
- Displayed in the risk monitor
- Works for both pending and filled positions

Configure in **Trading > Execution > Channel Management > Signal Update Automation**."""
    },

    "execution_vs_tracking": {
        "keywords": ["execution vs tracking", "difference", "execute vs track", "what is execution", "what is tracking"],
        "title": "Execution vs Tracking Mode",
        "content": """Understanding the two channel modes:

**Execution Mode (⚡)**
• Bot automatically places REAL orders with your broker
• Uses your connected broker account (Webull, Alpaca, IBKR)
• Requires broker credentials to be configured
• Supports risk management (stop loss, profit targets)
• Best for: Automated trading with trusted signal providers

**Tracking Mode (📡)**
• Bot monitors signals WITHOUT placing orders
• Tracks theoretical P&L based on entry/exit signals
• Great for testing signal quality before live trading
• Uses paper trading position sizing if configured
• Best for: Evaluating signal providers before committing real money

**Dual-Mode (⚡📡)**
You can enable BOTH on the same channel:
• Executes trades AND tracks performance
• Useful for auditing your actual vs theoretical performance
• FIFO matching for accurate P&L calculation"""
    },
    
    "brokers": {
        "keywords": ["broker", "brokers", "webull", "alpaca", "ibkr", "interactive brokers", "connect broker", "broker setup"],
        "title": "Broker Configuration",
        "content": """BotifyTrades supports multiple brokers:

**Alpaca (Paper & Live)**
• Commission-free stock trading
• Separate Paper (testing) and Live accounts
• Requires: API Key + Secret Key
• Get keys from: app.alpaca.markets
• Paper trading is recommended for testing!

**Webull**
• Popular for options trading
• Requires: Email, Password, Trade PIN
• Device ID (DID) - auto-generated on first login
• Access/Refresh tokens saved after login
• Toggle Paper Trading mode for testing

**Interactive Brokers (IBKR)**
• Professional-grade trading platform
• Requires TWS or IB Gateway running locally
• Configure: Host, Paper Port (7497), Live Port (7496), Client ID
• Toggle Paper mode for simulation

**Broker Status**
The Settings page shows connection status for each broker with colored badges:
• 🟢 Green = Connected
• 🟡 Yellow = Connecting
• ⚫ Gray = Disconnected

**Reload Credentials** - Click to refresh all broker connections without restarting."""
    },
    
    "options_trading": {
        "keywords": ["options", "option", "call", "put", "strike", "expiration", "option chain", "spx", "spy", "0dte", "greeks", "delta", "theta"],
        "title": "Options Trading Page",
        "content": """The Options page allows you to view and trade options with a professional single-row layout:

**Strike-Targeted Lookup**
Instead of loading entire option chains (which can freeze for SPX), enter:
• Symbol (e.g., SPY, SPX, AAPL)
• Expiration date (use the dropdown)
• Strike price (the specific strike you want)
• Call/Put toggle (C or P buttons)

**4-Row Layout**
View up to 4 different options simultaneously. Each row includes:
• Row number for easy identification
• Symbol, Strike, and Expiration inputs
• Call/Put toggle buttons
• Load button to fetch quote
• Live Bid/Ask/Mid prices
• Greeks display (IV, Delta, Volume)
• Limit price with +/- steppers
• Quantity with +/- steppers
• Total cost calculation
• BUY/SELL limit order buttons
• Clear row button

**Broker Selection**
Use the "Execute On" dropdown to choose: Webull, Alpaca Paper, Alpaca Live, or Interactive Brokers.

**Data Sources**
• Index options (SPX, NDX): Alpaca for expirations (supports 0DTE), Webull for prices
• Other symbols (SPY, AAPL): Webull for both expirations and prices
• Data source shown as "Webull" (green) or "Alpaca" (orange)

**30-Second Cache**
Option chain data is cached to prevent API rate limiting.

**SPX 0DTE Trading**
BotifyTrades supports SPX daily expirations (SPXW) - you can trade same-day expiring options!"""
    },
    
    "pnl_tracker": {
        "keywords": ["pnl", "p&l", "profit loss", "profit and loss", "tracker", "performance", "returns", "closed trades"],
        "title": "P&L Tracker",
        "content": """The P&L page shows comprehensive profit/loss tracking:

**Filtering Options:**
• **Date Range** - Today, Last 7 Days, Last 30 Days, This Year, All Time, Custom
• **Channel** - Filter by specific Discord channel
• **User** - Filter by signal author
• **Status** - OPEN, PARTIAL, CLOSED

**Summary Stats:**
• Total Positions
• Total P/L ($)
• Avg Return (%)
• Period being displayed

**Position Cards:**
Each position shows:
• Symbol and type (stock/option)
• Entry details (price, quantity, date)
• Current P&L ($ and %)
• Status: OPEN (blue), PARTIAL (orange), CLOSED (green)

**Expandable Closures**
Click any position to see individual STC (Sell-to-Close) transactions:
• Each closure shows quantity, price, P&L
• FIFO matching for accurate cost basis

**Reset All Data** - Clears entire P&L history (use with caution!)"""
    },
    
    "risk_management": {
        "keywords": ["risk", "risk management", "tiered", "protect", "best settings", "recommended", "combinations", "best risk settings"],
        "title": "Risk Management - Complete Guide",
        "content": """BotifyTrades has industry-grade risk management. Settings are in Trading > Execution > Channel Management > Per-Channel Risk.

**Global vs Per-Channel:**
- Global settings (Settings page) apply to ALL channels by default
- Per-channel settings OVERRIDE global when "Enable Risk Management" is toggled ON for that channel
- Toggle "Use Global Risk Settings" to inherit global defaults instead of custom

**=== 4-TIER PROFIT TARGETS ===**
Automatically sell portions of your position as profit grows:
- **PT1** - First target (e.g., sell 25% at +20% profit)
- **PT2** - Second target (e.g., sell 25% at +40% profit)
- **PT3** - Third target (e.g., sell 25% at +60% profit)
- **PT4** - Fourth target (e.g., sell remaining at +100% profit)
- Each tier has its own % trigger and quantity % to sell
- Tiers trigger sequentially (PT1 must hit before PT2 activates)

**=== STOP LOSS ===**
Automatically exit if position drops by X% from entry price.
- **SL %** - The percentage drop that triggers the exit
- **SL Order Type** - Choose Market (instant exit) or Limit (better price, retries before switching to market)
- **SL Limit Offset** - When using Limit SL, adds buffer between trigger and limit price (default 3%) for better fills
- **Follow-up SL Updates** - Signal providers can update SL via messages like "SL to $X" which overrides channel defaults
- **Dynamic SL Escalation** - After each profit target hit, the stop loss automatically moves up. Profiles: Standard, Aggressive, Conservative

**=== TRAILING STOP ===**
Locks in profit by trailing behind the peak price:
- **Activation %** - Position must gain this much before trailing begins (e.g., 15%)
- **Trail %** - How far price can drop from peak before selling (e.g., 5%)
- Example: Activate at +15%, trail by 5%. If price hits +25% then drops to +20%, it sells

**=== EARLY TRAILING STOP ===**
A breakeven-first approach for extra protection:
- **Activation %** - After this gain, stop moves to breakeven (entry price)
- **Step %** - Then locks in profit in steps as price climbs
- Example: 5% activation, 3% step. At +5% gain, SL moves to entry. At +8%, SL moves to +5%. Always protects downside first

**=== GIVEBACK GUARD ===**
Prevents giving back too much unrealized profit:
- **Giveback Allowed %** - Maximum % of peak profit you're willing to lose
- Triggers when profit drops below (peak_profit - giveback_allowed %)
- Great for volatile trades that spike then reverse

**=== LEAVE RUNNER ===**
Keep a small portion of winning trades running for extra upside:
- **Enable** - Toggle on/off
- **Runner %** - What percentage to leave (e.g., 25%)
- After all profit targets hit, the runner stays open with a trailing stop
- Lets you capture unexpected big moves

**=== POSITION SIZING ===**
- **Position Size %** - % of buying power per trade (execution)
- **Tracking Size %** - Separate sizing for paper/tracking
- **Default Quantity** - Fixed contracts/shares (overrides %)
- **Max Position Size $** - Dollar cap on any position
- **Force My Size** - Ignore signal provider's % and use your setting

**=== ORDER MODES ===**
- **Entry Order Mode** - Limit (default) or Market (faster fills)
- **SL Order Mode** - Limit (retries, then switches to market) or Market (immediate)
- **Trim Order Mode** - Market (default) or Limit for profit target exits

**=== ADVANCED FEATURES ===**
- **Limit Cap** - Prevents chasing runaway prices. Sets max limit price as % above trigger (e.g., 5% cap)
- **Slippage Protection** - Rejects orders if price moved too far from signal price
- **Circuit Breaker** - Emergency halt after daily loss limit is hit
- **Max Positions** - Limit concurrent open positions per channel
- **Daily Loss Limit** - Stop trading after losing $X in a day
- **Order Chase** - Auto-replace unfilled exit orders with updated mid-prices
- **Entry Chase** - Auto-replace unfilled entry orders with better prices
- **Settled Cash Validation** - Blocks BTO when settled cash is insufficient (prevents good faith violations)

**=== EXIT STRATEGY MODES ===**
- **Risk** - Only use risk management rules (PT/SL/trailing) to exit
- **Signal** - Only exit when signal provider sends STC
- **Hybrid** - Use BOTH risk rules AND signal provider exits (whichever triggers first)

**=== RECOMMENDED COMBINATIONS ===**

**Conservative (Low Risk):**
- SL: 10-15%
- PT1: 25% at +15%, PT2: 25% at +30%, PT3: 50% at +50%
- Trailing: Activate 10%, Trail 5%
- Early Trailing: ON, 5% activation, 3% step
- Position Size: 3-5% of account
- Entry Mode: Limit
- SL Mode: Market (guaranteed exit)
- Exit Strategy: Hybrid

**Moderate (Balanced):**
- SL: 20-25%
- PT1: 33% at +20%, PT2: 33% at +40%, PT3: 34% at +60%
- Trailing: Activate 15%, Trail 5%
- Leave Runner: ON, 25%
- Giveback Guard: 15%
- Position Size: 5-10%
- Entry Mode: Market (for fast-moving signals)
- SL Mode: Limit with 3% offset
- Exit Strategy: Hybrid

**Aggressive (High Risk/Reward):**
- SL: 30-40%
- PT1: 25% at +30%, PT2: 25% at +60%, PT3: 25% at +100%, PT4: 25% at +150%
- Trailing: Activate 20%, Trail 8%
- Leave Runner: ON, 30%
- Dynamic SL: ON, Aggressive profile
- Position Size: 10-15%
- Entry Mode: Market
- Exit Strategy: Risk

**Scalping/0DTE:**
- SL: 25-30%
- PT1: 50% at +15%, PT2: 50% at +30%
- No Trailing (too fast)
- Early Trailing: ON, 10% activation, 5% step
- Position Size: 3-5%
- Entry Mode: Market
- SL Mode: Market
- Exit Strategy: Hybrid"""
    },

    "profit_targets": {
        "keywords": ["profit targets", "profit target", "PT1", "PT2", "PT3", "PT4", "tiered targets", "take profit", "trim targets"],
        "title": "Profit Targets (4-Tier System)",
        "content": """BotifyTrades supports up to 4 tiered profit targets. Configure them in **Trading > Execution > Channel Management > Per-Channel Risk**.

**How It Works:**
Each tier has a **trigger %** (when to sell) and a **quantity %** (how much to sell):
- **PT1** - First target (e.g., sell 25% at +20% profit)
- **PT2** - Second target (e.g., sell 25% at +40% profit)
- **PT3** - Third target (e.g., sell 25% at +60% profit)
- **PT4** - Fourth target (e.g., sell remaining at +100% profit)

**Key Rules:**
- Tiers trigger sequentially - PT1 must hit before PT2 activates
- Each tier's quantity is % of the ORIGINAL position
- Total across all tiers should equal 100% (unless using Leave Runner)
- Set trigger to 0% to disable a tier

**Trim Order Mode:**
- **Market** (default) - Instant fill, may have slippage
- **Limit** - Better price control, but may not fill

**With Leave Runner:**
If Leave Runner is enabled, reduce total PT quantities to leave room (e.g., PT1: 25%, PT2: 25%, PT3: 25%, Runner: 25%)

**Example Setups:**
- **Conservative**: PT1: 50% at +15%, PT2: 50% at +30%
- **Balanced**: PT1: 33% at +20%, PT2: 33% at +40%, PT3: 34% at +60%
- **Aggressive**: PT1: 25% at +30%, PT2: 25% at +60%, PT3: 25% at +100%, PT4: 25% at +150%
- **Scalping/0DTE**: PT1: 50% at +15%, PT2: 50% at +30%"""
    },

    "stop_loss_settings": {
        "keywords": ["stop loss settings", "stop loss", "SL settings", "stop loss order type", "SL order type", "SL limit offset", "stop loss percentage"],
        "title": "Stop Loss Settings",
        "content": """Stop Loss automatically exits a position when it drops by X% from entry price. Configure in **Per-Channel Risk**.

**Settings:**
- **SL %** - The percentage drop from entry that triggers exit (e.g., 20% means exit if price drops 20%)
- **SL Order Type** - Choose how the exit order is placed:
  - **Limit** (default) - Places a limit order. Retries multiple times, then switches to market if unfilled
  - **Market** - Immediate market order for guaranteed exit (may have slippage)
- **SL Limit Offset** - When using Limit SL, adds a buffer between trigger price and limit price (default 3%) to improve fill probability

**Follow-up SL Updates:**
Signal providers can update your stop loss via messages like:
- "SL to $5.00" / "moving my SL to 4.50" / "stop loss $3"
- These override channel default and dynamic SL settings
- Displayed in the risk monitor

**Dynamic SL Escalation:**
After each profit target hit, the SL automatically moves up:
- **Standard** - Moderate escalation
- **Aggressive** - Fast escalation after each PT
- **Conservative** - Slow, gradual escalation

**Recommendations:**
- Use **Market** SL for 0DTE/scalping (speed matters most)
- Use **Limit** SL with 3-5% offset for swing trades (better fills)
- Set SL between 15-30% for most options strategies"""
    },

    "trailing_stop": {
        "keywords": ["trailing stop", "trail stop", "trailing percentage", "trail activation", "trailing stops"],
        "title": "Trailing Stop",
        "content": """Trailing Stop locks in profit by trailing behind the peak price. Configure in **Per-Channel Risk**.

**How It Works:**
1. Position must gain the **Activation %** before trailing begins
2. Once activated, it tracks the highest price reached
3. If price drops **Trail %** from the peak, it sells

**Settings:**
- **Activation %** - Minimum gain before trailing starts (e.g., 15%)
- **Trail %** - How far price can drop from peak before selling (e.g., 5%)

**Example:**
- Activation: 15%, Trail: 5%
- Position enters at $1.00, price rises to $1.25 (+25%) - trailing is active
- Peak reaches $1.30 (+30%)
- Trailing stop triggers at $1.235 ($1.30 - 5%)
- Position sells, locking in ~23.5% profit

**Tips:**
- Wider Trail % for volatile stocks (8-10%)
- Tighter Trail % for steady movers (3-5%)
- Works great combined with profit targets - trailing protects gains between tiers"""
    },

    "early_trailing_stop": {
        "keywords": ["early trailing", "early trailing stop", "breakeven stop", "breakeven first"],
        "title": "Early Trailing Stop",
        "content": """Early Trailing Stop is a breakeven-first approach that provides extra downside protection. Configure in **Per-Channel Risk**.

**How It Works:**
1. After the **Activation %** gain, the stop moves to breakeven (entry price)
2. Then it locks in profit in **Step %** increments as price climbs

**Settings:**
- **Activation %** - Gain needed to move stop to entry (e.g., 5%)
- **Step %** - Incremental profit lock-in above breakeven (e.g., 3%)

**Example:**
- Activation: 5%, Step: 3%
- Entry at $1.00
- Price hits $1.05 (+5%) → SL moves to $1.00 (breakeven)
- Price hits $1.08 (+8%) → SL moves to $1.05 (locking +5%)
- Price hits $1.11 (+11%) → SL moves to $1.08 (locking +8%)
- Price drops to $1.08 → Sells, locking in +8% profit

**Best For:**
- 0DTE trades where breakeven protection is crucial
- Volatile options that spike then reverse
- Combined with regular trailing stop for layered protection"""
    },

    "giveback_guard": {
        "keywords": ["giveback guard", "giveback", "max profit giveback", "profit protection"],
        "title": "Giveback Guard",
        "content": """Giveback Guard prevents giving back too much unrealized profit. Configure in **Per-Channel Risk**.

**How It Works:**
- Tracks the peak unrealized profit during a trade
- If profit drops more than **Giveback Allowed %** from peak, it exits

**Setting:**
- **Giveback Allowed %** - Maximum % of peak profit you're willing to lose (e.g., 15%)

**Example:**
- Giveback: 15%
- Position gains +50% (peak)
- Profit drops to +35% (gave back 15% of entry price from peak)
- Giveback Guard triggers and sells

**Best For:**
- Trades that spike quickly then reverse
- Protecting large unrealized gains
- Combining with trailing stops for extra safety"""
    },

    "leave_runner": {
        "keywords": ["leave runner", "runner", "runner position", "keep runner"],
        "title": "Leave Runner",
        "content": """Leave Runner keeps a small portion of winning trades running for extra upside. Configure in **Per-Channel Risk**.

**Settings:**
- **Enable** - Toggle on/off
- **Runner %** - What percentage of the position to keep (e.g., 25%)

**How It Works:**
1. All profit targets fire, selling most of the position
2. The Runner % stays open
3. A trailing stop protects the runner portion
4. Lets you capture unexpected big moves

**Example:**
- PT1: 25% at +20%, PT2: 25% at +40%, PT3: 25% at +60%
- Runner: 25% stays open after all PTs hit
- Runner protected by trailing stop

**Tips:**
- 15-25% runner is typical
- Ensure PT quantities + Runner % = 100%
- Works best on momentum trades with breakout potential"""
    },

    "dynamic_sl_escalation": {
        "keywords": ["dynamic SL", "dynamic SL escalation", "SL escalation", "escalation profile"],
        "title": "Dynamic SL Escalation",
        "content": """Dynamic SL Escalation automatically raises your stop loss after each profit target is hit. Configure in **Per-Channel Risk**.

**Profiles:**
- **Standard** - Moderate SL adjustment after each PT
- **Aggressive** - Large SL jumps after each PT (locks in more profit faster)
- **Conservative** - Small SL adjustments (gives more room to run)

**How It Works:**
1. PT1 hits → SL moves up to a % above entry
2. PT2 hits → SL moves higher
3. PT3 hits → SL moves even higher
4. Each escalation ratchets the SL up, never back down

**Example (Standard):**
- Original SL: -20% from entry
- After PT1 (+20%): SL moves to -5% (near breakeven)
- After PT2 (+40%): SL moves to +10% (profit locked)
- After PT3 (+60%): SL moves to +25% (significant profit protected)

**Best For:**
- Multi-target strategies where you want progressive protection
- Reducing risk as position becomes profitable"""
    },

    "circuit_breaker": {
        "keywords": ["circuit breaker", "emergency halt", "daily loss limit", "trading halt", "kill switch"],
        "title": "Circuit Breaker",
        "content": """Circuit Breaker provides emergency halt controls when daily losses exceed your threshold.

**Settings:**
- **Daily Loss Limit** - Stop trading after losing $X in a day
- **Max Positions** - Limit concurrent open positions per channel

**How It Works:**
1. Tracks cumulative daily P&L
2. When losses exceed the limit, ALL new entries are blocked
3. Existing positions continue to be managed (SL/PT still active)
4. Resets at market open next day

**Best For:**
- Preventing catastrophic loss days
- Discipline enforcement
- Account protection during volatile markets"""
    },

    "signals": {
        "keywords": ["signal", "signals", "bto", "stc", "buy to open", "sell to close", "signal format", "alert", "trade signal"],
        "title": "Signal Parsing",
        "content": """BotifyTrades automatically parses trading signals from Discord:

**Supported Signal Formats:**
• **BTO** - Buy to Open (entering a position)
• **STC** - Sell to Close (exiting a position)

**Stock Signals:**
`BTO AAPL @ 150.00`
`STC AAPL @ 155.00`

**Option Signals:**
`BTO SPY 450C 12/15 @ 2.50`
`STC SPY 450C 12/15 @ 3.00`

**Signal Components:**
• Direction: BTO or STC
• Symbol: Stock ticker (AAPL, SPY, etc.)
• Strike: For options, the strike price
• Call/Put: C or P
• Expiry: Expiration date (various formats supported)
• Price: Entry/exit price

**Channel User Filtering:**
Configure channels to only accept signals from specific Discord users (by User ID).

**Per-Signal Stop/Target:**
Signals can include stop loss and profit target prices that override channel defaults."""
    },
    
    "simulation": {
        "keywords": ["simulation", "simulate", "backtest", "projection", "portfolio growth", "what if", "compound", "replay"],
        "title": "Portfolio Simulation Engine",
        "content": """Project future portfolio growth based on trader performance:

**Simulation Target:**
• Select a User or Channel to simulate
• Loads their historical stats (win rate, avg win/loss %, trades per day)

**Two Simulation Modes:**

**1. Replay Actual Trades (📜)**
Uses each trade's REAL P&L percentage
Example: If trader had AAPL +25%, TSLA -8%, simulates those exact returns

**2. Simulate Averages (🎯)**
Uses statistical averages with optional overrides:
• Win Rate Override
• Avg Loss % Override

**Configuration:**
• Starting Portfolio ($)
• Simulation Period (1-365 days)
• Trades Per Day (auto from stats or override)
• Risk Per Trade ($ fixed or % of balance)
• Compound Returns (reinvest profits daily)

**Results Display:**
• Interactive chart showing daily balance
• Final portfolio value
• Total return %
• Summary statistics

Great for testing "what if" scenarios before following a trader!"""
    },
    
    "leaderboard": {
        "keywords": ["leaderboard", "ranking", "best traders", "top performers", "tqs", "trader quality score", "compare"],
        "title": "Channel Leaderboard",
        "content": """Compare channel/trader performance with TQS ranking:

**Trader Quality Score (TQS)**
A composite score (0-100) based on:
• 40% - Normalized P&L
• 25% - Profit Factor (gross profit / gross loss)
• 20% - Win Rate
• 15% - Avg % P&L per trade

**Leaderboard Columns:**
• Rank
• Channel/User Name
• TQS Score
• Total P&L ($)
• Win Rate (%)
• Total Trades
• Avg Return (%)

**Time Period Filters:**
• Today
• Last 7 Days
• Last 30 Days
• This Year
• All Time
• Custom Date Range

**Aggregates:**
• Total Channels tracked
• Total Trades across all channels
• Combined P&L
• Average Win Rate

Use the leaderboard to identify the best signal providers before enabling execution!"""
    },
    
    "settings_discord": {
        "keywords": ["discord token", "discord setup", "self bot", "user token", "how to get token"],
        "title": "Discord Setup",
        "content": """Setting up Discord monitoring:

**Important: This is a Self-Bot**
BotifyTrades uses YOUR Discord account to monitor channels (not a bot account).

**Getting Your Discord Token:**
1. Open Discord in a web browser (not the app)
2. Press F12 to open Developer Tools
3. Go to Network tab
4. Type /api in the filter
5. Click any request and look at Headers
6. Find "Authorization" header - that's your token

**In Settings:**
1. Paste your token in the Discord User Token field
2. Click Save to store it
3. Click Connect to start monitoring

**Status Badges:**
• Discord (Green) = Connected and monitoring
• Discord (Gray) = Disconnected

**Note:** Never share your Discord token with anyone!"""
    },
    
    "settings_api_keys": {
        "keywords": ["api key", "openai", "alpha vantage", "finnhub", "ai analysis", "market data"],
        "title": "API Keys Configuration",
        "content": """Configure external API keys for enhanced features:

**OpenAI API Key**
• Purpose: AI-powered trade analysis
• Format: sk-...
• Get from: platform.openai.com
• Used for: Post-trade analysis, market insights

**Alpha Vantage Key**
• Purpose: Option flow scanning
• Get from: alphavantage.co
• Used for: Real-time option flow data

**Finnhub API Key**
• Purpose: Market news and data
• Get from: finnhub.io
• Used for: News alerts, fundamental data

**Note:** These keys are encrypted and stored securely in the database."""
    },
    
    "notifications": {
        "keywords": ["notification", "webhook", "discord notification", "trade alert", "notify"],
        "title": "Trade Notifications",
        "content": """Set up Discord webhook notifications for trades:

**Webhook Setup:**
1. In your Discord server, go to Server Settings
2. Click Integrations → Webhooks
3. Create a new webhook
4. Copy the Webhook URL

**In BotifyTrades Settings:**
1. Enable Notifications toggle
2. Paste Webhook URL
3. (Optional) Set specific Channel ID
4. Click Save Notifications
5. Click Test Webhook to verify

**What Gets Notified:**
• Trade executions (BTO/STC)
• Position updates
• Error alerts
• P&L summaries

The webhook posts formatted messages with trade details to your chosen channel."""
    },
    
    "event_tracking": {
        "keywords": ["events", "event log", "trade events", "order events", "failures", "rejections", "broker failures", "entries", "exits", "activity", "what happened", "show events", "recent trades", "recent events", "errors", "order history"],
        "title": "Event Tracking & Order History",
        "content": """BotifyTrades tracks every order lifecycle event for full transparency. Use chatbot commands to query them.

**Event Types Tracked:**
- **ORDER_PLACED** - BTO/STC order submitted to broker
- **ORDER_FILLED** - Order confirmed filled by broker
- **ORDER_FAILED** - Order rejected by broker (insufficient funds, invalid order, etc.)
- **ORDER_REJECTED** - Order blocked by bot (slippage protection, ticker filter, settled cash, etc.)
- **STOP_LOSS** - Stop loss triggered
- **PROFIT_TARGET** - Profit target hit (PT1, PT2, PT3, PT4)
- **TRAILING_STOP** - Trailing stop triggered
- **EARLY_TRAILING** - Early trailing stop triggered
- **GIVEBACK_GUARD** - Giveback guard triggered (too much profit given back)
- **CHASER_TRACKING** - Unfilled order chaser started monitoring
- **CHASER_REPLACED** - Chaser cancelled stale order and replaced with better price
- **CHASER_FILLED** - Chaser confirmed order filled
- **CHASER_FAILED** - Chaser failed to replace order
- **RETRY_ATTEMPT** - Risk exit retry after a failed attempt
- **DUPLICATE_BLOCKED** - Duplicate order blocked by deduplication
- **SL_UPDATE** - Stop loss updated via signal provider message
- **MARKET_ORDER_ESCALATION** - Switched from limit to market order for faster fill
- **CONDITIONAL_CREATED** - Conditional "over/under" order created
- **CONDITIONAL_TRIGGERED** - Conditional order price condition met
- **CONDITIONAL_EXPIRED** - Conditional order expired without triggering

**Severity Levels:**
- **info** - Normal operations (fills, placements)
- **warning** - Attention needed (chasers, retries)
- **error** - Problems (failed orders, broker errors)
- **critical** - Urgent issues (circuit breaker, broker disconnect)

**Chatbot Commands:**
- "show events" or "recent events" - Last 20 events
- "show failures" or "show errors" - Recent failures and errors
- "show entries" - Recent BTO/entry events
- "show exits" - Recent STC/exit events
- "show broker failures" - Broker-specific errors
- "show stops" - Recent stop loss and trailing stop triggers
- "show targets" - Recent profit target hits
- "event summary" - 24-hour summary by event type
- "show events SPY" - Filter events by symbol
- "show events webull" - Filter events by broker

Events are stored for 30 days and automatically cleaned up."""
    },
    
    "authentication": {
        "keywords": ["login", "password", "forgot password", "reset password", "logout", "session", "security"],
        "title": "Authentication & Security",
        "content": """BotifyTrades security features:

**First-Time Setup:**
When you first access BotifyTrades, you'll go through a setup wizard:
• Create username (min 3 characters)
• Enter email (for password recovery)
• Set password (min 8 characters)

**Login:**
• Enter username and password
• Rate limiting protects against brute force (5 attempts per 5 minutes)
• Session persists until logout

**Forgot Password:**
1. Click "Forgot Password?" on login page
2. Enter your username
3. Check email for reset link (if SMTP configured)
4. Click link and set new password

**Logout:**
Click Logout in the navigation menu to end your session.

**Google Sign-In:**
If configured, you can also sign in with Google OAuth."""
    },
    
    "troubleshooting": {
        "keywords": ["error", "problem", "not working", "issue", "bug", "fix", "troubleshoot", "help"],
        "title": "Troubleshooting Common Issues",
        "content": """Common issues and solutions:

**Broker Not Connecting:**
• Verify credentials are correct
• Check if paper/live mode is set correctly
• For Webull: Ensure Trade PIN is 6 digits
• For IBKR: Confirm TWS/Gateway is running
• Click "Reload Credentials" to refresh

**Signals Not Executing:**
• Verify channel is in Execution mode
• Check if channel has correct broker assigned
• Ensure broker has sufficient buying power
• Verify signal format is supported

**Options Page Slow/Freezing:**
• Use strike-targeted lookup instead of full chain
• Data is cached for 30 seconds
• For SPX: System uses optimized hybrid data sourcing

**P&L Not Showing:**
• Ensure trades have been closed (STC received)
• Check date filter settings
• Try "Refresh" button
• Verify channel is in Tracking mode

**Discord Disconnected:**
• Token may have expired - get a new one
• Discord may have invalidated the session
• Re-enter token and click Connect

**Balance Shows $0:**
• Broker may not be connected
• Check Settings page for broker status
• Click refresh on dashboard

**Need More Help?**
Check the console logs for detailed error messages."""
    },
    
    "recent_updates": {
        "keywords": ["update", "new", "recent", "changelog", "what's new", "latest", "changes"],
        "title": "Recent Updates (December 2025)",
        "content": """Latest features and improvements:

**Options Trading Page Redesign**
• Strike-targeted lookup (no more freezing on SPX)
• 4-card grid for viewing multiple options
• Live bid/ask prices from Webull
• Greeks display (IV, Delta, Volume)
• Limit order execution

**Alpaca Dual Account Support**
• Separate Paper and Live trading cards
• Independent credential storage
• Fixed credential storage bug

**Webull Live Option Data**
• Switched to Webull for real-time option prices
• 30-second cache prevents API rate limiting
• Automatic fallback to Alpaca if needed

**SPX/NDX 0DTE Support**
• Daily expirations now load correctly
• Uses Alpaca for expiration dates (supports SPXW)
• Webull for live pricing data

**UI Updates**
• Premium glass-finish logo across all pages
• Updated favicon with BT branding
• Clean professional dark theme
• Fixed Options page layout responsiveness

**Bug Fixes**
• Fixed "UNKNOWN" broker display
• Fixed option chain parsing for nested data
• Database auto-migration for broker field"""
    },
    
    "architecture": {
        "keywords": ["architecture", "how it works", "technical", "system design", "components"],
        "title": "System Architecture",
        "content": """How BotifyTrades works under the hood:

**Core Components:**
• **Discord** - Monitors channels using discord.py-self
• **Flask Web GUI** - Control panel running on port 5000
• **SQLite Database** - Stores channels, trades, settings
• **Broker Abstraction** - Unified interface for multiple brokers

**Signal Flow:**
1. Discord message received
2. Signal parser extracts trade details
3. Pre-trade validation (slippage, risk rules)
4. Order sent to broker(s)
5. Trade recorded in database
6. Webhook notification sent (if enabled)
7. Risk management monitors position

**Multi-Broker System:**
• True dual-broker: Separate live and paper instances
• Per-channel broker selection
• Simultaneous multi-broker execution

**Data Storage:**
• Encrypted credentials in database
• Environment variable fallback
• Secure token storage

**Real-Time Updates:**
• WebSocket connections for live prices
• API caching to prevent rate limits
• Auto-refresh on dashboard"""
    },
    
    "position_sizing": {
        "keywords": ["position size", "how much", "quantity", "lot size", "how many contracts", "calculate quantity"],
        "title": "Position Sizing",
        "content": """How BotifyTrades calculates position sizes:

**Global Position Sizing (Settings):**
• Set as fixed dollar amount or % of portfolio
• Applied to all channels by default

**Per-Channel Override:**
• Each channel can have its own position size %
• Overrides global setting for that channel
• Found in channel edit/configuration

**Auto-Quantity Calculation:**
When a signal comes in:
1. Gets your allocated amount (from settings or channel override)
2. Divides by signal price
3. Rounds down to whole contracts/shares
4. Validates against minimum order size

**Example:**
• Position Size: 5% of $10,000 portfolio = $500
• Signal: BTO SPY 450C @ $2.50
• Calculation: $500 / $2.50 = 200 contracts

**Paper Trading Sizing:**
Tracking channels can have separate position sizing (tracking_position_size_pct) for paper trading simulations."""
    },
    
    "fifo_matching": {
        "keywords": ["fifo", "matching", "cost basis", "lot", "first in first out", "partial close"],
        "title": "FIFO P&L Matching",
        "content": """BotifyTrades uses FIFO (First In, First Out) for P&L calculation:

**How FIFO Works:**
When you sell, the system matches against your oldest purchases first.

**Example:**
1. BTO 10 contracts @ $1.00 (Lot 1)
2. BTO 5 contracts @ $1.50 (Lot 2)
3. STC 8 contracts @ $2.00

FIFO matches:
• 8 contracts from Lot 1 ($1.00 cost)
• P&L = (8 × $2.00) - (8 × $1.00) = $8.00 profit

**Partial Closes:**
• A position can be partially closed
• Remaining lots continue to track
• Status shows as "PARTIAL" until fully closed

**Signal Lots Table:**
The database tracks each lot with:
• Entry price and quantity
• Remaining quantity
• Associated channel/signal

This ensures accurate P&L regardless of multiple entries."""
    },
    
    "signal_formats": {
        "keywords": ["signal format", "format learning", "teach format", "custom signal", "learn signal", "ai format", "parse signal"],
        "title": "Signal Format Learning",
        "content": """BotifyTrades can learn new signal formats - no AI required! AI is optional for enhanced detection.

**How It Works:**
1. You show me an example signal via the chatbot
2. I analyze it using built-in rules (or AI if enabled) to understand the structure
3. I save the pattern for instant future parsing!

**Teaching a New Format:**
Say something like:
- "Teach this format: BTO AAPL 150C 12/20 @ 2.50"
- "Learn this signal: TRADE IDEA - SPY Entry: 450"
- "Recognize: BUY $TSLA at $250, TP: $260, SL: $240"

**Managing Formats:**
- "Show my formats" - List all learned formats
- "Delete format #X" - Remove a format
- "Disable format #X" - Temporarily turn off
- "Enable format #X" - Re-enable a format

**Benefits:**
- One-time AI cost per format (not per message)
- Instant parsing using stored templates
- Add formats without code changes
- AI fallback for edge cases

**Requirements:**
OpenAI API key configured in Settings > AI & Market Data APIs"""
    }
}

GREETINGS = [
    ("hi", "Hey! I'm here to help you with BotifyTrades. What would you like to know?"),
    ("hello", "Hello! How can I help you with BotifyTrades today?"),
    ("hey", "Hey there! What can I help you with?"),
    ("help", None),
    ("thanks", "You're welcome! Let me know if you have any other questions."),
    ("thank you", "Happy to help! Feel free to ask anything else about BotifyTrades."),
]

FALLBACK_RESPONSES = [
    "I'm not sure about that specific question. Try asking about:\n• Dashboard features\n• Channel configuration\n• Broker setup (Webull, Alpaca, IBKR)\n• Options trading\n• P&L tracking\n• Risk management\n• Recent updates",
    "I don't have specific information on that. Here are some topics I can help with:\n• Getting started\n• Settings and configuration\n• Trading signals\n• Leaderboard\n• Troubleshooting",
    "That's outside my knowledge area. I'm best at answering questions about BotifyTrades features like channels, brokers, trading, and settings.",
]


def similarity_score(s1: str, s2: str) -> float:
    """Calculate similarity between two strings"""
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def find_best_match(query: str) -> Tuple[Optional[str], float]:
    """Find the best matching topic from knowledge base"""
    query_lower = query.lower()
    best_topic = None
    best_score = 0.0
    
    for topic_id, topic_data in KNOWLEDGE_BASE.items():
        keywords = topic_data.get("keywords", [])
        
        for keyword in keywords:
            if keyword in query_lower:
                score = len(keyword) / len(query_lower) + 0.5
                if score > best_score:
                    best_score = score
                    best_topic = topic_id
            else:
                sim = similarity_score(keyword, query_lower)
                if sim > 0.6 and sim > best_score:
                    best_score = sim
                    best_topic = topic_id
    
    word_set = set(query_lower.split())
    for topic_id, topic_data in KNOWLEDGE_BASE.items():
        keywords = topic_data.get("keywords", [])
        keyword_matches = sum(1 for kw in keywords if any(kw in word or word in kw for word in word_set))
        if keyword_matches >= 2:
            score = keyword_matches * 0.3
            if score > best_score:
                best_score = score
                best_topic = topic_id
    
    return best_topic, best_score


def check_greeting(query: str) -> Optional[str]:
    """Check if query is a greeting and return appropriate response"""
    query_lower = query.lower().strip()
    
    for trigger, response in GREETINGS:
        if query_lower == trigger or query_lower.startswith(trigger + " ") or query_lower.startswith(trigger + "!"):
            return response
    
    return None


def _get_help_response() -> Dict:
    """Return comprehensive help message showing all available commands and topics."""
    help_text = """**BotifyTrades Assistant - Help Guide**

I can answer questions, run commands, and help you understand every feature. Here's everything I can do:

---

**Ask Me About (Topics):**
- "getting started" - Setup guide and first steps
- "dashboard" - Dashboard features and navigation
- "channels" / "channel settings" - How channels work, all settings explained
- "brokers" / "broker setup" - Connecting Webull, Alpaca, Schwab, Robinhood, IBKR, etc.
- "options trading" - How options signals are parsed and executed
- "risk management" - Stop losses, profit targets, trailing stops, and more
- "P&L" / "profit loss" - P&L tracking and performance analytics
- "signals" / "signal parsing" - How trading signals are detected and processed
- "conditional orders" - Price-triggered order system
- "position sizing" - Auto-quantity, account %, and signal override
- "ticker filter" - Allow/block list per channel
- "NDX to QQQ" - Index-to-ETF conversion
- "order chasing" - Unfilled order monitoring
- "notifications" - Discord webhooks and desktop alerts
- "leaderboard" - Channel performance rankings
- "troubleshooting" - Common issues and fixes

---

**Event Tracking Commands:**
- "show events" - Last 20 trading events
- "show failures" / "show errors" - Failed or rejected orders
- "show entries" - Recent BTO/entry orders
- "show exits" - Recent STC/exit orders
- "show stops" - Stop loss and trailing stop triggers
- "show targets" - Profit target hits
- "show fills" - Filled orders
- "show broker failures" - Broker-level errors
- "show chasers" - Order chaser activity
- "show conditionals" - Conditional order events
- "show duplicates" - Blocked duplicate signals
- "show sl updates" - Stop loss update events
- "show giveback" - Giveback guard triggers
- "event summary" - 24-hour overview of all activity
- "show events SPY" - Filter events by symbol
- "show events webull" - Filter events by broker

---

**Symbol Investigation (ask in plain English):**
- "what happened with SPY" - Full investigation: events, failures, logs, trades
- "why did AAPL fail" - Focus on failures and errors for a symbol
- "SPY history" / "SPY status" - Quick symbol lookup
- "investigate TSLA" / "debug QQQ" - Deep dive into a symbol
- "check SPY trades" - Show trade history for a symbol

---

**Signal Format Commands:**
- "teach this format: [paste signal]" - Teach a new signal format
- "show formats" / "list formats" - View all learned formats
- "delete format #1" - Remove a learned format
- "disable format #1" / "enable format #1" - Toggle formats

---

**Tips:**
- Ask anything in plain English - I understand natural questions
- Combine topics: "how do trailing stops work with profit targets?"
- Ask for recommendations: "best risk settings for scalping"
- Type any question - if I don't know, I'll try AI to help

What would you like to know?"""

    return {
        "success": True,
        "response": help_text,
        "topic": "help"
    }


HELP_TRIGGERS = [
    "help", "help me", "commands", "list commands", "show commands",
    "what can you do", "what do you do", "what are your commands",
    "available commands", "command list", "all commands",
    "how to use", "how do i use this", "how does this work",
    "what can i ask", "what can i ask you", "what should i ask",
    "menu", "options", "guide", "help guide", "user guide",
    "what can the chatbot do", "chatbot help", "assistant help",
    "show help", "bot help", "bot commands",
]


def get_response(query: str) -> Dict:
    """Get AI assistant response for a query.
    
    Priority order:
    1. Empty query - welcome message
    2. Greetings
    3. Format teaching commands (e.g., "teach this format: ...")
    4. Format management commands (e.g., "show formats", "delete format X")
    5. Knowledge base matches
    6. AI-powered response (if OpenAI available)
    7. Fallback responses
    """
    if not query or not query.strip():
        ai_status = " I can use AI to answer questions beyond my knowledge base." if is_ai_available() else ""
        return {
            "success": True,
            "response": f"Hi! I'm your BotifyTrades assistant. Ask me anything about the app - channels, brokers, trading, settings, and more!{ai_status}",
            "topic": None,
            "ai_available": is_ai_available()
        }
    
    query_lower = query.lower().strip()
    if query_lower in HELP_TRIGGERS or query_lower.rstrip('?') in HELP_TRIGGERS:
        return _get_help_response()
    
    greeting_response = check_greeting(query)
    if greeting_response:
        return {
            "success": True,
            "response": greeting_response,
            "topic": "greeting"
        }
    
    # Format teaching commands — explicit commands, always handle directly
    format_response = handle_format_commands(query)
    if format_response:
        return format_response

    # Event commands (show events, show failures, etc.) — always use dedicated handlers
    event_response = handle_event_commands(query)
    if event_response:
        return event_response

    q_lower_pre = query.lower().strip()
    _wants_channel_list = ('channel' in q_lower_pre and any(kw in q_lower_pre for kw in ['list', 'show', 'configured', 'how many', 'what are', 'which']))
    if _wants_channel_list:
        if not any(kw in q_lower_pre for kw in ['how do i', 'how to', 'what is a', 'explain', 'add channel']):
            return _list_channels_from_db()

    ai_available = is_ai_available()

    if ai_available:
        context_parts = []
        sym = _extract_symbol(query)
        q_lower = query.lower()

        is_trade_question = sym and any(kw in q_lower for kw in [
            'trade', 'what happened', 'position', 'pnl', 'p&l', 'profit', 'loss',
            'buy', 'sell', 'entry', 'exit', 'fill', 'order', 'execute', 'status',
            'close', 'open', 'held', 'stop', 'target', 'sl', 'why', 'fail',
        ])
        is_config_question = any(kw in q_lower for kw in [
            'channel', 'setting', 'config', 'broker', 'risk', 'sizing', 'setup',
            'how many', 'which', 'enable', 'disable', 'connect',
        ])
        is_issue_question = any(kw in q_lower for kw in [
            'log', 'error', 'fail', 'issue', 'problem', 'not working', 'crash', 'bug',
        ])

        if is_trade_question:
            result = analyze_trades(query)
            if result.get('ai_powered') or result.get('topic') == 'trade_summary':
                return result

        analysis_type = "general"
        if is_issue_question:
            analysis_type = "log_analysis"

        if sym:
            trade_ctx = _get_trade_context_for_symbol(sym)
            if trade_ctx:
                context_parts.append(trade_ctx)

        if is_config_question or not sym:
            bot_status = _get_bot_status_context()
            if bot_status:
                context_parts.append(f"CURRENT BOT STATUS:\n{bot_status}")

        if is_issue_question:
            try:
                log_lines = _get_log_context(count=100)
                if sym and log_lines:
                    symbol_lines = [l for l in log_lines.split('\n') if sym.upper() in l.upper()]
                    if symbol_lines:
                        context_parts.append(f"CONSOLE LOGS ({sym}):\n" + "\n".join(symbol_lines[-20:]))
                elif log_lines:
                    context_parts.append(f"RECENT CONSOLE LOGS:\n{log_lines}")
            except Exception:
                pass

        full_context = "\n\n".join(context_parts) if context_parts else ""
        ai_response = _call_ai(query, full_context, analysis_type)
        if ai_response:
            return {
                "success": True,
                "response": ai_response,
                "topic": None,
                "confidence": 0.9,
                "ai_powered": True
            }

    # AI unavailable — fall back to keyword handlers and knowledge base
    query_lower_check = query.lower().strip()

    if is_trade_query(query_lower_check):
        return analyze_trades(query)
    elif is_log_query(query_lower_check):
        return analyze_logs(query)
    elif is_error_query(query_lower_check):
        return analyze_errors(query)

    topic_id, score = find_best_match(query)
    if topic_id and score >= 0.3:
        topic = KNOWLEDGE_BASE[topic_id]
        return {
            "success": True,
            "response": f"**{topic['title']}**\n\n{topic['content']}",
            "topic": topic_id,
            "confidence": round(min(score, 1.0), 2)
        }

    import random
    return {
        "success": True,
        "response": random.choice(FALLBACK_RESPONSES),
        "topic": None,
        "confidence": 0
    }


def handle_event_commands(query: str) -> Optional[Dict]:
    """Handle event tracking and order history commands.
    
    Commands:
    - "show events" / "recent events" - Last 20 events
    - "show failures" / "show errors" - Recent failures
    - "show entries" - Recent BTO/entry events
    - "show exits" - Recent STC/exit events 
    - "show broker failures" - Broker errors
    - "show stops" - Stop loss/trailing stop triggers
    - "show targets" - Profit target hits
    - "event summary" - 24h summary
    - "show events SYMBOL" - Filter by symbol
    """
    query_lower = query.lower().strip()
    
    event_commands = {
        'show events': {'limit': 20},
        'recent events': {'limit': 20},
        'show recent events': {'limit': 20},
        'show all events': {'limit': 50},
        'show order events': {'limit': 20},
        'order history': {'limit': 20},
        'what happened': {'limit': 20},
        'show activity': {'limit': 20},
    }
    
    filter_commands = {
        'show failures': {'event_type': 'ORDER_FAILED,ORDER_REJECTED', 'label': 'Failures & Rejections'},
        'show errors': {'event_type': 'ORDER_FAILED,ORDER_REJECTED', 'label': 'Failures & Rejections'},
        'show rejections': {'event_type': 'ORDER_REJECTED', 'label': 'Order Rejections'},
        'show entries': {'event_type': 'ORDER_PLACED,ORDER_FILLED', 'direction': 'BTO', 'label': 'Entry Orders'},
        'show exits': {'event_type': 'ORDER_PLACED,ORDER_FILLED', 'direction': 'STC', 'label': 'Exit Orders'},
        'show broker failures': {'severity': 'error,critical', 'label': 'Broker Failures'},
        'show broker errors': {'severity': 'error,critical', 'label': 'Broker Errors'},
        'show stops': {'event_type': 'STOP_LOSS,TRAILING_STOP,EARLY_TRAILING', 'label': 'Stop Loss Triggers'},
        'show stop losses': {'event_type': 'STOP_LOSS,TRAILING_STOP,EARLY_TRAILING', 'label': 'Stop Loss Triggers'},
        'show targets': {'event_type': 'PROFIT_TARGET', 'label': 'Profit Target Hits'},
        'show profit targets': {'event_type': 'PROFIT_TARGET', 'label': 'Profit Target Hits'},
        'show fills': {'event_type': 'ORDER_FILLED', 'label': 'Filled Orders'},
        'show chasers': {'event_type': 'CHASER_TRACKING,CHASER_REPLACED,CHASER_FILLED,CHASER_FAILED', 'label': 'Order Chaser Activity'},
        'show conditionals': {'event_type': 'CONDITIONAL_CREATED,CONDITIONAL_TRIGGERED,CONDITIONAL_EXPIRED', 'label': 'Conditional Orders'},
        'show duplicates': {'event_type': 'DUPLICATE_BLOCKED', 'label': 'Blocked Duplicates'},
        'show sl updates': {'event_type': 'SL_UPDATE', 'label': 'Stop Loss Updates'},
        'show giveback': {'event_type': 'GIVEBACK_GUARD', 'label': 'Giveback Guard Triggers'},
    }
    
    if query_lower in ('event summary', 'show event summary', 'events summary', 'summary'):
        return _get_event_summary()
    
    for cmd, filters in filter_commands.items():
        if query_lower == cmd:
            return _query_events(filters.get('label', 'Events'), 
                               event_type=filters.get('event_type'),
                               severity=filters.get('severity'),
                               direction=filters.get('direction'))
    
    for cmd, opts in event_commands.items():
        if query_lower == cmd:
            return _query_events('Recent Events', limit=opts.get('limit', 20))
    
    import re
    sym_match = re.match(r'show events?\s+([A-Za-z]{1,5})$', query_lower)
    if sym_match:
        symbol = sym_match.group(1).upper()
        known_brokers = ['webull', 'alpaca', 'ibkr', 'schwab', 'robinhood', 'tastytrade', 'questrade', 'dhan', 'upstox', 'zerodha']
        if symbol.lower() in known_brokers:
            return _query_events(f'{symbol.title()} Events', broker=symbol.lower())
        return _query_events(f'{symbol} Events', symbol=symbol)
    
    symbol_investigation_patterns = [
        r'(?:what|tell me what)\s+happened\s+(?:with|to|for)\s+([A-Za-z]{1,5})',
        r'why\s+(?:did|was|is)\s+([A-Za-z]{1,5})\s+(?:fail|reject|error|not fill|not work|cancel)',
        r'(?:why|how)\s+(?:did|was)\s+([A-Za-z]{1,5})\s+(?:stop|exit|sell|trim|close)',
        r'(?:status|history|details|info|investigate|lookup|look up)\s+(?:of|for|on)?\s*([A-Za-z]{1,5})',
        r'([A-Za-z]{1,5})\s+(?:status|history|details|events|what happened|failures|summary)',
        r'(?:check|show|get)\s+([A-Za-z]{1,5})\s+(?:status|history|details|events|trades|orders)',
        r'(?:anything|everything)\s+(?:on|about|for|with)\s+([A-Za-z]{1,5})',
        r'(?:debug|diagnose|troubleshoot)\s+([A-Za-z]{1,5})',
    ]
    
    noise_words = {'the', 'a', 'an', 'my', 'our', 'this', 'that', 'it', 'for', 'on', 'in', 'is', 'was', 'did', 'do', 'not', 'all'}
    
    for pattern in symbol_investigation_patterns:
        match = re.search(pattern, query_lower)
        if match:
            symbol = match.group(1).upper()
            if symbol.lower() not in noise_words and len(symbol) >= 1:
                return _investigate_symbol(symbol, query)
    
    return None


def _investigate_symbol(symbol: str, original_query: str) -> Dict:
    """Build a comprehensive investigation report for a symbol using events + logs + trades."""
    try:
        from . import database as db
        
        response_parts = [f"**Investigation: {symbol}**\n"]
        
        events, total = db.get_order_events(
            symbol=symbol,
            limit=30
        )
        
        if events:
            response_parts.append(f"**Order Events** ({total} total)\n")
            
            event_counts = {}
            for e in events:
                etype = e.get('event_type', 'UNKNOWN')
                event_counts[etype] = event_counts.get(etype, 0) + 1
            
            summary_items = [f"{etype}: {count}" for etype, count in sorted(event_counts.items(), key=lambda x: -x[1])]
            response_parts.append("Summary: " + " | ".join(summary_items) + "\n")
            
            failures = [e for e in events if e.get('severity') in ('error', 'critical') or e.get('event_type') in ('ORDER_FAILED', 'ORDER_REJECTED')]
            if failures:
                response_parts.append(f"**Failures & Errors ({len(failures)}):**")
                for f_evt in failures[:5]:
                    ts = _utc_to_est(f_evt.get('timestamp', ''))
                    reason = f_evt.get('reason', 'No reason provided')
                    details = f_evt.get('details', '')
                    broker = f_evt.get('broker', '')
                    evt_type = f_evt.get('event_type', '')
                    line = f"- [{ts}] {evt_type}"
                    if broker:
                        line += f" ({broker})"
                    line += f": {reason}"
                    if details and 'Error type: ORDER_FAILED' not in details:
                        line += f"\n  Details: {details}"
                    elif details and '|' in details:
                        line += f"\n  Details: {details}"
                    response_parts.append(line)
                if len(failures) > 5:
                    response_parts.append(f"  *...and {len(failures) - 5} more failures*")
                response_parts.append("")
            
            risk_events = [e for e in events if e.get('event_type') in ('STOP_LOSS', 'PROFIT_TARGET', 'TRAILING_STOP', 'EARLY_TRAILING', 'GIVEBACK_GUARD', 'SL_UPDATE')]
            if risk_events:
                response_parts.append(f"**Risk Triggers ({len(risk_events)}):**")
                for r_evt in risk_events[:5]:
                    ts = _utc_to_est(r_evt.get('timestamp', ''))
                    evt_type = r_evt.get('event_type', '')
                    reason = r_evt.get('reason', '')
                    price = r_evt.get('price', '')
                    line = f"- [{ts}] {evt_type}"
                    if price:
                        line += f" @ ${price}"
                    if reason:
                        line += f" - {reason}"
                    response_parts.append(line)
                response_parts.append("")
            
            recent_timeline = sorted(events[:10], key=lambda e: e.get('timestamp') or '0000-00-00')
            response_parts.append("**Recent Timeline (chronological):**")
            for evt in recent_timeline:
                response_parts.append(_format_event_row(evt))
            if total > 10:
                response_parts.append(f"*...{total - 10} earlier events not shown*")
            response_parts.append("")
        else:
            response_parts.append("**Order Events:** No events found for this symbol.\n")
        
        log_lines = []
        try:
            from src.log_monitor import get_log_monitor
            monitor = get_log_monitor()
            symbol_logs = monitor.search_logs(symbol, count=20)
            if symbol_logs:
                response_parts.append(f"**Console Logs** ({len(symbol_logs)} entries with '{symbol}'):\n```")
                for log in symbol_logs[-10:]:
                    ts = log.get('timestamp', '')
                    if ts and len(ts) > 8:
                        ts = ts[-8:]
                    msg = log.get('message', '')
                    if len(msg) > 200:
                        msg = msg[:200] + '...'
                    response_parts.append(f"[{ts}] {msg}")
                response_parts.append("```")
                if len(symbol_logs) > 10:
                    response_parts.append(f"*{len(symbol_logs) - 10} earlier log entries not shown*")
                response_parts.append("")
        except Exception as log_err:
            pass
        
        try:
            trades = db.get_trades(limit=100)
            if trades:
                symbol_trades = [t for t in trades if symbol.upper() in (t.get('symbol', '') or '').upper()]
                if symbol_trades:
                    symbol_trades_sorted = sorted(
                        symbol_trades,
                        key=lambda t: t.get('executed_at') or t.get('filled_at') or t.get('created_at') or '0000-00-00'
                    )
                    display_trades = symbol_trades_sorted[-8:]
                    response_parts.append(f"**Trade History** ({len(symbol_trades)} trades, chronological):")
                    for t in display_trades:
                        action = t.get('action', t.get('side', '?'))
                        qty = t.get('quantity', t.get('qty', 0))
                        price = t.get('price', t.get('fill_price', 0))
                        status = t.get('status', '')
                        broker = t.get('broker', '')
                        raw_ts = t.get('executed_at') or t.get('filled_at') or t.get('created_at') or ''
                        ts = _utc_to_est(raw_ts)
                        line = f"- [{ts}] {action} x{qty} @ ${price}"
                        if status:
                            line += f" [{status}]"
                        if broker:
                            line += f" ({broker})"
                        response_parts.append(line)
                    if len(symbol_trades) > 8:
                        response_parts.append(f"  *...and {len(symbol_trades) - 8} more trades*")
                    response_parts.append("")
        except Exception:
            pass
        
        if len(response_parts) <= 2:
            response_parts.append("No activity found for this symbol. Events are recorded when the bot processes signals, places orders, or triggers risk rules during live trading.")
        
        response_parts.append("---")
        response_parts.append("**More commands for " + symbol + ":**")
        response_parts.append(f"- `show events {symbol}` - All events for {symbol}")
        response_parts.append(f"- `show failures` - All failed/rejected orders")
        response_parts.append(f"- `show entries` - All BTO/entry orders")
        response_parts.append(f"- `show exits` - All STC/exit orders")
        response_parts.append(f"- `show stops` - Stop loss & trailing stop triggers")
        response_parts.append(f"- `show targets` - Profit target hits")
        response_parts.append(f"- `show fills` - Filled orders")
        response_parts.append(f"- `show chasers` - Order chaser activity")
        response_parts.append(f"- `event summary` - 24-hour overview")
        response_parts.append(f"- `help` - Full list of all commands")
        
        return {
            "success": True,
            "response": "\n".join(response_parts),
            "topic": "symbol_investigation"
        }
    except Exception as e:
        print(f"[CHAT] Symbol investigation error for {symbol}: {e}")
        return {
            "success": True,
            "response": f"**Error investigating {symbol}**\n\nCould not retrieve data: {str(e)}\n\nTry `show events {symbol}` to see just the event log.",
            "topic": "symbol_investigation"
        }


def _utc_to_est(ts_str: str) -> str:
    """Convert a UTC timestamp string to EST/EDT display format (MM-DD HH:MM)."""
    if not ts_str or len(ts_str) < 16:
        return ts_str or ''
    try:
        ts_clean = ts_str.replace('T', ' ').replace('Z', '')
        if '.' in ts_clean:
            ts_clean = ts_clean.split('.')[0]
        utc_dt = datetime.strptime(ts_clean[:19], '%Y-%m-%d %H:%M:%S')
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        try:
            from zoneinfo import ZoneInfo
            est_dt = utc_dt.astimezone(ZoneInfo('America/New_York'))
        except ImportError:
            est_offset = timezone(timedelta(hours=-5))
            est_dt = utc_dt.astimezone(est_offset)
        return est_dt.strftime('%m-%d %H:%M')
    except Exception:
        if len(ts_str) > 16:
            return ts_str[5:16]
        return ts_str


def _format_event_row(event: Dict) -> str:
    """Format a single event row for display."""
    timestamp = _utc_to_est(event.get('timestamp', ''))
    
    event_type = event.get('event_type', 'UNKNOWN')
    symbol = event.get('symbol', '')
    broker = event.get('broker', '')
    severity = event.get('severity', 'info')
    reason = event.get('reason', '')
    direction = event.get('direction', '')
    qty = event.get('quantity', '')
    price = event.get('price', '')
    channel = event.get('channel_name', '')
    
    severity_icons = {'info': '[i]', 'warning': '[!]', 'error': '[X]', 'critical': '[!!]'}
    icon = severity_icons.get(severity, '[?]')
    
    line = f"{icon} **{timestamp}** | {event_type}"
    if symbol:
        line += f" | {symbol}"
    if direction:
        line += f" ({direction})"
    if qty:
        line += f" x{int(qty) if float(qty) == int(float(qty)) else qty}"
    if price:
        line += f" @ ${price}"
    if broker:
        line += f" | {broker}"
    if channel:
        line += f" | #{channel}"
    if reason:
        line += f"\n  Reason: {reason}"
    
    details = event.get('details', '')
    if details and severity in ('error', 'critical') and details != f"Error type: {event_type}":
        line += f"\n  Details: {details}"
    
    return line


def _query_events(label: str, event_type: str = None, severity: str = None, 
                  direction: str = None, symbol: str = None, broker: str = None,
                  limit: int = 20) -> Dict:
    """Query order events from database and format response."""
    try:
        from . import database as db
        
        events, total = db.get_order_events(
            limit=limit,
            event_type=event_type,
            severity=severity,
            direction=direction,
            symbol=symbol,
            broker=broker
        )
        
        if not events:
            return {
                "success": True,
                "response": f"**{label}**\n\nNo events found matching your criteria.\n\nEvents are recorded when trades are placed, filled, rejected, or risk rules trigger. Start trading to see activity here!",
                "topic": "event_tracking"
            }
        
        response = f"**{label}** (showing {len(events)} of {total} total)\n\n"
        
        for event in events:
            response += _format_event_row(event) + "\n"
        
        if total > limit:
            response += f"\n*{total - limit} more events not shown. Use more specific filters to narrow results.*"
        
        response += "\n\n**Filter commands:** show failures, show entries, show exits, show stops, show targets, show broker failures, event summary"
        
        return {
            "success": True,
            "response": response,
            "topic": "event_tracking"
        }
    except Exception as e:
        print(f"[CHAT] Error querying events: {e}")
        return {
            "success": True,
            "response": f"**Error Loading Events**\n\nCould not load events: {str(e)}\n\nThe event tracking system may not have recorded any events yet. Events are logged automatically during trading.",
            "topic": "event_tracking"
        }


def _get_event_summary() -> Dict:
    """Get 24-hour event summary."""
    try:
        from . import database as db
        
        summary = db.get_order_event_summary()
        
        if not summary:
            return {
                "success": True,
                "response": "**24-Hour Event Summary**\n\nNo events recorded in the last 24 hours.\n\nEvents are logged automatically when the bot places orders, fills them, triggers risk rules, or encounters errors.",
                "topic": "event_tracking"
            }
        
        response = "**24-Hour Event Summary**\n\n"
        
        total_events = sum(data['total'] for data in summary.values())
        total_errors = sum(data.get('error', 0) + data.get('critical', 0) for data in summary.values())
        total_warnings = sum(data.get('warning', 0) for data in summary.values())
        
        response += f"**Overview:** {total_events} total events"
        if total_errors:
            response += f" | {total_errors} errors"
        if total_warnings:
            response += f" | {total_warnings} warnings"
        response += "\n\n"
        
        categories = {
            'Orders': ['ORDER_PLACED', 'ORDER_FILLED', 'ORDER_FAILED', 'ORDER_REJECTED'],
            'Risk Triggers': ['STOP_LOSS', 'PROFIT_TARGET', 'TRAILING_STOP', 'EARLY_TRAILING', 'GIVEBACK_GUARD'],
            'Order Chasing': ['CHASER_TRACKING', 'CHASER_REPLACED', 'CHASER_FILLED', 'CHASER_FAILED'],
            'Conditionals': ['CONDITIONAL_CREATED', 'CONDITIONAL_TRIGGERED', 'CONDITIONAL_EXPIRED'],
            'Other': ['DUPLICATE_BLOCKED', 'SL_UPDATE', 'MARKET_ORDER_ESCALATION', 'RETRY_ATTEMPT']
        }
        
        for cat_name, cat_types in categories.items():
            cat_events = {k: v for k, v in summary.items() if k in cat_types}
            if cat_events:
                response += f"**{cat_name}:**\n"
                for evt_type, data in cat_events.items():
                    count = data['total']
                    extras = []
                    if data.get('error', 0):
                        extras.append(f"{data['error']} errors")
                    if data.get('warning', 0):
                        extras.append(f"{data['warning']} warnings")
                    extra_str = f" ({', '.join(extras)})" if extras else ""
                    response += f"- {evt_type}: {count}{extra_str}\n"
                response += "\n"
        
        uncategorized = {k: v for k, v in summary.items() 
                        if not any(k in types for types in categories.values())}
        if uncategorized:
            response += "**Other:**\n"
            for evt_type, data in uncategorized.items():
                response += f"- {evt_type}: {data['total']}\n"
        
        response += "\n**Commands:** show events, show failures, show entries, show exits, show stops, show targets"
        
        return {
            "success": True,
            "response": response,
            "topic": "event_tracking"
        }
    except Exception as e:
        print(f"[CHAT] Error getting event summary: {e}")
        return {
            "success": True,
            "response": f"**Error**\n\nCould not load event summary: {str(e)}",
            "topic": "event_tracking"
        }


def _handle_test_signal(signal_text: str) -> Dict:
    """Run a signal through the live registry and show exactly what gets extracted."""
    try:
        from src.services.signal_format_registry import get_signal_format_registry
        registry = get_signal_format_registry()
        result = registry.parse(signal_text.strip())

        if not result:
            return {
                "success": True,
                "response": (
                    f"**No Match** ❌\n\n"
                    f"Signal: `{signal_text[:120]}`\n\n"
                    f"No active format recognized this signal.\n\n"
                    f"**Options:**\n"
                    f"- `teach this format: {signal_text[:60]}` — teach it manually\n"
                    f"- `show formats` — see what formats are active\n"
                    f"- Run `analyze channel <id>` to auto-discover formats"
                ),
                "topic": "format_testing"
            }

        fmt_name = result.get('_format_name', 'unknown')
        action   = result.get('action', '?')
        symbol   = result.get('symbol', '?')
        asset    = result.get('asset', '?')
        strike   = result.get('strike')
        opt_type = result.get('opt_type')
        expiry   = result.get('expiry')
        price    = result.get('price')
        qty      = result.get('qty', 1)
        qty_spec = result.get('qty_specified', False)
        mkt      = result.get('is_market_order', False)
        conf     = result.get('confidence', 0)
        learned  = result.get('_learned_pattern', False)
        approved = result.get('_admin_approved', False)
        exec_ok  = result.get('_execution_allowed', False)

        status_icon = '✅' if exec_ok else '⚠️'
        conf_pct    = f"{int(conf * 100)}%" if conf else '?'

        lines = [
            f"**Signal Test Result** {status_icon}\n",
            f"Signal: `{signal_text[:120]}`\n",
            f"**Matched Format:** `{fmt_name}`  ({conf_pct} confidence)",
            f"**Type:** {'Learned' if learned else 'Built-in'} | {'Admin-approved ✓' if approved else 'Pending approval'}",
            "",
            "**Extracted Fields:**",
            f"  Action:   `{action}`",
            f"  Symbol:   `{symbol}`",
            f"  Asset:    `{asset}`",
        ]
        if asset == 'option':
            lines.append(f"  Strike:   `{strike if strike is not None else '❌ missing'}`")
            lines.append(f"  Opt Type: `{opt_type if opt_type else '❌ missing'}`")
            lines.append(f"  Expiry:   `{expiry if expiry else '❌ missing'}`")
        lines.append(f"  Price:    `{'market order' if mkt else (price if price is not None else '❌ missing')}`")
        lines.append(f"  Qty:      `{qty}` {'(specified)' if qty_spec else '(default)'}")

        missing = []
        if asset == 'option':
            if strike is None: missing.append('strike')
            if not opt_type:   missing.append('opt_type')
            if not expiry:     missing.append('expiry')
        if price is None and not mkt:
            missing.append('price')

        lines.append("")
        if missing:
            lines.append(f"**⚠️ Missing fields:** {', '.join(missing)}")
            lines.append("These will be blank when the trade executes — use `teach this format:` to fix.")
        else:
            lines.append("**All required fields extracted ✓** — this format is ready for live trading.")

        if not exec_ok:
            lines.append("\n⚠️ Execution is **not allowed** — format needs admin approval first.")

        return {
            "success": True,
            "response": "\n".join(lines),
            "topic": "format_testing"
        }

    except Exception as e:
        return {"success": True, "response": f"**Error testing signal:** {e}", "topic": "format_testing"}


def handle_format_commands(query: str) -> Optional[Dict]:
    """Handle format teaching and management commands.

    Commands:
    - "test signal: <signal>" - Test a signal against all active formats
    - "teach this format: <signal>" - Learn a new signal format
    - "show formats" / "list formats" - Show all learned formats
    - "delete format <name>" - Delete a learned format
    - "enable format <name>" / "disable format <name>" - Toggle format
    - "scan channel <channel_id>" - Scan messages and auto-learn formats
    - "scan channels" - List channels available for scanning
    """
    query_lower = query.lower().strip()

    # Test signal against live registry
    if query_lower.startswith('test signal:') or query_lower.startswith('test format:'):
        signal_part = query.split(':', 1)[1].strip() if ':' in query else ''
        if not signal_part:
            return {
                "success": True,
                "response": (
                    "**Test a Signal**\n\n"
                    "Paste any signal to see exactly what the bot would extract:\n\n"
                    "`test signal: 7/3 RIVN 13.5C .32`\n"
                    "`test signal: BTO AAPL 200C 12/20 @ 1.50`\n"
                    "`test signal: All out SOFI 135% gains`"
                ),
                "topic": "format_testing"
            }
        return _handle_test_signal(signal_part)

    # Redirect Discord bot commands to chatbot equivalents
    if query_lower.startswith('!extractraw ') or query_lower.startswith('!extract '):
        channel_id = query.split()[-1].strip()
        if channel_id.isdigit():
            return _handle_analyze_channel(channel_id)

    # Analyze channel formats (new pipeline)
    if query_lower.startswith('analyze channel ') or query_lower.startswith('analyze formats ') or query_lower.startswith('analyze '):
        channel_id = query.split()[-1].strip()
        if channel_id.isdigit():
            return _handle_analyze_channel(channel_id)

    # Show format candidates
    if query_lower.startswith('show candidates') or query_lower.startswith('format candidates'):
        parts = query.split()
        channel_id = parts[-1] if len(parts) > 2 and parts[-1].isdigit() else None
        return _handle_show_candidates(channel_id)

    # Approve format candidate
    if query_lower.startswith('approve format #') or query_lower.startswith('approve format ') and query_lower.replace('approve format ', '').strip()[:1].isdigit():
        cid = query_lower.replace('approve format #', '').replace('approve format ', '').strip()
        return _handle_approve_candidate(cid)

    if query_lower == 'approve all formats':
        return _handle_approve_all_candidates()

    # Reject format candidate
    if query_lower.startswith('reject format #'):
        parts = query_lower.replace('reject format #', '').strip().split(' ', 1)
        cid = parts[0]
        reason = parts[1] if len(parts) > 1 else ''
        return _handle_reject_candidate(cid, reason)

    # Scan channel command - legacy (still works)
    if query_lower.startswith('scan channel ') or (query_lower.startswith('scan ') and query.split()[-1].strip().isdigit()):
        channel_id = query.split()[-1].strip()
        return scan_channel_for_formats(channel_id)

    # List scannable channels
    if query_lower in ['scan channels', 'list channels', 'show channels for scanning', 'which channels can i scan']:
        return list_scannable_channels()

    # Teach format command
    if query_lower.startswith('teach this format:') or query_lower.startswith('teach format:'):
        signal_part = query.split(':', 1)[1].strip() if ':' in query else ''
        if not signal_part:
            return {
                "success": True,
                "response": "**Teaching a New Format**\n\nTo teach me a new signal format, use:\n\n`Teach this format: <paste your signal here>`\n\nFor example:\n`Teach this format: BTO SPY 600C 12/20 @ 1.50`\n\nI'll analyze the format once and remember it for future signals!",
                "topic": "format_teaching"
            }
        
        return teach_new_format(signal_part)
    
    # Show formats command
    if query_lower in ['show formats', 'list formats', 'show learned formats', 'list learned formats', 'what formats do you know']:
        return list_learned_formats()

    # Show active patterns in the live registry (learned_patterns table + singleton state)
    if any(query_lower == kw for kw in ['show active patterns', 'show registry', 'show trained formats',
                                         'check formats', 'list active patterns', 'show approved patterns']):
        return _handle_show_registry()

    # Force hot-reload of singleton from DB
    if query_lower in ['reload formats', 'reload patterns', 'refresh formats', 'refresh patterns']:
        try:
            from src.services.signal_format_registry import get_signal_format_registry
            registry = get_signal_format_registry()
            loaded = registry.reload_learned_patterns()
            return {
                "success": True,
                "response": f"**Reloaded** ✅\n\n`{loaded}` learned patterns now active in the live bot singleton.\n\nUse `show active patterns` to see them all.",
                "topic": "format_management"
            }
        except Exception as e:
            return {"success": True, "response": f"**Error reloading:** {e}", "topic": "format_management"}

    # Delete format command
    if query_lower.startswith('delete format '):
        format_name = query[14:].strip()
        return delete_learned_format(format_name)
    
    # Enable/disable format command
    if query_lower.startswith('enable format '):
        format_name = query[14:].strip()
        return toggle_format(format_name, enabled=True)
    
    if query_lower.startswith('disable format '):
        format_name = query[15:].strip()
        return toggle_format(format_name, enabled=False)
    
    return None


def _parse_signal_rule_based(signal_text: str) -> Optional[Dict]:
    """Parse a trading signal using rule-based patterns (no AI needed).
    
    Detects: action, symbol, strike, expiry, option type, entry price, SL, PT,
    conditional triggers (over/under), and role mentions.
    """
    import re
    text = signal_text.strip()
    text_upper = text.upper()
    
    parsed = {}
    
    role_match = re.search(r'<@&\d+>', text)
    if role_match:
        parsed['has_role_mention'] = True
    
    action_match = re.search(r'\b(BTO|STC|BUY|SELL|BUYING|SELLING|LONG|SHORT|BOUGHT|SOLD|ENTRY|ENTER|ENTERING)\b', text_upper)
    if action_match:
        action_map = {
            'BTO': 'BTO', 'BUY': 'BTO', 'BUYING': 'BTO', 'LONG': 'BTO', 'BOUGHT': 'BTO',
            'ENTRY': 'BTO', 'ENTER': 'BTO', 'ENTERING': 'BTO',
            'STC': 'STC', 'SELL': 'STC', 'SELLING': 'STC', 'SHORT': 'STC', 'SOLD': 'STC'
        }
        parsed['action'] = action_map.get(action_match.group(1), 'BTO')
    
    option_match = re.search(
        r'\$?([A-Z]{1,5})\s+\$?(\d{1,4}(?:\.\d{1,2})?)\s*([CcPp])\s*(?:(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?)?',
        text_upper
    )
    if option_match:
        parsed['symbol'] = option_match.group(1)
        parsed['strike'] = float(option_match.group(2))
        parsed['option_type'] = 'C' if option_match.group(3).upper() == 'C' else 'P'
        parsed['is_option'] = True
        parsed['asset_type'] = 'option'
        if option_match.group(4) and option_match.group(5):
            month = option_match.group(4)
            day = option_match.group(5)
            year = option_match.group(6) if option_match.group(6) else str(datetime.now().year)
            if len(year) == 2:
                year = '20' + year
            parsed['expiration'] = f"{month}/{day}/{year}"
    
    if 'symbol' not in parsed:
        sym_match = re.search(r'(?:^|\s)\$?([A-Z]{1,5})(?:\s|$)', text_upper)
        if sym_match and sym_match.group(1) not in ('BTO', 'STC', 'BUY', 'SELL', 'SL', 'PT', 'TP', 'TRIM', 'EXIT', 'OUT', 'OVER', 'UNDER', 'ABOVE', 'BELOW', 'ENTRY', 'ENTER', 'ENTERING', 'LONG', 'SHORT', 'BOUGHT', 'SOLD', 'BUYING', 'SELLING', 'LOTTO', 'THE', 'FOR', 'AND', 'ALL', 'IN', 'AT', 'TO', 'OF', 'ON', 'IS', 'IT', 'OR', 'UP', 'MY', 'BY', 'IF', 'SO', 'DO', 'NO', 'AN', 'AS', 'AM', 'BE', 'HE', 'ME', 'WE', 'US'):
            parsed['symbol'] = sym_match.group(1)
            parsed['is_option'] = False
            parsed['asset_type'] = 'stock'
    
    price_match = re.search(r'[@]\s*\$?([\d.]+)', text)
    if price_match:
        parsed['entry_price'] = float(price_match.group(1))
    elif not price_match:
        price_match2 = re.search(r'(?:entry|price|at|@)\s*[:=]?\s*\$?([\d.]+)', text, re.IGNORECASE)
        if price_match2:
            parsed['entry_price'] = float(price_match2.group(1))
    
    cond_match = re.search(r'(?:over|above|ocer|ober|ovwe|ovre|ovr|abve|abov)\s+\$?([\d.]+)', text, re.IGNORECASE)
    if cond_match:
        parsed['conditional_trigger'] = float(cond_match.group(1))
        parsed['trigger_direction'] = 'above'
        if 'action' not in parsed:
            parsed['action'] = 'BTO'
    
    cond_under = re.search(r'(?:under|below)\s+\$?([\d.]+)', text, re.IGNORECASE)
    if cond_under and not cond_match:
        parsed['conditional_trigger'] = float(cond_under.group(1))
        parsed['trigger_direction'] = 'below'
    
    sl_match = re.search(r'(?:SL|stop\s*loss|stop)\s*[:=]?\s*\$?([\d.]+)(%)?', text, re.IGNORECASE)
    if sl_match:
        if sl_match.group(2):
            parsed['stop_loss_pct'] = float(sl_match.group(1))
        else:
            parsed['stop_loss'] = float(sl_match.group(1))
    
    pt_matches = re.findall(r'(?:PT|TP|target|profit)\s*\d?\s*[:=]?\s*\$?([\d.]+)', text, re.IGNORECASE)
    if pt_matches:
        parsed['profit_targets'] = [float(p) for p in pt_matches]
    
    trim_match = re.search(r'\b(TRIM|EXIT|OUT|CLOSE|SOLD|TAKING\s+PROFIT)\b', text_upper)
    if trim_match and 'action' not in parsed:
        parsed['action'] = 'STC'
    
    return parsed if parsed.get('symbol') else None


def _build_regex_from_signal(signal_text: str, parsed: Dict) -> str:
    """Build a regex pattern from a signal example and its parsed fields."""
    import re
    pattern = re.escape(signal_text)
    
    if parsed.get('symbol'):
        pattern = pattern.replace(re.escape(parsed['symbol']), r'([A-Za-z]{1,5})')
    
    if parsed.get('is_option') and parsed.get('strike') is not None:
        strike_str = str(parsed['strike'])
        if strike_str.endswith('.0'):
            strike_str = strike_str[:-2]
        opt_type = parsed.get('option_type', 'C').lower()
        strike_with_type = re.escape(strike_str) + opt_type
        pattern = pattern.replace(strike_with_type, r'(\d+(?:\.\d+)?)\s*([cCpP])', 1)
        if re.escape(strike_str) in pattern:
            pattern = pattern.replace(re.escape(strike_str), r'([\d.]+)', 1)
    
    for field in ['entry_price', 'conditional_trigger', 'stop_loss']:
        val = parsed.get(field)
        if val is not None:
            val_str = str(val)
            if val_str.endswith('.0'):
                val_str = val_str[:-2]
            pattern = pattern.replace(re.escape(val_str), r'([\d.]+)', 1)
    
    if not parsed.get('is_option'):
        field_val = parsed.get('strike')
        if field_val is not None:
            val_str = str(field_val)
            if val_str.endswith('.0'):
                val_str = val_str[:-2]
            pattern = pattern.replace(re.escape(val_str), r'([\d.]+)', 1)
    
    if parsed.get('stop_loss_pct') is not None:
        val_str = str(parsed['stop_loss_pct'])
        if val_str.endswith('.0'):
            val_str = val_str[:-2]
        pattern = pattern.replace(re.escape(val_str), r'(\d+)', 1)
    
    pattern = pattern.replace(re.escape('<@&') + r'\d+' + re.escape('>'), r'<@&\d+>')
    
    role_fix = re.sub(r'<@\\&(\d+)>', r'<@&\\d+>', pattern)
    if role_fix != pattern:
        pattern = role_fix
    
    trailing_words = ['lotto', 'LOTTO', 'Lotto', 'daytrade', 'swing', 'scalp', 'risky', 'safe', 'weekly', 'daily']
    for word in trailing_words:
        esc_word = re.escape(word)
        if esc_word in pattern:
            pattern = pattern.replace(esc_word, r'(?:\S+)?')
    
    pattern = re.sub(r'(?:\\ )+', r'\\s+', pattern)
    
    if pattern.endswith(r'\s+(?:\S+)?'):
        pattern = pattern.replace(r'\s+(?:\S+)?', r'(?:\s+\S+)?')
    
    return pattern


def teach_new_format(signal_example: str) -> Dict:
    """Teach the bot a new signal format - works without AI using rule-based parsing.
    Falls back to AI for enhanced analysis if available."""
    try:
        parsed = _parse_signal_rule_based(signal_example)
        
        ai_result = None
        try:
            from .format_trainer import FormatTrainer
            trainer = FormatTrainer()
            if trainer.is_ai_available():
                ai_result = trainer.learn_format_from_example(signal_example)
                if ai_result and ai_result.get('success'):
                    parsed_ai = ai_result.get('parsed_fields', {})
                    if parsed_ai.get('symbol'):
                        if parsed is None:
                            parsed = {}
                        for key, val in parsed_ai.items():
                            if val is not None and key not in parsed:
                                parsed[key] = val
        except Exception as e:
            print(f"[CHAT] AI enhancement skipped: {e}")
        
        if not parsed or not parsed.get('symbol'):
            return {
                "success": True,
                "response": "**Could Not Parse Signal**\n\nI couldn't identify a trading signal in your example. Make sure it contains at least:\n- A ticker symbol (e.g., SPY, AAPL)\n- An action or trigger (e.g., BTO, over $150)\n\n**Example formats I can learn:**\n- `BTO SPY 600C 12/20 @ 1.50`\n- `AAPL over 150 SL 145`\n- `<@&role> TSLA 250C 1/15 @ 3.20`\n\nTry again with a clearer signal.",
                "topic": "format_teaching"
            }
        
        action = parsed.get('action', 'BTO')
        symbol = parsed.get('symbol', 'Unknown')
        asset_type = parsed.get('asset_type', 'option' if parsed.get('is_option') else 'stock')
        
        if ai_result and ai_result.get('success'):
            format_name = ai_result.get('format_name', f"Custom {symbol} Format")
            description = ai_result.get('description', f"Learned from example: {signal_example[:50]}")
            regex_pattern = ai_result.get('suggested_regex') or _build_regex_from_signal(signal_example, parsed)
            confidence = ai_result.get('confidence', 0.85)
            used_ai = True
        else:
            format_name = f"Custom {asset_type.title()} Format"
            if parsed.get('conditional_trigger'):
                format_name = f"Conditional {parsed.get('trigger_direction', 'above').title()} Entry"
            elif parsed.get('is_option'):
                format_name = f"Options {action} Format"
            description = f"Learned from example: {signal_example[:80]}"
            regex_pattern = _build_regex_from_signal(signal_example, parsed)
            confidence = 0.75
            used_ai = False
        
        from . import database as db
        
        field_mappings = {
            'action': action,
            'asset_type': asset_type,
            'has_sl': 'stop_loss' in parsed or 'stop_loss_pct' in parsed,
            'has_pt': 'profit_targets' in parsed,
            'has_conditional': 'conditional_trigger' in parsed,
            'is_option': parsed.get('is_option', False),
        }
        
        format_id = db.save_signal_format(
            name=format_name,
            description=description,
            example_signal=signal_example,
            parsed_fields=parsed,
            field_mappings=field_mappings,
            regex_pattern=regex_pattern
        )
        
        if regex_pattern:
            pattern_id = db.add_learned_pattern(
                name=format_name,
                pattern=regex_pattern,
                example_text=signal_example,
                action=action,
                asset_type=asset_type,
                description=description
            )
            if pattern_id:
                db.approve_learned_pattern(pattern_id, 'chatbot_teach')
                print(f"[CHAT] Auto-approved learned pattern #{pattern_id}: {format_name}")
        
        response_text = f"**Format Learned Successfully!**\n\n"
        response_text += f"**Name:** {format_name}\n"
        response_text += f"**Method:** {'AI-Enhanced' if used_ai else 'Rule-Based'} Analysis\n"
        response_text += f"**Confidence:** {confidence*100:.0f}%\n\n"
        response_text += f"**Parsed from your example:**\n"
        response_text += f"- Action: {action}\n"
        response_text += f"- Symbol: {symbol}\n"
        response_text += f"- Type: {asset_type.title()}\n"
        
        if parsed.get('entry_price'):
            response_text += f"- Entry: ${parsed['entry_price']}\n"
        if parsed.get('conditional_trigger'):
            response_text += f"- Trigger: {parsed.get('trigger_direction', 'above')} ${parsed['conditional_trigger']}\n"
        if parsed.get('is_option'):
            response_text += f"- Strike: ${parsed.get('strike')}\n"
            response_text += f"- Type: {'Call' if parsed.get('option_type') == 'C' else 'Put'}\n"
            if parsed.get('expiration'):
                response_text += f"- Expiry: {parsed['expiration']}\n"
        if parsed.get('stop_loss'):
            response_text += f"- Stop Loss: ${parsed['stop_loss']}\n"
        elif parsed.get('stop_loss_pct'):
            response_text += f"- Stop Loss: {parsed['stop_loss_pct']}%\n"
        if parsed.get('profit_targets'):
            response_text += f"- Profit Targets: {', '.join('$' + str(p) for p in parsed['profit_targets'])}\n"
        
        response_text += "\nThis format will now be automatically recognized for future signals!"
        if not used_ai:
            response_text += "\n\n*Tip: Enable AI in Settings for even better format detection.*"
        
        return {
            "success": True,
            "response": response_text,
            "topic": "format_teaching",
            "format_id": format_id,
            "ai_powered": used_ai
        }
        
    except Exception as e:
        print(f"[CHAT] Error teaching format: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": True,
            "response": f"**Error**\n\nSomething went wrong while learning the format: {str(e)}",
            "topic": "format_teaching"
        }


def list_learned_formats() -> Dict:
    """List all learned signal formats."""
    try:
        from . import database as db
        formats = db.get_signal_formats()
        
        if not formats:
            return {
                "success": True,
                "response": "**No Learned Formats**\n\nYou haven't taught me any custom signal formats yet.\n\nTo teach a new format, use:\n`Teach this format: <paste your signal here>`",
                "topic": "format_management"
            }
        
        response = "**Learned Signal Formats**\n\n"
        for f in formats:
            status = "Enabled" if f.get('is_enabled') else "Disabled"
            usage = f.get('usage_count', 0)
            response += f"**{f.get('name')}** ({status})\n"
            response += f"  Example: `{f.get('example_signal', '')[:50]}...`\n"
            response += f"  Used: {usage} times\n\n"
        
        response += "Commands:\n- `enable format <name>` - Enable a format\n- `disable format <name>` - Disable a format\n- `delete format <name>` - Delete a format"
        
        return {
            "success": True,
            "response": response,
            "topic": "format_management"
        }
        
    except Exception as e:
        print(f"[CHAT] Error listing formats: {e}")
        return {
            "success": True,
            "response": f"**Error**\n\nCouldn't retrieve formats: {str(e)}",
            "topic": "format_management"
        }


def _handle_show_registry() -> Dict:
    """Show learned_patterns active in DB vs what's actually loaded in the live singleton."""
    try:
        from . import database as db
        from src.services.signal_format_registry import get_signal_format_registry

        db_patterns = db.get_active_learned_patterns()
        registry = get_signal_format_registry()
        live_names = [n for n in registry._formats if n.startswith('learned_')]

        lines = [f"## Format Registry Status\n"]

        if not db_patterns:
            lines.append("**DB learned_patterns (active):** none\n\nNo formats have been approved yet.")
            lines.append("\n**How to add patterns:**")
            lines.append("1. `analyze channel <channel_id>` — scan channel history")
            lines.append("2. `show candidates` — view discovered patterns")
            lines.append("3. `approve format #N` — approve a candidate")
        else:
            lines.append(f"**DB active patterns:** {len(db_patterns)}")
            lines.append(f"**Live singleton loaded:** {len(live_names)}\n")

            db_names_set = {f"learned_{p['name']}" for p in db_patterns}
            live_names_set = set(live_names)
            if db_names_set != live_names_set:
                lines.append("⚠️ **Mismatch** — live bot registry differs from DB.")
                lines.append("Run `reload formats` to hot-reload them into the live bot.\n")
            else:
                lines.append("✅ **In sync** — all approved patterns are active in the live bot.\n")

            for p in db_patterns:
                pname = f"learned_{p['name']}"
                in_live = pname in live_names
                status_icon = '✅' if in_live else '❌'
                lines.append(f"{status_icon} **{p['name']}** (#{p['id']})")
                lines.append(f"   Pattern: `{p.get('pattern','?')[:70]}`")
                lines.append(f"   Example: `{str(p.get('example_text',''))[:60]}`")
                lines.append(f"   Action: `{p.get('action','?')}` | Asset: `{p.get('asset_type','?')}`")
                lines.append(f"   Approved by: `{p.get('approved_by','?')}` | In live singleton: {status_icon}\n")

        lines.append("\n**Commands:** `test signal: <signal>` · `approve format #N` · `reload formats`")

        return {"success": True, "response": "\n".join(lines), "topic": "format_management"}

    except Exception as e:
        return {"success": True, "response": f"**Error checking registry:** {e}", "topic": "format_management"}


def toggle_format(format_name: str, enabled: bool) -> Dict:
    """Enable or disable a learned format."""
    try:
        from . import database as db
        success = db.toggle_signal_format(format_name, enabled)
        
        if success:
            action = "enabled" if enabled else "disabled"
            return {
                "success": True,
                "response": f"Format **{format_name}** has been {action}.",
                "topic": "format_management"
            }
        else:
            return {
                "success": True,
                "response": f"Format **{format_name}** not found. Use `show formats` to see available formats.",
                "topic": "format_management"
            }
            
    except Exception as e:
        print(f"[CHAT] Error toggling format: {e}")
        return {
            "success": True,
            "response": f"**Error**\n\nCouldn't update format: {str(e)}",
            "topic": "format_management"
        }


def delete_learned_format(format_name: str) -> Dict:
    """Delete a learned format."""
    try:
        from . import database as db
        success = db.delete_signal_format_by_name(format_name)
        
        if success:
            return {
                "success": True,
                "response": f"Format **{format_name}** has been deleted.",
                "topic": "format_management"
            }
        else:
            return {
                "success": True,
                "response": f"Format **{format_name}** not found. Use `show formats` to see available formats.",
                "topic": "format_management"
            }
            
    except Exception as e:
        print(f"[CHAT] Error deleting format: {e}")
        return {
            "success": True,
            "response": f"**Error**\n\nCouldn't delete format: {str(e)}",
            "topic": "format_management"
        }


def list_scannable_channels() -> Dict:
    """List channels that have stored messages for format discovery."""
    try:
        from . import database as db
        channels = db.get_all_channels_with_messages()
        
        if not channels:
            return {
                "success": True,
                "response": "**No Channels Available for Scanning**\n\nI haven't collected any messages from monitored channels yet.\n\nTo enable format discovery:\n1. Add channels in the Channels page\n2. Wait for some messages to come through\n3. Then use `scan channel <channel_id>` to learn formats\n\nAlternatively, use `teach this format: <signal>` to teach formats manually.",
                "topic": "format_discovery"
            }
        
        response = "**Channels Available for Format Discovery**\n\n"
        for ch in channels:
            response += f"**{ch.get('channel_name', 'Unknown')}**\n"
            response += f"  ID: `{ch['channel_id']}`\n"
            response += f"  Messages: {ch['message_count']}\n"
            response += f"  Last activity: {ch.get('last_message', 'Unknown')}\n\n"
        
        response += "To scan a channel and auto-learn formats:\n`scan channel <channel_id>`"
        
        return {
            "success": True,
            "response": response,
            "topic": "format_discovery"
        }
        
    except Exception as e:
        print(f"[CHAT] Error listing scannable channels: {e}")
        return {
            "success": True,
            "response": f"**Error**\n\nCouldn't list channels: {str(e)}",
            "topic": "format_discovery"
        }


def scan_channel_for_formats(channel_id: str) -> Dict:
    """Scan a channel's messages and auto-learn signal formats using AI."""
    try:
        from . import database as db
        from .format_trainer import get_format_trainer
        
        trainer = get_format_trainer()
        
        if not trainer.is_ai_available():
            return {
                "success": True,
                "response": "**AI Not Available**\n\nTo scan channels and auto-learn formats, I need AI access.\n\nConfigure your AI provider in **Settings > AI & Market Data APIs**:\n- **Auto/Replit AI** - Uses Replit AI Integration\n- **OpenAI** - Uses your own OpenAI API key\n\nOr use `teach this format: <signal>` to teach formats one at a time.",
                "topic": "format_discovery"
            }
        
        messages = db.get_recent_channel_messages(channel_id, limit=50)
        
        if not messages:
            return {
                "success": True,
                "response": f"**No Messages Found**\n\nNo messages found for channel ID `{channel_id}`.\n\nMake sure:\n1. The channel is configured in the Channels page\n2. Some messages have been received\n3. The channel ID is correct\n\nUse `scan channels` to see available channels.",
                "topic": "format_discovery"
            }
        
        channels = db.get_all_channels_with_messages()
        channel_name = next((ch['channel_name'] for ch in channels if ch['channel_id'] == channel_id), 'Unknown Channel')
        
        result = trainer.discover_formats_from_messages(messages, channel_name)
        
        if not result.get('success'):
            return {
                "success": True,
                "response": f"**Discovery Failed**\n\n{result.get('error', 'Unknown error')}\n\nTry again later or teach formats manually.",
                "topic": "format_discovery"
            }
        
        formats_saved = result.get('formats_saved', [])
        formats_skipped = result.get('formats_skipped', [])
        
        if not formats_saved and not formats_skipped:
            return {
                "success": True,
                "response": f"**No New Formats Found**\n\nAnalyzed {len(messages)} messages from **{channel_name}** but didn't find any recognizable signal formats.\n\nThis could mean:\n- The channel doesn't contain trading signals\n- Signals use a format already known\n- Messages need more variety for pattern detection",
                "topic": "format_discovery"
            }
        
        response = f"**Format Discovery Complete!**\n\n"
        response += f"Scanned: {len(messages)} messages from **{channel_name}**\n"
        response += f"Summary: {result.get('summary', '')}\n\n"
        
        if formats_saved:
            response += f"**Formats Learned ({len(formats_saved)}):**\n"
            for fmt in formats_saved:
                response += f"- {fmt['name']} ({fmt['confidence']*100:.0f}% confidence)\n"
            response += "\n"
        
        if formats_skipped:
            response += f"**Skipped ({len(formats_skipped)}):**\n"
            for fmt in formats_skipped:
                response += f"- {fmt['name']}: {fmt['reason']}\n"
        
        response += "\nUse `show formats` to see all learned formats."
        
        return {
            "success": True,
            "response": response,
            "topic": "format_discovery",
            "ai_powered": True,
            "formats_saved": len(formats_saved)
        }
        
    except Exception as e:
        print(f"[CHAT] Error scanning channel: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": True,
            "response": f"**Error**\n\nCouldn't scan channel: {str(e)}",
            "topic": "format_discovery"
        }


def _extract_channel_history(channel_id: str, limit: int = 1000) -> Dict:
    """Extract channel history into DB via the running bot instance."""
    try:
        from .routes import _bot_instance
        if not _bot_instance or not hasattr(_bot_instance, 'loop') or not _bot_instance.loop:
            return {'success': False, 'error': 'Bot is not running. Start the bot first.'}

        import asyncio
        from src.services.format_learning_pipeline import async_extract_history_to_db

        loop = _bot_instance.loop
        if loop.is_closed():
            return {'success': False, 'error': 'Bot event loop is closed.'}

        future = asyncio.run_coroutine_threadsafe(
            async_extract_history_to_db(_bot_instance, int(channel_id), limit),
            loop
        )
        result = future.result(timeout=120)
        return result
    except Exception as e:
        return {'success': False, 'error': str(e)}


def _handle_analyze_channel(channel_id: str) -> Dict:
    """Trigger format analysis on a channel's buffered messages.
    Auto-extracts history if not enough messages are buffered."""
    try:
        from . import database as db
        msg_count = db.get_channel_message_count(channel_id)

        if msg_count < 50:
            extract_result = _extract_channel_history(channel_id, 1000)
            if extract_result.get('success'):
                msg_count = db.get_channel_message_count(channel_id)
                print(f"[FORMAT_LEARN] Auto-extracted {extract_result.get('messages_saved', 0)} messages from {extract_result.get('channel_name', channel_id)}, total buffered: {msg_count}")
            else:
                if msg_count == 0:
                    return {
                        "success": True,
                        "response": f"**Could Not Extract History**\n\n{extract_result.get('error', 'Unknown error')}\n\n"
                                   f"Make sure:\n"
                                   f"1. The channel `{channel_id}` is added in **Trading → Channels**\n"
                                   f"2. The bot is running and connected to Discord\n"
                                   f"3. The bot has access to read that channel",
                        "topic": "format_learning"
                    }

        if msg_count == 0:
            return {
                "success": True,
                "response": f"**No Messages Found**\n\nChannel `{channel_id}` has no messages. Make sure the channel is configured and the bot has access.",
                "topic": "format_learning"
            }

        from src.services.format_learning_pipeline import analyze_channel_formats
        result = analyze_channel_formats(channel_id)

        if not result.get('success'):
            return {"success": True, "response": f"**Analysis Failed**\n\n{result.get('error', 'Unknown error')}", "topic": "format_learning"}

        from src.services.format_learning_pipeline import format_candidates_for_display
        candidates_text = format_candidates_for_display(channel_id)

        response = f"**Format Analysis Complete**\n\n"
        response += f"Channel: **{result.get('channel_name', channel_id)}**\n"
        response += f"Messages analyzed: {result.get('messages_analyzed', 0)}\n"
        response += f"Heuristic patterns: {result.get('heuristic_patterns', 0)}\n"
        response += f"AI patterns: {result.get('ai_patterns', 0)}\n"
        response += f"Candidates saved: {result.get('candidates_saved', 0)}\n\n"
        response += candidates_text

        return {"success": True, "response": response, "topic": "format_learning", "ai_powered": True}

    except Exception as e:
        print(f"[CHAT] Analyze channel error: {e}")
        import traceback
        traceback.print_exc()
        return {"success": True, "response": f"**Error**\n\n{str(e)}", "topic": "format_learning"}


def _handle_show_candidates(channel_id: str = None) -> Dict:
    """Show pending format candidates."""
    try:
        from . import database as db
        if channel_id:
            candidates = db.get_format_candidates(channel_id, status='pending')
        else:
            candidates = db.get_format_candidates(status='pending')

        if not candidates:
            return {
                "success": True,
                "response": "**No Pending Candidates**\n\nNo format candidates are awaiting approval.\n\nTo discover formats:\n1. `analyze channel <channel_id>` — Run AI analysis on buffered messages",
                "topic": "format_learning"
            }

        from src.services.format_learning_pipeline import format_candidates_for_display
        if channel_id:
            text = format_candidates_for_display(channel_id)
        else:
            unique_channels = list(set(c['channel_id'] for c in candidates))
            parts = []
            for ch_id in unique_channels:
                parts.append(format_candidates_for_display(ch_id))
            text = "\n---\n".join(parts)

        return {"success": True, "response": text, "topic": "format_learning"}

    except Exception as e:
        return {"success": True, "response": f"**Error**: {str(e)}", "topic": "format_learning"}


def _handle_approve_candidate(candidate_id_str: str) -> Dict:
    """Approve a specific format candidate."""
    try:
        from . import database as db
        cid = int(candidate_id_str)
        candidates = db.get_format_candidates()
        candidate = next((c for c in candidates if c['id'] == cid), None)

        if not candidate:
            return {"success": True, "response": f"**Not Found**\n\nFormat candidate #{cid} not found.", "topic": "format_learning"}

        if candidate['status'] != 'pending':
            return {"success": True, "response": f"**Already {candidate['status'].title()}**\n\nCandidate #{cid} is already {candidate['status']}.", "topic": "format_learning"}

        ok = db.approve_format_candidate(cid, approved_by='chatbot')
        if not ok:
            return {"success": True, "response": f"**Failed** to approve candidate #{cid}.", "topic": "format_learning"}

        regex = candidate.get('regex_pattern') or ''
        if not regex:
            _HEURISTIC_REGEX = {
                'heuristic_option_bto': r'\$?([A-Z]{1,5})\s+\$?(\d+(?:\.\d+)?)\s*([CcPp])\s+(?:@\s*)?\$?(\.?\d+(?:\.\d+)?)',
                'heuristic_option_stc': r'(?:out|sold|STC|cut|trim|exit)\s+\$?([A-Z]{1,5})\s+(\d+(?:\.\d+)?)\s*([CcPp])',
                'heuristic_bto_keyword': r'(?:BTO|BUY|BUYING|LONG)\s+\$?([A-Z]{1,5})\s+\$?(\d+(?:\.\d+)?)\s*([CcPp])\s+(?:at\s+)?\$?(\.?\d+(?:\.\d+)?)',
                'heuristic_stc_keyword': r'(?:STC|SELL|SOLD|OUT|EXIT|TRIM|CLOSING|CUT)\s+\$?([A-Z]{1,5})',
                'heuristic_dollar_ticker': r'\$([A-Z]{1,5})\s+(?:.*?)(\d+(?:\.\d+)?)\s*([CcPp])\s+(?:.*?)(\.?\d+(?:\.\d+)?)',
                'heuristic_emoji_entry': r'[✅▶🟢]\s*\$?([A-Z]{1,5})\s+\$?(\d+(?:\.\d+)?)',
                'heuristic_emoji_exit': r'[❌⛔🔴]\s*\$?([A-Z]{1,5})',
            }
            regex = _HEURISTIC_REGEX.get(candidate['format_name'], '')

        if regex:
            try:
                import re as _re
                _re.compile(regex)
                pattern_id = db.add_learned_pattern(
                    name=candidate['format_name'],
                    pattern=regex,
                    example_text=candidate.get('example_messages', ''),
                    action=candidate['action'],
                    asset_type=candidate['asset_type'],
                    description=f"Auto-discovered for channel {candidate['channel_id']}"
                )
                if pattern_id:
                    db.approve_learned_pattern(pattern_id, 'format_learning')
                    print(f"[CHAT] Registered learned pattern: {candidate['format_name']} -> {regex[:60]}")
            except Exception as e:
                print(f"[CHAT] Error registering learned pattern: {e}")

        channel_id = candidate['channel_id']
        try:
            channel_info = db.get_channel_by_discord_id(channel_id)
            if channel_info:
                import json as _json
                allowed = channel_info.get('allowed_signal_formats')
                fmt_list = _json.loads(allowed) if allowed and isinstance(allowed, str) else (allowed or [])
                if candidate['format_name'] not in fmt_list:
                    fmt_list.append(candidate['format_name'])
                    db.update_channel(channel_info['id'], allowed_signal_formats=_json.dumps(fmt_list))
                    print(f"[CHAT] Updated allowed_signal_formats for channel {channel_id}: {fmt_list}")
        except Exception as e:
            print(f"[CHAT] Warning: approved format but failed to update channel allowed_signal_formats: {e}")

        reload_warning = ""
        try:
            from src.services.signal_format_registry import get_signal_format_registry
            registry = get_signal_format_registry()
            loaded = registry.reload_learned_patterns()
            print(f"[CHAT] Hot-reloaded learned patterns into singleton: {loaded} active")
        except Exception as e:
            print(f"[CHAT] Warning: could not hot-reload patterns: {e}")
            reload_warning = f"\n\n⚠️ **Note:** Live bot registry could not be updated ({e}). The format is saved in DB but the bot won't recognize it until restarted. Run `reload formats` to retry."

        return {
            "success": True,
            "response": f"**Approved** ✓\n\nFormat **{candidate['format_name']}** (#{cid}) is now active for channel `{candidate['channel_id']}`.\n\nThe bot will now recognize this signal format and route matches through conditional orders.{reload_warning}",
            "topic": "format_learning"
        }

    except ValueError:
        return {"success": True, "response": "**Invalid ID**. Use `approve format #123`.", "topic": "format_learning"}
    except Exception as e:
        return {"success": True, "response": f"**Error**: {str(e)}", "topic": "format_learning"}


def _handle_approve_all_candidates() -> Dict:
    """Approve all pending format candidates."""
    try:
        from . import database as db
        candidates = db.get_format_candidates(status='pending')
        if not candidates:
            return {"success": True, "response": "**No Pending Candidates** to approve.", "topic": "format_learning"}

        approved = 0
        for c in candidates:
            result = _handle_approve_candidate(str(c['id']))
            if 'Approved' in result.get('response', ''):
                approved += 1

        return {
            "success": True,
            "response": f"**Approved {approved}/{len(candidates)} Formats** ✓\n\nAll approved formats are now active.",
            "topic": "format_learning"
        }
    except Exception as e:
        return {"success": True, "response": f"**Error**: {str(e)}", "topic": "format_learning"}


def _handle_reject_candidate(candidate_id_str: str, reason: str = '') -> Dict:
    """Reject a format candidate."""
    try:
        from . import database as db
        cid = int(candidate_id_str)
        ok = db.reject_format_candidate(cid, reason)
        if ok:
            return {"success": True, "response": f"**Rejected** ✗\n\nFormat candidate #{cid} has been rejected.{f' Reason: {reason}' if reason else ''}", "topic": "format_learning"}
        return {"success": True, "response": f"**Not Found** — Candidate #{cid} not found.", "topic": "format_learning"}
    except ValueError:
        return {"success": True, "response": "**Invalid ID**. Use `reject format #123`.", "topic": "format_learning"}
    except Exception as e:
        return {"success": True, "response": f"**Error**: {str(e)}", "topic": "format_learning"}


def _list_channels_from_db() -> Dict:
    """List configured channels with real data from the database."""
    try:
        from . import database as db
        channels = db.get_channels()
        if not channels:
            return {"success": True, "response": "**No Channels Configured**\n\nGo to **Trading → Channels** to add your first channel.", "topic": "channels"}

        lines = [f"**Configured Channels ({len(channels)} total)**\n"]
        for i, ch in enumerate(channels, 1):
            name = ch.get('name', '?')
            disc_id = ch.get('discord_channel_id', '')
            exe = 'Execute' if ch.get('execute_enabled') else ''
            trk = 'Track' if ch.get('track_enabled') else ''
            mode = '+'.join(filter(None, [exe, trk])) or 'Disabled'
            broker = ch.get('enabled_brokers', '') or ch.get('broker_override', '') or 'Not assigned'
            risk = 'Risk ON' if ch.get('risk_management_enabled') else ''
            pos_size = ch.get('position_size_pct', 0) or 0
            default_qty = ch.get('default_quantity', '') or ''

            line = f"{i}. **{name}** (ID: {disc_id}) [{mode}]"
            if broker and broker != 'Not assigned':
                line += f" — Broker: {broker}"
            details = []
            if pos_size:
                details.append(f"Size: {pos_size}%")
            if default_qty:
                details.append(f"Qty: {default_qty}")
            if risk:
                details.append(risk)
            if details:
                line += f" | {', '.join(details)}"
            lines.append(line)

        return {"success": True, "response": "\n".join(lines), "topic": "channels_list"}
    except Exception as e:
        return {"success": True, "response": f"Error listing channels: {e}", "topic": "error"}


def get_suggestions(partial_query: str) -> List[str]:
    """Get topic suggestions based on partial query"""
    if not partial_query or len(partial_query) < 2:
        return ["Getting started", "Dashboard help", "How to add channels", "Broker setup", "Options trading"]
    
    suggestions = []
    partial_lower = partial_query.lower()
    
    for topic_id, topic_data in KNOWLEDGE_BASE.items():
        title = topic_data.get("title", "")
        keywords = topic_data.get("keywords", [])
        
        if partial_lower in title.lower():
            suggestions.append(title)
        else:
            for kw in keywords:
                if partial_lower in kw or kw in partial_lower:
                    suggestions.append(f"Tell me about {kw}")
                    break
    
    return suggestions[:5]


def get_all_topics() -> List[Dict]:
    """Get list of all available topics"""
    return [
        {"id": topic_id, "title": data["title"], "keywords": data["keywords"][:3]}
        for topic_id, data in KNOWLEDGE_BASE.items()
    ]


# ==================== ERROR MONITORING INTEGRATION ====================

def get_error_context() -> Dict:
    """Get current error context for the chat assistant."""
    try:
        from . import database as db
        
        # Get recent unresolved errors
        recent_errors = db.get_recent_errors(limit=5, hours=24)
        error_stats = db.get_error_stats(hours=24)
        unnotified = db.get_unnotified_errors()
        
        return {
            "has_errors": len(recent_errors) > 0,
            "error_count": error_stats.get('total', 0),
            "critical_count": error_stats.get('critical', 0),
            "recent_errors": recent_errors,
            "unnotified_count": len(unnotified),
            "unnotified_errors": unnotified[:3]  # Top 3 unnotified
        }
    except Exception as e:
        print(f"[CHAT] Error getting error context: {e}")
        return {"has_errors": False, "error_count": 0, "critical_count": 0, "recent_errors": [], "unnotified_count": 0, "unnotified_errors": []}


def get_error_help(error_message: str) -> Optional[Dict]:
    """Get help for a specific error message."""
    try:
        from . import database as db
        
        # Try to find a known issue solution
        known_issue = db.find_known_issue_solution(error_message)
        
        if known_issue:
            return {
                "found": True,
                "title": known_issue.get('issue_title', 'Known Issue'),
                "description": known_issue.get('issue_description', ''),
                "solution": known_issue.get('solution', ''),
                "category": known_issue.get('category', 'general')
            }
        
        return {"found": False}
        
    except Exception as e:
        print(f"[CHAT] Error getting error help: {e}")
        return {"found": False}


def format_error_alert(errors: List[Dict]) -> str:
    """Format error alerts for display."""
    if not errors:
        return ""
    
    severity_icons = {
        'critical': '🔴',
        'error': '🟠',
        'warning': '🟡',
        'info': '🔵'
    }
    
    lines = ["**Recent Issues Detected:**\n"]
    
    for error in errors[:3]:
        icon = severity_icons.get(error.get('severity', 'error'), '🟠')
        error_type = error.get('error_type', 'Unknown')
        message = error.get('error_message', '')[:100]
        occurrences = error.get('occurrence_count', 1)
        
        lines.append(f"{icon} **{error_type}**: {message}")
        if occurrences > 1:
            lines[-1] += f" (×{occurrences})"
    
    return '\n'.join(lines)


def get_contextual_response(query: str) -> Dict:
    """Get a response that considers current error context."""
    try:
        from . import database as db
        
        query_lower = query.lower()
        
        # Check if user is asking about errors/issues/problems
        error_keywords = ['error', 'issue', 'problem', 'wrong', 'broken', 'not working', 'failed', 'failing', 'help', 'fix']
        is_asking_about_errors = any(kw in query_lower for kw in error_keywords)
        
        if is_asking_about_errors:
            # Get current errors
            error_context = get_error_context()
            
            if error_context['has_errors']:
                recent = error_context['recent_errors']
                
                # Try to find solutions for the errors
                solutions = []
                for err in recent[:2]:
                    help_info = get_error_help(err.get('error_message', ''))
                    if help_info and help_info.get('found'):
                        solutions.append({
                            'error': err.get('error_type', 'Error'),
                            'solution': help_info
                        })
                
                if solutions:
                    response_parts = ["I found some recent issues and their solutions:\n"]
                    
                    for sol in solutions:
                        response_parts.append(f"**{sol['solution']['title']}**")
                        response_parts.append(f"{sol['solution']['description']}")
                        response_parts.append(f"\n**Solution:** {sol['solution']['solution']}\n")
                    
                    return {
                        "success": True,
                        "response": '\n'.join(response_parts),
                        "topic": "error_help",
                        "has_errors": True,
                        "error_count": error_context['error_count']
                    }
                else:
                    # Show errors without specific solutions
                    error_alert = format_error_alert(recent)
                    response = f"{error_alert}\n\nI detected these issues but don't have specific solutions yet. Try checking:\n• Broker credentials in Settings\n• Discord token validity\n• Network connection\n• Console logs for details"
                    
                    return {
                        "success": True,
                        "response": response,
                        "topic": "error_detected",
                        "has_errors": True,
                        "error_count": error_context['error_count']
                    }
        
        # Fall back to regular response
        return get_response(query)
        
    except Exception as e:
        print(f"[CHAT] Error in contextual response: {e}")
        return get_response(query)


def get_chat_status() -> Dict:
    """Get the current status for the chat widget (error badge, etc.)."""
    error_context = get_error_context()
    
    return {
        "has_unnotified": error_context['unnotified_count'] > 0,
        "unnotified_count": error_context['unnotified_count'],
        "has_critical": error_context['critical_count'] > 0,
        "total_errors": error_context['error_count'],
        "errors": error_context['unnotified_errors']
    }


def mark_errors_seen() -> bool:
    """Mark all unnotified errors as seen."""
    try:
        from . import database as db
        
        unnotified = db.get_unnotified_errors()
        if unnotified:
            error_ids = [e['id'] for e in unnotified]
            return db.mark_errors_notified(error_ids)
        return True
        
    except Exception as e:
        print(f"[CHAT] Error marking errors seen: {e}")
        return False


# ==================== AI-POWERED LOG & TRADE ANALYSIS ====================

def get_ai_response(query: str) -> Dict:
    """
    Get an AI-powered response using OpenAI to analyze logs, trades, and issues.
    This is the main entry point for intelligent chat queries.
    Falls back to knowledge base if OpenAI is not available.
    """
    query_lower = query.lower().strip()
    
    if is_format_teaching_query(query_lower):
        return handle_format_teaching(query)
    elif is_format_management_query(query_lower):
        return handle_format_management(query)
    elif is_signal_test_query(query_lower):
        return test_signal_parsing(query)
    elif is_trade_query(query_lower):
        return analyze_trades(query)
    elif is_log_query(query_lower):
        return analyze_logs(query)
    elif is_error_query(query_lower):
        return analyze_errors(query)
    else:
        return get_contextual_response(query)


def is_format_teaching_query(query: str) -> bool:
    """Check if query is about teaching/learning new signal formats."""
    teaching_keywords = ["teach", "learn", "new format", "add format", "train", 
                         "recognize", "parse this", "understand this signal",
                         "new signal type", "custom format"]
    return any(kw in query for kw in teaching_keywords)


def is_format_management_query(query: str) -> bool:
    """Check if query is about managing learned formats."""
    management_keywords = ["list format", "show format", "my format", "learned format",
                           "delete format", "disable format", "enable format",
                           "signal formats", "custom formats"]
    return any(kw in query for kw in management_keywords)


def handle_format_teaching(query: str) -> Dict:
    """
    Handle requests to teach new signal formats.
    Uses AI to analyze the signal and create a parsing template.
    """
    try:
        from .format_trainer import get_format_trainer
        trainer = get_format_trainer()
        
        if not trainer.is_ai_available():
            from .config_service import get_ai_provider
            provider = get_ai_provider()
            
            if provider == 'disabled':
                msg = """**AI Features Disabled**

AI is currently disabled in your settings. To teach new signal formats:

1. Go to **Settings** > **AI & Market Data APIs**
2. Select Claude, Gemini, or OpenAI from the dropdown
3. Enter your API key and click **Save API Keys**

Then try again!"""
            else:
                msg = """**AI API Key Required**

To teach new signal formats, configure your OpenAI API key:

1. Go to **Settings** > **AI & Market Data APIs**
2. Enter your OpenAI API key
3. Click **Save API Keys**"""
            
            return {
                "success": True,
                "response": msg,
                "topic": "format_teaching",
                "ai_powered": False
            }
        
        signal_match = re.search(r'(?:teach|learn|train|parse|recognize)[:\s]+(.+)', query, re.IGNORECASE | re.DOTALL)
        
        if not signal_match:
            example_signal = extract_signal_from_query(query)
            if not example_signal:
                return {
                    "success": True,
                    "response": """**Ready to Learn a New Signal Format!**

To teach me a new signal format, paste an example signal after your request:

**Examples:**
- "Teach this format: BTO AAPL 150C 12/20 @ 2.50"
- "Learn this signal: TRADE IDEA - SPY Entry: 450 Target: 455"
- "Recognize this: BUY $TSLA at $250, TP1: $260, SL: $240"

I'll analyze it with AI once and save the format for future use!""",
                    "topic": "format_teaching",
                    "ai_powered": True
                }
        else:
            example_signal = signal_match.group(1).strip()
        
        result = trainer.learn_format_from_example(example_signal)
        
        if not result.get('success'):
            return {
                "success": True,
                "response": f"**Couldn't Analyze Signal**\n\n{result.get('error', 'Unknown error occurred.')}",
                "topic": "format_teaching",
                "ai_powered": result.get('ai_powered', False)
            }
        
        parsed = result.get('parsed_fields', {})
        format_name = result.get('format_name', 'Custom Format')
        description = result.get('description', '')
        
        save_result = trainer.validate_and_save_format(
            name=format_name,
            description=description,
            example_signal=example_signal,
            parsed_fields=parsed,
            regex_pattern=result.get('suggested_regex'),
            field_mappings=result.get('field_mappings', {})
        )
        
        if save_result.get('success'):
            parsed_display = format_parsed_fields(parsed)
            return {
                "success": True,
                "response": f"""**Format Learned Successfully!**

**Format Name:** {format_name}
{f'**Description:** {description}' if description else ''}

**Parsed Information:**
{parsed_display}

**Confidence:** {int(result.get('confidence', 0.8) * 100)}%

This format is now saved and will be used to parse similar signals instantly without AI costs!

**Tip:** You can view and manage all learned formats by asking "Show my formats" """,
                "topic": "format_learned",
                "ai_powered": True,
                "format_id": save_result.get('format_id')
            }
        else:
            return {
                "success": True,
                "response": f"**Analyzed but couldn't save:**\n\n{save_result.get('error', 'Database error')}\n\nPlease try again.",
                "topic": "format_teaching",
                "ai_powered": True
            }
            
    except Exception as e:
        print(f"[CHAT] Format teaching error: {e}")
        return {
            "success": True,
            "response": f"An error occurred while learning the format. Please try again.",
            "topic": "error"
        }


def handle_format_management(query: str) -> Dict:
    """Handle requests to manage learned signal formats."""
    try:
        from .format_trainer import get_format_trainer
        trainer = get_format_trainer()
        
        query_lower = query.lower()
        
        if "delete" in query_lower:
            id_match = re.search(r'(?:format|id)\s*#?(\d+)', query_lower)
            if id_match:
                format_id = int(id_match.group(1))
                if trainer.delete_format(format_id):
                    return {
                        "success": True,
                        "response": f"**Format #{format_id} deleted successfully!**",
                        "topic": "format_deleted"
                    }
                else:
                    return {
                        "success": True,
                        "response": f"Couldn't delete format #{format_id}. It may not exist.",
                        "topic": "format_error"
                    }
        
        elif "disable" in query_lower or "enable" in query_lower:
            enable = "enable" in query_lower
            id_match = re.search(r'(?:format|id)\s*#?(\d+)', query_lower)
            if id_match:
                format_id = int(id_match.group(1))
                if trainer.toggle_format(format_id, enable):
                    status = "enabled" if enable else "disabled"
                    return {
                        "success": True,
                        "response": f"**Format #{format_id} {status}!**",
                        "topic": "format_toggled"
                    }
        
        formats = trainer.get_all_formats(include_disabled=True)
        
        if not formats:
            return {
                "success": True,
                "response": """**No Custom Formats Yet**

You haven't taught me any custom signal formats yet!

To add a new format, just say:
"Teach this format: [paste your signal here]"

I'll learn to recognize similar signals automatically.""",
                "topic": "format_list"
            }
        
        format_list = []
        for fmt in formats:
            status = "Active" if fmt.get('is_enabled') else "Disabled"
            usage = fmt.get('usage_count', 0)
            success_rate = fmt.get('success_rate', 100)
            format_list.append(
                f"**#{fmt['id']} - {fmt['name']}** ({status})\n"
                f"   Uses: {usage} | Success: {success_rate:.0f}%\n"
                f"   Example: `{fmt['example_signal'][:50]}...`" if len(fmt.get('example_signal', '')) > 50 
                else f"**#{fmt['id']} - {fmt['name']}** ({status})\n"
                     f"   Uses: {usage} | Success: {success_rate:.0f}%\n"
                     f"   Example: `{fmt.get('example_signal', 'N/A')}`"
            )
        
        return {
            "success": True,
            "response": f"""**Your Learned Signal Formats**

{chr(10).join(format_list)}

**Commands:**
- "Delete format #X" - Remove a format
- "Disable format #X" - Temporarily disable
- "Enable format #X" - Re-enable a format
- "Teach format: [signal]" - Add new format""",
            "topic": "format_list"
        }
        
    except Exception as e:
        print(f"[CHAT] Format management error: {e}")
        return {
            "success": True,
            "response": "An error occurred while managing formats.",
            "topic": "error"
        }


def extract_signal_from_query(query: str) -> Optional[str]:
    """Try to extract a signal from a query that might contain one."""
    lines = query.split('\n')
    for line in lines:
        line = line.strip()
        if len(line) > 10:
            signal_indicators = ['bto', 'stc', 'buy', 'sell', 'trade', 
                                 'entry', 'target', '@', '$']
            if any(ind in line.lower() for ind in signal_indicators):
                return line
    return None


def format_parsed_fields(parsed: Dict) -> str:
    """Format parsed fields for display."""
    lines = []
    field_labels = {
        'action': 'Action',
        'symbol': 'Symbol',
        'entry_price': 'Entry Price',
        'quantity': 'Quantity',
        'profit_targets': 'Profit Targets',
        'stop_loss': 'Stop Loss',
        'is_option': 'Option Trade',
        'strike': 'Strike',
        'expiration': 'Expiration',
        'option_type': 'Type'
    }
    
    for key, label in field_labels.items():
        value = parsed.get(key)
        if value is not None:
            if key == 'is_option':
                value = 'Yes' if value else 'No'
            elif key == 'option_type':
                value = 'Call' if value == 'C' else 'Put' if value == 'P' else value
            elif key == 'profit_targets' and isinstance(value, list):
                value = ', '.join([f'${v}' if isinstance(v, (int, float)) else str(v) for v in value])
            elif key == 'entry_price' or key == 'stop_loss' or key == 'strike':
                if isinstance(value, (int, float)):
                    value = f'${value}'
            lines.append(f"- **{label}:** {value}")
    
    return '\n'.join(lines) if lines else "No fields extracted"


def is_signal_test_query(query: str) -> bool:
    """Check if user wants to test if a signal will be recognized."""
    test_keywords = ["test this", "will this work", "parse this", "recognize this",
                     "try this signal", "check this signal", "validate this",
                     "will bot recognize", "can you parse", "test signal"]
    return any(kw in query for kw in test_keywords)


def test_signal_parsing(query: str) -> Dict:
    """Test if a signal will be recognized by regex parsers and/or AI fallback."""
    try:
        signal_text = extract_signal_from_query(query) or query
        signal_match = re.search(r'(?:test|parse|recognize|validate|check|try)[:\s]+(.+)', query, re.IGNORECASE | re.DOTALL)
        if signal_match:
            signal_text = signal_match.group(1).strip()

        from src.services.signal_format_registry import get_signal_format_registry
        reg = get_signal_format_registry()
        results = reg.parse_all(signal_text)

        if results:
            r = results[0]
            fmt = r.get('_format_name', 'unknown')
            action = r.get('action', '?')
            symbol = r.get('symbol', '?')
            price = r.get('price')
            is_cond = r.get('_conditional_order') or r.get('is_conditional')
            targets = r.get('profit_targets', [])
            sl = r.get('stop_loss_value') or r.get('stop_loss_fixed')
            sl_pct = r.get('stop_loss_pct')

            lines = [
                f"**Regex Match: {fmt}**\n",
                f"- **Action:** {action}",
                f"- **Symbol:** {symbol}",
                f"- **Price:** ${price}" if price else "- **Price:** market",
                f"- **Type:** {'Conditional Order' if is_cond else 'Immediate Execution'}",
            ]
            if targets:
                lines.append(f"- **Targets:** {', '.join(f'${t}' for t in targets)}")
            if sl:
                lines.append(f"- **Stop Loss:** ${sl}")
            elif sl_pct:
                lines.append(f"- **Stop Loss:** {sl_pct}%")
            lines.append(f"\nThis signal **will be recognized** by the regex parser and executed on your channel's assigned broker(s).")

            return {
                "success": True,
                "response": '\n'.join(lines),
                "topic": "signal_test",
                "ai_powered": False
            }
        else:
            ai_note = ""
            try:
                from gui_app.config_service import get_ai_provider
                provider = get_ai_provider()
                if provider != 'disabled':
                    ai_response = _call_ai(
                        f"Parse this trading signal:\n\n{signal_text}",
                        "", "signal_test"
                    )
                    if ai_response:
                        ai_note = f"\n\n**AI Fallback Analysis ({provider}):**\n{ai_response}"
                    else:
                        ai_note = f"\n\nAI fallback ({provider}) could not analyze this signal."
                else:
                    ai_note = "\n\nAI fallback is **disabled**. Enable it in Settings > AI & Market Data APIs to catch unrecognized formats."
            except Exception:
                pass

            return {
                "success": True,
                "response": f"**No Regex Match**\n\nThis signal does not match any of the 140+ registered format patterns.\n\n```\n{signal_text[:200]}\n```{ai_note}",
                "topic": "signal_test",
                "ai_powered": bool(ai_note)
            }

    except Exception as e:
        print(f"[CHAT] Signal test error: {e}")
        return {
            "success": True,
            "response": f"Error testing signal: {e}",
            "topic": "error"
        }


_NON_TICKER_WORDS = {
    'AI', 'IS', 'IT', 'TO', 'DO', 'IF', 'OR', 'ON', 'IN', 'UP', 'MY', 'NO', 'SO',
    'AM', 'AN', 'AS', 'AT', 'BY', 'GO', 'HE', 'ME', 'OF', 'OK', 'WE', 'BE', 'US',
    'HOW', 'THE', 'AND', 'FOR', 'NOT', 'ALL', 'CAN', 'HAS', 'HER', 'WAS', 'ONE',
    'SET', 'GET', 'USE', 'ADD', 'NEW', 'BOT', 'APP', 'API', 'GUI', 'LOG', 'RUN',
    'SHOW', 'HELP', 'GIVE', 'TELL', 'WHAT', 'WHEN', 'STEP', 'SETUP', 'WITH',
    'RISK', 'STOP', 'LOSS', 'FROM', 'THIS', 'THAT', 'DOES', 'HAVE', 'WILL',
    'BROKER', 'TRADE', 'ABOUT', 'WHICH', 'WHERE', 'THEIR', 'AFTER', 'FIRST',
    'SCHWAB', 'WEBULL', 'ALPACA', 'IBKR', 'ROBINHOOD', 'TASTYTRADE',
    'DISCORD', 'CHANNEL', 'SETTINGS', 'PAGE', 'CONFIGURE', 'CONNECT',
    'POSITION', 'ORDER', 'ENTRY', 'EXIT', 'PRICE', 'MODE', 'SIZE',
}

def _extract_symbol(query: str) -> str:
    """Extract a stock ticker symbol from a query if present."""
    import re
    words = re.findall(r'\b([A-Z]{1,5})\b', query.upper())
    for w in words:
        if w not in _NON_TICKER_WORDS and len(w) >= 2:
            return w
    return ""

def _is_channel_query(query: str) -> bool:
    """Check if query is about a channel's settings, not a stock trade."""
    q = query.lower()
    channel_kw = ["channel", "setting", "config", "sizing", "risk management",
                  "broker connected", "which broker", "position size", "setup"]
    return any(kw in q for kw in channel_kw)

def is_trade_query(query: str) -> bool:
    """Check if query is about trades — only when a real ticker symbol is detected."""
    if _is_channel_query(query):
        return False
    trade_keywords = ["trade history", "trade event", "what happened with", "show me trades",
                      "show trades", "give me trades", "pnl for", "p&l for",
                      "bto ", "stc ", "filled", "executed"]
    q = query.lower()
    if any(kw in q for kw in trade_keywords):
        return True
    sym = _extract_symbol(query)
    if sym:
        trade_context = ["history", "trade", "signal", "order", "position", "what happened",
                         "show", "give", "pnl", "p&l", "event", "buy", "sell", "entry", "exit"]
        if any(kw in q for kw in trade_context):
            return True
    return False


def is_log_query(query: str) -> bool:
    """Check if query is about logs or console."""
    log_keywords = ["log", "console", "output", "message", "what happened", 
                    "show me", "recent activity", "status"]
    return any(kw in query for kw in log_keywords)


def is_error_query(query: str) -> bool:
    """Check if query is about errors or issues."""
    error_keywords = ["error", "issue", "problem", "fail", "wrong", "not working",
                      "crash", "bug", "why did", "why didn't"]
    return any(kw in query for kw in error_keywords)


def analyze_trades(query: str) -> Dict:
    """Analyze trades and provide AI-powered insights with real bot state."""
    try:
        from . import database as db

        symbol = _extract_symbol(query)

        recent_trades = []
        symbol_trades = []
        try:
            conn = db.get_connection()
            cursor = conn.cursor()
            if symbol:
                cursor.execute("""
                    SELECT direction, symbol, asset_type, strike, expiry, call_put,
                           quantity, intended_price, executed_price, pnl, pnl_percent,
                           broker, status, executed_at, closed_at, stop_loss_price, profit_target_price
                    FROM trades WHERE UPPER(symbol) = ?
                    ORDER BY created_at DESC LIMIT 20
                """, (symbol.upper(),))
                symbol_trades = [dict(r) for r in cursor.fetchall()]
            cursor.execute("""
                SELECT direction, symbol, asset_type, quantity, executed_price, pnl, pnl_percent,
                       broker, status, executed_at
                FROM trades ORDER BY created_at DESC LIMIT 15
            """)
            recent_trades = [dict(r) for r in cursor.fetchall()]
        except Exception:
            pass

        open_positions = []
        try:
            open_positions = db.get_open_positions() or []
        except Exception:
            pass

        execution_lots_data = []
        execution_closures = []
        order_events_data = []
        signals_data = []
        if symbol:
            try:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT el.symbol, el.asset_type, el.strike, el.expiry, el.call_put,
                           el.original_qty, el.remaining_qty, el.fill_price, el.signal_price,
                           el.broker, el.status, el.order_filled_at, el.slippage_pct
                    FROM execution_lots el
                    WHERE UPPER(el.symbol) = ?
                    ORDER BY el.order_filled_at DESC LIMIT 15
                """, (symbol.upper(),))
                execution_lots_data = [dict(r) for r in cursor.fetchall()]

                cursor.execute("""
                    SELECT el.symbol, el.asset_type, el.strike, el.expiry, el.call_put,
                           ec.closed_qty, el.fill_price as entry_price, ec.fill_price as exit_price,
                           ec.pnl, ec.pnl_percent, ec.exit_source, ec.filled_at, ec.holding_days,
                           ec.broker
                    FROM execution_closures ec
                    JOIN execution_lots el ON ec.execution_lot_id = el.id
                    WHERE UPPER(el.symbol) = ?
                    ORDER BY ec.filled_at DESC LIMIT 15
                """, (symbol.upper(),))
                execution_closures = [dict(r) for r in cursor.fetchall()]
            except Exception:
                pass

            try:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT timestamp, event_type, symbol, broker, direction, asset_type,
                           quantity, price, status, reason, channel_name, severity, source
                    FROM order_events
                    WHERE UPPER(symbol) = ?
                    ORDER BY timestamp DESC LIMIT 20
                """, (symbol.upper(),))
                order_events_data = [dict(r) for r in cursor.fetchall()]
            except Exception:
                pass

            try:
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT direction, symbol, asset_type, strike, expiry, call_put,
                           quantity, price, author_name, received_at, executed,
                           execution_status, execution_reason
                    FROM signals
                    WHERE UPPER(symbol) = ?
                    ORDER BY received_at DESC LIMIT 10
                """, (symbol.upper(),))
                signals_data = [dict(r) for r in cursor.fetchall()]
            except Exception:
                pass

        conditional_orders = []
        try:
            conn = db.get_connection()
            cursor = conn.cursor()
            if symbol:
                cursor.execute("SELECT * FROM conditional_orders WHERE UPPER(symbol) = ? ORDER BY created_at DESC LIMIT 10", (symbol.upper(),))
            else:
                cursor.execute("SELECT * FROM conditional_orders ORDER BY created_at DESC LIMIT 10")
            conditional_orders = [dict(r) for r in cursor.fetchall()]
        except Exception:
            pass

        cond_text = "None"
        if conditional_orders:
            cond_lines = []
            for c in conditional_orders:
                status = c.get('status', 'unknown')
                sym = c.get('symbol', '?')
                trigger = c.get('trigger_price', 0)
                broker = c.get('broker', '?')
                created = c.get('created_at', '')
                sl = c.get('stop_loss', '')
                targets = c.get('profit_targets', '')
                cond_lines.append(f"  #{c.get('id','')} {sym} trigger=${trigger} broker={broker} status={status} SL={sl} targets={targets} created={created}")
            cond_text = "\n".join(cond_lines)

        log_context = ""
        q_lower = query.lower()
        needs_logs = any(kw in q_lower for kw in ['log', 'error', 'fail', 'why', 'issue', 'problem', 'what happened', 'not working'])
        if needs_logs:
            try:
                log_lines = _get_log_context(count=150)
                if symbol and log_lines:
                    symbol_lines = [l for l in log_lines.split('\n') if symbol.upper() in l.upper()]
                    if symbol_lines:
                        log_context = "\n".join(symbol_lines[-20:])
                else:
                    log_context = log_lines
            except Exception:
                pass

        symbol_trades_text = "None"
        if symbol_trades:
            lines = []
            for t in symbol_trades:
                d = t.get('direction', '?')
                qty = t.get('quantity', 0)
                ep = t.get('executed_price', 0)
                ip = t.get('intended_price', 0)
                pnl = t.get('pnl') or 0
                pnl_pct = t.get('pnl_percent') or 0
                brk = t.get('broker', '?')
                st = t.get('status', '?')
                at = (t.get('executed_at') or '')[:19]
                sl = t.get('stop_loss_price', '')
                pt = t.get('profit_target_price', '')
                asset = t.get('asset_type', 'stock')
                strike = t.get('strike', '')
                expiry = t.get('expiry', '')
                cp = t.get('call_put', '')
                opt_info = f" {strike}{cp} {expiry}" if asset == 'option' and strike else ""
                lines.append(f"  {at} | {d} {qty} {symbol}{opt_info} @ ${ep or ip} | broker={brk} status={st} P&L=${float(pnl):+.2f} ({float(pnl_pct):+.1f}%) SL={sl} PT={pt}")
            symbol_trades_text = "\n".join(lines)

        lots_text = "None"
        if execution_lots_data:
            lines = []
            for lot in execution_lots_data:
                asset = lot.get('asset_type', 'stock')
                opt_info = ""
                if asset == 'option':
                    opt_info = f" ${lot.get('strike','')}{lot.get('call_put','')} {lot.get('expiry','')}"
                slip = f" slippage={lot.get('slippage_pct',0):.1f}%" if lot.get('slippage_pct') else ""
                lines.append(f"  {(lot.get('order_filled_at') or '')[:19]} | BUY {lot.get('original_qty',0)} {lot.get('symbol','?')}{opt_info} ({asset}) @ ${lot.get('fill_price',0):.2f} (signal=${lot.get('signal_price',0):.2f}) | broker={lot.get('broker','?')} status={lot.get('status','?')} remaining={lot.get('remaining_qty',0)}{slip}")
            lots_text = "\n".join(lines)

        closure_text = "None"
        if execution_closures:
            lines = []
            for c in execution_closures:
                asset = c.get('asset_type', 'stock')
                opt_info = ""
                if asset == 'option':
                    opt_info = f" ${c.get('strike','')}{c.get('call_put','')} {c.get('expiry','')}"
                hold = f" held={c.get('holding_days',0):.1f}d" if c.get('holding_days') else ""
                lines.append(f"  {(c.get('filled_at') or '')[:19]} | EXIT {c.get('closed_qty',0)} {c.get('symbol','?')}{opt_info} ({asset}) entry=${float(c.get('entry_price') or 0):.2f} exit=${float(c.get('exit_price') or 0):.2f} | P&L=${float(c.get('pnl') or 0):+.2f} ({float(c.get('pnl_percent') or 0):+.1f}%) via {c.get('exit_source','?')} on {c.get('broker','?')}{hold}")
            closure_text = "\n".join(lines)

        events_text = "None"
        if order_events_data:
            lines = []
            for ev in order_events_data:
                ts = (ev.get('timestamp') or '')[:19]
                etype = ev.get('event_type', '?')
                sev = ev.get('severity', 'info')
                d = ev.get('direction', '')
                asset = ev.get('asset_type', '')
                qty = ev.get('quantity', '')
                price = ev.get('price', '')
                brk = ev.get('broker', '')
                status = ev.get('status', '')
                reason = ev.get('reason', '')
                ch = ev.get('channel_name', '')
                price_str = f" @ ${price}" if price else ""
                reason_str = f" | reason: {reason}" if reason else ""
                lines.append(f"  {ts} [{sev.upper()}] {etype}: {d} {qty} {symbol} ({asset}){price_str} | {brk} {status}{reason_str} [ch: {ch}]")
            events_text = "\n".join(lines)

        signals_text = "None"
        if signals_data:
            lines = []
            for sig in signals_data:
                d = sig.get('direction', '?')
                asset = sig.get('asset_type', 'stock')
                qty = sig.get('quantity', '')
                price = sig.get('price', 0) or 0
                author = sig.get('author_name', '')
                received = (sig.get('received_at') or '')[:19]
                executed = 'Yes' if sig.get('executed') else 'No'
                exec_status = sig.get('execution_status', '')
                exec_reason = sig.get('execution_reason', '')
                opt_info = ""
                if asset == 'option':
                    opt_info = f" ${sig.get('strike','')}{sig.get('call_put','')} {sig.get('expiry','')}"
                reason_str = f" | {exec_reason}" if exec_reason else ""
                lines.append(f"  {received} | {d} {qty} {symbol}{opt_info} ({asset}) @ ${price:.2f} | from: {author} | executed={executed} status={exec_status}{reason_str}")
            signals_text = "\n".join(lines)

        context_sections = [
            f"COMPLETE TRADE DATA FOR: {symbol or 'ALL'}",
            f"1. SIGNALS RECEIVED:\n{signals_text}",
            f"2. ORDER EVENTS:\n{events_text}",
            f"3. TRADE RECORDS:\n{symbol_trades_text}",
            f"4. EXECUTION ENTRIES:\n{lots_text}",
            f"5. EXECUTION EXITS:\n{closure_text}",
            f"6. CONDITIONAL ORDERS:\n{cond_text}",
        ]
        if not symbol:
            context_sections.append(f"7. RECENT TRADES (all symbols, last 15):\n{_format_trades(recent_trades)}")
        context_sections.append(f"OPEN POSITIONS:\n{_format_positions(open_positions)}")
        if log_context:
            context_sections.append(f"CONSOLE LOGS:\n{log_context}")
        context = "\n\n".join(context_sections)

        ai_response = _call_ai(query, context, "trade_analysis")

        if ai_response:
            return {
                "success": True,
                "response": ai_response,
                "topic": "trade_analysis",
                "ai_powered": True
            }
        else:
            summary = _generate_trade_summary(recent_trades, open_positions)
            return {
                "success": True,
                "response": summary,
                "topic": "trade_summary"
            }

    except Exception as e:
        print(f"[CHAT] Trade analysis error: {e}")
        return {
            "success": True,
            "response": "I couldn't retrieve trade data. Please check that your broker is connected in Settings.",
            "topic": "error"
        }


def analyze_logs(query: str) -> Dict:
    """Analyze console logs and provide insights."""
    try:
        log_context = _get_log_context(count=100)
        summary = _get_log_summary()
        
        ai_response = _call_openai(query, f"Log Summary:\n{summary}\n\nRecent Logs:\n{log_context}", "log_analysis")
        
        if ai_response:
            return {
                "success": True,
                "response": ai_response,
                "topic": "log_analysis",
                "ai_powered": True
            }
        else:
            return {
                "success": True,
                "response": f"**Recent Activity Summary**\n\n{summary}\n\n**Recent Logs:**\n```\n{log_context[:1500]}...\n```",
                "topic": "log_summary"
            }
            
    except Exception as e:
        print(f"[CHAT] Log analysis error: {e}")
        return {
            "success": True,
            "response": "I couldn't access the log monitor. Logs are being captured in the background.",
            "topic": "error"
        }


def analyze_errors(query: str) -> Dict:
    """Analyze errors and provide troubleshooting help."""
    try:
        error_context = get_error_context()
        log_context = _get_log_context(category="error", count=30)
        
        context = f"""Error Summary:
- Total errors (24h): {error_context.get('error_count', 0)}
- Critical errors: {error_context.get('critical_count', 0)}

Recent Error Logs:
{log_context}

Recent Errors from Database:
{_format_errors(error_context.get('recent_errors', []))}
"""
        
        ai_response = _call_openai(query, context, "error_analysis")
        
        if ai_response:
            return {
                "success": True,
                "response": ai_response,
                "topic": "error_analysis",
                "ai_powered": True,
                "has_errors": error_context.get('has_errors', False)
            }
        else:
            if error_context.get('has_errors'):
                return {
                    "success": True,
                    "response": f"**{error_context['error_count']} errors detected in the last 24 hours.**\n\nMost common issues:\n{_format_errors(error_context.get('recent_errors', [])[:5])}",
                    "topic": "error_summary",
                    "has_errors": True
                }
            else:
                return {
                    "success": True,
                    "response": "No errors detected in the last 24 hours. Your bot is running smoothly!",
                    "topic": "no_errors"
                }
                
    except Exception as e:
        print(f"[CHAT] Error analysis error: {e}")
        return get_contextual_response(query)


def _get_log_context(count: int = 50, category: Optional[str] = None) -> str:
    """Get recent logs formatted for AI context."""
    try:
        from src.log_monitor import get_log_monitor
        monitor = get_log_monitor()
        
        if category:
            logs = monitor.get_recent_logs(count=count, category=category)
        else:
            logs = monitor.get_recent_logs(count=count)
        
        return monitor.format_for_ai(logs)
    except Exception as e:
        return f"Log monitor not available: {e}"


def _get_log_summary() -> str:
    """Get a summary of log activity."""
    try:
        from src.log_monitor import get_log_monitor
        monitor = get_log_monitor()
        summary = monitor.get_summary()
        
        lines = [
            f"Total logs captured: {summary['total_logs']}",
            f"Errors: {summary['error_count']}",
            f"Warnings: {summary['warning_count']}",
            f"Trade-related: {summary['trade_count']}",
        ]
        
        if summary.get('categories'):
            lines.append("\nBy category:")
            for cat, count in sorted(summary['categories'].items(), key=lambda x: -x[1])[:5]:
                lines.append(f"  - {cat}: {count}")
        
        return "\n".join(lines)
    except Exception as e:
        return f"Summary not available: {e}"


def _format_trades(trades: List[Dict]) -> str:
    """Format trades for display."""
    if not trades:
        return "No recent trades found."

    lines = []
    for t in trades[:15]:
        symbol = t.get('symbol', '?')
        action = t.get('direction', t.get('action', t.get('side', '?')))
        qty = t.get('quantity', t.get('qty', 0))
        price = t.get('executed_price', t.get('price', t.get('fill_price', 0))) or 0
        intended = t.get('intended_price', 0) or 0
        pnl = t.get('pnl', 0) or 0
        pnl_pct = t.get('pnl_percent', 0) or 0
        broker = t.get('broker', '')
        status = t.get('status', '')
        asset = t.get('asset_type', 'stock')
        time_str = (t.get('executed_at') or t.get('filled_at') or t.get('created_at') or '')[:19]
        opt_info = ""
        if asset == 'option':
            strike = t.get('strike', '')
            cp = t.get('call_put', '')
            expiry = t.get('expiry', '')
            if strike:
                opt_info = f" ${strike}{cp} {expiry}"
        price_str = f"${price:.2f}" if price else f"${intended:.2f}(intended)"
        lines.append(f"  {time_str} | {action} {qty} {symbol}{opt_info} ({asset}) @ {price_str} | {broker} {status} P&L=${float(pnl):+.2f} ({float(pnl_pct):+.1f}%)")

    return "\n".join(lines) if lines else "No trades to display."


def _format_positions(positions: List[Dict]) -> str:
    """Format positions for display."""
    if not positions:
        return "No open positions."

    lines = []
    for p in positions:
        symbol = p.get('symbol', '?')
        qty = p.get('quantity', p.get('qty', 0))
        pnl = p.get('unrealized_pnl', p.get('pnl', 0)) or 0
        asset = p.get('asset_type', 'stock')
        broker = p.get('broker', '')
        avg_cost = p.get('avg_cost', p.get('average_price', 0)) or 0
        opt_info = ""
        if asset == 'option':
            opt_info = f" ${p.get('strike','')}{p.get('call_put','')} {p.get('expiry','')}"
        lines.append(f"  {symbol}{opt_info} ({asset}): {qty} @ ${float(avg_cost):.2f} | P&L: ${float(pnl):+.2f} | {broker}")

    return "\n".join(lines) if lines else "No positions."


def _format_errors(errors: List[Dict]) -> str:
    """Format errors for display."""
    if not errors:
        return "No errors found."
    
    lines = []
    for e in errors:
        error_type = e.get('error_type', 'Unknown')
        message = e.get('error_message', '')[:100]
        count = e.get('occurrence_count', 1)
        lines.append(f"  - [{error_type}] {message} (x{count})")
    
    return "\n".join(lines) if lines else "No errors."


def _generate_trade_summary(trades: List[Dict], positions: List[Dict]) -> str:
    """Generate a text summary of trading activity."""
    parts = ["**Trading Summary**\n"]
    
    if trades:
        parts.append(f"**Recent Trades ({len(trades)} total):**")
        parts.append(_format_trades(trades[:5]))
    else:
        parts.append("No recent trades found.")
    
    parts.append("")
    
    if positions:
        parts.append(f"**Open Positions ({len(positions)} total):**")
        parts.append(_format_positions(positions))
    else:
        parts.append("No open positions.")
    
    return "\n".join(parts)


_chat_ai_cache = {'client': None, 'provider': None, 'is_anthropic': False, 'is_gemini': False, 'model': None}

from gui_app.config_service import (
    AI_PROVIDER_DEFAULT_MODELS as _PROVIDER_DEFAULT_MODELS,
    AI_PROVIDER_MODEL_PREFIXES as _PROVIDER_MODEL_PREFIXES,
)

def _get_model_for_provider(provider: str) -> str:
    """Read model from ai_settings DB; validate it belongs to provider, else fall back to default."""
    try:
        from . import database as _db
        settings = _db.get_ai_settings()
        model = settings.get('model', '')
        if model:
            prefixes = _PROVIDER_MODEL_PREFIXES.get(provider, ())
            if any(model.startswith(p) for p in prefixes):
                return model
    except Exception:
        pass
    return _PROVIDER_DEFAULT_MODELS.get(provider, 'gpt-4o-mini')


def _get_ai_client():
    """Get AI client based on provider preference. Supports OpenAI, Claude, Replit AI.
    Returns (client, is_anthropic, model) or (None, False, None) if disabled.
    """
    import os

    try:
        from .config_service import get_ai_provider, load_config
        provider = get_ai_provider()

        _cur_model = _get_model_for_provider(provider)
        if (provider == _chat_ai_cache.get('provider') and _chat_ai_cache.get('client')
                and _cur_model == _chat_ai_cache.get('model')):
            return _chat_ai_cache['client'], _chat_ai_cache['is_anthropic'], _chat_ai_cache['model']

        if provider == 'disabled':
            return None, False, None

        if provider == 'claude':
            try:
                from anthropic import Anthropic
            except ImportError:
                print("[CHAT] Anthropic SDK not installed")
                return None, False, None
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if not api_key:
                try:
                    from .broker_credentials_service import get_api_keys_extended
                    keys = get_api_keys_extended()
                    api_key = keys.get('anthropic', '')
                except Exception:
                    pass
            if not api_key:
                try:
                    from .config_service import load_config
                    api_keys = load_config('api_keys') or {}
                    api_key = api_keys.get('anthropic', '')
                except Exception:
                    pass
            if not api_key:
                print("[CHAT] Anthropic API key not configured")
                return None, False, None
            client = Anthropic(api_key=api_key)
            model = _get_model_for_provider('claude')
            _chat_ai_cache.update({'client': client, 'provider': provider, 'is_anthropic': True, 'is_gemini': False, 'model': model})
            print(f"[CHAT] Using Claude (model={model})")
            return client, True, model

        if provider == 'gemini':
            try:
                from google import genai as _genai
            except ImportError:
                import sys
                print(f"[CHAT] Google GenAI SDK not installed — run: {sys.executable} -m pip install google-genai")
                return None, False, None
            api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
            if not api_key:
                try:
                    from .broker_credentials_service import get_api_keys_extended
                    keys = get_api_keys_extended()
                    api_key = keys.get('gemini', '')
                except Exception as e:
                    print(f"[CHAT] Gemini key lookup via credentials service failed: {e}")
            if not api_key:
                try:
                    from .config_service import load_config
                    api_keys = load_config('api_keys') or {}
                    api_key = api_keys.get('gemini', '')
                except Exception:
                    pass
            if not api_key:
                print("[CHAT] Gemini API key not configured (checked env, credentials service, config)")
                return None, False, None
            client = _genai.Client(api_key=api_key)
            model = _get_model_for_provider('gemini')
            _chat_ai_cache.update({'client': client, 'provider': provider, 'is_anthropic': False, 'model': model, 'is_gemini': True})
            print(f"[CHAT] Using Gemini (model={model})")
            return client, False, model

        # provider == 'openai'
        try:
            from openai import OpenAI
        except ImportError:
            return None, False, None
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            try:
                api_keys = load_config('api_keys')
                if api_keys and api_keys.get('openai'):
                    api_key = api_keys['openai']
            except Exception:
                pass
        if not api_key:
            try:
                from .broker_credentials_service import get_api_keys_extended
                keys = get_api_keys_extended()
                api_key = keys.get('openai', '')
            except Exception:
                pass
        if not api_key:
            print("[CHAT] OpenAI API key not configured")
            return None, False, None
        client = OpenAI(api_key=api_key)
        model = _get_model_for_provider('openai')
        _chat_ai_cache.update({'client': client, 'provider': provider, 'is_anthropic': False, 'is_gemini': False, 'model': model})
        print("[CHAT] Using OpenAI")
        return client, False, model

    except Exception as e:
        print(f"[CHAT] AI client init failed: {e}")
        return None, False, None


def _get_openai_client():
    """Legacy wrapper — returns client or None."""
    client, _, _ = _get_ai_client()
    return client


def is_ai_available() -> bool:
    """Check if any AI provider is available."""
    client, _, _ = _get_ai_client()
    return client is not None


def analyze_uploaded_log(log_content: str, query: str = "") -> Dict:
    """Analyze an uploaded log file for entries, exits, rejections, failures, etc."""
    try:
        if not log_content or not log_content.strip():
            return {
                "success": True,
                "response": "The uploaded log file appears to be empty. Please upload a file with log content.",
                "topic": "log_upload"
            }

        lines = log_content.strip().split('\n')
        total_lines = len(lines)

        entry_lines = []
        exit_lines = []
        error_lines = []
        reject_lines = []
        risk_lines = []
        signal_lines = []
        order_lines = []

        entry_kw = ['BTO', 'ENTRY', 'BUYING', 'BOUGHT', 'BUY_TO_OPEN', 'OPENING POSITION', 'ENTRY SIGNAL']
        exit_kw = ['STC', 'EXIT', 'SELLING', 'SOLD', 'SELL_TO_CLOSE', 'CLOSING POSITION', 'EXIT SIGNAL']
        error_kw = ['ERROR', 'FAILED', 'FAILURE', 'EXCEPTION', 'TRACEBACK', 'CRITICAL']
        reject_kw = ['REJECT', 'REJECTED', 'DENIED', 'BLOCKED', 'SKIPPED', 'IGNORED', 'INSUFFICIENT', 'INVALID']
        risk_kw = ['STOP LOSS', 'PROFIT TARGET', 'TRAILING', 'PT1', 'PT2', 'PT3', 'PT4', 'GIVEBACK', 'CIRCUIT BREAKER', 'RISK']
        signal_kw = ['SIGNAL', 'PARSED', 'DETECTED', 'PATTERN', 'FORMAT']
        order_kw = ['ORDER', 'FILLED', 'PENDING', 'CANCELLED', 'CANCELED', 'PLACED', 'SUBMITTED']

        for i, line in enumerate(lines):
            upper = line.upper()
            if any(kw in upper for kw in entry_kw):
                entry_lines.append((i + 1, line.strip()))
            if any(kw in upper for kw in exit_kw):
                exit_lines.append((i + 1, line.strip()))
            if any(kw in upper for kw in error_kw):
                error_lines.append((i + 1, line.strip()))
            if any(kw in upper for kw in reject_kw):
                reject_lines.append((i + 1, line.strip()))
            if any(kw in upper for kw in risk_kw):
                risk_lines.append((i + 1, line.strip()))
            if any(kw in upper for kw in signal_kw):
                signal_lines.append((i + 1, line.strip()))
            if any(kw in upper for kw in order_kw):
                order_lines.append((i + 1, line.strip()))

        summary_parts = [
            f"**Log File Analysis** ({total_lines} lines)\n",
            f"- Entries (BTO): **{len(entry_lines)}**",
            f"- Exits (STC): **{len(exit_lines)}**",
            f"- Orders: **{len(order_lines)}**",
            f"- Signals: **{len(signal_lines)}**",
            f"- Risk Events: **{len(risk_lines)}**",
            f"- Errors/Failures: **{len(error_lines)}**",
            f"- Rejections/Skips: **{len(reject_lines)}**",
        ]

        max_context_chars = 12000
        context_parts = []

        if error_lines:
            context_parts.append("=== ERRORS/FAILURES ===")
            for ln, txt in error_lines[:30]:
                context_parts.append(f"L{ln}: {txt[:300]}")

        if reject_lines:
            context_parts.append("\n=== REJECTIONS/SKIPS ===")
            for ln, txt in reject_lines[:20]:
                context_parts.append(f"L{ln}: {txt[:300]}")

        if entry_lines:
            context_parts.append("\n=== ENTRIES (BTO) ===")
            for ln, txt in entry_lines[:25]:
                context_parts.append(f"L{ln}: {txt[:300]}")

        if exit_lines:
            context_parts.append("\n=== EXITS (STC) ===")
            for ln, txt in exit_lines[:25]:
                context_parts.append(f"L{ln}: {txt[:300]}")

        if risk_lines:
            context_parts.append("\n=== RISK EVENTS ===")
            for ln, txt in risk_lines[:20]:
                context_parts.append(f"L{ln}: {txt[:300]}")

        if order_lines:
            context_parts.append("\n=== ORDER ACTIVITY ===")
            for ln, txt in order_lines[:20]:
                context_parts.append(f"L{ln}: {txt[:300]}")

        context = '\n'.join(context_parts)
        if len(context) > max_context_chars:
            context = context[:max_context_chars] + "\n... (truncated)"

        user_query = query.strip() if query.strip() else "Analyze this log file. Summarize all entries, exits, rejections, failures, and errors. Highlight anything unusual or problematic."

        ai_response = _call_openai(user_query, context, "log_upload")

        if ai_response:
            return {
                "success": True,
                "response": ai_response,
                "topic": "log_upload",
                "ai_powered": True,
                "stats": {
                    "total_lines": total_lines,
                    "entries": len(entry_lines),
                    "exits": len(exit_lines),
                    "errors": len(error_lines),
                    "rejections": len(reject_lines),
                    "risk_events": len(risk_lines),
                    "orders": len(order_lines),
                    "signals": len(signal_lines)
                }
            }
        else:
            summary = '\n'.join(summary_parts)
            if error_lines:
                summary += "\n\n**Recent Errors:**\n"
                for ln, txt in error_lines[:10]:
                    summary += f"- Line {ln}: `{txt[:150]}`\n"
            if reject_lines:
                summary += "\n**Rejections:**\n"
                for ln, txt in reject_lines[:10]:
                    summary += f"- Line {ln}: `{txt[:150]}`\n"
            if not error_lines and not reject_lines:
                summary += "\n\nNo errors or rejections found in the log file."

            return {
                "success": True,
                "response": summary,
                "topic": "log_upload",
                "stats": {
                    "total_lines": total_lines,
                    "entries": len(entry_lines),
                    "exits": len(exit_lines),
                    "errors": len(error_lines),
                    "rejections": len(reject_lines)
                }
            }

    except Exception as e:
        print(f"[CHAT] Log upload analysis error: {e}")
        return {
            "success": True,
            "response": f"Error analyzing log file: {str(e)}. Please try a smaller file or paste the relevant section.",
            "topic": "error"
        }


def _get_trade_context_for_symbol(symbol: str) -> str:
    """Build trade history + order events context for a symbol to pass to AI."""
    parts = []
    try:
        from . import database as db
        trades = db.get_trades(limit=200)
        if trades:
            symbol_trades = [t for t in trades if symbol.upper() in (t.get('symbol', '') or '').upper()]
            if symbol_trades:
                symbol_trades.sort(key=lambda t: t.get('executed_at') or t.get('filled_at') or t.get('created_at') or '0')
                recent = symbol_trades[-10:]
                lines = [f"TRADE HISTORY FOR {symbol} ({len(symbol_trades)} total, showing last {len(recent)}):"]
                for t in recent:
                    action = t.get('action', t.get('side', '?'))
                    qty = t.get('quantity', t.get('qty', 0))
                    price = t.get('price', t.get('fill_price', 0))
                    status = t.get('status', '')
                    broker = t.get('broker', '')
                    ts = t.get('executed_at') or t.get('filled_at') or t.get('created_at') or ''
                    channel = t.get('channel_name', '')
                    pnl = t.get('pnl', '')
                    pnl_pct = t.get('pnl_percent', t.get('pnl_pct', ''))
                    line = f"  {ts} | {action} x{qty} @ ${price} | {status} | {broker}"
                    if channel:
                        line += f" | ch:{channel}"
                    if pnl:
                        line += f" | pnl:${pnl}"
                    if pnl_pct:
                        line += f" ({pnl_pct}%)"
                    lines.append(line)
                parts.append("\n".join(lines))
    except Exception:
        pass

    try:
        from . import database as db
        import sqlite3
        conn = sqlite3.connect(db.DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT timestamp, event_type, symbol, broker, direction, price, quantity, reason, status FROM order_events WHERE UPPER(symbol)=? ORDER BY id DESC LIMIT 10", (symbol.upper(),))
        events = cur.fetchall()
        conn.close()
        if events:
            lines = [f"ORDER EVENTS FOR {symbol} (last {len(events)}):"]
            for e in reversed(list(events)):
                d = dict(e)
                reason = (d.get('reason') or '')[:150]
                line = f"  {d.get('timestamp','')} | {d.get('event_type','')} | {d.get('direction','')} x{d.get('quantity','')} @ ${d.get('price','')} | {d.get('broker','')}"
                if reason:
                    line += f" | {reason}"
                lines.append(line)
            parts.append("\n".join(lines))
    except Exception:
        pass

    return "\n\n".join(parts)


def _get_bot_status_context() -> str:
    """Get real-time bot status — channels, brokers, settings — for AI context."""
    try:
        from . import database as db
        lines = []

        try:
            channels = db.get_channels()
            exec_channels = [c for c in channels if c.get('execute_enabled')]
            track_channels = [c for c in channels if c.get('track_enabled')]
            lines.append(f"Channels: {len(channels)} total, {len(exec_channels)} execution, {len(track_channels)} tracking")
            for ch in channels:
                name = ch.get('name', '?')
                disc_id = ch.get('discord_channel_id', '')
                exe = 'Execute' if ch.get('execute_enabled') else ''
                trk = 'Track' if ch.get('track_enabled') else ''
                mode = '+'.join(filter(None, [exe, trk])) or 'Disabled'
                broker = ch.get('enabled_brokers', '') or ch.get('broker_override', '') or 'Not assigned'
                pos_size = ch.get('position_size_pct', 0) or 0
                default_qty = ch.get('default_quantity', '') or ''
                risk_enabled = 'Yes' if ch.get('risk_management_enabled') else 'No'
                pt1 = ch.get('profit_target_1_pct', 0) or 0
                sl = ch.get('stop_loss_pct', 0) or 0
                trail = ch.get('trailing_stop_pct', 0) or 0
                trail_act = ch.get('trailing_activation_pct', 0) or 0
                paper = 'Yes' if ch.get('paper_trade_enabled') else 'No'
                entry_mode = ch.get('entry_order_mode', 'limit')
                exit_mode = ch.get('exit_strategy_mode', 'hybrid')
                cond_enabled = 'Yes' if ch.get('conditional_orders_enabled') else 'No'
                max_pos = ch.get('max_positions', 0) or 0
                lines.append(
                    f"  - {name} (ID:{disc_id}) [{mode}] broker={broker} | "
                    f"position_size={pos_size}% default_qty={default_qty} | "
                    f"risk={risk_enabled} PT1={pt1}% SL={sl}% trail={trail}% trail_act={trail_act}% | "
                    f"paper={paper} entry_mode={entry_mode} exit_mode={exit_mode} conditional={cond_enabled} max_positions={max_pos}"
                )
        except Exception:
            pass

        try:
            from .config_service import get_ai_provider
            lines.append(f"AI Provider: {get_ai_provider()}")
        except Exception:
            pass

        try:
            risk = db.get_global_risk_settings() if hasattr(db, 'get_global_risk_settings') else {}
            if risk:
                enabled = 'Enabled' if risk.get('enabled') else 'Disabled'
                lines.append(f"Global Risk: {enabled}, PT={risk.get('profit_target_percent',0)}%, SL={risk.get('stop_loss_percent',0)}%, Trail={risk.get('trailing_stop_percent',0)}%")
        except Exception:
            pass

        try:
            settings = db.get_trading_settings() if hasattr(db, 'get_trading_settings') else {}
            if settings:
                lines.append(f"Max Position: ${settings.get('max_position_size',0)}, Default Qty: {settings.get('global_default_quantity',1)}")
        except Exception:
            pass

        return "\n".join(lines) if lines else ""
    except Exception:
        return ""


def _build_bot_knowledge_prompt() -> str:
    """Build comprehensive system prompt from KB so AI knows everything about the bot."""
    sections = []
    priority_topics = [
        'getting_started', 'brokers', 'channels', 'settings_discord',
        'execution_mode', 'position_sizing', 'risk_management',
        'profit_targets', 'stop_loss_settings', 'trailing_stop',
        'conditional_orders', 'options_trading', 'broker_override',
        'entry_order_mode', 'order_chasing', 'ticker_filter',
        'notifications', 'troubleshooting', 'signal_formats',
        'circuit_breaker', 'leave_runner', 'dynamic_sl_escalation',
        'early_trailing_stop', 'giveback_guard', 'simulation',
        'event_tracking', 'pnl_tracker', 'fifo_matching',
    ]
    for tid in priority_topics:
        if tid in KNOWLEDGE_BASE:
            t = KNOWLEDGE_BASE[tid]
            sections.append(f"### {t['title']}\n{t['content']}")
    return "\n\n".join(sections)

_BOT_KNOWLEDGE = None

def _get_bot_knowledge() -> str:
    global _BOT_KNOWLEDGE
    if _BOT_KNOWLEDGE is None:
        _BOT_KNOWLEDGE = _build_bot_knowledge_prompt()
    return _BOT_KNOWLEDGE

_CHAT_SYSTEM_PROMPTS = {
    "trade_analysis": """Answer ONLY about the specific symbol the user asked about. IGNORE all other symbols in the data.
Use ONLY the real trade records and order events provided — never fabricate data.
When explaining what happened with a trade:
- Show the timeline: when it was placed, filled, closed, and why
- Include entry price, exit price, P&L, broker, and any failure reasons from order events
- If the trade failed, explain WHY from the order event reason field
- If it was a conditional order, explain the trigger logic
Do NOT show other symbols' data. Do NOT add warnings or troubleshooting unless asked.
If no data exists for the symbol, say "No trade history found for [SYMBOL]" and stop.""",

    "log_analysis": """You are a technical assistant for BotifyTrades, a Discord trading bot.
Analyze the console logs and activity to answer the user's question.
Identify any issues, patterns, or important events.
Be concise and highlight the most relevant information.""",

    "error_analysis": """You are a troubleshooting assistant for BotifyTrades, a Discord trading bot.
Analyze the errors and issues to help the user understand what went wrong.
Provide clear explanations and suggest solutions when possible.
Be empathetic - users are often frustrated when things don't work.""",

    "log_upload": """You are a log file debugger for BotifyTrades, a Discord trading bot that automates stock and options trading.
The user has uploaded a log file. Analyze it thoroughly and answer their question.
Focus on:
- Trade entries (BTO) and exits (STC) - were they successful? What symbols/prices?
- Rejections and skipped signals - WHY were they rejected?
- Errors and failures - broker connection issues, order placement failures, API errors
- Risk management events - stop loss triggers, profit target hits, trailing stops
- Signal parsing - were signals detected and parsed correctly?
- Order flow - was the order placed, filled, or cancelled?
Provide a clear summary with specific line references. Highlight problems and suggest fixes.
Use markdown formatting for readability.""",

    "signal_test": """You are a signal parser for BotifyTrades. The user wants to test if a trading signal will be recognized.
Analyze the signal text and determine:
1. Is this a valid trading signal? (BTO/STC entry or exit)
2. What format does it match? (structured emoji, natural language, options, etc.)
3. What fields can be extracted? (symbol, price, action, targets, stop loss)
4. Is this a conditional order (break/trigger) or immediate entry?
Be specific about what was parsed and what might be missing.""",
}

def _get_system_prompt(analysis_type: str) -> str:
    bot_kb = _get_bot_knowledge()
    task_prompt = _CHAT_SYSTEM_PROMPTS.get(analysis_type, '')

    return f"""You are a knowledgeable assistant for BotifyTrades, a multi-broker automated trading bot.
You know EVERYTHING about this bot — setup, configuration, brokers, channels, risk management, and all features.
BotifyTrades monitors Discord channels for trading signals and executes trades on Schwab, Webull, Alpaca, IBKR, Tastytrade, and Robinhood.

{('TASK: ' + task_prompt) if task_prompt else ''}

COMPLETE BOT DOCUMENTATION:
{bot_kb}

STRICT RULES:
- ONLY answer what the user asked — nothing more
- When asked about a specific symbol/ticker, ONLY show data for THAT symbol — ignore everything else
- Do NOT add warnings, disclaimers, system errors, or unrelated information
- Do NOT mention broker connection issues, encryption errors, or system status unless the user specifically asked
- Do NOT hallucinate or guess — if data is not in the context provided, say "No data found" and stop
- When showing trade data, use ONLY the real records provided — never fabricate trades
- Keep responses SHORT and DIRECT — 2-5 sentences for simple questions, bullet points for complex ones
- Use markdown formatting for readability
- Do NOT suggest fixes or troubleshooting unless the user asked for help
- Do NOT dump all data — be selective and relevant to the question
- Do NOT make up features that don't exist in the documentation above"""


def _call_ai(query: str, context: str, analysis_type: str) -> Optional[str]:
    """Call AI provider (Claude, OpenAI, or Gemini) to analyze context and answer query."""
    try:
        client, is_anthropic, model = _get_ai_client()
        if not client:
            return None

        system_prompt = _get_system_prompt(analysis_type)
        user_content = f"Context:\n{context}\n\nUser Question: {query}" if context else query

        is_gemini = _chat_ai_cache.get('is_gemini', False)

        if is_gemini:
            response = client.models.generate_content(
                model=model,
                contents=f"{system_prompt}\n\n{user_content}"
            )
            return response.text
        elif is_anthropic:
            response = client.messages.create(
                model=model,
                max_tokens=600,
                temperature=0.5,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}]
            )
            return response.content[0].text
        else:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                max_tokens=600
            )
            return response.choices[0].message.content

    except Exception as e:
        try:
            print(f"[CHAT] AI call failed ({analysis_type}): {e}")
        except UnicodeEncodeError:
            print(f"[CHAT] AI call failed ({analysis_type}): {type(e).__name__}")
        return None


def _call_openai(query: str, context: str, analysis_type: str) -> Optional[str]:
    """Legacy wrapper — routes to provider-aware _call_ai."""
    return _call_ai(query, context, analysis_type)


def get_general_ai_response(query: str) -> Optional[str]:
    """Get a general AI response for questions not in knowledge base."""
    return _call_ai(query, "", "general")
