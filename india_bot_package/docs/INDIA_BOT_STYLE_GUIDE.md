# BotifyTrades India Market Bot - Complete Style & Architecture Guide

## Overview
This package contains everything needed to match the BotifyTrades UI/UX design system for the India Market trading bot.

---

## PART 1: UI/UX DESIGN SYSTEM

### Fonts (Add to HTML `<head>`)
```html
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
```

### CSS Variables (Core Theme)
```css
:root {
    /* Dark Theme Backgrounds */
    --bg-primary: #0E1117;
    --bg-secondary: #161B22;
    --bg-card: #1C2128;
    --bg-card-hover: #262C36;
    
    /* Premium Gradient Accents */
    --accent-mint: #0FF0B3;
    --accent-violet: #7C3AED;
    --accent-blue: #3B82F6;
    --accent-gradient: linear-gradient(135deg, #0FF0B3 0%, #7C3AED 50%, #3B82F6 100%);
    --accent-gradient-subtle: linear-gradient(135deg, rgba(15, 240, 179, 0.15) 0%, rgba(124, 58, 237, 0.15) 100%);
    
    /* Status Colors */
    --success: #10B981;
    --warning: #F59E0B;
    --error: #EF4444;
    --info: #0FF0B3;
    
    /* Text Colors */
    --text-primary: #F0F6FC;
    --text-secondary: #8B949E;
    --text-muted: #6E7681;
    
    /* Borders */
    --border-color: rgba(255, 255, 255, 0.08);
    --border-accent: rgba(15, 240, 179, 0.3);
    
    /* Shadows */
    --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.4);
    --shadow-md: 0 4px 20px rgba(0, 0, 0, 0.5);
    --shadow-lg: 0 8px 40px rgba(0, 0, 0, 0.6);
    --shadow-glow: 0 0 30px rgba(15, 240, 179, 0.25);
    --shadow-glow-violet: 0 0 30px rgba(124, 58, 237, 0.25);
    
    /* Typography */
    --font-primary: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --font-brand: 'Space Grotesk', sans-serif;
    --font-mono: 'JetBrains Mono', 'Consolas', 'Monaco', monospace;
    
    /* Border Radius */
    --radius-sm: 8px;
    --radius-md: 12px;
    --radius-lg: 16px;
    --radius-xl: 24px;
}
```

### Body Styling
```css
body {
    font-family: var(--font-primary);
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
    font-size: 14px;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}
```

### Brand Logo Block (Animated Gradient)
```css
.botify-logo-mark {
    position: relative;
    width: 46px;
    height: 46px;
    background: linear-gradient(135deg, #00F5FF 0%, #8B5CF6 100%);
    border-radius: 14px;
    box-shadow: 0 0 40px rgba(0, 245, 255, 0.3), inset 0 1px 1px rgba(255,255,255,0.3);
}

.logo-symbol {
    font-family: var(--font-brand);
    font-size: 18px;
    font-weight: 700;
    background: linear-gradient(135deg, #00F5FF 0%, #0FF0B3 25%, #8B5CF6 50%, #EC4899 75%, #F43F5E 100%);
    background-size: 200% 200%;
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: textGradient 4s ease infinite;
}

.botify-brand-name {
    font-family: var(--font-brand);
    font-size: 20px;
    font-weight: 700;
    background: linear-gradient(135deg, #fff 0%, rgba(255,255,255,0.8) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
```

### Key Color Palette
| Purpose | Color | Hex |
|---------|-------|-----|
| Mint Accent | Cyan-green glow | `#0FF0B3` |
| Violet Accent | Purple highlight | `#7C3AED` |
| Blue Accent | Primary blue | `#3B82F6` |
| Success | Green | `#10B981` |
| Warning | Yellow/Orange | `#F59E0B` |
| Error | Red | `#EF4444` |
| Background Primary | Dark navy | `#0E1117` |
| Background Card | Dark gray | `#1C2128` |
| Text Primary | Off-white | `#F0F6FC` |
| Text Secondary | Gray | `#8B949E` |

---

## PART 2: DATABASE SCHEMA - CHANNELS TABLE

### Complete Channels Schema (Per-Channel Risk Management)
```sql
CREATE TABLE channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_channel_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('EXECUTE', 'TRACK')),
    execute_enabled INTEGER DEFAULT 0,
    track_enabled INTEGER DEFAULT 0,
    broker_override TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Paper Trading
    paper_trade_enabled INTEGER DEFAULT 0,
    
    -- Risk Management Settings (Per-Channel)
    risk_management_enabled INTEGER DEFAULT 0,
    stop_loss_pct REAL DEFAULT NULL,
    trailing_stop_pct REAL DEFAULT NULL,
    trailing_activation_pct REAL DEFAULT NULL,
    
    -- 4-Tier Profit Targets
    profit_target_pct REAL DEFAULT NULL,
    profit_target_1_pct REAL DEFAULT NULL,  -- First target (e.g., 15%)
    profit_target_2_pct REAL DEFAULT NULL,  -- Second target (e.g., 25%)
    profit_target_3_pct REAL DEFAULT NULL,  -- Third target (e.g., 35%)
    profit_target_4_pct REAL DEFAULT NULL,  -- Fourth target (e.g., 50%)
    
    -- Profit Target Quantities (contracts to sell at each level)
    profit_target_qty_1 INTEGER DEFAULT NULL,
    profit_target_qty_2 INTEGER DEFAULT NULL,
    profit_target_qty_3 INTEGER DEFAULT NULL,
    profit_target_qty_4 INTEGER DEFAULT NULL,
    
    -- Broker Assignment (Multi-Broker)
    enabled_brokers TEXT DEFAULT NULL,  -- JSON array: ["UPSTOX", "ZERODHA"]
    
    -- Position Sizing
    position_size_pct REAL DEFAULT NULL,
    tracking_position_size_pct REAL DEFAULT NULL,
    default_quantity INTEGER DEFAULT NULL,
    channel_max_position_size REAL DEFAULT NULL,
    tracking_default_quantity INTEGER DEFAULT NULL,
    
    -- Conditional Orders
    conditional_order_enabled INTEGER DEFAULT 1,
    trigger_offset_percent REAL DEFAULT 0.0,
    conditional_order_expiry TEXT DEFAULT 'end_of_day',
    conditional_auto_execute INTEGER DEFAULT 1,
    conditional_order_timeout_minutes INTEGER DEFAULT NULL,
    order_timeout_minutes INTEGER DEFAULT NULL,
    
    -- Exit Strategy
    exit_strategy_mode TEXT DEFAULT 'signal',  -- 'signal', 'risk', 'hybrid'
    exit_strategy_mode_override TEXT DEFAULT NULL,
    leave_runner_enabled INTEGER DEFAULT 0,
    leave_runner_pct REAL DEFAULT 25.0,
    
    -- Trim Orders
    trim_order_mode TEXT DEFAULT 'market',
    trim_limit_offset REAL DEFAULT 0.01,
    
    -- Slippage Protection
    slippage_protection_enabled INTEGER DEFAULT 0,
    slippage_max_pct REAL DEFAULT NULL,
    
    -- Signal Update Automation
    signal_update_automation INTEGER DEFAULT 0,
    signal_update_automation_override TEXT DEFAULT NULL,
    
    -- Global Risk Override
    use_global_risk_settings INTEGER DEFAULT 1,
    
    -- Circuit Breaker
    channel_daily_loss_limit REAL DEFAULT 0,
    channel_max_positions INTEGER DEFAULT 0,
    circuit_breaker_enabled INTEGER DEFAULT 1,
    
    -- Enhanced Risk Management v2.0
    enable_dynamic_sl INTEGER DEFAULT 0,
    enable_giveback_guard INTEGER DEFAULT 0,
    giveback_allowed_pct REAL DEFAULT 30.0,
    dynamic_sl_profile TEXT DEFAULT 'standard',  -- 'conservative', 'standard', 'aggressive'
    
    -- Platform (Discord/Telegram)
    platform TEXT DEFAULT 'discord',
    telegram_chat_id TEXT DEFAULT NULL,
    telegram_chat_type TEXT DEFAULT NULL,
    telegram_username TEXT DEFAULT NULL,
    
    -- Market
    market TEXT DEFAULT 'US',  -- 'US', 'INDIA', 'CANADA'
    
    -- Trade Summary
    trade_summary_enabled INTEGER DEFAULT 1
);
```

### Risk Management Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `risk_management_enabled` | INT | 0=disabled, 1=enabled per channel |
| `stop_loss_pct` | REAL | Stop loss percentage (e.g., 30.0 = 30%) |
| `trailing_stop_pct` | REAL | Trailing stop percentage after activation |
| `trailing_activation_pct` | REAL | Profit % needed to activate trailing stop |
| `profit_target_1_pct` | REAL | First profit target (e.g., 15%) |
| `profit_target_2_pct` | REAL | Second profit target (e.g., 25%) |
| `profit_target_3_pct` | REAL | Third profit target (e.g., 35%) |
| `profit_target_4_pct` | REAL | Fourth profit target (e.g., 50%) |
| `exit_strategy_mode` | TEXT | 'signal' (follow trader), 'risk' (auto), 'hybrid' (both) |
| `enable_dynamic_sl` | INT | Dynamic SL escalation after profit targets |
| `dynamic_sl_profile` | TEXT | 'conservative', 'standard', 'aggressive' |
| `enable_giveback_guard` | INT | Max profit giveback protection |
| `giveback_allowed_pct` | REAL | Max % drop from peak before exit (e.g., 30%) |

### Dynamic SL Escalation Profiles

| Profile | PT1 Hit | PT2 Hit | PT3 Hit | PT4 Hit |
|---------|---------|---------|---------|---------|
| Conservative | SL → Breakeven | SL → +3% | SL → +10% | SL → +20% |
| Standard | SL → Breakeven | SL → +5% | SL → +15% | SL → +25% |
| Aggressive | SL → -2% | SL → Breakeven | SL → +10% | SL → +20% |

---

## PART 3: PNL TRACKING SCHEMA

### Signal Lots Table (FIFO P&L Tracking)
```sql
CREATE TABLE signal_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    signal_id INTEGER,
    trade_id INTEGER,
    asset_type TEXT NOT NULL CHECK(asset_type IN ('stock', 'option')),
    symbol TEXT NOT NULL,
    strike REAL,
    expiry TEXT,
    call_put TEXT,
    original_qty INTEGER NOT NULL,
    remaining_qty INTEGER NOT NULL,
    open_price REAL NOT NULL,
    opened_at TIMESTAMP NOT NULL,
    status TEXT DEFAULT 'OPEN' CHECK(status IN ('OPEN', 'CLOSED', 'PARTIAL')),
    source TEXT NOT NULL CHECK(source IN ('SIGNAL', 'TRADE')),
    author_name TEXT,
    user_id INTEGER,
    FOREIGN KEY (channel_id) REFERENCES channels(id),
    FOREIGN KEY (signal_id) REFERENCES signals(id),
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

CREATE INDEX idx_signal_lots_channel_symbol ON signal_lots(channel_id, asset_type, symbol, status);
CREATE INDEX idx_signal_lots_opened_at ON signal_lots(opened_at);
```

### Trades Table with P&L Fields
```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT,
    channel_name TEXT,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,  -- BTO, STC, BUY, SELL
    asset_type TEXT,  -- 'stock' or 'option'
    strike REAL,
    expiry TEXT,
    call_put TEXT,  -- 'C' or 'P'
    quantity INTEGER,
    price REAL,
    broker TEXT,
    order_id TEXT,
    status TEXT DEFAULT 'pending',
    fill_price REAL,
    fill_quantity INTEGER,
    pnl REAL,
    pnl_percent REAL,
    stop_loss_price REAL,
    profit_target_price REAL,
    signal_id INTEGER,
    signal_qty INTEGER,  -- Trader's original quantity
    remaining_qty INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    executed_at TIMESTAMP,
    message_id TEXT,
    author_name TEXT
);
```

### P&L Calculation Flow
1. **BTO Signal** → Creates `signal_lot` with `original_qty`, `remaining_qty`, `open_price`
2. **STC Signal** → Matches to oldest open lot (FIFO), calculates P&L:
   - `pnl = (exit_price - entry_price) * qty * multiplier`
   - For options: `multiplier = 100`
3. **Proportional Exit** → If trader exits 50%, bot exits 50% of its position

### Channel-PNL Alignment
- Each `signal_lot` has `channel_id` linking to the channel configuration
- P&L aggregation queries group by `channel_id` for per-channel performance
- Risk settings from `channels` table apply to position monitoring

---

## PART 4: INDIA MARKET BROKERS

### Supported India Brokers
| Broker | API Support | AMO | Paper Mode |
|--------|-------------|-----|------------|
| Upstox | Full REST API | Yes | No |
| Zerodha (Kite) | Full REST API | Yes | No |
| DhanQ | Full REST API | Yes | No |

### Broker Settings Schema
```sql
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    encrypted INTEGER DEFAULT 0
);

-- India Broker Keys:
-- upstox_api_key, upstox_api_secret, upstox_access_token, upstox_redirect_uri
-- zerodha_api_key, zerodha_api_secret, zerodha_access_token, zerodha_request_token
-- dhanq_client_id, dhanq_access_token
```

### Conditional Order Flow for India F&O
```
Signal: "BUY NIFTY 26500 PE ABOVE ₹100 SL ₹90 TGT ₹150"
     ↓
1. Parse signal → Extract: symbol=NIFTY, strike=26500, type=PE, trigger=100
     ↓
2. Create conditional order → Monitor NIFTY 26500 PE price
     ↓
3. When price > ₹100 → Execute BTO via Upstox/Zerodha/DhanQ
     ↓
4. Store in signal_lots → Track P&L per channel
     ↓
5. Apply channel risk settings → SL at ₹90, targets at ₹150
```

---

## PART 5: FILES INCLUDED

### Static Assets
- `/static/css/quantum-theme.css` - Main theme with all CSS variables
- `/static/css/style.css` - Additional styling and components
- `/static/images/logo.png` - Full BotifyTrades logo
- `/static/images/logo-icon.png` - Icon version
- `/static/images/favicon.svg` - Favicon

### Usage
1. Copy `/static/` folder to your Flask app
2. Link CSS in your base template:
```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/quantum-theme.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
```
3. Use logo:
```html
<img src="{{ url_for('static', filename='images/logo.png') }}" alt="BotifyTrades">
```

---

## PART 6: REPLIT PROMPT FOR INDIA BOT

Copy this prompt to your India Market Bot Replit project:

```
Build an India Market Trading Bot with the following specifications:

## UI REQUIREMENTS
- Match the BotifyTrades design system exactly (see /docs/INDIA_BOT_STYLE_GUIDE.md)
- Dark theme with #0E1117 background
- Accent colors: Mint #0FF0B3, Violet #7C3AED, Blue #3B82F6
- Fonts: Plus Jakarta Sans (primary), Space Grotesk (brand)
- Use the provided quantum-theme.css and style.css

## DATABASE SCHEMA
- Implement the channels table with per-channel risk management settings
- Include 4-tier profit targets, trailing stops, dynamic SL escalation
- Support FIFO P&L tracking via signal_lots table
- Each channel links to specific brokers (Upstox, Zerodha, DhanQ)

## RISK MANAGEMENT (Per Channel)
- Stop loss percentage
- 4-tier profit targets with qty allocation
- Trailing stop with activation threshold
- Exit strategy modes: signal, risk, hybrid
- Dynamic SL escalation profiles: conservative, standard, aggressive
- Max profit giveback guard

## BROKER INTEGRATION
- Upstox: OAuth2 authentication, REST API for orders
- Zerodha Kite: API key + access token flow
- DhanQ: Client ID + access token
- Support AMO (After Market Orders) for all brokers

## TELEGRAM INTEGRATION
- Read signals from configured Telegram channels/groups
- Parse India F&O signals: NIFTY, BANKNIFTY, stocks
- Support conditional orders: "BUY ABOVE", "SELL BELOW"
- Auto-resolve expiry using Expiry Resolver service

## KEY FEATURES
- Per-channel broker assignment
- Conditional order monitoring with price triggers
- Signal-to-execution tracking with audit trail
- Real-time position monitoring
- Channel-level P&L aggregation
```

---

## Quick Reference

### Essential CSS Classes
| Class | Purpose |
|-------|---------|
| `.bg-primary` | Main dark background |
| `.bg-card` | Card/panel background |
| `.text-primary` | Primary text color |
| `.text-secondary` | Secondary/muted text |
| `.accent-mint` | Cyan-green accent |
| `.btn-primary` | Primary action button |
| `.badge.success` | Green status badge |
| `.badge.error` | Red status badge |
| `.stat-card` | Statistics card component |
| `.data-table` | Data table styling |

### Common Patterns
```css
/* Card with hover effect */
.card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--radius-lg);
    transition: all 0.3s ease;
}
.card:hover {
    background: var(--bg-card-hover);
    border-color: var(--border-accent);
    box-shadow: var(--shadow-md);
}

/* Gradient button */
.btn-gradient {
    background: var(--accent-gradient);
    color: #000;
    font-weight: 600;
    border: none;
    border-radius: var(--radius-md);
}
```
