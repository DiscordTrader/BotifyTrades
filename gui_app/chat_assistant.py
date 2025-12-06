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
    """Get AI assistant response for a query"""
    if not query or not query.strip():
        return {
            "success": True,
            "response": "Hi! I'm your BotifyTrades assistant. Ask me anything about the app - channels, brokers, trading, settings, and more!",
            "topic": None
        }
    
    greeting_response = check_greeting(query)
    if greeting_response:
        return {
            "success": True,
            "response": greeting_response,
            "topic": "greeting"
        }
    
    topic_id, score = find_best_match(query)
    
    if topic_id and score >= 0.3:
        topic = KNOWLEDGE_BASE[topic_id]
        return {
            "success": True,
            "response": f"**{topic['title']}**\n\n{topic['content']}",
            "topic": topic_id,
            "confidence": round(score, 2)
        }
    
    import random
    return {
        "success": True,
        "response": random.choice(FALLBACK_RESPONSES),
        "topic": None,
        "confidence": 0
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
