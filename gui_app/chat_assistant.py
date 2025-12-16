"""
BotifyTrades AI Chat Assistant
Smart FAQ + Intent-Based Help System with Error Monitoring
"""
import re
from typing import Dict, List, Tuple, Optional
from difflib import SequenceMatcher
from datetime import datetime

KNOWLEDGE_BASE = {
    "getting_started": {
        "keywords": ["start", "begin", "setup", "first time", "new user", "how to use", "getting started", "introduction", "guide"],
        "title": "Getting Started with BotifyTrades",
        "content": """Welcome to BotifyTrades! Here's how to get started:

**Step 1: Setup Your Account**
When you first access BotifyTrades, you'll be guided through a setup wizard to create your admin account with a username, email, and secure password.

**Step 2: Configure Your Broker**
Go to Settings and connect at least one broker:
• **Alpaca** - Great for paper trading (testing)
• **Webull** - Popular for options trading
• **Interactive Brokers** - For professional traders

**Step 3: Add Discord Channels**
Go to Channels page and add Discord channels to monitor:
• **Execution Channels** - Bot will automatically execute trades
• **Tracking Channels** - Bot will track signals without executing

**Step 4: Configure Risk Management**
Set your profit targets, stop losses, and position sizing in Settings or per-channel.

You're all set! The bot will now monitor your channels and execute/track trades automatically."""
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
        "keywords": ["channel", "channels", "discord channel", "add channel", "execution", "tracking", "monitor", "configure channel"],
        "title": "Channel Configuration",
        "content": """Channels are Discord channels the bot monitors for trading signals:

**Two Types of Channels:**
1. **Execution Channels** (⚡) - Bot automatically executes trades from signals
2. **Tracking Channels** (📡) - Bot tracks signals for P&L without executing

**Adding a Channel:**
1. Get the Discord Channel ID (Right-click channel → Copy ID)
2. Go to Channels page
3. Enter Channel ID and a friendly name
4. Toggle "Execute" and/or "Track" modes
5. Click Add Channel

**Channel Features:**
• **Dual-Mode** - A channel can be both Execute AND Track simultaneously
• **Broker Override** - Assign specific broker per channel
• **Multi-Broker** - Execute on multiple brokers at once
• **Allowed Users** - Filter signals by specific Discord users only

**Per-Channel Risk Management:**
Each channel can have custom settings:
• 3-Tier Profit Targets (e.g., sell 33% at +20%, +40%, +60%)
• Stop Loss percentage
• Trailing Stop with activation threshold
• Position Size (% of portfolio)

**Reset Tracking** - Clears all signals/lots/closures for that channel to start fresh."""
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
        "keywords": ["risk", "stop loss", "profit target", "trailing stop", "position size", "risk management", "tiered", "protect"],
        "title": "Risk Management",
        "content": """BotifyTrades offers comprehensive risk management:

**Global Settings (in Settings page)**
• Enable/Disable monitoring
• Default Profit Target %
• Default Stop Loss %
• Default Trailing Stop %

**Per-Channel Overrides**
Each channel can have custom risk settings:

**3-Tier Profit Targets:**
• Tier 1: Sell X% at Y% profit
• Tier 2: Sell X% at Y% profit  
• Tier 3: Sell X% at Y% profit
Example: Sell 33% at +20%, 33% at +40%, 34% at +60%

**Stop Loss:**
Automatically sell if position drops by X% from entry

**Trailing Stop:**
• Activation %: Start trailing after position gains X%
• Trail %: Sell if price drops X% from the peak
Example: Activate at +15%, trail by 5% - if price hits +20% then drops to +15%, triggers sell

**Position Sizing:**
• Global: Fixed dollar amount or % of portfolio
• Per-Channel: Override with specific % of portfolio
• Auto-quantity calculation based on signal price

**Slippage Protection:**
• Maximum threshold % to reject trades
• Protects against bad fills when price moves too fast"""
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
        "title": "Discord Self-Bot Setup",
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
• **Discord Self-Bot** - Monitors channels using discord.py-self
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
        "title": "AI-Powered Signal Format Learning",
        "content": """BotifyTrades can learn new signal formats using AI - pay once to teach, use forever!

**How It Works:**
1. You show me an example signal via the chatbot
2. AI analyzes it ONCE to understand the structure
3. I save the pattern for instant future parsing (no more AI costs!)

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
    ("help", "I can help you understand BotifyTrades! Ask me about:\n• Getting started\n• Dashboard\n• Channels & trading\n• Settings & brokers\n• Options trading\n• P&L tracking\n• Risk management\n\nWhat would you like to know?"),
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
    
    greeting_response = check_greeting(query)
    if greeting_response:
        return {
            "success": True,
            "response": greeting_response,
            "topic": "greeting"
        }
    
    # Check for format teaching/management commands
    format_response = handle_format_commands(query)
    if format_response:
        return format_response
    
    topic_id, score = find_best_match(query)
    
    if topic_id and score >= 0.3:
        topic = KNOWLEDGE_BASE[topic_id]
        return {
            "success": True,
            "response": f"**{topic['title']}**\n\n{topic['content']}",
            "topic": topic_id,
            "confidence": round(score, 2)
        }
    
    # Try AI-powered response if available
    ai_response = get_general_ai_response(query)
    if ai_response:
        return {
            "success": True,
            "response": ai_response,
            "topic": None,
            "confidence": 0.7,
            "ai_powered": True
        }
    
    import random
    return {
        "success": True,
        "response": random.choice(FALLBACK_RESPONSES),
        "topic": None,
        "confidence": 0
    }


def handle_format_commands(query: str) -> Optional[Dict]:
    """Handle format teaching and management commands.
    
    Commands:
    - "teach this format: <signal>" - Learn a new signal format
    - "show formats" / "list formats" - Show all learned formats
    - "delete format <name>" - Delete a learned format
    - "enable format <name>" / "disable format <name>" - Toggle format
    - "scan channel <channel_id>" - Scan messages and auto-learn formats
    - "scan channels" - List channels available for scanning
    """
    query_lower = query.lower().strip()
    
    # Scan channel command - auto-discover formats
    if query_lower.startswith('scan channel '):
        channel_id = query[13:].strip()
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


def teach_new_format(signal_example: str) -> Dict:
    """Teach the bot a new signal format using AI."""
    try:
        from .format_trainer import FormatTrainer
        trainer = FormatTrainer()
        
        if not trainer.is_ai_available():
            return {
                "success": True,
                "response": "**AI Not Available**\n\nTo teach new signal formats, I need access to AI. This feature uses Replit AI Integrations (billed to your Replit credits) or you can configure your own OpenAI API key in Settings.\n\nWithout AI, I can still parse signals using built-in patterns.",
                "topic": "format_teaching"
            }
        
        # Learn the format
        result = trainer.learn_format_from_example(signal_example)
        
        if not result.get('success'):
            return {
                "success": True,
                "response": f"**Learning Failed**\n\nI couldn't learn that format: {result.get('error', 'Unknown error')}\n\nPlease try again with a different example.",
                "topic": "format_teaching"
            }
        
        # Save to database
        from . import database as db
        format_id = db.save_signal_format(
            name=result.get('format_name', 'Custom Format'),
            description=result.get('description', ''),
            example_signal=signal_example,
            parsed_fields=result.get('parsed_fields', {}),
            field_mappings=result.get('field_mappings', {}),
            regex_pattern=result.get('suggested_regex')
        )
        
        parsed = result.get('parsed_fields', {})
        action = parsed.get('action', 'Unknown')
        symbol = parsed.get('symbol', 'Unknown')
        
        response_text = f"""**Format Learned Successfully!** 

**Name:** {result.get('format_name', 'Custom Format')}
**Confidence:** {result.get('confidence', 0.8)*100:.0f}%

**Parsed from your example:**
- Action: {action}
- Symbol: {symbol}"""
        
        if parsed.get('entry_price'):
            response_text += f"\n- Entry: ${parsed.get('entry_price')}"
        if parsed.get('is_option'):
            response_text += f"\n- Strike: ${parsed.get('strike')}"
            response_text += f"\n- Type: {'Call' if parsed.get('option_type') == 'C' else 'Put'}"
        
        response_text += "\n\nThis format will now be automatically recognized for future signals!"
        
        return {
            "success": True,
            "response": response_text,
            "topic": "format_teaching",
            "format_id": format_id,
            "ai_powered": True
        }
        
    except Exception as e:
        print(f"[CHAT] Error teaching format: {e}")
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
2. Select **Auto (Replit AI)** or **OpenAI** from the dropdown
3. Click **Save API Keys**

Then try again!"""
            elif provider == 'replit_ai':
                msg = """**Replit AI Not Available**

Replit AI Integration is selected but not available. You can:

1. Go to **Settings** > **AI & Market Data APIs**
2. Select **OpenAI** and enter your API key
3. Click **Save API Keys**

Or wait and try again later."""
            else:
                msg = """**OpenAI API Key Required**

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


def is_trade_query(query: str) -> bool:
    """Check if query is about trades."""
    trade_keywords = ["trade", "position", "order", "buy", "sell", "bto", "stc", 
                      "filled", "executed", "profit", "loss", "p&l", "pnl"]
    return any(kw in query for kw in trade_keywords)


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
    """Analyze trades and provide AI-powered insights."""
    try:
        from . import database as db
        
        recent_trades = []
        try:
            recent_trades = db.get_recent_filled_orders(limit=20) or []
        except:
            pass
        
        open_positions = []
        try:
            open_positions = db.get_open_positions() or []
        except:
            pass
        
        log_context = _get_log_context()
        
        context = f"""Recent Trades (last 20):
{_format_trades(recent_trades)}

Open Positions:
{_format_positions(open_positions)}

Recent Console Activity:
{log_context}
"""
        
        ai_response = _call_openai(query, context, "trade_analysis")
        
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
    for t in trades[:10]:
        symbol = t.get('symbol', 'Unknown')
        action = t.get('action', t.get('side', 'Unknown'))
        qty = t.get('quantity', t.get('qty', 0))
        price = t.get('price', t.get('fill_price', 0))
        time = t.get('filled_at', t.get('created_at', ''))[:19] if t.get('filled_at') or t.get('created_at') else ''
        lines.append(f"  {time} | {action} {qty} {symbol} @ ${price}")
    
    return "\n".join(lines) if lines else "No trades to display."


def _format_positions(positions: List[Dict]) -> str:
    """Format positions for display."""
    if not positions:
        return "No open positions."
    
    lines = []
    for p in positions:
        symbol = p.get('symbol', 'Unknown')
        qty = p.get('quantity', p.get('qty', 0))
        pnl = p.get('unrealized_pnl', p.get('pnl', 0))
        lines.append(f"  {symbol}: {qty} shares (P&L: ${pnl:.2f})")
    
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


def _get_openai_client():
    """Get OpenAI client based on user's provider preference from GUI.
    
    Provider options (set in Settings > AI & Market Data APIs):
    - 'replit_ai': Use Replit AI Integrations (billed to Replit credits)
    - 'openai': Use user's own OpenAI API key
    - 'disabled': No AI features
    """
    import os
    
    try:
        from .config_service import get_ai_provider, load_config
        from openai import OpenAI
        
        provider = get_ai_provider()
        
        # Check if AI is disabled
        if provider == 'disabled':
            print("[CHAT] AI is disabled in settings")
            return None
        
        # Use Replit AI Integrations
        if provider == 'replit_ai':
            ai_integrations_key = os.environ.get('AI_INTEGRATIONS_OPENAI_API_KEY')
            ai_integrations_base = os.environ.get('AI_INTEGRATIONS_OPENAI_BASE_URL')
            
            if ai_integrations_key and ai_integrations_base:
                print("[CHAT] Using Replit AI Integrations")
                return OpenAI(api_key=ai_integrations_key, base_url=ai_integrations_base)
            else:
                print("[CHAT] Replit AI Integrations not available")
                return None
        
        # Use user's OpenAI API key
        if provider == 'openai':
            user_api_key = os.environ.get('OPENAI_API_KEY')
            
            if not user_api_key:
                api_keys = load_config('api_keys')
                if api_keys and api_keys.get('openai'):
                    user_api_key = api_keys['openai']
            
            if user_api_key:
                print("[CHAT] Using user's OpenAI API key")
                return OpenAI(api_key=user_api_key)
            else:
                print("[CHAT] OpenAI API key not configured")
                return None
        
        return None
    except Exception as e:
        print(f"[CHAT] OpenAI client initialization failed: {e}")
        return None


def is_ai_available() -> bool:
    """Check if OpenAI is available (via AI Integrations or user API key)."""
    return _get_openai_client() is not None


def _call_openai(query: str, context: str, analysis_type: str) -> Optional[str]:
    """Call OpenAI to analyze context and answer query."""
    try:
        client = _get_openai_client()
        if not client:
            return None
        
        system_prompts = {
            "trade_analysis": """You are a trading assistant for BotifyTrades, a Discord trading bot.
Analyze the provided trade data and console logs to answer the user's question.
Be concise but helpful. If you see errors, explain what they mean.
Format your response with markdown for readability.""",
            
            "log_analysis": """You are a technical assistant for BotifyTrades, a Discord trading bot.
Analyze the console logs and activity to answer the user's question.
Identify any issues, patterns, or important events.
Be concise and highlight the most relevant information.""",
            
            "error_analysis": """You are a troubleshooting assistant for BotifyTrades, a Discord trading bot.
Analyze the errors and issues to help the user understand what went wrong.
Provide clear explanations and suggest solutions when possible.
Be empathetic - users are often frustrated when things don't work.""",
            
            "general": """You are a helpful assistant for BotifyTrades, a Discord trading bot that automates stock and options trading.
Answer the user's question helpfully. Be concise but informative.
If asked about features, explain what BotifyTrades can do.
Format your response with markdown for readability."""
        }
        
        system_prompt = system_prompts.get(analysis_type, system_prompts["general"])
        
        # the newest OpenAI model is "gpt-5" which was released August 7, 2025.
        # do not change this unless explicitly requested by the user
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{context}\n\nUser Question: {query}"}
            ],
            max_completion_tokens=500
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"[CHAT] OpenAI call failed: {e}")
        return None


def get_general_ai_response(query: str) -> Optional[str]:
    """Get a general AI response for questions not in knowledge base."""
    try:
        client = _get_openai_client()
        if not client:
            return None
        
        system_prompt = """You are a helpful assistant for BotifyTrades, a Discord trading bot.
BotifyTrades monitors Discord channels for trading signals and automatically executes trades on brokers like Webull, Alpaca, Interactive Brokers, and Tastytrade.

Key features:
- Automated trade execution from Discord signals
- Risk management with profit targets and stop losses
- Paper and live trading modes
- Per-channel configuration
- Web-based control panel

Answer the user's question helpfully and concisely. Use markdown formatting.
If you don't know something specific about BotifyTrades, suggest they check the Settings or Channels page in the GUI."""
        
        # the newest OpenAI model is "gpt-5" which was released August 7, 2025.
        # do not change this unless explicitly requested by the user
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            max_completion_tokens=500
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"[CHAT] AI response failed: {e}")
        return None
